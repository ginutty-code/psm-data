import os
import random

# Directories
EXTRACTED_DIR = 'Extracted'
PROCESSED_DIR = 'Processed'
MANUAL_DIR = 'Manual'
OUTPUT_DIR = 'Output'

# Extracted — raw, unaltered data from web sources
PETOPIA_NPCS_CSV = os.path.join(EXTRACTED_DIR, 'petopia_npcs.csv')
PETOPIA_DATA_CSV = os.path.join(EXTRACTED_DIR, 'petopia_data.csv')
WOWHEAD_FAMILIES_CSV = os.path.join(EXTRACTED_DIR, 'wowhead_families.csv')   # raw scrape before Whiptail injection
WOWHEAD_NPCS_CSV = os.path.join(EXTRACTED_DIR, 'wowhead_npcs.csv')            # raw scrape before corrections
WOWHWEAD_DATA_CSV = os.path.join(EXTRACTED_DIR, 'wowhead_data.csv')           # enriched per-NPC data from web
WOWHEAD_SPELLS_CSV = os.path.join(EXTRACTED_DIR, 'wowhead_spells.csv')        # raw scrape before cleaning

# Processed — transformed/enriched intermediate data (processed_ prefix distinguishes from raw originals)
PROCESSED_FAMILIES_CSV = os.path.join(PROCESSED_DIR, 'processed_wowhead_families.csv')
PROCESSED_SPELLS_CSV = os.path.join(PROCESSED_DIR, 'processed_wowhead_spells.csv')
FINAL_NOTES_CSV = os.path.join(PROCESSED_DIR, 'final_notes.csv')
PROCESSED_NPCS_CSV = os.path.join(PROCESSED_DIR, 'processed_wowhead_npcs.csv')
LOCATION_DATA_CSV = os.path.join(PROCESSED_DIR, 'location_data.csv')

# Manual — human-curated input files
NOTES_UPDATES_CSV = os.path.join(MANUAL_DIR, 'notes_updates.csv')
NOTES_KEYWORDS_CSV = os.path.join(MANUAL_DIR, 'notes_keywords.csv')
SPELLS_MAPPING_CSV = os.path.join(MANUAL_DIR, 'spells_mapping.csv')
UPDATE_NPC_CSV = os.path.join(MANUAL_DIR, 'update_npcs.csv')
SKIP_NPC_IDS_CSV = os.path.join(MANUAL_DIR, 'skip_npc_ids.csv')
SKIP_DISPLAY_IDS_CSV = os.path.join(MANUAL_DIR, 'skip_display_ids.csv')
RECORD_OVERRIDES_CSV = os.path.join(MANUAL_DIR, 'record_overrides.csv')

# Processed — intermediate data (step 10 output, consumed by Lua generators)
COMBINED_PET_DATA_CSV = os.path.join(PROCESSED_DIR, 'pet_data.csv')

# Output — final deliverables for the addon (.lua files only)
ABILITIES_LUA = os.path.join(OUTPUT_DIR, 'AbilitiesData.lua')
MODELS_LUA = os.path.join(OUTPUT_DIR, 'ModelsData.lua')
COORDS_LUA = os.path.join(OUTPUT_DIR, 'CoordsData.lua')
CONDITIONS_LUA = os.path.join(OUTPUT_DIR, 'ConditionsData.lua')
NOTES_LUA = os.path.join(OUTPUT_DIR, 'NotesData.lua')


def ensure_dirs():
    """Ensure that the standard project directories exist."""
    for d in [EXTRACTED_DIR, PROCESSED_DIR, MANUAL_DIR, OUTPUT_DIR]:
        if not os.path.exists(d):
            os.makedirs(d, exist_ok=True)


# Rotating realistic browser-like header sets (Firefox and Safari are generally more reliable for Wowhead)
_HEADER_POOL = [
    {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
        'Upgrade-Insecure-Requests': '1',
        'Referer': 'https://www.wowhead.com/',
        'DNT': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-origin',
    },
    {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
        'Upgrade-Insecure-Requests': '1',
        'Referer': 'https://www.wowhead.com/',
        'DNT': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-origin',
    },
    {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-CA,en;q=0.9',
        'Referer': 'https://www.bing.com/',
    },
    {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7',
        'Referer': 'https://www.wowhead.com/npcs',
    }
]


def get_random_headers():
    """Returns a tuple (index, headers_dict) for rotating browser fingerprints."""
    idx = random.randint(0, len(_HEADER_POOL) - 1)
    return idx, dict(_HEADER_POOL[idx])