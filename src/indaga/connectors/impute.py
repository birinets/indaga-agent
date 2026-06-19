"""Owned local imputation — extend a consumer chip to a dense GRCh38 genome on-device.

Indaga's own "extend" stage: raw chip (GRCh37) → imputed GRCh38 genome
(~/.indaga/<subject>/imputed.vcf.gz), with the genome NEVER leaving the machine
(the privacy moat; TOPMed-grade needs a server upload and is off this path).

Engine: Beagle 5.5 (GPL). Panel: 1000G-30x GRCh38 phased (3,202 genomes, NYGC) —
GRCh38-native, a clear upgrade over the older GRCh37 1000G-phase3. (HGDP+1kGP,
more diverse, is a future upgrade with no ready phased release.)

Alignment: the panel is keyed by GRCh38 ``chrom:pos:ref:alt`` (no rsIDs), so the chip
is lifted GRCh37→GRCh38 (pyliftover + the UCSC chain Indaga downloads) and matched to
the panel BY POSITION; the chip genotype is coded against the panel's REF/ALT (forward
strand + reverse-complement fallback). Beagle then phases + imputes the chip scaffold
against the panel. Tooling: Beagle + Java + bcftools/bgzip/tabix + pyliftover.
"""

from __future__ import annotations

import csv
import gzip
import subprocess
from pathlib import Path

from ..reference import manager as refmgr
from ..runtime import paths

_COMPLEMENT = {"A": "T", "T": "A", "C": "G", "G": "C"}
_NO_CALL = {"--", "00", "..", "NN", ""}
_AUTOSOMES = [str(i) for i in range(1, 23)]


def _revcomp1(a: str) -> str:
    return _COMPLEMENT.get(a, "N")


_NC_ALLELE = {"-", ".", "0", "N", "", "I", "D"}  # no-call / non-SNV (indel I/D) single-allele codes


def _detect_delim(path: str) -> str:
    """Sniff the chip delimiter: tab (AncestryDNA/23andMe) vs comma (MyHeritage)."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            return "\t" if "\t" in line else ","
    return ","


def _iter_chip_rows(chip_path: str):
    """Yield (rsid, bare_chrom, pos, allele1, allele2) for every chip row, handling BOTH consumer
    layouts: MyHeritage/23andMe-CSV (col4 = combined 'AG') AND AncestryDNA (tab; col4/col5 = split
    'A','G'). Header + comment lines fall out (POSITION isn't a digit)."""
    delim = _detect_delim(chip_path)
    with open(chip_path, newline="", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            cells = next(csv.reader([line])) if delim == "," else line.split("\t")
            cells = [c.strip().strip('"') for c in cells]
            if len(cells) < 4 or not cells[2].isdigit():
                continue
            rsid, chrom, pos = cells[0], cells[1], int(cells[2])
            chrom = chrom[3:] if chrom.lower().startswith("chr") else chrom
            # split-allele (≥5 cols, single-char each) vs combined 2-char genotype in col4
            if len(cells) >= 5 and len(cells[3]) == 1 and len(cells[4]) == 1:
                a1, a2 = cells[3].upper(), cells[4].upper()
            else:
                g = cells[3].upper()
                if len(g) < 2:
                    continue
                a1, a2 = g[0], g[1]
            yield rsid, chrom, pos, a1, a2


def parse_chip(chip_csv: str) -> list[tuple[str, int, str, str]]:
    """[(chrom, pos_grch37, allele1, allele2)] from a consumer chip (MyHeritage/AncestryDNA/23andMe),
    forward strand, autosomes, called SNP genotypes only. chrom is bare (no 'chr')."""
    out: list[tuple[str, int, str, str]] = []
    for rsid, chrom, pos, a1, a2 in _iter_chip_rows(chip_csv):
        if chrom not in _AUTOSOMES or a1 in _NC_ALLELE or a2 in _NC_ALLELE:
            continue
        out.append((chrom, pos, a1, a2))
    return out


def chip_rsid_map(chip_csv: str, chain_path: str) -> dict[tuple[str, int], str]:
    """{(bare_chrom, pos38): rsid} from the chip, lifted to GRCh38 — used to re-attach the
    chip's rsIDs onto an imputed AGI whose panel uses chrom:pos:ref:alt IDs (so
    variant.resolve by rsID keeps working for directly-typed common variants)."""
    from pyliftover import LiftOver
    lo = LiftOver(chain_path)
    out: dict[tuple[str, int], str] = {}
    for rsid, chrom, pos, _a1, _a2 in _iter_chip_rows(chip_csv):
        if not rsid.startswith("rs") or chrom not in _AUTOSOMES:
            continue
        res = lo.convert_coordinate(f"chr{chrom}", pos - 1)
        if not res:
            continue
        c38 = res[0][0]
        out[(c38[3:] if c38.lower().startswith("chr") else c38, res[0][1] + 1)] = rsid
    return out


def lift_to_grch38(records, chain_path: str) -> dict[tuple[str, int], tuple[str, str]]:
    """Lift chip GRCh37 positions → {(chrom38_with_chr, pos38_1based): (a1, a2)}.
    pyliftover is 0-based; VCF/chip positions are 1-based."""
    from pyliftover import LiftOver
    lo = LiftOver(chain_path)
    out: dict[tuple[str, int], tuple[str, str]] = {}
    for chrom, pos, a1, a2 in records:
        res = lo.convert_coordinate(f"chr{chrom}", pos - 1)
        if not res:
            continue
        c38, p0 = res[0][0], res[0][1]
        out[(c38, p0 + 1)] = (a1, a2)
    return out


def _code_gt(a1: str, a2: str, ref: str, alt: str) -> str | None:
    """Code a chip genotype against panel REF/ALT → '0/0' | '0/1' | '1/1' (forward strand
    or reverse-complement). None if the alleles don't match the site."""
    s = {a1, a2}
    if s <= {ref, alt}:
        return f"{int(a1 == alt)}/{int(a2 == alt)}"
    rr, ra = _revcomp1(ref), _revcomp1(alt)
    if s <= {rr, ra}:
        return f"{int(a1 == ra)}/{int(a2 == ra)}"
    return None


def build_chip_vcf(lifted: dict, panel_vcf: str, out_vcf: str, sample: str = "SUBJECT") -> int:
    """Write a GRCh38 chip VCF for one chromosome by matching the lifted chip positions to
    the panel sites. Returns the number of scaffold sites; output is bgzipped + tabixed."""
    n = 0
    tmp = out_vcf[:-3] if out_vcf.endswith(".gz") else out_vcf
    with gzip.open(panel_vcf, "rt") as pf, open(tmp, "w", encoding="utf-8") as out:
        out.write("##fileformat=VCFv4.2\n")
        out.write('##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n')
        wrote_cols = False
        for line in pf:
            if line.startswith("##contig"):
                out.write(line)
                continue
            if line.startswith("#"):
                continue
            f = line.split("\t", 6)
            if len(f) < 6:
                continue
            pchrom, ppos, pid, pref, palt = f[0], f[1], f[2], f[3], f[4]
            if not wrote_cols:
                out.write(f"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t{sample}\n")
                wrote_cols = True
            if "," in palt or len(pref) != 1 or len(palt) != 1:
                continue  # biallelic SNV scaffold only
            g = lifted.get((pchrom, int(ppos)))
            if g is None:
                continue
            gt = _code_gt(g[0], g[1], pref, palt)
            if gt is None:
                continue
            out.write(f"{pchrom}\t{ppos}\t{pid}\t{pref}\t{palt}\t.\t.\t.\tGT\t{gt}\n")
            n += 1
    if not n:
        Path(tmp).unlink(missing_ok=True)
        return 0
    subprocess.run(["bgzip", "-f", tmp], check=True)
    subprocess.run(["tabix", "-f", "-p", "vcf", out_vcf], check=True)
    return n


def impute_chrom(lifted: dict, chrom: str, work: Path, *, threads: int = 4, mem_gb: int = 8) -> Path | None:
    """Impute one chromosome: build the chip scaffold, run Beagle against the panel.
    Uses a bref3 panel when available (≈10x faster, far lower RAM), else the VCF panel.
    Returns the imputed VCF path (None if panel/map/jar missing or no scaffold sites)."""
    jar = refmgr.beagle_jar_path()
    gmap = refmgr.beagle_map_path(chrom)
    # build the chip scaffold against the panel SITES (needs the VCF for site coords)
    panel_vcf = refmgr.ensure_panel_chrom(chrom)
    if not (jar.exists() and panel_vcf and gmap):
        return None
    chip_vcf = str(work / f"chip.chr{chrom}.vcf.gz")
    if not build_chip_vcf(lifted, str(panel_vcf), chip_vcf):
        return None
    ref = refmgr.ensure_panel_bref3(chrom) or panel_vcf   # bref3 if convertible, else VCF
    out_prefix = str(work / f"imputed.chr{chrom}")
    cmd = ["java", f"-Xmx{mem_gb}g", "-jar", str(jar),
           f"gt={chip_vcf}", f"ref={ref}", f"map={gmap}",
           f"out={out_prefix}", f"nthreads={threads}"]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    out_vcf = Path(out_prefix + ".vcf.gz")
    return out_vcf if out_vcf.exists() else None


def impute_genome(subject_id: str, chip_csv: str, *, chroms: list[str] | None = None,
                  threads: int = 4, mem_gb: int = 8, dr2_min: float = 0.0) -> dict:
    """Impute a chip to a GRCh38 genome at ~/.indaga/<subject>/imputed.vcf.gz.
    ``chroms`` defaults to all autosomes; pass e.g. ['22'] for a single-chromosome run."""
    paths.ensure_subject_dirs(subject_id)
    work = paths.work_dir(subject_id) / "impute"
    work.mkdir(parents=True, exist_ok=True)
    chain = paths.indaga_home() / "resources" / "liftover" / "hg19ToHg38.over.chain.gz"
    if not chain.exists():
        return {"status": "failed", "reason": "liftover chain missing; run: indaga install liftover-chains"}
    records = parse_chip(chip_csv)
    lifted = lift_to_grch38(records, str(chain))
    chroms = chroms or _AUTOSOMES
    per_chrom: list[str] = []
    for c in chroms:
        sub = {k: v for k, v in lifted.items() if k[0] == f"chr{c}"}
        out = impute_chrom(sub, c, work, threads=threads, mem_gb=mem_gb)
        if out:
            per_chrom.append(str(out))
    if not per_chrom:
        return {"status": "failed", "reason": "no chromosomes imputed (panel/jar missing?)",
                "chip_sites": len(records), "lifted_sites": len(lifted)}
    # Beagle output VCFs carry no ##contig lines, so a header-checking concat fails — use
    # --naive (raw BGZF block concat; per-chrom files share an identical header + one sample).
    # The full imputed.vcf.gz keeps ALL variants + their DR2; quality filtering (dr2_min) is
    # applied downstream at AGI build time (build_agi_from_vcf r2_min), not here.
    final = paths.subject_dir(subject_id) / "imputed.vcf.gz"
    if len(per_chrom) == 1:
        Path(per_chrom[0]).replace(final)
    else:
        subprocess.run(["bcftools", "concat", "--naive", "-Oz", "-o", str(final), *per_chrom], check=True)
    subprocess.run(["tabix", "-f", "-p", "vcf", str(final)], check=True)
    n = int(subprocess.run(["bcftools", "index", "-n", str(final)],
                           capture_output=True, text=True).stdout.strip() or 0)
    return {"status": "imputed", "subject": subject_id, "output": str(final),
            "chromosomes": chroms, "chip_sites": len(records), "lifted_sites": len(lifted),
            "imputed_variants": n, "dr2_filter_applied_at": "agi_build"}
