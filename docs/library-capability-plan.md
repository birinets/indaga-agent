# Indaga `library` capability — build plan

A local-first literature/knowledge base over the YouTube-transcript corpus
(`knowledge_base/`, 1,599 md docs) + the `Books/` PDFs, with **hybrid retrieval**
(FTS5 BM25 + local embeddings, rank-fused). Mirrors the `grounding` contract:
fully local, read-only, no third-party egress, degrades to `not_measured` +
`indaga …` hint when a piece is missing.

Status: PLAN (no code written yet).

---

## 1. Guiding principles (inherited from the existing agent)

- **Mirror `grounding`** (`skills/grounding/SKILL.md`): local files only, read-only,
  `externalIO=()` (localhost embedder is not third-party egress), per-section
  degradation, never convert context into a clinical claim.
- **Self-contained — NO HeathProject dependency** (same rule the imputation builder
  follows). The corpus is *ingested into* `~/.indaga/`, not read live from the
  HeathProject repo. A `--from <path>` flag points the one-time ingest at
  `HeathProject/knowledge_base/` + `HeathProject/Books/`.
- **One corpus, one schema.** PDFs become `source: book` alongside `source: youtube`,
  same frontmatter contract, same 14-bucket taxonomy.
- **Honesty / tiering.** Whole corpus is `tier: educational` (podcast/author opinion,
  not peer-reviewed). Kept **separate from the genomic evidence envelope** — the agent
  may *cite* ("per Masterjohn…"), never *assert*. Cites `skills/output-rules.md`.

---

## 2. Files (new)

```
src/indaga/corpus/                # heavy logic (mirrors how genome/ backs capabilities/genome.py)
  __init__.py
  schema.py        # SQLite DDL: documents, chunks, chunks_fts (FTS5), chunk_vec (sqlite-vec), corpus_meta
  pdf.py           # PDF/xlsx → markdown+frontmatter (pymupdf; docling/OCR fallback for slides); dedupe
  ingest.py        # md+frontmatter → documents/chunks rows; incremental via content_hash
  chunk.py         # heading-aware chunker (~800 tok, ~100 overlap), carries parent frontmatter
  embed.py         # local embedder client: Ollama (/api/embeddings) OR sentence-transformers; batched
  index.py         # build/refresh FTS5 + vector indexes
  retrieve.py      # hybrid search: BM25 + vector kNN → RRF fusion + metadata filters
  manifest.py      # corpus_meta read/write (embed model, dim, counts, built_at, freshness)
src/indaga/capabilities/library.py   # thin op layer: library.search/get/sources/stats (+ admin build)
src/indaga/eval/library_eval.py       # gold query→expected-doc recall guard (like other *_eval)
skills/library/SKILL.md               # skill doc; add line to skills/SKILL.md index
tests/test_library.py
```

Touched (small, read-only wiring):
- `reference/registry.py` — register the corpus + embedder as `LibrarySpec`s so
  `indaga.check_libraries` lists them / reports `not_installed`.
- `capabilities/analyze.py`, `capabilities/synthesis.py` — optional read-only
  "supporting literature" pull (never auto-elevates).
- `operations/bootstrap.py` — import the new capability module.

---

## 3. Storage layout (`~/.indaga/`)

```
~/.indaga/resources/knowledge/
  corpus/                 # normalized md (transcripts copied + PDFs converted)
    attia/ huberman/ masterjohn/ patrick/ lynch/ doac/ rogan/
    books/                # PDFs → md+frontmatter, source: book
  corpus.sqlite           # documents + chunks + chunks_fts + chunk_vec + corpus_meta
```

Subject-independent (a *resource*, like reference data) — not per-user, not in the
`facts` store.

---

## 4. Schema (stdlib `sqlite3` + sqlite-vec extension)

```sql
CREATE TABLE documents (
  doc_id TEXT PRIMARY KEY,        -- hash(url|path)
  source TEXT,                    -- youtube | book | xlsx
  author TEXT,                    -- attia | huberman | masterjohn | ...
  title TEXT, url TEXT, source_id TEXT, date TEXT, duration_min REAL,
  tier TEXT DEFAULT 'educational',
  tags_json TEXT,                 -- taxonomy buckets
  summary TEXT, path TEXT,
  content_hash TEXT,              -- incremental rebuild key
  ingested_at TEXT
);
CREATE TABLE chunks (
  chunk_id TEXT PRIMARY KEY, doc_id TEXT, ord INTEGER,
  heading TEXT, text TEXT, token_est INTEGER,
  char_start INTEGER, char_end INTEGER
);
-- BM25 keyword side (external-content FTS5 over chunks)
CREATE VIRTUAL TABLE chunks_fts USING fts5(
  text, heading, author UNINDEXED, tags,
  content='chunks', content_rowid='rowid'
);
-- vector side (dim from corpus_meta; fallback = numpy brute-force if ext unavailable)
CREATE VIRTUAL TABLE chunk_vec USING vec0(chunk_id TEXT PRIMARY KEY, embedding FLOAT[768]);
CREATE TABLE corpus_meta (key TEXT PRIMARY KEY, value TEXT);
  -- embed_model, embed_dim, embed_backend, schema_version, built_at, doc_count, chunk_count
```

---

## 5. Operations (reached via `indaga.invoke`)

| op | role | params | returns |
|---|---|---|---|
| `library.search` | entry_tool | `query`, `top_k?`, `author?`, `tags?`, `source?`, `min_score?` | ranked passages w/ provenance (title, author, url, heading, doc_id, ord, score) + `retrievers_fired` (fts/vector/hybrid) + `evidence_tier` |
| `library.get` | invoke | `doc_id` \| `chunk_id` (+`context?`) | full doc or chunk±neighbours with frontmatter |
| `library.sources` | invoke | — | authors/sources + counts + freshness |
| `library.stats` | invoke | — | doc/chunk counts, embed model/dim, last build, coverage by taxonomy bucket |
| `library.build` | admin / CLI | `from?`, `reindex?` | ingest + index summary |

`mutating: false` for search/get/sources/stats; `externalIO=()` (note: localhost
embedder only). `library.build` is the only mutating op. CLI: `indaga library build --from <path>`.

---

## 6. Hybrid retrieval (`retrieve.py`)

1. FTS5 BM25 → ranked chunk_ids + scores.
2. Embed query (`embed.py`) → sqlite-vec kNN (cosine) → ranked chunk_ids + distances.
3. **Reciprocal Rank Fusion** (RRF, k=60) merges the two lists → `top_k`.
4. Apply metadata filters (author / tags / source / tier).
5. Return passages with provenance.

Degradation (grounding-style, per-piece):
- embedder/vec unavailable → FTS5-only, flag `vector: not_measured`.
- `corpus.sqlite` missing → `not_measured` + `indaga library build` hint.

---

## 7. Ingest pipeline (`library.build`)

1. Discover: walk corpus md + `Books/*.pdf|*.xlsx`.
2. **PDF→md** (`pdf.py`): pymupdf text extract; low text-density / slide decks →
   docling/marker or `ocrmypdf`+tesseract fallback. Emit md + frontmatter
   (author from a filename→author map; tags via reused `knowledge_base/_scripts/tag.py`
   keyword logic; `source: book`). **Dedupe** by `content_hash` + normalized title
   (removes the `(1)` copies and the two Dirty Genes duplicates).
3. **xlsx→md** tables (openpyxl/pandas).
4. Parse frontmatter + body for every md.
5. **Chunk** (`chunk.py`): split on `##`/`###`, pack to ~800 tokens, ~100 overlap;
   carry heading + parent frontmatter.
6. Upsert documents + chunks; skip unchanged via `content_hash` (incremental).
7. Embed new/changed chunks (batched) → `chunk_vec`.
8. Refresh FTS5.
9. Write `corpus_meta`.

---

## 8. Integration (read-only, non-elevating)

- **analyze.report / synthesis** — for a headline finding (gene / taxonomy bucket),
  optional `library.search` pull attaches top citations as *context*; tier-gated,
  never written to the evidence envelope. Mirrors how grounding was wired in read-only.
- **journal** — `related_findings` frontmatter ↔ journal entries; search hits can be
  journaled; journal can cite `chunk_id`s.
- **reference registry** — corpus + embedder appear in `indaga.check_libraries`.

---

## 9. Dependencies (optional `corpus` extra; core stays lean)

- `pymupdf` (PDF text) — required for PDF ingest.
- `docling` *or* `ocrmypdf`+tesseract — slide/scan fallback (optional).
- `openpyxl`/`pandas` — xlsx.
- `sqlite-vec` loadable extension — vector in-SQLite; **fallback** = numpy brute-force
  kNN if the extension can't load (keeps it dependency-light, still local).
- Embedder: **Ollama** (HTTP, no python dep — fits self-hosting) *or*
  `sentence-transformers`.

---

## 10. Phasing

- **P0** — corpus dir + schema + ingest the 1,599 existing transcripts (no PDFs),
  FTS5 only. Proves retrieval end-to-end fast.
- **P1** — embeddings + sqlite-vec + RRF hybrid.
- **P2** — PDF/xlsx conversion + dedupe + tagging into the corpus.
- **P3** — wire into analyze/synthesis + journal; register in reference registry;
  SKILL.md + skills index.
- **P4** — `library_eval` (gold query→expected-doc) to guard recall.

---

## 11. Open decisions (resolved 2026-06-17 after reviewing vitelogy)

1. **Embedder model** — RESOLVED: `nomic-embed-text` (English-only, 768d, native
   Ollama + sqlite-vec, 8192-tok context, Matryoshka-truncatable). Dropped `bge-m3`
   (multilingual/multi-vector strengths are unused at EN-only + add integration
   friction). For the Tier-2 *claim* layer (short one-sentence text), prefer
   `bge-small-en-v1.5` (384d). NOTE: nomic requires `search_document:` /
   `search_query:` prefixes — wrong prefixes tank recall.
2. **Location / packaging** — RESOLVED: the KB is its **own standalone project,
   `IndagaKB`**, not an Indaga folder. It is a *producer* that emits (A) a versioned
   local SQLite **snapshot** Indaga downloads (default — zero egress, mirrors the
   `LibrarySpec` model) and (B) an optional live query **API/MCP** for freshness.
   Indaga is one *consumer* (its `library` capability wraps the snapshot/API).
3. **Chunk size / overlap** — 800/100 default; tune after P0.
4. **Slide-deck handling** — *Nutrition & Immunity Slides* is visual; OCR vs
   docling layout extract vs skip-slides-keep-transcript.

---

## 12. Revision after reviewing vitelogy (friend's claim-graph platform)

Reviewed a screenshot of vitelogy's 101-table data model. It is a **claim-graph
knowledge engine with an AI publishing layer**, not a RAG app. Key takeaways:

**Architecture observed (layers):**
- Ingest: `sources`, `youtube_channels`, `rss_feeds/items`, `videos`, `transcripts`,
  `papers`, `source_authors` — many feeds → one `sources` table.
- Decompose: `source_blobs` → `source_fragments` → `source_observations`
  (+ `source_merge_events` for dedup). Raw → chunk → atomic observation.
- **Claims (core):** `claim_candidates` → `claims`, `claim_frames`,
  `claim_candidate_evidence`, `claim_frame_evidence`, `*_signals`. The atomic unit
  is a **claim with evidence + provenance**; LLM proposes candidates → validation
  promotes to claims.
- Topics/publishing: `topics`, `topic_sections`, `topic_claims`,
  `publication_revisions`, `topic_render_cache` — generated topic pages w/ history.
- Serving: `search_packets(_fts)`, `*_relevance_cache`, `kb_graph_cache`.
- AI ops: `llm_call_log`, `llm_model_decisions`, `ai_model_validations`.
- SaaS/governance: `accounts`, `subscription_plans`, `entitlements`, `policies`,
  `rate_limits` — ~40 tables of multi-tenant plumbing.

**Decisions this drives:**
- **Steal the knowledge model, drop the SaaS plumbing.** No billing / entitlements /
  policy-audit / six cache tables at personal scale.
- **No vitelogy dependency at all.** Friend declined to share an export/API (he's
  leveraging his own project), so IndagaKB is a fully independent build. We learned
  from his claim-graph schema; we import nothing from it.
- **Two tiers:**
  - **Tier 1 — chunk + hybrid retrieval** (§1–10 above). Ship first.
  - **Tier 2 — claim layer**: reserve `claims`, `claim_evidence`, `topics`,
    `topic_claims` tables now; an LLM extraction pass turns chunks → cited claims;
    retrieval returns assertions + evidence; `synthesis` can render topic pages.
    Maps onto Indaga's cite-don't-assert / tier-the-evidence ethos. Add after Tier 1.
- **Standalone packaging** (see §11.2): `knowledge-core` producer + snapshot/API;
  Indaga = consumer.

**Tier-2 schema reservation (additive, no Tier-1 migration):**
```sql
CREATE TABLE claims (
  claim_id TEXT PRIMARY KEY, text TEXT, topic TEXT, tags_json TEXT,
  tier TEXT DEFAULT 'educational', polarity TEXT,        -- assert/refute/uncertain
  status TEXT DEFAULT 'candidate',                        -- candidate|validated
  created_at TEXT
);
CREATE TABLE claim_evidence (                              -- claim ↔ supporting chunk
  claim_id TEXT, chunk_id TEXT, doc_id TEXT,
  stance TEXT, strength REAL,                              -- supports|contradicts
  PRIMARY KEY (claim_id, chunk_id)
);
CREATE TABLE topic_claims (topic TEXT, claim_id TEXT, rank REAL,
  PRIMARY KEY (topic, claim_id));
```
`library.search` gains `mode: chunk|claim`; claim mode returns assertions with
their evidence chunks + stance, enabling contradiction surfacing.

**Live page check:** `vitelogy.com/topics/vo2-max` is login-gated (fetch saw only the
"Vitelogy" title); not publicly indexed. Analysis is from the schema screenshot only.

---

## 13. P0 build steps — IndagaKB, Tier 1 start (FTS5 over existing transcripts)

> **STATUS: SHIPPED 2026-06-17.** Project at `~/Documents/Claude/Projects/IndagaKB/`,
> store at `~/.indagakb/indagakb.sqlite`. Zero dependencies (stdlib only — wrote a
> minimal frontmatter parser instead of PyYAML). Build: **1,590 docs → 29,616 chunks
> in ~7.6s**; incremental rebuild skips all unchanged; smoke tests green; sample
> searches return relevant, fully-cited passages with `«»` snippet highlighting.
> Authors: masterjohn 578 · huberman 410 · attia 287 · patrick 142 · lynch 95 ·
> doac 55 · rogan 23. Next: **P1** (see §13.7).

**Goal of P0:** stand up the standalone `IndagaKB` project; ingest the 1,599 existing
transcript `.md` files; build an FTS5 BM25 index; expose `kb search` that returns
ranked passages with provenance. **No embeddings, no PDFs, no claims** — prove
retrieval end-to-end first.

**Proposed location:** `~/Documents/Claude/Projects/IndagaKB/` (sibling to
HeathProject; easy to change). Store: `~/.indagakb/indagakb.sqlite` (its own home).

### 13.1 Project skeleton
```
IndagaKB/
  pyproject.toml          # name=indagakb; deps: pyyaml (frontmatter). stdlib otherwise.
  README.md
  .gitignore              # data/, *.sqlite, __pycache__
  indagakb/
    __init__.py
    __main__.py           # CLI: build | search | stats | sources
    config.py             # home dir (~/.indagakb), db path, defaults (k=8, chunk=800/100)
    frontmatter.py        # split '---\nYAML\n---\nbody' → (meta dict, body str)
    schema.py             # DDL: documents, chunks, chunks_fts, kb_meta (claim tables NOT yet)
    chunk.py              # heading-aware split, then window-pack long sections
    ingest.py             # walk md → upsert documents+chunks; incremental via content_hash
    index.py              # (re)build FTS5 from chunks; bm25 config
    retrieve.py           # BM25 query + author/tags/source filters → ranked passages
    snapshot.py           # STUB (P1+): emit versioned signed SQLite bundle
  tests/
    test_ingest.py        # frontmatter parse + chunk counts on a fixture
    test_retrieve.py      # known query → expected doc in top-k
```

### 13.2 Schema (P0 subset of §4 — claim tables deferred to Tier 2)
`documents`, `chunks`, `chunks_fts` (FTS5 external-content over `chunks`,
`bm25`-ranked), `kb_meta`. No `chunk_vec` yet (that's P1).

### 13.3 Chunking note (transcripts are a wall of text)
The transcript bodies are basically one long `## Transcript` blob, so heading-split
alone won't help. `chunk.py`: split on `##`/`###` headings **first**, then for any
section over the limit, **window-pack** (~800 tokens, ~100 overlap) on
sentence/whitespace boundaries. Each chunk carries parent frontmatter
(author/title/url/tags) so a hit can cite itself.

### 13.4 CLI surface
- `kb build [--from PATH] [--reindex]` — default `--from` = HeathProject/knowledge_base;
  ingest + FTS index; incremental (skip unchanged via content_hash).
- `kb search "<query>" [--author X] [--tags a,b] [--source youtube] [-k 8]` — ranked
  passages with title · author · url · heading · BM25 score.
- `kb stats` — doc/chunk counts + coverage by author and taxonomy bucket.
- `kb sources` — authors + counts.

### 13.5 Definition of Done (P0)
1. `kb build --from .../knowledge_base` ingests ~1,599 docs → N chunks, prints summary.
2. `kb search "zone 2 training for vo2 max" --author attia -k 5` returns 5 visibly
   relevant passages with full provenance + score.
3. Re-running `kb build` is incremental (unchanged docs skipped).
4. `pytest` green: `test_ingest` (frontmatter + chunk counts), `test_retrieve`
   (gold query → expected doc in top-k).

### 13.6 Explicitly OUT of scope for P0
Embeddings / sqlite-vec / RRF hybrid (P1) · PDFs + xlsx + dedupe (P2) ·
claims / topics (Tier 2) · live API · snapshot signing · Indaga `library` wiring (P1).

### 13.7 Then P1 (next slice)
Add `nomic-embed-text` (Ollama) embeddings → `chunk_vec` (sqlite-vec; numpy
brute-force fallback) → RRF hybrid in `retrieve.py`; `snapshot.py` emits a versioned
bundle; build the Indaga consumer (`LibrarySpec` download + `library.search` op).
