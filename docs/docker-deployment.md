# Docker 服务器部署指南

本文说明如何在一台 Linux 服务器上部署 Web、Agent Worker 和 LiveKit。部署过程会构建 Python 镜像并拉取 LiveKit、Python 与 uv 基础镜像，但不会下载 VoxCPM 或 MOSS 模型。

## 1. 服务器准备

建议至少准备：

- Linux x86_64 或 arm64 服务器，2 核 CPU、4 GB 内存。
- Docker Engine 24+ 和 Docker Compose v2。
- 一张可被浏览器访问的公网 IP。

当前默认按“公网 IP 直接访问”配置，不要求域名。需要注意：浏览器通常禁止普通 `http://公网IP` 页面使用麦克风，因此 IP 直连适合先使用文字输入和 AI 语音回复。若要使用浏览器麦克风，仍需为页面提供浏览器信任的 HTTPS。

开放以下防火墙端口：

| 协议 | 端口 | 用途 |
| --- | --- | --- |
| TCP | 8766 | Web 页面 |
| TCP | 7880 | LiveKit WebSocket 信令 |
| TCP | 7881 | LiveKit WebRTC TCP 兜底 |
| UDP | 7882 | LiveKit WebRTC 媒体流（单端口复用） |

SSH 使用的 TCP `22` 应只允许管理 IP。若后续增加 HTTPS，再开放 TCP `80`、`443`，并将 `7880`、`8766` 限制为仅本机访问。

## 2. 配置环境变量

进入项目目录后执行：

```bash
cp .env.docker.example .env
chmod 600 .env
```

至少修改以下配置：

```env
LIVEKIT_API_KEY=随机生成的访问标识
LIVEKIT_API_SECRET=至少32字节的随机密钥
LIVEKIT_NODE_IP=服务器公网IP
LIVEKIT_PUBLIC_URL=ws://服务器公网IP:7880

CARTESIA_API_KEY=Cartesia密钥

MIMO_LLM_API_KEY=TokenPlan密钥
MIMO_TTS_API_KEY=小米按量API密钥
```

可以在服务器上生成 LiveKit 凭证：

```bash
openssl rand -hex 12
openssl rand -hex 32
```

MiMo 的两种密钥不能混用：

- `MIMO_LLM_API_KEY` 使用 Token Plan 的 `tp-` 密钥，Base URL 为 Token Plan 地址。
- `MIMO_TTS_API_KEY` 使用按量 API 的 `sk-` 密钥，Base URL 为 `https://api.xiaomimimo.com/v1`。

真实密钥只能放在服务器 `.env`，不能写入 Dockerfile、Compose、前端文件或 Git。

## 3. 使用公网 IP 访问

确认 `.env` 中的两个 IP 均已替换：

```env
LIVEKIT_NODE_IP=203.0.113.10
LIVEKIT_PUBLIC_URL=ws://203.0.113.10:7880
```

启动后通过以下地址访问：

```text
http://203.0.113.10:8766
```

请把示例地址中的 `203.0.113.10` 替换为真实公网 IP。此模式不需要 Nginx，但 `8766/TCP`、`7880/TCP`、`7881/TCP` 和 `7882/UDP` 必须同时在云安全组与服务器防火墙中放行。

公网 IP 的普通 HTTP 页面通常不能申请麦克风权限。文字输入、文字回复和 AI 语音播放不依赖麦克风，可以先用于部署验收。

## 4. 可选：配置 HTTPS 与 WSS

仓库提供 [Nginx 示例](../deploy/nginx.conf.example)。替换其中域名和证书路径后，将配置安装到服务器 Nginx。

示例拓扑：

```text
https://chat.example.com     -> 127.0.0.1:8766
wss://livekit.example.com    -> 127.0.0.1:7880
WebRTC TCP                   -> 公网IP:7881
WebRTC UDP                   -> 公网IP:7882
```

检查并重载 Nginx：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

若使用 Caddy、Traefik 或云负载均衡，需保证 LiveKit 域名支持 WebSocket Upgrade，并将长连接空闲超时调高。

## 5. 构建和启动

先检查配置展开结果：

```bash
docker compose config --quiet
```

首次构建并启动：

```bash
docker compose build worker
docker compose up -d
```

查看状态和日志：

```bash
docker compose ps
docker compose logs -f livekit worker web
```

正常情况下应看到：

- LiveKit 健康检查通过。
- Worker 以 `talk-to-me-mimo` 注册。
- Web 监听 `0.0.0.0:8766`。
- 浏览器请求 `/token` 后，日志出现房间创建和 Agent dispatch。

无域名时打开 `http://公网IP:8766`。页面会自动连接 LiveKit，输入框可直接填写；Agent 加入房间后即可发送，AI 会返回文字并播放克隆语音。扬声器按钮只控制 AI 回复音量，不影响文字。配置可信 HTTPS 后，点击麦克风图标即可启用语音输入。

## 6. 部署验收

依次验证：

1. 页面通过公网 IP 打开，状态为“峰哥就绪”。
2. 页面自动连接后状态变为“峰哥对话中”。
3. 输入文字后，页面显示用户消息与 AI 回复，并播放克隆语音。
4. 静音后仍能持续看到和发送文字。
5. 配置可信 HTTPS 后，允许麦克风，Cartesia 能识别中文并触发回复。
6. 暂时填入错误的 TTS 密钥时，页面仍显示 LLM 文字回复和“语音回复暂时不可用”提示。

## 7. 更新与回滚

更新代码后重新构建应用镜像：

```bash
git pull --ff-only
docker compose build worker
docker compose up -d
```

回滚时切回已知可用的 Git commit，再执行相同的构建和启动命令。`.env` 不受 Git 管理，不需要重复填写。

## 8. 常见问题

### 页面能打开但连接失败

IP 直连时检查 `LIVEKIT_PUBLIC_URL` 是否为浏览器可访问的 `ws://公网IP:7880`。使用 HTTPS 时应改成 `wss://` 地址，并确认 Nginx 已转发 WebSocket Upgrade。随后查看：

```bash
docker compose logs --tail=200 livekit web
```

### 连接成功但 Agent 不回复

确认 `AGENT_NAME=talk-to-me-mimo`，并在 Worker 日志中查找注册、dispatch 和房间名：

```bash
docker compose logs --tail=200 worker web
```

### 文字正常但没有声音

先确认未点击静音，再查看 Worker 中的 `[mimo_tts]`、HTTP 状态码和超时日志。`401` 通常表示误用了 Token Plan 密钥或按量密钥无效。

### 有文字输入但 LLM 不回复

检查 `MIMO_LLM_BASE_URL`、`MIMO_LLM_MODEL=mimo-v2.5` 及 Token Plan 订阅有效期。MiMo Token Plan 使用 `api-key` 认证头，代码已按此协议实现。

### 语音输入没有识别结果

检查浏览器麦克风权限、HTTPS、安全组和 `CARTESIA_API_KEY`。文字输入不依赖麦克风，可用于区分浏览器权限问题与 Agent 整体故障。

### 只能连接但听不到媒体流

确认云安全组和系统防火墙已开放 UDP `7882`、TCP `7881`，并确认 `LIVEKIT_NODE_IP` 是服务器公网 IP，而不是容器或内网地址。

### LiveKit 一直不健康

先检查配置与日志：

```bash
docker compose config --quiet
docker compose logs --tail=200 livekit
```

如果所选 LiveKit 镜像内没有 `wget`，可删除 Compose 中 LiveKit 的 `healthcheck` 和两个 `condition: service_healthy`，改为普通 `depends_on` 后启动；这只影响启动顺序检查，不影响服务协议。
