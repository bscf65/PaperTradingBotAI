#!/usr/bin/env python3
"""
Options/ETF Paper Bot v4

Paper-only scanner and simulator for bullish and bearish ETF trades.

Features:
- Scans liquid ETF symbols using yfinance market/option data.
- Uses internal "sub-bot" votes: trend, mean-reversion, breakout.
- Bullish setups can simulate long calls and ETF long positions.
- Bearish setups can simulate long puts and ETF short positions.
- Optional GDELT news advisory, used for context only, not as direct trade signal.
- Tracks trades, equity, open positions, and news notes in CSV logs.

This script is educational and paper-only. It does not place real trades.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

import numpy as np
import pandas as pd
import requests
import yfinance as yf

VERSION = "v4"
BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = Path(os.environ.get("INVESTAI_LOG_DIR", BASE_DIR / "logs")).expanduser()
STATE_FILE = LOG_DIR / f"options_state_{VERSION}.json"
TRADES_FILE = LOG_DIR / f"options_trades_{VERSION}.csv"
EQUITY_FILE = LOG_DIR / f"options_equity_{VERSION}.csv"
SCAN_FILE = LOG_DIR / f"options_scan_{VERSION}.csv"
NEWS_FILE = LOG_DIR / f"options_news_{VERSION}.csv"

DEFAULT_SYMBOLS = ["SPY", "QQQ", "SMH"]
SYMBOL_NEWS_TERMS = {
    "SPY": "S&P 500 OR SPY ETF OR US stocks",
    "QQQ": "Nasdaq 100 OR QQQ ETF OR technology stocks",
    "SMH": "semiconductor ETF OR SMH ETF OR chip stocks",
    "IWM": "Russell 2000 OR IWM ETF OR small cap stocks",
    "DIA": "Dow Jones OR DIA ETF",
    "TLT": "Treasury bonds OR TLT ETF OR US yields",
    "GLD": "gold ETF OR GLD ETF OR gold prices",
}

RISK_KEYWORDS = [
    "crash", "selloff", "recession", "inflation", "fed", "rates", "lawsuit",
    "sec", "ban", "war", "tariff", "default", "downgrade", "warning",
]
POSITIVE_KEYWORDS = [
    "rally", "surge", "record", "upgrade", "beat", "growth", "optimism", "cut rates",
]

# ANSI colors
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"


def ctext(text: str, color: str, no_color: bool) -> str:
    return text if no_color else f"{color}{text}{RESET}"


def now_local() -> datetime:
    return datetime.now().astimezone()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def ts_local() -> str:
    return now_local().isoformat(timespec="seconds")


def ts_utc() -> str:
    return now_utc().isoformat(timespec="seconds")


def local_date_str() -> str:
    return now_local().date().isoformat()


def ensure_logs() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def append_csv(path: Path, row: Dict[str, Any], header: List[str]) -> None:
    ensure_logs()
    exists = path.exists()
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        if not exists:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in header})


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        val = float(value)
        if math.isnan(val) or math.isinf(val):
            return default
        return val
    except Exception:
        return default


def normalize_pct(value: float) -> float:
    """Accept either 0.25 or 25 as 25%."""
    value = safe_float(value, 0.0)
    if value > 1.0:
        return value / 100.0
    return value


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50)


def reset_files() -> None:
    for path in [STATE_FILE, TRADES_FILE, EQUITY_FILE, SCAN_FILE, NEWS_FILE]:
        if path.exists():
            path.unlink()


def initial_state(paper_cash: float) -> Dict[str, Any]:
    return {
        "paper_cash_start": round(float(paper_cash), 2),
        "cash": round(float(paper_cash), 2),
        "realized_pl": 0.0,
        "positions": [],
        "position_counter": 0,
        "current_day": local_date_str(),
        "daily_start_equity": round(float(paper_cash), 2),
        "halted": False,
        "halt_reason": "",
    }


def load_state(paper_cash: float) -> Dict[str, Any]:
    if STATE_FILE.exists():
        with STATE_FILE.open("r") as f:
            state = json.load(f)
        state.setdefault("paper_cash_start", paper_cash)
        state.setdefault("cash", paper_cash)
        state.setdefault("realized_pl", 0.0)
        state.setdefault("positions", [])
        state.setdefault("position_counter", 0)
        state.setdefault("current_day", local_date_str())
        state.setdefault("daily_start_equity", state.get("paper_cash_start", paper_cash))
        state.setdefault("halted", False)
        state.setdefault("halt_reason", "")
        return state
    return initial_state(paper_cash)


def save_state(state: Dict[str, Any]) -> None:
    ensure_logs()
    with STATE_FILE.open("w") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def fetch_underlying(symbol: str) -> pd.DataFrame:
    df = yf.download(symbol, period="6mo", interval="1d", auto_adjust=True, progress=False, threads=False)
    if df.empty:
        raise RuntimeError(f"No market data returned for {symbol}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna(subset=["Open", "High", "Low", "Close"]).copy()
    df["EMA20"] = ema(df["Close"], 20)
    df["EMA50"] = ema(df["Close"], 50)
    df["RSI14"] = rsi(df["Close"], 14)
    df["RET5"] = df["Close"].pct_change(5)
    df["RET20"] = df["Close"].pct_change(20)
    df["HIGH20"] = df["High"].rolling(20).max()
    df["LOW20"] = df["Low"].rolling(20).min()
    return df.dropna()


def sub_bot_votes(df: pd.DataFrame) -> Dict[str, str]:
    latest = df.iloc[-1]
    price = safe_float(latest["Close"])
    ema20 = safe_float(latest["EMA20"])
    ema50 = safe_float(latest["EMA50"])
    r = safe_float(latest["RSI14"], 50)
    ret5 = safe_float(latest["RET5"])
    ret20 = safe_float(latest["RET20"])
    high20 = safe_float(latest["HIGH20"])
    low20 = safe_float(latest["LOW20"])

    votes: Dict[str, str] = {}

    if price > ema20 > ema50 and ret5 > 0 and ret20 > 0:
        votes["trend_bot"] = "BULL"
    elif price < ema20 < ema50 and ret5 < 0 and ret20 < 0:
        votes["trend_bot"] = "BEAR"
    else:
        votes["trend_bot"] = "NEUTRAL"

    if r < 30:
        votes["mean_reversion_bot"] = "BULL"
    elif r > 70:
        votes["mean_reversion_bot"] = "BEAR"
    else:
        votes["mean_reversion_bot"] = "NEUTRAL"

    # Breakout bot: bullish near 20d high with positive return; bearish near 20d low with negative return.
    if high20 and price >= high20 * 0.995 and ret5 > 0:
        votes["breakout_bot"] = "BULL"
    elif low20 and price <= low20 * 1.005 and ret5 < 0:
        votes["breakout_bot"] = "BEAR"
    else:
        votes["breakout_bot"] = "NEUTRAL"

    return votes


def consensus_from_votes(votes: Dict[str, str]) -> Tuple[str, int, int]:
    bull = sum(1 for v in votes.values() if v == "BULL")
    bear = sum(1 for v in votes.values() if v == "BEAR")
    if bull > bear:
        return "BULL", bull, bear
    if bear > bull:
        return "BEAR", bull, bear
    return "NEUTRAL", bull, bear


def score_underlying(df: pd.DataFrame) -> Dict[str, Any]:
    latest = df.iloc[-1]
    price = safe_float(latest["Close"])
    ema20 = safe_float(latest["EMA20"])
    ema50 = safe_float(latest["EMA50"])
    r = safe_float(latest["RSI14"], 50)
    ret5 = safe_float(latest["RET5"])
    ret20 = safe_float(latest["RET20"])
    high20 = safe_float(latest["HIGH20"])
    low20 = safe_float(latest["LOW20"])
    votes = sub_bot_votes(df)
    consensus, bull_votes, bear_votes = consensus_from_votes(votes)

    bull_score = 0.0
    bear_score = 0.0
    reasons: List[str] = []

    if price > ema20 > ema50:
        bull_score += 25
        reasons.append("trend_up")
    elif price < ema20 < ema50:
        bear_score += 25
        reasons.append("trend_down")
    else:
        reasons.append("trend_mixed")

    if ret5 > 0:
        bull_score += min(20, abs(ret5) * 2000)
    elif ret5 < 0:
        bear_score += min(20, abs(ret5) * 2000)

    if ret20 > 0:
        bull_score += min(20, abs(ret20) * 1000)
    elif ret20 < 0:
        bear_score += min(20, abs(ret20) * 1000)

    if 45 <= r <= 68:
        bull_score += 10
        reasons.append("rsi_bull_ok")
    elif 32 <= r <= 55:
        bear_score += 10
        reasons.append("rsi_bear_ok")
    elif r < 30:
        bull_score += 12
        reasons.append("rsi_oversold")
    elif r > 70:
        bear_score += 12
        reasons.append("rsi_overbought")

    if high20 and price >= high20 * 0.995:
        bull_score += 12
        reasons.append("near_breakout")
    if low20 and price <= low20 * 1.005:
        bear_score += 12
        reasons.append("near_breakdown")

    bull_score += bull_votes * 8
    bear_score += bear_votes * 8

    return {
        "price": price,
        "ema20": ema20,
        "ema50": ema50,
        "rsi14": r,
        "ret5": ret5,
        "ret20": ret20,
        "bull_score": round(min(bull_score, 100), 2),
        "bear_score": round(min(bear_score, 100), 2),
        "consensus": consensus,
        "bull_votes": bull_votes,
        "bear_votes": bear_votes,
        "votes": votes,
        "reasons": ";".join(reasons),
    }


def get_expiry_candidates(ticker: yf.Ticker, min_dte: int, max_dte: int) -> List[str]:
    today = date.today()
    expiries: List[str] = []
    for exp in list(ticker.options or []):
        try:
            exp_date = datetime.strptime(exp, "%Y-%m-%d").date()
        except Exception:
            continue
        dte = (exp_date - today).days
        if min_dte <= dte <= max_dte:
            expiries.append(exp)
    return expiries


def option_mid(row: pd.Series) -> float:
    bid = safe_float(row.get("bid"), 0.0)
    ask = safe_float(row.get("ask"), 0.0)
    last = safe_float(row.get("lastPrice"), 0.0)
    if bid > 0 and ask > 0 and ask >= bid:
        return (bid + ask) / 2.0
    if ask > 0:
        return ask
    if bid > 0:
        return bid
    return last


def option_spread_pct(row: pd.Series) -> float:
    bid = safe_float(row.get("bid"), 0.0)
    ask = safe_float(row.get("ask"), 0.0)
    mid = option_mid(row)
    if mid <= 0 or ask <= 0 or bid < 0:
        return 999.0
    return (ask - bid) / mid


def choose_option_contract(
    ticker: yf.Ticker,
    symbol: str,
    direction: str,
    underlying_price: float,
    min_dte: int,
    max_dte: int,
    min_volume: int,
    min_open_interest: int,
    max_spread_pct: float,
    max_contract_cost: float,
) -> Optional[Dict[str, Any]]:
    expiries = get_expiry_candidates(ticker, min_dte, max_dte)
    if not expiries:
        return None

    option_type = "call" if direction == "BULL" else "put"
    best: Optional[Dict[str, Any]] = None
    best_score = -1.0

    for exp in expiries[:6]:  # keep network/API usage reasonable
        try:
            chain = ticker.option_chain(exp)
            df = chain.calls.copy() if option_type == "call" else chain.puts.copy()
        except Exception:
            continue
        if df.empty:
            continue

        df["mid"] = df.apply(option_mid, axis=1)
        df["spread_pct"] = df.apply(option_spread_pct, axis=1)
        df["contract_cost"] = df["mid"] * 100.0
        df = df[df["mid"] > 0]
        df = df[df["contract_cost"] <= max_contract_cost]
        df = df[df["spread_pct"] <= max_spread_pct]
        if "volume" in df.columns:
            df = df[df["volume"].fillna(0) >= min_volume]
        if "openInterest" in df.columns:
            df = df[df["openInterest"].fillna(0) >= min_open_interest]
        if df.empty:
            continue

        # Prefer slightly OTM/ATM. Calls strike >= price but close. Puts strike <= price but close.
        if option_type == "call":
            df["moneyness_distance"] = (df["strike"] - underlying_price).abs() / underlying_price
            df = df[df["strike"] >= underlying_price * 0.98]
        else:
            df["moneyness_distance"] = (df["strike"] - underlying_price).abs() / underlying_price
            df = df[df["strike"] <= underlying_price * 1.02]
        if df.empty:
            continue

        for _, row in df.iterrows():
            vol = safe_float(row.get("volume"), 0)
            oi = safe_float(row.get("openInterest"), 0)
            spread = safe_float(row.get("spread_pct"), 999)
            dist = safe_float(row.get("moneyness_distance"), 999)
            iv = safe_float(row.get("impliedVolatility"), 0)
            score = 0.0
            score += min(25, vol / max(min_volume, 1) * 5)
            score += min(25, oi / max(min_open_interest, 1) * 3)
            score += max(0, 25 - spread * 100)
            score += max(0, 25 - dist * 400)
            if iv > 0.8:
                score -= 10
            if score > best_score:
                best_score = score
                exp_date = datetime.strptime(exp, "%Y-%m-%d").date()
                dte = (exp_date - date.today()).days
                best = {
                    "symbol": symbol,
                    "underlying_price": underlying_price,
                    "option_type": option_type,
                    "direction": direction,
                    "expiration": exp,
                    "dte": dte,
                    "contract_symbol": str(row.get("contractSymbol", "")),
                    "strike": safe_float(row.get("strike")),
                    "bid": safe_float(row.get("bid")),
                    "ask": safe_float(row.get("ask")),
                    "mid": safe_float(row.get("mid")),
                    "last": safe_float(row.get("lastPrice")),
                    "spread_pct": spread,
                    "volume": int(safe_float(row.get("volume"), 0)),
                    "open_interest": int(safe_float(row.get("openInterest"), 0)),
                    "implied_volatility": safe_float(row.get("impliedVolatility"), 0),
                    "contract_cost": safe_float(row.get("contract_cost")),
                    "liquidity_score": round(score, 2),
                }
    return best


def fetch_news_advisory(symbol: str, max_records: int = 5, timeout: int = 10) -> Dict[str, Any]:
    terms = SYMBOL_NEWS_TERMS.get(symbol.upper(), f"{symbol} ETF OR {symbol} stock")
    url = (
        "https://api.gdeltproject.org/api/v2/doc/doc?"
        f"query={quote_plus(terms)}&mode=artlist&format=json&maxrecords={int(max_records)}&sort=hybridrel"
    )
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "options-paper-bot/2.0"})
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return {"symbol": symbol, "article_count": 0, "risk_hits": 0, "positive_hits": 0, "titles": [], "error": str(exc)}

    articles = data.get("articles", []) or []
    titles: List[str] = []
    risk_hits = 0
    positive_hits = 0
    for art in articles[:max_records]:
        title = str(art.get("title", ""))
        titles.append(title)
        low = title.lower()
        risk_hits += sum(1 for kw in RISK_KEYWORDS if kw in low)
        positive_hits += sum(1 for kw in POSITIVE_KEYWORDS if kw in low)

    return {
        "symbol": symbol,
        "article_count": len(articles),
        "risk_hits": risk_hits,
        "positive_hits": positive_hits,
        "titles": titles,
        "error": "",
    }


def get_open_positions(state: Dict[str, Any], symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    positions = [p for p in state.get("positions", []) if p.get("status") == "OPEN"]
    if symbol:
        positions = [p for p in positions if p.get("symbol") == symbol]
    return positions


def next_position_id(state: Dict[str, Any]) -> str:
    state["position_counter"] = int(state.get("position_counter", 0)) + 1
    return f"OPT-{state['position_counter']:06d}"


def log_trade(row: Dict[str, Any]) -> None:
    header = [
        "timestamp_local", "timestamp_utc", "position_id", "symbol", "instrument", "strategy",
        "side", "direction", "quantity", "underlying_price", "contract_symbol", "option_type",
        "strike", "expiration", "dte", "price", "trade_value", "commission", "cash_after",
        "realized_pl", "reason",
    ]
    append_csv(TRADES_FILE, row, header)


def log_scan(row: Dict[str, Any]) -> None:
    header = [
        "timestamp_local", "timestamp_utc", "symbol", "price", "ema20", "ema50", "rsi14", "ret5", "ret20",
        "bull_score", "bear_score", "consensus", "votes", "reasons", "candidate_strategy",
        "candidate_contract", "candidate_cost", "candidate_spread_pct", "candidate_volume", "candidate_open_interest",
        "news_article_count", "news_risk_hits", "news_positive_hits",
    ]
    append_csv(SCAN_FILE, row, header)


def log_news(news: Dict[str, Any]) -> None:
    header = ["timestamp_local", "timestamp_utc", "symbol", "article_count", "risk_hits", "positive_hits", "titles", "error"]
    append_csv(NEWS_FILE, {
        "timestamp_local": ts_local(),
        "timestamp_utc": ts_utc(),
        "symbol": news.get("symbol"),
        "article_count": news.get("article_count"),
        "risk_hits": news.get("risk_hits"),
        "positive_hits": news.get("positive_hits"),
        "titles": " | ".join(news.get("titles", [])),
        "error": news.get("error", ""),
    }, header)


def open_option_position(state: Dict[str, Any], contract: Dict[str, Any], args: argparse.Namespace, reason: str) -> Optional[Dict[str, Any]]:
    cost = safe_float(contract.get("contract_cost"))
    commission = safe_float(args.option_commission_per_contract, 0.0)
    total = cost + commission
    cash = safe_float(state.get("cash"), 0.0)
    if cost <= 0 or total > cash or total > safe_float(args.trade_size, 0.0):
        return None

    pos_id = next_position_id(state)
    pos = {
        "position_id": pos_id,
        "status": "OPEN",
        "instrument": "OPTION",
        "strategy": "long_call" if contract["option_type"] == "call" else "long_put",
        "direction": contract["direction"],
        "symbol": contract["symbol"],
        "quantity": 1,
        "contract_symbol": contract["contract_symbol"],
        "option_type": contract["option_type"],
        "strike": contract["strike"],
        "expiration": contract["expiration"],
        "dte_at_entry": contract["dte"],
        "entry_underlying_price": contract["underlying_price"],
        "entry_price": contract["mid"],
        "entry_value": cost,
        "entry_commission": commission,
        "entry_total_cost": total,
        "entry_time_local": ts_local(),
        "entry_time_utc": ts_utc(),
    }
    state["cash"] = round(cash - total, 2)
    state["positions"].append(pos)
    log_trade({
        "timestamp_local": ts_local(), "timestamp_utc": ts_utc(), "position_id": pos_id,
        "symbol": contract["symbol"], "instrument": "OPTION", "strategy": pos["strategy"],
        "side": "BUY_TO_OPEN", "direction": contract["direction"], "quantity": 1,
        "underlying_price": contract["underlying_price"], "contract_symbol": contract["contract_symbol"],
        "option_type": contract["option_type"], "strike": contract["strike"], "expiration": contract["expiration"],
        "dte": contract["dte"], "price": contract["mid"], "trade_value": cost,
        "commission": commission, "cash_after": state["cash"], "realized_pl": 0.0, "reason": reason,
    })
    return pos


def open_etf_position(state: Dict[str, Any], symbol: str, direction: str, price: float, args: argparse.Namespace, reason: str) -> Optional[Dict[str, Any]]:
    if direction == "BEAR" and not args.allow_etf_short:
        return None
    cash = safe_float(state.get("cash"), 0.0)
    trade_size = min(safe_float(args.trade_size, 0.0), cash)
    if trade_size <= 0 or price <= 0:
        return None
    qty = trade_size / price
    pos_id = next_position_id(state)
    strategy = "etf_long" if direction == "BULL" else "etf_short"
    pos = {
        "position_id": pos_id,
        "status": "OPEN",
        "instrument": "ETF",
        "strategy": strategy,
        "direction": direction,
        "symbol": symbol,
        "quantity": qty,
        "entry_underlying_price": price,
        "entry_value": trade_size,
        "entry_commission": 0.0,
        "entry_total_cost": trade_size,
        "entry_time_local": ts_local(),
        "entry_time_utc": ts_utc(),
    }
    # For paper short simulation, reserve cash as collateral-like value.
    state["cash"] = round(cash - trade_size, 2)
    state["positions"].append(pos)
    log_trade({
        "timestamp_local": ts_local(), "timestamp_utc": ts_utc(), "position_id": pos_id,
        "symbol": symbol, "instrument": "ETF", "strategy": strategy, "side": "OPEN",
        "direction": direction, "quantity": qty, "underlying_price": price, "price": price,
        "trade_value": trade_size, "commission": 0.0, "cash_after": state["cash"],
        "realized_pl": 0.0, "reason": reason,
    })
    return pos


def current_option_value(symbol: str, pos: Dict[str, Any]) -> Optional[float]:
    try:
        ticker = yf.Ticker(symbol)
        chain = ticker.option_chain(pos["expiration"])
        df = chain.calls if pos.get("option_type") == "call" else chain.puts
        match = df[df["contractSymbol"] == pos.get("contract_symbol")]
        if match.empty:
            return None
        row = match.iloc[0]
        return option_mid(row) * 100.0
    except Exception:
        return None


def close_position(state: Dict[str, Any], pos: Dict[str, Any], underlying_price: float, reason: str, args: argparse.Namespace) -> None:
    cash = safe_float(state.get("cash"), 0.0)
    realized = 0.0
    exit_value = 0.0
    exit_price = underlying_price
    commission = 0.0

    if pos.get("instrument") == "OPTION":
        val = current_option_value(pos["symbol"], pos)
        if val is None:
            print(ctext(f"WARNING: option quote unavailable for {pos.get('contract_symbol', '')}; skipping close instead of marking to zero.", YELLOW, args.no_color))
            return
        exit_value = max(0.0, val)
        commission = safe_float(args.option_commission_per_contract, 0.0)
        realized = exit_value - safe_float(pos.get("entry_total_cost"), 0.0) - commission
        cash += max(0.0, exit_value - commission)
        exit_price = exit_value / 100.0
        side = "SELL_TO_CLOSE"
    else:
        qty = safe_float(pos.get("quantity"), 0.0)
        entry_value = safe_float(pos.get("entry_value"), 0.0)
        if pos.get("strategy") == "etf_long":
            exit_value = qty * underlying_price
            realized = exit_value - entry_value
            cash += exit_value
        else:
            # Paper short with reserved entry value. P/L = entry value - current buyback value.
            buyback_value = qty * underlying_price
            realized = entry_value - buyback_value
            cash += entry_value + realized
            exit_value = buyback_value
        side = "CLOSE"

    pos["status"] = "CLOSED"
    pos["exit_time_local"] = ts_local()
    pos["exit_time_utc"] = ts_utc()
    pos["exit_underlying_price"] = underlying_price
    pos["exit_value"] = exit_value
    pos["realized_pl"] = realized
    state["cash"] = round(cash, 2)
    state["realized_pl"] = round(safe_float(state.get("realized_pl"), 0.0) + realized, 2)

    log_trade({
        "timestamp_local": ts_local(), "timestamp_utc": ts_utc(), "position_id": pos.get("position_id"),
        "symbol": pos.get("symbol"), "instrument": pos.get("instrument"), "strategy": pos.get("strategy"),
        "side": side, "direction": pos.get("direction"), "quantity": pos.get("quantity"),
        "underlying_price": underlying_price, "contract_symbol": pos.get("contract_symbol", ""),
        "option_type": pos.get("option_type", ""), "strike": pos.get("strike", ""),
        "expiration": pos.get("expiration", ""), "dte": "", "price": exit_price,
        "trade_value": exit_value, "commission": commission, "cash_after": state["cash"],
        "realized_pl": realized, "reason": reason,
    })


def value_position(pos: Dict[str, Any], underlying_price: float) -> float:
    if pos.get("instrument") == "OPTION":
        val = current_option_value(pos["symbol"], pos)
        if val is None:
            # Conservative stale fallback: keep previous value if present, else zero.
            return safe_float(pos.get("last_value"), 0.0)
        pos["last_value"] = val
        return max(0.0, val)
    qty = safe_float(pos.get("quantity"), 0.0)
    entry_value = safe_float(pos.get("entry_value"), 0.0)
    if pos.get("strategy") == "etf_long":
        return qty * underlying_price
    # For paper short, reserved collateral plus open P/L.
    buyback_value = qty * underlying_price
    realized_if_closed = entry_value - buyback_value
    return entry_value + realized_if_closed


def maybe_exit_positions(state: Dict[str, Any], symbol_prices: Dict[str, float], args: argparse.Namespace) -> None:
    take_profit = normalize_pct(args.take_profit_pct)
    stop_loss = normalize_pct(args.stop_loss_pct)
    for pos in list(get_open_positions(state)):
        sym = pos.get("symbol")
        price = symbol_prices.get(sym)
        if price is None:
            continue
        current_value = value_position(pos, price)
        entry_cost = safe_float(pos.get("entry_total_cost", pos.get("entry_value", 0.0)), 0.0)
        if entry_cost <= 0:
            continue
        pl_pct = (current_value - entry_cost) / entry_cost
        if pl_pct >= take_profit:
            close_position(state, pos, price, f"take_profit {pl_pct:.2%}", args)
        elif pl_pct <= -stop_loss:
            close_position(state, pos, price, f"stop_loss {pl_pct:.2%}", args)


def calculate_equity(state: Dict[str, Any], symbol_prices: Dict[str, float]) -> float:
    eq = safe_float(state.get("cash"), 0.0)
    for pos in get_open_positions(state):
        price = symbol_prices.get(pos.get("symbol"), 0.0)
        eq += value_position(pos, price)
    return eq


def log_equity(state: Dict[str, Any], symbol_prices: Dict[str, float], equity: float) -> None:
    header = ["timestamp_local", "timestamp_utc", "cash", "equity", "realized_pl", "open_positions", "prices"]
    open_desc = []
    for p in get_open_positions(state):
        open_desc.append(f"{p.get('position_id')}:{p.get('symbol')}:{p.get('strategy')}")
    append_csv(EQUITY_FILE, {
        "timestamp_local": ts_local(),
        "timestamp_utc": ts_utc(),
        "cash": round(safe_float(state.get("cash"), 0.0), 2),
        "equity": round(equity, 2),
        "realized_pl": round(safe_float(state.get("realized_pl"), 0.0), 2),
        "open_positions": " | ".join(open_desc),
        "prices": json.dumps({k: round(v, 4) for k, v in symbol_prices.items()}),
    }, header)


def can_open_more(state: Dict[str, Any], args: argparse.Namespace) -> bool:
    return len(get_open_positions(state)) < int(args.max_open_positions)


def effective_max_contract_cost(state: Dict[str, Any], args: argparse.Namespace) -> float:
    """Maximum option premium we can afford after reserving commission.

    For a small account, the option contract premium alone is not enough.
    The bot must be able to pay contract premium + commission without exceeding
    available cash or the configured trade size.
    """
    cash = max(0.0, safe_float(state.get("cash"), 0.0))
    trade_size = max(0.0, safe_float(args.trade_size, 0.0))
    configured_max = max(0.0, safe_float(args.max_contract_cost, 0.0))
    commission = max(0.0, safe_float(args.option_commission_per_contract, 0.0))
    cap = min(configured_max, cash - commission, trade_size - commission)
    return max(0.0, cap)


def run_cycle(state: Dict[str, Any], args: argparse.Namespace) -> None:
    ensure_logs()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    symbol_prices: Dict[str, float] = {}
    candidates: List[Dict[str, Any]] = []

    print("\n" + "=" * 100)
    print(f"OPTIONS ETF PAPER BOT v4 - Local {ts_local()} | UTC {ts_utc()}")
    print("=" * 100)
    print(f"Symbols: {', '.join(symbols)} | strategies: {args.strategies} | scan_only={args.scan_only}")
    affordability_cap = effective_max_contract_cost(state, args)
    print(f"Cash: ${safe_float(state.get('cash'), 0):,.2f} | open positions: {len(get_open_positions(state))}/{args.max_open_positions}")
    print(f"Contract affordability cap: ${affordability_cap:,.2f} premium max after commission "
          f"(trade_size ${safe_float(args.trade_size, 0):,.2f}, configured max ${safe_float(args.max_contract_cost, 0):,.2f}, "
          f"commission ${safe_float(args.option_commission_per_contract, 0):,.2f})")

    if state.get("halted"):
        print(ctext(f"TRADING HALTED: {state.get('halt_reason')}", RED, args.no_color))

    for sym in symbols:
        try:
            df = fetch_underlying(sym)
            metrics = score_underlying(df)
            price = metrics["price"]
            symbol_prices[sym] = price
        except Exception as exc:
            print(ctext(f"{sym}: data error: {exc}", RED, args.no_color))
            continue

        news = {"article_count": 0, "risk_hits": 0, "positive_hits": 0, "titles": [], "error": ""}
        if args.enable_news:
            news = fetch_news_advisory(sym, args.news_max_records)
            log_news(news)

        ticker = yf.Ticker(sym)
        bullish_contract = None
        bearish_contract = None
        if args.allow_options and affordability_cap <= 0:
            print(ctext(f"{sym}: no affordable option premium available after commission; skipping option scan.", YELLOW, args.no_color))
        if args.allow_options and affordability_cap > 0:
            if metrics["bull_score"] >= args.min_score:
                bullish_contract = choose_option_contract(
                    ticker, sym, "BULL", price, args.min_dte, args.max_dte, args.min_option_volume,
                    args.min_open_interest, normalize_pct(args.max_option_spread_pct), affordability_cap,
                )
            if metrics["bear_score"] >= args.min_score:
                bearish_contract = choose_option_contract(
                    ticker, sym, "BEAR", price, args.min_dte, args.max_dte, args.min_option_volume,
                    args.min_open_interest, normalize_pct(args.max_option_spread_pct), affordability_cap,
                )

        votes_str = ", ".join([f"{k}={v}" for k, v in metrics["votes"].items()])
        score_line = f"Scores: BULL {metrics['bull_score']:.1f}/100 | BEAR {metrics['bear_score']:.1f}/100 | consensus {metrics['consensus']} ({votes_str})"
        print(f"\n{sym}")
        print(f"  Price:      ${price:,.2f} | EMA20 ${metrics['ema20']:,.2f} | EMA50 ${metrics['ema50']:,.2f}")
        print(f"  RSI14:      {metrics['rsi14']:.2f} | 5d ret {metrics['ret5']:.2%} | 20d ret {metrics['ret20']:.2%}")
        print("  " + ctext(score_line, GREEN if metrics['consensus'] == 'BULL' else RED if metrics['consensus'] == 'BEAR' else YELLOW, args.no_color))
        if args.enable_news:
            print(f"  News:       articles={news.get('article_count')} risk_hits={news.get('risk_hits')} positive_hits={news.get('positive_hits')} advisory_only")
            for title in news.get("titles", [])[:2]:
                print(f"              - {title[:110]}")

        candidate_strategy = ""
        candidate_contract = ""
        candidate_cost = ""
        candidate_spread = ""
        candidate_volume = ""
        candidate_oi = ""

        if bullish_contract:
            candidate_strategy = "long_call"
            candidate_contract = bullish_contract["contract_symbol"]
            candidate_cost = round(bullish_contract["contract_cost"], 2)
            candidate_spread = round(bullish_contract["spread_pct"], 4)
            candidate_volume = bullish_contract["volume"]
            candidate_oi = bullish_contract["open_interest"]
            print(f"  Bull option: {candidate_contract} cost ${candidate_cost} spread {candidate_spread:.2%} vol {candidate_volume} OI {candidate_oi}")
            candidates.append({"symbol": sym, "direction": "BULL", "score": metrics["bull_score"], "contract": bullish_contract, "metrics": metrics})
        if bearish_contract:
            if not candidate_strategy:
                candidate_strategy = "long_put"
                candidate_contract = bearish_contract["contract_symbol"]
                candidate_cost = round(bearish_contract["contract_cost"], 2)
                candidate_spread = round(bearish_contract["spread_pct"], 4)
                candidate_volume = bearish_contract["volume"]
                candidate_oi = bearish_contract["open_interest"]
            print(f"  Bear option: {bearish_contract['contract_symbol']} cost ${bearish_contract['contract_cost']:.2f} spread {bearish_contract['spread_pct']:.2%} vol {bearish_contract['volume']} OI {bearish_contract['open_interest']}")
            candidates.append({"symbol": sym, "direction": "BEAR", "score": metrics["bear_score"], "contract": bearish_contract, "metrics": metrics})

        if args.allow_etf_long and metrics["bull_score"] >= args.min_score:
            candidates.append({"symbol": sym, "direction": "BULL", "score": metrics["bull_score"] - 5, "contract": None, "metrics": metrics, "etf": True})
        if args.allow_etf_short and metrics["bear_score"] >= args.min_score:
            candidates.append({"symbol": sym, "direction": "BEAR", "score": metrics["bear_score"] - 5, "contract": None, "metrics": metrics, "etf": True})

        log_scan({
            "timestamp_local": ts_local(), "timestamp_utc": ts_utc(), "symbol": sym,
            "price": round(price, 4), "ema20": round(metrics["ema20"], 4), "ema50": round(metrics["ema50"], 4),
            "rsi14": round(metrics["rsi14"], 2), "ret5": round(metrics["ret5"], 5), "ret20": round(metrics["ret20"], 5),
            "bull_score": metrics["bull_score"], "bear_score": metrics["bear_score"], "consensus": metrics["consensus"],
            "votes": votes_str, "reasons": metrics["reasons"], "candidate_strategy": candidate_strategy,
            "candidate_contract": candidate_contract, "candidate_cost": candidate_cost, "candidate_spread_pct": candidate_spread,
            "candidate_volume": candidate_volume, "candidate_open_interest": candidate_oi,
            "news_article_count": news.get("article_count", 0), "news_risk_hits": news.get("risk_hits", 0), "news_positive_hits": news.get("positive_hits", 0),
        })

    maybe_exit_positions(state, symbol_prices, args)

    if not args.scan_only and not state.get("halted") and can_open_more(state, args):
        # Sort by score and open the best opportunities first.
        candidates = sorted(candidates, key=lambda x: x.get("score", 0), reverse=True)
        opened = 0
        for cand in candidates:
            if not can_open_more(state, args):
                break
            sym = cand["symbol"]
            if get_open_positions(state, sym):
                continue
            if cand.get("score", 0) < args.min_score:
                continue
            price = symbol_prices.get(sym, 0.0)
            if cand.get("contract"):
                pos = open_option_position(state, cand["contract"], args, f"{cand['direction']} candidate score {cand['score']:.1f}")
            elif cand.get("etf"):
                pos = open_etf_position(state, sym, cand["direction"], price, args, f"ETF {cand['direction']} candidate score {cand['score']:.1f}")
            else:
                pos = None
            if pos:
                opened += 1
                print(ctext(f"  OPENED {pos['strategy']} {pos['symbol']} position {pos['position_id']}", CYAN, args.no_color))
            if opened >= int(args.max_new_positions_per_cycle):
                break

    equity = calculate_equity(state, symbol_prices)
    start_cash = safe_float(state.get("paper_cash_start"), equity)
    total_pl = equity - start_cash
    max_loss_pct = normalize_pct(args.absolute_stop_pct)
    if max_loss_pct > 0 and equity <= start_cash * (1 - max_loss_pct):
        state["halted"] = True
        state["halt_reason"] = f"absolute stop: equity ${equity:.2f} <= ${start_cash * (1 - max_loss_pct):.2f}"
        print(ctext(f"ABSOLUTE STOP: {state['halt_reason']}", RED, args.no_color))

    log_equity(state, symbol_prices, equity)
    save_state(state)

    print("\n" + "-" * 100)
    print(f"Cash:         ${safe_float(state.get('cash'), 0):,.2f}")
    print(f"Equity:       ${equity:,.2f}")
    print(f"Total P/L:    ${total_pl:,.2f}")
    print(f"Realized P/L: ${safe_float(state.get('realized_pl'), 0):,.2f}")
    print(f"Open pos:     {len(get_open_positions(state))}")
    print(f"Logs:         {LOG_DIR}")
    print("-" * 100)


def build_parser(defaults: Optional[Dict[str, Any]] = None) -> argparse.ArgumentParser:
    d = defaults or {}
    p = argparse.ArgumentParser(description="Options ETF paper scanner/trader v4. Paper-only; no real orders.")
    p.add_argument("--config", default=d.get("config", ""), help="Optional JSON config file.")
    p.add_argument("--symbols", default=d.get("symbols", ",".join(DEFAULT_SYMBOLS)), help="Comma-separated tickers, e.g. SPY,QQQ,SMH")
    p.add_argument("--paper-cash", type=float, default=d.get("paper_cash", 100.0))
    p.add_argument("--trade-size", type=float, default=d.get("trade_size", 50.0))
    p.add_argument("--min-score", type=float, default=d.get("min_score", 65.0))
    p.add_argument("--strategies", default=d.get("strategies", "long_call,long_put"))
    p.add_argument("--allow-options", action=argparse.BooleanOptionalAction, default=d.get("allow_options", True))
    p.add_argument("--allow-etf-long", action=argparse.BooleanOptionalAction, default=d.get("allow_etf_long", False))
    p.add_argument("--allow-etf-short", action=argparse.BooleanOptionalAction, default=d.get("allow_etf_short", False))
    p.add_argument("--scan-only", action=argparse.BooleanOptionalAction, default=d.get("scan_only", False))
    p.add_argument("--min-dte", type=int, default=d.get("min_dte", 14))
    p.add_argument("--max-dte", type=int, default=d.get("max_dte", 60))
    p.add_argument("--min-option-volume", type=int, default=d.get("min_option_volume", 50))
    p.add_argument("--min-open-interest", type=int, default=d.get("min_open_interest", 100))
    p.add_argument("--max-option-spread-pct", type=float, default=d.get("max_option_spread_pct", 0.15))
    p.add_argument("--max-contract-cost", type=float, default=d.get("max_contract_cost", 49.0))
    p.add_argument("--option-commission-per-contract", type=float, default=d.get("option_commission_per_contract", 0.65))
    p.add_argument("--take-profit-pct", type=float, default=d.get("take_profit_pct", 0.35))
    p.add_argument("--stop-loss-pct", type=float, default=d.get("stop_loss_pct", 0.25))
    p.add_argument("--max-open-positions", type=int, default=d.get("max_open_positions", 1))
    p.add_argument("--max-new-positions-per-cycle", type=int, default=d.get("max_new_positions_per_cycle", 1))
    p.add_argument("--absolute-stop-pct", type=float, default=d.get("absolute_stop_pct", 25.0))
    p.add_argument("--enable-news", action=argparse.BooleanOptionalAction, default=d.get("enable_news", False))
    p.add_argument("--news-max-records", type=int, default=d.get("news_max_records", 5))
    p.add_argument("--poll", type=int, default=d.get("poll", 300))
    p.add_argument("--once", action=argparse.BooleanOptionalAction, default=d.get("once", False))
    p.add_argument("--reset", action=argparse.BooleanOptionalAction, default=d.get("reset", False))
    p.add_argument("--no-color", action=argparse.BooleanOptionalAction, default=d.get("no_color", False))
    return p


def load_config(path: str) -> Dict[str, Any]:
    if not path:
        return {}
    with open(path, "r") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("Config JSON must contain an object at top level.")
    return data


def main() -> int:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default="")
    pre_args, _ = pre.parse_known_args()
    defaults = load_config(pre_args.config) if pre_args.config else {}
    parser = build_parser(defaults)
    args = parser.parse_args()

    if args.reset:
        reset_files()
        print("Reset complete: deleted v4 option bot state/log files.")
    state = load_state(args.paper_cash)
    if args.once:
        run_cycle(state, args)
        return 0

    print("Starting options ETF paper bot v4. Press Ctrl+C to stop.")
    print(f"Poll: {args.poll}s | symbols: {args.symbols}")
    try:
        while True:
            try:
                run_cycle(state, args)
            except Exception as exc:
                print(ctext(f"ERROR during cycle: {exc}", RED, args.no_color), file=sys.stderr)
            time.sleep(max(30, int(args.poll)))
    except KeyboardInterrupt:
        save_state(state)
        print("\nStopped. State saved.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
