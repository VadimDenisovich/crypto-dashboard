#!/usr/bin/env python3
"""Скачивает исторические OHLCV через CCXT REST и сохраняет в parquet.

Использование:
    python scripts/fetch_historical.py \\
        --exchange binance --symbol BTC/USDT --timeframe 1h \\
        --from 2024-01-01 --to 2024-12-31 \\
        --output data/historical/binance_btc_usdt_1h_2024.parquet

Особенности:
- CCXT fetch_ohlcv лимит 1000 свечей/запрос — пагинируем по `since`.
- Между запросами `await asyncio.sleep(exchange.rateLimit/1000)` — не словить ban.
- Формат parquet: timestamp int64 ms, остальное — string (точный Decimal).
- Поддерживает resume: если файл существует, продолжает с последнего timestamp+1.
- Обновляет data/historical/INDEX.json: список доступных файлов.

Требует optional deps: `pip install ccxt pyarrow pandas tqdm`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import ccxt.async_support as ccxt_async  # type: ignore[import-not-found]
except ImportError:
    print("ccxt not installed: pip install ccxt", file=sys.stderr)
    sys.exit(2)

try:
    import pandas as pd  # type: ignore[import-not-found]
except ImportError:
    print("pandas not installed: pip install pandas pyarrow", file=sys.stderr)
    sys.exit(2)

try:
    from tqdm import tqdm  # type: ignore[import-not-found]
except ImportError:
    def tqdm(it, **kw):  # type: ignore[no-redef]
        return it


_TIMEFRAME_MS = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "30m": 30 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}


def _parse_date(s: str) -> int:
    # Принимаем YYYY-MM-DD или ISO-8601.
    dt = datetime.fromisoformat(s) if "T" in s else datetime.strptime(s, "%Y-%m-%d")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--exchange", required=True, help="binance | bybit | okx | mexc | ...")
    p.add_argument("--symbol", required=True, help="BTC/USDT")
    p.add_argument("--timeframe", required=True, choices=sorted(_TIMEFRAME_MS.keys()))
    p.add_argument("--from", dest="from_date", required=True, help="YYYY-MM-DD")
    p.add_argument("--to", dest="to_date", required=True, help="YYYY-MM-DD")
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--testnet", action="store_true", help="use testnet endpoint")
    return p.parse_args()


def _existing_max_ts(output: Path) -> int | None:
    if not output.exists():
        return None
    try:
        df = pd.read_parquet(output)
        if "timestamp" in df.columns and not df.empty:
            return int(df["timestamp"].max())
    except Exception:
        return None
    return None


def _save_parquet(output: Path, rows: list[list]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(
        rows, columns=["timestamp", "open", "high", "low", "close", "volume"]
    )
    df = df.astype(
        {
            "timestamp": "int64",
            "open": "string",
            "high": "string",
            "low": "string",
            "close": "string",
            "volume": "string",
        }
    )
    df.sort_values("timestamp", inplace=True)
    df.drop_duplicates(subset=["timestamp"], keep="last", inplace=True)
    df.to_parquet(output, index=False)


def _update_index(output: Path, meta: dict[str, object]) -> None:
    index_path = output.parent / "INDEX.json"
    index: list[dict[str, object]] = []
    if index_path.exists():
        try:
            index = json.loads(index_path.read_text())
            if not isinstance(index, list):
                index = []
        except Exception:
            index = []
    # Удаляем старую запись с тем же path
    index = [item for item in index if item.get("path") != meta["path"]]
    index.append(meta)
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False))


async def _fetch(args: argparse.Namespace) -> None:
    exchange_cls = getattr(ccxt_async, args.exchange)
    client = exchange_cls({"enableRateLimit": True})
    if args.testnet and hasattr(client, "set_sandbox_mode"):
        client.set_sandbox_mode(True)

    timeframe_ms = _TIMEFRAME_MS[args.timeframe]
    from_ms = _parse_date(args.from_date)
    to_ms = _parse_date(args.to_date)

    existing_max = _existing_max_ts(args.output)
    if existing_max is not None and existing_max >= from_ms:
        from_ms = existing_max + timeframe_ms
        print(f"Resuming from {datetime.fromtimestamp(from_ms/1000, timezone.utc)}", file=sys.stderr)

    rows: list[list] = []
    total_estimate = max(1, (to_ms - from_ms) // timeframe_ms)
    pbar = tqdm(total=total_estimate, desc=args.symbol, unit="candles")
    since = from_ms
    try:
        while since < to_ms:
            batch = await client.fetch_ohlcv(
                args.symbol, args.timeframe, since=since, limit=1000
            )
            if not batch:
                break
            for ts, o, h, l, c, v in batch:
                if ts > to_ms:
                    break
                rows.append([ts, str(o), str(h), str(l), str(c), str(v)])
            last_ts = batch[-1][0]
            if last_ts < since:
                break
            since = last_ts + timeframe_ms
            pbar.update(len(batch))
            # Промежуточное сохранение каждые 10к строк — для resumable
            if len(rows) >= 10_000:
                _save_parquet(args.output, rows)
                rows = []
            await asyncio.sleep(client.rateLimit / 1000)
        if rows:
            _save_parquet(args.output, rows)
    finally:
        pbar.close()
        await client.close()

    # Финальный read для метаданных индекса
    if args.output.exists():
        df = pd.read_parquet(args.output)
        _update_index(
            args.output,
            {
                "exchange": args.exchange,
                "symbol": args.symbol,
                "timeframe": args.timeframe,
                "from": int(df["timestamp"].min()),
                "to": int(df["timestamp"].max()),
                "rows": int(len(df)),
                "path": str(args.output.name),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        print(f"Saved {len(df)} candles to {args.output}", file=sys.stderr)


def main() -> int:
    args = _parse_args()
    asyncio.run(_fetch(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
