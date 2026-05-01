#!/usr/bin/env python3
"""
InvestAI ML Data Collector v4

Scans logs from all InvestAI paper bots and builds one normalized dataset for
future machine-learning experiments.

It does not train a model. It only prepares a clean, combined data feed.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd

VERSION = "v4"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCES = {
    "crypto": str(PROJECT_ROOT / "logs/crypto/*.csv"),
    "options": str(PROJECT_ROOT / "logs/options/*.csv"),
    "quantum_ai": str(PROJECT_ROOT / "logs/quantum-ai/*.csv"),
    "private_ai": str(PROJECT_ROOT / "logs/private-ai/*.csv"),
}
DEFAULT_OUT_DIR = str(PROJECT_ROOT / "data/ml")

NORMALIZED_COLUMNS = [
    "collector_version",
    "collected_at_utc",
    "source_bot",
    "source_file",
    "record_type",
    "timestamp_local",
    "timestamp_utc",
    "date_local",
    "symbol",
    "asset",
    "product_id",
    "strategy",
    "event",
    "side",
    "action",
    "score",
    "price",
    "quantity",
    "cash",
    "equity",
    "realized_pl",
    "unrealized_pl",
    "total_pl",
    "daily_pl",
    "fees",
    "commission",
    "alpha",
    "benchmark",
    "news_count",
    "news_risk_score",
    "raw_json",
]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return ""
    return str(v)


def first_present(row: Dict[str, Any], names: Iterable[str]) -> Any:
    for name in names:
        if name in row and pd.notna(row[name]) and str(row[name]) != "":
            return row[name]
    return ""


def guess_source_bot(path: Path) -> str:
    p = str(path).lower()
    if "btc-bot" in p or "crypto" in p or "btc_eth" in p or "coinbase" in p:
        return "crypto"
    if "options-bot" in p or "option" in p:
        return "options"
    if "quantum" in p:
        return "quantum_ai"
    if "private" in p or "ai-private" in p:
        return "private_ai"
    return "unknown"


def guess_record_type(path: Path) -> str:
    name = path.name.lower()
    for key in ["trade", "equity", "daily", "tax", "scan", "news", "research", "state"]:
        if key in name:
            return key
    return "csv"


def normalize_row(row: Dict[str, Any], path: Path, source_bot: str) -> Dict[str, Any]:
    record_type = guess_record_type(path)
    raw = {k: safe_str(v) for k, v in row.items()}
    norm = {
        "collector_version": VERSION,
        "collected_at_utc": now_utc(),
        "source_bot": source_bot,
        "source_file": str(path),
        "record_type": record_type,
        "timestamp_local": first_present(row, ["timestamp_local", "local_time", "timestamp", "time", "datetime"]),
        "timestamp_utc": first_present(row, ["timestamp_utc", "utc_time", "timestamp", "time", "datetime"]),
        "date_local": first_present(row, ["date_local", "date", "day"]),
        "symbol": first_present(row, ["symbol", "ticker", "underlying", "asset", "product_id"]),
        "asset": first_present(row, ["asset", "symbol", "ticker", "underlying"]),
        "product_id": first_present(row, ["product_id", "ticker", "symbol"]),
        "strategy": first_present(row, ["strategy", "position_type", "instrument_type"]),
        "event": first_present(row, ["event", "side", "action"]),
        "side": first_present(row, ["side", "action", "direction"]),
        "action": first_present(row, ["action", "signal", "side", "event"]),
        "score": first_present(row, ["score", "bullish_score", "bearish_score", "trade_score"]),
        "price": first_present(row, ["price", "entry_price", "exit_price", "close", "last_price", "underlying_price"]),
        "quantity": first_present(row, ["quantity", "qty", "shares", "contracts"]),
        "cash": first_present(row, ["cash", "cash_after"]),
        "equity": first_present(row, ["equity", "current_equity", "total_equity"]),
        "realized_pl": first_present(row, ["realized_pl", "realized_pnl", "trade_pl", "gain_loss_usd"]),
        "unrealized_pl": first_present(row, ["unrealized_pl", "open_pl"]),
        "total_pl": first_present(row, ["total_pl", "total_pnl", "daily_pl", "gain_loss_usd"]),
        "daily_pl": first_present(row, ["daily_pl", "day_pl"]),
        "fees": first_present(row, ["fees", "fee", "fees_paid", "total_trade_cost_usd"]),
        "commission": first_present(row, ["commission", "commissions_paid", "option_commission"]),
        "alpha": first_present(row, ["alpha", "alpha_vs_btc", "alpha_vs_benchmark"]),
        "benchmark": first_present(row, ["benchmark", "benchmark_name"]),
        "news_count": first_present(row, ["news_count", "article_count", "articles"]),
        "news_risk_score": first_present(row, ["news_risk_score", "risk_hits", "risk_score"]),
        "raw_json": json.dumps(raw, ensure_ascii=False, sort_keys=True),
    }
    return {col: safe_str(norm.get(col, "")) for col in NORMALIZED_COLUMNS}


def read_csv_safely(path: Path) -> pd.DataFrame:
    try:
        if not path.exists() or path.stat().st_size == 0:
            return pd.DataFrame()
        return pd.read_csv(path)
    except Exception as exc:
        print(f"WARNING: Could not read {path}: {exc}")
        return pd.DataFrame()


def collect(patterns: Dict[str, str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for source_name, pattern in patterns.items():
        paths = sorted(Path().home().glob(pattern.replace("~/", ""))) if pattern.startswith("~/") else sorted(Path().glob(pattern))
        for path in paths:
            if path.name.startswith("master_ml_"):
                continue
            df = read_csv_safely(path)
            if df.empty:
                continue
            source_bot = source_name if source_name else guess_source_bot(path)
            for _, series in df.iterrows():
                rows.append(normalize_row(series.to_dict(), path, source_bot))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="Collect InvestAI bot logs into one ML-ready dataset.")
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    ap.add_argument("--extra-glob", action="append", default=[], help="Additional CSV glob to include, e.g. '~/mybot/logs/*.csv'.")
    ap.add_argument("--no-defaults", action="store_true", help="Do not scan default bot log locations.")
    args = ap.parse_args()

    patterns: Dict[str, str] = {} if args.no_defaults else dict(DEFAULT_SOURCES)
    for i, pat in enumerate(args.extra_glob, start=1):
        patterns[f"extra_{i}"] = pat

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"master_ml_events_{VERSION}.csv"
    jsonl_path = out_dir / f"master_ml_events_{VERSION}.jsonl"

    rows = collect(patterns)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=NORMALIZED_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    with jsonl_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    print("=" * 80)
    print("InvestAI ML Data Collector v4")
    print("=" * 80)
    print(f"Rows collected: {len(rows)}")
    print(f"CSV:  {csv_path}")
    print(f"JSONL: {jsonl_path}")
    print("\nDefault sources scanned:")
    for name, pattern in patterns.items():
        print(f"  {name}: {pattern}")
    print("\nNote: This creates training/evaluation data only. It does not train or trade.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
