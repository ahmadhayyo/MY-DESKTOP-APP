"""
app_builder_tools.py — Build real Windows desktop applications end to end.

The agent can scaffold a project, write the GUI code, lint it, then COMPILE it
into a standalone .exe with PyInstaller — professionally and verifiably. Built for
legitimate apps (tools, utilities, dashboards). Default GUI is tkinter (bundled
with Python → zero extra installs → reliable in a live demo).

Pipeline tools:
  • scaffold_desktop_app(app_name, python_code, dest) — create project + main.py
  • lint_python(path)                                 — syntax + pyflakes warnings
  • build_exe(script_path, app_name, windowed, onefile, icon, dest)
                                                      — compile to .exe, clean up
  • build_desktop_app(app_name, python_code, ...)     — ONE call: scaffold→lint→build
  • run_executable(path, seconds)                     — launch the .exe to verify
  • list_build_tools()                                — what build tools are available
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated

from langchain_core.tools import tool

from config import DESKTOP_DIR

# Use the SAME interpreter the agent runs on, so the build env matches.
_PYEXE = sys.executable


def _venv_pyinstaller() -> str | None:
    """Locate a pyinstaller executable next to the active interpreter, else None."""
    scripts = Path(_PYEXE).parent
    for name in ("pyinstaller.exe", "pyinstaller"):
        cand = scripts / name
        if cand.exists():
            return str(cand)
    return shutil.which("pyinstaller")


def _resolve_dest(dest: str) -> Path:
    if not dest or dest.lower() in ("desktop", "desktop:"):
        return Path(str(DESKTOP_DIR))
    return Path(os.path.expandvars(os.path.expanduser(dest)))


@tool
def list_build_tools() -> str:
    """عرض أدوات البناء المتاحة (PyInstaller، tkinter، pyflakes...) وحالتها."""
    import importlib
    rows = []
    for mod, label in [("PyInstaller", "تجميع EXE"), ("tkinter", "واجهات رسومية"),
                       ("pyflakes", "تدقيق الكود"), ("PIL", "صور/أيقونات"),
                       ("customtkinter", "واجهات حديثة (اختياري)")]:
        try:
            importlib.import_module(mod)
            rows.append(f"  ✅ {mod} — {label}")
        except Exception:
            rows.append(f"  ❌ {mod} — {label} (غير مثبّت)")
    pyi = _venv_pyinstaller()
    rows.append(f"\n  pyinstaller: {pyi or 'غير موجود — ثبّته: pip install pyinstaller'}")
    rows.append(f"  مفسّر البناء: {_PYEXE}")
    return "🧰 أدوات بناء التطبيقات:\n" + "\n".join(rows)


@tool
def scaffold_desktop_app(
    app_name: Annotated[str, "App name (folder + entry file), e.g. 'Calculator'."],
    python_code: Annotated[str, "Full Python source for the app (tkinter GUI recommended)."],
    dest: Annotated[str, "Where to create the project folder. Empty = Desktop."] = "",
) -> str:
    """إنشاء مشروع تطبيق سطح مكتب: مجلد + main.py + requirements.txt + سكربت بناء.

    اكتب كود التطبيق (يُفضّل tkinter لأنه مدمج ولا يحتاج تثبيت). بعدها:
    lint_python ثم build_exe — أو استخدم build_desktop_app لتنفيذ كل ذلك دفعة واحدة.
    """
    try:
        safe = "".join(c for c in app_name if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_") or "App"
        root = _resolve_dest(dest) / f"{safe}_project"
        root.mkdir(parents=True, exist_ok=True)
        main = root / "main.py"
        main.write_text(python_code, encoding="utf-8")
        (root / "requirements.txt").write_text("# add third-party deps here\n", encoding="utf-8")
        (root / "README.txt").write_text(
            f"{app_name}\n\nرُن: python main.py\nبناء EXE: استخدم build_exe على main.py\n",
            encoding="utf-8")
        return (f"✅ تم إنشاء مشروع التطبيق:\n   {root}\n"
                f"   • main.py ({len(python_code)} حرف)\n"
                f"   التالي: lint_python(path='{main}') ثم build_exe(script_path='{main}', app_name='{safe}').")
    except Exception as e:
        return f"❌ خطأ في إنشاء المشروع: {e}"


@tool
def lint_python(
    path: Annotated[str, "Path to a .py file to validate."],
) -> str:
    """تدقيق ملف Python: فحص الأخطاء النحوية + تحذيرات pyflakes (متغيّرات/استيرادات غير مستخدمة...)."""
    p = Path(path)
    if not p.is_file():
        return f"❌ الملف غير موجود: {path}"
    src = p.read_text(encoding="utf-8", errors="replace")
    # 1) syntax
    try:
        compile(src, str(p), "exec")
    except SyntaxError as e:
        return f"❌ خطأ نحوي (السطر {e.lineno}): {e.msg}\n   {e.text or ''}"
    # 2) pyflakes warnings (best-effort)
    warns = ""
    try:
        proc = subprocess.run([_PYEXE, "-m", "pyflakes", str(p)],
                              capture_output=True, text=True, timeout=30)
        warns = (proc.stdout or "").strip()
    except Exception:
        warns = ""
    if warns:
        return f"✅ لا أخطاء نحوية. ⚠️ تحذيرات pyflakes:\n{warns}"
    return "✅ الكود سليم — لا أخطاء نحوية ولا تحذيرات."


@tool
def build_exe(
    script_path: Annotated[str, "Path to the .py entry file to compile."],
    app_name: Annotated[str, "Name for the produced .exe (no extension)."] = "",
    windowed: Annotated[bool, "True = GUI app (no console window). False = console app."] = True,
    onefile: Annotated[bool, "True = single portable .exe. False = folder with deps."] = True,
    icon: Annotated[str, "Optional path to a .ico icon."] = "",
    dest: Annotated[str, "Where to place the final .exe. Empty = Desktop."] = "",
) -> str:
    """تجميع ملف Python إلى تطبيق EXE مستقل باستخدام PyInstaller، ثم تنظيف ملفات البناء.

    ينتج ملف .exe جاهزاً للتشغيل بنقرة، وينقله إلى الوجهة (سطح المكتب افتراضياً).
    """
    p = Path(script_path)
    if not p.is_file():
        return f"❌ ملف المصدر غير موجود: {script_path}"
    pyi = _venv_pyinstaller()
    if not pyi:
        return ("❌ PyInstaller غير مثبّت. ثبّته:\n"
                f"   {_PYEXE} -m pip install pyinstaller")

    name = (app_name or p.stem).strip().replace(" ", "_")
    workdir = p.parent
    build_tmp = workdir / "_build"
    spec_tmp = workdir / "_spec"
    cmd = [pyi, "--noconfirm", "--clean", "--name", name,
           "--distpath", str(workdir / "_dist"),
           "--workpath", str(build_tmp),
           "--specpath", str(spec_tmp)]
    cmd.append("--onefile" if onefile else "--onedir")
    if windowed:
        cmd.append("--windowed")
    if icon and Path(icon).is_file():
        cmd += ["--icon", icon]
    cmd.append(str(p))

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=str(workdir))
    except subprocess.TimeoutExpired:
        return "❌ تجاوز وقت البناء (10 دقائق). جرّب --onedir أو بسّط التطبيق."
    except Exception as e:
        return f"❌ فشل تشغيل PyInstaller: {e}"

    # locate the produced exe
    dist = workdir / "_dist"
    exe = None
    if onefile:
        cand = dist / f"{name}.exe"
        exe = cand if cand.exists() else None
    else:
        cand = dist / name / f"{name}.exe"
        exe = cand if cand.exists() else None

    if not exe:
        tail = (proc.stderr or proc.stdout or "")[-600:]
        return f"❌ لم يُنتَج ملف EXE. مخرجات PyInstaller:\n{tail}"

    # move result to destination
    out_dir = _resolve_dest(dest)
    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / f"{name}.exe"
    try:
        if onefile:
            if final.exists():
                final.unlink()
            shutil.move(str(exe), str(final))
            result_path = str(final)
        else:
            # move the whole folder
            target_folder = out_dir / name
            if target_folder.exists():
                shutil.rmtree(target_folder, ignore_errors=True)
            shutil.move(str(dist / name), str(target_folder))
            result_path = str(target_folder / f"{name}.exe")
    except Exception as e:
        result_path = str(exe)  # leave it where it is
        out_note = f"\n⚠️ تعذّر النقل للوجهة ({e}) — الملف في: {result_path}"
    else:
        out_note = ""

    # clean build artifacts
    for junk in (build_tmp, spec_tmp, dist):
        shutil.rmtree(junk, ignore_errors=True)

    size_mb = 0.0
    try:
        size_mb = os.path.getsize(result_path) / 1048576
    except OSError:
        pass
    return (f"✅ تم بناء التطبيق بنجاح!\n"
            f"   📦 الملف: {result_path}\n"
            f"   الحجم: {size_mb:.1f} ميجابايت | نوع: "
            f"{'GUI' if windowed else 'Console'}, {'onefile' if onefile else 'onedir'}\n"
            f"   جاهز للتشغيل بنقرة مزدوجة." + out_note)


@tool
def build_desktop_app(
    app_name: Annotated[str, "App name."],
    python_code: Annotated[str, "Full Python source (tkinter GUI recommended)."],
    windowed: Annotated[bool, "True = GUI (no console). False = console app."] = True,
    onefile: Annotated[bool, "True = single .exe."] = True,
    dest: Annotated[str, "Output folder. Empty = Desktop."] = "",
) -> str:
    """🏗️ بناء تطبيق سطح مكتب كامل بأمر واحد: كتابة الكود → تدقيق → تجميع EXE.

    أعطِ اسم التطبيق وكوده (يُفضّل tkinter)، وستحصل على ملف EXE احترافي على سطح
    المكتب جاهزاً للتشغيل. مثال كود tkinter بسيط:
        import tkinter as tk
        def hello(): lbl.config(text='مرحباً!')
        root = tk.Tk(); root.title('تطبيقي'); root.geometry('300x150')
        lbl = tk.Label(root, text='اضغط الزر'); lbl.pack(pady=20)
        tk.Button(root, text='ابدأ', command=hello).pack()
        root.mainloop()
    """
    # 1) scaffold
    scaffold = scaffold_desktop_app.invoke(
        {"app_name": app_name, "python_code": python_code, "dest": dest})
    if scaffold.startswith("❌"):
        return scaffold
    safe = "".join(c for c in app_name if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_") or "App"
    main_path = str(_resolve_dest(dest) / f"{safe}_project" / "main.py")

    # 2) lint — abort on syntax error
    lint = lint_python.invoke({"path": main_path})
    if lint.startswith("❌"):
        return f"⛔ توقّف البناء بسبب خطأ في الكود:\n{lint}"

    # 3) build
    build = build_exe.invoke({
        "script_path": main_path, "app_name": safe,
        "windowed": windowed, "onefile": onefile, "dest": dest,
    })
    return f"🏗️ خط بناء التطبيق:\n\n1) {scaffold.splitlines()[0]}\n2) {lint}\n\n3) {build}"


@tool
def run_executable(
    path: Annotated[str, "Path to the .exe (or .py) to launch."],
    seconds: Annotated[int, "How long to let it run before reporting (GUI apps keep running)."] = 4,
) -> str:
    """تشغيل تطبيق (EXE أو سكربت) للتأكد من أنه يعمل — يلتقط أي تعطّل مبكّر."""
    p = Path(path)
    if not p.is_file():
        return f"❌ الملف غير موجود: {path}"
    try:
        if p.suffix.lower() == ".py":
            proc = subprocess.Popen([_PYEXE, str(p)], cwd=str(p.parent),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        else:
            proc = subprocess.Popen([str(p)], cwd=str(p.parent),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(max(1, min(seconds, 15)))
        if proc.poll() is None:
            # still running → GUI launched successfully; leave it open for the demo
            return f"✅ التطبيق يعمل الآن (نافذة مفتوحة): {p.name}"
        # exited quickly → capture why
        out, err = proc.communicate(timeout=5)
        code = proc.returncode
        msg = (err or out or b"").decode("utf-8", "replace")[-500:]
        if code == 0:
            return f"✅ التطبيق نُفّذ وأُغلق طبيعياً (رمز 0).\n{msg}"
        return f"⚠️ التطبيق خرج برمز {code}:\n{msg}"
    except Exception as e:
        return f"❌ تعذّر تشغيل التطبيق: {e}"
