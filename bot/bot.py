
"""
Monitoring tizimi — Telegram bot.

ISHGA TUSHIRISH:
  1) @BotFather orqali bot yarating va token oling.
  2) Render Environment bo'limiga BOT_TOKEN qo'shing.
  3) python bot/bot.py

MUHIM:
  Bot va FastAPI bitta serverda, bitta loyiha papkasida
  ishlashi kerak. Ikkalasi ham bir xil SQLite bazadan foydalanadi.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Loyiha asosiy papkasini Python yo'liga qo'shish
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# .env faylini yuklash
from dotenv import load_dotenv

load_dotenv(BASE_DIR / ".env")

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    CallbackQuery,
)

from backend.database import get_conn


# ==================================================
# SOZLAMALAR
# ==================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN topilmadi! Render Environment bo'limiga "
        "BOT_TOKEN qiymatini kiriting."
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)

router = Router()


# ==================================================
# VILOYATLAR
# ==================================================

VILOYATLAR = [
    "Qoraqalpog'iston Respublikasi",
    "Andijon",
    "Buxoro",
    "Farg'ona",
    "Jizzax",
    "Xorazm",
    "Namangan",
    "Navoiy",
    "Qashqadaryo",
    "Samarqand",
    "Sirdaryo",
    "Surxondaryo",
    "Toshkent viloyati",
    "Toshkent shahri",
]


# ==================================================
# FOYDALANUVCHI HOLATLARI
# ==================================================

class Reg(StatesGroup):
    viloyat = State()
    tuman = State()
    maktab = State()
    login = State()
    sinf = State()


# ==================================================
# KLAVIATURALAR
# ==================================================

def viloyat_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=viloyat,
                callback_data=f"vil:{index}",
            )
        ]
        for index, viloyat in enumerate(VILOYATLAR)
    ]

    return InlineKeyboardMarkup(inline_keyboard=rows)


# ==================================================
# /START
# ==================================================

@router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()

    await message.answer(
        "Assalomu alaykum!\n"
        "Monitoring tizimi natijalari botiga xush kelibsiz.\n\n"
        "Viloyatingizni tanlang:",
        reply_markup=viloyat_keyboard(),
    )

    await state.set_state(Reg.viloyat)


# ==================================================
# /CANCEL
# ==================================================

@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()

    await message.answer(
        "Jarayon bekor qilindi.\n"
        "Qaytadan boshlash uchun /start buyrug'ini yuboring."
    )


# ==================================================
# VILOYAT TANLASH
# ==================================================

@router.callback_query(
    Reg.viloyat,
    F.data.startswith("vil:")
)
async def viloyat_chosen(
    callback: CallbackQuery,
    state: FSMContext,
):
    try:
        idx = int(callback.data.split(":")[1])

        if idx < 0 or idx >= len(VILOYATLAR):
            raise ValueError

    except (ValueError, IndexError):
        await callback.answer(
            "Noto'g'ri viloyat tanlandi.",
            show_alert=True,
        )
        return

    await state.update_data(
        viloyat=VILOYATLAR[idx]
    )

    await callback.message.answer(
        "Tumaningiz nomini kiriting:"
    )

    await state.set_state(Reg.tuman)
    await callback.answer()


# ==================================================
# TUMAN KIRITISH
# ==================================================

@router.message(Reg.tuman)
async def tuman_entered(
    message: Message,
    state: FSMContext,
):
    if not message.text or not message.text.strip():
        await message.answer("Iltimos, tuman nomini matn bilan kiriting.")
        return

    await state.update_data(
        tuman=message.text.strip()
    )

    await message.answer(
        "Maktabingiz nomini yoki raqamini kiriting:"
    )

    await state.set_state(Reg.maktab)


# ==================================================
# MAKTAB KIRITISH
# ==================================================

@router.message(Reg.maktab)
async def maktab_entered(
    message: Message,
    state: FSMContext,
):
    if not message.text or not message.text.strip():
        await message.answer("Iltimos, maktab nomini kiriting.")
        return

    await state.update_data(
        maktab=message.text.strip()
    )

    await message.answer(
        "Loginni kiriting (Ism Familiyangiz, "
        "tizimdagi ro'yxatdagidek):"
    )

    await state.set_state(Reg.login)


# ==================================================
# LOGIN KIRITISH
# ==================================================

@router.message(Reg.login)
async def login_entered(
    message: Message,
    state: FSMContext,
):
    if not message.text or not message.text.strip():
        await message.answer("Iltimos, loginni matn bilan kiriting.")
        return

    await state.update_data(
        login=message.text.strip()
    )

    await message.answer(
        "Sinfingizni raqam bilan kiriting (masalan: 7):"
    )

    await state.set_state(Reg.sinf)


# ==================================================
# SINfni TEKSHIRISH VA NATIJALARNI CHIQARISH
# ==================================================

@router.message(Reg.sinf)
async def sinf_entered(
    message: Message,
    state: FSMContext,
):
    if not message.text or not message.text.strip().isdigit():
        await message.answer(
            "Sinfni faqat raqam bilan kiriting.\n"
            "Masalan: 7"
        )
        return

    sinf = int(message.text.strip())

    if not 1 <= sinf <= 11:
        await message.answer(
            "Sinf 1 dan 11 gacha bo'lishi kerak."
        )
        return

    data = await state.get_data()
    fish = data.get("login")

    conn = None

    try:
        conn = get_conn()

        # O'quvchini tekshirish
        student = conn.execute(
            """
            SELECT *
            FROM students
            WHERE fish = ? AND sinf = ?
            """,
            (fish, sinf),
        ).fetchone()

        if not student:
            await message.answer(
                "Login yoki sinf noto'g'ri.\n\n"
                "Qaytadan urinib ko'rish uchun /start buyrug'ini yuboring."
            )
            await state.clear()
            return

        # Telegram akkauntini o'quvchi bilan bog'lash
        conn.execute(
            """
            INSERT INTO telegram_links
                (chat_id, viloyat, tuman, maktab, student_id)
            VALUES (?, ?, ?, ?, ?)

            ON CONFLICT(chat_id) DO UPDATE SET
                viloyat = excluded.viloyat,
                tuman = excluded.tuman,
                maktab = excluded.maktab,
                student_id = excluded.student_id
            """,
            (
                message.chat.id,
                data["viloyat"],
                data["tuman"],
                data["maktab"],
                student["id"],
            ),
        )

        conn.commit()

        # Tugatilgan testlarni olish
        sessions = conn.execute(
            """
            SELECT
                sess.id,
                b.sinf,
                b.chorak,
                b.blok
            FROM sessions AS sess
            JOIN blocks AS b
                ON b.id = sess.block_id
            WHERE
                sess.student_id = ?
                AND sess.status = 'finished'
            ORDER BY sess.finished_at DESC
            """,
            (student["id"],),
        ).fetchall()

        if not sessions:
            await message.answer(
                "Sizning hisobingiz topildi, ammo hozircha "
                "tugatilgan test natijalari mavjud emas."
            )
            await state.clear()
            return

        # Natijalarni tayyorlash
        lines = [
            "📊 MONITORING NATIJALARI",
            "",
            f"📍 {data['viloyat']}, {data['tuman']} tumani",
            f"🏫 {data['maktab']}",
            f"👤 {student['fish']} ({student['sinf']}-sinf)",
            "",
        ]

        for sess in sessions:
            items = conn.execute(
                """
                SELECT
                    sub.name,
                    sq.is_correct
                FROM session_questions AS sq
                JOIN subjects AS sub
                    ON sub.id = sq.subject_id
                WHERE sq.session_id = ?
                """,
                (sess["id"],),
            ).fetchall()

            per_subject = {}

            for item in items:
                name = item["name"]

                if name not in per_subject:
                    per_subject[name] = [0, 0]

                per_subject[name][1] += 1

                if item["is_correct"]:
                    per_subject[name][0] += 1

            lines.append(
                f"📘 {sess['chorak']}-chorak, "
                f"{sess['blok']}-blok:"
            )

            total_correct = 0
            total_questions = 0

            for name, (correct, total) in per_subject.items():
                percent = (
                    round(correct / total * 100)
                    if total else 0
                )

                lines.append(
                    f"   • {name}: {correct}/{total} "
                    f"to'g'ri ({percent}%)"
                )

                total_correct += correct
                total_questions += total

            overall_percent = (
                round(total_correct / total_questions * 100)
                if total_questions else 0
            )

            lines.append(
                f"   ✅ Umumiy: {total_correct}/"
                f"{total_questions} ({overall_percent}%)"
            )

            lines.append("")

        # Telegram xabarining maksimal hajmini hisobga olish
        result_text = "\n".join(lines)

        if len(result_text) <= 4000:
            await message.answer(result_text)
        else:
            # Natijani qismlarga bo'lib yuborish
            chunk = ""

            for line in lines:
                if len(chunk) + len(line) + 1 > 4000:
                    await message.answer(chunk)
                    chunk = ""

                chunk += line + "\n"

            if chunk.strip():
                await message.answer(chunk)

        await state.clear()

    except Exception:
        logger.exception("Botda natijalarni olishda xatolik yuz berdi.")

        await message.answer(
            "Natijalarni olishda texnik xatolik yuz berdi.\n"
            "Iltimos, birozdan keyin qayta urinib ko'ring."
        )

    finally:
        if conn is not None:
            conn.close()


# ==================================================
# BOTNI ISHGA TUSHIRISH
# ==================================================

async def main():
    bot = Bot(token=BOT_TOKEN)

    dp = Dispatcher(
        storage=MemoryStorage()
    )

    dp.include_router(router)

    logger.info("Telegram bot ishga tushmoqda...")

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
