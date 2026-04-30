#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOT_PATH = ROOT / "bots/crypto/btc_bot_v13_package/btc_eth_sol_coinbase_paper_bot_v13.py"
ANALYZER_PATH = ROOT / "bots/crypto/btc_bot_v13_package/analyze_bot_performance_v13.py"
BACKTEST_PATH = ROOT / "bots/crypto/btc_bot_v13_package/backtest_walk_forward_v13.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load module spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_shell_syntax() -> None:
    subprocess.run(["bash", "-n", str(ROOT / "investai.sh")], check=True)


def test_paper_only_source() -> None:
    source = BOT_PATH.read_text(encoding="utf-8")
    banned = [
        "api_key",
        "api-secret",
        "create_order",
        "place_order",
        "/orders",
        "private/order",
    ]
    found = [term for term in banned if term.lower() in source.lower()]
    assert not found, f"possible live-trading terms found: {found}"


def test_log_dir_env_override_and_config() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["INVESTAI_LOG_DIR"] = tmp
        bot = load_module(BOT_PATH, "paper_bot_smoke")
        assert bot.LOG_DIR == Path(tmp)
        config = bot.load_config_file("configs/balanced_100.json")
        assert config["estimated_state_tax_rate"] == 0.093
        assert config["slippage_bps"] > 0
        assert config["missed_fill_rate"] > 0


def test_analyzer_minimal_logs() -> None:
    analyzer = load_module(ANALYZER_PATH, "analyzer_smoke")
    with tempfile.TemporaryDirectory() as tmp:
        log_dir = Path(tmp)
        (log_dir / "paper_equity_log_v13.csv").write_text(
            "timestamp_local,equity,benchmark_btc_equity,benchmark_eth_equity,benchmark_sol_equity,benchmark_equal_weight_equity\n"
            "2026-04-30T00:00:00-07:00,100.0,100.0,100.0,100.0,100.0\n"
            "2026-04-30T00:01:00-07:00,101.0,100.5,100.2,99.8,100.17\n",
            encoding="utf-8",
        )
        assert analyzer.analyze(log_dir) == 0


def test_walk_forward_backtest() -> None:
    backtest = load_module(BACKTEST_PATH, "backtest_smoke")
    rows = []
    price = 100.0
    for i in range(180):
        price *= 1.0005 + (0.001 if i % 17 == 0 else 0.0) - (0.0008 if i % 29 == 0 else 0.0)
        rows.append(
            {
                "time": f"2026-01-01T00:{i % 60:02d}:00Z" if i < 60 else f"2026-01-01T{i // 60:02d}:{i % 60:02d}:00Z",
                "Open": price * 0.999,
                "High": price * 1.003,
                "Low": price * 0.997,
                "Close": price,
                "Volume": 1000 + i,
            }
        )
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        csv_path = tmp_path / "synthetic_candles.csv"
        pd = __import__("pandas")
        pd.DataFrame(rows).to_csv(csv_path, index=False)
        df = backtest.load_candles(csv_path)
        args = backtest.argparse.Namespace(
            paper_cash=1000.0,
            trade_size=100.0,
            fee_rate=0.006,
            slippage_bps=5.0,
            synthetic_spread_pct=0.001,
            missed_fill_rate=0.0,
            estimated_short_term_tax_rate=0.22,
            estimated_state_tax_rate=0.093,
            train_bars=80,
            test_bars=30,
            step_bars=30,
            min_train_trades=0,
        )
        results, promotions = backtest.walk_forward(df, args, "BTC-USD")
        assert not results.empty
        assert not promotions.empty
        assert "decision" in promotions.columns


def main() -> int:
    test_shell_syntax()
    test_paper_only_source()
    test_log_dir_env_override_and_config()
    test_analyzer_minimal_logs()
    test_walk_forward_backtest()
    print("Smoke tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
