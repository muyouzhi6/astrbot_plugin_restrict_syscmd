"""
数据模型和类型定义
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Set, Dict, Any
import time


class PolicyMode(Enum):
    """策略模式"""
    BLOCKLIST = "blocklist"  # 拦截列表中的命令
    ALLOWLIST = "allowlist"  # 只允许列表中的命令


class FeedbackMode(Enum):
    """反馈模式"""
    NONE = "none"      # 不提示
    BRIEF = "brief"    # 简短提示
    DETAIL = "detail"  # 详细提示


@dataclass
class GlobalPolicy:
    """全局策略配置"""
    enabled: bool = True
    mode: PolicyMode = PolicyMode.BLOCKLIST
    commands: Set[str] = field(default_factory=lambda: {
        "new", "reset", "help", "start", "stop", 
        "about", "status", "config", "settings", "plugin", "plugins_ls"
    })
    command_prefixes: list[str] = field(default_factory=lambda: ["/", ":", "!", "#"])
    allow_bare_command: bool = False
    case_sensitive: bool = False
    user_whitelist: Set[str] = field(default_factory=set)
    enabled_platforms: Set[str] = field(default_factory=set)  # 空=全部
    disabled_platforms: Set[str] = field(default_factory=set)
    disabled_groups: Set[str] = field(default_factory=set)


@dataclass
class GroupPolicy:
    """群组策略 - 简单开关模式"""
    group_id: str
    enabled: bool = True  # True=继承全局策略, False=完全禁用拦截
    user_whitelist: Set[str] = field(default_factory=set)  # 群级白名单


@dataclass
class EffectivePolicy:
    """生效的策略（解析后）"""
    mode: PolicyMode
    commands: Set[str]
    user_whitelist: Set[str]
    source: str  # 策略来源描述


@dataclass
class FeedbackConfig:
    """反馈配置"""
    mode: FeedbackMode = FeedbackMode.BRIEF
    message_brief: str = "⚠️ 该命令仅管理员可用"
    message_detail: str = "⚠️ 命令 [{command}] 被拦截\n原因: {reason}\n如需使用，请联系管理员"
    cooldown_seconds: int = 30


@dataclass
class AuditConfig:
    """审计配置"""
    enabled: bool = True
    max_records: int = 1000


@dataclass
class CommandParseResult:
    """命令解析结果"""
    success: bool
    command: Optional[str] = None
    command_2seg: Optional[str] = None  # 两段命令 (如 "rsc block")
    prefix: Optional[str] = None
    original: Optional[str] = None
    normalized: Optional[str] = None


@dataclass
class ACLCheckResult:
    """ACL检查结果"""
    allowed: bool
    reason: str
    command: Optional[str] = None
    policy_source: Optional[str] = None
    is_admin: bool = False
    is_whitelisted: bool = False


@dataclass
class AuditRecord:
    """审计记录"""
    timestamp: float = field(default_factory=time.time)
    user_id: str = ""
    user_name: str = ""
    group_id: Optional[str] = None
    platform: str = ""
    command: str = ""
    original_message: str = ""
    action: str = ""  # blocked / allowed
    reason: str = ""
    policy_source: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "ts": self.timestamp,
            "uid": self.user_id,
            "uname": self.user_name,
            "gid": self.group_id,
            "platform": self.platform,
            "cmd": self.command,
            "msg": self.original_message[:100],  # 截断
            "action": self.action,
            "reason": self.reason,
            "source": self.policy_source,
        }
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AuditRecord":
        return cls(
            timestamp=d.get("ts", 0),
            user_id=d.get("uid", ""),
            user_name=d.get("uname", ""),
            group_id=d.get("gid"),
            platform=d.get("platform", ""),
            command=d.get("cmd", ""),
            original_message=d.get("msg", ""),
            action=d.get("action", ""),
            reason=d.get("reason", ""),
            policy_source=d.get("source", ""),
        )


@dataclass
class StatsData:
    """统计数据"""
    total_blocked: int = 0
    total_allowed: int = 0
    by_command: Dict[str, int] = field(default_factory=dict)
    by_user: Dict[str, int] = field(default_factory=dict)
    by_group: Dict[str, int] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_blocked": self.total_blocked,
            "total_allowed": self.total_allowed,
            "by_command": self.by_command,
            "by_user": self.by_user,
            "by_group": self.by_group,
        }
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "StatsData":
        return cls(
            total_blocked=d.get("total_blocked", 0),
            total_allowed=d.get("total_allowed", 0),
            by_command=d.get("by_command", {}),
            by_user=d.get("by_user", {}),
            by_group=d.get("by_group", {}),
        )
