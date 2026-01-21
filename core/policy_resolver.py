"""
策略解析器 - 解析并合并全局/群组策略
"""
from typing import Optional, Dict, Any, Set, List
from astrbot.api import logger
from ..models.types import (
    GlobalPolicy, GroupPolicy, EffectivePolicy, PolicyMode
)
from .command_normalizer import CommandNormalizer


class PolicyResolver:
    """策略解析器"""
    
    def __init__(self, global_policy: GlobalPolicy):
        self.global_policy = global_policy
        self.group_policies: Dict[str, GroupPolicy] = {}
    
    def set_global_policy(self, policy: GlobalPolicy):
        """设置全局策略"""
        self.global_policy = policy
    
    def set_group_policy(self, group_id: str, policy: GroupPolicy):
        """设置群组策略"""
        self.group_policies[group_id] = policy
    
    def remove_group_policy(self, group_id: str) -> bool:
        """移除群组策略"""
        if group_id in self.group_policies:
            del self.group_policies[group_id]
            return True
        return False
    
    def get_group_policy(self, group_id: str) -> Optional[GroupPolicy]:
        """获取群组策略"""
        return self.group_policies.get(group_id)
    
    def resolve(self, group_id: Optional[str] = None) -> EffectivePolicy:
        """
        解析生效的策略
        
        Args:
            group_id: 群组ID，None表示私聊
            
        Returns:
            EffectivePolicy: 生效的策略
        """
        base = self.global_policy
        
        # 检查是否在禁用群组列表
        if group_id and group_id in base.disabled_groups:
            return EffectivePolicy(
                mode=PolicyMode.BLOCKLIST,
                commands=set(),  # 空集合 = 不拦截任何命令
                user_whitelist=set(),
                source=f"global:disabled_group:{group_id}"
            )
        
        # 检查群组策略
        if group_id and group_id in self.group_policies:
            group = self.group_policies[group_id]
            
            if not group.enabled:
                # 群策略禁用 = 该群不进行任何拦截
                return EffectivePolicy(
                    mode=PolicyMode.BLOCKLIST,
                    commands=set(),
                    user_whitelist=set(),
                    source=f"group:{group_id}:disabled"
                )
            
            # 继承全局 + 合并群白名单
            return EffectivePolicy(
                mode=base.mode,
                commands=base.commands.copy(),
                user_whitelist=base.user_whitelist | group.user_whitelist,
                source=f"group:{group_id}"
            )
        
        # 使用全局策略
        return EffectivePolicy(
            mode=base.mode,
            commands=base.commands.copy(),
            user_whitelist=base.user_whitelist.copy(),
            source="global"
        )
    
    def is_platform_enabled(self, platform: str) -> bool:
        """检查平台是否启用"""
        base = self.global_policy
        
        # 检查禁用列表
        if platform in base.disabled_platforms:
            return False
        
        # 检查启用列表（空=全部启用）
        if base.enabled_platforms and platform not in base.enabled_platforms:
            return False
        
        return True
    
    @staticmethod
    def _parse_csv_to_set(value) -> Set[str]:
        """解析逗号分隔的字符串或列表为集合"""
        if not value:
            return set()
        if isinstance(value, str):
            return set(v.strip() for v in value.split(",") if v.strip())
        if isinstance(value, (list, set)):
            return set(value)
        return set()
    
    @staticmethod
    def _parse_csv_to_list(value) -> List[str]:
        """解析逗号分隔的字符串或列表为列表"""
        if not value:
            return []
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        if isinstance(value, list):
            return value
        return []
    
    def update_from_config(self, config: Dict[str, Any]):
        """从配置字典更新策略（只更新显式提供的字段）"""
        # 更新全局策略 - 只在配置显式提供时才覆盖
        if "enabled" in config:
            self.global_policy.enabled = bool(config["enabled"])
        
        if "mode" in config:
            mode_str = config["mode"]
            try:
                self.global_policy.mode = PolicyMode(mode_str)
            except ValueError:
                logger.warning(f"[RSC] 无效的策略模式: {mode_str}, 保持原值")
        
        if "blocked_commands" in config:
            cmds = config["blocked_commands"]
            # 支持逗号分隔字符串或列表
            case_sensitive = self.global_policy.case_sensitive
            parsed_cmds = self._parse_csv_to_set(cmds)
            if parsed_cmds:
                self.global_policy.commands = CommandNormalizer.normalize_command_set(
                    parsed_cmds, case_sensitive
                )
        
        if "command_prefixes" in config:
            prefixes = config["command_prefixes"]
            # 支持逗号分隔字符串或列表
            parsed_prefixes = self._parse_csv_to_list(prefixes)
            if parsed_prefixes:
                self.global_policy.command_prefixes = parsed_prefixes
        
        if "allow_bare_command" in config:
            self.global_policy.allow_bare_command = bool(config["allow_bare_command"])
        
        if "case_sensitive" in config:
            self.global_policy.case_sensitive = bool(config["case_sensitive"])
        
        if "user_whitelist" in config:
            users = config["user_whitelist"]
            # 支持逗号分隔字符串或列表
            self.global_policy.user_whitelist = self._parse_csv_to_set(users)
        
        if "enabled_platforms" in config:
            platforms = config["enabled_platforms"]
            self.global_policy.enabled_platforms = self._parse_csv_to_set(platforms)
        
        if "disabled_platforms" in config:
            platforms = config["disabled_platforms"]
            self.global_policy.disabled_platforms = self._parse_csv_to_set(platforms)
        
        if "disabled_groups" in config:
            groups = config["disabled_groups"]
            self.global_policy.disabled_groups = self._parse_csv_to_set(groups)
        
        # 更新群级白名单
        if "group_user_whitelist" in config:
            group_whitelist = config["group_user_whitelist"]
            if isinstance(group_whitelist, dict):
                for gid, users in group_whitelist.items():
                    if gid not in self.group_policies:
                        self.group_policies[gid] = GroupPolicy(group_id=gid)
                    self.group_policies[gid].user_whitelist = set(users)
    
    def to_config(self) -> Dict[str, Any]:
        """导出为配置字典"""
        group_whitelist = {}
        for gid, policy in self.group_policies.items():
            if policy.user_whitelist:
                group_whitelist[gid] = list(policy.user_whitelist)
        
        return {
            "enabled": self.global_policy.enabled,
            "mode": self.global_policy.mode.value,
            "blocked_commands": list(self.global_policy.commands),
            "command_prefixes": self.global_policy.command_prefixes,
            "allow_bare_command": self.global_policy.allow_bare_command,
            "case_sensitive": self.global_policy.case_sensitive,
            "user_whitelist": list(self.global_policy.user_whitelist),
            "enabled_platforms": list(self.global_policy.enabled_platforms),
            "disabled_platforms": list(self.global_policy.disabled_platforms),
            "disabled_groups": list(self.global_policy.disabled_groups),
            "group_user_whitelist": group_whitelist,
        }
