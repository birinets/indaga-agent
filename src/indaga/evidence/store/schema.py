"""Evidence-store DDL — the single source of truth for the genome evidence schema.

Two databases, mirroring genomi/evidence/store:
  * SHARED  (~/.indaga/shared-evidence.sqlite): cross-subject public reference —
    ClinVar variants + rsID/gene indexes + gnomAD population frequencies. Built
    once, ATTACH-blended into each subject read.
  * SUBJECT (~/.indaga/<subject>/evidence.sqlite): per-subject materialized
    findings — the P/LP screen + polygenic scores computed against the AGI.

ClinVar is imported **rsID-bearing only** for v1 (the chip-faithful core joins by
rsID, which is build-independent). Position joins / predictors (Phase B/E) widen it.
"""

from __future__ import annotations

# -- SHARED (cross-subject public reference) -------------------------------- #

SHARED_SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS clinvar_variants (
  chrom TEXT, pos INTEGER, ref TEXT, alt TEXT, genome_build TEXT,
  clinvar_id TEXT, allele_id TEXT,
  clinical_significance TEXT, review_status TEXT, conditions TEXT,
  gene_info TEXT, hgvs TEXT, mc TEXT
);

CREATE TABLE IF NOT EXISTS clinvar_variant_rsids (
  rsid TEXT, variant_rowid INTEGER, genome_build TEXT,
  PRIMARY KEY (rsid, variant_rowid)
);

CREATE TABLE IF NOT EXISTS clinvar_variant_genes (
  gene_symbol TEXT, variant_rowid INTEGER, genome_build TEXT
);

CREATE TABLE IF NOT EXISTS population_frequencies (
  chrom TEXT, pos INTEGER, ref TEXT, alt TEXT, genome_build TEXT, rsid TEXT,
  source TEXT, population TEXT,
  allele_count INTEGER, allele_number INTEGER, allele_frequency REAL,
  homozygote_count INTEGER, imported_at TEXT
);

CREATE TABLE IF NOT EXISTS gwas_associations (
  chrom TEXT, pos INTEGER, rsid TEXT, trait TEXT, gene TEXT,
  or_beta TEXT, pval REAL, mlog REAL, pmid TEXT
);
"""

# Indexes created AFTER bulk insert (much faster than per-row B-tree maintenance).
SHARED_INDEXES = (
    "CREATE INDEX IF NOT EXISTS clinvar_variant_idx ON clinvar_variants(chrom,pos,ref,alt,genome_build)",
    "CREATE INDEX IF NOT EXISTS clinvar_variant_rsids_rsid_idx ON clinvar_variant_rsids(rsid, genome_build)",
    "CREATE INDEX IF NOT EXISTS clinvar_variant_genes_gene_idx ON clinvar_variant_genes(gene_symbol, genome_build)",
    "CREATE INDEX IF NOT EXISTS population_frequency_rsid_idx ON population_frequencies(rsid, genome_build)",
    "CREATE INDEX IF NOT EXISTS gwas_assoc_pos_idx ON gwas_associations(chrom, pos)",
    "CREATE INDEX IF NOT EXISTS gwas_assoc_rsid_idx ON gwas_associations(rsid)",
)

# -- SUBJECT (per-subject materialized findings) ---------------------------- #

SUBJECT_SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS pl_findings (
  rsid TEXT, gene TEXT, panel TEXT,
  chrom TEXT, pos INTEGER, ref TEXT, alt TEXT, achange TEXT,
  candidate_reason TEXT,
  clinvar_sig TEXT, clinvar_disease TEXT, clinvar_review TEXT,
  gnomad_af REAL, gnomad_source TEXT,
  classification TEXT NOT NULL,
  zygosity TEXT, inheritance TEXT, carrier_status TEXT, interpretation TEXT,
  directly_typed INTEGER, confidence TEXT, review_stars INTEGER,
  created_at TEXT,
  PRIMARY KEY (rsid, chrom, pos, ref, alt)
);

CREATE TABLE IF NOT EXISTS pgs_results (
  pgs_id TEXT PRIMARY KEY,
  category TEXT, trait_label TEXT, direction TEXT, note TEXT,
  raw_score REAL, n_total INTEGER, n_matched INTEGER, coverage REAL,
  n_strand_flipped INTEGER, n_ambiguous_skipped INTEGER,
  af_coverage REAL, n_af_from_gnomad INTEGER,
  z_score REAL, percentile REAL, pop_mu REAL, pop_sd REAL,
  created_at TEXT
);
"""
