"""
Заходит в ЛК по сохранённой сессии и сохраняет HTML главной страницы
(до перехода во вкладку "Объявления") — для анализа, где на странице
находится баланс и остатки пакетов продвижения.

Запуск:
    python dump_dashboard_html.py Красноярск
"""

import sys
import os
from playwright.sync_api import sync_playwright

SESSIONS_DIR = "sessions"
MY_PAGE_URL = "https://www.drom.ru/my/"


def dump_html(city: str):
    session_path = os.path.join(SESSIONS_DIR, f"{city}.json")
    if not os.path.exists(session_path):
        print(f"❌ Файл сессии не найден: {session_path}")
        return False

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(storage_state=session_path)
        page = context.new_page()

        print("Открываю главную страницу ЛК...")
        page.goto(MY_PAGE_URL)
        page.wait_for_timeout(2000)

        print("\n👉 Если на странице есть что-то, что нужно раскрыть/прокрутить,")
        print("   чтобы увидеть баланс и остатки пакетов — сделай это вручную.")
        input("Нажми Enter, когда всё нужное видно на экране: ")

        html_content = page.content()
        output_file = f"dashboard_{city}.html"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(html_content)

        print(f"💾 HTML сохранён: {output_file}")

        # Заодно скриншот — так мне проще сопоставить визуально с разметкой
        page.screenshot(path=f"dashboard_{city}.png", full_page=True)
        print(f"📸 Скриншот сохранён: dashboard_{city}.png")

        context.close()
        browser.close()
        return True


def main():
    if len(sys.argv) < 2:
        print("Использование: python dump_dashboard_html.py <Город>")
        sys.exit(1)
    dump_html(sys.argv[1])


if __name__ == "__main__":
    main()
