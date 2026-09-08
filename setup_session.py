"""
Создаёт сохранённую сессию (cookies) для одного аккаунта Drom, чтобы в будущем
не логиниться заново при каждом запуске бота.

Запуск:
    python setup_session.py Красноярск

Результат:
    sessions/Красноярск.json — файл с сохранённой сессией браузера.

Если появится экран подтверждения по СМС — скрипт остановится и попросит
завершить вход вручную (ввести код), как и в test_login.py.
"""

import sys
import os
import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

CREDENTIALS_FILE = "credentials.json"
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1TwktqeDapCHr-jfCJnJYuprK_MNUMTOEWktRyYvqAeo/edit"
ACCOUNTS_SHEET_NAME = "Логин\\Пароль Дром"
LOGIN_URL = "https://my.drom.ru/sign?return=https%3A%2F%2Fwww.drom.ru%2Fmy%2F"
SESSIONS_DIR = "sessions"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def get_account(city_name: str):
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_url(SPREADSHEET_URL)
    accounts_sheet = spreadsheet.worksheet(ACCOUNTS_SHEET_NAME)
    rows = accounts_sheet.get_all_values()

    for row in rows:
        if len(row) >= 3 and row[0].strip().lower() == city_name.strip().lower():
            return row[0], row[1], row[2]
    raise ValueError(f"Город «{city_name}» не найден в таблице")


def create_session(city: str, login: str, password: str):
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    session_path = os.path.join(SESSIONS_DIR, f"{city}.json")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        print(f"Открываю страницу входа для города «{city}»...")
        page.goto(LOGIN_URL)

        try:
            page.get_by_role("textbox", name="Телефон / Логин").click(timeout=15000)
            page.get_by_role("textbox", name="Телефон / Логин").fill(login)

            page.get_by_role("textbox", name="Пароль").click()
            page.get_by_role("textbox", name="Пароль").fill(password)

            page.get_by_role("button", name="Войти с паролем").click()
        except PlaywrightTimeoutError:
            screenshot_path = f"setup_session_failed_{city}.png"
            page.screenshot(path=screenshot_path)
            print(f"❌ Форма входа не появилась вовремя — похоже, сайт показал что-то другое")
            print(f"   (антифрод/капча/лимит?). Скриншот: {screenshot_path}")
            print(f"   Текущий адрес: {page.url}")
            context.close()
            browser.close()
            return False

        page.wait_for_timeout(2000)
        if "/sign" in page.url:
            print("\n⚠️  Сайт запросил дополнительную проверку (СМС-код, капча или что-то ещё).")
            print("   Заверши вход вручную в открывшемся окне браузера.")
            print("   Затем нажми ▶ Resume в окне Playwright Inspector, чтобы продолжить.\n")
            page.pause()

        try:
            page.wait_for_url(lambda url: "/sign" not in url, timeout=10000)
            print(f"✅ Успешный вход. Текущий адрес: {page.url}")

            # Сохраняем сессию (cookies + local storage) в файл
            context.storage_state(path=session_path)
            print(f"💾 Сессия сохранена: {session_path}")
            success = True
        except PlaywrightTimeoutError:
            print(f"❌ Вход не подтверждён — страница осталась на {page.url}")
            page.screenshot(path=f"session_failed_{city}.png")
            print(f"   Скриншот сохранён как session_failed_{city}.png")
            success = False

        context.close()
        browser.close()
        return success


def main():
    if len(sys.argv) < 2:
        print("Использование: python setup_session.py <Город>")
        sys.exit(1)

    city_arg = sys.argv[1]
    city, login, password = get_account(city_arg)
    print(f"Аккаунт: {city} / {login}")

    result = create_session(city, login, password)
    sys.exit(0 if result else 1)


if __name__ == "__main__":
    main()
