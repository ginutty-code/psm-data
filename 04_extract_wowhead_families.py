"""
Extract hunter pet familes details from Wowhead
"""

import json
import os
import re
import sys
import csv

import requests
from config import WOWHEAD_FAMILIES_CSV, PROCESSED_FAMILIES_CSV, ensure_dirs

# Configuration
URL = 'https://www.wowhead.com/hunter-pets'

# Missing family data (Wowhead's JavaScript data is often incomplete)
WHIPTAIL_FAMILY_ID = 315
WHIPTAIL_RECORD = {
    'family_id': WHIPTAIL_FAMILY_ID,
    'family_name': 'Whiptail',
    'diet': 0,
    'expansion': 12,
    'icon': 'inv_stalkermount_red',
    'maxLevel': 0,
    'minLevel': 0,
    'type': 0,
    'spells': '16827;24450;1247058;1247078',
    'armor': 5,
    'damage': 5,
    'health': 5,
    'exotic': 1,
    'popularity': 0
}


def extract_families_from_html(html_content):
    """
    Extract pet families from the HTML page.
    Returns list of dicts with family data
    """
    # Find the JavaScript data array in the page
    # Pattern matches: data: [{id: 1, name: "Wolf"}, ...]
    pattern = r'data:\s*(\[.*?\])\s*\}\);\s*//\]\]'
    match = re.search(pattern, html_content, re.DOTALL)

    if not match:
        raise ValueError("Could not find pet data in HTML")

    data_json = match.group(1)

    # Parse the JSON array
    # Note: The data uses unquoted keys, so we need to handle that
    try:
        pet_data = json.loads(data_json)
    except json.JSONDecodeError:
        # Try to fix unquoted keys
        data_json = re.sub(r'(\w+):', r'"\1":', data_json)
        pet_data = json.loads(data_json)

    # Extract all available fields for each family
    families = []
    for item in pet_data:
        family = {}
        # Extract specified fields
        for field in ['id', 'name', 'diet', 'expansion', 'icon', 'maxLevel', 'minLevel', 'type', 'spells', 'armor', 'damage', 'health', 'exotic', 'popularity']:
            value = item.get(field)
            if field == 'id':
                family['family_id'] = value
            elif field == 'name':
                family['family_name'] = value
            elif field == 'spells' and isinstance(value, list):
                family[field] = ';'.join(map(str, value))
            else:
                family[field] = value
        families.append(family)

    return families


def fetch_families():
    """Fetch and extract families from Wowhead."""
    print(f"Fetching families from {URL}...")

    response = requests.get(URL, timeout=30)
    response.raise_for_status()

    families = extract_families_from_html(response.text)

    print(f"Found {len(families)} families:")
    for family in sorted(families, key=lambda x: int(x.get('family_id', 0))):
        family_id = family.get('family_id')
        family_name = family.get('family_name')
        print(f"  {family_id}: {family_name}")

    return families


def save_WOWHEAD_FAMILIES_CSV(families):
    """Save raw families to CSV file (no modifications — pure scrape)."""
    ensure_dirs()

    fieldnames = ['family_id', 'family_name', 'diet', 'expansion', 'icon', 'maxLevel', 'minLevel', 'type', 'spells', 'armor', 'damage', 'health', 'exotic', 'popularity']
    with open(WOWHEAD_FAMILIES_CSV, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for family in sorted(families, key=lambda x: int(x.get('family_id', 0))):
            writer.writerow(family)
    print(f"Raw families saved to {WOWHEAD_FAMILIES_CSV}")


def save_PROCESSED_FAMILIES_CSV(families):
    """Save processed families (with injected corrections) to CSV file."""
    ensure_dirs()

    # Ensure Whiptail (ID 315) is always included
    if not any(int(f.get('family_id', 0)) == WHIPTAIL_FAMILY_ID for f in families):
        print(f"  Adding missing family {WHIPTAIL_FAMILY_ID} (Whiptail) to processed dataset...")
        families.append({k: str(v) for k, v in WHIPTAIL_RECORD.items()})

    fieldnames = ['family_id', 'family_name', 'diet', 'expansion', 'icon', 'maxLevel', 'minLevel', 'type', 'spells', 'armor', 'damage', 'health', 'exotic', 'popularity']
    with open(PROCESSED_FAMILIES_CSV, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for family in sorted(families, key=lambda x: int(x.get('family_id', 0))):
            writer.writerow(family)
    print(f"Processed families saved to {PROCESSED_FAMILIES_CSV}")


def load_WOWHEAD_FAMILIES_CSV():
    """Load families from CSV file if it exists."""
    families = []
    if os.path.exists(WOWHEAD_FAMILIES_CSV):
        with open(WOWHEAD_FAMILIES_CSV, 'r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                families.append(row)
    return families if families else None


def ask_refresh(cached):
    """Ask user if they want to refresh or use cached data."""
    family_count = len(cached)
    name_count = sum(1 for item in cached if item.get('family_name'))

    print(f"\nCached families found: {WOWHEAD_FAMILIES_CSV}")
    print(f"Summary: {family_count} families with {name_count} named families")
    print("Options:")
    print("  [y] Refresh - Re-fetch from Wowhead")
    print("  [n] Use cached - Use existing data")
    print("  [q] Quit - Exit without changes")

    while True:
        try:
            choice = input("\nEnter choice (y/n/q): ").strip().lower()
        except EOFError:
            # Non-interactive mode - use cached data
            print("Non-interactive mode: using cached data")
            return False

        if choice in ('y', 'yes'):
            return True
        elif choice in ('n', 'no', ''):
            return False
        elif choice in ('q', 'quit', 'exit'):
            print("Exiting...")
            sys.exit(0)
        else:
            print("Invalid choice. Please enter y, n, or q.")


def main():
    """Main function to extract and save families."""
    ensure_dirs()

    # Try to load from cache first
    cached = load_WOWHEAD_FAMILIES_CSV()
    
    if cached:
        # Ensure processed file exists even if only raw cache is present
        if not os.path.exists(PROCESSED_FAMILIES_CSV):
            print(f"\nProcessed families file missing. Generating from cached raw data...")
            save_PROCESSED_FAMILIES_CSV(list(cached))

        should_refresh = ask_refresh(cached)
        
        if should_refresh:
            print("\nRefreshing families from Wowhead...")
            families = fetch_families()
            save_WOWHEAD_FAMILIES_CSV(families)
            save_PROCESSED_FAMILIES_CSV(list(families))
        else:
            print(f"\nUsing cached families ({len(cached)} families)")
            print("Run with --refresh flag to force refresh")
    else:
        # No cached data - fetch fresh
        families = fetch_families()
        save_WOWHEAD_FAMILIES_CSV(families)
        save_PROCESSED_FAMILIES_CSV(list(families))


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Extract pet families from Wowhead')
    parser.add_argument('--refresh', action='store_true', help='Refresh data from Wowhead (skip prompt)')
    args = parser.parse_args()
    
    if args.refresh:
        # Force refresh by removing cached file
        if os.path.exists(WOWHEAD_FAMILIES_CSV):
            os.remove(WOWHEAD_FAMILIES_CSV)
    
    main()
