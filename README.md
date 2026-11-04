# Velqo Shop
1. `.env.example` dagi o'zgaruvchilarni Railway'ga kiriting (BOT_TOKEN, DATABASE_URL, ADMIN_IDS, WEBAPP_URL).
2. Deploy: Dockerfile avtomatik topiladi, healthcheck `/healthz`.
3. BotFather → Menu Button = WEBAPP_URL.
4. Botda admin sifatida: `/set usd_rate 12650`, `/set card_number "8600 ..."`, `/set card_holder "ISM FAMILIYA"`, `/pending`.
Lokal sinov: `DEV_MODE=1`, brauzerda `?dev=<telegram_id>`.
Testlar (haqiqiy PostgreSQL, baza tozalanadi): `cd backend && TEST_DATABASE_URL=postgresql://... python -m pytest -q`
Eski SQLite'dan o'tish: `cd backend && python -m tools.import_old_sqlite old.db --dry-run`
Marshrutlar: `API.md`.

Bot: `/start` → (majburiy obuna) → til tanlash → do'kon. Buyruqlar: `/lang /ref /help`; adminlar: `/admin /pending /channels /set`. Majburiy obunani admin panelning «Obuna» bo'limidan boshqaring.
Eslatma: bir vaqtda faqat BITTA bot nusxasi ishlasin (aks holda Telegram `Conflict` xatosi chiqadi); bot kanalda ADMIN bo'lishi shart.
