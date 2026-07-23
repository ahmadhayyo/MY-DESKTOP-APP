---
name: fix-project
description: Autonomously analyze, fix, develop, auto-resolve blockers, test and report on a code project
triggers: [أصلح, اصلح, إصلاح, صحّح, طوّر, طور, fix, debug, bug, خلل, مشكلة, لا يعمل, broken, project, مشروع]
---

# Skill: Autonomous Project Work (analyze → fix → auto-resolve → test → report)

Work end-to-end WITHOUT asking the user to continue. Only stop when the project is
genuinely done, then report methodically. Follow these five phases in order.

## Phase 1 — Deep analysis (understand before touching anything)
- `list_dir(path=workspace)` to map the whole structure (recurse into key folders).
- Identify: language, framework, entry point, build/run command, config, dependencies
  (requirements.txt / package.json / build.gradle / etc.).
- Read the entry point + the core modules + any config. Build a real mental model.
- Do NOT re-read files already read this conversation.
- OUTPUT of this phase (state it explicitly before fixing): what the project does,
  how it runs, its components, and a prioritized list of the problems you found.

## Phase 2 — Develop & fix
- Work through the problem list. For each: go to the exact file:line, understand the
  root cause in one sentence, then `edit_file_replace` with the minimal change.
- Keep the live todo list (`todo_write`) updated — one item in_progress at a time.

## Phase 3 — Auto-resolve blockers (do NOT stop and ask)
- Missing library/tool → install it yourself: `terminal_run("python -m pip install X")` (in a
  persistent session so it stays available), or the right package manager.
- Need a program/app/SDK/binary you don't have → `find_on_computer` first; if truly
  missing, download it. Use `download_file(url, dest)` with a DIRECT url — do NOT
  scrape browser page links (fails on lazy-loaded pages). For a GitHub tool the
  stable direct url is
  `https://github.com/<owner>/<repo>/releases/latest/download/<asset>`
  (e.g. jq: `.../jqlang/jq/releases/latest/download/jq-win64.exe`). Unzip if needed,
  then run the exe directly by path — a portable exe needs no "install".
- Need to update an outdated program/app → do it, then continue.
- If no existing tool fits a sub-need → `forge_tool` to build one, then use it.
- Only surface to the user for a genuine credential/authorization wall.

## Phase 4 — Test (prove it works, fix what breaks, repeat)
- Run the project the real way (`terminal_run` / `run_script` / `run_executable`).
- GUI/web app → also `analyze_screen` to SEE it renders correctly.
- Android app → use the Android testing skill: start/verify the emulator with
  `android_devices`, `android_install_apk`, `android_launch_app`,
  `android_screenshot` + `analyze_screen`, drive it with `android_tap`/`android_input_text`.
- On ANY failure: read the error, fix it (back to Phase 2), and re-test. Loop until
  a clean pass. Continue through all tests before declaring done.

## Phase 5 — Confirm & report
- Only when every test passes and the project is truly ready, stop.
- Write a methodical final report: what the project is, the problems you found,
  exactly what you changed (files + why), how you resolved blockers, what tests you
  ran and their results, and the final working state.
