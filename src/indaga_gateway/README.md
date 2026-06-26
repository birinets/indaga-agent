# Indaga Gateway

The thin, **single-owner** HTTP surface the Indaga iOS app talks to. It runs on *your own machine*
next to `indaga-agent`, imports the engine **in-process**, mints an authorized `Context`, dispatches to
`call_operation`, and passes the **evidence envelope through to the client verbatim** — no business
logic, no second confidence model. This is the personal / bring-your-own-server model: your health data
never leaves your machine; the phone connects over a private link.

## Run

```bash
cd Indaga-agent
# deps (once): fastapi + uvicorn live in this project's .venv
INDAGA_SUBJECT=<you> PYTHONPATH=src .venv/bin/python -m indaga_gateway serve
```

Environment:
- `INDAGA_SUBJECT` — the subject this server serves (default `demo`).
- `INDAGA_USER_DIR` — ingest source dir (only used on a never-built subject; defaults to the store dir).
- `INDAGA_GATEWAY_HOST` / `INDAGA_GATEWAY_PORT` — bind address (default `127.0.0.1:8765`).
- `INDAGA_GATEWAY_ALLOW_INSECURE=1` — **dev only**, disables auth. Never set on a reachable server.

## Pair a device

```bash
PYTHONPATH=src .venv/bin/python -m indaga_gateway pair-code     # prints a 6-digit, 10-min code
# in the app: enter the code → POST /v1/pair → receive a device token (stored in the iOS Keychain)
```

Tokens are stored **hashed** in `~/.indaga/<subject>/gateway-devices.json` (0600). Revoke = delete the
entry. The pairing code is one-time.

## Networking (private phone ↔ personal server)

**Recommended: Tailscale.** Put the phone and this machine on your tailnet and bind the gateway to the
tailnet interface — zero open inbound ports, no public exposure of a health-data server, no cert
management, stable MagicDNS hostname for the app's base URL. Fallback: a reverse proxy + Let's Encrypt
TLS (larger attack surface; rate-limit it). Self-signed + pinning is not recommended.

## Endpoints

| Method | Path | Engine op(s) |
|---|---|---|
| GET | `/healthz` | — (liveness) |
| POST | `/v1/pair` | redeem pairing code → device token |
| GET | `/v1/today` | `decision.today` (+ deterministic phrasing) |
| GET | `/v1/today/strip` | `clock.state`, `cgm.glycemic_summary` |
| GET | `/v1/why/{action_id}` | the decision's legs' op results (provenance) |
| GET | `/v1/body` | `analyze.report` + `labs.panel_coverage` |
| GET | `/v1/sources` | `sources.list` |
| POST | `/v1/ingest/healthkit` | `ingest_hr_batch` → recompute `clock.state` |
| POST | `/v1/actions/done` | `journal.append` (Act→Learn loop) |
| POST | `/v1/ask` (SSE) | routes to one op; answers at the envelope's strength |
| GET | `/v1/visit-prep` | clinician handoff: abnormal labs + alert/watch findings + labs to order + **PharmCAT medication flags + PGx blind-spots** (the genome angle labs-only apps can't do) |
| GET | `/v1/explain/{analyte}` | explain one lab at the envelope's strength (never-measured → "unknown") |
| POST | `/v1/labs` | manually add a lab value (`{analyte, value, unit?, observed_at?, interpretation?}`); PDF OCR is a later path |

OpenAPI/Swagger at `/docs` (use it to generate or sanity-check the Swift client).

## Optional: Claude narration for Ask (egress — off by default)

`/v1/ask` answers from a **deterministic, envelope-honest floor** by default — fully local, nothing
leaves the machine. You can optionally have Claude *re-phrase* the grounded evidence:

```bash
export INDAGA_LLM_ENABLED=1
export ANTHROPIC_API_KEY=sk-ant-...        # or INDAGA_ANTHROPIC_API_KEY
export INDAGA_LLM_MODEL=claude-opus-4-8     # optional; default claude-opus-4-8
```

⚠️ **This is network egress.** When enabled, the question + grounded evidence (personal health facts)
are sent to Anthropic to phrase the answer. It is therefore **opt-in**, and every `/v1/ask` response
discloses it in the final SSE event via `narrated_by` (`"<model> (cloud)"` vs `"local (deterministic)"`).
The LLM only re-phrases **within the evidence envelope** — it never upgrades confidence, invents facts,
or states a clinical negative — and any failure falls back to the local summary, so Ask never breaks.
`ANTHROPIC_BASE_URL` is honoured for an Anthropic-compatible self-hosted endpoint. Requires the
optional `anthropic` package (`uv pip install anthropic`).

## The one rule

The gateway **never recomputes confidence**. Every response carries the engine's `evidence_envelope`
unchanged; the client maps it to a chip (`IndagaKit.chip(for:)`). Verified by diffing the gateway's
envelope against the direct op output — they are byte-identical.
