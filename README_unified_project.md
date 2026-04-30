# InvestAI Unified ProjectMain

Local-only paper-trading research project.

Root:

```text
/home/bscf/Documents/InvestAI/AIBots Project/ProjectMain
```

Dashboard:

```text
http://127.0.0.1:8765/
```

Common commands:

```bash
./investai.sh status
./investai.sh dashboard
./investai.sh start crypto --config configs/aggressive_100.json --once
./investai.sh start crypto --config configs/balanced_100.json --once
./investai.sh start crypto --config configs/conservative_100.json --once
./investai.sh analyze all
```

Notes:
- `configs/*.json` in the crypto commands are resolved inside `bots/crypto/btc_bot_v13_package`.
- `options`, `quantum-ai`, and `private-ai` folders are present as placeholders until their bot packages are installed.
- Bot logs launched through `investai.sh` are written under `logs/{bot-name}`.
