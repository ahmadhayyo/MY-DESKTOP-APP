"""
core/skills.py — a lightweight Skills system for the HAYO agent.

A "skill" is a reusable, named package of METHODOLOGY: step-by-step guidance the
agent can load to do a class of task well (build a desktop app, research the web,
fix an existing project...). This mirrors the reference platform's `.claude/skills`
and Claude Code's skills: instead of re-deriving the right procedure every time,
the agent loads a proven recipe.

Storage
-------
Skills live as markdown files in the repo-level ``skills/`` directory. Each file:

    ---
    name: build-desktop-app
    description: Build a Windows GUI app and package it as an .exe
    triggers: [tkinter, gui, desktop, exe, تطبيق, واجهة]
    ---
    # instructions / methodology in markdown...

The agent calls ``list_skills`` to see what's available and ``load_skill(name)``
to pull the full methodology into context. ``find_relevant`` matches a task
description against skill triggers/description so the planner can auto-suggest one.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

_SKILLS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "skills")


@dataclass
class Skill:
    name: str
    description: str = ""
    triggers: list[str] = field(default_factory=list)
    body: str = ""
    path: str = ""


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Return (metadata, body). Tolerates files with no frontmatter."""
    if text.startswith("---"):
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
        if m:
            raw_meta, body = m.group(1), m.group(2)
            meta: dict = {}
            for line in raw_meta.splitlines():
                if ":" not in line:
                    continue
                key, _, val = line.partition(":")
                key = key.strip().lower()
                val = val.strip()
                if key == "triggers":
                    val = val.strip("[]")
                    meta[key] = [t.strip().strip("'\"") for t in val.split(",") if t.strip()]
                else:
                    meta[key] = val
            return meta, body.strip()
    return {}, text.strip()


def _load_skill_file(path: str) -> Skill | None:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except Exception:
        return None
    meta, body = _parse_frontmatter(text)
    name = meta.get("name") or os.path.splitext(os.path.basename(path))[0]
    triggers = meta.get("triggers") or []
    if isinstance(triggers, str):
        triggers = [t.strip() for t in triggers.split(",") if t.strip()]
    return Skill(
        name=str(name).strip(),
        description=str(meta.get("description", "")).strip(),
        triggers=[str(t).lower() for t in triggers],
        body=body,
        path=path,
    )


def _all_skill_files(skills_dir: str | None = None) -> list[str]:
    d = skills_dir or _SKILLS_DIR
    if not os.path.isdir(d):
        return []
    return [os.path.join(d, f) for f in sorted(os.listdir(d))
            if f.lower().endswith((".md", ".markdown"))]


def load_all(skills_dir: str | None = None) -> list[Skill]:
    out: list[Skill] = []
    for p in _all_skill_files(skills_dir):
        s = _load_skill_file(p)
        if s and s.name:
            out.append(s)
    return out


def get_skill(name: str, skills_dir: str | None = None) -> Skill | None:
    target = (name or "").strip().lower()
    for s in load_all(skills_dir):
        if s.name.lower() == target:
            return s
    # tolerate filename-style names ("build-desktop-app" vs "Build Desktop App")
    slug = re.sub(r"[\s_]+", "-", target)
    for s in load_all(skills_dir):
        if re.sub(r"[\s_]+", "-", s.name.lower()) == slug:
            return s
    return None


def find_relevant(query: str, limit: int = 3, skills_dir: str | None = None) -> list[Skill]:
    """Rank skills by how well their triggers/description match `query`."""
    q = (query or "").lower()
    if not q:
        return []
    scored: list[tuple[int, Skill]] = []
    for s in load_all(skills_dir):
        score = 0
        for trig in s.triggers:
            if trig and trig in q:
                score += 2
        for word in re.findall(r"\w+", s.description.lower()):
            if len(word) > 3 and word in q:
                score += 1
        if score:
            scored.append((score, s))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [s for _, s in scored[:limit]]


def render_index(skills_dir: str | None = None) -> str:
    skills = load_all(skills_dir)
    if not skills:
        return "لا توجد مهارات متاحة بعد."
    lines = [f"🧩 المهارات المتاحة ({len(skills)}):"]
    for s in skills:
        lines.append(f"  • **{s.name}** — {s.description}")
    return "\n".join(lines)


if __name__ == "__main__":  # smoke test
    skills = load_all()
    print(f"loaded {len(skills)} skills:", [s.name for s in skills])
    if skills:
        rel = find_relevant("ابنِ لي تطبيق tkinter وحوّله exe")
        print("relevant to 'build tkinter exe':", [s.name for s in rel])
    print("skills engine OK")
