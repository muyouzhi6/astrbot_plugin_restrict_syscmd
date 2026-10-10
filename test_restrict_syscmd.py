"""Regression tests for commands after AstrBot removes the wake prefix."""

import ast
import inspect
import logging
import os
import re
import sys
import types
import typing
import unittest
from pathlib import Path


def _install_astrbot_stubs():
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    star = types.ModuleType("astrbot.api.star")
    event = types.ModuleType("astrbot.api.event")
    filters = types.ModuleType("astrbot.api.event.filter")
    commands = types.ModuleType("astrbot.core.star.filter.command")
    commands.GreedyStr = type("GreedyStr", (str,), {})

    class Star:
        def __init__(self, context):
            self.context = context

        async def get_kv_data(self, key, default=None):
            return default

        async def put_kv_data(self, key, value):
            self.saved_data = (key, value)

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
        "astrbot.core.star.filter.command": commands,
    })


_install_astrbot_stubs()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from astrbot_plugin_restrict_syscmd.main import RestrictSysCmd  # noqa: E402, I001 - Import after installing API stubs.


MISSING = object()


class At:
    def __init__(self, qq):
        self.qq = qq


class FakeEvent:
    def __init__(self, raw, processed=None, *, admin=False, platform="aiocqhttp", group=None,
                 private=True, messages=None):
        self.message_str = raw if processed is None else processed
        self.message_obj = types.SimpleNamespace(group_id=group, type="friend" if private else "group")
        if raw is not MISSING:
            self.message_obj.message_str = raw
        self.platform = types.SimpleNamespace(name=platform)
        self.private = private
        self.messages = [object()] if messages is None else messages
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
        return self.messages

    def is_private_chat(self):
        return self.private

    def get_self_id(self):
        return "bot-id"

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
    exec(compile(module, str(path), "exec"), namespace)  # noqa: S102 - Load local upstream pipeline methods.
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
        "At": At,
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


def _upstream_command_filter(root, command="reset", aliases=(), parents=None):
    path = root / "astrbot/core/star/filter/command.py"
    tree = ast.parse(path.read_text())
    tree.body = [
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        *[node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef))],
    ]
    ast.fix_missing_locations(tree)
    namespace = {"HandlerFilter": object, "inspect": inspect, "re": re,
                 "types": types, "typing": typing}
    exec(compile(tree, str(path), "exec"), namespace)  # noqa: S102 - Load the local upstream class for compatibility tests.
    # The plugin and filter must share the same GreedyStr marker, as in AstrBot.
    namespace["GreedyStr"] = sys.modules["astrbot.core.star.filter.command"].GreedyStr
    command_filter = namespace["CommandFilter"](
        command, alias=set(aliases), parent_command_names=parents
    )
    command_filter.handler_params = {}
    return command_filter


class RestrictSysCmdTests(unittest.IsolatedAsyncioTestCase):
    async def _check(self, raw, processed=None, config=None, *, upstream_command=False,
                     woken=False, **event_kwargs):
        settings = {"enabled_platforms": ["aiocqhttp"]}
        settings.update(config or {})
        plugin = RestrictSysCmd(None, settings)
        event = FakeEvent(raw, processed, **event_kwargs)
        event.is_at_or_wake_command = woken or upstream_command
        if upstream_command:
            command_filter = types.SimpleNamespace(get_complete_command_names=lambda: ["reset"])
            event.set_extra("activated_handlers", [types.SimpleNamespace(event_filters=[command_filter])])
        elif woken:
            event.set_extra("activated_handlers", [types.SimpleNamespace(event_filters=[AlwaysFilter()])])
        feedback = [item async for item in plugin.restrict_syscmd_handler(event)]
        return event, plugin.stats_collector.get_stats(), feedback

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
            ("default feedback", "/reset", "reset", None, {}, True),
            ("old event fallback", MISSING, "/reset", None, {}, True),
            ("empty original fallback", "", "/reset", None, {}, True),
            ("allowlist rejects reset", "/reset", "reset", {"mode": "allowlist", "blocked_commands": ["help"]}, {}, True),
            ("allowlist accepts help", "/help", "help", {"mode": "allowlist", "blocked_commands": ["help"]}, {}, False),
        ]
        for label, raw, processed, config, event_kwargs, blocked in cases:
            with self.subTest(label=label):
                event, stats, feedback = await self._check(raw, processed, config, **event_kwargs)
                self.assertEqual(event.stopped, blocked)
                self.assertEqual(stats.total_blocked, int(blocked))
                if label == "default feedback":
                    self.assertEqual(feedback, ["⚠️ 该命令仅管理员可用"])

    async def test_upstream_command_entry_regressions(self):
        for label, raw, processed in (
            ("bare private reset", "reset", "reset"),
            ("custom wake prefix", "$reset", "reset"),
            ("overlapping wake prefix", "//reset", "reset"),
            ("missing original after wake", MISSING, "reset"),
            ("empty original after wake", "", "reset"),
        ):
            with self.subTest(label=label):
                event, stats, _ = await self._check(raw, processed, upstream_command=True)
                self.assertTrue(event.stopped)
                self.assertEqual(stats.total_blocked, 1)

    async def test_private_noncommand_in_allowlist(self):
        event, stats, feedback = await self._check(
            "hello", config={"mode": "allowlist", "blocked_commands": ["help"]}, woken=True
        )
        self.assertFalse(event.stopped)
        self.assertEqual(stats.total_blocked, 0)
        self.assertEqual(feedback, [])

    def _source_roots(self):
        sources = os.environ.get("ASTRBOT_TEST_SOURCES")
        if not sources:
            self.skipTest("Set ASTRBOT_TEST_SOURCES to extracted AstrBot wheels")
        for version in ("4.26.8", "4.27.3", "4.28.2"):
            root = Path(sources) / f"astrbot-{version}"
            self.assertTrue(root.is_dir(), root)
            yield version, root

    async def _dispatch_case(self, root, raw, *, processed=None, command="reset",
                             aliases=(), parents=None, wake_prefix=None, private=True,
                             messages=None, config=None, admin=False, active=True,
                             blocked=True, expected_command=None, other_commands=()):
        settings = {"enabled_platforms": ["aiocqhttp"], "feedback_mode": "none"}
        settings.update(config or {})
        plugin = RestrictSysCmd(None, settings)
        executed = []

        async def command_handler(event):
            executed.append(event.get_message_str())

        handlers = [types.SimpleNamespace(
            event_filters=[AlwaysFilter()],
            handler_module_path="astrbot_plugin_restrict_syscmd.main",
            handler_full_name="plugin.restrict_syscmd_handler",
            handler_name="restrict_syscmd_handler",
            handler=plugin.restrict_syscmd_handler,
        )]
        for index, command_filter in enumerate([
            _upstream_command_filter(root, command, aliases, parents),
            *[_upstream_command_filter(root, name, alias) for name, alias in other_commands],
        ]):
            handlers.append(types.SimpleNamespace(
                event_filters=[command_filter],
                handler_module_path="astrbot.builtin_stars.builtin_commands.main",
                handler_full_name=f"builtin.command{index}",
                handler_name=f"command{index}",
                handler=command_handler,
            ))
        event = FakeEvent(raw, processed, private=private, messages=messages,
                          group=None if private else "group-1", admin=admin)
        stage = types.SimpleNamespace(
            unique_session=False,
            ignore_bot_self_message=False,
            ctx=types.SimpleNamespace(astrbot_config={
                "admins_id": [], "wake_prefix": wake_prefix or ["/"], "plugin_set": ["*"]
            }),
            friend_message_needs_wake_prefix=False,
            ignore_at_all=False,
            disable_builtin_commands=False,
            _umo_auto_name_recorder=types.SimpleNamespace(schedule=lambda event: None),
        )
        await _upstream_waking(root, handlers)(stage, event)
        if raw is MISSING:
            self.assertFalse(hasattr(event.message_obj, "message_str"))
        else:
            self.assertEqual(event.message_obj.message_str, raw)
        activated = event.get_extra("activated_handlers")
        self.assertEqual(handlers[1] in activated, active)
        async for _ in _upstream_dispatch(root)(None, event):
            pass
        # Check actual downstream execution first, so a regression records the bypass.
        self.assertEqual(executed, [] if blocked else [
            event.get_message_str() for handler in handlers[1:] if handler in activated
        ])
        self.assertEqual(event.stopped, blocked)
        stats = plugin.stats_collector.get_stats()
        self.assertEqual(stats.total_blocked, int(blocked))
        if expected_command:
            self.assertEqual(stats.by_command, {expected_command: 1})

    async def _run_dispatch_cases(self, cases):
        for version, root in self._source_roots():
            for label, kwargs in cases:
                with self.subTest(version=version, entry=label):
                    await self._dispatch_case(root, **kwargs)
                    print(f"AstrBot {version}: {label}: passed")

    async def test_real_astrbot_waking_and_dispatch(self):
        await self._run_dispatch_cases([
            ("prefixed private", {"raw": "/reset", "expected_command": "reset"}),
            ("bare private reset", {"raw": "reset", "expected_command": "reset"}),
            ("bare group mention help", {
                "raw": "help", "command": "help", "private": False,
                "messages": [At("bot-id")], "expected_command": "help",
            }),
            ("custom wake prefix", {
                "raw": "$reset", "wake_prefix": ["$"],
                "config": {"command_prefixes": ["!"]}, "expected_command": "reset",
            }),
            ("overlapping wake prefix", {
                "raw": "//reset", "wake_prefix": ["//"],
                "config": {"command_prefixes": ["!"]}, "expected_command": "reset",
            }),
            ("missing original after wake", {
                "raw": MISSING, "processed": "/reset", "expected_command": "reset",
            }),
            ("empty original after wake", {
                "raw": "", "processed": "/reset", "expected_command": "reset",
            }),
            ("bare group without mention", {
                "raw": "reset", "private": False, "messages": [],
                "active": False, "blocked": False,
            }),
            ("ordinary private text in allowlist", {
                "raw": "please reset", "active": False, "blocked": False,
                "config": {"mode": "allowlist", "blocked_commands": ["help"]},
            }),
        ])

    async def test_real_astrbot_aliases(self):
        await self._run_dispatch_cases([
            ("blocked canonical via alias", {"raw": "/wipe", "aliases": ["wipe"],
                                             "expected_command": "reset"}),
            ("bare alias", {"raw": "wipe", "aliases": ["wipe"],
                            "expected_command": "reset"}),
            ("alias after custom wake", {"raw": "$wipe", "aliases": ["wipe"],
                                         "wake_prefix": ["$"], "expected_command": "reset"}),
            ("alias with missing raw", {"raw": MISSING, "processed": "/wipe",
                                        "aliases": ["wipe"], "expected_command": "reset"}),
            ("blocked alias via canonical", {"raw": "/reset", "aliases": ["wipe"],
                                             "config": {"blocked_commands": ["wipe"]}}),
            ("allowed canonical via alias", {"raw": "/wipe", "aliases": ["wipe"],
                                             "blocked": False, "config": {
                                                 "mode": "allowlist", "blocked_commands": ["reset"]}}),
            ("allowed alias via canonical", {"raw": "/reset", "aliases": ["wipe"],
                                             "blocked": False, "config": {
                                                 "mode": "allowlist", "blocked_commands": ["wipe"]}}),
            ("unrelated inactive alias", {"raw": "/ping", "command": "ping",
                                          "blocked": False, "other_commands": [("reset", ["wipe"])]}),
            ("colliding active alias", {"raw": "/ping", "command": "ping",
                                        "other_commands": [("reset", ["ping"])]}),
        ])

    async def test_real_astrbot_multisegment_commands(self):
        await self._run_dispatch_cases([
            ("three segment command", {"raw": "/foo bar baz", "command": "foo bar baz",
                                        "config": {"blocked_commands": ["foo bar baz"]},
                                        "expected_command": "foo bar baz"}),
            ("four segment with arguments", {"raw": "/foo bar baz qux value",
                                             "command": "foo bar baz qux",
                                             "config": {"blocked_commands": ["foo bar baz qux"]}}),
            ("three segment allowlist", {"raw": "/foo bar baz", "command": "foo bar baz",
                                         "blocked": False, "config": {
                                             "mode": "allowlist", "blocked_commands": ["foo bar baz"]}}),
            ("three segment parent policy", {"raw": "/foo bar baz", "command": "foo bar baz",
                                             "config": {"blocked_commands": ["foo bar"]}}),
            ("multiword command token match", {"raw": "/foo bar bazooka", "command": "foo bar bazooka",
                                               "blocked": False,
                                               "config": {"blocked_commands": ["foo bar baz"]}}),
            ("alias retains trailing words", {"raw": "/wipe bar baz", "aliases": ["wipe"],
                                              "config": {"blocked_commands": ["reset bar baz"]}}),
            ("nested command alias", {"raw": "/foo bar wipe", "command": "baz",
                                      "parents": ["foo bar"], "aliases": ["wipe"],
                                      "config": {"blocked_commands": ["foo bar baz"]}}),
            ("parent group alias", {"raw": "/f b baz", "command": "baz",
                                    "parents": ["foo bar", "foo b", "f bar", "f b"],
                                    "config": {"blocked_commands": ["foo bar baz"]}}),
        ])

    async def test_alias_policy_exemptions_and_legacy_config(self):
        cases = [
            ("admin", {"admin": True}),
            ("global whitelist", {"config": {"user_whitelist": ["ordinary-user"]}}),
            ("group whitelist", {"private": False, "config": {
                "group_user_whitelist": {"group-1": ["ordinary-user"]}}}),
            ("disabled group", {"private": False, "config": {"disabled_groups": ["group-1"]}}),
            ("disabled plugin", {"config": {"enabled": False}}),
            ("disabled platform", {"config": {"disabled_platforms": ["aiocqhttp"]}}),
        ]
        await self._run_dispatch_cases([
            (label, {"raw": "/wipe", "aliases": ["wipe"], "blocked": False, **kwargs})
            for label, kwargs in cases
        ] + [("legacy CSV config", {"raw": "/wipe", "aliases": ["wipe"], "config": {
            "blocked_commands": "help,reset", "command_prefixes": "/,!,#",
            "enabled_platforms": "aiocqhttp", "allow_bare_command": False}})])

    async def test_multisegment_without_upstream_metadata(self):
        for mode, blocked in (("blocklist", True), ("allowlist", False)):
            with self.subTest(mode=mode):
                event, _, _ = await self._check(
                    "/foo bar baz argument", config={"mode": mode, "blocked_commands": ["foo bar baz"]}
                )
                self.assertEqual(event.stopped, blocked)

    async def test_symbol_alias_regressions(self):
        await self._run_dispatch_cases([
            ("symbol alias blocks canonical", {
                "raw": "/!", "aliases": ["!"], "expected_command": "reset",
            }),
            ("symbol alias with arguments", {
                "raw": "/! value", "aliases": ["!"], "expected_command": "reset",
            }),
            ("symbol alias missing raw", {
                "raw": MISSING, "processed": "/!", "aliases": ["!"],
                "expected_command": "reset",
            }),
            ("symbol alias excluded from allowlist", {
                "raw": "/!", "aliases": ["!"],
                "config": {"mode": "allowlist", "blocked_commands": ["help"]},
            }),
            ("symbol alias allowed by canonical", {
                "raw": "/!", "aliases": ["!"], "blocked": False,
                "config": {"mode": "allowlist", "blocked_commands": ["reset"]},
            }),
            ("prefix in alias must not match another rule", {
                "raw": "/!help", "aliases": ["!help"], "blocked": False,
                "config": {"blocked_commands": ["help"]},
            }),
            ("prefix in alias must not grant allowlist access", {
                "raw": "/!help", "aliases": ["!help"],
                "config": {"mode": "allowlist", "blocked_commands": ["help"]},
            }),
        ])

    async def test_management_full_command_arguments(self):
        for version, root in self._source_roots():
            for command, method_name in (
                ("rsc block add", "rsc_block_add"),
                ("rsc block del", "rsc_block_del"),
                ("rsc test", "rsc_test"),
            ):
                for argument in ("foo", "foo bar baz", "foo bar baz argument", ""):
                    with self.subTest(version=version, command=command, argument=argument):
                        plugin = RestrictSysCmd(None, {"blocked_commands": [argument or "help"]})
                        if method_name == "rsc_block_add":
                            plugin.resolver.global_policy.commands.clear()
                        command_filter = _upstream_command_filter(root, command)
                        command_filter.init_handler_md(types.SimpleNamespace(
                            handler=getattr(RestrictSysCmd, method_name)
                        ))
                        event = FakeEvent(f"{command} {argument}", admin=True)
                        event.is_at_or_wake_command = True
                        self.assertTrue(command_filter.filter(event, {}))
                        params = event.get_extra("parsed_params")
                        replies = [item async for item in getattr(plugin, method_name)(event, **params)]
                        if not argument:
                            self.assertIn("用法:", replies[0])
                        elif method_name == "rsc_block_add":
                            self.assertEqual(plugin.resolver.global_policy.commands, {argument})
                            self.assertEqual(plugin.saved_data[1]["blocked_commands"], [argument])
                        elif method_name == "rsc_block_del":
                            self.assertEqual(plugin.resolver.global_policy.commands, set())
                            self.assertEqual(plugin.saved_data[1]["blocked_commands"], [])
                        else:
                            self.assertIn(f"测试命令: {argument}\n", replies[0])
                            self.assertIn("结果: 🚫 拦截", replies[0])
                        self.assertEqual(params, {"cmd": argument})

    def test_diagnostic_multisegment_parity(self):
        for mode in ("blocklist", "allowlist"):
            for command, matches in (
                ("foo bar baz", True),
                ("foo bar baz argument", True),
                ("foo bar baz qux argument", True),
                ("ＦＯＯ\u200b  bar\tbaz argument", True),
                ("foo bar bazooka", False),
            ):
                with self.subTest(mode=mode, command=command):
                    plugin = RestrictSysCmd(None, {
                        "mode": mode, "blocked_commands": ["foo bar baz", "foo bar baz qux"],
                    })
                    runtime = plugin.acl_engine.check(
                        "/" + command, "ordinary-user", None, "aiocqhttp", False
                    )
                    diagnostic = plugin.acl_engine.test_command(command, "ordinary-user", None, False)
                    self.assertEqual(runtime.allowed, matches if mode == "allowlist" else not matches)
                    self.assertEqual(diagnostic.allowed, runtime.allowed)
                    if matches:
                        self.assertEqual(diagnostic.command, runtime.command)


if __name__ == "__main__":
    unittest.main()
