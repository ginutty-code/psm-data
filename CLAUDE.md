# PSM PetDataExtractor (psm-data)

A Python scraping/cleaning pipeline that turns Wowhead + Petopia pages into
the five `.lua` data tables consumed by the `psm-addon` repo (sibling,
`../psm-addon`) — hunter pet models, abilities, coordinates, taming
conditions, and notes.

For the full cross-repo picture — every pipeline stage as a diagram, which
`Manual/` CSV feeds which script, and the exact bridge point into the addon
— see `../architecture.html` (open in a browser, or `Read` it directly:
the node/edge data is plain JS literals, easy to parse as text).

## Pipeline shape

Numbered scripts run in order, each declaring its input/output paths via
`config.py` (the source of truth for `EXTRACTED_DIR`, `PROCESSED_DIR`,
`MANUAL_DIR`, `OUTPUT_DIR`):

1. **Extract** (`01`, `02`, `04`, `05`, `07`, `09`) — scrape raw data from
   Petopia/Wowhead into CSVs.
2. **Clean** (`03`, `08`, `10`) — apply hand-curated `Manual/*.csv`
   correction files (skip lists, ID remaps, keyword/location/spell
   overrides) on top of the raw scrape. `07 → 08 → 09` is one continuous
   chain: `08` applies `npcs_updates.csv` to `07`'s raw scrape, `09` reads
   that corrected list to pull coordinates and display IDs.
3. **Combine** (`11`) — merges into one master `pet_data.csv`.
4. **Generate** (`06`, `12`, `13`, `14`, `15`) — serialize the master data
   into `Output/{Abilities,Models,Coords,Conditions,Notes}Data.lua`.

One exception to the "corrections live in `Manual/`" rule: the missing
Whiptail family (id 315) is a constant hardcoded directly inside
`04_extract_wowhead_families.py`, not a `Manual/` CSV.

## Crossing into psm-addon

`sync.py` is the only thing that touches the other repo — run it explicitly
after regenerating (`python sync.py`) to copy the five compiled `Output/*.lua`
files into psm-addon. Four go to `../psm-addon/PetStableManagement_ModelsBrowser/Data/`
(the `ADDON_DATA_DIR` constant); `AbilitiesData.lua` goes to
`../psm-addon/PetStableManagement/Data/` instead (`CORE_ADDON_DATA_DIR`), because
the core addon's Owned Pets panel — always loaded, unlike the Models Browser — needs
it for its ability filter, and it's small enough (~34KB, vs hundreds of KB for its
siblings) that it doesn't need `LoadOnDemand`'s deferral. Both destination `Data/`
subfolders keep generated tables apart from their addon's hand-written Lua. Nothing
else in this pipeline should reach across the repo boundary, and the
`1x_generate_*.py` / `06_generate_*.py` scripts no longer sync as a side effect of
running — they only write to `Output/`.

Each generated file also stamps `PSM_DataSchemaVersion` (from `config.py`'s
`SCHEMA_VERSION`) at the top. The addon's `Schema.lua` asserts this on load
and fails with one clear error instead of every consumer hitting nil-index
errors independently. Bump `SCHEMA_VERSION` here and the matching constant in
`Schema.lua` together whenever a generated table's shape changes.

## Network resilience

Wowhead and Petopia both rate-limit/block under concurrent load, and the
scrapers vary in how much they defend against it:

- **`09_extract_wowhead_data.py`** is the reference implementation: a
  `threading.Lock`-guarded `global_backoff_until` timestamp that every
  worker thread checks before each request, tripped after `CONCURRENCY`
  consecutive failures in a row; a `stop_event` for graceful Ctrl+C
  shutdown mid-batch; and a thread-local `requests.Session` with a
  urllib3 `Retry` adapter for transient 429/5xx responses. It also tracks
  per-NPC status (`successful`/`skipped`/`retry`) as a CSV column, so a
  killed run resumes exactly where it left off.
- **`02_extract_petopia_data.py`** ports the same lock/backoff/stop_event/
  session pattern (added after repeated `ConnectTimeoutError`s under
  higher concurrency). It has no status column, so it resumes more simply:
  a still-failing NPC is just left out of the output CSV, and the next run
  picks it up because its `npc_id` isn't in `processed_npcs` yet.
- **`07_extract_wowhead_npcs.py`** has a lighter single-threaded
  exponential backoff on 403s only (no cross-thread coordination).
- **`01`, `04`, `05`** don't retry at all — smaller, less contentious
  endpoints, re-run manually if they fail.

If another scraper needs the same treatment, copy the pattern from `09` (or
`02`, which is the more minimal port) rather than inventing a new one.

`--delay` is accepted by both `07` and `09`; it overrides the built-in
delay only when explicitly passed (`default=None`, checked before falling
back to the module constant) — don't reintroduce a bare default here, or
it silently collapses `09`'s randomized jitter range to a fixed value on
every run, defeating the anti-detection jitter.

## Linting

`ruff check .` (`uvx ruff check .` if not installed locally) should report
zero warnings across all 15 scripts. One caveat: some editor Ruff/isort
integrations reformat the `from config import (...)` block into the same
group as `import requests`, without the blank line `ruff check` wants
before it (since `config` is a first-party local module, not third-party).
This produces a recurring, cosmetic `I001` warning that reappears after
edits in whichever file was last touched by that formatter — it's known
and accepted; don't chase it script-by-script.
