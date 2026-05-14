"""DEV-only: создать стартового пользователя в БД.

Назначение:
    Минимальный seed для удобства dev/staging — только пользователь, чтобы
    не вводить email/password при каждом сбросе БД. API-ключи и боты
    добавляются через UI (Settings → Create strategy).

    На проде в этом скрипте смысла нет: пользователь сам регистрируется на /register.

Запуск:
    python -m venv .venv-scripts && source .venv-scripts/bin/activate
    pip install -r scripts/requirements.txt
    python scripts/seed_dev_setup.py

Идемпотентность: повторный запуск проверяет существование и просто печатает доступ.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import asyncpg
from dotenv import load_dotenv
from passlib.context import CryptContext


DEV_EMAIL = os.environ.get("SEED_USER_EMAIL", "dev@local.test")
DEV_PASSWORD = os.environ.get("SEED_USER_PASSWORD", "dev-password-123")


def _to_asyncpg_dsn(sqlalchemy_url: str) -> str:
    """postgresql+asyncpg://... → postgresql://... (asyncpg.connect не понимает +asyncpg)."""
    parsed = urlparse(sqlalchemy_url)
    scheme = parsed.scheme.split("+")[0]
    return urlunparse(parsed._replace(scheme=scheme))


async def main() -> None:
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env")

    db_url_raw = os.environ.get("BACKEND_DATABASE_URL")
    if not db_url_raw:
        sys.exit("FATAL: BACKEND_DATABASE_URL is missing in .env")

    db_url = _to_asyncpg_dsn(db_url_raw)
    pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

    conn = await asyncpg.connect(db_url)
    try:
        row = await conn.fetchrow("SELECT id FROM users WHERE email = $1", DEV_EMAIL)
        if row is not None:
            print(f"[user] already exists: {DEV_EMAIL} (id={row['id']})")
        else:
            password_hash = pwd_ctx.hash(DEV_PASSWORD)
            user_id = await conn.fetchval(
                """
                INSERT INTO users (email, password_hash, role, is_active, created_at)
                VALUES ($1, $2, 'trader', TRUE, NOW())
                RETURNING id
                """,
                DEV_EMAIL,
                password_hash,
            )
            print(f"[user] created: {DEV_EMAIL} (id={user_id})")
    finally:
        await conn.close()

    print()
    print("=" * 60)
    print("Login credentials for the frontend:")
    print(f"  Email    : {DEV_EMAIL}")
    print(f"  Password : {DEV_PASSWORD}")
    print("=" * 60)
    print()
    print("Что дальше:")
    print("  1. Открой фронт → /login → залогинься этими данными.")
    print("  2. Settings → добавь Binance Testnet API Key + Secret.")
    print("  3. Strategies → Создать стратегию → SmaCross → Сохранить и запустить.")


if __name__ == "__main__":
    asyncio.run(main())
