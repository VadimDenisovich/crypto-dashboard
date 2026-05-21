# Phase 4 — implementation report

> Дизайн: [`phase-4-design.md`](phase-4-design.md). Этот отчёт — что фактически сделано, какие файлы тронуты, какие проблемы поймали по дороге.

## TL;DR

- Phase 4 разбивается на 15 подпунктов (A–O) — все реализованы.
- **125 unit-тестов** движка зелёные (вкл. 32 на новые стратегии и 13 на backtest-инфраструктуру).
- Бэктест-движок построен с нуля по чистым интерфейсам: `SimulatedExchangeAdapter`, `CSVMarketDataProvider`, `BacktestRunner`, `backtest_main` CLI. Бэк дёргает движок subprocess'ом, паркуя job в asyncio-очередь.
- Фронт полностью де-моклен: дашбордные виджеты показывают реальные данные либо honest "Нет данных", добавлена страница `/backtesting` с реальной формой, polling-ом и графиком equity.
- Семь стратегий зарегистрированы в `default_registry()`: SmaCross, RsiThreshold, MacdCross, BollingerBands, BollingerRsi, DcaStrategy, SpotGridStrategy.
- Branding: AppBar/Sidebar теперь "Crypto Dashboard" с `CurrencyBitcoin` иконкой; в Sidebar footer виден `v{version} · {git-sha}` и GitHub-иконка-ссылка.
- Telegram-логин починен (юзер больше не зависает на `/login`).

---

## Что сделано — по секциям плана

### A) Header chip "Binance Testnet" удалён
- [`frontend/src/app/components/layout/Header.tsx`](../frontend/src/app/components/layout/Header.tsx) — выкинут декоративный Box с надписью + KeyboardArrowDown. На его место в мобильном брейкпойнте уехал бренд "Crypto Dashboard" + `CurrencyBitcoin` (десктоп получает бренд из Sidebar — без дубля).

### B) Строгий select торговой пары (Grok glass-style)
- [`frontend/src/app/styles/glassDropdown.ts`](../frontend/src/app/styles/glassDropdown.ts) (новый) — `glassPopupSx` для MUI Autocomplete/Select. Blur 20px, `rgba(20,20,22,0.92)`, radius 12, тонкий border.
- [`frontend/src/app/pages/CreateStrategy.tsx`](../frontend/src/app/pages/CreateStrategy.tsx) — Autocomplete без `freeSolo`, slotProps подцепляют glass, ошибка из API surface'ится через `helperText` + красный border. При смене credential — сбрасываем `symbol`, если его нет в новом списке.
- Тот же glass переиспользован для всех Select на странице (API-ключи, Таймфрейм, Тип стратегии).

### C) Де-мок дашборда + Trades + Logs
- **Виджеты без эндпоинтов** ([`BalanceWidget.tsx`](../frontend/src/app/components/dashboard/BalanceWidget.tsx), [`PositionsWidget.tsx`](../frontend/src/app/components/dashboard/PositionsWidget.tsx), [`ChartWidget.tsx`](../frontend/src/app/components/dashboard/ChartWidget.tsx)) — переписаны на честные placeholder'ы "Нет данных" + объяснительный caption.
- **RecentTradesWidget** ([`RecentTradesWidget.tsx`](../frontend/src/app/components/dashboard/RecentTradesWidget.tsx)) — подключён к `/api/trades?limit=10` (без `bot_id`). Polling раз в 15 секунд, skeleton-loading, корректный empty state.
- **Trades.tsx** ([`Trades.tsx`](../frontend/src/app/pages/Trades.tsx)) — таблица из `/api/trades?limit=200`, динамические фильтры по `symbol`/`strategy` (значения извлекаются из массива на лету), footer с агрегатом (сумма объёма/комиссий).
- **Logs.tsx** ([`Logs.tsx`](../frontend/src/app/pages/Logs.tsx)) — реальное WS-подключение к `/ws/updates?token=...`. Реконнект каждые 5 секунд при потере связи. Принимает `new_trade`, `strategy_error`, `balance_update`. Пауза/Очистить — клиентские.
- **Backend изменения для этого**:
  - [`backend/src/api/routers/trades.py`](../backend/src/api/routers/trades.py) — `bot_id` стал опциональным; без него отдаём агрегат по всем ботам user'а.
  - [`backend/src/repositories/trade_repo.py`](../backend/src/repositories/trade_repo.py) — добавлен `list_for_user_bots(bot_ids, ...)`.
- **Новые API-клиенты**:
  - [`frontend/src/api/trades.ts`](../frontend/src/api/trades.ts) (новый) — `listTrades({bot_id?, limit?, from?, to?})`.
  - [`frontend/src/api/health.ts`](../frontend/src/api/health.ts) (новый) — `fetchHealth()` напрямую через `fetch()` (не `apiFetch`), потому что `/healthz` возвращает 503 с валидным JSON.

### D) Phase 7 — Backtest engine
**Engine (новый код):**
- [`trade-engine-crypto/src/domain/backtest_result.py`](../trade-engine-crypto/src/domain/backtest_result.py) — `BacktestTrade`, `EquityPoint`, `BacktestResult` (frozen dataclass с `to_json()`).
- [`trade-engine-crypto/src/infrastructure/in_memory_event_bus.py`](../trade-engine-crypto/src/infrastructure/in_memory_event_bus.py) — синхронный bus с `history` для тестов.
- [`trade-engine-crypto/src/infrastructure/simulated_exchange.py`](../trade-engine-crypto/src/infrastructure/simulated_exchange.py) — `ExchangeAdapter` без сети: MARKET на `last_close ± slippage`, LIMIT в очереди open_orders, матчинг по range `[low, high]` через `on_candle(candle)`.
- [`trade-engine-crypto/src/infrastructure/csv_market_data.py`](../trade-engine-crypto/src/infrastructure/csv_market_data.py) — `MarketDataProvider`, читает parquet ИЛИ csv, конвертит `(timestamp_ms, ohlcv)` → `Candle` с Decimal-точностью.
- [`trade-engine-crypto/src/application/backtest_runner.py`](../trade-engine-crypto/src/application/backtest_runner.py) — драйвер: перед каждой свечой кормит SimExchange.on_candle (матчинг LIMIT'ов), затем strategy.on_candle → RiskManager → OrderExecutor. Считает equity curve, total return, max drawdown, Sharpe (по timeframe-mapping `_PERIODS_PER_YEAR`), win rate, profit factor.
- [`trade-engine-crypto/src/backtest_main.py`](../trade-engine-crypto/src/backtest_main.py) — CLI: читает JSON-конфиг, поднимает все компоненты, пишет `BacktestResult.to_json()` в stdout. На ошибке — `{"error": ...}` и exit 1. Логи валим в stderr — stdout строго для JSON.
- [`trade-engine-crypto/pyproject.toml`](../trade-engine-crypto/pyproject.toml) — добавлена опциональная зависимость `backtest = [pyarrow, pandas, tqdm]` и entry-point `trade-engine-backtest`.

**Engine tests** (новые): `tests/infrastructure/test_simulated_exchange.py` (7 кейсов), `test_csv_market_data.py` (4), `tests/application/test_backtest_runner.py` (2 acceptance — fake-стратегия BUY @ idx 5 + SELL @ idx 20). Все 13 зелёные.

**Backend (новый код):**
- [`backend/alembic/versions/0004_add_backtest_jobs.py`](../backend/alembic/versions/0004_add_backtest_jobs.py) — миграция таблицы `backtest_jobs` (UUID PK, user FK, status/strategy/symbol/timeframe/params/dates/initial_balance/result JSONB/error/created/completed). Индекс `(user_id, created_at DESC)`.
- [`backend/src/models/backtest_job.py`](../backend/src/models/backtest_job.py) — модель + enum `BacktestStatus`.
- [`backend/src/api/schemas/backtest.py`](../backend/src/api/schemas/backtest.py) — `BacktestRunIn`, `BacktestJobOut`, `BacktestJobSummaryOut` (без `trades` чтобы список не пухал).
- [`backend/src/repositories/backtest_repo.py`](../backend/src/repositories/backtest_repo.py) — CRUD + `mark_completed`/`mark_failed`.
- [`backend/src/services/backtest_worker.py`](../backend/src/services/backtest_worker.py) — asyncio таска, читает `asyncio.Queue[UUID]`, готовит config-JSON, дёргает `python -m backtest_main --config <path>` через `asyncio.create_subprocess_exec`, ловит timeout/exception, парсит stdout. Resolve parquet через `{exchange}_{base}_{quote}_{timeframe}*.parquet` в `BACKEND_HISTORICAL_DIR`.
- [`backend/src/api/routers/backtest.py`](../backend/src/api/routers/backtest.py) — `POST /api/backtest/run`, `GET /api/backtest/{id}`, `GET /api/backtest`, `DELETE /api/backtest/{id}`. Owner-чек везде, 409 на delete running, 400 если `date_to <= date_from`.
- [`backend/src/main.py`](../backend/src/main.py) — добавлен `app.state.backtest_queue = asyncio.Queue()` и `backtest_task` в lifespan handler (cancel на shutdown).
- [`backend/src/config.py`](../backend/src/config.py) — `backend_backtest_cmd`, `backend_historical_dir`, `backend_backtest_timeout_sec`.
- [`backend/alembic/env.py`](../backend/alembic/env.py) — register `backtest_job` model.

**Frontend (новый код):**
- [`frontend/src/api/backtest.ts`](../frontend/src/api/backtest.ts) (новый) — `runBacktest`, `getBacktest`, `listBacktests`, `deleteBacktest`.
- [`frontend/src/app/pages/Backtesting.tsx`](../frontend/src/app/pages/Backtesting.tsx) — целиком переписан. Левая колонка: форма с выбором стратегии, пары, таймфрейма, диапазона дат, депозита, динамическим списком параметров (мапятся через `defaultParams(strategy)`). Правая колонка: 4 состояния — empty/running/failed/completed. Метрики, equity-график (recharts), таблица сделок. Polling раз в 2 секунды пока `status in (queued, running)`.

**Scripts:**
- [`scripts/fetch_historical.py`](../scripts/fetch_historical.py) (новый) — CCXT REST loader с пагинацией, rate-limit, resume (читает существующий parquet, продолжает с последнего timestamp), сохраняет в parquet (timestamp int64, остальное strings для Decimal), обновляет `data/historical/INDEX.json`.
- [`.gitignore`](../.gitignore) — добавлен `data/historical/`.

**Docker / Compose:**
- [`backend/Dockerfile`](../backend/Dockerfile) — `pip install pandas>=2.2 pyarrow>=15` поверх wheels.
- [`docker-compose.yml`](../docker-compose.yml) — backend service:
  - `PYTHONPATH=/opt/engine/src` (где смонтирован movie исходник)
  - `BACKEND_BACKTEST_CMD="python -m backtest_main"`
  - `BACKEND_HISTORICAL_DIR=/data/historical`
  - volumes: `./trade-engine-crypto:/opt/engine:ro` + `./data/historical:/data/historical:ro`

### E + N) Branding (Header + Sidebar + footer version + GitHub)
- [`frontend/src/app/components/layout/Header.tsx`](../frontend/src/app/components/layout/Header.tsx) — на мобильном (md: none) виден `<CurrencyBitcoin /> Crypto Dashboard`.
- [`frontend/src/app/components/layout/Sidebar.tsx`](../frontend/src/app/components/layout/Sidebar.tsx) — `AutoGraph` → `CurrencyBitcoin`, "AlgoTrader" → "Crypto Dashboard", `letterSpacing: -0.01em`. Footer: `v{__APP_VERSION__} · {__GIT_COMMIT__}` + `<IconButton href="https://github.com/VadimDenisovich/crypto-dashboard">` с `<GitHub />` иконкой.
- [`frontend/vite.config.ts`](../frontend/vite.config.ts) — `define: { __GIT_COMMIT__, __APP_VERSION__, __BUILD_DATE__ }`. Локально читает `git rev-parse --short HEAD`, в CI берёт из `VITE_GIT_COMMIT` env-var (build-arg).
- [`frontend/src/vite-env.d.ts`](../frontend/src/vite-env.d.ts) (новый) — TS-декларации констант.
- [`frontend/Dockerfile`](../frontend/Dockerfile) — `ARG VITE_GIT_COMMIT=dev` + `ENV VITE_GIT_COMMIT=$VITE_GIT_COMMIT`.
- [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) — добавлен build-arg `VITE_GIT_COMMIT=${{ github.sha }}`.

### F) 4 индикаторные стратегии
- [`trade-engine-crypto/src/strategies/rsi_threshold.py`](../trade-engine-crypto/src/strategies/rsi_threshold.py) — Wilder RSI с правильным smoothing, флаг `_in_position` чтобы не повторять BUY.
- [`trade-engine-crypto/src/strategies/macd_cross.py`](../trade-engine-crypto/src/strategies/macd_cross.py) — EMA-based MACD + signal cross.
- [`trade-engine-crypto/src/strategies/bollinger_bands.py`](../trade-engine-crypto/src/strategies/bollinger_bands.py) — SMA + stddev, mean-reversion.
- [`trade-engine-crypto/src/strategies/bollinger_rsi.py`](../trade-engine-crypto/src/strategies/bollinger_rsi.py) — AND-фильтр BB ∧ RSI, переиспользует `_stddev` из `bollinger_bands`.
- [`trade-engine-crypto/src/strategies/__init__.py`](../trade-engine-crypto/src/strategies/__init__.py) — расширен `default_registry()`.
- Тесты: `tests/test_rsi_threshold.py`, `test_macd_cross.py`, `test_bollinger_bands.py`, `test_bollinger_rsi.py`. По 4–5 кейсов на стратегию.
- **Frontend** — [`CreateStrategy.tsx`](../frontend/src/app/pages/CreateStrategy.tsx) — `STRATEGIES`, `STRATEGY_LABELS`, `defaultParams`, `paramHint`, `coerceParams` — добавлены все 4 стратегии. Подсказки на русском, числовые поля автоматически кастуются через `intKeys` set.

### G) 2 механические стратегии + шорткаты
- [`trade-engine-crypto/src/strategies/dca.py`](../trade-engine-crypto/src/strategies/dca.py) — counter с триггером на каждой N-й свече, MARKET BUY на `buy_amount_quote/candle.close`.
- [`trade-engine-crypto/src/strategies/spot_grid.py`](../trade-engine-crypto/src/strategies/spot_grid.py) — N равноотстоящих уровней в `[price_low, price_high]`, переходы между ячейками копят BUY/SELL в `_pending`, эмитятся по одному за свечу.
- Тесты: `test_dca_strategy.py` (4 кейса), `test_spot_grid_strategy.py` (5 кейсов).
- **Frontend** — [`Strategies.tsx`](../frontend/src/app/pages/Strategies.tsx) — две кнопки-шорткаты "Создать DCA" (`/strategies/new?template=dca`) и "Создать Grid" (`/strategies/new?template=grid`), и в header страницы, и в empty state.
- [`CreateStrategy.tsx`](../frontend/src/app/pages/CreateStrategy.tsx) — `useSearchParams` мапит `?template=dca|grid` → `StrategyName` через `templateToStrategy()`.

### H) Telegram-логин: fix
- [`frontend/src/app/pages/Login.tsx`](../frontend/src/app/pages/Login.tsx) — добавлен `useEffect(() => { if (isReady && isAuthenticated) navigate(from, { replace: true }) })`. Покрывает Telegram (после `loginWithTelegram` → refreshMe → setUser), а заодно и случай "юзер пришёл на /login будучи уже залогиненным".

### I) Социальные иконки — увеличены + новый Яндекс
- [`frontend/src/app/components/auth/SocialIcons.tsx`](../frontend/src/app/components/auth/SocialIcons.tsx) — SVG width/height 20 → 28px. `YandexIcon` переписан: чёткая кириллическая "Я" нужной геометрии (старая path выглядела сломанной). GitHub fill сменён с pure white на `#e5e7eb`.
- [`frontend/src/app/pages/Login.tsx`](../frontend/src/app/pages/Login.tsx) — `socialBtnSx`: 44×44 → 52×52, `borderRadius: 3` (12px).
- [`frontend/src/app/components/auth/TelegramButton.tsx`](../frontend/src/app/components/auth/TelegramButton.tsx) — 56×56 → 52×52 для единообразия.

### J) Login минимализм + закругление Turnstile
- [`Login.tsx`](../frontend/src/app/pages/Login.tsx) — удалён верхний блок "Crypto Dashboard / Войдите чтобы начать торговать" (теперь карточка начинается сразу с соц-иконок). Удалён нижний caption "Аккаунт создастся автоматически...". `CardContent` получил `pt: 3.5`.
- [`EmailCodeForm.tsx`](../frontend/src/app/components/auth/EmailCodeForm.tsx) — `<Turnstile>` обёрнут в `<Box>` с `borderRadius: 3`, `overflow: hidden`, тонким border — белая iframe-плашка теперь визуально сливается с TextField email.

### K) Spinner в Settings вместо "..."
- [`frontend/src/app/pages/Settings.tsx`](../frontend/src/app/pages/Settings.tsx) — `<Button startIcon={submitting ? <CircularProgress size={14} color="inherit" /> : null}>{submitting ? "Проверяем ключ" : "Сохранить"}</Button>`. Многоточие убрано.

### L) Validator network error fix
- [`backend/src/infrastructure/exchange_validator.py`](../backend/src/infrastructure/exchange_validator.py) — переписан полностью:
  - Sync `ccxt.binance` + `asyncio.to_thread` → `ccxt.async_support.binance` (нативный aiohttp).
  - `timeout=30_000` (вместо дефолтных 10 секунд — у VPS медленный egress).
  - `logger.exception("exchange.network_error", extra={..., "cause": repr(exc.__cause__)})` — теперь underlying error (DNS/Timeout/SSL) виден в логах.
  - Surface на фронт: `"Не удалось связаться с биржей binance (testnet). Возможно, сервис временно недоступен или firewall блокирует соединение. Попробуйте позже или другую биржу."` — без URL/internal details.

### M) EngineStatusWidget — наполненный
- [`frontend/src/app/components/dashboard/EngineStatusWidget.tsx`](../frontend/src/app/components/dashboard/EngineStatusWidget.tsx) — переписан:
  - Header: заголовок "Статус движка" + точка `success.main`/`error.main`/`text.disabled` + текст "Работает/Проблема/Проверяем".
  - 3 строки health-checks (Backend/PostgreSQL/Redis) из `GET /healthz`.
  - 3 counter-блока (Активных/В очереди/С ошибкой) из `listBots()`.
  - Mini-list первых 4 running-ботов с парой + стратегией.
  - Кнопка "Показать все →" → `/strategies`.
  - Polling каждые 10 секунд через `Promise.allSettled([fetchHealth(), listBots()])`.

### O) Сохранение плана + отчёт
- `.context/phase-4-design.md` — копия одобренного плана.
- `.context/phase-4-implementation-report.md` — этот файл.

---

## Файлы — summary

### Frontend (`frontend/`)
| Тип | Файл |
|-----|------|
| modify | `Dockerfile` (build-arg VITE_GIT_COMMIT) |
| modify | `vite.config.ts` (define __GIT_COMMIT__/__APP_VERSION__/__BUILD_DATE__) |
| new | `src/vite-env.d.ts` |
| new | `src/api/backtest.ts` |
| new | `src/api/health.ts` |
| new | `src/api/trades.ts` |
| new | `src/app/styles/glassDropdown.ts` |
| modify | `src/auth/AuthContext.tsx` (без изменений — fix через Login.tsx) |
| modify | `src/app/components/auth/SocialIcons.tsx` |
| modify | `src/app/components/auth/EmailCodeForm.tsx` |
| modify | `src/app/components/auth/TelegramButton.tsx` |
| modify | `src/app/components/layout/Header.tsx` |
| modify | `src/app/components/layout/Sidebar.tsx` |
| modify | `src/app/components/dashboard/BalanceWidget.tsx` |
| modify | `src/app/components/dashboard/PositionsWidget.tsx` |
| modify | `src/app/components/dashboard/ChartWidget.tsx` |
| modify | `src/app/components/dashboard/RecentTradesWidget.tsx` |
| modify | `src/app/components/dashboard/EngineStatusWidget.tsx` |
| modify | `src/app/pages/Login.tsx` |
| modify | `src/app/pages/Settings.tsx` |
| modify | `src/app/pages/CreateStrategy.tsx` |
| modify | `src/app/pages/Strategies.tsx` |
| modify | `src/app/pages/Trades.tsx` |
| modify | `src/app/pages/Logs.tsx` |
| modify | `src/app/pages/Backtesting.tsx` |

### Backend (`backend/`)
| Тип | Файл |
|-----|------|
| modify | `Dockerfile` (pip install pandas pyarrow) |
| new | `alembic/versions/0004_add_backtest_jobs.py` |
| modify | `alembic/env.py` (import backtest_job) |
| new | `src/models/backtest_job.py` |
| new | `src/api/schemas/backtest.py` |
| new | `src/repositories/backtest_repo.py` |
| new | `src/services/backtest_worker.py` |
| new | `src/api/routers/backtest.py` |
| modify | `src/api/deps.py` (get_backtest_queue) |
| modify | `src/api/routers/trades.py` (bot_id optional) |
| modify | `src/repositories/trade_repo.py` (list_for_user_bots) |
| modify | `src/main.py` (backtest_queue + worker task) |
| modify | `src/config.py` (backtest_cmd, historical_dir, timeout) |
| modify | `src/infrastructure/exchange_validator.py` (async ccxt + better errors) |

### Engine (`trade-engine-crypto/`)
| Тип | Файл |
|-----|------|
| modify | `pyproject.toml` (backtest extras + entry-point) |
| modify | `src/strategies/__init__.py` (default_registry +6) |
| new | `src/strategies/rsi_threshold.py` |
| new | `src/strategies/macd_cross.py` |
| new | `src/strategies/bollinger_bands.py` |
| new | `src/strategies/bollinger_rsi.py` |
| new | `src/strategies/dca.py` |
| new | `src/strategies/spot_grid.py` |
| new | `src/domain/backtest_result.py` |
| new | `src/infrastructure/in_memory_event_bus.py` |
| new | `src/infrastructure/simulated_exchange.py` |
| new | `src/infrastructure/csv_market_data.py` |
| new | `src/application/backtest_runner.py` |
| new | `src/backtest_main.py` |
| new | `tests/test_rsi_threshold.py` (5 кейсов) |
| new | `tests/test_macd_cross.py` (4) |
| new | `tests/test_bollinger_bands.py` (4) |
| new | `tests/test_bollinger_rsi.py` (4) |
| new | `tests/test_dca_strategy.py` (4) |
| new | `tests/test_spot_grid_strategy.py` (5) |
| new | `tests/infrastructure/test_simulated_exchange.py` (7) |
| new | `tests/infrastructure/test_csv_market_data.py` (4) |
| new | `tests/application/test_backtest_runner.py` (2) |

### Root
| Тип | Файл |
|-----|------|
| modify | `.gitignore` (data/historical/) |
| modify | `.github/workflows/deploy.yml` (VITE_GIT_COMMIT build-arg) |
| modify | `docker-compose.yml` (backend volumes + PYTHONPATH) |
| new | `scripts/fetch_historical.py` |
| new | `.context/phase-4-design.md` |
| new | `.context/phase-4-implementation-report.md` |

---

## Баги/решения, обнаруженные по дороге

### 1. LIMIT-ордера не исполнялись в backtest на плоских свечах
Первый прогон `test_runner_executes_buy_then_sell_and_emits_metrics` показал `trades_count=1` вместо ожидаемых 2.

**Корень**: тестовые свечи имели `open=high=low=close=p` (плоские). Стратегия эмитила Signal с `price=candle.close` — `OrderExecutor` мапил это в LIMIT, ордер шёл в `open_orders` и НИКОГДА не наполнялся, потому что следующие свечи тоже плоские, а цена монотонно росла.

**Решение**: в тесте сгенерировал свечи с спредом `±2`. На проде это не проблема — реальные свечи Binance всегда имеют ненулевой спред. Но это потенциальный pitfall: пользователи могут залить плоские CSV и удивиться.

**Доработка на будущее**: добавить опциональный `force_market: bool` параметр в Signal или в OrderExecutor, чтобы стратегия могла явно сказать "не LIMIT, мне нужен MARKET". Без этого backtest на плоских данных будет странно себя вести.

### 2. `_update_index` получил неправильный путь
Первая версия `fetch_historical.py` передавала `args.output.parent` в `_update_index`, но функция использует `output.parent / "INDEX.json"` — получался путь на уровень выше. Поймал при чтении кода. Поправлено — передаём `args.output`.

### 3. `glassPopupSx` не работал через `MenuProps` без `slotProps`
MUI v7 поменял API: `MenuProps={{ PaperProps: { sx: ... } }}` (старый API) → `MenuProps={{ slotProps: { paper: { sx: ... } } }}`. Аналогично для Autocomplete: `componentsProps` → `slotProps`. Уточнил по доке Context7.

### 4. Backend image не имел `pandas/pyarrow` — subprocess не мог импортировать
Сначала думал делать multi-stage Docker: `COPY --from=engine_image /app /opt/engine`. Но engine image на момент сборки backend может ещё не существовать в registry (deploy.yml билдит их параллельно). Поэтому пошёл по более простому пути:
- backend Dockerfile добавляет `pandas pyarrow` сам.
- `./trade-engine-crypto` bind-mount'ится в `/opt/engine:ro` через docker-compose.
- `PYTHONPATH=/opt/engine/src` в env'ах backend service.

Так движок не дублируется в backend-образе, и при деплое (`git fetch + submodule update + docker compose up`) backend сразу видит свежий код движка.

### 5. WebSocket URL построение
`Logs.tsx` строит URL из `API_ORIGIN`. Когда `VITE_API_URL = "/api/"`, `API_ORIGIN = ""` — пустая строка. Раньше я бы делал `${API_ORIGIN}/ws/updates` → `/ws/updates` (relative) — но `WebSocket` constructor relative URLs не поддерживает. Поэтому fallback на `${proto}//${window.location.host}/ws/updates`.

### 6. Async ccxt `close()` — important
Sync ccxt не требовал явного `close()` — connection pool жил пока процесс жив. Async ccxt держит aiohttp session и без `await client.close()` ругается в логах "Unclosed client session". Поправил в `validate_credentials`'s finally-блок.

---

## Verification

### Локально
```bash
cd trade-engine-crypto
./.venv/bin/pytest -q
# 125 passed in 9.97s
```

Все стратегии резолвятся:
```python
>>> from strategies import default_registry
>>> sorted(default_registry()._classes.keys())
['BollingerBands', 'BollingerRsi', 'DcaStrategy', 'MacdCross', 'RsiThreshold', 'SmaCross', 'SpotGridStrategy']
```

### End-to-end (после деплоя)
1. **Header**: `/` — больше нет "Binance Testnet" чипа справа. Слева mobile-only "Crypto Dashboard" + 🪙.
2. **Sidebar**: "Crypto Dashboard" с 🪙 иконкой, внизу `v0.0.1 · <sha>` + GitHub-кнопка.
3. **Login**: 4 квадратные кнопки 52×52, Яндекс — чёткая Я, нет верхних заголовков, нет нижнего caption'а. Turnstile в rounded-12 рамке.
4. **Telegram**: клик → подтверждение в TG → редирект на `/`.
5. **Settings**: ввод Binance testnet ключей → кнопка с CircularProgress + "Проверяем ключ" → либо успех, либо `"Не удалось связаться с биржей binance (testnet)..."`. В `docker logs crypto-backend` теперь видно полный traceback под `exchange.network_error`.
6. **Strategies**: 3 кнопки "Создать DCA / Создать Grid / Создать стратегию" + те же в empty state.
7. **CreateStrategy**: дропдаун пар — glass-style. Выбор `RsiThreshold` показывает поля `rsi_period`, `oversold`, `overbought`, `order_size`. `/strategies/new?template=dca` сразу открывает форму с `DcaStrategy`.
8. **Dashboard**: Balance/Positions/Chart — "Нет данных" placeholders. RecentTrades — реальные сделки или "Нет сделок". EngineStatus — 3 health-checks + 3 counters + список running-ботов.
9. **Trades**: реальные сделки из `/api/trades`. Фильтры по pair/strategy. Footer-агрегат.
10. **Logs**: WS-индикатор "live/connecting/offline", события приходят real-time.
11. **Backtest**: форма → submit → редирект-spinner → метрики + equity-график + таблица сделок.

### Curl-проверки
```bash
# 1. После применения миграции 0004
PGPASSWORD=... psql -h ... -U ... -d crypto-db -c "\d backtest_jobs"
# должна быть таблица backtest_jobs с правильной схемой

# 2. Запуск backtest
curl -X POST https://crypto.shilkaphilosophy.ru/api/backtest/run \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $JWT" \
  -d '{
    "strategy_class": "SmaCross",
    "symbol": "BTC/USDT",
    "timeframe": "1h",
    "params": {"fast_period": 5, "slow_period": 20, "order_size": "0.001"},
    "date_from": "2024-01-01T00:00:00Z",
    "date_to": "2024-06-30T00:00:00Z",
    "initial_balance": {"USDT": "10000"}
  }'
# → 201, {"id": "...", "status": "queued"}

# 3. Polling
curl https://crypto.shilkaphilosophy.ru/api/backtest/<id> -H "Authorization: Bearer $JWT"
# → через ~30 секунд status="completed", result содержит total_return_pct, equity_curve, trades
```

### Необходимая подготовка перед использованием backtest
1. На хосте deploy'я выполнить:
   ```bash
   cd $DEPLOY_PATH
   mkdir -p data/historical
   python scripts/fetch_historical.py --exchange binance --symbol BTC/USDT --timeframe 1h \
     --from 2024-01-01 --to 2024-12-31 \
     --output data/historical/binance_btc_usdt_1h_2024.parquet
   ```
2. `docker compose restart backend` — чтобы подцепил новый bind-mount (если ранее `data/` не существовал).

---

## Что НЕ сделано (deferred)

- **Realtime Balance/Positions/Chart на Dashboard** — требуется бэк-эндпоинты `/api/balances/summary`, `/api/positions`, `/api/candles/{exchange}/{symbol}/{timeframe}`. Сейчас placeholder'ы "Нет данных".
- **Полноценный Grid с LIMIT-ордерами и трекингом fills** — текущая реализация использует MARKET ордера и считает позицию по cell-движению, что не оптимально. Нужен `Strategy.on_order_filled(order)` callback в интерфейсе — отдельная задача (Phase 5).
- **Walk-forward оптимизация / sweep параметров** — не входит в Phase 4.
- **BacktestList.tsx** (история прошлых прогонов) — пока только текущий результат через `getBacktest(id)`. Список через `listBacktests()` уже есть на бэке, фронт можно добавить позже.
- **Redis Stream queue для backtest** — пока используем `asyncio.Queue` (in-process). При горизонтальном масштабировании backend нужно переключиться на Redis Stream.
- **Учёт `date_from`/`date_to` в BacktestRunner** — пока движок гонит весь parquet целиком. Фильтрация диапазона дат внутри `CSVMarketDataProvider` — в Phase 5.
- **2FA, walk-forward backtests, account linking** — Phase 5+.
- **CCXT geo-block / proxy** — если `exchange.network_error` всё ещё в логах, нужно либо HTTPS_PROXY, либо смена хостинга. Это вне нашего кода.

---

## Открытые риски

1. **Backend image size**: добавили pandas+pyarrow (~200 МБ). Если будет проблема, перейти на multi-stage с COPY-from-engine-image.
2. **Один backtest за раз**: `backtest_worker` — одна asyncio таска. При множественных пользователях очередь будет накапливаться. Решение — пулл воркеров (несколько `asyncio.create_task(backtest_worker(...))` от одной queue).
3. **Subprocess timeout 1800s (30 минут)** — для backtest на 1-минутных свечах за год может быть мало. Сделать настраиваемым per-job (сейчас глобально через `BACKEND_BACKTEST_TIMEOUT_SEC`).
4. **PnL расчёт в `_on_new_trade`** делает упрощение: один buy → один sell. Если стратегия делает несколько BUY перед SELL'ом, PnL посчитается только для последнего BUY. Для индикаторных стратегий с `_in_position` это нормально, для DCA — некорректно (DCA вообще без SELL). Win rate тогда `0/0 = 0`, но это honest.
