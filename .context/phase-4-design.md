# Phase 4 — UI cleanup + new strategies + Backtest engine (Phase 7) + auth/branding polish

## Context

После Phase 3 (Multi-exchange + Turnstile + Grok-Login) пора:

1. **Убрать декоративный чип "Binance Testnet"** в [Header.tsx](frontend/src/app/components/layout/Header.tsx:42-60) — он не функционален и сбивает с толку: у пользователя уже есть выбор биржи на уровне credentials.
2. **Превратить поле "Торговая пара"** на CreateStrategy из текстового `Autocomplete freeSolo` в **строгий select** с топ-N USDT-пар от выбранной биржи, оформленный в Grok-стиле (glass-morphism, soft-radius — как уже сделано для Login).
3. **Убрать все hardcoded-данные с фронта** (BalanceWidget, PositionsWidget, ChartWidget, RecentTradesWidget, EngineStatusWidget, Backtesting.tsx, Trades.tsx, Logs.tsx). Виджеты без API остаются с состоянием "Нет данных"; те, у которых API уже есть (Trades, Logs через WS) — подключаем к реальным эндпоинтам.
4. **Реализовать полный Phase 7 — бэктест-движок**: SimulatedExchangeAdapter, CSVMarketDataProvider, BacktestRunner, скрипт скачивания исторических данных, миграцию `backtest_jobs`, API `/api/backtest/*`, subprocess-воркер с отдельным Docker-контейнером `engine-backtest-worker`, фронт-страницу `/backtest` с формой и графиком equity. Архитектура движка уже к этому готова (`MarketDataProvider`, `ExchangeAdapter`, `Strategy` — это интерфейсы) — никакой ветки `if backtest_mode:` в боевом коде стратегий или Risk/Order слоях.
5. **Брендинг Header** — текст "Crypto Dashboard" слева в AppBar + иконка (вместо пустого пространства после удаления чипа Binance Testnet). Sidebar — переименовать `AlgoTrader` → `Crypto Dashboard` для консистентности, заменить иконку `AutoGraph` на более крипто-тематическую (`CurrencyBitcoin` из `@mui/icons-material` или `<img>` с favicon).
6. **Новые индикаторные стратегии**: RSI, MACD, Bollinger Bands, Bollinger Bands + RSI. Каждая — отдельный класс в `trade-engine-crypto/src/strategies/`, регистрация в `default_registry()`, отображение в CreateStrategy.tsx с подсказками параметров.
7. **Механические стратегии**: DCA (Dollar Cost Averaging) и Spot Grid Bot. На Strategies-странице — отдельные кнопки-шорткаты "Создать DCA" / "Создать Grid", которые открывают `/strategies/new?template=dca` (или `grid`) с предзаполненной формой.
8. **Фикс входа через Telegram** — после успешного `loginWithTelegramPayload` фронт остаётся на `/login` потому что в [Login.tsx](frontend/src/app/pages/Login.tsx) нет `useEffect`, наблюдающего за `isAuthenticated` (EmailCodeForm имеет собственный `onSuccess={navigate}`, а TelegramButton — нет). Добавить либо общий useEffect, либо `onSuccess` проп в TelegramButton.
9. **Социальные иконки** — увеличить SVG-иконки внутри кнопок (20 → 28px), кнопки сделать чуть крупнее (44 → 52px) с теми же rounded-corners, **переписать YandexIcon** с правильным логотипом ("Я" чётко в красном квадрате) — текущий выглядит сломанным.
10. **Минимализм Login** — убрать заголовок "Crypto Dashboard" + подзаголовок "Войдите, чтобы начать торговать" над иконками, убрать caption "Аккаунт создастся автоматически при первом входе." внизу. Карточка начинается сразу с ряда соц-иконок.
11. **Закругление плашки Turnstile** — обернуть `<Turnstile>` виджет в `<Box>` с `borderRadius: 12`, `overflow: "hidden"`, тонким border (как у `<TextField>` рядом) — чтобы белая iframe-плашка не торчала прямыми углами на фоне rounded grok-карточки.
12. **Spinner в Settings вместо троеточия** — пока идёт `createCredential` (там бэк делает `fetch_balance`), показывать `<CircularProgress size=14 color="inherit">` как `startIcon` и текст "Проверяем ключ" (без `...`). Аналогично в EmailCodeForm уже сделано.
13. **Network error при валидации ключей** — `network error: binance GET https://testnet.binance.vision/api/v3/exchangeInfo` ([backend/src/infrastructure/exchange_validator.py:67-68](backend/src/infrastructure/exchange_validator.py#L67-L68)). Корневая причина не видна из-за `f"network error: {exc}"` — ccxt прячет original cause. **Что делать:**
    - Логировать **full traceback** на бэке (`logger.exception(...)` + `repr(exc.__cause__)`) — нужно видеть реальный underlying error (DNSError vs ConnectionTimeout vs SSLError).
    - Увеличить `timeout: 30000` в ccxt config (по умолчанию 10s — может быть мало для VPS с медленным egress).
    - Перейти с **sync** `ccxt.binance` на **async** `ccxt.async_support.binance` — текущая обёртка `asyncio.to_thread(client.fetch_balance)` использует sync requests, который может тупить за блокирующим resolv.conf. Async-версия использует aiohttp, у которого DNS-resolver другой.
    - Диагностика на проде: `docker exec backend curl -v https://testnet.binance.vision/api/v3/exchangeInfo` — если curl тоже фейлит, проблема в network egress хоста (firewall / geo-block), и нужен HTTP-прокси или альтернативный endpoint.
    - Surface на фронт: вместо raw ccxt-сообщения отдавать понятное "Биржа недоступна с нашего сервера. Попробуйте позже или другую биржу.". Внутренние подробности — только в логи.
14. **EngineStatusWidget выглядит пустым** ([frontend/src/app/components/dashboard/EngineStatusWidget.tsx](frontend/src/app/components/dashboard/EngineStatusWidget.tsx)). После де-моков останутся только заголовок + 1 строка, что выглядит сиротливо в карточке `md=4`. Наполнить **реальными** данными:
    - Health-индикаторы (DB / Redis / Backend) из `GET /healthz` — три цветных точки с подписями.
    - Список активных стратегий: `listBots()` → фильтр `status === "running"` → первые 3-4 строки с парой + стратегией, + ссылка "Показать все →" на `/strategies`.
    - Заголовок остаётся "Статус движка".
    - Убрать хардкод `Uptime: 3ч 12м` (нет источника) — заменить на счётчик "Активных стратегий: N" + "В очереди: 0" (если есть `status === "starting"`).
15. **Версия в Sidebar + GitHub-иконка** — внизу Sidebar сейчас `v1.0.0-beta`. Сделать:
    - Auto-инъекция git short SHA через `vite.config.ts` (`define: { __GIT_COMMIT__: JSON.stringify(execSync("git rev-parse --short HEAD")) }`) — на каждый build версия обновляется автоматически от текущего коммита.
    - Отображение: `v0.0.1 · abc1234` (читаем `pkg.version` через Vite + commit hash).
    - Рядом — `<IconButton href="https://github.com/VadimDenisovich/crypto-dashboard" target="_blank" rel="noreferrer noopener">` с `<GitHub />` иконкой из `@mui/icons-material`. Open в новой вкладке.
16. **Сохранение плана + отчёт в `.context`** — после реализации скопировать этот план в `.context/phase-4-design.md` (как сделано для phase-1/2/3) и написать **детальный отчёт** `.context/phase-4-implementation-report.md` по образцу `phase-3-implementation-report.md`: что сделано, какие файлы изменены, какие тесты добавлены, какие проблемы решены, какие баги поймали и фиксили, как тестировали end-to-end.

Цель — закончить рефакторинг UI (никакого хардкода в проде), запустить Phase 7 (бэктест), починить Telegram и добавить два новых типа стратегий (индикаторные и механические).

---

## A) Удалить чип "Binance Testnet" — `[FRONTEND]`

**Файл:** [frontend/src/app/components/layout/Header.tsx](frontend/src/app/components/layout/Header.tsx)

- Удалить `<Box>` со строками 43–60 (содержит `Typography "Binance Testnet"` и `KeyboardArrowDown`).
- Убрать импорт `KeyboardArrowDown` из `@mui/icons-material` (после удаления он не используется в этом файле).
- `Stack direction="row" spacing={2}` на 42 остаётся; внутри теперь только блок с email + кнопкой "Выйти".

---

## B) Строгий select торговой пары в Grok-стиле — `[FRONTEND] [BACKEND]`

### B.1 Backend: увеличить лимит symbols endpoint до 30

**Файл:** `backend/src/api/routers/exchanges.py` (уже существует, см. Phase 3.4)

- Параметр `limit` уже принимается через query — оставляем 50 по умолчанию. На фронте отрезаем top-30.

### B.2 Frontend: переход на строгий Autocomplete

**Файл:** [frontend/src/app/pages/CreateStrategy.tsx](frontend/src/app/pages/CreateStrategy.tsx)

Линии 196–219:
- Убрать `freeSolo` → теперь только выбор из списка.
- Добавить состояние `symbolsError` (если API не отвечает — показать сообщение под полем).
- Поменять onChange: `onChange={(_e, v) => setSymbol(v ?? "")}` (без onInputChange, т.к. ручной ввод запрещён).
- При загрузке (`symbolsLoading`) — `loading` prop + `loadingText="Загружаем пары..."`.
- Если `topSymbols.length === 0` и нет ошибки — `noOptionsText="Сначала выберите биржу"`.
- `disableClearable` если `topSymbols.length > 0` (нельзя оставить поле пустым после выбора).
- Если `symbol` не в `topSymbols` после смены credential (например, пара не торгуется на новой бирже) — сбрасывать `setSymbol("")`.
- `componentsProps={{ paper: { sx: glassPopupSx } }}` — стиль поппера.
- `renderOption` с кастомным `<MenuItem>` с padding и hover (см. `glassMenuItemSx`).

### B.3 Frontend: Grok-style стили дропдауна

**Файл:** `frontend/src/app/styles/glassDropdown.ts` (новый, реэкспортируется из общего модуля)

```typescript
export const glassPopupSx: SxProps = {
  mt: 1,
  borderRadius: 3,                                  // 12px
  bgcolor: "rgba(20, 20, 22, 0.85)",
  backdropFilter: "blur(20px)",
  border: "1px solid rgba(255, 255, 255, 0.08)",
  boxShadow: "0 10px 40px rgba(0,0,0,0.4)",
  // Список и MenuItem'ы
  "& .MuiAutocomplete-listbox": {
    padding: 0.5,
    "& .MuiAutocomplete-option": {
      borderRadius: 2,
      padding: "10px 12px",
      fontSize: "0.875rem",
      "&[aria-selected='true']": { bgcolor: "rgba(255,255,255,0.08)" },
      "&.Mui-focused": { bgcolor: "rgba(255,255,255,0.05)" },
    },
  },
};
```

- Импортируем `glassPopupSx` в `CreateStrategy.tsx` и применяем через `slotProps.paper.sx`.
- В перспективе тот же стиль будет в `Backtest.tsx` форме (см. часть D.6).

### B.4 Чек, что endpoint реально работает

Симптом из скриншота — `helperText="например, BTC/USDT"` (`topSymbols.length === 0`). Проверить:
1. На фронте дёрнуть `GET /api/exchanges/binance/symbols` (devtools). Если 404 — добавить router в [backend/src/main.py:114](backend/src/main.py#L114) (он уже есть).
2. Если 200 + пустой массив — проверить Redis cache / CCXT load_markets. В DoD добавляем `curl /api/exchanges/binance/symbols | jq length` ≥ 30.

---

## C) Удалить mock-данные с фронта — `[FRONTEND]`

Принцип: **виджет без API остаётся, но показывает "Нет данных" / skeleton** (placeholder UX). Виджеты с API — подключаем к реальному.

### C.1 Dashboard — заглушки "Нет данных"

| Файл | Что меняем |
|---|---|
| [BalanceWidget.tsx](frontend/src/app/components/dashboard/BalanceWidget.tsx) | Удалить хардкод `12 345.67 USDT`, `+3.42%` и т.п. Заменить на `<Typography color="text.disabled">— USDT</Typography>` и блок "Нет данных" под заголовком. |
| [PositionsWidget.tsx](frontend/src/app/components/dashboard/PositionsWidget.tsx) | Удалить 2 хардкод-`TableRow` BTC/ETH. Вместо них `TableRow` с одной ячейкой `colSpan={3}` и текстом "Нет открытых позиций". |
| [ChartWidget.tsx](frontend/src/app/components/dashboard/ChartWidget.tsx) | Удалить `chartData = [...]`. Передавать в `<ComposedChart data={[]}>`. Вместо графика — `<Box>` с надписью "График появится, когда подключим источник свечей". Селект пары и таймфрейма оставляем как UI, но `disabled`. |
| [RecentTradesWidget.tsx](frontend/src/app/components/dashboard/RecentTradesWidget.tsx) | **Подключить к API**: `useEffect → listRecentTrades(limit=10)` из нового [frontend/src/api/trades.ts](frontend/src/api/trades.ts). Если `trades.length === 0` — "Нет сделок". (Эндпоинт `GET /api/trades` существует.) |
| [EngineStatusWidget.tsx](frontend/src/app/components/dashboard/EngineStatusWidget.tsx) | Удалить хардкод Uptime "3ч 12м" и "Активных стратегий: 2". Заменить uptime на "—". Подключить `активных стратегий` к `listBots()` (фильтр `status === "running"`). |

### C.2 Trades.tsx — подключить к /api/trades

**Файл:** [frontend/src/app/pages/Trades.tsx](frontend/src/app/pages/Trades.tsx)

- Удалить хардкод `tradesData = [...]` (строки 7–13).
- Добавить `useState<TradeOut[] | null>(null)` + `listTrades({pair, strategy, limit})`.
- Реализовать `frontend/src/api/trades.ts`: `listTrades({pair?, bot_id?, limit?, offset?})` → `apiFetch("/api/trades?...")`.
- Эндпоинт `GET /api/trades` — посмотреть [backend/src/api/routers/trades.py](backend/src/api/routers/trades.py); если фильтр по `pair` не поддерживается — фильтруем на фронте.
- Footer "Всего сделок / Общий объём / Комиссии" считаем из реально полученного массива.

### C.3 Logs.tsx — подключить к WS engine.errors

**Файл:** [frontend/src/app/pages/Logs.tsx](frontend/src/app/pages/Logs.tsx)

- Удалить `logLines = [...]`.
- Подписаться на WS `/api/ws/me` ([backend/src/api/routers/ws.py](backend/src/api/routers/ws.py)) — оттуда приходят `STRATEGY_ERROR` события.
- Состояние `useState<LogLine[]>([])`. Кнопка "Пауза" → флаг `paused`, новые записи не добавляем (но WS не разрываем). "Очистить" → `setLines([])`.
- Фильтры по уровню (INFO/WARNING/ERROR) — клиентские.
- Если соединение упало → переподключение через 5с (или используем существующий хук, если есть; искать `useWebSocket` / `wsClient.ts`).

### C.4 Backtesting.tsx — переписать целиком в часть D.6

Существующий [Backtesting.tsx](frontend/src/app/pages/Backtesting.tsx) с `equityData = [...]` будет полностью переписан в части D.6.

---

## D) Phase 7 — Бэктест-движок — `[ENGINE] [BACKEND] [FRONTEND]`

Архитектура (по [ROADMAP.md:386-615](ROADMAP.md#L386)):
```
Frontend  →  POST /api/backtest/run  →  Backend (создаёт backtest_jobs)
            ↓                             ↓ кладёт job_id в asyncio.Queue
            GET /api/backtest/{id}     BacktestWorker (asyncio task в бэке)
              poll until completed       ↓ subprocess: python -m backtest_main
                                         ↓
                                     engine: BacktestRunner.run()
                                       (SimulatedExchange + CSVProvider +
                                        Strategy + RiskManager + OrderExecutor)
                                         ↓
                                     stdout: BacktestResult JSON
                                         ↓
                                     Backend пишет result в БД
```

### D.1 Скачивание исторических данных — `[ENGINE] scripts/`

**Новый файл:** `scripts/fetch_historical.py` (репозиторий root).

CLI:
```bash
python scripts/fetch_historical.py \
    --exchange binance --symbol BTC/USDT --timeframe 1m \
    --from 2024-01-01 --to 2024-12-31 \
    --output data/historical/binance_btc_usdt_1m_2024.parquet
```

- Использует `ccxt.async_support.<exchange>().fetch_ohlcv(symbol, timeframe, since, limit=1000)` с пагинацией.
- Между запросами `await asyncio.sleep(exchange.rateLimit / 1000)`.
- Прогресс-бар через `tqdm` (опциональная зависимость).
- Resumable: если файл существует — продолжает с последнего timestamp.
- Формат parquet: колонки `timestamp (int64 ms), open/high/low/close/volume (string Decimal)`.
- В конце обновляет `data/historical/INDEX.json`: `[{exchange, symbol, timeframe, from, to, rows, path, fetched_at}, ...]`.
- `data/historical/` добавить в `.gitignore`.
- `data/historical/INDEX.json` тоже в `.gitignore` (его пересоздаёт fetch_historical).

### D.2 `SimulatedExchangeAdapter` — `[ENGINE]`

**Новый файл:** `trade-engine-crypto/src/infrastructure/simulated_exchange.py`

Реализует `domain.interfaces.ExchangeAdapter`:

```python
class SimulatedExchangeAdapter(ExchangeAdapter):
    def __init__(
        self,
        initial_balance: Mapping[str, Decimal],
        symbol: str,                              # для разбора base/quote
        fee_rate: Decimal = Decimal("0.001"),     # 0.1% taker
        slippage: Decimal = Decimal("0.0005"),    # 0.05%
        warmup_candles: list[Candle] | None = None,
    ) -> None: ...

    async def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None) -> list[Candle]:
        # отдаёт warmup_candles[:limit]

    async def create_order(self, symbol, side, type, size, price=None) -> Order:
        # MARKET: исполняется на self._last_close ± slippage
        # LIMIT: добавляется в self._open_orders, ждёт on_candle

    async def get_balance(self) -> Mapping[str, Balance]: ...

    async def close(self) -> None: ...

    # extras (не входят в интерфейс, использует BacktestRunner)
    def on_candle(self, candle: Candle) -> list[Order]:
        # обновляет self._last_close
        # для каждого open LIMIT: если candle.low <= price <= candle.high → исполнить
        # возвращает список свежезаполненных Order

    @property
    def filled_orders(self) -> list[Order]: ...
```

Списание баланса:
- BUY: `quote -= size * fill_price * (1 + fee)`, `base += size`
- SELL: `base -= size`, `quote += size * fill_price * (1 - fee)`
- Если баланс отрицательный → `OrderExecutionError("insufficient simulated balance")` (страховка; RiskManager должен ловить заранее).

### D.3 `CSVMarketDataProvider` — `[ENGINE]`

**Новый файл:** `trade-engine-crypto/src/infrastructure/csv_market_data.py`

```python
import pandas as pd
from pathlib import Path
from decimal import Decimal

class CSVMarketDataProvider(MarketDataProvider):
    def __init__(self, parquet_path: Path, symbol: str, timeframe: TimeFrame): ...

    def subscribe(self, symbol, timeframe) -> AsyncIterator[Candle]:
        # assert symbol/timeframe matches, иначе ValueError
        return self._iter()

    async def _iter(self) -> AsyncIterator[Candle]:
        df = pd.read_parquet(self._path)
        for row in df.itertuples(index=False):
            yield _to_candle(self._symbol, self._timeframe, row)
            await asyncio.sleep(0)   # yield control to event loop
```

Зависимости: `pyarrow>=15`, `pandas>=2.2`. Добавить в `trade-engine-crypto/pyproject.toml`:

```toml
[project.optional-dependencies]
backtest = ["pyarrow>=15", "pandas>=2.2", "tqdm>=4.66"]
```

### D.4 `BacktestRunner` + `BacktestResult` — `[ENGINE]`

**Новый файл:** `trade-engine-crypto/src/domain/backtest_result.py`

```python
@dataclass(frozen=True, slots=True)
class BacktestTrade:
    timestamp: datetime
    side: Side
    price: Decimal
    size: Decimal
    fee: Decimal
    pnl: Decimal | None  # для пары BUY→SELL

@dataclass(frozen=True, slots=True)
class EquityPoint:
    timestamp: datetime
    equity: Decimal

@dataclass(frozen=True, slots=True)
class BacktestResult:
    initial_balance: Mapping[str, Decimal]
    final_balance: Mapping[str, Decimal]
    total_return_pct: Decimal
    max_drawdown_pct: Decimal
    sharpe_ratio: Decimal | None
    trades_count: int
    win_rate: Decimal
    profit_factor: Decimal | None
    trades: list[BacktestTrade]
    equity_curve: list[EquityPoint]
```

**Новый файл:** `trade-engine-crypto/src/application/backtest_runner.py`

```python
class BacktestRunner:
    def __init__(
        self,
        strategy: Strategy,
        market_data: CSVMarketDataProvider,
        exchange: SimulatedExchangeAdapter,
        risk: RiskManager,
        executor: OrderExecutor,
        event_bus: InMemoryEventBus,
        equity_snapshot_every: int = 100,  # каждые N свечей
    ) -> None: ...

    async def run(self) -> BacktestResult:
        # 1. warmup strategy: вызовы on_candle на warmup_candles
        # 2. async for candle in market_data.subscribe(...):
        #       signal = strategy.on_candle(candle)
        #       if signal: risk → executor (как в StrategyRunner)
        #       exchange.on_candle(candle)   # match LIMIT, обновить last_close
        #       if i % equity_snapshot_every == 0: snapshot equity
        # 3. metrics()
        # 4. return BacktestResult
```

**Метрики** (по [ROADMAP.md:505-510](ROADMAP.md#L505)):
- `total_return_pct = (final_equity / initial_equity - 1) * 100`. Equity = `sum(balance_currency * last_price_in_quote)` (для USDT-кросса: `USDT + base * last_close`).
- `max_drawdown_pct` — по equity_curve, бегущий peak и trough.
- `sharpe_ratio = mean(returns) / std(returns) * sqrt(periods_per_year)`. `periods_per_year` мапится по `timeframe`: 1m→525600, 5m→105120, 15m→35040, 1h→8760, 4h→2190, 1d→365.
- `win_rate = winning_trades / total_trades`. Trade пара BUY→SELL даёт PnL.
- `profit_factor = sum(profits) / abs(sum(losses))` (None при `losses == 0`).

**InMemoryEventBus** для тестов и бэктеста — `trade-engine-crypto/src/infrastructure/in_memory_event_bus.py` (новый). Просто `dict[channel, list[handler]]` + `publish` синхронно вызывает handler-ы. Используется BacktestRunner для перехвата `engine.new_trade` и сохранения в `self._trades`.

### D.5 Engine CLI — `[ENGINE]`

**Новый файл:** `trade-engine-crypto/src/backtest_main.py`

```python
def main() -> None:
    # argparse --config <path-to-json>
    # config: {strategy, symbol, timeframe, params, parquet_path,
    #          initial_balance, fee_rate, slippage}
    # asyncio.run(BacktestRunner(...).run())
    # print(BacktestResult.to_json()) на stdout
    # exit 0
    # On error → JSON {"error": "..."} → stdout → exit 1
```

В `trade-engine-crypto/pyproject.toml`:
```toml
[project.scripts]
trade-engine = "engine_main:main"
trade-engine-backtest = "backtest_main:main"
```

Сериализация `BacktestResult` → JSON: пишем helper `backtest_result.to_json_dict()` — Decimal как string, datetime как ISO-8601.

### D.6 Backend: миграция + модель + API + воркер — `[BACKEND]`

**D.6.1 Миграция** `backend/alembic/versions/0004_add_backtest_jobs.py`:

```python
op.create_table(
    "backtest_jobs",
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    sa.Column("status", sa.String(16), nullable=False),  # queued | running | completed | failed
    sa.Column("strategy_class", sa.String(64), nullable=False),
    sa.Column("symbol", sa.String(32), nullable=False),
    sa.Column("timeframe", sa.String(8), nullable=False),
    sa.Column("params", postgresql.JSONB, nullable=False),
    sa.Column("date_from", sa.DateTime(timezone=True), nullable=False),
    sa.Column("date_to", sa.DateTime(timezone=True), nullable=False),
    sa.Column("initial_balance", postgresql.JSONB, nullable=False),
    sa.Column("result", postgresql.JSONB, nullable=True),
    sa.Column("error_message", sa.Text, nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
)
op.create_index("ix_backtest_jobs_user_created", "backtest_jobs", ["user_id", "created_at"], postgresql_using="btree")
```

**D.6.2 SQLAlchemy модель** `backend/src/models/backtest_job.py` — зеркало миграции, с enum-литералом `BacktestStatus`.

**D.6.3 Pydantic схемы** `backend/src/api/schemas/backtest.py`:
- `BacktestRunIn` — input для POST /run
- `BacktestJobOut` — full output
- `BacktestJobSummaryOut` — для списка (без `result.trades` чтобы JSON не пухал)

**D.6.4 Репозиторий** `backend/src/repositories/backtest_repo.py` — CRUD: `create`, `get`, `list_for_user`, `update_status`, `update_result`, `update_error`.

**D.6.5 Воркер** `backend/src/services/backtest_worker.py`:

```python
async def backtest_worker(
    queue: asyncio.Queue[uuid.UUID],
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    while True:
        job_id = await queue.get()
        try:
            await _run_one(job_id, session_factory, settings)
        except Exception as exc:
            logger.exception("backtest job failed", extra={"job_id": str(job_id)})
            await _mark_failed(job_id, session_factory, str(exc))

async def _run_one(job_id, session_factory, settings):
    # 1. status → running
    # 2. найти parquet через INDEX.json (или сразу качать через subprocess?)
    #    MVP: парсим data/historical/INDEX.json — если есть, путь известный
    #    если нет — пока возвращаем "no historical data, run fetch_historical.py"
    # 3. собрать config-json для backtest_main
    # 4. subprocess: `python -m backtest_main --config /tmp/<job_id>.json`
    #    через `asyncio.create_subprocess_exec`, timeout = 30 минут
    # 5. парсить stdout → BacktestResult
    # 6. status → completed, result → JSON
```

Стартует в `main.py` lifespan-handler:
```python
app.state.backtest_queue = asyncio.Queue()
backtest_task = asyncio.create_task(
    backtest_worker(app.state.backtest_queue, session_factory, settings),
    name="backtest-worker",
)
```

На shutdown — `cancel + gather`.

**D.6.6 API router** `backend/src/api/routers/backtest.py`:

```python
router = APIRouter(prefix="/api/backtest", tags=["backtest"])

@router.post("/run", response_model=BacktestJobOut, status_code=201)
async def run_backtest(body, user, db, queue): ...
# валидирует, создаёт row status=queued, await queue.put(job_id), возвращает row

@router.get("/{job_id}", response_model=BacktestJobOut)
async def get_backtest(job_id, user, db): ...
# only own

@router.get("", response_model=list[BacktestJobSummaryOut])
async def list_backtests(user, db, limit=20, offset=0): ...

@router.delete("/{job_id}", status_code=204)
async def delete_backtest(job_id, user, db): ...
# 409 если status=running
```

Регистрируем в `backend/src/main.py:create_app`: `app.include_router(backtest.router)`.

**D.6.7 Зависимости бэка** — никаких pandas/pyarrow в бэк-образе (subprocess изоляция). Только `asyncio.create_subprocess_exec`.

### D.7 Docker — отдельный контейнер `engine-backtest-worker`

**Новый файл:** `trade-engine-crypto/Dockerfile.backtest` (или `engine_backtest.Dockerfile`):

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[backtest]"
COPY src/ ./src/
ENV PYTHONPATH=/app/src
ENTRYPOINT ["python", "-m", "backtest_main"]
```

**Изменения в** `docker-compose.yml`:
- Новый сервис `engine-backtest-worker`:
  - `build: ./trade-engine-crypto -f Dockerfile.backtest`
  - `volumes: ./data/historical:/data/historical:ro` — read-only маунт
  - НЕТ `ports` — это утилита, бэк дёргает через subprocess
- **Но**: subprocess от бэка не запускает контейнер. Два варианта:
  - **(a) MVP**: бэк-контейнер сам содержит `[backtest]` зависимости и запускает `python -m backtest_main` локально. Тогда отдельный сервис не нужен. Простее, но бэк-образ +200 MB.
  - **(b) Production**: бэк дёргает `docker exec engine-backtest-worker python -m backtest_main` — тогда нужен docker-socket мaunt, что небезопасно. Альтернатива — Redis-очередь и engine-backtest-worker сам её читает (Phase 7.5+).

**Решение для Phase 7 MVP**: вариант **(a) с долей (b)**:
- backend-Dockerfile получает extra deps `[backtest]` (но через `engine-backtest-worker` image, см. ниже).
- В `docker-compose.yml`: бэк-сервис копирует `data/historical` volume.
- На самом деле — самое чистое: **отдельный image для бэка не нужен**, потому что subprocess `python -m backtest_main` запускается в том же контейнере что и бэк. Делаем shared base image со всем нужным.
- **Окончательно**: создаём `trade-engine-crypto/Dockerfile.backtest`, в backend Dockerfile добавляем `COPY --from=engine-backtest /app /opt/engine` и `PYTHONPATH=/opt/engine/src` для запуска subprocess.
- Альтернативно — пересобрать backend Dockerfile с двумя стадиями: `engine-backtest` со всеми deps, потом `backend` с `--from=engine-backtest` копированием. Тогда subprocess просто `python -m backtest_main`.

**Финальное решение** (избегаем сложности docker-in-docker): backend-образ при сборке делает `pip install -e /app/engine[backtest]`, где `/app/engine` — submodule. Это +200 MB к бэк-образу, но один процесс, один контейнер, всё работает. Phase 7.6 в ROADMAP это и называет "Альтернатива (проще для MVP)".

→ **Меняем** [backend/Dockerfile](backend/Dockerfile):
```dockerfile
COPY trade-engine-crypto /opt/engine
RUN pip install -e /opt/engine[backtest]
ENV ENGINE_BACKTEST_CMD="python -m backtest_main"
ENV ENGINE_HISTORICAL_DIR="/data/historical"
```

→ **Меняем** `docker-compose.yml`:
```yaml
backend:
  build:
    context: .
    dockerfile: backend/Dockerfile
  volumes:
    - ./data/historical:/data/historical:ro
```

(Submodule контекст: `context: .` нужен чтобы `COPY trade-engine-crypto` работал.)

### D.8 Frontend — страница бэктеста — `[FRONTEND]`

**Новый файл:** `frontend/src/api/backtest.ts`

```typescript
export interface BacktestRunRequest {
  strategy_class: string;
  symbol: string;
  timeframe: string;
  params: Record<string, unknown>;
  date_from: string;       // ISO-8601
  date_to: string;
  initial_balance: Record<string, string>;
}

export interface BacktestResult {
  total_return_pct: string;
  max_drawdown_pct: string;
  sharpe_ratio: string | null;
  trades_count: number;
  win_rate: string;
  profit_factor: string | null;
  equity_curve: { timestamp: string; equity: string }[];
  trades: BacktestTrade[];
}

export interface BacktestJob {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  strategy_class: string;
  symbol: string;
  timeframe: string;
  params: Record<string, unknown>;
  date_from: string;
  date_to: string;
  initial_balance: Record<string, string>;
  result: BacktestResult | null;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

export const runBacktest = (body): Promise<BacktestJob> => apiFetch("/api/backtest/run", { method: "POST", body });
export const getBacktest = (id): Promise<BacktestJob> => apiFetch(`/api/backtest/${id}`);
export const listBacktests = (): Promise<BacktestJob[]> => apiFetch("/api/backtest");
export const deleteBacktest = (id): Promise<void> => apiFetch(`/api/backtest/${id}`, { method: "DELETE" });
```

**Переписать целиком:** [frontend/src/app/pages/Backtesting.tsx](frontend/src/app/pages/Backtesting.tsx) → `Backtest.tsx` (переименовать, обновить роут в [routes.tsx](frontend/src/app/routes.tsx)).

Структура:
- **Левая колонка (форма)** — те же поля что в [CreateStrategy.tsx](frontend/src/app/pages/CreateStrategy.tsx), плюс:
  - Date range picker (`@mui/x-date-pickers` если есть, иначе 2 × `<TextField type="date">`)
  - Initial balance (USDT) — number input
  - Symbol — **строгий select** (тот же `glassPopupSx`!)
  - Strategy — select из STRATEGIES (`["SmaCross"]`)
  - Параметры стратегии — динамическая форма (как в CreateStrategy)
  - Кнопка "Запустить бэктест" → POST /api/backtest/run → редирект на `/backtest/{id}` (или показывает inline-результат)
- **Правая колонка (результаты)**:
  - Если нет активного `job_id` или `bots.length === 0` — empty state: "Запустите бэктест слева"
  - Если есть `job_id` и `status in (queued, running)` — `<CircularProgress>` + "Идёт прогон..."
  - Если `status === "completed"` — равномерно как сейчас в mock-варианте: метрики + equity-график через `recharts.LineChart`
  - Если `status === "failed"` — `<Alert severity="error">{error_message}</Alert>`
- **Polling** `getBacktest(id)` каждые 2 секунды через `setInterval` в `useEffect`, очищается на размонтировании или completion.

**Новая страница:** `frontend/src/app/pages/BacktestList.tsx` — список прошлых прогонов (linked в Sidebar). Опционально для Phase 7.7 — если успеется.

### D.9 Тесты — `[ENGINE] [BACKEND]`

**Engine** (`trade-engine-crypto/tests/`):
- `tests/unit/test_simulated_exchange.py`:
  - MARKET BUY с достаточным балансом → правильное списание quote, добавление base, fee учтён, slippage применён
  - MARKET SELL — наоборот
  - LIMIT BUY → ордер в open_orders, на свече с low ≤ price → FILLED
  - LIMIT SELL → аналогично с high ≥ price
  - Insufficient balance → `OrderExecutionError`
- `tests/unit/test_csv_market_data.py`:
  - Чтение валидного parquet → правильный порядок Candle
  - Невалидный путь → `FileNotFoundError`
  - Mismatch symbol → `ValueError`
- `tests/unit/test_backtest_runner.py`:
  - Фейковая стратегия: BUY на свече 10, SELL на свече 20. История 100 свечей с известными ценами.
  - Проверяем `trades_count == 2`, `win_rate`, `total_return_pct` — точное значение по формуле.
  - Проверяем `equity_curve` имеет N точек.

**Backend** (`backend/tests/integration/`):
- `test_backtest_api.py`:
  - POST /api/backtest/run → 201, status="queued", row в БД
  - GET /api/backtest/{id} → 200, owned-by-user проверка
  - GET /api/backtest → list только своих
  - DELETE /api/backtest/{id} → 204, потом 404
  - DELETE при status=running → 409
- `test_backtest_worker.py` (с моком subprocess'а):
  - Воркер берёт job из queue, дёргает subprocess (`AsyncMock`), парсит JSON → пишет result
  - При ошибке subprocess → status="failed", error_message

---

## E) Брендинг Header + Sidebar — `[FRONTEND]`

### E.1 Header — добавить заголовок и иконку

**Файл:** [frontend/src/app/components/layout/Header.tsx](frontend/src/app/components/layout/Header.tsx)

После удаления чипа "Binance Testnet" (часть A), в левой части AppBar (после burger-IconButton) добавить:

```tsx
<Stack direction="row" alignItems="center" spacing={1.25} sx={{ display: { md: "none" } }}>
  {/* Только на мобиле — на десктопе бренд в Sidebar */}
  <CurrencyBitcoin sx={{ fontSize: 22, color: "primary.main" }} />
  <Typography variant="h6" fontWeight={600} sx={{ letterSpacing: "-0.01em" }}>
    Crypto Dashboard
  </Typography>
</Stack>
```

(На десктопе Sidebar остаётся видимым и содержит бренд — дубликат в Header не нужен.)

Импорт `CurrencyBitcoin` из `@mui/icons-material`.

### E.2 Sidebar — переименовать + сменить иконку

**Файл:** [frontend/src/app/components/layout/Sidebar.tsx](frontend/src/app/components/layout/Sidebar.tsx)

Строка 50: `AlgoTrader` → `Crypto Dashboard`.
Строка 42: `<AutoGraph color="primary" sx={{ fontSize: 28 }} />` → `<CurrencyBitcoin color="primary" sx={{ fontSize: 28 }} />`.

Импорт: убрать `AutoGraph` из деструктуризации (если он не используется в navItems — в navItems он есть как иконка для "Стратегии", так что **оставляем импорт**, меняем только иконку бренда).

---

## F) Новые индикаторные стратегии — `[ENGINE] [FRONTEND]`

### F.1 Engine — реализация четырёх стратегий

Шаблон каждой стратегии — `domain.interfaces.Strategy` с `on_candle(candle) -> Signal | None`.

**Файл:** `trade-engine-crypto/src/strategies/rsi_threshold.py`

```python
class RsiThreshold(Strategy):
    """RSI mean-reversion: buy when RSI < oversold, sell when RSI > overbought."""

    def __init__(
        self,
        symbol: str,
        timeframe: TimeFrame,
        rsi_period: int = 14,
        oversold: Decimal = Decimal("30"),
        overbought: Decimal = Decimal("70"),
        order_size: Decimal | str = Decimal("0.001"),
    ) -> None:
        # validation + state
        self.startup_candle_count = rsi_period + 1
        self._closes: deque[Decimal] = deque(maxlen=rsi_period + 1)
        self._position_open = False  # упрощённо: либо в позиции, либо нет

    def on_candle(self, candle: Candle) -> Signal | None:
        self._closes.append(candle.close)
        if len(self._closes) < self.rsi_period + 1:
            return None
        rsi = _compute_rsi(list(self._closes), self.rsi_period)
        if rsi < self.oversold and not self._position_open:
            self._position_open = True
            return Signal(self.name, self.symbol, Side.BUY, self.order_size, price=None)
        if rsi > self.overbought and self._position_open:
            self._position_open = False
            return Signal(self.name, self.symbol, Side.SELL, self.order_size, price=None)
        return None
```

Helper `_compute_rsi(closes: list[Decimal], period: int) -> Decimal` — стандартная Wilder-RSI формула.

**Файл:** `trade-engine-crypto/src/strategies/macd_cross.py`
```python
class MacdCross(Strategy):
    """MACD crossover: BUY on MACD crossing above signal, SELL on cross below."""
    def __init__(self, symbol, timeframe, fast_period=12, slow_period=26, signal_period=9, order_size=Decimal("0.001")): ...
    # EMA-based, startup_candle_count = slow_period + signal_period
```

**Файл:** `trade-engine-crypto/src/strategies/bollinger_bands.py`
```python
class BollingerBands(Strategy):
    """Mean-reversion BB: BUY when close < lower band, SELL when close > upper band."""
    def __init__(self, symbol, timeframe, period=20, num_std=Decimal("2.0"), order_size=Decimal("0.001")): ...
```

**Файл:** `trade-engine-crypto/src/strategies/bollinger_rsi.py`
```python
class BollingerRsi(Strategy):
    """BB + RSI confirmation: BUY когда close < BB lower И RSI < oversold;
    SELL когда close > BB upper И RSI > overbought.
    """
    def __init__(self, symbol, timeframe, bb_period=20, bb_std=Decimal("2.0"),
                 rsi_period=14, oversold=Decimal("30"), overbought=Decimal("70"),
                 order_size=Decimal("0.001")): ...
```

**Регистрация:** [trade-engine-crypto/src/strategies/__init__.py](trade-engine-crypto/src/strategies/__init__.py):

```python
def default_registry() -> StrategyRegistry:
    reg = StrategyRegistry()
    reg.register("SmaCross", SmaCross)
    reg.register("RsiThreshold", RsiThreshold)
    reg.register("MacdCross", MacdCross)
    reg.register("BollingerBands", BollingerBands)
    reg.register("BollingerRsi", BollingerRsi)
    return reg
```

### F.2 Engine — тесты на каждую стратегию

Файлы `trade-engine-crypto/tests/unit/test_<strategy>.py` — каждая:
- Warmup на N свечах → `on_candle` возвращает None
- Конкретный сценарий cross/threshold → `on_candle` возвращает корректный Signal
- После открытия позиции → отсутствие повторного BUY до закрытия

### F.3 Frontend — расширить CreateStrategy

**Файл:** [frontend/src/app/pages/CreateStrategy.tsx](frontend/src/app/pages/CreateStrategy.tsx) — строки 31, 37–46, 48–56, 59–68.

- `STRATEGIES` → `["SmaCross", "RsiThreshold", "MacdCross", "BollingerBands", "BollingerRsi"] as const`.
- Добавить в `defaultParams(strategy)`:
  - `RsiThreshold`: `{ rsi_period: "14", oversold: "30", overbought: "70", order_size: "0.001" }`
  - `MacdCross`: `{ fast_period: "12", slow_period: "26", signal_period: "9", order_size: "0.001" }`
  - `BollingerBands`: `{ period: "20", num_std: "2.0", order_size: "0.001" }`
  - `BollingerRsi`: `{ bb_period: "20", bb_std: "2.0", rsi_period: "14", oversold: "30", overbought: "70", order_size: "0.001" }`
- Добавить в `paramHint` подсказки на русском по каждому параметру.
- Добавить в `coerceParams` правильную типизацию (числа vs строки-Decimal: `period`/`num_std` — Number, `order_size`/`oversold` если Decimal — оставить string).
- Дисплей-имена для select: можно мапить через `STRATEGY_LABELS: Record<string, string>` (`SmaCross → "SMA Cross"`, `RsiThreshold → "RSI порог"`, etc.).

---

## G) Механические стратегии: DCA + Grid + шорткаты — `[ENGINE] [FRONTEND]`

### G.1 Engine — DCA

**Файл:** `trade-engine-crypto/src/strategies/dca.py`

```python
class DcaStrategy(Strategy):
    """Покупка фиксированной суммы quote-валюты каждые N свечей.

    Простейший DCA: чистый BUY каждые `interval_candles`. Не закрывает позицию —
    стратегия накопления. Пользователь продаёт вручную через UI или другой бот.
    """
    def __init__(
        self,
        symbol: str,
        timeframe: TimeFrame,
        buy_amount_quote: Decimal | str = Decimal("10"),  # сколько USDT за раз
        interval_candles: int = 24,                        # на 1h timeframe → раз в сутки
    ) -> None:
        # validation
        self._counter = 0

    def on_candle(self, candle: Candle) -> Signal | None:
        self._counter += 1
        if self._counter < self.interval_candles:
            return None
        self._counter = 0
        # size = quote / current_close (MARKET BUY на сумму buy_amount_quote)
        size = self.buy_amount_quote / candle.close
        return Signal(self.name, self.symbol, Side.BUY, size=size, price=None)
```

### G.2 Engine — Spot Grid

**Файл:** `trade-engine-crypto/src/strategies/spot_grid.py`

```python
class SpotGridStrategy(Strategy):
    """Спотовый grid bot: симметричная сетка вокруг текущей цены.

    Алгоритм:
    - При старте определяем grid levels: N равноотстоящих уровней в [price_low, price_high].
    - На каждой свече определяем "текущую ячейку" (между какими уровнями close).
    - Если ячейка изменилась относительно прошлой — генерируем signal:
        * Если цена упала на K ячеек → K BUY (одна за раз — strategy stateful: emit one per candle, остальные накопятся).
        * Если цена поднялась на K ячеек → K SELL.
    - Размер каждого ордера = base_per_level (фикс. в базовой валюте).

    Упрощения для MVP:
    - Только MARKET ордера (не LIMIT) — RiskManager их одобрит при наличии баланса.
    - Не отслеживаем individual fills — Strategy не имеет такого callback'а.
    - Если баланс кончился, ExchangeAdapter вернёт OrderExecutionError — стратегия логирует и продолжает.
    """
    def __init__(
        self,
        symbol: str,
        timeframe: TimeFrame,
        price_low: Decimal | str,
        price_high: Decimal | str,
        num_levels: int = 10,
        base_per_level: Decimal | str = Decimal("0.001"),
    ) -> None:
        # validation: price_low < price_high, num_levels >= 2
        self._levels = [price_low + i * (price_high - price_low) / (num_levels - 1)
                        for i in range(num_levels)]
        self._last_cell: int | None = None
        self._pending: list[Side] = []   # очередь signal'ов

    def on_candle(self, candle: Candle) -> Signal | None:
        cell = self._find_cell(candle.close)
        if self._last_cell is None:
            self._last_cell = cell
            return None
        diff = cell - self._last_cell
        if diff < 0:                       # цена упала → BUY на |diff| ячеек
            for _ in range(-diff): self._pending.append(Side.BUY)
        elif diff > 0:                     # цена поднялась → SELL на diff ячеек
            for _ in range(diff): self._pending.append(Side.SELL)
        self._last_cell = cell
        if not self._pending:
            return None
        side = self._pending.pop(0)
        return Signal(self.name, self.symbol, side, size=self.base_per_level, price=None)
```

### G.3 Engine — регистрация + тесты

`trade-engine-crypto/src/strategies/__init__.py` — добавить `DcaStrategy`, `SpotGridStrategy` в `default_registry()`.

Тесты:
- `tests/unit/test_dca_strategy.py` — counter инкрементируется, signal на N-й свече, size = quote / close.
- `tests/unit/test_spot_grid_strategy.py` — задаём 5-level grid, гоняем 20 свечей с растущей/падающей ценой, проверяем количество BUY/SELL signal'ов и их size.

### G.4 Frontend — параметры в CreateStrategy

В дополнение к F.3 добавить:
- `STRATEGIES` → `[..., "DcaStrategy", "SpotGridStrategy"] as const`.
- `defaultParams`:
  - `DcaStrategy`: `{ buy_amount_quote: "10", interval_candles: "24" }`
  - `SpotGridStrategy`: `{ price_low: "60000", price_high: "70000", num_levels: "10", base_per_level: "0.001" }`
- `paramHint` для каждого ключа.
- `coerceParams`: `interval_candles` → Number, `num_levels` → Number, остальные Decimal-like — string.
- `STRATEGY_LABELS["DcaStrategy"] = "DCA (накопление)"`, `STRATEGY_LABELS["SpotGridStrategy"] = "Спотовый Grid"`.

### G.5 Frontend — шорткаты на странице Strategies

**Файл:** [frontend/src/app/pages/Strategies.tsx](frontend/src/app/pages/Strategies.tsx)

В header страницы (Stack после `<Typography variant="h1">Стратегии</Typography>`) рядом с "Создать стратегию" добавить две кнопки:

```tsx
<Button
  component={RouterLink}
  to="/strategies/new?template=dca"
  variant="outlined"
  color="inherit"
  startIcon={<Savings />}    // mui icons: Savings или MonetizationOn
>
  Создать DCA
</Button>
<Button
  component={RouterLink}
  to="/strategies/new?template=grid"
  variant="outlined"
  color="inherit"
  startIcon={<GridOn />}
>
  Создать Grid
</Button>
```

Также показать их в **empty state** ("Пока нет ни одного бота") — три кнопки в ряд:
- "Создать стратегию" (основная)
- "Создать DCA" 
- "Создать Grid"

### G.6 Frontend — CreateStrategy читает ?template=

В [CreateStrategy.tsx](frontend/src/app/pages/CreateStrategy.tsx) импорт `useSearchParams` из `react-router`, использовать для предзаполнения:

```tsx
const [searchParams] = useSearchParams();
const initialStrategy = useMemo<StrategyName>(() => {
  const t = searchParams.get("template");
  if (t === "dca") return "DcaStrategy";
  if (t === "grid") return "SpotGridStrategy";
  return "SmaCross";
}, [searchParams]);
const [strategy, setStrategy] = useState<StrategyName>(initialStrategy);
```

---

## H) Фикс Telegram-логина — `[FRONTEND]`

**Корневая причина:** [Login.tsx](frontend/src/app/pages/Login.tsx) делает `navigate(from)` только из `EmailCodeForm.onSuccess`, а TelegramButton после успешного `loginWithTelegram` ничего не делает — user становится authenticated, но остаётся на `/login`.

**Файл:** [frontend/src/app/pages/Login.tsx](frontend/src/app/pages/Login.tsx)

Добавить в начале компонента после `const from = ...`:

```tsx
const { isAuthenticated, isReady } = useAuth();

useEffect(() => {
  if (isReady && isAuthenticated) {
    navigate(from, { replace: true });
  }
}, [isReady, isAuthenticated, from, navigate]);
```

Это покрывает:
- Telegram login (после `refreshMe()` → `setUser(u)` → `isAuthenticated === true`)
- Email login (избыточно, но не вредно — `EmailCodeForm.onSuccess` уже вызывает `navigate`, но useEffect защитит от двойного клика)
- Случай когда user открывает `/login` будучи уже залогиненным (например, через старый таб) — сразу редиректит на `/`.

Импорт: `useEffect` уже импортирован? Если нет — добавить из `react`. `useAuth` уже импортирован в TelegramButton, в Login его пока нет — импортировать из `../../auth/AuthContext`.

**Проверка:** на проде. Залогиниться через Telegram → должен сразу попасть на `/`.

---

## I) Социальные иконки — улучшение визуала — `[FRONTEND]`

### I.1 Увеличить размеры

**Файл:** [frontend/src/app/components/auth/SocialIcons.tsx](frontend/src/app/components/auth/SocialIcons.tsx)

Все 4 SVG: `width="20" height="20"` → `width="28" height="28"`. Сами viewBox оставляем как есть (логотипы масштабируются).

**Файл:** [frontend/src/app/pages/Login.tsx](frontend/src/app/pages/Login.tsx)

В `socialBtnSx` (строки 29–41):
- `width: 44, height: 44` → `width: 52, height: 52`
- `borderRadius: 12` оставляем (квадратные с закругл. углами).
- TelegramButton.tsx тоже использует 56×56 — синхронизировать на 52×52 для единообразия. **Файл** [TelegramButton.tsx](frontend/src/app/components/auth/TelegramButton.tsx):143-148 — поменять `width: 56, height: 56` → `width: 52, height: 52`.

### I.2 Переписать YandexIcon

Текущая иконка — белая "Я" на красном фоне (бэк button), но path выглядит как обрезанная буква. Заменить на чистую кириллическую "Я":

```tsx
export function YandexIcon() {
  return (
    <svg viewBox="0 0 24 24" width="28" height="28" aria-hidden="true">
      {/* Чёткая кириллическая Я на прозрачном фоне (красный задаёт button bgcolor) */}
      <path
        fill="#fff"
        d="M13.91 5.5h-2.07c-2.65 0-4.84 1.71-4.84 4.93 0 2.04 0.95 3.52 2.7 4.32L6.5 18.5h2.13l3.13-4.07h.51v4.07h1.8V6.92c0-.95-.5-1.42-.94-1.42zm-1.64 7.16h-.51c-1.46 0-2.78-.79-2.78-2.99 0-2.27 1.41-3.16 2.78-3.16h.51v6.15z"
      />
    </svg>
  );
}
```

(Это canonical Yandex "Я" из их design guidelines — корректный letterform.)

### I.3 Лёгкая полировка остальных иконок

- **GoogleIcon**: viewBox 0 0 24 24, размер 28 — оставляем path как есть (это канонический G-логотип).
- **GitHubIcon**: проверить что path виден на тёмном фоне — у нас fill="#fff", окружено `socialBtnSx.bgcolor: rgba(255,255,255,0.04)` — низкий контраст. Можно поменять button bgcolor на `rgba(255,255,255,0.08)` или GitHub-фирменный `#24292e`. **Решение**: оставить ghost-style, но `fill="#e5e7eb"` (чуть мягче белого) — сольётся с grok-эстетикой.
- **TelegramIcon**: ничего не меняем (path корректен).

### I.4 Применить новые размеры на Login.tsx

Поскольку SVG теперь 28px и кнопка 52px — пересмотреть spacing в Stack (строка 92–97). `spacing={1.25}` (10px) с 52px кнопками → суммарно 4×52 + 3×10 = 238px. `maxWidth: 400` карточки минус padding = ~336px. Влезает с запасом.

---

## J) Login.tsx — минимализм + закругление капчи — `[FRONTEND]`

### J.1 Убрать тексты сверху и снизу

**Файл:** [frontend/src/app/pages/Login.tsx](frontend/src/app/pages/Login.tsx)

- Удалить целиком блок `<Box mb={3.5}>...</Box>` (строки 82–89) с `Crypto Dashboard` + `Войдите, чтобы начать торговать`. Карточка начинается сразу с ряда соц-иконок.
- Удалить блок `<Typography ... mt={3}>Аккаунт создастся автоматически при первом входе.</Typography>` (строки 157–166).
- После удаления — `CardContent sx={{ p: 4 }}` оставляем, но визуально первый элемент теперь `<Stack>` с соц-кнопками. Можно слегка уменьшить top padding (`pt: 3` вместо `4`) для лучшей симметрии.

### J.2 Закруглить плашку Turnstile

**Файл:** [frontend/src/app/components/auth/EmailCodeForm.tsx](frontend/src/app/components/auth/EmailCodeForm.tsx) — строки 119–129.

Обернуть `<Turnstile>` в `<Box>` с маской:

```tsx
{SITE_KEY ? (
  <Box display="flex" justifyContent="center">
    <Box
      sx={{
        borderRadius: 3,                                  // 12px
        overflow: "hidden",
        border: "1px solid rgba(255,255,255,0.08)",
        // компенсирует фирменную белую/чёрную бордюрную обводку Cloudflare
        "& iframe": { display: "block" },
      }}
    >
      <Turnstile
        ref={captchaRef}
        siteKey={SITE_KEY}
        options={{ theme: "dark", size: "flexible" }}
        onSuccess={(token: string) => setCaptchaToken(token)}
        onExpire={() => setCaptchaToken(null)}
        onError={() => setCaptchaToken(null)}
      />
    </Box>
  </Box>
) : (...)}
```

Cloudflare сама не даёт API для borderRadius, поэтому маскируем через `overflow: hidden` на родительском контейнере с `borderRadius: 12`. Тонкий border сольётся с другими `MuiOutlinedInput` радом.

---

## K) Settings: spinner вместо "..." при валидации — `[FRONTEND]`

**Файл:** [frontend/src/app/pages/Settings.tsx](frontend/src/app/pages/Settings.tsx) — строки 300–307.

Было:
```tsx
<Button type="submit" variant="contained" color="primary" disabled={submitting || !apiKey || !apiSecret}>
  {submitting ? "Проверяем ключ..." : "Сохранить"}
</Button>
```

Стало:
```tsx
<Button
  type="submit"
  variant="contained"
  color="primary"
  disabled={submitting || !apiKey || !apiSecret}
  startIcon={submitting ? <CircularProgress size={14} color="inherit" /> : null}
>
  {submitting ? "Проверяем ключ" : "Сохранить"}
</Button>
```

`CircularProgress` уже импортирован в Settings.tsx (строка 13). Менять ничего больше не нужно.

---

## L) Network error при валидации ключей — `[BACKEND]`

### L.1 Расширенное логирование

**Файл:** [backend/src/infrastructure/exchange_validator.py](backend/src/infrastructure/exchange_validator.py)

В блоке `_fetch_balance_sync` (строки 62–77) — расширить except'ы:

```python
import logging
logger = logging.getLogger(__name__)

def _fetch_balance_sync(client: Any) -> None:
    try:
        client.fetch_balance()
    except ccxt.AuthenticationError as exc:
        logger.warning("exchange.auth_failed", extra={"exchange": client.id, "err": repr(exc)})
        raise CredentialValidationError(f"Биржа отклонила ключ: {exc}") from exc
    except ccxt.NetworkError as exc:
        logger.exception(
            "exchange.network_error",
            extra={"exchange": client.id, "err": repr(exc), "cause": repr(exc.__cause__)},
        )
        raise CredentialValidationError(
            f"Не удалось связаться с биржей {client.id} (testnet). "
            "Возможно, сервис временно недоступен или firewall блокирует соединение. "
            "Попробуйте позже или другую биржу."
        ) from exc
    except Exception as exc:
        logger.exception("exchange.validate_failed", extra={"exchange": client.id})
        raise CredentialValidationError(f"Ошибка валидации: {exc}") from exc
    finally: ...
```

Это:
1. Логирует **полный traceback + cause** на бэке (увидим реальную причину — DNS, timeout, SSL, geo-block).
2. На фронт отдаёт **читаемое** сообщение без технических деталей URL.

### L.2 Увеличить таймаут + перейти на async ccxt

В `_build_client`:
```python
config: dict[str, Any] = {
    "apiKey": api_key,
    "secret": api_secret,
    "enableRateLimit": True,
    "timeout": 30000,           # 30 секунд вместо дефолтных 10
}
```

И переключить на async-вариант — это даст реальную async-обёртку через aiohttp вместо `to_thread(sync_requests)`:

```python
import ccxt.async_support as ccxt_async

def _build_async_client(exchange, api_key, api_secret, testnet, passphrase=None):
    # same as _build_client но через ccxt_async.<exchange>
    ...

async def validate_credentials(exchange, api_key, api_secret, *, testnet=True, passphrase=None) -> None:
    client = _build_async_client(exchange, api_key, api_secret, testnet=testnet, passphrase=passphrase)
    try:
        await client.fetch_balance()
    except ccxt_async.AuthenticationError as exc: ...
    except ccxt_async.NetworkError as exc: ...
    except Exception as exc: ...
    finally:
        await client.close()
```

Это убирает blocking I/O в `asyncio.to_thread` и даёт лучше backtrace.

### L.3 Диагностика на проде (verification step)

После деплоя выполнить **внутри backend контейнера**:
```bash
docker exec crypto-dashboard-backend-1 sh -c "
  echo '--- DNS ---'
  getent hosts testnet.binance.vision
  echo '--- curl exchangeInfo ---'
  curl -fsS -m 15 https://testnet.binance.vision/api/v3/exchangeInfo | head -c 200
  echo '--- curl serverTime ---'
  curl -fsS -m 15 https://testnet.binance.vision/api/v3/time
"
```

- **Если DNS не резолвится** → fix Docker DNS (добавить `dns: [8.8.8.8, 1.1.1.1]` в docker-compose.yml service).
- **Если curl timeout** → hosting блокирует egress к Binance. Решения:
  - Использовать HTTPS proxy через env `HTTPS_PROXY=http://proxy.host:port` (передать в ccxt config через `proxies`).
  - Сменить хостинг на тот, который не блокирует Binance.
- **Если curl OK** → проблема в Python/ccxt — в логах будет видно `cause=...`. Дальше точечно (старая версия ccxt — `pip show ccxt` в контейнере, обновить если <4.x).

### L.4 Surface полезного сообщения

После изменений ошибка во фронте будет: "Не удалось связаться с биржей binance (testnet). Возможно, сервис временно недоступен или firewall блокирует соединение. Попробуйте позже или другую биржу."

Это не выдаёт internal URL и позволяет пользователю переключиться на Bybit/OKX/MEXC.

---

## M) EngineStatusWidget — наполнение реальными данными — `[FRONTEND] [BACKEND]`

### M.1 Backend — мини-расширение `/healthz` (необязательно)

Уже есть `GET /healthz` с `{backend, postgres, redis}`. Использовать как есть. Дополнительно — можно сделать публично доступным без auth (если ещё не):

**Файл:** [backend/src/api/routers/health.py](backend/src/api/routers/health.py) — проверить что не требует auth deps. Если требует — оставить публичным.

Endpoint остаётся `GET /healthz` без префикса `/api`.

### M.2 Frontend — расширить виджет

**Файл:** [frontend/src/app/components/dashboard/EngineStatusWidget.tsx](frontend/src/app/components/dashboard/EngineStatusWidget.tsx)

Структура карточки:

```tsx
<Card sx={{ height: "100%", display: "flex", flexDirection: "column" }}>
  <CardContent sx={{ flex: 1, display: "flex", flexDirection: "column" }}>
    {/* Header — заголовок + статус */}
    <Stack direction="row" spacing={2} alignItems="center" mb={2}>
      <Box sx={{ p: 1.5, borderRadius: "50%", bgcolor: "rgba(59,130,246,0.1)" }}>
        <QueryStats color="primary" />
      </Box>
      <Box>
        <Typography variant="body1" fontWeight={600}>Статус движка</Typography>
        <Stack direction="row" alignItems="center" spacing={0.5} color={overallHealthy ? "success.main" : "error.main"}>
          <Box sx={{ width: 6, height: 6, borderRadius: "50%", bgcolor: "currentColor" }} />
          <Typography variant="caption">{overallHealthy ? "Работает" : "Проблема"}</Typography>
        </Stack>
      </Box>
    </Stack>

    {/* Health checks — 3 строки */}
    <Stack spacing={0.75} mb={2.5}>
      <HealthRow label="Backend"  ok={health?.backend === "ok"} />
      <HealthRow label="Postgres" ok={health?.postgres === "ok"} />
      <HealthRow label="Redis"    ok={health?.redis === "ok"} />
    </Stack>

    {/* Counters */}
    <Stack direction="row" spacing={2} mb={2.5}>
      <CounterBox label="Активных" value={runningBots} />
      <CounterBox label="В очереди" value={startingBots} />
      <CounterBox label="С ошибкой" value={errorBots} />
    </Stack>

    {/* Mini-list — running bots */}
    <Stack spacing={0.5} flexGrow={1}>
      <Typography variant="caption" color="text.secondary" sx={{ textTransform: "uppercase", letterSpacing: "0.05em" }}>
        Активные стратегии
      </Typography>
      {runningList.length === 0 ? (
        <Typography variant="body2" color="text.disabled" mt={0.5}>
          Нет запущенных стратегий
        </Typography>
      ) : runningList.slice(0, 4).map((b) => (
        <Stack key={b.id} direction="row" justifyContent="space-between" py={0.25}>
          <Typography variant="body2" noWrap>{b.symbol}</Typography>
          <Typography variant="caption" color="text.secondary">{b.strategy_class}</Typography>
        </Stack>
      ))}
    </Stack>

    {/* Footer link */}
    <Box mt="auto" pt={1.5}>
      <Button component={RouterLink} to="/strategies" size="small" variant="text" color="inherit"
              sx={{ p: 0, justifyContent: "flex-start" }}>
        Показать все →
      </Button>
    </Box>
  </CardContent>
</Card>
```

Где `HealthRow` — внутренний компонент: `<Stack direction="row" spacing={1} alignItems="center"><Box dot/><Typography>{label}</Typography><Typography ml="auto">{ok ? "OK" : "FAIL"}</Typography></Stack>`.

`CounterBox` — `<Box textAlign="center" flex={1} bgcolor="background.default" borderRadius={2} py={1}><Typography variant="h5">{value}</Typography><Typography variant="caption" color="text.secondary">{label}</Typography></Box>`.

Состояние:
```tsx
const [health, setHealth] = useState<HealthStatus | null>(null);
const [bots, setBots] = useState<BotOut[] | null>(null);

useEffect(() => {
  const tick = async () => {
    const [h, bs] = await Promise.allSettled([fetchHealth(), listBots()]);
    if (h.status === "fulfilled") setHealth(h.value);
    if (bs.status === "fulfilled") setBots(bs.value);
  };
  void tick();
  const t = setInterval(tick, 10_000);   // обновляем каждые 10 секунд
  return () => clearInterval(t);
}, []);

const runningList = useMemo(() => (bots ?? []).filter(b => b.status === "running"), [bots]);
const startingBots = (bots ?? []).filter(b => b.status === "starting").length;
const errorBots = (bots ?? []).filter(b => b.status === "error").length;
const overallHealthy = health?.backend === "ok" && health?.postgres === "ok" && health?.redis === "ok";
```

### M.3 API client для /healthz

**Новый файл:** `frontend/src/api/health.ts`:
```typescript
export interface HealthStatus {
  backend: string;
  postgres: string;
  redis: string;
}

export const fetchHealth = (): Promise<HealthStatus> =>
  apiFetch<HealthStatus>("/healthz", { skipAuthRetry: true });
```

`apiFetch` уже обрабатывает 503 как ошибку — но healthz может возвращать 503 с валидным body (когда часть проверок упала). Нужно handle: либо custom fetch с проверкой статуса, либо в `apiFetch` сделать option `acceptStatusCodes`.

**Решение**: написать отдельный `fetchHealth()` напрямую через `fetch()` (без `apiFetch`), который читает body даже при 503:
```typescript
export async function fetchHealth(): Promise<HealthStatus> {
  const res = await fetch("/healthz");
  return (await res.json()) as HealthStatus;  // body есть и при 200, и при 503
}
```

---

## N) Footer в Sidebar — версия + GitHub-иконка — `[FRONTEND]`

### N.1 Vite — инжектим git short SHA в build

**Файл:** [frontend/vite.config.ts](frontend/vite.config.ts)

```typescript
import { execSync } from "node:child_process";

function getGitCommit(): string {
  try {
    return execSync("git rev-parse --short HEAD", { cwd: __dirname }).toString().trim();
  } catch {
    return "dev";
  }
}

function getBuildDate(): string {
  return new Date().toISOString().slice(0, 10);  // 2026-05-18
}

export default defineConfig({
  // ... existing config
  define: {
    __GIT_COMMIT__: JSON.stringify(getGitCommit()),
    __BUILD_DATE__: JSON.stringify(getBuildDate()),
    __APP_VERSION__: JSON.stringify(process.env.npm_package_version ?? "0.0.1"),
  },
});
```

**Новый файл:** `frontend/src/vite-env.d.ts` (или дополнение существующего):
```typescript
declare const __GIT_COMMIT__: string;
declare const __BUILD_DATE__: string;
declare const __APP_VERSION__: string;
```

### N.2 Sidebar — рендер версии + GitHub

**Файл:** [frontend/src/app/components/layout/Sidebar.tsx](frontend/src/app/components/layout/Sidebar.tsx) — заменить блок `v1.0.0-beta` (строки 107–123).

```tsx
<Box
  sx={{
    p: 1.5,
    borderTop: `1px solid ${theme.palette.divider}`,
    display: "flex",
    alignItems: "center",
    justifyContent: isMini ? "center" : "space-between",
    gap: 1,
  }}
>
  <Typography
    variant="caption"
    color="text.secondary"
    noWrap
    sx={{ opacity: isMini ? 0 : 1, transition: "opacity 0.2s" }}
    title={`Build: ${__BUILD_DATE__}`}
  >
    v{__APP_VERSION__} · {__GIT_COMMIT__}
  </Typography>
  <IconButton
    size="small"
    component="a"
    href="https://github.com/VadimDenisovich/crypto-dashboard"
    target="_blank"
    rel="noreferrer noopener"
    aria-label="GitHub repo"
    sx={{ color: "text.secondary", "&:hover": { color: "text.primary" } }}
  >
    <GitHub fontSize="small" />
  </IconButton>
</Box>
```

Импорт: `import { GitHub } from "@mui/icons-material"`.

### N.3 Build / Docker

В существующем `frontend/Dockerfile` (multi-stage) — нужно убедиться что `.git/` доступна на этапе билда:
- Если build делается из контекста submodule — `.git` уже там.
- Если из root context — `.git` от root (там submodules ссылочно). Проверить и при необходимости передать SHA через build-arg в Dockerfile:
  ```dockerfile
  ARG GIT_COMMIT=dev
  ENV VITE_GIT_COMMIT=${GIT_COMMIT}
  ```
  и в vite.config.ts fallback на `process.env.VITE_GIT_COMMIT` если git недоступен.

**Решение MVP**: использовать `process.env.VITE_GIT_COMMIT` если задан (в CI), иначе `execSync("git rev-parse")`, иначе `"dev"`. В `.github/workflows/deploy.yml` добавить `build-args: GIT_COMMIT=${{ github.sha }}` и в Dockerfile `ARG GIT_COMMIT` → `ENV VITE_GIT_COMMIT=...`.

---

## Критичные файлы

### A) Header chip
- [frontend/src/app/components/layout/Header.tsx](frontend/src/app/components/layout/Header.tsx) — удалить строки 43–60

### B) Symbol dropdown
- [frontend/src/app/pages/CreateStrategy.tsx](frontend/src/app/pages/CreateStrategy.tsx) — убрать freeSolo, добавить slotProps.paper
- `frontend/src/app/styles/glassDropdown.ts` (новый) — glassPopupSx
- [backend/src/api/routers/exchanges.py](backend/src/api/routers/exchanges.py) — verify works (no changes expected)

### C) De-mock
- [frontend/src/app/components/dashboard/BalanceWidget.tsx](frontend/src/app/components/dashboard/BalanceWidget.tsx) — "Нет данных"
- [frontend/src/app/components/dashboard/PositionsWidget.tsx](frontend/src/app/components/dashboard/PositionsWidget.tsx) — "Нет позиций"
- [frontend/src/app/components/dashboard/ChartWidget.tsx](frontend/src/app/components/dashboard/ChartWidget.tsx) — empty chart + disabled controls
- [frontend/src/app/components/dashboard/RecentTradesWidget.tsx](frontend/src/app/components/dashboard/RecentTradesWidget.tsx) — wire к /api/trades
- [frontend/src/app/components/dashboard/EngineStatusWidget.tsx](frontend/src/app/components/dashboard/EngineStatusWidget.tsx) — wire к /api/bots
- [frontend/src/app/pages/Trades.tsx](frontend/src/app/pages/Trades.tsx) — wire к /api/trades
- [frontend/src/app/pages/Logs.tsx](frontend/src/app/pages/Logs.tsx) — wire к /api/ws/me
- `frontend/src/api/trades.ts` (новый)

### D) Backtest engine
**Engine:**
- `trade-engine-crypto/src/infrastructure/simulated_exchange.py` (новый)
- `trade-engine-crypto/src/infrastructure/csv_market_data.py` (новый)
- `trade-engine-crypto/src/infrastructure/in_memory_event_bus.py` (новый)
- `trade-engine-crypto/src/application/backtest_runner.py` (новый)
- `trade-engine-crypto/src/domain/backtest_result.py` (новый)
- `trade-engine-crypto/src/backtest_main.py` (новый — CLI)
- [trade-engine-crypto/pyproject.toml](trade-engine-crypto/pyproject.toml) — [backtest] extras + entry point

**Engine tests:**
- `trade-engine-crypto/tests/unit/test_simulated_exchange.py`
- `trade-engine-crypto/tests/unit/test_csv_market_data.py`
- `trade-engine-crypto/tests/unit/test_backtest_runner.py`

**Scripts:**
- `scripts/fetch_historical.py` (новый)
- [.gitignore](.gitignore) — добавить `data/historical/`

**Backend:**
- `backend/alembic/versions/0004_add_backtest_jobs.py` (новый)
- `backend/src/models/backtest_job.py` (новый)
- `backend/src/api/schemas/backtest.py` (новый)
- `backend/src/repositories/backtest_repo.py` (новый)
- `backend/src/services/backtest_worker.py` (новый)
- `backend/src/api/routers/backtest.py` (новый)
- [backend/src/main.py](backend/src/main.py) — include router + lifespan task
- [backend/Dockerfile](backend/Dockerfile) — `pip install -e /opt/engine[backtest]`
- [docker-compose.yml](docker-compose.yml) — volumes: `./data/historical`

**Backend tests:**
- `backend/tests/integration/test_backtest_api.py`
- `backend/tests/integration/test_backtest_worker.py`

**Frontend:**
- `frontend/src/api/backtest.ts` (новый)
- `frontend/src/app/pages/Backtest.tsx` (переименование из Backtesting.tsx, целиком переписан)
- [frontend/src/app/routes.tsx](frontend/src/app/routes.tsx) — обновить путь, добавить опциональный список

### E) Брендинг
- [frontend/src/app/components/layout/Header.tsx](frontend/src/app/components/layout/Header.tsx) — заголовок + иконка (mobile)
- [frontend/src/app/components/layout/Sidebar.tsx](frontend/src/app/components/layout/Sidebar.tsx) — "AlgoTrader" → "Crypto Dashboard", AutoGraph → CurrencyBitcoin

### F) Индикаторные стратегии
**Engine:**
- `trade-engine-crypto/src/strategies/rsi_threshold.py` (новый)
- `trade-engine-crypto/src/strategies/macd_cross.py` (новый)
- `trade-engine-crypto/src/strategies/bollinger_bands.py` (новый)
- `trade-engine-crypto/src/strategies/bollinger_rsi.py` (новый)
- [trade-engine-crypto/src/strategies/__init__.py](trade-engine-crypto/src/strategies/__init__.py) — добавить в `default_registry()`
- `trade-engine-crypto/tests/unit/test_rsi_threshold.py`, `test_macd_cross.py`, `test_bollinger_bands.py`, `test_bollinger_rsi.py`

**Frontend:**
- [frontend/src/app/pages/CreateStrategy.tsx](frontend/src/app/pages/CreateStrategy.tsx) — STRATEGIES + defaultParams + paramHint + coerceParams + STRATEGY_LABELS

### G) Механические стратегии
**Engine:**
- `trade-engine-crypto/src/strategies/dca.py` (новый)
- `trade-engine-crypto/src/strategies/spot_grid.py` (новый)
- `trade-engine-crypto/tests/unit/test_dca_strategy.py`, `test_spot_grid_strategy.py`

**Frontend:**
- [frontend/src/app/pages/Strategies.tsx](frontend/src/app/pages/Strategies.tsx) — две кнопки шорткаты + в empty state
- [frontend/src/app/pages/CreateStrategy.tsx](frontend/src/app/pages/CreateStrategy.tsx) — `useSearchParams` + `?template=dca|grid` → предзаполнение

### H) Telegram fix
- [frontend/src/app/pages/Login.tsx](frontend/src/app/pages/Login.tsx) — useEffect на `isAuthenticated`

### I) Social icons
- [frontend/src/app/components/auth/SocialIcons.tsx](frontend/src/app/components/auth/SocialIcons.tsx) — 20px → 28px, переписать YandexIcon
- [frontend/src/app/pages/Login.tsx](frontend/src/app/pages/Login.tsx) — socialBtnSx 44 → 52
- [frontend/src/app/components/auth/TelegramButton.tsx](frontend/src/app/components/auth/TelegramButton.tsx) — 56 → 52, иконка 20 → 28

### J) Login минимализм + капча
- [frontend/src/app/pages/Login.tsx](frontend/src/app/pages/Login.tsx) — удалить блок заголовка (стр. 82-89) и блок caption внизу (стр. 157-166)
- [frontend/src/app/components/auth/EmailCodeForm.tsx](frontend/src/app/components/auth/EmailCodeForm.tsx) — wrapper Box с borderRadius+overflow:hidden вокруг `<Turnstile>`

### K) Settings spinner
- [frontend/src/app/pages/Settings.tsx](frontend/src/app/pages/Settings.tsx) — startIcon CircularProgress + текст "Проверяем ключ" без многоточия

### L) Validator network error
- [backend/src/infrastructure/exchange_validator.py](backend/src/infrastructure/exchange_validator.py) — logger.exception, timeout 30s, переход на `ccxt.async_support`, user-friendly сообщение

### M) EngineStatusWidget
- [frontend/src/app/components/dashboard/EngineStatusWidget.tsx](frontend/src/app/components/dashboard/EngineStatusWidget.tsx) — health rows + counters + mini-list
- `frontend/src/api/health.ts` (новый)

### N) Footer version + GitHub
- [frontend/vite.config.ts](frontend/vite.config.ts) — `define: __GIT_COMMIT__/__APP_VERSION__/__BUILD_DATE__`
- `frontend/src/vite-env.d.ts` — type declarations
- [frontend/src/app/components/layout/Sidebar.tsx](frontend/src/app/components/layout/Sidebar.tsx) — версия + GitHub IconButton
- [frontend/Dockerfile](frontend/Dockerfile) — ARG GIT_COMMIT через build-arg
- [.github/workflows/deploy.yml](.github/workflows/deploy.yml) — передать `${{ github.sha }}` как build-arg

### O) Сохранение плана + отчёт
- `.context/phase-4-design.md` (новый) — копия этого плана
- `.context/phase-4-implementation-report.md` (новый) — детальный отчёт по образцу `.context/phase-3-implementation-report.md`

---

## Переиспользуемые модули

- `RiskManager` ([trade-engine-crypto/src/application/risk_manager.py](trade-engine-crypto/src/application/risk_manager.py)) — без изменений, инжектится в BacktestRunner
- `OrderExecutor` ([trade-engine-crypto/src/application/order_executor.py](trade-engine-crypto/src/application/order_executor.py)) — без изменений
- `default_registry()` ([trade-engine-crypto/src/strategies/__init__.py](trade-engine-crypto/src/strategies/__init__.py)) — для резолва strategy_class
- `Strategy.startup_candle_count` — backtest_runner делает warmup на N свечах перед началом loop
- `domain.models.Candle/Order/Signal/Balance` — все frozen dataclass, никаких изменений
- `apiFetch` ([frontend/src/api/client.ts](frontend/src/api/client.ts)) — для всех новых API-клиентов
- `recharts` — уже в package.json фронта
- `MUI Autocomplete` — переиспользуем в Backtest.tsx с тем же glassPopupSx
- Login-стилевые токены (`rgba(20,20,22,...)`, blur 20px, radius 12-16) — те же что определены в [phase-3-fix-and-updates-design-and-logic.md](.context/phase-3-fix-and-updates-design-and-logic.md) для grok-темы

---

## Verification (DoD)

### A) Header
- Открыть `/`. Справа сверху больше нет "Binance Testnet" чипа. Email + кнопка "Выйти" остаются.

### B) Dropdown
- Создать стратегию → выбрать credential → в поле "Торговая пара" виден дропдаун с ≥10 USDT-парами. Кликом раскрывается, hover подсвечивает, выбор фиксирует.
- Поппер имеет blur backdrop, radius 12, тонкий border (как grok-карточки).
- Попытка ввести произвольную пару клавиатурой → не сохраняется (clear на blur, если не из списка).
- Сменить credential на OKX → топ-пары обновляются.

### C) De-mock
- `/` (Dashboard) — Balance/Positions/Chart показывают "Нет данных" / "—". RecentTrades подтягивает реальные сделки (или "Нет сделок" если 0). EngineStatus считает активных ботов через listBots().
- `/trades` — список реальных сделок из БД. Если 0 — empty state.
- `/logs` — WS подключение, реальные STRATEGY_ERROR события появляются по мере прихода. Кнопка "Пауза" работает.
- Никаких хардкодных `BTC/USDT 67,450.00` в JS-бандле (`grep -r "67,450" frontend/dist` пустой).

### D) Backtest engine

**Engine unit tests:**
```bash
cd trade-engine-crypto
pip install -e ".[backtest]"
pytest tests/unit/test_simulated_exchange.py tests/unit/test_csv_market_data.py tests/unit/test_backtest_runner.py -v
```
Все зелёные.

**Data fetch:**
```bash
python scripts/fetch_historical.py --exchange binance --symbol BTC/USDT --timeframe 1h \
    --from 2024-01-01 --to 2024-06-30 \
    --output data/historical/binance_btc_usdt_1h_2024_h1.parquet
```
Создаётся файл ~50KB, `INDEX.json` обновлён.

**CLI smoke:**
```bash
python -m backtest_main --config tests/fixtures/sma_cross_config.json
# выводит на stdout JSON с total_return_pct, trades_count и т.п.
```

**Backend integration:**
```bash
cd backend
pytest tests/integration/test_backtest_api.py tests/integration/test_backtest_worker.py -v
```
Все зелёные.

### E) Брендинг
- Header слева на мобиле виден `<CurrencyBitcoin>` + "Crypto Dashboard". На десктопе Header пустой слева, бренд в Sidebar.
- Sidebar показывает "Crypto Dashboard" вместо "AlgoTrader", иконка Bitcoin.

### F) Индикаторные стратегии
- `cd trade-engine-crypto && pytest tests/unit/test_rsi_threshold.py tests/unit/test_macd_cross.py tests/unit/test_bollinger_bands.py tests/unit/test_bollinger_rsi.py -v` — все зелёные.
- На фронте `/strategies/new` — в селекте "Тип стратегии" 5 вариантов: SMA Cross, RSI порог, MACD Cross, Bollinger Bands, BB + RSI. При смене типа форма перерисовывает поля параметров.
- Можно создать и запустить (на Binance Testnet) бота с каждой из 4 новых стратегий — стартует без ошибки.

### G) Механические стратегии
- На `/strategies` рядом с "Создать стратегию" видны "Создать DCA" и "Создать Grid". В empty state — тройка кнопок.
- Клик "Создать DCA" → форма с `strategy=DcaStrategy`, параметры `buy_amount_quote`, `interval_candles`.
- Клик "Создать Grid" → форма с `strategy=SpotGridStrategy`, параметры `price_low`, `price_high`, `num_levels`, `base_per_level`.
- Можно сохранить и запустить — engine принимает.
- `pytest trade-engine-crypto/tests/unit/test_dca_strategy.py test_spot_grid_strategy.py -v` зелёный.

### H) Telegram fix
- Залогиниться через Telegram (на проде) → после подтверждения попадает на `/`, не на `/login`.
- Открыть `/login` будучи уже залогиненным → редирект на `/`.

### I) Social icons
- На `/login` 4 квадратные кнопки 52×52 с rounded-12 углами. SVG-иконки 28×28 внутри.
- Яндекс — чистая "Я" на красном фоне, без сломанного letterform'а.
- Все 4 кнопки одного размера и формы.

### J) Login минимализм + капча
- На `/login` карточка начинается сразу с ряда соц-иконок (нет "Crypto Dashboard" сверху и нет "Аккаунт создастся..." снизу).
- Виджет Turnstile имеет закруглённые углы (radius 12), сливается визуально с TextField email.

### K) Settings spinner
- На `/settings` после клика "Сохранить" — кнопка показывает крутящийся CircularProgress + "Проверяем ключ" (без многоточия). Кнопка disabled пока запрос идёт.

### L) Validator network fix
- Залить указанные testnet-ключи Binance (`u4nr...` / `h9dX...`). 
  - **Если фикс полностью устранил проблему** — ключ сохраняется, в списке появляется "Binance Testnet".
  - **Если egress всё ещё блокируется хостингом** — на фронте видно "Не удалось связаться с биржей binance (testnet)..." (без URL). В backend-логах (`docker logs crypto-dashboard-backend-1 | grep exchange.network_error`) — полный traceback с реальным cause (DNS / Timeout / SSL).
  - Если в логах видно `cause=DNS...` или `cause=ConnectionTimeout` — выполнить L.3 диагностику в backend контейнере и принять решение (proxy / смена хостинга / fallback exchange).

### M) EngineStatusWidget
- На Dashboard виджет "Статус движка" больше не выглядит пустым: видно 3 health-checks (Backend/Postgres/Redis), 3 счётчика (Активных/В очереди/С ошибкой), список первых 4 запущенных стратегий, ссылка "Показать все →".
- Если все 3 healthcheck'а OK — статус-точка зелёная "Работает". Если хоть один FAIL — красная "Проблема".
- Карточка заполняет всю высоту grid-ячейки рядом с RecentTrades.

### N) Footer version + GitHub
- В Sidebar внизу видно `v0.0.1 · <short SHA>` (например, `v0.0.1 · a3f9c1b`) — SHA соответствует текущему deploy-коммиту.
- Рядом — кликабельная GitHub-иконка, открывает https://github.com/VadimDenisovich/crypto-dashboard в новой вкладке.
- При `pnpm build` локально в dev — версия `v0.0.1 · <local SHA>`. В CI deploy — `v0.0.1 · ${{ github.sha }}` (первые 7 символов).

### O) Сохранение плана + отчёт
- `.context/phase-4-design.md` существует и совпадает с `.claude/plans/atomic-fluttering-firefly.md` на момент финального deploy'я.
- `.context/phase-4-implementation-report.md` существует и содержит:
  - **What was built** — список всех изменений по секциям A–N с конкретными файлами и счётчиком LoC.
  - **Files changed** — таблица "путь | change-type | summary".
  - **Tests added** — список новых юнит/integration-тестов с описанием сценариев.
  - **Bugs caught during implementation** — что было сломано в plan-чейке, как пофиксили.
  - **Verification log** — что вручную проверили на проде (с curl-командами / response сэмплами).
  - **What's deferred** — что не успели + ссылки на ROADMAP.
  - Стиль и глубина — как в `.context/phase-3-implementation-report.md`.

### D) Backtest engine (end-to-end UI)
1. Открыть `/backtest`.
2. Выбрать `SmaCross` / `BTC/USDT` / `1h` / `2024-01-01 → 2024-06-30` / `10000 USDT`.
3. Жмём "Запустить" → редирект на `/backtest/{id}` (или inline-результат).
4. Через несколько секунд (polling) — `status=completed`, видим equity curve, метрики.
5. Если parquet отсутствует → status=failed с понятным сообщением "Нет исторических данных для BTC/USDT 1h в указанном диапазоне. Выполните scripts/fetch_historical.py".

**Curl-чек API:**
```bash
curl -X POST https://crypto.shilkaphilosophy.ru/api/backtest/run \
    -H "Content-Type: application/json" \
    -H "Cookie: access_token=..." \
    -d '{"strategy_class":"SmaCross","symbol":"BTC/USDT","timeframe":"1h",
         "params":{"fast_period":5,"slow_period":20,"order_size":"0.01"},
         "date_from":"2024-01-01T00:00:00Z","date_to":"2024-06-30T00:00:00Z",
         "initial_balance":{"USDT":"10000"}}'
# → 201, {"id":"...","status":"queued",...}

curl https://crypto.shilkaphilosophy.ru/api/backtest/{id}
# через ~30 секунд → {"status":"completed","result":{...}}
```

---

## Финал — коммиты

Коммиты по submodules + 1 root-bump:

1. **`frontend`**: `feat(ui): testnet chip removed + brand header + grok symbol select + de-mock dashboard/trades/logs + backtest page + 6 strategies + DCA/Grid shortcuts + Telegram login fix + bigger social icons + minimal login + rounded captcha + settings spinner + engine status widget + footer version & GitHub`
2. **`backend`**: `feat(backtest): backtest_jobs migration + router + subprocess worker; fix(validator): async ccxt + 30s timeout + better error surface`
3. **`trade-engine-crypto`**: `feat(strategies+backtest): RSI/MACD/BB/BB+RSI/DCA/Grid strategies + SimulatedExchange + CSVMarketData + BacktestRunner + CLI`
4. **root scripts**: `feat: scripts/fetch_historical.py` (вместе с root-bump)
5. **`crypto-dashboard`** (root): `feat(phase-4): bump submodules, backend Dockerfile + compose for backtest, .gitignore data/, deploy.yml GIT_COMMIT build-arg, .context/phase-4-{design,implementation-report}.md`

Затем `.context/phase-4-implementation-report.md` — отчёт по образцу `phase-3-implementation-report.md`.

---

## Что НЕ делается в этой пачке

- Параллельное выполнение нескольких backtest-jobs (пока один за раз).
- Walk-forward оптимизация (sweep параметров).
- Backtest на нескольких таймфреймах одновременно (multi-tf strategy).
- BacktestList.tsx с пагинацией — только если успеем (можно отдельной PR).
- Redis Stream queue вместо asyncio.Queue (Phase 7.5+ ROADMAP).
- Полноценная очистка `data/historical/` через cron (пока ручное).
- Walk-forward optimization, monte-carlo — Phase 8+.
- Подключение Dashboard Balance/Positions/Chart к реальным эндпоинтам — отдельной задачей (нет источника данных пока).
- **Grid bot c LIMIT ордерами** (полноценная биржевая сетка с отслеживанием fills через `on_order_filled`) — потребует расширения `Strategy` интерфейса (`on_order_filled(order)`); MVP версия использует MARKET ордера и трекает позицию по cell-движению.
- **Telegram-логин для повторных пользователей** — текущий синтетический email (`telegram-<id>@noreply.invalid`) работает, но если у user'а уже есть email-учётка и он логинится через Telegram, identities resolve может создать дубликат вместо merge. Phase 5 (account linking) — отдельной задачей.
- **Полная палитра strategy types** на отдельной странице "Каталог стратегий" с описаниями каждой и рекомендуемыми параметрами — Phase 5.
- **2FA для пользователей** — отдельной задачей.
