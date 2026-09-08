"""
Проверяет, что сохранённая сессия (файл в sessions/) всё ещё действительна —
открывает браузер сразу с загруженными cookies, без ввода пароля.

Запуск:
    python check_session.py Красноярск
"""

import sys
import os
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

SESSIONS_DIR = "sessions"
MY_PAGE_URL = "https://www.drom.ru/my/"


def check_session(city: str):
    session_path = os.path.join(SESSIONS_DIR, f"{city}.json")

    if not os.path.exists(session_path):
        print(f"❌ Файл сессии не найден: {session_path}")
        print("   Сначала запусти: python setup_session.py", city)
        return False

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        # Загружаем сохранённую сессию при создании контекста
        context = browser.new_context(storage_state=session_path)
        page = context.new_page()

        print(f"Открываю личный кабинет для «{city}» с сохранённой сессией...")
        page.goto(MY_PAGE_URL)

        try:
            page.wait_for_url(lambda url: "/sign" not in url, timeout=8000)
            page.wait_for_timeout(1500)  # даём странице подгрузиться
            if "/sign" in page.url:
                print(f"❌ Сессия истекла — сайт перенаправил на вход: {page.url}")
                success = False
            else:
                print(f"✅ Сессия рабочая. Открыт личный кабинет: {page.url}")
                success = True
        except PlaywrightTimeoutError:
            print(f"❌ Что-то пошло не так, текущий адрес: {page.url}")
            success = False

        page.screenshot(path=f"session_check_{city}.png")
        print(f"   Скриншот сохранён: session_check_{city}.png")

        context.close()
        browser.close()
        return success


def main():
    if len(sys.argv) < 2:
        print("Использование: python check_session.py <Город>")
        sys.exit(1)

    city = sys.argv[1]
    result = check_session(city)
    sys.exit(0 if result else 1)


if __name__ == "__main__":
    main()
