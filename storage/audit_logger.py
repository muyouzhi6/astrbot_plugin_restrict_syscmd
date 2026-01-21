"""
审计日志 - 记录拦截事件
"""
from typing import List, Optional, Callable, Any, Dict
from collections import deque
import logging

audit_logger = logging.getLogger("astrbot.plugin.rsc.audit")

from ..models.types import AuditRecord


class AuditLogger:
    """审计日志记录器"""
    
    def __init__(
        self,
        max_records: int = 1000,
        persist_fn: Optional[Callable[[List[Dict[str, Any]]], None]] = None,
        load_fn: Optional[Callable[[], List[Dict[str, Any]]]] = None
    ):
        """
        初始化审计日志
        
        Args:
            max_records: 最大记录数
            persist_fn: 持久化函数 (records: List[dict]) -> None
            load_fn: 加载函数 () -> List[dict]
        """
        self.max_records = max_records
        self._persist_fn = persist_fn
        self._load_fn = load_fn
        self._records: deque[AuditRecord] = deque(maxlen=max_records)
        self._dirty = False
        
        # 尝试加载历史记录
        self._load()
    
    def _load(self):
        """从持久化存储加载"""
        if self._load_fn:
            try:
                data = self._load_fn()
                for d in data[-self.max_records:]:
                    self._records.append(AuditRecord.from_dict(d))
            except Exception as e:
                audit_logger.debug(f"加载审计日志失败: {e}")
    
    def _persist(self):
        """持久化到存储"""
        if self._persist_fn and self._dirty:
            try:
                data = [r.to_dict() for r in self._records]
                self._persist_fn(data)
                self._dirty = False
            except Exception as e:
                audit_logger.debug(f"持久化审计日志失败: {e}")
    
    def log(self, record: AuditRecord):
        """记录审计事件"""
        self._records.append(record)
        self._dirty = True
        # 每10条记录持久化一次
        if len(self._records) % 10 == 0:
            self._persist()
    
    def get_recent(self, n: int = 10) -> List[AuditRecord]:
        """获取最近N条记录"""
        records = list(self._records)
        return records[-n:][::-1]  # 最新的在前
    
    def query(
        self,
        user_id: Optional[str] = None,
        group_id: Optional[str] = None,
        command: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 50
    ) -> List[AuditRecord]:
        """
        查询审计记录
        
        Args:
            user_id: 用户ID过滤
            group_id: 群组ID过滤
            command: 命令过滤
            action: 动作过滤 (blocked/allowed)
            limit: 返回数量限制
            
        Returns:
            匹配的记录列表
        """
        results = []
        for record in reversed(self._records):
            if user_id and record.user_id != user_id:
                continue
            if group_id and record.group_id != group_id:
                continue
            if command and record.command != command:
                continue
            if action and record.action != action:
                continue
            results.append(record)
            if len(results) >= limit:
                break
        return results
    
    def clear(self):
        """清空记录"""
        self._records.clear()
        self._dirty = True
        self._persist()
    
    def flush(self):
        """强制持久化"""
        self._persist()
    
    def update_max_records(self, max_records: int):
        """更新最大记录数"""
        if max_records != self.max_records:
            self.max_records = max_records
            # 重建 deque 以应用新的 maxlen
            old_records = list(self._records)
            self._records = deque(old_records[-max_records:], maxlen=max_records)
            self._dirty = True
