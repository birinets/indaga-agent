"""The consent & egress matrix — per-operation privacy / data-access / network annotations.

`Operation` declares `privacy_scope` / `data_access` / `external_io` / `operation_scope` / `mutating`,
but capabilities register without them. Rather than scatter those across 36 register sites, this is the
ONE auditable table: a reviewer (or a future capability-based consent layer) can see the whole
egress surface — which tools touch the network, which touch raw DNA — at a glance. `bootstrap.load_all`
calls `apply()` after every capability registers.

Vocabulary:
  privacy_scope : none | personal | genomic   (genomic = touches raw DNA / the AGI — most sensitive)
  data_access   : the personal-data domains a tool actually reads
                  (genome/labs/cgm/wearable/derived/facts/timeseries/jobs)
  external_io   : network egress — ``gnomad`` (a live gnomAD variant query, which reveals a locus of
                  interest to a third party) and ``reference_download`` (fetches a reference library)
  mutating      : performs a non-trivial intentional state change (builds an index, downloads, spawns
                  a job, writes a report file). Idempotent derived-fact CACHING (variant.resolve writing
                  the resolved fact back into the index) is read-purpose and is NOT counted as mutating.
"""

from __future__ import annotations

from dataclasses import replace

from . import registry

# op_name -> (privacy_scope, data_access, external_io, mutating)
_ANN: dict[str, tuple[str, tuple[str, ...], tuple[str, ...], bool]] = {
    # --- admin (indaga.*) -------------------------------------------------- #
    "indaga.list_capabilities":    ("none", (), (), False),
    "indaga.read_skill":           ("none", (), (), False),
    "indaga.invoke":               ("none", (), (), False),  # egress depends on the dispatched tool
    "indaga.describe_context":     ("personal", ("facts",), (), False),
    "indaga.check_libraries":      ("none", (), (), False),
    "indaga.install":              ("none", (), ("reference_download",), True),
    "indaga.check_background_job": ("none", ("jobs",), (), False),
    "indaga.access_log":           ("personal", ("audit",), (), False),
    # --- health-index ------------------------------------------------------ #
    "facts.query":        ("personal", ("facts",), (), False),
    "sources.list":       ("personal", ("facts",), (), False),
    "context_pack.get":   ("personal", ("facts", "timeseries"), (), False),
    "timeseries.get":     ("personal", ("timeseries",), (), False),
    "provenance.resolve": ("personal", ("facts",), (), False),
    "corrections.list":   ("personal", ("facts",), (), False),
    # --- circadian / metabolic --------------------------------------------- #
    "clock.state":               ("personal", ("timeseries", "derived"), (), False),
    "clock.biological_midnight": ("personal", ("timeseries", "derived"), (), False),
    "cgm.glycemic_summary":      ("personal", ("cgm", "timeseries"), (), False),
    # --- labs -------------------------------------------------------------- #
    "labs.query":          ("personal", ("labs",), (), False),
    "labs.panel_coverage": ("personal", ("labs",), (), False),
    # --- domains ----------------------------------------------------------- #
    "domains.list": ("none", (), (), False),                 # lists domain names; no personal data
    "domains.get":  ("genomic", ("genome",), (), False),     # resolves per-domain DNA variants
    # --- nutrigenomics ----------------------------------------------------- #
    "nutrigenomics.markers": ("genomic", ("genome",), (), False),
    # --- investigation journal (operational memory; local, per-subject) ---- #
    "journal.append":  ("personal", ("journal",), (), True),   # append-only write
    "journal.read":    ("personal", ("journal",), (), False),
    "journal.summary": ("personal", ("journal",), (), False),
    # --- analytical grounding (local-first; no egress) --------------------- #
    "grounding.region":     ("genomic", ("genome",), (), False),
    "grounding.regulatory": ("genomic", ("genome",), (), False),  # genome only on the rsid/locus path
    "grounding.pathways":   ("genomic", ("genome",), (), False),  # genome only on the rsid/locus path
    "grounding.go":           ("genomic", ("genome",), (), False),  # genome only on the rsid/locus path
    "grounding.gene_disease": ("genomic", ("genome",), (), False),  # genome only on the rsid/locus path
    "grounding.diagnostic_panels": ("genomic", ("genome",), (), False),  # genome only on rsid/locus path
    "grounding.expression":   ("genomic", ("genome",), (), False),  # genome only on the rsid/locus path
    "grounding.celltype":   ("genomic", ("genome",), (), False),  # genome only on the rsid/locus path
    "grounding.gene":       ("genomic", ("genome",), (), False),  # composite; genome only on rsid/locus
    # --- genome (read; live gnomAD only when classifying an SNV) ----------- #
    "variant.resolve":   ("genomic", ("genome",), ("gnomad",), False),
    "genome.summary":    ("genomic", ("genome",), (), False),
    "clinvar.findings":  ("genomic", ("genome",), (), False),  # reads materialized pl_findings (local)
    "gwas.associations": ("genomic", ("genome",), (), False),
    "pgx.summary":       ("genomic", ("genome",), (), False),
    "pgs.score":         ("genomic", ("genome",), (), False),
    "acmg.classify":     ("genomic", ("genome",), ("gnomad",), False),
    "splice.assess":     ("genomic", ("genome",), ("gnomad",), False),
    # --- genome (mutating: spawn jobs + download references) --------------- #
    "genome.impute":    ("genomic", ("genome",), ("reference_download",), True),
    "genome.annotate":  ("genomic", ("genome",), ("gnomad", "reference_download"), True),
    "genome.pgx_run":   ("genomic", ("genome",), ("reference_download",), True),
    "ancestry.estimate":("genomic", ("genome",), ("reference_download",), True),  # FIX: was default mutating=False
    # --- synthesis / analyze ----------------------------------------------- #
    "synthesis.multi_omic_question": ("genomic", ("genome", "labs", "cgm", "wearable", "derived"), ("gnomad",), False),
    "analyze.report": ("genomic", ("genome", "labs", "cgm", "wearable", "derived"), (), False),
    "analyze.export": ("genomic", ("genome", "labs", "cgm", "wearable", "derived"), (), True),  # writes report.html
}


def apply() -> None:
    """Enrich every registered Operation with its consent/egress annotations (idempotent)."""
    for op in registry.all_operations():
        ann = _ANN.get(op.name)
        if ann is None:
            continue
        privacy, access, egress, mutating = ann
        registry.register(replace(
            op, privacy_scope=privacy, data_access=access, external_io=egress,
            operation_scope=("write" if mutating else op.operation_scope),
            mutating=mutating or op.mutating,
        ))


def missing() -> list[str]:
    """Registered operations with no annotation entry — must be empty (a coverage guard)."""
    return sorted(op.name for op in registry.all_operations() if op.name not in _ANN)
