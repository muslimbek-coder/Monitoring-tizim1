"""
Import funksiyalari:
  - import_students_from_excel: 1-ustun sinfi, 2-ustun F.I.Sh
  - import_questions_from_text: docx yoki txt dan savollar.
      Format:
        # Savol matni
        - Variant A
        - Variant B
        - Variant C
        - Variant D
      To'g'ri variant qatori oldiga "*" belgisi qo'yiladi, masalan:
        *- Toshkent
      (Agar hech biri "*" bilan belgilanmagan bo'lsa, birinchi variant
      to'g'ri deb olinadi va bu holat import natijasida alohida ko'rsatiladi,
      chunki har bir savolda to'g'ri javob matn ichida ko'rsatilishi SHART.)
"""
from __future__ import annotations

import io
import re
import sqlite3
from dataclasses import dataclass, field

import openpyxl
from docx import Document

from .database import get_conn


@dataclass
class ParsedQuestion:
    text: str
    options: list[str] = field(default_factory=list)
    correct_index: int = 0  # 0..3


def import_students_from_excel(
    file_bytes: bytes,
    school_location_id: int | None = None,
) -> dict:
    """Excelning sinf va F.I.Sh. ustunlarini tanlangan maktabga biriktiradi."""
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    ws = wb.active

    added, skipped = 0, 0
    conn = get_conn()
    try:
        for row in ws.iter_rows(min_row=1, values_only=True):
            if not row or row[0] is None or row[1] is None:
                continue
            sinf_raw, fish_raw = row[0], row[1]
            try:
                sinf = int(str(sinf_raw).strip().split("-")[0])
            except ValueError:
                continue
            fish = str(fish_raw).strip()
            if not fish or not (1 <= sinf <= 11):
                continue

            if school_location_id is not None:
                updated = conn.execute(
                    """
                    UPDATE students
                    SET school_location_id = ?, is_active = 1
                    WHERE sinf = ? AND fish = ? AND school_location_id IS NULL
                    """,
                    (school_location_id, sinf, fish),
                )
                if updated.rowcount:
                    added += 1
                    continue

            try:
                conn.execute(
                    """
                    INSERT INTO students (sinf, fish, school_location_id)
                    VALUES (?, ?, ?)
                    """,
                    (sinf, fish, school_location_id),
                )
                added += 1
            except sqlite3.IntegrityError:
                restored = conn.execute(
                    """
                    UPDATE students SET is_active = 1
                    WHERE sinf = ? AND fish = ? AND school_location_id IS ?
                        AND is_active = 0
                    """,
                    (sinf, fish, school_location_id),
                )
                if restored.rowcount:
                    added += 1
                else:
                    skipped += 1
        conn.commit()
    finally:
        conn.close()
    return {"added": added, "skipped": skipped}


def _parse_question_blocks(raw_text: str) -> list[ParsedQuestion]:
    lines = [ln.rstrip() for ln in raw_text.splitlines()]
    questions: list[ParsedQuestion] = []
    current: ParsedQuestion | None = None

    for ln in lines:
        stripped = ln.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            if current and current.options:
                questions.append(current)
            current = ParsedQuestion(text=stripped.lstrip("#").strip())
        elif stripped.startswith("-") or stripped.startswith("*-") or stripped.startswith("* -"):
            if current is None:
                continue
            is_correct = stripped.startswith("*")
            option_text = re.sub(r"^\*?\s*-\s*", "", stripped).strip()
            if is_correct:
                current.correct_index = len(current.options)
            current.options.append(option_text)
    if current and current.options:
        questions.append(current)
    return questions


def extract_text_from_upload(filename: str, file_bytes: bytes) -> str:
    if filename.lower().endswith(".docx"):
        doc = Document(io.BytesIO(file_bytes))
        return "\n".join(p.text for p in doc.paragraphs)
    return file_bytes.decode("utf-8", errors="ignore")


def import_questions_for_subject(subject_id: int, filename: str, file_bytes: bytes) -> dict:
    raw_text = extract_text_from_upload(filename, file_bytes)
    parsed = _parse_question_blocks(raw_text)
    if any(len(question.options) != 4 for question in parsed):
        raise ValueError(
            "Har bir savolda aynan 4 ta javob varianti bo'lishi kerak."
        )

    conn = get_conn()
    added = 0
    for q in parsed:
        opts = (q.options + [None, None, None, None])[:4]
        conn.execute(
            """INSERT INTO questions
               (subject_id, question_text, option_a, option_b, option_c, option_d, correct_option)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                subject_id,
                q.text,
                opts[0],
                opts[1],
                opts[2],
                opts[3],
                "abcd"[q.correct_index],
            ),
        )
        added += 1
    conn.commit()
    conn.close()
    return {"added": added, "total_parsed": len(parsed)}
