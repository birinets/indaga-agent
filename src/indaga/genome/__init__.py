"""Indaga genome engine — the Active Genome Index + evidence reuse.

Builds an own Active Genome Index (AGI) from a consumer chip (genotype + zygosity +
callability), mirroring a genome agent's records model, and surfaces clinical
evidence (ClinVar, PGS, PharmCAG) for the subject's variants. Genomic findings are
written back into the Active Health Index so DNA fuses with labs, CGM, and the
derived metrics — the thing a genomics-only agent cannot do.
"""
