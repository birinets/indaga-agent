# Deploying & sharing Indaga-agent

Two targets, one clean repo: **(A)** share with friends for testing, **(B)** deploy + test on your own
server (`<your-server>`, Claude installed). The repo ships **zero personal data** (see the `.gitignore`); each
person brings their own genome into their own `~/.indaga`.

Pre-flight (local, already done): repo is PII-swept (`STATUS.md` gitignored; examples genericised to `demo`),
`git init` + initial commit made. Verify before any push:

```bash
git -C Indaga-agent ls-files | grep -iE 'your-name|your-subjects|secret|token' && echo "STOP: PII tracked" || echo "clean"
git -C Indaga-agent ls-files | grep -E '\.(sqlite|vcf|bam|fastq)$' && echo "STOP: data tracked" || echo "no data files"
```

---

## A · Share with friends (private GitHub repo)

```bash
cd Indaga-agent
# create a PRIVATE repo (keep it private — it's pre-release) and push
gh repo create indaga-agent --private --source=. --remote=origin --push
# invite testers as collaborators:
gh repo edit --add-collaborator <github-username>
```

A friend then follows the **Quickstart in `README.md`**: clone → `pip install -e .` → `pytest` →
`indaga install …` → `indaga install-host claude` → bring their own chip (`indaga impute` / `annotate`).
Nothing of yours travels with the repo; their data stays in their own `~/.indaga`.

**License note:** no OSS licence is attached (it's *proprietary, for testing only*). Decide the licence before
any public release — given the open-core strategy, that's a deliberate business choice, not a default.

---

## B · Deploy + test on the server (`<your-server>`)

Assumes SSH access and that Claude (Claude Code CLI) is installed on the box.

### B0 · Check / update Claude on the server first
Indaga's MCP server speaks **MCP 2025-11-25** but **negotiates down**, so most recent Claude Code versions
connect; update to latest to get `outputSchema` / `structuredContent` cleanly.

```bash
ssh root@<your-server>
claude --version                 # note the version
claude update                    # self-update; or reinstall: curl -fsSL https://claude.ai/install.sh | bash
claude mcp --help                # confirm the `mcp` subcommand exists (MCP support present)
```

### B1 · Get the code + install
```bash
# on the server. uv is the path of least resistance — stock Ubuntu's python3 has NO ensurepip,
# so `python3 -m venv` fails; uv needs no system packages and no sudo.
git clone https://github.com/birinets/indaga-agent.git ~/indaga-agent && cd ~/indaga-agent
command -v uv || curl -LsSf https://astral.sh/uv/install.sh | sh   # → ~/.local/bin/uv
uv venv .venv && uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m pytest -q    # gate: ~146 tests must pass
# imputation also needs:  uv pip install --python .venv/bin/python -e ".[impute]"
#   + java17 + bcftools/htslib  (micromamba install -c conda-forge -c bioconda bcftools htslib openjdk=17)
```

### B2 · Reference libraries + a test subject
```bash
indaga install --check
indaga install clinvar-grch38 pgs-catalog-metadata gene-disease-validity \
               reactome-pathways hpa-tissue-rna gene-ontology   # add more as needed (big downloads)
# bring a chip to exercise the genome path (optional for a connection test):
indaga impute   --subject me --chip /path/to/raw_dna.txt
indaga annotate --subject me
```

### B3 · Register the MCP server with Claude Code
```bash
# easiest — Indaga writes ~/.claude.json (mcpServers.indaga) + symlinks the skills:
indaga install-host claude --subject me --user-dir ~/.indaga/me --write
# or register it manually:
claude mcp add indaga -- "$(which python3)" -m indaga.interfaces.cli serve \
   --subject me --user-dir ~/.indaga/me
claude mcp list                  # indaga should appear
```

### B4 · Smoke test (no MCP client needed)
```bash
indaga selftest --subject me --user-dir ~/.indaga/me     # drives the full surface
indaga tools | python3 -m json.tool | head               # base tool list
indaga call indaga.list_capabilities                     # one operation directly
```

### B5 · End-to-end through Claude
In a Claude Code session on the server: *"list indaga capabilities"*, then *"any ACMG-actionable secondary
findings for me?"* / *"what's my glucose summary?"*. Confirm tools resolve and the **honesty envelope** shows
(e.g. a never-measured lab returns `not_measured`, not a guess).

---

## Test checklist (both targets)
- [ ] `pytest -q` green + `ruff check` clean
- [ ] `indaga install --check` shows the intended libraries installed
- [ ] `indaga selftest` passes for the subject
- [ ] host shows `indaga` in its MCP list; `indaga.list_capabilities` returns from inside the host
- [ ] a never-measured query returns `not_measured` (the honesty contract is live)
- [ ] `~/.indaga` is `0700`, the per-subject stores `0600` (least-privilege, auto-set on build)

## Rollback / hygiene
- Nothing writes outside `~/.indaga` and the host config. To remove: `claude mcp remove indaga`, delete
  `~/.indaga/<subject>`, and (host) the `mcpServers.indaga` block.
