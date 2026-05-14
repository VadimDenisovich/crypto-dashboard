# QUICKSTART — первый запуск торговли через UI

Этот гайд проводит от свежего клона / свежего деплоя до первой сделки на Binance Testnet через веб-интерфейс. Никаких seed-скриптов с захардкоженными ботами — всё конфигурируется через UI.

---

## A. На прод-сервере

Если у тебя уже развёрнут проект на сервере (через `deploy.yml`):

### 1. Убедись, что engine задеплоен

В обновлённом `deploy.yml` добавлен build & push образа `crypto-trade-engine`. Чтобы это применилось:

```bash
# В корне crypto-dashboard локально:
git add docker-compose.yml .github/workflows/deploy.yml
git commit -m "feat: add engine to deploy pipeline"
git push origin main
```

GitHub Actions соберёт `ghcr.io/<owner>/crypto-trade-engine:<sha>` и задеплоит на сервер.

На сервере проверь:
```bash
docker compose ps
# должен быть контейнер crypto-engine со status Up

docker compose logs engine | tail -20
# должны быть строки:  "engine_starting", "command_listener_started", "state_manager_started"
```

### 2. GitHub Secrets — проверка

Перед push'ом убедись, что в GitHub → Settings → Secrets → Actions есть **все**:

| Secret | Что в нём |
|---|---|
| `DEPLOY_SSH_HOST`, `DEPLOY_SSH_PORT`, `DEPLOY_SSH_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_PATH` | SSH-доступ к серверу |
| `BACKEND_DATABASE_URL` | `postgresql+asyncpg://...` |
| `BACKEND_REDIS_URL` | `redis://...` |
| `BACKEND_JWT_SECRET` | случайный токен (64+ символа) |
| `BACKEND_ENCRYPTION_KEY` | Fernet-ключ (44 символа base64, заканчивается `=`) |
| `BACKEND_CORS_ORIGINS` | URL фронта, например `https://dashboard.example.com` |
| `BACKEND_LOG_LEVEL` | `INFO` или `DEBUG` |

`ENGINE_DATABASE_URL`, `ENGINE_REDIS_URL`, `ENGINE_ENCRYPTION_KEY` **отдельно создавать не надо** — `deploy.yml` использует те же значения от backend секретов (движок шарит БД, Redis и Fernet-ключ с бэком).

### 3. Открой фронт

`https://<твой-домен>` или `https://<ip-сервера>:5173` (зависит от nginx настройки).

---

## B. Локально (Docker)

Если хочешь поднять всё локально для разработки:

```bash
# 1. Убедись, что .env заполнен (он в gitignored, уже создан с реальными ключами)
grep -E "^(BACKEND|ENGINE)_(JWT_SECRET|ENCRYPTION_KEY)" .env
# Должны быть длинные значения, не CHANGE_ME_GENERATE_LOCALLY
# ENGINE_ENCRYPTION_KEY ОБЯЗАН совпадать с BACKEND_ENCRYPTION_KEY

# 2. Поднять всё (Postgres + Redis + backend + engine + frontend):
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d

# 3. Проверить:
docker compose ps
curl http://localhost:8000/healthz   # → {"db":"ok","redis":"ok"}
docker compose logs engine | tail -20
```

Фронт будет на `http://localhost:5173`.

---

## C. Flow в UI: от регистрации до первой сделки

После того как фронт открылся (`/login`):

### Шаг 1 — Регистрация

1. Открой `/register` (или нажми «Зарегистрироваться» на странице логина).
2. Введи email и пароль (минимум 8 символов).
3. После регистрации тебя автоматически залогинит и перебросит на `/`.

> **Опциональная альтернатива на локалке:** запустить `python scripts/seed_dev_setup.py` — он создаст dev-пользователя `dev@local.test` / `dev-password-123` напрямую в БД, без UI. Удобно при повторных сбросах локальной БД. На проде не нужен.

### Шаг 2 — Добавить API ключи Binance Testnet

1. Возьми ключи: https://testnet.binance.vision/ → «Generate HMAC_SHA256 Key».
2. На фронте: **Настройки** (sidebar) → форма «Добавить ключ Binance Testnet».
3. Вставь **API Key** и **Secret Key**, нажми «Сохранить».
4. Бэк прогонит ключи через CCXT в **sandbox-режиме** (`set_sandbox_mode(True)`) и сделает `fetch_balance` для валидации. Это занимает 2–5 секунд.
5. Если ключи валидные — увидишь зелёный alert «Ключ проверен и сохранён», и запись появится в списке «Подключённые ключи». Бэк шифрует их Fernet'ом перед сохранением в БД.

Если что-то пошло не так:
- `authentication failed: ...` — ключи неверные или не от testnet (у production-ключа нельзя проверить sandbox).
- `network error: ...` — на сервере нет доступа к `testnet.binance.vision` (фаервол).
- `validation failed: ...` — другая ошибка CCXT, смотри детали в alert.

### Шаг 3 — Создать стратегию

1. **Стратегии** → «Создать стратегию» (правый верхний угол).
2. Форма:
   - **API-ключи** — выбери только что добавленные.
   - **Торговая пара** — `BTC/USDT` (или любая доступная на testnet).
   - **Таймфрейм** — `1m` для быстрых сигналов, `15m` для более редких.
   - **Тип стратегии** — `SmaCross` (пока только она в реестре движка).
   - **Параметры** (дефолты):
     - `fast_period=5` — короткая SMA
     - `slow_period=20` — длинная SMA
     - `order_size=0.001` — размер сделки в BTC (минимум для Binance)
3. Нажми **«Сохранить и запустить»** — фронт отправит `POST /api/bots`, потом `POST /api/bots/{id}/start`. Бэк опубликует команду `engine.commands.start` в Redis, движок её подхватит.

### Шаг 4 — Наблюдай

На странице **Стратегии**:
- Бот появился в списке со статусом `Запускается` → через 1–2 секунды `Активна`.
- Polling каждые 5 секунд автоматически обновляет статусы.

Что движок делает в этот момент:
1. Получает команду из Redis.
2. Читает конфиг бота из БД.
3. Расшифровывает API-ключи Fernet'ом.
4. Создаёт CCXT-адаптер с `set_sandbox_mode(True)`.
5. Догружает `slow_period` исторических свечей (для прогрева SMA).
6. Подписывается на live-свечи через `watch_ohlcv` (WebSocket).
7. На каждой свече вычисляет SMA, при пересечении публикует сигнал.
8. RiskManager проверяет, OrderExecutor создаёт ордер, публикует `engine.new_trade`.
9. Бэк подписан на `engine.new_trade` — пишет в таблицу `orders`.

### Шаг 5 — Проверить сделки

Когда стратегия даст сигнал и Binance исполнит ордер:
- На сервере: `docker compose exec postgres psql -U user -d crypto-db -c "SELECT id, symbol, side, status FROM orders ORDER BY created_at DESC LIMIT 5;"`
- Локально: то же самое.

В будущих фазах (3.x и далее) фронт будет получать эти сделки через WebSocket и показывать в реальном времени — пока проверять через БД.

---

## Troubleshooting

| Симптом | Причина | Решение |
|---|---|---|
| `/login` показывает «Не удалось войти» | Неверный email/пароль | Сначала зарегистрируйся на `/register` |
| Settings: «authentication failed» при сохранении ключа | Бэк проверяет ключ через CCXT sandbox — твой ключ невалиден или production | Используй ключи с **testnet.binance.vision**, не с binance.com |
| Settings: «network error» при сохранении ключа | На бэк-контейнере нет доступа к testnet.binance.vision | Проверь, что egress на 443 открыт |
| Бот создан, статус `Запускается` навсегда | Движок не подхватил команду — не подписан или упал | `docker compose logs engine` — ищи `credential_decrypt_failed` (ключи Fernet разные!) или ошибки соединения |
| Бот в `Ошибка` | См. `engine.strategy_error` в Redis или логах | `docker compose exec redis redis-cli SUBSCRIBE engine.strategy_error` |
| `engine` рестартится в цикле | Падает на старте, обычно плохой `.env` | `docker compose logs engine` покажет stacktrace pydantic settings |
| 0 subscribers при публикации команды | Engine-контейнер не запущен | `docker compose up -d engine` и подожди ~5 сек |
| Сделки нет ни через час | SMA не пересекается / нет средств | Поменяй параметры (`fast=3, slow=8`) или пополни testnet-баланс через testnet.binance.vision |

---

## Что важно понимать

- **Один Fernet-ключ для всего**. `BACKEND_ENCRYPTION_KEY` шифрует то, что движок потом расшифровывает через `ENGINE_ENCRYPTION_KEY`. Если значения разные — движок упадёт с `credential_decrypt_failed`.
- **Только testnet на Phase 1**. Бэк по умолчанию валидирует ключи в sandbox, движок всегда создаёт CCXT с `set_sandbox_mode(True)`. Production-режим — отдельная задача (Phase 4+).
- **Бот = одна стратегия на одной паре**. Можно создать несколько ботов, они будут крутиться параллельно в одном engine-процессе.
- **Минимальный размер ордера** для Binance BTC/USDT testnet — 0.0001 BTC по объёму или 5 USDT по notional. SMA Cross с `order_size=0.001` BTC (~$60 при цене 60k) проходит.
- **Кеш WebSocket-свечей** обновляется в реальном времени; для бэктестинга используется отдельный pipeline (Phase 7 в ROADMAP).
