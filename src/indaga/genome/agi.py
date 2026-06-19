"""Active Genome Index (AGI) — Indaga's own genome engine for consumer chips.

Parses a consumer-array raw genotype export (MyHeritage / 23andMe / AncestryDNA —
``rsid, chromosome, position, genotype`` rows) into a queryable SQLite index, the
multi-omic sibling of a genome agent's AGI. For a CHIP, every probed SNP is a
genotyped call, so the build is single-phase (no gVCF reference-block tail).

The load-bearing honesty primitive is **callability**: a variant the chip did not
probe is `not_on_chip` — its absence is UNKNOWN, never "you don't have it". This is
the genomic leg of the multi-omic envelope (REQ_CALLABILITY / REQ_GENOTYPE_SUPPORT).

stdlib only (sqlite3 + csv).
"""

from __future__ import annotations

import csv
import gzip
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

_NO_CALL = {"--", "00", "..", "NN", ""}
_GT_SPLIT = re.compile(r"[/|]")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS variants (
  rsid TEXT, chrom TEXT, pos INTEGER, genotype TEXT,
  allele1 TEXT, allele2 TEXT, zygosity TEXT, record_kind TEXT,
  ref TEXT, alt TEXT, af REAL, typed INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS variants_rsid_idx ON variants(rsid);
CREATE INDEX IF NOT EXISTS variants_region_idx ON variants(chrom, pos);
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT);
"""
# variant.resolve fields (VariantCall) — the original 8; ref/alt/af are PGS-only extras.
_CORE_COLS = "rsid, chrom, pos, genotype, allele1, allele2, zygosity, record_kind"


@dataclass(frozen=True, slots=True)
class VariantCall:
    rsid: str
    chrom: str
    pos: int
    genotype: str            # e.g. "AG"
    allele1: str
    allele2: str
    zygosity: str            # "hom" | "het" | "no_call"
    record_kind: str         # "variant_call" | "no_call"
    typed: int = 0           # 1 = directly-typed chip hard-call overlaid onto the imputed AGI

    @property
    def callable(self) -> bool:
        return self.record_kind != "no_call"

    @property
    def directly_typed(self) -> bool:
        return bool(self.typed)

    @property
    def alleles(self) -> tuple[str, str]:
        return (self.allele1, self.allele2)


def _norm_chrom(c: str) -> str:
    c = c.strip()
    return c[3:] if c.lower().startswith("chr") else c


def _parse_genotype(result: str) -> tuple[str, str, str, str]:
    g = result.strip().upper()
    if g in _NO_CALL or len(g) < 2:
        return ("", "", "no_call", "no_call")
    a1, a2 = g[0], g[1]
    if a1 in "-." or a2 in "-.":
        return (a1, a2, "no_call", "no_call")
    zyg = "hom" if a1 == a2 else "het"
    return (a1, a2, zyg, "variant_call")


def build_agi(chip_csv: str, db_path: str) -> dict:
    """Build the AGI SQLite from a consumer chip CSV. Returns build stats."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript("DROP TABLE IF EXISTS variants; DROP TABLE IF EXISTS metadata;")
    con.executescript(_SCHEMA)

    header_meta: dict[str, str] = {}
    rows: list[tuple] = []
    n_total = n_call = n_nocall = 0
    with open(chip_csv, newline="", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("##"):
                if "=" in line:
                    k, _, v = line[2:].partition("=")
                    header_meta[k.strip()] = v.strip()
                continue
            if line.startswith("#"):
                continue
            # header row "RSID,CHROMOSOME,POSITION,RESULT" (quoted or not)
            cells = next(csv.reader([line]))
            if len(cells) < 4:
                continue
            rsid, chrom, pos, result = (c.strip().strip('"') for c in cells[:4])
            if rsid.upper() in ("RSID", "RS_ID") or not pos.isdigit():
                continue
            a1, a2, zyg, kind = _parse_genotype(result)
            rows.append((rsid, _norm_chrom(chrom), int(pos), result.strip().strip('"').upper(),
                         a1, a2, zyg, kind))
            n_total += 1
            n_call += 1 if kind == "variant_call" else 0
            n_nocall += 1 if kind == "no_call" else 0

    con.execute("BEGIN")
    con.executemany(f"INSERT INTO variants({_CORE_COLS}) VALUES (?,?,?,?,?,?,?,?)", rows)
    meta = {
        "chip": header_meta.get("chip", "unknown"),
        "build": header_meta.get("reference", header_meta.get("build", "build37")),
        "vendor": header_meta.get("fileformat", "unknown"),
        "n_variants": str(n_total),
        "n_called": str(n_call),
        "n_no_call": str(n_nocall),
        "source_path": str(chip_csv),
    }
    con.executemany("INSERT INTO metadata VALUES (?,?)", list(meta.items()))
    con.execute("COMMIT")
    con.close()
    from ..runtime import paths as _paths
    _paths.secure_file(db_path)  # personal genome index → owner-only
    return {**meta, "n_variants": n_total, "n_called": n_call, "n_no_call": n_nocall}


def _open_maybe_gz(path: str):
    return gzip.open(path, "rt", encoding="utf-8", errors="replace") if path.endswith(".gz") \
        else open(path, encoding="utf-8", errors="replace")


def build_agi_from_vcf(vcf_path: str, db_path: str, *, build: str = "GRCh38",
                       source: str = "imputed", sample_index: int = 0,
                       r2_min: float | None = None,
                       rsid_map: dict[tuple[str, int], str] | None = None) -> dict:
    """Build the AGI from a single-sample VCF (e.g. an IMPUTED genome — the depth path).

    Genotypes are reconstructed from GT against REF/ALT. ref/alt + the panel AF (INFO
    ``AF=``) are stored too, so PGS gets a real per-variant population frequency (no
    gnomAD extrapolation). ``rsid_map`` {(chrom,pos): rsid} re-attaches the chip's rsIDs
    when the panel/VCF uses chrom:pos:ref:alt IDs (so variant.resolve by rsID still works).
    Imputed calls are real but probabilistic — metadata records ``source`` for honesty."""
    _COLS = "rsid, chrom, pos, genotype, allele1, allele2, zygosity, record_kind, ref, alt, af"
    _PH = "(" + ",".join("?" * 11) + ")"
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript("DROP TABLE IF EXISTS variants; DROP TABLE IF EXISTS metadata;")
    con.executescript(_SCHEMA)

    rows: list[tuple] = []
    n_total = n_call = n_nocall = n_carry = n_rsid = 0
    con.execute("BEGIN")
    with _open_maybe_gz(vcf_path) as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            f = line.rstrip("\n").split("\t")
            if len(f) < 10:
                continue
            chrom, pos, vid, ref, alt, info = f[0], f[1], f[2], f[3], f[4], f[7]
            if alt == "." or not pos.isdigit():
                continue
            if r2_min is not None:
                m = re.search(r"(?:^|;)D?R2=([0-9.]+)", info)  # Beagle=DR2, Minimac/TOPMed=R2
                if m and float(m.group(1)) < r2_min:
                    continue
            gt_field = f[9 + sample_index].split(":", 1)[0]
            idx = _GT_SPLIT.split(gt_field)
            if len(idx) < 2:
                continue
            alleles = [ref] + alt.split(",")

            def allele_for(i: str) -> str | None:
                if i in (".", ""):
                    return None
                try:
                    return alleles[int(i)]
                except (ValueError, IndexError):
                    return None

            a1, a2 = allele_for(idx[0]), allele_for(idx[1])
            n_total += 1
            if a1 is None or a2 is None:
                n_nocall += 1
                continue
            zyg = "hom" if a1 == a2 else "het"
            nchrom, ipos = _norm_chrom(chrom), int(pos)
            rsid = (rsid_map or {}).get((nchrom, ipos))
            if rsid:
                n_rsid += 1
            elif vid.startswith("rs"):
                rsid = vid
            else:
                rsid = f"{nchrom}:{ipos}"
            alt1 = alt.split(",")[0]
            if alt1 in (a1, a2):
                n_carry += 1
            afm = re.search(r"(?:^|;)AF=([0-9.eE+-]+)", info)
            af = float(afm.group(1)) if afm else None
            rows.append((rsid, nchrom, ipos, f"{a1}/{a2}", a1, a2, zyg, "variant_call", ref, alt1, af))
            n_call += 1
            if len(rows) >= 100_000:
                con.executemany(f"INSERT INTO variants({_COLS}) VALUES {_PH}", rows)
                rows.clear()
    if rows:
        con.executemany(f"INSERT INTO variants({_COLS}) VALUES {_PH}", rows)
    meta = {
        "chip": source, "build": build, "vendor": source,
        "n_variants": str(n_call), "n_called": str(n_call), "n_no_call": str(n_nocall),
        "n_alt_carrying": str(n_carry), "n_rsid_attached": str(n_rsid),
        "source": source, "source_path": str(vcf_path),
    }
    con.executemany("INSERT INTO metadata VALUES (?,?)", list(meta.items()))
    con.execute("COMMIT")
    con.close()
    from ..runtime import paths as _paths
    _paths.secure_file(db_path)  # personal genome index → owner-only
    return {**meta, "n_variants": n_call, "n_called": n_call, "n_no_call": n_nocall,
            "n_alt_carrying": n_carry, "n_rsid_attached": n_rsid}


class AGIReader:
    """Query the built AGI. Build is GRCh37/hg19 (consumer chips); callers that need
    GRCh38 positions use rsid, which is build-independent."""

    def __init__(self, db_path: str) -> None:
        self._con = sqlite3.connect(db_path)
        cols = {r[1] for r in self._con.execute("PRAGMA table_info(variants)")}
        # `typed` marks directly-typed chip hard-calls overlaid onto the imputed AGI; older/chip
        # AGIs lack it → select a literal 0 so VariantCall always receives its 9th field.
        self._typed_sel = "typed" if "typed" in cols else "0 AS typed"

    @classmethod
    def open(cls, db_path: str) -> "AGIReader | None":
        return cls(db_path) if Path(db_path).exists() else None

    def _row(self, r) -> VariantCall:
        return VariantCall(*r)

    def lookup_rsid(self, rsid: str) -> VariantCall | None:
        r = self._con.execute(
            f"SELECT rsid, chrom, pos, genotype, allele1, allele2, zygosity, record_kind, {self._typed_sel} "
            "FROM variants WHERE rsid = ? ORDER BY typed DESC LIMIT 1"
            if self._typed_sel == "typed" else
            "SELECT rsid, chrom, pos, genotype, allele1, allele2, zygosity, record_kind, 0 AS typed "
            "FROM variants WHERE rsid = ? LIMIT 1",
            [rsid.strip()],
        ).fetchone()
        return self._row(r) if r else None

    def lookup_region(self, chrom: str, start: int, end: int) -> list[VariantCall]:
        rows = self._con.execute(
            f"SELECT rsid, chrom, pos, genotype, allele1, allele2, zygosity, record_kind, {self._typed_sel} "
            "FROM variants WHERE chrom = ? AND pos BETWEEN ? AND ? ORDER BY pos",
            [_norm_chrom(chrom), start, end],
        ).fetchall()
        return [self._row(r) for r in rows]

    def position_genotypes(self) -> dict[tuple[str, int], tuple[str, str]]:
        """All called variants as {(chrom, pos): (allele1, allele2)} for position-keyed
        scoring (PGS on an imputed GRCh38 genome). chrom is bare; positions are this build."""
        out: dict[tuple[str, int], tuple[str, str]] = {}
        for chrom, pos, a1, a2 in self._con.execute(
            "SELECT chrom, pos, allele1, allele2 FROM variants WHERE record_kind='variant_call'"
        ):
            out[(chrom, pos)] = (a1, a2)
        return out

    def rsid_genotypes(self) -> dict[str, tuple[str, str]]:
        """All called variants as {rsid: (allele1, allele2)} — the build-INDEPENDENT key,
        so PGS works on a GRCh37 chip against GRCh38 weights (position would mismatch)."""
        out: dict[str, tuple[str, str]] = {}
        for rsid, a1, a2 in self._con.execute(
            "SELECT rsid, allele1, allele2 FROM variants WHERE record_kind='variant_call' AND rsid LIKE 'rs%'"
        ):
            out[rsid] = (a1, a2)
        return out

    def position_pgs_index(self) -> dict[tuple[str, int], tuple[str, str, str, float | None]]:
        """{(chrom, pos): (allele1, allele2, alt, af)} for PGS — genotype + the variant's
        ALT allele and its population frequency (panel AF), so the effect-allele frequency
        can be oriented per variant (no gnomAD extrapolation)."""
        out: dict[tuple[str, int], tuple[str, str, str, float | None]] = {}
        for chrom, pos, a1, a2, alt, af in self._con.execute(
            "SELECT chrom, pos, allele1, allele2, alt, af FROM variants WHERE record_kind='variant_call'"
        ):
            out[(chrom, pos)] = (a1, a2, alt, af)
        return out

    def region_calls(self, chrom: str, start: int, end: int) -> list[dict]:
        """Carried variant calls in a region, with ref/alt (for predictor lookups). Used by
        the AlphaMissense screen-candidate scan over priority-gene regions."""
        rows = self._con.execute(
            "SELECT rsid, pos, allele1, allele2, zygosity, ref, alt FROM variants "
            "WHERE chrom=? AND pos BETWEEN ? AND ? AND record_kind='variant_call'",
            [_norm_chrom(chrom), int(start), int(end)],
        ).fetchall()
        return [{"rsid": r[0], "pos": r[1], "allele1": r[2], "allele2": r[3],
                 "zygosity": r[4], "ref": r[5], "alt": r[6]} for r in rows]

    def variant_extras(self, rsid: str) -> dict | None:
        """{ref, alt, af} for a variant by rsID — the panel-derived ref/alt/AF stored for
        imputed genomes (None / empty for a chip-built AGI). Feeds predictor + ACMG calls."""
        r = self._con.execute(
            "SELECT ref, alt, af FROM variants WHERE rsid = ? LIMIT 1", [rsid.strip()],
        ).fetchone()
        if not r:
            return None
        return {"ref": r[0], "alt": r[1], "af": r[2]}

    def metadata(self) -> dict:
        return {k: v for k, v in self._con.execute("SELECT key, value FROM metadata").fetchall()}

    def stats(self) -> dict:
        # Counts are a LIVE COUNT(*), not the stored metadata — the chip-overlay inserts new
        # directly-typed rows after the build, so the cached metadata.n_variants under-reports the
        # real callset (the genome.summary drift). Counting is cheap on the indexed table.
        meta = self.metadata()
        n_called = self._con.execute(
            "SELECT COUNT(*) FROM variants WHERE record_kind='variant_call'").fetchone()[0]
        n_no_call = self._con.execute(
            "SELECT COUNT(*) FROM variants WHERE record_kind='no_call'").fetchone()[0]
        return {
            "chip": meta.get("chip"), "build": meta.get("build"),
            "n_variants": n_called + n_no_call,
            "n_called": n_called,
            "n_no_call": n_no_call,
        }

    def close(self) -> None:
        self._con.close()


# --------------------------------------------------------------------------- #
# Raw-chip fallback — the directly-typed genotypes
# --------------------------------------------------------------------------- #
# Imputation can LOSE a directly-typed common SNP: the site comes back DR2=0 and is
# dropped from the imputed AGI (verified on real data for CYP1A2/HFE/ALDH2/ADH1B/FTO/LCT).
# The raw chip still carries that genotype as a direct measurement, so for any site the
# imputed genome can't confidently call we fall back to the chip — and report it as
# directly-typed (the honest best evidence), never as imputed. Build-once + cached.

_RAW_CHIP_GLOBS = ("dna/raw/*.csv", "dna/raw/*.txt", "dna/raw/*.csv.gz", "dna/raw/*.txt.gz")
_MIN_CHIP_CALLS = 1000  # below this the vendor format wasn't parsed (e.g. tab-delimited) → no usable chip AGI


def chip_agi_path(subject_id: str) -> Path:
    from ..runtime import paths
    return paths.subject_dir(subject_id) / "chip-genome-index.sqlite"


def find_raw_chip(user_dir: str | None) -> Path | None:
    """Locate the subject's raw consumer-chip export under their user dir (dna/raw/)."""
    if not user_dir:
        return None
    base = Path(user_dir)
    for pat in _RAW_CHIP_GLOBS:
        hits = sorted(base.glob(pat))
        if hits:
            return hits[0]
    return None


def open_chip_agi(subject_id: str, user_dir: str | None) -> "AGIReader | None":
    """Open (building + caching on first use) the subject's RAW-CHIP AGI.

    Keyed by the chip's own rsIDs and holding directly-typed genotypes — the authoritative
    fallback when imputation lost a typed site (DR2=0). Returns None when no raw chip is
    available, or when the vendor format isn't parseable here (then there is simply no
    fallback and callers degrade to imputed-only, never to a wrong call)."""
    cache = chip_agi_path(subject_id)
    if cache.exists():
        return AGIReader.open(str(cache))
    raw = find_raw_chip(user_dir)
    if raw is None:
        return None
    try:
        stats = build_agi(str(raw), str(cache))
    except Exception:
        cache.unlink(missing_ok=True)
        return None
    if int(stats.get("n_called") or 0) < _MIN_CHIP_CALLS:  # unsupported vendor parse → don't cache an empty index
        cache.unlink(missing_ok=True)
        return None
    return AGIReader.open(str(cache))


def _overlay_chain() -> Path | None:
    from ..reference import manager as refmgr
    p = refmgr._resolve(Path("resources", "liftover", "hg19ToHg38.over.chain.gz"))
    if Path(p).exists():
        return Path(p)
    hits = sorted(Path(refmgr._resolve(Path("."))).glob("**/hg19ToHg38.over.chain.gz"))
    return hits[0] if hits else None


def overlay_chip_calls(imputed_agi_path: str, chip_agi_path: str, *, chain_path: str | None = None) -> dict:
    """Bake the raw chip's directly-typed genotypes INTO the imputed AGI (lifting GRCh37→GRCh38).

    Imputation can lose a directly-typed common SNP (DR2=0 → dropped); the chip still holds it as a
    direct measurement. A chip hard-call WINS over the imputed call (which may be DR2=0 noise) and
    sites the imputed genome lost are inserted — so EVERY AGI consumer (nutrigenomics, variant.resolve,
    domains, …) sees the recovered genotype, not just the runtime fallback. Overlaid rows carry
    ``typed=1`` (graded A) and keep ``record_kind='variant_call'``. SNVs only (chips carry no usable
    indel representation). Idempotent. Returns counts."""
    from pyliftover import LiftOver
    chain = Path(chain_path) if chain_path else _overlay_chain()
    if chain is None or not Path(chain).exists():
        return {"status": "no_chain", "reason": "hg19ToHg38 liftover chain not found"}
    lo = LiftOver(str(chain))
    imp = sqlite3.connect(str(imputed_agi_path))
    cols = {r[1] for r in imp.execute("PRAGMA table_info(variants)")}
    if "typed" not in cols:
        imp.execute("ALTER TABLE variants ADD COLUMN typed INTEGER DEFAULT 0")
    chip = sqlite3.connect(str(chip_agi_path))
    rows = chip.execute(
        "SELECT rsid, chrom, pos, genotype, allele1, allele2, zygosity FROM variants "
        "WHERE record_kind='variant_call' AND length(allele1)=1 AND length(allele2)=1"
    ).fetchall()
    chip.close()
    n_lift = n_ins = n_upd = n_fail = 0
    imp.execute("BEGIN")
    for rsid, c37, p37, gt, a1, a2, zyg in rows:
        res = lo.convert_coordinate(f"chr{_norm_chrom(str(c37))}", int(p37) - 1)  # pyliftover is 0-based
        if not res:
            n_fail += 1
            continue
        c38 = res[0][0][3:] if res[0][0].startswith("chr") else res[0][0]
        p38 = res[0][1] + 1
        n_lift += 1
        hit = imp.execute("SELECT rowid FROM variants WHERE chrom=? AND pos=?", (c38, p38)).fetchone()
        if hit:
            imp.execute(
                "UPDATE variants SET rsid=?, genotype=?, allele1=?, allele2=?, zygosity=?, "
                "record_kind='variant_call', typed=1 WHERE rowid=?",
                (rsid, gt, a1, a2, zyg, hit[0]))
            n_upd += 1
        else:
            imp.execute(
                "INSERT INTO variants(rsid,chrom,pos,genotype,allele1,allele2,zygosity,record_kind,typed) "
                "VALUES(?,?,?,?,?,?,?,'variant_call',1)", (rsid, c38, p38, gt, a1, a2, zyg))
            n_ins += 1
    imp.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('chip_overlay','applied')")
    # keep the stored counts honest after inserting directly-typed rows (genome.summary reads a
    # live COUNT now, but the metadata should not lie either).
    n_called = imp.execute("SELECT COUNT(*) FROM variants WHERE record_kind='variant_call'").fetchone()[0]
    imp.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('n_variants',?)", (str(n_called),))
    imp.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('n_called',?)", (str(n_called),))
    imp.execute("COMMIT")
    imp.close()
    from ..runtime import paths as _paths
    _paths.secure_file(imputed_agi_path)  # personal genome index → owner-only
    return {"status": "ok", "chip_snvs": len(rows), "lifted": n_lift,
            "inserted": n_ins, "updated": n_upd, "lift_failed": n_fail}
