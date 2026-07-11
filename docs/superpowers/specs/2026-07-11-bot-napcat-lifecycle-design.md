# Bot 与 NapCat 生命周期修复设计

## 背景

ATRI QQBot Manager 当前存在两组互相关联的问题：

- “停止 Bot”只调用一次 `QProcess.terminate()`。Windows 下无窗口的 Python/Flask 子进程可能不会响应，因此 Bot 仍在运行。
- “重启 Bot”错误地停止 NapCat 并重新打开 QQ 登录流程，而且没有重新启动 Bot 核心。
- NapCat 可能恢复已保存的 QQ 会话；当前登录流程检测到 OneBot 在线时会直接报告登录成功，因此用户没有扫码也可能看到自动登录。
- 现有 NapCat 停止按钮只终止管理器持有的包装进程，不负责退出 QQ，也没有可靠的进程树停止兜底。

用户确认的目标是：

1. Bot 的启动、停止和重启只管理 Flask Bot 核心，不影响 NapCat 或 QQ 会话。
2. 新增明确的“退出 QQ 并停止 NapCat”操作，主要用于切换 QQ 账号。
3. 退出操作优先调用 NapCat 官方 OneBot `POST /bot_exit` 接口，再停止管理器内部启动的 NapCat 进程树。
4. 不删除 NapCat 登录数据或配置文件，不恢复图片、Pixiv、R18 等无关能力。

官方接口参考：<https://napcat.apifox.cn/283136399e0>

## 方案选择

采用“OneBot 退出接口 + 受控进程树停止”方案。

未采用的方案：

- 直接删除 NapCat 登录数据：可能误删配置或其他账号数据，风险不可接受。
- 模拟 NapCat WebUI 操作：依赖非稳定的 WebUI 内部行为，版本兼容性弱。
- 按进程名称全局结束 QQ/NapCat：可能终止不属于 ATRI 管理器的进程，越出管理范围。

## 组件职责

### `BotProcessService`

只负责 Bot 核心进程：

- `start()` 启动 `launcher.py --core` 或打包程序的 `--core` 模式。
- `request_stop()` 先请求优雅终止；超时后仅强制结束该服务持有的 Bot 子进程。
- `restart()` 记录重启意图，等待旧进程进入 `NotRunning` 后再调用 `start()`。
- 停止和重启均异步执行，不使用会阻塞 GUI 线程的 `waitForFinished()`。

Bot 生命周期不得调用 `NapCatService`、`QQLoginService` 或打开二维码对话框。

### `NapCatService`

只负责由管理器启动的 NapCat 进程：

- 保留现有启动、日志解析和状态跟踪。
- 增加可靠的内部停止流程和 `STOPPING` 状态。
- Windows 下只对当前 `QProcess.processId()` 使用受控的进程树终止，覆盖批处理包装进程及其子进程。
- 非 Windows 环境使用 `terminate()`，超时后 `kill()`。
- 当 NapCat 是外部启动时，不按进程名称搜索或强杀。

### `QQLoginService`

负责 QQ 登录会话的进入和退出：

- 登录流程保持现有二维码获取能力。
- 新增“退出 QQ 并停止 NapCat”编排方法。
- 使用现有异步 HTTP worker 模式向 `${ONEBOT_API_URL}/bot_exit` 发送 `POST {}`。
- 如果配置了 `ONEBOT_ACCESS_TOKEN`，按现有 OneBot 约定发送 `Authorization: Bearer <token>`。
- 收到成功响应后请求 `NapCatService` 停止内部进程树。
- 请求失败或 OneBot 已离线时仍尝试停止内部 NapCat，但必须报告“QQ 退出状态未确认”。
- 停止登录轮询，并忽略取消后到达的旧异步响应，避免对话框重新显示二维码或错误状态。

## UI 行为

Dashboard 增加“退出 QQ 并停止 NapCat”按钮。

NapCat 页面现有 `Stop NapCat (Internal)` 按钮改为相同的中文名称和相同行为，避免两个入口语义不一致。

点击任一入口时：

1. 显示确认框，明确说明当前 QQ 会退出，Bot 将暂时无法收发消息。
2. 用户取消时不发送请求，也不停止任何进程。
3. 用户确认后禁用重复操作，显示“正在退出 QQ 并停止 NapCat”。
4. 完成后显示以下结果之一：
   - QQ 已退出，内部 NapCat 已停止。
   - QQ 已退出；NapCat 是外部实例，管理器未强制停止它。
   - 内部 NapCat 已停止，但 QQ 退出状态未确认。
   - QQ 退出失败且没有可停止的内部 NapCat，保留明确错误信息。
5. 用户随后点击“QQ 扫码登录”时，按现有配置启动 NapCat 并获取新的二维码。

“重启 Bot”按钮改为调用 `BotProcessService.restart()`，不再显示二维码、不再停止 NapCat。

## 数据流

### 停止 Bot

```text
停止 Bot
→ BotProcessService.request_stop()
→ terminate()
→ 超时后仍为 Running/Starting：kill()
→ finished / NotRunning
→ UI 显示 Stopped
```

### 重启 Bot

```text
重启 Bot
→ BotProcessService.restart()
→ 标记 restart pending
→ 停止旧 Bot
→ finished / NotRunning
→ 清除 pending
→ start()
```

### 切换 QQ 账号

```text
退出 QQ 并停止 NapCat
→ 用户确认
→ 停止登录轮询
→ POST /bot_exit
→ 记录退出成功或失败
→ 停止管理器内部启动的 NapCat 进程树（如果存在）
→ 汇总结果并恢复按钮
→ 用户点击 QQ 扫码登录
```

## 错误处理与安全边界

- `/bot_exit` 只有在 HTTP 成功且业务响应 `status == "ok"`、`retcode == 0` 时才算退出成功。
- 请求设置有限超时；网络错误、非 JSON、HTTP 错误或业务错误均不得伪装成成功。
- 日志和 UI 不输出 OneBot token、WebUI token、二维码 URL 或其他凭据。
- 退出失败不阻止用户停止内部 NapCat，但结果必须说明登录状态未确认。
- 不对外部进程执行 `taskkill`，不按进程名称查找，不删除会话文件。
- 重复点击不会创建并发退出或停止任务。
- 关闭二维码对话框后，过期的异步回调不得重新更新登录状态。

## 测试设计

新增或修改本地单元测试，覆盖：

- Bot 停止先调用 `terminate()`，超时且仍运行时调用 `kill()`。
- Bot 在超时前结束时不会调用 `kill()`。
- Bot 重启必须等待旧进程结束后再启动。
- Dashboard 的“重启 Bot”不调用 NapCat 或 QQ 登录服务。
- `/bot_exit` 请求使用正确 URL、空 JSON body 和可选 Bearer token。
- 只有 `status: ok` 且 `retcode: 0` 被判定为成功。
- 退出成功后停止内部 NapCat。
- 退出失败后仍停止内部 NapCat，并报告未确认状态。
- 外部 NapCat 只退出 QQ，不执行进程树强杀。
- 用户取消确认时没有副作用。
- 登录流程取消后忽略迟到的二维码和错误回调。

验证命令：

```powershell
python -m unittest test_desktop_app test_napcat_qr_login -v
python -m unittest
python -m py_compile run_bot.py test_deepseek.py
git status --short --ignored
```

## 非目标

- 不自动清理或删除 NapCat/QQ 登录数据。
- 不管理非 ATRI 启动的外部进程树。
- 不改变 OneBot 地址、NapCat 路径或默认 preset。
- 不修改 Bot 聊天、命令、搜索、记忆或图片行为。
- 不引入新的第三方依赖。
