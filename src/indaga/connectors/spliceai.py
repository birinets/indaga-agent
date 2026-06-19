"""Owned splice-impact prediction — run SpliceAI's model on-the-fly for the variants we care
about, on-device.

The precomputed SpliceAI scores (~30 GB) sit behind Illumina BaseSpace authentication, so they
can't be a self-contained auto-download. Instead Indaga runs SpliceAI's neural net itself (the
``spliceai`` package + TensorFlow, isolated in ~/.indaga/tools/spliceai/venv) over just the handful
of variants being assessed — no 30 GB, no login. Same model, same scores.

SpliceAI catches what the canonical ±1/2 splice rule and AlphaMissense (missense-only) both miss:
deep-intronic cryptic sites, exonic splice disruption (even synonymous), and splice-region weakening.
It returns four delta scores (acceptor/donor × gain/loss, 0–1); the max is the splice-altering
probability (≥0.5 recommended, ≥0.8 high-confidence) → ACMG PP3 (computational support).

The gene annotation SpliceAI needs is generated from Indaga's own MANE model (so its transcript set +
chromosome naming match the consequence annotator and the GRCh38 FASTA). subprocess + stdlib.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from ..reference import manager as refmgr

_VENV = Path("tools", "spliceai", "venv")
_ANNOTATION = Path("tools", "spliceai", "mane_annotation.txt")
_WRAPPER = Path("tools", "spliceai", "run_spliceai.py")

# SpliceAI (≤v1.3.1) calls np.fromstring(seq, np.int8) — removed in numpy 2.x (which TensorFlow
# pulls in). This wrapper shims it back (no mutation of site-packages) then runs SpliceAI's CLI.
_WRAPPER_SRC = '''import sys
import numpy as np
_orig = np.fromstring
def _fromstring(s, dtype=float, *a, **k):
    if dtype == np.int8 and isinstance(s, (bytes, str)):
        return np.frombuffer(s.encode("latin-1") if isinstance(s, str) else s, np.int8)
    return _orig(s, dtype, *a, **k)
np.fromstring = _fromstring
from spliceai.__main__ import main
sys.exit(main())
'''


def _venv_python() -> Path:
    return refmgr._resolve(_VENV / "bin" / "python3")


def _ensure_wrapper() -> Path:
    w = refmgr._resolve(_WRAPPER)
    if not w.exists():
        w.parent.mkdir(parents=True, exist_ok=True)
        w.write_text(_WRAPPER_SRC, encoding="utf-8")
    return w


# TF supports Python ≤3.12; spliceai needs pkg_resources (setuptools<81) + BioPython (bgzf FASTA).
_DEPS = ("spliceai", "tensorflow", "pyfaidx", "biopython", "setuptools<81")
_PY_CANDIDATES = ("python3.12", "python3.11")


def available() -> bool:
    """True when the SpliceAI venv (TensorFlow) + the GRCh38 FASTA are both present."""
    return _venv_python().exists() and refmgr.ensure_reference_fasta() is not None


def ensure_env() -> dict:
    """Create the isolated SpliceAI venv (TensorFlow) reproducibly. TensorFlow has no Python-3.14
    wheel, so a 3.11/3.12 interpreter is required; returns {status, reason}. Slow (pulls TF)."""
    import shutil
    import subprocess
    if _venv_python().exists():
        return {"status": "ok", "python": str(_venv_python())}
    interp = next((shutil.which(p) for p in _PY_CANDIDATES if shutil.which(p)), None)
    if interp is None:
        return {"status": "failed", "reason": "no TensorFlow-compatible Python (need 3.11 or 3.12) on PATH"}
    venv = refmgr._resolve(_VENV)
    try:
        venv.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([interp, "-m", "venv", str(venv)], check=True, capture_output=True)
        py = str(_venv_python())
        # isolated venv (never the system/user env) + non-interactive. TensorFlow versions are left
        # unpinned by necessity (platform/Python-specific wheels); SpliceAI is opt-in + degrades to
        # unavailable on failure. Hash-pinned wheel vendoring is the deferred (P2/P3) hardening.
        _pip = [py, "-m", "pip", "install", "--quiet", "--no-input", "--disable-pip-version-check"]
        subprocess.run([*_pip, "--upgrade", "pip"], check=True, capture_output=True)
        subprocess.run([*_pip, *_DEPS], check=True, capture_output=True)
        return {"status": "ok", "python": py}
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "reason": str(exc)[-300:]}


def _annotation_file() -> Path | None:
    """Build (once) SpliceAI's gene-annotation table from Indaga's MANE model — chr-prefixed
    to match the reference FASTA. Format: NAME, CHROM, STRAND, TX_START, TX_END, EXON_START,
    EXON_END (comma-listed exon bounds)."""
    out = refmgr._resolve(_ANNOTATION)
    if out.exists():
        return out
    from ..genome.genemodel import GeneModel
    gm = GeneModel.open()
    if gm is None:
        return None
    try:
        rows = gm._con.execute("SELECT gene, chrom, strand, exon_json FROM transcripts").fetchall()
    except Exception:  # noqa: BLE001
        gm.close()
        return None
    import json
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        fh.write("#NAME\tCHROM\tSTRAND\tTX_START\tTX_END\tEXON_START\tEXON_END\n")
        for r in rows:
            exons = sorted(tuple(x) for x in json.loads(r["exon_json"]))
            if not exons:
                continue
            chrom = r["chrom"]
            chrom = chrom if str(chrom).startswith("chr") else f"chr{chrom}"
            starts = ",".join(str(s) for s, _ in exons) + ","
            ends = ",".join(str(e) for _, e in exons) + ","
            fh.write(f"{r['gene']}\t{chrom}\t{r['strand']}\t{exons[0][0]}\t{exons[-1][1]}\t{starts}\t{ends}\n")
    gm.close()
    return out


def _write_vcf(variants, path: Path) -> None:
    rows = sorted({(c if str(c).startswith("chr") else f"chr{c}", int(p), r, a)
                   for c, p, r, a in variants})
    chroms = sorted({c for c, *_ in rows})
    with path.open("w", encoding="utf-8") as f:
        f.write("##fileformat=VCFv4.2\n")
        for c in chroms:                       # pysam needs declared contigs to write records
            f.write(f"##contig=<ID={c}>\n")
        f.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n")
        for c, p, r, a in rows:
            f.write(f"{c}\t{p}\t.\t{r}\t{a}\t.\t.\t.\n")


def _parse(out_vcf: Path) -> dict:
    """Parse SpliceAI INFO (SpliceAI=ALLELE|SYMBOL|DS_AG|DS_AL|DS_DG|DS_DL|DP_AG|DP_AL|DP_DG|DP_DL)
    → {(bare_chrom,pos,ref,alt): {ds_*, ds_max, symbol}}."""
    out: dict = {}
    if not out_vcf.exists():
        return out
    with out_vcf.open(encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            f = line.rstrip("\n").split("\t")
            if len(f) < 8 or "SpliceAI=" not in f[7]:
                continue
            chrom = f[0][3:] if f[0].startswith("chr") else f[0]
            pos, ref, alt = int(f[1]), f[3], f[4]
            field = f[7].split("SpliceAI=", 1)[1].split(";", 1)[0].split(",")[0]
            parts = field.split("|")
            if len(parts) < 6:
                continue
            try:
                ds = {"ds_ag": float(parts[2]), "ds_al": float(parts[3]),
                      "ds_dg": float(parts[4]), "ds_dl": float(parts[5])}
            except ValueError:
                continue
            ds["ds_max"] = max(ds.values())
            ds["symbol"] = parts[1]
            out[(chrom, pos, ref, alt)] = ds
    return out


def score_variants(variants: list[tuple], *, distance: int = 50) -> dict:
    """Score variants [(chrom,pos,ref,alt), …] with SpliceAI. Returns {(chrom,pos,ref,alt):
    {ds_ag,ds_al,ds_dg,ds_dl,ds_max,symbol}}. Empty/{'_error':…} if SpliceAI is unavailable.
    One TensorFlow startup is amortized across the whole batch — pass many at once."""
    if not variants:
        return {}
    py = _venv_python()
    fasta = refmgr.ensure_reference_fasta()
    ann = _annotation_file()
    if not (py.exists() and fasta and ann):
        return {"_error": "SpliceAI unavailable (venv / FASTA / annotation missing)"}
    wrapper = _ensure_wrapper()
    work = Path(tempfile.mkdtemp(prefix="spliceai_"))
    inv, outv = work / "in.vcf", work / "out.vcf"
    _write_vcf(variants, inv)
    env = {**os.environ, "TF_CPP_MIN_LOG_LEVEL": "3", "CUDA_VISIBLE_DEVICES": "-1"}
    cmd = [str(py), str(wrapper), "-I", str(inv), "-O", str(outv), "-R", str(fasta),
           "-A", str(ann), "-D", str(distance)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
    except subprocess.CalledProcessError as exc:
        return {"_error": (exc.stderr or exc.stdout or "")[-600:]}
    finally:
        pass
    return _parse(outv)


def score_variant(chrom: str, pos: int, ref: str, alt: str) -> dict | None:
    """SpliceAI scores for one variant (or None). Note: a TensorFlow cold start (~10–20 s)."""
    res = score_variants([(chrom, pos, ref, alt)])
    if "_error" in res:
        return None
    c = chrom[3:] if str(chrom).startswith("chr") else str(chrom)
    return res.get((c, int(pos), ref, alt))


# ACMG mapping: SpliceAI delta score → PP3 (computational splice support), ClinGen-style bands.
def pp3(ds_max: float | None) -> tuple[str, str] | None:
    if ds_max is None:
        return None
    if ds_max >= 0.8:
        return ("PP3", "strong")
    if ds_max >= 0.5:
        return ("PP3", "moderate")
    if ds_max >= 0.2:
        return ("PP3", "supporting")
    return None  # below the recall threshold → no splice support (not benign evidence)
