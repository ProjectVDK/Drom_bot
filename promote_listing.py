"""
Находит объявление по городу + модели и применяет к нему продвижение
("Поднять" или "Прикрепить"), используя пакетные продвижения (без прямой оплаты).

Запуск (для теста):
    python promote_listing.py Красноярск "XCMG XT3207K" up
    python promote_listing.py Красноярск "XCMG XT3207K" sticky

Второй аргумент — часть названия модели (проверяется вхождением, без учёта регистра).
Третий аргумент — "up" (Поднять) или "sticky" (Прикрепить).
"""

import sys
import os
import re
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

SESSIONS_DIR = "sessions"
MY_PAGE_URL = "https://www.drom.ru/my/"

ACTION_NAMES = {
    "up": "Поднять",
    "sticky": "Прикрепить",
}


def collect_all_cards(page, max_scrolls: int = 80):
    """Прокручивает список и собирает уникальные пары (город, модель без года)
    со всех карточек, видимых на текущей странице пагинации."""
    collected = set()
    for _ in range(max_scrolls):
        cards = page.locator('[data-ftid="bulls-list_bull"]')
        count = cards.count()

        for i in range(count):
            card = cards.nth(i)
            try:
                title = card.locator('[data-ftid="title"]').inner_text(timeout=500)
                location = card.locator('[data-ftid="bull_location"]').inner_text(timeout=500)
            except PlaywrightTimeoutError:
                continue

            base_model = re.sub(r",\s*\d{4}\s*$", "", title.strip())
            collected.add((location.strip(), base_model))

        page.mouse.wheel(0, 900)
        page.wait_for_timeout(300)

    return collected


def process_card_action(page, card, action: str):
    """Выполняет действие (up/sticky) над уже найденной карточкой.
    Возвращает (status, info) — та же логика, что и внутри find_and_click_card,
    но вынесена отдельно для переиспользования в пакетной обработке."""

    try:
        url = card.locator('[data-ftid="title"]').locator("xpath=ancestor::a[1]").get_attribute("href", timeout=1000) or ""
    except PlaywrightTimeoutError:
        url = ""
    title = card.locator('[data-ftid="title"]').inner_text(timeout=1000)
    info = {"title": title, "url": url}

    if action == "up":
        try:
            last_date_text = card.locator('[data-ftid="bull_date"]').inner_text(timeout=1000)
        except PlaywrightTimeoutError:
            last_date_text = ""
        if "назад" in last_date_text:
            print(f"⏭️  «{title}»: Поднять уже применялось сегодня ({last_date_text}).")
            return "already_active", info

    button = card.locator(f'[data-ftid="{action}"]')
    button_text = button.inner_text(timeout=1000)
    expected_label = ACTION_NAMES[action]
    if expected_label not in button_text:
        print(f"⏭️  «{title}»: {expected_label} уже активно ({button_text}).")
        return "already_active", info

    button.click()
    confirmed = confirm_promotion(page)
    if confirmed:
        page.wait_for_timeout(1000)
        print(f"✅ «{title}»: {expected_label} применено.")
        return "clicked", info
    else:
        page.screenshot(path=f"promote_aborted_{title[:20]}.png")
        return "aborted", info


def scan_and_process_page(page, city: str, remaining_targets: list, max_scrolls: int = 80):
    """Прокручивает ТЕКУЩУЮ страницу и сверяет видимые карточки со всеми ещё
    не найденными целями (remaining_targets). Найденные цели обрабатываются
    сразу и удаляются из remaining_targets. Возвращает список результатов."""
    results = []

    for _ in range(max_scrolls):
        if not remaining_targets:
            break

        cards = page.locator('[data-ftid="bulls-list_bull"]')
        count = cards.count()

        for i in range(count):
            if not remaining_targets:
                break
            card = cards.nth(i)
            try:
                title = card.locator('[data-ftid="title"]').inner_text(timeout=500)
                location = card.locator('[data-ftid="bull_location"]').inner_text(timeout=500)
            except PlaywrightTimeoutError:
                continue

            if location.strip().lower() != city.strip().lower():
                continue

            match_idx = None
            for idx, target in enumerate(remaining_targets):
                if target["model"].strip().lower() in title.lower():
                    match_idx = idx
                    break
            if match_idx is None:
                continue

            target = remaining_targets.pop(match_idx)
            status, info = process_card_action(page, card, target["action"])
            results.append({**target, "status": status, "title": info.get("title", ""), "url": info.get("url", "")})

        page.mouse.wheel(0, 900)
        page.wait_for_timeout(300)

    return results


def promote_batch(city: str, targets: list):
    """Выполняет НЕСКОЛЬКО целей за один проход браузера и страниц.
    targets: список словарей {"model": str, "action": "up"|"sticky", ...любые доп. поля}
    (доп. поля сохраняются в результате — удобно прокинуть исходное правило для логирования).
    Возвращает список результатов: каждый target + status/title/url."""

    session_path = os.path.join(SESSIONS_DIR, f"{city}.json")
    if not os.path.exists(session_path):
        print(f"❌ Файл сессии не найден: {session_path}")
        return [{**t, "status": "no_session", "title": "", "url": ""} for t in targets]

    with sync_playwright() as playwright:
        # headless=True — облачный/безголовый запуск. Сессия уже сохранена заранее,
        # капча/СМС в этом сценарии не появляются (это подтверждено на практике),
        # поэтому видимый браузер здесь не нужен.
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(storage_state=session_path)
        page = context.new_page()

        page.goto(MY_PAGE_URL)
        page.wait_for_timeout(1000)
        page.get_by_role("link", name="Объявления").click()
        try:
            page.wait_for_selector('[data-ftid="bulls-list_bull"]', timeout=8000)
        except PlaywrightTimeoutError:
            print("⚠️  Список объявлений не появился вовремя — жду ещё немного.")
            page.wait_for_timeout(2000)

        setup_page_view(page, city)
        page.wait_for_timeout(1000)

        max_page = get_max_page(page)
        print(f"Всего страниц: {max_page}. Целей на этот город: {len(targets)}. Начинаю поиск с последней страницы.")

        remaining = [dict(t) for t in targets]  # копия, чтобы не мутировать вход
        results = []

        for page_number in range(max_page, 0, -1):
            if not remaining:
                break
            go_to_page(page, page_number)
            print(f"Смотрю страницу {page_number}... (осталось целей: {len(remaining)})")
            page_results = scan_and_process_page(page, city, remaining)
            results.extend(page_results)

        # То, что не нашли ни на одной странице — пробуем альтернативы из той же группы
        # (если они есть), по очереди, пока не найдётся хоть одна
        for t in remaining:
            print(f"❌ «{t['model']}» / {city} не найдено ни на одной странице.")
            alt_list = t.get("alternates", [])
            found_result = None

            for alt in alt_list:
                print(f"↪️  Пробую альтернативу из группы: «{alt['model']}» ({alt.get('action_label', alt['action'])})")
                single = [dict(alt)]
                for page_number in range(max_page, 0, -1):
                    if not single:
                        break
                    go_to_page(page, page_number)
                    page_res = scan_and_process_page(page, city, single)
                    if page_res:
                        found_result = page_res[0]
                        break
                if found_result:
                    break
                print(f"❌ «{alt['model']}» / {city} тоже не найдено.")

            if found_result:
                results.append(found_result)
            else:
                results.append({**t, "status": "not_found", "title": "", "url": ""})

        page.wait_for_timeout(1000)
        context.close()
        browser.close()
        return results


def find_and_click_card(page, city: str, model: str, action: str, max_scrolls: int = 80):
    """Прокручивает список объявлений, ищет карточку по городу+модели.
    Возвращает (status, info): status = 'clicked' | 'already_active' | 'not_found',
    info = {'title': ..., 'url': ...} (пусто, если not_found)."""

    for scroll_attempt in range(max_scrolls):
        cards = page.locator('[data-ftid="bulls-list_bull"]')
        count = cards.count()

        for i in range(count):
            card = cards.nth(i)
            try:
                title = card.locator('[data-ftid="title"]').inner_text(timeout=1000)
                location = card.locator('[data-ftid="bull_location"]').inner_text(timeout=1000)
            except PlaywrightTimeoutError:
                continue

            if model.strip().lower() in title.lower() and location.strip().lower() == city.strip().lower():
                print(f"Найдено объявление: «{title}» / {location}")

                try:
                    url = card.locator('[data-ftid="title"]').locator("xpath=ancestor::a[1]").get_attribute("href", timeout=1000) or ""
                except PlaywrightTimeoutError:
                    url = ""
                info = {"title": title, "url": url}

                if action == "up":
                    # Для "Поднять" индикатор — не сама кнопка, а дата рядом с городом:
                    # относительное время ("N часов назад") = поднятие было сегодня.
                    try:
                        last_date_text = card.locator('[data-ftid="bull_date"]').inner_text(timeout=1000)
                    except PlaywrightTimeoutError:
                        last_date_text = ""
                    if "назад" in last_date_text:
                        print(f"⏭️  Похоже, «Поднять» уже применялось сегодня ({last_date_text}) — пропускаю.")
                        return "already_active", info

                button = card.locator(f'[data-ftid="{action}"]')
                button_text = button.inner_text(timeout=1000)

                # Если вместо названия действия показано время (например "18 часов") —
                # продвижение уже активно, пропускаем.
                expected_label = ACTION_NAMES[action]
                if expected_label not in button_text:
                    print(f"⏭️  Продвижение «{expected_label}» уже активно ({button_text}) — пропускаю.")
                    return "already_active", info

                button.click()
                return "clicked", info

        # Не нашли на текущем экране — прокручиваем список дальше
        page.mouse.wheel(0, 900)
        page.wait_for_timeout(400)

    return "not_found", {}


def confirm_promotion(page) -> bool:
    """Ждёт всплывающее окно подтверждения ('Применить N поднятие/прикрепление')
    и нажимает его. Если появилось что-то другое (например, окно оплаты) — прерывает
    и возвращает False, чтобы не потратить деньги по ошибке."""

    try:
        confirm_button = page.get_by_role("button", name=re.compile("Применить"))
        confirm_button.wait_for(timeout=5000)
    except PlaywrightTimeoutError:
        print("⚠️  Не появилось стандартное окно подтверждения (Применить N ...).")
        print("   Возможно, это платное разовое продвижение — прерываю на всякий случай.")
        return False

    button_text = confirm_button.inner_text()
    print(f"Подтверждаю: «{button_text}»")
    confirm_button.click()
    return True


def setup_page_view(page, city: str):
    """Переключает на 100 объявлений на странице и, если есть фильтр «Город»
    (актуально для ЛК с несколькими городами, например Хабаровск/Благовещенск),
    применяет его для нужного города."""

    try:
        try:
            page.get_by_role("button", name="Показывать по").click(timeout=6000)
        except PlaywrightTimeoutError:
            page.get_by_role("combobox", name="Показывать по").click(timeout=6000)
        page.get_by_role("option", name="100 объявлений").click(timeout=4000)
        page.wait_for_timeout(1000)
        print("Переключено на «Показывать по 100».")
    except PlaywrightTimeoutError:
        print("ℹ️  Переключатель «Показывать по» не найден — пропускаю (скрипт всё равно пройдёт по всем страницам).")

    try:
        city_filter = page.get_by_role("combobox", name="Город", exact=True)
        city_filter.click(timeout=5000)
        # Название опции включает количество в скобках, например "Благовещенск (75)" — ищем по началу текста
        option = page.get_by_role("option", name=re.compile(f"^{re.escape(city)}\\s*\\("))
        option.click(timeout=4000)
        page.get_by_role("button", name="Показать").click(timeout=4000)
        page.wait_for_timeout(1000)
        print(f"Применён фильтр «Город»: {city}")
    except PlaywrightTimeoutError:
        print("ℹ️  Фильтр «Город» не найден или не применился — у этого ЛК может не быть нескольких городов.")


def get_max_page(page) -> int:
    """Определяет номер последней страницы по видимым ссылкам-цифрам пагинации.
    Ищем строго внутри data-ftid="component_pagination-item" — иначе можно случайно
    зацепить другие числа на странице (например, счётчик непрочитанных сообщений)."""
    links = page.locator('[data-ftid="component_pagination-item"]')
    count = links.count()
    if count == 0:
        return 1
    max_page = 1
    for i in range(count):
        try:
            text = links.nth(i).inner_text(timeout=500).strip()
            max_page = max(max_page, int(text))
        except (PlaywrightTimeoutError, ValueError):
            continue
    return max_page


def go_to_page(page, page_number: int):
    # Раньше здесь был шорткат "если page_number == 1 — ничего не делать",
    # что было верно только для поиска ВПЕРЁД от первой страницы. Поиск идёт
    # С КОНЦА (5→4→3→2→1), поэтому к странице 1 тоже нужно явно переходить —
    # иначе после посещения других страниц скрипт остаётся на последней из них.
    #
    # Ищем строго внутри блока пагинации (data-ftid="component_pagination-item"),
    # а не по всей странице — иначе get_by_role("link", name="1") может случайно
    # найти счётчик непрочитанных сообщений в шапке сайта вместо ссылки на страницу.
    try:
        pagination_links = page.locator('[data-ftid="component_pagination-item"]')
        count = pagination_links.count()
        target_str = str(page_number)
        for i in range(count):
            link = pagination_links.nth(i)
            text = link.inner_text(timeout=500).strip()
            if text == target_str:
                link.click(timeout=3000)
                page.wait_for_timeout(1000)
                return
        print(f"⚠️  Не найдена ссылка на страницу {page_number} в пагинации.")
    except PlaywrightTimeoutError:
        print(f"⚠️  Не удалось перейти на страницу {page_number}")


def promote(city: str, model: str, action: str):
    """Возвращает словарь: {success: bool, status: str, title: str, url: str}
    status одно из: 'clicked', 'already_active', 'not_found', 'aborted', 'no_session'.
    ВНИМАНИЕ: эта функция — только для ручного локального теста (headless=False),
    в облачном/автоматическом цикле используется promote_batch()."""

    if action not in ACTION_NAMES:
        raise ValueError(f"Неизвестное действие: {action}. Ожидается 'up' или 'sticky'.")

    session_path = os.path.join(SESSIONS_DIR, f"{city}.json")
    if not os.path.exists(session_path):
        print(f"❌ Файл сессии не найден: {session_path}")
        return {"success": False, "status": "no_session", "title": "", "url": ""}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(storage_state=session_path)
        page = context.new_page()

        page.goto(MY_PAGE_URL)
        page.wait_for_timeout(1000)
        page.get_by_role("link", name="Объявления").click()
        try:
            page.wait_for_selector('[data-ftid="bulls-list_bull"]', timeout=8000)
        except PlaywrightTimeoutError:
            print("⚠️  Список объявлений не появился вовремя — жду ещё немного.")
            page.wait_for_timeout(2000)

        setup_page_view(page, city)
        page.wait_for_timeout(1000)

        max_page = get_max_page(page)
        print(f"Всего страниц: {max_page}. Начинаю поиск с последней (там объявления без недавних действий).")

        status, info = "not_found", {}
        for page_number in range(max_page, 0, -1):
            go_to_page(page, page_number)
            print(f"Смотрю страницу {page_number}...")
            status, info = find_and_click_card(page, city, model, action)
            if status in ("clicked", "already_active"):
                break

        title = info.get("title", "")
        url = info.get("url", "")

        if status == "not_found":
            print(f"❌ Объявление «{model}» / {city} не найдено ни на одной странице.")
            success = False
        elif status == "already_active":
            success = True
        elif status == "clicked":
            confirmed = confirm_promotion(page)
            if confirmed:
                page.wait_for_timeout(1500)
                print("✅ Продвижение применено.")
                success = True
            else:
                page.screenshot(path="promote_aborted.png")
                print("   Скриншот сохранён: promote_aborted.png")
                success = False
                status = "aborted"

        page.wait_for_timeout(2000)
        context.close()
        browser.close()
        return {"success": success, "status": status, "title": title, "url": url}


def main():
    if len(sys.argv) < 4:
        print('Использование: python promote_listing.py <Город> "<Модель>" <up|sticky>')
        sys.exit(1)

    city, model, action = sys.argv[1], sys.argv[2], sys.argv[3]
    result = promote(city, model, action)
    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
