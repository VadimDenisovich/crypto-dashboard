# План: создать `ROADMAP.md` рядом с README — что осталось до боевой работы

## Context

Монорепо `crypto-dashboard` запушено в три публичных репозитория (root + 3 submodule). На текущий момент:

- **Backend** (`crypto-dashboard-backend`) — реализован полностью: REST + WS, JWT, Fernet, Redis Pub/Sub subscriber и publisher, миграции Alembic, healthcheck, тесты.
- **Engine** (`crypto-trade-engine`) — есть только **Domain + Application** слои (бизнес-логика + ABC-интерфейсы). **Infrastructure слой полностью отсутствует** (нет реализаций `EventBus`, `ExchangeAdapter`, `MarketDataProvider`, нет `CommandListener`, нет `StateManager`), нет entrypoint'а, пустые зависимости в `pyproject.toml`, нет стратегий, нет Dockerfile.
- **Frontend** (`crypto-dashboard-frontend`) — это **Figma-мок**: UI готов, но **нет ни одного реального API-вызова, нет JWT-клиента, нет WebSocket-подключения**, все данные хардкод.

Пользователь работает с одним сокомандником, разделение «горизонтальное» (без жёстких ролей). Нужно создать **один общий ROADMAP.md** рядом с `README.md` в корне `crypto-dashboard`, который:
1. Чётко описывает текущее состояние («что есть, что нет»).
2. Разбивает оставшееся на фазы (Phase 0…5) с явными метками компонента `[ENGINE] [BACKEND] [FRONTEND] [DEVOPS]`.
3. По каждой задаче даёт **конкретику**: какие файлы создать/изменить, какие функции/интерфейсы реализовать, какие зависимости добавить, как проверить готовность.
4. Содержит финальный «Definition of Done» — чек-лист «система работает целиком».

Файл `ROADMAP.md` живёт в `/Users/vadim_denisovich/Documents/Projects/crypto-dashboard/ROADMAP.md` (корневой репо). Это единственный файл, который создаётся в этой задаче — никакого кода.

---

## Финальное содержание `ROADMAP.md`

```markdown
# ROADMAP — что нужно сделать до полностью рабочей системы

Этот файл — план для двух соразработчиков. Задачи помечены меткой компонента,
которая указывает, в каком submodule их делать. Поскольку разделение между
разработчиками «горизонтальное», берите любую свободную задачу.

**Легенда меток:**
- `[ENGINE]` — submodule `trade-engine-crypto`
- `[BACKEND]` — submodule `backend`
- `[FRONTEND]` — submodule `frontend`
- `[DEVOPS]` — корневой репо `crypto-dashboard` или прод-сервер
- `[DOCS]` — README / правила / .context

Каждая задача в submodule — это PR в соответствующий репозиторий, плюс
обновление указателя submodule в корневом репо (`git submodule update --remote` →
коммит в `crypto-dashboard`).

---

## Текущее состояние (что готово, что нет)

| Компонент | Готово | Не готово |
|---|---|---|
| **Backend** | REST `/auth/*`, `/api/{bots,exchange-credentials,trades,orders,balances}`, `/ws/updates`, JWT, Fernet, миграции Alembic, Redis subscriber на `engine.*`, publisher `engine.commands.*`, healthcheck, unit-тесты, Dockerfile | Интеграционные тесты с реальным Postgres, alignment с фронтом по конкретным URL, rate-limit |
| **Engine** | Domain (`Candle`, `Order`, `Signal`, `Balance`, enums), Application (`StrategyRunner`, `RiskManager`, `OrderExecutor`), константы каналов | **Весь Infrastructure слой**, entrypoint, зависимости в `pyproject`, стратегии, Dockerfile |
| **Frontend** | UI-страницы (Dashboard, Strategies, Trades, Backtest, Logs, Settings), роутер, Tailwind+MUI | **API-клиент**, **JWT и логин-форма**, **WebSocket-клиент**, замена моков на реальные запросы |
| **Infra** | docker-compose (prod+dev), CI/CD workflows, .env.example, .gitignore | GitHub Secrets, deploy-ключ на сервере, external-сеть docker для postgres/redis, первичный compose-up на сервере |

---

## Архитектурное напоминание

```
Frontend ─HTTP─▶ Backend ◀─Pub/Sub─▶ Engine ◀─WS/REST─▶ Биржа
              ▲          (Redis)             (CCXT.pro)
              │
           WebSocket
              │
              ▼
         Real-time updates
```

Backend и Engine — **независимые процессы**, общаются только через PostgreSQL и Redis. Имена Pub/Sub-каналов — в `trade-engine-crypto/src/application/events.py` (источник истины) и зеркалом в `backend/src/domain/events.py`.

---

## Phase 0. Окружение и доступы (без этого нельзя начать) — `[DEVOPS]`

### 0.1 Локальный `.env`
1. `cp .env.example .env` в корне.
2. Сгенерировать секреты:
   ```bash
   python3 -c "import secrets; print('BACKEND_JWT_SECRET=' + secrets.token_urlsafe(64))"
   python3 -c "from cryptography.fernet import Fernet; print('BACKEND_ENCRYPTION_KEY=' + Fernet.generate_key().decode())"
   ```
3. Вставить значения в `.env`. **Никогда не коммитить.**

### 0.2 SSH deploy-ключ для CI
1. Сгенерировать пару: `ssh-keygen -t ed25519 -f ~/deploy_keys/crypto-dashboard -C "github-actions"`
2. Публичный ключ — на прод-сервер: `ssh-copy-id -i ~/deploy_keys/crypto-dashboard.pub -p <PORT> <USER>@<HOST>`. Если на сервере уже есть `authorized_keys`, добавить руками.
3. Приватный ключ — **полное содержимое файла**, в GitHub Secret `DEPLOY_SSH_KEY`.

### 0.3 GitHub Secrets (Settings → Secrets and variables → Actions)
Создать в репо `crypto-dashboard`:

| Secret | Значение | Как получить |
|---|---|---|
| `DEPLOY_SSH_HOST` | IP/домен прод-сервера | известно |
| `DEPLOY_SSH_PORT` | SSH-порт | известно |
| `DEPLOY_SSH_USER` | пользователь на сервере | известно |
| `DEPLOY_SSH_KEY` | приватный ed25519-ключ | см. 0.2 |
| `DEPLOY_PATH` | `/docker/crypto-dashboard` (или другой) | договориться |

### 0.4 Первичная подготовка сервера
На сервере (один раз):
```bash
mkdir -p /docker/crypto-dashboard && cd /docker/crypto-dashboard
git clone --recurse-submodules https://github.com/VadimDenisovich/crypto-dashboard.git .
cp .env.example .env && nano .env   # вписать прод-значения
```
Узнать имя docker-сети, в которой живут уже-поднятые `postgres` и `redis`:
```bash
docker network ls
docker inspect <postgres-container> --format '{{json .NetworkSettings.Networks}}' | jq
```
Записать имя сети — оно понадобится в `docker-compose.yml`.

### 0.5 Подключить наши сервисы к этой сети
В корневом `docker-compose.yml` раскомментировать блок `networks` внизу и подставить найденное имя:
```yaml
networks:
  default:
    name: <ИМЯ_СЕТИ_ИЗ_0.4>
    external: true
```
В `.env` на сервере: `DB_HOST=<имя-контейнера-postgres>`, `REDIS_HOST=<имя-контейнера-redis>` — именно имена контейнеров в этой сети, не IP и не `localhost`.

### 0.6 Доступ к GHCR
Если пакеты в GHCR приватные:
```bash
echo $GITHUB_TOKEN | docker login ghcr.io -u $GITHUB_USER --password-stdin
```
Иначе — в GitHub UI у каждого пакета `crypto-dashboard-backend` и `crypto-dashboard-frontend` поставить **Package visibility: Public**.

### ✅ Готово, когда
- `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build` локально поднимает всё; `curl http://localhost:8000/healthz` возвращает 200.
- В Actions при push в `main` отрабатывает `ci.yml` зелёным и `deploy.yml` доходит до шага «Deploy over SSH» без ошибки аутентификации.

---

## Phase 1. Движок: Infrastructure слой — `[ENGINE]`

Самый большой блок. Без этого ничего не торгует.

### 1.1 Создать структуру и обновить `pyproject.toml`
Файлы:
- `trade-engine-crypto/src/infrastructure/__init__.py`
- `trade-engine-crypto/src/infrastructure/{redis_event_bus,ccxt_exchange_adapter,ccxt_market_data,command_listener,state_manager,db_repositories}.py`
- `trade-engine-crypto/src/__main__.py`
- `trade-engine-crypto/src/strategies/__init__.py`, `trade-engine-crypto/src/strategies/sma_cross.py`

Зависимости в `pyproject.toml`:
```toml
dependencies = [
    "ccxt>=4.3",
    "redis>=5.0",
    "asyncpg>=0.29",
    "sqlalchemy[asyncio]>=2.0.30",
    "pydantic-settings>=2.3",
    "structlog>=24.1",
    "websockets>=12",
]
```

### 1.2 `redis_event_bus.py` — реализация `EventBus`
```python
class RedisEventBus(EventBus):
    def __init__(self, redis: Redis): ...
    async def publish(self, channel: str, payload: Mapping[str, Any]) -> None:
        await self._redis.publish(channel, json.dumps(payload, default=str))
```
Decimal сериализуется как строка (`default=str`). Проверь тестом, что `Decimal("0.001")` → `"0.001"`.

### 1.3 `ccxt_exchange_adapter.py` — реализация `ExchangeAdapter` поверх ccxt.pro
- В конструктор: `exchange_name: str`, `api_key: str`, `api_secret: str`.
- Все методы async, оборачивают вызовы ccxt в `try/except` с retry и экспоненциальным backoff (`tenacity` или ручной).
- `create_order` — округлять size/price через `exchange.amount_to_precision` / `price_to_precision`.
- Нормализовать выходы CCXT в наши `Order`/`Balance`/`Candle` dataclasses (см. `src/domain/models.py`).

### 1.4 `ccxt_market_data.py` — реализация `MarketDataProvider`
- `subscribe(symbol, timeframe)` → `AsyncIterator[Candle]` через `exchange.watch_ohlcv` (ccxt.pro).
- При обрыве WS — реконнект с backoff, **не падать**.

### 1.5 `command_listener.py` — подписка на `engine.commands.*`
- Подписан на каналы из `src/application/events.py` (нужно завести там же константы `COMMAND_START`, `COMMAND_STOP`, `COMMAND_UPDATE` — синхронизировать с backend `domain/events.py`).
- На каждое сообщение: парс JSON, диспатч в зарегистрированный handler.
- Idempotency: хранить уже обработанные `command_id` в Redis (`SET engine:commands:processed:<id> 1 EX 86400`).
- Архитектурно: `CommandListener` владеет ссылкой на `EngineOrchestrator`, у которого есть `start_strategy(bot_id, config) / stop_strategy(bot_id) / update_params(bot_id, params)`.

### 1.6 `state_manager.py`
- Держит в памяти dict `bot_id → RunningStrategy` (`task: asyncio.Task`, конфиг, последний баланс).
- Каждые 5–10 секунд: snapshot в Redis (`SET engine:state:<bot_id> <json> EX 30`) — backend может читать.
- Раз в N секунд публиковать heartbeat в `engine.status`:
  ```json
  {"uptime": 1234, "active_bots": ["uuid1", "uuid2"]}
  ```

### 1.7 Публикация `engine.balance_update`
В `state_manager` (или в отдельном `BalancePoller`): раз в N секунд вызывать `adapter.fetch_balance()` для каждого активного бота и публиковать:
```json
{
  "credential_id": "<uuid>",
  "balances": {
    "USDT": {"free": "100.50", "used": "0", "total": "100.50"},
    "BTC":  {"free": "0.0012", "used": "0", "total": "0.0012"}
  }
}
```
Поле `credential_id` обязательно — backend без него не запишет (см. `backend/src/services/event_projector.py`).

### 1.8 `db_repositories.py` — чтение конфигов и кредов
Движок должен иметь доступ к таблицам `bots` и `exchange_credentials` (только чтение). Движок и бэкенд **разделяют одну БД**.
- `BotRepository.get(bot_id)` → конфиг.
- `CredentialRepository.get_decrypted(credential_id)` — расшифровка тем же Fernet-ключом (`BACKEND_ENCRYPTION_KEY`, передаётся движку через env как `ENGINE_ENCRYPTION_KEY` — то же значение).
- **Важно:** Fernet-ключ должен совпадать у бэкенда и движка, иначе расшифровка сломается. Это явно прописать в README и .env.example.

### 1.9 `src/__main__.py` — entrypoint
```python
async def main() -> None:
    settings = load_settings()
    configure_logging(...)
    redis = await create_redis(settings.redis_url)
    db = create_engine(settings.database_url)
    event_bus = RedisEventBus(redis)
    state = StateManager(redis, event_bus)
    orchestrator = EngineOrchestrator(state, db, event_bus, encryption_key=settings.encryption_key)
    listener = CommandListener(redis, orchestrator)
    async with asyncio.TaskGroup() as tg:
        tg.create_task(listener.run())
        tg.create_task(state.run())  # heartbeat + snapshot loop

if __name__ == "__main__":
    asyncio.run(main())
```
Перехватывать `SIGTERM`/`SIGINT` для graceful shutdown.

### 1.10 Стратегия-пример `strategies/sma_cross.py`
- Простая SMA Cross на pandas (или чистом Python).
- `on_candle(candle) -> Signal | None`.
- `startup_candle_count = max(sma_long_period, …)`.
- Используется как пример для тестов и фронтового selector'а.

### 1.11 `Dockerfile` для движка
По образцу `backend/Dockerfile` (multi-stage, non-root). Раскомментировать сервис `engine` в `docker-compose.yml`.

### 1.12 Тесты
- Юнит-тесты для каждого инфра-класса с `fakeredis` и `unittest.mock.AsyncMock` вместо CCXT.
- Контракт: тест, что константы каналов в движке = константы в бэке (зеркальный к существующему `backend/tests/unit/test_events_constants.py`).
- Интеграционный smoke: запустить движок и бэк против общих postgres/redis, опубликовать команду через бэк → убедиться, что движок «принял» (можно по логам).

### ✅ Готово, когда
- `python -m src` или `docker compose run --rm engine` стартует без ошибок.
- `redis-cli publish engine.commands.start '{...}'` → в логах движка появляется «strategy started».
- В bus летят `engine.status` каждые ~10 сек, `engine.balance_update` раз в N сек.
- Реальная свеча с Binance Testnet → сигнал стратегии → ордер на бирже (testnet) → событие `engine.new_trade` → запись в `orders` таблице бэка.

---

## Phase 2. Frontend: интеграция с бэкендом — `[FRONTEND]`

Текущий фронт — Figma-мок, без бэка. Нужно подружить.

### 2.1 API-клиент
Файлы:
- `frontend/src/api/client.ts` — обёртка над `fetch`, читает `import.meta.env.VITE_API_URL`, прокидывает заголовок `Authorization: Bearer <access>`.
- `frontend/src/api/auth.ts` — `register/login/refresh/me`.
- `frontend/src/api/credentials.ts` — CRUD `/api/exchange-credentials`.
- `frontend/src/api/bots.ts` — CRUD + `/start /stop /params`.
- `frontend/src/api/market.ts` — `/api/trades`, `/api/orders`, `/api/balances`.

Все DTO типизировать через TypeScript интерфейсы, точно соответствующие Pydantic-схемам бэка (`backend/src/api/schemas/`). Decimal приходит как `string` — не конвертировать в `number`, чтобы не терять точность; использовать `decimal.js` или хранить как строку.

### 2.2 Auth-store и protected routes
- `frontend/src/stores/auth.ts` (Zustand или Context) — хранение `access_token`, `refresh_token`, `user`. Persist в `localStorage`.
- Интерцептор в `api/client.ts`: на 401 → попытка `refresh` → повтор. Если refresh не удался — редирект на `/login`.
- `frontend/src/app/routes.tsx`: ProtectedRoute wrapper, новые роуты `/login` и `/register`.
- Страница логина — простая форма email/password, при успехе сохраняет токены и редиректит на `/`.

### 2.3 WebSocket-клиент
- `frontend/src/api/ws.ts` — подключение к `import.meta.env.VITE_WS_URL?token=<access>`.
- Класс `EventStream`:
  - `connect()` / `disconnect()`.
  - Авто-reconnect с backoff.
  - Обработка `{type: "ping"}` от сервера (можно игнорировать — pong не нужен).
  - Подписки: `on('new_trade', handler)`, `on('balance_update', handler)`, `on('strategy_error', handler)`.
- Подключение в lifecycle авторизованного приложения (после логина).

### 2.4 Заменить моки на реальные данные
В каждом виджете дашборда, в `RecentTradesWidget`, в страницах `Strategies/Trades/Logs/Settings`:
- Заменить хардкод на `useQuery` (React Query — добавить зависимость `@tanstack/react-query`).
- Список ботов: `GET /api/bots`.
- История сделок: `GET /api/trades?bot_id=<id>`.
- Баланс: `GET /api/balances?credential_id=<id>` + live-обновления из WS.
- Журнал ошибок: список из `GET /api/orders` (с фильтром по status=error) + WS-события `strategy_error`.

### 2.5 Страницы создания/редактирования бота
- `/strategies/new` → форма (выбор exchange credential, strategy_class, symbol, timeframe, params) → `POST /api/bots`.
- Кнопка «Start»/«Stop» на карточке бота → `POST /api/bots/{id}/start|stop`.
- Изменение параметров: `PATCH /api/bots/{id}/params`.

### 2.6 Страница API-ключей
- `/settings/credentials` (новая) → список + форма добавления (`POST /api/exchange-credentials` с api_key/api_secret).
- Учесть, что бэк валидирует ключи через CCXT — может медленно отвечать (несколько секунд). Спиннер обязателен.

### ✅ Готово, когда
- На `/login` можно залогиниться/зарегистрироваться, токен сохраняется.
- Дашборд показывает реальный список ботов залогиненного пользователя, а не мок.
- WebSocket подключается, и при `redis-cli publish engine.new_trade '...'` сделка появляется в UI в реальном времени.
- Можно создать бота, запустить его, увидеть «running» статус.

---

## Phase 3. Backend — мелкие доработки — `[BACKEND]`

### 3.1 Resolver бота для balance_update / strategy_error
Сейчас в `backend/src/services/event_projector.py` (см. метод `_resolve_bot_for_strategy`) поиск бота идёт по `strategy_class` через `LIMIT 1` — это **некорректно**, если у пользователя несколько ботов с одной стратегией. Надо передавать `bot_id` в каждом событии движка и резолвить по нему. Согласовать с [ENGINE 1.7]: payload `engine.new_trade` и `engine.strategy_error` должен содержать `"bot_id": "<uuid>"`.

### 3.2 Rate limiting
- Добавить `slowapi` (или внутренний middleware на Redis).
- Лимиты: `/auth/login` 5/мин на IP, `/api/bots/*/start` 30/мин на user.

### 3.3 Интеграционные тесты
- `backend/tests/integration/test_auth_flow.py` — register → login → /auth/me с реальным Postgres из CI service.
- `backend/tests/integration/test_pubsub_to_db.py` — публикуем эталонный payload `engine.new_trade` в Redis, ждём, проверяем запись в `orders`.
- `backend/tests/integration/test_ws_updates.py` — подключаемся через `httpx_ws` (или starlette `TestClient.websocket_connect`), публикуем событие — получаем broadcast.

### 3.4 Endpoint `/api/engine/status`
Читает `engine:state:<bot_id>` и `engine:heartbeat` из Redis (snapshot от `StateManager` движка). Отдаёт фронту «движок жив, активные боты: …».

### 3.5 Логирование request_id
Middleware: на входе создаёт `request_id`, кладёт в `structlog.contextvars`. Прокидывает в payload команд движку, чтобы можно было трассировать «фронт → бэк → движок».

### ✅ Готово, когда
- В CI зелёные integration-тесты.
- `pytest backend/tests` локально проходит с реальным Postgres+Redis.
- В логах видна сквозная цепочка `request_id` в команде движку.

---

## Phase 4. Деплой и боевой запуск — `[DEVOPS]`

### 4.1 Первый ручной деплой
На сервере (после Phase 0):
```bash
cd /docker/crypto-dashboard
docker compose pull
docker compose run --rm migrate
docker compose up -d
docker compose ps         # все unhealthy → разбираем
docker compose logs backend -f
```
Проверки:
- `curl http://localhost:8000/healthz` → 200, оба пинга `ok`.
- `curl http://localhost:5173/healthz` → 200 от nginx.

### 4.2 nginx reverse proxy + TLS
- На сервере уже должен быть `nginx` или `traefik` для всех сервисов в `/docker`.
- Прописать виртуальный хост `dashboard.example.com` → `crypto-frontend:80`, и `api.dashboard.example.com` → `crypto-backend:8000`.
- TLS через Let's Encrypt (`certbot --nginx`).
- В `.env` на сервере: `BACKEND_CORS_ORIGINS=https://dashboard.example.com`.

### 4.3 Автодеплой через push в main
- Один раз сделать тестовый коммит/PR в `main` корневого репо.
- В Actions проследить, что `deploy.yml` зелёный: build & push в GHCR → SSH-шаг → миграции → up.
- На сервере `docker compose ps` показывает обновлённые образы.

### 4.4 Backups Postgres
Уже-существующий postgres-контейнер должен иметь cron для `pg_dump` в смонтированный том. Если нет — настроить (sidecar контейнер или хост-cron).

### ✅ Готово, когда
- По `https://dashboard.example.com` открывается фронт, авторизация работает, реальный бот запускается и торгует на testnet.
- При push в `main` автоматически обновляются контейнеры на сервере.

---

## Phase 5. Безопасность и эксплуатация — `[DEVOPS] [BACKEND]`

- **Логи бэка/движка** — централизованно (loki / promtail или хотя бы `docker logs` + ротация).
- **Алерт на падение** — `engine.status` heartbeat не приходит N секунд → телега-уведомление (можно отдельный sidecar-скриптом).
- **Чистка истории движка от пароля** (`crypto-trade-engine`): в его репо `.context/CLAUDE.md` всё ещё содержит пароль сервера в открытом виде. Сделать `git filter-repo --replace-text` или просто отредактировать файл и **зарезать репо через rotate-secret** (поменять пароль сервера, поскольку он публично утёк). Это разовая задача безопасности.
- **mypy strict** в CI для backend и engine.

---

## Phase 6. UX-полировка (опционально) — `[FRONTEND]`

- Dark/Light темы (тоггл уже в UI, прикрутить к `next-themes`).
- Графики: сделки на свечном графике через `recharts` (уже в package.json).
- Бэктестинг — отдельная страница, отдельный endpoint на бэке (Phase 3+).
- i18n (ru/en) — `react-i18next`.

---

## Definition of Done — «система работает»

- [ ] Свежий клон с нуля + `git submodule update --init --recursive` + локальный `.env` + `docker compose -f ... -f docker-compose.dev.yml up` → всё стартует, healthcheck'и зелёные.
- [ ] Пользователь регистрируется на `/login`, добавляет credentials Binance Testnet, создаёт бота с SMA Cross, нажимает Start.
- [ ] Через 1–2 минуты в UI появляются realtime-обновления баланса и первая сделка (если рынок сгенерил сигнал) или хотя бы heartbeat `engine.status`.
- [ ] Логи бэка показывают подписку на `engine.*`; логи движка показывают подписку на `engine.commands.*`.
- [ ] Push в `main` → автодеплой на сервер → новый билд работает.
- [ ] `pytest` в обоих submodule зелёный (юнит + интеграция).
- [ ] В публичных репо **нет** реальных секретов; `grep -RIn -E "(password|08022005|31\.200|BEGIN PRIVATE)" .` пусто.

---

## Как работать с submodule (напоминание)

Изменения в submodule = два коммита:
1. Коммит в submodule-репо (`crypto-dashboard-backend` / `-frontend` / `crypto-trade-engine`) + push.
2. В корневом репо обновить указатель: `cd crypto-dashboard && git submodule update --remote <path>` → коммит и push.

Без второго шага другие разработчики и CI/CD не увидят твоих изменений.

Pull свежего состояния:
```bash
git pull --recurse-submodules
git submodule update --init --recursive
```
```

---

## Файлы, которые создаются в этой задаче

- [/Users/vadim_denisovich/Documents/Projects/crypto-dashboard/ROADMAP.md](/Users/vadim_denisovich/Documents/Projects/crypto-dashboard/ROADMAP.md) — единственный файл.

## Файлы, на которые ссылается ROADMAP (существующие)

- [README.md](/Users/vadim_denisovich/Documents/Projects/crypto-dashboard/README.md) — рядом, как и попросил пользователь.
- [docker-compose.yml](/Users/vadim_denisovich/Documents/Projects/crypto-dashboard/docker-compose.yml), [docker-compose.dev.yml](/Users/vadim_denisovich/Documents/Projects/crypto-dashboard/docker-compose.dev.yml)
- [.github/workflows/ci.yml](/Users/vadim_denisovich/Documents/Projects/crypto-dashboard/.github/workflows/ci.yml), [.github/workflows/deploy.yml](/Users/vadim_denisovich/Documents/Projects/crypto-dashboard/.github/workflows/deploy.yml)
- В submodule backend: `src/services/event_projector.py`, `src/api/schemas/`, `src/domain/events.py`.
- В submodule engine: `src/application/events.py`, `src/domain/interfaces.py`, `src/domain/models.py`.

## Что НЕ делается в этой задаче

- Никакого кода ни в одном из четырёх репозиториев.
- Никаких git-операций (это будет следующим шагом, после одобрения).
- Никаких изменений в README — ROADMAP ссылается на него, но не правит.
