# Phase 1 — Engine Infrastructure Layer

## Context

`crypto-dashboard` — это монорепо с тремя submodules. По текущему состоянию:

- **Backend** ([backend/](backend/)) — готов: REST, WS, JWT, Fernet, Redis subscriber на `engine.*`, publisher `engine.commands.*`, Alembic.
- **Engine** ([trade-engine-crypto/](trade-engine-crypto/)) — есть только **Domain + Application** слои (бизнес-логика, ABC-интерфейсы, 4 канала событий, тесты на ~37% LOC). **Нет Infrastructure**, нет entrypoint, `pyproject.toml` с пустыми deps, нет стратегий, нет Dockerfile, нет CommandListener / StateManager / EngineOrchestrator.
- **Frontend** ([frontend/](frontend/)) — Figma-мок без реальных API-вызовов.

ROADMAP делит работу на 6 фаз. **Phase 1** (этот план) — самая большая: реализовать Infrastructure слой движка, чтобы движок **реально торговал** на Binance Testnet и общался с бэком через Redis Pub/Sub.

После Phase 1 будут зелёные тесты, докер-образ, и сценарий: `redis-cli publish engine.commands.start '{...}'` → движок запускает SMA-стратегию → реальная свеча с Binance Testnet → сигнал → ордер → событие `engine.new_trade` → запись в `orders` бэка → WebSocket-обновление готово для фронта (но сам фронт оживёт уже в Phase 2).

---

## Что уже есть и что нужно сделать

### Существует (НЕ трогаем, переиспользуем)

- **Domain слой** ([trade-engine-crypto/src/domain/](trade-engine-crypto/src/domain/)) — `Candle`, `Signal`, `Order`, `Balance`, `Position` (frozen dataclass + Decimal), enums, `DomainError`-иерархия, ABC-интерфейсы `ExchangeAdapter`, `MarketDataProvider`, `Strategy`, `EventBus`.
- **Application слой** ([trade-engine-crypto/src/application/](trade-engine-crypto/src/application/)) — `StrategyRunner`, `RiskManager`, `OrderExecutor`. События: 4 канала в `application/events.py:1-6`.
- **Backend события** ([backend/src/domain/events.py:1-25](backend/src/domain/events.py)) — побитово совпадают с движком, плюс 3 канала команд `engine.commands.{start,stop,update}`.
- **docker-compose.yml** ([docker-compose.yml:50-60](docker-compose.yml)) — закомментированный сервис `engine`, ждёт entrypoint.

### Нужно создать

| Слой | Файл | Назначение |
|---|---|---|
| Application | `src/application/events.py` (**дополнить**) | Добавить `COMMAND_START`, `COMMAND_STOP`, `COMMAND_UPDATE`, `LISTENED_CHANNELS`, зеркало бэка |
| Application | `src/application/orchestrator.py` (**новый**) | `EngineOrchestrator` — start/stop/update стратегии по `bot_id`, владеет dict `bot_id → RunningStrategy` |
| Infrastructure | `src/infrastructure/__init__.py` | пустой |
| Infrastructure | `src/infrastructure/settings.py` | `pydantic-settings.BaseSettings`, читает env (см. секцию «Секреты») |
| Infrastructure | `src/infrastructure/logging.py` | конфиг `structlog` (JSON, request_id support) |
| Infrastructure | `src/infrastructure/redis_event_bus.py` | `RedisEventBus(EventBus)` — `publish` через `redis.asyncio`, `default=str` для Decimal |
| Infrastructure | `src/infrastructure/ccxt_exchange_adapter.py` | `CCXTExchangeAdapter(ExchangeAdapter)` поверх `ccxt.pro`, retry с экспоненциальным backoff, `amount_to_precision` / `price_to_precision` |
| Infrastructure | `src/infrastructure/ccxt_market_data.py` | `CCXTMarketDataProvider(MarketDataProvider)` через `exchange.watch_ohlcv`, реконнект с backoff |
| Infrastructure | `src/infrastructure/command_listener.py` | Подписка на `engine.commands.*`, идемпотентность через `SET engine:commands:processed:<id> 1 EX 86400`, dispatch в `EngineOrchestrator` |
| Infrastructure | `src/infrastructure/state_manager.py` | dict `bot_id → RunningStrategy`, snapshot в Redis каждые 5-10с (`engine:state:<bot_id>` EX 30), heartbeat в `engine.status`, balance poll → `engine.balance_update` |
| Infrastructure | `src/infrastructure/db_repositories.py` | `BotRepository.get(bot_id)`, `CredentialRepository.get_decrypted(credential_id)` через SQLAlchemy 2.0 async + Fernet (общий ключ с бэком) |
| Entrypoint | `src/__main__.py` | wire-up: settings → redis → db → event_bus → orchestrator → listener + state.run() в `asyncio.TaskGroup`, SIGTERM/SIGINT handler |
| Strategies | `src/strategies/__init__.py` | реестр доступных стратегий по строковому имени (для `strategy_class` из команды бэка) |
| Strategies | `src/strategies/sma_cross.py` | SMA50/SMA200 cross, `deque(maxlen=200)`, `on_candle()` синхронный |
| Build | `pyproject.toml` (**дополнить**) | deps: `ccxt>=4.3`, `redis>=5.0`, `asyncpg>=0.29`, `sqlalchemy[asyncio]>=2.0.30`, `pydantic-settings>=2.3`, `structlog>=24.1`, `cryptography>=42`, `tenacity>=9` |
| Build | `Dockerfile` | multi-stage, non-root, по образцу [backend/Dockerfile](backend/Dockerfile) |
| Build | `docker-compose.yml` (**раскомментировать engine**, [docker-compose.yml:50-60](docker-compose.yml)) | + env-блок `ENGINE_*` |
| Build | `.env.example` (**дополнить**) | секция `=== ENGINE ===` (см. «Секреты») |
| Tests | `tests/infrastructure/*.py` | unit-тесты на `fakeredis`/`AsyncMock` для каждого инфра-класса |
| Tests | `tests/integration/test_command_roundtrip.py` | smoke с реальными postgres/redis: publish команды бэка → orchestrator стартует → state в Redis |
| Tests | `tests/integration/test_events_contract.py` | зеркало `backend/tests/unit/test_events_constants.py` — каналы в обе стороны идентичны |

---

## Архитектурные решения и несостыковки

### 1. Движок читает БД напрямую (через Infrastructure)
ROADMAP явно предписывает `db_repositories.py` в движке. Это **не нарушает Clean Architecture**: запрет на `sqlalchemy` — только для `domain/`, в `infrastructure/` импорт легален. Бэк и движок разделяют одну БД (один Postgres, одни таблицы `bots` / `exchange_credentials`). Bot config в БД, не в команде Redis (команда несёт только `command_id`, `bot_id`, опционально `params`).

### 2. Расшифровка credentials — у движка
Бэк шифрует `api_key`/`api_secret` через Fernet (`BACKEND_ENCRYPTION_KEY`). Движок при запуске стратегии:
1. Получает команду `engine.commands.start` с `bot_id`.
2. `BotRepository.get(bot_id)` → конфиг + `credential_id`.
3. `CredentialRepository.get_decrypted(credential_id)` использует **тот же Fernet-ключ** (`ENGINE_ENCRYPTION_KEY` = `BACKEND_ENCRYPTION_KEY`).
4. Передаёт plaintext в `CCXTExchangeAdapter(api_key=..., api_secret=...)`.

**Критично:** ключи должны совпадать. Иначе движок не сможет расшифровать.

### 3. EngineOrchestrator в Application, не в Infrastructure
В ROADMAP про `EngineOrchestrator` написано вскользь (раздел 1.5). Логически это **Application слой** (бизнес-флоу: «запустить стратегию по id, остановить, обновить»), а не Infrastructure. Поэтому файл — `src/application/orchestrator.py`. Это расширение Application, не нарушающее существующих модулей.

### 4. Каналы команд — добавить в `application/events.py`
Сейчас в движке только 4 канала событий. Команды бэка (`engine.commands.start|stop|update`) тоже должны быть константами в движке для единого источника правды. Зеркалим из [backend/src/domain/events.py:23-25](backend/src/domain/events.py#L23-L25).

### 5. EventBus.subscribe — не добавляем
`EventBus` в Domain — это **outbound** интерфейс (publish only). Подписка — это infrastructure-деталь, живёт в `CommandListener` напрямую через `redis.asyncio.Redis.pubsub()`. Domain остаётся чистым.

### 6. payload `engine.new_trade` / `engine.strategy_error` должен содержать `bot_id`
Бэковский resolver в `event_projector.py` ищет бота по `strategy_class` через `LIMIT 1` — это баг ROADMAP Phase 3.1. Чтобы Phase 3 был дешёвым, **уже сейчас в Phase 1** в payload каждого engine-события класть `"bot_id": "<uuid>"`. `OrderExecutor` сейчас публикует payload без `bot_id` ([trade-engine-crypto/src/application/order_executor.py:35-46]) — нужно его расширить (через DI из `EngineOrchestrator`).

### 7. Multi-bot, single-process
Один процесс движка обслуживает все боты всех пользователей. `StateManager` держит dict `bot_id → RunningStrategy(task: asyncio.Task, config, last_balance)`. Каждая стратегия — отдельная `asyncio.Task` в общем `TaskGroup`. Падение одной не валит остальные.

### 8. Биржа на Phase 1 — только Binance Testnet
`CCXTExchangeAdapter` пока поддерживает только Binance (через `ccxt.pro.binance`). Конструктор принимает `exchange_name`, но валидируется одно значение `"binance"` — чтобы при добавлении новых бирж не ломать API.

- testnet включается через `exchange.set_sandbox_mode(True)`
- Binance требует `apiKey` + `secret`

Тесты в `tests/infrastructure/test_ccxt_exchange_adapter.py` — с `AsyncMock` для CCXT.

Реестр стратегий загружает стратегию по строковому имени из `engine.commands.start.payload.strategy_class` — это не зависит от биржи (биржа берётся из `bot.exchange` в БД).

---

## Декомпозиция на PR'ы (для парной работы)

Поскольку с напарником разделение горизонтальное, разбиваем Phase 1 на 4 PR. PR2 и PR3 могут идти параллельно после PR1.

| PR | Содержимое | Зависит от |
|---|---|---|
| **PR1: Каркас + EventBus** | пустые папки, `pyproject.toml` deps, `settings.py`, `logging.py`, `RedisEventBus` + тесты, расширенный `events.py` (команды), `pre-commit`/mypy фиксы | — |
| **PR2: Биржевые адаптеры** | `CCXTExchangeAdapter`, `CCXTMarketDataProvider`, retry/backoff, precision, тесты с AsyncMock | PR1 |
| **PR3: Контроль и состояние** | `EngineOrchestrator`, `CommandListener`, `StateManager`, `db_repositories`, расширение `OrderExecutor` с `bot_id`, тесты с `fakeredis` | PR1 |
| **PR4: Entrypoint + стратегия + контейнер** | `__main__.py`, `strategies/sma_cross.py`, `Dockerfile`, раскомментированный `docker-compose.yml`, `.env.example`, integration smoke | PR2, PR3 |

После каждого PR в submodule — отдельный коммит в корне `crypto-dashboard` (`git submodule update --remote trade-engine-crypto`).

---

## Критичные файлы (источники истины)

- [trade-engine-crypto/src/domain/interfaces.py](trade-engine-crypto/src/domain/interfaces.py) — ABC, под которые пишем реализации
- [trade-engine-crypto/src/domain/models.py](trade-engine-crypto/src/domain/models.py) — `Candle`/`Order`/`Balance`, в которые нормализуем CCXT-ответы
- [trade-engine-crypto/src/application/events.py](trade-engine-crypto/src/application/events.py) — расширить командами
- [trade-engine-crypto/src/application/strategy_runner.py](trade-engine-crypto/src/application/strategy_runner.py) — переиспользуем без изменений
- [backend/src/domain/events.py](backend/src/domain/events.py) — зеркало каналов, обязано совпадать
- [backend/src/services/event_projector.py](backend/src/services/event_projector.py) — узнать, какие поля бэк ждёт в payload
- [backend/Dockerfile](backend/Dockerfile) — шаблон для `trade-engine-crypto/Dockerfile`
- [docker-compose.yml:50-60](docker-compose.yml) — секция engine, раскомментировать
- [.context/trade-engine-rules.md](.context/trade-engine-rules.md) — обязательные конвенции (Clean Arch, async-only, mypy strict)

---

## Секреты и env переменные

### Уже есть в `.env.example` (нужны и движку — те же значения)
- `BACKEND_DATABASE_URL` — движок использует тот же Postgres → `ENGINE_DATABASE_URL=<то же значение>`
- `BACKEND_REDIS_URL` — движок использует тот же Redis → `ENGINE_REDIS_URL=<то же значение>`
- `BACKEND_ENCRYPTION_KEY` — Fernet-ключ → `ENGINE_ENCRYPTION_KEY=<то же значение, ОБЯЗАТЕЛЬНО совпадает>`

### Новые переменные для движка (добавить в `.env.example` и в `docker-compose.yml`)
- `ENGINE_DATABASE_URL` — postgresql+asyncpg://user:pass@host:5432/db
- `ENGINE_REDIS_URL` — redis://host:6379/0
- `ENGINE_ENCRYPTION_KEY` — Fernet-ключ (==`BACKEND_ENCRYPTION_KEY`)
- `ENGINE_LOG_LEVEL` — INFO/DEBUG
- `ENGINE_HEARTBEAT_INTERVAL_SEC=10`
- `ENGINE_BALANCE_POLL_INTERVAL_SEC=15`
- `ENGINE_STATE_SNAPSHOT_TTL_SEC=30`
- `ENGINE_COMMAND_DEDUP_TTL_SEC=86400`

### Биржевые ключи (НЕ в env, а в БД!)
API-ключи Binance Testnet **не идут в env движка** — пользователь добавляет их через фронт (Phase 2: `POST /api/exchange-credentials`), бэк шифрует Fernet'ом, движок расшифровывает при запуске бота. Для интеграционного теста (`test_command_roundtrip.py`) можно временно поднять тестовые ключи через `INSERT INTO exchange_credentials ...`.

### Что нужно от тебя (пользователя) прямо сейчас

1. **Локальный `.env`** — добавить блок:
   ```bash
   # === ENGINE === (дублирует значения BACKEND_*, кроме лог-уровня и интервалов)
   ENGINE_DATABASE_URL=${BACKEND_DATABASE_URL}
   ENGINE_REDIS_URL=${BACKEND_REDIS_URL}
   ENGINE_ENCRYPTION_KEY=${BACKEND_ENCRYPTION_KEY}
   ENGINE_LOG_LEVEL=INFO
   ENGINE_HEARTBEAT_INTERVAL_SEC=10
   ENGINE_BALANCE_POLL_INTERVAL_SEC=15
   ```
   Bash-подстановки `${...}` сами не разрешатся — копируй фактические значения из секции BACKEND.

2. **Прод-сервер `.env`** — после деплоя добавить те же `ENGINE_*` строки. На прод-сервере уже должны быть валидные `BACKEND_ENCRYPTION_KEY` и `BACKEND_DATABASE_URL` от Phase 0.

3. **Binance Testnet API ключи** — нужны для верификации Phase 1 (но НЕ как `ENGINE_*` env):
   - Регистрация: https://testnet.binance.vision/ → API Key + Secret Key
   - После Phase 2 (фронт) — внести через UI. Для smoke-теста сейчас — `psql` инсертом или временным скриптом (`scripts/seed_dev_credential.py`), который шифрует тем же Fernet-ключом и кладёт в `exchange_credentials` с `exchange='binance'`.
   - Локальные тестовые ключи лежат в `.env` (gitignored) под именами `DEV_BINANCE_TESTNET_API_KEY` / `DEV_BINANCE_TESTNET_API_SECRET` — их читает только seed-скрипт, не сам движок.

4. **GitHub Secrets для CI/CD (Phase 0, если ещё не сделано)** — это к движку напрямую не относится, но напоминание: `DEPLOY_SSH_HOST`, `DEPLOY_SSH_PORT`, `DEPLOY_SSH_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_PATH`, плюс `BACKEND_*` для прод-`.env`. См. ROADMAP Phase 0.3.

5. **(Опционально) GHCR-токен** — если пакеты приватные, нужен `GHCR_PAT` в секретах, чтобы `docker login ghcr.io` работал в CI и на сервере. Иначе сделать пакеты `crypto-trade-engine` публичными в GitHub UI.

---

## Verification (Definition of Done для Phase 1)

1. **Локальный запуск**
   ```bash
   cd /Users/vadim_denisovich/Documents/Projects/crypto-dashboard
   docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
   curl http://localhost:8000/healthz   # 200
   docker compose logs engine | head    # «engine started, subscribed to engine.commands.*»
   ```

2. **Heartbeat в Redis Pub/Sub**
   ```bash
   docker compose exec redis redis-cli SUBSCRIBE engine.status
   # каждые ~10 сек: {"uptime": ..., "active_bots": []}
   ```

3. **Roundtrip команды (без UI)**
   ```bash
   # подготовить bot + credential в БД (psql или fixture)
   docker compose exec redis redis-cli PUBLISH engine.commands.start \
     '{"command_id":"<uuid>","bot_id":"<bot-uuid>"}'
   docker compose logs engine | grep "strategy started"
   docker compose exec redis redis-cli GET engine:state:<bot-uuid>   # должен быть JSON
   ```

4. **Реальная сделка (Binance Testnet)**
   - Создать бота с SMA Cross на `BTC/USDT 1m`, credentials Binance Testnet → ордер исполняется на Binance testnet.
   - В логах виден ордер → запись в `orders` таблице бэка → событие в `engine.new_trade` с правильным `bot_id`.

5. **Тесты**
   ```bash
   cd trade-engine-crypto
   pytest                          # юнит и интеграция зелёные
   mypy --strict src               # без ошибок
   ```

6. **Контракт каналов**
   ```bash
   cd backend && pytest tests/unit/test_events_constants.py
   cd ../trade-engine-crypto && pytest tests/integration/test_events_contract.py
   # оба зелёные → каналы синхронизированы
   ```

7. **Submodule pointer**
   После мерджа PR в `trade-engine-crypto`:
   ```bash
   cd /Users/vadim_denisovich/Documents/Projects/crypto-dashboard
   git submodule update --remote trade-engine-crypto
   git add trade-engine-crypto && git commit -m "chore: bump engine submodule (Phase 1)"
   ```

---

## Что НЕ делается в Phase 1 (отложено)

- Биржи кроме Binance (Bybit, OKX, Kraken и т.п.) — добавляются параметризацией позже
- Бэктестинг — Phase 6
- Rate limit и интеграционные тесты бэка — Phase 3
- API-клиент и WS на фронте — Phase 2
- nginx + TLS + автодеплой — Phase 4

---

## Сохранение плана

После одобрения через ExitPlanMode скопировать этот файл в [.context/phase-1-engine-infrastructure.md](.context/phase-1-engine-infrastructure.md) (внутри репо `crypto-dashboard`, рядом с `trade-engine-rules.md` и другими доками).
