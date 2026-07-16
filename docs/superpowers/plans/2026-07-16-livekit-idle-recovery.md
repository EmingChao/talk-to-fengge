# LiveKit 闲置断线恢复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复页面闲置或网络中断后文字消息无回复的问题，并让消息送达状态可观察。

**Architecture:** 前端基于 LiveKit 真实连接状态管理重连，通过消息 ACK 和一次重试避免静默丢包；后端保持 AgentSession 并在接收消息后返回 ACK；部署配置统一 LiveKit Server 版本。

**Tech Stack:** HTML、原生 JavaScript、LiveKit Client 2.19.1、Python 3.12、LiveKit Agents、Docker Compose

---

### Task 1: 建立失败检查

**Files:**
- Verify: `web/index.html`
- Verify: `worker/agent.py`
- Verify: `docker-compose.yml`

- [ ] 使用临时 Python 脚本断言前端包含重连事件和 ACK、后端关闭断线自动关会话、Compose 默认版本为 `v1.9.2`。
- [ ] 运行脚本并确认当前代码因缺少这些行为而失败。

### Task 2: 实现后端会话保持和 ACK

**Files:**
- Modify: `worker/agent.py`

- [ ] 增加 ACK topic 常量和 ACK 发布方法。
- [ ] 在消息参数校验完成后发送 ACK，再触发回复生成。
- [ ] 将 `RoomOptions.close_on_disconnect` 设置为 `False`。
- [ ] 增加 60 秒用户重连宽限期，超时后关闭孤立 Agent 作业。
- [ ] 运行 Python 编译检查。

### Task 3: 实现前端恢复流程

**Files:**
- Modify: `web/index.html`

- [ ] 使用 `room.state` 判断真实连接状态。
- [ ] 监听 `Reconnecting` 和 `Reconnected`，同步页面状态。
- [ ] 为全量重连增加互斥控制和旧 Room 事件隔离。
- [ ] 增加消息 ACK、超时和一次自动重试。
- [ ] Agent 离开或彻底断开时自动建立新房间。

### Task 4: 统一部署版本

**Files:**
- Modify: `docker-compose.yml`

- [ ] 将默认 LiveKit Server 镜像更新为 `v1.9.2`。

### Task 5: 验证

**Files:**
- Verify: `web/index.html`
- Verify: `worker/agent.py`
- Verify: `docker-compose.yml`

- [ ] 再次运行临时静态回归脚本并确认通过。
- [ ] 运行 Python 编译检查和现有单元测试。
- [ ] 启动本地 LiveKit/Web 调试环境，通过 Chrome DevTools 模拟 Offline → Online。
- [ ] 检查消息只处理一次、ACK 被清理、断线后页面能够恢复发送。
