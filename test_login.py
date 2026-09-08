"""
Тестовый скрипт: авторизация на drom.ru под одним из аккаунтов из Google Таблицы.

Логика:
1. Берём город/логин/пароль из листа "Логин\\Пароль Дром" (по умолчанию — первая строка).
2. Открываем браузер, заходим на страницу входа.
3. Вводим логин и пароль, нажимаем "Войти с паролем".
4. Проверяем, что вход прошёл успешно (адрес страницы изменился и больше не содержит /sign).

Перед запуском:
- credentials.json должен лежать в этой же папке
- один раз выполнить: playwright install chromium
"""

import sys
import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ---- Настройки ----
CREDENTIALS_FILE = "credentials.json"
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1TwktqeDapCHr-jfCJnJYuprK_MNUMTOEWktRyYvqAeo/edit"
ACCOUNTS_SHEET_NAME = "Логин\\Пароль Дром"
LOGIN_URL = "https://my.drom.ru/sign?return=https%3A%2F%2Fwww.drom.ru%2Fmy%2F"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def get_account(row_index: int = 0, city_name: str = None):
    """Читает один аккаунт (город, логин, пароль) из таблицы.
    Если указан city_name — ищет строку с этим городом (без учёта регистра).
    Иначе берёт строку по индексу row_index (0 = первая строка)."""
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_url(SPREADSHEET_URL)
    accounts_sheet = spreadsheet.worksheet(ACCOUNTS_SHEET_NAME)
    rows = accounts_sheet.get_all_values()

    if city_name:
        for row in rows:
            if len(row) >= 3 and row[0].strip().lower() == city_name.strip().lower():
                return row[0], row[1], row[2]
        raise ValueError(f"Город «{city_name}» не найден в таблице")

    if row_index >= len(rows):
        raise ValueError(f"В таблице нет строки с индексом {row_index}")

    city, login, password = rows[row_index][0], rows[row_index][1], rows[row_index][2]
    return city, login, password


def login_to_drom(login: str, password: str, city: str):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        print(f"Открываю страницу входа для города «{city}»...")
        page.goto(LOGIN_URL)

        page.get_by_role("textbox", name="Телефон / Логин").click()
        page.get_by_role("textbox", name="Телефон / Логин").fill(login)

        page.get_by_role("textbox", name="Пароль").click()
        page.get_by_role("textbox", name="Пароль").fill(password)

        page.get_by_role("button", name="Войти с паролем").click()

        # Проверяем, не появился ли экран доп. проверки (СМС, капча и т.п.)
        page.wait_for_timeout(2000)  # даём странице секунду на переход
        if "/sign" in page.url:
            print("\n⚠️  Сайт запросил дополнительную проверку (СМС-код, капча или что-то ещё).")
            print("   Браузер поставлен на паузу — заверши вход вручную в открывшемся окне.")
            print("   Затем нажми ▶ Resume в окне Playwright Inspector, чтобы продолжить скрипт.\n")
            page.pause()

        # Проверяем успешный вход: ждём, пока адрес страницы уйдёт со /sign
        try:
            page.wait_for_url(lambda url: "/sign" not in url, timeout=10000)
            print(f"✅ Успешный вход. Текущий адрес: {page.url}")
            success = True
        except PlaywrightTimeoutError:
            print(f"❌ Вход не подтверждён — страница осталась на {page.url}")
            print("   Возможные причины: неверный пароль, капча, доп. проверка (2FA), или изменилась разметка сайта.")
            page.screenshot(path="login_failed.png")
            print("   Скриншот сохранён как login_failed.png — посмотри, что показывает сайт.")
            success = False

        context.close()
        browser.close()
        return success


def main():
    # Можно запустить: python test_login.py Москва — тогда возьмётся аккаунт этого города.
    # Без аргумента — берётся первая строка таблицы.
    city_arg = sys.argv[1] if len(sys.argv) > 1 else None
    city, login, password = get_account(row_index=0, city_name=city_arg)
    print(f"Аккаунт для теста: {city} / {login}")

    result = login_to_drom(login, password, city)

    if result:
        print("\nТест пройден успешно.")
        sys.exit(0)
    else:
        print("\nТест не пройден, см. login_failed.png")
        sys.exit(1)


if __name__ == "__main__":
    main()
