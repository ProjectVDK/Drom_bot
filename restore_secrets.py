"""
Восстанавливает credentials.json и sessions/<Город>.json из переменных окружения
(GitHub Actions Secrets, переданные через workflow). Локально не нужен —
используется только в облачном запуске.

Секреты именуются латиницей (GitHub не разрешает кириллицу в именах Secrets),
соответствие городам задано в CITY_SECRET_MAP ниже.
"""

import os
import json

SESSIONS_DIR = "sessions"

# Соответствие: имя города (как в таблице "Правила") -> имя переменной окружения / Secret
CITY_SECRET_MAP = {
    "Красноярск": "SESSION_KRASNOYARSK",
    "Иркутск": "SESSION_IRKUTSK",
    "Хабаровск": "SESSION_KHABAROVSK",
    "Благовещенск": "SESSION_BLAGOVESHCHENSK",
    "Новосибирск": "SESSION_NOVOSIBIRSK",
    "Новокузнецк": "SESSION_NOVOKUZNETSK",
    "Кемерово": "SESSION_KEMEROVO",
    "Томск": "SESSION_TOMSK",
    "Чита": "SESSION_CHITA",
    "Улан-Удэ": "SESSION_ULAN_UDE",
    "Якутск": "SESSION_YAKUTSK",
    "Владивосток": "SESSION_VLADIVOSTOK",
}


def restore_credentials():
    content = os.environ.get("GOOGLE_CREDENTIALS_JSON", "").strip()
    if not content:
        print("❌ Секрет GOOGLE_CREDENTIALS_JSON не найден или пуст.")
        return False
    # Проверяем, что это валидный JSON, прежде чем писать файл
    json.loads(content)
    with open("credentials.json", "w", encoding="utf-8") as f:
        f.write(content)
    print("✅ credentials.json восстановлен.")
    return True


def restore_sessions():
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    restored = []
    missing = []
    for city, secret_name in CITY_SECRET_MAP.items():
        content = os.environ.get(secret_name, "").strip()
        if not content:
            missing.append(city)
            continue
        json.loads(content)  # проверка валидности
        path = os.path.join(SESSIONS_DIR, f"{city}.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        restored.append(city)

    print(f"✅ Восстановлено сессий: {len(restored)} ({', '.join(restored)})")
    if missing:
        print(f"ℹ️  Нет секрета для: {', '.join(missing)} (пропущено)")


def main():
    ok = restore_credentials()
    restore_sessions()
    if not ok:
        exit(1)


if __name__ == "__main__":
    main()
