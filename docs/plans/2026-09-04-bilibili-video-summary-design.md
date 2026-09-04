# B站视频总结功能技术方案设计 (Bilibili Video Summary Design)

## 1. 概述与目标

为 `qqbot` (Lite 架构) 增加高质量、低延迟的 B 站视频总结能力：
- 支持通过显式命令 `/video <链接/BV号> [额外要求]` 触发总结；
- 支持在普通聊天中检测到 B 站视频链接时自动识别并直读字幕总结（短路网络搜索）；
- 毫秒级直接调用 B 站 Web API 提取视频元数据与官方/AI 字幕，零额外重量级爬虫或浏览器依赖；
- 具备严格的 XML 语义沙箱防御、长字幕截断保护与无字幕优雅降级策略。

---

## 2. 架构设计与数据流

```text
[ 输入消息 ]
     │
     ├── 显式命令分支: /video BV1xx... 或 /v, /bv
     │       └── 命令处理函数 (src/commands/video.py)
     │
     └── 普通聊天分支: 用户消息中含 B站链接/BV号 (src/chat/chat_service.py)
             └── 前置检测: is_bilibili_video(url/text)
     │
     ▼
[ Bilibili 视频解析服务 (src/services/video_service.py) ]
     ├── 1. 规范化与短链重定向追踪 (b23.tv -> BV... / av...)
     ├── 2. 获取视频元数据: GET https://api.bilibili.com/x/web-interface/view
     │      (标题, UP主, 简介, 分区, 时长, 播放/点赞数据, cid)
     ├── 3. 获取播放器与字幕数据: GET https://api.bilibili.com/x/player/v2?bvid=...&cid=...
     └── 4. 下载并解析最佳中文字幕 (优先 zh-CN / zh-Hans / ai-zh)
     │
     ▼
[ 数据封装与沙箱隔离 (src/chat/prompt.py) ]
     ├── 无字幕降级: 提取简介、标签，标记 no_subtitle
     ├── 长文本保护: 字幕上限 20,000 字符，超长时保留头部/尾部并采样
     └── XML 沙箱转义: <external_bilibili_video>...</external_bilibili_video>
     │
     ▼
[ 结构化总结生成 (LLM) ]
     └── 输出格式:
         【视频核心主题】
         【核心要点与大纲】
         【关键结论】
```

---

## 3. 详细模块设计

### 3.1 视频服务模块 `src/services/video_service.py`
- **链接识别与规范化**：
  - 支持 `b23.tv` 短链接重定向解析；
  - 支持 `bilibili.com/video/BV...`、`bilibili.com/video/av...`；
  - 支持直接输入 `BV1...` 或 `av...`。
- **API 交互**：
  - `View API`：`https://api.bilibili.com/x/web-interface/view?bvid={bvid}`
  - `Player V2 API`：`https://api.bilibili.com/x/player/v2?bvid={bvid}&cid={cid}`
  - `Subtitle Download`：读取 `subtitle_url`（通常为 JSON 格式），解析 `body[].content`，拼接为带相对时间/段落的文本。
- **无字幕降级**：
  - 若无可用字幕，返回 `has_subtitles=False`，提取标题、UP 主、简介、发布时间、统计数据。

### 3.2 命令系统扩展 `src/commands/video.py` 与 `src/commands/__init__.py`
- 注册命令：`/video`, `/v`, `/bv`
- 处理逻辑：
  - 解析 BV 号与用户可能附带的提示（例如 `/video BV1xxx 总结里面的技术方案`）；
  - 调用 `video_service` 获取视频数据；
  - 将封装后的沙箱 payload 与用户 prompt 提交给 `chat_service._plain_reply` 或专属函数生成总结。

### 3.3 普通聊天前置直读扩展 `src/chat/chat_service.py`
- 在 `generate_reply` 中的 URL 前置直读流程中：
  - 检查链接是否为 B 站视频链接（`is_bilibili_video`）；
  - 若是 B 站视频链接，直接走 B 站专属视频直读，而不是通用的静态 HTML `fetch_document`；
  - 生成 `<external_bilibili_video>` 沙箱并由模型作答，跳过后续搜索引擎。

### 3.4 提示词与沙箱 `src/chat/prompt.py`
- 引入 `format_external_bilibili_video_sandbox(...)`：
  - 将标题、UP主、时长、简介与字幕文本进行 HTML/XML 实体转义；
  - 指导模型在总结时按结构化大纲输出，区分有字幕和无字幕（无字幕时明确说明基于简介推导）。

---

## 4. 依赖与环境
- **纯原生实现**：仅使用 Python 标准库（`json`, `re`, `urllib.parse`）与现有的 `requests`。
- **不引入**：`playwright`, `tauri`, `ffmpeg`, `yt-dlp` 等重型依赖。
- **与 Lite 架构 100% 兼容**。

---

## 5. 测试策略
- 单元测试：
  - `tests/test_video_service.py`：mock B 站 API 与字幕解析、短链解析、无字幕降级、长字幕截断。
  - `tests/test_video_command.py`：`/video` 指令路由、参数解析与拟人化回复测试。
  - `tests/test_video_chat_flow.py`：普通聊天中发送 B 站视频链接时的直读与总结流程。
