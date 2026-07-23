---
name: android-app-testing
description: Install and test an app on the Android emulator, drive the UI, verify visually, fix and repeat
triggers: [أندرويد, اندرويد, محاكي, apk, تطبيق أندرويد, android, emulator, install app, اختبار تطبيق]
---

# Skill: Android App Testing (emulator)

## 1. Ensure a device/emulator is ready
- `android_devices` to list connected devices/emulators. If none, start the emulator
  (via the SDK emulator command in `terminal_run`, e.g. `emulator -avd <name>`), then
  wait and re-check `android_devices` until one is "device".

## 2. Install
- `android_install_apk(path=...)` for the build under test. If install fails (missing
  SDK/adb, version conflict) resolve it (download SDK/adb, uninstall old with
  `android_uninstall_app`) then retry.

## 3. Launch & SEE
- `android_launch_app(package=...)`, then `android_screenshot` and `analyze_screen`
  to confirm it opened correctly (not a crash/blank/ANR).

## 4. Drive the test flows
- Interact with `android_tap`, `android_swipe`, `android_input_text`,
  `android_key_event`. After each meaningful step, screenshot + `analyze_screen` to
  verify the expected screen. Use `android_shell` (logcat) to read errors.

## 5. Fix & repeat
- On a crash/wrong screen: read logcat, fix the code, rebuild the APK, reinstall,
  and re-run the flow. Continue until all flows pass.

## 6. Report
- List the flows tested, their results, any bugs found + fixed, and the final state.
