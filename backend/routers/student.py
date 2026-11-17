from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..database import get_conn
from ..exam import finish_session, get_open_blocks_for_class, get_session_payload, save_answer, start_session

router = APIRouter()
TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates" / "student"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("select.html", {"request": request, "step": "sinf"})


@router.post("/select-class", response_class=HTMLResponse)
def select_class(request: Request, sinf: int = Form(...)):
    conn = get_conn()
    students = conn.execute(
        "SELECT id, fish FROM students WHERE sinf = ? ORDER BY fish", (sinf,)
    ).fetchall()
    blocks = get_open_blocks_for_class(sinf)
    conn.close()
    return templates.TemplateResponse(
        "select.html",
        {"request": request, "step": "ism", "sinf": sinf, "students": students, "blocks": blocks},
    )


@router.post("/start-code-prompt", response_class=HTMLResponse)
def start_code_prompt(request: Request, sinf: int = Form(...), student_id: int = Form(...), block_id: int = Form(...)):
    return templates.TemplateResponse(
        "select.html",
        {"request": request, "step": "kod", "sinf": sinf, "student_id": student_id, "block_id": block_id},
    )


@router.post("/begin-exam")
def begin_exam(request: Request, student_id: int = Form(...), block_id: int = Form(...), entry_code: str = Form(...)):
    conn = get_conn()
    block = conn.execute("SELECT * FROM blocks WHERE id = ?", (block_id,)).fetchone()
    existing = conn.execute(
        "SELECT id, status FROM sessions WHERE student_id = ? AND block_id = ?",
        (student_id, block_id),
    ).fetchone()
    conn.close()

    if not block or (block["entry_code"] or "") != entry_code.strip():
        return templates.TemplateResponse(
            "select.html",
            {
                "request": request,
                "step": "kod",
                "sinf": block["sinf"] if block else None,
                "student_id": student_id,
                "block_id": block_id,
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
    result["login"] = student["fish"] if student else ""
    result["password"] = str(student["sinf"]) if student else ""
    return JSONResponse(result)
