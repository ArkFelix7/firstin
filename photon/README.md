# FirstIn x Photon: officer approval and Q&A over iMessage

When the agent reaches its human-in-the-loop interrupt, the officer's iPhone gets an iMessage:

```
FirstIn pre-plan ready for approval
1234 Example St, Houston, TX

4-story, built 1978, Steel frame (era-inferred)

Top hazards:
1. Chlorine/oxidizer — Floor 1 east
2. Lightweight truss roof — Roof
3. Possible asbestos — Mechanical rooms

Reply APPROVE, REJECT, or ask a question (e.g. "where's the standpipe?"). [ref eac9]
```

| Officer sends | Bridge does |
|---|---|
| `APPROVE` / `yes` / `ok` / `lgtm` (tapbacks 👍/❤️ also work in v1 `cloud` mode only) | `POST :8000/approve/{run_id} {approved_by: <sender>, decision: "approve"}`, replies "Approved...", then polls `/incab/active` and confirms "Live on Engine 12 in-cab unit" |
| `REJECT` / `no` / `deny` | `POST /approve/{run_id} {decision: "reject"}` |
| `STATUS` | `GET /plan/{run_id}`, replies with a summary (stories, hazards, stairs, roof) |
| `HELP` | Lists the commands |
| anything else | `POST /ask {plan_id, question}`, replies with `answer` (shows a typing indicator while it waits) |

Safety:
- Only numbers in `OFFICER_PHONE` can approve or reject. Anyone else gets a polite refusal.
- A plan that is already decided can't be decided again.
- If the backend is down, the officer is told to use the dashboard. Nothing is silently dropped.
- Answers come only from the plan via `/ask`. On failure the reply is "VERIFY ON SITE".

When several plans are pending, add the ref code: `APPROVE eac9`. Otherwise the bridge uses the run it last messaged that officer about.
The run_id to conversation mapping is kept in memory (`GET /runs` to inspect it), so restarting the bridge forgets pending runs. Re-trigger `/notify` if that happens.

## Run it

Requires Node 22 or later (tested on Node 24 with `tsx`). Bun is not required.

```bash
cd photon
npm install
cp .env.example .env        # then fill it in (see "What the human must do")

npm run dry-run             # no credentials: iMessages are printed and you type the officer's replies
npm start                   # real iMessage: Photon 2.0 Beta (v2, auto for pho_prj_ ids) or Spectrum Cloud v1
```

The bridge listens on `:8010` (`PHOTON_PORT`).

### Dry-run walkthrough (no Photon account, no real backend)

```bash
python3 hardware/stub_server.py --port 8001 --photon http://localhost:8010    # fake backend that calls /notify
cd photon && BACKEND_URL=http://localhost:8001 npm run dry-run
# another terminal:
curl -XPOST localhost:8001/preplan -d '{}'        # -> the "iMessage" prints in the dry-run terminal
# in the dry-run terminal, type:
where's the standpipe?
approve
#   from:+19998887777 approve   -> tests the "not an officer" refusal
#   react:👍                    -> simulates a tapback
```

You can also inject an inbound message over HTTP from any mode: `curl -XPOST localhost:8010/simulate -d '{"text":"approve"}'`. It returns the replies as JSON.

### HTTP API of the bridge

- `POST /notify {run_id, address?, summary?, top_hazards?: (string | {type, location})[], plan_id?, to?}` returns `{ok, sent_to, code}`
- `POST /simulate {from?, text?, reaction?}` returns `{ok, replies}`
- `GET /health`, `GET /runs`

## Backend hook (one call, for the backend/integrator)

On the approval interrupt (when the plan status becomes `PENDING_APPROVAL`, right where the `interrupt` SSE event is emitted), add:

```python
# helper (top of the server module)
import json, os, threading, urllib.request
def notify_photon(run_id, plan):
    def _go():
        try:
            body = {"run_id": run_id, "address": plan.get("building", {}).get("address"),
                    "summary": (plan.get("voice_brief") or "")[:300], "top_hazards": plan.get("hazards", [])[:3]}
            urllib.request.urlopen(urllib.request.Request(os.getenv("PHOTON_URL", "http://localhost:8010") + "/notify",
                data=json.dumps(body).encode(), headers={"content-type": "application/json"}), timeout=5)
        except Exception as e:
            print("[photon] notify skipped:", e)
    threading.Thread(target=_go, daemon=True).start()

# the one line, at the interrupt:
notify_photon(run_id, plan)
```

The call runs in a thread and does nothing if the bridge is down, so the agent never blocks on iMessage. Assumptions, which you should change here if they don't match the backend:
- `/ask` receives `plan_id = run_id`. If the backend uses a separate plan id, include `"plan_id": ...` in the `/notify` body.
- `/ask` should answer while the plan is still `PENDING_APPROVAL` (the officer asks questions before approving). If it only answers approved plans, the officer gets "Couldn't get an answer...".

## What the human must do (Photon 2.0 Beta, which is what our credentials are)

The credentials are for the **Photon 2.0 Beta** platform (dashboard https://app.beta.photon.codes, project id `pho_prj_...`, project API key `pho_sk_...`).
spectrum-ts 12.x talks to the v1 platform and returns 422 for these ids, so the bridge has a **`PHOTON_MODE=v2`** transport. It sends with the Beta HTTP API (`POST https://api.photon.codes/v1/projects/{id}/messages`) and receives live inbound messages over Socket.IO (`/v1/projects/{id}/events/ws`, `message.received` events). v2 is chosen automatically when the project id starts with `pho_prj_`.

`photon/.env` (git-ignored, never commit). New variable names come first, and the legacy names are still read:
```
PHOTON_MODE=v2
PHOTON_PROJECT_ID=pho_prj_...      # or SPECTRUM_PROJECT_ID
PHOTON_API_KEY=pho_sk_...          # or SPECTRUM_PROJECT_SECRET. Needs project:read + project:write (platforms:write only to assign lines)
PHOTON_ORG_ID=pho_org_...          # informational; project-key calls don't need it
OFFICER_PHONE=+1XXXXXXXXXX
```

Setup status and the remaining human step:
1. Done: the project key works, iMessage is in **shared** mode, and a shared-line assignment exists for the officer:
   **officer +1XXXXXXXXXX -> Photon line +1 (628) 998-8619** (created via `POST /platforms/imessage/assignments`, opt-in `pending`).
2. **Human: from the officer iPhone (+1XXXXXXXXXX), open Messages, start a new iMessage (blue bubble, not SMS) to +1 628-998-8619, and send any text (e.g. `hi`).**
   Shared Beta lines **cannot send the first message**. Until the officer texts in, `/notify` returns `sent_to: []` with an explanatory `errors` entry.
   The bridge remembers undelivered approval requests and sends them as soon as the officer texts.
   On iPhone, check Settings -> Apps -> Messages -> Send & Receive to confirm you're sending *from* the phone number, not an Apple ID email.
3. `npm start`. The log should show `[photon-v2] project ok; imessage mode=shared assignments=+1XXXXXXXXXX->+16289988619` and `socket subscribed`.
4. Smoke test: `curl -XPOST localhost:8010/notify -H 'content-type: application/json' -d '{"run_id":"test1","address":"Test St","summary":"test","top_hazards":["none"]}'`
   returns `sent_to: ["+1XXXXXXXXXX"]`, and the phone gets the text. Replies show up in the log as `[photon-v2] event message.received` and `[bridge] <- +1XXXXXXXXXX: ...`.
5. Beta iMessage supports only text and images, so **tapbacks are not supported in v2**. Reply with the words APPROVE or REJECT.
6. A send that is "accepted" isn't confirmed as delivered. Check https://app.beta.photon.codes/project/activity if a text doesn't show up.

### Older path: Spectrum Cloud v1 (`PHOTON_MODE=cloud`)
Only for v1 credentials from app.photon.codes. It uses spectrum-ts `Spectrum({projectId, projectSecret, providers:[imessage.config()]})`.

### Fallback: local iMessage (no Photon account)

If the beta signup stalls, a Mac signed into Messages with an Apple ID that is **different** from the officer's phone can send and receive directly:

```bash
npm install @spectrum-ts/imessage-local     # pulls better-sqlite3 (native)
PHOTON_MODE=local npm start
```

Grant your terminal **Full Disk Access** (System Settings -> Privacy & Security), because it reads `~/Library/Messages/chat.db`. This path is untested and doesn't count for the Photon track.

## Implementation notes

- SDK: `spectrum-ts` 12.16, verified against the repo source and docs (github.com/photon-hq/spectrum-ts). The calls used are `Spectrum({projectId, projectSecret, providers: [imessage.config()]})`, `imessage(app).user(phone)`, `imessage(app).space.create(user)`, `space.send(text)`, `for await (const [space, message] of app.messages)`, `space.responding(fn)` (typing indicator), and `message.content.type === "text" | "reaction" | "reply"`.
- Files: `src/index.ts` (HTTP server and mode selection), `src/bridge.ts` (intents, mapping, backend calls), and `src/transport.ts` (`PhotonV2Transport` for the Beta HTTP API and Socket.IO, `SpectrumTransport` for v1 cloud/local, and `DryRunTransport`).
- v2 details: a send needs `spaceId` and the agent's `senderId`. Both are learned from the officer's inbound message (or from `GET /messages?direction=received` history after a restart). Replies set `parentMessageId`, and every send carries an `Idempotency-Key`. A typing indicator is shown while the bridge waits on `/ask` (`POST /spaces/{id}/typing`). The Socket.IO cursor is kept in memory.
- Tested: dry-run over stdin and over `/simulate` against `hardware/stub_server.py`, covering notify, question, non-officer refusal, status, tapback approve, double-approve guard and in-cab confirmation. Cloud mode fails cleanly when credentials are missing.
- v2 tested live: credentials verified, shared-line assignment created, Socket.IO subscribed, and `/notify` correctly reports that the officer must text first. The full round trip is waiting on the officer's first text.
- Not tested: Spectrum Cloud v1 (we have no v1 credentials) and local mode.
