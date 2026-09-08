"""
Заходит в ЛК по сохранённой сессии, открывает вкладку "Объявления"
и сохраняет HTML содержимого страницы в файл для анализа структуры.

Запуск:
    python dump_listings_html.py Красноярск
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

        print("Открываю личный кабинет...")
        page.goto(MY_PAGE_URL)
        page.wait_for_timeout(1500)

        print("Перехожу во вкладку «Объявления»...")
        page.get_by_role("link", name="Объявления").click()
        page.wait_for_timeout(2000)

        print("\n👉 Сейчас вручную:")
        print("   1) нажми «Показывать по 100 на странице» (если есть такая настройка)")
        print("   2) долистай до нужной страницы, если объявлений больше 100")
        print("   Когда всё будет видно на экране, вернись в терминал и нажми Enter.\n")
        input("Нажми Enter, когда готов сохранить HTML: ")

        # Сохраняем HTML всей страницы
        html_content = page.content()
        output_file = f"listings_page_{city}.html"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(html_content)

        print(f"💾 HTML сохранён: {output_file}")

        context.close()
        browser.close()
        return True


def main():
    if len(sys.argv) < 2:
        print("Использование: python dump_listings_html.py <Город>")
        sys.exit(1)
    dump_html(sys.argv[1])


if __name__ == "__main__":
    main()
