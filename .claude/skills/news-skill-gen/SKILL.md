---
name: news-skill-gen
description: Generate a new YAML bot news-skill (activation window, spread caps, risk multiplier) for a named economic event, based on the existing templates.
---

# News Skill Generator

Generate `backend/src/skills/news/<event>.yaml` for the event named in
`$ARGUMENTS`, and wire it up in `configs/news.yaml` — the YAML file alone is
not enough (see step 3).

## Steps
1. Read existing news skills (`nfp.yaml`, `cpi.yaml`, `fomc.yaml`,
   `generic_high_impact.yaml`) to match structure and conventions exactly.
   Schema (parsed by `backend/src/container.py:_load_news_skills`, which
   globs every `*.yaml` under this directory automatically — dropping the
   file in is enough for it to be *loaded*, but not enough for it to
   *activate*, see step 3):
   ```yaml
   name: <matches the filename stem by convention>
   activation:
     calendar_event: ["Exact Event Title", "..."]  # informational only — see step 3
     window: { before_min: <int>, after_min: <int> }
     symbols: [XAUUSD, XAGUSD, ...]                 # must trade instruments this event moves
   rules:
     pre_event: { close_all: true, block_new_entries: true }
     post_event:
       wait_candles_m5: <int>       # bars to sit out after the release before re-entering
       strategy_override: ""        # "" = fall back to the symbol's normal-skill strategy
       max_spread_points: <int>     # 0 = no override, use the symbol's configured cap
       risk_multiplier: <float>     # <= 1.0, see "Must never"
   ```
2. Determine sensible defaults for the event: affected symbols (XAUUSD/XAGUSD
   react to USD macro; BTCUSD less so, mainly risk-sentiment events like
   FOMC), window before/after (scale with how violent/prolonged the release
   typically is — NFP/CPI are single-instant prints with narrower windows,
   FOMC is two-stage (statement + press conference) with the widest window),
   post-event wait candles, max spread, risk multiplier ≤ 1.0. Check
   `GET /news/upcoming` (backend running) or the raw calendar feed
   (`configs/news.yaml: calendar.source`, forexfactory/finnhub) for the
   **exact event title string** the calendar source publishes — the match in
   step 3 is case-insensitive but otherwise exact, so a title that doesn't
   match verbatim silently never activates this skill.
3. **Register it in `configs/news.yaml: tracked_events`** — this is the step
   the YAML file alone doesn't cover, and skipping it means the skill sits
   in memory unreachable while its event silently falls through to whatever
   `"*"`-wildcard entry matches its impact level (today: `generic_high_impact`
   for any high-impact event) instead of using the settings you just wrote.
   `NewsWindowService._resolve_window_spec` matches an incoming calendar
   event's name against `tracked_events[].name` (case-insensitive, exact
   otherwise) to find `.skill`, then looks that up in the skills loaded from
   this directory — a skill with no matching `tracked_events` entry is dead
   code. Add:
   ```yaml
   tracked_events:
     - { name: "Exact Event Title", impact: high, skill: <name> }
   ```
   before any existing `{ name: "*", ... }` wildcard entry (matching is
   first-hit-wins in file order — the loader tries every specific `name`
   first regardless of list position, but keep new entries above the
   wildcard for readability anyway).
4. Write the news-skill YAML with a comment header explaining the event and
   the reasoning behind the chosen window/wait/spread/risk values (see the
   existing four files for the tone — one paragraph on what the event is and
   why its numbers are what they are, not a restatement of the fields).
5. Validate both files actually parse and wire together — there is no
   existing pytest target for this (don't invoke `-k yaml`, nothing matches
   it), so exercise the real loaders directly:
   ```bash
   cd backend && uv run python -c "
   from pathlib import Path
   from src.container import _load_news_skills
   from src.shared.config.loaders import load_news_config
   from src.shared.config.settings import Settings

   skills = _load_news_skills()
   assert '<name>' in skills, sorted(skills)
   news_config = load_news_config(Settings().configs_dir)
   matched = [t for t in news_config.tracked_events if t.skill == '<name>']
   assert matched, 'no tracked_events entry points at this skill'
   print('OK:', skills['<name>'], matched)
   "
   ```
   Then run the existing news-skill test suites to make sure nothing else
   broke: `uv run pytest tests/unit/skills tests/unit/news` from `backend/`.

## Must never
- Set a `risk_multiplier` above 1.0 or remove `block_new_entries` from the
  pre-event window of a high-impact event.
- Touch `configs/risk.yaml` (`configs/news.yaml` is a normal reviewed config,
  not user-owned like `risk.yaml` — editing it in step 3 is expected).
