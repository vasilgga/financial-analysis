"""
Категоризация и обезличивание операций.

Банк не присылает категории в выписке, поэтому каждая операция
размечается правилами (регулярные выражения по описанию).
Заодно из данных убирается всё персональное: номера телефонов,
номера договоров и карт, имена ИП и людей.

Вход:  data/raw/transactions_raw.csv   (результат parse_statement.py)
Выход: data/transactions.csv           (обезличенный, можно публиковать)

Запуск:
    python src/categorize.py
"""
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "transactions_raw.csv"
OUT = ROOT / "data" / "transactions.csv"

# --- Разовые крупные траты (со слов владельца счёта) ----------------------
ONE_OFF = {
    ("2026-09-05", -164947.00): "Отдых в Турции",
    ("2026-09-29", -95000.00): "Покупка MacBook",
}

# --- Правила для расходов: (регулярка, категория, «чистое» имя мерчанта) ---
# Порядок важен: срабатывает первое совпадение.
EXPENSE_RULES = [
    # Транспорт
    (r"YANDEX\*7999\*SCOOTERS|WHOOSH", "Самокаты", "Самокаты (Яндекс / Whoosh)"),
    (r"YANDEX\*4121\*(GO|TAXI|FASTEN)", "Такси", "Яндекс Go"),
    (r"STRELKACARD|Troyka|Mos\.Transport|AVTOBUSNYJ|METRO TPP|Petrogradskaya|"
     r"Elektrosila|bilet\.nspk|CPPK|TsPPK|RASPEL|_?\.?EKSPRESS|OOO PLATFORMA",
     "Общественный транспорт", "Общественный транспорт"),
    (r"AZS", "Общественный транспорт", "АЗС"),
    # Путешествия
    (r"Pobeda|Russian Railways|zhd perevozok", "Путешествия", "Билеты (авиа / ЖД)"),
    # Учёба
    (r"ITMO", "Учёба", "Университет ИТМО"),
    (r"FOTOKSEROKS", "Учёба", "Копицентр"),
    # Алкоголь и табак — выделены отдельно, это «гибкая» категория
    (r"KRASNOE ?(&|I)? ?BELOE|KRASNOEBELOE|WINELAB|BRISTOL|TABAK|BLACK TAB|"
     r"BEER AND FISH|TabakPivo|SPTABAK", "Алкоголь и табак", None),
    # Кафе, рестораны, бары, доставка готовой еды
    (r"BAR |\.BAR|BAR\.|LAUNDZH|SIMACH|NETMONET|KAFE|CAFE|COFFEE|KOFE|WAFFEL|"
     r"SHAVERMA|SHAURM|SHAVERNO|Vkusnoitochka|MOP SBP|ROSTICS|MEALTY|TOKINO|"
     r"MAKSHAVA|BOLO|ASTER|BI-BI|Rest |REMYKITCHEN|SWEE|SWEETSNACK|EFIMOVA|"
     r"DOSTAVKA$|4215\*DOSTAVKA|LYUDI LYUBYAT|PROSTO VASYA|CITY 6|KOMSOMOLSKAYA|"
     r"Unloc|SOKOL|SHLEND|Coffee|karrot|PEKOTBMF|AVANTA", "Кафе и рестораны", None),
    # Продукты
    (r"PYATEROCHK|DIXY|PEREK|MAGNIT|Lenta|VKUSVILL|LAVKA|SAMOKAT|SPAR|MONETKA|"
     r"VERNYJ|UNIVERSAM|PRODUKTY|GASTRONOM|SUPERMARKET|FERMER|TDREAL|TDReal|"
     r"Hlebnitca|PEKARNYA|KHLEB|MAGAZ|GRAND|Payment in AM\b|B118|FASOL|SOLNECHNYJ|"
     r"PRESNENSKIY|HOROSHEVSKIJ|NOSOVIKHINSKOE|DA S50|Uralskaya|Magazin|"
     r"OOO Veles|ASTRA|DIKIJ LOS",
     "Продукты", None),
    # Подписки и связь
    (r"T-? ?Bundle|PLUS|5815\*PLATFORM|VK Music|TELEGRAM|Tmobile|mBank\.t2|"
     r"Uyut Telekom|t\.me|planetconfig", "Подписки и связь", None),
    # Покупки (одежда, техника, маркетплейсы, рассрочка)
    (r"Dolyame", "Покупки", "Долями (рассрочка)"),
    (r"AVITO|Avito", "Покупки", "Авито"),
    (r"SIRKA|BEFREE|GOLD APPLE|ULYBKA RADUGI|Kleek|DNS|32links|"
     r"Avtozapchasti|AVTOZAPCHASTI", "Покупки", None),
    # Развлечения
    (r"INTIKETS|SINEMA|MIRAZH|GAME SERVICES|WINLINE", "Развлечения", None),
    # Здоровье
    (r"APTE|apteka", "Здоровье", "Аптека"),
    # Документы и госуслуги
    (r"DOKUMENT|DOCUMENT|GOSUSLUGI|Foto Uslugi|MFC|GCUPSBP", "Госуслуги и документы", None),
    # Сервисы
    (r"RUNCHARG|zabota|YM\*AMPP|\bID\b", "Прочие сервисы", None),
    # Небольшие точки у индивидуальных предпринимателей (ларьки, кофейни,
    # шаурмичные). По выписке тип точки не определить — отдельная категория.
    (r"\bIP\b|SP_?IP|SPIP", "Мелкие точки (ИП)", "ИП (название скрыто)"),
]

# Приведение названий сетей к читаемому виду
CHAINS = [
    (r"PYATEROCHK", "Пятёрочка"), (r"DIXY", "Дикси"), (r"PEREK", "Перекрёсток"),
    (r"MAGNIT", "Магнит"), (r"LAVKA", "Яндекс Лавка"), (r"TDREAL|TDReal", "ТД Реал"),
    (r"Vkusnoitochka|MOP SBP", "Вкусно — и точка"), (r"UNIVERSAM", "Универсам"),
    (r"BAR YUNION", "Бар Юнион"), (r"SIMACH", "Бар Симачёв"),
    (r"SHAURM|SHAVERM|SHAVERNO", "Шаурма"), (r"VKUSVILL", "ВкусВилл"),
    (r"Lenta", "Лента"), (r"T-? ?Bundle", "Т-Банк подписки"),
    (r"Tmobile|mBank\.t2", "Мобильная связь"), (r"INTIKETS", "Билеты на мероприятия"),
    (r"SIRKA", "Одежда (аутлет)"), (r"TELEGRAM", "Telegram Premium"), (r"Hlebnitca", "Хлебница"),
    # адреса магазинов у дома не публикуем
    (r"HOROSHEVSKIJ|PRESNENSKIY|NOSOVIKHINSKOE|Uralskaya|MAGAZ|Magazin|PRODUKTY|"
     r"DA S50|B118|CITY 6|Payment in AM\b|GRAND|FASOL|VERNYJ|SPAR|SUPERMARKET|"
     r"GASTRONOM|MONETKA|SOLNECHNYJ|DIKIJ LOS|OOO Veles|ASTRA|FERMER", "Продуктовый магазин"),
    (r"VK Music", "VK Музыка"), (r"5815\*PLUS", "Яндекс Плюс"), (r"5815\*PLATFORM", "Яндекс (подписка)"),
    (r"t\.me", "VPN (Telegram-бот)"), (r"Uyut Telekom", "Домашний интернет"),
    (r"KRASNOE|BELOE", "Красное&Белое"), (r"WINELAB", "Винлаб"),
]

# Имена ИП, люди, номера — всё, что нельзя публиковать
PERSONAL_RE = re.compile(
    r"\bIP\b.*|\bSP_?IP\b.*|\+7\d{10}|\b\d{6,}\b|\*{2,}.*|contract.*", re.I
)


def _clean_merchant(desc: str) -> str:
    """Обезличенное имя мерчанта из описания платежа."""
    name = re.sub(r"^Payment in\s+", "", desc)
    name = re.sub(r"\s+(SANKT-? ?PETERBU|Sankt-? ?Peterbu|Sankt-Pete|SPb|MOSCOW|"
                  r"MOSKVA|Moskva|Moscow|g\. Moskva|Reutov|Vidnoe|VIDNOE|"
                  r"Cheboksary|Kommunar|Tarychevo|Yagodnoe|Dolgoprudnyj|"
                  r"Ekaterinburg|Kazan|Saint-Petersb|MYTISCHI|Arzamas|Lakinsk|"
                  r"Lesnaya).*$", "", name)
    if re.search(r"\bIP\b|SP_?IP|SPIP", name):
        return "ИП (название скрыто)"
    name = PERSONAL_RE.sub("", name)
    return re.sub(r"\s+", " ", name).strip(" .,_-") or "—"


def classify(row: pd.Series) -> tuple[str, str, str]:
    """Возвращает (тип операции, категория, мерчант)."""
    desc, amount = row["description"], row["amount"]
    key = (row["datetime"][:10], round(amount, 2))

    # --- разовые крупные траты
    if key in ONE_OFF:
        return "expense", "Крупные разовые траты", ONE_OFF[key]

    # --- движения между своими счетами (накопительный, кредитка и т.п.)
    if re.search(r"Intrabank transfer from contract|Internal transfer to contract|"
                 r"c2c transfer ATM", desc):
        return "internal", "Переводы между своими счетами", "Свой счёт"

    # --- доходы и поступления
    if amount > 0:
        if "Replenishment with a partner ATM" in desc:
            return "income", "Зарплата", "Зарплата (внесение наличных)"
        if re.search(r"Cashback|Bonus", desc):
            return "refund", "Кэшбэк и бонусы", "Т-Банк"
        # возврат относим к категории исходной покупки, чтобы траты считались «нетто»
        if "AVIAKOMPANIY" in desc:
            return "refund", "Путешествия", "Возврат за авиабилет"
        if "TAXI" in desc:
            return "refund", "Такси", "Возврат за такси"
        if "Refund" in desc:
            return "refund", "Продукты", "Возврат за покупку"
        return "other_income", "Поступления от людей", "Перевод от физлица"

    # --- расходы
    if re.search(r"External transfer by phone|mBank\.perevod|transfer to card", desc, re.I):
        return "expense", "Переводы людям", "Перевод физлицу"
    if "Cash withdrawal" in desc:
        if "WINLINE" in desc:
            return "expense", "Развлечения", "Букмекер"
        return "expense", "Наличные", "Снятие наличных"
    if "Transfer fee" in desc:
        return "expense", "Комиссии", "Комиссия банка"

    for pattern, category, merchant in EXPENSE_RULES:
        if re.search(pattern, desc):
            if merchant is None:
                merchant = next((name for pat, name in CHAINS
                                 if re.search(pat, desc)), _clean_merchant(desc))
            return "expense", category, merchant
    return "expense", "Прочее", _clean_merchant(desc)


def main() -> None:
    raw = pd.read_csv(RAW)
    raw[["type", "category", "merchant"]] = raw.apply(
        lambda r: pd.Series(classify(r)), axis=1
    )
    dt = pd.to_datetime(raw["datetime"])
    out = pd.DataFrame({
        "date": dt.dt.date,
        "time": dt.dt.strftime("%H:%M"),
        "amount": raw["amount"],
        "type": raw["type"],
        "category": raw["category"],
        "merchant": raw["merchant"],
    }).sort_values(["date", "time"]).reset_index(drop=True)

    out.to_csv(OUT, index=False)
    print(f"Сохранено {len(out)} операций в {OUT}")
    print(out.groupby(["type", "category"])["amount"].agg(["count", "sum"]).round(0))


if __name__ == "__main__":
    main()
