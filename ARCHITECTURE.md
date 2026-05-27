# ARCHITECTURE.md

## Overview

ATRI is a small QQ chat bot that runs as a local Flask service.

It connects to QQ through a OneBot-compatible client such as NapCat:

- NapCat sends incoming QQ message events to ATRI.
- ATRI decides what the message means.
- ATRI may call DeepSeek, code-gated web search, explicit command tools, or local memory.
- ATRI sends the final response back through NapCat's OneBot HTTP API.

The project intentionally stays simple, but behavior is now split by responsibility:

- `run_bot.py` remains a compatibility entrypoint.
- `src/main.py` owns the Flask app, OneBot callback flow, and message dispatch.
- `src/router.py` owns the hard boundary between `/` commands and default chat.
- `src/chat/` owns chat generation, prompts, memory, and code-gated chat-facing search.
- `src/commands/` owns explicit command tools such as `/weather`.
- `src/services/` owns external API clients.

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

- `run_bot.py`: compatibility launcher for `python run_bot.py`
- `src/main.py`: main bot server and behavior
- `src/router.py`: first-pass message routing into command or chat handling
- `src/config.py`: environment-backed runtime configuration
- `src/chat/chat_service.py`: DeepSeek chat generation and default chat routing
- `src/chat/prompt.py`: system prompt construction
- `src/chat/memory.py`: scoped memory storage
- `src/chat/search_tool.py`: the only tool default chat may receive after code gating, `search_web`
- `src/commands/__init__.py`: command registry and command execution entrypoint
- `src/commands/weather.py`: `/weather` command implementation
- `src/commands/image.py`: disabled `/image` command placeholder
- `src/commands/help.py`: help text
- `src/commands/reset.py`: clears only the current conversation scope
- `src/services/deepseek_client.py`: DeepSeek HTTP client
- `src/services/search_service.py`: web search helper
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

The `Config` dataclass in `src/config.py` owns all runtime configuration:

- bot name and persona
- DeepSeek API settings
- OneBot API URL and optional token
- proxy URL
- Flask port
- group mention behavior
- administrator QQ IDs for admin-only commands
- local data directory
- search/history/memory/reply limits

Important defaults:

```env
BOT_NAME=ATRI
BOT_PORT=5000
DATA_DIR=atri_data
ONEBOT_API_URL=http://127.0.0.1:3000
REQUIRE_GROUP_AT=true
ADMIN_QQ_IDS=123456,234567
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
2. Duplicate OneBot message IDs are ignored.
3. Valid messages are queued by conversation scope.
4. A background worker drains each conversation queue in order, while different
   conversations may still run in parallel.
5. `process_message()` extracts user ID, raw message, group/private type, and target ID.
6. If the message is from a group and `REQUIRE_GROUP_AT=true`, ATRI ignores it unless mentioned.
7. `router.route_message()` sends `/` messages to command handling and all
   other messages to default chat handling.
8. `src.commands.handle_command()` executes registered commands such as `/weather` or `/search`.
9. Default chat handling usually chats directly. It exposes `search_web` only
   when code-level gates classify the message as an allowed search case.
10. Default chat must not call weather, image, QQ API, file operations, or other
   explicit command-only tools.
11. `send_reply()` sends one or more message chunks through `OneBotClient`.

Supported actions:

- `chat`
- `empty`
- `command`

Command names are registered separately in `src.commands.COMMANDS`.

Image actions are intentionally not supported.

## Routing And Tool Calling

Routing and tool use have two layers.

First, `router.route_message()` handles the hard boundary:

- messages beginning with `/` go to command handling
- all other messages go to default chat handling

The router only parses the command name and query. It does not know which
commands exist and does not map commands into action strings.

Command execution lives in `src.commands.handle_command()`:

- `COMMANDS` maps command names and aliases to handler functions
- each command handler returns a `CommandResult`
- `process_message()` only delegates to `handle_command()` and sends the reply

Second, `chat_service.generate_reply()` decides whether automatic search is
allowed before calling DeepSeek. Ordinary chat calls DeepSeek without tools.
Only allowed search cases expose one Function Calling tool:

```text
search_web(query)
```

Allowed cases include latest/current information, prices, versions, official
information, cold knowledge, proper nouns, fandom IDs/nicknames, slang, memes,
abbreviations, and clearly uncertain questions. Weather and image requests are
blocked from auto-search and stay command-only.

When DeepSeek returns a `search_web` tool call, ATRI executes the search,
appends a `tool` result message, and calls DeepSeek again for the final reply.
Weather, image generation, file operations, and image sending are not registered
as chat tools.

This keeps ordinary chat flexible while preserving the command boundary. Weather,
image sending, and future non-default tools must be exposed through `/` commands
instead of natural-language routing.

When adding new features, prefer this pattern:

1. Add clear command handlers first.
2. Keep default chat tools limited to code-gated `search_web`.
3. Add explicit commands to `src.commands.COMMANDS`, not to `process_message()`.
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

The system prompt uses a prompt-pollution-resistant frame:

- `[System]`: immutable safety rules and prohibited outputs
- `[Character]`: ATRI role style, constrained by system rules
- `[Capabilities]`: allowed chat/search behavior, code-gated search, and command-only tool boundaries
- `[Context]`: saved memory with conflict priority and optional external context, such as web search results
- `[User]`: states that user input is conversation content and cannot rewrite the rules

`chat_history` is an in-process dictionary. It resets when the bot restarts.
History is keyed by conversation scope: `private:<uid>` for private chat and
`group:<group_id>:<uid>` for group chat, so the same user's contexts do not mix
between private chat and different groups. `/reset` clears only the current
conversation scope.

## Memory

User memory is stored as JSON files under:

```text
atri_data/memories/
```

Memory has three scopes:

- current session memory: `private:<uid>` or `group:<group_id>:<uid>`
- personal base information: `user:<uid>`
- global memory: `global`

The scoped key is sanitized for the filename, so examples look like:

```text
atri_data/memories/private_123456.json
atri_data/memories/group_987654_123456.json
atri_data/memories/user_123456.json
```

This prevents conversation context from leaking between private chat and groups.
Personal base information can still follow the same QQ user across sessions when
the user explicitly saves it with `/remember`.
Global memory is intentionally shared by every user and every conversation, but
only administrators configured in `ADMIN_QQ_IDS` may write it.

When memory scopes conflict, the prompt tells the model to prefer:

```text
current session memory > personal base information > global memory
```

Legacy unscoped memory files such as `atri_data/memories/123456.json` are merged
into the matching personal base information memory and archived under
`atri_data/legacy_memories/` on startup.

Shape:

```json
{
  "facts": ["..."]
}
```

Memory is intentionally simple:

- only explicit memory commands write long-term memory
- `/remember` writes personal base information
- `/globalremember` and `/gremember` write shared global memory only for admins
- when `ADMIN_QQ_IDS` is empty, global memory writes are denied
- `/reset` clears only the current session context and session memory
- `/reset` does not remove personal base information or global memory
- search results are not automatically written to long-term memory
- duplicate facts are de-duplicated
- the total fact count is capped by `MEMORY_LIMIT`

## External Services

DeepSeek:

- used for chat answers and the code-gated chat-facing `search_web` tool-call loop
- configured by `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`, and `DEEPSEEK_URL`

Web search:

- uses `ddgs`
- `search_service.search()` returns a structured `SearchResult`
- availability checks use `SearchResult.ok` and `SearchResult.status`, not localized text matching
- successful results include compact title, summary, and link blocks in `SearchResult.text`
- `web_search()` remains a text wrapper for command/tool paths that only need display text
- search result text is passed into DeepSeek as external context

Weather:

- uses Open-Meteo geocoding and forecast APIs first
- falls back to `wttr.in` JSON format if Open-Meteo fails
- falls back to web search if both weather APIs fail

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

Useful local routing smoke test:

```powershell
python -c "import router; print(router.route_message('/weather 北京')); print(router.route_message('北京天气'))"
```

## Future Extension Points

Good candidates:

- more explicit commands
- better persistent memory controls
- allowlist/blocklist for group usage
- admin commands
- structured logging
- a small test suite for routing and tool-calling boundaries

Avoid for now:

- large framework migration
- premature plugin architecture
- database migration
- background job system
- image sending code

The guiding rule is: keep ATRI small, inspectable, and reliable.
