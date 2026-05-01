#!/usr/bin/env python3
"""Analyze AI Private-Tech Paper Bot v4 logs."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import pandas as pd

VERSION = "v4"
BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = Path(os.environ.get("INVESTAI_LOG_DIR", BASE_DIR / "logs")).expanduser()
TRADES_FILE = LOG_DIR / f"private_ai_trades_{VERSION}.csv"
EQUITY_FILE = LOG_DIR / f"private_ai_equity_{VERSION}.csv"
SCAN_FILE = LOG_DIR / f"private_ai_scan_{VERSION}.csv"
NEWS_FILE = LOG_DIR / f"private_ai_news_{VERSION}.csv"


def money(x: float) -> str:
    return f"${x:,.2f}"


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def max_drawdown(equity: pd.Series) -> tuple[float, float]:
    if equity.empty:
        return 0.0, 0.0
    roll_max = equity.cummax()
    dd = equity - roll_max
    dd_pct = dd / roll_max.replace(0, pd.NA) * 100
    return float(dd.min()), float(dd_pct.min()) if not dd_pct.dropna().empty else 0.0


def main() -> int:
    ap = argparse.ArgumentParser(description="Analyze AI Private-Tech Paper Bot v4 logs.")
    ap.add_argument("--log-dir", default=str(LOG_DIR))
    args = ap.parse_args()

    log_dir = Path(args.log_dir).expanduser().resolve()
    trades = read_csv(log_dir / f"private_ai_trades_{VERSION}.csv")
    equity = read_csv(log_dir / f"private_ai_equity_{VERSION}.csv")
    scans = read_csv(log_dir / f"private_ai_scan_{VERSION}.csv")
    news = read_csv(log_dir / f"private_ai_news_{VERSION}.csv")

    print("=" * 80)
    print("AI PRIVATE-TECH PAPER BOT PERFORMANCE ANALYZER v4")
    print("=" * 80)
    print(f"Log folder: {log_dir}")

    if equity.empty:
        print("\nNo equity log found yet. Run the bot first.")
        return 0

    equity["equity"] = pd.to_numeric(equity.get("equity"), errors="coerce")
    start_equity = float(equity["equity"].dropna().iloc[0]) if not equity["equity"].dropna().empty else 0.0
    final_equity = float(equity["equity"].dropna().iloc[-1]) if not equity["equity"].dropna().empty else 0.0
    total_pl = final_equity - start_equity
    dd_value, dd_pct = max_drawdown(equity["equity"].dropna())

    print("\nACCOUNT SUMMARY")
    print(f"  Start equity:       {money(start_equity)}")
    print(f"  Final equity:       {money(final_equity)}")
    print(f"  Total P/L:          {money(total_pl)}")
    print(f"  Return:             {(total_pl / start_equity * 100 if start_equity else 0):.2f}%")
    print(f"  Max drawdown:       {money(dd_value)} ({dd_pct:.2f}%)")

    if "fees_paid" in equity.columns or "commissions_paid" in equity.columns:
        fees = pd.to_numeric(equity.get("fees_paid", 0), errors="coerce").fillna(0).iloc[-1] if "fees_paid" in equity.columns else 0.0
        comm = pd.to_numeric(equity.get("commissions_paid", 0), errors="coerce").fillna(0).iloc[-1] if "commissions_paid" in equity.columns else 0.0
        print(f"  Fees/commissions:   {money(float(fees + comm))}")

    if not trades.empty:
        closes = trades[trades.get("event", "") == "CLOSE"].copy()
        opens = trades[trades.get("event", "") == "OPEN"].copy()
        print("\nTRADE SUMMARY")
        print(f"  Opens:              {len(opens)}")
        print(f"  Closes:             {len(closes)}")
        if not closes.empty and "realized_pl" in closes.columns:
            closes["realized_pl"] = pd.to_numeric(closes["realized_pl"], errors="coerce").fillna(0)
            wins = closes[closes["realized_pl"] > 0]
            losses = closes[closes["realized_pl"] < 0]
            gross_win = wins["realized_pl"].sum()
            gross_loss = abs(losses["realized_pl"].sum())
            profit_factor = gross_win / gross_loss if gross_loss else float("inf") if gross_win > 0 else 0.0
            print(f"  Closed P/L:         {money(closes['realized_pl'].sum())}")
            print(f"  Win rate:           {(len(wins) / len(closes) * 100 if len(closes) else 0):.1f}%")
            print(f"  Avg win:            {money(wins['realized_pl'].mean() if len(wins) else 0)}")
            print(f"  Avg loss:           {money(losses['realized_pl'].mean() if len(losses) else 0)}")
            print(f"  Profit factor:      {profit_factor:.2f}" if profit_factor != float("inf") else "  Profit factor:      inf")
            by_symbol = closes.groupby("symbol")["realized_pl"].agg(["count", "sum", "mean"]).sort_values("sum", ascending=False)
            print("\nP/L BY SYMBOL")
            for sym, row in by_symbol.iterrows():
                print(f"  {sym:<8} closes={int(row['count']):>3} total={money(float(row['sum'])):>12} avg={money(float(row['mean'])):>10}")

    if not scans.empty:
        print("\nSCAN SUMMARY")
        for col in ["bullish_score", "bearish_score"]:
            if col in scans.columns:
                scans[col] = pd.to_numeric(scans[col], errors="coerce")
        if "symbol" in scans.columns and "bullish_score" in scans.columns:
            recent = scans.groupby("symbol").tail(1).sort_values("bullish_score", ascending=False)
            print("  Latest scores:")
            for _, r in recent.iterrows():
                print(f"    {r.get('symbol',''):<8} bull={float(r.get('bullish_score',0)) if pd.notna(r.get('bullish_score',0)) else 0:>5.1f} bear={float(r.get('bearish_score',0)) if pd.notna(r.get('bearish_score',0)) else 0:>5.1f} action={r.get('action','')}")

    if not news.empty:
        print("\nNEWS ADVISORY SUMMARY")
        latest_news = news.groupby("symbol").tail(1)
        for _, r in latest_news.iterrows():
            print(f"  {r.get('symbol',''):<8} articles={r.get('article_count','')} risk_hits={r.get('risk_hits','')} sample={str(r.get('headline_sample',''))[:100]}")

    print("\nDIAGNOSTIC SUGGESTIONS")
    if total_pl < 0:
        print("  - Total P/L is negative: consider scan-only mode, lower trade size, or higher score thresholds.")
    if dd_pct < -10:
        print("  - Drawdown is large: reduce max_open_positions or lower trade_size.")
    if not trades.empty and len(trades[trades.get("event", "") == "OPEN"]) == 0:
        print("  - No trades opened: account size may be too small for options; use scan-only or equity-only mode.")
    print("  - For $100 paper tests, keep max_open_positions=1 and max_new_positions_per_cycle=1.")
    print("  - Treat news as advisory only; do not let headlines force trades.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
