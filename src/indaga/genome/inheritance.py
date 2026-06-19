"""Carrier-vs-at-risk interpretation — inheritance-mode context for P/LP findings.

A single P/LP allele in a RECESSIVE gene is usually **carrier status** (benign for the
person, relevant for reproductive planning), not personal disease risk — whereas one
P/LP allele in a DOMINANT gene can be **at-risk**. Without this, a screen over-alarms
(e.g. an SDHA or ALPL heterozygote looks like a finding when it's a common carrier state).

This is a CURATED map for the priority panels + the recessive/dominant genes that commonly
surface in a carried-P/LP screen. Genes not in the map return ``unknown`` (honest — we do
not assert carrier vs at-risk we can't support). A downloadable GenCC inheritance table is
the Phase-D robust upgrade; this curated map covers the high-value cases today.
"""

from __future__ import annotations

# AD = autosomal dominant · AR = autosomal recessive · XL = X-linked · AD/AR = both reported
GENE_INHERITANCE: dict[str, str] = {
    # ---- Hereditary cancer (priority panel) — mostly dominant ----
    "BRCA1": "AD", "BRCA2": "AD", "PALB2": "AD", "ATM": "AD", "CHEK2": "AD", "TP53": "AD",
    "MLH1": "AD", "MSH2": "AD", "MSH6": "AD", "PMS2": "AD", "EPCAM": "AD",
    "RAD51C": "AD", "RAD51D": "AD", "BARD1": "AD", "BRIP1": "AD",
    "APC": "AD", "STK11": "AD", "CDH1": "AD", "PTEN": "AD", "VHL": "AD",
    "NBN": "AD", "NF1": "AD", "NF2": "AD", "RB1": "AD", "RET": "AD", "MEN1": "AD",
    "MUTYH": "AR",  # MUTYH-associated polyposis is recessive
    # ---- Familial hypercholesterolaemia (priority panel) ----
    "LDLR": "AD", "APOB": "AD", "PCSK9": "AD", "APOE": "AD",
    "LDLRAP1": "AR", "ABCG5": "AR", "ABCG8": "AR",
    # ---- Inherited cardiac (priority panel) — dominant ----
    "MYH7": "AD", "MYBPC3": "AD", "TNNT2": "AD", "TNNI3": "AD", "LMNA": "AD",
    "KCNQ1": "AD", "KCNH2": "AD", "SCN5A": "AD", "RYR2": "AD", "DSP": "AD", "DSG2": "AD", "PKP2": "AD",
    # ---- Thrombophilia (priority panel) ----
    "F5": "AD", "F2": "AD", "PROC": "AD", "PROS1": "AD", "SERPINC1": "AD",
    # ---- Common recessive genes that surface as carrier states ----
    "CFTR": "AR", "HBB": "AR", "HBA1": "AR", "HBA2": "AR", "GAA": "AR", "PAH": "AR", "GALT": "AR",
    "ATP7B": "AR", "HFE": "AR", "GJB2": "AR", "SMN1": "AR", "DHCR7": "AR", "CYP21A2": "AR",
    "SLC22A5": "AR", "ACADM": "AR", "BCKDHA": "AR", "BCKDHB": "AR", "ASPA": "AR", "FANCA": "AR",
    "BLM": "AR", "MEFV": "AR", "ALPL": "AR", "SDHA": "AR", "RASA1": "AD", "GYG1": "AR",
    "DSPP": "AD", "CFH": "AD", "SLC25A13": "AR", "EYS": "AR", "MYO7A": "AR", "PEX1": "AR",
    "USH2A": "AR", "PKHD1": "AR", "CYP4V2": "AR", "ADA2": "AR", "VARS2": "AR", "MESP2": "AR",
    "SGSH": "AR", "GALC": "AR", "IDUA": "AR", "PRF1": "AR", "RAG1": "AR", "DOCK8": "AR",
    "SLC4A11": "AR", "SLC45A2": "AR", "TULP1": "AR", "CDH23": "AR", "PCDH15": "AR", "PDE6A": "AR",
    "ABCA4": "AR", "GBA": "AR", "G6PD": "XL", "DMD": "XL", "F8": "XL", "F9": "XL", "FMR1": "XL",
    "OTC": "XL", "ALPORT_COL4A5": "XL",
}

# carrier_status codes → (label, interpretation)
_INTERP = {
    "at_risk_dominant": "Dominant gene: a single P/LP allele may confer personal risk — clinically relevant.",
    "at_risk_biallelic": "Recessive gene, HOMOZYGOUS (biallelic): may be personally affected — clinically relevant.",
    "carrier": "Recessive gene, heterozygous: CARRIER status (not typically affected) — relevant for family planning, not personal risk.",
    "xlinked": "X-linked: interpret by sex and zygosity (males hemizygous → affected; female carriers variable).",
    "both_forms": "Both dominant and recessive forms reported — interpret in clinical context.",
    "unknown": "Inheritance mode not in the curated map — carrier-vs-risk not asserted; interpret with care.",
}


def carrier_status(gene: str | None, zygosity: str | None) -> dict:
    """Return {code, inheritance, label} classifying a carried P/LP variant as carrier vs at-risk."""
    mode = GENE_INHERITANCE.get((gene or "").upper())
    hom = (zygosity == "hom")
    if mode is None:
        code = "unknown"
    elif mode == "AD":
        code = "at_risk_dominant"
    elif mode == "AR":
        code = "at_risk_biallelic" if hom else "carrier"
    elif mode == "XL":
        code = "xlinked"
    else:  # AD/AR
        code = "both_forms"
    return {"code": code, "inheritance": mode, "label": _INTERP[code]}
