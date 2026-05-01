#!/usr/bin/env python3
"""
Quantum/AI Paper Investment Bot v2

Paper-only scanner/simulator for quantum-computing and AI-related stocks/ETFs.
No broker connection. No live orders.

Default universe includes:
- IONQ, RGTI, QBTS, QUBT
- QTUM, ARKQ, SMH

Features:
- Equity/ETF paper long positions
- Optional paper short positions (disabled by default)
- Options scanner for long calls and long puts
- News advisory via GDELT (optional)
- Config-file driven runs
- Logs trades, equity, scans, and state JSON
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote_plus

import numpy as np
import pandas as pd
import requests
import yfinance as yf

VERSION = "v2"
BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = Path(os.environ.get("INVESTAI_LOG_DIR", BASE_DIR / "logs")).expanduser()
STATE_FILE = LOG_DIR / f"quantum_ai_state_{VERSION}.json"
TRADES_FILE = LOG_DIR / f"quantum_ai_trades_{VERSION}.csv"
EQUITY_FILE = LOG_DIR / f"quantum_ai_equity_{VERSION}.csv"
SCAN_FILE = LOG_DIR / f"quantum_ai_scan_{VERSION}.csv"
NEWS_FILE = LOG_DIR / f"quantum_ai_news_{VERSION}.csv"

DEFAULT_UNIVERSE = ["IONQ", "RGTI", "QBTS", "QUBT", "QTUM", "ARKQ", "SMH"]
DEFAULT_ALIASES = {"INOQ": "IONQ"}
ETF_SYMBOLS = {"QTUM", "ARKQ", "SMH", "QQQ", "SPY", "XLK"}

COLOR_GREEN = "\033[92m"
COLOR_YELLOW = "\033[93m"
COLOR_RED = "\033[91m"
COLOR_BLUE = "\033[94m"
COLOR_RESET = "\033[0m"


def local_now() -> datetime:
    return datetime.now().astimezone()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def local_iso() -> str:
    return local_now().isoformat(timespec="seconds")


def utc_iso() -> str:
    return utc_now().isoformat(timespec="seconds")


def today_local() -> str:
    return local_now().date().isoformat()


def money(x: float) -> str:
    return f"${x:,.2f}"


def pct(x: float) -> str:
    return f"{x:.3f}%"


def safe_float(x: Any, default: float = float("nan")) -> float:
    try:
        y = float(x)
        if math.isnan(y) or math.isinf(y):
            return default
        return y
    except Exception:
        return default


def color(text: str, code: str, no_color: bool) -> str:
    return text if no_color else f"{code}{text}{COLOR_RESET}"


def ensure_dirs() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def append_csv(path: Path, row: Dict[str, Any], header: List[str]) -> None:
    ensure_dirs()
    exists = path.exists()
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        if not exists:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in header})


def load_json_file(path: str | Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_rate(value: float) -> float:
    """Allow 0.31 or 31 to mean tax/fee percentages."""
    v = float(value)
    if v > 1.0:
        return v / 100.0
    return v


def normalize_symbols(symbols: Iterable[str], aliases: Dict[str, str]) -> Tuple[List[str], List[str]]:
    normalized: List[str] = []
    notes: List[str] = []
    for raw in symbols:
        s = str(raw).strip().upper()
        if not s:
            continue
        if s in aliases:
            notes.append(f"Alias used: {s} -> {aliases[s]}")
            s = aliases[s].strip().upper()
        if s not in normalized:
            normalized.append(s)
    return normalized, notes


def initial_state(args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "version": VERSION,
        "starting_cash": round(float(args.paper_cash), 2),
        "cash": round(float(args.paper_cash), 2),
        "positions": [],
        "realized_pl": 0.0,
        "fees_paid": 0.0,
        "commissions_paid": 0.0,
        "current_day": today_local(),
        "daily_start_equity": round(float(args.paper_cash), 2),
        "trade_counter": 0,
        "halted": False,
        "halt_reason": "",
        "run_label": args.run_label,
    }


def load_state(args: argparse.Namespace) -> Dict[str, Any]:
    ensure_dirs()
    if args.reset:
        for path in [STATE_FILE, TRADES_FILE, EQUITY_FILE, SCAN_FILE, NEWS_FILE]:
            if path.exists():
                path.unlink()
        print("Reset complete: deleted v2 quantum/AI simulation state/log files.")
        return initial_state(args)
    if STATE_FILE.exists():
        with STATE_FILE.open("r", encoding="utf-8") as f:
            state = json.load(f)
        state.setdefault("positions", [])
        state.setdefault("trade_counter", 0)
        state.setdefault("run_label", args.run_label)
        return state
    return initial_state(args)


def save_state(state: Dict[str, Any]) -> None:
    ensure_dirs()
    with STATE_FILE.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def get_price_history(symbol: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
    df = yf.download(symbol, period=period, interval=interval, auto_adjust=True, progress=False, threads=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df.empty:
        raise RuntimeError(f"No market data for {symbol}")
    return df.dropna().copy()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50)


def analyze_symbol(symbol: str) -> Dict[str, Any]:
    df = get_price_history(symbol, period="6mo", interval="1d")
    close = df["Close"]
    latest = df.iloc[-1]
    price = safe_float(latest["Close"])
    volume = safe_float(latest.get("Volume", 0.0), 0.0)
    ema20 = safe_float(close.ewm(span=20, adjust=False).mean().iloc[-1])
    ema50 = safe_float(close.ewm(span=50, adjust=False).mean().iloc[-1])
    ema100 = safe_float(close.ewm(span=100, adjust=False).mean().iloc[-1])
    rsi14 = safe_float(rsi(close, 14).iloc[-1], 50.0)
    vol20 = safe_float(df["Volume"].rolling(20).mean().iloc[-1], 0.0) if "Volume" in df else 0.0
    vol_ratio = (volume / vol20) if vol20 else 0.0

    def ret(n: int) -> float:
        if len(close) <= n:
            return 0.0
        old = safe_float(close.iloc[-n - 1], price)
        return ((price / old) - 1.0) * 100.0 if old else 0.0

    ret5 = ret(5)
    ret20 = ret(20)
    ret60 = ret(60)

    # ATR-ish volatility percent
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr14 = safe_float(tr.ewm(alpha=1 / 14, adjust=False).mean().iloc[-1], 0.0)
    atr_pct = (atr14 / price * 100.0) if price else 0.0

    bullish = 0.0
    bearish = 0.0
    reasons_bull: List[str] = []
    reasons_bear: List[str] = []

    if price > ema20 > ema50:
        bullish += 30; reasons_bull.append("trend_up")
    elif price < ema20 < ema50:
        bearish += 30; reasons_bear.append("trend_down")
    else:
        reasons_bull.append("trend_mixed"); reasons_bear.append("trend_mixed")

    if ema50 > ema100:
        bullish += 10; reasons_bull.append("medium_trend_up")
    elif ema50 < ema100:
        bearish += 10; reasons_bear.append("medium_trend_down")

    mom_bull = sum([ret5 > 0.5, ret20 > 2.0, ret60 > 5.0]) * 8
    mom_bear = sum([ret5 < -0.5, ret20 < -2.0, ret60 < -5.0]) * 8
    bullish += mom_bull; bearish += mom_bear
    reasons_bull.append(f"momentum_points_{mom_bull}")
    reasons_bear.append(f"momentum_points_{mom_bear}")

    if 45 <= rsi14 <= 70:
        bullish += 10; reasons_bull.append("rsi_healthy")
    elif rsi14 > 70:
        bullish += 2; bearish += 8; reasons_bull.append("rsi_hot"); reasons_bear.append("overbought_risk")
    elif rsi14 < 35:
        bearish += 8; reasons_bear.append("rsi_weak")
        if rsi14 < 25:
            bullish += 4; reasons_bull.append("possible_oversold_bounce")
    else:
        reasons_bull.append("rsi_neutral"); reasons_bear.append("rsi_neutral")

    if vol_ratio >= 1.2:
        bullish += 8 if ret5 > 0 or ret20 > 0 else 0
        bearish += 8 if ret5 < 0 or ret20 < 0 else 0
        reasons_bull.append("volume_confirm")
        reasons_bear.append("volume_confirm")
    else:
        reasons_bull.append("volume_light")
        reasons_bear.append("volume_light")

    if atr_pct < 1.5:
        bullish -= 5; bearish -= 5
        reasons_bull.append("low_volatility")
        reasons_bear.append("low_volatility")
    elif atr_pct > 8.0:
        bullish -= 5; bearish -= 5
        reasons_bull.append("high_volatility")
        reasons_bear.append("high_volatility")

    bullish = max(0.0, min(100.0, bullish))
    bearish = max(0.0, min(100.0, bearish))

    return {
        "symbol": symbol,
        "asset_type": "ETF" if symbol in ETF_SYMBOLS else "STOCK",
        "price": price,
        "ema20": ema20,
        "ema50": ema50,
        "ema100": ema100,
        "rsi14": rsi14,
        "volume": volume,
        "volume_ratio": vol_ratio,
        "ret5d": ret5,
        "ret20d": ret20,
        "ret60d": ret60,
        "atr14": atr14,
        "atr_pct": atr_pct,
        "bullish_score": round(bullish, 2),
        "bearish_score": round(bearish, 2),
        "bull_reasons": ";".join(reasons_bull),
        "bear_reasons": ";".join(reasons_bear),
    }


def fetch_news(symbol: str, query: str) -> Dict[str, Any]:
    # GDELT DOC API: advisory-only, best effort.
    q = quote_plus(query)
    url = f"https://api.gdeltproject.org/api/v2/doc/doc?query={q}&mode=artlist&format=json&maxrecords=10&sort=hybridrel"
    try:
        r = requests.get(url, timeout=10)
        if not r.ok:
            return {"symbol": symbol, "article_count": 0, "risk_hits": 0, "headline_sample": f"HTTP {r.status_code}"}
        data = r.json()
        articles = data.get("articles", []) or []
        risk_terms = ["lawsuit", "SEC", "fraud", "dilution", "offering", "bankruptcy", "hack", "short seller", "investigation"]
        risk_hits = 0
        headlines = []
        for a in articles[:5]:
            title = str(a.get("title", ""))
            headlines.append(title)
            low = title.lower()
            risk_hits += sum(1 for term in risk_terms if term.lower() in low)
        return {"symbol": symbol, "article_count": len(articles), "risk_hits": risk_hits, "headline_sample": " | ".join(headlines[:3])}
    except Exception as exc:
        return {"symbol": symbol, "article_count": 0, "risk_hits": 0, "headline_sample": f"news_error: {exc}"}


def option_chain_candidate(symbol: str, direction: str, price: float, args: argparse.Namespace) -> Optional[Dict[str, Any]]:
    """Find an affordable long call/put candidate."""
    try:
        ticker = yf.Ticker(symbol)
        expirations = list(ticker.options or [])
    except Exception:
        return None
    if not expirations:
        return None

    best: Optional[Dict[str, Any]] = None
    best_score = -1e9
    now_date = local_now().date()
    max_total = min(args.trade_size, args.max_contract_cost, args.paper_cash)

    for exp in expirations[:8]:
        try:
            exp_date = datetime.fromisoformat(exp).date()
        except Exception:
            continue
        dte = (exp_date - now_date).days
        if dte < args.min_dte or dte > args.max_dte:
            continue
        try:
            chain = ticker.option_chain(exp)
            table = chain.calls if direction == "call" else chain.puts
        except Exception:
            continue
        if table is None or table.empty:
            continue
        table = table.copy()
        if "bid" not in table.columns or "ask" not in table.columns or "strike" not in table.columns:
            continue
        for _, row in table.iterrows():
            bid = safe_float(row.get("bid", 0.0), 0.0)
            ask = safe_float(row.get("ask", 0.0), 0.0)
            last = safe_float(row.get("lastPrice", 0.0), 0.0)
            strike = safe_float(row.get("strike", 0.0), 0.0)
            volume = safe_float(row.get("volume", 0.0), 0.0)
            oi = safe_float(row.get("openInterest", 0.0), 0.0)
            iv = safe_float(row.get("impliedVolatility", 0.0), 0.0)
            if ask <= 0:
                continue
            spread_pct = ((ask - bid) / ask) if ask else 1.0
            contract_cost = ask * 100.0
            total_cost = contract_cost + args.option_commission
            if total_cost > max_total:
                continue
            if volume < args.min_option_volume or oi < args.min_open_interest:
                continue
            if spread_pct > args.max_option_spread_pct:
                continue
            moneyness = abs(strike - price) / price if price else 999
            # Prefer near-the-money affordable and liquid options.
            liquidity_score = min(30.0, (volume / 10.0) + (oi / 50.0))
            moneyness_score = max(0.0, 30.0 - (moneyness * 300.0))
            dte_score = max(0.0, 20.0 - abs(dte - args.target_dte) / 2.0)
            spread_score = max(0.0, 20.0 - (spread_pct * 100.0))
            score = liquidity_score + moneyness_score + dte_score + spread_score
            if score > best_score:
                best_score = score
                best = {
                    "symbol": symbol,
                    "contract_symbol": row.get("contractSymbol", ""),
                    "strategy": "long_call" if direction == "call" else "long_put",
                    "expiration": exp,
                    "dte": dte,
                    "strike": strike,
                    "bid": bid,
                    "ask": ask,
                    "last": last,
                    "volume": volume,
                    "open_interest": oi,
                    "implied_volatility": iv,
                    "spread_pct": spread_pct * 100.0,
                    "contract_cost": contract_cost,
                    "total_cost": total_cost,
                    "candidate_score": score,
                }
    return best


def next_trade_id(state: Dict[str, Any], prefix: str) -> str:
    state["trade_counter"] = int(state.get("trade_counter", 0)) + 1
    return f"{prefix}-{state['trade_counter']:06d}"


def open_position(state: Dict[str, Any], pos: Dict[str, Any]) -> None:
    state["positions"].append(pos)


def position_count(state: Dict[str, Any]) -> int:
    return len([p for p in state.get("positions", []) if p.get("status") == "open"])


def already_positioned(state: Dict[str, Any], symbol: str) -> bool:
    return any(p.get("status") == "open" and p.get("symbol") == symbol for p in state.get("positions", []))


def can_open_new(state: Dict[str, Any], symbol: str, args: argparse.Namespace) -> Tuple[bool, str]:
    if state.get("halted"):
        return False, f"halted: {state.get('halt_reason', '')}"
    if position_count(state) >= args.max_open_positions:
        return False, f"max open positions reached ({args.max_open_positions})"
    if args.one_position_per_symbol and already_positioned(state, symbol):
        return False, "already positioned in symbol"
    return True, "ok"


def execute_equity_entry(state: Dict[str, Any], scan: Dict[str, Any], side: str, args: argparse.Namespace) -> Optional[Dict[str, Any]]:
    symbol = scan["symbol"]
    ok, reason = can_open_new(state, symbol, args)
    if not ok:
        return None
    cash = safe_float(state.get("cash", 0.0), 0.0)
    spend = min(cash, args.trade_size)
    if spend < args.min_trade_value:
        return None
    price = safe_float(scan["price"])
    if price <= 0:
        return None

    # Paper equity entry. For longs, spend is the invested cash.
    # For paper shorts, spend is reserved collateral + entry fee.
    # Real short selling involves margin/borrow rules; this is intentionally a simplified paper model.
    fee = spend * args.equity_fee_rate
    net_value = spend - fee
    qty = net_value / price
    if qty <= 0:
        return None
    state["cash"] = round(cash - spend, 2)
    state["fees_paid"] = round(safe_float(state.get("fees_paid", 0.0), 0.0) + fee, 2)
    trade_id = next_trade_id(state, symbol)
    pos = {
        "trade_id": trade_id,
        "status": "open",
        "instrument": "equity",
        "symbol": symbol,
        "side": side,  # long or paper short
        "entry_time_local": local_iso(),
        "entry_time_utc": utc_iso(),
        "entry_price": price,
        "qty": qty,
        "gross_entry_value": net_value,
        "entry_fee": fee,
        "collateral": net_value if side == "short" else 0.0,
        "cost_basis": spend,
        "highest_price": price,
        "lowest_price": price,
    }
    open_position(state, pos)
    log_trade({
        "event": "OPEN",
        "trade_id": trade_id,
        "symbol": symbol,
        "instrument": "equity",
        "strategy": f"equity_{side}",
        "side": "BUY" if side == "long" else "SHORT_SELL",
        "qty": qty,
        "price": price,
        "gross_value": spend,
        "fee_or_commission": fee,
        "cash_after": state["cash"],
        "realized_pl": 0.0,
        "reason": "paper equity entry",
    }, args)
    return pos


def execute_option_entry(state: Dict[str, Any], candidate: Dict[str, Any], args: argparse.Namespace) -> Optional[Dict[str, Any]]:
    symbol = candidate["symbol"]
    ok, reason = can_open_new(state, symbol, args)
    if not ok:
        return None
    cash = safe_float(state.get("cash", 0.0), 0.0)
    total = safe_float(candidate["total_cost"])
    if total <= 0 or total > cash or total > args.trade_size or safe_float(candidate["contract_cost"]) > args.max_contract_cost:
        return None
    state["cash"] = round(cash - total, 2)
    state["commissions_paid"] = round(safe_float(state.get("commissions_paid", 0.0), 0.0) + args.option_commission, 2)
    trade_id = next_trade_id(state, symbol)
    pos = {
        "trade_id": trade_id,
        "status": "open",
        "instrument": "option",
        "symbol": symbol,
        "contract_symbol": candidate["contract_symbol"],
        "strategy": candidate["strategy"],
        "entry_time_local": local_iso(),
        "entry_time_utc": utc_iso(),
        "expiration": candidate["expiration"],
        "dte_entry": candidate["dte"],
        "strike": candidate["strike"],
        "contracts": 1,
        "entry_ask": candidate["ask"],
        "entry_bid": candidate["bid"],
        "entry_price_per_share": candidate["ask"],
        "gross_entry_value": candidate["contract_cost"],
        "commission": args.option_commission,
        "cost_basis": total,
    }
    open_position(state, pos)
    log_trade({
        "event": "OPEN",
        "trade_id": trade_id,
        "symbol": symbol,
        "instrument": "option",
        "strategy": candidate["strategy"],
        "side": "BUY_TO_OPEN",
        "qty": 1,
        "price": candidate["ask"],
        "gross_value": candidate["contract_cost"],
        "fee_or_commission": args.option_commission,
        "cash_after": state["cash"],
        "realized_pl": 0.0,
        "reason": "paper option entry",
    }, args)
    return pos


def get_current_option_bid(position: Dict[str, Any]) -> Optional[float]:
    symbol = position["symbol"]
    contract_symbol = position.get("contract_symbol")
    if not contract_symbol:
        return None
    try:
        ticker = yf.Ticker(symbol)
        for exp in ticker.options or []:
            chain = ticker.option_chain(exp)
            tables = [chain.calls, chain.puts]
            for table in tables:
                if table is not None and not table.empty and "contractSymbol" in table.columns:
                    row = table[table["contractSymbol"] == contract_symbol]
                    if not row.empty:
                        bid = safe_float(row.iloc[0].get("bid", 0.0), 0.0)
                        last = safe_float(row.iloc[0].get("lastPrice", 0.0), 0.0)
                        return bid if bid > 0 else last
    except Exception:
        return None
    return None


def close_position(state: Dict[str, Any], position: Dict[str, Any], current_price: float, reason: str, args: argparse.Namespace) -> None:
    if position.get("instrument") == "equity":
        qty = safe_float(position.get("qty", 0.0), 0.0)
        entry = safe_float(position.get("entry_price", 0.0), 0.0)
        gross = qty * current_price
        exit_fee = gross * args.equity_fee_rate
        if position.get("side") == "short":
            collateral = safe_float(position.get("collateral", 0.0), 0.0)
            pnl_before_fees = (entry - current_price) * qty
            realized = pnl_before_fees - safe_float(position.get("entry_fee", 0.0), 0.0) - exit_fee
            cash_return = collateral + pnl_before_fees - exit_fee
            state["cash"] = round(safe_float(state.get("cash", 0.0), 0.0) + cash_return, 2)
        else:
            realized = gross - safe_float(position.get("cost_basis", 0.0), 0.0) - exit_fee
            state["cash"] = round(safe_float(state.get("cash", 0.0), 0.0) + gross - exit_fee, 2)
        state["fees_paid"] = round(safe_float(state.get("fees_paid", 0.0), 0.0) + exit_fee, 2)
        event_side = "SELL" if position.get("side") == "long" else "BUY_TO_COVER"
        gross_value = gross
        fee = exit_fee
        price = current_price
    else:
        bid = get_current_option_bid(position)
        if bid is None:
            print(color(f"WARNING: option quote unavailable for {position.get('contract_symbol', '')}; skipping close instead of marking to zero.", COLOR_YELLOW, args.no_color))
            return
        exit_price = bid
        gross_value = exit_price * 100.0
        fee = args.option_commission
        realized = gross_value - safe_float(position.get("cost_basis", 0.0), 0.0) - fee
        state["cash"] = round(safe_float(state.get("cash", 0.0), 0.0) + gross_value - fee, 2)
        state["commissions_paid"] = round(safe_float(state.get("commissions_paid", 0.0), 0.0) + fee, 2)
        event_side = "SELL_TO_CLOSE"
        price = exit_price
    state["realized_pl"] = round(safe_float(state.get("realized_pl", 0.0), 0.0) + realized, 2)
    position["status"] = "closed"
    position["exit_time_local"] = local_iso()
    position["exit_time_utc"] = utc_iso()
    position["exit_price"] = price
    position["exit_reason"] = reason
    position["realized_pl"] = realized
    log_trade({
        "event": "CLOSE",
        "trade_id": position.get("trade_id"),
        "symbol": position.get("symbol"),
        "instrument": position.get("instrument"),
        "strategy": position.get("strategy", f"equity_{position.get('side')}") ,
        "side": event_side,
        "qty": position.get("qty", position.get("contracts", 1)),
        "price": price,
        "gross_value": gross_value,
        "fee_or_commission": fee,
        "cash_after": state["cash"],
        "realized_pl": realized,
        "reason": reason,
    }, args)


def maybe_close_positions(state: Dict[str, Any], scans_by_symbol: Dict[str, Dict[str, Any]], args: argparse.Namespace) -> None:
    for pos in list(state.get("positions", [])):
        if pos.get("status") != "open":
            continue
        symbol = pos.get("symbol")
        scan = scans_by_symbol.get(symbol)
        if not scan:
            continue
        current_price = safe_float(scan["price"])
        reason = None
        if pos.get("instrument") == "equity":
            entry = safe_float(pos.get("entry_price", 0.0), 0.0)
            side = pos.get("side")
            if side == "long":
                pl_pct = (current_price / entry - 1.0) if entry else 0.0
                if pl_pct <= -args.stop_loss_pct:
                    reason = f"equity stop loss {pl_pct*100:.2f}%"
                elif pl_pct >= args.take_profit_pct:
                    reason = f"equity take profit {pl_pct*100:.2f}%"
                elif scan["bearish_score"] >= args.exit_opposite_score:
                    reason = "opposite bearish score exit"
            else:
                pl_pct = (entry / current_price - 1.0) if current_price else 0.0
                if pl_pct <= -args.stop_loss_pct:
                    reason = f"short stop loss {pl_pct*100:.2f}%"
                elif pl_pct >= args.take_profit_pct:
                    reason = f"short take profit {pl_pct*100:.2f}%"
                elif scan["bullish_score"] >= args.exit_opposite_score:
                    reason = "opposite bullish score exit"
        else:
            bid = get_current_option_bid(pos)
            if bid is None:
                continue
            gross_now = bid * 100.0
            basis = safe_float(pos.get("cost_basis", 0.0), 0.0)
            pl_pct = ((gross_now - args.option_commission) / basis - 1.0) if basis else 0.0
            if pl_pct <= -args.option_stop_loss_pct:
                reason = f"option stop loss {pl_pct*100:.2f}%"
            elif pl_pct >= args.option_take_profit_pct:
                reason = f"option take profit {pl_pct*100:.2f}%"
            else:
                strategy = pos.get("strategy")
                if strategy == "long_call" and scan["bearish_score"] >= args.exit_opposite_score:
                    reason = "call exit: bearish score"
                if strategy == "long_put" and scan["bullish_score"] >= args.exit_opposite_score:
                    reason = "put exit: bullish score"
        if reason:
            close_position(state, pos, current_price, reason, args)


def calc_open_value(state: Dict[str, Any], scans_by_symbol: Dict[str, Dict[str, Any]], args: argparse.Namespace) -> Tuple[float, float]:
    open_value = 0.0
    unrealized = 0.0
    for pos in state.get("positions", []):
        if pos.get("status") != "open":
            continue
        symbol = pos.get("symbol")
        scan = scans_by_symbol.get(symbol)
        if not scan:
            continue
        if pos.get("instrument") == "equity":
            price = safe_float(scan["price"])
            qty = safe_float(pos.get("qty", 0.0), 0.0)
            val = qty * price
            open_value += val
            if pos.get("side") == "short":
                unrealized += (safe_float(pos.get("entry_price", 0.0), 0.0) - price) * qty - safe_float(pos.get("entry_fee", 0.0), 0.0)
            else:
                unrealized += val - safe_float(pos.get("cost_basis", 0.0), 0.0)
        else:
            bid = get_current_option_bid(pos)
            if bid is None:
                bid = 0.0
            val = bid * 100.0
            open_value += val
            unrealized += val - safe_float(pos.get("cost_basis", 0.0), 0.0)
    return open_value, unrealized


def log_trade(row: Dict[str, Any], args: argparse.Namespace) -> None:
    header = [
        "timestamp_local", "timestamp_utc", "run_label", "event", "trade_id", "symbol", "instrument",
        "strategy", "side", "qty", "price", "gross_value", "fee_or_commission", "cash_after", "realized_pl", "reason"
    ]
    row = {**row, "timestamp_local": local_iso(), "timestamp_utc": utc_iso(), "run_label": args.run_label}
    append_csv(TRADES_FILE, row, header)


def log_scan(scan: Dict[str, Any], args: argparse.Namespace, action: str, note: str) -> None:
    header = [
        "timestamp_local", "timestamp_utc", "run_label", "symbol", "asset_type", "price", "bullish_score", "bearish_score",
        "rsi14", "ret5d", "ret20d", "ret60d", "atr_pct", "volume_ratio", "bull_reasons", "bear_reasons", "action", "note"
    ]
    row = {**scan, "timestamp_local": local_iso(), "timestamp_utc": utc_iso(), "run_label": args.run_label, "action": action, "note": note}
    append_csv(SCAN_FILE, row, header)


def log_news(row: Dict[str, Any], args: argparse.Namespace) -> None:
    header = ["timestamp_local", "timestamp_utc", "run_label", "symbol", "article_count", "risk_hits", "headline_sample"]
    row = {**row, "timestamp_local": local_iso(), "timestamp_utc": utc_iso(), "run_label": args.run_label}
    append_csv(NEWS_FILE, row, header)


def log_equity(state: Dict[str, Any], equity: float, open_value: float, unrealized: float, args: argparse.Namespace) -> None:
    header = [
        "timestamp_local", "timestamp_utc", "run_label", "cash", "open_value", "equity", "realized_pl", "unrealized_pl",
        "fees_paid", "commissions_paid", "open_positions", "halted", "halt_reason"
    ]
    append_csv(EQUITY_FILE, {
        "timestamp_local": local_iso(), "timestamp_utc": utc_iso(), "run_label": args.run_label,
        "cash": round(safe_float(state.get("cash", 0.0), 0.0), 2),
        "open_value": round(open_value, 2),
        "equity": round(equity, 2),
        "realized_pl": round(safe_float(state.get("realized_pl", 0.0), 0.0), 2),
        "unrealized_pl": round(unrealized, 2),
        "fees_paid": round(safe_float(state.get("fees_paid", 0.0), 0.0), 2),
        "commissions_paid": round(safe_float(state.get("commissions_paid", 0.0), 0.0), 2),
        "open_positions": position_count(state),
        "halted": state.get("halted", False),
        "halt_reason": state.get("halt_reason", ""),
    }, header)


def check_halts(state: Dict[str, Any], equity: float, args: argparse.Namespace) -> None:
    starting = safe_float(state.get("starting_cash", args.paper_cash), args.paper_cash)
    if args.absolute_stop_pct and equity <= starting * (1.0 - args.absolute_stop_pct):
        state["halted"] = True
        state["halt_reason"] = f"absolute_stop_pct {args.absolute_stop_pct*100:.2f}% hit"
    if args.absolute_stop_value and equity <= starting - args.absolute_stop_value:
        state["halted"] = True
        state["halt_reason"] = f"absolute_stop_value {args.absolute_stop_value:.2f} hit"


def run_cycle(state: Dict[str, Any], args: argparse.Namespace) -> None:
    aliases = {**DEFAULT_ALIASES, **(args.aliases or {})}
    symbols, notes = normalize_symbols(args.symbols, aliases)
    scans: List[Dict[str, Any]] = []
    scans_by_symbol: Dict[str, Dict[str, Any]] = {}

    print("\n" + "=" * 102)
    print(f"QUANTUM/AI PAPER INVESTMENT BOT {VERSION} - Local {local_iso()} | UTC {utc_iso()}")
    print("=" * 102)
    print(f"Run label: {args.run_label} | Cash: {money(safe_float(state.get('cash', 0.0), 0.0))} | Symbols: {', '.join(symbols)}")
    print(f"Mode: stocks={args.enable_equities} options={args.enable_options} news={args.enable_news} scan_only={args.scan_only}")
    if notes:
        for n in notes:
            print(color(f"NOTE: {n}", COLOR_YELLOW, args.no_color))

    for symbol in symbols:
        try:
            scan = analyze_symbol(symbol)
            scans.append(scan)
            scans_by_symbol[symbol] = scan
        except Exception as exc:
            print(color(f"{symbol}: data error: {exc}", COLOR_RED, args.no_color))

    maybe_close_positions(state, scans_by_symbol, args)

    # News advisory, optional and logged only.
    if args.enable_news:
        for scan in scans:
            q = f"{scan['symbol']} quantum computing AI chip stock"
            row = fetch_news(scan["symbol"], q)
            log_news(row, args)

    new_positions_this_cycle = 0
    # Build candidates. This prevents blindly buying every symbol; only best candidates are opened.
    candidates: List[Tuple[float, str, Dict[str, Any], Optional[Dict[str, Any]]]] = []
    for scan in scans:
        symbol = scan["symbol"]
        bull = safe_float(scan["bullish_score"], 0.0)
        bear = safe_float(scan["bearish_score"], 0.0)
        # Equity long candidate.
        if args.enable_equities and bull >= args.bullish_threshold:
            candidates.append((bull, "equity_long", scan, None))
        # Paper short only if explicitly allowed.
        if args.enable_equities and args.allow_paper_short and bear >= args.bearish_threshold:
            candidates.append((bear, "equity_short", scan, None))
        # Option candidates.
        if args.enable_options and bull >= args.bullish_threshold:
            opt = option_chain_candidate(symbol, "call", safe_float(scan["price"]), args)
            if opt:
                candidates.append((bull + safe_float(opt.get("candidate_score", 0.0)) / 5.0, "long_call", scan, opt))
        if args.enable_options and bear >= args.bearish_threshold:
            opt = option_chain_candidate(symbol, "put", safe_float(scan["price"]), args)
            if opt:
                candidates.append((bear + safe_float(opt.get("candidate_score", 0.0)) / 5.0, "long_put", scan, opt))

    candidates.sort(key=lambda x: x[0], reverse=True)
    if args.selection_mode == "best_only":
        candidates = candidates[:1]
    elif args.selection_mode == "top_two":
        candidates = candidates[:2]

    actions: Dict[str, str] = {}
    notes_by_symbol: Dict[str, str] = {}

    for score, ctype, scan, opt in candidates:
        if args.scan_only:
            actions[scan["symbol"]] = f"SCAN_{ctype}"
            notes_by_symbol[scan["symbol"]] = f"candidate score {score:.1f}"
            continue
        if new_positions_this_cycle >= args.max_new_positions_per_cycle:
            break
        if position_count(state) >= args.max_open_positions:
            break
        pos = None
        if ctype == "equity_long":
            pos = execute_equity_entry(state, scan, "long", args)
        elif ctype == "equity_short":
            pos = execute_equity_entry(state, scan, "short", args)
        elif ctype in {"long_call", "long_put"} and opt:
            pos = execute_option_entry(state, opt, args)
        if pos:
            new_positions_this_cycle += 1
            actions[scan["symbol"]] = "OPEN_" + ctype
            notes_by_symbol[scan["symbol"]] = f"opened {pos.get('trade_id')}"

    open_value, unrealized = calc_open_value(state, scans_by_symbol, args)
    equity = safe_float(state.get("cash", 0.0), 0.0) + open_value
    check_halts(state, equity, args)

    for scan in scans:
        symbol = scan["symbol"]
        bull_line = f"Bullish score: {scan['bullish_score']:>5.1f}/100 [{scan['bull_reasons']}]"
        bear_line = f"Bearish score: {scan['bearish_score']:>5.1f}/100 [{scan['bear_reasons']}]"
        action = actions.get(symbol, "WATCH")
        note = notes_by_symbol.get(symbol, "")
        print("\n" + color(symbol, COLOR_BLUE, args.no_color))
        print(f"  Type/Price:       {scan['asset_type']} / {money(scan['price'])}")
        print(f"  EMA20/50/100:     {money(scan['ema20'])} / {money(scan['ema50'])} / {money(scan['ema100'])}")
        print(f"  RSI14:            {scan['rsi14']:.2f}")
        print(f"  Return 5/20/60d:  {pct(scan['ret5d'])} / {pct(scan['ret20d'])} / {pct(scan['ret60d'])}")
        print(f"  ATR14:            {money(scan['atr14'])} ({scan['atr_pct']:.2f}%)")
        print("  " + color(bull_line, COLOR_GREEN, args.no_color))
        print("  " + color(bear_line, COLOR_RED, args.no_color))
        print(f"  Action:           {action} {('- ' + note) if note else ''}")
        log_scan(scan, args, action, note)

    if state.get("halted"):
        print(color(f"\nTRADING HALTED: {state.get('halt_reason', '')}", COLOR_RED, args.no_color))

    print("\n" + "-" * 102)
    print(f"Cash:              {money(safe_float(state.get('cash', 0.0), 0.0))}")
    print(f"Open value:        {money(open_value)}")
    print(f"Total equity:      {money(equity)}")
    print(f"Realized P/L:      {money(safe_float(state.get('realized_pl', 0.0), 0.0))}")
    print(f"Unrealized P/L:    {money(unrealized)}")
    print(f"Fees/commissions:  {money(safe_float(state.get('fees_paid', 0.0), 0.0) + safe_float(state.get('commissions_paid', 0.0), 0.0))}")
    print(f"Open positions:    {position_count(state)}")
    print(f"Logs folder:       {LOG_DIR}")
    print("-" * 102)

    log_equity(state, equity, open_value, unrealized, args)
    save_state(state)


def merge_config(args: argparse.Namespace, config: Dict[str, Any]) -> argparse.Namespace:
    # Convert JSON snake_case keys to argparse attributes. CLI args override config only if not None-ish.
    parser_defaults = build_arg_parser().parse_args([])
    for key, value in config.items():
        if key.startswith("_"):
            continue
        if not hasattr(args, key):
            continue
        current = getattr(args, key)
        default = getattr(parser_defaults, key)
        # If user provided value differs from parser default, keep CLI value.
        if current != default:
            continue
        setattr(args, key, value)
    return args


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Quantum/AI paper investment bot: stocks, ETFs, and options.")
    p.add_argument("--config", default=None, help="Path to JSON config file.")
    p.add_argument("--run-label", default="quantum_ai_v2", help="Label included in logs.")
    p.add_argument("--symbols", nargs="+", default=DEFAULT_UNIVERSE, help="Ticker symbols to scan.")
    p.add_argument("--aliases-json", default=None, help="Optional JSON string for aliases, e.g. '{\"INOQ\":\"IONQ\"}'.")
    p.add_argument("--paper-cash", type=float, default=100.0)
    p.add_argument("--trade-size", type=float, default=50.0)
    p.add_argument("--min-trade-value", type=float, default=10.0)
    p.add_argument("--max-open-positions", type=int, default=1)
    p.add_argument("--max-new-positions-per-cycle", type=int, default=1)
    p.add_argument("--selection-mode", choices=["best_only", "top_two", "all_signals"], default="best_only")
    p.add_argument("--one-position-per-symbol", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--enable-equities", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--enable-options", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--allow-paper-short", action=argparse.BooleanOptionalAction, default=False, help="Allow paper shorting of stocks/ETFs. Disabled by default.")
    p.add_argument("--bullish-threshold", type=float, default=60.0)
    p.add_argument("--bearish-threshold", type=float, default=60.0)
    p.add_argument("--exit-opposite-score", type=float, default=70.0)
    p.add_argument("--equity-fee-rate", type=float, default=0.001)
    p.add_argument("--stop-loss-pct", type=float, default=0.08)
    p.add_argument("--take-profit-pct", type=float, default=0.15)
    p.add_argument("--option-commission", type=float, default=0.65)
    p.add_argument("--max-contract-cost", type=float, default=49.0)
    p.add_argument("--min-dte", type=int, default=14)
    p.add_argument("--max-dte", type=int, default=75)
    p.add_argument("--target-dte", type=int, default=35)
    p.add_argument("--min-option-volume", type=float, default=1.0)
    p.add_argument("--min-open-interest", type=float, default=10.0)
    p.add_argument("--max-option-spread-pct", type=float, default=0.35)
    p.add_argument("--option-stop-loss-pct", type=float, default=0.40)
    p.add_argument("--option-take-profit-pct", type=float, default=0.60)
    p.add_argument("--absolute-stop-pct", type=float, default=0.25)
    p.add_argument("--absolute-stop-value", type=float, default=0.0)
    p.add_argument("--enable-news", action=argparse.BooleanOptionalAction, default=False)
    p.add_argument("--scan-only", action=argparse.BooleanOptionalAction, default=False)
    p.add_argument("--reset", action="store_true")
    p.add_argument("--once", action="store_true")
    p.add_argument("--poll", type=int, default=300)
    p.add_argument("--no-color", action="store_true")
    return p


def postprocess_args(args: argparse.Namespace) -> argparse.Namespace:
    args.equity_fee_rate = normalize_rate(args.equity_fee_rate)
    args.stop_loss_pct = normalize_rate(args.stop_loss_pct)
    args.take_profit_pct = normalize_rate(args.take_profit_pct)
    args.option_stop_loss_pct = normalize_rate(args.option_stop_loss_pct)
    args.option_take_profit_pct = normalize_rate(args.option_take_profit_pct)
    args.absolute_stop_pct = normalize_rate(args.absolute_stop_pct) if args.absolute_stop_pct else 0.0
    args.max_option_spread_pct = normalize_rate(args.max_option_spread_pct)
    aliases = {}
    if args.aliases_json:
        try:
            aliases = json.loads(args.aliases_json)
        except Exception as exc:
            print(f"WARNING: Could not parse --aliases-json: {exc}", file=sys.stderr)
    args.aliases = aliases
    return args


def main() -> int:
    p = build_arg_parser()
    # First parse for config path, then merge full config.
    pre, _ = p.parse_known_args()
    args = p.parse_args()
    if pre.config:
        config = load_json_file(pre.config)
        args = merge_config(args, config)
    args = postprocess_args(args)
    ensure_dirs()
    state = load_state(args)
    if args.once:
        run_cycle(state, args)
        return 0
    print(f"Starting Quantum/AI Paper Bot {VERSION}. Press Ctrl+C to stop.")
    print(f"Poll interval: {args.poll}s")
    try:
        while True:
            try:
                run_cycle(state, args)
            except Exception as exc:
                print(color(f"ERROR during cycle: {exc}", COLOR_RED, args.no_color), file=sys.stderr)
            time.sleep(max(30, int(args.poll)))
    except KeyboardInterrupt:
        save_state(state)
        print("\nStopped. State saved.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
