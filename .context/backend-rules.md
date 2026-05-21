# Описание проекта
Асинхронный алгоритмический торговый движок + FastAPI бэкенд + React фронтенд.
Backend API — это **тонкий шлюз** между фронтом и движком: REST + WebSocket для UI, подписчик Redis Pub/Sub и хранилище в PostgreSQL. Сам бэкенд **не торгует** и не ходит на биржи напрямую (кроме валидации API-ключей).

# 🚫 КРИТИЧЕСКИЕ АРХИТЕКТУРНЫЕ ПРАВИЛА (CLEAN ARCHITECTURE)
1. **Слои:** `api/` (routers, schemas, deps) → `services/` (use-cases) → `repositories/` (БД) → `infrastructure/` (Redis, шифрование, внешние клиенты). Router не лезет в репозиторий напрямую.
2. **Pydantic-схемы ≠ ORM-модели:** наружу из `repositories/` SQLAlchemy-модели не утекают.
3. **Разделение процессов:** Backend НЕ выполняет торговую логику, НЕ дергает CCXT для торговли (только для валидации ключей), НЕ считает индикаторы.
4. **DI через `Depends`:** соединения с БД/Redis, шифровальщик, publisher — параметрами в сервисы. Глобальное состояние запрещено.
5. **Идемпотентность команд:** команды движку несут `command_id` (UUID), повторная отправка не даёт двойного запуска.

# ⚡ АСИНХРОННОСТЬ И ПРОИЗВОДИТЕЛЬНОСТЬ
1. **Только async-стек:** FastAPI `async def`, `SQLAlchemy 2.0 Async` + `asyncpg`, `redis.asyncio`, `httpx.AsyncClient`. Запрещено `requests`, `psycopg2`, `time.sleep`.
2. **Без блокировок event loop:** CPU-bound — через `asyncio.to_thread`.
3. **`lifespan`, не `@on_event`:** инициализация пулов БД/Redis и подписчика Pub/Sub — в lifespan. На shutdown: `await engine.dispose()`, `await redis.aclose()`, отмена и `gather(return_exceptions=True)` фоновых задач.
4. **Подписчик Pub/Sub — отдельная задача:** падение → log + backoff reconnect.
5. **Таймауты на всё внешнее:** дефолт 5 сек.

# 💾 БАЗА ДАННЫХ И СОСТОЯНИЕ (POSTGRESQL + REDIS)
1. **SQLAlchemy 2.0 Async:** `Mapped[...]`, `mapped_column(...)`, `async_session.execute(select(...))`. Никаких `.query()`.
2. **Alembic — обязателен:** каждое изменение модели = новая ревизия с человекочитаемым именем.
3. **Владелец таблиц `users`, `bots`, `exchange_credentials`, `bot_commands`, `audit_log`** — бэкенд.
4. **Таблицы `orders`, `trades`, `balances_snapshots`, `strategy_errors`** пишутся бэкендом ПО СОБЫТИЯМ из Redis от движка.
5. **Redis — кэш и шина**, не БД. Балансы дублируются в БД для истории.
6. **Транзакции:** один HTTP-запрос = одна транзакция. Событие из Pub/Sub = отдельная короткая транзакция.

# 📡 КОНТРАКТ С ДВИЖКОМ (REDIS PUB/SUB)
1. **Подписка (channels из `trade-engine-crypto/src/application/events.py`):**
   - `engine.new_trade`, `engine.balance_update`, `engine.status`, `engine.strategy_error`.
2. **Публикация (команды движку):**
   - `engine.commands.start` — `{command_id, bot_id, strategy_class, symbol, timeframe, params, credentials_ref}`.
   - `engine.commands.stop` — `{command_id, bot_id, close_positions}`.
   - `engine.commands.update` — `{command_id, bot_id, params}`.
   Каждая команда дублируется в `bot_commands` для аудита/идемпотентности.
3. **Decimal как СТРОКА** в JSON (`"price": "42500.50"`).
4. **Имена каналов не выдумывать:** брать константы из движка.
5. **`credentials_ref`, не сами ключи:** в команду кладётся UUID записи `exchange_credentials`.

# 🔐 БЕЗОПАСНОСТЬ
1. **API-ключи бирж — Fernet:** `cryptography.fernet`, ключ из `BACKEND_ENCRYPTION_KEY`. В БД только ciphertext.
2. **Никогда не логировать секреты.** Фильтр в логгере по `*secret*`, `*token*`, `*password*`, `authorization`.
3. **JWT:** access 15 мин, refresh отдельным endpoint'ом. Секрет `BACKEND_JWT_SECRET`.
4. **RBAC:** `admin`/`trader`/`viewer`. Проверка владения `bot.user_id == current_user.id` — в сервисе.
5. **CORS — белый список** из env, не `["*"]`.
6. **Валидация Pydantic** на входе.
7. **Rate limit** на `/auth/login`, `/bots/{id}/start`.

# 🌐 WEBSOCKET ДЛЯ ФРОНТА
1. `/ws/updates` — JWT в query/header, поток событий пользователя.
2. ConnectionManager: `user_id -> set[WebSocket]`; broadcast от подписчика Pub/Sub.
3. Backpressure: переполнение → close `1013`.
4. Ping каждые 20 сек.

# 🧪 ТЕСТИРОВАНИЕ (TDD)
1. `httpx.AsyncClient` + `ASGITransport`. Никакого `TestClient` (sync).
2. `AsyncMock` для publisher; `fakeredis.aioredis` для подписчика.
3. PostgreSQL в интеграционных тестах — настоящий (контейнер). SQLite запрещён.
4. Сервисы покрываются ДО роутеров.
5. Контрактные тесты с эталонными payload'ами из `events.py`.

# ⚙️ КОНФИГ И СЕКРЕТЫ
1. `Pydantic Settings` единый класс. Никаких `os.getenv` по коду.
2. Env (минимум): `BACKEND_DATABASE_URL`, `BACKEND_REDIS_URL`, `BACKEND_JWT_SECRET`, `BACKEND_ENCRYPTION_KEY`, `BACKEND_CORS_ORIGINS`, `BACKEND_LOG_LEVEL`.
3. `.env.example` — обязателен; `.env` — в `.gitignore`. В проде — через GitHub Secrets / docker secrets.
4. `Dockerfile` мультистейдж, healthcheck `/healthz`. Миграции — отдельным шагом перед стартом.

# 📝 ЛОГИРОВАНИЕ
1. Структурированные JSON-логи (`structlog`). Поля: `timestamp`, `level`, `service=backend`, `request_id`, `user_id`, `event`.
2. `request_id` middleware → прокидывается в команды движку.
3. Тело запроса целиком не логировать (могут утечь ключи).

# 🧠 MCP MEMORY
Сохраняй в граф знаний имена таблиц, каналов Redis, формат payload'ов, сигнатуры публичных сервисов.

# MCP
Context7 — для документации FastAPI/SQLAlchemy/Pydantic v2/redis-py/alembic/cryptography.
Playwright — для открытия сайтов.

# СЕРВЕР
Реквизиты для подключения (хост, порт, пользователь, путь до тома Docker) — в локальном файле `.env` (не коммитится) и в GitHub Secrets для CI. В этих правилах их нет: репозиторий публичный.
