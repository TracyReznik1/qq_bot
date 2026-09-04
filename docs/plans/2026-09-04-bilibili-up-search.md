# Bilibili UP Owner Search Implementation Plan

> **For Antigravity:** REQUIRED WORKFLOW: Use `.agent/workflows/execute-plan.md` to execute this plan in single-flow mode.

**Goal:** Provide `/up` (alias `/biliup`) commands to search Bilibili UP creators, retrieve statistics and latest video BV links via official WBI/card APIs with zero headless browser overhead.

**Architecture:** Extend `src/services/video_service.py` with WBI-signed user search (`/x/web-interface/wbi/search/type`) and card direct lookup (`/x/web-interface/card`). Implement `/up` command in `src/commands/bili_user.py` supporting instant structured text cards and optional contextual LLM analysis.

**Tech Stack:** Python 3.11+, `requests`, WBI MD5 signing, standard library.

---

### Task 1: Bilibili UP Creator Service & Card Formatter

**Files:**
- Modify: `src/services/video_service.py`
- Test: `tests/test_bili_user_service.py`

**Step 1: Write failing tests**
- Test `fetch_bilibili_user` with keyword query (WBI signed search).
- Test `fetch_bilibili_user` with numeric UID query (`/card` API).
- Test `fetch_bilibili_user` with not-found result.
- Test `format_bilibili_user_card` human-friendly formatting (e.g. 10000 -> 1.0万, 924部, live status, recent videos).

**Step 2: Implement minimal code**
- Define `BilibiliUserVideo` and `BilibiliUserPayload` dataclasses.
- Implement `fetch_bilibili_user(keyword_or_mid: str) -> BilibiliUserPayload`.
- Implement `format_bilibili_user_card(payload: BilibiliUserPayload) -> str`.

**Step 3: Verify and commit**
- Run `python -B -m unittest tests/test_bili_user_service.py -v`.
- Commit changes.

---

### Task 2: Command Routing & LLM Integration

**Files:**
- Create: `src/commands/bili_user.py`
- Modify: `src/commands/__init__.py`
- Modify: `src/commands/help.py`
- Test: `tests/test_bili_user_command.py`

**Step 1: Write failing tests**
- Test `/up` without arguments returns help examples.
- Test `/up <name>` returns instant structured card (no LLM call).
- Test `/up <name> <question>` calls LLM with user card injected.
- Test `/biliup` alias works identically.

**Step 2: Implement minimal code**
- Create `src/commands/bili_user.py` with `bili_user_reply(query, context)`.
- Register in `src/commands/__init__.py`.
- Register in `src/commands/help.py`.

**Step 3: Verify and commit**
- Run `python -B -m unittest tests/test_bili_user_command.py -v`.
- Commit changes.

---

### Task 3: Full Regression and Documentation

**Files:**
- Modify: `README.md`
- Modify: `README_EN.md`
- Modify: `docs/plans/task.md`

**Step 1: Run full regression**
- Run `python -B -m unittest discover -s tests -t .`.
- Run `python -B -m compileall -q src tests run_bot.py`.

**Step 2: Update documentation**
- Add `/up` and `/biliup` to command reference tables in `README.md` and `README_EN.md`.
- Verify with `python -B -m unittest tests.test_readme_guide -v`.

**Step 3: Complete task list and commit**
- Commit documentation and completed task checklist.
