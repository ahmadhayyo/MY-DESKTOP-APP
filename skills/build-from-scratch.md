---
name: build-from-scratch
description: Build a new software project from zero, efficiently — plan, scaffold, implement, run, verify
triggers: [ابنِ, ابن, أنشئ, انشئ, اصنع, صمّم, صمم, من الصفر, مشروع جديد, build, create, make, develop, scaffold, new project, from scratch]
---

# Skill: Build a Project From Scratch (efficiently)

Goal: produce a WORKING project, not just files. Follow these phases.

## Phase 1 — Design before typing
- Restate in one line WHAT it does and its ONE core flow (input → process → output).
- Decide the stack: language + minimal libraries. Prefer the simplest that works
  (Python + stdlib / tkinter for desktop; plain HTML/JS or Flask for web).
- List the files you'll create and each file's single responsibility. Keep it
  small — 2–5 files beats an over-engineered tree.
- Seed the live todo list (`todo_write`) with the files/steps.

## Phase 2 — Scaffold
- `create_project(name, template, location)` for a standard base, OR just
  `write_file` each file directly when you want full control. Put it where the
  user asked, else the Desktop.
- Write real, runnable code — no `# TODO` placeholders in the core path.

## Phase 3 — Resolve dependencies (don't stop to ask)
- Missing library → `terminal_run("python -m pip install X")` (in a persistent
  session so it stays active for the run).
- Need an external program/SDK → `find_on_computer` first; only download from the
  web if it's genuinely not installed.

## Phase 4 — Run & verify (mandatory — this is what makes it "efficient", not just written)
- Run it the real way: `run_script` / `run_python` / `run_executable`.
- Desktop GUI or web page → also `analyze_screen` to SEE it renders correctly.
- Read any error, fix the file, re-run. Loop until a clean run.
- If you wrote tests, run them and make them pass.

## Phase 5 — Report
- State: what was built, the file layout, how to run it, and the verified result
  (what you saw when you ran it). Give the exact run command.

## Efficiency rules
- One in_progress todo at a time; mark done only after a tool confirms it.
- Don't gold-plate: build the core flow first, verify it works, then add extras
  only if asked.
- Never declare done before at least one successful run.

## Portability (so it runs on the USER's machine, not just yours)
- The user's default Windows console is often a legacy code page (cp1256/cp1252),
  NOT UTF-8. Printing fancy characters (✓ ✗ emoji …) will crash there with
  UnicodeEncodeError even though it works in your runner.
- Prefer plain ASCII in console output ([x]/[ ] instead of ✓/✗). If you must
  print Unicode, put `import sys; sys.stdout.reconfigure(encoding="utf-8")` at the
  very top of the entry file. If run_script prints a [⚠️ PORTABILITY] warning,
  FIX it before declaring done.
