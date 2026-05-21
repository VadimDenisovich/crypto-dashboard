# AGENTS.md — Crypto Dashboard

Гид для AI-агентов и разработчиков по этому проекту. Описывает архитектуру, стек,
конвенции, команды и **детально — что уже было проделано** (Phase 1–5).

> Источник истины по архитектурным правилам — `.context/backend-rules.md` и
> `.context/trade-engine-rules.md` (папка `.context/` не коммитится: репо публичный,
> чтобы не утащить реквизиты). Этот файл — безопасная для коммита выжимка без секретов.

---

## 1. Что это за проект

Система **алгоритмической торговли криптовалютой**: пользователь через веб-дашборд
заводит API-ключи биржи, создаёт торговых ботов (стратегии), запускает их на
**реальной торговле (testnet)** и прогоняет стратегии на **исторических данных
(бэктест)**. Учебный/курсовой проект, но архитектура «как в проде».

Ключевой принцип: **backend не торгует**. Торговую логику исполняет отдельный процесс
(движок). Связь между ними — только через **PostgreSQL** и **Redis Pub/Sub**, без
прямых HTTP-вызовов. Сбой веб-сервера не останавливает торговлю.

---

## 2. Структура репозитория (monorepo + 3 submodule)

```
crypto-dashboard/                  ← корневой superproject (этот репо)
├── backend/                       ← SUBMODULE → crypto-dashboard-backend (FastAPI)
├── frontend/                      ← SUBMODULE → crypto-dashboard-frontend (React+MUI+Vite)
├── trade-engine-crypto/           ← SUBMODULE → crypto-trade-engine (движок + бэктест)
├── scripts/                       ← fetch_historical.py, seed-скрипты
├── data/historical/               ← parquet-кэш OHLCV (gitignored, кроме .gitkeep)
├── docker-compose.yml             ← прод-композиция (+ docker-compose.dev.yml для dev)
├── .github/workflows/             ← ci.yml, deploy.yml
├── .context/                      ← правила + phase-отчёты (НЕ коммитятся)
├── README.md, QUICKSTART.md, ROADMAP.md
```

Все три submodule отслеживаются на ветке `main`. Корень привязывает их через git
submodule pointers. **Правка кода = коммит в submodule + bump pointer в корне.**

Удалённые репозитории:
- backend → `github.com/VadimDenisovich/crypto-dashboard-backend`
- frontend → `github.com/VadimDenisovich/crypto-dashboard-frontend`
- engine → `github.com/VadimDenisovich/crypto-trade-engine`

> Проект также мигрирует в организацию **Crypto-Dashboard-Kursovay** (там идут PR'ы и
> туда пушатся GHCR-образы `ghcr.io/crypto-dashboard-kursovay/...`).

---

## 3. Архитектура (5 логических сервисов)

1. **Frontend** (React SPA) — единственная точка входа для пользователя.
2. **Backend API** (FastAPI) — тонкий шлюз: REST + WebSocket для UI, подписчик Redis
   Pub/Sub, хранилище в PostgreSQL. Также запускает **backtest worker** (asyncio-таска,
   дёргает движок subprocess'ом).
3. **Trading Engine** (Python-процесс) — стратегии, ордера, риск-менеджмент,
   взаимодействие с биржами через CCXT/CCXT.pro.
4. **Backtest Engine** — переиспользует те же `Strategy`/`RiskManager`, но с
   симулированной биржей и историческими данными. Запускается как `python -m
   backtest_main` (живёт в репо движка, исполняется как subprocess внутри backend-контейнера).
5. **Data & State Layer** — PostgreSQL (долговременно) + Redis (кэш, Pub/Sub, состояние).

### Поток «свеча → сделка → UI»
Биржа → WS → ExchangeAdapter → Candle → StrategyRunner → `strategy.on_candle()` →
Signal → RiskManager → OrderExecutor → `create_order()` → запись события в Redis
(`engine.new_trade`) → backend (подписчик Pub/Sub) проецирует в PostgreSQL +
ретранслирует в `/ws/updates` → фронт обновляет UI.

### Контракт Redis Pub/Sub (имена каналов — НЕ выдумывать)
Канонические константы — в `trade-engine-crypto/src/application/events.py`,
зеркало — в `backend/src/domain/events.py` (есть контрактный тест на синхронность).

- **Движок публикует:** `engine.new_trade`, `engine.balance_update`, `engine.status`,
  `engine.strategy_error`.
- **Backend публикует (команды движку):** `engine.commands.start|stop|update` с
  `command_id` (UUID, для идемпотентности) и `credentials_ref` (UUID записи, **не сами
  ключи**).
- **Decimal в JSON — всегда строка** (`"price": "42500.50"`).

---

## 4. Технологический стек

| Слой | Технологии |
|---|---|
| Frontend | React 19, TypeScript, Vite 6, MUI v7, recharts, react-router, `@marsidev/react-turnstile` |
| Backend | FastAPI, SQLAlchemy 2.0 Async + asyncpg, redis.asyncio, Pydantic v2 + pydantic-settings, Alembic, structlog, cryptography(Fernet), authlib, httpx, ccxt |
| Engine | Python 3.11, ccxt + ccxt.pro, SQLAlchemy 2.0 Async, redis.asyncio, structlog, tenacity, pandas/pyarrow (extras `[backtest]`) |
| Инфра | Docker / docker-compose, GitHub Actions, GHCR, nginx, PostgreSQL, Redis |
| Менеджеры | backend/engine — `uv` (uv.lock); frontend — `pnpm` |

Биржи (multi-exchange): **Binance, Bybit, OKX (требует passphrase), MEXC**. Реестр —
`backend/src/infrastructure/exchange_meta.py`.

---

## 5. Внутреннее устройство компонентов

### Backend — Clean Architecture, строгие слои
```
api/ (routers, schemas, deps)  →  services/ (use-cases)  →  repositories/ (БД)  →  infrastructure/ (Redis, Fernet, ccxt, email, oauth)
```
- Router **не** ходит в репозиторий напрямую. ORM-модели **не** утекают наружу из
  `repositories/` (наружу — Pydantic-схемы/DTO).
- DI через `Depends`. Глобального состояния нет. Инициализация пулов БД/Redis и
  подписчика Pub/Sub — в `lifespan`.
- Только async: запрещены `requests`, `psycopg2`, `time.sleep`.
- Таблицы-владельцы backend'а: `users`, `bots`, `exchange_credentials`,
  `bot_commands`, `oauth_identities`, `backtest_jobs`. По событиям из Redis пишутся:
  `orders`, `trades`, `balance_snapshots`, `strategy_errors`.
- API-ключи бирж шифруются **Fernet** (`BACKEND_ENCRYPTION_KEY`), в БД только ciphertext.
- Конфиг — единый `Pydantic Settings` (`backend/src/config.py`), env-префикс `BACKEND_`/
  провайдерские. Никаких `os.getenv` по коду.

### Engine — Clean Architecture
```
domain/ (Strategy ABC, Candle/Order/Balance/Signal dataclasses, interfaces, enums)
application/ (StrategyRunner, OrderExecutor, RiskManager, Orchestrator, BacktestRunner)
infrastructure/ (ccxt adapters, market data, redis bus, command listener, state manager, db, simulated_exchange, csv/ccxt historical)
strategies/ (реализации + StrategyRegistry)
```
- В `domain/` **запрещены** импорты инфраструктуры (`ccxt`, `sqlalchemy`, `redis`).
- `EngineOrchestrator` держит `bot_id → RunningStrategy` (asyncio.Task), обрабатывает
  команды start/stop/update идемпотентно (Redis dedup по `command_id`).
- `StateManager` — три loop'а: heartbeat (`engine.status`), balance poll
  (`engine.balance_update`), state snapshot в Redis (TTL).
- CCXT-вызовы обёрнуты в retry (tenacity, экспоненциальный backoff); precision
  через `price_to_precision`/`amount_to_precision`.

### Frontend
```
src/app/
├── App.tsx, routes.tsx, theme.ts          ← роутинг + Grok-style тёмная тема
├── LogsContext.tsx                         ← глобальный WS-провайдер логов (см. Phase 5)
├── auth/AuthContext.tsx                    ← JWT в localStorage, auto-refresh
├── api/                                    ← тонкие клиенты (client.ts + per-resource)
├── app/pages/                              ← Dashboard, Strategies, CreateStrategy, Trades, Backtesting, Logs, Settings, Login, AuthCallback
├── app/components/                         ← layout/ (Header, Sidebar), dashboard/ (виджеты), strategies/, auth/
└── app/styles/glassDropdown.ts            ← glassPopupSx для MUI Select/Autocomplete
```
- Защищённые страницы под `ProtectedRoute → Layout`. Тема `#0a0a0a`, glass-морфизм.
- Vite вшивает `VITE_*` на этапе билда (build-args в Dockerfile/CI).

---

## 6. Стратегии и бэктест

**7 стратегий** в `default_registry()` (`trade-engine-crypto/src/strategies/__init__.py`):
`SmaCross`, `RsiThreshold`, `MacdCross`, `BollingerBands`, `BollingerRsi`,
`DcaStrategy`, `SpotGridStrategy`. Имя строкой в `bots.strategy_class` резолвится в класс.

**Бэктест-движок** (`application/backtest_runner.py` + `backtest_main.py`): тот же
`Strategy`/`RiskManager`/`OrderExecutor`, но с `SimulatedExchangeAdapter` (MARKET по
`last_close ± slippage`, LIMIT в очереди с матчингом по range свечи) и историческими
данными. Считает: total return, max drawdown, Sharpe, win rate, profit factor, equity
curve, список сделок. Результат — JSON в stdout (`BacktestResult.to_json()`).

**Поток бэктеста:** UI → `POST /api/backtest/run` → запись `backtest_jobs` (queued) →
`asyncio.Queue` → `backtest_worker` готовит JSON-конфиг → `python -m backtest_main
--config <tmp>` (subprocess в backend-контейнере, `PYTHONPATH=/opt/engine/src`) →
парсит stdout → `mark_completed/mark_failed`. Фронт поллит `GET /api/backtest/{id}`.

---

## 7. Команды разработки

> Локально нужны запущенные PostgreSQL + Redis (через docker-compose или хостовые).

**Backend** (`cd backend`, окружение — `uv` или `.venv`):
```bash
uv run pytest -q                 # или ./.venv/bin/python -m pytest -q
alembic upgrade head             # применить миграции
alembic revision --autogenerate -m "human readable"   # новая ревизия (обязательна при правке моделей)
uv run uvicorn src.main:app --reload
```

**Engine** (`cd trade-engine-crypto`):
```bash
./.venv/bin/python -m pytest -q  # ~125 тестов
trade-engine                     # запуск движка (после pip install -e .)
```

**Frontend** (`cd frontend`):
```bash
pnpm install
pnpm dev                         # http://localhost:5173
pnpm build                       # прод-сборка (esbuild; полноценный typecheck — отдельно tsc)
```

**Вся система:** `docker compose up -d` →
backend `http://localhost:8000` (`/docs`, `/healthz`), frontend `http://localhost:5173`.

---

## 8. Деплой (CI/CD)

- `.github/workflows/deploy.yml`: на push в `main` (или `workflow_dispatch`).
  1. **build-and-push** — собирает 3 образа (backend/frontend/engine) и пушит в GHCR
     с тегами `:<sha>` и `:latest`. Frontend получает `VITE_*` через build-args.
  2. **deploy** — SSH на сервер, пишет `.env` из секретов, синкует submodule'ы,
     **логинится в `ghcr.io`** (`docker login ... --password-stdin`, job имеет
     `permissions: packages: read`), `docker compose pull`, `docker compose run --rm
     migrate`, `docker compose up -d`, reload nginx.
- Секреты — только в GitHub Secrets / серверном `.env` (никогда в репо). Это:
  `BACKEND_*`, `*_CLIENT_ID/SECRET/REDIRECT_URI` (Google/Yandex/GitHub), `TELEGRAM_*`,
  `RESEND_*`, `CLOUDFLARE_TURNSTILE_*`, `DEPLOY_SSH_*`, `VITE_*`.
- **Важно про бэктест на сервере:** том `./data/historical:/data/historical`
  смонтирован **read-write** (движок докачивает и кэширует parquet). Каталог должен
  существовать (`data/historical/.gitkeep` в репо).

---

## 9. Что было проделано — история по фазам

### Phase 1 — Engine Infrastructure (движок «ожил»)
Движок получил entrypoint (`engine_main.py`, команда `trade-engine`), подключение к
общим Postgres+Redis, расшифровку Fernet-кредов, `RedisEventBus`, `CCXTExchangeAdapter`
(+retry/precision/нормализация), `CCXTMarketDataProvider` (WS + реконнект + дедуп),
`EngineOrchestrator` (start/stop/update ботов идемпотентно), `CommandListener`,
`StateManager` (heartbeat/balance/snapshot), стратегию `SmaCross` + `StrategyRegistry`,
Dockerfile, раскомментирован сервис `engine` в compose. `bot_id` прокинут во все
payload'ы заранее. 86 тестов, mypy --strict clean.

### Phase 2 — Auth: Identity Providers
Переход с email+пароль на **email-код** (через Resend) + **OAuth**
(Google/Yandex/GitHub/Telegram) + капча. Регистрация автоматическая при первом входе.
Новая таблица `oauth_identities`, миграция `0002` (TRUNCATE users, password_hash →
nullable). `identity_service.resolve_or_create`, `email_codes` на Redis (TTL/attempts/
rate-limit), Telegram HMAC-проверка. Фронт: единая `/login` с соц-кнопками + email-форма
+ `/auth/callback`. Title/favicon → Crypto Dashboard.

### Phase 2.5/3 — Multi-exchange + Turnstile + Grok-UI
- **Multi-exchange:** Binance/Bybit/OKX/MEXC. Реестр `exchange_meta.py`, миграция
  `0003` (`passphrase_enc`, обязателен для OKX), endpoint `/api/exchanges/supported` и
  `/api/exchanges/{name}/symbols` (раньше — топ-10 USDT-пар по объёму, кэш в Redis 1ч).
- **Капча:** hCaptcha → **Cloudflare Turnstile** (backend captcha.py + фронт
  `@marsidev/react-turnstile`).
- **UI:** Grok-эстетика в `theme.ts` (тёмная палитра, glass-морфизм) — все страницы
  подхватывают через MUI overrides.
- Хотфикс Telegram synthetic email (`.local` → `.invalid`).

### Phase 4 — Backtest engine + де-мок фронта
- **Движок бэктеста с нуля:** `SimulatedExchangeAdapter`, `CSVMarketDataProvider`
  (parquet/csv), `BacktestRunner` (метрики/equity), `backtest_main` CLI,
  `InMemoryEventBus`, `domain/backtest_result.py`. Добавлены 6 стратегий (RSI, MACD,
  BB, BB+RSI, DCA, Grid).
- **Backend:** таблица `backtest_jobs` (миграция `0004`), `backtest_repo`,
  `backtest_worker` (subprocess + asyncio.Queue), router `/api/backtest/*`, конфиг
  (`backend_backtest_cmd/historical_dir/timeout`), backend Dockerfile + pandas/pyarrow,
  bind-mount движка в backend.
- **Фронт:** де-мок Dashboard-виджетов (честные «Нет данных»), `RecentTradesWidget`/
  `Trades` на `/api/trades`, `Logs` на `/ws/updates`, страница `/backtesting` (форма +
  polling + recharts equity), branding (Header/Sidebar/footer-версия).
- `scripts/fetch_historical.py` (CCXT REST loader → parquet).
- 125 тестов движка.

### Phase 5 — Логи / ограничение пар / UI / реальный бэктест (последняя фаза)
> План: `.context/phase-5-logs-pairs-ui-backtest-design.md`. Все правки в submodule'ах
> на `main` (по решению автора отдельная ветка делалась только в корне).

1. **Логи онлайн + 12ч:** новый `frontend/src/app/LogsContext.tsx` — WS-соединение и
   буфер живут глобально, пока пользователь залогинен (провайдер обёрнут вокруг
   `Layout`), пишутся в `localStorage` (`crypto.logs.v1`), записи старше 12ч
   отсекаются. `Logs.tsx` стал потребителем `useLogs()`.
2. **Ограничение пар:** `ALLOWED_SYMBOLS = (BTC, SOL, XRP, BNB, ETH)/USDT` в
   `exchange_meta.py`; `/api/exchanges/{name}/symbols` отдаёт пересечение allowlist с
   реальными markets биржи (fallback — весь allowlist). Действует и для создания
   стратегии, и для бэктеста.
3. **UI:** капча растянута по ширине поля email; «Выйти» → иконка двери с тултипом
   (Header). *(Примечание: удаление строк Backend/PostgreSQL/Redis в `EngineStatusWidget`
   было откатано — строки намеренно оставлены.)*
4. **Реальный бэктест (гибрид):** в `backtest_jobs` добавлена колонка `exchange`
   (миграция `0005`), проброшена через схемы/репо/роутер. `backtest_worker` использует
   биржу job'а, передаёт диапазон дат (мс) и канонический путь кэша. Движок:
   `infrastructure/ccxt_historical.py` (тянет OHLCV с **реальной** биржи без sandbox,
   кэширует в parquet), фильтр диапазона дат в `CSVMarketDataProvider`, гибридная
   логика в `backtest_main` (есть parquet и покрывает период → берём кэш; иначе
   докачиваем с биржи и сохраняем). docker-compose mount `data/historical` стал
   read-write. Цифры теперь считаются строго за выбранный период на реальных данных.
5. **Deploy fix:** на сервере добавлен `docker login ghcr.io` перед `docker compose
   pull` + `permissions: packages: read` (приватные GHCR-образы давали `unauthorized`).

---

## 10. Известные ограничения / отложено

- Realtime Balance/Positions/Chart на Dashboard — пока placeholder'ы (нет
  `/api/balances/summary`, `/api/positions`, `/api/candles/...`).
- Один backtest за раз (одна asyncio-таска worker'а); очередь — in-process
  `asyncio.Queue`, не Redis Stream.
- Grid использует MARKET-ордера (нет `on_order_filled` callback'а); PnL в бэктесте
  упрощён (один BUY → один SELL).
- JWT в localStorage (XSS-риск); нет 2FA, нет revocation refresh-токенов.
- Колонка `users.password_hash` всё ещё nullable (legacy).
- Возможен `exchange.network_error` при гео-блоке биржи на VPS (нужен прокси/смена хоста).

---

## 11. Конвенции и правила (кратко)

- **Async везде.** Никаких блокирующих вызовов в event loop.
- **Миграции Alembic обязательны** при любой правке моделей; имена человекочитаемые,
  ревизии последовательны (`0001 → 0005`).
- **Контракт каналов/payload'ов синхронизируй** между движком и backend (есть тесты).
- **Decimal — строкой** в JSON-payload'ах.
- **Секреты не логировать и не коммитить.** `.env` в `.gitignore`; `.context/` тоже.
- **TDD:** сервисы/бизнес-логику покрывать тестами; биржу/БД мокать (`AsyncMock`,
  `fakeredis`); в интеграционных тестах backend — настоящий Postgres (SQLite запрещён).
- **Git:** правка submodule → коммит в submodule (`main`) → bump pointer в корне.
  Push/PR — по запросу. Образы и деплой завязаны на push в `main`.
- **MCP:** Context7 — для документации библиотек (FastAPI/SQLAlchemy/Pydantic v2/ccxt и т.п.).
```
Co-Authored-By в коммитах и стиль сообщений — `type(scope): summary` (conventional commits).
```
