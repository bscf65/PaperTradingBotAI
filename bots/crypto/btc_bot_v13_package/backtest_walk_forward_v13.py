#!/usr/bin/env python3
"""
Walk-forward backtest harness for the BTC/ETH/SOL paper bot.

This is a research tool only. It never places orders and never connects to
private broker/exchange APIs. It evaluates strategies on historical candle CSVs
using conservative paper assumptions: spread, fees, slippage, missed fills, and
estimated federal/state taxes.
"""

from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def normalize_rate(rate: float) -> float:
    rate = float(rate)
    if rate > 1.0:
        rate /= 100.0
    return max(0.0, min(1.0, rate))


def money(value: float) -> str:
    return f"${value:,.2f}"


def pct(value: float) -> str:
    return f"{value:.2f}%"


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50)


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.ewm(alpha=1 / period, adjust=False).mean()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
    df["RSI14"] = calculate_rsi(df["Close"], 14)
    df["ATR14"] = calculate_atr(df, 14)
    df["RET_5"] = df["Close"].pct_change(5)
    df["RET_15"] = df["Close"].pct_change(15)
    df["RET_30"] = df["Close"].pct_change(30)
    df["HIGH_30_PREV"] = df["High"].shift(1).rolling(30, min_periods=5).max()
    df["LOW_30_PREV"] = df["Low"].shift(1).rolling(30, min_periods=5).min()
    df["VOL_MA20"] = df["Volume"].rolling(20, min_periods=1).mean()
    return df.dropna().reset_index(drop=True)


def load_candles(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    rename = {c: c.strip().title() for c in df.columns}
    rename.update({"time": "time", "timestamp": "time", "date": "time"})
    df = df.rename(columns=rename)
    required = ["time", "Open", "High", "Low", "Close", "Volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"{path} missing required candle columns: {missing}")
    df["time"] = pd.to_datetime(df["time"], utc=True)
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=required).sort_values("time").drop_duplicates("time").reset_index(drop=True)
    if len(df) < 120:
        raise ValueError(f"{path} needs at least 120 candles for walk-forward testing")
    return add_indicators(df)


@dataclass(frozen=True)
class StrategySpec:
    name: str
    threshold: float
    stop_atr: float
    take_profit_atr: float
    trailing_atr: float
    max_hold_bars: int


@dataclass
class Metrics:
    strategy: str
    segment: str
    bars: int
    start_equity: float
    final_equity: float
    total_return_pct: float
    buy_hold_return_pct: float
    alpha_pct: float
    max_drawdown_pct: float
    sharpe_like: float
    trades: int
    win_rate_pct: float
    avg_win: float
    avg_loss: float
    expectancy: float
    after_tax_pl: float
    fee_rate: float
    slippage_bps: float
    synthetic_spread_pct: float
    missed_fill_rate: float


def missed_fill(product: str, side: str, timestamp: pd.Timestamp, price: float, base_rate: float, spread_pct: float) -> bool:
    probability = max(0.0, min(0.50, normalize_rate(base_rate) + min(0.08, spread_pct * 4)))
    if probability <= 0:
        return False
    key = f"{timestamp.isoformat()}|{product}|{side}|{price:.2f}"
    sample = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
    return sample < probability


def signal_for(row: pd.Series, spec: StrategySpec) -> tuple[bool, str]:
    close = float(row["Close"])
    if spec.name == "buy_hold":
        return True, "buy_hold_entry"
    if spec.name == "momentum":
        score = 0.0
        score += 30 if close > float(row["EMA50"]) and float(row["EMA20"]) > float(row["EMA50"]) else 0
        score += 20 if float(row["RET_15"]) > 0.002 else 0
        score += 15 if float(row["RET_30"]) > 0.004 else 0
        score += 15 if 45 <= float(row["RSI14"]) <= 72 else 0
        return score >= spec.threshold, f"momentum_score={score:.1f}"
    if spec.name == "mean_reversion":
        below_ema = close < float(row["EMA20"]) * 0.995
        oversold = float(row["RSI14"]) <= spec.threshold
        trend_ok = close >= float(row["EMA50"]) * 0.985
        return bool(below_ema and oversold and trend_ok), "mean_reversion_pullback"
    if spec.name == "breakout":
        vol_ok = float(row["Volume"]) >= float(row["VOL_MA20"]) * 1.05
        breakout = close > float(row["HIGH_30_PREV"]) * (1 + spec.threshold)
        return bool(vol_ok and breakout), "breakout_30_high"
    if spec.name == "volatility_filter":
        atr_pct = float(row["ATR14"]) / close if close else 0.0
        trend_ok = close > float(row["EMA50"])
        rsi_ok = 40 <= float(row["RSI14"]) <= 70
        vol_ok = 0.0015 <= atr_pct <= spec.threshold
        return bool(trend_ok and rsi_ok and vol_ok), f"atr_pct={atr_pct:.4f}"
    raise ValueError(f"unknown strategy: {spec.name}")


def tax_after_pl(gain_loss: float, args: argparse.Namespace) -> tuple[float, float]:
    rate = normalize_rate(args.estimated_short_term_tax_rate) + normalize_rate(args.estimated_state_tax_rate)
    rate = max(0.0, min(1.0, rate))
    if gain_loss > 0:
        tax = gain_loss * rate
        return gain_loss - tax, tax
    return gain_loss, 0.0


def close_position(
    cash: float,
    qty: float,
    cost_basis: float,
    exit_price: float,
    fee_rate: float,
    args: argparse.Namespace,
) -> tuple[float, float, float]:
    proceeds_gross = qty * exit_price
    fee = proceeds_gross * fee_rate
    proceeds_net = proceeds_gross - fee
    realized = proceeds_net - cost_basis
    after_tax, _tax = tax_after_pl(realized, args)
    return cash + proceeds_net, realized, after_tax


def run_strategy(df: pd.DataFrame, spec: StrategySpec, args: argparse.Namespace, segment: str, product: str) -> Metrics:
    cash = float(args.paper_cash)
    start_cash = cash
    qty = 0.0
    cost_basis = 0.0
    entry_price = 0.0
    entry_bar = 0
    highest = 0.0
    realized_after_tax: list[float] = []
    realized_pre_tax: list[float] = []
    equity_curve: list[float] = []
    spread = normalize_rate(args.synthetic_spread_pct)
    fee_rate = normalize_rate(args.fee_rate)
    slip = max(0.0, float(args.slippage_bps) / 10_000.0)

    for i, row in df.iterrows():
        close = float(row["Close"])
        atr = max(0.0, float(row["ATR14"]))
        bid = close * (1 - spread / 2)
        ask = close * (1 + spread / 2)

        if qty > 0:
            highest = max(highest, close)
            sell_reason = (
                spec.name != "buy_hold"
                and (
                    close <= entry_price - spec.stop_atr * atr
                    or close >= entry_price + spec.take_profit_atr * atr
                    or close <= highest - spec.trailing_atr * atr
                    or (i - entry_bar) >= spec.max_hold_bars
                )
            )
            if sell_reason and not missed_fill(product, "SELL", row["time"], close, args.missed_fill_rate, spread):
                exec_price = bid * (1 - slip)
                cash, pre_tax, after_tax = close_position(cash, qty, cost_basis, exec_price, fee_rate, args)
                realized_pre_tax.append(pre_tax)
                realized_after_tax.append(after_tax)
                qty = 0.0
                cost_basis = 0.0
                entry_price = 0.0

        if qty <= 0:
            buy, _reason = signal_for(row, spec)
            if buy and cash >= 10 and not missed_fill(product, "BUY", row["time"], close, args.missed_fill_rate, spread):
                gross_spend = min(cash, float(args.trade_size))
                fee = gross_spend * fee_rate
                exec_price = ask * (1 + slip)
                qty = (gross_spend - fee) / exec_price
                if qty > 0:
                    cash -= gross_spend
                    cost_basis = gross_spend
                    entry_price = exec_price
                    highest = close
                    entry_bar = int(i)

        liquidation = cash + qty * bid * (1 - slip) * (1 - fee_rate)
        equity_curve.append(liquidation)

    if qty > 0:
        row = df.iloc[-1]
        close = float(row["Close"])
        bid = close * (1 - spread / 2)
        cash, pre_tax, after_tax = close_position(cash, qty, cost_basis, bid * (1 - slip), fee_rate, args)
        realized_pre_tax.append(pre_tax)
        realized_after_tax.append(after_tax)
        equity_curve[-1] = cash

    equity = pd.Series(equity_curve, dtype=float)
    returns = equity.pct_change().dropna()
    sharpe_like = float((returns.mean() / returns.std()) * (len(returns) ** 0.5)) if len(returns) >= 2 and float(returns.std()) > 0 else 0.0
    peak = equity.cummax()
    dd_pct = ((equity - peak) / peak.replace(0, np.nan) * 100).min()
    gains = pd.Series(realized_pre_tax, dtype=float)
    wins = gains[gains > 0]
    losses = gains[gains < 0]
    buy_hold = start_cash * float(df["Close"].iloc[-1]) / float(df["Close"].iloc[0])

    return Metrics(
        strategy=spec.name,
        segment=segment,
        bars=len(df),
        start_equity=start_cash,
        final_equity=float(equity.iloc[-1]),
        total_return_pct=(float(equity.iloc[-1]) - start_cash) / start_cash * 100 if start_cash else 0.0,
        buy_hold_return_pct=(buy_hold - start_cash) / start_cash * 100 if start_cash else 0.0,
        alpha_pct=(float(equity.iloc[-1]) - buy_hold) / start_cash * 100 if start_cash else 0.0,
        max_drawdown_pct=float(dd_pct) if pd.notna(dd_pct) else 0.0,
        sharpe_like=sharpe_like,
        trades=len(gains),
        win_rate_pct=(len(wins) / len(gains) * 100) if len(gains) else 0.0,
        avg_win=float(wins.mean()) if len(wins) else 0.0,
        avg_loss=float(losses.mean()) if len(losses) else 0.0,
        expectancy=float(gains.mean()) if len(gains) else 0.0,
        after_tax_pl=float(sum(realized_after_tax)),
        fee_rate=fee_rate,
        slippage_bps=float(args.slippage_bps),
        synthetic_spread_pct=spread,
        missed_fill_rate=normalize_rate(args.missed_fill_rate),
    )


def candidates() -> list[StrategySpec]:
    return [
        StrategySpec("buy_hold", 0.0, 0.0, 0.0, 0.0, 10_000),
        StrategySpec("momentum", 50, 2.0, 4.0, 2.5, 80),
        StrategySpec("momentum", 65, 2.0, 5.0, 3.0, 100),
        StrategySpec("mean_reversion", 38, 1.8, 2.5, 2.0, 60),
        StrategySpec("mean_reversion", 32, 2.2, 3.0, 2.5, 90),
        StrategySpec("breakout", 0.000, 2.2, 4.5, 3.0, 100),
        StrategySpec("breakout", 0.003, 2.5, 5.0, 3.2, 120),
        StrategySpec("volatility_filter", 0.012, 2.0, 4.0, 2.5, 90),
    ]


def score_train(metrics: Metrics, min_trades: int) -> tuple[float, bool]:
    enough = metrics.trades >= min_trades
    positive = metrics.after_tax_pl > 0 and metrics.expectancy > 0 and metrics.alpha_pct >= 0
    score = metrics.after_tax_pl + metrics.alpha_pct * 10 + metrics.sharpe_like * 5 + metrics.max_drawdown_pct
    return score, bool(enough and positive)


def walk_forward(df: pd.DataFrame, args: argparse.Namespace, product: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    promotions: list[dict[str, Any]] = []
    start = 0
    fold = 1
    while start + args.train_bars + args.test_bars <= len(df):
        train = df.iloc[start : start + args.train_bars].reset_index(drop=True)
        test = df.iloc[start + args.train_bars : start + args.train_bars + args.test_bars].reset_index(drop=True)
        train_results = [(spec, run_strategy(train, spec, args, f"fold_{fold}_train", product)) for spec in candidates()]
        scored = [(spec, metrics, *score_train(metrics, args.min_train_trades)) for spec, metrics in train_results]
        scored.sort(key=lambda item: item[2], reverse=True)
        best_spec, best_train, _score, train_passed = scored[0]
        best_test = run_strategy(test, best_spec, args, f"fold_{fold}_test", product)
        test_passed = train_passed and best_test.after_tax_pl > 0 and best_test.expectancy > 0 and best_test.alpha_pct >= 0

        for spec, metrics in train_results:
            row = metrics.__dict__.copy()
            row["fold"] = fold
            row["product"] = product
            row["phase"] = "train"
            row["variant"] = strategy_variant(spec)
            row["selected"] = spec == best_spec
            rows.append(row)

        for spec, _train_metrics in train_results:
            metrics = run_strategy(test, spec, args, f"fold_{fold}_test", product)
            row = metrics.__dict__.copy()
            row["fold"] = fold
            row["product"] = product
            row["phase"] = "test"
            row["variant"] = strategy_variant(spec)
            row["selected"] = spec == best_spec
            rows.append(row)
        promotions.append(
            {
                "fold": fold,
                "product": product,
                "strategy": best_spec.name,
                "variant": strategy_variant(best_spec),
                "train_passed": train_passed,
                "test_passed": test_passed,
                "train_after_tax_pl": best_train.after_tax_pl,
                "test_after_tax_pl": best_test.after_tax_pl,
                "test_expectancy": best_test.expectancy,
                "test_alpha_pct": best_test.alpha_pct,
                "decision": "candidate_for_promotion" if test_passed else "reject_or_collect_more_data",
            }
        )
        start += args.step_bars
        fold += 1

    if not rows:
        raise ValueError("not enough candles for one train/test fold")
    return pd.DataFrame(rows), pd.DataFrame(promotions)


def strategy_variant(spec: StrategySpec) -> str:
    return (
        f"{spec.name}"
        f"_thr{spec.threshold:g}"
        f"_stop{spec.stop_atr:g}"
        f"_tp{spec.take_profit_atr:g}"
        f"_trail{spec.trailing_atr:g}"
        f"_hold{spec.max_hold_bars}"
    )


def summarize_by_category(results: pd.DataFrame) -> pd.DataFrame:
    test = results[results["phase"] == "test"].copy()
    if test.empty:
        return pd.DataFrame()
    grouped = test.groupby("strategy", as_index=False).agg(
        folds=("fold", "nunique"),
        variants=("variant", "nunique"),
        total_after_tax_pl=("after_tax_pl", "sum"),
        mean_expectancy=("expectancy", "mean"),
        mean_alpha_pct=("alpha_pct", "mean"),
        mean_return_pct=("total_return_pct", "mean"),
        worst_drawdown_pct=("max_drawdown_pct", "min"),
        total_trades=("trades", "sum"),
    )
    grouped["decision_note"] = np.where(
        (grouped["total_after_tax_pl"] > 0) & (grouped["mean_expectancy"] > 0) & (grouped["mean_alpha_pct"] >= 0),
        "category_positive_out_of_sample",
        "category_not_promoted",
    )
    return grouped.sort_values(["decision_note", "total_after_tax_pl"], ascending=[True, False])


def main() -> int:
    parser = argparse.ArgumentParser(description="Walk-forward paper backtest using historical candle CSV data.")
    parser.add_argument("--csv", type=Path, required=True, help="Historical candle CSV with time, Open, High, Low, Close, Volume columns.")
    parser.add_argument("--product", default="BTC-USD")
    parser.add_argument("--paper-cash", type=float, default=10_000.0)
    parser.add_argument("--trade-size", type=float, default=500.0)
    parser.add_argument("--fee-rate", type=float, default=0.006)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--synthetic-spread-pct", type=float, default=0.001)
    parser.add_argument("--missed-fill-rate", type=float, default=0.02)
    parser.add_argument("--estimated-short-term-tax-rate", type=float, default=0.22)
    parser.add_argument("--estimated-state-tax-rate", type=float, default=0.093)
    parser.add_argument("--train-bars", type=int, default=600)
    parser.add_argument("--test-bars", type=int, default=200)
    parser.add_argument("--step-bars", type=int, default=200)
    parser.add_argument("--min-train-trades", type=int, default=5)
    parser.add_argument("--out-dir", type=Path, default=Path("reports/backtests"))
    args = parser.parse_args()

    df = load_candles(args.csv)
    results, promotions = walk_forward(df, args, args.product)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.csv.stem
    results_path = args.out_dir / f"{stem}_walk_forward_results.csv"
    promotions_path = args.out_dir / f"{stem}_walk_forward_decisions.csv"
    category_path = args.out_dir / f"{stem}_strategy_category_summary.csv"
    category_summary = summarize_by_category(results)
    results.to_csv(results_path, index=False)
    promotions.to_csv(promotions_path, index=False)
    category_summary.to_csv(category_path, index=False)

    print("\nWalk-forward backtest complete")
    print("=" * 80)
    print(f"Input candles:        {args.csv} ({len(df)} usable rows)")
    print(f"Results CSV:          {results_path}")
    print(f"Promotion decisions:  {promotions_path}")
    print(f"Category summary:     {category_path}")
    print("\nPromotion summary")
    print("-" * 80)
    print(promotions.to_string(index=False))
    if not category_summary.empty:
        print("\nStrategy category out-of-sample summary")
        print("-" * 80)
        print(category_summary.to_string(index=False))
    accepted = int((promotions["decision"] == "candidate_for_promotion").sum())
    print(f"\nAccepted folds:       {accepted}/{len(promotions)}")
    print("Rule: promote only when train and out-of-sample test are positive after costs/taxes and alpha is non-negative.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
