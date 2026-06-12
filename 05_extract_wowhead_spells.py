"""
Extract spell details for each spell ID in families.csv and assign category and tag.
"""

import json
import os
import re
import sys
import csv
import html
import requests
from config import WOWHEAD_FAMILIES_CSV, WOWHEAD_SPELLS_CSV, SPELLS_MAPPING_CSV, ensure_dirs

BASE_URL = 'https://www.wowhead.com'
SKIP_SPELL_IDS = {16827, 17253, 49966}


def load_required_spell_ids():
    """Load unique spell IDs from families.csv and spells_mapping.csv."""
    spell_ids = set()

    if not os.path.exists(WOWHEAD_FAMILIES_CSV):
        raise FileNotFoundError(f"Families CSV not found: {WOWHEAD_FAMILIES_CSV}")

    with open(WOWHEAD_FAMILIES_CSV, 'r', encoding='utf-8', newline='') as f:
        for row in csv.DictReader(f):
            for sid in row.get('spells', '').split(';'):
                sid = sid.strip()
                if sid.isdigit():
                    sid_int = int(sid)
                    if sid_int not in SKIP_SPELL_IDS:
                        spell_ids.add(sid_int)

    # Also include IDs from the manual mapping file (for Spec-related spells)
    if os.path.exists(SPELLS_MAPPING_CSV):
        with open(SPELLS_MAPPING_CSV, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Normalize keys of the current row for robust lookup
                normalized_row = {k.strip().lower(): v for k, v in row.items()}
                sid = (normalized_row.get('spell_id') or normalized_row.get('id') or '').strip()
                if sid.isdigit():
                    sid_int = int(sid)
                    if sid_int not in SKIP_SPELL_IDS:
                        spell_ids.add(sid_int)

    return sorted(spell_ids)


def clean_description(text):
    """Clean Wowhead tooltip HTML into plain readable text."""
    if not text:
        return ""

    # 1. Unescape HTML entities (handles double-encoding like &amp;lt;)
    text = html.unescape(html.unescape(text))

    # 2. Two or more consecutive <br> tags → period + space (section separator)
    text = re.sub(r'(?:<br\s*/?>\s*){2,}', '. ', text, flags=re.IGNORECASE)

    # 3. Any remaining single <br> → space
    text = re.sub(r'<br\s*/?>', ' ', text, flags=re.IGNORECASE)

    # 4. White-coloured spans become "Name: " (sub-ability headers)
    text = re.sub(
        r'<span[^>]*style="[^"]*color\s*:\s*#fff(?:fff)?[^"]*"[^>]*>\s*(.*?)\s*</span>',
        r' \1: ',
        text,
        flags=re.IGNORECASE | re.DOTALL
    )

    # 5. Correct Wowhead data placeholders
    # Specifically handles (percentOfAttackPower_format, X.XX) -> (X.XX% of Attack Power)
    text = re.sub(
        r'percentOfAttackPower_format,\s*([\d.]+)',
        r'\1% of Attack Power',
        text, flags=re.IGNORECASE
    )

    # 6. Strip all remaining HTML tags
    text = re.sub(r'<[^>]+>', '', text)

    # 7. Normalize whitespace
    text = re.sub(r'\s+', ' ', text)

    # 8. Fix punctuation artifacts from the transforms above
    text = re.sub(r'\s*\.\s*\.', '.', text)  # ". ." → "."
    text = re.sub(r'\.\s*:', ':', text)        # ".: " → ":"
    text = re.sub(r':\s*\.', ':', text)        # ":." → ":"
    text = re.sub(r'\s+:', ':', text)          # stray space before colon
    text = re.sub(r':\s{2,}', ': ', text)      # normalize post-colon space

    return text.strip()


def extract_spell_data_from_html(html_content, spell_id):
    """Extract spell data dict from a Wowhead spell page."""
    pattern = r'WH\.Gatherer\.addData\(6,\s*\d+,\s*(\{.*?\})\);'
    for match in re.finditer(pattern, html_content, re.DOTALL):
        try:
            data = json.loads(match.group(1))
            if str(spell_id) in data:
                info = data[str(spell_id)]
                info['id'] = spell_id
                return info
        except (json.JSONDecodeError, KeyError):
            continue
    return None


def fetch_spell_details(spell_id):
    """Fetch and extract spell details for a single spell ID."""
    url = f"{BASE_URL}/spell={spell_id}"
    print(f"Fetching spell {spell_id} from {url}...")
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Error fetching spell {spell_id}: {e}")
        return None
    return extract_spell_data_from_html(response.text, spell_id)


def fetch_all_spells(spell_ids):
    """Fetch details for a list of spell IDs."""
    spells = []
    for spell_id in spell_ids:
        spell_data = fetch_spell_details(spell_id)
        if spell_data:
            spells.append(spell_data)
    print(f"Successfully fetched {len(spells)} out of {len(spell_ids)} spells")
    return spells


def load_manual_spell_mapping():
    """Load manual category and tag assignments from SPELLS_MAPPING_CSV."""
    mapping = {}
    if not os.path.exists(SPELLS_MAPPING_CSV):
        return mapping
    try:
        with open(SPELLS_MAPPING_CSV, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Normalize keys for robust lookup
                normalized_row = {k.strip().lower(): v for k, v in row.items()}
                sid = (normalized_row.get('spell_id') or normalized_row.get('id') or '').strip()
                
                if sid.isdigit():
                    mapping[int(sid)] = {
                        'spell_category': (normalized_row.get('spell_category') or normalized_row.get('category') or '').strip(),
                        'spell_tag': (normalized_row.get('spell_tag') or normalized_row.get('tag') or '').strip(),
                        'icon': (normalized_row.get('spell_icon') or normalized_row.get('icon') or '').strip(),
                    }
    except Exception as e:
        print(f"Warning: Could not load manual mappings from {SPELLS_MAPPING_CSV}: {e}")
    return mapping


def save_spells_csv(spells):
    """Clean and save spells to WOWHEAD_SPELLS_CSV."""
    ensure_dirs()
    if not spells:
        print("No spells to save")
        return

    manual_mapping = load_manual_spell_mapping()

    exclude = {'screenshot', 'screenshot_enus', 'displayName', 'displayName_enus',
               'tooltip_html', 'tooltip_html_enus'}

    def clean_spell_data(spell):
        # Rename and filter keys
        cleaned = {}
        for k, v in spell.items():
            if k in exclude:
                continue
            new_key = k.replace('_enus', '')
            if new_key == 'id':
                cleaned['spell_id'] = v
            elif new_key == 'name':
                cleaned['spell_name'] = v
            elif new_key == 'description':
                cleaned['spell_description'] = v
            elif new_key == 'icon':
                cleaned['spell_icon'] = v
            elif new_key == 'rank':
                cleaned['spell_rank'] = v
            else:
                cleaned[new_key] = v

        # Clean any field that is a string and contains HTML or placeholders
        for field, value in cleaned.items():
            if isinstance(value, str) and ('<' in value or '_format' in value or '&' in value):
                cleaned[field] = clean_description(value)

        # Apply manual mapping overrides and ensure new column names
        spell_id_int = int(spell.get('spell_id') or spell.get('id') or 0)
        manual = manual_mapping.get(spell_id_int, {})
        
        # Merge manual overrides: only update if mapping provides a non-empty value
        if manual.get('spell_category'):
            cleaned['spell_category'] = manual['spell_category']
        if manual.get('spell_tag'):
            cleaned['spell_tag'] = manual['spell_tag']
        if manual.get('icon'):
            cleaned['spell_icon'] = manual['icon']

        # Ensure all requested fields are present, even if empty
        for key in ['spell_id', 'spell_name', 'spell_description', 'spell_icon', 'spell_rank', 'spell_category', 'spell_tag']:
            cleaned.setdefault(key, '')

        return cleaned

    cleaned_spells = [clean_spell_data(s) for s in spells]

    # Define the desired order of fieldnames
    fieldnames = [
        'spell_id',
        'spell_name',
        'spell_description',
        'spell_icon',
        'spell_rank',
        'spell_category',
        'spell_tag',
    ]
    # Add any other remaining fields, sorted, to the end
    other_fields = sorted([k for s in cleaned_spells for k in s if k not in fieldnames])
    fieldnames.extend(other_fields)

    with open(WOWHEAD_SPELLS_CSV, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(cleaned_spells)
    print(f"Spells saved to {WOWHEAD_SPELLS_CSV}")


def load_spells_csv():
    """Load cached spells from WOWHEAD_SPELLS_CSV. Returns empty list if not found."""
    if not os.path.exists(WOWHEAD_SPELLS_CSV):
        return []
    with open(WOWHEAD_SPELLS_CSV, 'r', encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def main():
    ensure_dirs()

    try:
        spell_ids = load_required_spell_ids()
    except FileNotFoundError as e:
        print(e)
        sys.exit(1)

    print(f"Found {len(spell_ids)} unique spell IDs to process")

    cached = [s for s in load_spells_csv() if int(s.get('spell_id', 0)) not in SKIP_SPELL_IDS]
    cached_ids = {int(s.get('spell_id', 0)) for s in cached}
    missing_ids = [sid for sid in spell_ids if sid not in cached_ids]

    if cached:
        print(f"Found {len(cached)} cached spells. Fetching {len(missing_ids)} missing ones...")
    
    new_spells = fetch_all_spells(missing_ids) if missing_ids else []

    # Always re-save to apply current cleaning logic to all records
    save_spells_csv(cached + new_spells)


if __name__ == '__main__':
    main()