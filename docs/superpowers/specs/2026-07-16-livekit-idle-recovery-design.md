# LiveKit 闲置断线恢复设计

## 背景

页面长时间闲置、浏览器休眠或网络短暂中断后，LiveKit 可能进入重连或彻底断开状态。当前页面只维护一个布尔型 `connected` 状态，没有处理重连过程；消息发送后也没有 Agent 接收确认。后端 `AgentSession` 使用默认的 `close_on_disconnect=True`，关联用户断开时可能提前关闭会话。

## 目标

- 短暂断网恢复后，无需刷新页面即可继续发送消息。
- 彻底断开后，页面自动获取新 token、创建新房间并重新 dispatch Agent。
- 消息只有收到 Agent ACK 后才视为已送达；未确认时自动重试一次并明确提示。
- 用户短暂离线时不关闭当前 `AgentSession`。
- Docker 默认 LiveKit Server 版本与部署示例统一为 `v1.9.2`。

## 方案

### 前端连接状态

以 `room.state` 作为真实连接状态，监听 `Reconnecting`、`Reconnected` 和 `Disconnected`。重连期间保留输入内容但暂停实际发送；重连成功后继续发送。彻底断开时执行一次受互斥保护的全量重连，重新调用 `/token` 并创建新的 `Room`。

### 消息确认

前端为每条文字消息生成 `messageId`，发送后放入待确认集合。Agent 收到合法消息后立即通过 `agent.message_ack` topic 返回 ACK。前端收到 ACK 后清理超时计时器；超时后先检查连接并自动重试一次，第二次仍未确认则恢复输入并提示用户。

ACK 只表示 Agent 已接收并开始处理，不表示 LLM 已完成回复。

### 后端会话

`RoomOptions` 设置 `close_on_disconnect=False`，避免浏览器短暂断线直接关闭会话。用户离开后保留 60 秒重连宽限期；宽限期结束仍无普通用户时主动关闭 Agent 作业，避免孤立房间长期占用资源。Agent 收到消息并完成参数校验后先发送 ACK，再调用 `generate_reply`。

### 部署配置

将 `docker-compose.yml` 中 LiveKit Server 默认镜像调整为 `v1.9.2`，避免未设置 `LIVEKIT_IMAGE` 时回退到旧版本。

## 异常处理

- 重连过程中不重复创建多个房间。
- 旧房间的异步事件不得覆盖新房间状态。
- Agent 不在房间时触发全量重连，而不是静默丢弃消息。
- ACK 超时最多自动重试一次，避免网络异常时无限重复生成回复。
- 后端 ACK 发送失败只记录日志，不阻断已经收到的用户消息。

## 验证

按照项目约定不新增测试类。使用临时静态回归脚本验证关键配置，再通过 Chrome DevTools 模拟离线和恢复，检查重连事件、消息 ACK、重复发送保护及页面提示。
