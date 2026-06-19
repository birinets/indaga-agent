# Indaga-agent

**A local-first, multi-omic personal-health agent runtime.** The agent backend for the
Indaga product (the consumer app + website are a separate codebase). Where a genome agent
turns your DNA into a queryable, honest expert, Indaga-agent does the same across **every
modality** — genome, labs, wearables, CGM, and the derived metrics built from them — in one
coherent system, queryable by any MCP-compatible host (Claude Desktop, Claude Code, …).

It is built on three spines, applied to all of your health data:

1. **A persistent per-subject Active Health Index** (`~/.indaga/<subject>/active-health-index.sqlite`)
   behind a storage-agnostic port — local SQLite now; a hosted / zero-knowledge adapter later,
   with no upstream change.
2. **One evidence-envelope honesty contract.** Every answer is typed: `finding_state`,
   `answer_readiness`, and `negative_inference`. *Absence is never "normal".* A lab that was
   never measured returns `not_measured`; a Biological Midnight before 14 nights is
   `index_incomplete`; a stale CGM read refuses to claim your current glucose. This is the
   multi-omic generalization of genomic callability, and it is the point of the product.
3. **A dispatcher + per-capability skills.** `tools/list` shows a small base set; everything else
   is reached via `indaga.invoke` after the agent reads that capability's `SKILL.md`
   (progressive disclosure).

## Quickstart

```bash
# 1 — clone (Python ≥3.10; 3.11/3.12 recommended for the predictor venvs)
git clone https://github.com/birinets/indaga-agent.git && cd indaga-agent

# 2 — install. RECOMMENDED: uv — sudo-free, no system packages, makes its own venv.
#     (curl the installer if you don't have it: curl -LsSf https://astral.sh/uv/install.sh | sh)
uv venv .venv && uv pip install --python .venv/bin/python -e ".[dev]"
#  …or with stock pip (needs the python3-venv package — e.g. `sudo apt install python3.12-venv`
#    on Debian/Ubuntu, which ship python3 without ensurepip):
#     python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"

# 3 — verify the engine on synthetic fixtures (no personal data needed)
.venv/bin/python -m pytest -q          # ~146 tests
.venv/bin/python -m ruff check src tests

# 4 — download the reference libraries you want (cached in ~/.indaga, queried OFFLINE).
#     `indaga` lives in the venv; activate it (`. .venv/bin/activate`) or call `.venv/bin/indaga`.
.venv/bin/indaga install --check       # see the catalog + what's installed
.venv/bin/indaga install clinvar-grch38 pgs-catalog-metadata gene-disease-validity \
               reactome-pathways hpa-tissue-rna gene-ontology

# 5 — wire it into your MCP host (writes the config + symlinks the skills)
.venv/bin/indaga install-host claude   # also: openclaw | hermes   (preview without --write)
```

**Bring your own genome** — a consumer chip export (23andMe / MyHeritage / AncestryDNA):

```bash
# imputation needs the pyliftover extra + a Java 17 runtime + bcftools/bgzip/tabix on PATH.
# sudo-free way to get the system tools:  micromamba install -c conda-forge -c bioconda bcftools htslib openjdk=17
uv pip install --python .venv/bin/python -e ".[impute]"

.venv/bin/indaga impute   --subject me --chip /path/to/your_raw_dna.txt  # liftover + Beagle/1000G → GRCh38 (pulls the panel)
.venv/bin/indaga annotate --subject me                                   # ClinVar P/LP · PGS · GWAS · ACMG · PGx · panels
```

> Chip-tier works with **no toolchain at all**: skip `impute` and run `annotate` directly on the raw
> chip (`dna/raw/`) — the Active Genome Index is built in pure Python (ClinVar P/LP screen + PGS), and
> imputation only adds the deeper imputed-variant tier.

…then ask your host: *"any ACMG-actionable secondary findings?"*, *"what diagnostic panels is my LDLR in?"*,
*"what's my biological midnight?"*, *"how's my glucose?"* — and watch the **honesty** surface (it refuses to
guess what wasn't measured).

> **Privacy:** this repo ships **zero personal data**. Reference libraries and your per-subject genome/health
> data live only in `~/.indaga/<subject>/` on your own machine; nothing is uploaded, and grounding/panels run
> from downloaded files (no per-variant egress). The only optional network call at query time is a single
> gnomAD lookup during variant resolution, which is disclosed.

## Layout

```
Indaga-agent/
├── README.md  AGENTS.md  CLAUDE.md  INSTALL_FOR_AGENTS.md  llms.txt  llms-full.txt
├── pyproject.toml
├── skills/                         # agent-facing capability skills (progressive disclosure)
│   ├── SKILL.md                    # root skill: routing + the honesty contract
│   ├── genome/ grounding/ journal/ synthesis/ analyze/      (SKILL.md each)
│   ├── circadian/ labs/ metabolic/ health-index/ domains/   (SKILL.md each)
│   └── conventions/evidence-envelope.md  ·  output-rules.md
└── src/indaga/
    ├── runtime/        # ~/.indaga home, per-subject paths, secured 0600, audit, jobs, observability
    ├── store/          # the port (Reader/Writer/Store) + typed model + LocalSQLiteStore + conformance
    ├── evidence/       # the multi-omic EvidenceEnvelope + confidence calculus + allele-safe store reader
    ├── reference/      # the reference-library registry + downloader (ClinVar, PGS, Reactome, GenCC, …)
    ├── genome/         # AGI, VRS allele identity, predictors/ACMG, panels (ACMG SF/carrier), gene_disease …
    ├── operations/     # Operation model + registry + JSON-schema validation + indaga.invoke dispatcher
    ├── capabilities/   # genome · grounding (7 tools) · journal · synthesis · analyze · circadian · labs · …
    ├── spine/          # deterministic science (24h cosinor Biological Clock, CGM, PGS)
    ├── interfaces/     # MCP server (2025-11-25, stdio) + CLI + host_install
    └── eval/           # envelope / allele-safety / genome-parity / analyze honesty gates
```

## Status

A working multi-omic engine: own genome pipeline (chip → **imputation** → Active Genome Index →
annotation), **9 analytical-grounding tools** (region/regulatory/pathways/GO/expression/celltype/gene/
gene-disease/diagnostic-panels — all local, zero-egress), the full **industry-standard panel stack**
(ACMG SF v3.3 · GenCC/ClinGen validity · PanelApp · ACMG carrier-113 · CPIC · PGS), a **VRS-style durable
allele identity**, an investigation **journal**, **multi-omic synthesis**, and a self-contained `analyze`
report — all behind one evidence-envelope honesty contract and a progressive-disclosure skills layer
(**~49 tools**). Gates: `pytest` + conformance / envelope / allele-safety / genome-parity / analyze.

Indaga-agent is wellness **decision-support, not medical diagnosis**.

**License:** [AGPL-3.0-or-later](LICENSE) — free to use, study, and modify; if you run a modified version
as a network service, you must offer your source changes to its users (the AGPL network clause). For a
commercial license without the copyleft obligations, get in touch.
