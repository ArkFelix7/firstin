Unzip the CoStar data kit here as kit/ (kit/index.md, kit/data/*.jsonl, kit/commercial-properties.csv).
Proprietary: everything in this folder except this README and .gitignore is git-ignored. Never commit it.
agent/tools/costar.py reads agent/cache/costar/<building_id>.json first (also git-ignored), then the kit.
Rebuild the per-building cache:  agent/.venv/bin/python -m agent.tools.costar build [building_id ...]
Or set COSTAR_DATA_DIR in .env.
