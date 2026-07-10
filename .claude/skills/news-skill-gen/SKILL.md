---
name: news-skill-gen
description: Generate a new YAML bot news-skill (activation window, spread caps, risk multiplier) for a named economic event, based on the existing templates.
---

# News Skill Generator

Generate `backend/src/skills/news/<event>.yaml` for the event named in `$ARGUMENTS`.

## Steps
1. Read existing news skills (`nfp.yaml`, `cpi.yaml`, `fomc.yaml`,
   `generic_high_impact.yaml`) to match structure and conventions exactly.
2. Determine sensible defaults for the event: affected symbols (XAUUSD/XAGUSD
   react to USD macro; BTCUSD less so), window before/after, whether to flatten
   pre-event, post-event wait candles, max spread, risk multiplier ≤ 1.0.
3. Write the YAML with a comment header explaining the event and choices.
4. Validate it loads: `uv run pytest tests/unit/skills -k yaml` from `backend/`.

## Must never
- Set a `risk_multiplier` above 1.0 or remove `block_new_entries` from the
  pre-event window of a high-impact event.
- Touch `configs/risk.yaml`.
