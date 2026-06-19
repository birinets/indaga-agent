"""Indaga reference-library layer: LibrarySpec registry + downloader.

Indaga owns its reference data (ClinVar, gnomAD, PGS weights, …) under
``~/.indaga/`` rather than depending on any other tool's install. ``registry``
declares every source; ``manager`` downloads / inspects / ensures them.
"""

from .manager import (
    LibraryUnavailable,
    check_all,
    clinvar_vcf_path,
    ensure,
    ensure_pgs_weight,
    install,
    install_command,
    pgs_metadata_path,
    pgs_weight_path,
    status,
)
from .registry import all_specs, spec_by_id, specs_for_phase, specs_for_purpose
from .spec import Freshness, Kind, LibrarySpec, Source, Transform

__all__ = [
    "LibrarySpec", "Source", "Kind", "Transform", "Freshness",
    "all_specs", "spec_by_id", "specs_for_purpose", "specs_for_phase",
    "check_all", "status", "install", "ensure", "ensure_pgs_weight",
    "install_command", "LibraryUnavailable",
    "clinvar_vcf_path", "pgs_weight_path", "pgs_metadata_path",
]
