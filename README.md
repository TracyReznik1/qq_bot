# ATRI QQ 聊天机器人

这是一个基于 Flask + OneBot HTTP API + DeepSeek 的 QQ 聊天机器人。

## 功能

- 私聊和群聊对话
- 群聊默认需要 @ ATRI 才响应
- 普通聊天始终只给模型 `search_web` 这一个工具；闲聊可直接回答，遇到不懂的新梗、黑话、缩写、圈内 ID 等必须先搜索
- 普通聊天遇到最新信息、实时信息、冷门知识、专有名词、圈内昵称或梗时可以联网搜索；搜不到时会按 ATRI 的性格带着不确定性继续回答
- `/search` 搜索成功时会结合模型整理回答；搜索失败时会按 ATRI 的性格说明不知道或无法确认
- `/weather` 命令查询今天、明天、后天天气；普通聊天不会自动查天气
- `/reset` 只清空当前会话上下文
- `/remember` 保存跨私聊和群聊生效的个人基础信息
- `/globalremember` 保存对所有用户生效的全局记忆，仅管理员可写
- DeepSeek、OneBot、代理、端口都从 `.env` 配置

## 安装

```powershell
python -m pip install -r requirements.txt
```

## 配置

复制 `.env.example` 的内容到 `.env`，至少确认这些值：

```env
DEEPSEEK_API_KEY=sk-your-key-here
ONEBOT_API_URL=http://127.0.0.1:3000
BOT_HOST=127.0.0.1
CALLBACK_SECRET=
PROXY_URL=
ADMIN_QQ_IDS=123456,234567
```

如果你需要代理，再把 `PROXY_URL` 改成你的代理地址，例如：

```env
PROXY_URL=http://127.0.0.1:7890
```

OneBot 端需要把 HTTP 事件上报地址设置为：

```text
http://127.0.0.1:5000/
```

默认只监听本机 `127.0.0.1`。如果 OneBot 不在同一台机器上，需要把 `BOT_HOST` 改成可访问地址，并建议配置 `CALLBACK_SECRET`；配置后，OneBot 回调请求需要带 `Authorization: Bearer <CALLBACK_SECRET>` 或 `X-ATRI-Callback-Secret: <CALLBACK_SECRET>`。

## 启动

```powershell
python run_bot.py
```

`run_bot.py` 是兼容入口，实际应用入口在 `src/main.py`。

浏览器打开下面地址可以检查机器人服务是否启动：

```text
http://127.0.0.1:5000/health
```

## 用法示例

```text
你好
kskbl 是什么意思
/search DeepSeek 最新消息
/weather 北京
/remember 我喜欢简洁回答
/globalremember 所有人都知道的设定
/reset
/help
```

`ADMIN_QQ_IDS` 用英文逗号分隔。没有配置管理员时，`/globalremember` 默认禁止写入。

## 文件说明

- `run_bot.py`：兼容启动入口
- `src/main.py`：机器人主程序和 Flask 回调
- `src/router.py`：区分 `/` 命令和默认聊天
- `src/chat/`：普通聊天、提示词、记忆、聊天可用的 `search_web`
- `src/commands/`：命令功能，例如 `/weather`
- `src/services/`：DeepSeek 和搜索服务客户端
- `test_deepseek.py`：DeepSeek 连通性测试
- `.env.example`：配置模板
- `atri_data/memories`：保存当前会话记忆、个人基础信息和全局记忆
