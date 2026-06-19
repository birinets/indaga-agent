"""Analytical grounding — grounding.region against the MANE coding-transcript model (local)."""

import json
import sqlite3

import pytest

from indaga.capabilities.grounding import (
    _grounding_celltype,
    _grounding_diagnostic_panels,
    _grounding_expression,
    _grounding_gene,
    _grounding_gene_disease,
    _grounding_go,
    _grounding_pathways,
    _grounding_region,
    _grounding_regulatory,
)
from indaga.operations.model import Context
from indaga.store import Surface
from indaga.store.memory import InMemoryStore


@pytest.fixture
def gene_model(tmp_path, monkeypatch):
    # synthetic MANE gene model at INDAGA_HOME/resources/mane/gene_model.sqlite
    monkeypatch.setenv("INDAGA_HOME", str(tmp_path))
    p = tmp_path / "resources" / "mane" / "gene_model.sqlite"
    p.parent.mkdir(parents=True)
    con = sqlite3.connect(str(p))
    con.execute("CREATE TABLE transcripts (transcript_id TEXT, gene TEXT, chrom TEXT, strand TEXT, "
                "tx_start INT, tx_end INT, cds_json TEXT, exon_json TEXT)")
    con.execute("INSERT INTO transcripts VALUES (?,?,?,?,?,?,?,?)",
                ("NM_TEST", "TESTG", "1", "+", 1000, 2000,
                 json.dumps([[1050, 1100], [1900, 1950]]),     # CDS
                 json.dumps([[1000, 1100], [1900, 2000]])))    # exons
    con.commit()
    con.close()
    return tmp_path


def _region(**params):
    ctx = Context(subject_id="demo", store=InMemoryStore(), surface=Surface.APP)
    return _grounding_region(params, ctx)


def test_coding_exon(gene_model):
    r = _region(chrom="1", pos=1075)
    assert r["gene"] == "TESTG" and r["strand"] == "+"
    assert r["feature"] == "coding_exon"
    assert r["distance_to_tss"] == 75


def test_untranslated_exon(gene_model):
    r = _region(chrom="1", pos=1010)  # exonic but outside the CDS → UTR
    assert r["feature"] == "untranslated_exon"


def test_intron(gene_model):
    r = _region(chrom="1", pos=1500)  # within the gene span, non-exonic
    assert r["feature"] == "intron"


def test_intergenic(gene_model):
    r = _region(chrom="1", pos=5000)  # no transcript here
    assert r["feature"] == "intergenic" and r["gene"] is None


def test_requires_a_locus(gene_model):
    r = _region()  # no rsid / chrom / pos
    assert r["evidence_envelope"]["finding_state"] == "not_assessed"


# --- grounding.pathways (Reactome GMT, local) ------------------------------- #

@pytest.fixture
def reactome_gmt(gene_model):
    # synthetic Reactome GMT at INDAGA_HOME/resources/reactome/ReactomePathways.gmt
    # (gene_model already set INDAGA_HOME and built the synthetic MANE model for TESTG)
    import indaga.genome.genesets as gs_mod
    gs_mod._CACHE.clear()  # the loader caches by fingerprint per process — isolate the test
    home = gene_model
    p = home / "resources" / "reactome" / "ReactomePathways.gmt"
    p.parent.mkdir(parents=True)
    p.write_text(
        "Signal transduction\tR-HSA-162582\tTESTG\tBRAF\tKRAS\n"
        "Wnt signaling\tR-HSA-195721\tTESTG\tCTNNB1\n"
        "Apoptosis\tR-HSA-109581\tCASP3\tBAX\n",
        encoding="utf-8",
    )
    return home


def _pathways(**params):
    ctx = Context(subject_id="demo", store=InMemoryStore(), surface=Surface.APP)
    return _grounding_pathways(params, ctx)


def test_pathways_by_gene(reactome_gmt):
    r = _pathways(gene="TESTG")
    assert r["gene"] == "TESTG" and r["n_pathways"] == 2
    names = {p["name"] for p in r["pathways"]}
    assert names == {"Signal transduction", "Wnt signaling"}
    assert r["pathways"][0]["id"].startswith("R-HSA-")
    assert r["evidence_envelope"]["finding_state"] == "evidence_present"


def test_pathways_gene_case_insensitive(reactome_gmt):
    assert _pathways(gene="testg")["n_pathways"] == 2


def test_pathways_via_locus_resolves_gene(reactome_gmt):
    # chrom+pos inside the synthetic TESTG transcript → resolves to gene TESTG, then its pathways
    r = _pathways(chrom="1", pos=1075)
    assert r["gene"] == "TESTG" and r["n_pathways"] == 2
    assert r["locus"]["pos"] == 1075


def test_pathways_gene_absent_is_empty_scope(reactome_gmt):
    r = _pathways(gene="UNSEEN")
    assert r["pathways"] == [] and r["n_pathways"] == 0
    assert r["evidence_envelope"]["finding_state"] == "not_observed_in_consulted_scope"


def test_pathways_requires_a_gene_or_locus(reactome_gmt):
    r = _pathways()  # no gene / rsid / chrom / pos
    assert r["evidence_envelope"]["finding_state"] == "not_assessed"


def test_pathways_library_missing_is_not_measured(gene_model, monkeypatch):
    # gene_model sets INDAGA_HOME but installs NO Reactome GMT → not_measured (never a false empty).
    # Block the auto-install so the test stays fully offline (no reactome.org fetch).
    import indaga.genome.genesets as gs_mod
    import indaga.reference.manager as refmgr
    gs_mod._CACHE.clear()
    monkeypatch.setattr(refmgr, "install", lambda ids: {"ok": False})
    r = _pathways(gene="TESTG")
    assert r["evidence_envelope"]["finding_state"] == "not_measured"


# --- grounding.expression (HPA consensus tissue RNA, local sqlite cache) ----- #

@pytest.fixture
def hpa_tissue(gene_model):
    # synthetic HPA consensus TSV at INDAGA_HOME/resources/hpa/rna_tissue_consensus.tsv; the loader
    # builds its sqlite cache from this (gene_model already set INDAGA_HOME + the TESTG MANE model).
    home = gene_model
    # ensure no stale cache from a prior test under a reused tmp path
    (home / "resources" / "hpa" / "tissue_expression.sqlite").unlink(missing_ok=True)
    p = home / "resources" / "hpa" / "rna_tissue_consensus.tsv"
    p.parent.mkdir(parents=True)
    p.write_text(
        "Gene\tGene name\tTissue\tnTPM\n"
        "ENSG1\tTESTG\tpancreas\t90.0\n"
        "ENSG1\tTESTG\tliver\t12.5\n"
        "ENSG1\tTESTG\tbrain\t3.0\n"
        "ENSG2\tOTHERG\tkidney\t40.0\n",
        encoding="utf-8",
    )
    return home


def _expr(**params):
    ctx = Context(subject_id="demo", store=InMemoryStore(), surface=Surface.APP)
    return _grounding_expression(params, ctx)


def test_expression_by_gene_sorted(hpa_tissue):
    r = _expr(gene="TESTG")
    assert r["gene"] == "TESTG" and r["unit"] == "nTPM" and r["n_tissues"] == 3
    assert [t["tissue"] for t in r["top_tissues"]] == ["pancreas", "liver", "brain"]  # nTPM desc
    assert r["top_tissues"][0]["ntpm"] == 90.0
    assert r["evidence_envelope"]["finding_state"] == "evidence_present"


def test_expression_limit(hpa_tissue):
    r = _expr(gene="TESTG", limit=2)
    assert r["n_tissues"] == 2 and [t["tissue"] for t in r["top_tissues"]] == ["pancreas", "liver"]


def test_expression_case_insensitive(hpa_tissue):
    assert _expr(gene="testg")["n_tissues"] == 3


def test_expression_via_locus_resolves_gene(hpa_tissue):
    r = _expr(chrom="1", pos=1075)  # inside the synthetic TESTG transcript
    assert r["gene"] == "TESTG" and r["top_tissues"][0]["tissue"] == "pancreas"
    assert r["locus"]["pos"] == 1075


def test_expression_gene_absent_is_empty_scope(hpa_tissue):
    r = _expr(gene="UNSEEN")
    assert r["top_tissues"] == [] and r["n_tissues"] == 0
    assert r["evidence_envelope"]["finding_state"] == "not_observed_in_consulted_scope"


def test_expression_requires_a_gene_or_locus(hpa_tissue):
    r = _expr()
    assert r["evidence_envelope"]["finding_state"] == "not_assessed"


def test_expression_library_missing_is_not_measured(gene_model, monkeypatch):
    # INDAGA_HOME set, no HPA TSV installed → not_measured. Block auto-install to stay offline.
    import indaga.reference.manager as refmgr
    monkeypatch.setattr(refmgr, "install", lambda ids: {"ok": False})
    r = _expr(gene="TESTG")
    assert r["evidence_envelope"]["finding_state"] == "not_measured"


# --- grounding.celltype (HPA single-cell RNA, local sqlite cache) ------------ #

@pytest.fixture
def hpa_singlecell(gene_model):
    home = gene_model
    (home / "resources" / "hpa" / "singlecell_expression.sqlite").unlink(missing_ok=True)
    p = home / "resources" / "hpa" / "rna_single_cell_type.tsv"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "Gene\tGene name\tCell type\tnCPM\n"
        "ENSG1\tTESTG\tHepatocytes\t120.0\n"
        "ENSG1\tTESTG\tT-cells\t8.0\n"
        "ENSG1\tTESTG\tEnterocytes\t40.0\n"
        "ENSG2\tOTHERG\tMacrophages\t55.0\n",
        encoding="utf-8",
    )
    return home


def _cell(**params):
    ctx = Context(subject_id="demo", store=InMemoryStore(), surface=Surface.APP)
    return _grounding_celltype(params, ctx)


def test_celltype_by_gene_sorted(hpa_singlecell):
    r = _cell(gene="TESTG")
    assert r["gene"] == "TESTG" and r["unit"] == "nCPM" and r["n_cell_types"] == 3
    assert [c["cell_type"] for c in r["top_cell_types"]] == ["Hepatocytes", "Enterocytes", "T-cells"]
    assert r["evidence_envelope"]["finding_state"] == "evidence_present"


def test_celltype_limit_and_case(hpa_singlecell):
    r = _cell(gene="testg", limit=2)
    assert r["n_cell_types"] == 2 and r["top_cell_types"][0]["cell_type"] == "Hepatocytes"


def test_celltype_via_locus(hpa_singlecell):
    r = _cell(chrom="1", pos=1075)  # inside synthetic TESTG transcript
    assert r["gene"] == "TESTG" and r["top_cell_types"][0]["cell_type"] == "Hepatocytes"


def test_celltype_absent_is_empty_scope(hpa_singlecell):
    r = _cell(gene="UNSEEN")
    assert r["n_cell_types"] == 0
    assert r["evidence_envelope"]["finding_state"] == "not_observed_in_consulted_scope"


def test_celltype_library_missing_is_not_measured(gene_model, monkeypatch):
    import indaga.reference.manager as refmgr
    monkeypatch.setattr(refmgr, "install", lambda ids: {"ok": False})
    r = _cell(gene="TESTG")
    assert r["evidence_envelope"]["finding_state"] == "not_measured"


# --- grounding.regulatory (ENCODE cCRE, local interval sqlite) -------------- #

@pytest.fixture
def encode_ccre(gene_model):
    home = gene_model
    (home / "resources" / "encode" / "ccre.sqlite").unlink(missing_ok=True)
    p = home / "resources" / "encode" / "GRCh38-cCREs.bed"
    p.parent.mkdir(parents=True, exist_ok=True)
    # BED: chrom 0-based-start end acc1 acc2 cCRE-class
    p.write_text(
        "chr1\t1000\t1200\tEH1\tEH1b\tdELS\n"
        "chr1\t2000\t2100\tEH2\tEH2b\tPLS\n"
        "chr7\t5000\t5300\tEH3\tEH3b\tCA-CTCF\n",
        encoding="utf-8",
    )
    return home


def _reg(**params):
    ctx = Context(subject_id="demo", store=InMemoryStore(), surface=Surface.APP)
    return _grounding_regulatory(params, ctx)


def test_regulatory_hit_enhancer(encode_ccre):
    r = _reg(chrom="1", pos=1100)  # inside [1000,1200) dELS
    assert r["n_elements"] == 1
    el = r["elements"][0]
    assert el["ccre_class"] == "dELS" and "enhancer" in el["label"]
    assert r["evidence_envelope"]["finding_state"] == "evidence_present"


def test_regulatory_chr_prefix_and_promoter(encode_ccre):
    r = _reg(chrom="chr1", pos=2050)  # 'chr1' must normalize to '1'; inside the PLS
    assert r["elements"][0]["ccre_class"] == "PLS"


def test_regulatory_no_overlap_is_empty_scope(encode_ccre):
    r = _reg(chrom="1", pos=1500)  # between the two chr1 elements
    assert r["n_elements"] == 0
    assert r["evidence_envelope"]["finding_state"] == "not_observed_in_consulted_scope"


def test_regulatory_requires_a_locus(encode_ccre):
    r = _reg()
    assert r["evidence_envelope"]["finding_state"] == "not_assessed"


def test_regulatory_library_missing_is_not_measured(gene_model, monkeypatch):
    import indaga.reference.manager as refmgr
    monkeypatch.setattr(refmgr, "install", lambda ids: {"ok": False})
    r = _reg(chrom="1", pos=1100)
    assert r["evidence_envelope"]["finding_state"] == "not_measured"


# --- HGNC entity-canon (alias / prev / id → approved symbol) ----------------- #

@pytest.fixture
def hgnc(gene_model):
    import indaga.genome.genesymbols as gsym
    gsym._CACHE.clear()
    home = gene_model
    p = home / "resources" / "hgnc" / "hgnc_complete_set.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "hgnc_id\tsymbol\talias_symbol\tprev_symbol\tentrez_id\tensembl_gene_id\n"
        "HGNC:1\tTESTG\tALIASG\tOLDTESTG\t1234\tENSG1\n",
        encoding="utf-8",
    )
    return home


def test_hgnc_canonicalizes_alias_prev_and_ids(hgnc):
    from indaga.genome.genesymbols import GeneSymbols
    gs = GeneSymbols.open()
    assert gs.canonical("OLDTESTG") == "TESTG"   # previous symbol
    assert gs.canonical("aliasg") == "TESTG"      # alias, case-insensitive
    assert gs.canonical("1234") == "TESTG"        # Entrez id
    assert gs.canonical("ENSG1") == "TESTG"       # Ensembl id
    assert gs.canonical("TESTG") == "TESTG"       # approved → itself
    assert gs.canonical("NOSUCH") == "NOSUCH"     # unknown → unchanged (best-effort)


def test_pathways_resolve_through_old_symbol(hgnc, reactome_gmt):
    # GMT is keyed by the approved symbol TESTG; a query with the OLD symbol must still ground
    r = _pathways(gene="OLDTESTG")
    assert r["gene"] == "TESTG" and r["n_pathways"] == 2
    assert r["evidence_envelope"]["finding_state"] == "evidence_present"


def test_canon_is_identity_when_hgnc_absent(gene_model, monkeypatch):
    # no HGNC installed + install blocked → canonicalisation is a no-op, never breaks the query
    import indaga.genome.genesymbols as gsym
    import indaga.reference.manager as refmgr
    gsym._CACHE.clear()
    monkeypatch.setattr(refmgr, "install", lambda ids: {"ok": False})
    from indaga.capabilities.grounding import _canon_gene
    assert _canon_gene("OLDTESTG") == "OLDTESTG"


# --- grounding.go (Gene Ontology: GAF + OBO, local sqlite) ------------------- #

@pytest.fixture
def gene_ontology(gene_model):
    home = gene_model
    (home / "resources" / "go" / "go_terms.sqlite").unlink(missing_ok=True)
    go = home / "resources" / "go"
    go.mkdir(parents=True, exist_ok=True)
    # OBO: id → name + namespace; one obsolete term must be dropped
    (go / "go-basic.obo").write_text(
        "[Term]\nid: GO:0006096\nname: glycolytic process\nnamespace: biological_process\n\n"
        "[Term]\nid: GO:0004340\nname: glucokinase activity\nnamespace: molecular_function\n\n"
        "[Term]\nid: GO:0005829\nname: cytosol\nnamespace: cellular_component\n\n"  # generic → suppressed
        "[Term]\nid: GO:0099999\nname: obsolete thing\nnamespace: biological_process\nis_obsolete: true\n\n",
        encoding="utf-8",
    )
    # GAF (gzipped): cols 3=symbol, 4=qualifier, 5=GO id, 9=aspect
    import gzip as _gz
    rows = [
        "!gaf-version: 2.2",
        "UniProtKB\tP1\tTESTG\t\tGO:0006096\tPMID:1\tIDA\t\tP\tname\t\tprotein\ttaxon:9606\t20200101\tUniProt",
        "UniProtKB\tP1\tTESTG\t\tGO:0004340\tPMID:2\tIDA\t\tF\tname\t\tprotein\ttaxon:9606\t20200101\tUniProt",
        "UniProtKB\tP1\tTESTG\t\tGO:0005829\tPMID:3\tIDA\t\tC\tname\t\tprotein\ttaxon:9606\t20200101\tUniProt",
        "UniProtKB\tP1\tTESTG\tNOT\tGO:0006096\tPMID:4\tIDA\t\tP\tname\t\tprotein\ttaxon:9606\t20200101\tUniProt",
    ]
    with _gz.open(go / "goa_human.gaf.gz", "wt", encoding="utf-8") as fh:
        fh.write("\n".join(rows) + "\n")
    return home


def _go(**params):
    ctx = Context(subject_id="demo", store=InMemoryStore(), surface=Surface.APP)
    return _grounding_go(params, ctx)


def test_go_by_gene_joins_names_drops_generic_and_not(gene_ontology):
    r = _go(gene="TESTG")
    names = {t["name"] for t in r["go_terms"]}
    assert names == {"glycolytic process", "glucokinase activity"}  # cytosol (generic) dropped
    assert r["by_aspect_counts"]["biological_process"] == 1
    assert r["by_aspect_counts"]["molecular_function"] == 1
    assert r["evidence_envelope"]["finding_state"] == "evidence_present"


def test_go_not_qualifier_excluded(gene_ontology):
    # the NOT-qualified GO:0006096 row must not add a duplicate / negative annotation
    r = _go(gene="TESTG")
    gp = [t for t in r["go_terms"] if t["go_id"] == "GO:0006096"]
    assert len(gp) == 1  # the positive annotation only


def test_go_aspect_filter(gene_ontology):
    r = _go(gene="TESTG", aspect="function")
    assert r["n_terms"] == 1 and r["go_terms"][0]["aspect"] == "F"


def test_go_via_locus(gene_ontology):
    r = _go(chrom="1", pos=1075)  # resolves to TESTG via MANE
    assert r["gene"] == "TESTG" and r["n_terms"] == 2


def test_go_absent_is_empty_scope(gene_ontology):
    r = _go(gene="UNSEEN")
    assert r["n_terms"] == 0
    assert r["evidence_envelope"]["finding_state"] == "not_observed_in_consulted_scope"


def test_go_library_missing_is_not_measured(gene_model, monkeypatch):
    import indaga.reference.manager as refmgr
    monkeypatch.setattr(refmgr, "install", lambda ids: {"ok": False})
    r = _go(gene="TESTG")
    assert r["evidence_envelope"]["finding_state"] == "not_measured"


# --- grounding.gene_disease (GenCC + ClinGen validity, local sqlite) --------- #

@pytest.fixture
def gene_disease(gene_model):
    home = gene_model
    (home / "resources" / "gene_disease" / "gene_disease.sqlite").unlink(missing_ok=True)
    gd = home / "resources" / "gene_disease"
    gd.mkdir(parents=True, exist_ok=True)
    # GenCC TSV — cols incl gene_symbol(4), disease_curie(5), disease_title(6), classification_title(10),
    # moi_title(12), submitter_title(14); pad to 15 columns
    header = ["c0", "c1", "c2", "submission_id", "gene_symbol", "disease_curie", "disease_title",
              "c7", "c8", "c9", "classification_title", "c11", "moi_title", "c13", "submitter_title"]

    def grow(g, dcurie, dtitle, cls, moi, sub):
        c = [""] * 15  # values aligned to the header indices above
        c[4], c[5], c[6], c[10], c[12], c[14] = g, dcurie, dtitle, cls, moi, sub
        return "\t".join(c)
    rows = [
        "\t".join(header),
        grow("TESTG", "MONDO:1", "test cardiomyopathy", "Strong", "Autosomal dominant", "ClinGen"),
        grow("TESTG", "MONDO:1", "test cardiomyopathy", "Moderate", "Autosomal dominant", "PanelApp Australia"),
        grow("TESTG", "MONDO:2", "test weak disease", "Limited", "Autosomal recessive", "Orphanet"),
        grow("TESTG", "MONDO:3", "test disputed disease", "Disputed Evidence", "AD", "ClinGen"),
        grow("OTHERG", "MONDO:9", "other disease", "Definitive", "AR", "ClinGen"),
    ]
    (gd / "gencc-submissions.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    # ClinGen CSV — 6 banner lines then data; data rows have HGNC: in col 1
    clines = [
        '"CLINGEN GENE DISEASE VALIDITY CURATIONS","","","","","","",""',
        '"FILE CREATED: 2026-06-17","","","","","","",""',
        '"WEBPAGE: x","","","","","","",""',
        '"++++","++++","++++","++++","++++","++++","++++"',
        '"GENE SYMBOL","GENE ID (HGNC)","DISEASE LABEL","DISEASE ID (MONDO)","MOI","SOP","CLASSIFICATION"',
        '"++++","++++","++++","++++","++++","++++","++++"',
        '"TESTG","HGNC:1","test cardiomyopathy","MONDO:1","AD","SOP10","Definitive"',
    ]
    (gd / "clingen-gene-validity.csv").write_text("\n".join(clines) + "\n", encoding="utf-8")
    return home


def _gd(**params):
    ctx = Context(subject_id="demo", store=InMemoryStore(), surface=Surface.APP)
    return _grounding_gene_disease(params, ctx)


def test_gene_disease_aggregates_best_validity(gene_disease):
    r = _gd(gene="TESTG")
    # cardiomyopathy appears in GenCC (Strong/Moderate) AND ClinGen (Definitive) → best = Definitive
    cm = next(d for d in r["diseases"] if d["mondo"] == "MONDO:1")
    assert cm["classification"] == "Definitive"
    assert cm["n_sources"] >= 2  # merged ClinGen + GenCC submitters
    assert r["diseases"][0]["classification"] == "Definitive"  # strongest first


def test_gene_disease_default_drops_disputed(gene_disease):
    r = _gd(gene="TESTG")  # default min=limited → the Disputed MONDO:3 is excluded
    assert all(d["mondo"] != "MONDO:3" for d in r["diseases"])
    assert any(d["mondo"] == "MONDO:2" for d in r["diseases"])  # Limited is kept


def test_gene_disease_all_shows_disputed(gene_disease):
    r = _gd(gene="TESTG", min_classification="all")
    assert any(d["mondo"] == "MONDO:3" for d in r["diseases"])


def test_gene_disease_min_definitive(gene_disease):
    r = _gd(gene="TESTG", min_classification="definitive")
    assert {d["mondo"] for d in r["diseases"]} == {"MONDO:1"}


def test_gene_disease_via_locus(gene_disease):
    r = _gd(chrom="1", pos=1075)  # resolves to TESTG
    assert r["gene"] == "TESTG" and r["n_diseases"] >= 1


def test_gene_disease_absent_is_empty_scope(gene_disease):
    r = _gd(gene="UNSEEN")
    assert r["n_diseases"] == 0
    assert r["evidence_envelope"]["finding_state"] == "not_observed_in_consulted_scope"


def test_gene_disease_library_missing_is_not_measured(gene_model, monkeypatch):
    import indaga.reference.manager as refmgr
    monkeypatch.setattr(refmgr, "install", lambda ids: {"ok": False})
    r = _gd(gene="TESTG")
    assert r["evidence_envelope"]["finding_state"] == "not_measured"


# --- grounding.diagnostic_panels (PanelApp green genes, local sqlite) -------- #

@pytest.fixture
def panelapp(gene_model):
    import json as _json
    home = gene_model
    (home / "resources" / "panelapp" / "diagnostic_panels.sqlite").unlink(missing_ok=True)
    pa = home / "resources" / "panelapp"
    pa.mkdir(parents=True, exist_ok=True)
    # panel 49 (HCM): TESTG green, NOISE red(1) → only green is indexed
    (pa / "49.json").write_text(_json.dumps({"id": 49, "name": "Hypertrophic cardiomyopathy",
        "version": "6.2", "genes": [
            {"confidence_level": "3", "gene_data": {"gene_symbol": "TESTG"}, "mode_of_inheritance": "MONOALLELIC"},
            {"confidence_level": "1", "gene_data": {"gene_symbol": "NOISE"}}]}), encoding="utf-8")
    # panel 47 (DCM): TESTG also green here → gene in two panels
    (pa / "47.json").write_text(_json.dumps({"id": 47, "name": "Dilated cardiomyopathy",
        "version": "1.97", "genes": [
            {"confidence_level": "3", "gene_data": {"gene_symbol": "TESTG"}}]}), encoding="utf-8")
    return home


def _dp(**params):
    ctx = Context(subject_id="demo", store=InMemoryStore(), surface=Surface.APP)
    return _grounding_diagnostic_panels(params, ctx)


def test_diagnostic_panels_green_only_and_multi(panelapp):
    r = _dp(gene="TESTG")
    names = {p["panel"] for p in r["panels"]}
    assert names == {"Hypertrophic cardiomyopathy", "Dilated cardiomyopathy"}  # both green panels
    assert r["n_panels"] == 2
    assert r["evidence_envelope"]["finding_state"] == "evidence_present"


def test_diagnostic_panels_red_gene_not_indexed(panelapp):
    r = _dp(gene="NOISE")  # red (confidence 1) → not a green gene → empty scope
    assert r["n_panels"] == 0
    assert r["evidence_envelope"]["finding_state"] == "not_observed_in_consulted_scope"


def test_diagnostic_panels_via_locus(panelapp):
    r = _dp(chrom="1", pos=1075)  # resolves to TESTG
    assert r["gene"] == "TESTG" and r["n_panels"] == 2


def test_diagnostic_panels_library_missing_is_not_measured(gene_model, monkeypatch):
    import indaga.reference.manager as refmgr
    monkeypatch.setattr(refmgr, "install", lambda ids: {"ok": False})
    r = _dp(gene="TESTG")
    assert r["evidence_envelope"]["finding_state"] == "not_measured"


# --- grounding.gene (composite: region + pathways + expression) ------------- #

def _gene(**params):
    ctx = Context(subject_id="demo", store=InMemoryStore(), surface=Surface.APP)
    return _grounding_gene(params, ctx)


def test_gene_composite_by_gene(reactome_gmt, hpa_tissue):
    r = _gene(gene="TESTG")
    assert r["gene"] == "TESTG" and r["locus"] is None and r["region"] is None  # no locus → no region
    assert r["pathways"]["state"] == "evidence_present" and r["pathways"]["n_pathways"] == 2
    assert r["expression"]["state"] == "evidence_present" and r["expression"]["n_tissues"] == 3
    assert r["expression"]["top_tissues"][0]["tissue"] == "pancreas"
    assert r["evidence_envelope"]["finding_state"] == "evidence_present"


def test_gene_composite_via_locus(reactome_gmt, hpa_tissue):
    r = _gene(chrom="1", pos=1075)  # inside synthetic TESTG CDS
    assert r["gene"] == "TESTG" and r["locus"]["pos"] == 1075
    assert r["region"]["state"] == "evidence_present" and r["region"]["feature"] == "coding_exon"
    assert r["pathways"]["n_pathways"] == 2 and r["expression"]["n_tissues"] == 3


def test_gene_composite_includes_regulatory(reactome_gmt, hpa_tissue, encode_ccre):
    # with a locus + the cCRE library present, the composite carries the regulatory section
    r = _gene(chrom="1", pos=1100)  # inside the synthetic dELS [1000,1200)
    assert r["regulatory"]["state"] == "evidence_present"
    assert r["regulatory"]["elements"][0]["ccre_class"] == "dELS"


def test_gene_composite_partial_when_one_library_missing(reactome_gmt, monkeypatch):
    # Reactome present, HPA absent → expression section degrades to not_measured, answer still stands.
    import indaga.reference.manager as refmgr
    monkeypatch.setattr(refmgr, "install", lambda ids: {"ok": False})
    r = _gene(gene="TESTG")
    assert r["evidence_envelope"]["finding_state"] == "evidence_present"
    assert r["pathways"]["state"] == "evidence_present" and r["pathways"]["n_pathways"] == 2
    assert r["expression"]["state"] == "not_measured"


def test_gene_pathway_cap(reactome_gmt, hpa_tissue):
    r = _gene(gene="TESTG", pathway_limit=1)
    assert r["pathways"]["n_pathways"] == 2  # true total preserved
    assert len(r["pathways"]["pathways"]) == 1 and r["pathways"]["truncated_to"] == 1


def test_gene_requires_a_gene_or_locus(reactome_gmt, hpa_tissue):
    r = _gene()
    assert r["evidence_envelope"]["finding_state"] == "not_assessed"
