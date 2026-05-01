# Options ETF Paper Bot v4

Paper-only two-way ETF options scanner and simulator.

This bot does **not** place real trades. It is for learning, scanning, and paper simulation.

## What v4 fixes

v4 is the safer $100-account version. It tightens the same type of issue we saw in the crypto bot: over-allocation and trades that do not fit the small account.

- Defaults changed to a $100 paper account.
- Default trade size changed to $50.
- Default max contract premium changed to $49 so commission can still fit inside the trade budget.
- Default max open positions changed to 1.
- Default max new positions per cycle remains 1.
- ETF shorting is disabled by default.
- The bot now shows a **contract affordability cap** every cycle.
- Option scans now use the affordability cap, not just the static max contract cost.

## What it does

- Bullish setups can simulate **long calls**.
- Bearish setups can simulate **long puts**.
- Optional ETF long paper simulation.
- ETF short simulation exists, but is disabled by default for the $100 test.
- Internal sub-bot votes:
  - `trend_bot`
  - `mean_reversion_bot`
  - `breakout_bot`
- Optional GDELT news advisory.
- News is advisory-only and does not directly force trades.

## Install from Fraser's InvestAI/ETF folder

Download/unzip the package under:

```bash
/home/bscf/Documents/InvestAI/ETF
```

Then run:

```bash
cd /home/bscf/Documents/InvestAI/ETF
unzip options_bot_v4_investai_etf_package.zip
cd options_bot_v4_investai_etf_package
bash setup_options_bot.sh
cd ~/options-bot
```

## Run scan-only with news

```bash
./run_options_bot.sh options_etf_paper_bot_v4.py \
  --config configs/scan_only_with_news.json \
  --once
```

## Run the safer $100 two-way options paper simulation

```bash
./run_options_bot.sh options_etf_paper_bot_v4.py \
  --config configs/two_way_default.json \
  --reset
```

## Analyze results

```bash
./run_options_bot.sh analyze_options_performance_v4.py
```

## Main config files

- `configs/two_way_default.json` — $100 long-call / long-put paper simulation.
- `configs/scan_only_with_news.json` — no paper trades, scan only.
- `configs/etf_long_short_paper.json` — allows ETF long but keeps ETF short disabled by default.
- `configs/all_flags_template.json` — same safe defaults as `two_way_default.json`.

## Important options

| Setting | v4 safe default | Meaning |
|---|---:|---|
| `paper_cash` | 100 | Starting paper cash |
| `trade_size` | 50 | Max paper cash per new position |
| `max_contract_cost` | 49 | Max option premium before commission |
| `option_commission_per_contract` | 0.65 | Simulated option commission |
| `max_open_positions` | 1 | Prevents using all cash too fast |
| `max_new_positions_per_cycle` | 1 | Prevents multiple new trades in one scan |
| `absolute_stop_pct` | 25 | Halt if account falls 25% from starting cash |
| `allow_etf_short` | false | Keeps real-world unlimited-short-risk away from beginner tests |
| `scan_only` | false | Show candidates only when true |
| `enable_news` | true | Pull advisory-only GDELT headlines |

## Contract affordability cap

The display now shows:

```text
Contract affordability cap: $49.00 premium max after commission
```

That cap is calculated from:

```text
available cash
trade_size
max_contract_cost
option commission
```

This prevents the bot from scanning or selecting option contracts that cannot actually fit inside the account/trade budget.

## Lingo

- **Long call**: bullish option trade. Max loss is premium paid plus commission.
- **Long put**: bearish option trade. Max loss is premium paid plus commission.
- **ETF long**: buy the ETF, profit if it rises.
- **ETF short**: paper simulation of shorting the ETF, profit if it falls. Real shorting requires margin and has larger risk.
- **DTE**: days to expiration.
- **Open interest**: number of open option contracts.
- **Spread**: difference between bid and ask. Wide spreads are dangerous.

## Output files

```text
logs/options_state_v4.json
logs/options_trades_v4.csv
logs/options_equity_v4.csv
logs/options_scan_v4.csv
logs/options_news_v4.csv
```

## Warnings

- This is paper-only.
- It does not connect to a broker.
- It does not place real trades.
- Options can lose money quickly.
- A $100 account may find very few affordable liquid contracts.
- Real short selling can lose more than the initial trade amount.
- News/headlines can be delayed, duplicated, biased, or wrong.
