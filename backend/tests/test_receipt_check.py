from datetime import datetime
from app import receipt_check as rc

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=rc.TZ)
CFG = {"max_age_minutes": 60, "require_card_match": False}
CARD = "8600 1234 5678 9012"
OK = "Перевод выполнен\nСумма: 50 000 сум\nКарта **** 9012\n01.11.2026 11:45:10"


def ev(text, amount=50000, cfg=CFG, dup=False): return rc.evaluate(text, amount, CARD, cfg, dup, NOW)


def test_pass(): assert ev(OK)["verdict"] == "pass"
def test_amount_mismatch(): r = ev(OK.replace("50 000", "60 000")); assert r["verdict"] == "fail" and "amount_mismatch" in r["reasons"]
def test_amount_not_found(): r = ev("Chek\n01.11.2026 11:45\n**** 9012"); assert r["verdict"] == "review" and "amount_not_found" in r["reasons"]
def test_decimals_and_dots(): assert rc.amounts("Итого 50.000,00 UZS")[0] == [50000]
def test_card_not_counted_as_amount(): assert rc.amounts("8600 1234 5678 9012\n50 000 so'm")[1] == []
def test_too_old(): r = ev(OK.replace("11:45:10", "09:00:00")); assert r["verdict"] == "fail" and "too_old" in r["reasons"]
def test_future(): r = ev(OK.replace("11:45:10", "13:00:00")); assert "future_date" in r["reasons"]
def test_no_date(): r = ev("Сумма 50 000 сум\n**** 9012"); assert r["verdict"] == "review" and "date_not_found" in r["reasons"]
def test_card_mismatch(): r = ev(OK.replace("9012", "1111")); assert "card_mismatch" in r["reasons"] and r["verdict"] == "review"
def test_card_required(): r = ev(OK.replace("**** 9012", ""), cfg={**CFG, "require_card_match": True}); assert "card_not_found" in r["reasons"]
def test_duplicate(): assert ev(OK, dup=True)["reasons"] == ["duplicate_receipt"]
def test_low_quality(): assert ev("  ")["reasons"] == ["low_quality"]
def test_hamming(): assert rc.hamming("0000000000000000", "000000000000001f") == 5
