"""
Document Expansion Tool — expand a Word study/curriculum precisely.

For humanitarian training material (World Vision): give a .docx and get back a
richer, more professional version — every table preserved, each section expanded
with a strong model, rendered as a clean RTL Arabic Word file. Reliable by design:
if a section can't be expanded it keeps the original, so content is never lost.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from langchain_core.tools import tool

from config import resolve_output_path
from core import doc_expand as _de


@tool
def expand_study_document(
    src: Annotated[str, "مسار مستند Word المصدر (.docx) المراد توسيعه."],
    dest: Annotated[str, "مسار مستند Word الناتج الموسّع (.docx)."],
    instruction: Annotated[str, "توجيه إضافي اختياري (مثل: ركّزي على خطوات التيسير "
                                "والتقييم، أو أضيفي أمثلة من بيئة المخيمات)."] = "",
) -> str:
    """Expand a Word study/curriculum to be more precise and professional using a
    strong model — preserving ALL tables and structure, rendered RTL. Never loses
    content: any section that can't be expanded keeps its original text/tables."""
    try:
        src = str(Path(src).expanduser())
        if not Path(src).exists():
            return f"❌ الملف غير موجود: {src}"
        if Path(src).suffix.lower() != ".docx":
            return "❌ المصدر يجب أن يكون ملف Word (.docx)."
        out = resolve_output_path(dest)
        stats = _de.expand_document(src, out, instruction=instruction)
        grew = stats["words_out"] - stats["words_in"]
        pct = round(100 * grew / stats["words_in"]) if stats["words_in"] else 0
        return (
            f"✅ تم إنشاء الدراسة الموسّعة: {stats['path']}\n"
            f"📚 الأقسام: {stats['sections']} · وُسّع منها: {stats['expanded_sections']}\n"
            f"📊 الجداول: {stats['tables_out']}/{stats['tables_in']} (محفوظة بالكامل)\n"
            f"✍️ الكلمات: {stats['words_in']} → {stats['words_out']} "
            f"(+{grew}، {pct}%+)"
        )
    except Exception as exc:
        return f"❌ expand_study_document: {exc}"
