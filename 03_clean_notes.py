"""
Generate a cleaned notes dataset from raw Petopia data.

Pipeline order:
1. Load raw Petopia data, extract (npc_id, npc_name, notes).
2. Deduplicate note strings in-memory — clean each unique note once.
3. For each unique note:
   a. Basic whitespace normalization and backslash removal.
   b. Strip "Located in X." sentences unless they contain parentheses.
   c. Apply keyword filter — notes with no valuable keyword are dropped.
   d. Apply search-and-replace cleanup rules (notes_cleanup.csv).
   e. Final whitespace normalization.
4. Map cleaned notes back to all NPCs (many NPCs may share the same raw note).
5. Write final_notes.csv with npc_id, npc_name, notes (only rows with a non-empty note).
"""

import csv
import os
import re
from config import (
    PETOPIA_DATA_CSV, NOTES_KEYWORDS_CSV, NOTES_CLEANUP_CSV,
    FINAL_NOTES_CSV, ensure_dirs
)


# Matches any "Located in <anything>." sentence.
# The substitution function checks for parentheses before stripping.
LOCATION_STRIP_RE = re.compile(r'Located in [^.]+\.', re.IGNORECASE)


def load_note_keywords():
    keywords = set()
    if os.path.exists(NOTES_KEYWORDS_CSV):
        with open(NOTES_KEYWORDS_CSV, 'r', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                kw = row.get('keyword') or row.get('\ufeffkeyword')
                if kw:
                    kw = kw.strip()
                    if kw:
                        keywords.add(kw)
    return keywords


def load_notes_cleanup():
    rules = []
    if os.path.exists(NOTES_CLEANUP_CSV):
        with open(NOTES_CLEANUP_CSV, 'r', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                search = row.get('search') or row.get('\ufeffsearch')
                replace = row.get('replace') or ""
                if search:
                    rules.append((
                        re.compile(re.escape(search.strip()), re.IGNORECASE),
                        replace.strip()
                    ))
    return rules


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

    # 4. Search and replace cleanup
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

    compiled_rules = load_notes_cleanup()
    print(f"Loaded and compiled {len(compiled_rules)} cleanup rules.")

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

    # Deduplicate: clean each unique note string once
    unique_notes = {note for _, _, note in raw_records if note}
    print(f"Cleaning {len(unique_notes)} unique note strings...")

    note_cache = {}
    for note in unique_notes:
        note_cache[note] = clean_note(note, compiled_rules, keyword_pattern)

    # Empty string sentinel for NPCs with no note
    note_cache[''] = ''

    # Map cleaned notes back to all NPCs, drop empty results
    output_rows = []
    dropped = 0
    for npc_id, npc_name, raw_note in raw_records:
        cleaned = note_cache.get(raw_note, '')
        if cleaned:
            output_rows.append({
                'npc_id': npc_id,
                'npc_name': npc_name,
                'notes': cleaned
            })
        else:
            dropped += 1

    print(f"Kept {len(output_rows)} records, dropped {dropped} (no note or filtered out).")

    with open(FINAL_NOTES_CSV, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['npc_id', 'npc_name', 'notes'])
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"Successfully generated {FINAL_NOTES_CSV}.")


if __name__ == "__main__":
    main()