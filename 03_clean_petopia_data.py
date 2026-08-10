"""
Clean and process Petopia data, generating a cleaned dataset with notes and taming requirements.

Pipeline order:
1. Load raw Petopia data.
2. Deduplicate by npc_id (keep first occurrence).
3. Clean notes (keyword filter, location stripping, global search/replace, NPC-specific updates) and add missing NPCs from notes_updates.csv.
4. Clean taming skills from tamingskillname1/tamingskillname2.
5. Merge taming_updates.csv — override/add taming_requirements where specified.
6. Write processed_petopia_data.csv with columns: npc_id, npc_name, zone, family, name_keeper, notes, taming_requirements.
"""

import csv
import os
import re
import sys

from config import (
    NOTES_KEYWORDS_CSV,
    NOTES_UPDATES_CSV,
    PETOPIA_DATA_CSV,
    PROCESSED_PETOPIA_DATA_CSV,
    TAMING_UPDATES_CSV,
    ensure_dirs,
)

# Matches any "Located in <anything>." sentence.
# The substitution function checks for parentheses before stripping.
LOCATION_STRIP_RE = re.compile(r'Located in [^.]+\.', re.IGNORECASE)


# --- Taming skill cleaning (moved from 11_combine_data.py) ---

# Raw tamingskillname1/2 values after stripping "Required Skill:" and "Taming"/"Family" suffix
# are already in standard form (e.g., "Exotic", "Cloud Serpent", "Blood Beast", "Mechanical").
# No additional normalization map needed.

def clean_taming_skill(skill):
    """Clean a taming skill string to its normalized form."""
    if not skill:
        return ""
    skill = skill.replace("Required Skill:", "").strip()
    skill = re.sub(r'\s*(?:Taming|Family)$', '', skill, flags=re.IGNORECASE)
    return skill.strip()


# --- Skip list loading ---

def load_skip_npc_ids(filepath):
    """Load global NPC skip IDs from the skip list CSV."""
    skip_ids = set()
    if not os.path.exists(filepath):
        print(f"Warning: Skip list file not found: {filepath}")
        return skip_ids
    with open(filepath, 'r', encoding='utf-8-sig', newline='', errors='replace') as f:
        reader = csv.DictReader(f)
        for row in reader:
            npc_id = row.get('npc_id', '').strip()
            if npc_id:
                skip_ids.add(npc_id)
    return skip_ids


# --- Notes cleaning (from 03_update_notes.py) ---

def load_note_keywords():
    keywords = set()
    if os.path.exists(NOTES_KEYWORDS_CSV):
        with open(NOTES_KEYWORDS_CSV, 'r', encoding='utf-8-sig', errors='replace') as f:
            for row in csv.DictReader(f):
                kw = row.get('keyword') or row.get('\ufeffkeyword')
                if kw:
                    kw = kw.strip()
                    if kw:
                        keywords.add(kw)
    return keywords


def load_notes_updates():
    """
    Load notes update rules from notes_updates.csv.
    Returns:
        global_rules: list of (compiled_pattern, replace_str) for npc_id="" rows
        npc_add: dict mapping npc_id -> note_text (search empty, replace non-empty)
        npc_remove: set of npc_id (search empty, replace empty)
        npc_modify: dict mapping npc_id -> list of (compiled_pattern, replace_str)
    """
    global_rules = []
    npc_add = {}
    npc_remove = set()
    npc_modify = {}

    if not os.path.exists(NOTES_UPDATES_CSV):
        return global_rules, npc_add, npc_remove, npc_modify

    with open(NOTES_UPDATES_CSV, 'r', encoding='utf-8-sig', errors='replace') as f:
        for row in csv.DictReader(f):
            raw_npc_id = (row.get('npc_id') or row.get('\ufeffnpc_id') or '').strip()
            search = (row.get('search') or row.get('\ufeffsearch') or '').strip()
            replace = row.get('replace') or ""

            if not raw_npc_id:
                # Global search/replace rule
                if search:
                    global_rules.append((
                        re.compile(re.escape(search), re.IGNORECASE),
                        replace.strip()
                    ))
            else:
                if not search and replace.strip():
                    # Add/override note for a specific NPC
                    npc_add[raw_npc_id] = replace.strip()
                elif not search and not replace.strip():
                    # Remove note for a specific NPC
                    npc_remove.add(raw_npc_id)
                elif search:
                    # Scoped search/replace for a specific NPC
                    npc_modify.setdefault(raw_npc_id, []).append((
                        re.compile(re.escape(search), re.IGNORECASE),
                        replace.strip()
                    ))

    return global_rules, npc_add, npc_remove, npc_modify


def strip_location_sentences(note):
    """
    Remove "Located in X." sentences where X contains no parentheses.
    Sentences with parentheses (e.g. "Located in Uldir (Raid).") are kept.
    """
    def _replacer(match):
        return '' if '(' not in match.group() else match.group()
    return LOCATION_STRIP_RE.sub(_replacer, note)


def clean_note(note, compiled_rules, keyword_pattern):
    """
    Full cleaning pipeline for a single note string.
    Returns cleaned note or empty string if it doesn't survive filtering.
    """
    note = (note or '').strip()
    if not note:
        return ""

    # 1. Remove backslashes, normalize whitespace
    note = note.replace('\\', '')
    note = note.replace('.,', ',')
    note = ' '.join(note.split())

    # 2. Strip plain "Located in X." sentences
    note = strip_location_sentences(note)
    note = ' '.join(note.split())

    if not note:
        return ""

    # 3. Keyword filter on the stripped note
    if keyword_pattern and not keyword_pattern.search(note):
        return ""

    # 4. Global search and replace cleanup
    for pattern, replace in compiled_rules:
        note = pattern.sub(replace, note)

    # 5. Final whitespace normalization
    note = ' '.join(note.split())

    return note


# --- Taming updates loading ---

def load_taming_updates(filepath):
    """Load taming_updates.csv, returns dict of npc_id -> taming_requirements string."""
    updates = {}
    if not os.path.exists(filepath):
        print(f"Warning: Taming updates file not found: {filepath}")
        return updates
    with open(filepath, 'r', encoding='utf-8-sig', newline='', errors='replace') as f:
        reader = csv.DictReader(f)
        for row in reader:
            npc_id = row.get('npc_id', '').strip()
            taming_req = row.get('taming_requirements', '').strip()
            if npc_id and taming_req:
                # If NPC already has an entry, append (for multiple zone entries)
                if npc_id in updates:
                    existing = set(updates[npc_id].split('|'))
                    existing.update(taming_req.split('|'))
                    updates[npc_id] = '|'.join(sorted(existing))
                else:
                    updates[npc_id] = taming_req
    return updates


# --- Main ---

def main():
    print("=" * 60)
    print("Step 03: Clean Petopia Data")
    print("=" * 60)
    ensure_dirs()

    # 1. Load raw Petopia data
    if not os.path.exists(PETOPIA_DATA_CSV):
        print(f"Error: {PETOPIA_DATA_CSV} not found.")
        sys.exit(1)

    raw_records = []
    with open(PETOPIA_DATA_CSV, 'r', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            npc_id = (row.get('npc_id') or '').strip()
            if npc_id:
                raw_records.append(row)

    total_loaded = len(raw_records)
    print(f"Loaded {total_loaded} raw Petopia records.")

    # 2. Deduplicate by npc_id (keep first occurrence)
    seen_ids = set()
    deduped_records = []
    for r in raw_records:
        npc_id = r.get('npc_id', '').strip()
        if npc_id not in seen_ids:
            seen_ids.add(npc_id)
            deduped_records.append(r)

    skipped_dupes = len(raw_records) - len(deduped_records)
    print(f"Skipped {skipped_dupes} duplicate NPC IDs.")

    # 3. Clean notes
    keywords = load_note_keywords()
    keyword_pattern = None
    if keywords:
        keyword_pattern = re.compile(
            r'\b(' + '|'.join(map(re.escape, keywords)) + r')s?\b',
            re.IGNORECASE
        )
        print(f"Loaded {len(keywords)} keywords for filtering.")

    global_rules, npc_add, npc_remove, npc_modify = load_notes_updates()
    print(f"Loaded {len(global_rules)} global cleanup rules.")
    print(f"Loaded {len(npc_add)} npc-specific note additions.")
    print(f"Loaded {len(npc_remove)} npc-specific note removals.")
    print(f"Loaded {len(npc_modify)} npc-specific note modifications.")

    # Deduplicate note strings for efficient cleaning
    unique_notes = {r.get('notes', '').strip() for r in deduped_records if r.get('notes', '').strip()}
    print(f"Cleaning {len(unique_notes)} unique note strings...")

    note_cache = {}
    for note in unique_notes:
        note_cache[note] = clean_note(note, global_rules, keyword_pattern)
    note_cache[''] = ''

    # Apply notes to records
    dropped_notes = 0
    for r in deduped_records:
        raw_note = r.get('notes', '').strip()
        cleaned = note_cache.get(raw_note, '')
        r['cleaned_notes'] = cleaned
        if not cleaned:
            dropped_notes += 1

    # Apply npc-specific modifications
    for r in deduped_records:
        npc_id = r.get('npc_id', '').strip()
        if npc_id in npc_modify:
            note = r['cleaned_notes']
            for pattern, replace in npc_modify[npc_id]:
                note = pattern.sub(replace, note)
            note = ' '.join(note.split())
            r['cleaned_notes'] = note

    # Apply npc-specific additions (overrides)
    for r in deduped_records:
        npc_id = r.get('npc_id', '').strip()
        if npc_id in npc_add:
            r['cleaned_notes'] = npc_add[npc_id]

    # Apply npc-specific removals
    deduped_records = [r for r in deduped_records if r.get('npc_id', '').strip() not in npc_remove]
    print(f"Records after note removals: {len(deduped_records)}")

    # ---------------------------------------------------------------------
    # Add missing NPCs from notes_updates
    # ---------------------------------------------------------------------
    # Some note updates refer to NPCs that are not present in the raw
    # Petopia data.  The original pipeline discarded those updates, but
    # the downstream data model expects every note update to be represented
    # in the final cleaned dataset.  We therefore create minimal records
    # for any NPC IDs that appear in ``npc_add`` but are missing from the
    # deduped records.  The note text is cleaned using the same rules as
    # for existing records.
    existing_ids = {r.get('npc_id', '').strip() for r in deduped_records}
    missing_ids = set(npc_add.keys()) - existing_ids - npc_remove
    added_count = 0
    for missing_id in missing_ids:
        raw_note = npc_add[missing_id]
        cleaned_note = clean_note(raw_note, global_rules, keyword_pattern)
        deduped_records.append({
            'npc_id': missing_id,
            'npc_name': '',
            'zone': '',
            'family': '',
            'name_keeper': '',
            'cleaned_notes': cleaned_note,
            'taming_requirements': '',
        })
        added_count += 1
    if added_count:
        print(f"Added {added_count} missing NPC(s) from notes_updates.")

    # 4. Clean taming skills
    for r in deduped_records:
        skills = []
        for key in ('tamingskillname1', 'tamingskillname2'):
            s = r.get(key, '')
            if s:
                cleaned = clean_taming_skill(s)
                if cleaned:
                    skills.append(cleaned)
        r['taming_requirements'] = '|'.join(skills)

    # 5. Merge taming_updates.csv
    taming_updates = load_taming_updates(TAMING_UPDATES_CSV)
    print(f"Loaded {len(taming_updates)} taming requirement updates.")

    for r in deduped_records:
        npc_id = r.get('npc_id', '').strip()
        if npc_id in taming_updates:
            r['taming_requirements'] = taming_updates[npc_id]

    # 6. Write output
    output_columns = ['npc_id', 'npc_name', 'zone', 'family', 'name_keeper', 'notes', 'taming_requirements']

    output_rows = []
    for r in deduped_records:
        notes = r.get('cleaned_notes', '')
        output_rows.append({
            'npc_id': r.get('npc_id', '').strip(),
            'npc_name': r.get('npc_name', '').strip(),
            'zone': r.get('zone', '').strip(),
            'family': r.get('family', '').strip(),
            'name_keeper': r.get('name_keeper', '').strip(),
            'notes': notes,
            'taming_requirements': r.get('taming_requirements', ''),
        })

    # Sort by npc_id numerically
    output_rows.sort(key=lambda x: int(x['npc_id']) if x['npc_id'].isdigit() else 0)

    print(f"Writing {len(output_rows)} cleaned records to {PROCESSED_PETOPIA_DATA_CSV}...")
    with open(PROCESSED_PETOPIA_DATA_CSV, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=output_columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(output_rows)

    # Summary
    print("\n" + "-" * 40)
    print("Cleaning Statistics Summary:")
    print(f"  Total records loaded:              {total_loaded}")
    print(f"  Skipped (duplicate NPC IDs):       {skipped_dupes}")
    print(f"  Dropped (no surviving notes):      {dropped_notes}")
    print(f"  Added missing NPCs from updates:   {len(missing_ids)}")
    print(f"  Taming updates applied:            {len(taming_updates)}")
    print(f"  Final records written:             {len(output_rows)}")
    print("-" * 40 + "\n")
    print("Petopia data cleaning step completed successfully.")


if __name__ == "__main__":
    main()