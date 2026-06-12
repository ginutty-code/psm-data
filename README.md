<<<<<<< HEAD
# PSM PetDataExtractor

This project is a specialized data extraction pipeline located within the `PSM_Data` directory. it is designed to collect comprehensive Hunter Pet information from Wowhead and Petopia for the World of Warcraft addon. The system automates the scraping of NPC metadata, models, spells, and coordinates, transforming them into optimized Lua data structures.

## Prerequisites

- **Python 3.10+**
- **Required Libraries:**
  - `requests`: For handling HTTP requests.
  - `beautifulsoup4`: For parsing HTML content.
  - `urllib3`: For robust retry logic.

## Project Configuration

The pipeline's directory structure and file naming conventions are centrally managed in `config.py`. This script serves as the source of truth for all scripts:

- **Path Centralization**: All input/output filenames and directory paths (like `EXTRACTED_DIR`, `MANUAL_DIR`, and `OUTPUT_DIR`) are defined here as constants. This makes it easy to reorganize the project without updating individual scripts.
- **Environment Setup**: It provides the `ensure_dirs()` utility function. Extraction scripts call this at the start of execution to automatically create any missing project folders.
- **Source of Truth**: By importing constants from this file, the pipeline ensures that Step 01's output path perfectly matches Step 02's input path, maintaining data integrity throughout the crawl.

### Directory Structure
- **`Extracted/`**: Stores intermediate data and raw CSVs scraped from Petopia and Wowhead.
- **`Manual/`**: Contains human-curated data, such as `record_overrides.csv` (for field-level corrections), skip lists, and note cleanup rules.
- **`Output/`**: The destination for the addon's `.lua` files and the consolidated `pet_data.csv` used as the generation source.

## Extraction Pipeline

The scripts must be run in numerical order. Each step validates its dependencies and supports resuming from previous progress.

| Step | Script | Description | Input | Output |
| :--- | :--- | :--- | :--- | :--- |
| 01 | `01_extract_petopia_npcs.py` | Scrapes NPC IDs and names from the Petopia Available Pets gallery. | Petopia Web | `petopia_npcs.csv` |
| 02 | `02_extract_petopia_data.py` | Fetches detailed metadata (taming skills, notes, appearance) for Step 01 IDs. | `petopia_npcs.csv` | `petopia_data.csv` |
| 03 | `03_clean_notes.py` | Cleans and filters raw Petopia notes, applying keyword filtering and cleanup rules. | `petopia_data.csv`, `notes_keywords.csv`, `notes_cleanup.csv` | `final_notes.csv` |
| 04 | `04_extract_wowhead_families.py` | Scrapes pet family metadata (expansion, icon, base stats) from Wowhead. | Wowhead Web | `wowhead_families.csv` | 
| 05 | `05_extract_wowhead_spells.py` | Scrapes and cleans spell descriptions from Wowhead for all family abilities. | `wowhead_families.csv`, `spells_mapping.csv` | `wowhead_spells.csv` |
| 06 | `06_generate_abilities_lua.py` | Generates the hierarchical `AbilitiesData.lua` for the addon. | `wowhead_families.csv`, `wowhead_spells.csv` | `AbilitiesData.lua` |
| 07 | `07_extract_wowhead_npcs.py` | Crawls Wowhead to list every tameable NPC belonging to known families. | `wowhead_families.csv` | `wowhead_npcs.csv` |
| 08 | `08_update_npcs.py` | Applies human-curated overrides from `npcs_update.csv` to the dataset. | `wowhead_npcs.csv`, `npcs_update.csv` | `wowhead_npcs.csv` |
| 09 | `09_extract_wowhead_data.py` | Enriches NPCs with Display IDs, coordinates, and patch info using stealth scraping. | `wowhead_npcs.csv`, `skip_npc_ids.csv` | `wowhead_data.csv` |
| 10 | `10_combine_data.py` | Merges sources and applies `record_overrides.csv` for final data consolidation. | `wowhead_data.csv`, `petopia_data.csv`, `final_notes.csv`, `skip_npc_ids.csv`, `skip_display_ids.csv`, `record_overrides.csv` | `pet_data.csv` |
| 11 | `11_generate_models_lua.py` | Generates `ModelsData.lua` (Family > Display ID > NPC) with location aggregation. | `pet_data.csv` | `ModelsData.lua` |
| 12 | `12_generate_coords_lua.py` | Generates `CoordsData.lua` mapping NPCs to zone coordinates and Map IDs. | `pet_data.csv` | `CoordsData.lua` |
| 13 | `13_generate_conditions_lua.py` | Generates `ConditionsData.lua` mapping NPC IDs to special conditions. | `pet_data.csv` | `ConditionsData.lua` |
| 14 | `14_generate_notes_lua.py` | Generates `NotesData.lua` with space-saving note deduplication logic. | `pet_data.csv` | `NotesData.lua` |

## Key Features

### Robust Scraping
- **Anti-Detection**: Scripts like `09_extract_wowhead_data.py` use a rotating pool of realistic browser headers, randomized request jitter, and a multi-tiered backoff strategy. If a 403 or 429 error occurs, the script enforces a cooldown and rebuilds the session to bypass IP-level throttling.
- **Maintenance Persistence**: The system identifies missing data (like the hardcoded "Whiptail" family logic in Step 03) and automatically fixes local caches during execution.

### Data Cleaning
The pipeline ensures data integrity through specialized cleaning logic at every stage:
- **Families**: Automatically patches incomplete Wowhead JavaScript data (e.g., injecting the missing Whiptail family) and normalizes field types.
- **Spells**: Transforms raw Wowhead tooltip HTML into readable text by resolving data placeholders (like attack power formulas), converting stylized spans into sub-headers, and applying manual categories/tags.
- **Notes**: Employs an aggressive multi-pass cleaner that strips redundant "Located in..." filler, enforces relevance via keyword filtering, and applies global search-and-replace rules from `notes_cleanup.csv`.
- **Taming Skills**: Normalizes Petopia skill strings by stripping redundant terminology (e.g., "Required Skill:") and aggregates these requirements across unique models (Display IDs) to ensure consistency.
- **Skip Lists**: Ensures data accuracy by filtering out NPCs that are no longer in-game, incorrectly marked as tameable, or lack sufficient location data (`skip_npc_ids.csv`). Similarly, `skip_display_ids.csv` removes display IDs that do not render correctly in-game.
- **NPC Metadata**: Hardened regex patterns handle Wowhead’s character escapes in names and classifications. Step 08 allows for manual identification corrections before the data is enriched.
- **Consolidation & Extraction**: The final merge applies high-priority overrides from `record_overrides.csv`. It also uses context-aware regex to "deduce" missing data, such as identifying faction-only tames or special item requirements (like Elusive Baits) based on the text of the cleaned notes.

## Usage

1. **Initialization**: Ensure `Manual/npcs_update.csv`, `Manual/skip_npc_ids.csv`, `Manual/skip_display_ids.csv`, `Manual/notes_cleanup.csv`, and `Manual/notes_keywords.csv` are populated.
2. **Execution**: Navigate to the `PSM_Data` directory and run scripts sequentially:
   ```bash
   cd PSM_Data
   python 01_petopia_npcs.py
   python 02_petopia_data.py
   # ... and so on
   ```
3. **Options**: 
   - Use `--refresh` on scrapers to bypass cached files.
   - Use `--delay X.X` to manually adjust the scraping speed.
   - Use `--reset` on Step 08 to clear scraping progress.

## Output Files

The addon expects the following files from the `Output/` folder:
- `AbilitiesData.lua`: Family ability mappings and spell descriptions.
- `ModelsData.lua`: Hierarchical model and NPC metadata.
- `CoordsData.lua`: Coordinate data for map integration.
- `NotesData.lua`: Curated flavor text and taming instructions.
- `TacticData.lua`: Tactical requirements for special tames.

---
*Generated by PSM PetDataExtractor Pipeline*
=======
# Hunter-Pet-Data
Collaboration space to share the hunter pet data and correct it.
>>>>>>> cf16e30145d1f6970e683ff8bab79fc9cf4cf195
