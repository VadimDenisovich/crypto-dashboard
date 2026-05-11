# crypto-dashboard

Монорепо для платформы алгоритмической торговли криптой:
- **trade-engine-crypto** — асинхронный торговый движок (отдельный репо, подключён как git submodule).
- **backend** — FastAPI-шлюз между UI и движком (submodule).
- **frontend** — React + Vite SPA (submodule).

Движок и бэкенд — независимые процессы. Общаются исключительно через PostgreSQL и Redis Pub/Sub.

## Архитектура

```
        ┌────────────┐       HTTP/WS         ┌──────────────────┐
        │  Frontend  │ ───────────────────▶ │     Backend      │
        │  (React)   │ ◀─── WebSocket ──── │     (FastAPI)    │
        └────────────┘                       └──────┬───────────┘
                                                    │
                                ┌───────────────────┼───────────────────┐
                                │                   │                   │
                          PostgreSQL              Redis              ccxt
                          (история,              (Pub/Sub:           (валидация
                          пользователи,           engine.*           API-ключей
                          конфиги ботов)          каналы)            при добавлении)
                                ▲                   ▲
                                │                   │
                                └─────────┬─────────┘
                                          │
                                  ┌───────┴────────┐
                                  │  Trade Engine  │
                                  │   (asyncio)    │
                                  └───────┬────────┘
                                          │
                                       ccxt.pro
                                          │
                                  Binance / Bybit
```

**Контракт через Redis Pub/Sub** (имена каналов взяты из [trade-engine-crypto/src/application/events.py](trade-engine-crypto/src/application/events.py)):

| Канал | Направление | Назначение |
|---|---|---|
| `engine.new_trade` | engine → backend | исполненный ордер |
| `engine.balance_update` | engine → backend | снимок баланса |
| `engine.status` | engine → backend | heartbeat |
| `engine.strategy_error` | engine → backend | отказ риск-менеджера / сбой исполнения |
| `engine.commands.start` | backend → engine | старт стратегии |
| `engine.commands.stop` | backend → engine | стоп стратегии |
| `engine.commands.update` | backend → engine | обновить параметры |

## Структура

```
crypto-dashboard/
├── .context/                      # (локально, в .gitignore) правила для разработки
├── .github/workflows/             # CI/CD
│   ├── ci.yml                     # lint + tests + docker build
│   └── deploy.yml                 # push в GHCR + SSH deploy
├── trade-engine-crypto/           # SUBMODULE → crypto-trade-engine
├── backend/                       # SUBMODULE → crypto-dashboard-backend
│   ├── src/                       # FastAPI: api/, services/, repositories/, infrastructure/, models/
│   ├── alembic/                   # миграции
│   ├── tests/
│   ├── Dockerfile
│   └── pyproject.toml
├── frontend/                      # SUBMODULE → crypto-dashboard-frontend
│   ├── src/                       # React + MUI + Tailwind
│   ├── Dockerfile                 # nginx prod
│   └── Dockerfile.dev             # pnpm dev
├── docker-compose.yml             # прод: backend + frontend + migrate (без БД и Redis)
├── docker-compose.dev.yml         # override: добавляет локальные postgres + redis
├── .env.example                   # шаблон переменных окружения (без секретов)
└── README.md
```

## Локальный запуск

```bash
# 1. Клонировать с подмодулями
git clone --recurse-submodules https://github.com/VadimDenisovich/crypto-dashboard.git
cd crypto-dashboard

# 2. Подготовить .env
cp .env.example .env

# 3. Сгенерировать секреты и вставить в .env
python3 -c "import secrets; print('BACKEND_JWT_SECRET=' + secrets.token_urlsafe(64))"
python3 -c "from cryptography.fernet import Fernet; print('BACKEND_ENCRYPTION_KEY=' + Fernet.generate_key().decode())"

# 4. Поднять локалку (postgres + redis + backend + frontend)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

После запуска:
- Backend OpenAPI: http://localhost:8000/docs
- Healthcheck: http://localhost:8000/healthz
- Frontend: http://localhost:5173

## 🔑 Куда вставлять ключи

| Переменная | Где | Как сгенерировать / что вписать |
|---|---|---|
| `BACKEND_JWT_SECRET` | локально в `.env`, в проде — GitHub Secrets | `python3 -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `BACKEND_ENCRYPTION_KEY` | локально в `.env`, в проде — GitHub Secrets | `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `BACKEND_DATABASE_URL` | `.env` / Secrets | `postgresql+asyncpg://user:pass@host:5432/dbname` |
| `BACKEND_REDIS_URL` | `.env` / Secrets | `redis://host:6379/0` |
| `BACKEND_CORS_ORIGINS` | `.env` / Secrets | CSV списка доменов фронта, например `https://app.example.com` |
| API-ключи бирж пользователей | через POST `/api/exchange-credentials` | хранятся в БД зашифрованными (Fernet) |

**Никогда не коммить `.env`** — он закрыт `.gitignore`. Для прод-серверов значения хранятся в **GitHub Secrets** (см. ниже) и прокидываются в `docker compose` через `--env-file`.

### GitHub Secrets (для `deploy.yml`)

Зайди в репозиторий → **Settings → Secrets and variables → Actions** и добавь:

| Secret | Назначение |
|---|---|
| `DEPLOY_SSH_HOST` | IP/домен прод-сервера |
| `DEPLOY_SSH_PORT` | SSH-порт |
| `DEPLOY_SSH_USER` | пользователь на сервере |
| `DEPLOY_SSH_KEY` | приватный SSH-ключ (`ssh-keygen -t ed25519 -f deploy_key`; публичный — в `~/.ssh/authorized_keys` на сервере) |
| `DEPLOY_PATH` | путь до проекта на сервере, напр. `/docker/crypto-dashboard` |

Кроме того, на сервере в `${DEPLOY_PATH}/.env` должны лежать:
`BACKEND_DATABASE_URL`, `BACKEND_REDIS_URL`, `BACKEND_JWT_SECRET`, `BACKEND_ENCRYPTION_KEY`,
`BACKEND_CORS_ORIGINS`, `BACKEND_LOG_LEVEL`, `BACKEND_IMAGE`, `FRONTEND_IMAGE` — реальные значения.

## Миграции

Применить:
```bash
docker compose run --rm migrate
# или локально:
cd backend && alembic upgrade head
```

Создать новую ревизию:
```bash
cd backend && alembic revision --autogenerate -m "human readable description"
```

## CI/CD

- **`.github/workflows/ci.yml`** — на каждый push/PR: тесты бэка с реальной БД и Redis, билд фронта, проверочная сборка Docker-образов.
- **`.github/workflows/deploy.yml`** — на push в `main`: билд и push в GHCR (`ghcr.io/vadimdenisovich/crypto-dashboard-{backend,frontend}:latest` и `:<sha>`), затем SSH на прод-сервер → `git pull` → `docker compose pull` → миграции → `up -d`.

Чтобы CI прошёл проверки на новом форке/клоне, проследи, что submodules инициализированы (`actions/checkout@v4` с `submodules: recursive`).

## Деплой на сервер (первый раз)

На сервере:
```bash
mkdir -p /docker/crypto-dashboard && cd /docker/crypto-dashboard
git clone --recurse-submodules https://github.com/VadimDenisovich/crypto-dashboard.git .
cp .env.example .env && nano .env   # заполни прод-значения
# Залогинься в GHCR (для приватных образов; если пакеты публичные — пропустить):
echo $GITHUB_TOKEN | docker login ghcr.io -u $GITHUB_USER --password-stdin
docker compose pull
docker compose run --rm migrate
docker compose up -d
```

PostgreSQL и Redis на сервере поднимаются отдельным compose-проектом в том же томе `/docker`. Подключи backend к их сети одним из способов:
- внешняя docker network: раскомментировать блок `networks` в `docker-compose.yml` и проставить `DB_HOST`/`REDIS_HOST` равными именам тех контейнеров;
- через хост: `DB_HOST=host.docker.internal` (или конкретный IP) и пробросить порты на хосте.

## Контракт с движком (для разработчиков)

Канонические константы имён каналов и полей payload'а — в [trade-engine-crypto/src/application/events.py](trade-engine-crypto/src/application/events.py). На стороне бэкенда зеркалируются в [backend/src/domain/events.py](backend/src/domain/events.py). Любая правка с одной стороны = синхронная правка с другой; есть тест `tests/unit/test_events_constants.py`, который зафейлится, если константы разъедутся.

Все денежные значения в payload — строки (`"price": "42500.50"`), Decimal восстанавливается на стороне бэка. Подробнее — в локальной папке `.context/` (см. `backend-rules.md` и `trade-engine-rules.md`); эти файлы не коммитятся, чтобы не утащить никакие реквизиты в публичный репо.

## Дальнейшие шаги

- Реализовать в движке подписку на `engine.commands.*` и публикацию `engine.balance_update` / `engine.status` (сейчас движок их не публикует).
- Выровнять REST-эндпоинты под реальные вызовы фронта (фронт взят из открытого репо, его API-клиенты могут ожидать чуть иные пути).
- Добавить nginx + TLS для прод-фронта.
- Описать backup-стратегию для PostgreSQL.

## Сабмодули

| Путь | Репозиторий |
|---|---|
| `trade-engine-crypto/` | https://github.com/VadimDenisovich/crypto-trade-engine |
| `backend/` | https://github.com/VadimDenisovich/crypto-dashboard-backend |
| `frontend/` | https://github.com/VadimDenisovich/crypto-dashboard-frontend |

Фронт изначально взят из [4444urka/crypto-dashboard](https://github.com/4444urka/crypto-dashboard) (директория `frontend/`) и теперь живёт в собственном репозитории.
