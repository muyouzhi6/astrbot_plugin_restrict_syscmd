# AstrBot 系统指令权限控制插件

> 🛡️ 专业的机器人安全防护插件，防止非管理员恶意操作和身份探测

[![GitHub](https://img.shields.io/badge/GitHub-仓库地址-blue)](https://github.com/muyouzhi6/astrbot_plugin_restrict_syscmd)
[![Version](https://img.shields.io/badge/版本-v2.0.1-green)](https://github.com/muyouzhi6/astrbot_plugin_restrict_syscmd)
[![AstrBot](https://img.shields.io/badge/适配-AstrBot%20v3.5+-orange)](https://github.com/AstrBotDevs/AstrBot)

## 🎯 插件简介

本插件专门用于保护 AstrBot 免受恶意用户的攻击和探测，通过**静默拦截**非管理员的系统指令，有效防止：

- **🔒 恶意重置攻击**：防止他人使用 `/reset`、`/new` 等指令重置机器人会话状态
- **🔍 身份探测防护**：阻止通过 `/help`、`/about` 等指令探测机器人身份特征  
- **🛡️ 系统滥用防护**：限制 `/config`、`/settings` 等管理指令仅管理员可用

### ✨ 核心特性

- **🔇 静默拦截**：不提供任何回复，完全隐藏机器人特征
- **🌐 全格式支持**：拦截 `/command`、`command`（私聊）、`@机器人 command`（群聊）
- **⚡ 超高优先级**：在所有系统指令执行前完成拦截
- **👑 管理员保护**：管理员权限完全不受影响，正常使用所有功能
- **⚙️ 可配置化**：支持通过 WebUI 自定义拦截指令列表

## 📦 安装方法

### 方式一：直接下载
1. 下载本插件文件到 `data/plugins/restrict_syscmd/` 目录
2. 重启 AstrBot 或在 WebUI 中热重载插件
3. 插件将自动激活并开始保护

### 方式二：Git克隆
```bash
cd data/plugins
git clone https://github.com/muyouzhi6/astrbot_plugin_restrict_syscmd.git restrict_syscmd
```

## 🔧 配置说明

### 默认拦截指令
插件默认拦截以下系统指令：
```
new, reset, help, start, stop, about, status, config, settings
```

### 自定义配置
1. 进入 AstrBot WebUI 管理面板
2. 导航到"插件管理" -> "restrict_syscmd"
3. 点击"配置"按钮
4. 在"blocked_commands"中自定义要拦截的指令列表

### 配置示例
```json
{
  "blocked_commands": [
    "reset", "new", "help", "about", 
    "config", "settings", "status"
  ]
}
```

## 🛠️ 技术实现

### 核心原理
- **事件拦截**：使用 `@filter.event_message_type(ALL)` 全局监听消息
- **超高优先级**：设置 `priority=sys.maxsize-1` 确保最先执行
- **多格式检测**：智能识别各种命令输入格式
- **事件控制**：通过 `event.stop_event()` 阻止系统指令执行

### 拦截流程
```
用户输入命令 → 插件优先拦截 → 权限检查 → 静默阻止/允许执行
```

### 安全设计
- **静默处理**：不提供任何响应，避免暴露拦截机制
- **权限保护**：管理员操作不受任何影响
- **日志记录**：详细记录拦截操作供管理员审查

## 📋 支持的命令格式

| 场景 | 格式示例 | 说明 |
|------|----------|------|
| 通用 | `/help` | 传统斜杠命令格式 |
| 私聊 | `help` | 私聊直接发送命令 |
| 群聊 | `@机器人 help` | 群聊@机器人发送命令 |

## ⚠️ 使用注意

### 重要提醒
- **管理员权限**：确保管理员身份正确配置，否则可能影响正常管理
- **拦截范围**：插件只拦截配置列表中的指令，其他指令不受影响
- **静默特性**：被拦截的用户不会收到任何提示，完全静默处理

### 兼容性
- **AstrBot版本**：支持 v3.4.0 及以上版本
- **平台支持**：适配所有 AstrBot 支持的聊天平台
- **Python版本**：需要 Python 3.8+

## 🔍 常见问题

### Q: 为什么选择静默拦截而不是提示？
A: 静默拦截可以避免暴露机器人身份，防止恶意用户通过系统响应识别机器人特征。

### Q: 管理员权限如何判断？
A: 基于 AstrBot 内置的权限系统，通过 `event.is_admin()` 方法判断。

### Q: 如何确认插件是否正常工作？
A: 查看 AstrBot 日志，插件会详细记录所有拦截操作。

## 📞 技术支持

- **GitHub Issues**：[提交问题反馈](https://github.com/muyouzhi6/astrbot_plugin_restrict_syscmd/issues)
- **AstrBot官方群**：322154837
- **作者**：木有知

## 📄 开源协议

本项目采用与 AstrBot 相同的开源协议。

---

**🎯 让你的 AstrBot 更安全，从拦截恶意指令开始！**
