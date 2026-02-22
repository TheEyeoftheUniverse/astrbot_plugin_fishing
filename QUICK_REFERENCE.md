# 用户WebUI 快速参考指南

## ✅ 集成完成

用户WebUI功能已完全集成到钓鱼插件中。以下是快速参考。

## 🎮 管理员命令

### 启动用户WebUI
```
/启动用户WebUI
```

**预期输出：**
```
✅ 用户WebUI已启动！
🔗 访问地址: http://localhost:8888
⚠️ 提示：确保端口 8888 未被占用
```

### 关闭用户WebUI
```
/关闭用户WebUI
```

**预期输出：**
```
✅ 用户WebUI已关闭
```

## 🔧 配置

编辑插件配置文件中的 `user_webui` 部分：

```json
"user_webui": {
  "port": 8888,                              // WebUI访问端口
  "secret_key": "your_secret_key_here",      // 会话加密密钥
  "enabled": true                            // 是否启用功能
}
```

## 📂 集成的文件

| 文件 | 说明 | 改动 |
|------|------|------|
| `_conf_schema.json` | 配置模式定义 | 添加了user_webui配置项 |
| `main.py` | 主插件文件 | 初始化、命令注册、清理逻辑 |
| `handlers/admin_handlers.py` | 管理员命令处理 | 添加了start/stop函数 |
| `manager/user_server.py` | 用户WebUI服务器 | 已存在，无改动 |
| `manager/user_api.py` | 用户API路由 | 已存在，无改动 |

## 🔍 技术细节

### 初始化流程
1. 从配置文件读取user_webui配置
2. 在插件启动时初始化相关实例变量
3. 管理员可通过命令启动/停止服务

### 启动流程
1. 验证是否已在运行
2. 创建Quart应用实例
3. 注入必要的服务（UserService, InventoryService等）
4. 启动Hypercorn异步服务器
5. 绑定到配置的端口

### 停止流程
1. 验证是否在运行
2. 取消异步任务
3. 清理资源

### 关闭流程（插件卸载时）
1. 检查user_web_task是否存在
2. 取消任务
3. 释放资源

## 🚀 使用示例

### 场景1：启动WebUI进行管理
```
管理员: /启动用户WebUI
机器人: ✅ 用户WebUI已启动！
       🔗 访问地址: http://localhost:8888
管理员: （用户现在可以访问WebUI）
```

### 场景2：进行维护后关闭
```
管理员: /关闭用户WebUI
机器人: ✅ 用户WebUI已关闭
```

## 📋 服务注入

WebUI应用会自动注入以下服务：
- `user_repo` - 用户数据仓储
- `inventory_repo` - 背包数据仓储
- `item_template_service` - 物品模板服务
- `user_service` - 用户服务
- `market_service` - 市场服务
- `fishing_service` - 钓鱼服务
- `gacha_service` - 抽卡服务

## 🔒 安全建议

1. **更改默认密钥**
   ```json
   "secret_key": "your_very_secure_random_string_here"
   ```

2. **配置防火墙**
   - 仅允许内网访问端口8888
   - 或通过Nginx反向代理进行HTTPS

3. **定期检查**
   - 监控WebUI访问日志
   - 检查异常连接

## 💡 常见问题

### Q: 如何自定义WebUI端口？
A: 在配置文件中修改 `user_webui.port` 值

### Q: 可以同时运行管理员WebUI和用户WebUI吗？
A: 可以，它们使用不同的端口（7777 vs 8888），互不干扰

### Q: WebUI启动失败怎么办？
A: 检查以下几点：
- 端口是否被占用
- 配置是否正确
- 查看机器人日志了解具体错误

### Q: 如何在生产环境中运行？
A: 推荐使用Nginx进行反向代理和HTTPS配置

## 📞 技术支持

如有问题，请查阅：
- `USER_WEBUI_INTEGRATION.md` - 完整集成指南
- `USER_WEBUI_GUIDE.md` - 用户使用指南
- `INTEGRATION_SUMMARY.md` - 集成总结

---

**最后更新：** 2025-12-09
**集成版本：** 1.0 (完整实现)
