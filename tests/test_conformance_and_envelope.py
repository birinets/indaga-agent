"""Port of the two CI-safe gates: store port-conformance (n=1 isolation) + the envelope honesty
regression. Both run fully in-memory — no subject store, no reference data — so they belong in CI.
(genome_parity / analyze_eval need a built subject + the 3 GB ClinVar DB and stay as local
integration scripts, run via `python -m indaga.eval.*`.)
"""

from indaga.eval.envelope_eval import run as run_envelope
from indaga.store import conformance


def test_store_conformance():
    assert conformance.main() == 0


def test_envelope_states():
    results = run_envelope()
    failed = [name for name, ok, _detail in results if not ok]
    assert not failed, f"envelope checks failed: {failed}"
