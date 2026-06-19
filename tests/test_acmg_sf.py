"""ACMG SF v3.3 — the vendored 84-gene actionable standard + its wiring into the P/LP screen labels."""

from indaga.genome import acmg_carrier, acmg_sf
from indaga.genome.pl_screen import _panel_annotations, _panel_for_gene


def test_exactly_84_genes_v3_3():
    assert len(acmg_sf.ACMG_SF_V3_3) == 84
    assert acmg_sf.SF_VERSION == "v3.3"
    # the three v3.3 additions over v3.2's 81
    for g in ("ABCD1", "CYP27A1", "PLN"):
        assert g in acmg_sf.ACMG_SF_V3_3 and acmg_sf.ACMG_SF_V3_3[g][2] == "3.3"


def test_is_sf_gene_case_insensitive_and_none():
    assert acmg_sf.is_sf_gene("BRCA1") and acmg_sf.is_sf_gene("brca1")
    assert not acmg_sf.is_sf_gene("MTHFR")   # common nutrigenetic gene, not actionable SF
    assert not acmg_sf.is_sf_gene(None) and not acmg_sf.is_sf_gene("")


def test_sf_info_fields():
    sf = acmg_sf.sf_info("LDLR")
    assert sf["category"] == "Cardiovascular" and sf["inheritance"] == "AD"
    assert "hypercholesterolemia" in sf["disorder"].lower()
    assert acmg_sf.sf_info("MTHFR") is None


def test_disputed_hcm_genes_are_not_in_sf():
    # the 9 genes ClinGen reclassified to Disputed for HCM (JACC 2025) must NOT be on the SF list
    for g in ("ANKRD1", "CALR3", "MYH6", "MYLK2", "MYOM1", "MYOZ2", "MYPN", "TCAP", "VCL"):
        assert not acmg_sf.is_sf_gene(g)


def test_panel_label_prefers_acmg_sf_then_bespoke():
    assert _panel_for_gene("BRCA1") == "ACMG SF v3.3: Cancer"        # authoritative
    assert _panel_for_gene("LDLR") == "ACMG SF v3.3: Cardiovascular"
    assert _panel_for_gene("RNU7-1") == "Interferonopathy"          # bespoke fallback (not in SF)
    assert _panel_for_gene("F5") == "Thrombophilia"                 # bespoke fallback (not in SF)
    assert _panel_for_gene("ESR1") == "—"                           # neither SF nor a bespoke panel
    assert _panel_for_gene(None) == "—"


def test_panel_annotations_struct():
    f = _panel_annotations("RET")
    assert f["acmg_sf"] is True and f["acmg_sf_category"] == "Cancer"
    assert f["acmg_sf_inheritance"] == "AD"
    n = _panel_annotations("MTHFR")
    assert n["acmg_sf"] is False and n["acmg_sf_category"] is None


# --- ACMG 2021 carrier screening (113 genes) -------------------------------- #

def test_carrier_exactly_113_genes_split():
    assert len(acmg_carrier.ACMG_CARRIER_2021) == 113
    moi = [v[0] for v in acmg_carrier.ACMG_CARRIER_2021.values()]
    assert moi.count("AR") == 97 and moi.count("XL") == 16


def test_carrier_is_gene_and_info():
    assert acmg_carrier.is_carrier_gene("CFTR") and acmg_carrier.is_carrier_gene("cftr")
    assert acmg_carrier.is_carrier_gene("FMR1")          # X-linked fragile X
    assert not acmg_carrier.is_carrier_gene("BRCA1")     # actionable SF, not a carrier-screening gene
    info = acmg_carrier.carrier_info("HEXA")
    assert info["inheritance"] == "AR" and "Tay" in info["condition"]
    assert acmg_carrier.carrier_info("MTHFR") is None


def test_panel_annotations_includes_carrier():
    f = _panel_annotations("CFTR")
    assert f["acmg_carrier"] is True and f["acmg_carrier_inheritance"] == "AR"
    assert "ystic fibrosis" in f["acmg_carrier_condition"]
    assert f["acmg_sf"] is False  # CFTR is carrier, not actionable-SF
