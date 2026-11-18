from datetime import datetime, timezone

import openpyxl
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from .database import get_conn
from .signers import SIGNER_ROLES

QUESTIONS_PER_SUBJECT = 15
EXAM_DURATION_SECONDS = 90 * 60


def get_open_blocks_for_class(sinf: int) -> list:
    """O'quvchi sinfi uchun ochiq bloklarni fan nomlari bilan qaytaradi."""
    conn = get_conn()
    try:
        return conn.execute(
            """
            SELECT
                b.*,
                s1.name AS s1name,
                s2.name AS s2name,
                s3.name AS s3name
            FROM blocks AS b
            LEFT JOIN subjects AS s1 ON s1.id = b.subject1_id
            LEFT JOIN subjects AS s2 ON s2.id = b.subject2_id
            LEFT JOIN subjects AS s3 ON s3.id = b.subject3_id
            WHERE b.sinf = ? AND b.is_open = 1
            ORDER BY b.chorak, b.blok
            """,
            (sinf,),
        ).fetchall()
    finally:
        conn.close()


def start_session(student_id: int, block_id: int) -> int:
    """Sessiya yaratib, har bir blok fanidan 15 tadan savol tanlaydi."""
    conn = get_conn()
    try:
        student = conn.execute(
            "SELECT sinf FROM students WHERE id = ?",
            (student_id,),
        ).fetchone()
        block = conn.execute(
            "SELECT * FROM blocks WHERE id = ? AND is_open = 1",
            (block_id,),
        ).fetchone()
        if not student or not block or student["sinf"] != block["sinf"]:
            raise ValueError("O'quvchi yoki ochiq test bloki topilmadi.")

        subject_ids = [
            block["subject1_id"],
            block["subject2_id"],
            block["subject3_id"],
        ]
        if any(subject_id is None for subject_id in subject_ids):
            raise ValueError("Test blokida uchta fan to'liq sozlanmagan.")

        questions_by_subject = []
        for subject_id in subject_ids:
            questions = conn.execute(
                """
                SELECT id FROM questions
                WHERE subject_id = ?
                ORDER BY RANDOM()
                LIMIT ?
                """,
                (subject_id, QUESTIONS_PER_SUBJECT),
            ).fetchall()
            if len(questions) < QUESTIONS_PER_SUBJECT:
                raise ValueError(
                    "Har bir fan uchun kamida 15 ta test savoli bo'lishi kerak."
                )
            questions_by_subject.append((subject_id, questions))

        started_at = datetime.now(timezone.utc).isoformat()
        cursor = conn.execute(
            """
            INSERT INTO sessions (student_id, block_id, started_at)
            VALUES (?, ?, ?)
            """,
            (student_id, block_id, started_at),
        )
        session_id = cursor.lastrowid

        for subject_id, questions in questions_by_subject:
            conn.executemany(
                """
                INSERT INTO session_questions
                    (session_id, question_id, subject_id, position_in_subject)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (session_id, question["id"], subject_id, position)
                    for position, question in enumerate(questions, start=1)
                ],
            )

        conn.commit()
        return session_id
    finally:
        conn.close()


def get_session_payload(session_id: int) -> dict:
    """Imtihon sahifasiga savollarni va qolgan vaqtni tayyorlaydi."""
    conn = get_conn()
    try:
        session = conn.execute(
            "SELECT started_at FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if not session:
            raise ValueError("Test sessiyasi topilmadi.")

        started_at = datetime.fromisoformat(session["started_at"])
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
        remaining_seconds = max(
            0,
            EXAM_DURATION_SECONDS - int(elapsed),
        )

        questions = conn.execute(
            """
            SELECT
                sq.id AS sq_id,
                sq.position_in_subject,
                sq.selected_option,
                sub.name AS subject_name,
                q.question_text,
                q.option_a,
                q.option_b,
                q.option_c,
                q.option_d
            FROM session_questions AS sq
            JOIN questions AS q ON q.id = sq.question_id
            JOIN subjects AS sub ON sub.id = sq.subject_id
            WHERE sq.session_id = ?
            ORDER BY sq.id
            """,
            (session_id,),
        ).fetchall()

        return {
            "remaining_seconds": remaining_seconds,
            "questions": [dict(question) for question in questions],
        }
    finally:
        conn.close()


def save_answer(session_id: int, session_question_id: int, option: str) -> None:
    """O'quvchi javobini tekshiradi va saqlaydi."""
    if option not in ("a", "b", "c", "d"):
        raise ValueError("Javob varianti noto'g'ri.")

    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT
                sess.status,
                q.correct_option,
                q.option_a,
                q.option_b,
                q.option_c,
                q.option_d
            FROM session_questions AS sq
            JOIN sessions AS sess ON sess.id = sq.session_id
            JOIN questions AS q ON q.id = sq.question_id
            WHERE sq.id = ? AND sq.session_id = ?
            """,
            (session_question_id, session_id),
        ).fetchone()
        if not row:
            raise ValueError("Savol ushbu test sessiyasiga tegishli emas.")
        if row["status"] != "started":
            raise ValueError("Yakunlangan test javoblarini o'zgartirib bo'lmaydi.")
        if not row[f"option_{option}"]:
            raise ValueError("Tanlangan javob varianti mavjud emas.")

        conn.execute(
            """
            UPDATE session_questions
            SET selected_option = ?, is_correct = ?
            WHERE id = ? AND session_id = ?
            """,
            (
                option,
                int(option == row["correct_option"]),
                session_question_id,
                session_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def finish_session(session_id: int) -> dict:
    """Testni yakunlab, umumiy va fanlar bo'yicha natijalarni qaytaradi."""
    conn = get_conn()
    try:
        session = conn.execute(
            "SELECT status FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if not session:
            raise ValueError("Test sessiyasi topilmadi.")

        if session["status"] == "started":
            conn.execute(
                """
                UPDATE session_questions
                SET is_correct = CASE
                    WHEN selected_option IS NOT NULL
                         AND is_correct = 1 THEN 1
                    ELSE 0
                END
                WHERE session_id = ?
                """,
                (session_id,),
            )
            conn.execute(
                """
                UPDATE sessions
                SET status = 'finished', finished_at = ?
                WHERE id = ? AND status = 'started'
                """,
                (datetime.now(timezone.utc).isoformat(), session_id),
            )
            conn.commit()

        per_subject = conn.execute(
            """
            SELECT
                sub.name,
                COUNT(*) AS total,
                COALESCE(SUM(sq.is_correct), 0) AS correct
            FROM session_questions AS sq
            JOIN subjects AS sub ON sub.id = sq.subject_id
            WHERE sq.session_id = ?
            GROUP BY sq.subject_id, sub.name
            ORDER BY MIN(sq.id)
            """,
            (session_id,),
        ).fetchall()

        subjects = [
            {
                "name": item["name"],
                "correct": item["correct"],
                "total": item["total"],
                "percent": round(item["correct"] / item["total"] * 100)
                if item["total"]
                else 0,
            }
            for item in per_subject
        ]
        total_correct = sum(item["correct"] for item in subjects)
        total_questions = sum(item["total"] for item in subjects)
        return {
            "total_correct": total_correct,
            "total_questions": total_questions,
            "score_100": round(total_correct / total_questions * 100)
            if total_questions
            else 0,
            "per_subject": subjects,
        }
    finally:
        conn.close()


def export_block_results_to_excel(block_id: int) -> bytes:
    """Blok bo'yicha tugatilgan sessiyalarni Excel hisobotiga yig'adi."""
    conn = get_conn()

    try:
        block = conn.execute(
            """SELECT b.*, s1.name AS s1n, s2.name AS s2n, s3.name AS s3n
               FROM blocks b
               LEFT JOIN subjects s1 ON s1.id = b.subject1_id
               LEFT JOIN subjects s2 ON s2.id = b.subject2_id
               LEFT JOIN subjects s3 ON s3.id = b.subject3_id
               WHERE b.id = ?""",
            (block_id,),
        ).fetchone()

        # ENG MUHIM TUZATISH: blok mavjudligini tekshirish
        if block is None:
            raise ValueError(f"{block_id}-ID li blok topilmadi.")

        signer_names = {
            row["role"]: row["full_name"]
            for row in conn.execute(
                "SELECT role, full_name FROM monitoring_signers"
            ).fetchall()
        }

        subject_names = [
            n for n in (block["s1n"], block["s2n"], block["s3n"]) if n
        ]

        sessions = conn.execute(
            """SELECT sess.id, st.fish
               FROM sessions sess
               JOIN students st ON st.id = sess.student_id
               WHERE sess.block_id = ? AND sess.status = 'finished'
               ORDER BY st.fish""",
            (block_id,),
        ).fetchall()

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = f"{block['sinf']}-sinf {block['chorak']}ch {block['blok']}blok"[:31]

        bold = Font(bold=True)
        center = Alignment(
            horizontal="center",
            vertical="center",
            wrap_text=True
        )

        # Sarlavhalar
        ws.cell(row=1, column=1, value="O'quvchi F.I.Sh").font = bold
        ws.merge_cells(start_row=1, start_column=1, end_row=2, end_column=1)

        col = 2
        subject_col_start = {}

        for name in subject_names:
            subject_col_start[name] = col

            ws.merge_cells(
                start_row=1,
                start_column=col,
                end_row=1,
                end_column=col + QUESTIONS_PER_SUBJECT - 1,
            )

            c = ws.cell(row=1, column=col, value=name)
            c.font = bold
            c.alignment = center

            for i in range(QUESTIONS_PER_SUBJECT):
                hc = ws.cell(row=2, column=col + i, value=i + 1)
                hc.alignment = center

            col += QUESTIONS_PER_SUBJECT

        for extra in ("To'g'ri", "Noto'g'ri", "Ball (100)"):
            ws.merge_cells(
                start_row=1,
                start_column=col,
                end_row=2,
                end_column=col,
            )
            hc = ws.cell(row=1, column=col, value=extra)
            hc.font = bold
            hc.alignment = center
            col += 1

        # O'quvchilar natijalari
        row = 3

        for s in sessions:
            ws.cell(row=row, column=1, value=s["fish"])

            items = conn.execute(
                """SELECT sq.subject_id,
                          sq.position_in_subject,
                          sq.is_correct,
                          sub.name AS subject_name
                   FROM session_questions sq
                   JOIN subjects sub ON sub.id = sq.subject_id
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

            percent = round(total_correct / total_q * 100) if total_q else 0
            ws.cell(row=row, column=last_col + 2, value=percent)

            row += 1

        # Mas'ul shaxs va imzolar
        row += 2

        responsible = block["responsible_name"] or "____________________"
        ws.cell(
            row=row,
            column=1,
            value=f"Mas'ul: {responsible}"
        ).font = bold

        row += 2

        for role, title in SIGNER_ROLES:
            ws.cell(row=row, column=1, value=title).font = bold
            full_name = signer_names.get(role, "").strip()
            ws.cell(
                row=row,
                column=2,
                value=f"F.I.Sh: {full_name or '______________________'}",
            )
            ws.cell(row=row, column=4, value="Imzo: ______________")
            row += 1

        # Ustunlar kengligi
        for c in range(1, col):
            ws.column_dimensions[get_column_letter(c)].width = 10
        ws.column_dimensions["A"].width = 28
        ws.column_dimensions["B"].width = 36
        ws.column_dimensions["D"].width = 20

        import io

        buf = io.BytesIO()
        wb.save(buf)

        return buf.getvalue()

    finally:
        conn.close()


def export_class_results_to_excel(location_id: int, sinf: int) -> bytes:
    """Mas'ul biriktirilgan maktabning bitta sinfi natijalarini Excelga yozadi."""
    conn = get_conn()
    try:
        location = conn.execute(
            "SELECT viloyat, tuman, maktab FROM school_locations WHERE id = ?",
            (location_id,),
        ).fetchone()
        if not location:
            raise ValueError("Maktab topilmadi.")

        class_setting = conn.execute(
            """
            SELECT class_teacher_name FROM class_settings
            WHERE school_location_id = ? AND sinf = ?
            """,
            (location_id, sinf),
        ).fetchone()
        class_teacher = (
            class_setting["class_teacher_name"] if class_setting else ""
        )

        records = conn.execute(
            """
            SELECT
                st.id AS student_id,
                st.fish,
                sess.id AS session_id,
                sess.finished_at,
                b.chorak,
                b.blok,
                b.test_creator_name,
                COUNT(sq.id) AS total_questions,
                COALESCE(SUM(sq.is_correct), 0) AS total_correct
            FROM students AS st
            LEFT JOIN sessions AS sess
                ON sess.student_id = st.id AND sess.status = 'finished'
            LEFT JOIN blocks AS b ON b.id = sess.block_id
            LEFT JOIN session_questions AS sq ON sq.session_id = sess.id
            WHERE st.school_location_id = ? AND st.sinf = ?
            GROUP BY
                st.id,
                st.fish,
                sess.id,
                sess.finished_at,
                b.chorak,
                b.blok,
                b.test_creator_name
            ORDER BY st.fish, sess.finished_at
            """,
            (location_id, sinf),
        ).fetchall()

        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        worksheet.title = f"{sinf}-sinf natijalari"[:31]
        headers = [
            "Viloyat",
            "Tuman",
            "Maktab",
            "Sinf",
            "Sinf rahbari",
            "O'quvchi F.I.Sh",
            "Chorak",
            "Blok",
            "Test tuzuvchisi",
            "Fanlar bo'yicha natija",
            "To'g'ri javob",
            "Savollar soni",
            "Ball (%)",
            "Tugatilgan vaqt",
        ]
        header_font = Font(bold=True)
        header_alignment = Alignment(horizontal="center", wrap_text=True)
        for column, title in enumerate(headers, start=1):
            cell = worksheet.cell(row=1, column=column, value=title)
            cell.font = header_font
            cell.alignment = header_alignment

        for row_number, record in enumerate(records, start=2):
            subject_results = []
            if record["session_id"]:
                subjects = conn.execute(
                    """
                    SELECT
                        sub.name,
                        COUNT(*) AS total,
                        COALESCE(SUM(sq.is_correct), 0) AS correct
                    FROM session_questions AS sq
                    JOIN subjects AS sub ON sub.id = sq.subject_id
                    WHERE sq.session_id = ?
                    GROUP BY sq.subject_id, sub.name
                    ORDER BY MIN(sq.id)
                    """,
                    (record["session_id"],),
                ).fetchall()
                subject_results = [
                    (
                        f"{subject['name']}: {subject['correct']}/"
                        f"{subject['total']} "
                        f"({round(subject['correct'] / subject['total'] * 100)}%)"
                    )
                    for subject in subjects
                ]

            total_questions = record["total_questions"]
            total_correct = record["total_correct"]
            row_values = [
                location["viloyat"],
                location["tuman"],
                location["maktab"],
                sinf,
                class_teacher,
                record["fish"],
                record["chorak"] or "",
                record["blok"] or "",
                record["test_creator_name"] or "",
                "; ".join(subject_results) or "Natija mavjud emas",
                total_correct if record["session_id"] else "",
                total_questions if record["session_id"] else "",
                round(total_correct / total_questions * 100)
                if total_questions
                else (0 if record["session_id"] else ""),
                record["finished_at"] or "",
            ]
            for column, value in enumerate(row_values, start=1):
                worksheet.cell(row=row_number, column=column, value=value)

        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = f"A1:N{max(len(records) + 1, 1)}"
        widths = (22, 22, 18, 9, 26, 30, 10, 9, 26, 64, 15, 15, 12, 27)
        for column, width in enumerate(widths, start=1):
            worksheet.column_dimensions[get_column_letter(column)].width = width

        import io

        output = io.BytesIO()
        workbook.save(output)
        return output.getvalue()
    finally:
        conn.close()