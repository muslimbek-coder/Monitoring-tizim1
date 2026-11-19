
from pathlib import Path
import sqlite3
from urllib.parse import quote

from fastapi import (
    APIRouter,
    File,
    Form,
    Request,
    UploadFile,
    HTTPException,
)
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.templating import Jinja2Templates

from ..database import get_conn
from ..exam import export_block_results_to_excel
from ..importers import (
    import_questions_for_subject,
    import_students_from_excel,
)
from ..security import hash_password, verify_password
from ..signers import SIGNER_ROLES


router = APIRouter()

TEMPLATES_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "templates"
    / "admin"
)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def ensure_default_admin():
    """Birinchi ishga tushganda boshlang'ich admin yaratadi."""
    conn = get_conn()

    try:
        row = conn.execute(
            "SELECT id FROM admin_users LIMIT 1"
        ).fetchone()

        if not row:
            conn.execute(
                """
                INSERT INTO admin_users (username, password_hash)
                VALUES (?, ?)
                """,
                ("admin", hash_password("admin123")),
            )
            conn.commit()

    finally:
        conn.close()


def _require_admin_or_redirect(request: Request, login_path: str):
    """Admin tizimga kirganligini tekshiradi."""
    if not request.session.get("is_admin"):
        return RedirectResponse(login_path)

    return None


def _is_primary_admin(request: Request) -> bool:
    admin_id = request.session.get("admin_user_id")
    if not request.session.get("is_admin") or not admin_id:
        return False

    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT username FROM admin_users WHERE id = ?",
            (admin_id,),
        ).fetchone()
        return bool(row and row["username"] == "admin")
    finally:
        conn.close()


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": None,
        },
    )


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    conn = get_conn()

    try:
        row = conn.execute(
            "SELECT * FROM admin_users WHERE username = ?",
            (username,),
        ).fetchone()

    finally:
        conn.close()

    if not row or not verify_password(password, row["password_hash"]):
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Login yoki parol noto'g'ri",
            },
        )

    request.session["is_admin"] = True
    request.session["admin_user_id"] = row["id"]

    return RedirectResponse(
        url=str(request.url).rsplit("/login", 1)[0] + "/dashboard",
        status_code=302,
    )


@router.get("/logout")
def logout(request: Request):
    request.session.clear()

    return RedirectResponse(
        url=str(request.url).rsplit("/logout", 1)[0] + "/login"
    )


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    redirect = _require_admin_or_redirect(
        request,
        str(request.url).rsplit("/dashboard", 1)[0] + "/login",
    )

    if redirect:
        return redirect

    conn = get_conn()

    try:
        subjects = conn.execute(
            "SELECT * FROM subjects ORDER BY name"
        ).fetchall()

        blocks = conn.execute(
            """
            SELECT
                b.*,
                s1.name AS s1n,
                s2.name AS s2n,
                s3.name AS s3n
            FROM blocks b
            LEFT JOIN subjects s1 ON s1.id = b.subject1_id
            LEFT JOIN subjects s2 ON s2.id = b.subject2_id
            LEFT JOIN subjects s3 ON s3.id = b.subject3_id
            ORDER BY sinf, chorak, blok
            """
        ).fetchall()

        student_count = conn.execute(
            "SELECT COUNT(*) AS c FROM students WHERE is_active = 1"
        ).fetchone()["c"]

        students = conn.execute(
            """
            SELECT
                st.id, st.sinf, st.fish, st.is_active,
                sl.viloyat, sl.tuman, sl.maktab,
                COUNT(DISTINCT CASE WHEN sess.status = 'finished' THEN sess.id END)
                    AS finished_count,
                COUNT(DISTINCT CASE WHEN sess.status = 'started' THEN sess.id END)
                    AS started_count
            FROM students AS st
            LEFT JOIN school_locations AS sl ON sl.id = st.school_location_id
            LEFT JOIN sessions AS sess ON sess.student_id = st.id
            GROUP BY st.id, sl.viloyat, sl.tuman, sl.maktab
            ORDER BY st.is_active DESC, sl.maktab, st.sinf, st.fish
            """
        ).fetchall()

        subject_question_counts = conn.execute(
            """
            SELECT sub.id, sub.name, COUNT(q.id) AS question_count
            FROM subjects AS sub
            LEFT JOIN questions AS q ON q.subject_id = sub.id
            GROUP BY sub.id
            ORDER BY sub.name
            """
        ).fetchall()

        admins = conn.execute(
            "SELECT id, username FROM admin_users ORDER BY username"
        ).fetchall()

        locations = conn.execute(
            """
            SELECT id, viloyat, tuman, maktab
            FROM school_locations
            ORDER BY viloyat, tuman, maktab
            """
        ).fetchall()

        responsibles = conn.execute(
            """
            SELECT
                ru.id,
                ru.username,
                ru.full_name,
                sl.viloyat,
                sl.tuman,
                sl.maktab
            FROM responsible_users AS ru
            JOIN school_locations AS sl ON sl.id = ru.school_location_id
            ORDER BY sl.viloyat, sl.tuman, sl.maktab, ru.full_name
            """
        ).fetchall()

        class_settings = conn.execute(
            """
            SELECT
                cs.sinf,
                cs.class_teacher_name,
                sl.viloyat,
                sl.tuman,
                sl.maktab
            FROM class_settings AS cs
            JOIN school_locations AS sl ON sl.id = cs.school_location_id
            ORDER BY sl.viloyat, sl.tuman, sl.maktab, cs.sinf
            """
        ).fetchall()

        signer_names = {
            row["role"]: row["full_name"]
            for row in conn.execute(
                "SELECT role, full_name FROM monitoring_signers"
            ).fetchall()
        }

    finally:
        conn.close()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "subjects": subjects,
            "blocks": blocks,
            "student_count": student_count,
            "students": students,
            "admins": admins,
            "admin_can_manage_accounts": _is_primary_admin(request),
            "subject_question_counts": subject_question_counts,
            "locations": locations,
            "responsibles": responsibles,
            "class_settings": class_settings,
            "signer_roles": SIGNER_ROLES,
            "signer_names": signer_names,
            "error": request.query_params.get("error"),
            "notice": request.query_params.get("notice"),
        },
    )


@router.post("/admins/create")
def admin_create(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    base = str(request.url).split("/admins/create")[0]
    redirect = _require_admin_or_redirect(request, base + "/login")
    if redirect:
        return redirect
    if not _is_primary_admin(request):
        return RedirectResponse(
            url=base + "/dashboard?error=Faqat%20asosiy%20admin%20yangi%20admin%20qo%27sha%20oladi",
            status_code=303,
        )

    username = username.strip()
    if not 3 <= len(username) <= 32 or not username.replace("_", "").isalnum():
        return RedirectResponse(
            url=base + "/dashboard?error=Login%203-32%20ta%20harf%20yoki%20raqamdan%20iborat%20bo%27lsin",
            status_code=303,
        )
    if len(password) < 6:
        return RedirectResponse(
            url=base + "/dashboard?error=Parol%20kamida%206%20ta%20belgi%20bo%27lsin",
            status_code=303,
        )

    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO admin_users (username, password_hash) VALUES (?, ?)",
            (username, hash_password(password)),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        return RedirectResponse(
            url=base + "/dashboard?error=Bu%20login%20allaqachon%20mavjud",
            status_code=303,
        )
    finally:
        conn.close()

    return RedirectResponse(
        url=base + "/dashboard?notice=Mas%27ul%20admin%20qo%27shildi",
        status_code=303,
    )


@router.post("/responsibles/create")
def responsible_create(
    request: Request,
    full_name: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    location_id: int = Form(...),
):
    base = str(request.url).split("/responsibles/create")[0]
    redirect = _require_admin_or_redirect(request, base + "/login")
    if redirect:
        return redirect

    full_name = full_name.strip()
    username = username.strip()
    if not full_name or len(full_name) > 100:
        return RedirectResponse(
            url=base + "/dashboard?error=Mas%27ul%20F.I.Sh.ni%20to%27g%27ri%20kiriting",
            status_code=303,
        )
    if not 3 <= len(username) <= 32 or not username.replace("_", "").isalnum():
        return RedirectResponse(
            url=base + "/dashboard?error=Login%203-32%20ta%20harf%20yoki%20raqamdan%20iborat%20bo%27lsin",
            status_code=303,
        )
    if len(password) < 6:
        return RedirectResponse(
            url=base + "/dashboard?error=Parol%20kamida%206%20ta%20belgi%20bo%27lsin",
            status_code=303,
        )

    conn = get_conn()
    try:
        location = conn.execute(
            "SELECT id FROM school_locations WHERE id = ?",
            (location_id,),
        ).fetchone()
        if not location:
            return RedirectResponse(
                url=base + "/dashboard?error=Hudud%20va%20maktabni%20tanlang",
                status_code=303,
            )
        conn.execute(
            """
            INSERT INTO responsible_users
                (username, password_hash, full_name, school_location_id)
            VALUES (?, ?, ?, ?)
            """,
            (username, hash_password(password), full_name, location_id),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        return RedirectResponse(
            url=base + "/dashboard?error=Bu%20maktabda%20ushbu%20login%20mavjud",
            status_code=303,
        )
    finally:
        conn.close()

    return RedirectResponse(
        url=base + "/dashboard?notice=Mas%27ul%20hisobi%20qo%27shildi",
        status_code=303,
    )


@router.post("/classes/save")
def class_settings_save(
    request: Request,
    sinf: int = Form(...),
    class_teacher_name: str = Form(...),
    location_id: int = Form(...),
):
    base = str(request.url).split("/classes/save")[0]
    redirect = _require_admin_or_redirect(request, base + "/login")
    if redirect:
        return redirect

    class_teacher_name = class_teacher_name.strip()
    if not 1 <= sinf <= 11 or not class_teacher_name or len(class_teacher_name) > 100:
        return RedirectResponse(
            url=base + "/dashboard?error=Sinf%20yoki%20sinf%20rahbari%20ma%27lumotini%20tekshiring",
            status_code=303,
        )

    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO class_settings
                (school_location_id, sinf, class_teacher_name)
            VALUES (?, ?, ?)
            ON CONFLICT(school_location_id, sinf)
            DO UPDATE SET class_teacher_name = excluded.class_teacher_name
            """,
            (location_id, sinf, class_teacher_name),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        return RedirectResponse(
            url=base + "/dashboard?error=Hudud%20va%20maktabni%20tanlang",
            status_code=303,
        )
    finally:
        conn.close()

    return RedirectResponse(
        url=base + "/dashboard?notice=Sinf%20rahbari%20saqlandi",
        status_code=303,
    )


@router.post("/signers/save")
def signers_save(
    request: Request,
    chair: str = Form(""),
    secretary: str = Form(""),
    member_1: str = Form(""),
    member_2: str = Form(""),
    member_3: str = Form(""),
    member_4: str = Form(""),
):
    base = str(request.url).split("/signers/save")[0]
    redirect = _require_admin_or_redirect(request, base + "/login")
    if redirect:
        return redirect

    names = {
        "chair": chair.strip(),
        "secretary": secretary.strip(),
        "member_1": member_1.strip(),
        "member_2": member_2.strip(),
        "member_3": member_3.strip(),
        "member_4": member_4.strip(),
    }
    if any(len(name) > 100 for name in names.values()):
        return RedirectResponse(
            url=base + "/dashboard?error=F.I.Sh%20100%20ta%20belgidan%20oshmasin",
            status_code=303,
        )

    conn = get_conn()
    try:
        conn.executemany(
            "UPDATE monitoring_signers SET full_name = ? WHERE role = ?",
            [(names[role], role) for role, _ in SIGNER_ROLES],
        )
        conn.commit()
    finally:
        conn.close()

    return RedirectResponse(
        url=base + "/dashboard?notice=Imzo%20qo%27yuvchilar%20saqlandi",
        status_code=303,
    )


@router.post("/locations/create")
def location_create(
    request: Request,
    viloyat: str = Form(...),
    tuman: str = Form(...),
    maktab: str = Form(...),
):
    base = str(request.url).split("/locations/create")[0]
    redirect = _require_admin_or_redirect(request, base + "/login")
    if redirect:
        return redirect

    values = [viloyat.strip(), tuman.strip(), maktab.strip()]
    if any(not value or len(value) > 64 for value in values):
        return RedirectResponse(
            url=base + "/dashboard?error=Viloyat%2C%20tuman%20va%20maktab%20nomlarini%20to%27g%27ri%20kiriting",
            status_code=303,
        )

    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO school_locations (viloyat, tuman, maktab)
            VALUES (?, ?, ?)
            """,
            values,
        )
        conn.commit()
    finally:
        conn.close()

    return RedirectResponse(
        url=base + "/dashboard?notice=Hudud%20va%20maktab%20saqlandi",
        status_code=303,
    )


@router.post("/students/import")
async def students_import(
    request: Request,
    file: UploadFile = File(...),
    location_id: int = Form(...),
):
    base = str(request.url).split("/students/import")[0]

    redirect = _require_admin_or_redirect(
        request,
        base + "/login",
    )

    if redirect:
        return redirect

    conn = get_conn()
    try:
        location = conn.execute(
            "SELECT id FROM school_locations WHERE id = ?",
            (location_id,),
        ).fetchone()
    finally:
        conn.close()
    if not location:
        raise HTTPException(status_code=400, detail="Maktab tanlanmagan.")

    content = await file.read()

    import_students_from_excel(content, school_location_id=location_id)

    return RedirectResponse(
        url=base + "/dashboard",
        status_code=302,
    )


@router.post("/students/{student_id}/deactivate")
def student_deactivate(request: Request, student_id: int):
    base = str(request.url).split(f"/students/{student_id}/deactivate")[0]
    redirect = _require_admin_or_redirect(request, base + "/login")
    if redirect:
        return redirect

    conn = get_conn()
    try:
        updated = conn.execute(
            "UPDATE students SET is_active = 0 WHERE id = ? AND is_active = 1",
            (student_id,),
        )
        conn.commit()
        if not updated.rowcount:
            return RedirectResponse(
                url=base + "/dashboard?error=Faol%20o%27quvchi%20topilmadi",
                status_code=303,
            )
    finally:
        conn.close()

    return RedirectResponse(
        url=base + "/dashboard?notice=O%27quvchi%20ro%27yxatdan%20chiqarildi",
        status_code=303,
    )


@router.post("/students/{student_id}/activate")
def student_activate(request: Request, student_id: int):
    base = str(request.url).split(f"/students/{student_id}/activate")[0]
    redirect = _require_admin_or_redirect(request, base + "/login")
    if redirect:
        return redirect

    conn = get_conn()
    try:
        updated = conn.execute(
            "UPDATE students SET is_active = 1 WHERE id = ?",
            (student_id,),
        )
        conn.commit()
        if not updated.rowcount:
            return RedirectResponse(
                url=base + "/dashboard?error=O%27quvchi%20topilmadi",
                status_code=303,
            )
    finally:
        conn.close()

    return RedirectResponse(
        url=base + "/dashboard?notice=O%27quvchi%20ro%27yxatga%20qaytarildi",
        status_code=303,
    )


@router.get("/subjects/{subject_id}/questions", response_class=HTMLResponse)
def subject_questions(request: Request, subject_id: int):
    base = str(request.url).split(f"/subjects/{subject_id}/questions")[0]
    redirect = _require_admin_or_redirect(request, base + "/login")
    if redirect:
        return redirect

    conn = get_conn()
    try:
        subject = conn.execute(
            "SELECT id, name FROM subjects WHERE id = ?",
            (subject_id,),
        ).fetchone()
        if not subject:
            raise HTTPException(status_code=404, detail="Fan topilmadi.")
        questions = conn.execute(
            """
            SELECT question_text, option_a, option_b, option_c, option_d,
                correct_option
            FROM questions
            WHERE subject_id = ?
            ORDER BY id
            """,
            (subject_id,),
        ).fetchall()
    finally:
        conn.close()

    return templates.TemplateResponse(
        "questions.html",
        {
            "request": request,
            "subject": subject,
            "questions": questions,
        },
    )


@router.post("/subjects/create")
def subject_create(
    request: Request,
    name: str = Form(...),
):
    base = str(request.url).split("/subjects/create")[0]

    redirect = _require_admin_or_redirect(
        request,
        base + "/login",
    )

    if redirect:
        return redirect

    conn = get_conn()

    try:
        name = name.strip()

        if name:
            conn.execute(
                "INSERT INTO subjects (name) VALUES (?)",
                (name,),
            )
            conn.commit()

    except Exception:
        conn.rollback()

    finally:
        conn.close()

    return RedirectResponse(
        url=base + "/dashboard",
        status_code=302,
    )


@router.post("/subjects/{subject_id}/import-questions")
async def subject_import_questions(
    request: Request,
    subject_id: int,
    file: UploadFile = File(...),
):
    base = str(request.url).split(
        f"/subjects/{subject_id}/import-questions"
    )[0]

    redirect = _require_admin_or_redirect(
        request,
        base + "/login",
    )

    if redirect:
        return redirect

    content = await file.read()

    try:
        import_questions_for_subject(
            subject_id,
            file.filename,
            content,
        )
    except ValueError as exc:
        return RedirectResponse(
            url=base + "/dashboard?error=" + quote(str(exc)),
            status_code=303,
        )

    return RedirectResponse(
        url=base + "/dashboard",
        status_code=302,
    )


@router.post("/blocks/save")
def block_save(
    request: Request,
    sinf: int = Form(...),
    chorak: int = Form(...),
    blok: int = Form(...),
    subject1_id: int = Form(...),
    subject2_id: int = Form(...),
    subject3_id: int = Form(...),
    entry_code: str = Form(...),
    responsible_name: str = Form(""),
    test_creator_name: str = Form(...),
    is_open: str = Form(None),
):
    base = str(request.url).split("/blocks/save")[0]

    redirect = _require_admin_or_redirect(
        request,
        base + "/login",
    )

    if redirect:
        return redirect

    conn = get_conn()

    try:
        conn.execute(
            """
            INSERT INTO blocks (
                sinf,
                chorak,
                blok,
                subject1_id,
                subject2_id,
                subject3_id,
                entry_code,
                responsible_name,
                test_creator_name,
                is_open
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

            ON CONFLICT(sinf, chorak, blok)
            DO UPDATE SET
                subject1_id = excluded.subject1_id,
                subject2_id = excluded.subject2_id,
                subject3_id = excluded.subject3_id,
                entry_code = excluded.entry_code,
                responsible_name = excluded.responsible_name,
                test_creator_name = excluded.test_creator_name,
                is_open = excluded.is_open
            """,
            (
                sinf,
                chorak,
                blok,
                subject1_id,
                subject2_id,
                subject3_id,
                entry_code.strip(),
                responsible_name.strip(),
                test_creator_name.strip(),
                1 if is_open else 0,
            ),
        )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    return RedirectResponse(
        url=base + "/dashboard",
        status_code=302,
    )


@router.get("/blocks/{block_id}/export")
def block_export(
    request: Request,
    block_id: int,
):
    base = str(request.url).split(
        f"/blocks/{block_id}/export"
    )[0]

    redirect = _require_admin_or_redirect(
        request,
        base + "/login",
    )

    if redirect:
        return redirect

    try:
        data = export_block_results_to_excel(block_id)

    except ValueError as e:
        raise HTTPException(
            status_code=404,
            detail=str(e),
        )

    return StreamingResponse(
        iter([data]),
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": (
                f"attachment; filename=natijalar_blok_{block_id}.xlsx"
            )
        },
    )
