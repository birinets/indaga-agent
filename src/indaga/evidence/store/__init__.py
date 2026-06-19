"""Indaga's own genome evidence store (mirrors genomi/evidence/store/).

A shared ClinVar/gnomAD reference DB (``~/.indaga/shared-evidence.sqlite``) +
per-subject materialized findings (``~/.indaga/<subject>/evidence.sqlite``),
ATTACH-blended for reads. This is the genome-engine-internal artifact that
replaces the dependency on HeathProject's pre-computed OpenCRAVAT outputs.
"""

from .clinvar_import import import_clinvar_vcf
from .connection import init_shared, init_subject, open_reader
from .gwas_import import import_gwas_catalog
from .population import GnomadClient
from .reader import EvidenceStoreReader
from .writer import upsert_pgs_results, upsert_pl_findings

__all__ = [
    "import_clinvar_vcf", "import_gwas_catalog", "init_shared", "init_subject", "open_reader",
    "GnomadClient", "EvidenceStoreReader", "upsert_pl_findings", "upsert_pgs_results",
]
