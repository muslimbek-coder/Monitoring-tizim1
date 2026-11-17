import random
from datetime import datetime, timedelta, timezone

import openpyxl
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from .database import get_conn

EXAM_MINUTES = 90
QUESTIONS_PER_SUBJECT = 15


def get_open_blocks_for_class(sinf: int) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        """SELECT b.*, s1.name AS s1name, s2.name AS s2name, s3.name AS s3name
           FROM blocks b
           LEFT JOIN subjects s1 ON s1.id = b.subject1_id
           LEFT JOIN subjects s2 ON s2.id = b.subject2_id
           LEFT JOIN subjects s3 ON s3.id = b.subject3_id
           WHERE b.sinf = ? AND b.is_open = 1""",
        (sinf,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def start_session(student_id: int, block_id: int) -> int:
    """Yangi sessiya yaratadi: har fandan 50 tadan 15 tasini tasodifiy tanlaydi."""
    conn = get_conn()
    block = conn.execute("SELECT * FROM blocks WHERE id = ?", (block_id,)).fetchone()
    if not block:
        conn.close()
        raise ValueError("Blok topilmadi")

    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO sessions (student_id, block_id, started_at, status) VALUES (?, ?, ?, 'started')",
        (student_id, block_id, now),
    )
    session_id = cur.lastrowid

    for subject_id in (block["subject1_id"], block["subject2_id"], block["subject3_id"]):
        if not subject_id:
            continue
        pool = conn.execute(
            "SELECT id FROM questions WHERE subject_id = ?", (subject_id,)
        ).fetchall()
        pool_ids = [r["id"] for r in pool]
        random.shuffle(pool_ids)
        chosen = pool_ids[:QUESTIONS_PER_SUBJECT]
        for pos, qid in enumerate(chosen, start=1):
            conn.execute(
                """INSERT INTO session_questions
                   (session_id, question_id, subject_id, position_in_subject)
                   VALUES (?, ?, ?, ?)""",
                (session_id, qid, subject_id, pos),
            )
    conn.commit()
    conn.close()
    return session_id


def get_session_payload(session_id: int) -> dict:
    """Talaba ekranida ko'rsatish uchun: savollar, variantlar, qolgan vaqt."""
    conn = get_conn()
    session = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not session:
        conn.close()
        raise ValueError("Sessiya topilmadi")

    items = conn.execute(
        """SELECT sq.id AS sq_id, sq.position_in_subject, sq.subject_id,
                  sq.selected_option, s.name AS subject_name,
                  q.question_text, q.option_a, q.option_b, q.option_c, q.option_d
           FROM session_questions sq
           JOIN questions q ON q.id = sq.question_id
           JOIN subjects s ON s.id = sq.subject_id
           WHERE sq.session_id = ?
           ORDER BY sq.subject_id, sq.position_in_subject""",
        (session_id,),
    ).fetchall()
    conn.close()

    started_at = datetime.fromisoformat(session["started_at"])
    deadline = started_at + timedelta(minutes=EXAM_MINUTES)
    remaining = (deadline - datetime.now(timezone.utc)).total_seconds()

    return {
        "session_id": session_id,
        "status": session["status"],
        "remaining_seconds": max(0, int(remaining)),
        "questions": [dict(r) for r in items],
    }


def save_answer(session_id: int, session_question_id: int, option: str) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE session_questions SET selected_option = ? WHERE id = ? AND session_id = ?",
        (option, session_question_id, session_id),
    )
    conn.commit()
    conn.close()


def finish_session(session_id: int) -> dict:
    conn = get_conn()
    items = conn.execute(
        """SELECT sq.id, sq.subject_id, sq.selected_option, q.correct_option, s.name AS subject_name
           FROM session_questions sq
           JOIN questions q ON q.id = sq.question_id
           JOIN subjects s ON s.id = sq.subject_id
           WHERE sq.session_id = ?""",
        (session_id,),
    ).fetchall()

    per_subject: dict[int, dict] = {}
    total_correct = 0
    for r in items:
        is_correct = 1 if (r["selected_option"] and r["selected_option"] == r["correct_option"]) else 0
        conn.execute(
            "UPDATE session_questions SET is_correct = ? WHERE id = ?", (is_correct, r["id"])
        )
        total_correct += is_correct
        bucket = per_subject.setdefault(
            r["subject_id"], {"name": r["subject_name"], "correct": 0, "total": 0}
        )
        bucket["total"] += 1
        bucket["correct"] += is_correct

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE sessions SET status = 'finished', finished_at = ? WHERE id = ?",
        (now, session_id),
    )
    conn.commit()
    conn.close()

    total_questions = sum(b["total"] for b in per_subject.values()) or 1
    score_100 = round(total_correct / total_questions * 100)
    for b in per_subject.values():
        b["percent"] = round(b["correct"] / b["total"] * 100) if b["total"] else 0

    return {
        "total_correct": total_correct,
        "total_questions": total_questions,
        "score_100": score_100,
        "per_subject": list(per_subject.values()),
    }


def export_block_results_to_excel(block_id: int) -> bytes:
    """Blok bo'yicha barcha tugatilgan sessiyalarni hisobot-jadvaliga yig'adi,
    ostiga Monitoring raisi/kotibi/a'zolari imzo shablonini qo'shadi."""
    conn = get_conn()
    block = conn.execute(
        """SELECT b.*, s1.name AS s1n, s2.name AS s2n, s3.name AS s3n
           FROM blocks b
           LEFT JOIN subjects s1 ON s1.id=b.subject1_id
           LEFT JOIN subjects s2 ON s2.id=b.subject2_id
           LEFT JOIN subjects s3 ON s3.id=b.subject3_id
           WHERE b.id = ?""",
        (block_id,),
    ).fetchone()
    subject_names = [n for n in (block["s1n"], block["s2n"], block["s3n"]) if n]

    sessions = conn.execute(
        """SELECT sess.id, st.fish FROM sessions sess
           JOIN students st ON st.id = sess.student_id
           WHERE sess.block_id = ? AND sess.status = 'finished'
           ORDER BY st.fish""",
        (block_id,),
    ).fetchall()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"{block['sinf']}-sinf {block['chorak']}ch {block['blok']}blok"

    bold = Font(bold=True)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # --- sarlavha qatorlari ---
    ws.cell(row=1, column=1, value="O'quvchi F.I.Sh").font = bold
    ws.merge_cells(start_row=1, start_column=1, end_row=2, end_column=1)
    col = 2
    subject_col_start = {}
    for name in subject_names:
        subject_col_start[name] = col
        ws.merge_cells(start_row=1, start_column=col, end_row=1, end_column=col + QUESTIONS_PER_SUBJECT - 1)
        c = ws.cell(row=1, column=col, value=name)
        c.font = bold
        c.alignment = center
        for i in range(QUESTIONS_PER_SUBJECT):
            hc = ws.cell(row=2, column=col + i, value=i + 1)
            hc.alignment = center
        col += QUESTIONS_PER_SUBJECT
    for extra in ("To'g'ri", "Noto'g'ri", "Ball (100)"):
        ws.merge_cells(start_row=1, start_column=col, end_row=2, end_column=col)
        hc = ws.cell(row=1, column=col, value=extra)
        hc.font = bold
        hc.alignment = center
        col += 1

    # --- har bir o'quvchi uchun qator ---
    row = 3
    for s in sessions:
        ws.cell(row=row, column=1, value=s["fish"])
        items = conn.execute(
            """SELECT sq.subject_id, sq.position_in_subject, sq.is_correct, sub.name AS subject_name
               FROM session_questions sq JOIN subjects sub ON sub.id = sq.subject_id
               WHERE sq.session_id = ?""",
            (s["id"],),
        ).fetchall()
        total_correct = 0
        total_q = 0
        for it in items:
            start = subject_col_start.get(it["subject_name"])
            if start is None:
                continue
            col_idx = start + it["position_in_subject"] - 1
            val = 1 if it["is_correct"] else 0
            ws.cell(row=row, column=col_idx, value=val)
            total_correct += val
            total_q += 1
        last_col = col - 3
        ws.cell(row=row, column=last_col, value=total_correct)
        ws.cell(row=row, column=last_col + 1, value=total_q - total_correct)
        ws.cell(row=row, column=last_col + 2, value=round(total_correct / total_q * 100) if total_q else 0)
        row += 1
    conn.close()

    # --- mas'ul shaxs va imzo shabloni ---
    row += 2
    ws.cell(row=row, column=1, value=f"Mas'ul: {block['responsible_name'] or '____________________'}").font = bold
    row += 2
    signers = [
        ("Monitoring raisi", ""),
        ("Kotibi", ""),
        ("1-a'zo", ""),
        ("2-a'zo", ""),
        ("3-a'zo", ""),
        ("4-a'zo", ""),
    ]
    for title, _ in signers:
        ws.cell(row=row, column=1, value=title).font = bold
        ws.cell(row=row, column=2, value="F.I.Sh: ______________________")
        ws.cell(row=row, column=4, value="Imzo: ______________")
        row += 1

    for c in range(1, col):
        ws.column_dimensions[get_column_letter(c)].width = 10

    import io as _io
    buf = _io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
