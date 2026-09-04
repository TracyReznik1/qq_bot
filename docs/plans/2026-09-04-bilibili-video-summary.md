# Bilibili 视频总结功能 Implementation Plan

> **For Antigravity:** REQUIRED WORKFLOW: Use `.agent/workflows/execute-plan.md` to execute this plan in single-flow mode.

**Goal:** 为 qqbot (Lite) 增加轻量级 B 站视频总结功能（支持 `/video` 命令与聊天中发送视频链接自动直读），基于 B 站官方 Web API 提取元数据与中文字幕流，零额外重量级依赖。

**Architecture:** 创建 `src/services/video_service.py` 实现视频 ID 提取、View API、Player V2 API 与字幕流解析；在 `src/chat/prompt.py` 中引入安全 XML 语义沙箱 `<external_bilibili_video>`；在 `src/commands/video.py` 实现显式 `/video` 命令；在 `src/chat/chat_service.py` 中引入视频链接拦截并短路普通搜索；覆盖完整单元测试。

**Tech Stack:** Python 3.10+, `requests`, `unittest`, Bilibili Web API.

---

### Task 1: Bilibili 视频与字幕解析服务 (`src/services/video_service.py`)

**Files:**
- Create: `src/services/video_service.py`
- Test: `tests/test_video_service.py`

**Step 1: Write the failing test**
Create `tests/test_video_service.py` testing:
- BV / av 号提取与 `b23.tv` 短链重定向规范化
- `fetch_bilibili_video_info` 成功解析标题、UP主、简介、时长、cid
- `fetch_bilibili_subtitles` 成功下载并合并 JSON 字幕行
- 无字幕时的优雅降级（返回 `has_subtitles=False`）
- 超长字幕安全截断（上限 20,000 字符）

**Step 2: Run test to verify it fails**
Run: `python -B -m unittest tests/test_video_service.py -v`
Expected: FAIL with "ModuleNotFoundError" or "ImportError"

**Step 3: Write minimal implementation**
Implement `src/services/video_service.py` with:
- `extract_bilibili_video_id(text: str) -> tuple[str, str, str]`
- `fetch_bilibili_video_data(bvid: str, aid: str = "") -> BilibiliVideoData`
- `fetch_bilibili_subtitles(bvid: str, cid: int) -> tuple[bool, str]`
- `get_bilibili_video_summary_context(url_or_text: str) -> BilibiliVideoSummaryPayload`

**Step 4: Run test to verify it passes**
Run: `python -B -m unittest tests/test_video_service.py -v`
Expected: PASS

**Step 5: Commit**
Run:
`git add src/services/video_service.py tests/test_video_service.py`
`git commit -m "feat(video): add bilibili video and subtitle parsing service"`

---

### Task 2: 提示词与 XML 沙箱封装 (`src/chat/prompt.py`)

**Files:**
- Modify: `src/chat/prompt.py`
- Test: `tests/test_video_prompt_sandbox.py`

**Step 1: Write the failing test**
Create `tests/test_video_prompt_sandbox.py` testing:
- `format_bilibili_video_sandbox(video_data)` 将标题、UP主、简介、字幕转义并放入 `<external_bilibili_video>`
- 沙箱转义能抵御恶意的 XML 尖括号注入与 Prompt 越狱标记
- `build_untrusted_context` 正确注入视频沙箱

**Step 2: Run test to verify it fails**
Run: `python -B -m unittest tests/test_video_prompt_sandbox.py -v`
Expected: FAIL with missing function

**Step 3: Write minimal implementation**
In `src/chat/prompt.py`:
- Implement `format_bilibili_video_sandbox(payload: BilibiliVideoSummaryPayload) -> str`
- Update `build_untrusted_context` to accept `video_payload: str = ""`

**Step 4: Run test to verify it passes**
Run: `python -B -m unittest tests/test_video_prompt_sandbox.py -v`
Expected: PASS

**Step 5: Commit**
Run:
`git add src/chat/prompt.py tests/test_video_prompt_sandbox.py`
`git commit -m "feat(prompt): add external bilibili video xml sandbox"`

---

### Task 3: 显式命令 `/video` (`src/commands/video.py` & registry)

**Files:**
- Create: `src/commands/video.py`
- Modify: `src/commands/__init__.py`
- Modify: `src/commands/help.py`
- Test: `tests/test_video_command.py`

**Step 1: Write the failing test**
Create `tests/test_video_command.py` testing:
- `/video BV1xxx` 返回总结
- `/video` 缺少参数时返回帮助提示
- 无效视频链接时返回友好错误说明
- 注册别名 `/v` 和 `/bv`

**Step 2: Run test to verify it fails**
Run: `python -B -m unittest tests/test_video_command.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**
- Create `src/commands/video.py` with `video_command(query, context, store)`
- Register `video`, `v`, `bv` in `src/commands/__init__.py:COMMANDS`
- Update `src/commands/help.py` to mention `/video`

**Step 4: Run test to verify it passes**
Run: `python -B -m unittest tests/test_video_command.py -v`
Expected: PASS

**Step 5: Commit**
Run:
`git add src/commands/video.py src/commands/__init__.py src/commands/help.py tests/test_video_command.py`
`git commit -m "feat(commands): add /video command for bilibili video summary"`

---

### Task 4: 普通聊天中的 B 站视频前置直读与总结 (`src/chat/chat_service.py`)

**Files:**
- Modify: `src/chat/chat_service.py`
- Test: `tests/test_video_chat_flow.py`

**Step 1: Write the failing test**
Create `tests/test_video_chat_flow.py` testing:
- 用户消息输入 `看下这个视频 https://www.bilibili.com/video/BV1xx...` 时，前置拦截为 B 站视频直读，生成总结并短路搜索
- 普通非视频链接继续走 `fetch_document`

**Step 2: Run test to verify it fails**
Run: `python -B -m unittest tests/test_video_chat_flow.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**
In `src/chat/chat_service.py`:
- 拦截并识别 `extract_bilibili_video_id`
- 若命中 B 站视频链接，调用 `get_bilibili_video_summary_context` 生成 `video_payload`
- 调用 `_plain_reply` 传入 `video_payload`，短路后续网络搜索

**Step 4: Run test to verify it passes**
Run: `python -B -m unittest tests/test_video_chat_flow.py -v`
Expected: PASS

**Step 5: Commit**
Run:
`git add src/chat/chat_service.py tests/test_video_chat_flow.py`
`git commit -m "feat(chat): support inline bilibili video direct summarization"`

---

### Task 5: 全量测试回归与文档更新

**Files:**
- Modify: `README.md`
- Modify: `README_EN.md`
- Test: 全量单元测试

**Step 1: Run full regression tests**
Run: `python -B -m unittest discover -s tests -t . -v`
Expected: ALL PASS (520+ tests)

**Step 2: Update README**
Add `/video` instruction and inline Bilibili video summary feature description.

**Step 3: Commit**
Run:
`git add README.md README_EN.md`
`git commit -m "docs: update readme with bilibili video summary capabilities"`
