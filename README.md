# ATRI QQ 聊天机器人

ATRI 是一个本地运行的 QQ 聊天机器人，基于 Flask + OneBot HTTP API + 多模型 LLM（Gemini / DeepSeek fallback 链）。

## 功能概览

**聊天**：自然对话，遇到实时/冷门/不确定的内容会自动联网搜索后回答。

**命令**：

| 命令 | 说明 |
|---|---|
| `/search <关键词>` | 网页搜索（Tavily + DDGS fallback） |
| `/url <网址>` | 读取网页内容并总结 |
| `/video <链接>` | 理解视频（B站标题/字幕/页面文字） |
| `/buser` `/bfuser` | B站用户搜索 |
| `/bvideo` `/bfvideo` | B站视频搜索 |
| `/weather <城市>` | 天气查询（今天/明天/后天/大后天） |
| `/remember <内容>` | 个人记忆 |
| `/globalremember <内容>` | 全局记忆（管理员） |
| `/reset` | 清空当前会话上下文 |
| `/image <描述>` | ComfyUI 本地生图（需配置 IMAGE_ENABLE=true，管理员） |
| `/pic <关键词> [数量]` | 搜索图片并发送（需配置 IMAGE_SEARCH_ENABLE=true） |

**图片发送**：`/pic` 和 `/image` 共享统一的图片发送能力，优先 `file:///`，失败自动 fallback `base64://`。

**会话并发**：同一用户消息按顺序处理，不同用户并行处理，互不堵塞。

## 快速开始

```powershell
# 安装依赖
pip install -r requirements.txt

# 配置
copy .env.example .env    # 编辑 .env，至少填入 GEMINI_API_KEY 或 DEEPSEEK_API_KEY

# 启动
python run_bot.py
# 或双击 启动ATRI.bat
```

## 配置

`.env` 关键项：

```env
GEMINI_API_KEY=          # 推荐，免费获取 https://aistudio.google.com/apikey
DEEPSEEK_API_KEY=        # 备选
TAVILY_API_KEY=          # 搜索用 https://tavily.com
ADMIN_QQ_IDS=            # 你的QQ号
ONEBOT_API_URL=http://127.0.0.1:3000
```

详见 `.env.example`。

## OneBot

ATRI 监听 `http://127.0.0.1:5000/`，向 OneBot `http://127.0.0.1:3000` 发消息。

在 NapCat / Lagrange 中将 HTTP 事件上报设为 `http://127.0.0.1:5000/`。

## 桌面管理器进程控制

- “停止 Bot”会先请求正常退出，超时后强制结束 Bot 核心进程。
- “重启 Bot”只重启 Bot 核心，不会重启 NapCat 或改变 QQ 登录状态。
- “退出 QQ 并停止 NapCat”用于切换账号：先调用 NapCat `/bot_exit`，再停止管理器内部启动的 NapCat；外部实例不会被强制结束。

## 模型 Fallback

默认链路：Gemini 3.1 Flash-Lite → Gemma 4 26B → DeepSeek V4 Flash → DeepSeek V4 Pro

一个挂了自动切下一个。想只用 DeepSeek 可设 `LLM_PRIMARY_PROVIDER=deepseek`。

## 项目结构

```text
run_bot.py             启动入口
src/main.py            Flask 回调、消息分发
src/router.py          命令 vs 聊天路由
src/messaging.py       消息去重、会话级队列
src/config.py          .env 配置
src/chat/              聊天生成、prompt、记忆
src/commands/          命令实现
src/services/          LLM、OneBot、搜索、生图等
src/utils/             JSON 存储
启动ATRI.bat           Windows 一键启动
```

## 群聊

默认需要 `@ATRI` 才响应。`.env` 设 `REQUIRE_GROUP_AT=false` 可关闭。

## 行为边界

- 普通聊天只暴露 `search_web` / `fetch_url` / `understand_video_url` / B站搜索等受控工具
- 天气、图片生成、图片搜索必须通过 `/` 命令触发
- Pixiv / R18 / lolicon 自动抓图已移除
- 本地数据（聊天记录、记忆、图片缓存）保存在 `atri_data/`，已 gitignore
