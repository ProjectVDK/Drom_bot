"""
Собирает с главной страницы ЛК: денежный баланс и остатки пакетов
(Поднять/Прикрепить) по каждому городу, представленному в этом ЛК.

Использование как модуль:
    from dashboard_scraper import get_dashboard_info
    info = get_dashboard_info("Красноярск")

Тестовый запуск:
    python dashboard_scraper.py Красноярск
"""

import sys
import os
import re
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

SESSIONS_DIR = "sessions"
MY_PAGE_URL = "https://www.drom.ru/my/"


def scrape_dashboard(page) -> dict:
    data = {"balance": None, "packages": []}

    try:
        balance_el = page.locator('[data-ftid="my-account_balance_amount"]')
        raw = balance_el.inner_text(timeout=3000)
        data["balance"] = raw.replace("\xa0", " ").strip()
    except PlaywrightTimeoutError:
        pass

    packages = page.locator('[data-ftid="my-account_package"]')
    count = packages.count()

    for i in range(count):
        pkg = packages.nth(i)
        try:
            title = pkg.locator('[data-ftid="package_title"]').inner_text(timeout=1000)
        except PlaywrightTimeoutError:
            continue

        is_sticky = pkg.locator('[data-ftid="categoryId=1_type=sticky"]').count() > 0
        is_up = pkg.locator('[data-ftid="categoryId=1_type=up"]').count() > 0
        ptype = "sticky" if is_sticky else ("up" if is_up else "unknown")

        try:
            expiry = pkg.locator('[data-ftid="package-expiry-date"]').inner_text(timeout=1000)
        except PlaywrightTimeoutError:
            expiry = ""

        try:
            caption_text = pkg.locator('[data-ftid="package_caption"]').inner_text(timeout=1000)
            lines = [l.strip() for l in caption_text.split("\n") if l.strip()]
            city = lines[-1] if lines else ""
        except PlaywrightTimeoutError:
            city = ""

        # "1 прикрепление" -> остаток 1; "41 поднятие" -> остаток 41
        match = re.match(r"(\d+)", title.strip())
        remaining = int(match.group(1)) if match else None

        data["packages"].append({
            "type": ptype,
            "title": title.strip(),
            "remaining": remaining,
            "expiry": expiry.strip(),
            "city": city,
        })

    return data


def get_dashboard_info(city: str) -> dict:
    session_path = os.path.join(SESSIONS_DIR, f"{city}.json")
    if not os.path.exists(session_path):
        print(f"❌ Файл сессии не найден: {session_path}")
        return {"balance": None, "packages": []}

    with sync_playwright() as playwright:
        # headless=True — облачный/безголовый запуск, используем сохранённую сессию,
        # СМС/капча в этом сценарии не появляются.
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(storage_state=session_path)
        page = context.new_page()

        try:
            page.goto(MY_PAGE_URL, wait_until="domcontentloaded", timeout=45000)
        except PlaywrightTimeoutError:
            print("⚠️  Страница не загрузилась с первой попытки — пробую ещё раз...")
            page.goto(MY_PAGE_URL, wait_until="domcontentloaded", timeout=45000)

        page.wait_for_timeout(1500)

        data = scrape_dashboard(page)

        context.close()
        browser.close()
        return data


def main():
    if len(sys.argv) < 2:
        print("Использование: python dashboard_scraper.py <Город>")
        sys.exit(1)

    city = sys.argv[1]
    info = get_dashboard_info(city)

    print(f"\nБаланс: {info['balance']}")
    print("Пакеты:")
    for pkg in info["packages"]:
        print(f"  [{pkg['type']}] {pkg['city']}: {pkg['title']} — {pkg['expiry']}")


if __name__ == "__main__":
    main()
