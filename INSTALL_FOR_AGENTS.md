# INSTALL_FOR_AGENTS.md

How an agent (Claude Code / Claude Desktop / any MCP host) installs and wires up Indaga-agent.

## What it is

A local MCP server over the user's own health data. It runs as a subprocess on the user's
machine; raw data never leaves it. The server exposes a small **base tool set** plus an
`indaga.invoke` dispatcher; deeper tools are reached after reading a capability's `SKILL.md`.

## 0. Prerequisites

- Python ≥ 3.10 with `numpy` and `scipy` available (the only third-party deps; `sqlite3` is stdlib).
  Verify: `python3 -c "import numpy, scipy, sqlite3"`.
- The user's data directory (`--user-dir`) containing what they have, e.g.
  `healthlake/silver/tables/observations.csv` (labs), `wearables/parsed/hr_series.json`,
  `wearables/parsed/glucose.json`. Missing inputs are simply absent capabilities — never faked.

## 1. Get the code

```bash
git clone <indaga-agent repo> Indaga-agent     # or copy the folder
# optional editable install (adds the `indaga` command):
pip install -e Indaga-agent
```

Running from source (no install) is fully supported — set `PYTHONPATH` to `Indaga-agent/src`.

## 2. Smoke-test before wiring a host

```bash
PYTHONPATH=Indaga-agent/src python3 -m indaga.interfaces.cli selftest \
  --subject <subject> --user-dir <abs path to the user's data dir>
```

You should see `initialize`, the base `tools/list`, and a `clock.state` answer that is either a
real Biological Midnight or an honest `calibrating` state.

## 3. Register the MCP server with the host

The server speaks MCP over **stdio**. First build is a one-time ingest into
`~/.indaga/<subject>/active-health-index.sqlite` (~seconds); subsequent starts reuse it.

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`, macOS) —
merge into `mcpServers`, do not overwrite the file:

```json
{
  "mcpServers": {
    "indaga": {
      "command": "/ABSOLUTE/path/to/python3",
      "args": ["-m", "indaga.interfaces.cli", "serve",
               "--subject", "<subject>",
               "--user-dir", "/ABSOLUTE/path/to/user/data",
               "--hr-limit", "20000"],
      "env": { "PYTHONPATH": "/ABSOLUTE/path/to/Indaga-agent/src" }
    }
  }
}
```

Use the **absolute** path to a Python that has `numpy`/`scipy`. `INDAGA_HOME` (default `~/.indaga`)
and `INDAGA_SKILLS` (default `<repo>/skills`) can be set in `env` if you relocate them. Restart the
host fully after editing the config.

**Claude Code / other hosts:** point their MCP config at the same command; the protocol is identical.

## 3b. One command for OpenClaw / Hermes / Claude Code — `install-host`

Indaga ships **no host-specific plugin code**: it is a generic MCP server, so OpenClaw, Hermes, and
Claude Code all consume it the same way (an MCP-server config entry + skill symlinks — the Genomi
pattern). OpenClaw's MCP client (SDK 1.29.0) already reads the `outputSchema`/`structuredContent` Indaga
emits, so there is nothing to build in TypeScript.

**One-shot (the Genomi-style orchestrator)** — download references → wire hosts → verify, in one command
(the in-package flow `indaga install-for-agents`, or the source-checkout script `scripts/install_for_agents.py`):

```bash
# dry-run: show missing reference libs + the per-host config snippets it would write
python3 scripts/install_for_agents.py --subject <subject> --user-dir /ABS/path/to/user/data
indaga install-for-agents --subject <subject> --user-dir /ABS/path/to/user/data           # same, in-package

# perform it: download references + merge host configs + symlink skills + verify
python3 scripts/install_for_agents.py --subject <subject> --user-dir /ABS/path/to/user/data --write --editable
```

**Host wiring only** (references already installed) — `install-host` does just step (2):

```bash
# dry-run: print the exact per-host config snippets + the skill links it would create
indaga install-host --subject <subject> --user-dir /ABS/path/to/user/data --host all

# apply: merge each host config (existing entries preserved) + create the skill symlinks
indaga install-host --subject <subject> --user-dir /ABS/path/to/user/data --host all --write
```

It writes an MCP-server entry to **OpenClaw** `~/.openclaw/openclaw.json` (`mcp.servers.indaga`),
**Hermes** `~/.hermes/config.yaml` (`mcp_servers.indaga`; or use `hermes mcp add`), and **Claude Code**
`~/.claude.json` (`mcpServers.indaga`) — each `{command, args:[serve, --subject, …, --user-dir, …]}`
(falling back to `python -m … + PYTHONPATH` when the `indaga` console script isn't on `PATH`). It then
symlinks `~/.<host>/skills/indaga` → `<repo>/skills` and `indaga-<capability>` → `skills/<capability>`
for each capability. Dry-run is the default; `--write` is the explicit opt-in (JSON merges preserve
existing entries; an existing Hermes `config.yaml` is left untouched with the snippet printed to add).

## 4. How an agent uses it (the loop)

1. `indaga.list_capabilities` → see the capabilities + their skill paths.
2. `indaga.read_skill({"capability": "<cap>"})` → load that capability's `SKILL.md`.
3. Call the smallest useful tool — base/entry tools directly, focused tools via
   `indaga.invoke({"tool": "<name>", "params": {...}})`.
4. **Read the `evidence_envelope` on every result** and answer at exactly its strength
   (see `skills/SKILL.md`). Never report `not_measured` / `not_observed` as "normal".

## 5. Updating

Pull the repo (`git -C Indaga-agent pull --ff-only`) and restart the host. The persistent index is
rebuilt automatically when its source data changes (or pass `--rebuild`).
