"""
配置迁移模块

负责在插件加载前自动检测并修复旧版本配置格式，确保配置文件符合当前 schema 要求。

迁移策略：
- v1 -> v2: 将字符串类型的列表字段转换为数组格式
- 自动备份旧配置文件
- 记录迁移日志
"""
import json
import os
import shutil
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# 需要迁移为数组类型的字段
LIST_FIELDS = [
    "blocked_commands",
    "command_prefixes", 
    "user_whitelist",
    "enabled_platforms",
    "disabled_platforms",
    "disabled_groups",
]

# 当前配置版本
CURRENT_CONFIG_VERSION = 2


def get_config_path(plugin_name: str, data_path: str) -> str:
    """获取插件配置文件路径"""
    return os.path.join(data_path, "config", f"{plugin_name}_config.json")


def load_raw_config(config_path: str) -> Optional[Dict[str, Any]]:
    """加载原始配置文件（不做任何处理）"""
    if not os.path.exists(config_path):
        return None
    try:
        with open(config_path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def save_config(config_path: str, config: Dict[str, Any]) -> bool:
    """保存配置文件"""
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except IOError:
        return False


def backup_config(config_path: str) -> Optional[str]:
    """备份配置文件，返回备份文件路径"""
    if not os.path.exists(config_path):
        return None
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{config_path}.{timestamp}.bak"
    
    try:
        shutil.copy2(config_path, backup_path)
        return backup_path
    except IOError:
        return None


def _parse_string_to_list(value: Any) -> List[str]:
    """将字符串值解析为列表
    
    支持的格式：
    - 空字符串 "" -> []
    - 逗号分隔 "a,b,c" -> ["a", "b", "c"]
    - 已经是列表 -> 保持不变
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, str):
        if not value.strip():
            return []
        return [v.strip() for v in value.split(",") if v.strip()]
    return []


def detect_migration_needed(config: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """检测是否需要迁移
    
    返回: (需要迁移, 需要迁移的字段列表)
    """
    # 检查配置版本
    version = config.get("_config_version", 1)
    if version >= CURRENT_CONFIG_VERSION:
        return False, []
    
    # 检查需要迁移的字段
    fields_to_migrate = []
    for field in LIST_FIELDS:
        value = config.get(field)
        if value is not None and isinstance(value, str):
            fields_to_migrate.append(field)
    
    return len(fields_to_migrate) > 0 or version < CURRENT_CONFIG_VERSION, fields_to_migrate


def migrate_config(config: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """执行配置迁移
    
    返回: (迁移后的配置, 迁移日志列表)
    """
    logs = []
    migrated = config.copy()
    
    old_version = config.get("_config_version", 1)
    
    # v1 -> v2: 字符串列表字段转换为数组
    for field in LIST_FIELDS:
        old_value = config.get(field)
        if old_value is not None and isinstance(old_value, str):
            new_value = _parse_string_to_list(old_value)
            migrated[field] = new_value
            logs.append(f"  {field}: \"{old_value}\" -> {new_value}")
    
    # 更新版本号
    migrated["_config_version"] = CURRENT_CONFIG_VERSION
    
    if logs:
        logs.insert(0, f"配置迁移 v{old_version} -> v{CURRENT_CONFIG_VERSION}:")
    
    return migrated, logs


def run_migration(plugin_name: str, data_path: str, logger=None) -> bool:
    """执行完整的迁移流程
    
    Args:
        plugin_name: 插件名称
        data_path: AstrBot data 目录路径
        logger: 可选的日志记录器
    
    Returns:
        是否执行了迁移
    """
    def log_info(msg: str):
        if logger:
            logger.info(msg)
        else:
            print(f"[RSC Migration] {msg}")
    
    def log_warning(msg: str):
        if logger:
            logger.warning(msg)
        else:
            print(f"[RSC Migration] WARNING: {msg}")
    
    config_path = get_config_path(plugin_name, data_path)
    
    # 加载配置
    config = load_raw_config(config_path)
    if config is None:
        # 配置文件不存在，无需迁移
        return False
    
    # 检测是否需要迁移
    needs_migration, fields = detect_migration_needed(config)
    if not needs_migration:
        return False
    
    log_info(f"检测到旧版本配置，需要迁移字段: {fields}")
    
    # 备份
    backup_path = backup_config(config_path)
    if backup_path:
        log_info(f"已备份配置到: {backup_path}")
    else:
        log_warning("备份配置失败，继续迁移...")
    
    # 执行迁移
    migrated_config, logs = migrate_config(config)
    
    # 保存
    if save_config(config_path, migrated_config):
        for log in logs:
            log_info(log)
        log_info("配置迁移完成")
        return True
    else:
        log_warning("保存迁移后的配置失败")
        return False
