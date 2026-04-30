#!/usr/bin/env python3
"""
Analyze BTC/ETH/SOL Paper Bot v13 CSV logs.

Reads:
- logs/paper_trades_v13.csv
- logs/paper_equity_log_v13.csv
- logs/paper_daily_pnl_v13.csv
- logs/paper_tax_capital_gains_v13.csv

Prints:
- Account performance
- Bot vs BTC/ETH/SOL/equal-weight buy-and-hold benchmarks
- Drawdown
- Closed-trade stats
- Fees and estimated after-tax P/L
- P/L by asset
- Latest local and UTC timestamps when available
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = Path(os.environ.get("INVESTAI_LOG_DIR", BASE_DIR / "logs")).expanduser()


def money(x: float) -> str:
    return f"${x:,.2f}"


def pct(x: float) -> str:
    return f"{x:.2f}%"


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def as_float_series(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[col], errors="coerce").fillna(0.0)


def max_drawdown(equity: pd.Series) -> tuple[float, float]:
    if equity.empty:
        return 0.0, 0.0
    running_peak = equity.cummax()
    dd = equity - running_peak
    dd_pct = (dd / running_peak.replace(0, pd.NA)) * 100
    return float(dd.min()), float(dd_pct.min())


def return_pct(final: float, start: float) -> float:
    return (final - start) / start * 100 if start else 0.0


def print_benchmark(name: str, start_equity: float, final_equity: float, bot_final: float) -> None:
    if final_equity <= 0:
        print(f"{name:28s} unavailable")
        return
    alpha = bot_final - final_equity
    print(f"{name:28s} {money(final_equity):>14s}  return {pct(return_pct(final_equity, start_equity)):>9s}  bot alpha {money(alpha):>12s}")


def analyze(log_dir: Path) -> int:
    trades = read_csv(log_dir / "paper_trades_v13.csv")
    equity = read_csv(log_dir / "paper_equity_log_v13.csv")
    daily = read_csv(log_dir / "paper_daily_pnl_v13.csv")
    tax = read_csv(log_dir / "paper_tax_capital_gains_v13.csv")

    print("\nBTC/ETH/SOL PAPER BOT v13 PERFORMANCE REPORT")
    print("=" * 80)

    if equity.empty:
        print("No equity log found yet. Run the bot first.")
        return 1

    equity_series = as_float_series(equity, "equity")
    final_equity = float(equity_series.iloc[-1])
    start_equity = float(equity_series.iloc[0])
    total_pl = final_equity - start_equity
    total_pl_pct = return_pct(final_equity, start_equity)
    dd_usd, dd_pct = max_drawdown(equity_series)

    print(f"Start equity:              {money(start_equity)}")
    print(f"Final equity:              {money(final_equity)}")
    print(f"Total P/L:                 {money(total_pl)} ({pct(total_pl_pct)})")
    print(f"Max drawdown:              {money(dd_usd)} ({pct(dd_pct)})")

    if "cash_yield_total" in equity:
        print(f"Idle cash yield total:     {money(float(as_float_series(equity, 'cash_yield_total').iloc[-1]))}")

    if any(c in equity.columns for c in ["open_entry_fees_usd", "open_est_exit_fees_usd", "open_market_move_pl_usd", "open_net_liquidation_pl_usd"]):
        print("\nOpen-position cost breakdown, latest snapshot")
        print("-" * 80)
        for label, col in [
            ("Open entry fees paid", "open_entry_fees_usd"),
            ("Open estimated exit fees", "open_est_exit_fees_usd"),
            ("Open market-move P/L", "open_market_move_pl_usd"),
            ("Open net liquidation P/L", "open_net_liquidation_pl_usd"),
        ]:
            if col in equity:
                print(f"{label:28s} {money(float(as_float_series(equity, col).iloc[-1]))}")

    print("\nBot vs buy-and-hold benchmarks")
    print("-" * 80)
    print_benchmark("BTC buy-and-hold", start_equity, float(as_float_series(equity, "benchmark_btc_equity").iloc[-1]), final_equity)
    print_benchmark("ETH buy-and-hold", start_equity, float(as_float_series(equity, "benchmark_eth_equity").iloc[-1]), final_equity)
    if "benchmark_sol_equity" in equity.columns:
        print_benchmark("SOL buy-and-hold", start_equity, float(as_float_series(equity, "benchmark_sol_equity").iloc[-1]), final_equity)
    print_benchmark("Equal-weight BTC/ETH/SOL", start_equity, float(as_float_series(equity, "benchmark_equal_weight_equity").iloc[-1]), final_equity)

    if not trades.empty:
        buys = trades[trades["side"] == "BUY"] if "side" in trades else pd.DataFrame()
        sells = trades[trades["side"] == "SELL"] if "side" in trades else pd.DataFrame()
        total_fees = float(as_float_series(trades, "fee_usd").sum())
        total_trade_costs = float(as_float_series(trades, "trade_cost_usd").sum())
        print("\nTrade activity")
        print("-" * 80)
        print(f"Buy trades:                {len(buys)}")
        print(f"Sell trades:               {len(sells)}")
        print(f"Total logged fees:         {money(total_fees)}")
        print(f"Total trade costs:         {money(total_trade_costs)}")
        if len(trades):
            print(f"Average fee/trade:         {money(total_fees / len(trades))}")

    if not tax.empty:
        gains = as_float_series(tax, "gain_loss_usd")
        wins = gains[gains > 0]
        losses = gains[gains < 0]
        total_gain = float(gains.sum())
        after_tax = as_float_series(tax, "after_tax_gain_loss_usd")
        total_after_tax = float(after_tax.sum()) if not after_tax.empty else total_gain
        total_tax = float(as_float_series(tax, "estimated_tax_usd").sum())
        total_tax_savings = float(as_float_series(tax, "estimated_tax_savings_usd").sum())
        gross_wins = float(wins.sum()) if len(wins) else 0.0
        gross_losses = abs(float(losses.sum())) if len(losses) else 0.0
        profit_factor = (gross_wins / gross_losses) if gross_losses else float("inf")

        print("\nClosed-trade stats")
        print("-" * 80)
        print(f"Closed trades:             {len(tax)}")
        print(f"Win rate:                  {pct(len(wins) / len(tax) * 100) if len(tax) else '0.00%'}")
        print(f"Average win:               {money(float(wins.mean())) if len(wins) else '$0.00'}")
        print(f"Average loss:              {money(float(losses.mean())) if len(losses) else '$0.00'}")
        print(f"Profit factor:             {profit_factor:.3f}" if profit_factor != float("inf") else "Profit factor:             inf")
        print(f"Pre-tax closed P/L:        {money(total_gain)}")
        print(f"Estimated tax:             {money(total_tax)}")
        print(f"Estimated tax savings:     {money(total_tax_savings)}")
        print(f"After-tax est. closed P/L: {money(total_after_tax)}")
        print(f"Best trade:                {money(float(gains.max()))}")
        print(f"Worst trade:               {money(float(gains.min()))}")

        if "asset" in tax:
            by_asset = tax.groupby("asset")["gain_loss_usd"].sum().sort_values(ascending=False)
            by_asset_after = tax.groupby("asset")["after_tax_gain_loss_usd"].sum().sort_values(ascending=False) if "after_tax_gain_loss_usd" in tax else by_asset
            print("\nP/L by asset")
            print("-" * 80)
            for asset, value in by_asset.items():
                aft = float(by_asset_after.get(asset, value))
                print(f"{asset:8s} pre-tax {money(float(value)):>12s}   after-tax est. {money(aft):>12s}")

    if not daily.empty:
        print("\nLatest daily snapshots")
        print("-" * 80)
        cols = [c for c in ["timestamp_local", "date_local", "timestamp_utc", "date_utc", "current_equity", "daily_pl", "daily_pl_pct", "alpha_vs_equal_weight_usd"] if c in daily.columns]
        print(daily[cols].tail(8).to_string(index=False))

    print("\nFiles analyzed:")
    print(f"  {log_dir}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze BTC/ETH/SOL paper bot v13 performance logs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--log-dir", type=Path, default=LOG_DIR, help="Folder containing v13 CSV log files.")
    args = parser.parse_args()
    return analyze(args.log_dir)


if __name__ == "__main__":
    raise SystemExit(main())
