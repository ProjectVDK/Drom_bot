"""
Главный скрипт бота. Запускается планировщиком каждые 5 минут (в активном окне).

Логика:
1. Читает лист "Правила".
2. Читает лист "Журнал" (для истории — что и когда уже применялось).
3. Определяет текущее время UTC.
4. Для каждого правила проверяет: подходит ли день недели и время запуска (окно ±10 минут).
5. Правила с одинаковой парой (Группа, Город) обрабатываются как пул:
   выбирается модель, которая дольше всего не продвигалась (по Журналу),
   и только если сегодня по этому пулу+городу ещё ничего не делалось.
6. Выполняет нужные действия через promote_listing.promote(), пишет результат в "Журнал".

Запуск:
    python run_bot.py
"""

from datetime import datetime, timezone, timedelta
import os
import sys
import time
import gspread
from google.oauth2.service_account import Credentials

from promote_listing import promote_batch, ACTION_NAMES
from dashboard_scraper import get_dashboard_info

CREDENTIALS_FILE = "credentials.json"
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1TwktqeDapCHr-jfCJnJYuprK_MNUMTOEWktRyYvqAeo/edit"
RULES_SHEET_NAME = "Правила"
LOG_SHEET_NAME = "Журнал"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

EARLY_MINUTES = 10     # можно стартовать чуть раньше "Времени запуска"
CATCHUP_MINUTES = 60   # правило остаётся "созревшим" ещё столько минут после времени запуска
                       # (страховка от пропущенных/задержанных тиков cron в GitHub Actions;
                       # повторов нет — их исключает проверка по Журналу)

LOCK_FILE = "run_bot.lock"
LOCK_MAX_AGE_SECONDS = 240  # если lock свежее этого — считаем, что другой запуск ещё работает

DEBUG_LOG_FILE = "run_bot_debug.log"


class Tee:
    """Дублирует вывод одновременно в консоль и в файл."""
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            s.write(data)
            s.flush()

    def flush(self):
        for s in self.streams:
            s.flush()


def setup_debug_log():
    """Открывает run_bot_debug.log. Если файл создан не в текущие "рабочие сутки" —
    перезаписывает (начинает день заново), иначе — дописывает.

    Граница смены дня искусственно сдвинута на 12:00 UTC (а не на полночь UTC),
    потому что активное окно бота (23:00–03:00 UTC) пересекает полночь — если
    считать по календарной дате UTC, первый же запуск после полуночи стирал бы
    записи о том, что произошло с 23:00 до полуночи того же окна."""
    shifted_now = datetime.now(timezone.utc) - timedelta(hours=12)
    today_str = shifted_now.strftime("%Y-%m-%d")

    mode = "a"
    if os.path.exists(DEBUG_LOG_FILE):
        shifted_file_time = datetime.fromtimestamp(
            os.path.getmtime(DEBUG_LOG_FILE), tz=timezone.utc
        ) - timedelta(hours=12)
        file_date = shifted_file_time.strftime("%Y-%m-%d")
        if file_date != today_str:
            mode = "w"
    else:
        mode = "w"

    log_file = open(DEBUG_LOG_FILE, mode, encoding="utf-8")
    sys.stdout = Tee(sys.__stdout__, log_file)
    sys.stderr = Tee(sys.__stderr__, log_file)

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'=' * 70}\nЗапуск: {now_str} UTC\n{'=' * 70}")
    return log_file


def restore_stdio(log_file):
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__
    log_file.close()


def acquire_lock() -> bool:
    if os.path.exists(LOCK_FILE):
        age = time.time() - os.path.getmtime(LOCK_FILE)
        if age < LOCK_MAX_AGE_SECONDS:
            print(f"⏭️  Похоже, другой экземпляр run_bot.py уже выполняется (lock создан {int(age)} сек назад) — выхожу.")
            return False
        print("⚠️  Найден устаревший lock-файл (предыдущий запуск завис или упал) — перезаписываю.")
    with open(LOCK_FILE, "w") as f:
        f.write(str(time.time()))
    return True


def release_lock():
    try:
        os.remove(LOCK_FILE)
    except FileNotFoundError:
        pass

WEEKDAY_MAP = {
    "Пн": 0, "Вт": 1, "Ср": 2, "Чт": 3, "Пт": 4, "Сб": 5, "Вс": 6,
}

ACTION_BY_LABEL = {v: k for k, v in ACTION_NAMES.items()}  # "Поднять" -> "up", "Прикрепить" -> "sticky"


def get_client():
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    return gspread.authorize(creds)


def load_rules(spreadsheet):
    sheet = spreadsheet.worksheet(RULES_SHEET_NAME)
    rows = sheet.get_all_records()  # использует 1-ю строку как заголовки
    return rows


def load_log(spreadsheet):
    sheet = spreadsheet.worksheet(LOG_SHEET_NAME)
    rows = sheet.get_all_records()
    return sheet, rows


def parse_time(value: str):
    value = value.strip()
    hh, mm = value.split(":")
    return int(hh), int(mm)


def is_due(rule: dict, now: datetime, ignore_time: bool = False) -> bool:
    days_raw = str(rule.get("Дни (UTC)", "")).strip()
    days = [d.strip() for d in days_raw.split(",") if d.strip()]
    weekday_numbers = [WEEKDAY_MAP[d] for d in days if d in WEEKDAY_MAP]

    if ignore_time:
        return now.weekday() in weekday_numbers

    time_raw = str(rule.get("Время запуска (UTC)", "")).strip()
    if not time_raw:
        return False

    try:
        hh, mm = parse_time(time_raw)
    except ValueError:
        print(f"⚠️  Не удалось разобрать время «{time_raw}» в правиле, пропускаю.")
        return False

    # Проверяем сегодняшнее и вчерашнее вхождение расписания: окно догона может
    # пересекать полночь UTC (правило 23:30 должно сработать и в 00:10 следующих суток).
    # День недели считается по дате, на которую запланировано правило.
    for day_offset in (0, 1):
        scheduled = (now - timedelta(days=day_offset)).replace(
            hour=hh, minute=mm, second=0, microsecond=0)
        if scheduled.weekday() not in weekday_numbers:
            continue
        delta = (now - scheduled).total_seconds() / 60
        if -EARLY_MINUTES <= delta <= CATCHUP_MINUTES:
            return True
    return False


def work_day(dt: datetime) -> str:
    """«Рабочие сутки» бота: граница сдвинута на 12:00 UTC, чтобы окно 23:00–03:55 UTC
    не разрезалось полуночью. Используется для проверки «уже сделано сегодня»."""
    return (dt - timedelta(hours=12)).strftime("%Y-%m-%d")


def row_work_day(row: dict) -> str:
    """Рабочие сутки строки Журнала (по её 'Дата/время' в UTC); '' если не разобрать."""
    raw = str(row.get("Дата/время", ""))[:16]
    try:
        dt = datetime.strptime(raw, "%Y-%m-%d %H:%M")
    except ValueError:
        return ""
    return work_day(dt)


def already_done_today(log_rows: list, city: str, group: str, model: str = None) -> bool:
    """Проверяет по Журналу: было ли сегодня успешное действие по этой группе+городу
    (если group пустая — проверяет конкретно по городу+модели)."""
    today_str = work_day(datetime.now(timezone.utc))

    for row in log_rows:
        if row_work_day(row) != today_str:
            continue
        if str(row.get("Город", "")).strip() != city:
            continue
        if str(row.get("Результат", "")).strip() not in ("Успешно", "Уже активно"):
            continue

        if model:
            logged_model = str(row.get("Модель", "")).strip().lower()
            rule_model = model.strip().lower()
            # В Журнале модель пишется вместе с годом ("XCMG XCT30_S1, 2024"),
            # поэтому сравниваем по вхождению, а не точным совпадением.
            if rule_model in logged_model or logged_model in rule_model:
                return True

    return False


def last_promoted_at(log_rows: list, city: str, model: str):
    """Возвращает datetime последнего успешного действия по этой модели+городу, либо None."""
    latest = None
    for row in log_rows:
        if str(row.get("Город", "")).strip() != city:
            continue
        logged_model = str(row.get("Модель", "")).strip().lower()
        rule_model = model.strip().lower()
        if not (rule_model in logged_model or logged_model in rule_model):
            continue
        if str(row.get("Результат", "")).strip() not in ("Успешно", "Уже активно"):
            continue
        raw = str(row.get("Дата/время", "")).strip()
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        if latest is None or dt > latest:
            latest = dt
    return latest


def rank_group_candidates(group_rules: list, log_rows: list) -> list:
    """Ранжирует правила одной группы+города от самого давнего к самому недавнему
    (никогда не продвигавшиеся — первыми). Первый элемент — основной кандидат,
    остальные — резервные варианты на случай, если основной не найдётся на сайте."""
    def sort_key(rule):
        model = str(rule.get("Модель", "")).strip()
        city = str(rule.get("Город", "")).strip()
        last = last_promoted_at(log_rows, city, model)
        return (last is not None, last or datetime.min)

    return sorted(group_rules, key=sort_key)


def append_log(log_sheet, city, model, url, action_label, result):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    # Вставляем в строку 2 (сразу после заголовков), чтобы новые записи были сверху
    log_sheet.insert_row([timestamp, city, model, url, action_label, result], index=2)


def log_dashboard_info(city: str, info: dict, log_sheet):
    if info["balance"]:
        append_log(log_sheet, city, "-", "", "Баланс", info["balance"])
    for pkg in info["packages"]:
        if pkg["type"] == "sticky":
            label = "Остаток пакета Прикрепить"
        elif pkg["type"] == "up":
            label = "Остаток пакета Поднять"
        else:
            label = "Остаток пакета (неизвестный тип)"
        result_text = f"{pkg['title']}, {pkg['expiry']}"
        append_log(log_sheet, pkg["city"] or city, "-", "", label, result_text)


def get_exhausted_set(city: str, info: dict) -> set:
    """Возвращает множество (город, тип), у которых остаток пакета = 0."""
    exhausted = set()
    for pkg in info["packages"]:
        if pkg["remaining"] == 0:
            exhausted.add((pkg["city"] or city, pkg["type"]))
    return exhausted


def resolve_targets(rule: dict, log_sheet, exhausted: set, alternate_rules: list = None) -> dict:
    """Проверяет одно правило (уже определено, что due) и возвращает
    словарь-цель {model, action, action_label, alternates} для пакетной обработки,
    либо None, если правило нужно пропустить (уже сделано / пакет исчерпан).
    alternate_rules — остальные правила той же группы+города, на случай если
    основная модель не найдётся на сайте (пробуются по порядку давности)."""
    city = str(rule.get("Город", "")).strip()
    model = str(rule.get("Модель", "")).strip()
    action_label = str(rule.get("Тип продвижения", "")).strip()
    action = ACTION_BY_LABEL.get(action_label)

    if action is None:
        print(f"⚠️  Неизвестный тип продвижения «{action_label}» для {city}/{model}, пропускаю.")
        return None

    if (city, action) in exhausted:
        print(f"⛔ Пакет «{action_label}» в городе {city} исчерпан — пропускаю {model}.")
        append_log(log_sheet, city, model, "", action_label, "Пакет исчерпан")
        return None

    alternates = []
    for alt_rule in (alternate_rules or []):
        alt_model = str(alt_rule.get("Модель", "")).strip()
        alt_action_label = str(alt_rule.get("Тип продвижения", "")).strip()
        alt_action = ACTION_BY_LABEL.get(alt_action_label)
        if alt_action is None:
            continue
        alternates.append({"model": alt_model, "action": alt_action, "action_label": alt_action_label})

    return {"model": model, "action": action, "action_label": action_label, "alternates": alternates}


def log_batch_results(city: str, results: list, log_sheet):
    result_map = {
        "clicked": "Успешно",
        "already_active": "Уже активно",
        "not_found": "Не найдено",
        "aborted": "Прервано (доп. проверка)",
        "no_session": "Нет сессии",
    }
    for r in results:
        result_text = result_map.get(r["status"], "Ошибка")
        title = r.get("title") or r["model"]
        append_log(log_sheet, city, title, r.get("url", ""), r["action_label"], result_text)


def main():
    log_file = setup_debug_log()
    try:
        if not acquire_lock():
            return
        try:
            run()
        finally:
            release_lock()
    finally:
        restore_stdio(log_file)


def run():
    force_mode = "--force" in sys.argv

    client = get_client()
    spreadsheet = client.open_by_url(SPREADSHEET_URL)

    rules = load_rules(spreadsheet)
    log_sheet, log_rows = load_log(spreadsheet)

    now = datetime.now(timezone.utc)
    print(f"Текущее время UTC: {now.strftime('%Y-%m-%d %H:%M')} ({now.strftime('%A')})")
    if force_mode:
        print("🔁 Режим --force: беру все правила сегодняшнего дня недели, игнорируя точное время запуска.")

    due_rules = [r for r in rules if is_due(r, now, ignore_time=force_mode)]
    if not due_rules:
        print("Подходящих по времени правил не найдено. Завершаю.")
        return

    print(f"Найдено due-правил: {len(due_rules)}")

    balance_due = [r for r in due_rules if str(r.get("Тип продвижения", "")).strip().lower() == "баланс"]
    promotion_due = [r for r in due_rules if str(r.get("Тип продвижения", "")).strip().lower() != "баланс"]

    # ЭТАП 1: определяем "кандидатов" на выполнение (уже было сегодня? выбор из пула) —
    # БЕЗ проверки исчерпанных пакетов, чтобы понять, для каких городов вообще есть
    # что делать в этом запуске. Это нужно, чтобы не сканировать баланс впустую на
    # каждом тике планировщика, если сегодня всё уже выполнено.
    candidate_by_city: dict = {}
    processed_groups = set()  # (Группа, Город), которые уже обработали в этом запуске

    for rule in promotion_due:
        group = str(rule.get("Группа", "")).strip()
        city = str(rule.get("Город", "")).strip()
        model = str(rule.get("Модель", "")).strip()

        if group:
            key = (group, city)
            if key in processed_groups:
                continue
            processed_groups.add(key)

            group_rules = [
                r for r in rules
                if str(r.get("Группа", "")).strip() == group and str(r.get("Город", "")).strip() == city
            ]

            today_str = work_day(now)
            done_today = any(
                str(row.get("Город", "")).strip() == city
                and row_work_day(row) == today_str
                and str(row.get("Результат", "")).strip() in ("Успешно", "Уже активно")
                and any(str(row.get("Модель", "")).strip() in str(gr.get("Модель", "")).strip()
                        or str(gr.get("Модель", "")).strip() in str(row.get("Модель", "")).strip()
                        for gr in group_rules)
                for row in log_rows
            )
            if done_today:
                print(f"⏭️  Группа «{group}» в городе {city} уже обработана сегодня — пропускаю.")
                continue

            ranked = rank_group_candidates(group_rules, log_rows)
            if not ranked:
                continue
            candidate_rule = ranked[0]
            alternate_rules = ranked[1:]

        else:
            if already_done_today(log_rows, city, group="", model=model):
                print(f"⏭️  {city} / {model} уже обработано сегодня — пропускаю.")
                continue
            candidate_rule = rule
            alternate_rules = []

        candidate_by_city.setdefault(city, []).append((candidate_rule, alternate_rules))

    # ЭТАП 2: сканируем баланс/пакеты только для городов, где есть хотя бы 1 кандидат,
    # плюс города с явным due-правилом "Баланс"
    scan_cities = sorted(set(candidate_by_city.keys())
                          | {str(r.get("Город", "")).strip() for r in balance_due})

    exhausted = set()
    for city in scan_cities:
        print(f"\n--- Проверяю баланс и пакеты: {city} ---")
        info = get_dashboard_info(city)
        log_dashboard_info(city, info, log_sheet)
        exhausted |= get_exhausted_set(city, info)

    if exhausted:
        print(f"⚠️  Исчерпаны пакеты: {exhausted}")

    # ЭТАП 3: финализируем цели, отфильтровав исчерпанные пакеты
    targets_by_city: dict = {}
    for city, candidate_pairs in candidate_by_city.items():
        for candidate_rule, alternate_rules in candidate_pairs:
            target = resolve_targets(candidate_rule, log_sheet, exhausted, alternate_rules)
            if target is not None:
                targets_by_city.setdefault(city, []).append(target)

    # ЭТАП 4: выполняем — один проход браузера и страниц на город
    for city, targets in targets_by_city.items():
        print(f"\n=== Город: {city} — целей: {len(targets)} ===")
        for t in targets:
            print(f"  • {t['model']} — {t['action_label']}")
        try:
            results = promote_batch(city, targets)
            log_batch_results(city, results, log_sheet)
        except Exception as e:
            print(f"❌ Необработанная ошибка при обработке города {city}: {e}")
            print("   Пропускаю этот город, продолжаю со следующим.")


if __name__ == "__main__":
    main()
