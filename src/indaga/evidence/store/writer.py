"""Writer — materialize the P/LP screen + PGS results into a subject's evidence.sqlite."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_pl_findings(con: sqlite3.Connection, findings: list[dict]) -> int:
    now = _now()
    con.execute("DELETE FROM pl_findings")
    rows = [(
        f.get("rsid"), f.get("gene"), f.get("panel"),
        f.get("chrom"), f.get("pos"), f.get("ref"), f.get("alt"), f.get("achange"),
        f.get("candidate_reason"),
        f.get("clinvar_sig"), f.get("clinvar_disease"), f.get("clinvar_review"),
        f.get("gnomad_af"), f.get("gnomad_source"),
        f.get("classification") or "uncertain",
        f.get("zygosity"), f.get("inheritance"), f.get("carrier_status"), f.get("interpretation"),
        1 if f.get("directly_typed") else 0, f.get("confidence"), f.get("review_stars"),
        now,
    ) for f in findings]
    con.executemany(
        "INSERT OR REPLACE INTO pl_findings(rsid,gene,panel,chrom,pos,ref,alt,achange,candidate_reason,"
        "clinvar_sig,clinvar_disease,clinvar_review,gnomad_af,gnomad_source,classification,"
        "zygosity,inheritance,carrier_status,interpretation,directly_typed,confidence,review_stars,created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    return len(rows)


def upsert_pgs_results(con: sqlite3.Connection, results: list[dict]) -> int:
    now = _now()
    con.execute("DELETE FROM pgs_results")
    rows = [(
        s.get("pgs_id"), s.get("category"), s.get("trait_label"), s.get("direction"), s.get("note"),
        s.get("raw_score"), s.get("n_total"), s.get("n_matched"), s.get("coverage"),
        s.get("n_strand_flipped"), s.get("n_ambiguous_skipped"),
        s.get("af_coverage"), s.get("n_af_from_gnomad"),
        s.get("z_score"), s.get("percentile"), s.get("pop_mu"), s.get("pop_sd"), now,
    ) for s in results]
    con.executemany(
        "INSERT OR REPLACE INTO pgs_results(pgs_id,category,trait_label,direction,note,raw_score,"
        "n_total,n_matched,coverage,n_strand_flipped,n_ambiguous_skipped,af_coverage,n_af_from_gnomad,"
        "z_score,percentile,pop_mu,pop_sd,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    return len(rows)
