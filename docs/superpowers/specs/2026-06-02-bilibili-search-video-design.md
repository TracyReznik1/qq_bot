# Bilibili Search Video Design

## Goal

Make ATRI's Bilibili search more useful while keeping command behavior predictable.

The bot should support both Bilibili user search and Bilibili video search. Explicit commands remain deterministic, while ordinary chat can let the model choose the right Bilibili search tool when the user asks naturally.

## Current Context

Existing behavior:

- `/bsearch` and `/bs` search Bilibili public users, UPs, streamers, and live-room related profiles.
- Ordinary chat only exposes `bilibili_user_search` when the latest user message contains Bilibili signals such as `B站`, `bilibili`, `UP主`, `主播`, or `直播间`.
- Search results are formatted early as text lines in `src/services/bilibili_search.py`.

Known limitations to address during this work:

- Keyword cleanup is brittle for natural language queries.
- English usernames and numeric-only identifiers can be rejected by the current CJK gate.
- The service returns strings instead of structured result items, which makes ranking, formatting, and future extension harder.

## User-Facing Behavior

Commands:

- `/bsearch <query>` and `/bs <query>` keep searching Bilibili users.
- Add `/bvideo <query>` and `/bv <query>` for Bilibili video search.
- Empty `/bvideo` queries should return a short usage hint, similar to `/bsearch`.

Ordinary chat:

- When the message has Bilibili context, ATRI should expose both user and video search tools.
- The model chooses `bilibili_user_search` for people, UPs, streamers, live rooms, or profile questions.
- The model chooses `bilibili_video_search` for videos,投稿, BV-like questions, latest videos, tutorials, clips, reviews, or "find a B站 video" requests.
- The model may extract a cleaner keyword, but search results are the only factual basis for the final answer.

## Service Design

Keep `src/services/bilibili_search.py` as the Bilibili search service for now. The file can grow slightly, but the responsibilities should be explicit:

- query normalization
- Bilibili API/HTML fetching
- API response parsing
- result formatting

Introduce structured item dataclasses:

- `BilibiliUserItem`
- `BilibiliVideoItem`

Keep a simple text-facing result wrapper compatible with existing command and tool paths:

- `BilibiliSearchResult(ok: bool, status: str, text: str)`

Add functions:

- `search_bilibili_users(query: str) -> BilibiliSearchResult`
- `search_bilibili_videos(query: str) -> BilibiliSearchResult`
- `bilibili_user_search(query: str) -> str`
- `bilibili_video_search(query: str) -> str`

The command and chat layers should call the public search functions instead of parsing API responses themselves.

## Video Search Details

Use Bilibili's public search endpoint with `search_type=video` first:

- URL: `https://api.bilibili.com/x/web-interface/search/type`
- Parameters include `search_type=video` and `keyword=<normalized keyword>`.

Video result text should include the top 3 results when available:

- title
- UP name
- duration
- play count if present
- danmaku/comment-like count if present
- publish time if present
- description/snippet if present
- canonical video link

If the API request raises or the response cannot be parsed, return a clear failure or fallback result. HTML fallback for video search can be added only if it is small and testable; otherwise keep it out of this first pass.

## Query Normalization

Use a hybrid approach:

- deterministic cleanup first for obvious Bilibili markers, links, command words, and question suffixes
- allow model tool arguments in ordinary chat to provide cleaner query strings
- do not require CJK characters, because Bilibili names and video titles can be English, numeric, or mixed

Do not add an extra DeepSeek call inside command handling in the first pass. `/bsearch` and `/bvideo` should remain fast and deterministic. The existing chat tool-call loop already lets the model produce better query arguments for natural chat.

## Chat Tool Design

Add a second tool definition in `src/chat/chat_service.py`:

- `bilibili_video_search`

When `has_bilibili_search_signal(text)` is true, expose:

- `search_web`
- `bilibili_user_search`
- `bilibili_video_search`

`run_tool()` should dispatch both Bilibili tools explicitly. Unsupported tool names remain ignored by existing filtering.

## Command Design

Update `src/commands/bsearch.py` or add a small sibling command module if that keeps the command code clearer.

Register:

- `bvideo`
- `bv`

Keep `/bsearch` behavior unchanged except for improved normalization/search reliability.

For successful `/bvideo`, pass tool context like:

```text
B站视频搜索结果：
...
```

For failed `/bvideo`, ask the model to say that no matching Bilibili videos were found and not invent a definite result.

## Error Handling

Use explicit statuses:

- `empty_query`
- `no_results`
- `request_failed`
- `success`

Keep user-facing text short. The model can soften failed search replies, but the tool context must state the search status plainly.

## Documentation

Update:

- `README.md` feature list and usage examples
- `ARCHITECTURE.md` Bilibili search section
- command help text in `src/commands/help.py`

No new dependency should be required.

## Testing

Add or update tests for:

- `/bsearch` still searches users.
- `/bvideo` searches videos and passes video search context to `generate_reply`.
- empty `/bvideo` does not search.
- ordinary chat with Bilibili video wording exposes `bilibili_video_search`.
- the tool-call loop dispatches `bilibili_video_search`.
- video API payload parsing formats title, UP, duration, and link.
- non-CJK Bilibili query strings are not rejected before search.

Run before finishing implementation:

```powershell
python -m unittest test_run_bot_search.py test_run_bot_router.py
python -m py_compile run_bot.py test_deepseek.py
```

## Non-Goals

- Do not send images, thumbnails, or rich media.
- Do not reintroduce removed image-search/Pixiv behavior.
- Do not add login-only Bilibili APIs.
- Do not make `/bsearch` fully LLM-routed in this pass.
