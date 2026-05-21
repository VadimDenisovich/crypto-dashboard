# Phase 1 — отчёт о реализации

Этот файл описывает простым языком, что было сделано в рамках Phase 1 ROADMAP'а (Engine Infrastructure layer). Все изменения относятся к ветке `main` всех трёх репозиториев (корневой `crypto-dashboard`, submodule `trade-engine-crypto`, submodule `frontend`).

---

## Кратко: что было «до» и что стало «после»

**До:**
- Движок (`trade-engine-crypto`) имел только бизнес-логику (Domain + Application), но **не умел запускаться** — не было entrypoint, не было подключения к Redis/БД/бирже, не было Docker-образа.
- В коде упоминались две биржи: Binance и Bybit (фронт, README, комментарии в движке).
- В `docker-compose.yml` сервис `engine` был закомментирован с пометкой «реализуй сначала».

**После:**
- Движок умеет запускаться одной командой `trade-engine` (или `docker compose up engine`). Подключается к общему с бэком Postgres+Redis, расшифровывает API-ключи бирж, подписывается на команды от бэка, исполняет стратегии, публикует события обратно бэку.
- Все упоминания Bybit удалены — поддерживается только Binance Testnet.
- 86 тестов проходят, `mypy --strict` без ошибок.

---

## 1. Чистка Bybit (везде, не только в движке)

Пользователь решил, что на Phase 1 поддерживаем только Binance. Я нашёл все упоминания Bybit `grep -ri "bybit"` и удалил:

| Файл | Что было | Что стало |
|---|---|---|
| [README.md](../README.md) (строка 35) | «Binance / Bybit» в ascii-схеме архитектуры | «Binance» |
| [frontend/src/app/pages/Settings.tsx](../frontend/src/app/pages/Settings.tsx) | Целый блок UI «Bybit Testnet» с полями API Key/Secret и кнопкой «Проверить соединение» (строки 103-141) | Удалён вместе с `Divider`'ом-разделителем; импорт `Divider` тоже убран как неиспользуемый |
| [frontend/src/app/components/strategies/BasicParameters.tsx](../frontend/src/app/components/strategies/BasicParameters.tsx) | В Select «Биржа» был пункт `<MenuItem value="bybit">Bybit Testnet</MenuItem>` | Удалён, остался только Binance |
| [frontend/src/app/pages/Strategies.tsx](../frontend/src/app/pages/Strategies.tsx) | В мок-данных бот #3 («Спотовый Grid #1») имел `exchange: "Bybit Testnet"` | Заменено на `"Binance Testnet"` |
| [trade-engine-crypto/src/domain/interfaces.py](../trade-engine-crypto/src/domain/interfaces.py) | Комментарий «`Concrete adapters wrap CCXT (Binance, Bybit, ...)`» | «`Concrete adapters wrap CCXT (Binance for now)`» |
| [.context/phase-1-engine-infrastructure.md](phase-1-engine-infrastructure.md) | Раздел про две биржи + verification на Bybit Testnet | Переписано под одну Binance |

После правок `grep -ri "bybit"` возвращает пусто.

---

## 2. Локальный `.env`

В корне проекта `.env` не существовал (только `.env.example`). Я скопировал шаблон в `.env` (он в `.gitignore`, в репо не попадёт) и дописал в него **две новые секции**:

### `=== ENGINE ===`
```env
ENGINE_DATABASE_URL=postgresql+asyncpg://user:postgres@postgres:5432/crypto-db
ENGINE_REDIS_URL=redis://redis:6379/0
ENGINE_ENCRYPTION_KEY=CHANGE_ME_GENERATE_LOCALLY
ENGINE_LOG_LEVEL=INFO
ENGINE_HEARTBEAT_INTERVAL_SEC=10
ENGINE_BALANCE_POLL_INTERVAL_SEC=15
ENGINE_STATE_SNAPSHOT_TTL_SEC=30
ENGINE_COMMAND_DEDUP_TTL_SEC=86400
```

**Важно:** `ENGINE_ENCRYPTION_KEY` сейчас плейсхолдер. Чтобы движок реально работал, замени его на то же значение, что у `BACKEND_ENCRYPTION_KEY` (Fernet-ключ должен быть идентичен у бэка и движка — иначе движок не сможет расшифровать API-ключи бирж, которые бэк зашифровал и положил в БД).

### `=== DEV: Binance Testnet seed credentials ===`
Ключи Binance Testnet, которые ты прислал:
```env
DEV_BINANCE_TESTNET_API_KEY=u4nrBpRv...
DEV_BINANCE_TESTNET_API_SECRET=h9dXPtqR...
```

Они **не читаются движком напрямую** — их использует только seed-скрипт (`scripts/seed_dev_credential.py`, который ещё надо написать), чтобы вставить креды в таблицу `exchange_credentials` бэка с шифрованием Fernet. В production-окружении этот блок не нужен.

Параллельно я обновил [.env.example](../.env.example): добавил секцию `=== ENGINE ===` без значений и закомментированный шаблон `DEV_BINANCE_TESTNET_*` для других разработчиков.

---

## 3. Каркас движка (PR1)

### 3.1. `pyproject.toml` — зависимости

Раньше `dependencies = []`. Я добавил:
```toml
dependencies = [
    "ccxt>=4.3",           # клиент бирж (включая ccxt.pro для WebSocket)
    "redis>=5.0",          # асинхронный клиент Redis
    "asyncpg>=0.29",       # асинхронный драйвер Postgres
    "sqlalchemy[asyncio]>=2.0.30",  # ORM
    "pydantic>=2.7",
    "pydantic-settings>=2.3",  # для класса EngineSettings
    "structlog>=24.1",     # структурированные JSON-логи
    "cryptography>=42",    # Fernet для расшифровки API-ключей
    "tenacity>=9",         # retry с экспоненциальным backoff
]
```

И добавил `fakeredis>=2.23` в dev (нужен для тестов на Redis Pub/Sub без поднятия реального Redis).

Плюс прописал `[project.scripts] trade-engine = "engine_main:main"` — после `pip install` появляется бинарь `trade-engine`, который запускает движок. Используется в Dockerfile.

### 3.2. `src/infrastructure/settings.py` — конфиг

Класс `EngineSettings(BaseSettings)`. Все поля читаются из env с префиксом `ENGINE_`. С валидацией:
- `database_url`, `redis_url`, `encryption_key` — обязательны (без них старт упадёт сразу при загрузке).
- `heartbeat_interval_sec=10`, `balance_poll_interval_sec=15`, `snapshot_ttl_sec=30`, `command_dedup_ttl_sec=86400` — дефолты разумные, можно переопределить через env.

### 3.3. `src/infrastructure/logging.py` — structlog

Настройка JSON-вывода в stdout. После `configure_logging("INFO")` все логи идут в формате:
```json
{"event": "engine_starting", "level": "info", "timestamp": "2026-05-12T20:00:00Z", "redis": "redis://...", "db": "postgresql+..."}
```
Это удобно для Docker logs / любого log-aggregator'а (Grafana Loki и т.п.).

### 3.4. `src/infrastructure/redis_event_bus.py` — RedisEventBus

Реализация интерфейса `EventBus` из Domain. Класс с одним публичным методом `publish(channel, payload)`. Внутри — `json.dumps(payload, default=str)`. Почему `default=str`:
- `Decimal("0.001")` сериализуется как строка `"0.001"`, а не как float `0.001` (без потери точности).
- `datetime(2026, 5, 12, ...)` сериализуется как ISO-строка.

Если кто-то попытается опубликовать payload с экзотическим типом (например, set) — упадёт с TypeError, что правильно (не нужно молча терять данные).

### 3.5. `src/application/events.py` — каналы

Было 4 канала (которые публикует движок). Я добавил ещё 3 (которые слушает движок):
```python
COMMAND_START = "engine.commands.start"
COMMAND_STOP = "engine.commands.stop"
COMMAND_UPDATE = "engine.commands.update"
```
Это зеркало `backend/src/domain/events.py:23-25`. Чтобы не было дрейфа — есть [tests/integration/test_events_contract.py](../trade-engine-crypto/tests/integration/test_events_contract.py), который парсит backend/src/domain/events.py и сверяет значения побитово.

Также добавил кортежи `PUBLISHED_CHANNELS` и `LISTENED_CHANNELS` — чтобы listener мог одной строкой подписаться на всё разом.

### 3.6. Тесты RedisEventBus
4 теста на `fakeredis`: сериализация dict, Decimal → строка, datetime → строка, отсутствие подписчиков.

---

## 4. Биржевые адаптеры (PR2)

### 4.1. `src/infrastructure/ccxt_exchange_adapter.py` — CCXTExchangeAdapter

Реализация интерфейса `ExchangeAdapter` поверх `ccxt.pro.binance`. Что важно:

- **Whitelist бирж:** `SUPPORTED_EXCHANGES = {"binance"}`. Конструктор валидирует — если пришёл другой `exchange_name`, бросает `ValueError`. Это страховка: если в БД случайно окажется `exchange="bybit"`, движок не упадёт с непонятной CCXT-ошибкой, а скажет «эта биржа не поддерживается».
- **Testnet:** конструктор принимает `testnet=True` (по умолчанию) и вызывает `exchange.set_sandbox_mode(True)`.
- **Retry:** все сетевые методы (`fetch_ohlcv`, `create_order`, `get_balance`) обёрнуты декоратором `@_network_retry()` на базе tenacity. При `NetworkError`, `ExchangeNotAvailable`, `RequestTimeout` — повтор с экспоненциальным backoff (0.5с, 1с, 2с, 4с, 8с, потом сдаёмся).
- **Precision:** перед `create_order` цена и количество прогоняются через `exchange.price_to_precision()` и `exchange.amount_to_precision()` — это правильная для биржи минимальная точность (tick size, lot size). Без этого Binance может отказать в ордере.
- **Нормализация:** ответы CCXT (dict с float/string полями) преобразуются в наши доменные `Order`/`Balance`/`Candle` (frozen dataclass с Decimal). Все конверсии через `Decimal(str(value))`, чтобы не потерять точность.
- **Маппинг статусов:** CCXT возвращает status строками (`"open"`, `"closed"`, `"canceled"`, `"expired"`, `"rejected"`), движок маппит в свой `OrderStatus` enum. `"closed"` → `FILLED`.
- **Балансы:** CCXT отдаёт `{free: ..., used: ..., total: ...}` для каждой валюты. Я считаю `total = free + used` (игнорируем locked/staked), чтобы соблюсти инвариант доменного `Balance`. Нулевые балансы выкидываются, чтобы не раздувать payload.

12 тестов: валидация конструктора, нормализация всех типов ответов, рефлекшен ошибок CCXT в наш `OrderExecutionError`.

### 4.2. `src/infrastructure/ccxt_market_data.py` — CCXTMarketDataProvider

Async-генератор свечей через `ccxt.pro.exchange.watch_ohlcv()` (WebSocket).

Ключевые моменты:
- **Реконнект:** если WebSocket падает с любым `Exception` — логируем, ждём по backoff (1с → 2с → 4с → 8с → 16с → 30с max) и пробуем снова. Бесконечный цикл. Движок никогда не должен умирать из-за обрыва WS.
- **Дедуп:** `ccxt.pro` может слать несколько обновлений одной и той же свечи (на каждый тик внутри минуты). Я храню `last_ts_ms` и пропускаю всё со старым timestamp — отдаём стратегии только новые свечи. Это правильное поведение для индикаторных стратегий (SMA, RSI и т.п.), которые работают на закрытых свечах.
- **Отмена:** при `task.cancel()` корректно пробрасываем `CancelledError`, не глотаем — иначе graceful shutdown не сработает.

4 теста: нормализация, дедуп, реконнект с подменённым `asyncio.sleep`, прохождение `CancelledError`.

---

## 5. Чтение БД + расшифровка + Orchestrator (PR3)

### 5.1. `src/infrastructure/db.py`, `db_models.py`, `db_repositories.py`

Движок и бэк делят одну БД. Бэк пишет таблицы, движок читает.

- **`db.py`** — фабрики async-движка SQLAlchemy и sessionmaker. Один движок на процесс, sessions создаются по необходимости.
- **`db_models.py`** — engine-side ORM-модели для двух таблиц: `bots` и `exchange_credentials`. Это **отдельный `Base`**, не импортируется из бэка (чтобы движок не зависел от submodule бэка). Минимальный набор полей, нужный движку. Если бэк изменит схему (Alembic-миграция), движок просто перечитает БД — поле появится у бэка раньше, чем движок его попросит.
- **`db_repositories.py`** — `BotRepository` и `CredentialRepository`. Они **не возвращают ORM-объекты**, а DTO-датаклассы (`BotConfig`, `DecryptedCredential`) — чтобы внутренние слои не знали про SQLAlchemy. `CredentialRepository.get_decrypted()` сразу расшифровывает Fernet'ом — если ключ не подходит (`InvalidToken`), бросает специальное исключение `CredentialDecryptError` с подсказкой «проверь, что `ENGINE_ENCRYPTION_KEY` == `BACKEND_ENCRYPTION_KEY`».

5 тестов: чтение существующего/несуществующего бота, Fernet round-trip, проверка что неверный ключ бросает понятную ошибку.

### 5.2. `src/application/orchestrator.py` — EngineOrchestrator

Это **сердце** всего PR3. Класс держит в памяти словарь `bot_id → RunningStrategy` (где `RunningStrategy` — это структура с `asyncio.Task`, инстансом стратегии, инстансом адаптера и метаданными бота).

Три публичных метода:

**`start_strategy(bot_id)`:**
1. Если бот уже в словаре — `return` (идемпотентность).
2. Грузим `BotConfig` из БД (`BotRepository.get`).
3. Грузим расшифрованные креды (`CredentialRepository.get_decrypted`).
4. Резолвим класс стратегии по строковому имени из БД (`bot.strategy_class` → класс через `StrategyRegistry.resolve`).
5. Создаём `CCXTExchangeAdapter` через инжектированную фабрику, передавая ему расшифрованные ключи.
6. Создаём `CCXTMarketDataProvider` поверх того же CCXT instance.
7. Инициализируем стратегию: `strategy_cls(symbol=..., timeframe=..., **params)` (params приходят из JSONB-поля БД как dict).
8. **Warmup:** если у стратегии `startup_candle_count > 0`, делаем REST-запрос исторических свечей через `adapter.fetch_ohlcv(limit=N)` и прогоняем каждую через `strategy.on_candle()`. Так стратегия успевает накопить индикаторы до начала live-цикла.
9. Создаём `RiskManager`, `OrderExecutor` (с `bot_id`!), `StrategyRunner` (тоже с `bot_id`).
10. Стартуем `asyncio.create_task(runner.run())` и кладём `RunningStrategy` в словарь.

Всё это под `asyncio.Lock`, чтобы две одновременные команды start от бэка не запустили двух одинаковых ботов.

**`stop_strategy(bot_id)`:**
1. Достаём `RunningStrategy` из словаря (если нет — no-op).
2. `task.cancel()`, `await task` (с подавлением `CancelledError`).
3. `adapter.close()` (закрытие WebSocket).
4. Логируем.

**`update_strategy(bot_id)`:**
Phase 1: просто `stop + start`. Бэк перед публикацией команды update должен обновить `bots.params` в БД, тогда новый start подцепит свежие параметры.

И ещё:
- **`shutdown()`** — останавливает все боты разом (для graceful shutdown процесса).
- **`active_bot_ids`** и **`iter_running()`** — для StateManager'а, чтобы он мог итерировать активные стратегии для heartbeat и balance poll.

8 тестов: успешный старт, идемпотентность, остановка, реакция на отсутствующего бота, отсутствующие креды, update = restart, full shutdown.

### 5.3. Bot_id в payload — фикс ROADMAP Phase 3.1 заранее

В оригинальном ROADMAP'е раздел 3.1 говорит: «в бэковском `event_projector.py` поиск бота идёт по `strategy_class` через `LIMIT 1` — это баг, если у пользователя два бота с одной стратегией. Надо передавать `bot_id` в каждом payload движка». Я сделал это сразу в Phase 1, чтобы Phase 3 был дешёвым:

- `OrderExecutor.__init__` теперь требует `bot_id: UUID`. В payload `engine.new_trade` добавлено поле `"bot_id": str(bot_id)`.
- Аналогично `StrategyRunner.__init__` принимает `bot_id`, и в payload `engine.strategy_error` тоже кладётся `bot_id`.
- Существующие тесты обновлены: добавлен `_BOT_ID` фикстура.

### 5.4. `src/infrastructure/command_listener.py` — CommandListener

Подписка на 3 канала команд (`engine.commands.start|stop|update`) через `redis.asyncio.Redis.pubsub()`.

Жизненный цикл:
1. `run()` подписывается, входит в бесконечный цикл `pubsub.get_message(timeout=1.0)`.
2. На каждое сообщение: декод bytes→str, парс JSON.
3. **Идемпотентность:** перед обработкой — `redis.set("engine:commands:processed:<command_id>", "1", ex=86400, nx=True)`. Если ключ уже существует (`nx=True` вернёт `None`) — это дубликат, пропускаем. Это страховка на случай, если бэк дважды публикует команду (например, при retry).
4. Парсим `bot_id` (UUID).
5. Резолвим handler по каналу (`COMMAND_START` → `orchestrator.start_strategy`, и т.д.) и вызываем.
6. Если handler бросил исключение — логируем и **продолжаем цикл** (одна сбойная команда не валит listener).

Защита от мусора:
- Невалидный JSON — логируем warning, не падаем.
- Отсутствие `command_id` или `bot_id` — логируем warning.
- Невалидный UUID — логируем warning.
- Неизвестный канал (теоретически невозможно, мы только на 3 подписаны) — логируем warning.

`stop()` устанавливает `asyncio.Event` — на следующей итерации while-loop выйдет и закроет pubsub.

7 тестов: dispatch всех трёх команд, дубликат-skip, missing fields, плохой JSON, падение handler'а не валит listener.

### 5.5. `src/infrastructure/state_manager.py` — StateManager

Это процесс-«рапортовщик» — он периодически рассказывает бэку, что движок жив и что у активных ботов с балансом.

`run()` запускает **три параллельных loop'а** в `asyncio.TaskGroup`:

**Heartbeat loop** (раз в `heartbeat_interval_sec`, по умолчанию 10с):
- Публикует в `engine.status`: `{"uptime_sec": ..., "active_bots": [bot_id1, bot_id2, ...], "timestamp": "..."}`.
- Бэк читает этот канал — если 30 секунд тишины, alerting может пингнуть в Telegram (Phase 5).

**Balance poll loop** (раз в `balance_poll_interval_sec`, по умолчанию 15с):
- Для каждого активного бота: `adapter.get_balance()` (REST через CCXT).
- Публикует в `engine.balance_update`: `{"bot_id": ..., "credential_id": ..., "balances": {USDT: {free, used, total}, BTC: {...}}, "timestamp": ...}`.
- Поле `credential_id` обязательно (бэковский projector без него не запишет).
- Если для одного бота `get_balance` упал (биржа лежит) — логируем, продолжаем с остальными. Один сбойный бот не валит весь loop.

**State snapshot loop** (раз в `heartbeat_interval / 2`, минимум 2с):
- Для каждого активного бота: `redis.set("engine:state:<bot_id>", json_snapshot, ex=30)`.
- Snapshot содержит `bot_id, credential_id, symbol, strategy_name, timestamp`.
- Это нужно для будущего endpoint'а `/api/engine/status` (ROADMAP Phase 3.4) — бэк делает быстрый `GET` без обращения к движку.

`stop()` ставит `asyncio.Event`, все loops видят его на следующей итерации и выходят.

5 тестов: heartbeat публикуется, balance публикуется per-bot, snapshot пишется в Redis с TTL, сбой одного бота не валит loop, пустой список ботов = только heartbeat (балансы не публикуются).

### 5.6. Стратегия SMA Cross + реестр

**`src/strategies/sma_cross.py` — SmaCross:**

Простая стратегия: пересечение быстрой (по умолчанию 50) и медленной (200) скользящих средних по close-ценам.

- Внутри `collections.deque(maxlen=slow_period)` для хранения истории.
- На каждой свече: `self._closes.append(candle.close)`. Если меньше `slow_period` элементов — `return None` (warmup ещё не закончился).
- Считаем `fast = mean(last_N_closes)` и `slow = mean(all_closes)`. Всё в `Decimal`, без float.
- Сравниваем с предыдущими `fast`/`slow`:
  - Если `prev_fast <= prev_slow` и `fast > slow` → пересечение снизу вверх → `BUY`.
  - Если `prev_fast >= prev_slow` и `fast < slow` → пересечение сверху вниз → `SELL`.
- Иначе `None`.

Конструктор валидирует параметры (`fast < slow`, оба `> 0`, `order_size > 0`).

**`src/strategies/__init__.py` — StrategyRegistry:**

Тонкая обёртка вокруг dict `name → class`. `default_registry()` создаёт реестр с зарегистрированной `SmaCross`. Используется orchestrator'ом для резолва `bot.strategy_class` (строковое имя из БД) в реальный класс.

6 тестов: warmup, bullish cross, bearish cross, поля сигнала, корректное `startup_candle_count`, валидация конструктора.

---

## 6. Entrypoint + Docker + интеграционные тесты (PR4)

### 6.1. `src/engine_main.py` — entrypoint

Функция `_run()` собирает всё дерево зависимостей:
1. `load_settings()` — читает env, валидирует.
2. `configure_logging(...)` — настраивает structlog.
3. Создаёт SQLAlchemy engine + session_factory.
4. Создаёт `Redis.from_url(...)`.
5. Создаёт `RedisEventBus`, `Fernet`, `BotRepository`, `CredentialRepository`.
6. Создаёт фабрики `_exchange_factory` и `_market_data_factory` — это closure'ы, которые orchestrator вызывает при старте каждой стратегии.
7. Создаёт `EngineOrchestrator`, `CommandListener`, `StateManager`.
8. Регистрирует обработчики `SIGTERM` и `SIGINT` через `loop.add_signal_handler` — они вызывают `.stop()` у listener'а и state_manager'а и сетят `stop_event`.
9. Стартует `listener.run()` и `state_manager.run()` как отдельные таски.
10. `await stop_event.wait()` — главный поток просто ждёт сигнала.
11. На shutdown: ждёт завершения listener/state_manager, делает `orchestrator.shutdown()` (отменяет все стратегии, закрывает все CCXT-коннекты), закрывает Redis и Postgres.

Sync-функция `main()` оборачивает `asyncio.run(_run())` — её регистрирует `[project.scripts] trade-engine = "engine_main:main"` в pyproject. После `pip install` появляется команда `trade-engine`.

### 6.2. `Dockerfile`

Multi-stage по образцу `backend/Dockerfile`:
- **builder** — `python:3.11-slim` + `build-essential`, `libpq-dev`. Собирает wheels из pyproject.
- **runtime** — `python:3.11-slim` + только `libpq5` (рантайм-зависимость asyncpg). Создаёт non-root user `app` (uid 1000). Ставит wheels. Копирует только `src/`.
- `CMD ["trade-engine"]` — использует тот самый script из pyproject.
- `HEALTHCHECK` — простая проверка что процесс жив. Детальный health (через `engine.status`) будет в Phase 3.4.

### 6.3. `docker-compose.yml` — раскомментирован сервис `engine`

Раньше блок `engine:` был полностью закомментирован с пометкой «TODO: реализовать». Я его раскомментировал и расширил:
- Использует образ `ghcr.io/vadimdenisovich/crypto-trade-engine:latest` (когда CI его соберёт).
- Все env-переменные `ENGINE_*` с **fallback на `BACKEND_*`** через `${ENGINE_DATABASE_URL:-${BACKEND_DATABASE_URL}}`. Это значит: если в `.env` не задан `ENGINE_DATABASE_URL` — возьмёт значение `BACKEND_DATABASE_URL`. Удобно — не надо дублировать.
- `depends_on: migrate` — движок стартует только после успешных миграций (иначе ORM-модели могут сломаться).
- `extra_hosts: host.docker.internal:host-gateway` — на маке/Linux для доступа к хостовому Postgres/Redis.
- `restart: unless-stopped`.

### 6.4. `tests/integration/test_events_contract.py`

Два теста:
- **`test_canonical_channel_values`** — фиксация эталонных значений всех 7 каналов. Если кто-то изменит `application/events.py` — тест упадёт.
- **`test_engine_channels_match_backend_source_of_truth`** — открывает `backend/src/domain/events.py`, регуляркой парсит каждую константу и сверяет с движком. Если submodule бэка не инициализирован — `pytest.skip`. У нас инициализирован, тест проходит, значит каналы синхронизированы побитово.

---

## 7. Итоговая статистика

**Файлов создано в движке:**
- 13 файлов исходников (в `src/infrastructure/`, `src/application/orchestrator.py`, `src/strategies/`, `src/engine_main.py`)
- 6 файлов тестов (5 в `infrastructure/`, 1 в `application/`, 1 в `integration/`, 1 для SMA Cross)
- 1 `Dockerfile`

**Файлов изменено:**
- `pyproject.toml` (deps + scripts + mypy overrides)
- `src/application/events.py` (+3 канала команд + кортежи)
- `src/application/__init__.py` (новые экспорты)
- `src/application/order_executor.py` (+bot_id)
- `src/application/strategy_runner.py` (+bot_id)
- `src/domain/interfaces.py` (+ExchangeAdapter.close default no-op, удалён Bybit из комментария)
- `tests/application/test_order_executor.py` и `test_strategy_runner.py` (обновлены под bot_id)
- 3 файла фронта (Bybit удалён)
- `README.md` (Bybit удалён в ascii-диаграмме)
- `docker-compose.yml` (раскомментирован engine)
- `.env.example` (+ENGINE секция + DEV ключи закомментировано)
- `.env` (создан с ENGINE секцией + ключами Binance)

**Тесты:** **86 passed**, 0 failed.
**Mypy `--strict`:** clean, 0 errors.

---

## 8. Что нужно от пользователя прямо сейчас

1. **Заменить `ENGINE_ENCRYPTION_KEY=CHANGE_ME_GENERATE_LOCALLY` в `.env`** на реальное значение от `BACKEND_ENCRYPTION_KEY`. Без этого движок упадёт при первой попытке расшифровать credentials.

2. **GitHub Secrets:** если на проде уже стоит `BACKEND_ENCRYPTION_KEY` — добавь точно такое же значение под именем `ENGINE_ENCRYPTION_KEY`. (Или в `.env` на прод-сервере — compose возьмёт через fallback.)

3. **Submodule pointer:** изменения в `trade-engine-crypto/` пока не закоммичены. План — четыре отдельных PR в submodule-репо `crypto-trade-engine`, затем bump в корневом `crypto-dashboard`. Я этого сам не делал, чтобы ты мог проверить и решить, как разбить на коммиты.

4. **CI для движка:** в `.github/workflows/deploy.yml` сейчас собираются только backend и frontend образы. Чтобы автодеплой работал — нужно добавить build-and-push job для `crypto-trade-engine` (тот же паттерн, что у backend). Это Phase 4.

---

## 9. Что НЕ сделано (отложено по плану)

- **Seed-скрипт** `scripts/seed_dev_credential.py` для вставки Binance Testnet ключей в `exchange_credentials` через Fernet (нужен для первого smoke-теста на реальной БД).
- **Add engine build to `deploy.yml`** — Phase 4.
- **Phase 2 (фронт):** UI пока остаётся моком — никаких API-вызовов, JWT, WebSocket. Это следующий большой блок.
- **Phase 3 (бэк):** rate-limit, интеграционные тесты, `/api/engine/status` endpoint, request_id в логах.
- **Phase 4 (прод-деплой):** nginx, TLS, push-to-deploy.
- **Phase 5 (наблюдаемость):** Telegram-алерты, централизованные логи.
