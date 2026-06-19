"""Genome annotation orchestrator — Indaga's own pipeline, no HeathProject outputs.

Given a subject's Active Genome Index (built from their imputed GRCh38 genome, or a
raw chip as fallback), this:
  1. ensures the matching-build ClinVar is imported into the shared evidence DB,
  2. runs the P/LP screen (ClinVar⋈AGI carriers + gnomAD refutation),
  3. computes polygenic scores against the downloaded PGS weights,
  4. materializes both into the subject's evidence.sqlite and marks annotation complete.

Idempotent: re-running with an unchanged AGI is a no-op (the AGI signature is stored).
This replaces the dependency on HeathProject's pre-computed OpenCRAVAT/PGS outputs.
"""

from __future__ import annotations

from ..evidence.store import (
    EvidenceStoreReader,
    GnomadClient,
    import_clinvar_vcf,
    import_gwas_catalog,
    init_subject,
    upsert_pgs_results,
    upsert_pl_findings,
)
from ..evidence.store import connection as econn
from ..genome import pgs as pgs_mod
from ..genome import pl_screen
from ..genome.agi import AGIReader
from ..reference import manager as refmgr
from ..runtime import paths


def _norm_build(raw: str | None) -> str:
    b = (raw or "").lower()
    if "38" in b:
        return "GRCh38"
    if "37" in b or b == "build37":
        return "GRCh37"
    return "GRCh38"


def annotate_genome(store, subject_id: str, user_dir: str | None = None, *,
                    online: bool = True, rebuild: bool = False, run_pgs: bool = True) -> dict:
    agi_path = str(paths.active_genome_index_path(subject_id))
    agi = AGIReader.open(agi_path)
    if agi is None:
        return {"status": "no_agi", "subject": subject_id}
    meta = agi.metadata()
    build = _norm_build(meta.get("build"))
    source = meta.get("source", meta.get("chip", "unknown"))
    signature = f"{meta.get('source_path')}|{meta.get('n_variants')}|{build}"

    ev_path = paths.evidence_path(subject_id)
    con = init_subject(ev_path)
    try:
        done = (econn.get_meta(con, "annotation_complete") == "1"
                and econn.get_meta(con, "agi_signature") == signature)
        pgs_done = econn.get_meta(con, "pgs_complete") == "1"
        if not rebuild and done and (not run_pgs or pgs_done):
            agi.close()
            return {"status": "cached", "subject": subject_id, "build": build,
                    "pl_findings": _count(con, "pl_findings"), "pgs": _count(con, "pgs_results")}

        # 1) ensure ClinVar for this build (cached after first import)
        clinvar_vcf = refmgr.clinvar_vcf_path(build)
        clinvar_ok = clinvar_vcf.exists()
        if clinvar_ok:
            import_clinvar_vcf(str(clinvar_vcf), genome_build=build)

        # 1b) ensure the GWAS Catalog is imported into shared (cached; best-effort, build-shared)
        gwas_zip = refmgr.gwas_zip_path()
        if gwas_zip.exists():
            try:
                import_gwas_catalog(str(gwas_zip))
            except Exception:  # noqa: BLE001 — GWAS is optional; never block annotation
                pass

        # 2) P/LP screen (ClinVar⋈AGI carriers + gnomAD refutation)
        pl: list[dict] = []
        if clinvar_ok:
            reader = EvidenceStoreReader.open(ev_path)
            gnomad = GnomadClient(build=build, online=online)
            pl = pl_screen.run_pl_screen(reader, agi_path, gnomad, build=build)
            reader.close()
            upsert_pl_findings(con, pl)

        # 3) polygenic scores — AF from the genome's own panel AF (offline, reliable)
        scores: list[dict] = []
        if run_pgs:
            scores = pgs_mod.run_pgs(agi, build=build)
            upsert_pgs_results(con, scores)

        # 4) mark complete
        econn.set_meta(con, "annotation_complete", "1")
        econn.set_meta(con, "agi_signature", signature)
        econn.set_meta(con, "genome_build", build)
        econn.set_meta(con, "genome_source", source)
        if run_pgs:
            econn.set_meta(con, "pgs_complete", "1")
        con.commit()
        n_real = sum(1 for f in pl if f.get("classification") not in ("common_likely_false_alarm",))
        return {"status": "annotated", "subject": subject_id, "build": build, "source": source,
                "pl_findings": len(pl), "pl_after_refutation": n_real,
                "pgs": len([s for s in scores if s.get("percentile") is not None]),
                "clinvar_available": clinvar_ok}
    finally:
        con.close()
        agi.close()


def _count(con, table: str) -> int:
    return con.execute(f"SELECT count(*) AS c FROM {table}").fetchone()["c"]
