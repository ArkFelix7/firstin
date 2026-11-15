# FirstIn backend. Run from repo root.
PY := agent/.venv/bin/python
UV ?= $(shell command -v uv 2>/dev/null || echo /Users/aarya/.langflow/uv/uv)
PORT ?= 8000

.PHONY: venv backend backend-offline backend-agent stage stage-offline test warm-vision smoke

venv:
	$(UV) venv --python 3.12 agent/.venv
	$(UV) pip install --python $(PY) -r agent/requirements.txt

backend:            ## auto mode: agent if ANTHROPIC_API_KEY set, else offline
	$(PY) -m uvicorn agent.main:app --reload --reload-dir agent --host 0.0.0.0 --port $(PORT)

backend-offline:    ## force deterministic pipeline (demo-safe)
	FIRSTIN_OFFLINE=1 $(PY) -m uvicorn agent.main:app --reload --reload-dir agent --host 0.0.0.0 --port $(PORT)

stage:              ## demo day: real agent, no auto-reload (runs survive edits)
	$(PY) -m uvicorn agent.main:app --host 0.0.0.0 --port $(PORT)

stage-offline:      ## demo day, no network needed: replays cached real runs
	FIRSTIN_OFFLINE=1 $(PY) -m uvicorn agent.main:app --host 0.0.0.0 --port $(PORT)

test:
	FIRSTIN_OFFLINE=1 FIRSTIN_PACE=0 $(PY) -m pytest agent/tests -q

warm-vision:        ## needs ANTHROPIC_API_KEY; ONLY=la-002 to limit
	$(PY) -m agent.scripts.warm_vision $(if $(ONLY),--only $(ONLY),)

smoke:              ## server must be running
	bash scripts/smoke.sh
