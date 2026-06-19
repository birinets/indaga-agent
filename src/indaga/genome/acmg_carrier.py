"""ACMG 2021 carrier-screening panel (Tier 3) — 113 genes for universal/pan-ethnic carrier screening.

The recognized standard for preconception/reproductive carrier screening: 97 autosomal-recessive + 16
X-linked conditions where a heterozygous (or X-linked) pathogenic variant means CARRIER status (usually
unaffected), relevant for reproductive risk. Complements ACMG SF (medically-actionable for the individual)
and PanelApp (diagnostic) — this is the carrier axis.

Provenance: Gregg AR, Aarabi M, Klugman S, et al. "Screening for autosomal recessive and X-linked conditions
during pregnancy and preconception: a practice resource of the ACMG." *Genet Med* 2021;23(10):1793-1806
(PMID 34285390; full gene tables in PMC8488021). No maintained flat file — vendored verbatim from the paper's
Tables 1-6 (97 AR + 16 XL = 113, count-verified). A 2024 ACMG technical standard (Guha 2024, PMID 38814327)
is a lab standard, NOT a new list. Refresh on a future ACMG carrier update. stdlib only.
"""

from __future__ import annotations

CARRIER_VERSION = "ACMG 2021 (Tier 3)"
CARRIER_CITATION = "ACMG carrier screening 2021, Genet Med 2021;23(10):1793 (PMID 34285390)"

# gene -> (inheritance, condition)
ACMG_CARRIER_2021: dict[str, tuple[str, str]] = {
    "ABCA3": ("AR", "Surfactant metabolism dysfunction, pulmonary 3"),
    "ABCC8": ("AR", "Diabetes mellitus, permanent neonatal 3"),
    "ABCD1": ("XL", "Adrenoleukodystrophy (ALD)"),
    "ACADM": ("AR", "Medium-chain acyl-coenzyme A dehydrogenase deficiency"),
    "ACADVL": ("AR", "Very long chain acyl-CoA dehydrogenase deficiency"),
    "ACAT1": ("AR", "α-Methylacetoacetic aciduria"),
    "AFF2": ("XL", "Mental retardation, X-linked, associated with fragile site"),
    "AGA": ("AR", "Aspartylglucosaminuria"),
    "AGXT": ("AR", "Hyperoxaluria, primary type I"),
    "AHI1": ("AR", "Joubert syndrome 3"),
    "AIRE": ("AR", "Autoimmune polyendocrinopathy syndrome type I"),
    "ALDOB": ("AR", "Hereditary fructosuria"),
    "ALPL": ("AR", "Hypophosphatasia, adult"),
    "ANO10": ("AR", "Spinocerebellar ataxia 10"),
    "ARSA": ("AR", "Metachromatic leukodystrophy"),
    "ARX": ("XL", "Developmental and epileptic encephalopathy 1 (DEE1)"),
    "ASL": ("AR", "Argininosuccinate aciduria"),
    "ASPA": ("AR", "Canavan disease"),
    "ATP7B": ("AR", "Wilson disease"),
    "BBS1": ("AR", "Bardet–Biedl syndrome 1"),
    "BBS2": ("AR", "Bardet–Biedl syndrome 2"),
    "BCKDHB": ("AR", "Maple syrup urine disease"),
    "BLM": ("AR", "Bloom syndrome"),
    "BTD": ("AR", "Biotinidase deficiency"),
    "CBS": ("AR", "Homocystinuria, B6 responsive and nonresponsive"),
    "CC2D2A": ("AR", "Joubert syndrome 9"),
    "CCDC88C": ("AR", "Congenital hydrocephalus 1"),
    "CEP290": ("AR", "Joubert syndrome 5"),
    "CFTR": ("AR", "Cystic fibrosis"),
    "CHRNE": ("AR", "Myasthenic syndrome, congenital, 4A, slow-channel"),
    "CLCN1": ("AR", "Congenital myotonia, autosomal recessive form"),
    "CLRN1": ("AR", "Usher syndrome 3a"),
    "CNGB3": ("AR", "Achromatopsia 3"),
    "COL7A1": ("AR", "Recessive dystrophic epidermolysis bullosa"),
    "CPT2": ("AR", "Carnitine palmitoyltransferase II deficiency, infantile"),
    "CYP11A1": ("AR", "Adrenal insufficiency, congenital, with 46,XY sex reversal"),
    "CYP21A2": ("AR", "Congenital adrenal hyperplasia (21-hydroxylase deficiency)"),
    "CYP27A1": ("AR", "Cerebrotendinous xanthomatosis"),
    "CYP27B1": ("AR", "Vitamin D–dependent rickets, type 1"),
    "DHCR7": ("AR", "Smith–Lemli–Opitz syndrome"),
    "DHDDS": ("AR", "Congenital disorder of glycosylation type 1"),
    "DLD": ("AR", "Dihydrolipoamide dehydrogenase deficiency"),
    "DMD": ("XL", "Muscular dystrophy, Duchenne/Becker"),
    "DYNC2H1": ("AR", "Short-rib thoracic dysplasia 3"),
    "ELP1": ("AR", "Familial dysautonomia"),
    "ERCC2": ("AR", "Cerebrooculofacioskeletal syndrome 2"),
    "EVC2": ("AR", "Chondroectodermal dysplasia"),
    "F8": ("XL", "Hemophilia A (HEMA)"),
    "F9": ("XL", "Hemophilia B (HEMB)"),
    "FAH": ("AR", "Tyrosinemia type I"),
    "FANCC": ("AR", "Fanconi anemia, complementation group C"),
    "FKRP": ("AR", "Muscular dystrophy–dystroglycanopathy, type A, 5"),
    "FKTN": ("AR", "Cardiomyopathy, dilated, 1X"),
    "FMO3": ("AR", "Trimethylaminuria"),
    "FMR1": ("XL", "Fragile X syndrome (FXS)"),
    "FXN": ("AR", "Friedreich ataxia"),
    "G6PC": ("AR", "Glycogen storage disease type IA"),
    "GAA": ("AR", "Glycogen storage disease, type II (Pompe disease)"),
    "GALT": ("AR", "Galactosemia"),
    "GBA": ("AR", "Gaucher disease, type I"),
    "GBE1": ("AR", "Glycogen storage disease, type IV"),
    "GJB2": ("AR", "Nonsyndromic hearing loss recessive 1A"),
    "GLA": ("XL", "Fabry disease"),
    "GNPTAB": ("AR", "Mucolipidosis type II alpha/beta"),
    "GRIP1": ("AR", "Fraser syndrome"),
    "HBA1": ("AR", "Alpha-thalassemia"),
    "HBA2": ("AR", "Alpha-thalassemia"),
    "HBB": ("AR", "Sickle cell anemia / β-thalassemia"),
    "HEXA": ("AR", "Tay–Sachs disease"),
    "HPS1": ("AR", "Hermansky–Pudlak syndrome 1"),
    "HPS3": ("AR", "Hermansky–Pudlak syndrome 3"),
    "IDUA": ("AR", "Mucopolysaccharidosis Ih (Hurler syndrome)"),
    "L1CAM": ("XL", "Hydrocephalus, X-linked (aqueductal stenosis)"),
    "LRP2": ("AR", "Donnai–Barrow syndrome"),
    "MCCC2": ("AR", "3-methylcrotonyl-CoA carboxylase 2 deficiency"),
    "MCOLN1": ("AR", "Mucolipidosis type IV"),
    "MCPH1": ("AR", "Primary microcephaly 1, recessive"),
    "MID1": ("XL", "Opitz GBBB syndrome, type I (GBBB1)"),
    "MLC1": ("AR", "Megalencephalic leukoencephalopathy with subcortical cysts"),
    "MMACHC": ("AR", "Methylmalonic aciduria with homocystinuria, cblC"),
    "MMUT": ("AR", "Methylmalonic aciduria (methylmalonyl-CoA mutase deficiency)"),
    "MVK": ("AR", "Hyper-IgD syndrome / mevalonate kinase deficiency"),
    "NAGA": ("AR", "Schindler disease, type 1"),
    "NEB": ("AR", "Nemaline myopathy 2"),
    "NPHS1": ("AR", "Finnish congenital nephrotic syndrome"),
    "NR0B1": ("XL", "Adrenal hypoplasia, congenital (AHC)"),
    "OCA2": ("AR", "Oculocutaneous albinism type II"),
    "OTC": ("XL", "Ornithine transcarbamylase deficiency"),
    "PAH": ("AR", "Phenylketonuria"),
    "PCDH15": ("AR", "Deafness, autosomal recessive 23 / Usher 1F"),
    "PKHD1": ("AR", "Autosomal recessive polycystic kidney disease"),
    "PLP1": ("XL", "Spastic paraplegia 2 / Pelizaeus–Merzbacher"),
    "PMM2": ("AR", "Congenital disorder of glycosylation type Ia"),
    "POLG": ("AR", "Mitochondrial DNA depletion syndrome 4A"),
    "PRF1": ("AR", "Hemophagocytic lymphohistiocytosis, familial, 2"),
    "RARS2": ("AR", "Pontocerebellar hypoplasia type 6"),
    "RNASEH2B": ("AR", "Aicardi–Goutières syndrome 2"),
    "RPGR": ("XL", "Retinitis pigmentosa 3 (RP3)"),
    "RS1": ("XL", "X-linked juvenile retinoschisis (RS1)"),
    "SCO2": ("AR", "Mitochondrial complex IV deficiency, nuclear type 2"),
    "SLC19A3": ("AR", "Biotin-responsive basal ganglia disease"),
    "SLC26A2": ("AR", "Epiphyseal dysplasia, multiple, 4 / diastrophic dysplasia"),
    "SLC26A4": ("AR", "Deafness, autosomal recessive 4 / Pendred syndrome"),
    "SLC37A4": ("AR", "Glycogen storage disease Ib"),
    "SLC6A8": ("XL", "Cerebral creatine deficiency syndrome 1 (CCDS1)"),
    "SMN1": ("AR", "Spinal muscular atrophy"),
    "SMPD1": ("AR", "Niemann–Pick disease, type A"),
    "TF": ("AR", "Atransferrinemia"),
    "TMEM216": ("AR", "Joubert syndrome 2"),
    "TNXB": ("AR", "Ehlers–Danlos-like syndrome (tenascin-X deficiency)"),
    "TYR": ("AR", "Oculocutaneous albinism type 1A/1B"),
    "USH2A": ("AR", "Usher syndrome, type 2A"),
    "XPC": ("AR", "Xeroderma pigmentosum"),
}

CARRIER_GENES = frozenset(ACMG_CARRIER_2021)


def is_carrier_gene(gene: str | None) -> bool:
    return bool(gene) and gene.strip().upper() in {g.upper() for g in CARRIER_GENES}


def carrier_info(gene: str | None) -> dict | None:
    """The ACMG carrier-screening record for ``gene`` (inheritance + condition), or None."""
    if not gene:
        return None
    for g, (moi, cond) in ACMG_CARRIER_2021.items():
        if g.upper() == gene.strip().upper():
            return {"gene": g, "inheritance": moi, "condition": cond, "carrier_version": CARRIER_VERSION}
    return None
