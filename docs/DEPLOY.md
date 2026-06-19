# Deploying Indaga on your own server

How to run Indaga-agent on a remote box and reach it from Claude Code over MCP. The repo ships **zero
personal data** (see `.gitignore`) — you bring your own genome and health data into your own `~/.indaga`,
and nothing leaves the machine. For a local install, the **Quickstart in [`../README.md`](../README.md)**
is all you need; this guide covers the server case.

Assumes SSH access to the box and that Claude Code is installed on it.

---

## 0 · Check / update Claude on the server first
Indaga's MCP server speaks **MCP 2025-11-25** but **negotiates down**, so most recent Claude Code versions
connect; update to the latest to get `outputSchema` / `structuredContent` cleanly.

```bash
ssh you@your.server.example
claude --version                 # note the version
claude update                    # self-update; or reinstall: curl -fsSL https://claude.ai/install.sh | bash
claude mcp --help                # confirm the `mcp` subcommand exists (MCP support present)
```

## 1 · Get the code + install
```bash
# uv is the path of least resistance — some distros' python3 has NO ensurepip, so `python3 -m venv`
# fails; uv needs no system packages and no sudo.
git clone https://github.com/birinets/indaga-agent.git ~/indaga-agent && cd ~/indaga-agent
command -v uv || curl -LsSf https://astral.sh/uv/install.sh | sh   # → ~/.local/bin/uv
uv venv .venv && uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m pytest -q    # gate: ~146 tests must pass
# imputation also needs:  uv pip install --python .venv/bin/python -e ".[impute]"
#   + java17 + bcftools/htslib  (micromamba install -c conda-forge -c bioconda bcftools htslib openjdk=17)
```

## 2 · Reference libraries + a test subject
```bash
.venv/bin/indaga install --check
.venv/bin/indaga install clinvar-grch38 pgs-catalog-metadata gene-disease-validity \
               reactome-pathways hpa-tissue-rna gene-ontology   # add more as needed (big downloads)
# bring a chip to exercise the genome path (optional for a connection test):
.venv/bin/indaga impute   --subject me --chip /path/to/raw_dna.txt
.venv/bin/indaga annotate --subject me
```

## 3 · Register the MCP server with Claude Code
```bash
# easiest — Indaga writes ~/.claude.json (mcpServers.indaga) + symlinks the skills:
.venv/bin/indaga install-host claude --subject me --user-dir ~/.indaga/me --write
# or register it manually (note: the venv interpreter, NOT system python3):
claude mcp add indaga -- "$(pwd)/.venv/bin/python" -m indaga.interfaces.cli serve \
   --subject me --user-dir ~/.indaga/me
claude mcp list                  # indaga should appear
```

## 4 · Smoke test (no MCP client needed)
```bash
.venv/bin/indaga selftest --subject me --user-dir ~/.indaga/me   # drives the full surface
.venv/bin/indaga tools | python3 -m json.tool | head            # base tool list
.venv/bin/indaga call indaga.list_capabilities                  # one operation directly
```

## 5 · End-to-end through Claude
In a Claude Code session on the server: *"list indaga capabilities"*, then *"any ACMG-actionable secondary
findings for me?"* / *"what's my glucose summary?"*. Confirm tools resolve and the **honesty envelope** shows
(e.g. a never-measured lab returns `not_measured`, not a guess).

---

## Test checklist
- [ ] `.venv/bin/python -m pytest -q` green + `.venv/bin/python -m ruff check src` clean
- [ ] `indaga install --check` shows the intended libraries installed
- [ ] `indaga selftest` passes for the subject
- [ ] host shows `indaga` in its MCP list; `indaga.list_capabilities` returns from inside the host
- [ ] a never-measured query returns `not_measured` (the honesty contract is live)
- [ ] `~/.indaga` is `0700`, the per-subject stores `0600` (least-privilege, auto-set on build)

## Rollback / hygiene
- Nothing writes outside `~/.indaga` and the host config. To remove: `claude mcp remove indaga`, delete
  `~/.indaga/<subject>`, and (host) the `mcpServers.indaga` block.
