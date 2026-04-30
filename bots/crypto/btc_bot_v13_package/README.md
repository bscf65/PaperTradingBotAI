# BTC/ETH/SOL Coinbase Public-Data Paper Bot v13

This is a paper-trading simulator. It uses Coinbase public market data only. It does not use API keys and does not place real orders.

## v13 additions: local computer-time logs + JSON config files

v13 writes both local computer time and UTC time into the CSV files. The terminal display also shows local time first. Daily P/L rolls over using your computer's local date instead of UTC.

Check or change your Kali/Linux system timezone with:

```bash
timedatectl
sudo timedatectl set-timezone America/New_York
```

The bot still keeps UTC columns too, because Coinbase/exchange data is commonly timestamped in UTC.

v13 also lets you put the long command-line settings into a separate JSON file.

Instead of typing this every time:

```bash
./run_btc_bot.sh btc_eth_sol_coinbase_paper_bot_v13.py \
  --reset \
  --paper-cash 100 \
  --trade-size 50 \
  --loss-stop-value 50 \
  --absolute-stop-pct 25 \
  --daily-profit-lock 25 \
  --idle-cash-apy 0.04 \
  --fee-model conservative \
  --max-spread-pct 0.010 \
  --edge-threshold 45 \
  --min-profit-minutes 5 \
  --quick-profit-pct 0.0015 \
  --poll 60
```

You can now run:

```bash
./run_btc_bot.sh btc_eth_sol_coinbase_paper_bot_v13.py --config configs/aggressive_100.json --reset
```

Command-line options override config-file values. For example:

```bash
./run_btc_bot.sh btc_eth_sol_coinbase_paper_bot_v13.py \
  --config configs/aggressive_100.json \
  --reset \
  --trade-size 25
```

That uses the aggressive config, but changes the trade size to $25.



## Full config files: every supported bot flag is listed

The config files in `configs/` now explicitly list every supported bot option, even when the value is just the default. This makes each JSON file an editable template.

Included full config files:

```text
configs/all_flags_template.json
configs/aggressive_100.json
configs/balanced_100.json
configs/conservative_100.json
```

Important safety note: `reset` and `once` are included in the JSON files so you can see that they exist, but they are set to `false` by default. I recommend passing `--reset` on the command line only when you intentionally want to wipe logs/state and start fresh.

Use a config:

```bash
./run_btc_bot.sh btc_eth_sol_coinbase_paper_bot_v13.py --config configs/aggressive_100.json --reset
```

Override one config value from the terminal:

```bash
./run_btc_bot.sh btc_eth_sol_coinbase_paper_bot_v13.py \
  --config configs/aggressive_100.json \
  --reset \
  --trade-size 25
```

Because command-line flags override the config file, this uses the aggressive config but changes only the trade size.

## Included config files

After setup, these will be in:

```text
~/btc-bot/configs/
```

Included examples:

```text
configs/aggressive_100.json
configs/balanced_100.json
configs/conservative_100.json
```

### Aggressive $100 config

```bash
./run_btc_bot.sh btc_eth_sol_coinbase_paper_bot_v13.py --config configs/aggressive_100.json --reset
```

### Balanced $100 config

```bash
./run_btc_bot.sh btc_eth_sol_coinbase_paper_bot_v13.py --config configs/balanced_100.json --reset
```

### Conservative $100 config

```bash
./run_btc_bot.sh btc_eth_sol_coinbase_paper_bot_v13.py --config configs/conservative_100.json --reset
```

## Important config-file note

The config files intentionally do **not** set `reset`.

Use `--reset` on the command line only when you want a fresh clean simulation.

Use no `--reset` when you want to continue from the saved JSON state file.

## Install

From the unzipped package folder:

```bash
bash setup_btc_bot.sh
cd ~/btc-bot
```

If the popup tool is missing:

```bash
sudo apt install -y libnotify-bin
```

The bot will still run without `notify-send`; you just may not get desktop popups.

## Help

```bash
./run_btc_bot.sh --help
./run_btc_bot.sh btc_eth_sol_coinbase_paper_bot_v13.py --help
```

## Edit a config file

Use nano:

```bash
nano ~/btc-bot/configs/aggressive_100.json
```

Example config values:

```json
{
  "products": ["BTC-USD", "ETH-USD", "SOL-USD"],
  "paper_cash": 100,
  "trade_size": 50,
  "loss_stop_value": 50,
  "absolute_stop_pct": 25,
  "daily_profit_lock": 25,
  "idle_cash_apy": 0.04,
  "fee_model": "conservative",
  "max_spread_pct": 0.01,
  "edge_threshold": 45,
  "min_profit_minutes": 5,
  "quick_profit_pct": 0.0015,
  "poll": 60
}
```

Use underscores in config keys, like:

```text
paper_cash
trade_size
loss_stop_value
absolute_stop_pct
```

Hyphenated names also work, but underscores are cleaner.

## Absolute stop settings

You can use a percentage, a dollar value, or both.

Percentage stop:

```json
"absolute_stop_pct": 25
```

With $100 starting paper cash, this stops the bot at about $75 equity.

Dollar stop:

```json
"absolute_stop_value": 25
```

With $100 starting paper cash, this also stops the bot at about $75 equity.

Disable the percentage stop:

```json
"absolute_stop_pct": 0
```

If both percentage and dollar stops are enabled, whichever triggers first stops trading.

## Colors and alerts

- Yellow = temporary halt, such as drawdown halt or normal loss stop.
- Red = absolute final stop.
- The bot beeps when either warning first triggers.
- The bot tries to show a desktop popup when the absolute final stop triggers.
- The score line remains red to make it easier to spot.

Disable colors:

```bash
--no-color
```

Disable beeps:

```bash
--no-beep
```

Disable popup:

```bash
--no-popup
```

Set beep count in config:

```json
"beep_count": 5
```

Or on the command line:

```bash
--beep-count 5
```

## Run inside tmux

```bash
cd ~/btc-bot
tmux new -s btcbot
```

Run the bot command, then detach:

```text
Ctrl+B
D
```

Reconnect:

```bash
tmux attach -t btcbot
```

## Analyze

```bash
./run_btc_bot.sh analyze_bot_performance_v13.py
```

## v13 log files

```text
logs/paper_state_v13.json
logs/paper_trades_v13.csv
logs/paper_equity_log_v13.csv
logs/paper_daily_pnl_v13.csv
logs/paper_tax_capital_gains_v13.csv
logs/paper_research_log_v13.csv
```

Most CSV files now include local-time columns such as:

```text
timestamp_local
date_local
acquire_date_local
dispose_date_local
```

and also UTC columns such as:

```text
timestamp_utc
date_utc
acquire_date_utc
dispose_date_utc
```

## What is the JSON state file?

The state file is the bot's saved simulation memory:

```text
logs/paper_state_v13.json
```

It remembers current cash, open positions, lots, realized P/L, high-water mark, alerts, and halt status.

Use `--reset` when you want to start a new clean test. Do not use `--reset` when you want to continue the same simulation.

## Reminder

This is not financial, tax, or legal advice. It is a paper-trading test lab.
