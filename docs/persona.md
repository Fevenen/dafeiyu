# 人格配置

安装器会在桌宠目录旁创建 pet_workspace/AGENTS.md，已有文件不会覆盖。编辑后在 DSH 新建会话加载。

config/AGENTS.example.md 是可公开的人格示例；bridge/dsh_persona.md 是同一模板。工具协议要求真实调用、原样传递确认词，并区分待确认、成功、失败与未知。人格语气不会改变这些执行规则。

从 0.1 升级时，可保留自己的角色设定，将示例中的“工具协议 0.2”替换旧工具规则。旧 confirm_send() 示例应改为 confirm_send(confirmation="确认")，或统一调用 route_command。
