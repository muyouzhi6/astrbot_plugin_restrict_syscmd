"""Regression tests for commands after AstrBot removes the wake prefix."""

import ast
import inspect
import logging
import os
from pathlib import Path
import re
import sys
import types
import unittest


def _install_astrbot_stubs():
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    star = types.ModuleType("astrbot.api.star")
    event = types.ModuleType("astrbot.api.event")
    filters = types.ModuleType("astrbot.api.event.filter")

    class Star:
        def __init__(self, context):
            self.context = context

        async def get_kv_data(self, key, default=None):
            return default

    star.Context = type("Context", (), {})
    star.Star = Star
    filters.EventMessageType = types.SimpleNamespace(ALL="all")
    filters.event_message_type = lambda *args, **kwargs: lambda method: method
    filters.command = lambda *args, **kwargs: lambda method: method
    event.filter = filters
    event.AstrMessageEvent = type("AstrMessageEvent", (), {})
    api.logger = logging.getLogger("restrict-syscmd-test")
    sys.modules.update({
        "astrbot": astrbot,
        "astrbot.api": api,
        "astrbot.api.star": star,
        "astrbot.api.event": event,
        "astrbot.api.event.filter": filters,
    })


_install_astrbot_stubs()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from astrbot_plugin_restrict_syscmd.main import RestrictSysCmd


MISSING = object()


class FakeEvent:
    def __init__(self, raw, processed=None, *, admin=False, platform="aiocqhttp", group=None):
        self.message_str = raw if processed is None else processed
        self.message_obj = types.SimpleNamespace(group_id=group, type="friend")
        if raw is not MISSING:
            self.message_obj.message_str = raw
        self.platform = types.SimpleNamespace(name=platform)
        self.role = "admin" if admin else "member"
        self.is_at_or_wake_command = False
        self.is_wake = False
        self.plugins_name = None
        self._extras = {}
        self.stopped = False

    def get_message_str(self):
        return self.message_str

    def get_sender_id(self):
        return "ordinary-user"

    def get_sender_name(self):
        return "ordinary-user"

    def get_messages(self):
        return [object()]

    def is_private_chat(self):
        return True

    def get_platform_name(self):
        return self.platform.name

    def get_extra(self, key=None, default=None):
        return self._extras.get(key, default) if key is not None else self._extras

    def set_extra(self, key, value):
        self._extras[key] = value

    def is_admin(self):
        return self.role == "admin"

    def stop_event(self):
        self.stopped = True

    def is_stopped(self):
        return self.stopped

    def clear_result(self):
        pass

    def plain_result(self, text):
        return text


def _load_method(path, class_name, method_name, namespace):
    tree = ast.parse(path.read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    method = next(node for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name)
    module = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        method,
    ], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(path), "exec"), namespace)
    return namespace[method_name]


def _load_process(path, class_name, namespace):
    return _load_method(path, class_name, "process", namespace)


def _upstream_waking(root, handlers):
    class Registry:
        def get_handlers_by_event_type(self, event_type, plugins_name=None):
            return handlers

    class SessionPluginManager:
        @staticmethod
        async def filter_handlers_by_session(event, selected):
            return selected

    namespace = {
        "At": type("At", (), {}),
        "AtAll": type("AtAll", (), {}),
        "Reply": type("Reply", (), {}),
        "MessageType": types.SimpleNamespace(GROUP_MESSAGE="group"),
        "EventType": types.SimpleNamespace(AdapterMessageEvent="adapter"),
        "CommandGroupFilter": type("CommandGroupFilter", (), {}),
        "PermissionTypeFilter": type("PermissionTypeFilter", (), {}),
        "SessionPluginManager": SessionPluginManager,
        "star_handlers_registry": Registry(),
        "logger": logging.getLogger("upstream-waking"),
    }
    return _load_process(root / "astrbot/core/pipeline/waking_check/stage.py", "WakingCheckStage", namespace)


def _upstream_dispatch(root):
    async def call_handler(event, handler, **params):
        result = handler(event, **params)
        if inspect.isasyncgen(result):
            yielded = False
            async for item in result:
                yielded = True
                yield item
            if not yielded:
                yield None
        else:
            yield await result

    async def fail_on_plugin_error(*args):
        raise AssertionError("Upstream handler raised an exception")

    namespace = {
        "star_map": {
            "astrbot_plugin_restrict_syscmd.main": types.SimpleNamespace(name="plugin"),
            "astrbot.builtin_stars.builtin_commands.main": types.SimpleNamespace(name="builtin"),
        },
        "logger": logging.getLogger("upstream-dispatch"),
        "call_handler": call_handler,
        "call_event_hook": fail_on_plugin_error,
    }
    return _load_process(root / "astrbot/core/pipeline/process_stage/method/star_request.py", "StarRequestSubStage", namespace)


class AlwaysFilter:
    def filter(self, event, config):
        return True


def _upstream_reset_filter(root):
    path = root / "astrbot/core/star/filter/command.py"
    filter_method = _load_method(path, "CommandFilter", "filter", {"re": re})

    class ResetFilter:
        filter = filter_method
        handler_params = {}

        def custom_filter_ok(self, event, config):
            return True

        def get_complete_command_names(self):
            return ["reset"]

        def validate_and_convert_params(self, params, param_types):
            return {}

    return ResetFilter()


class RestrictSysCmdTests(unittest.IsolatedAsyncioTestCase):
    async def _check(self, raw, processed=None, config=None, **event_kwargs):
        settings = {"enabled_platforms": ["aiocqhttp"], "feedback_mode": "none"}
        settings.update(config or {})
        plugin = RestrictSysCmd(None, settings)
        event = FakeEvent(raw, processed, **event_kwargs)
        async for _ in plugin.restrict_syscmd_handler(event):
            pass
        return event, plugin.stats_collector.get_stats()

    async def test_user_entry_and_policy_edges(self):
        cases = [
            ("stripped wake prefix", "/reset", "reset", None, {}, True),
            ("another configured prefix", ":reset", "reset", None, {}, True),
            ("unicode command", "/ｒｅｓｅｔ", "ｒｅｓｅｔ", None, {}, True),
            ("default blocked help", "/help", "help", None, {}, True),
            ("plain prefixed command", "/reset", "/reset", None, {}, True),
            ("unrelated sentence", "please reset", "please reset", None, {}, False),
            ("embedded prefix", "say /reset", "say /reset", None, {}, False),
            ("bare command disabled", "reset", "reset", None, {}, False),
            ("bare command enabled", "reset", "reset", {"allow_bare_command": True}, {}, True),
            ("admin exemption", "/reset", "reset", None, {"admin": True}, False),
            ("user whitelist", "/reset", "reset", {"user_whitelist": ["ordinary-user"]}, {}, False),
            ("disabled group", "/reset", "reset", {"disabled_groups": ["g-disabled"]}, {"group": "g-disabled"}, False),
            ("disabled plugin", "/reset", "reset", {"enabled": False}, {}, False),
            ("disabled platform", "/reset", "reset", None, {"platform": "telegram"}, False),
            ("default feedback", "/reset", "reset", {"feedback_mode": "brief"}, {}, True),
            ("old event fallback", MISSING, "/reset", None, {}, True),
            ("empty original fallback", "", "/reset", None, {}, True),
            ("allowlist rejects reset", "/reset", "reset", {"mode": "allowlist", "blocked_commands": ["help"]}, {}, True),
            ("allowlist accepts help", "/help", "help", {"mode": "allowlist", "blocked_commands": ["help"]}, {}, False),
        ]
        for label, raw, processed, config, event_kwargs, blocked in cases:
            with self.subTest(label=label):
                event, stats = await self._check(raw, processed, config, **event_kwargs)
                self.assertEqual(event.stopped, blocked)
                self.assertEqual(stats.total_blocked, int(blocked))

    async def test_real_astrbot_waking_and_dispatch(self):
        sources = os.environ.get("ASTRBOT_TEST_SOURCES")
        if not sources:
            self.skipTest("Set ASTRBOT_TEST_SOURCES to extracted AstrBot wheels")

        for version in ("4.26.8", "4.27.3", "4.28.2"):
            with self.subTest(version=version):
                root = Path(sources) / f"astrbot-{version}"
                self.assertTrue(root.is_dir(), root)
                plugin = RestrictSysCmd(None, {"enabled_platforms": ["aiocqhttp"], "feedback_mode": "none"})
                executed = []

                async def reset_command(event):
                    executed.append(event.get_message_str())

                handlers = [
                    types.SimpleNamespace(
                        event_filters=[AlwaysFilter()],
                        handler_module_path="astrbot_plugin_restrict_syscmd.main",
                        handler_full_name="plugin.restrict_syscmd_handler",
                        handler_name="restrict_syscmd_handler",
                        handler=plugin.restrict_syscmd_handler,
                    ),
                    types.SimpleNamespace(
                        event_filters=[_upstream_reset_filter(root)],
                        handler_module_path="astrbot.builtin_stars.builtin_commands.main",
                        handler_full_name="builtin.reset",
                        handler_name="reset",
                        handler=reset_command,
                    ),
                ]
                event = FakeEvent("/reset")
                stage = types.SimpleNamespace(
                    unique_session=False,
                    ignore_bot_self_message=False,
                    ctx=types.SimpleNamespace(astrbot_config={"admins_id": [], "wake_prefix": ["/"], "plugin_set": ["*"]}),
                    friend_message_needs_wake_prefix=False,
                    ignore_at_all=False,
                    disable_builtin_commands=False,
                    _umo_auto_name_recorder=types.SimpleNamespace(schedule=lambda event: None),
                )
                await _upstream_waking(root, handlers)(stage, event)
                self.assertEqual(event.get_message_str(), "reset")
                self.assertEqual(event.message_obj.message_str, "/reset")
                self.assertEqual(event.get_extra("activated_handlers"), handlers)
                async for _ in _upstream_dispatch(root)(None, event):
                    pass
                self.assertTrue(event.stopped)
                self.assertEqual(executed, [])
                self.assertEqual(plugin.stats_collector.get_stats().total_blocked, 1)
                print(f"AstrBot {version}: /reset blocked before builtin handler")


if __name__ == "__main__":
    unittest.main()
