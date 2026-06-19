"""P1.2 — the consent/egress matrix is complete and the mutating flags are honest."""

from indaga.operations import annotations, bootstrap, registry


def _ops():
    bootstrap.load_all()
    return {o.name: o for o in registry.all_operations()}


def test_every_operation_is_annotated():
    bootstrap.load_all()
    assert annotations.missing() == []


def test_ancestry_estimate_is_mutating():
    op = _ops()["ancestry.estimate"]
    assert op.mutating is True
    assert op.operation_scope == "write"
    assert "reference_download" in op.external_io


def test_gnomad_querying_tools_declare_egress():
    by = _ops()
    for name in ("variant.resolve", "acmg.classify", "splice.assess", "synthesis.multi_omic_question"):
        assert "gnomad" in by[name].external_io, name


def test_downloaders_declare_egress_and_mutate():
    by = _ops()
    for name in ("genome.impute", "genome.annotate", "genome.pgx_run", "indaga.install"):
        assert "reference_download" in by[name].external_io, name
        assert by[name].mutating is True, name


def test_local_read_tools_have_no_egress():
    by = _ops()
    for name in ("genome.summary", "clinvar.findings", "pgs.score", "pgx.summary", "labs.query"):
        assert by[name].external_io == (), name


def test_genomic_tools_marked_genomic():
    by = _ops()
    for name in ("variant.resolve", "clinvar.findings", "pgs.score", "nutrigenomics.markers"):
        assert by[name].privacy_scope == "genomic", name
