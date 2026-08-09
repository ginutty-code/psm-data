import os
import random

# Directories
EXTRACTED_DIR = 'psm-data/Extracted'
MANUAL_DIR = 'psm-data/Manual'
PROCESSED_DIR = 'psm-data/Processed'
OUTPUT_DIR = 'psm-data/Output'

# Extracted — raw, unaltered data from web sources
PETOPIA_NPCS_CSV = os.path.join(EXTRACTED_DIR, 'petopia_npcs.csv')
PETOPIA_DATA_CSV = os.path.join(EXTRACTED_DIR, 'petopia_data.csv')
WOWHEAD_NPCS_CSV = os.path.join(EXTRACTED_DIR, 'wowhead_npcs.csv')            # raw scrape before corrections
WOWHEAD_DATA_CSV = os.path.join(EXTRACTED_DIR, 'wowhead_data.csv')           # enriched per-NPC data from web
WOWHEAD_FAMILIES_CSV = os.path.join(EXTRACTED_DIR, 'wowhead_families.csv')   # raw scrape before Whiptail injection
WOWHEAD_SPELLS_CSV = os.path.join(EXTRACTED_DIR, 'wowhead_spells.csv')        # raw scrape before cleaning

# Manual — human-curated input files
SKIP_NPC_IDS_CSV = os.path.join(MANUAL_DIR, 'skip_npc_ids.csv')
SKIP_DISPLAY_IDS_CSV = os.path.join(MANUAL_DIR, 'skip_display_ids.csv')
NOTES_UPDATES_CSV = os.path.join(MANUAL_DIR, 'notes_updates.csv')
NOTES_KEYWORDS_CSV = os.path.join(MANUAL_DIR, 'notes_keywords.csv')
TAMING_UPDATES_CSV = os.path.join(MANUAL_DIR, 'taming_updates.csv')
NPC_UPDATES_CSV = os.path.join(MANUAL_DIR, 'npcs_updates.csv')
LOCATION_UPDATES_CSV = os.path.join(MANUAL_DIR, 'location_updates.csv')
SPELLS_MAPPING_CSV = os.path.join(MANUAL_DIR, 'spells_mapping.csv')
RECORD_OVERRIDES_CSV = os.path.join(MANUAL_DIR, 'record_overrides.csv')

# Processed — transformed/enriched intermediate data (processed_ prefix distinguishes from raw originals)
PROCESSED_PETOPIA_DATA_CSV = os.path.join(PROCESSED_DIR, 'processed_petopia_data.csv')
PROCESSED_NPCS_CSV = os.path.join(PROCESSED_DIR, 'processed_wowhead_npcs.csv')
PROCESSED_WOWHEAD_DATA_CSV = os.path.join(PROCESSED_DIR, 'processed_wowhead_data.csv')
PROCESSED_FAMILIES_CSV = os.path.join(PROCESSED_DIR, 'processed_wowhead_families.csv')
PROCESSED_SPELLS_CSV = os.path.join(PROCESSED_DIR, 'processed_wowhead_spells.csv')

# Processed — master file combining all relevant data for final output generation (pet_data.csv is the main source for the addon)
COMBINED_PET_DATA_CSV = os.path.join(PROCESSED_DIR, 'pet_data.csv')

# Output — final deliverables for the addon (.lua files only)
ABILITIES_LUA = os.path.join(OUTPUT_DIR, 'AbilitiesData.lua')
MODELS_LUA = os.path.join(OUTPUT_DIR, 'ModelsData.lua')
COORDS_LUA = os.path.join(OUTPUT_DIR, 'CoordsData.lua')
CONDITIONS_LUA = os.path.join(OUTPUT_DIR, 'ConditionsData.lua')
NOTES_LUA = os.path.join(OUTPUT_DIR, 'NotesData.lua')

ADDON_MODELS_BROWSER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'psm-addon', 'PetStableManagement_ModelsBrowser', 'ModelsBrowser'))


def ensure_dirs():
    """Ensure that the standard project directories exist."""
    for d in [EXTRACTED_DIR, PROCESSED_DIR, MANUAL_DIR, OUTPUT_DIR, ADDON_MODELS_BROWSER_DIR]:
        if not os.path.exists(d):
            os.makedirs(d, exist_ok=True)


def sync_output_to_addon(target_file=None):
    """Sync file(s) from Output directory to the addon directory."""
    import shutil
    ensure_dirs()
    if target_file:
        files = [target_file]
    else:
        files = [ABILITIES_LUA, MODELS_LUA, COORDS_LUA, CONDITIONS_LUA, NOTES_LUA]

    for src in files:
        if os.path.exists(src):
            filename = os.path.basename(src)
            dest = os.path.join(ADDON_MODELS_BROWSER_DIR, filename)
            shutil.copy2(src, dest)
            print(f"Synced {filename} -> {dest}")


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