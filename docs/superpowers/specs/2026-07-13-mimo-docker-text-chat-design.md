# MiMo、Docker 与文字对话适配设计

## 1. 目标

将现有实时语音项目适配为可在 Linux 服务器上通过 Docker Compose 部署的混合对话应用，并满足以下要求：

- 语音识别使用 Cartesia `ink-whisper`。
- 大语言模型使用小米 MiMo `mimo-v2.5`，通过 Token Plan OpenAI 兼容接口调用。
- 语音合成使用小米 `mimo-v2.5-tts-voiceclone`，根据仓库内峰哥参考音频复刻音色。
- 用户既可以使用麦克风说话，也可以在同一会话中输入文字。
- 用户输入文字后，页面显示双方消息，同时继续播放 AI 的语音回复。
- TTS 失败、静音或浏览器无法使用麦克风时，文字通道仍然可用，不能出现整个会话无法交流的情况。
- 本地不部署服务、不构建镜像、不调用付费 API；提交服务器部署所需代码、配置和文档。

## 2. 已确认的外部接口

### 2.1 MiMo LLM

- Base URL：由 `MIMO_LLM_BASE_URL` 配置，部署时使用 Token Plan 中国区地址。
- API Key：由 `MIMO_LLM_API_KEY` 配置，使用 `tp-` 类型密钥。
- 模型：由 `MIMO_LLM_MODEL` 配置，默认 `mimo-v2.5`。
- 路径：`POST /chat/completions`。
- 认证头：`api-key: <key>`，不能使用现有 DeepSeek/MiniMax provider 的 `Authorization: Bearer` 写法。
- 返回格式：OpenAI 兼容 SSE，读取 `choices[0].delta.content`。

### 2.2 MiMo VoiceClone TTS

- Base URL：由 `MIMO_TTS_BASE_URL` 配置，默认 `https://api.xiaomimimo.com/v1`。
- API Key：由 `MIMO_TTS_API_KEY` 配置，使用与 Token Plan 独立的 `sk-` 类型密钥。
- 模型：由 `MIMO_TTS_MODEL` 配置，默认 `mimo-v2.5-tts-voiceclone`。
- 路径：`POST /chat/completions`。
- 认证头：`api-key: <key>`。
- 待合成文本：放在 `messages` 中 `role=assistant` 的消息内。
- 参考音频：读取 `MIMO_TTS_VOICE_FILE`，Base64 编码后以 `data:audio/wav;base64,...` 或 `data:audio/mpeg;base64,...` 传入 `audio.voice`。
- 输出：请求 `audio.format=pcm16`，按官方约定解析 24 kHz、单声道、PCM16LE 音频。
- 官方当前未提供 VoiceClone 真正的低延迟流式推理。实现按句切分 LLM 输出并逐句请求 TTS，以缩短首段语音等待时间。

真实密钥不得写入任何受 Git 管理的文件。仓库只提供环境变量名称和占位符。

## 3. 总体架构

浏览器、LiveKit 和 Agent 继续使用同一个房间与 `AgentSession`，不新增独立 HTTP 聊天会话：

```text
语音输入 ──WebRTC──┐
                   ├─> LiveKit ─> AgentSession ─> MiMo LLM ─┬─> 页面文字
文字输入 ─lk.chat──┘                                        └─> MiMo TTS ─> WebRTC 音频
```

文字输入使用 LiveKit 原生 `lk.chat` text stream。AgentSession 默认监听该 topic，将输入加入与 STT 结果相同的聊天上下文，并中断当前发言后生成新回复。这样语音、文字、人格和记忆始终共享同一条会话历史。

AI 回复使用 AgentSession 默认的 `lk.transcription` text stream 返回浏览器。服务端关闭文字与音频的同步等待，让文字在 LLM 生成时直接发布，不依赖 TTS 是否成功。

## 4. 后端设计

### 4.1 MiMo LLM provider

在现有 OpenAI 兼容流式包装中增加可配置认证头和 provider 名称，或者新增同接口的 `MiMoChatStream`。工厂与 Agent 根据 `LLM_PROVIDER=mimo` 创建实例。

实现必须：

- 启动或首次调用前校验 Base URL、API Key 和模型名。
- 使用独立的 `httpx.AsyncClient`，禁用不受控的本机代理继承。
- 设置连接、读取和总超时。
- 对非 200 响应保留状态码和经过长度限制的响应正文，不能记录 API Key。
- 正确处理空 SSE 行、`[DONE]` 和无 `choices` 的事件。
- 将 provider/model 写入可读日志，不能输出密钥。

### 4.2 MiMo TTS provider

新增符合 LiveKit TTS 协议的 MiMo 插件，职责包括：

- 在初始化时读取并缓存参考音频的 Data URI，避免每句话重复读取和编码文件。
- 校验参考文件存在、格式为 WAV/MP3 且编码后未超过官方 10 MB 限制。
- 收集短句并调用 MiMo VoiceClone。
- 解析 SSE 中 `delta.audio.data` 的 Base64 PCM 数据并推送为 24 kHz 单声道音频帧。
- 将 HTTP、JSON、Base64 和空音频错误转换成 LiveKit 可观察的 API 错误。
- 在关闭会话时释放 HTTP 客户端。

TTS 工厂增加 `mimo` 分支。选择 `mimo` 后初始化失败必须清晰报错，不再静默回退到本机不存在的 MOSS 服务。文字输出不依赖该回退机制。

### 4.3 文字优先的失败降级

AgentSession 启动时显式启用文字输入和文字输出，并将 `sync_transcription` 设为 `False`。其结果是：

- LLM 回复一产生，浏览器就能接收文字。
- TTS 延迟不会阻塞页面文字。
- TTS 单次失败会触发错误提示和日志，但不会清空聊天上下文。
- 用户可以继续发送下一条文字或语音。

记忆记录继续监听 `conversation_item_added`，因此语音和文字消息都进入同一记忆流程。现有 STT 专属事件不得重复记录文字输入。

## 5. 前端设计

### 5.1 对话区

在现有全屏场景上增加轻量对话记录区，展示用户和 AI 的最终消息。消息记录限制数量并允许滚动，避免长会话无限增长 DOM。

浏览器注册 `lk.transcription` text stream handler：

- 根据发送者 identity 区分用户与 Agent。
- 使用 stream attributes 中的 segment id 合并同一段增量文本。
- 最终消息替换临时消息，避免重复显示。
- 语音输入的 STT 文本和文字输入都进入相同的消息列表。

### 5.2 输入与发送

- 文本框只有在 LiveKit 房间连接后可发送。
- `Enter` 发送，`Shift+Enter` 换行。
- 忽略纯空白内容，并设置合理最大长度。
- 发送期间防止相同内容重复提交。
- 使用 `room.localParticipant.sendText(text, {topic: "lk.chat"})`。
- 发送失败时恢复输入内容并显示错误。
- 未连接时点击输入区或发送按钮，提示先建立连接。

### 5.3 音频和权限

连接 LiveKit 与启用麦克风拆开处理。麦克风授权失败只提示语音输入不可用，不得断开房间，文字输入仍然启用。

增加扬声器静音按钮：

- 只控制远端 AI 音频，不影响连接、文字或麦克风。
- 静音状态保存到浏览器本地存储。
- 按钮使用明确图标、`aria-label` 和 tooltip。

### 5.4 服务端地址

前端不再硬编码 `ws://127.0.0.1:7880`。`/token` 响应同时返回浏览器可访问的 `LIVEKIT_PUBLIC_URL`，前端以该值连接。

## 6. Docker 部署设计

提供以下文件：

- `Dockerfile`：基于 Python 3.12 slim，安装锁定依赖并复制应用代码，以非 root 用户运行。
- `.dockerignore`：排除 Git、缓存、本地环境、密钥和无关数据。
- `docker-compose.yml`：定义 `livekit`、`worker`、`web` 三个服务。
- `deploy/livekit.yaml`：LiveKit 端口、RTC 和开发单节点配置。
- `.env.docker.example`：仅包含占位符和部署说明。
- `docs/docker-deployment.md`：服务器准备、端口、防火墙、HTTPS/WSS、启动、日志与升级步骤。

容器网络规则：

- Worker 和 Web 使用内部地址 `ws://livekit:7880`。
- 浏览器使用 `LIVEKIT_PUBLIC_URL`，生产环境应为可公开访问的 `wss://` 地址。
- Web Server 绑定 `0.0.0.0:8766`。
- LiveKit API Key/Secret 由部署环境提供，不能依赖生产环境的固定开发密钥。
- 不在应用镜像中运行 LiveKit，也不把多个长期进程塞进同一个容器。

由于浏览器麦克风通常要求安全上下文，生产部署文档必须说明使用反向代理配置 HTTPS/WSS；仅 `localhost` 可在无 HTTPS 时例外使用麦克风。

## 7. 错误处理和可观测性

服务启动和运行日志至少覆盖：

- 选择的 STT、LLM、TTS provider 和模型。
- LiveKit Worker 注册和房间 dispatch。
- MiMo LLM 的 HTTP 状态和首 token 时间。
- MiMo TTS 的分句、请求耗时、首音频时间和音频字节数。
- 前端连接、麦克风权限、文字发送和 TTS 错误状态。

日志不得输出 API Key、完整 Token、参考音频 Base64 或完整系统提示词。

## 8. 验证范围

本次不在本机安装依赖、启动容器或调用真实 API。允许的验证包括：

- Python 语法编译检查。
- Docker Compose 配置静态检查（仅在本机已有 Docker 且不会拉取镜像时执行）。
- HTML/JavaScript 静态检查。
- 环境变量示例与代码引用一致性检查。
- Git diff、密钥扫描和敏感信息检查。

服务器部署后的验收标准：

1. 浏览器能够获取 token 并进入 LiveKit 房间。
2. 允许麦克风后，语音可经 Cartesia STT、MiMo LLM 和 MiMo TTS 完成一轮对话。
3. 拒绝麦克风权限后，仍可输入文字并看到 AI 回复。
4. 输入文字后，AI 回复同时以文字展示和克隆语音播放。
5. 静音后仍能持续看到和发送文字。
6. 人为填入无效 TTS Key 后，页面仍能收到 LLM 文字回复，并显示语音不可用状态。
7. 真实密钥不出现在 Git 历史、镜像层和前端响应中。

## 9. 非目标

- 不重做现有人格或记忆系统。
- 不新增用户账号、数据库或持久聊天记录。
- 不在本次改造中部署 Nginx、Caddy 或云厂商基础设施，只提供反向代理和端口要求。
- 不将 MiMo TTS 的参考音频上传为长期远端 voice id；每次请求按官方 VoiceClone 协议携带缓存后的 Data URI。
- 不保留前端现有 MiniMax、DeepSeek、Gemini 多模型切换入口；部署默认固定为 MiMo，避免选择不存在的 Worker 导致无法交流。
