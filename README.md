# Monitoring tizimi

Maktab test-monitoring tizimi: admin panel (maxfiy yo'ldan kiriladi), Excel orqali
o'quvchilar ro'yxati, sinf/chorak/blok bo'yicha 3 fandan tasodifiy test, 90 daqiqalik
taymer, natijalar hisoboti (imzo shabloni bilan) va natijalarni Telegram bot orqali
ko'rish.

## 1. O'rnatish

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

`.env.example` faylini `.env` nomiga ko'chiring va qiymatlarni to'ldiring:

```bash
cp .env.example .env
```

- `ADMIN_SECRET_PATH` — admin panelga kiradigan **maxfiy** yo'l. Standart qiymatni
  albatta o'zgartiring va hech kimga, hech qanday linkda ko'rsatmang.
- `SESSION_SECRET` — tasodifiy, uzun qator qiling.
- `BOT_TOKEN` — Telegram'da @BotFather orqali bot yaratib, undan olingan token.

## 2. Ishga tushirish

**Veb-ilova (admin + o'quvchilar):**
```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```
- O'quvchilar uchun sahifa: `http://sizning-domen:8000/`
- Admin panel: `http://sizning-domen:8000/<ADMIN_SECRET_PATH>/login`
  (standart login/parol: `admin` / `admin123` — **birinchi kirishdan so'ng darhol
  o'zgartirish tavsiya etiladi**; hozircha buni admin panelidan o'zgartirish tugmasi
  yo'q, to'g'ridan-to'g'ri bazadan yangilash kerak bo'ladi — xohlasangiz shu funksiyani
  qo'shib beraman).

**Telegram bot (alohida, lekin BIR XIL papkada/serverda):**
```bash
python bot/bot.py
```

Ikkalasi ham `data/monitoring.db` faylidan baravar foydalanadi, shuning uchun
ikkalasini ham bitta serverda ishga tushiring.

## 3. Fayl tuzilishi

```
backend/        - FastAPI ilova, baza, import/export, imtihon mantiqi
templates/      - admin va o'quvchi sahifalari (Jinja2/HTML)
static/         - CSS va JS (taymer, navigatsiya, skrinshotga qarshi choralar)
bot/bot.py      - Telegram bot (aiogram)
data/           - monitoring.db shu yerda yaraladi (avtomatik)
```

## 4. Men qabul qilgan taxminlar — ILTIMOS TEKSHIRING

Sizning tavsifingizda ba'zi texnik tafsilotlar aniq ko'rsatilmagan edi. Ishni
boshlash uchun quyidagicha qaror qabul qildim — mos kelmasa ayting, o'zgartiraman:

1. **To'g'ri javobni belgilash.** Fayl formatida `#`/`-` bor edi, lekin to'g'ri
   javobni qanday ko'rsatish aytilmagan edi. Men variant oldiga `*` qo'yish
   qoidasini kiritdim:
   ```
   # Savol matni?
   - Noto'g'ri variant
   *- To'g'ri variant
   - Noto'g'ri variant
   ```
2. **Skrinshotni oldini olish.** Brauzer orqali skrinshotni 100% bloklab bo'lmaydi
   (operatsion tizim, telefon kamerasi va h.k. orqali baribir olinishi mumkin).
   Hozir sahifada: o'ng tugma o'chirilgan, matn tanlab bo'lmaydi, nusxa olish
   (Ctrl+C) bloklangan, PrintScreen/oyna fokusdan chiqishi aniqlanib ogohlantirish
   chiqadi. Bu to'liq kafolat EMAS, faqat yordamchi chora.
3. **Telegram bot joylashuvi.** Men bu muhitda jonli botni ishga tushira olmayman
   (bu yerdan Telegram serverlariga tarmoq ulanishi yo'q). Botni siz o'z
   serveringizda/hostingingizda (masalan, avvalgi loyihalaringizda ishlatgan
   serveringizda) alohida jarayon sifatida ishga tushirishingiz kerak — kod to'liq
   tayyor, faqat `BOT_TOKEN` qo'yib, `python bot/bot.py` deb ishga tushirasiz.
4. **Viloyat/tuman/maktab.** Bitta "Monitoring tizimi" o'rnatmasi bitta maktab
   uchun deb faraz qildim. Botda viloyat/tuman/maktab faqat
   ro'yxatdan o'tish/identifikatsiya va natija xabarida ko'rsatish uchun
   ishlatiladi (14 ta viloyat tugma bilan, tuman va maktab esa erkin matn —
   to'liq tuman ro'yxati kiritilmagan, xohlasangiz qo'shib beraman).
5. **Natijalar jadvalidagi "test raqami".** Har bir o'quvchiga tasodifiy BOSHQA-
   BOSHQA 15 ta savol chiqqani uchun, jadvaldagi 1-15 raqamlari savol bankidagi ID
   emas, balki o'sha o'quvchi UCHUN savol TARTIB-RAQAMI (pozitsiyasi).

## 5. Hali qo'shilmagan / keyingi qadamlar

- Admin parolini panel ichidan o'zgartirish ekrani
- To'liq viloyat→tuman→maktab ma'lumotlar bazasi (hozir tuman/maktab erkin matn)
- Dizaynni yanada jilolash (hozirgi ko'rinish — funksional, lekin sodda)
- Bir nechta admin foydalanuvchi / rollar

Shu nuqtalarning birortasini hoziroq to'ldirib berishimni xohlasangiz, ayting.
