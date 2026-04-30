#!/usr/bin/env python3
"""
BTC/ETH/SOL Coinbase Public-Data Paper Trading Bot v13

What it does:
- Uses Coinbase Exchange public market-data endpoints only. No API keys. No live orders.
- Simulates BTC/ETH/SOL spot trades using bid/ask-aware paper execution.
- Tracks cash, positions, realized/unrealized P/L, daily P/L, kill-switch halts, and idle cash yield.
- Exports a simulated capital-gains CSV for recordkeeping/tax-prep review.
- Compares the bot against simple buy-and-hold BTC, ETH, and equal-weight BTC/ETH/SOL benchmarks.
- Adds spread filters, drawdown risk ladder, daily profit lock, and configurable fee presets.

Important:
- This is a paper-trading simulator, not tax, legal, or financial advice.
- The capital-gains CSV is only for simulated trades made by this script.
- For real taxable trades, reconcile against Coinbase records and a tax professional/software.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import numpy as np
import pandas as pd
import requests

COINBASE_EXCHANGE_API = "https://api.exchange.coinbase.com"
DEFAULT_PRODUCTS = ["BTC-USD", "ETH-USD", "SOL-USD"]

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = Path(os.environ.get("INVESTAI_LOG_DIR", BASE_DIR / "logs")).expanduser()
STATE_FILE = LOG_DIR / "paper_state_v13.json"
TRADES_FILE = LOG_DIR / "paper_trades_v13.csv"
EQUITY_FILE = LOG_DIR / "paper_equity_log_v13.csv"
DAILY_FILE = LOG_DIR / "paper_daily_pnl_v13.csv"
TAX_FILE = LOG_DIR / "paper_tax_capital_gains_v13.csv"
RESEARCH_FILE = LOG_DIR / "paper_research_log_v13.csv"

USER_AGENT = "btc-eth-sol-paper-bot-v13/1.0"

ANSI_RED = "\033[91m"
ANSI_YELLOW = "\033[93m"
ANSI_RESET = "\033[0m"


def color_enabled(args: argparse.Namespace) -> bool:
    """Return True when terminal color should be used."""
    return not getattr(args, "no_color", False) and sys.stdout.isatty()


def color_text(text: str, color: str, args: argparse.Namespace) -> str:
    if not color_enabled(args):
        return text
    if color == "red":
        return f"{ANSI_RED}{text}{ANSI_RESET}"
    if color == "yellow":
        return f"{ANSI_YELLOW}{text}{ANSI_RESET}"
    return text


def terminal_beep(args: argparse.Namespace, count: int | None = None) -> None:
    """Emit terminal bells. Some terminals mute bells; this is best-effort."""
    if getattr(args, "no_beep", False):
        return
    beep_count = int(count if count is not None else getattr(args, "beep_count", 3))
    for _ in range(max(0, beep_count)):
        sys.stdout.write("\a")
        sys.stdout.flush()
        time.sleep(0.15)


def desktop_popup(title: str, message: str, args: argparse.Namespace) -> bool:
    """Best-effort Linux desktop popup for absolute stop events."""
    if getattr(args, "no_popup", False):
        return False

    commands: list[list[str]] = []
    if shutil.which("notify-send"):
        commands.append(["notify-send", "-u", "critical", title, message])
    if shutil.which("zenity"):
        commands.append(["zenity", "--warning", f"--title={title}", f"--text={message}"])
    if shutil.which("xmessage"):
        commands.append(["xmessage", "-center", f"{title}\n\n{message}"])

    for cmd in commands:
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            continue
    return False


def alert_once(state: dict[str, Any], key: str, args: argparse.Namespace, *, color: str, title: str, message: str, popup: bool = False) -> None:
    """Print/alert only once per unique key+message combination."""
    prior = state.get(key, "")
    if prior == message:
        return
    state[key] = message
    print(color_text(message, color, args))
    terminal_beep(args)
    if popup:
        shown = desktop_popup(title, message, args)
        if not shown:
            print(color_text("Popup not shown: notify-send/zenity/xmessage unavailable or desktop notification failed.", color, args))


def utc_now() -> datetime:
    """Current UTC time with timezone info."""
    return datetime.now(timezone.utc)


def local_now() -> datetime:
    """Current local computer time with timezone info.

    This uses the operating system timezone from the computer running the bot.
    On Kali/Linux, check it with: timedatectl
    """
    return datetime.now().astimezone()


def now_iso() -> str:
    """UTC timestamp retained for exchange/data consistency."""
    return utc_now().replace(microsecond=0).isoformat()


def local_now_iso() -> str:
    """Local computer-time timestamp for readable logs and CSV files."""
    return local_now().replace(microsecond=0).isoformat()


def today_utc() -> str:
    return utc_now().date().isoformat()


def today_local() -> str:
    return local_now().date().isoformat()


def safe_float(value: Any, default: float = float("nan")) -> float:
    try:
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except (TypeError, ValueError):
        return default


def usd(value: Any) -> float:
    """Round a numeric value for dollar-denominated CSV columns."""
    return round(safe_float(value, 0.0), 2)


def qty8(value: Any) -> float:
    """Round crypto quantity for readable CSV output while preserving useful precision."""
    return round(safe_float(value, 0.0), 8)


def pct6(value: Any) -> float:
    """Round rate/percentage decimal values for CSV output."""
    return round(safe_float(value, 0.0), 6)


def ensure_dirs() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def ensure_csv(path: Path, header: list[str]) -> None:
    ensure_dirs()
    if not path.exists():
        with path.open("w", newline="") as f:
            csv.writer(f).writerow(header)


def append_csv(path: Path, row: dict[str, Any], header: list[str]) -> None:
    ensure_csv(path, header)
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writerow({key: row.get(key, "") for key in header})


def reset_files() -> None:
    ensure_dirs()
    for path in [STATE_FILE, TRADES_FILE, EQUITY_FILE, DAILY_FILE, TAX_FILE, RESEARCH_FILE]:
        if path.exists():
            path.unlink()


def product_to_asset(product_id: str) -> str:
    return product_id.split("-")[0]


def request_json(
    url: str,
    params: dict[str, Any] | None = None,
    timeout: int = 15,
    retries: int = 3,
    backoff_seconds: float = 1.25,
) -> Any:
    """Fetch JSON with small retry/backoff handling for public market-data hiccups."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    last_exc: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last_exc = exc
            if attempt >= retries:
                break
            time.sleep(backoff_seconds * attempt)

    raise RuntimeError(f"request failed after {retries} attempts: {url} params={params} error={last_exc}")


def fetch_coinbase_candles(product_id: str, granularity: int) -> pd.DataFrame:
    """Fetch latest Coinbase Exchange candles.

    Coinbase Exchange public candles format:
      [time, low, high, open, close, volume]
    Usually returns latest candles in reverse chronological order.
    """
    url = f"{COINBASE_EXCHANGE_API}/products/{product_id}/candles"
    data = request_json(url, params={"granularity": granularity})

    if not isinstance(data, list) or not data:
        raise RuntimeError(f"No candle data returned for {product_id}: {data}")

    rows = []
    for candle in data:
        if len(candle) < 6:
            continue
        ts, low, high, open_, close, volume = candle[:6]
        rows.append(
            {
                "time": pd.to_datetime(int(ts), unit="s", utc=True),
                "Open": safe_float(open_),
                "High": safe_float(high),
                "Low": safe_float(low),
                "Close": safe_float(close),
                "Volume": safe_float(volume),
            }
        )

    df = pd.DataFrame(rows).dropna()
    if df.empty:
        raise RuntimeError(f"Coinbase candle dataframe empty for {product_id}")

    df = df.sort_values("time").drop_duplicates(subset=["time"]).reset_index(drop=True)
    return df


def fetch_coinbase_ticker(product_id: str) -> dict[str, float]:
    url = f"{COINBASE_EXCHANGE_API}/products/{product_id}/ticker"
    data = request_json(url)
    return {
        "price": safe_float(data.get("price")),
        "bid": safe_float(data.get("bid")),
        "ask": safe_float(data.get("ask")),
        "volume": safe_float(data.get("volume")),
    }


def fetch_coinbase_book_l1(product_id: str) -> dict[str, float]:
    url = f"{COINBASE_EXCHANGE_API}/products/{product_id}/book"
    data = request_json(url, params={"level": 1})
    bids = data.get("bids") or []
    asks = data.get("asks") or []
    bid = safe_float(bids[0][0]) if bids else float("nan")
    ask = safe_float(asks[0][0]) if asks else float("nan")
    return {"bid": bid, "ask": ask}


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


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
    df["VOL_MA20"] = df["Volume"].rolling(20, min_periods=1).mean()
    df["RET_5"] = df["Close"].pct_change(5)
    df["RET_15"] = df["Close"].pct_change(15)
    df["RET_30"] = df["Close"].pct_change(30)
    df["HIGH_30_PREV"] = df["High"].shift(1).rolling(30, min_periods=5).max()
    df["LOW_30_PREV"] = df["Low"].shift(1).rolling(30, min_periods=5).min()
    return df


def volatility_regime(price: float, atr: float) -> tuple[str, float]:
    atr_pct = atr / price if price else 0.0
    if atr_pct < 0.0015:
        return "low", atr_pct
    if atr_pct < 0.006:
        return "normal", atr_pct
    if atr_pct < 0.012:
        return "high", atr_pct
    return "extreme", atr_pct


def spread_pct(bid: float, ask: float, fallback_price: float) -> float:
    if bid > 0 and ask > 0 and ask >= bid:
        mid = (bid + ask) / 2
        return (ask - bid) / mid if mid else 0.0
    return 0.001  # fallback estimate


def build_market_snapshot(product_id: str, granularity: int) -> dict[str, Any]:
    df = add_indicators(fetch_coinbase_candles(product_id, granularity))
    latest = df.iloc[-1]
    ticker = fetch_coinbase_ticker(product_id)

    try:
        book = fetch_coinbase_book_l1(product_id)
    except Exception:
        book = {"bid": ticker.get("bid", float("nan")), "ask": ticker.get("ask", float("nan"))}

    price = safe_float(ticker.get("price"), safe_float(latest["Close"]))
    bid = safe_float(book.get("bid"), safe_float(ticker.get("bid"), price))
    ask = safe_float(book.get("ask"), safe_float(ticker.get("ask"), price))

    regime, atr_pct = volatility_regime(price, safe_float(latest["ATR14"], 0.0))
    spread = spread_pct(bid, ask, price)

    snapshot = {
        "product_id": product_id,
        "asset": product_to_asset(product_id),
        "price": price,
        "bid": bid,
        "ask": ask,
        "spread_pct": spread,
        "time": latest["time"].isoformat(),
        "ema20": safe_float(latest["EMA20"]),
        "ema50": safe_float(latest["EMA50"]),
        "rsi14": safe_float(latest["RSI14"]),
        "atr14": safe_float(latest["ATR14"]),
        "atr_pct": atr_pct,
        "volatility_regime": regime,
        "ret_5": safe_float(latest["RET_5"], 0.0),
        "ret_15": safe_float(latest["RET_15"], 0.0),
        "ret_30": safe_float(latest["RET_30"], 0.0),
        "volume": safe_float(latest["Volume"], 0.0),
        "vol_ma20": safe_float(latest["VOL_MA20"], 0.0),
        "high_30_prev": safe_float(latest["HIGH_30_PREV"], 0.0),
        "low_30_prev": safe_float(latest["LOW_30_PREV"], 0.0),
    }
    snapshot["trade_score"], snapshot["score_reasons"] = score_trade_setup(snapshot)
    return snapshot


def score_trade_setup(s: dict[str, Any]) -> tuple[float, str]:
    score = 0.0
    reasons: list[str] = []

    price = s["price"]
    ema20 = s["ema20"]
    ema50 = s["ema50"]
    rsi = s["rsi14"]
    ret_5 = s["ret_5"]
    ret_15 = s["ret_15"]
    ret_30 = s["ret_30"]
    volume = s["volume"]
    vol_ma20 = s["vol_ma20"]
    spread = s["spread_pct"]
    regime = s["volatility_regime"]
    high_30 = s["high_30_prev"]

    if price > ema50 and ema20 > ema50:
        score += 20
        reasons.append("trend_up")
    elif price > ema50:
        score += 10
        reasons.append("price_above_ema50")
    else:
        score -= 15
        reasons.append("trend_weak")

    momentum_points = 0
    if ret_5 > 0:
        momentum_points += 5
    if ret_15 > 0:
        momentum_points += 7
    if ret_30 > 0:
        momentum_points += 8
    if ret_5 > 0.002 and ret_15 > 0.002:
        momentum_points += 5
    score += momentum_points
    reasons.append(f"momentum_points_{momentum_points}")

    if 45 <= rsi <= 68:
        score += 15
        reasons.append("rsi_healthy")
    elif 35 <= rsi < 45:
        score += 5
        reasons.append("rsi_recovering")
    elif 68 < rsi <= 76:
        score += 3
        reasons.append("rsi_hot")
    else:
        score -= 10
        reasons.append("rsi_unhelpful")

    if high_30 > 0 and price > high_30:
        score += 12
        reasons.append("breakout_30")

    if vol_ma20 > 0 and volume > 1.15 * vol_ma20:
        score += 8
        reasons.append("volume_confirm")
    elif vol_ma20 > 0 and volume < 0.65 * vol_ma20:
        score -= 5
        reasons.append("low_volume")

    if regime == "normal":
        score += 10
        reasons.append("vol_normal")
    elif regime == "low":
        score += 2
        reasons.append("vol_low_chop_risk")
    elif regime == "high":
        score -= 3
        reasons.append("vol_high")
    else:
        score -= 15
        reasons.append("vol_extreme")

    if spread < 0.0015:
        score += 8
        reasons.append("spread_tight")
    elif spread < 0.004:
        score += 2
        reasons.append("spread_ok")
    else:
        score -= 10
        reasons.append("spread_wide")

    score = max(0.0, min(100.0, score))
    return score, ";".join(reasons)


def initial_state(starting_cash: float, products: list[str]) -> dict[str, Any]:
    return {
        "starting_cash": round(float(starting_cash), 2),
        "cash": round(float(starting_cash), 2),
        "positions": {
            p: {
                "qty": 0.0,
                "avg_price": 0.0,
                "cost_basis": 0.0,
                "entry_fee_usd": 0.0,
                "entry_gross_spend_usd": 0.0,
                "highest_price": 0.0,
                "entry_time_utc": "",
                "entry_time_local": "",
                "entry_score": 0.0,
                "entry_atr": 0.0,
                "lot_id": "",
            }
            for p in products
        },
        "current_day_local": today_local(),
        "current_day_utc": today_utc(),
        "daily_start_equity": round(float(starting_cash), 2),
        "realized_pl_total": 0.0,
        "realized_pl_today": 0.0,
        "trading_halted": False,
        "halt_reason": "",
        "absolute_stop_triggered": False,
        "absolute_stop_reason": "",
        "alerted_temp_halt_reason": "",
        "alerted_absolute_stop_reason": "",
        "daily_profit_locked_date": "",
        "cash_yield_total": 0.0,
        "cash_yield_today": 0.0,
        "last_interest_accrual_utc": now_iso(),
        "benchmark_start_prices": {},
        "benchmark_start_time_utc": "",
        "next_lot_id": 1,
    }


def load_state(starting_cash: float, products: list[str]) -> dict[str, Any]:
    ensure_dirs()
    if not STATE_FILE.exists():
        return initial_state(starting_cash, products)

    with STATE_FILE.open("r") as f:
        state = json.load(f)

    state.setdefault("starting_cash", round(float(starting_cash), 2))
    state.setdefault("cash", round(float(starting_cash), 2))
    state.setdefault("positions", {})
    for p in products:
        state["positions"].setdefault(
            p,
            {
                "qty": 0.0,
                "avg_price": 0.0,
                "cost_basis": 0.0,
                "entry_fee_usd": 0.0,
                "entry_gross_spend_usd": 0.0,
                "highest_price": 0.0,
                "entry_time_utc": "",
                "entry_time_local": "",
                "entry_score": 0.0,
                "entry_atr": 0.0,
                "lot_id": "",
            },
        )
    for p in products:
        state["positions"][p].setdefault("entry_fee_usd", 0.0)
        state["positions"][p].setdefault("entry_gross_spend_usd", 0.0)
        state["positions"][p].setdefault("entry_time_local", "")
        state["positions"][p].setdefault("lot_id", "")
    state.setdefault("current_day_local", today_local())
    state.setdefault("current_day_utc", today_utc())
    state.setdefault("daily_start_equity", safe_float(state.get("starting_cash", starting_cash), starting_cash))
    state.setdefault("realized_pl_total", 0.0)
    state.setdefault("realized_pl_today", 0.0)
    state.setdefault("trading_halted", False)
    state.setdefault("halt_reason", "")
    state.setdefault("absolute_stop_triggered", False)
    state.setdefault("absolute_stop_reason", "")
    state.setdefault("alerted_temp_halt_reason", "")
    state.setdefault("alerted_absolute_stop_reason", "")
    state.setdefault("daily_profit_locked_date", "")
    state.setdefault("cash_yield_total", 0.0)
    state.setdefault("cash_yield_today", 0.0)
    state.setdefault("last_interest_accrual_utc", now_iso())
    state.setdefault("benchmark_start_prices", {})
    state.setdefault("benchmark_start_time_utc", "")
    state.setdefault("next_lot_id", 1)
    return state


def save_state(state: dict[str, Any]) -> None:
    ensure_dirs()
    with STATE_FILE.open("w") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def calculate_equity(state: dict[str, Any], prices: dict[str, float]) -> float:
    equity = safe_float(state.get("cash", 0.0), 0.0)
    for product, pos in state.get("positions", {}).items():
        qty = safe_float(pos.get("qty", 0.0), 0.0)
        price = safe_float(prices.get(product, 0.0), 0.0)
        equity += qty * price
    return equity


def maybe_roll_day(state: dict[str, Any], current_equity: float) -> None:
    # Daily P/L now rolls on the computer's local date, not UTC.
    today = today_local()
    if state.get("current_day_local") != today:
        state["current_day_local"] = today
        state["current_day_utc"] = today_utc()
        state["daily_start_equity"] = round(current_equity, 2)
        state["realized_pl_today"] = 0.0
        state["cash_yield_today"] = 0.0
        state["daily_profit_locked_date"] = ""


def position_age_minutes(pos: dict[str, Any]) -> float:
    entry = pos.get("entry_time_utc", "")
    if not entry:
        return 0.0
    try:
        entry_dt = datetime.fromisoformat(entry)
        if entry_dt.tzinfo is None:
            entry_dt = entry_dt.replace(tzinfo=timezone.utc)
        return max(0.0, (utc_now() - entry_dt).total_seconds() / 60.0)
    except ValueError:
        return 0.0


def unrealized_pl_for_position(pos: dict[str, Any], price: float) -> float:
    qty = safe_float(pos.get("qty", 0.0), 0.0)
    cost_basis = safe_float(pos.get("cost_basis", 0.0), 0.0)
    return (qty * price) - cost_basis


def net_profit_pct_for_position(pos: dict[str, Any], bid: float, fee_rate: float) -> float:
    qty = safe_float(pos.get("qty", 0.0), 0.0)
    cost_basis = safe_float(pos.get("cost_basis", 0.0), 0.0)
    if qty <= 0 or cost_basis <= 0:
        return 0.0
    proceeds_net = (qty * bid) * (1 - fee_rate)
    return (proceeds_net - cost_basis) / cost_basis


def open_position_accounting(pos: dict[str, Any], snap: dict[str, Any], fee_rate: float) -> dict[str, float]:
    """Detailed open-position accounting for display and CSV logs.

    The goal is to separate market movement from fee/spread drag:
    - token_cost_ex_fee_usd: dollars that actually bought the crypto, excluding entry fee
    - mark_value_usd: quantity valued at last traded/market price
    - market_move_pl_usd: mark value minus token cost before entry fee
    - open_pl_after_entry_fee_usd: mark value minus cost basis including entry fee
    - estimated_exit_fee_usd: estimated fee to sell at the current bid
    - net_liquidation_value_usd: estimated cash received if sold now at bid after exit fee
    - net_liquidation_pl_usd: estimated P/L if closed now after entry and exit fees
    """
    qty = safe_float(pos.get("qty", 0.0), 0.0)
    price = safe_float(snap.get("price", 0.0), 0.0)
    bid = safe_float(snap.get("bid", price), price)
    cost_basis = safe_float(pos.get("cost_basis", 0.0), 0.0)
    entry_fee = safe_float(pos.get("entry_fee_usd", 0.0), 0.0)
    entry_gross = safe_float(pos.get("entry_gross_spend_usd", cost_basis), cost_basis)
    token_cost_ex_fee = max(0.0, entry_gross - entry_fee)

    mark_value = qty * price
    bid_value = qty * bid
    estimated_exit_fee = max(0.0, bid_value * fee_rate)
    net_liquidation_value = bid_value - estimated_exit_fee

    market_move_pl = mark_value - token_cost_ex_fee
    open_pl_after_entry_fee = mark_value - cost_basis
    net_liquidation_pl = net_liquidation_value - cost_basis
    total_fee_drag_est = entry_fee + estimated_exit_fee
    break_even_bid = (cost_basis / (qty * (1 - fee_rate))) if qty > 0 and fee_rate < 1 else 0.0
    move_needed_to_break_even_pct = ((break_even_bid / price) - 1) if price > 0 else 0.0

    return {
        "entry_fee_usd": entry_fee,
        "entry_gross_spend_usd": entry_gross,
        "token_cost_ex_fee_usd": token_cost_ex_fee,
        "mark_value_usd": mark_value,
        "bid_value_usd": bid_value,
        "market_move_pl_usd": market_move_pl,
        "open_pl_after_entry_fee_usd": open_pl_after_entry_fee,
        "estimated_exit_fee_usd": estimated_exit_fee,
        "estimated_total_fees_if_closed_usd": total_fee_drag_est,
        "net_liquidation_value_usd": net_liquidation_value,
        "net_liquidation_pl_usd": net_liquidation_pl,
        "net_liquidation_pct": (net_liquidation_pl / cost_basis) if cost_basis > 0 else 0.0,
        "break_even_bid_usd": break_even_bid,
        "move_needed_to_break_even_pct": move_needed_to_break_even_pct,
    }


def normalize_rate(rate: float) -> float:
    """Accept either 0.22 or 22 as 22%. Clamp to 0-100%."""
    rate = safe_float(rate, 0.0)
    if rate > 1.0:
        rate = rate / 100.0
    return max(0.0, min(1.0, rate))



def effective_fee_rate(args: argparse.Namespace, liquidity: str = "taker") -> float:
    """Return the simulated fee rate.

    The paper bot uses bid/ask execution, so "taker" is the conservative default.
    Rates can be passed as decimals (0.006) or percent-style values (0.6).
    """
    model = getattr(args, "fee_model", "conservative")
    if model == "custom":
        return normalize_rate(args.fee_rate)
    if model == "coinbase-advanced-maker":
        return normalize_rate(args.maker_fee_rate)
    if model == "coinbase-advanced-taker":
        return normalize_rate(args.taker_fee_rate)

    # Conservative retail-like fallback. The max() keeps users from accidentally
    # underestimating trading friction when testing tiny, fast trades.
    return max(normalize_rate(args.fee_rate), 0.006)


def drawdown_pct_from_start(state: dict[str, Any], equity: float) -> float:
    start = safe_float(state.get("starting_cash", equity), equity)
    if start <= 0:
        return 0.0
    return max(0.0, (start - equity) / start)


def risk_ladder_settings(state: dict[str, Any], equity: float, args: argparse.Namespace) -> dict[str, Any]:
    """Adjust simulated trade size and selectivity during drawdowns."""
    dd = drawdown_pct_from_start(state, equity)
    settings = {
        "drawdown_pct": dd,
        "trade_size_multiplier": 1.0,
        "edge_threshold_bump": 0.0,
        "hard_halt": False,
        "reason": "normal_risk",
    }

    if getattr(args, "disable_drawdown_ladder", False):
        return settings

    max_dd = normalize_rate(getattr(args, "max_drawdown_pct", 0.10))
    if max_dd > 0 and dd >= max_dd:
        settings.update(
            {
                "trade_size_multiplier": 0.0,
                "edge_threshold_bump": 999.0,
                "hard_halt": True,
                "reason": f"max_drawdown_pct_halt dd={dd:.2%} >= {max_dd:.2%}",
            }
        )
        return settings

    step3 = normalize_rate(getattr(args, "drawdown_step3_pct", 0.07))
    step2 = normalize_rate(getattr(args, "drawdown_step2_pct", 0.05))
    step1 = normalize_rate(getattr(args, "drawdown_step1_pct", 0.03))

    if step3 > 0 and dd >= step3:
        settings.update(
            {
                "trade_size_multiplier": 0.25,
                "edge_threshold_bump": 15.0,
                "reason": f"drawdown_ladder_step3 dd={dd:.2%}: 25% size, +15 score",
            }
        )
    elif step2 > 0 and dd >= step2:
        settings.update(
            {
                "trade_size_multiplier": 0.50,
                "edge_threshold_bump": 8.0,
                "reason": f"drawdown_ladder_step2 dd={dd:.2%}: 50% size, +8 score",
            }
        )
    elif step1 > 0 and dd >= step1:
        settings.update(
            {
                "trade_size_multiplier": 0.75,
                "edge_threshold_bump": 4.0,
                "reason": f"drawdown_ladder_step1 dd={dd:.2%}: 75% size, +4 score",
            }
        )

    return settings


def daily_profit_locked(state: dict[str, Any], equity: float, args: argparse.Namespace) -> tuple[bool, str]:
    lock_value = safe_float(getattr(args, "daily_profit_lock", 0.0), 0.0)
    if lock_value <= 0:
        return False, ""

    today = state.get("current_day_local", today_local())
    if state.get("daily_profit_locked_date") == today:
        return True, f"daily_profit_lock_active for {today}"

    daily_start = safe_float(state.get("daily_start_equity", equity), equity)
    daily_pl = equity - daily_start
    if daily_pl >= lock_value:
        state["daily_profit_locked_date"] = today
        return True, f"daily profit lock triggered: ${daily_pl:.2f} >= ${lock_value:.2f}"

    return False, ""


def should_skip_new_buy(snap: dict[str, Any], state: dict[str, Any], equity: float, args: argparse.Namespace) -> tuple[bool, str]:
    if safe_float(snap.get("spread_pct", 0.0), 0.0) > normalize_rate(args.max_spread_pct):
        return True, f"spread too wide {snap['spread_pct']:.4%} > {normalize_rate(args.max_spread_pct):.4%}"

    if snap.get("volatility_regime") == "extreme" and not getattr(args, "allow_extreme_vol_trades", False):
        return True, "extreme volatility regime: no new buy"

    locked, reason = daily_profit_locked(state, equity, args)
    if locked:
        return True, reason

    return False, ""


def accrue_idle_cash_yield(state: dict[str, Any], args: argparse.Namespace) -> float:
    """Accrue simulated interest/yield on idle paper cash.

    This is not Coinbase yield. It is a generic paper assumption for testing
    money-market/T-bill/HYSA-like idle cash behavior.
    """
    apy = normalize_rate(getattr(args, "idle_cash_apy", 0.0))
    now = utc_now()

    last_raw = state.get("last_interest_accrual_utc") or now.isoformat()
    try:
        last = datetime.fromisoformat(last_raw)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
    except Exception:
        last = now

    state["last_interest_accrual_utc"] = now.replace(microsecond=0).isoformat()

    if apy <= 0:
        return 0.0

    elapsed_seconds = max(0.0, (now - last).total_seconds())
    if elapsed_seconds <= 0:
        return 0.0

    cash = safe_float(state.get("cash", 0.0), 0.0)
    interest = cash * apy * elapsed_seconds / (365.25 * 24 * 60 * 60)
    if interest > 0:
        state["cash"] = round(cash + interest, 6)
        state["cash_yield_total"] = round(safe_float(state.get("cash_yield_total", 0.0), 0.0) + interest, 6)
        state["cash_yield_today"] = round(safe_float(state.get("cash_yield_today", 0.0), 0.0) + interest, 6)
    return interest


def ensure_benchmark_start_prices(state: dict[str, Any], snapshots: dict[str, dict[str, Any]]) -> None:
    if state.get("benchmark_start_prices"):
        return
    state["benchmark_start_prices"] = {
        product: usd(snap["price"]) for product, snap in snapshots.items() if safe_float(snap.get("price", 0.0), 0.0) > 0
    }
    state["benchmark_start_time_utc"] = now_iso()


def benchmark_values(state: dict[str, Any], snapshots: dict[str, dict[str, Any]], equity: float) -> dict[str, float]:
    start_cash = safe_float(state.get("starting_cash", equity), equity)
    starts = state.get("benchmark_start_prices", {}) or {}
    values: dict[str, float] = {}

    # Individual buy-and-hold benchmark for every tracked product.
    for product in snapshots.keys():
        start_price = safe_float(starts.get(product, 0.0), 0.0)
        current = safe_float((snapshots.get(product) or {}).get("price", 0.0), 0.0)
        key = product_to_asset(product).lower()
        if start_price > 0 and current > 0:
            values[f"benchmark_{key}_equity"] = start_cash * current / start_price
            values[f"alpha_vs_{key}_usd"] = equity - values[f"benchmark_{key}_equity"]
        else:
            values[f"benchmark_{key}_equity"] = 0.0
            values[f"alpha_vs_{key}_usd"] = 0.0

    # Equal-weight benchmark across products available at benchmark start.
    available = []
    for product, start_price_raw in starts.items():
        if product in snapshots:
            start_price = safe_float(start_price_raw, 0.0)
            current = safe_float(snapshots[product].get("price", 0.0), 0.0)
            if start_price > 0 and current > 0:
                available.append(current / start_price)

    if available:
        values["benchmark_equal_weight_equity"] = start_cash * (sum(available) / len(available))
        values["alpha_vs_equal_weight_usd"] = equity - values["benchmark_equal_weight_equity"]
    else:
        values["benchmark_equal_weight_equity"] = 0.0
        values["alpha_vs_equal_weight_usd"] = 0.0

    return values


def estimated_tax_values(gain_loss_usd: float, term: str, args: argparse.Namespace) -> dict[str, float]:
    """Estimate tax impact for simulated gains/losses.

    This is intentionally simple and configurable. It is a planning estimate only,
    not tax advice and not a replacement for Form 8949/Schedule D/tax software.
    By default, losses do not create an after-tax benefit unless
    --assume-loss-tax-benefit is used.
    """
    federal_rate = normalize_rate(
        args.estimated_long_term_tax_rate if term == "long" else args.estimated_short_term_tax_rate
    )
    state_rate = normalize_rate(args.estimated_state_tax_rate)
    total_rate = max(0.0, min(1.0, federal_rate + state_rate))

    if gain_loss_usd > 0:
        estimated_tax = gain_loss_usd * total_rate
        estimated_tax_savings = 0.0
        after_tax_gain_loss = gain_loss_usd - estimated_tax
    elif args.assume_loss_tax_benefit:
        estimated_tax = 0.0
        estimated_tax_savings = abs(gain_loss_usd) * total_rate
        after_tax_gain_loss = gain_loss_usd + estimated_tax_savings
    else:
        estimated_tax = 0.0
        estimated_tax_savings = 0.0
        after_tax_gain_loss = gain_loss_usd

    return {
        "estimated_federal_tax_rate": federal_rate,
        "estimated_state_tax_rate": state_rate,
        "estimated_total_tax_rate": total_rate,
        "estimated_tax_usd": estimated_tax,
        "estimated_tax_savings_usd": estimated_tax_savings,
        "after_tax_gain_loss_usd": after_tax_gain_loss,
    }


def buy_position(product: str, state: dict[str, Any], snap: dict[str, Any], trade_size: float, fee_rate: float) -> dict[str, Any] | None:
    pos = state["positions"][product]
    if safe_float(pos.get("qty", 0.0), 0.0) > 0:
        return None

    cash = safe_float(state.get("cash", 0.0), 0.0)
    gross_spend = min(cash, float(trade_size))
    if gross_spend < 10:
        return None

    ask = safe_float(snap.get("ask"), snap["price"])
    fee = gross_spend * fee_rate
    net_spend = gross_spend - fee
    qty = net_spend / ask
    if qty <= 0:
        return None

    lot_num = int(state.get("next_lot_id", 1))
    lot_id = f"{product_to_asset(product)}-{lot_num:06d}"
    state["next_lot_id"] = lot_num + 1

    entry_time_utc = now_iso()
    entry_time_local = local_now_iso()

    state["cash"] = round(cash - gross_spend, 2)
    pos.update(
        {
            "lot_id": lot_id,
            "qty": qty,
            "avg_price": gross_spend / qty,
            "cost_basis": gross_spend,
            "entry_fee_usd": fee,
            "entry_gross_spend_usd": gross_spend,
            "highest_price": snap["price"],
            "entry_time_utc": entry_time_utc,
            "entry_time_local": entry_time_local,
            "entry_score": snap["trade_score"],
            "entry_atr": snap["atr14"],
        }
    )

    return {
        "timestamp_local": local_now_iso(),
        "timestamp_utc": now_iso(),
        "product_id": product,
        "asset": product_to_asset(product),
        "lot_id": lot_id,
        "side": "BUY",
        "qty": qty8(qty),
        "market_price": usd(snap["price"]),
        "exec_price": usd(ask),
        "fee_usd": usd(fee),
        "trade_cost_usd": usd(fee),
        "total_trade_cost_usd": usd(fee),
        "cash_after": usd(state["cash"]),
        "realized_pl_usd": 0.0,
        "trade_score": round(snap["trade_score"], 2),
        "reason": "paper_buy_score_threshold",
    }


def sell_position(product: str, state: dict[str, Any], snap: dict[str, Any], args: argparse.Namespace, reason: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    pos = state["positions"][product]
    qty = safe_float(pos.get("qty", 0.0), 0.0)
    if qty <= 0:
        return None, None

    bid = safe_float(snap.get("bid"), snap["price"])
    proceeds_gross = qty * bid
    sell_fee = proceeds_gross * effective_fee_rate(args, "taker")
    proceeds_net = proceeds_gross - sell_fee
    cost_basis = safe_float(pos.get("cost_basis", 0.0), 0.0)
    realized = proceeds_net - cost_basis
    buy_fee = safe_float(pos.get("entry_fee_usd", 0.0), 0.0)
    total_trade_cost = buy_fee + sell_fee

    state["cash"] = round(safe_float(state.get("cash", 0.0), 0.0) + proceeds_net, 2)
    state["realized_pl_total"] = round(safe_float(state.get("realized_pl_total", 0.0), 0.0) + realized, 2)
    state["realized_pl_today"] = round(safe_float(state.get("realized_pl_today", 0.0), 0.0) + realized, 2)

    entry_time = pos.get("entry_time_utc", "")
    entry_time_local = pos.get("entry_time_local", "")
    lot_id = pos.get("lot_id", "")
    exit_time = now_iso()
    exit_time_local = local_now_iso()
    holding_days = 0
    try:
        entry_dt = datetime.fromisoformat(entry_time)
        exit_dt = datetime.fromisoformat(exit_time)
        holding_days = max(0, (exit_dt - entry_dt).days)
    except Exception:
        holding_days = 0

    trade = {
        "timestamp_local": exit_time_local,
        "timestamp_utc": exit_time,
        "product_id": product,
        "asset": product_to_asset(product),
        "lot_id": lot_id,
        "side": "SELL",
        "qty": qty8(qty),
        "market_price": usd(snap["price"]),
        "exec_price": usd(bid),
        "fee_usd": usd(sell_fee),
        "trade_cost_usd": usd(sell_fee),
        "total_trade_cost_usd": usd(total_trade_cost),
        "cash_after": usd(state["cash"]),
        "realized_pl_usd": usd(realized),
        "trade_score": round(snap["trade_score"], 2),
        "reason": reason,
    }

    term = "long" if holding_days > 365 else "short"
    tax_est = estimated_tax_values(realized, term, args)

    tax = {
        "tax_year": exit_time_local[:4],
        "asset": product_to_asset(product),
        "product_id": product,
        "lot_id": lot_id,
        "acquire_date_local": entry_time_local,
        "dispose_date_local": exit_time_local,
        "acquire_date_utc": entry_time,
        "dispose_date_utc": exit_time,
        "holding_period_days": holding_days,
        "term": term,
        "quantity": qty8(qty),
        "gross_sell_value_usd": usd(proceeds_gross),
        "cost_basis_usd": usd(cost_basis),
        "proceeds_usd": usd(proceeds_net),
        "gain_loss_usd": usd(realized),
        "buy_avg_price_usd": usd(pos.get("avg_price", 0.0)),
        "sell_exec_price_usd": usd(bid),
        "buy_fee_usd": usd(buy_fee),
        "sell_fee_usd": usd(sell_fee),
        "total_trade_cost_usd": usd(total_trade_cost),
        "estimated_federal_tax_rate": pct6(tax_est["estimated_federal_tax_rate"]),
        "estimated_state_tax_rate": pct6(tax_est["estimated_state_tax_rate"]),
        "estimated_total_tax_rate": pct6(tax_est["estimated_total_tax_rate"]),
        "estimated_tax_usd": usd(tax_est["estimated_tax_usd"]),
        "estimated_tax_savings_usd": usd(tax_est["estimated_tax_savings_usd"]),
        "after_tax_gain_loss_usd": usd(tax_est["after_tax_gain_loss_usd"]),
        "source": "paper_simulation_coinbase_public_data",
        "note": "Simulated paper trade. Tax estimates are configurable planning estimates only; reconcile real trades with broker records/tax software.",
    }

    pos.update(
        {
            "qty": 0.0,
            "avg_price": 0.0,
            "cost_basis": 0.0,
            "entry_fee_usd": 0.0,
            "entry_gross_spend_usd": 0.0,
            "highest_price": 0.0,
            "entry_time_utc": "",
            "entry_time_local": "",
            "entry_score": 0.0,
            "entry_atr": 0.0,
            "lot_id": "",
        }
    )
    return trade, tax


def log_trade(trade: dict[str, Any]) -> None:
    header = [
        "timestamp_local", "timestamp_utc", "product_id", "asset", "lot_id", "side", "qty", "market_price", "exec_price",
        "fee_usd", "trade_cost_usd", "total_trade_cost_usd", "cash_after", "realized_pl_usd", "trade_score", "reason",
    ]
    append_csv(TRADES_FILE, trade, header)


def log_tax(tax_row: dict[str, Any]) -> None:
    header = [
        "tax_year", "asset", "product_id", "lot_id", "acquire_date_local", "dispose_date_local", "acquire_date_utc", "dispose_date_utc",
        "holding_period_days", "term", "quantity", "gross_sell_value_usd",
        "cost_basis_usd", "proceeds_usd", "gain_loss_usd",
        "buy_avg_price_usd", "sell_exec_price_usd",
        "buy_fee_usd", "sell_fee_usd", "total_trade_cost_usd",
        "estimated_federal_tax_rate", "estimated_state_tax_rate", "estimated_total_tax_rate",
        "estimated_tax_usd", "estimated_tax_savings_usd", "after_tax_gain_loss_usd",
        "source", "note",
    ]
    append_csv(TAX_FILE, tax_row, header)


def log_equity(state: dict[str, Any], snapshots: dict[str, dict[str, Any]], equity: float, fee_rate: float = 0.006) -> None:
    unrealized = 0.0
    open_positions = []
    open_entry_fees_usd = 0.0
    open_est_exit_fees_usd = 0.0
    open_market_move_pl_usd = 0.0
    open_net_liquidation_pl_usd = 0.0

    for product, pos in state["positions"].items():
        qty = safe_float(pos.get("qty", 0.0), 0.0)
        if qty > 0 and product in snapshots:
            snap = snapshots[product]
            price = snap["price"]
            acct = open_position_accounting(pos, snap, fee_rate)
            u = acct["open_pl_after_entry_fee_usd"]
            unrealized += u
            open_entry_fees_usd += acct["entry_fee_usd"]
            open_est_exit_fees_usd += acct["estimated_exit_fee_usd"]
            open_market_move_pl_usd += acct["market_move_pl_usd"]
            open_net_liquidation_pl_usd += acct["net_liquidation_pl_usd"]
            open_positions.append(
                f"{product}:{pos.get('lot_id', '')}:{qty:.8f}@{safe_float(pos.get('avg_price'), 0.0):.2f}"
            )

    daily_start = safe_float(state.get("daily_start_equity", equity), equity)
    daily_pl = equity - daily_start
    daily_pct = (daily_pl / daily_start * 100) if daily_start else 0.0
    benchmarks = benchmark_values(state, snapshots, equity)

    equity_row = {
        "timestamp_local": local_now_iso(),
        "timestamp_utc": now_iso(),
        "cash": round(safe_float(state.get("cash", 0.0), 0.0), 2),
        "equity": round(equity, 2),
        "realized_pl_total": round(safe_float(state.get("realized_pl_total", 0.0), 0.0), 2),
        "realized_pl_today": round(safe_float(state.get("realized_pl_today", 0.0), 0.0), 2),
        "unrealized_pl": round(unrealized, 2),
        "open_entry_fees_usd": usd(open_entry_fees_usd),
        "open_est_exit_fees_usd": usd(open_est_exit_fees_usd),
        "open_market_move_pl_usd": usd(open_market_move_pl_usd),
        "open_net_liquidation_pl_usd": usd(open_net_liquidation_pl_usd),
        "daily_pl": round(daily_pl, 2),
        "daily_pl_pct": round(daily_pct, 4),
        "cash_yield_total": round(safe_float(state.get("cash_yield_total", 0.0), 0.0), 2),
        "cash_yield_today": round(safe_float(state.get("cash_yield_today", 0.0), 0.0), 2),
        "open_positions": " | ".join(open_positions),
        "trading_halted": state.get("trading_halted", False),
        "halt_reason": state.get("halt_reason", ""),
        "absolute_stop_triggered": state.get("absolute_stop_triggered", False),
        "absolute_stop_reason": state.get("absolute_stop_reason", ""),
        "daily_profit_locked_date": state.get("daily_profit_locked_date", ""),
        "benchmark_btc_equity": usd(benchmarks.get("benchmark_btc_equity", 0.0)),
        "benchmark_eth_equity": usd(benchmarks.get("benchmark_eth_equity", 0.0)),
        "benchmark_sol_equity": usd(benchmarks.get("benchmark_sol_equity", 0.0)),
        "benchmark_equal_weight_equity": usd(benchmarks.get("benchmark_equal_weight_equity", 0.0)),
        "alpha_vs_btc_usd": usd(benchmarks.get("alpha_vs_btc_usd", 0.0)),
        "alpha_vs_eth_usd": usd(benchmarks.get("alpha_vs_eth_usd", 0.0)),
        "alpha_vs_sol_usd": usd(benchmarks.get("alpha_vs_sol_usd", 0.0)),
        "alpha_vs_equal_weight_usd": usd(benchmarks.get("alpha_vs_equal_weight_usd", 0.0)),
    }
    append_csv(
        EQUITY_FILE,
        equity_row,
        [
            "timestamp_local", "timestamp_utc", "cash", "equity", "realized_pl_total", "realized_pl_today",
            "unrealized_pl", "open_entry_fees_usd", "open_est_exit_fees_usd", "open_market_move_pl_usd",
            "open_net_liquidation_pl_usd", "daily_pl", "daily_pl_pct", "cash_yield_total", "cash_yield_today",
            "open_positions", "trading_halted", "halt_reason", "absolute_stop_triggered", "absolute_stop_reason", "daily_profit_locked_date",
            "benchmark_btc_equity", "benchmark_eth_equity", "benchmark_sol_equity", "benchmark_equal_weight_equity",
            "alpha_vs_btc_usd", "alpha_vs_eth_usd", "alpha_vs_sol_usd", "alpha_vs_equal_weight_usd",
        ],
    )

    daily_row = {
        "timestamp_local": local_now_iso(),
        "timestamp_utc": now_iso(),
        "date_local": state.get("current_day_local", today_local()),
        "date_utc": state.get("current_day_utc", today_utc()),
        "daily_start_equity": round(daily_start, 2),
        "current_equity": round(equity, 2),
        "daily_pl": round(daily_pl, 2),
        "daily_pl_pct": round(daily_pct, 4),
        "realized_pl_today": round(safe_float(state.get("realized_pl_today", 0.0), 0.0), 2),
        "unrealized_pl": round(unrealized, 2),
        "cash_yield_today": round(safe_float(state.get("cash_yield_today", 0.0), 0.0), 2),
        "benchmark_btc_equity": usd(benchmarks.get("benchmark_btc_equity", 0.0)),
        "benchmark_eth_equity": usd(benchmarks.get("benchmark_eth_equity", 0.0)),
        "benchmark_sol_equity": usd(benchmarks.get("benchmark_sol_equity", 0.0)),
        "benchmark_equal_weight_equity": usd(benchmarks.get("benchmark_equal_weight_equity", 0.0)),
        "alpha_vs_btc_usd": usd(benchmarks.get("alpha_vs_btc_usd", 0.0)),
        "alpha_vs_eth_usd": usd(benchmarks.get("alpha_vs_eth_usd", 0.0)),
        "alpha_vs_sol_usd": usd(benchmarks.get("alpha_vs_sol_usd", 0.0)),
        "alpha_vs_equal_weight_usd": usd(benchmarks.get("alpha_vs_equal_weight_usd", 0.0)),
    }
    append_csv(
        DAILY_FILE,
        daily_row,
        [
            "timestamp_local", "timestamp_utc", "date_local", "date_utc", "daily_start_equity", "current_equity",
            "daily_pl", "daily_pl_pct", "realized_pl_today", "unrealized_pl", "cash_yield_today",
            "benchmark_btc_equity", "benchmark_eth_equity", "benchmark_sol_equity", "benchmark_equal_weight_equity",
            "alpha_vs_btc_usd", "alpha_vs_eth_usd", "alpha_vs_sol_usd", "alpha_vs_equal_weight_usd",
        ],
    )


def maybe_log_news(products: list[str]) -> None:
    """Advisory-only GDELT-style web/news context. It never triggers trades."""
    query = '(bitcoin OR ethereum OR solana OR "crypto market")'
    params = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "maxrecords": 10,
        "sort": "hybridrel",
    }
    url = "https://api.gdeltproject.org/api/v2/doc/doc"
    try:
        data = request_json(url, params=params, timeout=20)
        articles = data.get("articles", []) if isinstance(data, dict) else []
        titles = [str(a.get("title", "")).replace("\n", " ")[:160] for a in articles[:5]]
        append_csv(
            RESEARCH_FILE,
            {
                "timestamp_local": local_now_iso(),
                "timestamp_utc": now_iso(),
                "source": "GDELT_DOC_API",
                "query": query,
                "article_count_sample": len(articles),
                "sample_titles": " | ".join(titles),
                "note": "Advisory only. Not used for automatic trade execution.",
            },
            ["timestamp_local", "timestamp_utc", "source", "query", "article_count_sample", "sample_titles", "note"],
        )
    except Exception as exc:
        append_csv(
            RESEARCH_FILE,
            {
                "timestamp_local": local_now_iso(),
                "timestamp_utc": now_iso(),
                "source": "GDELT_DOC_API",
                "query": query,
                "article_count_sample": 0,
                "sample_titles": "",
                "note": f"news_fetch_failed: {exc}",
            },
            ["timestamp_local", "timestamp_utc", "source", "query", "article_count_sample", "sample_titles", "note"],
        )


def should_sell(pos: dict[str, Any], snap: dict[str, Any], args: argparse.Namespace) -> tuple[bool, str]:
    price = snap["price"]
    bid = snap["bid"]
    avg = safe_float(pos.get("avg_price", 0.0), 0.0)
    qty = safe_float(pos.get("qty", 0.0), 0.0)
    if qty <= 0:
        return False, "no_position"

    highest = max(safe_float(pos.get("highest_price", 0.0), 0.0), price)
    pos["highest_price"] = highest
    atr = safe_float(snap.get("atr14", 0.0), 0.0)
    score = safe_float(snap.get("trade_score", 0.0), 0.0)
    age = position_age_minutes(pos)
    net_profit_pct = net_profit_pct_for_position(pos, bid, effective_fee_rate(args, "taker"))

    stop_price = avg - (args.stop_atr_multiple * atr)
    trailing_stop = highest - (args.trailing_atr_multiple * atr)
    take_profit_price = avg + (args.take_profit_atr_multiple * atr)

    if price <= stop_price:
        return True, f"stop_loss_atr price {price:.2f} <= {stop_price:.2f}"

    if highest > avg and price <= trailing_stop:
        return True, f"trailing_stop price {price:.2f} <= {trailing_stop:.2f}"

    if price >= take_profit_price and snap["rsi14"] >= 68:
        return True, f"take_profit_atr price {price:.2f} >= {take_profit_price:.2f}"

    # User-requested behavior: take profit quickly if it is profitable and conditions weaken.
    if age >= args.min_profit_minutes and net_profit_pct >= args.quick_profit_pct:
        weakening = (
            score < args.edge_threshold - 8
            or snap["ret_5"] < 0
            or snap["rsi14"] > 74
            or price < snap["ema20"]
        )
        if weakening:
            return True, f"quick_profit_protection age={age:.1f}m net_profit={net_profit_pct:.4%} score={score:.1f}"

    if score < 30 and net_profit_pct > 0:
        return True, f"protect_profit_on_low_score net_profit={net_profit_pct:.4%} score={score:.1f}"

    if score < 20 and price < snap["ema50"]:
        return True, f"trend_break_exit score={score:.1f} price_below_ema50"

    return False, "hold"


def absolute_stop_status(state: dict[str, Any], equity: float, args: argparse.Namespace) -> tuple[bool, str]:
    """Hard final circuit breaker based on starting cash.

    This is different from the drawdown ladder. The drawdown halt may be treated
    as a temporary yellow stop. The absolute stop is a red final stop intended to
    protect the account from losing too much of starting capital.
    """
    start_cash = safe_float(state.get("starting_cash", equity), equity)
    if start_cash <= 0:
        return False, ""

    checks: list[tuple[float, str]] = []

    absolute_pct = normalize_rate(getattr(args, "absolute_stop_pct", 0.25))
    if absolute_pct > 0:
        stop_equity = start_cash * (1 - absolute_pct)
        checks.append((stop_equity, f"absolute stop pct triggered: equity ${equity:.2f} <= ${stop_equity:.2f} ({absolute_pct:.2%} loss from starting cash)"))

    absolute_value = safe_float(getattr(args, "absolute_stop_value", 0.0), 0.0)
    if absolute_value > 0:
        stop_equity = start_cash - absolute_value
        checks.append((stop_equity, f"absolute stop value triggered: equity ${equity:.2f} <= ${stop_equity:.2f} (${absolute_value:.2f} loss from starting cash)"))

    for stop_equity, reason in checks:
        if equity <= stop_equity:
            return True, reason

    return False, ""


def mark_absolute_stop(state: dict[str, Any], reason: str) -> None:
    state["absolute_stop_triggered"] = True
    state["absolute_stop_reason"] = reason
    state["trading_halted"] = True
    state["halt_reason"] = reason



def check_kill_switch(state: dict[str, Any], equity: float, args: argparse.Namespace) -> tuple[bool, str]:
    risk = risk_ladder_settings(state, equity, args)
    if risk.get("hard_halt"):
        return True, risk["reason"]

    max_loss = float(args.loss_stop_value)
    if max_loss <= 0:
        return False, ""

    if args.loss_mode == "daily":
        baseline = safe_float(state.get("daily_start_equity", equity), equity)
        loss = baseline - equity
        if loss >= max_loss:
            return True, f"daily loss stop triggered: loss ${loss:.2f} >= ${max_loss:.2f}"
    else:
        baseline = safe_float(state.get("starting_cash", equity), equity)
        loss = baseline - equity
        if loss >= max_loss:
            return True, f"total loss stop triggered: loss ${loss:.2f} >= ${max_loss:.2f}"

    return False, ""


def run_cycle(state: dict[str, Any], products: list[str], args: argparse.Namespace) -> None:
    snapshots: dict[str, dict[str, Any]] = {}
    prices: dict[str, float] = {}

    for product in products:
        snap = build_market_snapshot(product, args.granularity)
        snapshots[product] = snap
        prices[product] = snap["price"]

    ensure_benchmark_start_prices(state, snapshots)
    interest_added = accrue_idle_cash_yield(state, args)

    equity = calculate_equity(state, prices)
    maybe_roll_day(state, equity)

    if args.enable_news:
        maybe_log_news(products)

    risk = risk_ladder_settings(state, equity, args)
    effective_threshold = args.edge_threshold + safe_float(risk.get("edge_threshold_bump", 0.0), 0.0)
    adjusted_trade_size = max(0.0, args.trade_size * safe_float(risk.get("trade_size_multiplier", 1.0), 1.0))
    fee_rate = effective_fee_rate(args, "taker")
    benchmarks = benchmark_values(state, snapshots, equity)

    print("\n" + "=" * 94)
    print(f"COINBASE PUBLIC-DATA PAPER BOT v13 - Local {local_now_iso()} | UTC {now_iso()}")
    print("=" * 94)
    print(f"Fee model: {args.fee_model} | effective simulated taker fee: {fee_rate:.4%}")
    risk_line = f"Risk ladder: {risk['reason']} | trade size now ${adjusted_trade_size:,.2f} | buy score threshold {effective_threshold:.1f}"
    if risk.get("hard_halt") or str(risk.get("reason", "")).startswith("drawdown_ladder"):
        print(color_text(risk_line, "yellow", args))
    else:
        print(risk_line)
    if interest_added > 0:
        print(f"Idle cash yield accrued this cycle: ${interest_added:.4f}")

    # Absolute stop check before any new actions. This is a red, final stop.
    abs_stop, abs_reason = absolute_stop_status(state, equity, args)
    if abs_stop:
        mark_absolute_stop(state, abs_reason)

    # Temporary kill switch/drawdown halt check. This is a yellow halt.
    if not state.get("absolute_stop_triggered"):
        halted, reason = check_kill_switch(state, equity, args)
        if halted:
            state["trading_halted"] = True
            state["halt_reason"] = reason

    # Force-close positions if a halt triggered.
    if state.get("trading_halted"):
        if state.get("absolute_stop_triggered"):
            msg = f"ABSOLUTE STOP - TRADING HAS STOPPED: {state.get('absolute_stop_reason', state.get('halt_reason', ''))}"
            alert_once(state, "alerted_absolute_stop_reason", args, color="red", title="Trading has stopped", message=msg, popup=True)
            forced_reason = "forced_exit_absolute_stop"
        else:
            msg = f"TRADING HALTED: {state.get('halt_reason', '')}"
            alert_once(state, "alerted_temp_halt_reason", args, color="yellow", title="Trading halted", message=msg, popup=False)
            forced_reason = "forced_exit_kill_switch"

        for product in products:
            pos = state["positions"][product]
            if safe_float(pos.get("qty", 0.0), 0.0) > 0:
                trade, tax = sell_position(product, state, snapshots[product], args, forced_reason)
                if trade:
                    log_trade(trade)
                if tax:
                    log_tax(tax)
        equity = calculate_equity(state, prices)
        log_equity(state, snapshots, equity, effective_fee_rate(args, "taker"))
        save_state(state)
        if args.exit_on_halt or state.get("absolute_stop_triggered"):
            raise SystemExit(3 if state.get("absolute_stop_triggered") else 2)
        return

    locked, lock_reason = daily_profit_locked(state, equity, args)
    if locked:
        print(f"Daily profit lock: {lock_reason}. New buys blocked; existing positions may still sell.")

    for product, snap in snapshots.items():
        pos = state["positions"][product]
        qty = safe_float(pos.get("qty", 0.0), 0.0)
        action = "HOLD"
        action_reason = ""

        if qty > 0:
            sell_now, reason = should_sell(pos, snap, args)
            if sell_now:
                trade, tax = sell_position(product, state, snap, args, reason)
                if trade:
                    log_trade(trade)
                    action = "SELL"
                    action_reason = reason
                if tax:
                    log_tax(tax)
            else:
                action = "HOLD_POSITION"
                action_reason = reason
        else:
            skip_buy, skip_reason = should_skip_new_buy(snap, state, equity, args)
            if skip_buy:
                action = "NO_BUY"
                action_reason = skip_reason
            elif snap["trade_score"] >= effective_threshold:
                trade = buy_position(product, state, snap, adjusted_trade_size, fee_rate)
                if trade:
                    log_trade(trade)
                    action = "BUY"
                    action_reason = f"score {snap['trade_score']:.1f} >= threshold {effective_threshold:.1f}"
                else:
                    action = "NO_BUY"
                    action_reason = "insufficient cash, trade size too small, or already positioned"
            else:
                action = "WATCH"
                action_reason = f"score {snap['trade_score']:.1f} below threshold {effective_threshold:.1f}"

        pos_after = state["positions"][product]
        qty_after = safe_float(pos_after.get("qty", 0.0), 0.0)
        acct = open_position_accounting(pos_after, snap, fee_rate) if qty_after > 0 else {}
        open_pl = acct.get("open_pl_after_entry_fee_usd", 0.0) if qty_after > 0 else 0.0
        net_pct = acct.get("net_liquidation_pct", 0.0) if qty_after > 0 else 0.0

        print(f"\n{product}")
        print(f"  Price/Bid/Ask:   ${snap['price']:,.2f} / ${snap['bid']:,.2f} / ${snap['ask']:,.2f}")
        print(f"  Spread:          {snap['spread_pct']:.4%} | max allowed {normalize_rate(args.max_spread_pct):.4%}")
        print(f"  EMA20/EMA50:     ${snap['ema20']:,.2f} / ${snap['ema50']:,.2f}")
        print(f"  RSI14:           {snap['rsi14']:.2f}")
        print(f"  ATR14:           ${snap['atr14']:,.2f} ({snap['atr_pct']:.4%}) {snap['volatility_regime']}")
        print(f"  Momentum 5/15/30:{snap['ret_5']:.3%} / {snap['ret_15']:.3%} / {snap['ret_30']:.3%}")
        score_line = f"  Score:           {snap['trade_score']:.1f}/100 [{snap['score_reasons']}]"
        print(color_text(score_line, "red", args))
        print(f"  Action:          {action} - {action_reason}")
        if qty_after > 0:
            print(f"  Lot:             {pos_after.get('lot_id', '')}")
            print(f"  Position:        {qty_after:.8f} {product_to_asset(product)} avg ${safe_float(pos_after.get('avg_price'), 0.0):,.2f}")
            print(f"  Entry fee paid:  ${acct['entry_fee_usd']:,.2f}")
            print(f"  Market move P/L: ${acct['market_move_pl_usd']:,.2f} before entry fee")
            print(f"  Open P/L:        ${acct['open_pl_after_entry_fee_usd']:,.2f} after entry fee")
            print(f"  Est. exit fee:   ${acct['estimated_exit_fee_usd']:,.2f} if sold at current bid")
            print(f"  Net liquidation: ${acct['net_liquidation_pl_usd']:,.2f} after entry+exit fees | {net_pct:.4%}")
            print(f"  Break-even bid:  ${acct['break_even_bid_usd']:,.2f} | move needed {acct['move_needed_to_break_even_pct']:.4%}")
            print(f"  Age:             {position_age_minutes(pos_after):.1f}m")
        else:
            print("  Position:        none")

    equity = calculate_equity(state, {p: s["price"] for p, s in snapshots.items()})
    abs_stop, abs_reason = absolute_stop_status(state, equity, args)
    if abs_stop:
        mark_absolute_stop(state, abs_reason)
        msg = f"ABSOLUTE STOP - TRADING HAS STOPPED: {abs_reason}"
        alert_once(state, "alerted_absolute_stop_reason", args, color="red", title="Trading has stopped", message=msg, popup=True)
    else:
        halted, reason = check_kill_switch(state, equity, args)
        if halted:
            state["trading_halted"] = True
            state["halt_reason"] = reason
            msg = f"TRADING HALTED: {reason}"
            alert_once(state, "alerted_temp_halt_reason", args, color="yellow", title="Trading halted", message=msg, popup=False)

    log_equity(state, snapshots, equity, effective_fee_rate(args, "taker"))
    save_state(state)

    daily_start = safe_float(state.get("daily_start_equity", equity), equity)
    daily_pl = equity - daily_start
    total_pl = equity - safe_float(state.get("starting_cash", equity), equity)
    benchmarks = benchmark_values(state, snapshots, equity)
    print("\n" + "-" * 94)
    print(f"Cash:                  ${safe_float(state.get('cash', 0.0), 0.0):,.2f}")
    print(f"Total equity:          ${equity:,.2f}")
    print(f"Total P/L:             ${total_pl:,.2f}")
    print(f"Daily P/L:             ${daily_pl:,.2f}")
    print(f"Realized total:        ${safe_float(state.get('realized_pl_total', 0.0), 0.0):,.2f}")
    print(f"Cash yield total:      ${safe_float(state.get('cash_yield_total', 0.0), 0.0):,.2f}")
    print(f"Benchmark BTC equity:  ${benchmarks.get('benchmark_btc_equity', 0.0):,.2f} | alpha ${benchmarks.get('alpha_vs_btc_usd', 0.0):,.2f}")
    print(f"Benchmark ETH equity:  ${benchmarks.get('benchmark_eth_equity', 0.0):,.2f} | alpha ${benchmarks.get('alpha_vs_eth_usd', 0.0):,.2f}")
    print(f"Benchmark SOL equity:  ${benchmarks.get('benchmark_sol_equity', 0.0):,.2f} | alpha ${benchmarks.get('alpha_vs_sol_usd', 0.0):,.2f}")
    print(f"Benchmark equal-wt eq.:${benchmarks.get('benchmark_equal_weight_equity', 0.0):,.2f} | alpha ${benchmarks.get('alpha_vs_equal_weight_usd', 0.0):,.2f}")
    print(f"Tax CSV:               {TAX_FILE}")
    print(f"State JSON:            {STATE_FILE}")
    print(f"Logs folder:           {LOG_DIR}")
    print("-" * 94)


def parse_products(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        products = [str(x).strip().upper() for x in value if str(x).strip()]
    else:
        products = [x.strip().upper() for x in str(value).split(",") if x.strip()]
    if not products:
        raise argparse.ArgumentTypeError("At least one product is required, e.g. BTC-USD,ETH-USD,SOL-USD")
    return products


def load_config_file(config_path: str | None) -> dict[str, Any]:
    """Load bot options from a JSON file.

    Config keys should use argparse destination names, for example:
      paper_cash, trade_size, loss_stop_value, absolute_stop_pct

    Hyphenated keys are accepted and converted to underscores.
    Percent fields use the same convention as the CLI: 0.25 or 25 both mean 25%.
    """
    if not config_path:
        return {}

    path = Path(config_path).expanduser()
    if not path.is_absolute():
        path = (BASE_DIR / path).resolve()

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError("Config file must contain a JSON object at the top level.")

    cleaned: dict[str, Any] = {}
    for key, value in data.items():
        if str(key).startswith("_"):
            # Allow comment-like metadata such as "_notes" without affecting argparse.
            continue
        dest = str(key).strip().lstrip("-").replace("-", "_")
        if dest == "products":
            value = parse_products(value)
        cleaned[dest] = value

    return cleaned


def apply_config_defaults(parser: argparse.ArgumentParser, config: dict[str, Any]) -> dict[str, Any]:
    """Apply only known argparse destinations from the config file."""
    if not config:
        return {}

    known_dests = {
        action.dest
        for action in parser._actions
        if action.dest and action.dest != argparse.SUPPRESS
    }

    valid = {key: value for key, value in config.items() if key in known_dests}
    unknown = sorted(key for key in config if key not in known_dests)

    if unknown:
        print(f"WARNING: Ignoring unknown config key(s): {', '.join(unknown)}", file=sys.stderr)

    parser.set_defaults(**valid)
    return valid


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Coinbase public-data BTC/ETH/SOL paper-trading simulator v13 with local-time CSV logging, JSON config-file support, benchmarks, risk ladder, spread filter, daily profit lock, idle-cash yield, and estimated fee/tax-aware capital-gains CSV.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--config", type=str, default=None, help="Path to a JSON config file with bot options. Command-line options override config values.")
    parser.add_argument("--products", type=parse_products, default=DEFAULT_PRODUCTS, help="Comma-separated Coinbase products. Default includes BTC-USD, ETH-USD, and SOL-USD.")
    parser.add_argument("--paper-cash", "--starting-cash", dest="paper_cash", type=float, default=10_000.0, help="Starting simulated account cash.")
    parser.add_argument("--trade-size", "--start-invest-value", dest="trade_size", type=float, default=500.0, help="Maximum simulated dollars invested per new trade.")
    parser.add_argument("--loss-stop-value", "--max-loss", dest="loss_stop_value", type=float, default=1_000.0, help="Stop trading after this simulated loss amount.")
    parser.add_argument("--loss-mode", choices=["total", "daily"], default="total", help="Whether the loss stop uses total account loss or daily loss.")
    parser.add_argument("--edge-threshold", type=float, default=65.0, help="Minimum 0-100 trade score required to buy before risk-ladder adjustments.")
    parser.add_argument("--max-spread-pct", type=float, default=0.006, help="Do not open new trades if bid/ask spread exceeds this percentage. 0.006 = 0.60 percent.")
    parser.add_argument("--allow-extreme-vol-trades", action="store_true", help="Allow new buys during extreme volatility. Default blocks them.")
    parser.add_argument("--disable-drawdown-ladder", action="store_true", help="Disable automatic trade-size reduction and threshold increases during drawdowns.")
    parser.add_argument("--drawdown-step1-pct", type=float, default=0.03, help="At this drawdown, reduce trade size to 75 percent and add 4 score points.")
    parser.add_argument("--drawdown-step2-pct", type=float, default=0.05, help="At this drawdown, reduce trade size to 50 percent and add 8 score points.")
    parser.add_argument("--drawdown-step3-pct", type=float, default=0.07, help="At this drawdown, reduce trade size to 25 percent and add 15 score points.")
    parser.add_argument("--max-drawdown-pct", type=float, default=0.10, help="Yellow hard halt if total account drawdown reaches this percentage. 0 disables percentage drawdown halt.")
    parser.add_argument("--absolute-stop-pct", type=float, default=0.25, help="Red final stop if account equity falls this percentage below starting cash. 0.25 or 25 = 25 percent. 0 disables.")
    parser.add_argument("--absolute-stop-value", type=float, default=0.0, help="Red final stop if account loses this many dollars from starting cash. 0 disables. If set with --absolute-stop-pct, whichever triggers first stops trading.")
    parser.add_argument("--daily-profit-lock", type=float, default=0.0, help="If daily profit reaches this dollar amount, stop opening new trades for the rest of the UTC day. 0 disables.")
    parser.add_argument("--idle-cash-apy", type=float, default=0.0, help="Simulated annual yield on idle paper cash. 0.04 = 4 percent APY. This is a paper assumption only.")
    parser.add_argument("--fee-model", choices=["conservative", "custom", "coinbase-advanced-maker", "coinbase-advanced-taker"], default="conservative", help="Fee preset used for simulated trades. The bot uses bid/ask execution, so taker/conservative is usually more realistic.")
    parser.add_argument("--fee-rate", type=float, default=0.006, help="Custom simulated fee rate, or conservative floor. 0.006 = 0.60 percent.")
    parser.add_argument("--maker-fee-rate", type=float, default=0.004, help="Simulated maker fee when --fee-model coinbase-advanced-maker is selected.")
    parser.add_argument("--taker-fee-rate", type=float, default=0.006, help="Simulated taker fee when --fee-model coinbase-advanced-taker is selected.")
    parser.add_argument("--estimated-short-term-tax-rate", type=float, default=0.22, help="Estimated combined federal short-term tax rate before state. Accepts 0.22 or 22 for 22 percent.")
    parser.add_argument("--estimated-long-term-tax-rate", type=float, default=0.15, help="Estimated federal long-term capital gains tax rate before state. Accepts 0.15 or 15 for 15 percent.")
    parser.add_argument("--estimated-state-tax-rate", type=float, default=0.0, help="Estimated state/local tax rate to add to federal estimate. Accepts 0.05 or 5 for 5 percent.")
    parser.add_argument("--assume-loss-tax-benefit", action="store_true", help="For losses, estimate tax savings in after-tax P/L. Conservative default is off: losses show no immediate tax benefit.")
    parser.add_argument("--granularity", type=int, default=60, choices=[60, 300, 900, 3600, 21600, 86400], help="Coinbase candle granularity in seconds.")
    parser.add_argument("--poll", type=int, default=60, help="Seconds between bot cycles in continuous mode.")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit.")
    parser.add_argument("--reset", action="store_true", help="Delete v13 simulation state/log files before starting a clean paper simulation.")
    parser.add_argument("--exit-on-halt", action="store_true", help="Exit the program when the loss kill switch triggers.")
    parser.add_argument("--enable-news", action="store_true", help="Log advisory-only GDELT news context. News never forces trades.")
    parser.add_argument("--min-profit-minutes", type=float, default=5.0, help="Minimum minutes before quick profit-protection selling is allowed.")
    parser.add_argument("--quick-profit-pct", type=float, default=0.003, help="Net profit pct needed for quick profit-protection selling. 0.003 = 0.30 percent.")
    parser.add_argument("--stop-atr-multiple", type=float, default=2.0, help="ATR multiple for stop-loss.")
    parser.add_argument("--trailing-atr-multiple", type=float, default=2.5, help="ATR multiple for trailing stop.")
    parser.add_argument("--take-profit-atr-multiple", type=float, default=4.0, help="ATR multiple for take-profit zone.")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI terminal colors.")
    parser.add_argument("--no-beep", action="store_true", help="Disable terminal beeps on halts/stops.")
    parser.add_argument("--beep-count", type=int, default=3, help="Number of terminal beeps when a halt or absolute stop first triggers.")
    parser.add_argument("--no-popup", action="store_true", help="Disable Linux desktop popup notification for absolute stop events.")
    return parser


def main() -> int:
    # First parse only --config, then use the config values as argparse defaults.
    # Final command-line options still override config-file values.
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--config", type=str, default=None)
    pre_args, _ = pre_parser.parse_known_args()

    parser = build_parser()
    loaded_config = load_config_file(pre_args.config)
    applied_config = apply_config_defaults(parser, loaded_config)
    args = parser.parse_args()

    ensure_dirs()

    if applied_config:
        config_path = str(Path(args.config).expanduser()) if args.config else ""
        print(f"Loaded config: {config_path}")
        print("Config options applied: " + ", ".join(sorted(applied_config.keys())))

    if args.reset:
        reset_files()
        print("Reset complete: deleted v13 simulation state/log files.")

    products = args.products if isinstance(args.products, list) else parse_products(args.products)
    state = load_state(args.paper_cash, products)

    if args.once:
        run_cycle(state, products, args)
        return 0

    print("Starting Coinbase public-data paper bot v13. Press Ctrl+C to stop.")
    print(f"Products: {', '.join(products)} | Poll: {args.poll}s")

    try:
        while True:
            try:
                run_cycle(state, products, args)
            except SystemExit:
                raise
            except Exception as exc:
                print(f"ERROR during cycle: {exc}", file=sys.stderr)
            time.sleep(max(10, int(args.poll)))
    except KeyboardInterrupt:
        save_state(state)
        print("\nStopped. State saved.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
