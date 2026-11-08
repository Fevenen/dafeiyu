# 在 DSH 里用桌宠

> DSH = DeepSeek Harness（本项目的宿主界面）。这一页讲怎么让桌宠在 DSH 里工作。

---

## 为什么要接 DSH

不接 DSH，你只能在桌宠窗口里跟她说话。

接上之后：

- 在 DSH 的聊天框里说话，她照样能发 QQ、设提醒
- 她的回复可以用语音念出来
- 可以同时用 DSH 的编程能力（读文件、跑命令）

---

## 两种接法，选一种

| 方式 | 适合 | 复杂度 |
|---|---|---|
| **A. 工作区 `AGENTS.md`** | 大多数情况（推荐） | 低：放一个文本文件 |
| **B. Agent 预设** | 想要多个角色、想单独控模型 | 中：改 YAML 配置 |

**两种可以同时用**（预设里也有人格时，AGENTS.md 会叠加）。

---

## 方式 A：工作区 AGENTS.md（推荐）

**原理**：DSH 在会话第一次请求时，会读取工作区里的 `AGENTS.md` 和 `CLAUDE.md`，当固定指令。

### 步骤

1. 建一个专门的工作区目录，例如 `D:\project\MP\pet_workspace`
2. 把 `config/AGENTS.example.md` 复制进去，改名 `AGENTS.md`
3. DSH 里打开这个工作区 → 新建会话
4. 说一句话，看她的口气对不对

### 改人设

直接编辑 `AGENTS.md`，**下次新建会话生效**（已开的会话不会重新读）。

详见 [persona.md](persona.md)。

### 让 DSH 能发 QQ / 设提醒

`AGENTS.md` 只负责人格，工具来自 MCP。确保桌宠的 `mcp_servers.json` 里有：

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

如果你想让 **DSH 自己**（而不是桌宠）能调这些工具，见方式 B 的 `@deepseek-ai/dsh-mcp-client` 部分。

---

## 方式 B：Agent 预设

**原理**：DSH 的"预设"是一个插件声明行，定义这个会话用哪套人设、挂哪些工具。

### 1. 找到配置文件

```
C:\Users\<你>\.dsh\profiles\desktop\cordis.patch.yml
```

**改之前先备份**：

```powershell
Copy-Item cordis.patch.yml cordis.patch.yml.bak
```

### 2. 追加预设

把 `config/cordis.patch.example.yml` 追加到文件末尾，按注释改两处：

- `<你的 python 路径>\python.exe`
- `<桌宠目录>\bridge\server.py`
- `prefix:` 下面粘人设文本（缩进保持一致）

### 3. 重启 DSH

**完全退出**（包括托盘图标），再打开。

### 4. 新建会话，选预设

在会话/新建会话的位置选「大肥鱼（桌宠）」。

### 常见错误

| 现象 | 原因 |
|---|---|
| 预设列表里没有「大肥鱼」 | `- insert:` 写错层级（新条目必须包在 `- insert:` 里） |
| DSH 起不来 | YAML 语法错 → `copy cordis.patch.yml.bak cordis.patch.yml` 回滚 |
| 预设选了但没人设 | 会话没新建 |
| 工具没挂上 | `args` 路径错，或 python 没装 `mcp` 包 |

**验证 YAML 没写坏：**

```powershell
python -c "import yaml;print(len(yaml.safe_load(open(r'C:\Users\<你>\.dsh\profiles\desktop\cordis.patch.yml',encoding='utf-8'))))"
```

能打印数字 = 语法 OK。

---

## 选模型

DSH 里每个会话可以单独选模型。三种常见选择：

| 模型 | 配置 | 特点 |
|---|---|---|
| **云端 flash** | DSH 自带 `deepseek-flash` | 快、稳、工具调用可靠 |
| **Ollama 本地** | `base_url: http://127.0.0.1:11434/v1` | 免费，但工具调用看模型 |
| **KVMem** | `base_url: http://127.0.0.1:18200/v1` | 带 KV 缓存，长对话方便 |

**在 `cordis.patch.yml` 里定义提供商：**

```yaml
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
```

**默认模型：**

```yaml
- id: agent-default-model
  config:
    provider: local
    model: qwen2.5:7b
```

> ⚠️ 本地模型工具调用不一定稳。不稳时的兜底：`dsh_watch.py` 会用代码直接执行"给X发消息"这类明确指令。

---

## 让她念出 DSH 的回复

DSH 的回复默认只是文字。要变成她的语音，跑监听器：

```powershell
cd <桌宠目录>
.venv\Scripts\python.exe bridge\dsh_watch.py --dir D:\project\MP\pet_workspace
```

它做的事：

1. 每 0.3 秒看一次该工作区最新会话的 JSON
2. 新回复一出现就切句 → 调 `/api/say` → 她说出来
3. 明确的指令（发消息/确认/提醒）由代码直接执行，不信模型的嘴
4. 她说"已发送"但工具没调用 → 替换成"其实没发出去"

**启动脚本已经包含这一步**（`启动桌宠客户端.cmd` 第 4 步）。

---

## 排查

**她不说话**

```powershell
# 监听器活着吗（0 = 死了）
Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*dsh_watch.py*' }
# 最近念了什么
Get-Content <桌宠目录>\logs\watch.out -Tail 20
```

**她胡说"已经发了"**

```powershell
Get-Content <桌宠目录>\logs\tool_calls.jsonl -Tail 5
```

没有对应记录 = 模型编的。`dsh_watch.py` 会拦截并纠正。

**消息发不出去**

```powershell
# QQ 桥在吗
Get-NetTCPConnection -LocalPort 3000 -State Listen
```

不在 → 启动 SnowLuma 并登录 QQ。

---

## 完整示例：从零到"在 DSH 里发消息"

```
1. 启动：双击 启动桌宠客户端.cmd（拉起 SnowLuma/后端/调度/监听/客户端）
2. DSH 打开工作区 D:\project\MP\pet_workspace，新建会话
3. 说："给 feven 发消息说明天见"
   → 她在 DSH 里回："准备发给 feven（1234567890）：明天见，确认吗？"
   → 同时她念出来
4. 说："确认"
   → QQ 真的发出
5. 说："1小时后提醒我喝水"
   → 到点 QQ 收到 + 她主动开口
```
