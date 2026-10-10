"""
AstrBot 系统指令权限控制插件 v2.0.1

功能:
- 拦截非管理员使用特定系统命令
- 支持 blocklist/allowlist 两种策略模式
- 支持分群策略、用户白名单
- 支持运行时管理命令
- 审计日志和统计报表
- Unicode 规范化防绕过
"""
import time
from typing import Optional, Dict, Any, List, Set

from astrbot.api.star import Context, Star
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api import logger

from .models.types import (
    GlobalPolicy, FeedbackConfig, AuditConfig, AuditRecord,
    PolicyMode, FeedbackMode
)
from .core.command_normalizer import CommandNormalizer
from .core.policy_resolver import PolicyResolver
from .core.acl_engine import ACLEngine
from .core.rate_limiter import RateLimiter
from .storage.audit_logger import AuditLogger
from .storage.stats_collector import StatsCollector


class RestrictSysCmd(Star):
    """系统指令权限控制插件"""
    
    def __init__(self, context: Context, config: Optional[Dict[str, Any]] = None):
        super().__init__(context)
        self.config = config or {}
        
        # 标记是否已加载KV数据
        self._kv_loaded = False
        
        # 初始化组件
        self._init_components()
        
        logger.info(
            f"[RSC] 插件已加载 | 模式: {self.resolver.global_policy.mode.value} | "
            f"命令数: {len(self.resolver.global_policy.commands)} | "
            f"前缀: {self.resolver.global_policy.command_prefixes}"
        )
    
    async def _ensure_kv_loaded(self):
        """确保 KV 数据已加载（懒加载）"""
        if self._kv_loaded:
            return
        
        try:
            # 加载策略覆盖
            policy_override = await self.get_kv_data("policy_override", None)
            if policy_override and isinstance(policy_override, dict):
                # 合并到当前配置
                for key, value in policy_override.items():
                    if key not in self.config:  # 优先使用 WebUI 配置
                        self.config[key] = value
                # 重新初始化组件以应用覆盖
                self._init_components()
                logger.info("[RSC] 已加载持久化策略覆盖")
        except Exception as e:
            logger.warning(f"[RSC] 加载 KV 数据失败: {e}")
        
        self._kv_loaded = True
    
    def _init_components(self):
        """初始化所有组件"""
        # 解析配置
        global_policy = self._parse_global_policy()
        feedback_config = self._parse_feedback_config()
        audit_config = self._parse_audit_config()
        
        # 策略解析器 (先创建并更新配置)
        self.resolver = PolicyResolver(global_policy)
        self.resolver.update_from_config(self.config)
        
        # 命令规范化器 (使用最终生效的策略配置)
        final_policy = self.resolver.global_policy
        self.normalizer = CommandNormalizer(
            prefixes=final_policy.command_prefixes,
            allow_bare_command=final_policy.allow_bare_command,
            case_sensitive=final_policy.case_sensitive
        )
        
        # ACL 引擎
        self.acl_engine = ACLEngine(self.normalizer, self.resolver)
        
        # 冷却限制器
        self.rate_limiter = RateLimiter(feedback_config.cooldown_seconds)
        
        # 反馈配置
        self.feedback_config = feedback_config
        
        # 审计日志 (不在初始化时加载，首次访问时懒加载)
        self.audit_logger = AuditLogger(
            max_records=audit_config.max_records,
            persist_fn=None,  # 异步持久化在别处处理
            load_fn=None
        ) if audit_config.enabled else None
        
        # 统计收集器 (同上)
        self.stats_collector = StatsCollector(
            persist_fn=None,
            load_fn=None
        )
        
        # 标记是否已加载KV数据
        self._kv_loaded = False
    
    def _parse_config_set(self, value, default: Optional[Set[str]] = None) -> Set[str]:
        """解析配置值为集合（支持列表或逗号分隔字符串）"""
        if default is None:
            default = set()
        if not value:
            return default
        if isinstance(value, (list, set)):
            return set(str(v) for v in value if v)
        if isinstance(value, str):
            return set(v.strip() for v in value.split(",") if v.strip())
        return default
    
    def _parse_config_list(self, value, default: Optional[List[str]] = None) -> List[str]:
        """解析配置值为列表（支持列表或逗号分隔字符串）"""
        if default is None:
            default = []
        if not value:
            return default
        if isinstance(value, list):
            return [str(v) for v in value if v]
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        return default
    
    def _parse_global_policy(self) -> GlobalPolicy:
        """从配置解析全局策略"""
        mode_str = self.config.get("mode", "blocklist")
        try:
            mode = PolicyMode(mode_str)
        except ValueError:
            mode = PolicyMode.BLOCKLIST
        
        case_sensitive = self.config.get("case_sensitive", False)
        
        # 解析命令列表（支持逗号分隔字符串或列表）
        default_commands = {"new", "reset", "help", "start", "stop",
                           "about", "status", "config", "settings", "plugin", "plugins_ls"}
        raw_commands = self._parse_config_set(
            self.config.get("blocked_commands"),
            default_commands
        )
        
        # 解析前缀列表
        default_prefixes = ["/", ":", "!", "#"]
        command_prefixes = self._parse_config_list(
            self.config.get("command_prefixes"),
            default_prefixes
        )
        
        return GlobalPolicy(
            enabled=self.config.get("enabled", True),
            mode=mode,
            commands=CommandNormalizer.normalize_command_set(raw_commands, case_sensitive),
            command_prefixes=command_prefixes,
            allow_bare_command=self.config.get("allow_bare_command", False),
            case_sensitive=case_sensitive,
            user_whitelist=self._parse_config_set(self.config.get("user_whitelist")),
            enabled_platforms=self._parse_config_set(self.config.get("enabled_platforms")),
            disabled_platforms=self._parse_config_set(self.config.get("disabled_platforms")),
            disabled_groups=self._parse_config_set(self.config.get("disabled_groups"))
        )
    
    def _parse_feedback_config(self) -> FeedbackConfig:
        """从配置解析反馈配置"""
        mode_str = self.config.get("feedback_mode", "brief")
        try:
            mode = FeedbackMode(mode_str)
        except ValueError:
            mode = FeedbackMode.BRIEF
        
        return FeedbackConfig(
            mode=mode,
            message_brief=self.config.get("feedback_message_brief", "⚠️ 该命令仅管理员可用"),
            message_detail=self.config.get(
                "feedback_message_detail",
                "⚠️ 命令 [{command}] 被拦截\n原因: {reason}\n如需使用，请联系管理员"
            ),
            cooldown_seconds=self.config.get("cooldown_seconds", 30)
        )
    
    def _parse_audit_config(self) -> AuditConfig:
        """从配置解析审计配置"""
        return AuditConfig(
            enabled=self.config.get("audit_enabled", True),
            max_records=self.config.get("audit_max_records", 1000)
        )
    
    def _get_group_id(self, event: AstrMessageEvent) -> Optional[str]:
        """获取群组ID"""
        try:
            msg_obj = event.message_obj
            if hasattr(msg_obj, "group_id"):
                return str(msg_obj.group_id) if msg_obj.group_id else None
        except Exception as e:
            logger.debug(f"[RSC] 获取群组ID失败: {e}")
        return None
    
    def _get_platform(self, event: AstrMessageEvent) -> str:
        """获取平台名称"""
        try:
            if hasattr(event, "platform") and event.platform:
                if hasattr(event.platform, "name"):
                    return str(event.platform.name)
        except Exception as e:
            logger.debug(f"[RSC] 获取平台名称失败: {e}")
        return "unknown"
    
    async def _send_feedback(
        self,
        event: AstrMessageEvent,
        command: str,
        reason: str,
        group_id: Optional[str]
    ):
        """发送拦截反馈"""
        if self.feedback_config.mode == FeedbackMode.NONE:
            return
        
        user_id = event.get_sender_id()
        
        # 检查冷却
        if not self.rate_limiter.should_notify(group_id or "", user_id):
            return
        
        # 生成消息
        if self.feedback_config.mode == FeedbackMode.BRIEF:
            msg = self.feedback_config.message_brief
        else:
            msg = self.feedback_config.message_detail.format(
                command=command,
                reason=reason
            )
        
        # 发送
        try:
            yield event.plain_result(msg)
        except Exception as e:
            logger.warning(f"[RSC] 发送反馈失败: {e}")
    
    def _record_audit(
        self,
        event: AstrMessageEvent,
        command: str,
        action: str,
        reason: str,
        policy_source: str,
        group_id: Optional[str],
        platform: str
    ):
        """记录审计日志"""
        if not self.audit_logger:
            return
        
        record = AuditRecord(
            timestamp=time.time(),
            user_id=event.get_sender_id(),
            user_name=event.get_sender_name(),
            group_id=group_id,
            platform=platform,
            command=command,
            original_message=event.get_message_str()[:200],
            action=action,
            reason=reason,
            policy_source=policy_source
        )
        self.audit_logger.log(record)
    
    # ==================== 核心拦截处理器 ====================
    
    @filter.event_message_type(filter.EventMessageType.ALL, priority=1000)
    async def restrict_syscmd_handler(self, event: AstrMessageEvent):
        """核心拦截处理器 - 高优先级确保最先执行"""
        # 确保 KV 数据已加载
        await self._ensure_kv_loaded()
        
        raw_msg = getattr(getattr(event, "message_obj", None), "message_str", None)
        processed_msg = event.get_message_str()
        msg = raw_msg if isinstance(raw_msg, str) and raw_msg else processed_msg
        user_id = event.get_sender_id()
        group_id = self._get_group_id(event)
        platform = self._get_platform(event)
        is_admin = event.is_admin()
        
        # ACL 检查
        result = self.acl_engine.check(
            message=msg,
            user_id=user_id,
            group_id=group_id,
            platform=platform,
            is_admin=is_admin
        )

        # 已激活的命令按唤醒后的文本检查；原名和别名使用同一策略。
        if getattr(event, "is_at_or_wake_command", False):
            handlers = event.get_extra("activated_handlers") or ()
            command_filters = [
                event_filter
                for handler in handlers
                for event_filter in getattr(handler, "event_filters", ())
                if callable(getattr(event_filter, "get_complete_command_names", None))
            ]
            command_text = " ".join(processed_msg.split())
            for command_filter in command_filters:
                names = command_filter.get_complete_command_names()
                variants = tuple(
                    name + command_text[len(matched):]
                    for matched in names
                    if command_text == matched or command_text.startswith(matched + " ")
                    for name in names
                )
                result = self.acl_engine.check(
                    message=processed_msg,
                    user_id=user_id,
                    group_id=group_id,
                    platform=platform,
                    is_admin=is_admin,
                    allow_bare_override=True,
                    command_variants=variants
                )
                if not result.allowed:
                    break
        
        # 无命令或允许通过
        if result.allowed or not result.command:
            if result.command:
                # 记录放行（仅统计）
                self.stats_collector.record_allowed(result.command, user_id, group_id)
            return
        
        # 拦截
        user_info = f"{event.get_sender_name()}({user_id})"
        logger.info(f"[RSC] 拦截: {user_info} | 群: {group_id} | 命令: {result.command} | 原因: {result.reason}")
        
        # 记录统计
        self.stats_collector.record_blocked(result.command, user_id, group_id)
        
        # 记录审计
        self._record_audit(
            event=event,
            command=result.command,
            action="blocked",
            reason=result.reason,
            policy_source=result.policy_source or "unknown",
            group_id=group_id,
            platform=platform
        )
        
        # 发送反馈
        async for resp in self._send_feedback(event, result.command, result.reason, group_id):
            yield resp
        
        # 停止事件传播
        event.stop_event()
    
    # ==================== 管理命令 ====================
    
    @filter.command("rsc")
    async def rsc_help(self, event: AstrMessageEvent):
        """显示帮助"""
        help_text = """📋 RSC 命令帮助
/rsc list - 查看当前规则
/rsc block add <cmd> - 添加拦截命令
/rsc block del <cmd> - 移除拦截命令
/rsc allow add <user_id> - 添加用户白名单
/rsc allow del <user_id> - 移除用户白名单
/rsc test <cmd> - 测试命令是否会被拦截
/rsc stats - 查看统计
/rsc recent [n] - 查看最近拦截记录
/rsc reload - 重载配置"""
        yield event.plain_result(help_text)
    
    @filter.command("rsc list")
    async def rsc_list(self, event: AstrMessageEvent):
        """查看当前规则"""
        if not event.is_admin():
            yield event.plain_result("⚠️ 仅管理员可用")
            return
        
        p = self.resolver.global_policy
        mode_text = "黑名单模式（拦截列表中的命令）" if p.mode == PolicyMode.BLOCKLIST else "白名单模式（只允许列表中的命令）"
        
        lines = [
            f"📋 RSC 当前规则",
            f"├ 状态: {'启用' if p.enabled else '禁用'}",
            f"├ 模式: {mode_text}",
            f"├ 命令列表 ({len(p.commands)}): {', '.join(sorted(p.commands)[:20])}{'...' if len(p.commands) > 20 else ''}",
            f"├ 前缀: {p.command_prefixes}",
            f"├ 区分大小写: {'是' if p.case_sensitive else '否'}",
            f"├ 允许裸命令: {'是' if p.allow_bare_command else '否'}",
            f"├ 用户白名单 ({len(p.user_whitelist)}): {', '.join(list(p.user_whitelist)[:10])}{'...' if len(p.user_whitelist) > 10 else ''}",
            f"└ 禁用群组 ({len(p.disabled_groups)}): {', '.join(list(p.disabled_groups)[:5])}{'...' if len(p.disabled_groups) > 5 else ''}"
        ]
        yield event.plain_result("\n".join(lines))
    
    @filter.command("rsc block add")
    async def rsc_block_add(self, event: AstrMessageEvent, cmd: str = ""):
        """添加拦截命令"""
        if not event.is_admin():
            yield event.plain_result("⚠️ 仅管理员可用")
            return
        
        if not cmd:
            yield event.plain_result("用法: /rsc block add <命令>")
            return
        
        # 规范化命令（尊重 case_sensitive 设置）
        cmd = self.normalizer.normalize_text(cmd)
        if not self.resolver.global_policy.case_sensitive:
            cmd = cmd.lower()
        
        self.resolver.global_policy.commands.add(cmd)
        await self._persist_policy()
        
        yield event.plain_result(f"✅ 已添加拦截命令: {cmd}")
    
    @filter.command("rsc block del")
    async def rsc_block_del(self, event: AstrMessageEvent, cmd: str = ""):
        """移除拦截命令"""
        if not event.is_admin():
            yield event.plain_result("⚠️ 仅管理员可用")
            return
        
        if not cmd:
            yield event.plain_result("用法: /rsc block del <命令>")
            return
        
        # 规范化命令（尊重 case_sensitive 设置）
        cmd = self.normalizer.normalize_text(cmd)
        if not self.resolver.global_policy.case_sensitive:
            cmd = cmd.lower()
        
        if cmd in self.resolver.global_policy.commands:
            self.resolver.global_policy.commands.remove(cmd)
            await self._persist_policy()
            yield event.plain_result(f"✅ 已移除拦截命令: {cmd}")
        else:
            yield event.plain_result(f"⚠️ 命令不在列表中: {cmd}")
    
    @filter.command("rsc allow add")
    async def rsc_allow_add(self, event: AstrMessageEvent, user_id: str = ""):
        """添加用户白名单"""
        if not event.is_admin():
            yield event.plain_result("⚠️ 仅管理员可用")
            return
        
        if not user_id:
            yield event.plain_result("用法: /rsc allow add <用户ID>")
            return
        
        user_id = user_id.strip()
        self.resolver.global_policy.user_whitelist.add(user_id)
        await self._persist_policy()
        
        yield event.plain_result(f"✅ 已添加白名单用户: {user_id}")
    
    @filter.command("rsc allow del")
    async def rsc_allow_del(self, event: AstrMessageEvent, user_id: str = ""):
        """移除用户白名单"""
        if not event.is_admin():
            yield event.plain_result("⚠️ 仅管理员可用")
            return
        
        if not user_id:
            yield event.plain_result("用法: /rsc allow del <用户ID>")
            return
        
        user_id = user_id.strip()
        if user_id in self.resolver.global_policy.user_whitelist:
            self.resolver.global_policy.user_whitelist.remove(user_id)
            await self._persist_policy()
            yield event.plain_result(f"✅ 已移除白名单用户: {user_id}")
        else:
            yield event.plain_result(f"⚠️ 用户不在白名单中: {user_id}")
    
    @filter.command("rsc test")
    async def rsc_test(self, event: AstrMessageEvent, cmd: str = ""):
        """测试命令是否会被拦截"""
        if not event.is_admin():
            yield event.plain_result("⚠️ 仅管理员可用")
            return
        
        if not cmd:
            yield event.plain_result("用法: /rsc test <命令>")
            return
        
        group_id = self._get_group_id(event)
        result = self.acl_engine.test_command(
            command=cmd.strip(),
            user_id="test_user",
            group_id=group_id,
            is_admin=False
        )
        
        status = "✅ 允许" if result.allowed else "🚫 拦截"
        yield event.plain_result(
            f"测试命令: {cmd}\n"
            f"结果: {status}\n"
            f"原因: {result.reason}\n"
            f"策略来源: {result.policy_source}"
        )
    
    @filter.command("rsc stats")
    async def rsc_stats(self, event: AstrMessageEvent):
        """查看统计"""
        if not event.is_admin():
            yield event.plain_result("⚠️ 仅管理员可用")
            return
        
        yield event.plain_result(self.stats_collector.get_summary())
    
    @filter.command("rsc recent")
    async def rsc_recent(self, event: AstrMessageEvent, n: str = "10"):
        """查看最近拦截记录"""
        if not event.is_admin():
            yield event.plain_result("⚠️ 仅管理员可用")
            return
        
        if not self.audit_logger:
            yield event.plain_result("⚠️ 审计日志未启用")
            return
        
        try:
            limit = min(int(n), 50)
        except ValueError:
            limit = 10
        
        records = self.audit_logger.get_recent(limit)
        
        if not records:
            yield event.plain_result("📋 暂无拦截记录")
            return
        
        lines = [f"📋 最近 {len(records)} 条拦截记录:"]
        for r in records:
            ts = time.strftime("%m-%d %H:%M", time.localtime(r.timestamp))
            lines.append(f"[{ts}] {r.user_name}({r.user_id}) | {r.command} | {r.action}")
        
        yield event.plain_result("\n".join(lines))
    
    @filter.command("rsc reload")
    async def rsc_reload(self, event: AstrMessageEvent):
        """重载配置"""
        if not event.is_admin():
            yield event.plain_result("⚠️ 仅管理员可用")
            return
        
        try:
            self._init_components()
            yield event.plain_result("✅ 配置已重载")
        except Exception as e:
            yield event.plain_result(f"❌ 重载失败: {e}")
    
    async def _persist_policy(self):
        """持久化策略变更"""
        config_data = self.resolver.to_config()
        for key, value in config_data.items():
            self.config[key] = value
        # 通过 KV 存储持久化
        try:
            await self.put_kv_data("policy_override", config_data)
        except Exception as e:
            logger.warning(f"[RSC] 持久化策略失败: {e}")
    
    # ==================== 生命周期 ====================
    
    async def terminate(self):
        """插件卸载"""
        # 持久化数据
        if self.audit_logger:
            self.audit_logger.flush()
        self.stats_collector.flush()
        
        logger.info("[RSC] 插件已卸载")
