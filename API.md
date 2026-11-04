# Velqo Shop API
Ro'yxatlar `?limit=` (≤200, standart 50) va `?offset=` qabul qiladi, javob `{items, total}`.
Barcha `/api/*` so'rovlar `X-Init-Data` (Telegram initData) bilan; xato: `{error, message, ...}`. Pul — butun son **USD sent**, topup summasi — so'm.

| Yo'l | Tavsif |
|---|---|
| GET /api/bootstrap | `{user{id,first_name,username,lang,balance,is_admin,is_super}, settings{min_stars,max_stars,usd_rate,star_packs[{qty,price}],premium_prices,card_number,card_holder,topup_min,topup_max,help}, sub{required,channels[]}}` |
| POST /api/check-sub | obunani qayta tekshirish → `{required, channels}` |
| POST /api/quote | `{kind: stars\|premium, qty}` → `{price}` |
| POST /api/orders | `{kind, qty, recipient{type: self\|other, username}}` → 201 `{order, balance}`; 402 `insufficient_balance {need}` |
| GET /api/orders, /api/topups | oxirgi 50 ta |
| POST /api/topups | multipart `amount` (so'm), `receipt` (JPG/PNG/WEBP ≤ 5 MB) → 201; fon vazifasi tekshiradi |
| GET /api/me | yengil so'rov (Mini App har ~6 s so'raydi): `{balance, lang, lang_set, pending_orders, pending_topups}` — admin balansni o'zgartirsa, foydalanuvchi qayta kirmasdan ko'radi |
| PATCH /api/me | `{lang}` (`lang_set=true` bo'ladi) |
| POST /api/ads/claim, GET /api/adsgram/reward?userid=&secret= | reklama mukofoti (standart o'chiq; limit/pauza server tomonda; xato: `limit_reached`, `cooldown`) |
| GET /api/referral | `{percent, invited, earned, link, leaderboard[]}` |
| POST /api/promo/redeem | `{code}` → `{amount, balance}`; `promo_not_found` / `promo_used` / `promo_expired` / `promo_exhausted` |

**Admin** (`/api/admin/*`, `ADMIN_IDS` yoki xodim; o'zgartiruvchi so'rovlar auditga yoziladi): `stats`, `orders?status=`, `orders/{id}/(complete\|cancel)`, `topups?status=`, `topups/{id}/receipt`, `topups/{id}/(approve\|reject\|recheck)`, `users?q=`, `users/{id}/block`, `users/{id}/balance {delta,note}`, `users/{id}/message {text}`, `settings` (GET/PUT), `channels` (GET/POST `{chat,title}`, DELETE `/{username}` — majburiy obuna; bot kanalda admin bo'lishi shart), `users/{id}/message`, `promos` (GET/POST), `promos/{code}` (PATCH `{active,amount,max_uses,days}` / DELETE), `promos/{code}/redemptions`, `broadcast` (POST) + `broadcast/{id}`, `audit`, `staff` (faqat super: GET/POST, DELETE `/{id}`).

Xato kodlari: `cooldown 429, unauthorized 401, blocked 403, forbidden 403, sub_required 403, maintenance 503, rate_limited 429, insufficient_balance 402, username_required 400, invalid_input 400, limit_reached 429, conflict 409, not_found 404, server_error 500`.
