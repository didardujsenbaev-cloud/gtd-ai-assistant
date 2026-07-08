"""
Railway / cloud deployment entry point.

Решает проблему с Google credentials:
  - Локально: GOOGLE_CREDENTIALS_FILE=path/to/file.json (файл лежит рядом)
  - Railway/cloud: файл недоступен, используем GOOGLE_CREDENTIALS_JSON (содержимое JSON)

Если GOOGLE_CREDENTIALS_JSON задан и файла нет — записываем во временный файл
и прописываем путь в GOOGLE_CREDENTIALS_FILE.

Запуск:
  python3 start.py          # на Railway / любом сервере
  python3 telegram_bot.py   # локально (как раньше, без изменений)
"""

import os
import json
import tempfile
import sys


def _setup_credentials() -> None:
    """Записать credentials из env-переменной во временный файл, если нужно."""
    creds_json_str = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()
    creds_file     = os.getenv("GOOGLE_CREDENTIALS_FILE", "").strip()

    # Если файл уже есть — ничего делать не надо
    if creds_file and os.path.exists(creds_file):
        print(f"✅ Google credentials: {creds_file}")
        return

    # Если JSON-строка задана — пишем во временный файл
    if creds_json_str:
        try:
            creds_data = json.loads(creds_json_str)
            tmp = tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".json",
                delete=False,
                prefix="gcp_creds_",
            )
            json.dump(creds_data, tmp, ensure_ascii=False, indent=2)
            tmp.close()
            os.environ["GOOGLE_CREDENTIALS_FILE"] = tmp.name
            sa = creds_data.get("client_email", "?")
            print(f"✅ Google credentials (из GOOGLE_CREDENTIALS_JSON): {sa}")
        except json.JSONDecodeError as e:
            print(f"❌ GOOGLE_CREDENTIALS_JSON не является валидным JSON: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"❌ Ошибка записи credentials: {e}")
            sys.exit(1)
    else:
        # Нет ни файла, ни JSON-строки — бот запустится, но Google-функции упадут
        print(
            "⚠️  GOOGLE_CREDENTIALS_FILE не найден и GOOGLE_CREDENTIALS_JSON не задан.\n"
            "   Google Sheets / Drive будут недоступны.\n"
            "   Добавь GOOGLE_CREDENTIALS_JSON в переменные Railway."
        )


if __name__ == "__main__":
    _setup_credentials()

    # Запускаем основной бот
    import telegram_bot
    telegram_bot.main()
