"""
冷却限制器 - 防止反馈消息刷屏
"""
import time
from typing import Dict, Tuple, Optional


class RateLimiter:
    """冷却限制器"""
    
    def __init__(self, cooldown_seconds: int = 30):
        self.cooldown_seconds = cooldown_seconds
        # 记录: {(group_id, user_id): last_notify_timestamp}
        self._last_notify: Dict[Tuple[str, str], float] = {}
        # 清理阈值：超过这个数量时清理过期记录
        self._cleanup_threshold = 1000
    
    def should_notify(self, group_id: str, user_id: str) -> bool:
        """
        检查是否应该发送通知
        
        Args:
            group_id: 群组ID（私聊用空字符串）
            user_id: 用户ID
            
        Returns:
            bool: True=应该通知, False=在冷却中
        """
        now = time.time()
        key = (group_id or "", user_id)
        
        last = self._last_notify.get(key, 0)
        
        if now - last >= self.cooldown_seconds:
            self._last_notify[key] = now
            self._maybe_cleanup(now)
            return True
        
        return False
    
    def _maybe_cleanup(self, now: float):
        """清理过期记录"""
        if len(self._last_notify) > self._cleanup_threshold:
            expired_keys = [
                k for k, v in self._last_notify.items()
                if now - v > self.cooldown_seconds * 10  # 10倍冷却时间后清理
            ]
            for k in expired_keys:
                del self._last_notify[k]
    
    def update_cooldown(self, cooldown_seconds: int):
        """更新冷却时间"""
        self.cooldown_seconds = cooldown_seconds
    
    def reset(self, group_id: Optional[str] = None, user_id: Optional[str] = None):
        """
        重置冷却记录
        
        Args:
            group_id: 指定群组（None=不限制）
            user_id: 指定用户（None=不限制）
        """
        if group_id is None and user_id is None:
            self._last_notify.clear()
            return
        
        keys_to_remove = []
        for key in self._last_notify:
            gid, uid = key
            if group_id is not None and gid != group_id:
                continue
            if user_id is not None and uid != user_id:
                continue
            keys_to_remove.append(key)
        
        for k in keys_to_remove:
            del self._last_notify[k]
