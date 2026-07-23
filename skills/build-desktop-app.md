---
name: build-desktop-app
description: Build a Windows GUI app from scratch and package it as an .exe, verified visually
triggers: [ابنِ, ابن, تطبيق, واجهة, برنامج, tkinter, gui, desktop, exe, حاسبة, app]
---

# Skill: Build a Desktop App (build → run → SEE → fix)

## 1. Plan the UI
- Decide the window, widgets, and behaviour in one short list. Prefer tkinter
  (built-in, no extra installs) unless the user asked otherwise.

## 2. Build in one shot when possible
- `build_desktop_app(app_name, python_code)` writes the code, lints it, and
  compiles a professional .exe. For finer control:
  scaffold_desktop_app → lint_python → build_exe → run_executable.

## 3. Run it
- Launch the app (`run_executable` or `terminal_run` with `start ...` so it does
  not block the session).

## 4. SEE it (mandatory for any UI)
- `analyze_screen(question="هل ظهرت الواجهة صحيحة؟ هل توجد عناصر ناقصة أو أخطاء بصرية؟")`.
- Fix any visual problem the vision model reports, rebuild, and look again.

## 5. Report
- Confirm it launches, looks correct (per the visual check), and where the .exe is.
