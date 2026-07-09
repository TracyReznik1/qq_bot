# AGENTS.md

## Project

This repository contains **ATRI**, a local QQ chat bot built with Flask, OneBot HTTP API, and DeepSeek.

Primary runtime entry:

- `run_bot.py`

Main implementation lives under:

- `src/`

Reference documents:

- `README.md` — user-facing setup and usage
- `ARCHITECTURE.md` — current architecture and module boundaries
- `PROJECT_STATE.md` — current status, known limits, and risks
- `TASKS.md` — small executable tasks

If code and documentation disagree, **source code wins**. Fix the documentation instead of silently changing behavior.

---

## Tool / Agent Division

This project may be worked on by both Codex and Claude Code. They should not do the same kind of work in the same turn.

### Claude Code should be used for

- Reading and summarizing larger context
- Reviewing architecture, project memory, and task plans
- Splitting large tasks into smaller executable tasks
- Writing or revising `.md` documents
- Producing implementation plans for Codex
- Explaining tradeoffs before a code change

Claude Code should avoid direct large code rewrites unless the user explicitly asks for that exact change.

### Codex should be used for

- Executing one small code task at a time
- Editing specific files after the plan is approved
- Running local checks and tests
- Reporting exact diffs, affected files, and verification results
- Fixing test failures caused by the current task

Codex should not reinterpret the project direction. If a task seems too broad, Codex must stop and ask for a smaller task.

### Handoff format from Claude Code to Codex

When Claude Code prepares a task for Codex, use this format:

```md
## Task
<one concrete objective>

## Scope
Allowed files:
- `path/to/file.py`

Forbidden:
- no unrelated refactor
- no command rename
- no dependency changes unless explicitly listed

## Required reading
- `AGENTS.md`
- `ARCHITECTURE.md`
- `PROJECT_STATE.md`
- relevant source/test files

## Expected change
<what behavior or document should change>

## Verification
- `python -m py_compile ...`
- `python -m unittest ...`
- any manual smoke test
```

---

## AI Agent Working Rules

### Rule 1: Do not modify code without a concrete task and plan

Before changing runtime code, test code, configuration templates, or startup scripts, the agent MUST state:

- The single task being addressed
- The exact files and functions expected to change
- Why the change is needed
- What behavior should remain unchanged
- How the change will be verified

Runtime code includes, but is not limited to:

- `run_bot.py`
- `src/**/*.py`
- `test_*.py`
- `requirements.txt`
- `.env.example`
- `启动ATRI.bat`
- any script that affects startup, deployment, or local data

Wait for explicit user approval before modifying these files.

Documentation-only changes may proceed without extra approval when the user explicitly asked for documentation edits, but the agent must still summarize changes afterward.

### Rule 2: Keep every change small

Each work session should address ONE task or ONE bug.

Do NOT:

- Restructure the entire project
- Rename modules or files across the codebase
- Merge or split modules unless the current task requires it
- Introduce a new framework, ORM, database, queue, async runtime, scheduler, or service manager
- Add dependencies casually
- Change coding style in unrelated files
- Rewrite tests unrelated to the current task
- “Clean up” nearby code without a direct reason

If a task touches many files, split it into independently reviewable steps and ask which step to do first.

### Rule 3: Preserve existing user-visible behavior

Do NOT change these unless the task explicitly requires it:

- Command names or aliases
- Command output semantics
- `/weather`, `/search`, `/url`, `/video`, `/buser`, `/bvideo`, memory, reset, and help behavior
- Group mention behavior
- Message splitting behavior
- Chat history and memory persistence semantics
- `BOT_PERSONA` / system prompt format
- `.env.example` key names
- Public function/class names used by other modules

If a public interface must change, list all callers first.

### Rule 4: Respect tool and feature boundaries

Ordinary chat is not a full Agent. Do NOT:

- Expose weather, image, file, QQ API, shell, filesystem, or admin tools to the chat model
- Move command business logic into `process_message()` or `src/router.py`
- Add new chat tools without updating the allowlist and tests
- Let ordinary chat send files, images, or CQ codes
- Reintroduce Pixiv, R18, image search, `CQ:image` auto-send, or removed image features without a standalone design and explicit user approval
- Make the model claim it has watched video frames or heard audio when only page text, metadata, or subtitles were read
- Add `/image` auto-trigger from ordinary chat — image generation must stay behind the `/image` command, gated by `IMAGE_ENABLE` and `IMAGE_ADMIN_ONLY`

Allowed ordinary chat tools must stay narrow and auditable.

### Rule 4b: Image generation boundaries

The `/image` command calls a local ComfyUI / Anima workflow.  These rules apply:

- **AI image project is read-only.** `D:\Desktop\AI生图` may be read (e.g. workflow JSON) but must never be modified, deleted, or written to.
- **Do not copy models or LoRA files** into the QQ bot project.
- **LoRA is disabled by default.** `IMAGE_USE_CHARACTER_LORA=false` and `IMAGE_USE_STYLE_LORA=false`.  Users enable LoRA by editing `.env` — never by changing default code values.
- **Do not auto-enable LoRA** even when the user mentions a character name like "夏目安安" — only put the tag in the prompt.
- **A single-task lock** prevents concurrent GPU work.  Do not remove or bypass `IMAGE_SINGLE_TASK_LOCK`.
- **Workflow path is configurable.**  Default is `COMFYUI_WORKFLOW_API_PATH`, not hardcoded.

### Rule 5: Protect secrets and local data

Never commit or print secrets.

Do NOT expose:

- `.env`
- API keys
- OneBot tokens
- callback secrets
- QQ IDs from local config
- `atri_data/`
- `atri_data/generated_images/`
- chat history files
- memory files

If the agent discovers a real secret in a tracked file, copied document, log, or prompt output, it must stop and report the risk without quoting the secret.

If `.env` is only present locally and ignored by git, do not call it “leaked” unless there is evidence that it was committed, uploaded, pasted, or shared.

### Rule 6: High-risk operations require explicit approval

The agent must ask before doing any of the following:

- Deleting directories
- Removing files from git history
- Running destructive git commands
- Changing dependencies
- Adding background services or startup persistence
- Changing security checks
- Changing callback authentication
- Changing command names or memory behavior
- Enabling image/media pipeline features
- Modifying `D:\Desktop\AI生图` (read-only reference project)
- Changing image generation workflow path or preset defaults
- Enabling LoRA by default
- Moving or deleting `.codex_tmp/`, `gemini废案/`, or other large local-only directories

Before deletion, inspect and summarize what would be removed.

### Rule 7: Test before claiming completion

After code changes, run the smallest relevant check plus the broader check when feasible.

Baseline checks:

```powershell
python -m py_compile run_bot.py test_deepseek.py
python -m unittest
```

For changed source files, compile them directly:

```powershell
python -m py_compile path\to\changed_file.py
```

Routing smoke test:

```powershell
python -c "from src.router import route_message; print(route_message('/weather 北京')); print(route_message('北京天气'))"
```

Removed-feature boundary check:

```powershell
rg -n "ddy|image_search|Pixiv|R18|CQ:image|lolicon|搜图|发图" . -g !.venv -g !__pycache__ -g !.git -g !.codex_tmp -g !atri_data
```

If a check cannot be run, state exactly why. Do not claim success for checks that were not run.

### Rule 8: Report changes in a fixed format

After finishing, report:

```md
## Changes Made

### Files Modified
- `path/to/file1.py` — what changed and why

### Verification
- [x] `python -m py_compile ...`
- [x] `python -m unittest ...`
- [ ] Not run: reason

### Behavioral Impact
- User-visible behavior changed: yes/no
- Compatibility risk: low/medium/high

### Notes
- Any follow-up task discovered
```

### Rule 9: Update documents when behavior changes

When behavior, commands, config, module responsibility, or feature status changes:

- Update `README.md` for user-facing behavior
- Update `.env.example` for config keys
- Update `ARCHITECTURE.md` for architecture/module changes
- Update `PROJECT_STATE.md` for completion status and known issues
- Update `TASKS.md` when tasks are completed or discovered
- Update `AGENTS.md` only when working rules themselves change

### Rule 10: Be conservative with implementation claims

Before editing or reporting, read the relevant source files.

Do not infer current behavior only from old documents. If behavior was not verified in code, mark it as “待核验” instead of stating it as fact.

---

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

---

## Configuration

Runtime configuration is loaded from `.env`.

Important defaults:

- `BOT_NAME=ATRI`
- `DATA_DIR=atri_data`
- `BOT_PORT=5000`
- `ONEBOT_API_URL=http://127.0.0.1:3000`

Never hardcode API keys, tokens, secrets, or QQ IDs in source code.

---

## Do Not Commit

Local-only files and directories:

- `.env`
- `atri_data/`
- `ddy_data/`
- `gemini废案/`
- `__pycache__/`
- `data_tmp/`
- `.venv/`
- `.codex_tmp/`

Keep `.env.example` safe and generic. It must contain placeholders only.

---

## Git

Main branch:

- `main`

Remote repository:

- `https://github.com/TracyReznik1/qq_bot.git`

Use clear, focused commits. Example:

```powershell
git add AGENTS.md README.md run_bot.py .env.example .gitignore
git commit -m "Update bot guidance"
git push
```

Do not push unless the user explicitly asks.

---

## Verification Quick Reference

| Check | Command |
|---|---|
| Compile check | `python -m py_compile run_bot.py test_deepseek.py test_llm.py src/services/comfyui_client.py src/services/image_generation_service.py` |
| All unit tests | `python -m unittest` |
| Test discovery | `python -m unittest discover -v` |
| Router smoke test | `python -c "from src.router import route_message; print(route_message('/weather 北京')); print(route_message('北京天气'))"` |
| DeepSeek connectivity | `python test_deepseek.py` |
| LLM chain connectivity | `python test_llm.py` |
| Image generation tests | `python -m unittest test_image_generation -v` |
| ComfyUI workflow smoke | `python -c "from src.services.image_generation_service import load_workflow, _find_positive_node; wf=load_workflow(r'D:\Desktop\AI生图\workflows\anima\03_anima_enhanced_api.json'); print('OK' if _find_positive_node(wf)[0]=='4' else 'FAIL')"` |
| Removed image feature scan | `rg -n "ddy\|image_search\|Pixiv\|R18\|CQ:image\|lolicon\|搜图\|发图" . -g !.venv -g !__pycache__ -g !.git -g !.codex_tmp -g !atri_data` |
| Secret tracking check | `git ls-files .env` |
| Ignore check | `git check-ignore -v .env` |
| Git status check | `git status --short --ignored` |
