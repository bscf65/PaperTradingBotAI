#!/usr/bin/env python3
"""Analyze Options ETF Paper Bot v4 logs."""

from __future__ import annotations

import os
from pathlib import Path
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = Path(os.environ.get("INVESTAI_LOG_DIR", BASE_DIR / "logs")).expanduser()
TRADES_FILE = LOG_DIR / "options_trades_v4.csv"
EQUITY_FILE = LOG_DIR / "options_equity_v4.csv"
SCAN_FILE = LOG_DIR / "options_scan_v4.csv"
NEWS_FILE = LOG_DIR / "options_news_v4.csv"


def money(x: float) -> str:
    return f"${x:,.2f}"


def main() -> int:
    print("\nOPTIONS ETF PAPER BOT v4 ANALYZER")
    print("=" * 72)
    if not EQUITY_FILE.exists():
        print(f"No equity log found: {EQUITY_FILE}")
        print("Run the bot first.")
        return 0

    eq = pd.read_csv(EQUITY_FILE)
    if eq.empty:
        print("Equity log is empty.")
        return 0
    eq["equity"] = pd.to_numeric(eq["equity"], errors="coerce")
    eq = eq.dropna(subset=["equity"])
    start = float(eq["equity"].iloc[0])
    final = float(eq["equity"].iloc[-1])
    total_pl = final - start
    running_max = eq["equity"].cummax()
    drawdown = eq["equity"] - running_max
    max_dd = float(drawdown.min()) if not drawdown.empty else 0.0
    max_dd_pct = float((drawdown / running_max).min() * 100) if not drawdown.empty else 0.0

    print(f"Start equity:       {money(start)}")
    print(f"Final equity:       {money(final)}")
    print(f"Total P/L:          {money(total_pl)} ({(total_pl/start*100 if start else 0):.2f}%)")
    print(f"Max drawdown:       {money(max_dd)} ({max_dd_pct:.2f}%)")

    if TRADES_FILE.exists():
        tr = pd.read_csv(TRADES_FILE)
        print("\nTRADES")
        print("-" * 72)
        print(f"Total trade rows:   {len(tr)}")
        if not tr.empty:
            print(tr.groupby(["instrument", "strategy", "side"]).size().to_string())
            closes = tr[pd.to_numeric(tr.get("realized_pl", 0), errors="coerce").fillna(0) != 0].copy()
            if not closes.empty:
                closes["realized_pl"] = pd.to_numeric(closes["realized_pl"], errors="coerce").fillna(0)
                wins = closes[closes["realized_pl"] > 0]
                losses = closes[closes["realized_pl"] < 0]
                gross_wins = wins["realized_pl"].sum()
                gross_losses = abs(losses["realized_pl"].sum())
                profit_factor = gross_wins / gross_losses if gross_losses else float("inf")
                print(f"Closed P/L rows:    {len(closes)}")
                print(f"Win rate:           {(len(wins)/len(closes)*100 if len(closes) else 0):.2f}%")
                print(f"Average win:        {money(wins['realized_pl'].mean() if len(wins) else 0)}")
                print(f"Average loss:       {money(losses['realized_pl'].mean() if len(losses) else 0)}")
                print(f"Profit factor:      {profit_factor:.2f}" if profit_factor != float("inf") else "Profit factor:      inf")
                print("\nP/L by symbol:")
                print(closes.groupby("symbol")["realized_pl"].sum().round(2).to_string())
            else:
                print("No closed trades with realized P/L yet.")

    if SCAN_FILE.exists():
        sc = pd.read_csv(SCAN_FILE)
        if not sc.empty:
            print("\nSCAN SUMMARY")
            print("-" * 72)
            for col in ["bull_score", "bear_score"]:
                sc[col] = pd.to_numeric(sc[col], errors="coerce")
            print("Average scores by symbol:")
            print(sc.groupby("symbol")[["bull_score", "bear_score"]].mean().round(2).to_string())
            print("\nConsensus counts:")
            print(sc.groupby(["symbol", "consensus"]).size().to_string())

    if NEWS_FILE.exists():
        news = pd.read_csv(NEWS_FILE)
        if not news.empty:
            print("\nNEWS ADVISORY SUMMARY")
            print("-" * 72)
            for col in ["article_count", "risk_hits", "positive_hits"]:
                news[col] = pd.to_numeric(news[col], errors="coerce").fillna(0)
            print(news.groupby("symbol")[["article_count", "risk_hits", "positive_hits"]].sum().round(0).to_string())

    print("\nDIAGNOSTIC NOTES")
    print("-" * 72)
    if total_pl < 0:
        print("- Bot is losing so far. Check whether losses are mostly options premium decay, bad direction, or wide spreads.")
    if max_dd_pct < -10:
        print("- Drawdown is large. Reduce trade size, raise min_score, or use scan-only mode longer.")
    print("- Compare long calls vs long puts separately. A two-way bot can still be biased if market regime is choppy.")
    print("- News is advisory only. Do not treat headline counts as trade recommendations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
