"""
Тестовый скрипт: проверяем, что Python может подключиться к Google Таблице
и прочитать список аккаунтов из листа "Логин\\Пароль Дром".

Перед запуском:
1. Убедись, что файл credentials.json лежит в этой же папке.
2. Убедись, что email из credentials.json добавлен в таблицу как "Редактор".
3. Установи библиотеки:  pip install -r requirements.txt
"""

import gspread
from google.oauth2.service_account import Credentials

# ---- Настройки ----
CREDENTIALS_FILE = "credentials.json"
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1TwktqeDapCHr-jfCJnJYuprK_MNUMTOEWktRyYvqAeo/edit"
ACCOUNTS_SHEET_NAME = "Логин\\Пароль Дром"

# Права доступа, которые нам нужны от Google
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]


def main():
    print("Подключаюсь к Google Sheets...")

    # 1. Авторизуемся через Service Account
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)

    # 2. Открываем таблицу и нужный лист
    spreadsheet = client.open_by_url(SPREADSHEET_URL)
    accounts_sheet = spreadsheet.worksheet(ACCOUNTS_SHEET_NAME)

    # 3. Читаем все строки (данные с 1-й строки, без заголовков)
    rows = accounts_sheet.get_all_values()

    print(f"\nНайдено строк: {len(rows)}\n")
    print(f"{'Город':<20} {'Логин':<25} {'Пароль'}")
    print("-" * 60)

    for row in rows:
        if len(row) < 3:
            continue  # пропускаем пустые/неполные строки
        city, login, password = row[0], row[1], row[2]
        # пароль в консоли не показываем полностью, только для проверки что он есть
        masked_password = password[:2] + "***" if password else "(пусто)"
        print(f"{city:<20} {login:<25} {masked_password}")

    print(f"\nГотово. Прочитано аккаунтов: {len(rows)}")


if __name__ == "__main__":
    main()
