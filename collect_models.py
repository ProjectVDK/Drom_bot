"""
Собирает все уникальные модели (город + название без года) из всех ЛК,
для которых есть сохранённые сессии в sessions/. Записывает результат
на лист "Модели" и настраивает выпадающий список на столбце "Модель"
листа "Правила".

Запуск:
    python collect_models.py
"""

import os
import glob
import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

from promote_listing import setup_page_view, get_max_page, go_to_page, collect_all_cards

CREDENTIALS_FILE = "credentials.json"
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1TwktqeDapCHr-jfCJnJYuprK_MNUMTOEWktRyYvqAeo/edit"
RULES_SHEET_NAME = "Правила"
MODELS_SHEET_NAME = "Модели"
SESSIONS_DIR = "sessions"
MY_PAGE_URL = "https://www.drom.ru/my/"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def get_client():
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    return gspread.authorize(creds)


def get_sessions_cities():
    files = glob.glob(os.path.join(SESSIONS_DIR, "*.json"))
    return sorted(os.path.splitext(os.path.basename(f))[0] for f in files)


def collect_for_city(city: str):
    session_path = os.path.join(SESSIONS_DIR, f"{city}.json")
    print(f"\n=== Собираю модели: {city} ===")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(storage_state=session_path)
        page = context.new_page()

        page.goto(MY_PAGE_URL)
        page.wait_for_timeout(1000)
        page.get_by_role("link", name="Объявления").click()
        try:
            page.wait_for_selector('[data-ftid="bulls-list_bull"]', timeout=8000)
        except Exception:
            page.wait_for_timeout(2000)

        setup_page_view(page, city)
        page.wait_for_timeout(1000)

        max_page = get_max_page(page)
        print(f"Страниц: {max_page}")

        all_found = set()
        for page_number in range(1, max_page + 1):
            go_to_page(page, page_number)
            print(f"  Страница {page_number}...")
            found = collect_all_cards(page)
            all_found |= found

        context.close()
        browser.close()
        return all_found


def write_models_sheet(spreadsheet, all_models: set):
    try:
        sheet = spreadsheet.worksheet(MODELS_SHEET_NAME)
        sheet.clear()
    except gspread.exceptions.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title=MODELS_SHEET_NAME, rows=len(all_models) + 10, cols=2)

    rows = [["Город", "Модель"]] + sorted(all_models)
    sheet.update(rows)
    print(f"\n💾 Записано на лист «{MODELS_SHEET_NAME}»: {len(all_models)} строк")
    return sheet


def apply_dropdown(spreadsheet, rules_sheet, unique_model_names: list):
    requests = [{
        "setDataValidation": {
            "range": {
                "sheetId": rules_sheet.id,
                "startRowIndex": 1,       # со 2-й строки (после заголовков)
                "endRowIndex": 1000,      # с запасом на будущие правила
                "startColumnIndex": 1,    # столбец B — "Модель"
                "endColumnIndex": 2,
            },
            "rule": {
                "condition": {
                    "type": "ONE_OF_LIST",
                    "values": [{"userEnteredValue": m} for m in unique_model_names],
                },
                "showCustomUi": True,
                "strict": False,  # разрешаем вписать модель вручную, если её вдруг нет в списке
            },
        }
    }]
    spreadsheet.batch_update({"requests": requests})
    print(f"📋 Выпадающий список настроен на «{RULES_SHEET_NAME}» (столбец «Модель»), вариантов: {len(unique_model_names)}")


def main():
    cities = get_sessions_cities()
    if not cities:
        print("❌ Нет сохранённых сессий в папке sessions/")
        return

    print(f"Города с сессиями: {', '.join(cities)}")

    client = get_client()
    spreadsheet = client.open_by_url(SPREADSHEET_URL)

    all_pairs = set()
    for city in cities:
        found = collect_for_city(city)
        all_pairs |= found
        print(f"  Найдено моделей: {len(found)}")

    write_models_sheet(spreadsheet, all_pairs)

    unique_models = sorted({model for (_, model) in all_pairs})
    rules_sheet = spreadsheet.worksheet(RULES_SHEET_NAME)
    apply_dropdown(spreadsheet, rules_sheet, unique_models)

    print("\n✅ Готово.")


if __name__ == "__main__":
    main()
