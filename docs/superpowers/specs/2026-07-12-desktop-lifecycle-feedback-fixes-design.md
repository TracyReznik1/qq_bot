# Desktop Login and Process Feedback Fixes Design

## Goal

Fix four user-visible regressions in ATRI QQBot Manager and publish the result as `v0.1.13`:

1. QR login completes on the phone but the manager does not report success.
2. “退出 QQ 并停止 NapCat” reports that QQ logout is unconfirmed even though NapCat stops.
3. “重启 Bot” provides no clear completion feedback.
4. “停止 Bot” always waits for the two-second fallback on Windows.

Successful QR login and successful Bot restart will both update the status label and show an explicit success dialog.

## Root Causes

### Lost WebUI discovery signal

`NapCatService` can emit the WebUI URL and token before the QR dialog starts polling. `QQLoginService._handle_webui_detected()` currently accepts the signal only while both `_is_polling` and `_waiting_for_webui` are true, so an early signal is discarded permanently. QR URL fallback is cached, but WebUI connection data is not. The dialog can display a QR code yet never gain the authenticated WebUI channel needed to observe `isLogin=true`.

### `/bot_exit` closes its own response channel

The installed NapCat implementation maps `/bot_exit` to `process.exit(0)`. The OneBot process can exit before its HTTP response reaches the manager, so a connection error is expected and cannot be used as proof that logout failed.

The same installed version exposes authenticated WebUI endpoints:

```text
POST /QQLogin/GetQuickLoginQQ
POST /QQLogin/SetQuickLoginQQ  {"uin": ""}
```

Clearing the quick-login account before stopping NapCat is the reliable condition for switching accounts on the next start.

### Missing restart operation state

`BotProcessService.restart()` sequences stop and start but exposes only generic QProcess states. The UI cannot distinguish a user-requested restart from an ordinary start, so it has no reliable completion event for a dialog.

### Ineffective Windows graceful stop

The Bot core is a headless Python/Flask process. On Windows, `QProcess.terminate()` does not stop this process, so every stop waits until the two-second timer invokes `kill()`.

## Design

### WebUI discovery and login completion

`QQLoginService` will cache the latest WebUI URL and token whenever `webui_detected` fires, regardless of polling state.

When `start_login_flow()` runs:

1. Restore the cached WebUI connection with `NapCatWebUIService.setup()` if necessary.
2. Authenticate when no valid WebUI credential is available.
3. Continue status polling.
4. When `CheckLoginStatus` returns `isLogin=true`, stop polling, update status to `QQ 登录状态: 已登录`, emit `login_success`, close the QR dialog, and display `QQ 登录成功。` once.

Late responses from a cancelled login flow remain ignored.

### Account switch and NapCat stop

The account-switch sequence becomes:

```text
user confirmation
→ ensure WebUI authentication
→ POST /QQLogin/SetQuickLoginQQ {"uin": ""}
→ send /bot_exit as a best-effort exit request
→ stop the internally managed NapCat process tree
→ report the combined result
```

`/bot_exit` response loss is not treated as failure. Success is based on:

```text
quick-login account cleared AND internal NapCat stopped
```

If quick-login clearing fails, internal NapCat still stops, but the warning explicitly says the previous account may auto-login again. External NapCat process trees are never killed.

The WebUI service will expose an asynchronous `clear_quick_login()` operation. It will reuse existing authentication and retry once after HTTP 401/403.

### Immediate Windows Bot stop

`BotProcessService.request_stop()` will:

- call `kill()` immediately on Windows for the owned headless Bot process;
- keep `terminate()` plus the two-second `kill()` fallback on non-Windows systems.

The operation remains asynchronous; `finished` and `stateChanged` drive final UI state.

### Bot restart feedback

`BotProcessService` will add explicit restart signals:

```python
restart_started = Signal()
restart_finished = Signal(bool, str)
```

`restart_started` is emitted when a restart request is accepted. `restart_finished(True, "Bot 重启成功。")` is emitted only when the replacement process reaches `QProcess.Running`. A start error during restart emits `restart_finished(False, <message>)`.

Dashboard behavior:

- immediately display `Bot Status: Restarting` and disable repeated restart clicks;
- on success, display `Bot Status: Running` and show an information dialog;
- on failure, display `Bot Status: Stopped` and show a warning dialog.

## Error Handling

- Do not log WebUI tokens, OneBot tokens, credentials, or QR URLs.
- WebUI discovery data is kept only in memory.
- WebUI authentication or quick-login clearing failures produce actionable messages.
- `/bot_exit` connection errors are logged as an expected best-effort outcome, not shown as logout failure.
- Account-switch completion is emitted once even if late HTTP callbacks arrive.
- Repeated stop, restart, login, and account-switch requests remain idempotent while an operation is active.

## Test Strategy

Add failing tests before implementation for:

- WebUI discovery before `start_login_flow()` is cached and later authenticated.
- `isLogin=true` emits one login-success result and one success dialog.
- quick-login clearing calls `/QQLogin/SetQuickLoginQQ` with an empty UIN.
- quick-login clearing retries authentication after 401/403.
- `/bot_exit` connection loss does not turn a confirmed account switch into a failure.
- quick-login clearing failure produces an auto-login warning after NapCat stops.
- Windows Bot stop calls `kill()` immediately and does not schedule the two-second timer.
- non-Windows Bot stop keeps graceful termination and fallback.
- restart success is emitted only when the replacement process reaches Running.
- restart failure restores controls and shows an error.

Run the complete local suite, compilation checks, offscreen GUI smoke test, and packaged executable smoke test before publishing `v0.1.13` into `release/`.

## Scope Boundaries

- No chat, command, search, memory, weather, image, or OneBot message behavior changes.
- No deletion of QQ/NapCat data or configuration files.
- No global process-name killing.
- No new third-party dependency.
- Preserve unrelated user-owned working-tree changes.
