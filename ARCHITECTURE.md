# ARCHITECTURE.md

## Overview

ATRI is a small QQ chat bot that runs as a local Flask service.

It connects to QQ through a OneBot-compatible client such as NapCat:

- NapCat sends incoming QQ message events to ATRI.
- ATRI decides what the message means.
- ATRI may call DeepSeek, web search, weather lookup, or local memory.
- ATRI sends the final response back through NapCat's OneBot HTTP API.

The project intentionally stays simple. The runtime code currently lives in one main file:

- `run_bot.py`

This is acceptable for the current size. Do not split it into many layers unless the bot grows enough to make that worthwhile.

## Runtime Topology

```text
QQ
  |
  v
NapCat / OneBot
  |
  | POST http://127.0.0.1:5000/
  v
ATRI Flask app (run_bot.py)
  |
  | DeepSeek API / weather / web search
  v
External services
  |
  v
ATRI response
  |
  | POST http://127.0.0.1:3000/send_private_msg
  | POST http://127.0.0.1:3000/send_group_msg
  v
NapCat / OneBot
  |
  v
QQ
```

Default ports:

- ATRI Flask server: `5000`
- OneBot HTTP API: `3000`

## Files

Core files:

- `run_bot.py`: main bot server and behavior
- `test_deepseek.py`: checks whether DeepSeek configuration works
- `requirements.txt`: Python dependencies
- `.env.example`: safe configuration template
- `README.md`: user-facing setup guide
- `AGENTS.md`: maintenance rules for future agents
- `ARCHITECTURE.md`: this document

Local-only files and folders:

- `.env`: real runtime secrets and local config
- `atri_data/`: local user memory
- `gemini废案/`: archived old experimental or removed files
- `__pycache__/`: Python cache

These local-only paths must not be committed.

## Configuration

Configuration is loaded from `.env` using `python-dotenv`.

The `Config` dataclass in `run_bot.py` owns all runtime configuration:

- bot name and persona
- DeepSeek API settings
- OneBot API URL and optional token
- proxy URL
- Flask port
- group mention behavior
- local data directory
- search/history/memory/reply limits

Important defaults:

```env
BOT_NAME=ATRI
BOT_PORT=5000
DATA_DIR=atri_data
ONEBOT_API_URL=http://127.0.0.1:3000
REQUIRE_GROUP_AT=true
```

Secrets must only live in `.env`.

## Message Flow

Incoming messages enter through:

```python
@app.route("/", methods=["POST"])
def onebot_event()
```

The route only handles OneBot events where:

```python
post_type == "message"
```

Main flow:

1. `onebot_event()` receives the JSON event.
2. `process_message()` extracts user ID, raw message, group/private type, and target ID.
3. If the message is from a group and `REQUIRE_GROUP_AT=true`, ATRI ignores it unless mentioned.
4. `detect_intent()` decides the action.
5. The selected handler runs.
6. `send_reply()` sends one or more message chunks through `OneBotClient`.

Supported actions:

- `chat`
- `web_search`
- `weather`
- `remember`
- `help`
- `empty`

Image actions are intentionally not supported.

## Intent Routing

Intent routing has two layers.

First, `rule_based_intent()` handles obvious commands and common Chinese phrases:

- help/menu
- remember
- `/search`
- `/weather`
- weather words
- search/latest/news words

Second, `detect_intent()` asks DeepSeek to classify unclear messages into one of:

```text
chat | web_search | weather | remember
```

This keeps common requests fast and makes ambiguous natural language flexible.

When adding new features, prefer this pattern:

1. Add clear rule-based triggers first.
2. Add the action to the DeepSeek intent prompt only if the feature needs natural language detection.
3. Add one explicit branch in `process_message()`.
4. Update `README.md`, `.env.example`, and this file if behavior changes.

## Chat Generation

Chat responses are produced by:

```python
generate_reply()
```

It builds messages using:

- the system prompt from `build_system_prompt()`
- recent in-memory chat history
- the current user message

The system prompt includes:

- ATRI persona
- saved user memory
- optional external context, such as web search results

`chat_history` is an in-process dictionary. It resets when the bot restarts.
History is keyed by conversation scope: `private:<uid>` for private chat and
`group:<group_id>:<uid>` for group chat, so the same user's contexts do not mix
between private chat and different groups.

## Memory

User memory is stored as JSON files under:

```text
atri_data/memories/
```

Each user gets one file:

```text
atri_data/memories/<user_id>.json
```

Shape:

```json
{
  "facts": ["..."]
}
```

Memory is intentionally simple:

- only explicit "remember" style messages write memory
- duplicate facts are de-duplicated
- the total fact count is capped by `MEMORY_LIMIT`

## External Services

DeepSeek:

- used for intent detection when rules are not enough
- used for final chat answers
- configured by `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`, and `DEEPSEEK_URL`

Web search:

- uses `ddgs`
- returns compact title, summary, and link blocks
- search results are passed into DeepSeek as external context

Weather:

- uses `wttr.in` JSON format
- falls back to web search if the weather API fails

Proxy:

- all external calls use `PROXY_URL` when configured
- leave `PROXY_URL=` empty if no local proxy is running

## OneBot Integration

`OneBotClient` sends responses back to NapCat.

Private messages:

```text
POST /send_private_msg
```

Group messages:

```text
POST /send_group_msg
```

The endpoint base comes from:

```env
ONEBOT_API_URL=http://127.0.0.1:3000
```

If `ONEBOT_ACCESS_TOKEN` is set, ATRI sends it as:

```text
Authorization: Bearer <token>
```

## Removed Image Feature

The project previously had image/Pixiv/R18-related code. It has been removed because the feature is not currently usable.

Do not reintroduce:

- Pixiv search
- `lolicon.app`
- `CQ:image`
- local image history
- R18 confirmation flow
- `data_tmp` image downloads

Only add image support again if the user explicitly asks for it.

## Error Handling

Current behavior:

- sending QQ messages logs errors but does not crash the bot
- DeepSeek configuration errors are reported to the QQ chat
- unexpected message handling errors are logged and reported with a short friendly reply
- web search and weather failures return fallback text

This is enough for local use. If the bot becomes long-running or public-facing, add stronger logging, auth checks, and process management.

## Verification

Basic syntax check:

```powershell
python -m py_compile run_bot.py test_deepseek.py
```

DeepSeek connectivity:

```powershell
python test_deepseek.py
```

Run server:

```powershell
python run_bot.py
```

Health check:

```text
http://127.0.0.1:5000/health
```

Useful local intent smoke test:

```powershell
python -c "import run_bot; print(run_bot.rule_based_intent('北京天气')); print(run_bot.rule_based_intent('查一下 DeepSeek 最新消息'))"
```

## Future Extension Points

Good candidates:

- more explicit commands
- better persistent memory controls
- allowlist/blocklist for group usage
- admin commands
- structured logging
- a small test suite for intent routing

Avoid for now:

- large framework migration
- premature plugin architecture
- database migration
- background job system
- image sending code

The guiding rule is: keep ATRI small, inspectable, and reliable.
