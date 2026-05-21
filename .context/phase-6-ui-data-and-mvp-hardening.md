# Phase 6 — UI-данные + MVP hardening

> Два раунда: (1) убрать заглушки и привязать UI к реальным данным, (2) закрыть BLOCKER/HIGH дыры MVP.

## TL;DR

- **Round 1**: Добавлены 3 новых backend-эндпоинта + 4 frontend-виджета переведены с placeholder на живые данные. Исправлены engine-команда UPDATE (теперь передаёт payload), расширен event_projector.
- **Round 2**: 5 критических/HIGH-проблем MVP устранены. Добавлены stop-loss/take-profit во все стратегии, сверка позиций с биржей при старте, миграция для positions_snapshots, реальный healthcheck engine.
- Тесты: **143 engine + 28 backend + 88 frontend** — все зелёные (+18 новых тестов на PositionManager).

---

## Round 1 — Убрать заглушки и связать UI с движком

### Backend: новые эндпоинты

| Эндпоинт | Файл | Описание |
|---|---|---|
| `GET /api/positions?credential_id=` | `backend/src/api/routers/positions.py` | Последние снапшоты позиций |
| `GET /api/balances/summary` | `backend/src/api/routers/balances.py` | Агрегированный баланс по всем credentials |
| `GET /api/candles/{exchange}/{symbol}/{timeframe}` | `backend/src/api/routers/candles.py` | Публичные свечи через CCXT + Redis кэш 60с |

### Backend: model + repo + projector

- `backend/src/models/position_snapshot.py` (новый) — SQLAlchemy `PositionSnapshot`
- `backend/src/repositories/position_repo.py` (новый) — `insert` + `latest_for_credential`
- `backend/src/services/event_projector.py` — добавлен `_handle_positions_update` для канала `engine.positions_update`
- `backend/src/main.py` — зарегистрированы routers `positions` и `candles`
- `backend/src/api/schemas/market.py` — добавлены `PositionOut`, `BalanceSummaryOut`

### Engine: command_update payload

- `trade-engine-crypto/src/infrastructure/command_listener.py` — `_dispatch_table` возвращает `(handler, use_payload)`; `update` теперь передаёт полный payload
- `trade-engine-crypto/src/application/orchestrator.py` — `update_strategy` принимает `payload: dict | None` (параметры уже сохранены в БД бэком)
- `tests/infrastructure/test_command_listener.py` — обновлён под новую сигнатуру

### Frontend: виджеты

| Виджет | Было | Стало |
|---|---|---|
| `BalanceWidget` | Статический placeholder с "—" | `GET /api/balances/summary`, polling 15с, equity/free/used/open PnL/позиции |
| `PositionsWidget` | "Нет открытых позиций" статически | `GET /api/exchange-credentials` → `GET /api/positions` по каждому, polling 15с |
| `ChartWidget` | disabled select + "График появится позже" | recharts LineChart, live-свечи через `/api/candles/binance/{symbol}/{tf}`, выбор символа/таймфрейма |
| `Dashboard` | — | Все виджеты живы |

### Frontend: API модули

- `frontend/src/api/balances.ts` (новый) — `listBalances`, `fetchBalanceSummary`
- `frontend/src/api/positions.ts` (новый) — `listPositions`
- `frontend/src/api/candles.ts` (новый) — `fetchCandles`
- `frontend/src/api/types.ts` — добавлены `PositionOut`, `BalanceOut`, `BalanceSummaryOut`, `CandleOut`

### Frontend: тесты

- `vitest.config.ts` — jsdom + react plugin + coverage v8
- `src/test/setup.ts` — ResizeObserver (recharts) + localStorage полифилы
- 7 тестовых файлов, 88 тестов, **90.55% lines** coverage

---

## Round 2 — MVP hardening

### 🔴 BLOCKER: миграция `positions_snapshots`

- `backend/alembic/versions/0006_positions_snapshots.py` (новый) — создаёт таблицу `positions_snapshots` (id, credential_id, symbol, side, entry_price, size, current_pnl, observed_at)
- `backend/alembic/env.py` — импорт `position_snapshot` (был пропущен, таблица не создавалась)

### 🟠 HIGH: healthcheck engine

- `trade-engine-crypto/src/healthcheck.py` (новый) — пингует Redis, выходит 0/1
- `trade-engine-crypto/Dockerfile` — `CMD python -m healthcheck` вместо `python -c "import sys; sys.exit(0)"`

### 🟠 HIGH: stop-loss / take-profit

- `trade-engine-crypto/src/domain/position_manager.py` (новый) — `PositionManager` + `TrackedPosition`:
  - `check_exits(candle)` — проверяет candle.low/high против stop_loss_price/take_profit_price
  - Поддержка long (стоп ниже, тейк выше) и short (стоп выше, тейк ниже)
  - `reconcile(exchange_positions)` — загрузка существующих позиций с биржи
  - `open(side, entry_price, size, stop_loss_pct, take_profit_pct)`
  - `close(index)`, `open_positions`, `has_position`
- `trade-engine-crypto/src/application/strategy_runner.py` — после каждого BUY открывает позицию в `PositionManager`; каждый candle проверяет exit-сигналы и исполняет через RiskManager → OrderExecutor
- Параметры `stop_loss_pct`/`take_profit_pct` читаются из `bot.params` и из `signal.metadata`

### 🟠 HIGH: сверка позиций при старте (reconciliation)

- `trade-engine-crypto/src/application/orchestrator.py` — `start_strategy`:
  - Извлекает `stop_loss_pct`/`take_profit_pct` из `bot.params`
  - Вызывает `adapter.get_positions()`, фильтрует по `bot.symbol`
  - Передаёт в `PositionManager.reconcile()` — stop-loss/take-profit работают от реальной цены входа
  - При ошибке логирует и продолжает без позиций (graceful degradation)

### Тесты

- `tests/domain/test_position_manager.py` (новый) — 18 тестов: лимиты long/short, стоп/тейк цены, множественные позиции, reconcile, manual close, exit signal

---

## Файлы, тронутые в Round 2

| Файл | Изменение |
|---|---|
| `backend/alembic/versions/0006_positions_snapshots.py` | Создан |
| `backend/alembic/env.py` | + import position_snapshot |
| `trade-engine-crypto/src/domain/position_manager.py` | Создан |
| `trade-engine-crypto/src/application/strategy_runner.py` | + PositionManager интеграция |
| `trade-engine-crypto/src/application/orchestrator.py` | + reconcile + позиции при старте |
| `trade-engine-crypto/src/healthcheck.py` | Создан |
| `trade-engine-crypto/Dockerfile` | healthcheck заменён |
| `tests/domain/test_position_manager.py` | Создан |

## Файлы, тронутые в Round 1

| Файл | Изменение |
|---|---|
| `backend/src/models/position_snapshot.py` | Создан |
| `backend/src/repositories/position_repo.py` | Создан |
| `backend/src/api/routers/positions.py` | Создан |
| `backend/src/api/routers/candles.py` | Создан |
| `backend/src/api/routers/balances.py` | + balances/summary |
| `backend/src/api/schemas/market.py` | + PositionOut, BalanceSummaryOut |
| `backend/src/services/event_projector.py` | + positions_update handler |
| `backend/src/main.py` | + positions, candles routers |
| `trade-engine-crypto/src/infrastructure/command_listener.py` | payload для UPDATE |
| `trade-engine-crypto/src/application/orchestrator.py` | payload опциональный |
| `frontend/src/app/components/dashboard/BalanceWidget.tsx` | Полностью переписан |
| `frontend/src/app/components/dashboard/PositionsWidget.tsx` | Полностью переписан |
| `frontend/src/app/components/dashboard/ChartWidget.tsx` | Полностью переписан |
| `frontend/src/api/balances.ts` | Создан |
| `frontend/src/api/positions.ts` | Создан |
| `frontend/src/api/candles.ts` | Создан |
| `frontend/src/api/types.ts` | + DTO |
| `frontend/vitest.config.ts` | Создан |
| `frontend/src/test/setup.ts` | Создан |
| `frontend/src/test/*.test.tsx` | 7 файлов, 88 тестов |
| `frontend/src/app/components/dashboard/EngineStatusWidget.tsx` | + HealthRow в JSX (был вычислен, но не рендерился) |
| `frontend/package.json` | + scripts test/test:coverage |
