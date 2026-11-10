# 在 DSH 里使用桌宠

## 配置步骤

1. 运行 install.ps1，找到安装目录中的 `bridge/data/generated/cordis.patch.ready.yml`。
2. 将片段合并到用户目录下 `.dsh/profiles/desktop/cordis.patch.yml`，保留原配置备份。
3. 在 DSH 打开安装器创建的 pet_workspace，新建会话，选择“大肥鱼（桌宠）”预设。工作区 AGENTS.md 提供人格，MCP 提供工具。
4. 使用本地 KVMem 时，把对应 provider 的 baseURL 设置为 `http://127.0.0.1:18080/v1`，实际上游通过 KVMEM_UPSTREAM 配置。
5. 运行桌宠启动器，确认后端、网关与 watcher 日志正常。

不要把生成片段中的本机路径提交到 GitHub。移动目录后重新安装，生成新片段并替换宿主旧配置。

## 命令处理

网关优先处理明确命令，未识别且命中候选能力时才请求模型分类。普通聊天直接流式转发；DSH 原生工具继续保留。后续工具结果请求不重新执行之前的用户指令。

MCP 推荐调用 route_command(text=用户原文, request_id=本轮稳定ID)。直接调用 confirm_send 时必须提供 confirmation=用户本轮原始确认文字，例如“确认”；不能根据自己的判断编一个确认。

不要在每次闲聊前调用 recent_actions。它只用于查询发送状态，历史结果不能替代新请求。

## 多会话

自定义宿主应传 X-Session-ID 和 X-Request-ID，或 metadata 对应字段。没有稳定会话 ID 的 DSH 接入，使用首条用户消息指纹并检查历史连续性；遇到同开场的分支冲突会停止动作。

需要同时独立操控多个 DSH 会话时，为各会话配置独立网关实例、端口和 BRIDGE_SESSION_ID（可通过不同 PET_CONFIG 文件），或扩展宿主让它传入稳定 ID。不要把所有会话强行绑定到同一固定 ID。

MCP stdio 进程默认各自隔离。重启 MCP 后请重新准备消息再确认，不复用旧的 pending。

## 语音

watcher 每 0.3 秒读取 DSH 会话文件，根据标点或短暂稳定状态提交文字。它只负责播报，不执行发消息或提醒。

```powershell
python -m bridge.dsh_watch --dir "<你的工作区>"
python -m bridge.dsh_watch --list
python -m bridge.dsh_watch --session <会话ID> --dry
```

--dry 只打印，不连接模型、QQ 或桌宠接口，也不修改播放游标。入队失败不会推进游标；入队后的实际播放状态通过 /api/speech/status 查询。

升级后必须停止旧版监听器再启动新版；旧版仍有执行命令的逻辑，不能与新版并行运行。
