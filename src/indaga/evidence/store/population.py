"""gnomAD population-frequency client (ported from HeathProject _pl_screen_core.py).

Live GraphQL against gnomAD r4 (GRCh38), with a persistent JSON cache under
``~/.indaga/gnomad_cache.json`` so a re-run is offline for already-seen variants.
Used by the P/LP screen's rare-variant filter (the common-false-alarm refutation)
and optionally by PGS allele-frequency fill-in. stdlib only.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ...runtime import paths

_GNOMAD_URL = "https://gnomad.broadinstitute.org/api"
# gnomAD datasets by build: GRCh38 → gnomad_r4, GRCh37 → gnomad_r2_1 (the chip is GRCh37).
_DATASET_BY_BUILD = {"GRCh38": "gnomad_r4", "GRCh37": "gnomad_r2_1"}
_QUERY = """
query VariantInfo($variantId: String!) {
  variant(variantId: $variantId, dataset: %s) {
    variantId
    rsids
    exome { ac an af }
    genome { ac an af }
  }
}
"""


class GnomadClient:
    """Caches gnomAD AF lookups by 'chrom-pos-ref-alt'. Dataset follows the genome build
    (GRCh37 → gnomad_r2_1, GRCh38 → gnomad_r4); cache keys are namespaced by dataset."""

    def __init__(self, cache_path: str | Path | None = None, *, online: bool = True,
                 build: str = "GRCh37", min_interval: float = 0.34, retries: int = 4) -> None:
        self._path = Path(cache_path or paths.gnomad_cache_path())
        self._online = online
        self._dataset = _DATASET_BY_BUILD.get(build, "gnomad_r4")
        self._min_interval = min_interval   # throttle: ~3 req/s, well under gnomAD's limit
        self._retries = retries
        self._cache: dict = {}              # successful lookups, persisted
        self._errors: dict = {}             # transient (this run only) — never persisted, retried next run
        self._last = 0.0
        if self._path.exists():
            try:
                self._cache = json.loads(self._path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                self._cache = {}
        self._dirty = False

    def variant_id(self, chrom: str, pos: int, ref: str, alt: str) -> str:
        return f"{str(chrom).replace('chr', '')}-{pos}-{ref}-{alt}"

    def _key(self, vid: str) -> str:
        return f"{self._dataset}:{vid}"

    def _http(self, vid: str, *, throttle: bool) -> dict:
        """One request with backoff retry. ``throttle`` serialises requests for the
        single-call path; the parallel prefetch passes throttle=False (workers + retry)."""
        payload = json.dumps({"query": _QUERY % self._dataset, "variables": {"variantId": vid}}).encode()
        req = urllib.request.Request(_GNOMAD_URL, data=payload,
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "Indaga/0.1"})
        backoff = 1.0
        last_err = None
        for attempt in range(self._retries):
            if throttle:
                gap = time.monotonic() - self._last
                if gap < self._min_interval:
                    time.sleep(self._min_interval - gap)
                self._last = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code in (429, 500, 502, 503, 504) and attempt < self._retries - 1:
                    time.sleep(backoff); backoff *= 2; continue
                raise
            except (urllib.error.URLError, TimeoutError, ValueError) as e:
                last_err = e
                if attempt < self._retries - 1:
                    time.sleep(backoff); backoff *= 2; continue
                raise
        raise last_err or RuntimeError("gnomad request failed")

    @staticmethod
    def _parse(body: dict) -> dict:
        data = (body.get("data") or {}).get("variant")
        if data is None:
            return {"af": None, "found": False}
        af = source = None
        for src in ("exome", "genome"):
            s = data.get(src)
            if s and s.get("af") is not None:
                af, source = s["af"], src
                break
        return {"af": af, "source": source, "found": True, "rsids": data.get("rsids") or []}

    def prefetch(self, variants, *, workers: int = 6) -> int:
        """Populate the cache for many (chrom,pos,ref,alt) in parallel. Returns the number
        newly fetched. After this, ``fetch`` for the same variants is an instant cache hit."""
        if not self._online:
            return 0
        todo = []
        for (chrom, pos, ref, alt) in variants:
            vid = self.variant_id(chrom, pos, ref, alt)
            key = self._key(vid)
            if key not in self._cache and key not in self._errors:
                todo.append((vid, key))
        if not todo:
            return 0
        n = 0
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(self._http, vid, throttle=False): (vid, key) for vid, key in todo}
            for fut in as_completed(futs):
                vid, key = futs[fut]
                try:
                    self._cache[key] = self._parse(fut.result())
                    self._dirty = True
                    n += 1
                except Exception as e:  # noqa: BLE001
                    self._errors[key] = {"error": str(e)}
        return n

    def fetch(self, chrom: str, pos: int, ref: str, alt: str) -> dict:
        """Return {af, source, found, rsids?} or {error}. Best of exome > genome.
        Errors are NOT persisted (so a later run retries), but are remembered for this
        run to avoid re-hammering the same failing variant."""
        vid = self.variant_id(chrom, pos, ref, alt)
        key = self._key(vid)
        if key in self._cache:
            return self._cache[key]
        if key in self._errors:
            return self._errors[key]
        if not self._online:
            return {"af": None, "found": False}
        try:
            body = self._http(vid, throttle=True)
        except Exception as e:  # noqa: BLE001 — surface as a transient, non-persisted error
            result = {"error": str(e)}
            self._errors[key] = result
            return result
        result = self._parse(body)
        self._cache[key] = result
        self._dirty = True
        return result

    def save(self) -> None:
        if self._dirty:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._cache, indent=2), encoding="utf-8")
            self._dirty = False
