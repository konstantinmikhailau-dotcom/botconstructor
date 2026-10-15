
"""
database.py — слой работы с SQLite для Meta-Bot System.

Python 3.10+
Зависимости: только стандартная библиотека Python.

Хранит:
- созданных Telegram-ботов;
- пользователей этих ботов;
- экраны меню и их кнопки;
- ответы пользователей на анкеты.

Запуск файла напрямую создаёт базу данных и таблицы.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any


# ---------------------------------------------------------
# 1. Конфигурация
# ---------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "meta_bot.db"

# Обязательная подпись для создаваемых ботов.
WATERMARK = "⚡️ Made with @RedMafinBot"


def get_connection() -> sqlite3.Connection:
    """Создаёт новое соединение с базой данных."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(
        str(DB_PATH),
        timeout=10.0,
    )
    connection.row_factory = sqlite3.Row

    # Включаем проверку внешних ключей для соединения.
    connection.execute("PRAGMA foreign_keys = ON")

    return connection


def _json_dumps(value: Any) -> str:
    """Преобразует Python-объект в JSON."""
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _json_loads(value: str | None, default: Any = None) -> Any:
    """Безопасно читает JSON из базы."""
    if value is None:
        return default

    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _dict_from_row(row: sqlite3.Row | None) -> dict | None:
    """Преобразует строку SQLite в обычный словарь."""
    return dict(row) if row is not None else None


# ---------------------------------------------------------
# 2. Создание схемы базы данных
# ---------------------------------------------------------

def init_db() -> None:
    """
    Создаёт все таблицы, если они ещё не существуют.
    Можно безопасно вызывать при каждом запуске приложения.
    """
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS bots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                owner_telegram_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                username TEXT,

                -- Токен нужен движку для подключения к Telegram.
                -- Для production необходимо шифрование токена.
                token TEXT NOT NULL UNIQUE,

                start_text TEXT NOT NULL DEFAULT
                    'Привет! Добро пожаловать в моего бота!',

                start_screen_key TEXT NOT NULL DEFAULT 'main',

                is_active INTEGER NOT NULL DEFAULT 1
                    CHECK (is_active IN (0, 1)),

                settings_json TEXT NOT NULL DEFAULT '{}',

                created_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

                updated_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            );

            CREATE INDEX IF NOT EXISTS idx_bots_owner
                ON bots(owner_telegram_id);

            CREATE TABLE IF NOT EXISTS bot_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                bot_id INTEGER NOT NULL,
                telegram_user_id INTEGER NOT NULL,

                username TEXT,
                first_name TEXT,
                last_name TEXT,
                language_code TEXT,

                -- Например: waiting_for_phone.
                -- Используется движком для восстановления диалога.
                state TEXT,

                state_data_json TEXT NOT NULL DEFAULT '{}',

                first_seen_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

                last_seen_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

                UNIQUE(bot_id, telegram_user_id),

                FOREIGN KEY (bot_id)
                    REFERENCES bots(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_bot_users_telegram
                ON bot_users(telegram_user_id);

            CREATE TABLE IF NOT EXISTS screens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                bot_id INTEGER NOT NULL,
                screen_key TEXT NOT NULL,

                title TEXT NOT NULL DEFAULT '',
                text TEXT NOT NULL DEFAULT '',

                -- Inline-кнопки, URL, WebApp и переходы
                -- хранятся как JSON-массив.
                buttons_json TEXT NOT NULL DEFAULT '[]',

                created_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

                updated_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

                UNIQUE(bot_id, screen_key),

                FOREIGN KEY (bot_id)
                    REFERENCES bots(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_screens_bot
                ON screens(bot_id);

            CREATE TABLE IF NOT EXISTS form_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                bot_id INTEGER NOT NULL,
                telegram_user_id INTEGER NOT NULL,

                -- Например: contact_form или application.
                form_key TEXT NOT NULL,

                -- Все ответы конкретной анкеты в JSON.
                answers_json TEXT NOT NULL DEFAULT '{}',

                status TEXT NOT NULL DEFAULT 'completed'
                    CHECK (status IN (
                        'in_progress',
                        'completed',
                        'cancelled'
                    )),

                created_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

                updated_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

                FOREIGN KEY (bot_id)
                    REFERENCES bots(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_submissions_bot_user
                ON form_submissions(bot_id, telegram_user_id);

            CREATE INDEX IF NOT EXISTS idx_submissions_form
                ON form_submissions(bot_id, form_key);
            """
        )


# ---------------------------------------------------------
# 3. Работа с ботами
# ---------------------------------------------------------

def create_bot(
    owner_telegram_id: int,
    name: str,
    token: str,
    username: str | None = None,
    start_text: str = "Привет! Добро пожаловать в моего бота!",
    settings: dict | None = None,
) -> int:
    """
    Регистрирует нового бота.
    Возвращает внутренний ID записи в SQLite.

    Владелец — Telegram ID пользователя конструктора.
    """
    if not name.strip():
        raise ValueError("Название бота не может быть пустым.")

    if not token.strip():
        raise ValueError("Токен бота не может быть пустым.")

    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO bots (
                owner_telegram_id,
                name,
                username,
                token,
                start_text,
                settings_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                owner_telegram_id,
                name.strip(),
                username,
                token.strip(),
                start_text,
                _json_dumps(settings or {}),
            ),
        )
        return cursor.lastrowid


def get_bot(bot_id: int) -> dict | None:
    """Возвращает бота по внутреннему ID."""
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM bots WHERE id = ?",
            (bot_id,),
        ).fetchone()

    result = _dict_from_row(row)
    if result:
        result["settings"] = _json_loads(
            result.pop("settings_json"), {}
        )
    return result


def get_bot_by_token(token: str) -> dict | None:
    """
    Ищет бота по токену.
    Используется внутренним движком, а не публичным API.
    """
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM bots WHERE token = ?",
            (token,),
        ).fetchone()

    result = _dict_from_row(row)
    if result:
        result["settings"] = _json_loads(
            result.pop("settings_json"), {}
        )
    return result


def list_bots(owner_telegram_id: int) -> list[dict]:
    """Список ботов, принадлежащих пользователю конструктора."""
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, owner_telegram_id, name, username,
                   start_text, start_screen_key, is_active,
                   created_at, updated_at
            FROM bots
            WHERE owner_telegram_id = ?
            ORDER BY id DESC
            """,
            (owner_telegram_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def update_bot(bot_id: int, **fields: Any) -> bool:
    """
    Обновляет разрешённые поля бота.

    Пример:
        update_bot(1, name="Новый бот", is_active=True)

    Возвращает True, если запись найдена.
    """
    allowed_fields = {
        "name",
        "username",
        "start_text",
        "start_screen_key",
        "is_active",
        "settings",
    }

    unknown = set(fields) - allowed_fields
    if unknown:
        raise ValueError(
            f"Недопустимые поля: {', '.join(sorted(unknown))}"
        )

    if not fields:
        return False

    if "settings" in fields:
        fields["settings_json"] = _json_dumps(
            fields.pop("settings")
        )

    if "is_active" in fields:
        fields["is_active"] = int(bool(fields["is_active"]))

    assignments = ", ".join(
        f"{field} = ?" for field in fields
    )
    values = list(fields.values())

    with get_connection() as connection:
        cursor = connection.execute(
            f"""
            UPDATE bots
            SET {assignments},
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (*values, bot_id),
        )
        return cursor.rowcount > 0


def delete_bot(bot_id: int, owner_telegram_id: int) -> bool:
    """
    Удаляет бота только при совпадении ID владельца.
    Связанные пользователи, экраны и анкеты удаляются каскадно.
    """
    with get_connection() as connection:
        cursor = connection.execute(
            """
            DELETE FROM bots
            WHERE id = ? AND owner_telegram_id = ?
            """,
            (bot_id, owner_telegram_id),
        )
        return cursor.rowcount > 0


# ---------------------------------------------------------
# 4. Пользователи созданных ботов
# ---------------------------------------------------------

def upsert_bot_user(
    bot_id: int,
    telegram_user_id: int,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    language_code: str | None = None,
) -> int:
    """
    Добавляет пользователя или обновляет его данные.
    Уникальность определяется парой bot_id + telegram_user_id.
    """
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO bot_users (
                bot_id, telegram_user_id, username,
                first_name, last_name, language_code
            )
            VALUES (?, ?, ?, ?, ?, ?)

            ON CONFLICT(bot_id, telegram_user_id)
            DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                language_code = excluded.language_code,
                last_seen_at =
                    strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            """,
            (
                bot_id,
                telegram_user_id,
                username,
                first_name,
                last_name,
                language_code,
            ),
        )

        row = connection.execute(
            """
            SELECT id FROM bot_users
            WHERE bot_id = ? AND telegram_user_id = ?
            """,
            (bot_id, telegram_user_id),
        ).fetchone()

    return row["id"]


def get_bot_user(
    bot_id: int,
    telegram_user_id: int,
) -> dict | None:
    """Получает пользователя конкретного бота."""
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT * FROM bot_users
            WHERE bot_id = ? AND telegram_user_id = ?
            """,
            (bot_id, telegram_user_id),
        ).fetchone()

    result = _dict_from_row(row)
    if result:
        result["state_data"] = _json_loads(
            result.pop("state_data_json"), {}
        )
    return result


def set_user_state(
    bot_id: int,
    telegram_user_id: int,
    state: str | None,
    state_data: dict | None = None,
) -> bool:
    """
    Сохраняет этап диалога пользователя.
    Позволяет продолжить анкету после перезапуска движка.
    Пользователь должен быть предварительно зарегистрирован.
    """
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE bot_users
            SET state = ?,
                state_data_json = ?,
                last_seen_at =
                    strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE bot_id = ? AND telegram_user_id = ?
            """,
            (
                state,
                _json_dumps(state_data or {}),
                bot_id,
                telegram_user_id,
            ),
        )
        return cursor.rowcount > 0


# ---------------------------------------------------------
# 5. Экраны меню и кнопки
# ---------------------------------------------------------

def save_screen(
    bot_id: int,
    screen_key: str,
    text: str,
    buttons: list[dict] | None = None,
    title: str = "",
) -> int:
    """
    Создаёт экран или обновляет существующий.

    Пример кнопки:
        {
            "text": "Наш сайт",
            "type": "url",
            "url": "https://example.com"
        }

    Типы кнопок обрабатывает движок:
        callback, url, web_app, screen, form.
    """
    if not screen_key.strip():
        raise ValueError("Ключ экрана не может быть пустым.")

    if buttons is not None and not isinstance(buttons, list):
        raise TypeError("buttons должен быть списком словарей.")

    buttons_json = _json_dumps(buttons or [])

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO screens (
                bot_id, screen_key, title, text, buttons_json
            )
            VALUES (?, ?, ?, ?, ?)

            ON CONFLICT(bot_id, screen_key)
            DO UPDATE SET
                title = excluded.title,
                text = excluded.text,
                buttons_json = excluded.buttons_json,
                updated_at =
                    strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            """,
            (bot_id, screen_key, title, text, buttons_json),
        )

        row = connection.execute(
            """
            SELECT id FROM screens
            WHERE bot_id = ? AND screen_key = ?
            """,
            (bot_id, screen_key),
        ).fetchone()

    return row["id"]


def get_screen(
    bot_id: int,
    screen_key: str,
) -> dict | None:
    """Получает экран вместе с декодированным списком кнопок."""
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT * FROM screens
            WHERE bot_id = ? AND screen_key = ?
            """,
            (bot_id, screen_key),
        ).fetchone()

    result = _dict_from_row(row)
    if result:
        result["buttons"] = _json_loads(
            result.pop("buttons_json"), []
        )
    return result


def list_screens(bot_id: int) -> list[dict]:
    """Возвращает все экраны конкретного бота."""
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM screens
            WHERE bot_id = ?
            ORDER BY id
            """,
            (bot_id,),
        ).fetchall()

    result = []
    for row in rows:
        screen = dict(row)
        screen["buttons"] = _json_loads(
            screen.pop("buttons_json"), []
        )
        result.append(screen)

    return result


def delete_screen(bot_id: int, screen_key: str) -> bool:
    """Удаляет экран по ключу, не затрагивая остальные экраны."""
    with get_connection() as connection:
        cursor = connection.execute(
            """
            DELETE FROM screens
            WHERE bot_id = ? AND screen_key = ?
            """,
            (bot_id, screen_key),
        )
        return cursor.rowcount > 0


# ---------------------------------------------------------
# 6. Сбор и хранение анкет
# ---------------------------------------------------------

def save_submission(
    bot_id: int,
    telegram_user_id: int,
    form_key: str,
    answers: dict,
    status: str = "completed",
    submission_id: int | None = None,
) -> int:
    """
    Создаёт новую анкету или обновляет существующую.

    answers:
        {
            "name": "Иван",
            "phone": "+48123456789",
            "question": "Как с вами связаться?"
        }

    Для постепенного сбора ответов передавайте статус
    in_progress, а после завершения — completed.
    """
    allowed_statuses = {
        "in_progress",
        "completed",
        "cancelled",
    }

    if status not in allowed_statuses:
        raise ValueError("Недопустимый статус анкеты.")

    if not isinstance(answers, dict):
        raise TypeError("answers должен быть словарём.")

    with get_connection() as connection:
        if submission_id is None:
            cursor = connection.execute(
                """
                INSERT INTO form_submissions (
                    bot_id, telegram_user_id, form_key,
                    answers_json, status
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    bot_id,
                    telegram_user_id,
                    form_key,
                    _json_dumps(answers),
                    status,
                ),
            )
            return cursor.lastrowid

        cursor = connection.execute(
            """
            UPDATE form_submissions
            SET answers_json = ?,
                status = ?,
                updated_at =
                    strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ? AND bot_id = ?
              AND telegram_user_id = ?
            """,
            (
                _json_dumps(answers),
                status,
                submission_id,
                bot_id,
                telegram_user_id,
            ),
        )

        if cursor.rowcount == 0:
            raise ValueError(
                "Анкета не найдена или принадлежит другому пользователю."
            )

        return submission_id


def get_submission(submission_id: int) -> dict | None:
    """Получает одну анкету по её ID."""
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT * FROM form_submissions WHERE id = ?
            """,
            (submission_id,),
        ).fetchone()

    result = _dict_from_row(row)
    if result:
        result["answers"] = _json_loads(
            result.pop("answers_json"), {}
        )
    return result


def list_submissions(
    bot_id: int,
    form_key: str | None = None,
    telegram_user_id: int | None = None,
    limit: int = 100,
) -> list[dict]:
    """Получает анкеты с необязательными фильтрами."""
    if not 1 <= limit <= 1000:
        raise ValueError("limit должен быть от 1 до 1000.")

    query = "SELECT * FROM form_submissions WHERE bot_id = ?"
    params: list[Any] = [bot_id]

    if form_key is not None:
        query += " AND form_key = ?"
        params.append(form_key)

    if telegram_user_id is not None:
        query += " AND telegram_user_id = ?"
        params.append(telegram_user_id)

    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    with get_connection() as connection:
        rows = connection.execute(query, params).fetchall()

    result = []
    for row in rows:
        submission = dict(row)
        submission["answers"] = _json_loads(
            submission.pop("answers_json"), {}
        )
        result.append(submission)

    return result


# ---------------------------------------------------------
# 7. Самопроверка при запуске файла
# ---------------------------------------------------------

if __name__ == "__main__":
    init_db()
    print("Meta-Bot System: база данных готова.")
    print(f"Файл базы данных: {DB_PATH}")
