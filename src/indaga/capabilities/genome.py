"""Genome capability — DNA analysis over the Active Genome Index + reused evidence.

Tools: `variant.resolve` (genotype + callability + ClinVar), `genome.summary`,
`clinvar.findings` (the P/LP screen with honest false-alarm refutation), `pgs.score`,
`pgx.summary`. Resolved variants are written back into the Active Health Index as
graded genomic Facts so DNA fuses with labs / CGM / derived metrics.

The callability honesty (a variant the chip didn't probe → `not_measured`, never
"you don't have it") is the genomic leg of the multi-omic envelope.
"""

from __future__ import annotations

from ..evidence import envelope as E
from ..genome import evidence as ev
from ..genome.agi import AGIReader, VariantCall, open_chip_agi
from ..operations.model import Context, Operation
from ..operations.registry import register
from ..runtime import paths
from ..serialize import fact_to_dict
from ..store import (
    Caveat,
    CaveatCode,
    EvidenceGrade,
    Fact,
    Provenance,
    Scope,
    Severity,
    Surface,
)

_CAP = "genome"
_SKILL = "skills/genome/SKILL.md"


def _scope(context: Context) -> Scope:
    return Scope(context.subject_id, surface=context.surface or Surface.APP)


def _subj(scope: Scope) -> dict:
    return {"subject_id": scope.subject_id, "uses_personal_data": True, "omic_scope": "genomic"}


def _open_agi(context: Context) -> AGIReader | None:
    return AGIReader.open(str(paths.active_genome_index_path(context.subject_id)))


def _pl_for_rsid(user_dir: str, rsid: str, subject_id: str | None = None) -> dict | None:
    for f in ev.pl_findings(user_dir, subject_id):
        if f.get("rsid") == rsid:
            return f
    return None


def _variant_fact(subject_id: str, v: VariantCall, cv: dict | None, pl: dict | None,
                  *, directly_typed: bool) -> tuple[Fact, Provenance]:
    gene = (cv or {}).get("gene") or (pl or {}).get("gene")
    sig = (cv or {}).get("clinvar_sig") or (pl or {}).get("clinvar_sig")
    caveats: list[Caveat] = []
    # Grade by how the genotype was OBSERVED, never assumed: a directly chip-typed call is a
    # direct measurement (A); an imputed call is real but statistically inferred (C + caveat).
    # Grading an imputed genotype as a direct measurement is exactly the over-confidence the
    # evidence envelope exists to prevent — so the imputed default carries an IMPUTED caveat.
    if directly_typed:
        grade = EvidenceGrade.A
    else:
        grade = EvidenceGrade.C
        caveats.append(Caveat(
            CaveatCode.IMPUTED,
            "Genotype is imputed (statistically inferred from the reference panel), not directly "
            "typed on the chip — probabilistic; confirm a high-stakes call with a targeted assay.",
            Severity.INFO))
    if pl and pl.get("classification") == "common_likely_false_alarm":
        caveats.append(Caveat(
            CaveatCode.REFUTED,
            "Common variant (high population frequency) — a likely false-positive 'pathogenic' "
            "call, not a real high-penetrance risk.", Severity.WARN))
        grade = EvidenceGrade.C
    fid = f"variant_{v.rsid}"
    fact = Fact(
        fact_id=fid, subject_id=subject_id, domain="genomic",
        name=(f"{gene}_{v.rsid}" if gene else v.rsid),
        display=f"{(gene + ' ') if gene else ''}{v.rsid}",
        value_text=v.genotype, code_system="ClinVar" if sig else "dbSNP", code=v.rsid,
        evidence_grade=grade, caveats=tuple(caveats), provenance_id=f"prov_{fid}",
        attributes={
            "rsid": v.rsid, "gene": gene, "genotype": v.genotype, "zygosity": v.zygosity,
            "chrom": v.chrom, "pos": v.pos, "on_chip": directly_typed, "directly_typed": directly_typed,
            "clinvar_sig": sig, "clinvar_disease": (cv or {}).get("clinvar_disease"),
            "pl_classification": (pl or {}).get("classification"),
        },
    )
    prov = Provenance(f"prov_{fid}", fid, "variant", None,
                      "dna:myheritage_gsa" if directly_typed else "dna:imputed_genome",
                      "active-genome-index.sqlite", f"{v.chrom}:{v.pos} {v.rsid}",
                      "chip_genotype" if directly_typed else "imputation",
                      1.0 if directly_typed else None,
                      "genotyped" if directly_typed else "imputed")
    return fact, prov


def _pl_fact(subject_id: str, f: dict) -> Fact:
    """Turn one P/LP screen finding (a raw dict) into a graded genomic Fact via the confidence
    calculus — so the highest-stakes findings enter the Fact/envelope contract and the multi-omic
    synthesis layer can read them as graded facts, not bypass them (the review's #1 deeper finding)."""
    from ..evidence.confidence_calculus import grade_pl_finding
    grade, caveats = grade_pl_finding(f)
    gene, rsid = f.get("gene"), f.get("rsid")
    key = rsid or f"{f.get('chrom')}:{f.get('pos')}"
    fid = f"pl_{key}"
    return Fact(
        fact_id=fid, subject_id=subject_id, domain="genomic",
        name=(f"{gene}_{rsid}" if (gene and rsid) else (gene or rsid or key)),
        display=f"{(gene + ' ') if gene else ''}{rsid or key} (ClinVar P/LP)",
        value_text=f.get("clinvar_sig"),
        code_system="ClinVar", code=rsid or f.get("clinvar_id"),
        evidence_grade=grade, caveats=caveats, provenance_id=None,
        attributes={
            "rsid": rsid, "gene": gene, "chrom": f.get("chrom"), "pos": f.get("pos"),
            "ref": f.get("ref"), "alt": f.get("alt"), "zygosity": f.get("zygosity"),
            "clinvar_sig": f.get("clinvar_sig"), "classification": f.get("classification"),
            "carrier_status": f.get("carrier_status"), "confidence": f.get("confidence"),
            "review_stars": f.get("review_stars"), "directly_typed": bool(f.get("directly_typed")),
            "pl_finding": True,
        },
    )


def _variant_resolve(params: dict, context: Context) -> dict:
    scope = _scope(context)
    agi = _open_agi(context)
    if agi is None:
        return E_blocked("variant.resolve", scope, "Active Genome Index not built; ingest a genome source first.")
    rsid = (params.get("rsid") or params.get("query") or "").strip()
    if not rsid.lower().startswith("rs"):
        return {"evidence_envelope": E.not_assessed(
            operation="variant.resolve", reason="provide an rsID, e.g. {'rsid': 'rs7903146'}",
            subject_context=_subj(scope))}

    v = agi.lookup_rsid(rsid)
    cv = ev.clinvar_for_rsid(context.user_dir, rsid, context.subject_id)
    # Rare ClinVar variants aren't on the chip, so the imputed AGI keys them by chrom:pos,
    # not rsID — resolve via ClinVar's rsID→position index, then look up the genotype.
    via_position = False
    if (v is None or not v.callable) and cv and cv.get("chrom") and cv.get("pos") is not None:
        cands = agi.lookup_region(cv["chrom"], int(cv["pos"]), int(cv["pos"]))
        if cands:
            v = next((c for c in cands if cv.get("alt") in c.alleles), cands[0])
            via_position = True
    from_chip = False
    if v is None or not v.callable:
        # Imputation can lose a directly-typed common SNP (DR2=0 → dropped). The raw chip still
        # carries it as a direct measurement — recover it there before declaring "not measured".
        chip = open_chip_agi(context.subject_id, context.user_dir)
        cvar = chip.lookup_rsid(rsid) if chip else None
        if chip:
            chip.close()
        if cvar is not None and cvar.callable:
            v, from_chip = cvar, True
    if v is None or not v.callable:
        # Not in the genome (or a no-call): UNKNOWN, never "absent".
        env = E.not_measured(
            operation="variant.resolve", what=f"genotype at {rsid}",
            requires=(E.REQ_CALLABILITY, E.REQ_GENOTYPE_SUPPORT),
            reason=f"{rsid} is not in the subject's genome (not chip-typed and not confidently "
                   "imputed) — its genotype is unknown, not absent.",
            subject_context=_subj(scope))
        return {"rsid": rsid, "on_chip": False, "callable": False, "evidence_envelope": env}

    pl = _pl_for_rsid(context.user_dir, rsid, context.subject_id)
    # The chip is GRCh37; the AM/ACMG/consequence predictors are GRCh38-positioned, so they run
    # only on the imputed (GRCh38) genome. A chip-recovered call reports the directly-typed
    # genotype + ClinVar and skips the GRCh38-coordinate predictors.
    if from_chip:
        am = acmg_res = revel = None
    else:
        am, acmg_res, revel, _splice = _predict_and_classify(agi, v, rsid, cv)
    # A genotype is a direct measurement if it came straight from the chip (from_chip), or if it
    # was chip-typed in the AGI AND resolved by its own rsID — not recovered by position from the
    # imputed genome (via_position). Otherwise it is imputed → graded down + caveated in the Fact.
    agi_imputed = agi.metadata().get("source") == "imputed"
    # directly-typed if: recovered straight from the chip (from_chip), baked into the AGI by the
    # chip-overlay (v.typed), or chip-built AGI resolved by its own rsID (not a position recovery).
    directly_typed = from_chip or bool(getattr(v, "typed", 0)) or ((not via_position) and (not agi_imputed))
    fact, prov = _variant_fact(scope.subject_id, v, cv, pl, directly_typed=directly_typed)
    if acmg_res:
        fact.attributes["acmg_tier"] = acmg_res["acmg_tier"]
        fact.attributes["am_pathogenicity"] = (am or {}).get("am_pathogenicity")
    context.store.upsert_facts(scope, [fact])
    context.store.attach_provenance(scope, prov)
    consulted = ["chip/imputed", "ClinVar"] + (["AlphaMissense", "ACMG/AMP"] if acmg_res else [])
    if revel:
        consulted.append("REVEL")
    env = E.derive_envelope("variant.resolve", scope, [fact], omic_scope="genomic",
                            query_scope={"rsid": rsid}, consulted_sources=consulted)
    return {
        "rsid": rsid, "gene": fact.attributes["gene"], "genotype": v.genotype,
        "zygosity": v.zygosity, "chrom": v.chrom, "pos": v.pos,
        "directly_typed": directly_typed, "callable": True,
        "clinvar": cv, "pl_classification": fact.attributes.get("pl_classification"),
        "alphamissense": am, "revel": revel, "acmg": acmg_res,
        "fact": fact_to_dict(fact), "evidence_envelope": env,
    }


def _predict_and_classify(agi: AGIReader, v: VariantCall, rsid: str, cv: dict | None,
                          *, run_spliceai: bool = False):
    """Compute an ACMG/AMP tier for a variant the subject carries: AlphaMissense (missense
    SNVs) + REVEL + PVS1 (LoF consequence + gene constraint) + frequency, and — when
    ``run_spliceai`` (SpliceAI is slow: a TensorFlow cold start) — splice impact. Returns
    (alphamissense | None, acmg | None, revel | None, splice | None)."""
    extras = agi.variant_extras(rsid) or {}
    # ref/alt from the AGI (chip-typed) or ClinVar (rare position-resolved variants)
    ref = extras.get("ref") or (cv or {}).get("ref")
    alt = extras.get("alt") or (cv or {}).get("alt")
    panel_af = extras.get("af")
    gene = (cv or {}).get("gene")
    consequence = (cv or {}).get("consequence")
    # NOVEL variants (not in ClinVar, or ClinVar lacks a consequence): compute the molecular
    # consequence ourselves from the MANE model + FASTA → enables PVS1 (LoF) on novel findings,
    # which Genomi/OpenCRAVAT cannot (they only look ClinVar up). Also fills the gene symbol.
    if consequence is None and ref and alt:
        try:
            from ..genome.consequence import ConsequenceAnnotator
            ann = ConsequenceAnnotator.open()
            if ann is not None:
                cres = ann.annotate(v.chrom, v.pos, ref, alt)
                ann.close()
                if cres:
                    consequence = cres["consequence"]
                    gene = gene or cres["gene"]
        except Exception:  # noqa: BLE001 — consequence is optional (needs MANE + FASTA installed)
            pass
    from ..genome import acmg as acmg_mod
    from ..genome import constraint as constraint_mod
    from ..genome.pl_screen import PRIORITY_GENES
    from ..genome.predictors import AlphaMissense, Revel
    established_lof = bool(gene and gene in PRIORITY_GENES)

    is_snv = bool(ref and alt and len(ref) == 1 and len(alt) == 1 and ref != alt)
    am_res = pp = revel_score = None
    if is_snv:
        am = AlphaMissense.open()
        if am is not None:
            am_res = am.lookup(v.chrom, v.pos, ref, alt)
            if am_res:
                pp = AlphaMissense.pp3_bp4(am_res["am_pathogenicity"], am_res["am_class"])
            am.close()
        rv = Revel.open()
        if rv is not None:
            revel_score = rv.lookup(v.chrom, v.pos, ref, alt)
            rv.close()
    # PP3/BP4: AlphaMissense is primary; REVEL only fills in when AM doesn't cover the variant
    # (ClinGen guidance: don't stack predictors). REVEL is otherwise a reported second opinion.
    if pp is None and revel_score is not None:
        pp = Revel.pp3_bp4(revel_score)
    revel = _revel_payload(revel_score, am_res)

    # SpliceAI (opt-in; TensorFlow cold start). It scores a DIFFERENT mechanism than the missense
    # predictors, so it supplies PP3 only where they're silent (non-missense) — no double-counting.
    splice = None
    if run_spliceai and ref and alt:
        from ..connectors import spliceai as spliceai_mod
        sv = spliceai_mod.score_variant(v.chrom, v.pos, ref, alt)
        if sv:
            sp_pp = spliceai_mod.pp3(sv["ds_max"])
            splice = {"ds_max": round(sv["ds_max"], 2), "ds_ag": sv["ds_ag"], "ds_al": sv["ds_al"],
                      "ds_dg": sv["ds_dg"], "ds_dl": sv["ds_dl"], "symbol": sv["symbol"],
                      "pp3": f"{sp_pp[0]}_{sp_pp[1]}" if sp_pp else None}
            if pp is None and sp_pp:
                pp = sp_pp

    if not (am_res or consequence or revel_score or splice):
        return am_res, None, revel, splice  # nothing to classify

    af = panel_af
    if is_snv:
        try:
            from ..evidence.store import GnomadClient
            g = GnomadClient(build="GRCh38").fetch(v.chrom, v.pos, ref, alt)
            if g.get("af") is not None:
                af = g["af"]
        except Exception:  # noqa: BLE001 — fall back to panel AF
            pass
    acmg_res = acmg_mod.classify(
        gnomad_af=af, am_pathogenicity=(am_res or {}).get("am_pathogenicity"),
        am_class=(am_res or {}).get("am_class"), am_pp3_bp4=pp,
        consequence=consequence, gene_constraint=constraint_mod.constraint_for(gene),
        established_lof_gene=established_lof, clinvar_sig=(cv or {}).get("clinvar_sig"))
    return am_res, acmg_res, revel, splice


def _revel_payload(score: float | None, am_res: dict | None) -> dict | None:
    """REVEL second-opinion payload: score, its ClinGen PP3/BP4 call, and concordance with
    AlphaMissense (agreement is reassuring; divergence flags a borderline missense)."""
    if score is None:
        return None
    from ..genome.predictors import Revel
    call = Revel.pp3_bp4(score)
    out = {"score": round(score, 3), "call": (f"{call[0]}_{call[1]}" if call else None)}
    am_class = (am_res or {}).get("am_class")
    if am_class in ("likely_pathogenic", "likely_benign"):
        out["concordant_with_alphamissense"] = ((am_class == "likely_pathogenic") == (score >= 0.5))
    return out


def _genome_summary(params: dict, context: Context) -> dict:
    scope = _scope(context)
    agi = _open_agi(context)
    if agi is None:
        return E_blocked("genome.summary", scope, "Active Genome Index not built; ingest a genome source first.")
    st = agi.stats()
    ud = context.user_dir or ""
    sid = context.subject_id
    payload = {
        "active_genome_index": st,
        "clinvar_screen_candidates": len(ev.pl_findings(ud, sid)),
        "pgs_scores": len(ev.pgs_scores(ud, sid)),
        "pgx_available": ev.pharmcat_available(sid),
        "gwas_available": ev.gwas_available(sid),
    }
    env = E.evidence_present(operation="genome.summary", subject_context=_subj(scope), observations=st)
    return {**payload, "evidence_envelope": env}


def _clinvar_findings(params: dict, context: Context) -> dict:
    scope = _scope(context)
    findings = ev.pl_findings(context.user_dir or "", context.subject_id)
    not_common = [f for f in findings if f.get("classification") != "common_likely_false_alarm"]
    # Carrier-vs-at-risk: a recessive heterozygote is a CARRIER (not personal risk); only a
    # dominant single allele or a biallelic recessive is personal "at-risk". And imputed
    # (not directly-typed) P/LP not seen in gnomAD is likely an imputation artifact → confirm.
    at_risk = [f for f in not_common if f.get("carrier_status") in ("at_risk_dominant", "at_risk_biallelic")]
    confident_at_risk = [f for f in at_risk if f.get("confidence") == "directly_typed"]
    needs_confirmation = [f for f in at_risk if f.get("confidence") != "directly_typed"]
    carriers = [f for f in not_common if f.get("carrier_status") == "carrier"]
    out = [{
        "gene": f.get("gene"), "rsid": f.get("rsid"), "clinvar_sig": f.get("clinvar_sig"),
        "disease": f.get("clinvar_disease"), "classification": f.get("classification"),
        "gnomad_af": f.get("gnomad_af"), "zygosity": f.get("zygosity"),
        "inheritance": f.get("inheritance"), "carrier_status": f.get("carrier_status"),
        "interpretation": f.get("interpretation"), "panel": f.get("panel"),
        "directly_typed": f.get("directly_typed"), "confidence": f.get("confidence"),
        "review_stars": f.get("review_stars"),
    } for f in findings]
    # Materialize each finding as a GRADED genomic Fact in the Active Health Index, so the multi-omic
    # synthesis layer reads the P/LP findings through the same Fact/grade contract as everything else
    # (closes the review's #1 deeper finding: the screen previously emitted raw dicts that bypassed it).
    if findings:
        context.store.upsert_facts(scope, [_pl_fact(scope.subject_id, f) for f in findings])
    obs = {"candidates": len(findings), "after_refuting_common": len(not_common),
           "confident_at_risk": len(confident_at_risk),
           "needs_confirmation": len(needs_confirmation), "carrier_only": len(carriers)}
    # Gate the envelope on the ACTUAL evidence, never a blanket evidence_present (the bug that let an
    # allele-mismatch artifact present as a decision-grade positive). Only a directly-typed, exact-
    # match at-risk finding is decision-grade; imputed/needs-confirmation or carrier findings exist but
    # require orthogonal confirmation; nothing real → not a true negative (don't imply "clear").
    if confident_at_risk:
        env = E.evidence_present(
            operation="clinvar.findings", answer_readiness=E.SCOPED_ANSWER_ONLY,
            subject_context=_subj(scope), observations=obs)
    elif needs_confirmation or carriers:
        env = E.evidence_present(
            operation="clinvar.findings", answer_readiness=E.NEEDS_CLINICAL_CONFIRMATION,
            subject_context=_subj(scope), observations=obs)
    else:
        env = E.empty_consulted_scope(
            operation="clinvar.findings", subject_context=_subj(scope), observations=obs)
    return {"findings": out, "n_candidates": len(findings), "likely_real": len(not_common),
            "confident_at_risk": len(confident_at_risk), "needs_confirmation": len(needs_confirmation),
            "carrier_only": len(carriers),
            "note": "P/LP candidates, gnomAD-filtered + inheritance-aware + confidence-flagged. "
                    "'common_likely_false_alarm' = common variant wrongly flagged (ignore). carrier_status: "
                    "at_risk_dominant/at_risk_biallelic = personal risk; 'carrier' = recessive heterozygote "
                    "(family-planning, NOT personal risk). confidence: 'directly_typed' = high-confidence "
                    "chip call; 'imputed_unconfirmed' = imputed + not in gnomAD = LIKELY IMPUTATION ARTIFACT, "
                    "requires orthogonal confirmation (Sanger/clinical) before acting.",
            "evidence_envelope": env}


def _pgs_score(params: dict, context: Context) -> dict:
    scope = _scope(context)
    scores = ev.pgs_scores(context.user_dir or "", context.subject_id)
    if not scores:
        return {"evidence_envelope": E.not_measured(
            operation="pgs.score", what="polygenic scores", subject_context=_subj(scope))}
    q = (params.get("trait") or params.get("pgs_id") or "").lower()
    if q:
        sel = [s for s in scores if q in str(s.get("trait_label", "")).lower()
               or q in str(s.get("pgs_id", "")).lower() or q in str(s.get("category", "")).lower()]
    else:
        sel = sorted((s for s in scores if s.get("percentile") is not None),
                     key=lambda s: abs((s.get("percentile") or 50) - 50), reverse=True)[:8]
    def _conf(s) -> str:
        cov = s.get("coverage") or 0
        if cov >= 0.8:
            return "high"
        if cov >= 0.5:
            return "moderate"
        return "low"  # local imputation recovered <half the score's variants — interpret loosely

    out = [{"pgs_id": s.get("pgs_id"), "trait": s.get("trait_label"),
            "percentile": round(s["percentile"], 1) if s.get("percentile") is not None else None,
            "direction": s.get("direction"), "category": s.get("category"),
            "coverage": round(s.get("coverage") or 0, 2),
            "variants_used": f"{s.get('n_matched')}/{s.get('n_total')}",
            "confidence": _conf(s)} for s in sel]
    low = sum(1 for s in out if s["confidence"] == "low")
    env = E.evidence_present(
        operation="pgs.score", answer_readiness=E.SCOPED_ANSWER_ONLY, subject_context=_subj(scope),
        observations={"n_scores": len(scores), "returned": len(out), "low_confidence": low})
    return {"scores": out, "n_total": len(scores),
            "note": "Polygenic scores are population-relative percentiles, directional, not a diagnosis. "
                    "'confidence'/'coverage' reflect how many of the score's variants the LOCAL imputation "
                    "recovered: 'low' (<50%) percentiles regress toward 50th and UNDERSTATE risk — they are "
                    "coverage-limited, not a true low score. The percentile is analytic (z→normal CDF) and "
                    "ASSUMES the score's variants are in linkage equilibrium (independent); for LD-correlated "
                    "scores it underestimates variance, so extreme percentiles are over-dispersed (read 95th/5th "
                    "as 'high/low', not literally). High-confidence polygenic scoring needs a denser panel "
                    "(TOPMed, server-side); the local 1000G-30x panel is the privacy-preserving ceiling.",
            "evidence_envelope": env}


def _pgx_summary(params: dict, context: Context) -> dict:
    scope = _scope(context)
    genes = ev.pharmcat_genes(subject_id=context.subject_id)
    if not genes:
        return {"evidence_envelope": E.not_measured(
            operation="pgx.summary", what="pharmacogenomic diplotypes (run genome.pgx_run first)",
            subject_context=_subj(scope))}
    called = [g for g in genes if g["called"]]
    blind = [g["gene"] for g in genes if not g["called"]]
    # genes whose reference call leans on absent-to-ref filling (low defining-position coverage):
    # surfaced explicitly so a "normal metabolizer" that is actually an assumption isn't trusted.
    ref_assumed = [g["gene"] for g in genes if g.get("reference_assumed")]
    gene_q = (params.get("gene") or "").upper()
    if gene_q:
        called = [g for g in called if g["gene"] == gene_q]
    env = E.evidence_present(
        operation="pgx.summary", answer_readiness=E.SCOPED_ANSWER_ONLY, subject_context=_subj(scope),
        observations={"genes_called": len(called), "blind_spots": blind, "reference_assumed": ref_assumed})
    return {
        "diplotypes": [{"gene": g["gene"], "diplotype": g["diplotype"], "phenotype": g["phenotype"],
                        "function": g["function"], "activity_score": g.get("activity_score"),
                        "coverage": g.get("coverage")} for g in called],
        "blind_spots": blind,
        "reference_assumed": ref_assumed,
        "note": "PharmCAT diplotypes computed in-house on the imputed genome (CPIC star-alleles). "
                "PGx positions absent from the imputed subset are filled as reference (--absent-to-ref). "
                "A NON-reference diplotype requires an observed alt, so it is never an absent-to-ref "
                "artifact; but a REFERENCE call resting on mostly-absent defining positions is an "
                "assumption — those genes are flagged 'reference_assumed' and treated as no-call, not a "
                "confident 'normal metabolizer'. 'coverage' is the fraction of each gene's defining "
                "positions actually observed. Blind-spot genes (e.g. CYP2D6) that arrays/imputation "
                "cannot confidently resolve are listed separately — for drugs they govern, a clinical PGx "
                "panel is needed before prescribing. Decision-support, not a prescription.",
        "evidence_envelope": env,
    }


def _genome_pgx_run(params: dict, context: Context) -> dict:
    """Run in-house PharmCAT on the imputed genome as a BACKGROUND job (the first run also
    fetches PharmCAT's ~883 MB reference FASTA). Poll indaga.check_background_job; then query
    pgx.summary. Requires an imputed genome (genome.impute) first."""
    from ..runtime import jobs
    scope = _scope(context)
    args = ["pharmcat", "--subject", context.subject_id, "--user-dir", context.user_dir or ""]
    rep = jobs.start_cli_job(context.subject_id, args, "in-house PharmCAT (PGx on imputed genome)")
    env = E.evidence_present(operation="genome.pgx_run", subject_context=_subj(scope), observations=rep)
    return {**rep,
            "note": "PharmCAT runs in the BACKGROUND. Poll indaga.check_background_job with this job_id; "
                    "when finished, call pgx.summary. The first run downloads PharmCAT's GRCh38 reference "
                    "FASTA (~883 MB) — later runs take ~1 minute.",
            "evidence_envelope": env}


def _gwas_associations(params: dict, context: Context) -> dict:
    scope = _scope(context)
    trait = params.get("trait")
    assoc = ev.gwas_associations(context.user_dir or "", trait=trait, limit=int(params.get("limit", 25)),
                                 subject_id=context.subject_id)
    if not assoc:
        # GWAS computable (annotated GRCh38 + catalog) but nothing matched → searched, not absent.
        # Otherwise the capability genuinely cannot assess (no annotation / GRCh37-only / no catalog).
        if ev.gwas_available(context.subject_id):
            return {"trait": trait,
                    "note": "No GWAS-Catalog association matched in the consulted scope — not a "
                            "negative finding (the catalog is trait-curated and incomplete).",
                    "evidence_envelope": E.empty_consulted_scope(
                        operation="gwas.associations", subject_context=_subj(scope))}
        return {"evidence_envelope": E.not_measured(
            operation="gwas.associations", what=f"GWAS associations{' for ' + trait if trait else ''}",
            subject_context=_subj(scope))}
    env = E.evidence_present(
        operation="gwas.associations", answer_readiness=E.SCOPED_ANSWER_ONLY, subject_context=_subj(scope),
        observations={"associations": len(assoc), "trait": trait})
    return {"associations": assoc, "trait": trait,
            "note": "GWAS-Catalog associations for the subject's variants. Association ≠ causation; "
                    "effect sizes (OR/beta) are population-level and small for most common variants. "
                    "Ancestry of the original study affects transferability.",
            "evidence_envelope": env}


def _genome_impute(params: dict, context: Context) -> dict:
    """Start on-device imputation (Beagle + 1000G-30x) as a BACKGROUND job — it runs for
    minutes (full genome). Poll indaga.check_background_job, then call genome.annotate."""
    from ..runtime import jobs
    scope = _scope(context)
    if not context.user_dir:
        return E_blocked("genome.impute", scope, "no user-dir (raw chip location) for this subject")
    args = ["impute", "--subject", context.subject_id, "--user-dir", context.user_dir]
    if params.get("chroms"):
        args += ["--chroms", str(params["chroms"])]
    rep = jobs.start_cli_job(context.subject_id, args, "genome imputation (Beagle + 1000G-30x)")
    env = E.evidence_present(operation="genome.impute", subject_context=_subj(scope), observations=rep)
    return {**rep,
            "note": "Imputation runs in the BACKGROUND (~minutes to ~tens of minutes for the full "
                    "genome; bref3 panels make it fast). Poll indaga.check_background_job with this "
                    "job_id; when finished, run genome.annotate to build the AGI + screen + scores.",
            "evidence_envelope": env}


def _genome_annotate(params: dict, context: Context) -> dict:
    """Run the full in-house annotation: build the AGI + ClinVar P/LP screen (carrier/confidence/
    ACMG-aware) + polygenic scores. Reasonably quick; use after imputation completes."""
    from ..connectors.annotate import annotate_genome
    scope = _scope(context)
    rep = annotate_genome(context.store, context.subject_id, context.user_dir,
                          run_pgs=not bool(params.get("no_pgs")), rebuild=bool(params.get("rebuild")))
    env = E.evidence_present(operation="genome.annotate", subject_context=_subj(scope), observations=rep)
    return {**rep, "evidence_envelope": env}


def _ancestry_estimate(params: dict, context: Context) -> dict:
    """Most likely continental superpopulation by ancestry-informative-marker likelihood,
    from the imputed genome. Builds the AIM reference once (background) on first use."""
    from ..connectors.ancestry import aim_reference_path, estimate_ancestry
    scope = _scope(context)
    if not aim_reference_path().exists():
        from ..runtime import jobs
        rep = jobs.start_cli_job(context.subject_id,
                                 ["ancestry", "--subject", context.subject_id, "--user-dir", context.user_dir or ""],
                                 "ancestry AIM-reference build (1000G panel scan)")
        return {**rep,
                "note": "Building the ancestry reference (one-time 1000G-panel scan, ~minutes) in the "
                        "BACKGROUND. Poll indaga.check_background_job, then call ancestry.estimate again.",
                "evidence_envelope": E.evidence_present(operation="ancestry.estimate",
                                                        subject_context=_subj(scope), observations=rep)}
    res = estimate_ancestry(context.subject_id)
    if res.get("status") != "ok":
        return {**res, "evidence_envelope": E.not_measured(
            operation="ancestry.estimate", what="continental ancestry estimate", subject_context=_subj(scope))}
    env = E.evidence_present(
        operation="ancestry.estimate", answer_readiness=E.SCOPED_ANSWER_ONLY, subject_context=_subj(scope),
        observations={"assigned": res["assigned_superpopulation"], "n_markers": res["n_markers"]})
    return {"assigned_superpopulation": res["assigned_superpopulation"], "confidence": res["confidence"],
            "similarity": res["similarity"], "n_markers": res["n_markers"],
            "note": "Nearest-superpopulation assignment by ancestry-informative-marker (AIM) similarity "
                    "(correlation of the subject's allele dosage with 1000G AFR/AMR/EAS/EUR/SAS allele "
                    "frequencies). This is continental ASSIGNMENT, not admixture-fraction deconvolution — "
                    "'similarity' is a relative genetic-similarity ranking, not genome ancestry fractions; "
                    "recent admixture and self-identified identity aren't captured.",
            "evidence_envelope": env}


def _splice_assess(params: dict, context: Context) -> dict:
    """SpliceAI splice-impact assessment for a variant (by rsID), with a splice-aware ACMG tier.
    SLOW (a TensorFlow cold start) — call when splicing is the question, not for every variant."""
    scope = _scope(context)
    from ..connectors import spliceai as spliceai_mod
    rsid = (params.get("rsid") or params.get("query") or "").strip()
    if not rsid.lower().startswith("rs"):
        return {"evidence_envelope": E.not_assessed(
            operation="splice.assess", reason="provide an rsID, e.g. {'rsid': 'rs...'}",
            subject_context=_subj(scope))}
    if not spliceai_mod.available():
        return {"evidence_envelope": E.not_measured(
            operation="splice.assess", what="SpliceAI splice prediction (its TensorFlow venv + the "
            "GRCh38 reference FASTA must be installed)", subject_context=_subj(scope))}
    agi = _open_agi(context)
    if agi is None:
        return E_blocked("splice.assess", scope, "Active Genome Index not built; ingest a genome source first.")
    v = agi.lookup_rsid(rsid)
    cv = ev.clinvar_for_rsid(context.user_dir, rsid, context.subject_id)
    if (v is None or not v.callable) and cv and cv.get("chrom") and cv.get("pos") is not None:
        cands = agi.lookup_region(cv["chrom"], int(cv["pos"]), int(cv["pos"]))
        if cands:
            v = next((c for c in cands if cv.get("alt") in c.alleles), cands[0])
    if v is None or not v.callable:
        return {"rsid": rsid, "callable": False, "evidence_envelope": E.not_measured(
            operation="splice.assess", what=f"genotype at {rsid}",
            requires=(E.REQ_CALLABILITY, E.REQ_GENOTYPE_SUPPORT), subject_context=_subj(scope))}
    _am, acmg_res, _rv, splice = _predict_and_classify(agi, v, rsid, cv, run_spliceai=True)
    env = E.evidence_present(operation="splice.assess", answer_readiness=E.SCOPED_ANSWER_ONLY,
                            subject_context=_subj(scope),
                            observations={"ds_max": (splice or {}).get("ds_max"), "scored": bool(splice)})
    note = ("SpliceAI delta scores (acceptor/donor × gain/loss, 0–1); ds_max is the splice-altering "
            "probability (≥0.5 likely, ≥0.8 high-confidence). A high score predicts a splice effect the "
            "missense predictors and the canonical ±1/2 rule miss → contributes ACMG PP3 (computational). "
            "RNA confirmation is the gold standard before acting." if splice else
            "SpliceAI returned no score — the variant lies outside any annotated transcript window "
            "(>50 bp from an exon) or is not in a MANE gene; no splice effect is predicted there.")
    return {"rsid": rsid, "gene": (cv or {}).get("gene") or (splice or {}).get("symbol"),
            "genotype": v.genotype, "chrom": v.chrom, "pos": v.pos,
            "splice": splice, "acmg": acmg_res, "note": note, "evidence_envelope": env}


def _acmg_classify(params: dict, context: Context) -> dict:
    """Compute an ACMG/AMP classification for a variant by rsID (PVS1 LoF + PM2/BA1/BS1 +
    PP3/BP4 AlphaMissense → 5-tier), alongside ClinVar's call. Thin focus over variant.resolve."""
    r = _variant_resolve({"rsid": params.get("rsid") or params.get("query") or ""}, context)
    return {"rsid": r.get("rsid"), "gene": r.get("gene"), "genotype": r.get("genotype"),
            "clinvar": r.get("clinvar"), "alphamissense": r.get("alphamissense"),
            "acmg": r.get("acmg"), "evidence_envelope": r["evidence_envelope"]}


def E_blocked(op: str, scope: Scope, msg: str) -> dict:
    return {"evidence_envelope": E.not_assessed(operation=op, reason=msg, subject_context=_subj(scope))}


register(Operation("variant.resolve", _variant_resolve, capability=_CAP, skill=_SKILL,
    description="Resolve a variant by rsID: the subject's genotype + zygosity, ClinVar "
                "significance, callability, AND — for missense SNVs — an AlphaMissense score "
                "plus a COMPUTED ACMG/AMP classification (not just ClinVar's lookup). A variant "
                "not in the genome returns 'not measured' (unknown), never a false negative.",
    input_schema={"type": "object", "properties": {"rsid": {"type": "string"}, "query": {"type": "string"}}},
    produces=("genomic_fact", "evidence_envelope"), omic_scope="genomic", discovery_role="entry_tool"))

register(Operation("genome.summary", _genome_summary, capability=_CAP, skill=_SKILL,
    description="Active Genome Index stats (chip, build, variant + callability counts) and what genome "
                "evidence is available (ClinVar screen, PGS, PharmCAG).",
    input_schema={"type": "object", "properties": {}},
    produces=("evidence_envelope",), omic_scope="genomic", discovery_role="entry_tool"))

register(Operation("clinvar.findings", _clinvar_findings, capability=_CAP, skill=_SKILL,
    description="High-penetrance ClinVar P/LP candidates from the screen, with honest false-alarm "
                "refutation (common variants wrongly flagged pathogenic are marked, not alarmed).",
    input_schema={"type": "object", "properties": {}},
    produces=("evidence_envelope",), omic_scope="genomic", discovery_role="focused_tool"))

register(Operation("gwas.associations", _gwas_associations, capability=_CAP, skill=_SKILL,
    description="GWAS-Catalog trait/disease associations for the subject's variants (from the "
                "annotation), strongest p-value first. Filter by trait. Association, not causation.",
    input_schema={"type": "object", "properties": {
        "trait": {"type": "string"}, "limit": {"type": "integer"}}},
    produces=("evidence_envelope",), omic_scope="genomic", discovery_role="focused_tool"))

register(Operation("pgx.summary", _pgx_summary, capability=_CAP, skill=_SKILL,
    description="Pharmacogenomic diplotypes (PharmCAG) per gene, with honest chip blind-spots "
                "(CYP2D6/CYP2C19 can't be phenotyped from an array). Filter by gene.",
    input_schema={"type": "object", "properties": {"gene": {"type": "string"}}},
    produces=("evidence_envelope",), omic_scope="genomic", discovery_role="focused_tool"))

register(Operation("pgs.score", _pgs_score, capability=_CAP, skill=_SKILL,
    description="Polygenic scores (PGS Catalog, on imputed data) as population percentiles. Filter by "
                "trait/pgs_id, or get the most extreme. Directional, not diagnostic. Coverage/confidence flagged.",
    input_schema={"type": "object", "properties": {
        "trait": {"type": "string"}, "pgs_id": {"type": "string"}}},
    produces=("evidence_envelope",), omic_scope="genomic", discovery_role="focused_tool"))

register(Operation("acmg.classify", _acmg_classify, capability=_CAP, skill=_SKILL,
    description="Compute an ACMG/AMP classification for a variant by rsID — PVS1 (LoF + gene "
                "constraint) + PM2/BA1/BS1 (frequency) + PP3/BP4 (AlphaMissense) combined into a "
                "5-tier call, shown next to ClinVar's. Indaga COMPUTES this; it isn't a lookup.",
    input_schema={"type": "object", "properties": {"rsid": {"type": "string"}, "query": {"type": "string"}}},
    produces=("evidence_envelope",), omic_scope="genomic", discovery_role="focused_tool"))

register(Operation("splice.assess", _splice_assess, capability=_CAP, skill=_SKILL,
    description="SpliceAI splice-impact prediction for a variant by rsID (delta scores + splice-aware "
                "ACMG PP3) — catches splice-altering variants AlphaMissense and the canonical ±1/2 rule "
                "miss (deep-intronic, exonic-splice). SLOW (TensorFlow cold start); use when splicing is "
                "the question.",
    input_schema={"type": "object", "properties": {"rsid": {"type": "string"}, "query": {"type": "string"}}},
    produces=("evidence_envelope",), omic_scope="genomic", discovery_role="focused_tool"))

register(Operation("genome.impute", _genome_impute, capability=_CAP, skill=_SKILL,
    description="Extend the subject's chip to a dense GRCh38 genome on-device (Beagle + 1000G-30x). "
                "Long-running → starts a BACKGROUND job; poll indaga.check_background_job, then "
                "genome.annotate. Pass 'chroms' (e.g. '22') for a quick subset.",
    input_schema={"type": "object", "properties": {"chroms": {"type": "string"}}},
    produces=("evidence_envelope",), omic_scope="genomic", discovery_role="focused_tool", mutating=True))

register(Operation("genome.annotate", _genome_annotate, capability=_CAP, skill=_SKILL,
    description="Run the full in-house annotation over the subject's genome: build the Active Genome "
                "Index + ClinVar P/LP screen (carrier/confidence/ACMG-aware) + polygenic scores. "
                "Use after imputation. 'no_pgs' for screen-only; 'rebuild' to recompute.",
    input_schema={"type": "object", "properties": {
        "no_pgs": {"type": "boolean"}, "rebuild": {"type": "boolean"}}},
    produces=("evidence_envelope",), omic_scope="genomic", discovery_role="focused_tool", mutating=True))

register(Operation("genome.pgx_run", _genome_pgx_run, capability=_CAP, skill=_SKILL,
    description="Run in-house PharmCAT (CPIC star-allele diplotypes) on the imputed genome. "
                "Long-running → starts a BACKGROUND job; poll indaga.check_background_job, then "
                "pgx.summary. Requires genome.impute first; the first run also fetches a reference FASTA.",
    input_schema={"type": "object", "properties": {}},
    produces=("evidence_envelope",), omic_scope="genomic", discovery_role="focused_tool", mutating=True))

register(Operation("ancestry.estimate", _ancestry_estimate, capability=_CAP, skill=_SKILL,
    description="Most likely continental superpopulation (1000G AFR/AMR/EAS/EUR/SAS) for the subject's "
                "imputed genome, by ancestry-informative-marker likelihood. Continental ASSIGNMENT, not "
                "admixture fractions. Builds its AIM reference once (background) on first use.",
    input_schema={"type": "object", "properties": {}},
    produces=("evidence_envelope",), omic_scope="genomic", discovery_role="focused_tool"))
