# ATRI QQ 聊天机器人

ATRI 是一个本地运行的 QQ 聊天机器人，基于 Flask、OneBot HTTP API 和多模型 LLM 支持（默认 Gemini，DeepSeek 作为 fallback）。它的目标是保持简单：默认像聊天对象一样回复，需要查证时联网搜索，也能在你给出 URL 时直接读取网页内容；天气、B站检索、记忆等能力通过明确命令触发。

## 模型

ATRI 支持多模型 fallback。默认使用：

1. **Gemini 3.1 Flash-Lite** — Google AI Studio（推荐配置 `GEMINI_API_KEY`）
2. **Gemma 4 26B A4B** — 纯文本模型，需要工具调用时跳过
3. **DeepSeek V4 Flash** — DeepSeek API
4. **DeepSeek V4 Pro** — DeepSeek API

所有模型都走 OpenAI 兼容接口，fallback 只在调用失败时触发（不会因为"回答不好"而切换模型）。

推荐至少配置 `GEMINI_API_KEY` 和 `DEEPSEEK_API_KEY`，这样任一 provider 出问题时都能自动降级。

如果只想用 DeepSeek，在 `.env` 里写 `LLM_PROVIDER=deepseek` 或手动修改 primary 即可。

## 功能

- 支持私聊和群聊；群聊默认需要 `@ATRI` 才响应
- 普通聊天由 DeepSeek 生成回复，保留最近上下文
- 普通聊天默认只暴露 `search_web` 工具，由 DeepSeek 决定是否调用；闲聊不搜索，遇到新消息、实时信息、冷门知识、专有名词、圈内 ID、昵称、梗或不确定内容时可搜索后回答；如果模型给的搜索词过泛，或只给主题词却漏掉原因、趋势、评价、舆论等意图，执行层会用用户原话清洗出更完整的 fallback；网页搜索会自动安全读取部分结果页正文摘录
- 普通聊天检测到 http/https URL 时，会额外暴露 `fetch_url` 工具，直接读取网页标题和正文摘录后再总结；如果模型误把 URL 交给 `search_web`，或调用 `fetch_url` 时漏填 URL 参数，执行层会从用户原话中抽取 URL 并改用 URL 直读
- 普通聊天检测到视频链接、B站 BV 号或 av 号时，会额外暴露 `understand_video_url` 工具；B站视频优先读取标题、简介、统计和可用字幕，其他视频页只读取页面文字；如果模型误把视频链接交给 `search_web` 或 `fetch_url`，或调用视频工具时漏填 URL 参数，执行层会从用户原话中抽取视频 URL 并改用视频理解
- 检测到 B站、bilibili、小破站、阿B、UP主、主播、直播间、投稿等搜索语境时，普通聊天会额外暴露 `bilibili_user_search` 和 `bilibili_video_search`；如果用户已经给出具体视频链接、BV 号或 av 号，则优先走视频理解，不再同时暴露 B站搜索工具
- `/search` 会清理口语化关键词、执行网页搜索；首个 provider 结果整体弱相关时会尝试备用 provider，然后先按查询相关性、再按来源优先级安全读取部分结果页正文，并让模型结合带状态、检索时间、搜索意图、时效性要求、发布时间覆盖、时效性风险、证据质量、相关性、来源优先级、域名覆盖、引用编号、交叉验证、风险提示和疑似冲突提示的搜索结果整理回复；结果过长时会压缩正文摘录并标记压缩状态；最新消息、最近热度、趋势、舆论或评价这类高时效问题会按检索时间和结果发布时间谨慎表达，疑似冲突来源不会被直接合并
- `/search` 收到明确 URL 时会先按链接类型直读：视频链接走视频理解，普通网页走 URL 直读；只有非 URL 查询才执行网页搜索
- `/url` 会直接读取指定网页，不把 URL 当搜索词；只支持 http/https 文本网页，并拒绝本机、内网或过大的内容
- `/video` 会按视频链接理解：当前支持 B站视频信息/字幕和普通视频页文字；直接 `.mp4`、`.m3u8` 等媒体流会说明缺少哪些下载、转写或抽帧能力，不会假装完整看过画面或听过音频
- `/buser`、`/bvideo` 按原话搜索 B站用户或视频
- `/bfuser`、`/bfvideo` 先用 DeepSeek 筛选关键词，再搜索 B站用户或视频；筛选失败会退回本地关键词清理
- 网页搜索、URL 直读和 B站搜索入口分开；搜索结果包含 `搜索状态`、`搜索类型`、`搜索词`、`检索时间`、`搜索意图`、`时效性要求`、`结果数`、`页面读取数`、`证据质量`、`来源类型汇总`、`来源优先级说明`、`相关性说明`、`查询具体度`、`查询提示`、`相关性质量`、`相关性汇总`、`发布时间覆盖`、高时效查询下的 `时效性风险`、`域名覆盖`、`域名集中风险`、`引用方式`、`可引用来源`、`交叉验证`、`风险提示`，结果过长时还包含 `结果压缩` 和 `压缩说明`，明显版本/日期不一致时还包含 `疑似冲突` 和 `冲突处理`；URL 直读包含 `获取状态`、`URL`、`标题` 和 `正文摘录`
- B站用户和视频搜索优先使用公开 API；视频短链会先尝试解析重定向；接口失败或限流时会尽量用公开 HTML 页面兜底；精确 BV/av 号在无结果时会返回公开视频直链
- `/weather` 查询今天、明天、后天或大后天的天气；普通聊天不会自动调用天气接口
- `/remember` 保存跨私聊和群聊生效的个人基础信息
- `/globalremember` 保存对所有用户生效的全局记忆，仅管理员可写
- `/reset` 清空当前会话的上下文和当前会话记忆，不删除个人基础信息或全局记忆
- `/image` 已实现基于本地 ComfyUI 的生图功能（默认关闭，仅管理员可用，需配置 `IMAGE_ENABLE=true`）；Pixiv、R18 自动发图相关功能已移除
- `/pic` 搜索图片并发送（默认关闭，需配置 `IMAGE_SEARCH_ENABLE=true` 和 `TAVILY_API_KEY`）；普通聊天不会自动搜图；不支持 Pixiv/R18/lolicon 自动抓图；当前 `/pic` 只负责搜图发图，不接入 `/image` 参考图

## 项目结构

```text
run_bot.py                 兼容启动入口
src/main.py                Flask 回调、消息分发、群聊 @ 检查、回复发送
src/router.py              区分 / 命令和普通聊天
src/messaging.py           消息去重、按会话顺序处理
src/config.py              .env 配置读取
src/chat/                  聊天生成、提示词、记忆和聊天工具调用
src/commands/              /search、/url、/video、/weather、/buser、/remember、/pic、/image 等命令
src/services/              DeepSeek、OneBot、网页搜索、URL 直读、视频理解、B站搜索、图片搜索客户端
src/utils/                 JSON 存储和安全文件名工具
test_*.py                  本地测试
```

本地运行数据默认写入 `atri_data/`：

- `atri_data/history/`：会话历史，受 `PERSIST_HISTORY` 控制
- `atri_data/memories/`：当前会话记忆、个人基础信息和全局记忆
- `atri_data/legacy_memories/`：旧版记忆迁移归档

这些目录和 `.env` 都是本地文件，不应提交。

## 安装

```powershell
python -m pip install -r requirements.txt
```

也可以直接运行 `启动ATRI.bat`，它会尝试激活 `.venv` 并在缺少 Flask 时安装依赖。

## 配置

复制 `.env.example` 为 `.env`，至少确认以下配置：

```env
# ═══════════════════════════════════════════════
# LLM Provider Chain
# ═══════════════════════════════════════════════
# At minimum, configure GEMINI_API_KEY or DEEPSEEK_API_KEY.
# Fallback order: Gemini 3.1 Flash-Lite → Gemma 4 26B → DeepSeek V4 Flash → DeepSeek V4 Pro
LLM_PRIMARY_PROVIDER=gemini
LLM_PRIMARY_MODEL=gemini-3.1-flash-lite
LLM_FALLBACK_1_PROVIDER=gemini
LLM_FALLBACK_1_MODEL=gemma-4-26b-a4b-it
LLM_FALLBACK_2_PROVIDER=deepseek
LLM_FALLBACK_2_MODEL=deepseek-v4-flash
LLM_FALLBACK_3_PROVIDER=deepseek
LLM_FALLBACK_3_MODEL=deepseek-v4-pro

# Backward compatibility (usually leave empty)
LLM_PROVIDER=

# Gemini / Google AI Studio
GEMINI_API_KEY=
GEMINI_URL=https://generativelanguage.googleapis.com/v1beta/openai/chat/completions
GEMINI_MODEL=gemini-3.1-flash-lite

# DeepSeek
DEEPSEEK_API_KEY=sk-your-key-here
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_URL=https://api.deepseek.com/chat/completions

# OpenAI (reserved, not used by default)
OPENAI_API_KEY=

ONEBOT_API_URL=http://127.0.0.1:3000
ONEBOT_ACCESS_TOKEN=
CALLBACK_SECRET=

BOT_NAME=ATRI
BOT_HOST=127.0.0.1
BOT_PORT=5000
REQUIRE_GROUP_AT=true
ADMIN_QQ_IDS=123456,234567

PROXY_URL=
TAVILY_API_KEY=
VIDEO_ENABLE_MEDIA_PIPELINE=false
VIDEO_MAX_DOWNLOAD_MB=50
VIDEO_MAX_SECONDS=600
PERSIST_HISTORY=true
DATA_DIR=atri_data
```

如果需要代理，`PROXY_URL` 写成代理地址，例如：

```env
PROXY_URL=http://127.0.0.1:7890
```

如果 OneBot 不在同一台机器上，把 `BOT_HOST` 改成 OneBot 可访问的地址，并建议配置 `CALLBACK_SECRET`。配置后，OneBot 回调请求需要携带以下任一方式：

```text
Authorization: Bearer <CALLBACK_SECRET>
X-ATRI-Callback-Secret: <CALLBACK_SECRET>
```

`ADMIN_QQ_IDS` 用英文逗号分隔。为空时，`/globalremember` 默认禁止写入。

## NapCat / OneBot

ATRI 默认监听：

```text
http://127.0.0.1:5000/
```

OneBot HTTP API 默认地址：

```text
http://127.0.0.1:3000
```

NapCat 或其他 OneBot 客户端中，把 HTTP 事件上报地址设置为：

```text
http://127.0.0.1:5000/
```

ATRI 发送消息时会调用：

```text
POST http://127.0.0.1:3000/send_private_msg
POST http://127.0.0.1:3000/send_group_msg
```

## 启动

```powershell
python run_bot.py
```

健康检查：

```text
http://127.0.0.1:5000/health
```

DeepSeek 连通性测试：

```powershell
python test_deepseek.py
```

LLM 模型链连通性测试：

```powershell
python test_llm.py
```

## 用法

普通聊天：

```text
你好
kskbl 是什么意思
最近 DeepSeek 有什么消息
帮我看下 https://example.com 讲了什么
帮我看下 https://www.bilibili.com/video/BV... 讲了什么
B站UP主大东彦是谁
小破站大东彦是谁
帮我找一个 B站无畏契约教学视频
```

命令：

```text
/help
/search DeepSeek 最新消息
/url https://example.com
/video https://www.bilibili.com/video/BV...
/buser 大东彦
/bfuser 大东彦是谁
/bvideo 无畏契约 教学
/bvideo BV1xx411c7mD
/bvideo av170001
/bfvideo 搜索视频 comfyvibe 这个视频
/weather 北京
/weather 上海大后天
/remember 我喜欢简洁回答
/globalremember 所有人都知道的设定
/reset
/image 猫娘
/pic 蓝色雨夜 二次元头像
/pic 夏目安安 3
```

行为边界：

- 天气必须用 `/weather`，普通聊天不会自动查天气接口
- 图片生成：已实现基于本地 ComfyUI 的 `/image` 生图命令，但默认关闭。
  - 需在 `.env` 中设置 `IMAGE_ENABLE=true`。
  - 默认仅管理员可用，需配置 `ADMIN_QQ_IDS=你的QQ号`。推荐将 `IMAGE_ADMIN_ONLY` 设为 `true`。
  - 使用前需要启动本地 ComfyUI Desktop，默认地址为 `http://127.0.0.1:8188`。
  - 默认使用本地 Anima 高清增强版工作流，路径为 `D:\Desktop\AI生图\workflows\anima\03_anima_enhanced_api.json`，默认 preset 为 `highres_output`。
  - LoRA 接口（角色与风格）已保留，但默认关闭。
  - 普通聊天不会自动触发图片生成工具。
  - 已知限制：base64 fallback 发图机制待实现；NapCat file URI 发图兼容性以本机实际测试为准；在没有 LoRA 或参考图输入的情况下，指定角色的外观一致性有限。
- 图片搜索：已实现 `/pic` 搜图发图命令，默认关闭。
  - 需在 `.env` 中设置 `IMAGE_SEARCH_ENABLE=true` 并配置 `TAVILY_API_KEY`。
  - 默认返回 1 张图，`/pic 关键词 3` 最多 3 张。
  - 图片下载到 `atri_data/image_search_cache/`（已加入 .gitignore）。
  - 普通聊天不会自动搜图；不支持 Pixiv/R18/lolicon。
  - 当前 `/pic` 只负责搜图发图，不接入 `/image` 参考图。
- 普通聊天不能调用 QQ API、文件操作、天气或图片工具
- URL 直读只在用户给出 URL 时可用；执行层会从工具参数或用户原话中抽取第一个 URL，再校验域名解析结果、重定向目标、内容类型和大小，拒绝读取本机或局域网地址
- 视频理解只在用户给出视频链接或 B站 BV/av 号时可用；执行层会从工具参数或用户原话中抽取视频 URL，当前基于页面信息、简介和可用字幕，不能声称已经完整看过画面或听过音频；具体视频引用优先走视频理解，不混入 B站搜索工具；即使模型误选 `fetch_url`，执行层也会把视频链接改走视频理解
- 搜索结果会清理关键词、跳过没有链接的 provider 条目、去重并标记 `success`、`no_results`、`provider_error` 等状态；`search_web` 工具调用里的查询词为空、明显比用户原话更泛，或只给主题词却漏掉原因、趋势、评价、舆论等意图时，会回退到用户原话清洗后的更完整查询；`web` 搜索会先按 provider 原始标题/摘要/链接判断相关性，首个 provider 结果整体弱相关时尝试备用 provider，再按查询词命中情况和来源优先级分配页面读取预算，避免把不贴题的官方页排在贴题结果前；官方/文档和机构公共来源优先级最高，代码/项目源、百科、新闻/媒体居中，低优先级普通网页或社交论坛只作为线索；搜索上下文会标记检索时间、搜索意图、时效性要求、发布时间覆盖、时效性风险、证据质量、相关性说明、查询具体度、查询提示、相关性质量、相关性汇总、域名覆盖、域名集中风险、来源类型汇总、来源优先级说明、引用编号、可引用来源、交叉验证、风险提示、疑似版本/日期冲突、页面读取状态和正文摘录；provider 返回日期时，每条结果会包含 `发布时间`；高时效查询下发布时间缺失或过旧会标记 `时效性风险`；同一域名下的多条结果会标记为集中风险，不当作独立交叉验证；当查询具体度为 `low` 时，会提示搜索词可能过短或过泛；当整体相关性为 `weak` 时，即使页面读取成功或来源看似权威，也会提示只能作为线索；当上下文过长时会压缩长正文摘录并标记 `结果压缩`、`压缩说明`；`bilibili_user`、`bilibili_video` 使用统一搜索上下文格式；结果只用于回答和短期上下文，不会自动写入长期记忆
- 长期记忆只通过 `/remember` 或管理员 `/globalremember` 写入

## 验证

基础编译检查：

```powershell
python -m py_compile run_bot.py test_deepseek.py
```

完整单元测试：

```powershell
python -m unittest
```

路由烟测：

```powershell
python -c "from src.router import route_message; print(route_message('/weather 北京')); print(route_message('北京天气'))"
```

检查不应提交的本地文件：

```powershell
git status --short --ignored
```

检查已移除图片功能是否有实现残留：

```powershell
rg -n "ddy|image_search|Pixiv|R18|CQ:image|lolicon|搜图|发图" . -g !.venv -g !__pycache__ -g !.git -g !.codex_tmp -g !atri_data
```

## 维护原则

- 保持 bot 小而清楚
- 新功能优先走 `/command 参数`
- 普通聊天只放少量、明确受控的工具
- 不要把天气、图片、文件、QQ API 等能力暴露给普通聊天
- 改变行为时同步更新 `README.md`、`ARCHITECTURE.md` 和 `.env.example`
