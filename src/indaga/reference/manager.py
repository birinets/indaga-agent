"""Reference-library manager — download, status, check, ensure.

The single code path that materializes reference libraries under ``indaga_home()``
and reports what is installed. "Full download always": references are fetched
into ``~/.indaga/`` (never silently borrowed from ``~/.genomi`` or HeathProject)
so Indaga is genuinely standalone. Idempotent — an installed library is not
re-fetched unless ``force=True``.

Slim port of ``genomi/runtime/libraries/manager.py`` (stdlib only: urllib + json
+ hashlib). Mirrors the ``*.indaga-manifest.json`` sidecar convention.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..runtime import paths
from . import registry
from .spec import Kind, LibrarySpec

_MANIFEST_SUFFIX = ".indaga-manifest.json"
_TIMEOUT = 300


class LibraryUnavailable(RuntimeError):
    """A required reference library is not installed and could not be auto-fetched."""

    def __init__(self, library_id: str, message: str):
        super().__init__(message)
        self.library_id = library_id
        self.install_command = install_command([library_id])


# -- path resolution -------------------------------------------------------- #

def _resolve(rel: Path) -> Path:
    return paths.indaga_home() / rel


def _manifest_path(target: Path) -> Path:
    return target.with_name(target.name + _MANIFEST_SUFFIX)


def _manifest_sha256(target: Path) -> str | None:
    """The sha256 recorded when ``target`` was first downloaded (trust-on-first-use), or None.
    Used to VERIFY a re-fetch matches the original bytes — so upstream drift/tampering on a
    ``force`` re-download is caught even when the spec ships no vendor-published checksum."""
    mp = _manifest_path(target)
    if not mp.exists():
        return None
    try:
        return json.loads(mp.read_text(encoding="utf-8")).get("sha256")
    except (OSError, ValueError):
        return None


def install_command(ids: list[str] | tuple[str, ...]) -> str:
    return "indaga install " + " ".join(ids)


def clinvar_vcf_path(build: str = "GRCh38") -> Path:
    return _resolve(Path("resources", "clinvar", build, "clinvar.vcf.gz"))


def pgs_weight_path(pgs_id: str, build: str = "GRCh38") -> Path:
    return _resolve(Path("reference", "pgs", pgs_id, f"{pgs_id}_hmPOS_{build}.txt.gz"))


def pgs_metadata_path() -> Path:
    return _resolve(Path("resources", "pgs", "pgs_all_metadata_scores.csv"))


# -- in-silico predictors (Phase B) ----------------------------------------- #

def constraint_path() -> Path:
    return _resolve(Path("resources", "gnomad", "constraint_metrics.tsv"))


def ensure_constraint() -> Path | None:
    """Return the gnomAD gene-constraint TSV (pLI/LOEUF), downloading it once. None if unavailable."""
    p = constraint_path()
    if p.exists():
        return p
    return p if install(["gnomad-constraint"])["ok"] and p.exists() else None


def alphamissense_bgz_path() -> Path:
    return _resolve(Path("resources", "alphamissense", "AlphaMissense_hg38.tsv.bgz"))


def ensure_alphamissense() -> Path | None:
    """Return a bgzipped + tabix-indexed AlphaMissense (position-queryable), downloading +
    transforming the DeepMind .tsv.gz once. None if unavailable."""
    import subprocess
    bgz = alphamissense_bgz_path()
    if bgz.exists() and bgz.with_name(bgz.name + ".tbi").exists():
        return bgz
    spec = registry.spec_by_id("alphamissense")
    gz = _resolve(spec.required_paths[0]) if spec else None
    if gz is None:
        return None
    if not gz.exists():
        if not install(["alphamissense"])["ok"]:
            return None
    try:
        # gunzip → bgzip (the DeepMind file is plain gzip; tabix needs BGZF), then index.
        with open(bgz, "wb") as out:
            g = subprocess.Popen(["gunzip", "-c", str(gz)], stdout=subprocess.PIPE)
            subprocess.run(["bgzip"], stdin=g.stdout, stdout=out, check=True)
            g.wait()
        subprocess.run(["tabix", "-s", "1", "-b", "2", "-e", "2", str(bgz)], check=True)
        return bgz
    except Exception:  # noqa: BLE001
        bgz.unlink(missing_ok=True)
        return None


# -- REVEL (Phase B: second missense predictor) ----------------------------- #

def revel_bgz_path() -> Path:
    return _resolve(Path("resources", "revel", "revel_grch38.tsv.bgz"))


def ensure_revel() -> Path | None:
    """Return a bgzipped + tabix-indexed GRCh38 REVEL table (chrom,pos,ref,alt,REVEL),
    building it once from the downloaded zip. The REVEL CSV is sorted by GRCh37 position, so
    it is re-sorted by GRCh38 position for tabix. None if unavailable."""
    import csv
    import subprocess
    import tempfile
    import zipfile
    bgz = revel_bgz_path()
    if bgz.exists() and bgz.with_name(bgz.name + ".tbi").exists():
        return bgz
    spec = registry.spec_by_id("revel")
    zp = _resolve(spec.targets[0]) if spec and spec.targets else None
    if zp is None:
        return None
    if not zp.exists() and not (install(["revel"])["ok"] and zp.exists()):
        return None
    try:
        zf = zipfile.ZipFile(zp)
        member = next((m for m in zf.namelist() if not m.endswith("/")), None)
        if member is None:
            return None
        tmp = Path(tempfile.mkstemp(dir=str(bgz.parent), suffix=".revel.tsv")[1])
        with zf.open(member) as raw, tmp.open("w", encoding="utf-8") as out:
            rdr = csv.reader((ln.decode("utf-8", "replace") for ln in raw))
            next(rdr, None)  # skip header: chr,hg19_pos,grch38_pos,ref,alt,aaref,aaalt,REVEL,Ensembl_transcriptid
            for row in rdr:
                if len(row) < 8 or not row[2].isdigit():   # grch38_pos == '.' → no GRCh38 mapping
                    continue
                out.write(f"{row[0]}\t{row[2]}\t{row[3]}\t{row[4]}\t{row[7]}\n")
        sorted_tsv = tmp.with_suffix(".sorted")
        with sorted_tsv.open("w") as so:
            subprocess.run(["sort", "-k1,1", "-k2,2n", str(tmp)], check=True, stdout=so)
        with open(bgz, "wb") as fh:
            subprocess.run(["bgzip", "-c", str(sorted_tsv)], check=True, stdout=fh)
        subprocess.run(["tabix", "-s", "1", "-b", "2", "-e", "2", str(bgz)], check=True)
        tmp.unlink(missing_ok=True)
        sorted_tsv.unlink(missing_ok=True)
        return bgz
    except Exception:  # noqa: BLE001
        bgz.unlink(missing_ok=True)
        return None


# -- gene model + reference FASTA (Phase E: consequence annotation) ---------- #

def mane_gff_path() -> Path:
    return _resolve(Path("resources", "mane", "MANE.GRCh38.v1.4.ensembl_genomic.gff.gz"))


def ensure_mane(*, auto_install: bool = True) -> Path | None:
    """Return the MANE Select GFF (transcript/exon/CDS model), downloading it once. With
    ``auto_install=False`` (the read-only grounding path) it never downloads — returns None if absent."""
    p = mane_gff_path()
    if p.exists():
        return p
    if not auto_install:
        return None
    return p if install(["mane-select"])["ok"] and p.exists() else None


# -- HPA single-cell-type RNA (analytical grounding: cell-type breadth) ------ #

def hpa_singlecell_zip_path() -> Path:
    return _resolve(Path("resources", "hpa", "rna_single_cell_type.tsv.zip"))


def hpa_singlecell_tsv_path() -> Path:
    return _resolve(Path("resources", "hpa", "rna_single_cell_type.tsv"))


def ensure_hpa_singlecell(*, auto_install: bool = True) -> Path | None:
    """Return the extracted HPA single-cell-type TSV (Gene, Gene name, Cell type, nCPM), downloading +
    unzipping the ~16 MB archive once. Streams the single ``.tsv`` member to a fixed path (no extractall).
    With ``auto_install=False`` (the read-only grounding path) it never downloads but still extracts an
    already-downloaded zip. None if unavailable."""
    import shutil
    import zipfile
    tsv = hpa_singlecell_tsv_path()
    if tsv.exists():
        return tsv
    zp = hpa_singlecell_zip_path()
    if not zp.exists() and not (auto_install and install(["hpa-single-cell"])["ok"] and zp.exists()):
        return None
    try:
        zf = zipfile.ZipFile(zp)
        member = next((m for m in zf.namelist() if m.endswith(".tsv") and not m.endswith("/")), None)
        if member is None:
            return None
        tsv.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as raw, tsv.open("wb") as out:
            shutil.copyfileobj(raw, out)
        return tsv
    except Exception:  # noqa: BLE001
        tsv.unlink(missing_ok=True)
        return None


# -- ENCODE cCRE registry (analytical grounding: regulatory regions) --------- #

def encode_ccre_bed_path() -> Path:
    return _resolve(Path("resources", "encode", "GRCh38-cCREs.bed"))


def ensure_encode_ccre(*, auto_install: bool = True) -> Path | None:
    """Return the ENCODE SCREEN cCRE BED (GRCh38), downloading the ~129 MB file once. With
    ``auto_install=False`` (the read-only grounding path) it never downloads — None if absent."""
    p = encode_ccre_bed_path()
    if p.exists():
        return p
    if not auto_install:
        return None
    return p if install(["encode-ccre"])["ok"] and p.exists() else None


# -- Gene Ontology (analytical grounding: GO process/function/component) ------ #

def go_gaf_path() -> Path:
    return _resolve(Path("resources", "go", "goa_human.gaf.gz"))


def go_obo_path() -> Path:
    return _resolve(Path("resources", "go", "go-basic.obo"))


def ensure_gene_ontology(*, auto_install: bool = True) -> tuple[Path, Path] | None:
    """Return (GAF, OBO) for the human Gene Ontology, downloading both once. With ``auto_install=False``
    (the read-only grounding path) it never downloads — None if either file is absent."""
    gaf, obo = go_gaf_path(), go_obo_path()
    if gaf.exists() and obo.exists():
        return (gaf, obo)
    if not auto_install:
        return None
    if install(["gene-ontology"])["ok"] and gaf.exists() and obo.exists():
        return (gaf, obo)
    return None


# -- PanelApp diagnostic panels (green genes per disorder) ------------------- #

def panelapp_dir() -> Path:
    return _resolve(Path("resources", "panelapp"))


def ensure_panelapp(*, auto_install: bool = True) -> Path | None:
    """Return the dir holding the downloaded PanelApp panel JSONs, downloading the curated set once.
    With ``auto_install=False`` (read-only grounding) it never downloads — None if nothing present."""
    d = panelapp_dir()
    if d.exists() and any(d.glob("*.json")):
        return d
    if not auto_install:
        return None
    install(["panelapp-green"])
    return d if d.exists() and any(d.glob("*.json")) else None


# -- Gene-disease validity (GenCC + ClinGen — graded clinical panels) -------- #

def gencc_tsv_path() -> Path:
    return _resolve(Path("resources", "gene_disease", "gencc-submissions.tsv"))


def clingen_validity_path() -> Path:
    return _resolve(Path("resources", "gene_disease", "clingen-gene-validity.csv"))


def ensure_gene_disease(*, auto_install: bool = True) -> tuple[Path | None, Path | None]:
    """Return (GenCC TSV, ClinGen CSV) for gene-disease validity, downloading both once. Either may be
    None (the loader builds from whichever is present). With ``auto_install=False`` (read-only grounding)
    it never downloads — returns whatever is already on disk."""
    gencc, clingen = gencc_tsv_path(), clingen_validity_path()
    have = gencc.exists() or clingen.exists()
    if not have and auto_install:
        install(["gene-disease-validity"])
    return (gencc if gencc.exists() else None, clingen if clingen.exists() else None)


# -- HGNC complete gene set (analytical grounding: entity-canon) ------------- #

def hgnc_complete_path() -> Path:
    return _resolve(Path("resources", "hgnc", "hgnc_complete_set.txt"))


def ensure_hgnc(*, auto_install: bool = True) -> Path | None:
    """Return the HGNC complete-gene-set TSV (approved symbols + aliases), downloading once. With
    ``auto_install=False`` (the read-only grounding path) it never downloads — None if absent."""
    p = hgnc_complete_path()
    if p.exists():
        return p
    if not auto_install:
        return None
    return p if install(["hgnc-complete"])["ok"] and p.exists() else None


# -- Reactome pathway gene sets (analytical grounding) ---------------------- #

def reactome_gmt_zip_path() -> Path:
    return _resolve(Path("resources", "reactome", "ReactomePathways.gmt.zip"))


def reactome_gmt_path() -> Path:
    return _resolve(Path("resources", "reactome", "ReactomePathways.gmt"))


def ensure_reactome_gmt(*, auto_install: bool = True) -> Path | None:
    """Return the extracted Reactome pathway GMT (gene-symbol gene sets), downloading + unzipping
    the ~0.3 MB archive once. Reads the single ``.gmt`` member to a fixed path (no extractall, so no
    zip-slip surface). With ``auto_install=False`` (the read-only grounding path) it never downloads —
    it still extracts an already-downloaded zip, but returns None if the zip is absent."""
    import zipfile
    gmt = reactome_gmt_path()
    if gmt.exists():
        return gmt
    zp = reactome_gmt_zip_path()
    if not zp.exists() and not (auto_install and install(["reactome-pathways"])["ok"] and zp.exists()):
        return None
    try:
        zf = zipfile.ZipFile(zp)
        member = next((m for m in zf.namelist() if m.endswith(".gmt") and not m.endswith("/")), None)
        if member is None:
            return None
        gmt.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as raw, gmt.open("wb") as out:
            out.write(raw.read())
        return gmt
    except Exception:  # noqa: BLE001
        gmt.unlink(missing_ok=True)
        return None


# -- Human Protein Atlas tissue expression (analytical grounding) ----------- #

def hpa_tissue_zip_path() -> Path:
    return _resolve(Path("resources", "hpa", "rna_tissue_consensus.tsv.zip"))


def hpa_tissue_tsv_path() -> Path:
    return _resolve(Path("resources", "hpa", "rna_tissue_consensus.tsv"))


def ensure_hpa_tissue(*, auto_install: bool = True) -> Path | None:
    """Return the extracted HPA consensus tissue TSV (Gene, Gene name, Tissue, nTPM), downloading +
    unzipping the ~5 MB archive once. Streams the single ``.tsv`` member to a fixed path (no
    extractall, so no zip-slip surface). With ``auto_install=False`` (the read-only grounding path) it
    never downloads — it still extracts an already-downloaded zip, but returns None if the zip is absent."""
    import shutil
    import zipfile
    tsv = hpa_tissue_tsv_path()
    if tsv.exists():
        return tsv
    zp = hpa_tissue_zip_path()
    if not zp.exists() and not (auto_install and install(["hpa-tissue-rna"])["ok"] and zp.exists()):
        return None
    try:
        zf = zipfile.ZipFile(zp)
        member = next((m for m in zf.namelist() if m.endswith(".tsv") and not m.endswith("/")), None)
        if member is None:
            return None
        tsv.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as raw, tsv.open("wb") as out:
            shutil.copyfileobj(raw, out)
        return tsv
    except Exception:  # noqa: BLE001
        tsv.unlink(missing_ok=True)
        return None


def reference_fasta_path() -> Path:
    return _resolve(Path("resources", "fasta", "hg38.fa.bgz"))


def ensure_reference_fasta() -> Path | None:
    """Return a bgzipped + faidx-indexed GRCh38 FASTA for codon lookup. Reuses the FASTA
    PharmCAT already downloaded (~883 MB) when present — same assembly, chr-prefixed — to
    avoid a second ~950 MB download; otherwise fetches + indexes the dedicated UCSC hg38."""
    import subprocess
    # 1) reuse PharmCAT's reference if it's installed + indexed (same GRCh38, chr-named)
    pc_fa = pharmcat_dir() / "reference.fna.bgz"
    if pc_fa.exists() and pc_fa.with_name(pc_fa.name + ".fai").exists():
        return pc_fa
    # 2) the dedicated bgzf FASTA, if already built
    bgz = reference_fasta_path()
    if bgz.exists() and bgz.with_name(bgz.name + ".fai").exists():
        return bgz
    # 3) download + transform (gunzip → bgzip → faidx)
    spec = registry.spec_by_id("reference-fasta-grch38")
    gz = _resolve(spec.targets[0]) if spec and spec.targets else None
    if gz is None:
        return None
    if not gz.exists() and not install(["reference-fasta-grch38"])["ok"]:
        return None
    try:
        with open(bgz, "wb") as out:
            g = subprocess.Popen(["gunzip", "-c", str(gz)], stdout=subprocess.PIPE)
            subprocess.run(["bgzip"], stdin=g.stdout, stdout=out, check=True)
            g.wait()
        subprocess.run(["samtools", "faidx", str(bgz)], check=True)
        return bgz
    except Exception:  # noqa: BLE001
        bgz.unlink(missing_ok=True)
        return None


# -- PharmCAT (Phase D) ----------------------------------------------------- #

# PharmCAT preprocessor deps, version-PINNED so the runtime install is reproducible and a single
# compromised "latest" can't be pulled. Installed into a DEDICATED venv (never the system/user env);
# if the pinned install fails (no wheel for this Python), PGx degrades to unavailable — never silent.
# Full hash-pinned wheel vendoring is the deferred (P2/P3) hardening.
_PHARMCAT_DEPS = ("colorama==0.4.6", "pandas==2.2.3", "packaging==24.1")


def pharmcat_dir() -> Path:
    return _resolve(Path("tools", "pharmcat"))


def pharmcat_pipeline_script() -> Path:
    return pharmcat_dir() / "pharmcat_pipeline"


def pharmcat_positions_path() -> Path:
    return pharmcat_dir() / "pharmcat_positions.vcf.bgz"


def pharmcat_python() -> str | None:
    """A Python interpreter that has the PharmCAT preprocessor deps (colorama/pandas/
    packaging). Prefers a dedicated venv under the PharmCAT dir (self-contained); falls
    back to the current interpreter if it already has them. None if neither works."""
    import subprocess
    import sys
    venv_py = pharmcat_dir() / "venv" / "bin" / "python3"
    probe = "import colorama, pandas, packaging"
    for py in (str(venv_py), sys.executable):
        if py == str(venv_py) and not venv_py.exists():
            continue
        try:
            subprocess.run([py, "-c", probe], check=True, capture_output=True)
            return py
        except Exception:  # noqa: BLE001
            continue
    return None


def _ensure_pharmcat_venv() -> str | None:
    """Create a venv under the PharmCAT dir with the preprocessor deps. Returns its python
    path, or None if creation/installation fails (no network / no wheels)."""
    import subprocess
    import sys
    existing = pharmcat_python()
    if existing:
        return existing
    venv = pharmcat_dir() / "venv"
    py = venv / "bin" / "python3"
    try:
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, capture_output=True)
        subprocess.run([str(py), "-m", "pip", "install", "--quiet", "--no-input",
                        "--disable-pip-version-check", *_PHARMCAT_DEPS],
                       check=True, capture_output=True)
        return str(py) if py.exists() else None
    except Exception:  # noqa: BLE001
        return None


def _safe_extract(tf, dest: Path) -> None:
    """Extract a tar archive, guarding against path-traversal (a member resolving OUTSIDE ``dest``,
    via ``../`` or an absolute path, or a symlink pointing out). Prefers the stdlib 'data' filter
    (Python 3.12+ / 3.8.17+/3.9.17+/3.10.12+/3.11.4+ backport), which also strips devices/setuid;
    on older runtimes it validates every member by hand. Replaces a bare ``extractall``."""
    dest = dest.resolve()
    prefix = str(dest) + os.sep
    try:
        tf.extractall(dest, filter="data")  # type: ignore[call-arg]
        return
    except TypeError:
        pass  # no 'filter' kwarg on this runtime → manual validation below
    for member in tf.getmembers():
        target = (dest / member.name).resolve()
        if target != dest and not str(target).startswith(prefix):
            raise LibraryUnavailable("pharmcat-pipeline", f"unsafe tar member path: {member.name!r}")
        if member.issym() or member.islnk():
            link = (dest / member.name).parent.joinpath(member.linkname).resolve()
            if not str(link).startswith(prefix):
                raise LibraryUnavailable("pharmcat-pipeline", f"unsafe tar link target: {member.name!r}")
    tf.extractall(dest)


def ensure_pharmcat() -> dict | None:
    """Materialize the PharmCAT pipeline (download the tar, extract it flat into
    ~/.indaga/tools/pharmcat, ensure a deps venv). Returns {dir, python, pipeline,
    positions} or None if unavailable. The GRCh38 reference FASTA (~883 MB) is fetched
    by PharmCAT's own preprocessor on the first run."""
    import tarfile
    script = pharmcat_pipeline_script()
    if not script.exists():
        tar = pharmcat_dir() / "pharmcat-pipeline.tar.gz"
        if not tar.exists() and not (install(["pharmcat-pipeline"])["ok"] and tar.exists()):
            return None
        try:
            with tarfile.open(tar) as tf:
                _safe_extract(tf, pharmcat_dir())  # path-traversal-guarded extraction
        except Exception:  # noqa: BLE001
            return None
        script.chmod(0o755)
    py = _ensure_pharmcat_venv()
    if py is None or not pharmcat_positions_path().exists():
        return None
    return {"dir": str(pharmcat_dir()), "python": py, "pipeline": str(script),
            "positions": str(pharmcat_positions_path())}


# -- GWAS Catalog (Phase D) ------------------------------------------------- #

def gwas_zip_path() -> Path:
    return _resolve(Path("resources", "gwas", "gwas-catalog-associations.zip"))


def ensure_gwas() -> Path | None:
    """Return the zipped GWAS Catalog associations TSV, downloading it once. None if unavailable."""
    p = gwas_zip_path()
    if p.exists():
        return p
    return p if install(["gwas-catalog"])["ok"] and p.exists() else None


# -- imputation (Beagle + panel + maps) ------------------------------------- #

def beagle_jar_path() -> Path:
    return _resolve(Path("tools", "beagle", "beagle.jar"))


def bref3_jar_path() -> Path:
    return _resolve(Path("tools", "beagle", "bref3.jar"))


def panel_dir() -> Path:
    return _resolve(Path("reference", "impute_panel", "1000g_30x"))


def panel_chrom_path(chrom: str) -> Path:
    return panel_dir() / f"chr{chrom}.phased.vcf.gz"


def panel_bref3_path(chrom: str) -> Path:
    return panel_dir() / f"chr{chrom}.phased.bref3"


def ensure_panel_bref3(chrom: str) -> Path | None:
    """Return the chromosome's panel as bref3, converting the VCF once (≈10x faster Beagle).
    Falls back to None if the bref3 jar or the panel VCF is unavailable."""
    import subprocess
    out = panel_bref3_path(chrom)
    if out.exists():
        return out
    jar = bref3_jar_path()
    if not jar.exists():
        return None
    vcf = ensure_panel_chrom(chrom)
    if not vcf:
        return None
    try:
        with open(out, "wb") as fh:
            subprocess.run(["java", "-jar", str(jar), str(vcf)], check=True, stdout=fh)
        return out
    except Exception:  # noqa: BLE001 — fall back to the VCF panel
        out.unlink(missing_ok=True)
        return None


def ensure_panel_chrom(chrom: str) -> Path | None:
    """Materialize one chromosome of the 1000G-30x GRCh38 phased panel (~445 MB/chr)."""
    target = panel_chrom_path(chrom)
    if target.exists():
        return target
    spec = registry.spec_by_id("impute-panel-1000g-30x")
    if spec is None or not spec.source.url_template:
        return None
    url = spec.source.url_template.format(key=chrom)
    try:
        # per-key file: no single spec checksum, but verify a re-fetch against the TOFU hash.
        _download(url, target, user_agent=spec.source.user_agent, sha256=_manifest_sha256(target))
        return target
    except Exception:  # noqa: BLE001
        return None


def beagle_map_path(chrom: str) -> Path | None:
    """Return the per-chromosome PLINK GRCh38 map (chr-prefixed, to match the 1000G-30x
    panel's 'chrNN' contigs), extracting it from the maps zip once."""
    import zipfile
    out = _resolve(Path("reference", "beagle_maps", f"plink.chrchr{chrom}.GRCh38.map"))
    if out.exists():
        return out
    zip_path = _resolve(Path("reference", "beagle_maps", "plink.GRCh38.map.zip"))
    if not zip_path.exists():
        return None
    member = f"chr_in_chrom_field/plink.chrchr{chrom}.GRCh38.map"
    try:
        with zipfile.ZipFile(zip_path) as z:
            data = z.read(member)
        out.write_bytes(data)
        return out
    except (KeyError, OSError):
        return None


# -- download primitive ----------------------------------------------------- #

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _download(url: str, target: Path, *, user_agent: str | None, sha256: str | None) -> dict[str, Any]:
    target.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": user_agent or registry.USER_AGENT})
    digest = hashlib.sha256()
    size = 0
    last_modified = None
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".part")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp, os.fdopen(fd, "wb") as out:
            last_modified = resp.headers.get("Last-Modified")
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        got = digest.hexdigest()
        if sha256 and got != sha256:
            raise LibraryUnavailable("?", f"sha256 mismatch for {url}: expected {sha256}, got {got}")
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    manifest = {
        "downloaded_at_utc": _utc_now(),
        "source_url": url,
        "output": str(target),
        "size_bytes": size,
        "sha256": digest.hexdigest(),
        "last_modified": last_modified,
        "status": "completed",
    }
    _manifest_path(target).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


# -- public surface --------------------------------------------------------- #

def status(spec: LibrarySpec) -> dict[str, Any]:
    """Report install state for one library. Online libraries are 'live'."""
    if spec.is_online:
        return {"id": spec.id, "kind": spec.kind.value, "phase": spec.phase,
                "installed": True, "state": "live", "api_base": spec.source.api_base}
    if spec.kind is Kind.PARAMETERIZED:
        root = _resolve(spec.required_paths[0]) if spec.required_paths else None
        n = len(list(root.glob("*/"))) if root and root.exists() else 0
        return {"id": spec.id, "kind": spec.kind.value, "phase": spec.phase,
                "installed": n > 0, "state": "per-key", "cached_keys": n,
                "root": str(root) if root else None}
    required = [_resolve(p) for p in spec.required_paths]
    missing = [str(p) for p in required if not p.exists()]
    installed = not missing
    return {
        "id": spec.id, "kind": spec.kind.value, "phase": spec.phase, "title": spec.title,
        "size_class": spec.size_class, "installed": installed,
        "state": "installed" if installed else "not_installed",
        "paths": [str(p) for p in required], "missing": missing,
        "install_command": None if installed else install_command([spec.id]),
        "manual": spec.kind is Kind.MANUAL,
    }


def check_all() -> dict[str, Any]:
    """Status of every registered library — the payload behind indaga.check_libraries."""
    rows = [status(s) for s in registry.all_specs()]
    return {
        "home": str(paths.indaga_home()),
        "installed": sorted(r["id"] for r in rows if r["installed"]),
        "missing": sorted(r["id"] for r in rows if not r["installed"]),
        "libraries": rows,
    }


def install(ids: list[str] | tuple[str, ...] | None = None, *, force: bool = False) -> dict[str, Any]:
    """Download the named OFFLINE libraries into indaga_home(). Default: all phase-A offline libs."""
    if not ids:
        ids = [s.id for s in registry.all_specs() if s.phase == "A" and s.downloadable]
    results = []
    for lid in ids:
        spec = registry.spec_by_id(lid)
        if spec is None:
            results.append({"id": lid, "ok": False, "error": "unknown_library"})
            continue
        if not spec.downloadable:
            results.append({"id": lid, "ok": False, "error": f"not auto-downloadable ({spec.kind.value})",
                            "manual": spec.kind is Kind.MANUAL})
            continue
        st = status(spec)
        if st["installed"] and not force:
            results.append({"id": lid, "ok": True, "state": "already_installed", "paths": st.get("paths")})
            continue
        try:
            files = []
            for url, rel in zip(spec.source.urls, spec.targets):
                target = _resolve(rel)
                # enforce the vendor-published checksum if the spec declares one, else the
                # trust-on-first-use hash recorded on the original download (catches re-fetch drift).
                expected = spec.source.sha256 or _manifest_sha256(target)
                files.append(_download(url, target, user_agent=spec.source.user_agent, sha256=expected))
            results.append({"id": lid, "ok": True, "state": "downloaded",
                            "bytes": sum(f["size_bytes"] for f in files), "files": [f["output"] for f in files]})
        except Exception as exc:  # noqa: BLE001 — surface, don't abort the batch
            results.append({"id": lid, "ok": False, "error": str(exc)})
    return {"results": results, "ok": all(r["ok"] for r in results)}


def ensure(library_id: str) -> Path:
    """Return the primary installed path for a library, fetching it if missing.

    Raises LibraryUnavailable (with an install command) if it cannot be made present.
    """
    spec = registry.spec_by_id(library_id)
    if spec is None:
        raise LibraryUnavailable(library_id, f"unknown library {library_id!r}")
    st = status(spec)
    if not st["installed"]:
        if spec.downloadable:
            rep = install([library_id])
            if not rep["ok"]:
                err = next((r.get("error") for r in rep["results"] if not r["ok"]), "download failed")
                raise LibraryUnavailable(library_id, f"could not fetch {library_id}: {err}")
        else:
            raise LibraryUnavailable(
                library_id,
                f"{library_id} is not installed ({spec.kind.value}); run: {install_command([library_id])}")
    return _resolve(spec.required_paths[0]) if spec.required_paths else paths.indaga_home()


def ensure_pgs_weight(pgs_id: str, build: str = "GRCh38") -> Path | None:
    """Materialize one PGS harmonized scoring file; return its path (None if unavailable)."""
    target = pgs_weight_path(pgs_id, build)
    if target.exists():
        return target
    spec = registry.spec_by_id("pgs-weights")
    if spec is None or not spec.source.url_template:
        return None
    url = spec.source.url_template.format(key=pgs_id, build=build)
    try:
        _download(url, target, user_agent=spec.source.user_agent, sha256=_manifest_sha256(target))
        return target
    except Exception:  # noqa: BLE001 — a missing score is non-fatal; caller skips it
        return None
