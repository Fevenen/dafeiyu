# 语音（TTS）

> 桌宠用什么声音说话、怎么换、出问题怎么修。

---

## 两种主流选择

| 方案 | 自然度 | 需要联网 | 需要 ffmpeg | 显存 | 成本 |
|---|---|---|---|---|---|
| **edge-tts**（微软神经音色） | ★★★★★ | ✅ | ✅ | 0 | 免费 |
| **sherpa-onnx**（本地 VITS） | ★★★ | ❌ | ❌ | 0 | 免费 |
| Azure TTS（官方 API） | ★★★★★ | ✅ | ✅ | 0 | 免费额度 |
| CosyVoice2（本地大模型） | ★★★★★ | ❌ | ❌ | 2~4 GB | 免费 |

**作者当前用的是 `edge-tts` + `zh-CN-XiaoyiNeural`（晓伊，活泼女声）。**

---

## 方案一：edge-tts（推荐）

### 依赖

```
· edge-tts 库（>= 7.3.1，旧版本会被微软接口 403）
· ffmpeg（edge 输出 mp3，桌宠要转 wav）
```

**装 ffmpeg：**

```powershell
winget install --id Gyan.FFmpeg -e
```

装完**重开终端**（或重启服务），让它进 PATH。

### 配置

`pet\conf.yaml`：

```yaml
tts_config:
  tts_model: 'edge_tts'

  edge_tts:
    voice: 'zh-CN-XiaoyiNeural'
```

### 中文音色清单

```
zh-CN-XiaoxiaoNeural        女声，温柔（默认推荐）
zh-CN-XiaoyiNeural          女声，活泼
zh-CN-YunxiNeural           男声，青年
zh-CN-YunjianNeural         男声，解说
zh-CN-YunyangNeural         男声，新闻
zh-CN-liaoning-XiaobeiNeural 东北女声
zh-CN-shaanxi-XiaoniNeural   陕西女声
```

**列全部：**

```powershell
python -c "import asyncio, edge_tts; print(asyncio.run(edge_tts.list_voices()))"
```

### 试听（不改配置）

```powershell
python -c "import asyncio, edge_tts; asyncio.run(edge_tts.Communicate('你好呀，我是大肥鱼', 'zh-CN-XiaoyiNeural').save('test.mp3'))"
```

### 验证

改完配置重启后端，日志应出现：

```
Initializing TTS: edge_tts
```

---

## 方案二：sherpa-onnx（离线）

**不需要联网、不需要 ffmpeg**，但自然度差一档。

```yaml
tts_config:
  tts_model: 'sherpa_onnx_tts'

  sherpa_onnx_tts:
    vits_model: 'models/sherpa/bronya/bronya.onnx'
    vits_lexicon: 'models/sherpa/bronya/lexicon.txt'
    vits_tokens: 'models/sherpa/bronya/tokens.txt'
    vits_dict_dir: 'models/sherpa/bronya/dict'
    tts_rule_fsts: 'models/sherpa/bronya/number.fst,models/sherpa/bronya/phone.fst,models/sherpa/bronya/date.fst'
```

模型在 Releases 的 `tts-bronya.zip` 里。

---

## 常见问题

### 报 `403 Invalid response status`

```
原因：edge-tts 版本太旧，微软改了接口
解决：uv pip install -U edge-tts
      （当前可用版本 7.3.1+）
```

### 报 `Error loading or converting generated audio`

```
原因：没有 ffmpeg / ffprobe
解决：winget install Gyan.FFmpeg -e
      装完重启后端（PATH 要带上）
```

### 报 `Couldn't find ffprobe or avprobe`

```
同上：ffmpeg 没装，或者没进 PATH
检查：ffmpeg -version
```

### 声音很慢（5 秒/句）

```
edge-tts 本身 1.5 秒左右
多出来的是 mp3→wav 转换 + 网络

· 网络差 → 换 sherpa（离线，快）
· 依然慢 → 检查 ffmpeg 是不是每次都在重新启动
```

### 声音像机器人

```
edge-tts 不会这样；出现这种情况说明用的是 sherpa
检查 conf.yaml 的 tts_model 是不是 edge_tts
```

### 换声音没生效

```
· 改完要重启后端
· 确认改的是当前生效的 conf.yaml（不是备份）
```

---

## 切换对照表

| 想做什么 | 改哪里 |
|---|---|
| 换音色 | `edge_tts.voice` |
| 换引擎 | `tts_model` |
| 调语速 | edge-tts 目前不支持直接调速（需改代码） |
| 完全离线 | 切 `sherpa_onnx_tts` |
| 更好但吃显存 | `cosyvoice2_tts`（需 GPU） |
