# ARCHITECTURE.md

> 本文档描述当前项目的目标结构、模块边界和已知运行方式。  
> 若本文档与源码不一致，以源码为准，并应优先修正文档。不要为了迎合文档而改动代码行为。

---

## 1. 项目目标

ATRI 是一个本地运行的 QQ 聊天机器人。

核心链路：

```text
QQ
  → OneBot 兼容客户端（如 NapCat）
  → ATRI Flask 服务
  → DeepSeek / 搜索 / B站 / 天气等外部服务
  → OneBot HTTP API
  → QQ
```

设计目标：

- 默认是自然聊天机器人，不是复杂 Agent
- 普通聊天只允许少量受控工具
- 天气、B站搜索、记忆等能力优先通过显式 `/command` 进入
- 项目保持小、可读、可测试
- 不把已移除的图片、Pixiv、R18、自动发图逻辑混回主流程

---

## 2. 运行拓扑

```text
QQ
  |
  v
NapCat / OneBot client
  |
  | POST http://127.0.0.1:5000/
  v
ATRI Flask app
  |
  | Gemini / DeepSeek / Tavily / ddgs / Bilibili API / Open-Meteo / wttr.in / ComfyUI
  v
External services
  |
  v
ATRI reply
  |
  | POST http://127.0.0.1:3000/send_private_msg
  | POST http://127.0.0.1:3000/send_group_msg
  v
NapCat / OneBot client
  |
  v
QQ
```

默认端口：

- ATRI Flask: `127.0.0.1:5000`
- OneBot HTTP API: `127.0.0.1:3000`

---

## 3. 项目目录

```text
run_bot.py                      兼容启动入口
启动ATRI.bat                     Windows 一键启动脚本
requirements.txt                 Python 依赖
.env.example                     配置模板，不能包含真实 key
.env                             本地配置，不能提交
.gitignore
README.md                        用户文档
ARCHITECTURE.md                  架构文档
AGENTS.md                        AI agent 工作规则
PROJECT_STATE.md                 项目状态
TASKS.md                         当前任务拆分

src/
  __init__.py
  main.py                        Flask app、OneBot 回调、消息分发、回复发送
  router.py                      只区分 / 命令和普通聊天
  messaging.py                   消息去重、会话队列、按会话顺序处理
  config.py                      .env 配置读取
  util.py                        共享 HTTP 辅助，如代理 fallback

  chat/
    chat_service.py              LLM 对话构造、工具定义、工具调用循环、聊天历史
    prompt.py                    系统提示词和非可信上下文构建
    memory.py                    会话记忆、个人基础信息、全局记忆、旧记忆迁移

  commands/
    __init__.py                  命令注册表和命令分发
    search.py                    /search
    url.py                       /url
    video.py                     /video
    bsearch.py                   /buser、/bfuser、/bvideo、/bfvideo
    weather.py                   /weather
    help.py                      /help
    reset.py                     /reset
    image.py                     /image 本地 ComfyUI 图片生成

  services/
    llm_types.py                 共享类型：ChatResponse、LLMModelSpec
    llm_client.py                LLM fallback 路由与模型链
    gemini_client.py             Gemini OpenAI 兼容 API 客户端
    deepseek_client.py           DeepSeek OpenAI 兼容 API 客户端
    onebot_client.py             OneBot HTTP API 客户端
    search_service.py            Tavily + ddgs 网页搜索
    url_fetch_service.py         URL 安全直读
    video_service.py             B站视频/通用视频页理解
    bilibili_search.py           B站用户/视频搜索
    comfyui_client.py            ComfyUI REST API 客户端 + prompt sanitize
    image_prompt_service.py      LLM 提示词转换 + 内容安全过滤
    image_generation_service.py  工作流 patcher + LoRA 控制 + 生成编排器

  utils/
    storage.py                   JSON 文件读写、safe_id

test_*.py                        单元测试
docs/                            设计文档和后续说明
atri_data/                       本地运行数据，不提交
```

说明：

- `.env`、`atri_data/`、`.codex_tmp/`、`gemini废案/` 都应视为本地文件。
- `REFACTOR_REQUIREMENTS.md` 如果仍存在，应视为历史参考，不应覆盖当前架构和任务计划。

---

## 4. 核心消息生命周期

```text
OneBot POST /
  → 校验 CALLBACK_SECRET（如果配置）
  → 只处理 post_type == "message"
  → message_id 去重
  → 根据 session_key 入队
  → 同一 session 串行处理，不同 session 可并行
  → process_message()
    → 群聊 @ 检查
    → route_message()
      → command: handle_command()
      → chat: generate_reply()
    → send_reply()
```

会话 key：

- 私聊：`private:<uid>`
- 群聊：`group:<group_id>:<uid>`

路由原则：

- `src/router.py` 只做第一层硬边界：
  - 不以 `/` 开头 → 普通聊天
  - 以 `/` 开头 → 命令
- `router.py` 不应该知道具体命令有哪些，也不应该放业务逻辑。

---

## 5. 普通聊天边界

普通聊天由 LLM（默认 Gemini，DeepSeek 等作为 fallback）生成回复，允许少量受控工具。

允许的普通聊天工具应保持窄边界：

- `search_web(query)`
- `fetch_url(url)`：仅在用户提供 URL 时暴露或重路由
- `understand_video_url(url)`：仅在用户提供视频链接、BV 号、av 号时使用
- `bilibili_user_search(query)` / `bilibili_video_search(query)`：仅在 B站搜索语境下暴露

普通聊天禁止：

- 调用天气接口
- 发送图片、文件或 CQ 码
- 操作 QQ 管理能力
- 读写本地文件
- 执行 shell
- 写入长期记忆
- 暴露管理员命令
- 自动启用已移除的图片/Pixiv/R18 相关逻辑

---

## 6. 命令系统

命令由 `src/commands/__init__.py` 的注册表分发。

当前命令组：

```text
help/h
search/s
url/u
video/vid
buser/bu
bfuser/bfu
bsearch/bs
bfsearch/bfs
bvideo/bv
bfvideo/bfv
weather/w
remember/memo
globalremember/gremember
image/img
reset
```

命令边界：

- `/weather` 是天气入口；普通聊天不直接调用天气 API
- `/image` / `/img` — 调用本地 ComfyUI / Anima 高清增强版工作流生成图片。默认关闭（`IMAGE_ENABLE=false`），第一版建议仅管理员可用（`IMAGE_ADMIN_ONLY=true`）。LoRA 接口保留但默认关闭。普通聊天不会自动调用图片生成。
- `/remember` 写入个人基础信息
- `/globalremember` 只能由管理员写入全局记忆
- `/reset` 清空当前会话历史和当前会话记忆，不删除个人基础信息或全局记忆

---

## 7. 主要模块职责

### `run_bot.py`

兼容启动入口。应保持薄封装，不放业务逻辑。

### `src/main.py`

负责：

- Flask app
- `/` OneBot 回调
- `/health` 健康检查
- callback 鉴权
- 群聊 @ 检查
- 消息去重和入队
- 消息处理主流程
- 回复分片和发送

不应负责：

- 命令具体业务
- 搜索业务
- B站业务
- URL 解析细节
- 记忆存储细节

### `src/router.py`

只负责判断普通聊天还是命令。

不应负责：

- 具体命令判断
- 天气、搜索、记忆等业务逻辑
- 调用外部服务

### `src/messaging.py`

负责：

- message_id 去重
- session_key 构建
- 同会话串行处理
- 不同会话并行处理

### `src/config.py`

负责从 `.env` 读取配置并集中管理。

配置项必须保持向后兼容。新增配置时同步更新：

- `.env.example`
- `README.md`
- `PROJECT_STATE.md` 或 `ARCHITECTURE.md` 中相关描述

### `src/chat/chat_service.py`

负责：

- 构造 DeepSeek messages
- 管理聊天历史
- 暴露和过滤普通聊天工具
- 执行工具调用循环
- 工具 query 兜底和 URL/视频重路由
- 生成最终自然语言回复

不应负责：

- 命令注册
- OneBot 发送
- Flask 回调

### `src/chat/prompt.py`

负责：

- 系统提示词
- 非可信上下文构造
- 记忆与外部信息的优先级说明

不要随意改变系统提示词格式。改变前必须说明影响。

### `src/chat/memory.py`

负责：

- 会话记忆
- 个人基础信息
- 全局记忆
- 旧记忆迁移
- JSON 持久化

记忆优先级：

```text
当前会话记忆 > 个人基础信息 > 全局记忆
```

### `src/commands/`

每个命令应保持独立。新增功能优先新增命令，不要塞进普通聊天。

### `src/services/`

外部服务封装层：

- `llm_types.py` — 共享类型：`ChatResponse`、`LLMModelSpec`
- `llm_client.py` — LLM fallback 路由与模型链
- `gemini_client.py` — Gemini OpenAI 兼容 API 客户端
- `deepseek_client.py` — DeepSeek OpenAI 兼容 API 客户端
- `onebot_client.py` — OneBot 发送消息和 CQ 图片
- `search_service.py` — 网页搜索
- `url_fetch_service.py` — URL 安全直读
- `video_service.py` — 视频页/B站视频理解
- `bilibili_search.py` — B站搜索
- `comfyui_client.py` — ComfyUI REST API 客户端（`_queue_prompt` / `_wait_for_outputs` / `_download_image` 作为类方法；module-level `_sanitize` + `_safe_error_preview`）
- `image_prompt_service.py` — LLM 提示词转换 + 内容安全过滤
- `image_generation_service.py` — 工作流加载/patch + LoRA 控制 + 单任务锁 + 生成编排器

### `src/utils/storage.py`

负责通用 JSON 读写和安全文件名转换。

---

## 8. 数据持久化

默认本地数据目录：

```text
atri_data/
  history/
  memories/
  legacy_memories/
  generated_images/       /image 命令生成的图片
```

这些目录不能提交。

聊天历史：

- 受 `PERSIST_HISTORY` 控制
- 每个会话按 `HISTORY_TURNS` 裁剪

记忆：

- JSON 格式
- 每个记忆文件最多 `MEMORY_LIMIT` 条
- `/reset` 不删除个人基础信息和全局记忆

---

## 9. 外部服务

已使用或预期使用的外部服务：

- Gemini API (Google AI Studio, OpenAI 兼容端点)
- DeepSeek API
- OneBot HTTP API
- Tavily API（可选）
- ddgs / DuckDuckGo fallback
- Bilibili 公开 API 和 HTML fallback
- Open-Meteo
- wttr.in
- ComfyUI REST API（默认 `http://127.0.0.1:8188`），用于 `/image` 命令

代理：

- 统一通过 `PROXY_URL` 配置
- HTTP 请求辅助函数应优先使用统一代理逻辑，不要在各模块各写一套

---

## 10. 安全边界

必须保持：

- `.env` 不提交
- callback secret 校验不被绕过
- URL 直读拒绝内网、本机、保留地址、链路本地、多播地址
- 重定向后重新校验目标
- 只读取文本类内容
- 限制 URL 读取大小
- 不向聊天模型暴露本地文件、QQ 管理、天气、图片等工具
- 不让模型自动发送 CQ 图片码

---

## 11. 已知限制

这些是当前限制，不要让模型假装已经实现：

- `/image` 命令需要 `IMAGE_ENABLE=true` 并启动 ComfyUI Desktop。NapCat file URI 发图兼容性待验证，base64 fallback 待实现。workflow 自动节点识别已修复（BOM + API `"prompt"` wrapper 解包装），推荐在 `.env` 中配置节点 ID 作为兜底
- 直接 `.mp4`、`.m3u8` 等媒体流没有完整下载、ASR、抽帧管线
- 视频理解主要依赖 B站元数据、简介、字幕或普通网页文字
- 无 systemd/supervisor/NSSM 等进程守护配置
- 日志轮转待补充
- 群组 allowlist/blocklist 待补充
- `test_run_bot_search.py` 过大，待拆分
- `.codex_tmp/` 和 `gemini废案/` 是否删除需要先人工确认

---

## 12. 验证命令

基础编译检查：

```powershell
python -m py_compile run_bot.py test_deepseek.py
```

完整测试：

```powershell
python -m unittest
```

测试发现：

```powershell
python -m unittest discover -v
```

路由烟测：

```powershell
python -c "from src.router import route_message; print(route_message('/weather 北京')); print(route_message('北京天气'))"
```

不应恢复的图片功能扫描：

```powershell
rg -n "ddy|image_search|Pixiv|R18|CQ:image|lolicon|搜图|发图" . -g !.venv -g !__pycache__ -g !.git -g !.codex_tmp -g !atri_data
```

本地敏感文件检查：

```powershell
git status --short --ignored
git check-ignore -v .env
git ls-files .env
```
