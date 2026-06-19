"""
Structured citation store + inline-footnote machinery.

The project principle is that "every number a user sees traces to a citation".
Today citations are scattered as inline prose; this module centralises them so
each report can render numbered inline markers ``[1]`` that link to a single
bibliography at the foot of the document.

URLs are only attached where the identifier is verified. Entries without a URL
render as text — deliberately, so we never publish a guessed DOI/PMID. Enrich
``REGISTRY`` (or, later, an external ``shared/references.json``) as identifiers
are confirmed.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Reference:
    id: str
    title: str           # study title or topic
    authors: str         # e.g. "Mandsager K, et al."
    source: str          # journal / venue + year, e.g. "JAMA Network Open, 2018"
    url: str | None = None
    verified: bool = False  # True only when id/url has been checked


# Seed registry — extend as domains are migrated onto the kit.
REGISTRY: dict[str, Reference] = {
    "mandsager2018": Reference(
        id="mandsager2018",
        title="Cardiorespiratory fitness and long-term mortality",
        authors="Mandsager K, Harb S, Cremer P, et al.",
        source="JAMA Network Open, 2018;1(6):e183605",
        url="https://doi.org/10.1001/jamanetworkopen.2018.3605",
        verified=True,
    ),
    "cooper_norms": Reference(
        id="cooper_norms",
        title="Normative VO₂max values by age and sex (Cooper Institute reference tables)",
        authors="The Cooper Institute",
        source="Cooper Institute fitness norms (age/sex stratified)",
        url=None,
    ),
    "actn3_yang2003": Reference(
        id="actn3_yang2003",
        title="ACTN3 R577X genotype and human athletic performance",
        authors="Yang N, MacArthur DG, Gulbin JP, et al.",
        source="American Journal of Human Genetics, 2003;73(3):627–631",
        url=None,
    ),
    "heritage_bouchard2011": Reference(
        id="heritage_bouchard2011",
        title="Genomic predictors of the maximal O₂ uptake response to standardized "
              "exercise training (HERITAGE Family Study)",
        authors="Bouchard C, Sarzynski MA, Rankinen T, et al.",
        source="Journal of Applied Physiology, 2011;110(5):1160–1170",
        url=None,
    ),
    "ference2017": Reference(
        id="ference2017",
        title="LDL cholesterol is causally associated with atherosclerotic cardiovascular "
              "disease (EAS Consensus Panel statement)",
        authors="Ference BA, Ginsberg HN, Graham I, et al.",
        source="European Heart Journal, 2017;38(32):2459–2472",
        url=None,
    ),
    "cpic_slco1b1": Reference(
        id="cpic_slco1b1",
        title="CPIC guideline for SLCO1B1, ABCG2, CYP2C9 and statin-associated "
              "musculoskeletal symptoms",
        authors="Cooper-DeHoff RM, Niemi M, Ramsey LB, et al.",
        source="Clinical Pharmacology & Therapeutics, 2022;111(5):1007–1021",
        url=None,
    ),
    "gmi_bergenstal2018": Reference(
        id="gmi_bergenstal2018",
        title="Glucose Management Indicator (GMI): a new term for estimating A1C from "
              "continuous glucose monitoring",
        authors="Bergenstal RM, Beck RW, Close KL, et al.",
        source="Diabetes Care, 2018;41(11):2275–2280",
        url=None,
    ),
    "tir_battelino2019": Reference(
        id="tir_battelino2019",
        title="Clinical targets for continuous glucose monitoring data interpretation "
              "(International Consensus on Time in Range)",
        authors="Battelino T, Danne T, Bergenstal RM, et al.",
        source="Diabetes Care, 2019;42(8):1593–1603",
        url=None,
    ),
    "vilpa_stamatakis2022": Reference(
        id="vilpa_stamatakis2022",
        title="Association of wearable device-measured vigorous intermittent lifestyle "
              "physical activity (VILPA) with mortality",
        authors="Stamatakis E, Ahmadi MN, Gill JMR, et al.",
        source="Nature Medicine, 2022;28(12):2521–2529",
        url=None,
    ),
}


def esc(s: object) -> str:
    s = "" if s is None else str(s)
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


class RefCollector:
    """Per-report citation tracker. Numbers references in order of first use."""

    def __init__(self, registry: dict[str, Reference] | None = None):
        self.registry = registry if registry is not None else REGISTRY
        self.order: list[str] = []

    def cite(self, ref_id: str) -> str:
        """Return an inline superscript marker; registers the reference."""
        if ref_id not in self.registry:
            # Fail soft: a missing citation should never crash a report build,
            # but it should be visible during review.
            return f'<sup class="cite" title="unknown reference: {esc(ref_id)}">[?]</sup>'
        if ref_id not in self.order:
            self.order.append(ref_id)
        n = self.order.index(ref_id) + 1
        return f'<sup class="cite"><a href="#ref-{esc(ref_id)}">[{n}]</a></sup>'

    def bibliography_html(self) -> str:
        """Render the ordered bibliography, or '' if nothing was cited."""
        if not self.order:
            return ""
        items = []
        for rid in self.order:
            r = self.registry[rid]
            link = (f' <a href="{esc(r.url)}" target="_blank" rel="noopener">link</a>'
                    if r.url else "")
            unverified = "" if r.verified or not r.url else ' <span title="unverified">·</span>'
            items.append(
                f'<li id="ref-{esc(rid)}">'
                f'<span class="r-title">{esc(r.title)}</span>. '
                f'{esc(r.authors)} {esc(r.source)}.{link}{unverified}</li>'
            )
        return '<ol class="refs-list">\n' + "\n".join(items) + "\n</ol>"
