"""Генератор xlsx-шаблонов для онбординга Print Cafe.

Запуск:
    uv run python client_intake/_generate_xlsx.py
или
    python client_intake/_generate_xlsx.py

Создаёт два файла рядом со скриптом:
    - 02_products.xlsx
    - 03_pricing.xlsx

Файл нужен команде разработки, чтобы при необходимости перегенерировать
шаблоны. Заказчику отдавать его не нужно.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

HERE = Path(__file__).parent

HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
EXAMPLE_FILL = PatternFill("solid", fgColor="EAF3FB")
EXAMPLE_FONT = Font(italic=True, color="555555")
WRAP = Alignment(wrap_text=True, vertical="top")
HEADER_ALIGN = Alignment(wrap_text=True, vertical="center", horizontal="center")


def style_header(ws: Worksheet, columns: list[tuple[str, int]]) -> None:
    """Шапка: жирный белый текст на синем фоне, заморозка первой строки."""
    for col_idx, (title, width) in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=col_idx, value=title)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    ws.row_dimensions[1].height = 32
    ws.freeze_panes = "A2"


def fill_examples(ws: Worksheet, rows: list[list[object]]) -> None:
    """Заполнить пример-строки и подсветить, чтобы заказчик видел, где образец."""
    for row_idx, row in enumerate(rows, start=2):
        for col_idx, value in enumerate(row, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.fill = EXAMPLE_FILL
            cell.font = EXAMPLE_FONT
            cell.alignment = WRAP
        ws.row_dimensions[row_idx].height = 60


def make_products() -> Workbook:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Каталог"

    columns: list[tuple[str, int]] = [
        ("Артикул / SKU", 16),
        ("Название", 28),
        ("Категория", 16),
        ("Бренд / производитель", 18),
        ("Материал и плотность", 22),
        ("Доступные размеры", 22),
        ("Доступные цвета", 24),
        ("Минимальный тираж", 14),
        ("Базовая цена за шт. (без печати), ₽", 16),
        ("Доступные методы печати", 26),
        ("Размер области печати, см × см", 18),
        ("Ссылка на фото / карточку", 30),
        ("Примечания", 26),
    ]
    style_header(ws, columns)

    examples: list[list[object]] = [
        [
            "TS-STED-CL",
            "Футболка Stedman Classic-T",
            "футболка",
            "Stedman",
            "хлопок 155 г/м²",
            "XS, S, M, L, XL, XXL",
            "белый, чёрный, серый, синий, красный",
            1,
            390,
            "DTG, шелкография, термотрансфер",
            "30 × 40",
            "https://printcafe.ru/catalog/ts-sted-cl",
            "Самая ходовая модель, всегда в наличии",
        ],
        [
            "TS-SOLS-IMP",
            "Футболка Sol's Imperial",
            "футболка",
            "Sol's",
            "хлопок 190 г/м²",
            "S, M, L, XL, XXL",
            "белый, чёрный, серый меланж, бордо",
            10,
            520,
            "DTG, шелкография",
            "30 × 40",
            "https://printcafe.ru/catalog/ts-sols-imp",
            "Плотнее Stedman, для премиум-заказов",
        ],
        [
            "HD-GIL-18500",
            "Толстовка Gildan Heavy Blend 18500",
            "толстовка",
            "Gildan",
            "хлопок 50% / полиэстер 50%, 280 г/м²",
            "S, M, L, XL, XXL",
            "чёрный, серый, тёмно-синий, бордо",
            5,
            1850,
            "DTG, шелкография, вышивка",
            "28 × 35",
            "https://printcafe.ru/catalog/hd-gil-18500",
            "Капюшон, карман-кенгуру",
        ],
        [
            "MUG-CER-330",
            "Кружка керамическая 330 мл",
            "кружка",
            "своё",
            "керамика, белая глянец",
            "330 мл",
            "белый",
            1,
            180,
            "сублимация, УФ",
            "20 × 8 (запахом)",
            "https://printcafe.ru/catalog/mug-cer-330",
            "Можно сублимация фото-качество",
        ],
        [
            "BAG-COTTON-38",
            "Шоппер хлопковый 38×42 см",
            "шоппер",
            "своё",
            "хлопок 220 г/м², суровый",
            "38 × 42 см, ручки 60 см",
            "натуральный, чёрный, белый",
            10,
            210,
            "DTG, шелкография, термотрансфер",
            "25 × 30",
            "https://printcafe.ru/catalog/bag-cotton-38",
            "Под брендирование на корпоративы",
        ],
    ]
    fill_examples(ws, examples)

    return wb


def make_pricing() -> Workbook:
    wb = Workbook()
    default_sheet = wb.active
    assert default_sheet is not None
    wb.remove(default_sheet)

    # ---------- Лист 1: Цены печати ----------
    ws1 = wb.create_sheet("Цены печати")
    cols1: list[tuple[str, int]] = [
        ("Категория продукта", 18),
        ("Метод печати", 18),
        ("1–10 шт, ₽/шт", 14),
        ("11–50 шт, ₽/шт", 14),
        ("51–100 шт, ₽/шт", 14),
        ("101–500 шт, ₽/шт", 14),
        ("500+ шт, ₽/шт", 14),
        ("Примечания", 30),
    ]
    style_header(ws1, cols1)
    fill_examples(
        ws1,
        [
            ["футболка", "DTG", 350, 290, 240, 200, 170, "Полноцвет, 1 сторона"],
            ["футболка", "шелкография (1 цвет)", "—", 180, 130, 90, 60, "От 11 шт"],
            ["футболка", "шелкография (4 цвета)", "—", 320, 240, 170, 120, "От 11 шт, доп. цвета +50 ₽/цвет"],
            ["футболка", "термотрансфер", 250, 210, 180, 150, 130, "До A4"],
            ["толстовка", "DTG", 450, 380, 320, 270, 230, ""],
            ["толстовка", "вышивка (до 5 тыс. стежков)", 350, 320, 280, 250, 220, "Логотип на груди"],
            ["кружка", "сублимация", 150, 130, 110, 90, 75, "Полноцвет вокруг"],
            ["кружка", "УФ", 200, 180, 160, 140, 120, "Можно белилами"],
            ["шоппер", "шелкография (1 цвет)", "—", 110, 90, 70, 55, "От 11 шт"],
            ["кепка", "вышивка", 280, 250, 220, 190, 170, "Лоб, до 7 тыс. стежков"],
        ],
    )

    # ---------- Лист 2: Доплаты ----------
    ws2 = wb.create_sheet("Доплаты")
    cols2: list[tuple[str, int]] = [
        ("Опция", 28),
        ("Описание", 40),
        ("Стоимость", 22),
    ]
    style_header(ws2, cols2)
    fill_examples(
        ws2,
        [
            ["Доп. цвет (шелкография)", "Каждый цвет сверх первого", "+50 ₽/шт за цвет"],
            ["Двусторонняя печать", "Печать спереди и сзади на одном изделии", "+70% к стоимости печати"],
            ["Печать большим форматом (A3+)", "Площадь нанесения больше 30×40 см", "+30% к стоимости печати"],
            ["Срочность 24 часа", "Готов к выдаче за сутки", "+100% к стоимости печати"],
            ["Срочность 3 дня", "Готов к выдаче за 3 рабочих дня", "+50% к стоимости печати"],
            ["Печать по тёмной ткани (DTG)", "Подложка белилами", "+30 ₽/шт"],
            ["Индивидуальная упаковка", "Каждое изделие в полипакет с биркой", "+15 ₽/шт"],
        ],
    )

    # ---------- Лист 3: Доп. услуги ----------
    ws3 = wb.create_sheet("Доп. услуги")
    cols3: list[tuple[str, int]] = [
        ("Услуга", 30),
        ("Стоимость", 22),
        ("Срок", 22),
        ("Примечания", 36),
    ]
    style_header(ws3, cols3)
    fill_examples(
        ws3,
        [
            ["Отрисовка макета (простой логотип)", "от 1 500 ₽", "1 рабочий день", "Готовый текст + 1–2 элемента"],
            ["Отрисовка макета (сложный)", "от 3 500 ₽", "2–3 рабочих дня", "Иллюстрация, несколько вариантов"],
            ["Векторизация растрового логотипа", "от 800 ₽", "1 рабочий день", ""],
            ["Доставка по Москве в пределах МКАД", "500 ₽", "1–2 дня", "Курьер до двери"],
            ["Доставка СДЭК по России", "по тарифу СДЭК", "3–7 дней", "Расчёт при оформлении"],
            ["Образец / тестовая печать", "себестоимость + 300 ₽", "2–3 дня", "Сумма зачитывается при тираже от 30 шт"],
            ["Самовывоз", "0 ₽", "—", "ул. Примерная, 1, по будням 10:00–19:00"],
        ],
    )

    # ---------- Лист 4: Скидки ----------
    ws4 = wb.create_sheet("Скидки")
    cols4: list[tuple[str, int]] = [
        ("Условие", 40),
        ("Скидка", 18),
        ("Примечания", 36),
    ]
    style_header(ws4, cols4)
    fill_examples(
        ws4,
        [
            ["Постоянный клиент (от 3 заказов за год)", "5%", "На печать, не на сами изделия"],
            ["Юрлицо с НДС, договор", "по запросу", "Обсуждается при оформлении"],
            ["Объём от 200 шт", "5%", "Применяется к строке прайса"],
            ["Объём от 500 шт", "10%", ""],
            ["Объём от 1 000 шт", "15%", "+ возможна индивидуальная цена"],
            ["Школы, вузы, НКО", "10%", "При предъявлении подтверждающих документов"],
            ["Самовывоз", "—", "Просто без доплаты за доставку"],
        ],
    )

    return wb


def main() -> None:
    products_path = HERE / "02_products.xlsx"
    pricing_path = HERE / "03_pricing.xlsx"

    make_products().save(products_path)
    make_pricing().save(pricing_path)

    print(f"OK: {products_path}")
    print(f"OK: {pricing_path}")


if __name__ == "__main__":
    main()
