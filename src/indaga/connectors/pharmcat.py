"""Owned pharmacogenomics — run PharmCAT on the subject's imputed genome, on-device.

Indaga's PGx stage: the imputed GRCh38 genome (~/.indaga/<subject>/imputed.vcf.gz) →
PharmCAT (CPIC star-allele matcher + phenotyper + reporter) → the subject's own
phenotype.json under ~/.indaga/<subject>/pharmcat/. Nothing is borrowed; PharmCAT is
downloaded + wrapped (see reference.manager.ensure_pharmcat), the genome never leaves
the machine.

Two genome-specific fixes make a Beagle-imputed VCF a valid PharmCAT input:
  1. Subset to the PharmCAT positions that ship with the tool (~300 sites) — fast, and it
     drops the dense imputed background PharmCAT never reads.
  2. Declare ``END`` in the header: the 1000G-30x panel emits ``END=`` on some records but
     never declares it, which makes PharmCAT's preprocessor abort. Adding the INFO
     definition (a header-only rewrite of the small subset) makes the field well-typed.
``--absent-to-ref`` then fills any PGx position the subset doesn't carry with reference.

Tools: bcftools/bgzip/tabix + Java 17 (PharmCAT) + a small deps venv (colorama/pandas).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ..reference import manager as refmgr
from ..runtime import paths

# PharmCAT + bcftools live on the user's PATH; Homebrew's keg-only JDK 17 is prepended
# when present (PharmCAT needs Java 17 specifically).
_BREW_JDK17 = "/opt/homebrew/opt/openjdk@17/bin"
_END_HDR = '##INFO=<ID=END,Number=1,Type=Integer,Description="End position of the variant">\n'
# Below this imputation R², a call is NO evidence at a PGx allele-defining position. Writing a
# sub-threshold genotype as a confident 0|0/1|1 makes the star-allele matcher no-call: e.g. three
# DR2=0 1|1 artifacts at CYP2C19 defining sites (chr10:94762712/94762715/94842866) force a CYP2C19
# no-call and lose clopidogrel/SSRI/PPI guidance, while the genuine *2 (rs4244285, DR2=1) is right
# there. We null these to ./. so the matcher treats them as missing, not confident reference.
_PGX_R2_MIN = 0.8
# PGx chip-overlay recovers genes imputation loses to DR2=0 (NAT2 → *6/*6, verified) but is DISABLED:
# the raw chip carries rare-variant hom-alt FALSE POSITIVES at some PGx sites (rs367543002/3 at the
# CYP2C19 94762712/715 positions), and injecting those un-does the DR2-gate → CYP2C19 no-call again.
# Needs AF-based chip-quality filtering (cf. genome/pl_screen) before it's safe; clinical CYP2C19 must
# not regress for a NAT2 gain. The override path below is kept, flag-gated, for that follow-up.
_PGX_CHIP_OVERLAY = False


def _env() -> dict:
    env = dict(os.environ)
    extra = [p for p in (_BREW_JDK17, "/opt/homebrew/bin") if Path(p).is_dir()]
    if extra:
        env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
    return env


def phenotype_path(subject_id: str) -> Path:
    """The subject's own PharmCAT phenotype JSON (PharmCAT names it after the input)."""
    return paths.subject_dir(subject_id) / "pharmcat" / "typed.phenotype.json"


_COMP = {"A": "T", "T": "A", "C": "G", "G": "C"}


def _chip_gt(a1: str, a2: str, ref: str, alt: str) -> str | None:
    """Encode a chip genotype (allele letters) as a GT against a PGx position's ref/alt, trying
    forward strand then reverse-complement. Returns '0/0' | '1/1', or None.

    HOMOZYGOUS calls only: a chip genotype is unphased, and injecting an unphased het next to the
    imputed PHASED records breaks phase-dependent diplotype resolution (it forced CYP2C19 to
    no-call). Hom calls are phase-independent and safe to overlay — and the pharmacogenes
    imputation loses wholesale (e.g. NAT2, all-0|0) are exactly the hom-dominated ones."""
    for tf in (lambda x: x, lambda x: _COMP.get(x, x)):
        b1, b2 = tf(a1), tf(a2)
        if b1 in (ref, alt) and b2 in (ref, alt):
            n = (b1 == alt) + (b2 == alt)
            return "1/1" if n == 2 else ("0/0" if n == 0 else None)
    return None


def _apply_chip_overrides(gated_vcf: Path, positions_vcf: str, out_vcf: Path, chip, env: dict) -> int:
    """Override PGx-defining positions with the raw chip's directly-typed hard-calls (matched by
    rsID). Imputation can lose a whole pharmacogene to DR2=0 — NAT2 comes back all-0|0 even though
    it's densely chip-typed — and the chip holds the real genotype. Uses PharmCAT's own ref/alt
    (so no REF-mismatch discard) + the chip-derived GT. Returns the count overridden/inserted."""
    pv = subprocess.run(["bcftools", "view", "-H", positions_vcf],
                        capture_output=True, text=True, env=env).stdout
    overrides: dict[tuple[str, int], str] = {}  # (chrom,pos) -> full VCF record line
    for line in pv.splitlines():
        f = line.split("\t")
        if len(f) < 5:
            continue
        chrom, pos, rsid, ref, alt = f[0], f[1], f[2], f[3], f[4].split(",")[0]
        if not rsid.startswith("rs") or len(ref) != 1 or len(alt) != 1:
            continue
        v = chip.lookup_rsid(rsid)
        if v is None or not v.callable:
            continue
        gt = _chip_gt(v.allele1, v.allele2, ref, alt)
        if gt:
            overrides[(chrom, int(pos))] = f"{chrom}\t{pos}\t{rsid}\t{ref}\t{alt}\t.\tPASS\tDR2=1\tGT\t{gt}"
    if not overrides:
        return 0
    header: list[str] = []
    records: list[tuple[str, int, str]] = []   # a LIST preserves multi-record positions (e.g. the
    contigs: set[str] = set()                  # overlapping UGT1A1 indels) — a dict would collapse them
    raw = subprocess.run(["bcftools", "view", str(gated_vcf)], capture_output=True, text=True, env=env).stdout
    for line in raw.splitlines():
        if line.startswith("#"):
            header.append(line)
            if line.startswith("##contig=") and "ID=" in line:
                contigs.add(line.split("ID=")[1].split(",")[0].split(">")[0])
        else:
            f = line.split("\t")
            records.append((f[0], int(f[1]), line))
    # never inject on a contig the header doesn't declare (e.g. chrX/G6PD when the imputed genome is
    # autosome-only) — PharmCAT's preprocessor aborts on an undeclared contig.
    overrides = {k: v for k, v in overrides.items() if k[0] in contigs}
    if not overrides:
        return 0
    # replace ONLY the records at an override position (drop them, add the chip hard-call); every
    # other original record — including multi-record positions — is preserved untouched.
    out = [r for r in records if (r[0], r[1]) not in overrides]
    out += [(c, p, line) for (c, p), line in overrides.items()]

    def _ck(r: tuple[str, int, str]) -> tuple[int, int]:
        c = r[0][3:] if r[0].startswith("chr") else r[0]
        try:
            ci = int(c)
        except ValueError:
            ci = {"X": 23, "Y": 24, "M": 25, "MT": 25}.get(c, 99)
        return (ci, r[1])

    out.sort(key=_ck)
    tmp = out_vcf.parent / "over.tmp.vcf"
    tmp.write_text("\n".join(header + [r[2] for r in out]) + "\n", encoding="utf-8")
    subprocess.run(["bgzip", "-f", str(tmp)], check=True, capture_output=True, text=True, env=env)
    Path(str(tmp) + ".gz").rename(out_vcf)
    return len(overrides)


def _prepare_input(imputed_vcf: Path, positions_vcf: str, work: Path, env: dict, chip=None) -> Path | None:
    """Subset the imputed genome to the PharmCAT positions → an HONEST PGx input the matcher can
    resolve. Steps: (1) exact-position subset; (2) drop symbolic structural alts (``<DEL>/<DUP>/
    <INS:…>``) that overlap PGx SNVs; (3) null sub-threshold ALT imputations (``DR2 < _PGX_R2_MIN``
    carrying an alt) to ``./.`` — a no-confidence call must read as MISSING, never a confident 1|1
    (that is what made CYP2C19 no-call); low-DR2 hom-ref is left as the reference context RYR1 needs;
    (4) **chip-overlay**: override PGx-defining positions with the chip's directly-typed hard-calls
    (recovers genes imputation lost to DR2=0, e.g. NAT2). END is declared last."""
    sub = work / "sub.vcf.gz"
    noalt = work / "noalt.vcf.gz"
    gated = work / "gated.vcf.gz"
    over = work / "over.vcf.gz"
    typed = work / "typed.vcf.gz"
    hdr = work / "end.hdr"
    hdr.write_text(_END_HDR, encoding="utf-8")

    def _bcf(args: list[str]) -> None:
        subprocess.run(args, check=True, capture_output=True, text=True, env=env)

    _bcf(["bcftools", "view", "-R", positions_vcf, str(imputed_vcf), "-Oz", "-o", str(sub)])
    _bcf(["bcftools", "view", "-e", 'ALT[*]~"<"', str(sub), "-Oz", "-o", str(noalt)])
    _bcf(["bcftools", "+setGT", str(noalt), "-Oz", "-o", str(gated),
          "--", "-t", "q", "-i", f'INFO/DR2<{_PGX_R2_MIN} && GT="alt"', "-n", "."])
    src = gated
    if _PGX_CHIP_OVERLAY and chip is not None and _apply_chip_overrides(gated, positions_vcf, over, chip, env):
        src = over
    _bcf(["bcftools", "annotate", "-h", str(hdr), str(src), "-Oz", "-o", str(typed)])
    _bcf(["tabix", "-f", "-p", "vcf", str(typed)])
    return typed if typed.exists() else None


def run_pharmcat(subject_id: str) -> dict:
    """Run PharmCAT on the subject's imputed genome → ~/.indaga/<subject>/pharmcat/.
    The first ever run also triggers PharmCAT's ~883 MB GRCh38 reference-FASTA download
    (its preprocessor manages it); later runs are ~1 minute."""
    pc = refmgr.ensure_pharmcat()
    if pc is None:
        return {"status": "failed", "reason": "PharmCAT unavailable; run: indaga install pharmcat-pipeline "
                "(needs Java 17 + bcftools, and a venv with colorama/pandas/packaging)"}
    imputed = paths.subject_dir(subject_id) / "imputed.vcf.gz"
    if not imputed.exists():
        return {"status": "failed", "reason": "no imputed genome; run genome.impute first "
                "(PharmCAT needs the GRCh38 imputed VCF, not the raw chip)"}

    paths.ensure_subject_dirs(subject_id)
    work = paths.subject_dir(subject_id) / "pharmcat"
    work.mkdir(parents=True, exist_ok=True)
    env = _env()
    # the raw-chip AGI holds directly-typed genotypes for pharmacogenes imputation loses to DR2=0
    # (e.g. NAT2 — densely chip-typed but all-0|0 imputed); used to overlay the PGx subset. Built
    # and cached during genome ingest; None → imputed-only (no override, never a wrong call).
    from ..genome.agi import AGIReader, chip_agi_path
    chip = AGIReader.open(str(chip_agi_path(subject_id)))
    try:
        prepared = _prepare_input(imputed, pc["positions"], work, env, chip=chip)
        if chip is not None:
            chip.close()
        if prepared is None:
            return {"status": "failed", "reason": "could not prepare the PGx VCF subset"}
        subprocess.run(
            [pc["python"], pc["pipeline"], str(prepared), "-o", str(work),
             "--absent-to-ref", "-reporterJson", "-cp", "2"],
            check=True, capture_output=True, text=True, cwd=pc["dir"], env=env)
    except subprocess.CalledProcessError as exc:
        tail = (exc.stderr or exc.stdout or "")[-800:]
        return {"status": "failed", "reason": "PharmCAT run error", "detail": tail}

    pheno = phenotype_path(subject_id)
    if not pheno.exists():
        return {"status": "failed", "reason": "PharmCAT produced no phenotype.json"}
    from ..genome import evidence as ev
    genes = ev.pharmcat_genes(subject_id=subject_id)
    called = [g for g in genes if g["called"]]
    return {"status": "ok", "subject": subject_id, "phenotype_json": str(pheno),
            "genes_reported": len(genes), "genes_called": len(called)}
