"""
astrbot_plugin_restrict_syscmd 包初始化

在插件加载前自动执行配置迁移，确保旧版本配置格式兼容。
"""
import os
import logging

# 尝试执行配置迁移
try:
    from .config_migrator import run_migration
    
    # 获取 AstrBot data 路径
    # 插件位于 data/plugins/plugin_name/，data 目录在上两级
    plugin_dir = os.path.dirname(os.path.abspath(__file__))
    plugins_dir = os.path.dirname(plugin_dir)
    data_path = os.path.dirname(plugins_dir)
    
    # 获取插件名称
    plugin_name = os.path.basename(plugin_dir)
    
    # 执行迁移
    logger = logging.getLogger("astrbot")
    run_migration(plugin_name, data_path, logger)
    
except Exception as e:
    # 迁移失败不应阻止插件加载
    logging.getLogger("astrbot").debug(f"[RSC] 配置迁移检查失败（可忽略）: {e}")
