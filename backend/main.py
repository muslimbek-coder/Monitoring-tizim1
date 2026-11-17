import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .database import init_db
from .routers import admin, student

BASE_DIR = Path(__file__).resolve().parent.parent

# Admin panelning manzili ODDIY, taxmin qilish oson bo'lmagan maxfiy yo'l.
# Buni albatta .env faylida o'zgartiring (pastga qarang).
ADMIN_SECRET_PATH = os.environ.get("ADMIN_SECRET_PATH", "boshqaruv-7f3a9c")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "iltimos-buni-ozgartiring-prod-da")

app = FastAPI(title="Monitoring tizimi")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site="lax")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# E'TIBOR: admin yo'li asosiy saytning hech bir joyidan link qilinmaydi —
# faqat shu to'liq manzilni biladigan kishi kira oladi:
#   https://sizning-domen/<ADMIN_SECRET_PATH>/login
app.include_router(admin.router, prefix=f"/{ADMIN_SECRET_PATH}", tags=["admin"])
app.include_router(student.router, tags=["student"])


@app.on_event("startup")
def on_startup():
    init_db()
    admin.ensure_default_admin()


@app.get("/__admin_path__")
def reveal_admin_path_locally():
    """Faqat diagnostika uchun: joriy maxfiy admin yo'lini ko'rsatadi.
    Ishga tushirgandan so'ng buni o'chirib qo'yish (yoki kommentariyaga olish) tavsiya etiladi."""
    return {"admin_path": f"/{ADMIN_SECRET_PATH}/login"}
