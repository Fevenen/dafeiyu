# QQ 登录与 SnowLuma 的关系

> 这一页解决最常见的困惑：**"我要怎么登录我的 QQ？"**
> 答案：**SnowLuma 不登录 QQ，它注入你已经登录的 QQ。**

---

## 一句话原理

```
官方 QQ 客户端（NTQQ）  ← 你在这里登录
        ↑ 注入（hook）
SnowLuma                ← 读到一个已登录的号，对外开 OneBot 接口
```

**SnowLuma 本身没有登录界面**，它启动后会去找"正在运行的 QQ 进程"，注入进去，
然后日志里打印：

```
[App] hook auto-load enabled: every discovered QQ process will be injected
[Hook] login detected: PID=14700 UIN=3964603738
[Hook] pipe connected: PID=14700
[OneBot.HTTP] [http-default] listening 127.0.0.1:3000/
[WebUI] listening http://127.0.0.1:5099
```

看到 `login detected` + `listening` = 成功。

---

## 完整步骤（第一次）

### 1. 装官方 QQ 并登录

- 下载 Windows 版 QQ（NTQQ）
- 登录**你自己的号**（扫码 / 密码都行）
- **登录后不要退出**，最小化即可

> 这就完成了"登录"。SnowLuma 之后会自动读到这个号。

### 2. 下载并启动 SnowLuma

- 从官方 Release 下载 Windows 包
- 解压到任意目录，例如 `D:\QQBridge\SnowLuma`
- 双击 `launcher.bat`

会弹一个黑窗口刷日志。**关掉这个窗口 = 停止服务。**

### 3. 确认三件事

```
① 日志出现 [Hook] login detected: PID=... UIN=<你的QQ号>
② 日志出现 [OneBot.HTTP] listening 127.0.0.1:3000/
③ 浏览器打开 http://127.0.0.1:5099 能看到 WebUI
```

WebUI 第一次进会要求设密码（它自己的管理密码，不是 QQ 密码）。

### 4. 拿 accessToken

WebUI → OneBot / 网络配置 → HTTP 服务器：

```
地址：127.0.0.1
端口：3000
accessToken：一串随机字符
```

也可以直接看文件：

```
SnowLuma\config\onebot_<你的QQ号>.json
```

### 5. 填进 bridge 配置

```json
// pet\bridge\config.json
{
  "onebot": {
    "url": "http://127.0.0.1:3000",
    "token": "<上面那串>"
  }
}
```

用 `bootstrap.ps1` 安装的话，它会在安装时直接问你。

### 6. 启动桌宠

```
双击 pet\启动桌宠客户端.cmd
```

---

## 每次开机的顺序

```
① 登录 QQ（官方客户端）
② 双击 启动桌宠客户端.cmd
```

**顺序不能反。** QQ 没登录就启 SnowLuma，它会等 60 秒也等不到注入。

> 启动脚本会自动拉起 SnowLuma（如果没在跑），但**不会帮你登录 QQ**。

---

## 多账号：每个号要不同端口

同一台机器登两个号时，SnowLuma 为每个号生成一份配置，**但端口默认都是 3000**，
第二个号会报：

```
ERROR [OneBot.HTTP] server error: listen EADDRINUSE:
      address already in use 127.0.0.1:3000
```

改法：第二个号的配置换端口。

```json
// config\onebot_<第二个号>.json
"httpServers": [{ "host": "127.0.0.1", "port": 3002 }],
"wsServers":  [{ "host": "127.0.0.1", "port": 3003 }]
```

对应的 bridge 配置也要改：

```json
"onebot": { "url": "http://127.0.0.1:3002", "token": "..." }
```

> 一个 bridge 实例只连一个号。要同时用两个号，就起两个 bridge（不同目录）。

---

## 排查表

| 现象 | 原因 | 解决 |
|---|---|---|
| 日志没有 `login detected` | QQ 没登录 / 版本不匹配 | 先登录 QQ；换 SnowLuma 支持的 QQ 版本 |
| 日志刷 `waiting for QQ process` | 没找到 QQ 进程 | 确认 QQ 在跑（任务管理器里有 QQ） |
| 3000 没监听 | SnowLuma 没起来 / 端口被占 | 看黑窗口报错；`netstat -ano \| findstr :3000` |
| 注入失败 / 权限报错 | 不是管理员 / 杀软拦截 | 右键"以管理员身份运行"；加杀软白名单 |
| 发消息报 502 | QQ 掉线了（hook 还在但号离线） | 重新登录 QQ |
| `EADDRINUSE` | 两个号都用 3000 | 改第二个号端口 |
| 关了 QQ 就发不出 | hook 依赖 QQ 进程 | 保持 QQ 运行 |

---

## 安全提醒

- SnowLuma 的 OneBot 接口只监听 `127.0.0.1`，**不要改成 `0.0.0.0`**
- `accessToken` 等于"操作你 QQ 的钥匙"，别提交进仓库（本项目 `.gitignore` 已挡住）
- 用协议端/注入方式登录 QQ **可能违反腾讯用户协议，有封号风险**，请自行评估
