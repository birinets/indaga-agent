#!/usr/bin/env bash
# Regenerate llms-full.txt = llms.txt + the root and capability skills inlined.
set -euo pipefail
cd "$(dirname "$0")/.."
SKILLS=(skills/SKILL.md skills/genome/SKILL.md skills/domains/SKILL.md skills/nutrigenomics/SKILL.md
        skills/circadian/SKILL.md skills/labs/SKILL.md skills/metabolic/SKILL.md
        skills/health-index/SKILL.md skills/synthesis/SKILL.md skills/analyze/SKILL.md
        skills/output-rules.md skills/conventions/evidence-envelope.md)
{
  cat llms.txt
  for f in "${SKILLS[@]}"; do
    printf '\n\n================================================================\nFILE: %s\n================================================================\n\n' "$f"
    cat "$f"
  done
} > llms-full.txt
echo "wrote llms-full.txt ($(wc -l < llms-full.txt) lines)"
