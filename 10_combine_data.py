"""
Generate a consolidated pet dataset by merging Wowhead and Petopia data files.

The pipeline follows these strict steps:
1. Initial Filtering: Load Wowhead records and filter them by NPC ID skip lists and successful status.
2. Taming Skill Aggregation (by Display ID): Collect and consolidate Petopia taming skills and manual overrides, mapping them to unique display IDs (excluding skipped ones).
3. Core Data Merge & Override Application: Combine filtered Wowhead data with Petopia details and cleaned notes. Then, apply manual record overrides, which can supersede previously merged data.
4. Contextual Condition & Requirement Extraction: Analyze the merged notes and NPC reaction data to identify special taming conditions and item-based taming requirements.
5. Final Output: Construct the complete dataset, incorporating all derived information, and save it.
"""

import csv
import os
import re
import json
from config import (
    WOWHWEAD_DATA_CSV, PETOPIA_DATA_CSV, SKIP_NPC_IDS_CSV, SKIP_DISPLAY_IDS_CSV,
    RECORD_OVERRIDES_CSV, COMBINED_PET_DATA_CSV, FINAL_NOTES_CSV,
    ensure_dirs
)

EXPANSION_MAPPING = {
    1: "Vanilla", 2: "The Burning Crusade", 3: "Wrath of the Lich King",
    4: "Cataclysm", 5: "Mists of Pandaria", 6: "Warlords of Draenor",
    7: "Legion", 8: "Battle for Azeroth", 9: "Shadowlands",
    10: "Dragonflight", 11: "The War Within", 12: "Midnight", 13: "The Last Titan"
}

TYPE_MAP = {
    '1': 'Beast', '2': 'Dragonkin', '4': 'Elemental',
    '6': 'Undead', '9': 'Mechanical', '15': 'Aberration'
}

# Unified Category Mapping: Maps keywords to (Category, Normalized Value)
CATEGORY_MAP = {
    "Instance": ["Dungeon", "Raid", "Scenario", "Delve", "Battleground", "Torghast"],
    "World Event": ["N'Zoth Assault", "Faction Assault", "Covenant Assault", "Fyrakk Assault", "Void Assault",
                    "Legion Invasion", "Void Invasion", "Garrison Invasion",
                    "Void Strike", "Ritual Site", "Runestone Defense", 
                    "Superbloom", "Grand Hunt", "Community Feast", "Researchers Under Fire", "Time Rift", "Dreamsurge", 
                    "Worldsoul Memory", "World Quest"],
    "Seasonal Event": ["Brewfest", "Feast of Winter Veil", "Love is in the Air", "Hallow's End", "Lunar Festival", "Midsummer Fire Festival", "Noblegarden", "Children's Week", "Pirates' Day", "Day of the Dead", "Pilgrim's Bounty"],
    "Profession": ["Herbalism", "Skinning", "Leatherworking", "Mining", "Blacksmithing", "Siren's Sting", "Elusive Creature Bait", "Elusive Creature Lure"],
    "Covenant": ["Kyrian", "Necrolord", "Night Fae", "Venthyr"],
    "Prerequisite": ["Reputation", "Achievement", "Quest", "Garrison", "Campaign"],
    "Miscellaneous": ["Disturbed Earth", "N'lyeth, Sliver of N'Zoth"],
    "Faction": ["Alliance", "Horde"],
    "Race": ["Blood Elf", "Dark Iron Dwarf", "Dracthyr", "Draenei", "Dwarf", "Earthen","Pandaren", "Gnome", "Goblin", "Haranir", "Highmountain Tauren", "Human", "Kul Tiran","Lightforged Draenei", "Mag'har Orc", "Mechagnome", "Night Elf", "Nightborne","Orc", "Tauren", "Troll", "Undead", "Void Elf", "Vulpera", "Worgen"]
}

CONDITION_NORMALIZATION = {
    # Normalization Aliases (Synonyms back to standard terms)
    "Questline": "Quest","Storyline": "Quest","Quest Chain": "Quest",

    # Profession Item mapping to parent profession
    "Siren's Sting": "Herbalism (Siren's Sting)",
    "Elusive Creature Bait": "Skinning (Elusive Creature Bait)",
    "Elusive Creature Lure": "Skinning (Elusive Creature Lure)",

    # Scenario Aggregation
    "Island Expeditions": "Scenario", "Kvaldir Invasion": "Scenario", "Mogu Invasion": "Scenario",
    "Horrific Vision": "Scenario",

    # Invasion Aggregation
    "Greater Invasion Point": "Legion Invasion", "Invasion Point": "Legion Invasion",
    "Iron Horde garrison invasion": "Garrison Invasion",

    # Assault Aggregation
    "all Assaults": "N'Zoth Assault", "Assault phase": "N'Zoth Assault", "Assault phases": "N'Zoth Assault", "all Assaults phases": "N'Zoth Assault", "N'Zoth Invasion": "N'Zoth Assault",
    "Amathet Assault": "N'Zoth Assault", "Black Empire Assault": "N'Zoth Assault", "Aqir Unearthed Assault": "N'Zoth Assault", "Mantid Assault": "N'Zoth Assault", "Mogu Assault": "N'Zoth Assault",
    "Horde assaults": "Faction Assault", "Alliance assaults": "Faction Assault",
    "Venthyr Assault": "Covenant Assault", "Kyrian Assault": "Covenant Assault", "Night Fae Assault": "Covenant Assault", "Necrolord Assault": "Covenant Assault",
    
    # Plural to Singular normalization
    "Draenai": "Draenei", "Lightforge Draenai": "Lightforged Draenei", "Forsaken": "Undead",
    "Humans": "Human", "Dwarves": "Dwarf", "Orcs": "Orc", "Trolls": "Troll", "Taurens": "Tauren",
    "Gnomes": "Gnome", "Goblins": "Goblin", "Pandarens": "Pandaren", "Night Elves": "Night Elf",
    "Blood Elves": "Blood Elf", "Void Elves": "Void Elf", "Lightforged": "Lightforged Draenei",
    "Lightforged Draeneis": "Lightforged Draenei", "Dark Iron": "Dark Iron Dwarf",
    "Dark Iron Dwarves": "Dark Iron Dwarf", "Highmountain": "Highmountain Tauren",
    "Highmountain Taurens": "Highmountain Tauren", "Zandalari": "Zandalari Troll",
    "Zandalari Trolls": "Zandalari Troll", "Mag'har": "Mag'har Orc", "Mag'har Orcs": "Mag'har Orc",
    "Kul Tirans": "Kul Tiran", "Mechagnomes": "Mechagnome",
    "Assaults": "Assault", "Invasions": "Invasion", "Void Strikes": "Void Strike", "Void Assaults": "Void Assault", "World Quests": "World Quest"
}

def is_proper_name(text):
    """Validates if a string looks like a proper name (Title Case, quoted, or specific allowed formats)."""
    text = text.strip()
    if not text or len(text) < 3:
        return False
    # Allow quoted strings
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return True
    # Reject if it contains common lowercase sentence words not usually in WoW titles
    if re.search(r'\b(is|are|was|were|the|at|in|on|by|of|to|has|had|been|seventh|first|boss|after|only)\b', text):
        # Allow "The" and "of" if they are part of a Title Case sequence
        if not re.match(r'^([A-Z][\w\']*\b\s*|the\s|of\s)+$', text, re.IGNORECASE):
            return False
    # Ensure it starts with a Capital or Number
    if not (text[0].isupper() or text[0].isdigit()):
        return False
    return True


NEGATIONS = ("not ", "never ", "doesn't ", "don't ", "isn't ", "aren't ", "cannot ", "can't ", "pre-", "pre ", "older ", "except ")
# Helper to build context-aware patterns for Race and Faction
def _build_contextual_patterns(item, is_faction=False):
    escaped = re.escape(item)
    prefix = r'(?:(?:Alliance|Horde)\s+)?' if not is_faction else ''
    return [
        re.compile(r'(?i)\b' + prefix + escaped + r' hunters? (?:.*?)\bcan\b'),
        re.compile(r'(?i)\b(?:only (?:ever )?(?:available|accessible|tameable|visible) (?:to|during)|tameable by)\s+(?:an? |the )?' + prefix + escaped + r'\b'),
        re.compile(r'(?i)\bif you\'re (?:an? |the )?' + prefix + escaped + r'\b'),
        re.compile(r'(?i)\b' + prefix + escaped + r' (?:only|starting|players?|characters?|allied(?: race)?)\b'),
        re.compile(r'(?i)\b' + prefix + escaped + r'-only\b'),
        re.compile(r'(?i)\bfor (?:an? |the )?' + prefix + escaped + r' (?:hunters?|players?|characters?)\b'),
    ]

# Derive Race and Faction search terms from CATEGORY_MAP and Normalization Aliases
def _get_category_keywords(category_name):
    base_terms = set(CATEGORY_MAP.get(category_name, []))
    aliases = [k for k, v in CONDITION_NORMALIZATION.items() if v in base_terms]
    return sorted(list(base_terms) + aliases, key=len, reverse=True)

# Pre-compiled at module load — no re-compilation during the main loop
CATEGORY_PATTERNS = {}
for cat in CATEGORY_MAP.keys():
    for kw in _get_category_keywords(cat):
        CATEGORY_PATTERNS[(cat, kw)] = re.compile(r'(?i)\b' + re.escape(kw) + r's?\b')

RACE_SEARCH_TERMS = _get_category_keywords("Race")
FACTION_SEARCH_TERMS = _get_category_keywords("Faction")

RACE_PATTERNS = {item: _build_contextual_patterns(item) for item in RACE_SEARCH_TERMS}
FACTION_PATTERNS = {f: _build_contextual_patterns(f, is_faction=True) for f in FACTION_SEARCH_TERMS}

FACTION_NAMES = CATEGORY_MAP["Faction"]

# --- Helpers ---

def clean_taming_skill(skill):
    if not skill:
        return ""
    skill = skill.replace("Required Skill:", "").strip()
    skill = re.sub(r'\s*(?:Taming|Family)$', '', skill, flags=re.IGNORECASE)
    skill = skill.strip()
    return CONDITION_NORMALIZATION.get(skill, skill)

def get_expansion(patch_id):
    if not patch_id:
        return ""
    try:
        return EXPANSION_MAPPING.get(int(str(patch_id).split('.')[0]), "")
    except (ValueError, IndexError):
        return ""

def _read_first_col(path, col_names):
    """Generic loader: returns a set of stripped string values from the first matching column."""
    result = set()
    if not os.path.exists(path):
        return result
    with open(path, 'r', encoding='utf-8-sig', newline='', errors='replace') as f:
        reader = csv.DictReader(f)
        for row in reader:
            for key in row:
                clean_key = key.strip().replace('\ufeff', '')
                if clean_key in col_names:
                    val = row[key]
                    if val:
                        result.add(str(val).strip())
                    break
    return result

def load_skip_ids():
    return _read_first_col(SKIP_NPC_IDS_CSV, {'npc_id'})

def load_skip_display_ids():
    return _read_first_col(SKIP_DISPLAY_IDS_CSV, {'id', 'display_id'})

def load_petopia_data():
    data = {}
    if os.path.exists(PETOPIA_DATA_CSV):
        with open(PETOPIA_DATA_CSV, 'r', encoding='utf-8', errors='replace') as f:
            for row in csv.DictReader(f):
                npc_id = row.get('npc_id')
                if npc_id:
                    data[npc_id.strip()] = row
    return data

def load_record_overrides():
    overrides = {}
    if os.path.exists(RECORD_OVERRIDES_CSV):
        with open(RECORD_OVERRIDES_CSV, 'r', encoding='utf-8-sig', errors='replace') as f:
            for row in csv.DictReader(f):
                npc_id = row.get('npc_id', '').strip()
                zone_id = row.get('zone_id', '').strip()
                if npc_id and zone_id:
                    overrides[(npc_id, zone_id)] = {k: v for k, v in row.items() if v.strip()}
    return overrides

def load_final_notes():
    """Loads pre-cleaned notes from the external processing script."""
    notes_map = {}
    if os.path.exists(FINAL_NOTES_CSV):
        with open(FINAL_NOTES_CSV, 'r', encoding='utf-8-sig', errors='replace') as f:
            for row in csv.DictReader(f):
                npc_id = row.get('npc_id', '').strip()
                if npc_id:
                    notes_map[npc_id] = row.get('notes', '').strip()
    return notes_map

# --- Condition extraction (note-scoped, cached) ---

def extract_note_conditions(final_notes):
    """
    Extract all non-faction, non-row-specific conditions from a note string.
    Results are cached by the caller; this should only run once per unique note.
    """
    npc_conditions = set()

    # Split note into segments to avoid extracting conditions from "Not Tameable" sections
    segments = re.split(r'[.;:!]', final_notes)
    for segment in segments:
        seg_lower = segment.lower()
        if any(neg in seg_lower for neg in ["not tameable", "cannot be tamed"]):
            continue

        # 1. Standard Categories (Collect all matches in segment first)
        segment_tags = set()
        all_category_matches = []
        for (cat, kw), pattern in CATEGORY_PATTERNS.items():
            if cat in ("Race", "Faction"): continue # Use context-aware scanning for these instead
            for match in pattern.finditer(segment):
                pre_text = segment[max(0, match.start() - 40):match.start()].lower()
                is_negated = False
                for neg in NEGATIONS:
                    if neg in pre_text:
                        # Ignore general "not" if it's part of an inclusionary "not just" phrase
                        if neg == "not " and "not just " in pre_text:
                            continue
                        is_negated = True
                        break
                if is_negated:
                    continue
                
                val = CONDITION_NORMALIZATION.get(kw, kw)
                all_category_matches.append((cat, val, match.start(), match.end()))

        # Sort by match length descending so longer matches are processed first
        # Then filter out matches contained within longer matches to avoid redundancy
        # e.g. "Greater Invasion Point" suppresses "Invasion Point" and "Invasion"
        all_category_matches.sort(key=lambda m: m[3] - m[2], reverse=True)
        covered_ranges = []
        for cat, val, start, end in all_category_matches:
            is_contained = False
            for cs, ce in covered_ranges:
                if start >= cs and end <= ce:
                    is_contained = True
                    break
            if not is_contained:
                segment_tags.add((cat, val))
                covered_ranges.append((start, end))

        # Refinement: If "World Event: World Quest" matches, suppress the generic "Prerequisite: Quest" 
        # because World Quests are better categorized as events.
        if any(c == "World Event" and v == "World Quest" for c, v in segment_tags):
            segment_tags = { (c, v) for c, v in segment_tags if not (c == "Prerequisite" and v == "Quest") }

        # Refinement: If an Instance condition is present (e.g. Island Expeditions Scenario),
        # suppress generic "Invasion" and "Assault" World Event matches, as these are often
        # scenario-internal mechanics rather than open-world events.
        if any(c == "Instance" for c, v in segment_tags):
            segment_tags = { (c, v) for c, v in segment_tags if not (c == "World Event" and v in ("Invasion", "Assault")) }

        for c, v in segment_tags:
            npc_conditions.add(f"{c}: {v}")

        # Context-aware races
        for item in RACE_SEARCH_TERMS:
            for pattern in RACE_PATTERNS[item]:
                for match in pattern.finditer(segment):
                    pre_text = segment[max(0, match.start() - 40):match.start()].lower()
                    if any(neg in pre_text for neg in NEGATIONS):
                        continue
                    val = CONDITION_NORMALIZATION.get(item, item)
                    npc_conditions.add(f"Race: {val}")
                    break

    # Final deduplication: remove generic category values if a specific parenthesized version exists
    # e.g. Removes 'Profession: Herbalism' if 'Profession: Herbalism (Siren's Sting)' is present.
    if npc_conditions:
        specific_parents = { c.split(" (")[0] for c in npc_conditions if "(" in c and ":" in c }
        return [c for c in npc_conditions if c not in specific_parents]
    return []


def check_explicit_faction(faction_name, final_notes):
    """Check whether a note explicitly mentions a faction requirement."""
    segments = re.split(r'[.;:!]', final_notes)
    for segment in segments:
        seg_lower = segment.lower()
        if "not tameable" in seg_lower or "cannot be tamed" in seg_lower:
            continue

        for pattern in FACTION_PATTERNS[faction_name]:
            for match in pattern.finditer(segment):
                pre_text = segment[max(0, match.start() - 40):match.start()].lower()
                if not any(neg in pre_text for neg in NEGATIONS):
                    return True
    return False


# --- Main ---

def main():
    print("Starting final pet data generation...")
    ensure_dirs()

    skip_ids = load_skip_ids()
    print(f"Loaded {len(skip_ids)} NPC IDs to skip.")

    skip_display_ids = load_skip_display_ids()
    print(f"Loaded {len(skip_display_ids)} display IDs to skip.")

    petopia_info = load_petopia_data()
    print(f"Loaded Petopia info for {len(petopia_info)} NPCs.")

    final_notes_map = load_final_notes()
    print(f"Loaded {len(final_notes_map)} pre-cleaned notes.")

    full_record_overrides = load_record_overrides()
    print(f"Loaded {len(full_record_overrides)} record overrides.")

    if not os.path.exists(WOWHWEAD_DATA_CSV):
        print(f"Error: {WOWHWEAD_DATA_CSV} not found. Run step wowhead_data.py script first.")
        return

    # Group overrides by NPC ID for O(1) lookup in pass 1
    overrides_by_npc = {}
    for (n_id, z_id), override in full_record_overrides.items():
        overrides_by_npc.setdefault(n_id, []).append(override)

    columns = [
        'npc_id', 'npc_name', 'family_id', 'family_name', 'display_ids',
        'zone_id', 'zone_name', 'uiMapId', 'uiMapName', 'coords',
        'patch_id', 'patch_name', 'expansion', 'react', 'classification_id',
        'classification_name', 'type_id', 'type_name',
        'tamingskillname1', 'tamingskilldesc1', 'tamingskillname2',
        'tamingskilldesc2', 'notes', 'taming_requirements', 'special_conditions'
    ]

    print("Loading and filtering Wowhead records...")
    wowhead_records = []
    with open(WOWHWEAD_DATA_CSV, 'r', encoding='utf-8', errors='replace') as f:
        for row in csv.DictReader(f):
            npc_id = row.get('npc_id', '').strip()
            if npc_id and npc_id not in skip_ids and row.get('status') == 'successful':
                wowhead_records.append(row)

    # Pass 1: build display_id → taming skills map
    print("First pass: Aggregating taming requirements...")
    display_to_taming = {}
    npc_skill_map = {}

    for row in wowhead_records:
        npc_id = row['npc_id']
        if npc_id not in npc_skill_map:
            p_info = petopia_info.get(npc_id, {})
            skills = []
            for key in ('tamingskillname1', 'tamingskillname2'):
                s = p_info.get(key)
                if s:
                    cleaned = clean_taming_skill(s)
                    if cleaned:
                        skills.append(cleaned)
            for override in overrides_by_npc.get(npc_id, []):
                if 'taming_requirements' in override:
                    for s in override['taming_requirements'].split('|'):
                        cleaned = clean_taming_skill(s)
                        if cleaned and cleaned not in skills:
                            skills.append(cleaned)
            npc_skill_map[npc_id] = skills

        for d_id in (d.strip() for d in row.get('display_ids', '').split('|') if d.strip()):
            if d_id not in skip_display_ids:
                display_to_taming.setdefault(d_id, set()).update(npc_skill_map[npc_id])

    # Pre-parse every unique react string once (only 15 unique values empirically)
    react_parse_cache = {}
    def parse_react(react_str):
        if react_str not in react_parse_cache:
            v_a, v_h = 999, 999
            if react_str:
                try:
                    vals = json.loads(react_str)
                    if isinstance(vals, list) and len(vals) >= 2:
                        v_a, v_h = vals[0], vals[1]
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
            react_parse_cache[react_str] = (v_a, v_h)
        return react_parse_cache[react_str]

    # Pass 2: generate final rows
    print("Second pass: Generating final rows...")
    final_rows = []
    # Cache note-scoped conditions (expensive regex work, keyed by cleaned note text)
    conditions_cache = {}
    # Cache faction scan results per note (also note-scoped)
    faction_note_cache = {}
    # Master cache: (notes, react) -> (npc_conditions_base, v_a, v_h)
    # Covers ~80% of rows that share the same note+react combo
    combo_cache = {}

    for row in wowhead_records:
        npc_id = row['npc_id']

        p_info = petopia_info.get(npc_id, {})

        # Pre-override display IDs from Wowhead
        display_ids_str = row.get('display_ids', '').strip()
 
        override = full_record_overrides.get((npc_id, row.get('zone_id', '').strip()), {})
        current_zone_id = row.get('zone_id', '').strip()
        override = full_record_overrides.get((npc_id, current_zone_id), {})

        # Fallback to bulk_zone_id if no override found and zone_id is empty
        if not override and not current_zone_id:
            for b_id in (b.strip() for b in row.get('bulk_zone_id', '').split('|') if b.strip()):
                override = full_record_overrides.get((npc_id, b_id), {})
                if override:
                    break
 
        patch_id = row.get('patch_id', '').strip()
        type_id = row.get('type', '').strip()

        record_data = {
            'npc_id': npc_id,
            'npc_name': row.get('displayName') or row.get('npc_name', ''),
            'family_id': row.get('family_id') or row.get('bulk_family_id', ''),
            'family_name': row.get('bulk_family_name', ''),
            'display_ids': display_ids_str,
            'zone_id': row.get('zone_id', '').strip(),
            'zone_name': row.get('zone_name', '').strip(),
            'uiMapId': row.get('uiMapId', '').strip(),
            'uiMapName': row.get('uiMapName', '').strip(),
            'coords': row.get('coords', '').strip(),
            'patch_id': patch_id,
            'patch_name': row.get('patch_name', ''),
            'expansion': get_expansion(patch_id),
            'react': row.get('react', ''),
            'classification_id': row.get('classification_id', ''),
            'classification_name': row.get('bulk_classification', ''),
            'type_id': type_id,
            'type_name': TYPE_MAP.get(type_id, ''),
            'tamingskillname1': p_info.get('tamingskillname1', ''),
            'tamingskilldesc1': p_info.get('tamingskilldesc1', ''),
            'tamingskillname2': p_info.get('tamingskillname2', ''),
            'tamingskilldesc2': p_info.get('tamingskilldesc2', ''),
            'notes': final_notes_map.get(npc_id, ""),
            'taming_requirements': "",
            'special_conditions': ""
        }

        # Apply manual record overrides (which could change display_ids)
        record_data.update(override)

        # Now filter display IDs against the skip list, after overrides have been applied
        display_ids_list = [d.strip() for d in record_data.get('display_ids', '').split('|') if d.strip()]
        allowed_display_ids = [d for d in display_ids_list if d not in skip_display_ids]
        if not allowed_display_ids:
            continue

        # Update record with filtered display IDs for final output
        record_data['display_ids'] = '|'.join(allowed_display_ids)

        final_notes = record_data.get('notes', '')
        final_react = record_data.get('react', '')

        # Aggregate taming set from display IDs (row-specific)
        npc_taming_set = set()
        for d_id in allowed_display_ids:
            npc_taming_set.update(display_to_taming.get(d_id, set()))

        # (notes, react) combo cache — covers ~80% of rows
        combo_key = (final_notes, final_react)
        if combo_key not in combo_cache:
            # Note-scoped conditions
            if final_notes not in conditions_cache:
                conditions_cache[final_notes] = extract_note_conditions(final_notes)
            base_conditions = list(conditions_cache[final_notes])
            note_segments = re.split(r'[.;:!]', final_notes)

            v_a, v_h = parse_react(final_react)
            row_factions = set()
            is_explicitly_universal = False

            # Note-based explicit faction scan (cached per note)
            if final_notes not in faction_note_cache:
                found = set()
                for f in FACTION_NAMES:
                    if check_explicit_faction(f, final_notes):
                        found.add(f"Faction: {f}")
                faction_note_cache[final_notes] = found
            row_factions.update(faction_note_cache[final_notes])

            # Check for universal phrases that signal the pet is for everyone
            for segment in note_segments:
                seg_lower = segment.lower()
                if any(p in seg_lower for p in ["visible to all", "tameable by all", "available to all"]):
                    is_explicitly_universal = True
                    break

            # Fallback: implied faction from restriction phrases
            if not row_factions and not is_explicitly_universal:
                for segment in note_segments:
                    seg_lower = segment.lower()
                    if "not tameable" in seg_lower or "cannot be tamed" in seg_lower:
                        continue
                    res_a = any(phrase in seg_lower for phrase in ["friendly to alliance", "not visible to alliance", "doesn't appear to be visible to alliance"])
                    res_h = any(phrase in seg_lower for phrase in ["friendly to horde", "not visible to horde", "doesn't appear to be visible to horde"])
                    if res_a and not res_h:
                        row_factions.add("Faction: Horde")
                    elif res_h and not res_a:
                        row_factions.add("Faction: Alliance")

            # React-based faction signals (only as a fallback hint if the note is silent)
            if not row_factions and not is_explicitly_universal:
                if v_a is None and v_h is not None:
                    row_factions.add("Faction: Horde")
                elif v_h is None and v_a is not None:
                    row_factions.add("Faction: Alliance")
                elif v_a in (-1, 0) and v_h == 1:
                    row_factions.add("Faction: Alliance")
                elif v_h in (-1, 0) and v_a == 1:
                    row_factions.add("Faction: Horde")

            # Final veto: null react overrides everything
            if v_a is None: row_factions.discard("Faction: Alliance")
            if v_h is None: row_factions.discard("Faction: Horde")

            for f in row_factions:
                if f not in base_conditions:
                    base_conditions.append(f)

            combo_cache[combo_key] = (base_conditions, v_a, v_h)

        npc_conditions, v_a, v_h = combo_cache[combo_key]
        npc_conditions = list(npc_conditions)  # copy — elusive check may append below

        # Elusive creature check (row-specific: depends on name + expansion)
        npc_name_lower = record_data['npc_name'].lower()
        if "elusive" in npc_name_lower:
            expansion = record_data['expansion']
            if expansion == "Dragonflight":
                val = "Profession: Skinning (Elusive Creature Bait)"
                if val not in npc_conditions:
                    npc_conditions.append(val)
            elif expansion == "The War Within":
                val = "Profession: Skinning (Elusive Creature Lure)"
                if val not in npc_conditions:
                    npc_conditions.append(val)

        # Final deduplication of generic vs specific conditions 
        if npc_conditions:
            specific_parents = { c.split(" (")[0] for c in npc_conditions if "(" in c and ":" in c }
            npc_conditions = [c for c in npc_conditions if c not in specific_parents]
        
        record_data['taming_requirements'] = "|".join(sorted(npc_taming_set))
        record_data['special_conditions'] = "|".join(sorted(npc_conditions))
        final_rows.append(record_data)

    final_rows.sort(key=lambda x: (
        int(x['npc_id']) if x['npc_id'].isdigit() else 0,
        x['zone_name'], x['uiMapId']
    ))

    with open(COMBINED_PET_DATA_CSV, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(final_rows)

    print(f"Successfully generated {COMBINED_PET_DATA_CSV} with {len(final_rows)} records.")

if __name__ == "__main__":
    main()