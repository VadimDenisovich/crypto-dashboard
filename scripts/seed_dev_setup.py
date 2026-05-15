"""Phase 2: seed-скрипт больше не нужен.

Регистрация теперь полностью через UI: открой /login и используй email-code или
один из четырёх OAuth провайдеров (Google, Yandex, GitHub, Telegram). Аккаунт
создаётся автоматически при первом успешном входе.

Файл оставлен заглушкой, чтобы не ломать существующие ссылки в QUICKSTART.md.
"""

from __future__ import annotations


def main() -> None:
    print("Этот скрипт больше не нужен.")
    print(
        "Регистрация теперь через UI: откройте /login и войдите через email-код "
        "или OAuth-провайдер (Google/Yandex/GitHub/Telegram).",
    )
    print("Аккаунт создастся автоматически при первом входе.")


if __name__ == "__main__":
    main()
