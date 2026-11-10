# 大肥鱼桌宠 · Dafeiyu

在 DSH 或桌宠窗口里聊天，让桌宠帮你给 QQ 好友发消息、设置提醒，并把回答念出来。

**0.2.0：统一命令路由、事务化执行状态、可移植安装和分段语音预合成。** 本次没有新增视觉功能。

## 使用示例

```text
你：给小王发消息说明天见
她：准备发给小王（…）：明天见。确认发送吗？
你：确认
她：已发送给小王：明天见

你：十分钟后提醒我喝水
她：好，…提醒你：喝水
```

“已发送”表示 QQ 协议端返回成功，不代表对方已读。发送超时会显示“结果未知”，不会自动重发。

## 处理流程

```text
DSH / 桌宠输入
  → 规则识别明确命令
  → 规则未识别：KVMem 网关按候选能力请求一次意图解析
  → 统一路由 → 对应工具 → SQLite 任务状态 → 实际结果

普通聊天 → 模型 SSE → DSH 显示
DSH 会话文件 → 只读 watcher → 语音队列 → TTS 预合成 → 顺序播放
```

- 聊天不会执行所有工具。网关保留 DSH 原生工具，只筛选桌宠相关工具定义。
- MCP、桌宠规则入口和网关使用同一个发送确认服务。
- 待发消息按会话保存；数据库事务保证同一任务只能被一个确认者领取。
- 同一请求 ID 的命令重试返回已有结果；不同轮次应使用不同 ID。
- 提醒的 QQ 与语音入队状态分别记录，明确失败可以重试，结果未知需人工核对。
- watcher 不执行命令；`--dry` 不发声、不修改游标，也不执行任何工具。

## 安装（Windows）

需要 Git、Python 3.10–3.12、uv，以及你自己的模型服务。安装完整桌宠：

```powershell
git clone https://github.com/Fevenen/dafeiyu.git
cd dafeiyu
powershell -ExecutionPolicy Bypass -File .\deps\bootstrap.ps1 -Root "D:\我的助手"
```

安装器固定使用 Open-LLM-VTuber v1.2.1，校验提交 `3afa41014b4548a0842e9ee2f576f4b164b48886`，包含前端子模块，并安装本仓库的后端覆盖文件。已有桌宠可直接安装：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -PetRoot "D:\我的助手\pet"
```

安装前请关闭旧服务。安装器会备份被替换的后端文件，并保留已有配置与人设。其他上游版本会被拒绝覆盖。

完整桌宠安装保留 MCP 1.x 以兼容上游后端；桥接层独立使用同时支持 MCP 1.x/2.x。

接下来配置：

1. `pet/conf.yaml`：LLM、TTS、Live2D。后端地址建议设为 `127.0.0.1`。
2. `pet/bridge/config.json`：QQ 协议端地址/token、KVMem 上游地址、可选客户端和 SnowLuma 启动位置。
3. 按 [DSH 接入](docs/dsh.md) 使用安装器生成的 MCP/DSH 配置片段。

桌宠、模型权重、音色、Live2D 和 SnowLuma 不包含在这个 Git 仓库中；安装器不自动下载账号或角色资源。QQ 连接见 [QQ 配置](docs/qq-setup.md)。

```powershell
cd "D:\我的助手\pet"
.\.venv\Scripts\python.exe -m bridge.doctor
.\.venv\Scripts\python.exe -m bridge.launcher
# 服务启动后，检查健康接口（不发送消息）
.\.venv\Scripts\python.exe -m bridge.doctor --network
```

也可以双击安装到 pet 目录的 `启动桌宠客户端.cmd`。未配置 `desktop_client` 时只启动服务；可以使用上游网页客户端或配置自己的 Electron 客户端。

只使用 MCP/QQ 工具、不安装桌宠时，可在本仓库创建虚拟环境、`pip install -r requirements.txt`，再运行 `python -m bridge.server`。

## 配置与可移植性

配置优先级：支持该选项的命令行参数 → 环境变量 → `config.json` → 默认值。路径相对于配置文件所在目录解析，和启动目录无关。

| 配置/环境变量 | 作用 |
|---|---|
| `PET_CONFIG` | 选择本地 JSON 配置文件 |
| `pet_root` / `PET_ROOT` | 包含 run_server.py 的桌宠目录 |
| `pet_data_dir` / `PET_DATA_DIR` | 数据库、日志、缓存状态与安装备份目录 |
| `pet_api` / `PET_API` | 桌宠后端地址 |
| `onebot.url` / `ONEBOT_URL` | QQ 协议端 HTTP 地址 |
| `onebot.token` / `ONEBOT_TOKEN` | QQ token，只保存在本机 |
| `kvmem_upstream` / `KVMEM_UPSTREAM` | 本地模型上游地址 |
| `kvmem_proxy_port` / `KVMEM_PROXY_PORT` | 网关监听端口 |
| `workspace` / `WORKSPACE` | watcher 默认工作区 |
| `desktop_client` | 可选 Electron 可执行文件 |
| `snowluma_launcher` | 可选 SnowLuma 启动脚本 |

MCP 宿主要求的绝对路径由安装器生成到 `bridge/data/generated/`，不提交 Git。移动安装目录后重新运行安装器生成片段，并更新宿主配置。源码不依赖作者的盘符、用户名或旧 v0 目录。

## 会话隔离与重试

自定义 HTTP 客户端应传入 `X-Session-ID`、`X-Request-ID`，也可使用请求 `metadata.session_id`、`metadata.request_id`。不同会话 ID 必须不同；同轮重试的请求 ID 保持相同。

DSH 未提供稳定 ID 时，网关使用首条用户消息的指纹作为兼容退路，并检查历史是否连续；发现分支冲突会停止执行，要求显式绑定。**相同开场的并行 DSH 会话不能依靠指纹获得可靠隔离**，应使用独立网关配置/端口和不同 `BRIDGE_SESSION_ID`，或让宿主传入稳定会话 ID。

每个 MCP stdio 进程默认独立作用域，进程重启后旧待确认不可直接确认。`confirm_send` 要求原样传入本轮确认文字。SQLite 领取与固定动作 ID 防止同一任务重复发出，但外部网络无法提供端到端“恰好一次”；超时或进程在发送中崩溃时保持未知状态。

## 工具与扩展

提供 `route_command`、`list_capabilities`，以及联系人、准备发送、确认、取消、创建/列出/取消提醒、查询执行记录等兼容工具。

新增能力按 [扩展指南](docs/architecture.md) 注册：描述与工具组 → 参数校验 → 工具实现 → 离线测试。当前规则路由一次执行一个动作，复杂组合请求应先澄清或分步处理。

## 语音与接口

| 接口 | 用途 |
|---|---|
| `GET /api/health` | 版本、在线客户端和语音队列能力 |
| `POST /api/chat` | 向在线桌宠发起对话 |
| `POST /api/say` | 直接播报；`enqueue: true` 可立即入队 |
| `GET /api/speech/status?job_id=…` | 查询 queued / playing / played / failed / cancelled |
| `POST /api/speech/cancel` | 取消外部语音队列并停止前端播放 |
| `GET /api/transcript` | 桌宠后端历史记录 |

语音采用“每段完整合成、当前段播放时预合成下一段”，不是音频采样流式输出。`job_id` 用于进程内去重；入队成功不等于已播放，后端重启会丢失内存队列。watcher 游标记录已入队文本，需要重播时应由用户重新触发。没有在线客户端或队列满时不会推进游标。

## 开发与验证

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

测试不调用真实 QQ、模型或音频设备，覆盖并发确认、进程间抢占、会话隔离、超时状态、提醒并发写入、SSE 提前到达、原生工具保留、语音预合成和中文空格路径安装。GitHub Actions 配置了 Windows/Linux、Python 3.10/3.12、MCP 1.x/2.x 的测试矩阵；远程运行结果以 Actions 页面为准。

目录：`bridge/` 核心与适配器；`runtime/` 固定上游版本的后端覆盖文件；`config/` 公开模板；`tests/` 离线测试；`docs/` 使用和架构说明。

## 升级与限制

- 从旧版本升级请先关闭旧网关、watcher、调度器和后端，再启动新版本。
- 旧 `_v0/reminders.json` 会导入 SQLite 并保留原文件，归属 legacy `local` 作用域；到期调度仍会处理，查询时可使用该作用域。旧 pending.json 不迁移，需要重新提出发送请求。
- watcher 仍依赖 DSH 会话 JSON 格式，不保证逐 token 获得文字；桌宠收到的是分段播报。
- 本次没有新增屏幕理解、持续观察、多 QQ 账号或群消息。
- 未连接的外部服务不会被离线测试替代验证；完整使用仍需正确配置 QQ、模型、TTS 与角色资源。

## 许可

桥接代码采用 MIT；运行时覆盖文件保留 Open-LLM-VTuber 的 MIT 许可，见 `runtime/LICENSE-Open-LLM-VTuber`。其他组件和角色资源遵循各自许可。
