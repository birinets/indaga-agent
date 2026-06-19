"""The Indaga reference-data catalog — one ``LibrarySpec`` per source.

Single source of truth for every external reference Indaga uses. Phase-A (v1)
entries are downloadable today; later-phase entries are registered now (so
``indaga.check_libraries`` shows the whole roadmap and reports them as
``not_installed``) and become live as each phase ships. Paths are RELATIVE to
``indaga_home()``; the manager resolves them.

Mirrors ``genomi/runtime/libraries/registry.py``. URLs verified against Genomi's
installed copies (ClinVar NCBI FTP, PGS Catalog EBI FTP).
"""

from __future__ import annotations

from pathlib import Path

from .spec import Freshness, Kind, LibrarySpec, Source, Transform

USER_AGENT = "Indaga installer/0.1 (+https://indaga.health)"


def _p(*parts: str) -> Path:
    return Path(*parts)


# Curated Genomics England PanelApp signed-off / high-value diagnostic panels (id → label) — green
# (diagnostic-grade) genes per disorder. NON-COMMERCIAL: PanelApp's licence is informal; commercial
# redistribution needs Genomics England sign-off. Fine for personal/research use.
_PANELAPP_PANELS: tuple[tuple[int, str], ...] = (
    (772, "Familial hypercholesterolaemia"), (49, "Hypertrophic cardiomyopathy"),
    (47, "Dilated cardiomyopathy"), (134, "Arrhythmogenic RV cardiomyopathy"),
    (842, "Cardiac arrhythmias"), (76, "Long QT syndrome"), (214, "CPVT"),
    (700, "Thoracic aortic aneurysm/dissection"), (245, "Adult solid tumour susceptibility"),
    (635, "Inherited breast & ovarian cancer"), (503, "Lynch syndrome (MMR)"),
    (504, "Inherited polyposis / early-onset CRC"), (516, "Thrombophilia (monogenic)"),
    (502, "Hereditary amyloidosis"),
)
_PANELAPP_BASE = "https://panelapp.genomicsengland.co.uk/api/v1/panels"


_SPECS: tuple[LibrarySpec, ...] = (
    # ===== Phase A (v1) — the chip-faithful core's references ================
    LibrarySpec(
        id="clinvar-grch38",
        title="ClinVar VCF (GRCh38)",
        helps="exact ClinVar significance lookup + P/LP candidate triage against the Active Genome Index",
        kind=Kind.OFFLINE,
        size_class="~190 MB",
        purposes=("chip-core", "everything"),
        phase="A",
        source=Source(urls=("https://ftp.ncbi.nlm.nih.gov/pub/clinvar/vcf_GRCh38/clinvar.vcf.gz",),
                      user_agent=USER_AGENT),
        freshness=Freshness.HTTP_VALIDATORS,
        targets=(_p("resources", "clinvar", "GRCh38", "clinvar.vcf.gz"),),
        required_paths=(_p("resources", "clinvar", "GRCh38", "clinvar.vcf.gz"),),
    ),
    LibrarySpec(
        id="clinvar-grch37",
        title="ClinVar VCF (GRCh37)",
        helps="GRCh37 ClinVar for position fallbacks on build37 inputs (rsID join is build-independent)",
        kind=Kind.OFFLINE,
        size_class="~190 MB",
        purposes=("chip-core",),
        phase="A",
        source=Source(urls=("https://ftp.ncbi.nlm.nih.gov/pub/clinvar/vcf_GRCh37/clinvar.vcf.gz",),
                      user_agent=USER_AGENT),
        freshness=Freshness.HTTP_VALIDATORS,
        targets=(_p("resources", "clinvar", "GRCh37", "clinvar.vcf.gz"),),
        required_paths=(_p("resources", "clinvar", "GRCh37", "clinvar.vcf.gz"),),
    ),
    LibrarySpec(
        id="pgs-catalog-metadata",
        title="PGS Catalog score metadata (CSV)",
        helps="trait labels + publication metadata for polygenic scores, without per-score lookups",
        kind=Kind.OFFLINE,
        size_class="~3 MB",
        purposes=("chip-core", "everything"),
        phase="A",
        source=Source(urls=("https://ftp.ebi.ac.uk/pub/databases/spot/pgs/metadata/pgs_all_metadata_scores.csv",),
                      user_agent=USER_AGENT),
        freshness=Freshness.HTTP_VALIDATORS,
        targets=(_p("resources", "pgs", "pgs_all_metadata_scores.csv"),),
        required_paths=(_p("resources", "pgs", "pgs_all_metadata_scores.csv"),),
    ),
    LibrarySpec(
        id="pgs-weights",
        title="PGS Catalog harmonized scoring files (per score id)",
        helps="per-PGS effect weights (GRCh38) used to compute polygenic scores from the genome",
        kind=Kind.PARAMETERIZED,
        size_class="~1 MB/score",
        purposes=("chip-core", "everything"),
        phase="A",
        source=Source(
            url_template="https://ftp.ebi.ac.uk/pub/databases/spot/pgs/scores/"
                         "{key}/ScoringFiles/Harmonized/{key}_hmPOS_{build}.txt.gz",
            user_agent=USER_AGENT,
        ),
        freshness=Freshness.HTTP_VALIDATORS,
        # per-key target resolved by manager.pgs_weight_path(pgs_id)
        required_paths=(_p("reference", "pgs"),),
    ),
    LibrarySpec(
        id="gnomad",
        title="gnomAD population frequencies (live GraphQL API)",
        helps="population allele frequency for the P/LP rare-variant filter (common false-alarm refutation)",
        kind=Kind.ONLINE,
        size_class="online",
        purposes=("chip-core", "everything"),
        phase="A",
        source=Source(api_base="https://gnomad.broadinstitute.org/api", user_agent=USER_AGENT),
        freshness=Freshness.LIVE,
    ),

    # ===== Phase B — in-silico predictor ensemble (owned libraries) ==========
    LibrarySpec(
        id="alphamissense",
        title="AlphaMissense pathogenicity scores (GRCh38)",
        helps="missense pathogenicity prior for ACMG PP3/BP4 and novel-variant triage",
        kind=Kind.OFFLINE, size_class="~1 GB", purposes=("predictors",), phase="B",
        source=Source(urls=("https://storage.googleapis.com/dm_alphamissense/"
                            "AlphaMissense_hg38.tsv.gz",), user_agent=USER_AGENT),
        targets=(_p("resources", "alphamissense", "AlphaMissense_hg38.tsv.gz"),),
        required_paths=(_p("resources", "alphamissense", "AlphaMissense_hg38.tsv.gz"),),
    ),
    LibrarySpec(
        id="revel", title="REVEL ensemble missense scores", helps="second ensemble missense opinion (concordance with AlphaMissense)",
        kind=Kind.OFFLINE, size_class="~600 MB zip", purposes=("predictors",), phase="B",
        source=Source(urls=("https://rothsj06.dmz.hpc.mssm.edu/revel-v1.3_all_chromosomes.zip",), version="1.3", user_agent=USER_AGENT),
        targets=(_p("resources", "revel", "revel-v1.3_all_chromosomes.zip"),),
        required_paths=(_p("resources", "revel", "revel-v1.3_all_chromosomes.zip"),),
    ),
    LibrarySpec(
        id="cadd", title="CADD scores (exome subset, GRCh38)", helps="deleteriousness score for coding variants",
        kind=Kind.OFFLINE, size_class="~3 GB (exome)", purposes=("predictors",), phase="B",
        source=Source(urls=("https://kircherlab.bihealth.org/download/CADD/v1.7/GRCh38/whole_genome_SNVs.tsv.gz",),
                      user_agent=USER_AGENT),
        required_paths=(_p("resources", "cadd", "cadd_grch38.tsv.gz"),),
    ),
    LibrarySpec(
        id="spliceai", title="SpliceAI (on-the-fly TensorFlow model)",
        helps="splice-altering prediction (ACMG PP3) — runs the model on-device, no 30GB precomputed VCFs",
        kind=Kind.MANUAL, size_class="~1 GB venv (TensorFlow); needs Python 3.11/3.12",
        purposes=("predictors",), phase="B", freshness=Freshness.MANUAL,
        required_paths=(_p("tools", "spliceai", "venv", "bin", "python3"),),
    ),
    LibrarySpec(
        id="gnomad-constraint", title="gnomAD gene constraint (pLI/LOEUF)", helps="LoF intolerance for ACMG PVS1 weighting",
        kind=Kind.OFFLINE, size_class="~30 MB", purposes=("predictors", "acmg"), phase="C",
        source=Source(urls=("https://storage.googleapis.com/gcp-public-data--gnomad/release/4.1/constraint/"
                            "gnomad.v4.1.constraint_metrics.tsv",), user_agent=USER_AGENT),
        targets=(_p("resources", "gnomad", "constraint_metrics.tsv"),),
        required_paths=(_p("resources", "gnomad", "constraint_metrics.tsv"),),
    ),

    # ===== Phase E — gene model + consequence annotation (novel-variant LoF) =
    LibrarySpec(
        id="mane-select", title="MANE Select transcript model (GRCh38 GFF)",
        helps="molecular-consequence calling (PVS1 LoF) on novel variants + coding-exon coordinates",
        kind=Kind.OFFLINE, size_class="~10 MB", purposes=("consequence", "acmg"), phase="E",
        source=Source(urls=("https://ftp.ncbi.nlm.nih.gov/refseq/MANE/MANE_human/release_1.4/"
                            "MANE.GRCh38.v1.4.ensembl_genomic.gff.gz",), version="1.4", user_agent=USER_AGENT),
        targets=(_p("resources", "mane", "MANE.GRCh38.v1.4.ensembl_genomic.gff.gz"),),
        required_paths=(_p("resources", "mane", "MANE.GRCh38.v1.4.ensembl_genomic.gff.gz"),),
    ),
    LibrarySpec(
        id="reactome-pathways", title="Reactome pathway gene sets (GMT, gene symbols)",
        helps="local pathway membership for a gene (analytical grounding) — the offline equivalent of "
              "Genomi's live Reactome lookup, so no gene-of-interest leaves the device",
        kind=Kind.OFFLINE, size_class="~0.3 MB zip (~1 MB gmt)", purposes=("grounding",), phase="E",
        source=Source(urls=("https://reactome.org/download/current/ReactomePathways.gmt.zip",),
                      user_agent=USER_AGENT),
        targets=(_p("resources", "reactome", "ReactomePathways.gmt.zip"),),
        required_paths=(_p("resources", "reactome", "ReactomePathways.gmt.zip"),),
    ),
    LibrarySpec(
        id="hpa-tissue-rna", title="Human Protein Atlas consensus tissue RNA (nTPM)",
        helps="local gene→tissue expression (analytical grounding) — the offline equivalent of Genomi's "
              "live HPA lookup; CC BY 4.0, no login",
        kind=Kind.OFFLINE, size_class="~5 MB zip (~40 MB tsv → cached sqlite)", purposes=("grounding",),
        phase="E",
        source=Source(urls=("https://www.proteinatlas.org/download/tsv/rna_tissue_consensus.tsv.zip",),
                      user_agent=USER_AGENT),
        targets=(_p("resources", "hpa", "rna_tissue_consensus.tsv.zip"),),
        required_paths=(_p("resources", "hpa", "rna_tissue_consensus.tsv.zip"),),
    ),
    LibrarySpec(
        id="hpa-single-cell", title="Human Protein Atlas single-cell-type RNA (nCPM)",
        helps="local gene→cell-type expression (analytical grounding — single-cell breadth beyond bulk "
              "tissue); CC BY 4.0, no login",
        kind=Kind.OFFLINE, size_class="~16 MB zip (~120 MB tsv → cached sqlite)", purposes=("grounding",),
        phase="E",
        source=Source(urls=("https://www.proteinatlas.org/download/tsv/rna_single_cell_type.tsv.zip",),
                      user_agent=USER_AGENT),
        targets=(_p("resources", "hpa", "rna_single_cell_type.tsv.zip"),),
        required_paths=(_p("resources", "hpa", "rna_single_cell_type.tsv.zip"),),
    ),
    LibrarySpec(
        id="encode-ccre", title="ENCODE SCREEN candidate cis-Regulatory Elements (GRCh38, V4)",
        helps="local locus→regulatory element (promoter/enhancer/CTCF) for grounding non-coding variants; "
              "ENCODE open data, no restrictions",
        kind=Kind.OFFLINE, size_class="~129 MB BED (~2.3M elements → cached sqlite)", purposes=("grounding",),
        phase="E",
        source=Source(urls=("https://downloads.wenglab.org/Registry-V4/GRCh38-cCREs.bed",),
                      user_agent=USER_AGENT),
        targets=(_p("resources", "encode", "GRCh38-cCREs.bed"),),
        required_paths=(_p("resources", "encode", "GRCh38-cCREs.bed"),),
    ),
    LibrarySpec(
        id="gene-ontology", title="Gene Ontology — human annotations (GAF) + ontology (OBO)",
        helps="local gene→GO biological-process / molecular-function / cellular-component terms (analytical "
              "grounding — the open slice of MSigDB C5 / KEGG ontology); GO is CC BY 4.0, no login",
        kind=Kind.OFFLINE, size_class="~10 MB GAF + ~32 MB OBO → cached sqlite", purposes=("grounding",),
        phase="E",
        source=Source(urls=("https://ftp.ebi.ac.uk/pub/databases/GO/goa/HUMAN/goa_human.gaf.gz",
                            "https://current.geneontology.org/ontology/go-basic.obo"),
                      user_agent=USER_AGENT),
        targets=(_p("resources", "go", "goa_human.gaf.gz"), _p("resources", "go", "go-basic.obo")),
        required_paths=(_p("resources", "go", "goa_human.gaf.gz"), _p("resources", "go", "go-basic.obo")),
    ),
    LibrarySpec(
        id="gene-disease-validity", title="Gene-disease validity (GenCC + ClinGen)",
        helps="graded gene→disease validity (Definitive→Limited) + mode-of-inheritance — the industry "
              "standard (GenCC aggregates ClinGen/Orphanet/PanelApp/…; ClinGen adds native GCEP curations). "
              "Replaces hand-curated panels with citable, graded gene-disease relationships, downloaded locally",
        kind=Kind.OFFLINE, size_class="~25 MB GenCC TSV + ~1 MB ClinGen CSV → cached sqlite",
        purposes=("grounding",), phase="E",
        source=Source(urls=("https://thegencc.org/download/action/submissions-export-tsv?format=new",
                            "https://search.clinicalgenome.org/kb/gene-validity/download"),
                      user_agent=USER_AGENT),
        targets=(_p("resources", "gene_disease", "gencc-submissions.tsv"),
                 _p("resources", "gene_disease", "clingen-gene-validity.csv")),
        # either file alone is enough to build; existence of the dir-level files proves install
        required_paths=(_p("resources", "gene_disease", "gencc-submissions.tsv"),
                        _p("resources", "gene_disease", "clingen-gene-validity.csv")),
    ),
    LibrarySpec(
        id="panelapp-green", title="Genomics England PanelApp diagnostic panels (green genes)",
        helps="curated, signed-off DIAGNOSTIC gene panels per disorder (green = diagnostic-grade) — the "
              "best-in-class disease-specific panels (cardiomyopathy/arrhythmia/aortopathy, hereditary "
              "cancer, FH, thrombophilia, amyloidosis). NON-COMMERCIAL licence (informal; commercial reuse "
              "needs Genomics England sign-off)",
        kind=Kind.OFFLINE, size_class="~5 MB (14 panel JSONs → cached sqlite)", purposes=("grounding",),
        phase="E",
        source=Source(urls=tuple(f"{_PANELAPP_BASE}/{i}/?format=json" for i, _ in _PANELAPP_PANELS),
                      user_agent=USER_AGENT),
        targets=tuple(_p("resources", "panelapp", f"{i}.json") for i, _ in _PANELAPP_PANELS),
        required_paths=tuple(_p("resources", "panelapp", f"{i}.json") for i, _ in _PANELAPP_PANELS),
    ),
    LibrarySpec(
        id="hgnc-complete", title="HGNC complete gene set (approved symbols + aliases)",
        helps="entity-canon: map alias / previous / Entrez / Ensembl gene identifiers to the approved HGNC "
              "symbol, so grounding lookups are robust to old/alias names; open data",
        kind=Kind.OFFLINE, size_class="~17 MB tsv → cached sqlite", purposes=("grounding",), phase="E",
        source=Source(urls=("https://storage.googleapis.com/public-download-files/hgnc/tsv/tsv/"
                            "hgnc_complete_set.txt",), user_agent=USER_AGENT),
        targets=(_p("resources", "hgnc", "hgnc_complete_set.txt"),),
        required_paths=(_p("resources", "hgnc", "hgnc_complete_set.txt"),),
    ),
    LibrarySpec(
        id="reference-fasta-grch38", title="GRCh38 reference FASTA (UCSC hg38)",
        helps="reference codon sequence for consequence calling (nonsense/missense)",
        kind=Kind.OFFLINE, size_class="~950 MB", purposes=("consequence",), phase="E",
        source=Source(urls=("https://hgdownload.soe.ucsc.edu/goldenPath/hg38/bigZips/hg38.fa.gz",),
                      user_agent=USER_AGENT),
        transform=Transform.GUNZIP_FAIDX,
        targets=(_p("resources", "fasta", "hg38.fa.gz"),),
        required_paths=(_p("resources", "fasta", "hg38.fa.bgz"),),
    ),

    # ===== Phase D — remaining external-pipeline reads brought in-house ======
    LibrarySpec(
        id="pharmcat-pipeline", title="PharmCAT pipeline (jar + preprocessor + positions)",
        helps="star-allele diplotypes + CPIC pharmacogenomics on the imputed genome",
        kind=Kind.OFFLINE, size_class="~28 MB tar (jar+preprocessor; ref FASTA auto-fetched on first run)",
        purposes=("pgx",), phase="D",
        source=Source(urls=("https://github.com/PharmGKB/PharmCAT/releases/download/v3.2.0/"
                            "pharmcat-pipeline-3.2.0.tar.gz",), version="3.2.0", user_agent=USER_AGENT),
        targets=(_p("tools", "pharmcat", "pharmcat-pipeline.tar.gz"),),
        required_paths=(_p("tools", "pharmcat", "pharmcat-pipeline.tar.gz"),),
    ),
    LibrarySpec(
        id="gwas-catalog", title="GWAS Catalog associations (ontology-annotated, zipped TSV)",
        helps="trait/disease associations for the user's variants (position + rsID keyed)",
        kind=Kind.OFFLINE, size_class="~60 MB zip", purposes=("gwas",), phase="D",
        source=Source(urls=("https://ftp.ebi.ac.uk/pub/databases/gwas/releases/latest/"
                            "gwas-catalog-associations_ontology-annotated-full.zip",), user_agent=USER_AGENT),
        targets=(_p("resources", "gwas", "gwas-catalog-associations.zip"),),
        required_paths=(_p("resources", "gwas", "gwas-catalog-associations.zip"),),
    ),
    LibrarySpec(
        id="ancestry-1000g", title="1000G AIM frequency table (GRCh38)",
        helps="continental-ancestry estimate via ancestry-informative-marker likelihood",
        kind=Kind.DERIVED, size_class="~0.5 MB (built from the imputation panel)", purposes=("ancestry",),
        phase="D", freshness=Freshness.MANUAL,
        required_paths=(_p("reference", "ancestry", "aim_freqs.tsv"),),
    ),

    # ===== EXTEND: owned local imputation (Beagle 5.5 + HGDP+1kGP, GRCh38) ===
    # Impute-first is the primary path: raw chip → extend → GRCh38 imputed genome → annotate.
    # Beagle 5.5 = GPL (free incl. commercial), fastest, lowest-memory, easiest to wrap.
    # HGDP+1kGP (gnomAD, ~4,096 genomes, native GRCh38) is the best freely-downloadable panel —
    # more diverse + better rare-variant accuracy than 1000G-phase3, and no liftover-back.
    LibrarySpec(
        id="beagle-jar", title="Beagle 5.5 imputation engine (JAR)",
        helps="local genotype imputation/phasing — extends a chip to millions of variants on-device (no upload)",
        kind=Kind.OFFLINE, size_class="~1 MB", purposes=("imputation",), phase="A",
        source=Source(urls=("https://faculty.washington.edu/browning/beagle/beagle.27Feb25.75f.jar",),
                      user_agent=USER_AGENT),
        targets=(_p("tools", "beagle", "beagle.jar"),),
        required_paths=(_p("tools", "beagle", "beagle.jar"),),
    ),
    LibrarySpec(
        id="bref3-jar", title="Beagle bref3 panel converter (JAR)",
        helps="converts a VCF reference panel to bref3 — ~10x faster imputation + far lower RAM",
        kind=Kind.OFFLINE, size_class="~0.1 MB", purposes=("imputation",), phase="A",
        source=Source(urls=("https://faculty.washington.edu/browning/beagle/bref3.27Feb25.75f.jar",),
                      user_agent=USER_AGENT),
        targets=(_p("tools", "beagle", "bref3.jar"),),
        required_paths=(_p("tools", "beagle", "bref3.jar"),),
    ),
    LibrarySpec(
        id="beagle-maps-grch38", title="Beagle genetic maps (PLINK, GRCh38)",
        helps="recombination maps Beagle needs for phasing/imputation on GRCh38",
        kind=Kind.OFFLINE, size_class="~30 MB", purposes=("imputation",), phase="A",
        source=Source(urls=("https://bochet.gcc.biostat.washington.edu/beagle/genetic_maps/plink.GRCh38.map.zip",),
                      user_agent=USER_AGENT),
        targets=(_p("reference", "beagle_maps", "plink.GRCh38.map.zip"),),
        required_paths=(_p("reference", "beagle_maps", "plink.GRCh38.map.zip"),),
    ),
    LibrarySpec(
        id="impute-panel-1000g-30x", title="1000G 30x GRCh38 phased imputation panel (per-chromosome)",
        helps="the reference haplotypes Beagle imputes against — 3,202 genomes at 30×, NATIVE GRCh38, "
              "pre-phased (NYGC 20220422). A clear upgrade over the older GRCh37 1000G-phase3: "
              "GRCh38-native (no liftover-back) + more samples. (HGDP+1kGP, ~4,096 + more diverse, is a "
              "future upgrade — it has no ready phased release and must be assembled from gnomAD VCFs.)",
        kind=Kind.PARAMETERIZED, size_class="~9 GB (all chr; ~445 MB/chr)", purposes=("imputation",), phase="A",
        source=Source(
            url_template="https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/data_collections/"
                         "1000G_2504_high_coverage/working/20220422_3202_phased_SNV_INDEL_SV/"
                         "1kGP_high_coverage_Illumina.chr{key}.filtered.SNV_INDEL_SV_phased_panel.vcf.gz",
            user_agent=USER_AGENT),
        freshness=Freshness.HTTP_VALIDATORS,
        required_paths=(_p("reference", "impute_panel", "1000g_30x"),),
    ),
    LibrarySpec(
        id="liftover-chains", title="UCSC liftover chains (hg19→hg38)",
        helps="lift a build37 consumer chip to GRCh38 before imputing against a GRCh38 panel",
        kind=Kind.OFFLINE, size_class="~2 MB", purposes=("imputation", "liftover"), phase="A",
        source=Source(urls=("https://hgdownload.soe.ucsc.edu/goldenPath/hg19/liftOver/hg19ToHg38.over.chain.gz",
                            "https://hgdownload.soe.ucsc.edu/goldenPath/hg38/liftOver/hg38ToHg19.over.chain.gz"),
                      user_agent=USER_AGENT),
        targets=(_p("resources", "liftover", "hg19ToHg38.over.chain.gz"),
                 _p("resources", "liftover", "hg38ToHg19.over.chain.gz")),
        required_paths=(_p("resources", "liftover", "hg19ToHg38.over.chain.gz"),
                        _p("resources", "liftover", "hg38ToHg19.over.chain.gz")),
    ),
)

_BY_ID = {s.id: s for s in _SPECS}


def all_specs() -> tuple[LibrarySpec, ...]:
    return _SPECS


def spec_by_id(library_id: str) -> LibrarySpec | None:
    return _BY_ID.get(library_id)


def specs_for_purpose(purpose: str) -> tuple[LibrarySpec, ...]:
    return tuple(s for s in _SPECS if purpose in s.purposes)


def specs_for_phase(phase: str) -> tuple[LibrarySpec, ...]:
    return tuple(s for s in _SPECS if s.phase == phase)
