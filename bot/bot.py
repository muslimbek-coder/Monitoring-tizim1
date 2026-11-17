"""
Monitoring tizimi — Telegram bot.

ISHGA TUSHIRISH:
  1) @BotFather dan bot yarating, tokenni oling.
  2) `export BOT_TOKEN="sizning_tokeningiz"` (yoki pastdagi BOT_TOKEN ga yozing)
  3) `python bot/bot.py`

MUHIM: bu bot backend/data/monitoring.db faylini backend (FastAPI) bilan
BIR XIL joydan o'qiydi — shuning uchun ikkalasi ham bitta serverda,
bitta papka ichida ishga tushirilishi kerak.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery

from backend.database import get_conn

BOT_TOKEN = os.environ.get("BOT_TOKEN", "QO'YING_BOT_TOKENINGIZNI_BU_YERGA")

VILOYATLAR = [
    "Qoraqalpog'iston Respublikasi", "Andijon", "Buxoro", "Farg'ona", "Jizzax",
    "Xorazm", "Namangan", "Navoiy", "Qashqadaryo", "Samarqand",
    "Sirdaryo", "Surxondaryo", "Toshkent viloyati", "Toshkent shahri",
]

router = Router()


class Reg(StatesGroup):
    viloyat = State()
    tuman = State()
    maktab = State()
    login = State()
    parol = State()


def viloyat_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=v, callback_data=f"vil:{i}")] for i, v in enumerate(VILOYATLAR)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Assalomu alaykum! Monitoring tizimi natijalar boti.\n\nViloyatingizni tanlang:",
        reply_markup=viloyat_keyboard(),
    )
    await state.set_state(Reg.viloyat)


@router.callback_query(F.data.startswith("vil:"))
async def viloyat_chosen(callback: CallbackQuery, state: FSMContext):
    idx = int(callback.data.split(":")[1])
    await state.update_data(viloyat=VILOYATLAR[idx])
    await callback.message.answer("Tumaningizni yozing:")
    await state.set_state(Reg.tuman)
    await callback.answer()


@router.message(Reg.tuman)
async def tuman_entered(message: Message, state: FSMContext):
    await state.update_data(tuman=message.text.strip())
    await message.answer("Maktabingizni yozing (nomi yoki raqami):")
    await state.set_state(Reg.maktab)


@router.message(Reg.maktab)
async def maktab_entered(message: Message, state: FSMContext):
    await state.update_data(maktab=message.text.strip())
    await message.answer("Endi login (Ism Familiyangiz, ro'yxatdagidek) kiriting:")
    await state.set_state(Reg.login)


@router.message(Reg.login)
async def login_entered(message: Message, state: FSMContext):
    await state.update_data(login=message.text.strip())
    await message.answer("Parol (sinfingiz, masalan: 7) kiriting:")
    await state.set_state(Reg.parol)


@router.message(Reg.parol)
async def parol_entered(message: Message, state: FSMContext):
    fish = (await state.get_data()).get("login")
    try:
        sinf = int(message.text.strip())
    except ValueError:
        await message.answer("Sinfni raqam bilan yozing, masalan: 7")
        return

    conn = get_conn()
    student = conn.execute(
        "SELECT * FROM students WHERE fish = ? AND sinf = ?", (fish, sinf)
    ).fetchone()

    if not student:
        conn.close()
        await message.answer("Login yoki parol noto'g'ri. Qaytadan urinib ko'ring: /start")
        await state.clear()
        return

    data = await state.get_data()
    conn.execute(
        """INSERT INTO telegram_links (chat_id, viloyat, tuman, maktab, student_id)
           VALUES (?,?,?,?,?)
           ON CONFLICT(chat_id) DO UPDATE SET
             viloyat=excluded.viloyat, tuman=excluded.tuman,
             maktab=excluded.maktab, student_id=excluded.student_id""",
        (message.chat.id, data["viloyat"], data["tuman"], data["maktab"], student["id"]),
    )
    conn.commit()

    sessions = conn.execute(
        """SELECT sess.id, b.sinf, b.chorak, b.blok FROM sessions sess
           JOIN blocks b ON b.id = sess.block_id
           WHERE sess.student_id = ? AND sess.status = 'finished'
           ORDER BY sess.finished_at DESC""",
        (student["id"],),
    ).fetchall()

    if not sessions:
        conn.close()
        await message.answer("Hali tugatilgan test topilmadi.")
        await state.clear()
        return

    lines = [
        f"📍 {data['viloyat']}, {data['tuman']} tumani, {data['maktab']}",
        f"👤 {student['fish']} ({student['sinf']}-sinf)",
        "",
    ]
    for sess in sessions:
        items = conn.execute(
            """SELECT sub.name, sq.is_correct FROM session_questions sq
               JOIN subjects sub ON sub.id = sq.subject_id
               WHERE sq.session_id = ?""",
            (sess["id"],),
        ).fetchall()
        per_subject: dict[str, list[int]] = {}
        for it in items:
            per_subject.setdefault(it["name"], [0, 0])
            per_subject[it["name"]][1] += 1
            if it["is_correct"]:
                per_subject[it["name"]][0] += 1

        lines.append(f"📘 {sess['chorak']}-chorak, {sess['blok']}-blok:")
        total_c, total_t = 0, 0
        for name, (c, t) in per_subject.items():
            pct = round(c / t * 100) if t else 0
            lines.append(f"   • {name}: {c}/{t} to'g'ri ({pct}%)")
            total_c += c
            total_t += t
        overall_pct = round(total_c / total_t * 100) if total_t else 0
        lines.append(f"   ✅ Umumiy: {total_c}/{total_t} ({overall_pct}%)\n")

    conn.close()
    await message.answer("\n".join(lines))
    await state.clear()


async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
