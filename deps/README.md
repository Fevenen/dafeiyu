# 依赖怎么来（为什么不直接打包）

本仓库**只提供代码**。运行需要的"底座"体积太大、许可也不允许随包分发，所以改成
**一条命令自动拉取**。

## 为什么不能打包

| 组件 | 体积 | 能不能随包分发 |
|---|---|---|
| Open-LLM-VTuber 本体 + Python 依赖 | ~1 GB | ✅ MIT，但体积大 |
| Electron 客户端（pet-web） | ~1.2 GB | ✅ 可发，但没必要（浏览器也能用） |
| 语音模型（布洛妮娅音色） | ~300 MB | ❌ 游戏角色音色，不可再分发 |
| Live2D 模型（大肥鱼） | ~18 MB | ❌ 同人作品，作者仅授权个人使用 |
| SnowLuma | ~130 MB | ❌ 专有 EULA，禁止再分发 |
| 本地大模型（KVMem / Qwen） | **43 GB** | ❌ 太大，且要自己下载 |

**合计约 50 GB —— 任何代码托管平台都放不下，法律上也放不了。**

## 自动安装（推荐）

```powershell
# 在仓库根目录
powershell -ExecutionPolicy Bypass -File .\deps\bootstrap.ps1
```

它会做：

1. 检查 Git / Python 3.10+ / uv（缺了提示 winget 命令）
2. `git clone` Open-LLM-VTuber 到 `..\pet`
3. `uv sync` 装 Python 依赖
4. **自动下载** SnowLuma 最新官方 Release，解压到 `..\v0\SnowLuma`（走 GitHub API，从官方源下载）
5. 把 `bridge\` 复制进 `pet\`
6. 生成 `bridge\config.json` + 工作区 `AGENTS.md` + 启动脚本
7. 打印登录 QQ、配模型、启动的步骤

**它不会做的事：** 下载 LLM 模型文件（用你自己的本地模型，见主 README「接你自己的本地模型」）。

## 不装 Electron 也能用

**Open-LLM-VTuber 自带网页版**：启动后端后打开

```
http://127.0.0.1:12393
```

Live2D、聊天面板、语音都在网页里。**Electron 客户端只是把它包成桌面窗口**，测试阶段完全可以不用。

## 免费替代资产（不涉及侵权）

| 我们用的 | 你可以换成 |
|---|---|
| 布洛妮娅音色 | **edge-tts**（`edge-tts`，OLV 配置里选 `edge_tts`，音色如 `zh-CN-XiaoxiaoNeural`） |
| 大肥鱼 Live2D | **OLV 自带的默认模型**（仓库内 `live2d-models/`） |
| 本地大模型 | DeepSeek / OpenAI 兼容 API，或 Ollama（`qwen2.5:7b` 等） |

配置示例（`conf.yaml`）：

```yaml
tts_config:
  tts_model: edge_tts
  edge_tts:
    voice: zh-CN-XiaoxiaoNeural

llm_config:
  llm_provider: openai_compatible_llm
  openai_compatible_llm:
    base_url: https://api.deepseek.com/v1
    llm_api_key: <你的 key>
    model: deepseek-chat
```

## 想用和作者一样的声音/形象怎么办

**自己训练/委托制作**，或者找作者授权。仓库里不提供，也不要从别人的包里拷贝 —— 那是侵权。
