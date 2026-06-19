"""ACMG Secondary Findings (SF) v3.3 — the recognized "medically actionable, return-of-results" gene list.

This is the *industry-standard* answer to "which incidental P/LP findings should be reported regardless of
indication" — the authoritative replacement for a hand-curated actionability panel. 84 genes across Cancer /
Cardiovascular / Metabolic / Other, each with its actionable disorder + inheritance + the SF version that
added it.

Provenance: ACMG SF v3.3, board-approved Feb 2025, published Jun 2025 — Lee K, Abul-Husn NS, Amendola LM,
et al. *Genet Med* 2025;27(8):101454 (PMID 40568962). v3.3 added ABCD1, CYP27A1, PLN over v3.2 (81). The
gene/category/inheritance table is vendored verbatim from ClinGen's maintained ACMG-SF sheet (the
authoritative machine-readable home; ClinVar's HTML page is stale at v3.2). A small, stable list updated
~yearly with each ACMG SF version — refresh on the next version bump. stdlib only.
"""

from __future__ import annotations

SF_VERSION = "v3.3"
SF_CITATION = "ACMG SF v3.3, Genet Med 2025;27(8):101454 (PMID 40568962)"

# gene -> (phenotype_category, inheritance, sf_version_added, actionable_disorder)
ACMG_SF_V3_3: dict[str, tuple[str, str, str, str]] = {
    "ABCD1": ("Metabolic", "XL", "3.3", "X-linked adrenoleukodystrophy"),
    "ACTA2": ("Cardiovascular", "AD", "1", "Familial thoracic aortic aneurysm"),
    "ACTC1": ("Cardiovascular", "AD", "1", "Hypertrophic cardiomyopathy"),
    "ACVRL1": ("Other", "AD", "3", "Hereditary hemorrhagic telangiectasia"),
    "APC": ("Cancer", "AD", "1", "Familial adenomatous polyposis"),
    "APOB": ("Cardiovascular", "AD", "1", "Familial hypercholesterolemia"),
    "ATP7B": ("Other", "AR", "2", "Wilson disease"),
    "BAG3": ("Cardiovascular", "AD", "3.1", "Dilated cardiomyopathy"),
    "BMPR1A": ("Cancer", "AD", "1", "Juvenile polyposis syndrome"),
    "BRCA1": ("Cancer", "AD", "1", "Hereditary breast and ovarian cancer"),
    "BRCA2": ("Cancer", "AD", "1", "Hereditary breast and ovarian cancer"),
    "BTD": ("Metabolic", "AR", "3", "Biotinidase deficiency"),
    "CACNA1S": ("Other", "AD", "1", "Malignant hyperthermia"),
    "CALM1": ("Cardiovascular", "AD", "3.2", "Long-QT syndrome type 14"),
    "CALM2": ("Cardiovascular", "AD", "3.2", "Long-QT syndrome type 15"),
    "CALM3": ("Cardiovascular", "AD", "3.2", "Long-QT syndrome type 16"),
    "CASQ2": ("Cardiovascular", "AR", "3", "Catecholaminergic polymorphic ventricular tachycardia"),
    "COL3A1": ("Cardiovascular", "AD", "1", "Ehlers-Danlos syndrome, vascular type"),
    "CYP27A1": ("Metabolic", "AR", "3.3", "Cerebrotendinous xanthomatosis"),
    "DES": ("Cardiovascular", "AD", "3.1", "Dilated cardiomyopathy"),
    "DSC2": ("Cardiovascular", "AD", "1", "Arrhythmogenic right ventricular cardiomyopathy"),
    "DSG2": ("Cardiovascular", "AD", "1", "Arrhythmogenic right ventricular cardiomyopathy"),
    "DSP": ("Cardiovascular", "AD", "1", "Arrhythmogenic right ventricular cardiomyopathy"),
    "ENG": ("Other", "AD", "3", "Hereditary hemorrhagic telangiectasia"),
    "FBN1": ("Cardiovascular", "AD", "1", "Marfan syndrome"),
    "FLNC": ("Cardiovascular", "AD", "3", "Dilated cardiomyopathy"),
    "GAA": ("Metabolic", "AR", "3", "Pompe disease"),
    "GLA": ("Cardiovascular/Metabolic", "XL", "1", "Fabry disease"),
    "HFE": ("Other", "AR", "3", "Hereditary hemochromatosis (C282Y homozygotes)"),
    "HNF1A": ("Other", "AD", "3", "Maturity-Onset Diabetes of the Young"),
    "KCNH2": ("Cardiovascular", "AD", "1", "Long-QT syndrome type 2"),
    "KCNQ1": ("Cardiovascular", "AD", "1", "Long-QT syndrome type 1"),
    "LDLR": ("Cardiovascular", "AD", "1", "Familial hypercholesterolemia"),
    "LMNA": ("Cardiovascular", "AD", "1", "Dilated cardiomyopathy"),
    "MAX": ("Cancer", "AD", "3", "Hereditary paraganglioma-pheochromocytoma syndrome"),
    "MEN1": ("Cancer", "AD", "1", "Multiple endocrine neoplasia type 1"),
    "MLH1": ("Cancer", "AD", "1", "Lynch syndrome"),
    "MSH2": ("Cancer", "AD", "1", "Lynch syndrome"),
    "MSH6": ("Cancer", "AD", "1", "Lynch syndrome"),
    "MUTYH": ("Cancer", "AR", "1", "MUTYH-associated polyposis"),
    "MYBPC3": ("Cardiovascular", "AD", "1", "Hypertrophic cardiomyopathy"),
    "MYH11": ("Cardiovascular", "AD", "1", "Familial thoracic aortic aneurysm"),
    "MYH7": ("Cardiovascular", "AD", "1", "Hypertrophic cardiomyopathy"),
    "MYL2": ("Cardiovascular", "AD", "1", "Hypertrophic cardiomyopathy"),
    "MYL3": ("Cardiovascular", "AD", "1", "Hypertrophic cardiomyopathy"),
    "NF2": ("Cancer", "AD", "1", "NF2-related schwannomatosis"),
    "OTC": ("Metabolic", "XL", "2", "Ornithine transcarbamylase deficiency"),
    "PALB2": ("Cancer", "AD", "3", "Hereditary breast cancer"),
    "PCSK9": ("Cardiovascular", "AD", "1", "Familial hypercholesterolemia"),
    "PKP2": ("Cardiovascular", "AD", "1", "Arrhythmogenic right ventricular cardiomyopathy"),
    "PLN": ("Cardiovascular", "AD", "3.3", "Dilated cardiomyopathy"),
    "PMS2": ("Cancer", "AD", "1", "Lynch syndrome"),
    "PRKAG2": ("Cardiovascular/Metabolic", "AD", "1", "Hypertrophic cardiomyopathy"),
    "PTEN": ("Cancer", "AD", "1", "PTEN hamartoma tumor syndrome"),
    "RB1": ("Cancer", "AD", "1", "Retinoblastoma"),
    "RBM20": ("Cardiovascular", "AD", "3.1", "Dilated cardiomyopathy"),
    "RET": ("Cancer", "AD", "1", "Familial medullary thyroid cancer"),
    "RPE65": ("Other", "AR", "3", "RPE65-related retinopathy"),
    "RYR1": ("Other", "AD", "1", "Malignant hyperthermia"),
    "RYR2": ("Cardiovascular", "AD", "1", "Catecholaminergic polymorphic ventricular tachycardia"),
    "SCN5A": ("Cardiovascular", "AD", "1", "Long-QT syndrome type 3"),
    "SDHAF2": ("Cancer", "AD", "1", "Hereditary paraganglioma-pheochromocytoma syndrome"),
    "SDHB": ("Cancer", "AD", "1", "Hereditary paraganglioma-pheochromocytoma syndrome"),
    "SDHC": ("Cancer", "AD", "1", "Hereditary paraganglioma-pheochromocytoma syndrome"),
    "SDHD": ("Cancer", "AD", "1", "Hereditary paraganglioma-pheochromocytoma syndrome"),
    "SMAD3": ("Cardiovascular", "AD", "1", "Loeys-Dietz syndrome"),
    "SMAD4": ("Cancer", "AD", "1", "Juvenile polyposis syndrome"),
    "STK11": ("Cancer", "AD", "1", "Peutz-Jeghers syndrome"),
    "TGFBR1": ("Cardiovascular", "AD", "1", "Loeys-Dietz syndrome"),
    "TGFBR2": ("Cardiovascular", "AD", "1", "Loeys-Dietz syndrome"),
    "TMEM127": ("Cancer", "AD", "3", "Hereditary paraganglioma-pheochromocytoma syndrome"),
    "TMEM43": ("Cardiovascular", "AD", "1", "Arrhythmogenic right ventricular cardiomyopathy"),
    "TNNC1": ("Cardiovascular", "AD", "3.1", "Dilated cardiomyopathy"),
    "TNNI3": ("Cardiovascular", "AD", "1", "Hypertrophic cardiomyopathy"),
    "TNNT2": ("Cardiovascular", "AD", "1", "Dilated cardiomyopathy"),
    "TP53": ("Cancer", "AD", "1", "Li-Fraumeni syndrome"),
    "TPM1": ("Cardiovascular", "AD", "1", "Hypertrophic cardiomyopathy"),
    "TRDN": ("Cardiovascular", "AR", "3", "Catecholaminergic polymorphic ventricular tachycardia"),
    "TSC1": ("Cancer", "AD", "1", "Tuberous sclerosis complex"),
    "TSC2": ("Cancer", "AD", "1", "Tuberous sclerosis complex"),
    "TTN": ("Cardiovascular", "AD", "3", "Dilated cardiomyopathy (truncating variants only)"),
    "TTR": ("Other", "AD", "3.1", "Hereditary transthyretin-related amyloidosis"),
    "VHL": ("Cancer", "AD", "1", "Von Hippel-Lindau syndrome"),
    "WT1": ("Cancer", "AD", "1", "WT1-related Wilms tumor"),
}

SF_GENES = frozenset(ACMG_SF_V3_3)


def is_sf_gene(gene: str | None) -> bool:
    return bool(gene) and gene.strip().upper() in {g.upper() for g in SF_GENES}


def sf_info(gene: str | None) -> dict | None:
    """The ACMG SF record for ``gene`` (category / inheritance / version-added / actionable disorder), or
    None if it is not an SF gene. Note ``TTN`` is SF only for truncating variants; ``HFE`` only for the
    C282Y homozygote — those caveats are in the disorder string."""
    if not gene:
        return None
    for g, (cat, moi, ver, dis) in ACMG_SF_V3_3.items():
        if g.upper() == gene.strip().upper():
            return {"gene": g, "category": cat, "inheritance": moi,
                    "sf_version_added": ver, "disorder": dis, "sf_version": SF_VERSION}
    return None
