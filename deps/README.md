# 外部依赖

bootstrap.ps1 固定下载 Open-LLM-VTuber v1.2.1 及其前端子模块，安装其 Python 依赖和 bridge 依赖，再调用 install.ps1 安装覆盖文件。

SnowLuma/其他兼容 OneBot v11 HTTP 服务需用户单独安装并登录 QQ。模型服务、TTS 音色、Live2D 资源由用户配置，不会从作者的本机复制，也不自动从旧 Release 附件下载。

安装后配置 pet/conf.yaml 与 pet/bridge/config.json。完整步骤与版本约束见仓库 README。
