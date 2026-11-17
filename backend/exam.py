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

        signers = [
            "Monitoring raisi",
            "Kotibi",
            "1-a'zo",
            "2-a'zo",
            "3-a'zo",
            "4-a'zo",
        ]

        for title in signers:
            ws.cell(row=row, column=1, value=title).font = bold
            ws.cell(row=row, column=2, value="F.I.Sh: ______________________")
            ws.cell(row=row, column=4, value="Imzo: ______________")
            row += 1

        # Ustunlar kengligi
        for c in range(1, col):
            ws.column_dimensions[get_column_letter(c)].width = 10

        import io

        buf = io.BytesIO()
        wb.save(buf)

        return buf.getvalue()

    finally:
        conn.close()