"""Haqiqiy PostgreSQL bilan: TEST_DATABASE_URL=postgresql://... python -m pytest -q  (bo'lmasa o'tkazib yuboriladi). BAZA TOZALANADI — alohida test bazasini bering."""
import asyncio, json, os, sqlite3, tempfile
import pytest

URL = os.getenv("TEST_DATABASE_URL")
os.environ.update(BOT_TOKEN="123:test", DATABASE_URL=URL or "postgresql://x/x", ADMIN_IDS="1", DEV_MODE="1")
asyncpg = pytest.importorskip("asyncpg")
from aiohttp.test_utils import TestClient, TestServer
from app import main


class _O:
    def __init__(s, **k): s.__dict__.update(k)


class FakeBot:
    def __init__(s): s.sent = []; s.bot_status = "administrator"
    async def get_chat(s, chat):
        if chat == "@nochan": raise RuntimeError("chat not found")
        return _O(title="Chan", type="channel")
    async def me(s): return _O(id=999)
    async def send_message(s, uid, text, **kw): s.sent.append((uid, text))
    async def send_photo(s, uid, photo, **kw): s.sent.append((uid, kw.get("caption", "")))
    async def get_chat_member(s, chat, uid):
        if uid == 999: return _O(status=s.bot_status)
        raise RuntimeError("no")


def case(f):
    def w():
        async def go():
            main.P, main.BOT = await asyncpg.create_pool(URL), FakeBot()
            await main.init_schema()
            await main.P.execute("TRUNCATE users,orders,topups,balance_log,settings,promos,promo_uses,admins,audit,broadcasts,ad_views RESTART IDENTITY CASCADE")
            main.drop_cache(); main.SUB_CACHE.clear(); main.HITS.clear(); main.STAFF.clear(); main.ADS_SECRET = ""
            try: await f()
            finally: await asyncio.sleep(0.05); await main.P.close()
        asyncio.run(go())
    w.__name__ = f.__name__
    return pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL yo'q")(w)


H = lambda u: {"X-Dev-User": str(u)}
ORDER = {"kind": "stars", "qty": 50, "recipient": {"type": "self"}}  # 50 Stars = 83 sent
bal = lambda u: main.P.fetchval("SELECT balance FROM users WHERE id=$1", u)
stat = lambda t: main.P.fetchval("SELECT status FROM topups WHERE id=$1", t)


async def mkuser(i, balance=0, by=None):
    await main.P.execute("INSERT INTO users(id,first_name,username,balance,invited_by) VALUES($1,$2,$3,$4,$5)", i, f"U{i}", f"user_{i}", balance, by)


async def topup(uid, amount=50000, rate=12650):
    return await main.P.fetchval("INSERT INTO topups(user_id,amount,rate,credit,receipt,mime) VALUES($1,$2,$3,$4,$5,'image/png') RETURNING id", uid, amount, rate, amount * 100 // rate, b"x")


async def client():
    c = TestClient(TestServer(main.make_app())); await c.start_server(); return c


@case
async def test_parallel_orders_never_negative():
    await mkuser(101, 83 * 3); c = await client()
    rs = await asyncio.gather(*[c.post("/api/orders", json=ORDER, headers=H(101)) for _ in range(10)])
    st = [r.status for r in rs]
    assert st.count(201) == 3 and st.count(402) == 7 and await bal(101) == 0
    await c.close()


@case
async def test_cancel_refunds_once_and_done_is_final():
    await mkuser(101, 166); c = await client()
    o1 = (await (await c.post("/api/orders", json=ORDER, headers=H(101))).json())["order"]["id"]
    o2 = (await (await c.post("/api/orders", json=ORDER, headers=H(101))).json())["order"]["id"]
    res = await asyncio.gather(main.decide_order(o1, "cancel", "x"), main.decide_order(o1, "cancel", "x"))
    assert sum(1 for r in res if r) == 1 and await bal(101) == 83
    assert await main.decide_order(o2, "done") and await main.decide_order(o2, "cancel", "x") is None and await bal(101) == 83
    await c.close()


@case
async def test_topup_triple_approve_and_conversion():
    await mkuser(101); tid = await topup(101)  # 50 000 so'm @ 12 650 = 395 sent
    res = [r for r in await asyncio.gather(*[main.decide_topup(tid, True) for _ in range(3)]) if r]
    assert len(res) == 1 and res[0]["credit"] == 395 and await bal(101) == 395


@case
async def test_decisions_idempotent():
    await mkuser(101); tid = await topup(101)
    assert await main.decide_topup(tid, False, note="x") and await main.decide_topup(tid, False) is None and await main.decide_topup(tid, True) is None
    assert await bal(101) == 0


@case
async def test_referral_bonus_once_and_notified():
    await mkuser(5); await mkuser(6, by=5); tid = await topup(6)
    await main.decide_topup(tid, True); await main.decide_topup(tid, True); await asyncio.sleep(0.1)
    assert await bal(5) == 19 and await main.P.fetchval("SELECT ref_earned FROM users WHERE id=5") == 19  # 395 * 5%
    assert [u for u, _ in main.BOT.sent].count(5) == 1


@case
async def test_promo_once_and_limit():
    await mkuser(101); await mkuser(102); c = await client()
    await main.P.execute("INSERT INTO promos(code,amount,max_uses) VALUES('GIFT',100,1)")
    assert (await c.post("/api/promo/redeem", json={"code": "gift"}, headers=H(101))).status == 200
    assert (await c.post("/api/promo/redeem", json={"code": "GIFT"}, headers=H(101))).status == 409
    assert (await c.post("/api/promo/redeem", json={"code": "GIFT"}, headers=H(102))).status == 409
    assert await bal(101) == 100 and await bal(102) == 0
    await c.close()


@case
async def test_blocked_and_maintenance():
    await mkuser(101); await mkuser(102); c = await client()
    await main.P.execute("UPDATE users SET is_blocked=true WHERE id=101")
    assert (await c.get("/api/bootstrap", headers=H(101))).status == 403
    await main.P.execute("INSERT INTO settings VALUES('maintenance','true')"); main.drop_cache()
    assert (await c.get("/api/bootstrap", headers=H(102))).status == 503
    assert (await c.get("/api/bootstrap", headers=H(1))).status == 200  # admin
    await c.close()


@case
async def test_ocr_auto_modes():
    orig = main.rc.analyze
    try:
        await mkuser(101)
        cfg = {"mode": "auto", "auto_approve_max": 100000, "max_age_minutes": 60, "auto_reject": True, "require_card_match": False}
        await main.P.execute("INSERT INTO settings VALUES('receipt_check',$1::jsonb)", __import__("json").dumps(cfg)); main.drop_cache()
        main.rc.analyze = lambda *a: {"verdict": "pass", "reasons": [], "found": {}}
        small, big = await topup(101, 50000), await topup(101, 200000)
        await main.run_check(small); await main.run_check(big)
        assert await stat(small) == "approved" and await stat(big) == "pending"
        assert await main.P.fetchval("SELECT decided_auto FROM topups WHERE id=$1", small)
        main.rc.analyze = lambda *a: {"verdict": "fail", "reasons": ["amount_mismatch"], "found": {}}
        bad = await topup(101, 50000); await main.run_check(bad)
        assert await stat(bad) == "rejected" and await main.P.fetchval("SELECT note FROM topups WHERE id=$1", bad) == "amount_mismatch"
    finally: main.rc.analyze = orig


@case
async def test_import_old_sqlite_idempotent_and_dry_run():
    from tools import import_old_sqlite as imp
    f = os.path.join(tempfile.mkdtemp(), "old.db"); db = sqlite3.connect(f)
    db.execute("CREATE TABLE users(id INTEGER, first_name TEXT, username TEXT, balance REAL)")
    db.execute("INSERT INTO users VALUES(7,'A','a_user',1.65)"); db.commit(); db.close()
    assert (await imp.run(f, True, URL))["new"] == 1 and await main.P.fetchval("SELECT count(*) FROM users") == 0
    assert (await imp.run(f, False, URL))["new"] == 1 and await bal(7) == 165
    assert (await imp.run(f, False, URL))["new"] == 0 and await bal(7) == 165


@case
async def test_me_reflects_balance_changes_without_reopening():
    await mkuser(101, 100); c = await client()
    assert (await (await c.get("/api/me", headers=H(101))).json())["balance"] == 100
    await main.P.execute("UPDATE users SET balance=balance+50 WHERE id=101")  # admin pul qo'shdi
    d = await (await c.get("/api/me", headers=H(101))).json()
    assert d["balance"] == 150 and "pending_orders" in d and "pending_topups" in d
    await c.close()


@case
async def test_language_is_chosen_explicitly():
    await mkuser(101); c = await client()
    assert (await (await c.get("/api/bootstrap", headers=H(101))).json())["user"]["lang_set"] is False
    assert (await c.patch("/api/me", json={"lang": "ru"}, headers=H(101))).status == 200
    u = (await (await c.get("/api/bootstrap", headers=H(101))).json())["user"]
    assert u["lang"] == "ru" and u["lang_set"] is True
    await c.close()


@case
async def test_channels_admin_add_list_delete_and_enforcement():
    await mkuser(101); c = await client()
    main.BOT.bot_status = "member"
    assert (await c.post("/api/admin/channels", json={"chat": "@velqotest"}, headers=H(1))).status == 400  # bot admin emas
    assert (await c.post("/api/admin/channels", json={"chat": "bad name"}, headers=H(1))).status == 400
    assert (await c.post("/api/admin/channels", json={"chat": "@nochan"}, headers=H(1))).status == 400  # topilmadi
    main.BOT.bot_status = "administrator"
    assert (await c.post("/api/admin/channels", json={"chat": "https://t.me/velqotest", "title": "Velqo"}, headers=H(1))).status == 201
    d = await (await c.get("/api/admin/channels", headers=H(1))).json()
    assert d["total"] == 1 and d["items"][0]["chat"] == "@velqotest" and d["items"][0]["bot_admin"]
    # a'zo bo'lmagan foydalanuvchi API'dan foydalana olmaydi, admin esa ozod
    async def left(chat, uid): return _O(status="left") if uid != 999 else _O(status="administrator")
    main.BOT.get_chat_member = left; main.SUB_CACHE.clear()
    assert (await c.get("/api/orders", headers=H(101))).status == 403
    assert (await c.get("/api/orders", headers=H(1))).status == 200
    assert (await c.delete("/api/admin/channels/velqotest", headers=H(1))).status == 200
    assert (await (await c.get("/api/admin/channels", headers=H(1))).json())["total"] == 0
    main.SUB_CACHE.clear(); assert (await c.get("/api/orders", headers=H(101))).status == 200
    await c.close()


def test_start_flow_texts_and_commands_exist():
    assert main.MULTI_PICK and set(main.LANG_NAMES) == {"uz", "ru", "en"}
    assert all("help_text" in main.BT[l] for l in main.BT)


@case
async def test_rate_limit():
    await mkuser(101); c = await client()
    st = [(await c.get("/api/me", headers=H(101))).status for _ in range(31)]
    assert st[:30] == [200] * 30 and st[30] == 429
    await c.close()


@case
async def test_pagination_total_and_bad_limit():
    await mkuser(101, 83 * 5); c = await client()
    for _ in range(5): await c.post("/api/orders", json=ORDER, headers=H(101))
    d = await (await c.get("/api/orders?limit=2&offset=0", headers=H(101))).json()
    assert len(d["items"]) == 2 and d["total"] == 5
    assert len((await (await c.get("/api/orders?limit=2&offset=4", headers=H(101))).json())["items"]) == 1
    assert (await c.get("/api/orders?limit=abc", headers=H(101))).status == 400
    await c.close()


@case
async def test_admin_only_staff_and_audit():
    await mkuser(101); c = await client()
    assert (await c.get("/api/admin/stats", headers=H(101))).status == 403
    assert (await c.get("/api/admin/stats", headers=H(1))).status == 200
    assert (await c.post("/api/admin/staff", json={"id": 101}, headers=H(1))).status == 201
    assert (await c.get("/api/admin/stats", headers=H(101))).status == 200  # endi xodim
    assert (await c.post("/api/admin/staff", json={"id": 55}, headers=H(101))).status == 403  # xodim xodim qo'sha olmaydi
    assert (await c.delete("/api/admin/staff/1", headers=H(1))).status == 400  # env adminni o'chirib bo'lmaydi
    assert await main.P.fetchval("SELECT count(*) FROM audit WHERE action LIKE 'POST /api/admin/staff%'") >= 1
    await c.close()


@case
async def test_admin_message_and_balance_guard():
    await mkuser(101, 100); c = await client()
    assert (await c.post("/api/admin/users/101/message", json={"text": "<b>Salom</b>"}, headers=H(1))).status == 200 and main.BOT.sent[-1][0] == 101
    assert (await c.post("/api/admin/users/999/message", json={"text": "x"}, headers=H(1))).status == 404
    assert (await c.post("/api/admin/users/101/balance", json={"delta": -101}, headers=H(1))).status == 400  # minusga tushmaydi
    assert (await c.post("/api/admin/users/101/balance", json={"delta": -100, "note": "t"}, headers=H(1))).status == 200 and await bal(101) == 0
    await c.close()


@case
async def test_promo_edit():
    c = await client()
    assert (await c.post("/api/admin/promos", json={"code": "abc", "amount": 100, "max_uses": 2, "days": 3}, headers=H(1))).status == 201
    assert (await c.patch("/api/admin/promos/ABC", json={"amount": 250, "max_uses": 5, "days": None}, headers=H(1))).status == 200
    r = await main.P.fetchrow("SELECT * FROM promos WHERE code='ABC'")
    assert r["amount"] == 250 and r["max_uses"] == 5 and r["expires_at"] is None
    await c.close()


@case
async def test_ads_limits_and_callback_secret():
    await mkuser(101); c = await client()
    await main.P.execute("INSERT INTO settings VALUES('ads',$1::jsonb)", json.dumps({"enabled": True, "block_id": "b", "reward": 2, "daily_limit": 2, "cooldown": 0}))
    main.drop_cache(); main.ADS_SECRET = "s3"
    assert (await c.post("/api/ads/claim", json={}, headers=H(101))).status == 200
    assert (await c.get("/api/adsgram/reward?userid=101&secret=bad")).status == 403
    assert (await c.get("/api/adsgram/reward?userid=101&secret=s3")).status == 200
    r = await c.post("/api/ads/claim", json={}, headers=H(101))
    assert r.status == 429 and (await r.json())["error"] == "limit_reached" and await bal(101) == 4
    await c.close()


@case
async def test_topup_validation_and_pending_limit():
    from aiohttp import FormData
    await mkuser(101); c = await client()
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    def form(amount, data, ct):
        f = FormData(); f.add_field("amount", str(amount)); f.add_field("receipt", data, filename="r.png", content_type=ct); return f
    assert (await c.post("/api/topups", data=form(50000, b"hello", "image/png"), headers=H(101))).status == 400  # soxta rasm
    assert (await c.post("/api/topups", data=form(5, png, "image/png"), headers=H(101))).status == 400  # minimumdan kam
    assert (await c.post("/api/topups", data=form(50000, png, "text/plain"), headers=H(101))).status == 400
    for _ in range(3): assert (await c.post("/api/topups", data=form(50000, png, "image/png"), headers=H(101))).status == 201
    assert (await c.post("/api/topups", data=form(50000, png, "image/png"), headers=H(101))).status == 429
    await c.close()


@case
async def test_username_validation_and_normalization():
    await mkuser(101, 1000); c = await client()
    assert (await c.post("/api/orders", json={**ORDER, "recipient": {"type": "other", "username": "a b"}}, headers=H(101))).status == 400
    assert (await c.post("/api/orders", json={**ORDER, "recipient": {"type": "other", "username": "@Some_User1"}}, headers=H(101))).status == 201
    assert await main.P.fetchval("SELECT recipient FROM orders") == "Some_User1"
    await c.close()


def test_bot_texts_same_keys_and_placeholders_in_all_languages():
    import string
    assert set(main.BT["uz"]) == set(main.BT["ru"]) == set(main.BT["en"])
    fields = lambda t: {f[1] for f in string.Formatter().parse(t) if f[1]}
    for k in main.BT["uz"]: assert fields(main.BT["uz"][k]) == fields(main.BT["ru"][k]) == fields(main.BT["en"][k]), k


def test_every_receipt_reason_is_translated():
    for code in ("duplicate_receipt", "amount_mismatch", "amount_not_found", "card_mismatch", "card_not_found", "too_old", "future_date", "date_not_found", "ocr_failed", "low_quality", "manual_reject"):
        assert code in main.RT and len(main.RT[code]) == 3


def test_clean_html_allows_only_safe_tags():
    assert main.clean_html("<b>x</b><script>y</script>") == "<b>x</b>&lt;script&gt;y&lt;/script&gt;"
    assert main.clean_html('<a href="https://t.me/x">l</a>') == '<a href="https://t.me/x">l</a>'
    assert '<a href="javascript' not in main.clean_html('<a href="javascript:alert(1)">l</a>')
