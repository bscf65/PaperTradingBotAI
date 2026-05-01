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
./investai.sh start options --config configs/scan_only_with_news.json --once
./investai.sh start options --config configs/two_way_default.json --once
./investai.sh start quantum --config configs/scan_only_quantum_ai.json --once
./investai.sh start quantum --config configs/quantum_ai_100.json --once
./investai.sh start privateai --config configs/scan_only_private_ai.json --once
./investai.sh start privateai --config configs/private_ai_100.json --once
./investai.sh analyze all
```

Notes:
- `configs/*.json` in the crypto commands are resolved inside `bots/crypto/btc_bot_v13_package`.
- `configs/*.json` for options, quantum-ai, and private-ai are resolved inside each installed bot folder.
- Bot logs launched through `investai.sh` are written under `logs/{bot-name}`.
- All installed bots are paper-trading simulators/scanners only. They do not place live broker orders.
