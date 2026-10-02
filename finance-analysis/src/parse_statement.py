"""
Парсер PDF-выписки Т-Банка («Справка о движении средств», англ. версия).

Что делает:
  1. Достаёт из PDF все операции (дата, время, сумма, описание, карта).
  2. Сверяет итоги с суммами «Replenishment / Expenses» в конце выписки.
  3. Сохраняет СЫРЫЕ данные в data/raw/ (эта папка в .gitignore —
     в ней есть персональные данные, в репозиторий она не попадает).

Запуск:
    python src/parse_statement.py path/to/statement.pdf

Обезличивание и категоризация — в src/categorize.py.
"""
import re
import sys
from pathlib import Path

import pandas as pd
import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"

DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}$")
AMOUNT_RE = re.compile(r"^([+-])([\d\s]+[.,]\d{2})\s*₽$")

# Границы колонок в PDF (координата x левого края, в пунктах)
COL_DATE, COL_PROC, COL_AMOUNT, COL_AMOUNT_CARD, COL_DESC, COL_CARD = (
    56, 126, 199, 294, 389, 499,
)


def _column(x0: float) -> str:
    """Определяет колонку по горизонтальной координате слова."""
    if x0 < COL_PROC - 5:
        return "date"
    if x0 < COL_AMOUNT - 5:
        return "proc"
    if x0 < COL_AMOUNT_CARD - 5:
        return "amount"
    if x0 < COL_DESC - 5:
        return "amount_card"
    if x0 < COL_CARD - 5:
        return "desc"
    return "card"


def _parse_amount(text: str) -> float:
    m = AMOUNT_RE.match(text.strip())
    if not m:
        raise ValueError(f"Не удалось распознать сумму: {text!r}")
    sign = -1 if m.group(1) == "-" else 1
    return sign * float(m.group(2).replace(" ", "").replace(",", "."))


def parse_pdf(pdf_path: Path) -> pd.DataFrame:
    rows = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            words = [
                w for w in page.extract_words(keep_blank_chars=True, x_tolerance=1.5)
                if w["top"] < page.height - 60  # без колонтитула банка
            ]
            # итоги и подпись в конце выписки — дальше операций нет
            stop = [w["top"] for w in words
                    if w["text"].startswith(("Replenishment:", "Best regards"))]
            if stop:
                words = [w for w in words if w["top"] < min(stop) - 2]

            # «якоря» — даты в первой колонке, с них начинается операция
            anchors = sorted(
                w["top"] for w in words
                if _column(w["x0"]) == "date" and DATE_RE.match(w["text"].strip())
            )
            page_rows = [{"date": "", "time": "", "amount": "", "desc": [], "card": ""}
                         for _ in anchors]

            for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
                # строка операции = последний якорь не ниже слова (допуск 3 pt,
                # т.к. сумма в PDF напечатана на 1 pt выше даты)
                idx = max((i for i, a in enumerate(anchors) if a <= w["top"] + 3),
                          default=None)
                if idx is None:
                    continue
                row, col, text = page_rows[idx], _column(w["x0"]), w["text"].strip()
                if col == "date" and DATE_RE.match(text):
                    row["date"] = text
                elif col == "date" and TIME_RE.match(text):
                    row["time"] = text
                elif col == "amount" and "₽" in text and not row["amount"]:
                    row["amount"] = text
                elif col == "desc":
                    row["desc"].append(text)
                elif col == "card" and not row["card"]:
                    row["card"] = text
            rows.extend(page_rows)

    df = pd.DataFrame(rows)
    df["description"] = df["desc"].apply(lambda parts: " ".join(parts))
    df["amount"] = df["amount"].apply(_parse_amount)
    df["datetime"] = pd.to_datetime(df["date"] + " " + df["time"],
                                    format="%d.%m.%Y %H:%M")
    return df[["datetime", "amount", "description", "card"]]


def check_totals(df: pd.DataFrame, pdf_path: Path) -> None:
    """Сверка с итогами из последней страницы выписки."""
    with pdfplumber.open(pdf_path) as pdf:
        last = pdf.pages[-1].extract_text()
    expected = {}
    for key in ("Replenishment", "Expenses"):
        m = re.search(key + r":\s*([\d\s]+,\d{2})", last)
        if m:
            expected[key] = float(m.group(1).replace(" ", "").replace(",", "."))
    got = {
        "Replenishment": round(df.loc[df.amount > 0, "amount"].sum(), 2),
        "Expenses": round(-df.loc[df.amount < 0, "amount"].sum(), 2),
    }
    for key, value in expected.items():
        status = "OK" if abs(value - got[key]) < 0.01 else "РАСХОЖДЕНИЕ"
        print(f"{key:14s} в выписке: {value:>14,.2f}  распарсено: {got[key]:>14,.2f}  {status}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Использование: python src/parse_statement.py statement.pdf")
    pdf_path = Path(sys.argv[1])
    df = parse_pdf(pdf_path)
    print(f"Найдено операций: {len(df)}")
    check_totals(df, pdf_path)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out = RAW_DIR / "transactions_raw.csv"
    df.to_csv(out, index=False)
    print(f"Сырые данные сохранены в {out} (не коммитить!)")
