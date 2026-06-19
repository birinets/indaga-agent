"""DNA connector — build the Active Genome Index from a consumer chip, and write
genomic facts into the Active Health Index.

Indaga owns its genome engine (`indaga.genome`): a consumer chip is parsed into a
per-subject Active Genome Index (genotype + zygosity + callability). Clinical
interpretation (ClinVar / PGS / PharmCAG) is reused from the already-computed
annotation; resolved variants are written back as graded genomic Facts.
"""

from __future__ import annotations

import glob
from pathlib import Path

from ..genome.agi import build_agi, build_agi_from_vcf
from ..runtime import paths
from ..store import Fact, HealthlakeStore, Scope, SourceRef

# Imputed (GRCh38) genomes are the DEPTH path — annotate millions of variants, not the
# ~600k raw chip. The imputed genome is INDAGA'S OWN output (~/.indaga/<subject>/imputed.vcf.gz),
# produced by Indaga's owned Beagle+HGDP imputer (connectors/impute.py). A user who installs
# the product has only their raw DNA + what Indaga computes — no external project on disk.
# If imputation hasn't run yet, the raw chip is the (thin) baseline.
def _own_imputed_vcf(subject_id: str) -> str | None:
    p = paths.subject_dir(subject_id) / "imputed.vcf.gz"
    return str(p) if p.exists() else None


def _find_chip(user_dir: str) -> str | None:
    for ext in ("*.csv", "*.txt"):
        hits = sorted(glob.glob(str(Path(user_dir) / "dna" / "raw" / ext)))
        if hits:
            return hits[0]
    return None


def ingest_genome(store: HealthlakeStore, subject_id: str, user_dir: str | None) -> int:
    """Build the Active Genome Index, preferring Indaga's own imputed GRCh38 genome over the
    raw chip. Returns the number of variants indexed (0 if no genome source found)."""
    paths.ensure_subject_dirs(subject_id)
    agi_path = str(paths.active_genome_index_path(subject_id))
    imputed = _own_imputed_vcf(subject_id)
    if imputed:
        # Imputed genome carries all variants + DR2; keep only confident calls (DR2≥0.3)
        # for the AGI. Re-attach the chip's rsIDs (the panel uses chrom:pos:ref:alt IDs) so
        # variant.resolve by rsID works for directly-typed common variants.
        rsid_map = None
        chain = paths.indaga_home() / "resources" / "liftover" / "hg19ToHg38.over.chain.gz"
        chip = _find_chip(user_dir) if user_dir else None
        if chip and chain.exists():
            from .impute import chip_rsid_map
            try:
                rsid_map = chip_rsid_map(chip, str(chain))
            except Exception:  # noqa: BLE001 — rsID re-attach is best-effort
                rsid_map = None
        stats = build_agi_from_vcf(imputed, agi_path, build="GRCh38", source="imputed",
                                   r2_min=0.3, rsid_map=rsid_map)
        # Overlay the raw chip's directly-typed genotypes onto the imputed AGI. Imputation can
        # LOSE a typed common SNP (it returns DR2=0 and is dropped — CYP1A2/HFE/ALDH2/…); the chip
        # still holds it as a direct measurement, which wins over imputation. Baking it in here (vs
        # a runtime fallback) means every consumer sees the recovered, grade-A genotype.
        if chip:
            from ..genome.agi import chip_agi_path, open_chip_agi, overlay_chip_calls
            try:
                cr = open_chip_agi(subject_id, user_dir)
                if cr is not None:
                    cr.close()
                    overlay_chip_calls(agi_path, str(chip_agi_path(subject_id)))
            except Exception:  # noqa: BLE001 — chip overlay is best-effort; never block the build
                pass
        kind, sid = "dna_imputed", "dna:imputed_grch38"
    elif user_dir and (chip := _find_chip(user_dir)):
        stats = build_agi(chip, agi_path)
        kind, sid = "dna_chip", "dna:chip"
    else:
        return 0
    n = int(stats["n_variants"])
    store.register_source(Scope(subject_id), SourceRef(
        source_file_id=sid,
        label=f"genome ({stats.get('source', stats.get('chip', '?'))}, {stats.get('build', '?')}, "
              f"{n:,} variants)",
        kind=kind, document_count=n,
    ))
    return n


def ingest_dna_chip(store: HealthlakeStore, subject_id: str, chip_path: str) -> int:
    """Build the Active Genome Index from a consumer chip CSV and register the source.
    Returns the number of variants indexed."""
    paths.ensure_subject_dirs(subject_id)
    stats = build_agi(chip_path, str(paths.active_genome_index_path(subject_id)))
    n = int(stats["n_variants"])
    store.register_source(Scope(subject_id), SourceRef(
        source_file_id="dna:myheritage_gsa",
        label=f"DNA chip ({stats.get('chip', '?')}, {stats.get('build', '?')}, {n:,} variants, "
              f"{int(stats['n_called']):,} called)",
        kind="dna_chip", document_count=n,
    ))
    return n


def ingest_genomic_facts(store: HealthlakeStore, subject_id: str, facts: list[Fact]) -> int:
    """Write genomic `Fact`s into the Active Health Index (e.g. from a batch screen)."""
    return store.upsert_facts(Scope(subject_id), facts)
