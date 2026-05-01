#!/usr/bin/env python3
"""
Fetch public Coinbase historical candles and evaluate each crypto product.

Paper-research only:
- Uses Coinbase Exchange public market data.
- Does not use API keys.
- Does not place orders.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests


COINBASE_EXCHANGE_API = "https://api.exchange.coinbase.com"
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parents[2]
DEFAULT_PRODUCTS = ["BTC-USD", "ETH-USD", "SOL-USD"]


def parse_products(value: str) -> list[str]:
    products = [part.strip().upper() for part in value.split(",") if part.strip()]
    if not products:
        raise argparse.ArgumentTypeError("at least one product is required")
    return products


def request_json(url: str, params: dict[str, Any]) -> Any:
    headers = {"User-Agent": "investai-paper-history-evaluator/1.0", "Accept": "application/json"}
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=20)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(attempt * 1.5)
    raise RuntimeError(f"Coinbase request failed: {last_error}")


def fetch_coinbase_candles(product: str, start: datetime, end: datetime, granularity: int) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    cursor = start
    max_span = timedelta(seconds=granularity * 300)
    url = f"{COINBASE_EXCHANGE_API}/products/{product}/candles"

    while cursor < end:
        chunk_end = min(cursor + max_span, end)
        data = request_json(
            url,
            {
                "start": cursor.isoformat().replace("+00:00", "Z"),
                "end": chunk_end.isoformat().replace("+00:00", "Z"),
                "granularity": granularity,
            },
        )
        if isinstance(data, list):
            for candle in data:
                if len(candle) < 6:
                    continue
                ts, low, high, open_, close, volume = candle[:6]
                rows.append(
                    {
                        "time": pd.to_datetime(int(ts), unit="s", utc=True),
                        "Open": float(open_),
                        "High": float(high),
                        "Low": float(low),
                        "Close": float(close),
                        "Volume": float(volume),
                    }
                )
        cursor = chunk_end
        time.sleep(0.20)

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError(f"no candle data returned for {product}")
    return df.sort_values("time").drop_duplicates("time").reset_index(drop=True)


def run_backtest(csv_path: Path, product: str, args: argparse.Namespace) -> None:
    cmd = [
        sys.executable,
        str(BASE_DIR / "backtest_walk_forward_v13.py"),
        "--csv",
        str(csv_path),
        "--product",
        product,
        "--paper-cash",
        str(args.paper_cash),
        "--trade-size",
        str(args.trade_size),
        "--fee-rate",
        str(args.fee_rate),
        "--slippage-bps",
        str(args.slippage_bps),
        "--synthetic-spread-pct",
        str(args.synthetic_spread_pct),
        "--missed-fill-rate",
        str(args.missed_fill_rate),
        "--estimated-short-term-tax-rate",
        str(args.estimated_short_term_tax_rate),
        "--estimated-state-tax-rate",
        str(args.estimated_state_tax_rate),
        "--train-bars",
        str(args.train_bars),
        "--test-bars",
        str(args.test_bars),
        "--step-bars",
        str(args.step_bars),
        "--min-train-trades",
        str(args.min_train_trades),
        "--out-dir",
        str(args.out_dir),
    ]
    subprocess.run(cmd, check=True)


def aggregate_category_summaries(out_dir: Path) -> Path:
    summaries = []
    for path in sorted(out_dir.glob("*_strategy_category_summary.csv")):
        df = pd.read_csv(path)
        if df.empty:
            continue
        product = path.name.split("_", 1)[0]
        df.insert(0, "product", product)
        summaries.append(df)
    aggregate_path = out_dir / "ALL_PRODUCTS_strategy_category_summary.csv"
    if summaries:
        pd.concat(summaries, ignore_index=True).to_csv(aggregate_path, index=False)
    return aggregate_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate crypto strategies on Coinbase public historical candles.")
    parser.add_argument("--products", type=parse_products, default=DEFAULT_PRODUCTS, help="Comma-separated Coinbase products.")
    parser.add_argument("--days", type=int, default=30, help="Lookback window in days.")
    parser.add_argument("--granularity", type=int, default=3600, choices=[60, 300, 900, 3600, 21600, 86400])
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data/raw/crypto")
    parser.add_argument("--out-dir", type=Path, default=PROJECT_ROOT / "reports/backtests")
    parser.add_argument("--paper-cash", type=float, default=10_000.0)
    parser.add_argument("--trade-size", type=float, default=500.0)
    parser.add_argument("--fee-rate", type=float, default=0.006)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--synthetic-spread-pct", type=float, default=0.001)
    parser.add_argument("--missed-fill-rate", type=float, default=0.02)
    parser.add_argument("--estimated-short-term-tax-rate", type=float, default=0.22)
    parser.add_argument("--estimated-state-tax-rate", type=float, default=0.093)
    parser.add_argument("--train-bars", type=int, default=300)
    parser.add_argument("--test-bars", type=int, default=100)
    parser.add_argument("--step-bars", type=int, default=100)
    parser.add_argument("--min-train-trades", type=int, default=3)
    args = parser.parse_args()

    args.data_dir.mkdir(parents=True, exist_ok=True)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    end = datetime.now(timezone.utc).replace(microsecond=0)
    start = end - timedelta(days=max(1, args.days))

    for product in args.products:
        print(f"\nFetching {product} candles from {start.isoformat()} to {end.isoformat()}...")
        df = fetch_coinbase_candles(product, start, end, args.granularity)
        csv_path = args.data_dir / f"{product}_{args.granularity}s_{start.date()}_{end.date()}.csv"
        df.to_csv(csv_path, index=False)
        print(f"Saved {len(df)} candles: {csv_path}")
        run_backtest(csv_path, product, args)

    aggregate_path = aggregate_category_summaries(args.out_dir)
    if aggregate_path.exists():
        print(f"\nAggregate category summary: {aggregate_path}")
    print("Historical evaluation complete. Treat results as research evidence, not a profitability claim.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
