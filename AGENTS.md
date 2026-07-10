# AGENTS.md

## Project

This repository contains **ATRI**, a QQ chat bot built with Flask, OneBot HTTP API, and DeepSeek.

Primary file:

- `run_bot.py`

Current supported features:

- private and group chat
- group replies only when ATRI is mentioned, by default
- DeepSeek-powered conversation
- web search before answering
- weather lookup
- simple per-user memory

Removed / disabled feature:

- image sending, Pixiv search, R18 confirmation, and related image history code have been intentionally removed
- Image sending is currently removed. It may be reintroduced later when explicitly requested and implemented cleanly as a separate feature path.

## Local Runtime

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Test DeepSeek connectivity:

```powershell
python test_deepseek.py
```

Start the bot:

```powershell
python run_bot.py
```

Health check:

```text
http://127.0.0.1:5000/health
```

NapCat / OneBot configuration:

- OneBot API URL used by ATRI: `http://127.0.0.1:3000`
- OneBot event callback URL: `http://127.0.0.1:5000/`

## Configuration

Runtime configuration is loaded from `.env`.

Important defaults:

- `BOT_NAME=ATRI`
- `DATA_DIR=atri_data`
- `BOT_PORT=5000`
- `ONEBOT_API_URL=http://127.0.0.1:3000`

Never hardcode API keys or secrets in source code.

## Do Not Commit

The following are local-only and must not be committed:

- `.env`
- `atri_data/`
- `ddy_data/`
- `gemini废案/`
- `__pycache__/`
- `data_tmp/`

Keep `.env.example` safe and generic. It must not contain real keys.

## Engineering Rules

Work conservatively and keep changes focused.

- read relevant files before editing
- prefer editing existing files over adding new ones
- keep this small bot simple; do not introduce large architecture splits without a clear need
- avoid unused helpers, dead code, and placeholder logic
- handle errors explicitly enough that debugging is possible
- preserve current user-facing behavior unless the task asks to change it
- do not overwrite unrelated user changes

When adding features:

- keep the command/intent routing easy to inspect
- update `README.md` and `.env.example` when behavior or configuration changes
- add dependencies only when the standard library or existing dependencies are not enough
- update `.gitignore` if new local runtime data is created

## Verification

Before finishing code changes, run:

```powershell
python -m py_compile run_bot.py test_deepseek.py
```

For routing changes, also test the relevant intent helpers locally where possible.

Useful checks:

```powershell
git status --short --ignored
```

Search for removed feature leftovers when relevant:

```powershell
rg -n "ddy|image_search|Pixiv|R18|CQ:image|lolicon|搜图|发图" .
```

## Git

Main branch:

- `main`

Remote repository:

- `https://github.com/TracyReznik1/qq_bot.git`

Use clear commits. Example:

```powershell
git add AGENTS.md README.md run_bot.py .env.example .gitignore
git commit -m "Update bot guidance"
git push
```
