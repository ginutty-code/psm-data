"""
Generate a final notes dataset from raw Petopia data with manual updates.

Pipeline order:
1. Load raw Petopia data, extract (npc_id, npc_name, notes).
2. Deduplicate note strings in-memory — clean each unique note once.
3. For each unique note:
   a. Basic whitespace normalization and backslash removal.
   b. Strip "Located in X." sentences unless they contain parentheses.
   c. Apply keyword filter — notes with no valuable keyword are dropped.
   d. Apply global (npc_id empty) search-and-replace cleanup rules (notes_updates.csv).
   e. Final whitespace normalization.
4. Map cleaned notes back to all NPCs (many NPCs may share the same raw note).
5. Apply npc_id-specific updates from notes_updates.csv:
   - search empty, replace non-empty  → add/override note for that NPC
   - search empty, replace empty      → remove note for that NPC
   - search and replace both non-empty → scoped search/replace on that NPC's note
6. Write final_notes.csv with npc_id, npc_name, notes.
"""

import csv
import os
import re
from config import (
    PETOPIA_DATA_CSV, NOTES_KEYWORDS_CSV, NOTES_UPDATES_CSV,
    FINAL_NOTES_CSV, ensure_dirs
)


# Matches any "Located in <anything>." sentence.
# The substitution function checks for parentheses before stripping.
LOCATION_STRIP_RE = re.compile(r'Located in [^.]+\.', re.IGNORECASE)


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


def main():
    print("Starting notes generation...")
    ensure_dirs()

    if not os.path.exists(PETOPIA_DATA_CSV):
        print(f"Error: {PETOPIA_DATA_CSV} not found.")
        return

    keywords = load_note_keywords()
    keyword_pattern = None
    if keywords:
        keyword_pattern = re.compile(
            r'\b(' + '|'.join(map(re.escape, keywords)) + r')s?\b',
            re.IGNORECASE
        )
        print(f"Loaded {len(keywords)} keywords for filtering.")

    # Load update rules (global + npc-specific)
    global_rules, npc_add, npc_remove, npc_modify = load_notes_updates()
    print(f"Loaded {len(global_rules)} global cleanup rules.")
    print(f"Loaded {len(npc_add)} npc-specific note additions.")
    print(f"Loaded {len(npc_remove)} npc-specific note removals.")
    print(f"Loaded {len(npc_modify)} npc-specific note modifications.")

    # Load raw Petopia records
    raw_records = []
    with open(PETOPIA_DATA_CSV, 'r', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            npc_id = (row.get('npc_id') or '').strip()
            npc_name = (row.get('npc_name') or '').strip()
            note = (row.get('notes') or '').strip()
            if npc_id:
                raw_records.append((npc_id, npc_name, note))

    print(f"Loaded {len(raw_records)} raw Petopia records.")

    # Build name lookup from Petopia data (used for npc_add entries)
    petopia_names = {npc_id: npc_name for npc_id, npc_name, _ in raw_records}

    # Deduplicate: clean each unique note string once
    unique_notes = {note for _, _, note in raw_records if note}
    print(f"Cleaning {len(unique_notes)} unique note strings...")

    note_cache = {}
    for note in unique_notes:
        note_cache[note] = clean_note(note, global_rules, keyword_pattern)

    # Empty string sentinel for NPCs with no note
    note_cache[''] = ''

    # Map cleaned notes back to all NPCs
    # Start with a dict so we can insert npc_add records later
    output_map = {}
    dropped = 0
    for npc_id, npc_name, raw_note in raw_records:
        cleaned = note_cache.get(raw_note, '')
        if cleaned:
            output_map[npc_id] = {
                'npc_id': npc_id,
                'npc_name': npc_name,
                'notes': cleaned
            }
        else:
            dropped += 1

    # Apply npc-specific modifications (search/replace scoped to one NPC)
    for npc_id, rules in npc_modify.items():
        if npc_id in output_map:
            note = output_map[npc_id]['notes']
            for pattern, replace in rules:
                note = pattern.sub(replace, note)
            note = ' '.join(note.split())
            if note:
                output_map[npc_id]['notes'] = note
            else:
                del output_map[npc_id]
                dropped += 1

    # Apply npc-specific additions (overrides any existing note)
    for npc_id, note_text in npc_add.items():
        output_map[npc_id] = {
            'npc_id': npc_id,
            'npc_name': petopia_names.get(npc_id, ''),
            'notes': note_text
        }

    # Apply npc-specific removals
    for npc_id in npc_remove:
        if npc_id in output_map:
            del output_map[npc_id]
            dropped += 1

    # Convert map to sorted list
    def npc_sort_key(item):
        nid = item['npc_id']
        return int(nid) if nid.isdigit() else 0

    output_rows = sorted(output_map.values(), key=npc_sort_key)

    print(f"Kept {len(output_rows)} records, dropped {dropped} (no note or filtered out).")

    with open(FINAL_NOTES_CSV, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['npc_id', 'npc_name', 'notes'])
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"Successfully generated {FINAL_NOTES_CSV}.")


if __name__ == "__main__":
    main()