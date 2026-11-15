#!/usr/bin/env bash
# End-to-end curl smoke test against a running backend: preplan -> stream -> interrupt -> approve -> incab.
set -euo pipefail
API=${API:-http://localhost:8000}
BID=${1:-la-002}
echo "== health"; curl -s $API/health; echo
RID=$(curl -s -XPOST $API/preplan -H 'content-type: application/json' -d "{\"building_id\":\"$BID\"}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["run_id"])')
echo "== run $RID (streaming until interrupt)"
python3 - "$API/stream/$RID" <<'PY'
import json, sys, urllib.request
for raw in urllib.request.urlopen(sys.argv[1], timeout=120):
    line = raw.decode().strip()
    if not line.startswith("data:"):
        continue
    e = json.loads(line[5:]); p = e["payload"]
    print(" ", e["type"], p.get("agent") or p.get("name") or "", p.get("tool") or "",
          str(p.get("summary") or p.get("message") or p.get("path") or "")[:90])
    if e["type"] in ("interrupt", "done"):
        break
PY
echo "== ask (pending)"; curl -s -XPOST $API/ask -H 'content-type: application/json' -d "{\"plan_id\":\"$RID\",\"question\":\"Where are the stairs?\"}"; echo
echo "== approve"; curl -s -XPOST $API/approve/$RID -H 'content-type: application/json' -d '{"approved_by":"Capt. Demo","decision":"approve","edits":{"access.hydrants":"Hydrant at Perrino Pl & Union Pacific Ave (officer)"}}'; echo
sleep 4
echo "== incab"; curl -s $API/incab/active; echo
