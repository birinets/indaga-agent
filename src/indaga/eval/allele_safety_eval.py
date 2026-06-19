"""Allele-safety regression — the P/LP ClinVar⋈AGI join must match on the EXACT allele.

This is the regression the architecture review demanded: it asserts the *mapping*, not
"a finding must/мust-not exist". The release-blocking bug was that ``clinvar_pl_carriers``
joined ClinVar↔AGI on ``(chrom,pos)`` only and accepted a carrier whenever the ClinVar ALT
appeared among the subject's two alleles — with **no REF/ALT identity check**. So a ClinVar
indel ``AA>C`` collided with a chip SNP genotype ``A/C`` (ALT ``C`` ∈ {A,C}) and the subject
inherited a *different variant's* pathogenic significance.

The test builds tiny ClinVar + AGI SQLite fixtures (no network, no 3 GB reference) and drives
``EvidenceStoreReader.clinvar_pl_carriers`` directly:

  TRAP rows  — must NOT be returned (a match here is the bug):
    * BRCA2-like indel  ClinVar AA>C  vs chip SNP A/C      (the headline collision)
    * SNV ref-mismatch  ClinVar G>A   vs chip genotype G/C (carries C, not the ALT A)
    * imputed alt-mismatch ClinVar C>T vs imputed C/A row  (AGI alt=A ≠ ClinVar alt=T)
    * imputed indel mismatch ClinVar CA>C (del A) vs imputed CT>C (del T) at one locus
  REAL rows  — must be returned (an exact match):
    * chip SNV     ClinVar A>T  vs chip genotype A/T
    * imputed SNV  ClinVar C>G  vs imputed C/G row (AGI ref=C, alt=G match)
    * imputed indel, DIFFERENT ANCHOR  ClinVar CA>C vs imputed CAA>CA — the same deletion encoded
      with a longer anchor. Raw string-equality MISSES it; VRS minimal-representation matches it.

It FAILS on the pre-fix reader (the indel + mismatches surface) and PASSES once the join
requires VRS-normalized REF/ALT identity (see genome/vrs.py). Run:

    PYTHONPATH=src python3 -m indaga.eval.allele_safety_eval
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

from ..evidence.store import EvidenceStoreReader
from ..evidence.store import connection as econn
from ..evidence.store import schema as evschema
from ..genome.agi import _SCHEMA as AGI_SCHEMA

_BUILD = "GRCh37"


def _clinvar_row(chrom, pos, ref, alt, *, sig="Pathogenic", gene="GENEX"):
    # mirrors the clinvar_variants column order used by EvidenceStoreReader
    return (chrom, int(pos), ref, alt, _BUILD, f"VCV{pos}", f"AL{pos}",
            sig, "criteria provided, single submitter", "Test condition",
            f"{gene}:1", f"NM_test:c.{pos}", None)


def _build_shared(path: Path, rows: list[tuple]) -> None:
    con = sqlite3.connect(str(path))
    con.executescript(evschema.SHARED_SCHEMA)
    con.executemany(
        "INSERT INTO clinvar_variants(chrom,pos,ref,alt,genome_build,clinvar_id,allele_id,"
        "clinical_significance,review_status,conditions,gene_info,hgvs,mc) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


def _build_agi(path: Path, rows: list[tuple]) -> None:
    """rows: (rsid, chrom, pos, genotype, allele1, allele2, zygosity, record_kind, ref, alt, af, typed)"""
    con = sqlite3.connect(str(path))
    con.executescript(AGI_SCHEMA)
    con.executemany(
        "INSERT INTO variants(rsid,chrom,pos,genotype,allele1,allele2,zygosity,record_kind,ref,alt,af,typed) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    # a chip-built AGI (no imputation): mark source so directly_typed resolves to True
    con.execute("INSERT INTO metadata(key,value) VALUES('build', ?)", (_BUILD,))
    con.commit()
    con.close()


def run() -> int:
    passed = total = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal passed, total
        total += 1
        passed += 1 if ok else 0
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        shared = tmp / "shared-evidence.sqlite"
        subj = tmp / "evidence.sqlite"
        agi = tmp / "active-genome-index.sqlite"

        clinvar_rows = [
            _clinvar_row("13", 32332592, "AA", "C", gene="BRCA2"),   # TRAP: indel vs chip SNP
            _clinvar_row("2", 200, "G", "A", gene="SNVMIS"),         # TRAP: subject carries C, not A
            _clinvar_row("4", 400, "C", "T", gene="IMPMIS"),         # TRAP: imputed alt=A ≠ T
            _clinvar_row("5", 500, "A", "G", gene="TRIALLELE"),      # TRAP: chip G/T — ref A absent (not this variant)
            _clinvar_row("7", 700, "CA", "C", gene="TRAPINDEL"),     # TRAP: imputed del-T ≠ this del-A
            _clinvar_row("1", 100, "A", "T", gene="REALCHIP"),       # REAL: exact chip SNV
            _clinvar_row("3", 300, "C", "G", gene="REALIMP"),        # REAL: exact imputed SNV
            _clinvar_row("6", 600, "CA", "C", gene="REALINDEL"),     # REAL: same del, different anchor
        ]
        _build_shared(shared, clinvar_rows)

        agi_rows = [
            # rsid, chrom, pos, genotype, a1, a2, zyg, kind, ref, alt, af, typed
            ("rs144848", "13", 32332592, "A/C", "A", "C", "het", "variant_call", None, None, None, 0),
            ("rsMIS",    "2", 200, "G/C", "G", "C", "het", "variant_call", None, None, None, 0),
            ("rsIMPMIS", "4", 400, "C/A", "C", "A", "het", "variant_call", "C", "A", 0.1, 0),
            ("rsTRI",    "5", 500, "G/T", "G", "T", "het", "variant_call", None, None, None, 0),
            ("rsTIND",   "7", 700, "CT/C", "CT", "C", "het", "variant_call", "CT", "C", 0.05, 0),
            ("rsREAL",   "1", 100, "A/T", "A", "T", "het", "variant_call", None, None, None, 0),
            ("rsREALIMP","3", 300, "C/G", "C", "G", "het", "variant_call", "C", "G", 0.2, 0),
            ("rsRIND",   "6", 600, "CAA/CA", "CAA", "CA", "het", "variant_call", "CAA", "CA", 0.05, 0),
        ]
        _build_agi(agi, agi_rows)

        con = econn.init_subject(subj, shared_path=shared)
        con.close()

        reader = EvidenceStoreReader.open(subj)
        carriers = reader.clinvar_pl_carriers(str(agi), build=_BUILD)
        reader.close()

        by_gene = {c.get("gene"): c for c in carriers}
        pos_set = {(c["chrom"], c["pos"], c["ref"], c["alt"]) for c in carriers}

        print("Allele-safety: ClinVar⋈AGI must match the EXACT ref→alt (no position-only collisions)")
        # TRAP assertions — the mapping must reject these
        check("indel ClinVar AA>C does NOT match chip SNP A/C (the release blocker)",
              ("13", 32332592, "AA", "C") not in pos_set, f"BRCA2 in carriers={'BRCA2' in by_gene}")
        check("SNV ref-mismatch (subject carries C, ClinVar alt=A) is rejected",
              ("2", 200, "G", "A") not in pos_set, f"SNVMIS in carriers={'SNVMIS' in by_gene}")
        check("imputed alt-mismatch (AGI alt=A ≠ ClinVar alt=T) is rejected",
              ("4", 400, "C", "T") not in pos_set, f"IMPMIS in carriers={'IMPMIS' in by_gene}")
        check("chip genotype G/T not drawn from {ref A, alt G} is rejected",
              ("5", 500, "A", "G") not in pos_set, f"TRIALLELE in carriers={'TRIALLELE' in by_gene}")
        check("imputed indel mismatch (del-T row ≠ ClinVar del-A) is rejected",
              ("7", 700, "CA", "C") not in pos_set, f"TRAPINDEL in carriers={'TRAPINDEL' in by_gene}")
        # REAL assertions — exact matches must still surface
        check("exact chip SNV A>T surfaces", ("1", 100, "A", "T") in pos_set,
              f"REALCHIP in carriers={'REALCHIP' in by_gene}")
        check("exact imputed SNV C>G surfaces", ("3", 300, "C", "G") in pos_set,
              f"REALIMP in carriers={'REALIMP' in by_gene}")
        check("imputed indel, SAME deletion / different anchor (CAA>CA ≡ CA>C) surfaces via VRS",
              ("6", 600, "CA", "C") in pos_set, f"REALINDEL in carriers={'REALINDEL' in by_gene}")
        # every carrier carries a stable VRS-style allele identity (provenance / durable join key)
        check("each carrier has an indaga:VA. allele identity",
              all(str(c.get("allele_id", "")).startswith("indaga:VA.") for c in carriers),
              f"{len(carriers)} carriers")

    print(f"\n{passed}/{total} allele-safety checks passed.")
    return 0 if passed == total else 1


def main(argv=None) -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
