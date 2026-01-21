"""
统计收集器 - 收集拦截统计数据
"""
from typing import Optional, Callable, Dict, Any
import logging

stats_logger = logging.getLogger("astrbot.plugin.rsc.stats")

from ..models.types import StatsData


class StatsCollector:
    """统计收集器"""
    
    def __init__(
        self,
        persist_fn: Optional[Callable[[Dict[str, Any]], None]] = None,
        load_fn: Optional[Callable[[], Dict[str, Any]]] = None
    ):
        """
        初始化统计收集器
        
        Args:
            persist_fn: 持久化函数 (data: dict) -> None
            load_fn: 加载函数 () -> dict
        """
        self._persist_fn = persist_fn
        self._load_fn = load_fn
        self._stats = StatsData()
        self._dirty = False
        
        # 尝试加载历史统计
        self._load()
    
    def _load(self):
        """从持久化存储加载"""
        if self._load_fn:
            try:
                data = self._load_fn()
                if data:
                    self._stats = StatsData.from_dict(data)
            except Exception as e:
                stats_logger.debug(f"加载统计数据失败: {e}")
    
    def _persist(self):
        """持久化到存储"""
        if self._persist_fn and self._dirty:
            try:
                self._persist_fn(self._stats.to_dict())
                self._dirty = False
            except Exception as e:
                stats_logger.debug(f"持久化统计数据失败: {e}")
    
    def record_blocked(
        self,
        command: str,
        user_id: str,
        group_id: Optional[str] = None
    ):
        """记录拦截事件"""
        self._stats.total_blocked += 1
        
        # 按命令统计
        self._stats.by_command[command] = self._stats.by_command.get(command, 0) + 1
        
        # 按用户统计
        self._stats.by_user[user_id] = self._stats.by_user.get(user_id, 0) + 1
        
        # 按群统计
        if group_id:
            self._stats.by_group[group_id] = self._stats.by_group.get(group_id, 0) + 1
        
        self._dirty = True
        
        # 每10次记录持久化一次
        if self._stats.total_blocked % 10 == 0:
            self._persist()
    
    def record_allowed(
        self,
        command: str,
        user_id: str,
        group_id: Optional[str] = None
    ):
        """记录放行事件（仅计数）"""
        self._stats.total_allowed += 1
        self._dirty = True
    
    def get_stats(self) -> StatsData:
        """获取统计数据"""
        return self._stats
    
    def get_summary(self) -> str:
        """获取统计摘要"""
        s = self._stats
        lines = [
            f"📊 拦截统计",
            f"├ 总拦截: {s.total_blocked}",
            f"├ 总放行: {s.total_allowed}",
        ]
        
        # Top 5 命令
        if s.by_command:
            top_cmds = sorted(s.by_command.items(), key=lambda x: -x[1])[:5]
            lines.append(f"├ Top 命令:")
            for cmd, count in top_cmds:
                lines.append(f"│  ├ {cmd}: {count}")
        
        # Top 5 用户
        if s.by_user:
            top_users = sorted(s.by_user.items(), key=lambda x: -x[1])[:5]
            lines.append(f"├ Top 用户:")
            for uid, count in top_users:
                lines.append(f"│  ├ {uid}: {count}")
        
        # Top 5 群组
        if s.by_group:
            top_groups = sorted(s.by_group.items(), key=lambda x: -x[1])[:5]
            lines.append(f"└ Top 群组:")
            for gid, count in top_groups:
                lines.append(f"   ├ {gid}: {count}")
        
        return "\n".join(lines)
    
    def reset(self):
        """重置统计"""
        self._stats = StatsData()
        self._dirty = True
        self._persist()
    
    def flush(self):
        """强制持久化"""
        self._persist()
