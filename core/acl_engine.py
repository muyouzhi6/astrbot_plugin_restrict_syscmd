"""
ACL 引擎 - 访问控制核心逻辑
"""
from typing import Optional
from ..models.types import (
    ACLCheckResult, CommandParseResult, EffectivePolicy, PolicyMode
)
from .command_normalizer import CommandNormalizer
from .policy_resolver import PolicyResolver


class ACLEngine:
    """访问控制引擎"""
    
    def __init__(
        self,
        normalizer: CommandNormalizer,
        resolver: PolicyResolver
    ):
        self.normalizer = normalizer
        self.resolver = resolver
    
    def check(
        self,
        message: str,
        user_id: str,
        group_id: Optional[str],
        platform: str,
        is_admin: bool,
        *,
        allow_bare_override: bool = False
    ) -> ACLCheckResult:
        """
        检查消息是否被允许
        
        Args:
            message: 原始消息
            user_id: 用户ID
            group_id: 群组ID（私聊为None）
            platform: 平台名称
            is_admin: 是否为管理员
            
        Returns:
            ACLCheckResult: 检查结果
        """
        # 检查全局开关
        if not self.resolver.global_policy.enabled:
            return ACLCheckResult(
                allowed=True,
                reason="插件已禁用",
                is_admin=is_admin
            )
        
        # 检查平台是否启用
        if not self.resolver.is_platform_enabled(platform):
            return ACLCheckResult(
                allowed=True,
                reason=f"平台 {platform} 未启用拦截",
                is_admin=is_admin
            )
        
        # 解析命令
        parse_result = self.normalizer.extract_command(
            message, allow_bare_override=allow_bare_override
        )
        
        if not parse_result.success or not parse_result.command:
            return ACLCheckResult(
                allowed=True,
                reason="非命令消息",
                is_admin=is_admin
            )
        
        # 获取生效策略
        policy = self.resolver.resolve(group_id)
        
        # 检查命令是否在策略范围内（优先匹配2段命令）
        command = parse_result.command
        command_2seg = parse_result.command_2seg
        
        # 优先尝试匹配2段命令
        matched_command = None
        is_in_list = False
        
        if command_2seg and command_2seg in policy.commands:
            matched_command = command_2seg
            is_in_list = True
        elif command in policy.commands:
            matched_command = command
            is_in_list = True
        else:
            matched_command = command  # 用于日志
        
        if policy.mode == PolicyMode.BLOCKLIST:
            # 黑名单模式：命令在列表中才需要检查权限
            if not is_in_list:
                return ACLCheckResult(
                    allowed=True,
                    reason="命令不在拦截列表",
                    command=matched_command,
                    policy_source=policy.source,
                    is_admin=is_admin
                )
        else:
            # 白名单模式：命令不在列表中需要检查权限
            if is_in_list:
                return ACLCheckResult(
                    allowed=True,
                    reason="命令在允许列表",
                    command=matched_command,
                    policy_source=policy.source,
                    is_admin=is_admin
                )
        
        # 命令需要权限检查
        
        # 管理员直接放行
        if is_admin:
            return ACLCheckResult(
                allowed=True,
                reason="管理员权限",
                command=matched_command,
                policy_source=policy.source,
                is_admin=True
            )
        
        # 检查用户白名单
        if user_id in policy.user_whitelist:
            return ACLCheckResult(
                allowed=True,
                reason="用户在白名单",
                command=matched_command,
                policy_source=policy.source,
                is_admin=False,
                is_whitelisted=True
            )
        
        # 拦截
        if policy.mode == PolicyMode.BLOCKLIST:
            reason = f"命令 [{matched_command}] 在拦截列表中"
        else:
            reason = f"命令 [{matched_command}] 不在允许列表中"
        
        return ACLCheckResult(
            allowed=False,
            reason=reason,
            command=matched_command,
            policy_source=policy.source,
            is_admin=False,
            is_whitelisted=False
        )
    
    def test_command(
        self,
        command: str,
        user_id: str,
        group_id: Optional[str],
        is_admin: bool
    ) -> ACLCheckResult:
        """
        测试命令是否会被拦截（用于 /rsc test）
        
        Args:
            command: 命令（不含前缀）
            user_id: 用户ID
            group_id: 群组ID
            is_admin: 是否管理员
            
        Returns:
            ACLCheckResult: 检查结果
        """
        # 获取生效策略
        policy = self.resolver.resolve(group_id)
        
        # 大小写处理
        if not self.normalizer.case_sensitive:
            command = command.lower()
        
        # 检查命令是否在策略范围内
        is_in_list = command in policy.commands
        
        if policy.mode == PolicyMode.BLOCKLIST:
            if not is_in_list:
                return ACLCheckResult(
                    allowed=True,
                    reason="命令不在拦截列表",
                    command=command,
                    policy_source=policy.source,
                    is_admin=is_admin
                )
        else:
            if is_in_list:
                return ACLCheckResult(
                    allowed=True,
                    reason="命令在允许列表",
                    command=command,
                    policy_source=policy.source,
                    is_admin=is_admin
                )
        
        # 管理员放行
        if is_admin:
            return ACLCheckResult(
                allowed=True,
                reason="管理员权限",
                command=command,
                policy_source=policy.source,
                is_admin=True
            )
        
        # 用户白名单
        if user_id in policy.user_whitelist:
            return ACLCheckResult(
                allowed=True,
                reason="用户在白名单",
                command=command,
                policy_source=policy.source,
                is_whitelisted=True
            )
        
        # 会被拦截
        if policy.mode == PolicyMode.BLOCKLIST:
            reason = f"命令 [{command}] 在拦截列表中，非管理员将被拦截"
        else:
            reason = f"命令 [{command}] 不在允许列表中，非管理员将被拦截"
        
        return ACLCheckResult(
            allowed=False,
            reason=reason,
            command=command,
            policy_source=policy.source
        )
