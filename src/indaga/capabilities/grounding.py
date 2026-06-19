"""Analytical grounding — the interpretation-depth layer (LOCAL-FIRST, no egress).

Turns a bare finding ("you carry rs7903146") into biological *context* ("rs7903146 sits in an intron of
TCF7L2…"). Genomi's grounding is mostly live external APIs (Reactome/KEGG/HPA/OpenTargets) — each query
leaks the user's gene-of-interest to a third party. Indaga grounds from DOWNLOADED reference data instead,
so grounding is fully offline and discloses no locus interest (``external_io=()``).

Tools (built incrementally):
  - ``grounding.region``    — locus → overlapping gene model feature (exon/intron, coding/UTR, dist-to-TSS)
                              from the MANE GeneModel already on disk. (this module)
  - ``grounding.regulatory``— locus → overlapping ENCODE cCRE (promoter/enhancer/CTCF). (this module)
  - ``grounding.pathways``  — gene (or locus→gene) → Reactome pathway memberships (local GMT). (this module)
  - ``grounding.go``        — gene (or locus→gene) → Gene Ontology process/function/component terms. (this module)
  - ``grounding.gene_disease``— gene (or locus→gene) → graded GenCC+ClinGen disease validity. (this module)
  - ``grounding.diagnostic_panels``— gene (or locus→gene) → green PanelApp diagnostic panels. (this module)
  - ``grounding.expression``— gene (or locus→gene) → top tissues by HPA consensus RNA (nTPM). (this module)
  - ``grounding.celltype``  — gene (or locus→gene) → top cell types by HPA single-cell RNA (nCPM). (this module)
  - ``grounding.gene``      — one call composing region + regulatory + pathways + expression (entry Genomi lacks).
"""

from __future__ import annotations

from ..evidence import envelope as E
from ..genome.agi import AGIReader
from ..genome.celltype import CellTypeExpression
from ..genome.expression import TissueExpression
from ..genome.gene_disease import GeneDisease
from ..genome.genemodel import GeneModel
from ..genome.genesets import GeneSets
from ..genome.genesymbols import GeneSymbols
from ..genome.go_terms import GoTerms
from ..genome.panels_diagnostic import DiagnosticPanels
from ..genome.regulatory import RegulatoryElements
from ..operations.model import Context, Operation
from ..operations.registry import register
from ..runtime import paths
from ..store import Scope, Surface

_CAP = "grounding"
_SKILL = "skills/grounding/SKILL.md"


def _scope(context: Context) -> Scope:
    return Scope(context.subject_id, surface=context.surface or Surface.APP)


def _canon_gene(gene: str | None) -> str | None:
    """Canonicalise a gene symbol to the approved HGNC name (entity-canon), so an alias / previous /
    Entrez / Ensembl identifier still grounds. Best-effort: identity if HGNC isn't installed."""
    if not gene:
        return gene
    gs = GeneSymbols.open()
    return gs.canonical(gene) if gs is not None else gene


def _subj(scope: Scope) -> dict:
    return {"subject_id": scope.subject_id, "uses_personal_data": True, "omic_scope": "genomic"}


def _resolve_locus(context: Context, params: dict) -> tuple[str | None, int | None, str | None]:
    """Return (chrom, pos, rsid). Accepts explicit chrom+pos, or an rsID resolved via the AGI."""
    chrom = params.get("chrom")
    pos = params.get("pos")
    rsid = (params.get("rsid") or params.get("query") or "").strip() or None
    if rsid and (not chrom or pos is None):
        agi = AGIReader.open(str(paths.active_genome_index_path(context.subject_id)))
        v = agi.lookup_rsid(rsid) if agi else None
        if agi:
            agi.close()
        if v is not None:
            chrom, pos = v.chrom, v.pos
    return chrom, (int(pos) if pos is not None else None), rsid


def _grounding_region(params: dict, context: Context) -> dict:
    """Ground a locus against the MANE transcript model: which gene, exon vs intron, coding vs UTR,
    strand, and distance to the transcription start site. Local-only (no network)."""
    scope = _scope(context)
    chrom, pos, rsid = _resolve_locus(context, params)
    if not chrom or pos is None:
        return {"evidence_envelope": E.not_assessed(
            operation="grounding.region",
            reason="provide an rsID (on the subject's genome) or explicit chrom + pos",
            subject_context=_subj(scope))}

    gm = GeneModel.open(auto_install=False)  # read-only: never trigger a download from grounding
    if gm is None:
        return {"rsid": rsid, "chrom": chrom, "pos": pos, "evidence_envelope": E.not_measured(
            operation="grounding.region",
            what="MANE gene model (run: indaga install mane-select)",
            subject_context=_subj(scope))}
    tx = gm.transcript_at(chrom, pos)
    gm.close()

    if tx is None:
        # not within a MANE coding transcript → intergenic (in the consulted model)
        return {"rsid": rsid, "chrom": chrom, "pos": pos, "gene": None, "feature": "intergenic",
                "note": "Not within a MANE coding transcript (intergenic, or a non-coding/non-MANE gene). "
                        "Grounding uses MANE Select coding transcripts only.",
                "evidence_envelope": E.empty_consulted_scope(
                    operation="grounding.region", subject_context=_subj(scope))}

    in_exon = any(s <= pos <= e for s, e in tx["exons"])
    in_cds = any(s <= pos <= e for s, e in tx["cds"])
    feature = "coding_exon" if in_cds else ("untranslated_exon" if in_exon else "intron")
    starts = [s for s, e in tx["exons"]]
    ends = [e for s, e in tx["exons"]]
    tx_start, tx_end = min(starts), max(ends)
    tss = tx_start if tx["strand"] == "+" else tx_end
    dist_tss = (pos - tss) if tx["strand"] == "+" else (tss - pos)
    env = E.evidence_present(operation="grounding.region", answer_readiness=E.SCOPED_ANSWER_ONLY,
                             subject_context=_subj(scope),
                             observations={"gene": tx["gene"], "feature": feature})
    return {
        "rsid": rsid, "chrom": chrom, "pos": pos,
        "gene": tx["gene"], "transcript_id": tx["transcript_id"], "strand": tx["strand"],
        "feature": feature, "distance_to_tss": dist_tss,
        "note": "Region grounding from the MANE Select coding transcript model (local). 'feature': "
                "coding_exon = in the CDS (a protein-coding position); untranslated_exon = exonic UTR; "
                "intron = within the gene but non-exonic. Decision-support context, not a clinical call.",
        "evidence_envelope": env,
    }


def _grounding_regulatory(params: dict, context: Context) -> dict:
    """Ground a locus against the ENCODE cCRE registry: does it sit in a candidate cis-regulatory element
    (promoter-/enhancer-like, CTCF, chromatin-accessible)? Complements grounding.region — which only sees
    MANE coding transcripts and calls non-coding variants 'intron'/'intergenic'. Local-only."""
    scope = _scope(context)
    chrom, pos, rsid = _resolve_locus(context, params)
    if not chrom or pos is None:
        return {"evidence_envelope": E.not_assessed(
            operation="grounding.regulatory",
            reason="provide an rsID (on the subject's genome) or explicit chrom + pos",
            subject_context=_subj(scope))}

    re_ = RegulatoryElements.open()
    if re_ is None:
        return {"rsid": rsid, "chrom": chrom, "pos": pos, "evidence_envelope": E.not_measured(
            operation="grounding.regulatory",
            what="ENCODE cCRE registry (run: indaga install encode-ccre)",
            subject_context=_subj(scope))}

    elements = re_.at(chrom, pos)
    re_.close()
    if not elements:
        return {"rsid": rsid, "chrom": chrom, "pos": pos, "elements": [], "n_elements": 0,
                "note": "Not within any ENCODE candidate cis-regulatory element (in the registry's "
                        "consulted scope) — no registered regulatory annotation here.",
                "evidence_envelope": E.empty_consulted_scope(
                    operation="grounding.regulatory", subject_context=_subj(scope))}

    env = E.evidence_present(operation="grounding.regulatory", answer_readiness=E.SCOPED_ANSWER_ONLY,
                             subject_context=_subj(scope),
                             observations={"chrom": chrom, "pos": pos, "ccre": elements[0]["ccre_class"]})
    return {
        "rsid": rsid, "chrom": chrom, "pos": pos, "n_elements": len(elements), "elements": elements,
        "note": "Overlapping ENCODE candidate cis-regulatory element(s). A non-coding variant here is "
                "plausibly regulatory (promoter/enhancer/insulator); a candidate element is biochemical "
                "evidence of regulatory potential, NOT proof this variant alters function. Pair with "
                "splice.assess / expression context. Decision-support, n=1.",
        "evidence_envelope": env,
    }


def _gene_from_params(context: Context, params: dict) -> tuple[str | None, dict | None]:
    """Resolve a gene symbol from an explicit ``gene``, or from a locus (rsid / chrom+pos) via the
    MANE model. Returns (gene_or_None, locus_info_or_None)."""
    gene = (params.get("gene") or "").strip() or None
    if gene:
        return _canon_gene(gene), None
    chrom, pos, rsid = _resolve_locus(context, params)
    if not chrom or pos is None:
        return None, None
    gm = GeneModel.open(auto_install=False)  # read-only: never trigger a download from grounding
    tx = gm.transcript_at(chrom, pos) if gm is not None else None
    if gm is not None:
        gm.close()
    if tx is None:
        return None, {"rsid": rsid, "chrom": chrom, "pos": pos}
    return _canon_gene(tx["gene"]), {"rsid": rsid, "chrom": chrom, "pos": pos}


def _grounding_pathways(params: dict, context: Context) -> dict:
    """Pathway memberships for a gene (or a locus resolved to its gene) from the Reactome gene sets.
    Local-only — the offline equivalent of Genomi's live Reactome lookup, with no locus egress."""
    scope = _scope(context)
    gene, locus = _gene_from_params(context, params)
    if not gene:
        return {"evidence_envelope": E.not_assessed(
            operation="grounding.pathways",
            reason="provide a `gene` symbol, or an rsID/chrom+pos that resolves to a MANE gene",
            subject_context=_subj(scope))}

    gs = GeneSets.open()
    if gs is None:
        return {"gene": gene, "locus": locus, "evidence_envelope": E.not_measured(
            operation="grounding.pathways",
            what="Reactome pathway gene sets (run: indaga install reactome-pathways)",
            subject_context=_subj(scope))}

    sets = gs.pathways_for_gene(gene)
    if not sets:
        return {"gene": gene, "locus": locus, "pathways": [], "n_pathways": 0,
                "note": f"{gene} is not present in any Reactome pathway gene set (the consulted scope "
                        "was complete; this is an absence within Reactome, not 'no function').",
                "evidence_envelope": E.empty_consulted_scope(
                    operation="grounding.pathways", subject_context=_subj(scope))}

    env = E.evidence_present(operation="grounding.pathways", answer_readiness=E.SCOPED_ANSWER_ONLY,
                             subject_context=_subj(scope),
                             observations={"gene": gene, "n_pathways": len(sets)})
    return {
        "gene": gene, "locus": locus, "n_pathways": len(sets), "pathways": sets,
        "note": "Reactome pathway memberships (local GMT). Pathway membership is biological context, "
                "not pathogenicity, and breadth varies — a gene in a top-level set like 'Metabolism' "
                "is not specifically implicated. Decision-support, n=1.",
        "evidence_envelope": env,
    }


def _grounding_expression(params: dict, context: Context) -> dict:
    """Top tissues for a gene (or a locus resolved to its gene) from the HPA consensus tissue RNA.
    Local-only — the offline equivalent of Genomi's live HPA lookup, with no locus egress."""
    scope = _scope(context)
    gene, locus = _gene_from_params(context, params)
    if not gene:
        return {"evidence_envelope": E.not_assessed(
            operation="grounding.expression",
            reason="provide a `gene` symbol, or an rsID/chrom+pos that resolves to a MANE gene",
            subject_context=_subj(scope))}

    limit = max(1, min(int(params.get("limit") or 10), 51))
    te = TissueExpression.open()
    if te is None:
        return {"gene": gene, "locus": locus, "evidence_envelope": E.not_measured(
            operation="grounding.expression",
            what="HPA consensus tissue RNA (run: indaga install hpa-tissue-rna)",
            subject_context=_subj(scope))}

    tissues = te.top_tissues(gene, limit=limit)
    te.close()
    if not tissues:
        return {"gene": gene, "locus": locus, "top_tissues": [], "n_tissues": 0,
                "note": f"{gene} is not in the HPA consensus tissue table (an absence within HPA, not "
                        "'not expressed').",
                "evidence_envelope": E.empty_consulted_scope(
                    operation="grounding.expression", subject_context=_subj(scope))}

    env = E.evidence_present(operation="grounding.expression", answer_readiness=E.SCOPED_ANSWER_ONLY,
                             subject_context=_subj(scope),
                             observations={"gene": gene, "top_tissue": tissues[0]["tissue"]})
    return {
        "gene": gene, "locus": locus, "unit": "nTPM", "n_tissues": len(tissues), "top_tissues": tissues,
        "note": "Top tissues by HPA consensus RNA (nTPM), highest first. Bulk-tissue RNA is biological "
                "context — not cell-resolution and not protein; broad low-level expression is common, so "
                "presence in a tissue is not specificity. Decision-support, n=1.",
        "evidence_envelope": env,
    }


def _section(result: dict, *, fields: tuple[str, ...]) -> dict:
    """Distil a sub-handler result into a composite section: its honesty state + the named fields it
    carried. A missing library surfaces here as ``state='not_measured'`` — never a false empty."""
    state = (result.get("evidence_envelope") or {}).get("finding_state")
    out: dict = {"state": state}
    for f in fields:
        if f in result:
            out[f] = result[f]
    return out


def _grounding_gene(params: dict, context: Context) -> dict:
    """One-call composite grounding for a gene (or a locus → its gene): region feature (when a locus is
    given) + Reactome pathways + HPA tissue expression. The single convenience entry Genomi lacks — and
    fully local. Each section keeps its own evidence state, so a missing library degrades that section
    only, never the whole answer."""
    scope = _scope(context)
    chrom, pos, rsid = _resolve_locus(context, params)
    has_locus = bool(chrom and pos is not None)
    gene = (params.get("gene") or "").strip() or None

    region = _grounding_region(params, context) if has_locus else None
    regulatory = _grounding_regulatory(params, context) if has_locus else None
    if region is not None and not gene:
        gene = region.get("gene")  # resolve the gene from the locus
    gene = _canon_gene(gene)  # entity-canon: alias/prev/Entrez/Ensembl → approved HGNC symbol
    if not gene:
        return {"evidence_envelope": E.not_assessed(
            operation="grounding.gene",
            reason="provide a `gene` symbol, or an rsID/chrom+pos that resolves to a MANE gene",
            subject_context=_subj(scope))}

    p_limit = max(1, min(int(params.get("pathway_limit") or 15), 100))
    t_limit = max(1, min(int(params.get("tissue_limit") or 8), 51))
    pathways = _grounding_pathways({"gene": gene}, context)
    expression = _grounding_expression({"gene": gene, "limit": t_limit}, context)

    # cap the listed pathways (Reactome order is not relevance-ranked) but report the true total
    pw_section = _section(pathways, fields=("n_pathways", "pathways"))
    if isinstance(pw_section.get("pathways"), list) and len(pw_section["pathways"]) > p_limit:
        pw_section["pathways"] = pw_section["pathways"][:p_limit]
        pw_section["truncated_to"] = p_limit

    env = E.evidence_present(operation="grounding.gene", answer_readiness=E.SCOPED_ANSWER_ONLY,
                             subject_context=_subj(scope), observations={"gene": gene})
    return {
        "gene": gene,
        "locus": {"rsid": rsid, "chrom": chrom, "pos": pos} if has_locus else None,
        "region": _section(region, fields=("feature", "transcript_id", "strand", "distance_to_tss"))
                  if region is not None else None,
        "regulatory": _section(regulatory, fields=("n_elements", "elements"))
                      if regulatory is not None else None,
        "pathways": pw_section,
        "expression": _section(expression, fields=("unit", "n_tissues", "top_tissues")),
        "note": "Composite grounding (region + regulatory + Reactome pathways + HPA tissue RNA) for one "
                "gene. Each "
                "section carries its own state — a missing library shows as not_measured there, not a "
                "false empty. Pathway/tissue lists are capped (see truncated_to / n_pathways). Biological "
                "context, not a clinical verdict; n=1.",
        "evidence_envelope": env,
    }


register(Operation("grounding.gene", _grounding_gene, capability=_CAP, skill=_SKILL,
    description="One-call composite grounding for a gene: region feature + regulatory element (if a locus "
                "is given) + Reactome pathway memberships + HPA tissue expression, each with its own "
                "evidence state. Accepts a "
                "`gene` symbol, or an rsID / chrom+pos that resolves to its MANE gene. Local-only — no "
                "external lookup, no locus-of-interest egress.",
    input_schema={"type": "object", "properties": {
        "gene": {"type": "string"}, "rsid": {"type": "string"}, "query": {"type": "string"},
        "chrom": {"type": "string"}, "pos": {"type": "integer"},
        "pathway_limit": {"type": "integer", "minimum": 1, "maximum": 100},
        "tissue_limit": {"type": "integer", "minimum": 1, "maximum": 51}}},
    produces=("evidence_envelope",), omic_scope="genomic", discovery_role="entry_tool"))


_GD_MINRANK = {
    "definitive": 6, "strong": 5, "moderate": 4, "limited": 3,
    "supported": 3, "all": None, "any": None,
}


def _grounding_gene_disease(params: dict, context: Context) -> dict:
    """Graded gene→disease associations for a gene from the local GenCC + ClinGen validity backbone — the
    industry-standard, citable replacement for a hand-curated panel. Local-only, no egress."""
    scope = _scope(context)
    gene, locus = _gene_from_params(context, params)
    if not gene:
        return {"evidence_envelope": E.not_assessed(
            operation="grounding.gene_disease",
            reason="provide a `gene` symbol, or an rsID/chrom+pos that resolves to a MANE gene",
            subject_context=_subj(scope))}

    # default: show Limited+ (drop No-Known/Disputed/Refuted unless the caller asks for 'all')
    raw = str(params.get("min_classification") or "limited").strip().lower()
    min_rank = _GD_MINRANK.get(raw, 3)
    limit = max(1, min(int(params.get("limit") or 30), 100))
    gd = GeneDisease.open()
    if gd is None:
        return {"gene": gene, "locus": locus, "evidence_envelope": E.not_measured(
            operation="grounding.gene_disease",
            what="gene-disease validity (run: indaga install gene-disease-validity)",
            subject_context=_subj(scope))}

    diseases = gd.for_gene(gene, min_rank=min_rank, limit=limit)
    gd.close()
    if not diseases:
        return {"gene": gene, "locus": locus, "diseases": [], "n_diseases": 0,
                "note": f"{gene} has no gene-disease validity assertion at this threshold (absence within "
                        "GenCC/ClinGen, not 'no relationship'). Try min_classification='all'.",
                "evidence_envelope": E.empty_consulted_scope(
                    operation="grounding.gene_disease", subject_context=_subj(scope))}

    top = diseases[0]
    env = E.evidence_present(operation="grounding.gene_disease", answer_readiness=E.SCOPED_ANSWER_ONLY,
                             subject_context=_subj(scope),
                             observations={"gene": gene, "top_disease": top["disease"],
                                           "top_validity": top["classification"]})
    return {
        "gene": gene, "locus": locus, "n_diseases": len(diseases), "diseases": diseases,
        "note": "Gene-disease validity from GenCC (aggregates ClinGen/Orphanet/PanelApp/…) + ClinGen GCEP, "
                "best classification per disease, strongest first (Definitive→Limited). Validity grades the "
                "GENE-DISEASE relationship, not this subject's variant — a Definitive gene still needs a "
                "pathogenic variant to matter. Decision-support, n=1.",
        "evidence_envelope": env,
    }


def _grounding_diagnostic_panels(params: dict, context: Context) -> dict:
    """Which diagnostic-grade (green) Genomics England PanelApp panels a gene appears in — the best-in-class
    disease-specific panel view (complements ACMG SF's actionable list + GenCC/ClinGen validity). Local."""
    scope = _scope(context)
    gene, locus = _gene_from_params(context, params)
    if not gene:
        return {"evidence_envelope": E.not_assessed(
            operation="grounding.diagnostic_panels",
            reason="provide a `gene` symbol, or an rsID/chrom+pos that resolves to a MANE gene",
            subject_context=_subj(scope))}

    dp = DiagnosticPanels.open()
    if dp is None:
        return {"gene": gene, "locus": locus, "evidence_envelope": E.not_measured(
            operation="grounding.diagnostic_panels",
            what="PanelApp diagnostic panels (run: indaga install panelapp-green)",
            subject_context=_subj(scope))}

    panels = dp.panels_for_gene(gene)
    dp.close()
    if not panels:
        return {"gene": gene, "locus": locus, "panels": [], "n_panels": 0,
                "note": f"{gene} is not a green (diagnostic-grade) gene in the installed PanelApp panels "
                        "(absence within the curated set, not 'no disease role').",
                "evidence_envelope": E.empty_consulted_scope(
                    operation="grounding.diagnostic_panels", subject_context=_subj(scope))}

    env = E.evidence_present(operation="grounding.diagnostic_panels", answer_readiness=E.SCOPED_ANSWER_ONLY,
                             subject_context=_subj(scope),
                             observations={"gene": gene, "n_panels": len(panels)})
    return {
        "gene": gene, "locus": locus, "n_panels": len(panels), "panels": panels,
        "note": "Genomics England PanelApp panels where this gene is GREEN (diagnostic-grade). 'Green' = "
                "enough evidence to use diagnostically for that disorder — gene-level, not this subject's "
                "variant. Source licence is non-commercial. Decision-support, n=1.",
        "evidence_envelope": env,
    }


def _grounding_celltype(params: dict, context: Context) -> dict:
    """Top cell types for a gene (or a locus resolved to its gene) from the HPA single-cell RNA — the
    cell-type-resolution companion to grounding.expression. Local-only, no locus egress."""
    scope = _scope(context)
    gene, locus = _gene_from_params(context, params)
    if not gene:
        return {"evidence_envelope": E.not_assessed(
            operation="grounding.celltype",
            reason="provide a `gene` symbol, or an rsID/chrom+pos that resolves to a MANE gene",
            subject_context=_subj(scope))}

    limit = max(1, min(int(params.get("limit") or 10), 50))
    ce = CellTypeExpression.open()
    if ce is None:
        return {"gene": gene, "locus": locus, "evidence_envelope": E.not_measured(
            operation="grounding.celltype",
            what="HPA single-cell-type RNA (run: indaga install hpa-single-cell)",
            subject_context=_subj(scope))}

    cells = ce.top_cell_types(gene, limit=limit)
    ce.close()
    if not cells:
        return {"gene": gene, "locus": locus, "top_cell_types": [], "n_cell_types": 0,
                "note": f"{gene} is not in the HPA single-cell table (an absence within HPA, not "
                        "'not expressed').",
                "evidence_envelope": E.empty_consulted_scope(
                    operation="grounding.celltype", subject_context=_subj(scope))}

    env = E.evidence_present(operation="grounding.celltype", answer_readiness=E.SCOPED_ANSWER_ONLY,
                             subject_context=_subj(scope),
                             observations={"gene": gene, "top_cell_type": cells[0]["cell_type"]})
    return {
        "gene": gene, "locus": locus, "unit": "nCPM", "n_cell_types": len(cells), "top_cell_types": cells,
        "note": "Top cell types by HPA single-cell RNA (nCPM), highest first — finer-grained than the "
                "bulk-tissue view in grounding.expression. Context, not specificity or protein; n=1.",
        "evidence_envelope": env,
    }


_GO_ASPECT = {
    "p": "P", "process": "P", "biological_process": "P", "bp": "P",
    "f": "F", "function": "F", "molecular_function": "F", "mf": "F",
    "c": "C", "component": "C", "cellular_component": "C", "cc": "C",
}


def _grounding_go(params: dict, context: Context) -> dict:
    """GO terms (biological-process / molecular-function / cellular-component) for a gene, from the local
    Gene Ontology. The open process/function vocabulary slice of grounding. Local-only, no locus egress."""
    scope = _scope(context)
    gene, locus = _gene_from_params(context, params)
    if not gene:
        return {"evidence_envelope": E.not_assessed(
            operation="grounding.go",
            reason="provide a `gene` symbol, or an rsID/chrom+pos that resolves to a MANE gene",
            subject_context=_subj(scope))}

    aspect = _GO_ASPECT.get(str(params.get("aspect") or "").strip().lower()) or None
    limit = max(1, min(int(params.get("limit") or 30), 100))
    go = GoTerms.open()
    if go is None:
        return {"gene": gene, "locus": locus, "evidence_envelope": E.not_measured(
            operation="grounding.go",
            what="Gene Ontology (run: indaga install gene-ontology)",
            subject_context=_subj(scope))}

    terms = go.terms_for_gene(gene, aspect=aspect, limit=limit)
    go.close()
    if not terms:
        return {"gene": gene, "locus": locus, "go_terms": [], "n_terms": 0, "aspect": aspect,
                "note": f"{gene} has no GO annotation in the consulted scope"
                        + (f" for aspect {aspect}" if aspect else "") + " (absence within GO, not 'no function').",
                "evidence_envelope": E.empty_consulted_scope(
                    operation="grounding.go", subject_context=_subj(scope))}

    counts = {"P": 0, "F": 0, "C": 0}
    for t in terms:
        counts[t["aspect"]] = counts.get(t["aspect"], 0) + 1
    env = E.evidence_present(operation="grounding.go", answer_readiness=E.SCOPED_ANSWER_ONLY,
                             subject_context=_subj(scope), observations={"gene": gene, "n_terms": len(terms)})
    return {
        "gene": gene, "locus": locus, "aspect": aspect, "n_terms": len(terms),
        "by_aspect_counts": {"biological_process": counts["P"], "molecular_function": counts["F"],
                             "cellular_component": counts["C"]},
        "go_terms": terms,
        "note": "Gene Ontology terms (local GOA + go-basic), generic root/binding/location terms suppressed. "
                "GO annotates the GENE's roles (process/function/component) — biological context, not a "
                "weight on this variant. Decision-support, n=1.",
        "evidence_envelope": env,
    }


register(Operation("grounding.go", _grounding_go, capability=_CAP, skill=_SKILL,
    description="GO terms for a gene from the local Gene Ontology: biological-process / molecular-function "
                "/ cellular-component. Accepts a `gene` symbol, or an rsID / chrom+pos that resolves to its "
                "MANE gene; optional `aspect` (process/function/component) + `limit`. Local-only.",
    input_schema={"type": "object", "properties": {
        "gene": {"type": "string"}, "rsid": {"type": "string"}, "query": {"type": "string"},
        "chrom": {"type": "string"}, "pos": {"type": "integer"},
        "aspect": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}},
    produces=("evidence_envelope",), omic_scope="genomic", discovery_role="focused_tool"))


register(Operation("grounding.diagnostic_panels", _grounding_diagnostic_panels, capability=_CAP, skill=_SKILL,
    description="Which diagnostic-grade (green) Genomics England PanelApp panels a gene appears in — the "
                "disease-specific diagnostic-panel view. Accepts a `gene` symbol or an rsID/chrom+pos. "
                "Local-only — no egress. (PanelApp data is non-commercial licence.)",
    input_schema={"type": "object", "properties": {
        "gene": {"type": "string"}, "rsid": {"type": "string"}, "query": {"type": "string"},
        "chrom": {"type": "string"}, "pos": {"type": "integer"}}},
    produces=("evidence_envelope",), omic_scope="genomic", discovery_role="focused_tool"))


register(Operation("grounding.gene_disease", _grounding_gene_disease, capability=_CAP, skill=_SKILL,
    description="Graded gene→disease associations from the local GenCC + ClinGen validity backbone "
                "(Definitive→Limited + mode of inheritance) — the industry-standard, citable replacement for "
                "a hand-curated panel. Accepts a `gene` symbol or an rsID/chrom+pos; optional "
                "`min_classification` (definitive/strong/moderate/limited/all). Local-only — no egress.",
    input_schema={"type": "object", "properties": {
        "gene": {"type": "string"}, "rsid": {"type": "string"}, "query": {"type": "string"},
        "chrom": {"type": "string"}, "pos": {"type": "integer"},
        "min_classification": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}},
    produces=("evidence_envelope",), omic_scope="genomic", discovery_role="focused_tool"))


register(Operation("grounding.celltype", _grounding_celltype, capability=_CAP, skill=_SKILL,
    description="Top cell types for a gene by HPA single-cell RNA (nCPM) — single-cell resolution beyond "
                "the bulk tissues in grounding.expression. Accepts a `gene` symbol, or an rsID / chrom+pos "
                "that resolves to its MANE gene; optional `limit`. Local-only — no external lookup.",
    input_schema={"type": "object", "properties": {
        "gene": {"type": "string"}, "rsid": {"type": "string"}, "query": {"type": "string"},
        "chrom": {"type": "string"}, "pos": {"type": "integer"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50}}},
    produces=("evidence_envelope",), omic_scope="genomic", discovery_role="focused_tool"))


register(Operation("grounding.expression", _grounding_expression, capability=_CAP, skill=_SKILL,
    description="Top tissues for a gene by HPA consensus RNA (nTPM). Accepts a `gene` symbol, or an "
                "rsID / chrom+pos that resolves to its MANE gene; optional `limit` (default 10). "
                "Local-only — no external lookup, no locus-of-interest egress.",
    input_schema={"type": "object", "properties": {
        "gene": {"type": "string"}, "rsid": {"type": "string"}, "query": {"type": "string"},
        "chrom": {"type": "string"}, "pos": {"type": "integer"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 51}}},
    produces=("evidence_envelope",), omic_scope="genomic", discovery_role="focused_tool"))


register(Operation("grounding.pathways", _grounding_pathways, capability=_CAP, skill=_SKILL,
    description="Pathway memberships for a gene from the local Reactome gene sets. Accepts a `gene` "
                "symbol, or an rsID / chrom+pos that resolves to its MANE gene. Local-only — no "
                "external lookup, no locus-of-interest egress.",
    input_schema={"type": "object", "properties": {
        "gene": {"type": "string"}, "rsid": {"type": "string"}, "query": {"type": "string"},
        "chrom": {"type": "string"}, "pos": {"type": "integer"}}},
    produces=("evidence_envelope",), omic_scope="genomic", discovery_role="focused_tool"))


register(Operation("grounding.region", _grounding_region, capability=_CAP, skill=_SKILL,
    description="Ground a locus in the MANE gene model: which gene it falls in, exon vs intron, coding "
                "(CDS) vs untranslated, strand, and distance to the TSS. Accepts an rsID (resolved on the "
                "subject's genome) or explicit chrom+pos. Local-only — no external lookup.",
    input_schema={"type": "object", "properties": {
        "rsid": {"type": "string"}, "query": {"type": "string"},
        "chrom": {"type": "string"}, "pos": {"type": "integer"}}},
    produces=("evidence_envelope",), omic_scope="genomic", discovery_role="entry_tool"))


register(Operation("grounding.regulatory", _grounding_regulatory, capability=_CAP, skill=_SKILL,
    description="Ground a locus in the ENCODE cCRE registry: does it overlap a candidate cis-regulatory "
                "element (promoter-/enhancer-like, CTCF, chromatin-accessible)? Fills grounding.region's "
                "non-coding blind spot. Accepts an rsID (resolved on the subject's genome) or chrom+pos. "
                "Local-only — no external lookup.",
    input_schema={"type": "object", "properties": {
        "rsid": {"type": "string"}, "query": {"type": "string"},
        "chrom": {"type": "string"}, "pos": {"type": "integer"}}},
    produces=("evidence_envelope",), omic_scope="genomic", discovery_role="focused_tool"))


# --- shared helper: compact grounding context for other capabilities -------- #
# Reactome top-level umbrella sets are not specific (a gene in 'Metabolism' is not implicated by it);
# prefer deeper pathway names when distilling a one-line context for a finding.
_PW_UMBRELLA = frozenset({
    "Metabolism", "Signal Transduction", "Disease", "Immune System", "Gene expression (Transcription)",
    "Metabolism of proteins", "Developmental Biology", "Cell Cycle", "Hemostasis", "Metabolism of RNA",
    "Transport of small molecules", "Vesicle-mediated transport", "Programmed Cell Death",
    "Metabolism of lipids", "Cellular responses to stimuli", "Adaptive Immune System", "Innate Immune System",
    "Membrane Trafficking", "Post-translational protein modification", "Cellular responses to stress",
})


def gene_context(context: Context, gene: str | None, *, n_pathways: int = 3, n_tissues: int = 3) -> dict | None:
    """Compact, READ-ONLY grounding context for a gene (top specific pathways + top tissues), for other
    capabilities (analyze / synthesis) to attach to a finding. Calls the grounding handlers in-process;
    grounding never auto-installs, so this is download-free. Returns None when nothing grounds (the
    libraries aren't installed, or the gene is absent) — the caller then renders exactly as before."""
    if not gene:
        return None

    def _ok(r):
        return (r.get("evidence_envelope") or {}).get("finding_state") == "evidence_present"

    pw = _grounding_pathways({"gene": gene}, context)
    ex = _grounding_expression({"gene": gene, "limit": n_tissues}, context)
    pathways = [p["name"] for p in (pw.get("pathways") or [])] if _ok(pw) else []
    specific = [p for p in pathways if p not in _PW_UMBRELLA] or pathways
    tissues = [t["tissue"] for t in (ex.get("top_tissues") or [])] if _ok(ex) else []

    # clinical context: top graded gene-disease validity (Strong+) + diagnostic-panel membership
    gd = _grounding_gene_disease({"gene": gene, "min_classification": "strong", "limit": 1}, context)
    disease = None
    if _ok(gd) and gd.get("diseases"):
        d0 = gd["diseases"][0]
        disease = {"name": d0["disease"], "classification": d0["classification"]}
    dp = _grounding_diagnostic_panels({"gene": gene}, context)
    panels = [p["panel"] for p in (dp.get("panels") or [])] if _ok(dp) else []

    out: dict = {}
    if specific:
        out["pathways"] = specific[:n_pathways]
    if tissues:
        out["tissues"] = tissues[:n_tissues]
    if disease:
        out["disease"] = disease
    if panels:
        out["panels"] = panels[:4]
    return out or None
