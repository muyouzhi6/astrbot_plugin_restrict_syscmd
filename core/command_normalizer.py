"""
命令规范化器 - 防止 Unicode/空白/大小写等绕过
"""
import re
import unicodedata
from typing import Optional, Tuple, List, Set
from ..models.types import CommandParseResult


# 零宽字符映射表（用于移除）
ZERO_WIDTH_CHARS = dict.fromkeys(
    map(ord, [
        "\u200b",  # Zero Width Space
        "\u200c",  # Zero Width Non-Joiner
        "\u200d",  # Zero Width Joiner
        "\u200e",  # Left-to-Right Mark
        "\u200f",  # Right-to-Left Mark
        "\ufeff",  # BOM / Zero Width No-Break Space
        "\u2060",  # Word Joiner
        "\u2061",  # Function Application
        "\u2062",  # Invisible Times
        "\u2063",  # Invisible Separator
        "\u2064",  # Invisible Plus
    ]), 
    None
)


class CommandNormalizer:
    """命令规范化器"""
    
    # 静态方法：归一化命令 key（用于策略侧，避免初始化依赖）
    @staticmethod
    def normalize_command_key(cmd: str, case_sensitive: bool = False) -> str:
        """
        归一化命令 key（用于策略入库时统一处理）
        
        Args:
            cmd: 原始命令字符串
            case_sensitive: 是否区分大小写
            
        Returns:
            归一化后的命令 key
        """
        # Unicode NFKC 归一化
        cmd = unicodedata.normalize("NFKC", cmd)
        # 移除零宽字符
        cmd = cmd.translate(ZERO_WIDTH_CHARS)
        # 空白归一化
        cmd = re.sub(r"\s+", " ", cmd)
        # 首尾去空白
        cmd = cmd.strip()
        # 大小写处理
        if not case_sensitive:
            cmd = cmd.lower()
        return cmd
    
    @staticmethod
    def normalize_command_set(cmds: Set[str], case_sensitive: bool = False) -> Set[str]:
        """
        归一化命令集合
        
        Args:
            cmds: 原始命令集合
            case_sensitive: 是否区分大小写
            
        Returns:
            归一化后的命令集合
        """
        return {
            CommandNormalizer.normalize_command_key(cmd, case_sensitive)
            for cmd in cmds
        }
    
    def __init__(
        self,
        prefixes: List[str],
        allow_bare_command: bool = False,
        case_sensitive: bool = False
    ):
        self.prefixes = prefixes
        self.allow_bare_command = allow_bare_command
        self.case_sensitive = case_sensitive
        # 按长度降序排序，防止 "/" 与 "//" 冲突
        self._sorted_prefixes = sorted(
            [p for p in prefixes if p],  # 过滤空前缀
            key=len, 
            reverse=True
        )
    
    def normalize_text(self, text: str) -> str:
        """
        规范化文本：
        1. Unicode NFKC 归一化（全角→半角等）
        2. 移除零宽字符
        3. 空白归一化
        4. 首尾去空白
        """
        # Unicode NFKC 归一化
        text = unicodedata.normalize("NFKC", text)
        # 移除零宽字符
        text = text.translate(ZERO_WIDTH_CHARS)
        # 空白归一化（多个空白→单个空格）
        text = re.sub(r"\s+", " ", text)
        # 首尾去空白
        text = text.strip()
        return text
    
    def extract_command(self, message: str) -> CommandParseResult:
        """
        从消息中提取命令
        
        Returns:
            CommandParseResult: 解析结果
        """
        original = message
        normalized = self.normalize_text(message)
        
        if not normalized:
            return CommandParseResult(
                success=False,
                original=original,
                normalized=normalized
            )
        
        # 尝试匹配前缀
        matched_prefix: Optional[str] = None
        command_text = normalized
        
        for prefix in self._sorted_prefixes:
            # 规范化前缀本身（以防配置中有全角字符）
            norm_prefix = self.normalize_text(prefix)
            if normalized.startswith(norm_prefix):
                matched_prefix = prefix
                command_text = normalized[len(norm_prefix):].lstrip()
                break
        
        # 如果没有匹配到前缀
        if matched_prefix is None:
            if not self.allow_bare_command:
                return CommandParseResult(
                    success=False,
                    original=original,
                    normalized=normalized
                )
            # 允许裸命令
            command_text = normalized
        
        # 提取命令部分（支持多段命令key，最多2段）
        if not command_text:
            return CommandParseResult(
                success=False,
                original=original,
                normalized=normalized
            )
        
        # 分割命令文本
        parts = command_text.split(" ", 2)
        
        # 尝试匹配2段命令（如 "rsc block"）
        cmd_2seg = " ".join(parts[:2]) if len(parts) >= 2 else None
        # 单段命令
        cmd_1seg = parts[0]
        
        # 大小写处理
        if not self.case_sensitive:
            cmd_1seg = cmd_1seg.lower()
            if cmd_2seg:
                cmd_2seg = cmd_2seg.lower()
        
        return CommandParseResult(
            success=True,
            command=cmd_1seg,
            command_2seg=cmd_2seg,  # 新增字段
            prefix=matched_prefix,
            original=original,
            normalized=normalized
        )
    
    def update_config(
        self,
        prefixes: Optional[List[str]] = None,
        allow_bare_command: Optional[bool] = None,
        case_sensitive: Optional[bool] = None
    ):
        """更新配置"""
        if prefixes is not None:
            self.prefixes = prefixes
            self._sorted_prefixes = sorted(
                [p for p in prefixes if p],
                key=len,
                reverse=True
            )
        if allow_bare_command is not None:
            self.allow_bare_command = allow_bare_command
        if case_sensitive is not None:
            self.case_sensitive = case_sensitive
