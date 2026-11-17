from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from ..database import get_conn
from ..exam import export_class_results_to_excel
from ..security import verify_password

router = APIRouter()
TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates" / "responsible"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _locations() -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT id, viloyat, tuman, maktab
            FROM school_locations
            ORDER BY viloyat, tuman, maktab
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _require_responsible(request: Request):
    responsible_id = request.session.get("responsible_user_id")
    location_id = request.session.get("responsible_location_id")
    if not responsible_id or not location_id:
        return RedirectResponse("/responsible/login", status_code=303)

    conn = get_conn()
    try:
        responsible = conn.execute(
            """
            SELECT
                ru.id,
                ru.full_name,
                ru.username,
                sl.id AS location_id,
                sl.viloyat,
                sl.tuman,
                sl.maktab
            FROM responsible_users AS ru
            JOIN school_locations AS sl ON sl.id = ru.school_location_id
            WHERE ru.id = ? AND sl.id = ?
            """,
            (responsible_id, location_id),
        ).fetchone()
        if not responsible:
            request.session.pop("responsible_user_id", None)
            request.session.pop("responsible_location_id", None)
            return RedirectResponse("/responsible/login", status_code=303)
        return responsible
    finally:
        conn.close()


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    if request.session.get("responsible_user_id"):
        return RedirectResponse("/responsible/dashboard", status_code=303)
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "locations": _locations(),
            "error": None,
        },
    )


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    location_id: int = Form(...),
    username: str = Form(...),
    password: str = Form(...),
):
    conn = get_conn()
    try:
        responsible = conn.execute(
            """
            SELECT id, password_hash
            FROM responsible_users
            WHERE username = ? AND school_location_id = ?
            """,
            (username.strip(), location_id),
        ).fetchone()
    finally:
        conn.close()

    if not responsible or not verify_password(password, responsible["password_hash"]):
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "locations": _locations(),
                "error": "Hudud, login yoki parol noto'g'ri.",
            },
            status_code=401,
        )

    request.session["responsible_user_id"] = responsible["id"]
    request.session["responsible_location_id"] = location_id
    return RedirectResponse("/responsible/dashboard", status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.pop("responsible_user_id", None)
    request.session.pop("responsible_location_id", None)
    return RedirectResponse("/responsible/login", status_code=303)


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    responsible = _require_responsible(request)
    if isinstance(responsible, RedirectResponse):
        return responsible

    conn = get_conn()
    try:
        classes = conn.execute(
            """
            SELECT
                st.sinf,
                COUNT(DISTINCT st.id) AS student_count,
                COUNT(DISTINCT sess.id) AS result_count,
                MAX(sess.finished_at) AS latest_result_at,
                cs.class_teacher_name,
                rc.checked_at
            FROM students AS st
            LEFT JOIN sessions AS sess
                ON sess.student_id = st.id AND sess.status = 'finished'
            LEFT JOIN class_settings AS cs
                ON cs.school_location_id = st.school_location_id
                AND cs.sinf = st.sinf
            LEFT JOIN responsible_checks AS rc
                ON rc.responsible_user_id = ? AND rc.sinf = st.sinf
            WHERE st.school_location_id = ?
            GROUP BY st.sinf, cs.class_teacher_name, rc.checked_at
            ORDER BY st.sinf
            """,
            (responsible["id"], responsible["location_id"]),
        ).fetchall()
    finally:
        conn.close()

    class_rows = []
    for row in classes:
        item = dict(row)
        item["needs_review"] = bool(
            item["checked_at"]
            and item["latest_result_at"]
            and item["latest_result_at"] > item["checked_at"]
        )
        class_rows.append(item)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "responsible": responsible,
            "classes": class_rows,
        },
    )


@router.get("/classes/{sinf}", response_class=HTMLResponse)
def class_results(request: Request, sinf: int):
    responsible = _require_responsible(request)
    if isinstance(responsible, RedirectResponse):
        return responsible
    if not 1 <= sinf <= 11:
        raise HTTPException(status_code=404, detail="Sinf topilmadi.")

    conn = get_conn()
    try:
        class_setting = conn.execute(
            """
            SELECT class_teacher_name FROM class_settings
            WHERE school_location_id = ? AND sinf = ?
            """,
            (responsible["location_id"], sinf),
        ).fetchone()
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
            (responsible["location_id"], sinf),
        ).fetchall()
        check = conn.execute(
            """
            SELECT checked_at FROM responsible_checks
            WHERE responsible_user_id = ? AND sinf = ?
            """,
            (responsible["id"], sinf),
        ).fetchone()

        result_rows = []
        latest_result_at = None
        for row in records:
            item = dict(row)
            item["subjects"] = []
            if item["session_id"]:
                latest_result_at = max(
                    latest_result_at or item["finished_at"],
                    item["finished_at"],
                )
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
                    (item["session_id"],),
                ).fetchall()
                item["subjects"] = [
                    {
                        "name": subject["name"],
                        "total": subject["total"],
                        "correct": subject["correct"],
                        "percent": round(
                            subject["correct"] / subject["total"] * 100
                        )
                        if subject["total"]
                        else 0,
                    }
                    for subject in subjects
                ]
                item["score"] = round(
                    item["total_correct"] / item["total_questions"] * 100
                ) if item["total_questions"] else 0
            result_rows.append(item)
    finally:
        conn.close()

    checked_at = check["checked_at"] if check else None
    needs_review = bool(
        checked_at and latest_result_at and latest_result_at > checked_at
    )
    is_checked = bool(checked_at and not needs_review)
    return templates.TemplateResponse(
        "class.html",
        {
            "request": request,
            "responsible": responsible,
            "sinf": sinf,
            "class_teacher": (
                class_setting["class_teacher_name"] if class_setting else ""
            ),
            "results": result_rows,
            "checked_at": checked_at,
            "is_checked": is_checked,
            "needs_review": needs_review,
        },
    )


@router.post("/classes/{sinf}/check")
def mark_class_checked(request: Request, sinf: int):
    responsible = _require_responsible(request)
    if isinstance(responsible, RedirectResponse):
        return responsible
    if not 1 <= sinf <= 11:
        raise HTTPException(status_code=404, detail="Sinf topilmadi.")

    conn = get_conn()
    try:
        student = conn.execute(
            """
            SELECT 1 FROM students
            WHERE school_location_id = ? AND sinf = ?
            LIMIT 1
            """,
            (responsible["location_id"], sinf),
        ).fetchone()
        if not student:
            raise HTTPException(status_code=404, detail="Bu sinfda o'quvchilar yo'q.")
        conn.execute(
            """
            INSERT INTO responsible_checks
                (responsible_user_id, sinf, checked_at)
            VALUES (?, ?, ?)
            ON CONFLICT(responsible_user_id, sinf)
            DO UPDATE SET checked_at = excluded.checked_at
            """,
            (
                responsible["id"],
                sinf,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(
        f"/responsible/classes/{sinf}",
        status_code=303,
    )


@router.get("/classes/{sinf}/export")
def export_class(request: Request, sinf: int):
    responsible = _require_responsible(request)
    if isinstance(responsible, RedirectResponse):
        return responsible
    if not 1 <= sinf <= 11:
        raise HTTPException(status_code=404, detail="Sinf topilmadi.")

    conn = get_conn()
    try:
        check = conn.execute(
            """
            SELECT checked_at FROM responsible_checks
            WHERE responsible_user_id = ? AND sinf = ?
            """,
            (responsible["id"], sinf),
        ).fetchone()
        latest_result = conn.execute(
            """
            SELECT MAX(sess.finished_at) AS finished_at
            FROM sessions AS sess
            JOIN students AS st ON st.id = sess.student_id
            WHERE st.school_location_id = ?
                AND st.sinf = ?
                AND sess.status = 'finished'
            """,
            (responsible["location_id"], sinf),
        ).fetchone()["finished_at"]
        student = conn.execute(
            """
            SELECT 1 FROM students
            WHERE school_location_id = ? AND sinf = ?
            LIMIT 1
            """,
            (responsible["location_id"], sinf),
        ).fetchone()
    finally:
        conn.close()

    if not student:
        raise HTTPException(status_code=404, detail="Bu sinfda o'quvchilar yo'q.")
    if not check or (
        latest_result and latest_result > check["checked_at"]
    ):
        raise HTTPException(
            status_code=403,
            detail="Avval sinf natijalarini tekshirilgan deb belgilang.",
        )

    data = export_class_results_to_excel(responsible["location_id"], sinf)
    return StreamingResponse(
        iter([data]),
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": (
                f'attachment; filename="{sinf}-sinf_natijalari.xlsx"'
            )
        },
    )
