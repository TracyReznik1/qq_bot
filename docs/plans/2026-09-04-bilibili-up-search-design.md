# Bilibili UP Owner Search Command (`/up`) Design

**Date**: 2026-09-04
**Topic**: Add `/up` and `/biliup` commands to query Bilibili UP owners, view statistics, and display recent video BV links.

---

## 1. Goal and Background
Following the lightweight addition of Bilibili video summaries (`/video`), users need a fast and seamless way to look up Bilibili UP owners (content creators) to check their fan count, video archives, biography, official badges, and latest video BV links without opening a browser or running heavy browser automation.

---

## 2. Architecture & Design Decisions

### 2.1 Zero Heavy Dependencies
- Reuses existing native HTTP requests with Bilibili's official WBI authentication (`sign_wbi_params` and `get_wbi_mixin_key`).
- No headless browser, no Playwright, no bulk scrapers.

### 2.2 Dual Search Routes
1. **Keyword / Nickname Search**:
   - Endpoint: `https://api.bilibili.com/x/web-interface/wbi/search/type?search_type=bili_user&keyword=<keyword>`
   - Authenticated with dynamic WBI signature (`w_rid`, `wts`).
   - Returns top matched UP creator with `uname`, `mid`, `fans`, `videos`, `usign`, `level`, `official_verify`, `is_live`, `room_id`, and `res` (up to 3 latest video BV IDs and titles).
2. **UID Direct Query**:
   - If input is purely numerical digits or formatted as `UID:12345`:
   - Endpoint: `https://api.bilibili.com/x/web-interface/card?mid=<mid>`
   - Resolves exact creator by UID.

### 2.3 Output Modes
1. **Pure Structured Card (Fast Path, Default)**:
   - When user enters `/up <UP主名称>` without an additional question.
   - Formatted in plain text with human-friendly units (e.g. 1734.1万粉丝, 924部投稿).
   - Zero LLM tokens consumed, response time <300ms.
   - Includes hint to directly run `/video <BV号>` on the recent videos.
2. **Contextual LLM Analysis (When Question Provided)**:
   - When user enters `/up 影视飓风 他的主要视频风格是什么？`.
   - The fetched UP owner card is injected into untrusted context sandbox, and LLM generates a targeted answer.

---

## 3. Command Specification

| Command | Alias | Description |
|---|---|---|
| `/up <昵称或UID>` | `/biliup` | 查询 B站 UP主名片、粉丝数、认证与最新投稿视频 |

### Command Syntax Examples:
- `/up` -> Returns usage examples.
- `/up 影视飓风` -> Instant structured card.
- `/up 946974` -> Query by UID.
- `/biliup 何同学 这个UP主有哪些代表作` -> LLM targeted summary.

---

## 4. File Changes Plan
- `src/services/video_service.py`: Add `BilibiliUserPayload`, `BilibiliUserVideo`, `fetch_bilibili_user()`, `format_bilibili_user_card()`.
- `src/commands/bili_user.py`: Command handler implementation.
- `src/commands/__init__.py`: Register `/up` and `/biliup`.
- `src/commands/help.py`: Add `/up` to help catalog.
- `tests/test_bili_user.py`: Unit tests for user fetch, card formatting, and command routing.
- `README.md`, `README_EN.md`: Document `/up` command and feature.
