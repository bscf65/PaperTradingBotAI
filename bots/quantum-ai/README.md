# Quantum/AI Paper Investment Bot v2

A paper-only scanner/simulator for quantum-computing, AI, semiconductor, and related ETF opportunities.

Default focus list:

- `IONQ` — IonQ
- `RGTI` — Rigetti Computing
- `QBTS` — D-Wave Quantum
- `QTUM` — Quantum computing ETF
- `ARKQ` — Autonomous technology / robotics ETF
- `SMH` — Semiconductor ETF

The bot also recognizes the common typo `INOQ` as an alias for `IONQ`.

## Important safety notes

This tool is for **paper trading and research only**.

It does not connect to a broker.
It does not place real orders.
It does not use margin.
It does not provide financial, tax, or investment advice.

Options can lose value quickly. Shorting stocks/ETFs can create large losses in real life. Paper shorting is disabled by default.

## Install location

The package is intended to be downloaded/unzipped under:

```bash
/home/bscf/Documents/InvestAI/QuantumAI
```

The setup script installs the working bot folder at:

```bash
/home/bscf/quantum-ai-bot
```

## Install

```bash
cd /home/bscf/Documents/InvestAI/QuantumAI
unzip quantum_ai_bot_v2_investai_package.zip
cd quantum_ai_bot_v2_investai_package
bash setup_quantum_ai_bot.sh
cd ~/quantum-ai-bot
```

## Run a scan-only check first

```bash
./run_quantum_ai_bot.sh quantum_ai_paper_bot_v2.py \
  --config configs/scan_only_quantum_ai.json \
  --once
```

## Start a $100 paper simulation

```bash
./run_quantum_ai_bot.sh quantum_ai_paper_bot_v2.py \
  --config configs/quantum_ai_100.json \
  --reset
```

## Equity-only safer mode

Options contracts may often be too expensive for a $100 paper account. This mode disables options and only simulates stock/ETF paper positions:

```bash
./run_quantum_ai_bot.sh quantum_ai_paper_bot_v2.py \
  --config configs/equity_only_quantum_ai_100.json \
  --reset
```

## Analyze results

```bash
./run_quantum_ai_bot.sh analyze_quantum_ai_performance_v2.py
```

## Logs

Logs are written to:

```bash
~/quantum-ai-bot/logs
```

Main files:

```text
quantum_ai_state_v2.json
quantum_ai_trades_v2.csv
quantum_ai_equity_v2.csv
quantum_ai_scan_v2.csv
quantum_ai_news_v2.csv
```

The JSON state file is the bot's memory between runs. Use `--reset` when you want to wipe the previous simulation and start fresh.

## What the bot analyzes

For each ticker it calculates:

- EMA20 / EMA50 / EMA100 trend
- RSI14
- 5-day, 20-day, and 60-day returns
- ATR volatility
- volume ratio
- bullish score
- bearish score
- optional GDELT news advisory
- affordable long call / long put candidates when options are enabled

## Modes

### Long equity / ETF paper investing

The bot can simulate buying stock/ETF shares when bullish conditions are strong.

### Long calls and long puts

The bot can simulate buying calls for bullish setups and buying puts for bearish setups.

### Paper shorting

`allow_paper_short` exists, but it is disabled by default. Keep it disabled while learning. Use long puts for bearish options practice instead.

## Common commands

Run one scan:

```bash
./run_quantum_ai_bot.sh quantum_ai_paper_bot_v2.py --config configs/scan_only_quantum_ai.json --once
```

Run continuous simulation:

```bash
./run_quantum_ai_bot.sh quantum_ai_paper_bot_v2.py --config configs/quantum_ai_100.json --reset
```

Stop with:

```text
Ctrl+C
```

Analyze:

```bash
./run_quantum_ai_bot.sh analyze_quantum_ai_performance_v2.py
```

## GitHub safety

Do not upload:

```text
.venv/
logs/
quantum_ai_state_*.json
quantum_ai_trades_*.csv
quantum_ai_equity_*.csv
quantum_ai_scan_*.csv
quantum_ai_news_*.csv
```

Upload code, README, setup scripts, runner scripts, and example configs only.
