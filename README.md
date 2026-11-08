# 大肥鱼桌宠 · QQ 消息与提醒桥接

把 **桌面宠物（Open-LLM-VTuber）** 和 **QQ 发消息 / 定时提醒** 连在一起：
跟桌宠说一句话，她就能帮你给好友发消息、设提醒、查联系人 —— 而且**有语音、有表情、有文字记录**。

> 这个仓库只包含**我们自己写的桥接层**（`bridge/`）和配置模板。
> 桌宠本体、QQ 协议端、语音模型、Live2D 模型都需要你自己安装（见「依赖」）。

---

## 能做什么

```
你：QQ联系人有哪些
她：联系人共 6 个：……

你：给 feven 发消息说明天见
她：准备发给 feven（1234567890）：明天见，确认吗？
你：确认
她：已发送给 feven：明天见          ← QQ 真的发出去了

你：1小时后提醒我喝水
她：好，1 小时后提醒你：喝水
（到点：QQ 收到提醒 + 她主动开口说话）
```

**三种使用方式：**

| 方式 | 说明 |
|---|---|
| 桌宠窗口 | 直接跟她打字/说话 |
| DSH 会话 | 在 DeepSeek Harness 里选「大肥鱼」预设，她照样能发消息 |
| 命令行 | `pet_chat.cmd "今天好累"`，脚本化的入口 |

---

## 架构

```
┌──────────────────────────────────────────────────────────┐
│  DSH（可选）                                              │
│    · 聊天界面 + 模型（云端 flash / 本地 KVMem）            │
│    · 通过 MCP 调用 bridge 的 7 个工具                     │
└──────────────┬───────────────────────────┬───────────────┘
               │ MCP (stdio)               │ 读会话 JSON
               ▼                           ▼
┌────────────────────────────┐   ┌─────────────────────────┐
│ bridge/（本仓库）           │   │ dsh_watch.py            │
│  · 7 个工具                │   │  把 DSH 回复变成她的语音 │
│  · 确认闸门 / 固定句式      │   │  假成功拦截 / 指令路由    │
│  · 提醒调度                │   └───────────┬─────────────┘
└──────┬─────────────────────┘               │ HTTP /api/say
       │ 内置模块（_v0）                      ▼
       ▼                          ┌─────────────────────────┐
┌──────────────────────┐          │ 桌宠后端（OLV, :12393）  │
│ bridge/_v0（内置）     │          │  · 对话 / 记忆 / ASR     │
│  vault 联系人         │◄─────────┤  · TTS（sherpa）         │
│  sender 发送          │  工具结果 │  · Live2D / WebSocket    │
│  reminders 提醒       │          └───────────┬─────────────┘
│  when 时间解析        │                      │
└──────┬───────────────┘                      │
       │ OneBot HTTP                          ▼
       ▼                          ┌─────────────────────────┐
┌──────────────────────┐          │ Electron 客户端（窗口）   │
│ SnowLuma（QQ 协议端）  │          │  Live2D + 聊天面板       │
│  登录 QQ，:3000       │          └─────────────────────────┘
└──────────────────────┘
```

**三条数据流：**

| 场景 | 路径 |
|---|---|
| 桌宠自己聊 | 客户端 → 12393 → 模型 → TTS → 客户端 |
| 发消息 / 提醒 | 模型 → bridge → SnowLuma → QQ |
| DSH 里操控 | DSH → MCP bridge → 同上；DSH 回复 → watcher → `/api/say` → 她念 |

---

## 设计原则

> **模型负责"听懂"，代码负责"事实"。**

本地小模型的工具调用不稳定，会编造"我已经发了"。所以：

- **联系人匹配**：严格打分（≥90）+ 拼音/别名兜底，匹配不到就明确报错
- **时间解析**：代码解析（"10分钟后" / "明天早上8点"），不让模型自己换算
- **确认发送**：先挂起 → 用户说"确认" → 代码才真正发送
- **固定句式直通**：`给X发消息Y` / `喊X…` / `X分钟后提醒我Y` 由代码直接执行，不进模型
- **假成功拦截**：她说"已发送"但工具日志没记录 → 替换成"其实没发出去"
- **调用审计**：每次工具调用写 `logs/tool_calls.jsonl`，可核对

---

## 依赖（都需要你自己装）

| 组件 | 作用 | 说明 |
|---|---|---|
| [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber) | 桌宠本体 | MIT 协议 |
| [SnowLuma](https://github.com/SnowLumaDevs/SnowLuma) | QQ 协议端 | 专有 EULA，**不随本仓库分发** |
| 一个 LLM | 对话 / 工具调用 | 云端 API 或本地 llama.cpp / Ollama / KVMem |
| sherpa-onnx TTS 模型 | 她的声音 | 自己准备音色模型 |
| Live2D 模型 | 她的形象 | 自己准备 |
| [DSH](https://github.com/deepseek-ai/dsh)（可选） | 聊天界面 + Agent | 用 MCP 挂载本仓库工具 |

> ⚠️ 本仓库**不包含**任何模型权重、音色、Live2D 资源、QQ 账号配置或 API Key。
> 原因（体积 + 许可）和替代方案见 **[deps/README.md](deps/README.md)**。

### 自动安装依赖

```powershell
powershell -ExecutionPolicy Bypass -File .\deps\bootstrap.ps1
```

它会：检查工具 → `git clone` 桌宠 → `uv sync` → 提示下载 SnowLuma → 复制 bridge → 生成 config。

> 语音和形象默认用**免费替代**：`edge-tts` + 桌宠自带的 Live2D 模型。
> 想用作者同款音色/形象，请自己训练或找作者授权。

### 接你自己的本地模型

**模型不用打包，用你自己电脑上已经有的。** 桌宠支持任何 OpenAI 兼容接口。

**① Ollama（最简单）**

```powershell
ollama pull qwen2.5:7b
ollama serve        # 默认 http://127.0.0.1:11434
```

`pet\conf.yaml`：

```yaml
llm_config:
  llm_provider: openai_compatible_llm
  openai_compatible_llm:
    base_url: http://127.0.0.1:11434/v1
    model: qwen2.5:7b
    llm_api_key: ollama
```

**② llama.cpp / vLLM**

```powershell
# llama.cpp
llama-server -m <模型.gguf> --port 8080 -c 8192

# vLLM
vllm serve <模型目录> --port 8000
```

```yaml
llm_config:
  llm_provider: openai_compatible_llm
  openai_compatible_llm:
    base_url: http://127.0.0.1:8080/v1   # 或 8000
    model: local-model
    llm_api_key: local
```

**③ KVMem（作者用的，带 KV 缓存）**

```powershell
# 启动 KVMem 控制台 → 选后端 → 启动，默认端口 18200
```

```yaml
llm_config:
  llm_provider: openai_compatible_llm
  openai_compatible_llm:
    base_url: http://127.0.0.1:18200/v1
    model: <你的模型名>
    llm_api_key: local
```

**④ 云端 API（不想本地跑）**

```yaml
    base_url: https://api.deepseek.com/v1
    model: deepseek-chat
    llm_api_key: <你的 key>
```

> 桌宠要求模型**支持工具调用（function calling）**，否则发消息/提醒会不稳定。
> 实测比较稳的：DeepSeek 系列、Qwen 2.5 14B 以上、KVMem 的 Qwen3。

**DSH 侧怎么指向同一个模型**

```yaml
# ~/.dsh/profiles/desktop/cordis.patch.yml
- id: llm-pi-ai
  config:
    providers:
      local:
        displayName: 本地模型
        api: openai-completions
        baseURL: http://127.0.0.1:11434/v1
        models:
          - id: qwen2.5:7b
            name: qwen2.5:7b


---

## 快速开始

### 1. 准备桌宠

按 Open-LLM-VTuber 文档装好，能正常启动、能说话。

### 2. 放代码

把本仓库的 `bridge/` 复制到桌宠根目录下（即 `<桌宠>/bridge/`），然后：

```powershell
Copy-Item .\bridge\config.example.json .\bridge\config.json
```

编辑 `bridge/config.json`：

```json
{
  "onebot": {
    "url": "http://127.0.0.1:3000",
    "token": "<SnowLuma 的 Access Token，没设就留空>"
  },
  "python_exe": "D:\\你的项目\\pet\\.venv\\Scripts\\python.exe",
  "pet_root": "D:\\你的项目\\pet",
  "pet_api": "http://127.0.0.1:12393"
}
```

> `config.json` 已被 `.gitignore` 忽略，不会进仓库。

### 3. 挂 MCP（桌宠自己用）

在桌宠的 `mcp_servers.json` 里加入：

```json
{
  "mcp_servers": {
    "msg-bridge": {
      "command": "<你的 python>\\python.exe",
      "args": ["<桌宠目录>\\bridge\\server.py"]
    }
  }
}
```

重启桌宠后端，日志里应出现 `ToolManager initialized with 7 OpenAI tools`。

### 4.（可选）挂进 DSH

两种方式，详见 **[docs/dsh.md](docs/dsh.md)**：

```text
方式 A（推荐）：把 config/AGENTS.example.md 复制到工作区，改名 AGENTS.md
方式 B（进阶）：把 config/cordis.patch.example.yml 追加到
              C:\Users\<你>\.dsh\profiles\desktop\cordis.patch.yml
```

改人设看 **[docs/persona.md](docs/persona.md)**。

> ⚠️ 改完配置必须**完全退出 DSH** 再打开，而且**新开会话**才生效。

### 5. 启动

把 `启动桌宠客户端.cmd` 放到桌宠根目录，双击。它会依次拉起：

```
SnowLuma → 后端 → 提醒调度 → DSH 监听 → 客户端
```

---

## 目录说明

```
bridge/
├─ __init__.py          路径与目录（state / logs）
├─ v0_load.py           懒加载内置模块（_v0）
├─ _v0/                 内置的联系人 / 发送 / 提醒 / 时间解析（从 v0 搬来）
│   ├─ config.py        读 bridge\config.json（OneBot 地址 / token）
│   ├─ sender.py        OneBot HTTP：发私聊、拉好友、登录信息
│   ├─ vault.py         好友缓存 + 名字匹配（拼音 + 模糊）
│   ├─ name_match.py    严格匹配规则
│   ├─ reminders.py     提醒 JSON 存储
│   ├─ when.py          中文时间解析
│   ├─ aliases.py       别名表
│   └─ models.py        Candidate / Contact
├─ safety.py            联系人匹配、时间解析、待确认状态、确认/取消词表
├─ tools.py             7 个工具的实现 + 调用审计
├─ server.py            MCP stdio 服务器（暴露 7 个工具）
├─ gate.py              确认闸门（确认/取消由代码判断）
├─ fastpath.py          固定句式直通（给X发消息 / 喊X… / X分钟后提醒我）
├─ speech.py            英文名/QQ号转中文读法（TTS 念得出来）
├─ reminder_daemon.py   提醒调度（15 秒轮询，到点发 QQ + 让她说话）
├─ dsh_watch.py         盯 DSH 会话，把回复变成她的语音 + 指令路由 + 假成功拦截
├─ pet_chat.py          命令行入口：跟她说一句话 / 让她念一句 / 看记录
├─ dsh_persona.md       人设（DSH 预设用）
├─ openai_shim.py       （可选）把桌宠伪装成 OpenAI 模型，给 DSH 当模型用
├─ ws_test.py           测试：通过 WebSocket 跟她对话
└─ run_suite.py         测试：回归用例
```

**其它目录：**

```
config\   模板：AGENTS.md / cordis 预设 / mcp_servers / config.json
docs\     文档：DSH 集成（dsh.md）、人设（persona.md）
deps\     依赖安装（bootstrap.ps1）+ 为什么不能打包
scripts\  命令行小工具（pet_chat.cmd / run_ws_test.cmd）
```

## 7 个工具

| 工具 | 作用 |
|---|---|
| `list_contacts(query)` | 查 QQ 好友 |
| `send_qq_message(to, text)` | 生成待确认消息 |
| `confirm_send()` | 确认发送 |
| `cancel_send()` | 取消 |
| `set_reminder(time_text, content)` | 设提醒 |
| `list_reminders()` | 查看提醒 |
| `cancel_reminder(keyword)` | 取消提醒 |

**HTTP 接口**（由桌宠后端提供）：

```
POST /api/chat        {"text": "..."}   等于在桌宠里打字
POST /api/say         {"text": "..."}   让她直接念（不进模型）
GET  /api/transcript?limit=50            最近对话
```

---

## 常见问题

**Q：她说话说"已经发了"，但对方没收到？**

看 `logs/tool_calls.jsonl` 有没有对应记录。没有 = 模型编的。
`dsh_watch.py` 已内置拦截：会把"已发送"替换成"其实没发出去"。

**Q：QQ 一直说"没这个人"？**

SnowLuma 没开 / 没登录。`bridge` 会自动重拉一次好友列表；仍失败会明确提示"QQ 没连上"。

**Q：她突然不说话了？**

`dsh_watch.py` 进程挂了。重跑启动脚本即可（脚本会检查并补起）。日志：`logs/watch.out`。

**Q：很慢？**

- 本地模型：提示词越大越慢（工具定义 + 人设 + 历史）
- 建议：日常用云端 flash，本地模型只在离线场景用
- 精简手段：减少工具数量、缩短人设、缩短历史

**Q：确认/取消没反应？**

确认词表在 `safety.py` 的 `is_confirm` / `is_cancel`，可按需扩充。

---

## 已知限制

| # | 限制 | 影响 | 现状 |
|---|---|---|---|
| 1 | 没有 Electron 客户端 | 用浏览器（`http://127.0.0.1:12393`），功能一样 | 设计如此 |
| 2 | 不附带音色 / Live2D | 用 `edge-tts` + 桌宠自带模型 | 版权原因 |
| 3 | 本地模型工具调用不稳 | 偶尔不调工具、编"已发送" | 已加：代码路由 + 假成功拦截 |
| 4 | 监听器靠读会话 JSON | DSH 改格式可能失效 | 已在 `dsh_watch.py` 隔离 |
| 5 | 只支持私聊 | 不能发群消息 | 未做 |
| 6 | 提醒只存在本机 JSON | 换电脑要重设 | 未做同步 |
| 7 | 单 QQ 账号 | 一个 SnowLuma 实例一个号 | 上游限制 |
| 8 | 确认词表是固定词 | 说法太怪会识别不到 | 可自行扩充 |

**已知限制都不是"坏掉"，是有意的取舍。** 需要的话可以自己扩。

---

## 安全与隐私

- 本仓库**不含**任何 API Key、QQ 号、聊天记录
- `config.json`、`state/`、`logs/` 已被 `.gitignore` 忽略
- 首次运行前请确认：不要把 `bridge/state/`（含待确认消息、QQ 号）和 `logs/` 提交进仓库

**协议风险：** 使用协议端登录 QQ 可能违反腾讯用户协议，存在封号风险，请自行评估。

---

## 许可

本仓库代码：**MIT**（见 `LICENSE`）。

第三方组件各自遵循其许可：

| 组件 | 许可 |
|---|---|
| Open-LLM-VTuber | MIT |
| SnowLuma | 专有 EULA（不可再分发） |
| TTS / Live2D 模型 | 各自作者授权，**不可商用/再分发** |

---

## 路线图

- [ ] 多账号支持
- [ ] 群消息
- [ ] 提醒的"推迟 10 分钟"
- [ ] 语音输入（ASR）→ DSH 的完整链路
- [ ] 监视页（浏览器里看对话）
