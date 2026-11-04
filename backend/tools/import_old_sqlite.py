"""Eski SQLite (balans USD) -> PostgreSQL (USD sent).
Ishlatish (backend/ papkasidan):  python -m tools.import_old_sqlite old.db [--dry-run]
Taxmin: eski bazada `users` jadvali bor; ustunlar: id (yoki tg_id/user_id), first_name (yoki name), username, lang (yoki language), balance (USD).
Xavfsiz takrorlash: mavjud foydalanuvchiga tegilmaydi, balans faqat YANGI qo'shilganlarga yoziladi.
Ilova kamida bir marta ishga tushgan bo'lishi kerak (sxema yaratilgan)."""
import argparse, asyncio, os, sqlite3
from decimal import Decimal

import asyncpg

ALIASES = {"id": ("id", "tg_id", "user_id", "telegram_id"), "first_name": ("first_name", "name", "full_name"),
           "username": ("username",), "lang": ("lang", "language"), "balance": ("balance", "usd", "balance_usd")}


def read_users(path):
    db = sqlite3.connect(path); db.row_factory = sqlite3.Row
    cols = {r["name"].lower(): r["name"] for r in db.execute("PRAGMA table_info(users)")}
    if not cols: raise SystemExit("Eski bazada `users` jadvali topilmadi")
    pick = {k: next((cols[a] for a in v if a in cols), None) for k, v in ALIASES.items()}
    if not pick["id"] or not pick["balance"]: raise SystemExit(f"id/balance ustunlari topilmadi: {sorted(cols)}")
    out = []
    for r in db.execute("SELECT * FROM users"):
        lang = (r[pick["lang"]] if pick["lang"] else "uz") or "uz"
        out.append({"id": int(r[pick["id"]]), "first_name": (r[pick["first_name"]] if pick["first_name"] else None) or "User",
                    "username": r[pick["username"]] if pick["username"] else None, "lang": lang if lang in ("uz", "ru", "en") else "uz",
                    "cents": int((Decimal(str(r[pick["balance"]] or 0)) * 100).quantize(Decimal(1)))})  # round(usd*100)
    db.close()
    return out


async def run(path, dry_run=False, dsn=None):
    users, new, cents = read_users(path), 0, 0
    c = await asyncpg.connect(dsn or os.environ["DATABASE_URL"])
    try:
        async with c.transaction():
            for u in users:
                if dry_run:
                    if not await c.fetchval("SELECT 1 FROM users WHERE id=$1", u["id"]): new += 1; cents += max(u["cents"], 0)
                    continue
                if await c.fetchval("INSERT INTO users(id,first_name,username,lang,balance) VALUES($1,$2,$3,$4,$5) ON CONFLICT(id) DO NOTHING RETURNING 1",
                                    u["id"], u["first_name"], u["username"], u["lang"], max(u["cents"], 0)):
                    new += 1; cents += max(u["cents"], 0)
                    if u["cents"] > 0:
                        await c.execute("INSERT INTO balance_log(user_id,delta,balance_after,reason) VALUES($1,$2,$2,'import')", u["id"], u["cents"])
    finally: await c.close()
    return {"total": len(users), "new": new, "cents": cents, "dry_run": dry_run}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("db"); ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(); print(asyncio.run(run(a.db, a.dry_run)))
