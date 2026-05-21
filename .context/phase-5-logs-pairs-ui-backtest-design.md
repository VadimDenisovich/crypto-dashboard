# План правок: логи, ограничение пар, UI, бэктест-движок

> Статус: **реализовано** (ветка `feat/logs-pairs-ui-backtest` в корне; код submodule'ов
> на их `main`). Тесты: engine 125 passed, backend 28 passed, frontend `vite build` ok.

## Context

Дашборд состоит из трёх submodule-репозиториев: `backend` (FastAPI), `frontend`
(React + MUI + Vite), `trade-engine-crypto` (движок/бэктест). Нужно внести группу
правок по запросу пользователя:

1. **Логи** копятся только пока открыта страница `Logs` (WS подключается на mount,
   буфер — локальный state, теряется при уходе со страницы). Нужно собирать логи
   глобально пока пользователь онлайн, хранить в `localStorage` и чистить записи
   старше 12 часов.
2. **Торговые пары**: сейчас `/api/exchanges/{name}/symbols` отдаёт топ-10 по
   объёму. Нужно ограничить список до **BTC, SOL, XRP, BNB, ETH (к USDT)** для всех
   бирж — и в создании стратегии, и в бэктесте.
3. **Мелкий UI**: капча по ширине поля email; выпадающий список пар в бэктесте (как
   при создании стратегии); убрать строки «Backend/PostgreSQL/Redis OK» в виджете
   статуса; заменить кнопку «Выйти» на иконку двери.
4. **Бэктест-движок**: backend жёстко зашивает `exchange="binance"`, **игнорирует**
   `date_from`/`date_to` (гонит весь parquet целиком), а каталога `data/historical`
   нет — поэтому цифры не соответствуют выбранному периоду и выглядят «фиктивными».
   Нужно: выбор биржи; реальные исторические данные с реальной (не testnet) биржи;
   гибрид — сначала parquet-кэш, иначе дотягиваем через CCXT и сохраняем parquet на
   сервер; учёт диапазона дат.

Решения пользователя: источник данных — **гибрид (parquet + fallback CCXT, кэш в
parquet на сервере)**; хранение логов — **localStorage, чистка 12ч**.

---

## Часть 1. Логи: глобальный сбор + localStorage (12ч)

**Новый файл `frontend/src/app/LogsContext.tsx`** — провайдер, который:
- держит WS-соединение к `/ws/updates` живым всё время, пока есть access-token
  (логика `buildWsUrl`/reconnect переносится из `Logs.tsx`);
- хранит `lines` в state, синхронизирует с `localStorage` (ключ `crypto.logs.v1`);
  каждая запись имеет `time` (ISO) — на каждом append и по таймеру (раз в ~5 мин)
  отбрасываем записи старше **12 часов** (`Date.now() - t > 12*3600*1000`); общий
  кап ~2000 строк;
- при инициализации читает из `localStorage`, сразу прунит >12ч;
- отдаёт через context: `lines`, `wsState`, `paused`, `setPaused`, `clear()`.

**`frontend/src/app/components/Layout.tsx`** — обернуть содержимое (вокруг `Outlet`/
всего шелла) в `<LogsProvider>`. Layout рендерится только под `ProtectedRoute`, т.е.
провайдер живёт всю авторизованную сессию на любой странице и размонтируется при
выходе → логи копятся «пока пользователь в сети», а не только на странице логов.

**`frontend/src/app/pages/Logs.tsx`** — превратить в чистого потребителя контекста:
убрать `useEffect` с WS и локальный буфер; брать `lines/wsState/paused/clear` из
`useLogs()`. UI фильтров/паузы/очистки оставить как есть (кнопка «Очистить» зовёт
`clear()`, которая также чистит `localStorage`).

> Примечание: WS-сервер (`backend/.../ws.py`, `ws_manager.py`) менять не нужно —
> меняется только клиент.

---

## Часть 2. Ограничение торговых пар до 5 (все биржи)

**`backend/src/infrastructure/exchange_meta.py`** — добавить единый источник правды:
```python
ALLOWED_SYMBOLS: tuple[str, ...] = (
    "BTC/USDT", "SOL/USDT", "XRP/USDT", "BNB/USDT", "ETH/USDT",
)
```

**`backend/src/api/routers/exchanges.py`** — в `list_symbols` вернуть пересечение
`ALLOWED_SYMBOLS` с реальными `markets` биржи (сохраняя порядок allowlist); если
загрузка markets упала — отдать полный `ALLOWED_SYMBOLS` как fallback. Это убирает
зависимость от объёма/`fetch_tickers` (функцию `_fetch_top_symbols` упростить под
allowlist). Кэш в Redis оставить (ключ забамплен на `v2`).

**Frontend** — `CreateStrategy.tsx` уже строит дропдаун из `listExchangeSymbols`, так
что автоматически ограничится. `Backtesting.tsx` — см. Часть 4 (там пара станет
дропдауном из того же источника).

---

## Часть 3. Мелкий UI

1. **Капча по ширине email** — `frontend/src/app/components/auth/EmailCodeForm.tsx`:
   обёртку капчи (сейчас центрированный `Box` с `display:flex/justifyContent:center`
   и inline-границей) сделать `width: "100%"` без центрирования; Turnstile уже
   `size:"flexible"` → растянется по ширине контейнера = ширине поля email
   (оба внутри одного `Stack` с `fullWidth` TextField).

2. **Дропдаун пары в бэктесте** — реализуется в Части 4 (Autocomplete как в
   `CreateStrategy.tsx`, источник — `listExchangeSymbols(exchange)`).

3. **Убрать строки статуса** — `frontend/.../dashboard/EngineStatusWidget.tsx`:
   удалить блок `Stack` с тремя `HealthRow` (Backend/PostgreSQL/Redis) и сам компонент
   `HealthRow`. Верхний индикатор «Статус движка / Работает|Проблема» оставить
   (он считается по тем же `health*` переменным, их вычисление сохранить).

4. **Иконка двери вместо «Выйти»** — `frontend/.../layout/Header.tsx`: заменить
   `<Button startIcon={<Logout/>}>Выйти</Button>` на `<Tooltip title="Выйти"><IconButton
   color="inherit" onClick={logout} aria-label="Выйти"><Logout/></IconButton></Tooltip>`.
   Email пользователя рядом оставить.

---

## Часть 4. Бэктест: выбор биржи + реальные данные (гибрид) + диапазон дат

### 4.1 БД и схемы (backend)
- **`models/backtest_job.py`** — добавить колонку `exchange: Mapped[str]`
  (`String(32)`, `nullable=False`, `default="binance"`, `server_default="binance"`).
- **Новая миграция `backend/alembic/versions/0005_add_backtest_exchange.py`** —
  `add_column('backtest_jobs', Column('exchange', String(32), nullable=False,
  server_default='binance'))` (+ downgrade `drop_column`).
- **`api/schemas/backtest.py`** — `BacktestRunIn`: добавить `exchange: str`
  (валидируется `field_validator` против `SUPPORTED_EXCHANGES`, нормализуется в
  lowercase); `BacktestJobOut`/`BacktestJobSummaryOut`: добавить `exchange`.
- **`repositories/backtest_repo.py`** — `create(...)` принимает `exchange` и кладёт
  в модель.
- **`api/routers/backtest.py`** — `run_backtest` пробрасывает `body.exchange` в
  `repo.create(... exchange=...)`; невалидная биржа → 422 от pydantic.

### 4.2 Worker: биржа, путь кэша, диапазон дат (backend)
- **`services/backtest_worker.py`**:
  - `_resolve_parquet_path` → вернуть **канонический путь кэша**
    `{historical_dir}/{exchange}_{slug(symbol)}_{timeframe}.parquet` независимо от
    наличия файла (если есть существующий matching — берём его). Файл больше не
    обязателен заранее.
  - использовать `job.exchange` вместо хардкода `"binance"`.
  - `_build_config_payload` → добавить `exchange`, `date_from_ms`/`date_to_ms` в
    миллисекундах (`int(dt.timestamp()*1000)`), и `parquet_path` = канонический путь
    (целевой для записи кэша).
  - убрать ветку немедленного `mark_failed` при отсутствии parquet (теперь движок
    сам дотянет данные); ошибки сети/пустой выборки придут из движка как `{"error"}`.

### 4.3 Движок: гибридный источник + фильтр диапазона (trade-engine-crypto)
- **Новый `infrastructure/ccxt_historical.py`** — async `fetch_ohlcv_rows(exchange,
  symbol, timeframe, since_ms, until_ms) -> list[tuple]`: создаёт
  `ccxt.async_support.<exchange>({"enableRateLimit": True})` **без** `set_sandbox_mode`
  (реальная биржа), пагинирует `fetch_ohlcv(..., since, limit=1000)` до `until_ms`,
  возвращает строки `(ts_ms, o, h, l, c, v)` со строковыми Decimal. Плюс
  `save_parquet(path, rows)` — пишет/мёрджит parquet (`drop_duplicates` по timestamp,
  pandas импортируется лениво), создаёт каталог. Плюс `timeframe_ms(tf)`.
- **`infrastructure/csv_market_data.py`** — `CSVMarketDataProvider.__init__` принимает
  опциональные `start_ms`/`end_ms`; строки фильтруются по `[start_ms, end_ms]`.
  Это и есть «реальные цифры за выбранный период».
- **`backtest_main.py`** (`_run` + хелперы `_parquet_range`, `_ensure_market_data`):
  - читать `exchange`, `date_from_ms`/`date_to_ms`, `parquet_path` из конфига.
  - **гибрид**: если parquet существует и покрывает `[start,end]` (file_min ≤ start и
    file_max ≥ end−step) → `CSVMarketDataProvider(path, ..., start_ms, end_ms)`;
    иначе `fetch_ohlcv_rows(...)` → `save_parquet(...)` (кэш на сервере) → провайдер
    с фильтром. Пустая выборка → понятная ошибка (попадёт в `{"error"}` → failed).

### 4.4 Инфраструктура (mount под запись)
- **`docker-compose.yml`** — изменён `- ./data/historical:/data/historical:ro` на
  `- ./data/historical:/data/historical` (rw), чтобы движок мог писать parquet-кэш.
  Создан `data/historical/.gitkeep` (+ исключение в `.gitignore`:
  `data/historical/*` и `!data/historical/.gitkeep`).
- backtest_main выполняется как subprocess **в backend-контейнере** (PYTHONPATH на
  смонтированный движок); `pandas`/`pyarrow`/`ccxt` есть в backend-образе.

### 4.5 Frontend бэктеста
- **`api/backtest.ts`** — в `BacktestRunIn` добавить `exchange: string`;
  `BacktestJobOut`/`Summary` — `exchange`.
- **`pages/Backtesting.tsx`**:
  - `Select` «Биржа» из `listSupportedExchanges()` (дефолт первая/`binance`).
  - текстовое поле «Пара» заменено на `Autocomplete`, источник —
    `listExchangeSymbols(exchange)` (повторный фетч при смене биржи; `symbol`
    сбрасывается на первый доступный, если текущий отсутствует).
  - в `onSubmit` отправляется `exchange`.

---

## Git
Ветка **`feat/logs-pairs-ui-backtest`** — **только в корневом superproject**
`crypto-dashboard`. Submodule'ы (`backend`, `frontend`, `trade-engine-crypto`)
правятся на их `main`. Push/PR — по запросу (по умолчанию не пушим).

## Критичные файлы
- Логи: `frontend/src/app/LogsContext.tsx` (new), `components/Layout.tsx`, `pages/Logs.tsx`
- Пары: `backend/src/infrastructure/exchange_meta.py`, `api/routers/exchanges.py`
- UI: `auth/EmailCodeForm.tsx`, `dashboard/EngineStatusWidget.tsx`, `layout/Header.tsx`
- Бэктест backend: `models/backtest_job.py`, `alembic/versions/0005_*.py`,
  `api/schemas/backtest.py`, `repositories/backtest_repo.py`, `api/routers/backtest.py`,
  `services/backtest_worker.py`
- Бэктест движок: `infrastructure/ccxt_historical.py` (new),
  `infrastructure/csv_market_data.py`, `backtest_main.py`
- Инфра/фронт: `docker-compose.yml`, `.gitignore`, `data/historical/.gitkeep`,
  `frontend/src/api/backtest.ts`, `frontend/src/app/pages/Backtesting.tsx`

## Проверка (end-to-end)
1. **Логи**: залогиниться, побыть на Dashboard, затем открыть `Logs` — события,
   пришедшие до открытия страницы, уже видны. Перезагрузить вкладку — логи на месте.
   В DevTools → Application → localStorage есть `crypto.logs.v1`; вручную подложить
   запись с `time` >12ч назад и убедиться, что она отсеивается. «Очистить» опустошает
   и буфер, и localStorage. Выход (logout) → провайдер размонтирован.
2. **Пары**: открыть `/strategies/new` и `/backtesting` для каждой биржи — в дропдауне
   ровно BTC/SOL/XRP/BNB/ETH к USDT (минус отсутствующие на конкретной бирже).
3. **UI**: капча по ширине поля email; в виджете статуса нет строк Backend/PG/Redis;
   в шапке — иконка двери с тултипом «Выйти»; в бэктесте пара выбирается дропдауном.
4. **Бэктест**: применить миграцию (`docker compose run --rm migrate`). Запустить
   бэктест на разных биржах и узком диапазоне дат. Первый прогон: проверить, что в
   `data/historical/` появился `{exchange}_{base_quote}_{tf}.parquet`; второй прогон
   того же — берётся из кэша (быстрее). Метрики/equity/сделки соответствуют выбранному
   периоду. Тесты движка: `cd trade-engine-crypto && pytest tests/application/test_backtest_runner.py tests/infrastructure/test_csv_market_data.py`.
   Тесты backend: `cd backend && pytest`.
