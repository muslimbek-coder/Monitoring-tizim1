from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..database import get_conn
from ..exam import finish_session, get_open_blocks_for_class, get_session_payload, save_answer, start_session

router = APIRouter()
TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates" / "student"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    conn = get_conn()
    try:
        locations = [
            dict(row)
            for row in conn.execute(
                """
                SELECT id, viloyat, tuman, maktab
                FROM school_locations
                ORDER BY viloyat, tuman, maktab
                """
            ).fetchall()
        ]
    finally:
        conn.close()
    return templates.TemplateResponse(
        "select.html",
        {"request": request, "step": "sinf", "locations": locations},
    )


@router.post("/select-class", response_class=HTMLResponse)
def select_class(
    request: Request,
    sinf: int = Form(...),
    location_id: int = Form(...),
):
    if not 1 <= sinf <= 11:
        raise HTTPException(status_code=400, detail="Sinf 1 dan 11 gacha bo'lishi kerak.")

    conn = get_conn()
    try:
        location = conn.execute(
            "SELECT id, viloyat, tuman, maktab FROM school_locations WHERE id = ?",
            (location_id,),
        ).fetchone()
        if not location:
            raise HTTPException(status_code=400, detail="Maktab tanlanmagan.")
        students = conn.execute(
            """
            SELECT id, fish FROM students
            WHERE sinf = ? AND school_location_id = ? AND is_active = 1
            ORDER BY fish
            """,
            (sinf, location_id),
        ).fetchall()
    finally:
        conn.close()

    blocks = get_open_blocks_for_class(sinf)
    return templates.TemplateResponse(
        "select.html",
        {
            "request": request,
            "step": "ism",
            "sinf": sinf,
            "location": location,
            "students": students,
            "blocks": blocks,
        },
    )


@router.post("/start-code-prompt", response_class=HTMLResponse)
def start_code_prompt(
    request: Request,
    sinf: int = Form(...),
    student_id: int = Form(...),
    block_id: int = Form(...),
    location_id: int = Form(...),
):
    conn = get_conn()
    try:
        location = conn.execute(
            "SELECT id, viloyat, tuman, maktab FROM school_locations WHERE id = ?",
            (location_id,),
        ).fetchone()
        student = conn.execute(
            """
            SELECT id FROM students
            WHERE id = ? AND sinf = ? AND school_location_id = ? AND is_active = 1
            """,
            (student_id, sinf, location_id),
        ).fetchone()
        block = conn.execute(
            "SELECT id FROM blocks WHERE id = ? AND sinf = ? AND is_open = 1",
            (block_id, sinf),
        ).fetchone()
        if not location or not student or not block:
            raise HTTPException(status_code=400, detail="Tanlangan ma'lumotlar mos kelmadi.")
    finally:
        conn.close()

    return templates.TemplateResponse(
        "select.html",
        {
            "request": request,
            "step": "kod",
            "sinf": sinf,
            "student_id": student_id,
            "block_id": block_id,
            "location": location,
        },
    )


@router.post("/begin-exam")
def begin_exam(
    request: Request,
    student_id: int = Form(...),
    block_id: int = Form(...),
    entry_code: str = Form(...),
    sinf: int = Form(...),
    location_id: int = Form(...),
):
    conn = get_conn()
    try:
        location = conn.execute(
            "SELECT id, viloyat, tuman, maktab FROM school_locations WHERE id = ?",
            (location_id,),
        ).fetchone()
        student = conn.execute(
            """
            SELECT id FROM students
            WHERE id = ? AND sinf = ? AND school_location_id = ? AND is_active = 1
            """,
            (student_id, sinf, location_id),
        ).fetchone()
        block = conn.execute(
            "SELECT * FROM blocks WHERE id = ? AND sinf = ? AND is_open = 1",
            (block_id, sinf),
        ).fetchone()
        existing = None
        if location and student and block:
            existing = conn.execute(
                """
                SELECT id, status FROM sessions
                WHERE student_id = ? AND block_id = ?
                """,
                (student_id, block_id),
            ).fetchone()
    finally:
        conn.close()

    if (
        not location
        or not student
        or not block
        or (block["entry_code"] or "") != entry_code.strip()
    ):
        return templates.TemplateResponse(
            "select.html",
            {
                "request": request,
                "step": "kod",
                "sinf": sinf,
                "student_id": student_id,
                "block_id": block_id,
                "location": location,
                "error": "Kirish kodi noto'g'ri",
            },
        )

    if existing and existing["status"] == "finished":
        return templates.TemplateResponse(
            "select.html",
            {"request": request, "step": "already_done"},
        )

    session_id = existing["id"] if existing else start_session(student_id, block_id)
    request.session["exam_session_id"] = session_id
    request.session["exam_student_id"] = student_id
    return RedirectResponse(url="/exam", status_code=302)


@router.get("/exam", response_class=HTMLResponse)
def exam_page(request: Request):
    session_id = request.session.get("exam_session_id")
    if not session_id:
        return RedirectResponse(url="/")
    return templates.TemplateResponse("exam.html", {"request": request, "session_id": session_id})


@router.get("/api/exam/{session_id}")
def exam_api(session_id: int):
    return JSONResponse(get_session_payload(session_id))


@router.post("/api/exam/{session_id}/answer")
async def exam_answer(session_id: int, request: Request):
    body = await request.json()
    save_answer(session_id, body["session_question_id"], body["option"])
    return {"ok": True}


@router.post("/api/exam/{session_id}/finish")
def exam_finish(session_id: int, request: Request):
    result = finish_session(session_id)
    conn = get_conn()
    student_id = request.session.get("exam_student_id")
    student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    conn.close()
    request.session.pop("exam_session_id", None)
    result["login"] = f"O{student['id']}" if student else ""
    result["password"] = str(student["sinf"]) if student else ""
    return JSONResponse(result)
