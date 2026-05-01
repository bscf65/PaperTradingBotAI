# InvestAI AI Private-Tech Paper Bot v4 — Global News / China / BRICS Layer

Paper-only testing bot for AI/private-market access funds, AI ETFs, semiconductor ETFs, and related sentiment names.

Default universe:

- `VCX` - Fundrise Innovation / Growth Tech Fund style AI/private-tech exposure
- `DXYZ` - Destiny Tech100 / private-tech exposure proxy
- `ARKK`, `ARKQ` - innovation / robotics / AI ETFs
- `QQQ` - Nasdaq 100 technology proxy
- `SMH` - semiconductor ETF proxy
- `AIQ` - AI ETF proxy

This bot does **not** place real trades and does **not** connect to a broker.

## What v4 adds

v4 expands the advisory news layer. It can now check and log:

- GDELT global news search
- Briefs / Market Briefs public category pages
- BBC Business / BBC World RSS
- Al Jazeera public RSS
- India Today latest/business RSS
- CNBC top stories RSS
- MarketWatch top stories RSS
- China/BRICS monitor via discounted source weighting, including a lower-weight China state-media bucket

News remains **advisory-only**. It does not force trades. The purpose is to log context so later machine-learning analysis can test whether source/category/news-impact signals actually helped.

## China, blogs, and BRICS caution

v4 deliberately treats China/state-aligned and blog-like signals with extra caution:

- China/state-aligned feeds are assigned lower source weight.
- Blog/vlog/social rumor terms are logged as `low_trust_hits`.
- BRICS and China narrative hits are logged separately as `brics_hits` and `china_hits`.
- The output includes `news_impact_score`, but it is only a rough advisory score.

This is not an attempt to declare news as true/false. It is a way to preserve signal context for later analysis while avoiding blindly trusting low-confidence sources.

## Install location

Download/unzip this package under:

```bash
/home/bscf/Documents/InvestAI/PrivateAI
```

Install to the working folder:

```bash
cd /home/bscf/Documents/InvestAI/PrivateAI
unzip private_ai_bot_v4_globalnews_package.zip
cd private_ai_bot_v4_globalnews_package
bash setup_private_ai_bot.sh
cd ~/ai-private-tech-bot
```

## Run scan-only first

```bash
./run_private_ai_bot.sh private_ai_paper_bot_v4.py \
  --config configs/scan_only_private_ai.json \
  --once
```

## Start $100 paper simulation

```bash
./run_private_ai_bot.sh private_ai_paper_bot_v4.py \
  --config configs/private_ai_100.json \
  --reset
```

## Equity-only mode

This is safer for a tiny $100 test account because options may be too expensive.

```bash
./run_private_ai_bot.sh private_ai_paper_bot_v4.py \
  --config configs/equity_only_private_ai_100.json \
  --reset
```

## News config fields

```json
"enable_news": true,
"news_sources": "gdelt,briefs,globalfeeds",
"briefs_categories": "stock,technology,crypto,economy",
"briefs_max_headlines": 40,
"global_news_feeds": "bbc_business,bbc_world,aljazeera_all,india_today_latest,india_today_business,cnbc_top,marketwatch_top,cgtn_world",
"global_news_max_items": 80,
"watch_china_brics": true
```

## News log

News is logged to:

```bash
~/ai-private-tech-bot/logs/private_ai_news_v4.csv
```

Important columns:

```text
article_count
gdelt_article_count
briefs_article_count
global_article_count
global_scanned_count
risk_hits
positive_hits
china_hits
brics_hits
low_trust_hits
global_weighted_impact
news_impact_score
source_breakdown
source_buckets
headline_sample
```

## Analyze private-AI bot results

```bash
./run_private_ai_bot.sh analyze_private_ai_performance_v4.py
```

## Build machine-learning dataset from all bots

This tool scans logs from:

- `~/btc-bot/logs/*.csv`
- `~/options-bot/logs/*.csv`
- `~/quantum-ai-bot/logs/*.csv`
- `~/ai-private-tech-bot/logs/*.csv`

Then creates:

```bash
~/investai-ml-data/master_ml_events_v4.csv
~/investai-ml-data/master_ml_events_v4.jsonl
```

Run:

```bash
./run_private_ai_bot.sh collect_investai_ml_data_v4.py
```

This does **not** train a model yet. It only builds a normalized dataset for future machine-learning experiments.

## Logs

The bot writes:

```text
logs/private_ai_state_v4.json
logs/private_ai_trades_v4.csv
logs/private_ai_equity_v4.csv
logs/private_ai_scan_v4.csv
logs/private_ai_news_v4.csv
```

## Important cautions

- VCX/DXYZ may have limited or unusual data availability.
- Private-tech access funds can trade at premiums/discounts and be very volatile.
- News/blog/vlog sentiment is advisory only and should not force trades.
- China/BRICS feeds and state-aligned sources are logged with lower confidence.
- Keep this paper-only until results prove the logic is useful.
- Do not commit logs, tax files, API keys, or state JSON to GitHub.

## Suggested Git ignore additions

```gitignore
logs/
*.csv
*_state_*.json
.venv/
__pycache__/
*.pyc
```
