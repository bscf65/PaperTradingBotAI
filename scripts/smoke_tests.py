#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOT_PATH = ROOT / "bots/crypto/btc_bot_v13_package/btc_eth_sol_coinbase_paper_bot_v13.py"
ANALYZER_PATH = ROOT / "bots/crypto/btc_bot_v13_package/analyze_bot_performance_v13.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load module spec for {path}")
    module = importlib.util.module_from_spec(spec)
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


def main() -> int:
    test_shell_syntax()
    test_paper_only_source()
    test_log_dir_env_override_and_config()
    test_analyzer_minimal_logs()
    print("Smoke tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
