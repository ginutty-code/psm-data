"""
Extract tameable NPCs for each family ID in families.csv
"""

import os
import re
import sys
import time
import csv

import requests
from config import WOWHEAD_FAMILIES_CSV, WOWHEAD_NPCS_CSV, ensure_dirs, get_random_headers

# Use concurrency=1 to avoid rate limiting
CONCURRENCY = 1
REQUEST_DELAY = 5.0  # Delay between requests in seconds (increased to avoid 403 errors)

# Classification mapping
CLASSIFICATION_MAP = {
    0: "Normal",
    1: "Elite",
    2: "Rare Elite",
    3: "Boss",
    4: "Rare"
}


def load_families():
    """Load families from CSV cache."""
    families = {}
    with open(WOWHEAD_FAMILIES_CSV, 'r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            families[row['family_id']] = row['family_name']
    return families


def load_WOWHEAD_NPCS_CSV():
    """Load NPCs from CSV cache if it exists."""
    npcs = []
    if os.path.exists(WOWHEAD_NPCS_CSV):
        with open(WOWHEAD_NPCS_CSV, 'r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                npcs.append(row)
    return npcs if npcs else None


def save_WOWHEAD_NPCS_CSV(npcs):
    """Save NPCs to CSV file in Cache."""
    ensure_dirs()
    
    # Write CSV for step 2 output
    columns = [
        'npc_id',
        'npc_name',
        'classification',
        'classification_id',
        'family_id',
        'family_name',
        'zone_id',
        'react',
    ]
    with open(WOWHEAD_NPCS_CSV, 'w', encoding='utf-8', newline='') as cf:
        writer = csv.DictWriter(cf, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        for rec in npcs:
            row = {k: ('' if rec.get(k) is None else rec.get(k)) for k in columns}
            writer.writerow(row)
    print(f"NPCs CSV saved to {WOWHEAD_NPCS_CSV}")


def extract_npcs_from_html(html_content, family_id, family_name):
    """
    Extract tameable NPCs from family page HTML.
    Returns list of {npc_id, npc_name, classification, family_id, family_name, zone_id, react}
    """
    npcs = []
    
    # Find the tameable Listview - more flexible pattern that allows for various structures
    # Look for Listview definitions containing id: 'tameable' or id: "tameable"
    pattern = r"new Listview\(\{"
    matches = list(re.finditer(pattern, html_content))
    
    if not matches:
        print(f"  Warning: Could not find any Listview for family {family_id}")
        return []
    
    # Find the one with id: 'tameable' or id: "tameable"
    tameable_match = None
    for match in matches:
        start = match.start()
        # Look ahead to find the closing brace of this Listview initialization
        # and check if it contains id: tameable
        brace_depth = 1
        pos = match.end()
        check_end = min(pos + 2000, len(html_content))  # check next 2000 chars
        
        while brace_depth > 0 and pos < check_end:
            if html_content[pos] == '{':
                brace_depth += 1
            elif html_content[pos] == '}':
                brace_depth -= 1
            pos += 1
        
        check_text = html_content[start:pos]
        if re.search(r'id\s*:\s*[\'"]tameable[\'"]', check_text):
            tameable_match = match
            break
    
    if not tameable_match:
        print(f"  Warning: Could not find tameable Listview for family {family_id}")
        return []
    
    start = tameable_match.start()
    
    # Find data array
    data_start = html_content.find('data:', start)
    bracket_start = html_content.find('[', data_start)
    
    if bracket_start == -1:
        print(f"  Warning: Could not find data array for family {family_id}")
        return []
    
    # Extract data array by finding matching closing bracket
    depth = 1
    pos = bracket_start + 1
    while depth > 0 and pos < len(html_content):
        if html_content[pos] == '[':
            depth += 1
        elif html_content[pos] == ']':
            depth -= 1
        pos += 1
    
    if depth != 0:
        print(f"  Warning: Could not find matching closing bracket for family {family_id}")
        return []
    
    data_json = html_content[bracket_start:pos]
    
    # Extract individual NPC records by properly handling nested braces and strings
    records = []
    pos = 0
    while pos < len(data_json):
        # Find opening brace
        brace_start = data_json.find('{', pos)
        if brace_start == -1:
            break
        
        # Count braces while tracking if we're inside a string (to avoid counting braces in strings)
        depth = 0
        brace_pos = brace_start
        in_string = False
        escape_next = False
        
        while brace_pos < len(data_json):
            ch = data_json[brace_pos]
            
            # Handle escape sequences
            if escape_next:
                escape_next = False
                brace_pos += 1
                continue
            
            if ch == '\\':
                escape_next = True
                brace_pos += 1
                continue
            
            # Handle string context
            if ch == '"':
                in_string = not in_string
                brace_pos += 1
                continue
            
            # Count braces only outside strings
            if not in_string:
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        records.append(data_json[brace_start:brace_pos + 1])
                        break
            
            brace_pos += 1
        
        pos = brace_start + 1
    
    for record in records:
        # Extract fields using regex
        id_match = re.search(r'[,{]\s*"?id"?:\s*(\d+)', record)
        name_match = re.search(r'"name":\s*"((?:[^"\\]|\\.)*)"', record)
        display_match = re.search(r'"displayName":\s*"((?:[^"\\]|\\.)*)"', record)
        class_match = re.search(r'"classification":\s*(\d+)', record)
        location_match = re.search(r'"location"\s*:\s*\[([^\]]*)\]', record)

        if not id_match:
            continue

        npc_id = id_match.group(1)
        
        # Extract react field
        react_match = re.search(r'"react":\s*(\[[^\]]*\])', record)
        react_str = react_match.group(1) if react_match else "[]"

        # Extract and clean name — unescape \" first, then strip remaining backslashes and quote characters
        if name_match:
            npc_name = name_match.group(1).replace('\\"', '"').replace('\\', '').replace('"', '')
        elif display_match:
            npc_name = display_match.group(1).replace('\\"', '"').replace('\\', '').replace('"', '')
        else:
            npc_name = ""

        classification_id = int(class_match.group(1)) if class_match else 0
        classification = CLASSIFICATION_MAP.get(classification_id, "Normal")

        # Determine zone_id: pipe-separated zone IDs, or 'unknown' if missing
        if location_match:
            location_numbers = re.findall(r'-?\d+', location_match.group(1))
            valid_location_ids = [lid for lid in location_numbers if lid not in ('-1', '0')]
            zone_id = '|'.join(valid_location_ids) if valid_location_ids else 'unknown'
        else:
            zone_id = 'unknown'

        npcs.append({
            'npc_id': npc_id,
            'npc_name': npc_name,
            'classification': classification,
            'classification_id': str(classification_id),
            'family_id': family_id,
            'family_name': family_name,
            'zone_id': zone_id,
            'react': react_str
        })
    
    return npcs

def fetch_family_npcs(family_id, family_name):
    """
    Fetch and extract NPCs from a single family page.
    URL pattern: https://www.wowhead.com/pet={family_id}/{family-name}#tameable
    """
    url = f"https://www.wowhead.com/pet={family_id}/{family_name.lower().replace(' ', '-')}#tameable"
    
    print(f"  Fetching family {family_id}: {family_name}...")
    
    response = None
    max_retries = 3
    for attempt in range(max_retries):
        try:
            hdr_idx, hdrs = get_random_headers()
            response = requests.get(url, headers=hdrs, timeout=30)
            if response.status_code == 200:
                break
            elif response.status_code == 403:
                if attempt < max_retries - 1:
                    wait_time = REQUEST_DELAY * (2 ** attempt)  # exponential backoff
                    print(f"  403 Forbidden (Header #{hdr_idx}), waiting {wait_time}s before retry {attempt+1}/{max_retries}")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"  Failed to fetch family {family_id} after {max_retries} attempts due to 403")
                    return []
            else:
                # For other HTTP errors, we don't retry
                print(f"  HTTP {response.status_code} for family {family_id}: {response.reason}")
                return []
        except requests.RequestException as e:
            # For connection errors, etc., we retry
            if attempt < max_retries - 1:
                wait_time = REQUEST_DELAY * (2 ** attempt)
                print(f"  Request error: {e}, waiting {wait_time}s before retry {attempt+1}/{max_retries}")
                time.sleep(wait_time)
                continue
            else:
                print(f"  Failed to fetch family {family_id} after {max_retries} attempts: {e}")
                return []
    
    # If we succeeded (status code 200)
    if response is None:
        return []
    
    npcs = extract_npcs_from_html(response.text, family_id, family_name)
    print(f"  Found {len(npcs)} NPCs")
    
    return npcs


def get_npcs_by_family(cached_npcs):
    """Group NPCs by family and return dict of {family_id: [npcs]}."""
    by_family = {}
    for npc in cached_npcs:
        fid = npc.get('family_id')
        if fid not in by_family:
            by_family[fid] = []
        by_family[fid].append(npc)
    return by_family

def ask_refresh(cached, families):
    """
    Ask user what to do with cached data.
    Returns: 'all', 'none', or list of family_ids to refresh
    """
    if not cached:
        return 'all'
    
    by_family = get_npcs_by_family(cached)
    
    print(f"\nCached NPCs found: {WOWHEAD_NPCS_CSV}")
    print(f"Total: {len(cached)} NPCs")
    
    print()
    
    # Show summary by family
    print("Cached data by family:")
    for family_id in sorted(families.keys(), key=int):
        family_name = families[family_id]
        count = len(by_family.get(family_id, []))
        status = f"[{count} NPCs]" if count > 0 else "[not cached]"
        print(f"  {family_id}: {family_name} - {status}")
    
    print()
    print("Options:")
    print("  [all] Refresh all families")
    print("  [none] Use cached data (skip refresh)")
    print("  [q] Quit")
    print("  Or enter family ID(s) to refresh (comma-separated, e.g., '1,9')")
    
    while True:
        try:
            choice = input("\nEnter choice (all/none/q or family ID(s)): ").strip().lower()
        except EOFError:
            # Non-interactive mode - use cached data
            print("Non-interactive mode: using cached data")
            return 'none'
        
        if choice in ('all', 'a'):
            return 'all'
        elif choice in ('none', 'n', ''):
            return 'none'
        elif choice in ('q', 'quit', 'exit'):
            print("Exiting...")
            sys.exit(0)
        else:
            # Try to parse as comma-separated family IDs
            family_ids = [f.strip() for f in choice.split(',')]
            valid = True
            for fid in family_ids:
                if not fid.isdigit() or fid not in families:
                    valid = False
                    break
            if valid and family_ids:
                return family_ids
            else:
                print(f"Invalid choice. Enter 'all', 'none', 'q', or family ID(s) (e.g., '1,9')")


def main():
    """Main function to extract NPCs from all families."""
    print("=" * 60)
    ensure_dirs()

    print("Step 2: Extracting Tameable NPCs from Family Pages")
    print("=" * 60)
    print(f"Concurrency: {CONCURRENCY} (sequential to avoid rate limiting)")
    print(f"Request delay: {REQUEST_DELAY}s between requests")
    print()
    
    # Load families
    print("Loading families...")
    families = load_families()
    print(f"Loaded {len(families)} families")
    print()
    
    # Check for cached NPCs
    cached = load_WOWHEAD_NPCS_CSV()
    
    if cached:
        action = ask_refresh(cached, families)
        
        if action == 'none':
            print(f"\nUsing cached NPCs ({len(cached)} NPCs)")
            print("Run with --refresh flag to force refresh all")
            return
        elif action == 'all':
            print("\nRefreshing all families from Wowhead...")
            if os.path.exists(WOWHEAD_NPCS_CSV):
                os.remove(WOWHEAD_NPCS_CSV)
            cached = None
        else:
            # Refresh specific families
            family_ids = action  # Now a list
            print(f"\nRefreshing families: {', '.join(family_ids)}...")
            
            # Remove NPCs for these families from cache
            all_npcs = [npc for npc in cached if npc.get('family_id') not in family_ids]
            
            # Fetch fresh data for each family
            for family_id in family_ids:
                family_name = families[family_id]
                print(f"  Processing family {family_id}: {family_name}")
                new_npcs = fetch_family_npcs(family_id, family_name)
                all_npcs.extend(new_npcs)
                time.sleep(REQUEST_DELAY)
            
            # Remove duplicates
            seen = set()
            unique_npcs = []
            for npc in all_npcs:
                key = npc['npc_id']
                if key not in seen:
                    seen.add(key)
                    unique_npcs.append(npc)
            
            print()
            print(f"Total NPCs: {len(unique_npcs)}")
            save_WOWHEAD_NPCS_CSV(unique_npcs)
            return
    
    # Process all families
    all_npcs = []
    
    for i, (family_id, family_name) in enumerate(families.items(), 1):
        print(f"[{i}/{len(families)}] Processing family: {family_name} (ID: {family_id})")
        
        npcs = fetch_family_npcs(family_id, family_name)
        all_npcs.extend(npcs)
        
        # Add delay between requests to avoid rate limiting
        if i < len(families):
            time.sleep(REQUEST_DELAY)
    
    print()
    print(f"Total NPCs extracted: {len(all_npcs)}")
    
    # Remove duplicates based on npc_id
    seen = set()
    unique_npcs = []
    for npc in all_npcs:
        key = npc['npc_id']
        if key not in seen:
            seen.add(key)
            unique_npcs.append(npc)
    
    if len(all_npcs) != len(unique_npcs):
        print(f"Removed {len(all_npcs) - len(unique_npcs)} duplicate NPCs")
    
    print(f"Unique NPCs: {len(unique_npcs)}")
    
    # Count by classification
    classification_counts = {}
    for npc in unique_npcs:
        cls = npc['classification']
        classification_counts[cls] = classification_counts.get(cls, 0) + 1
    
    print("Classification breakdown:")
    for cls, count in sorted(classification_counts.items()):
        print(f"  {cls}: {count}")
    
    # Save to file
    save_WOWHEAD_NPCS_CSV(unique_npcs)
    
    # Show sample
    print()
    print("Sample NPCs:")
    for npc in unique_npcs[:10]:
        print(f"  {npc['npc_id']}: {npc['npc_name']} ({npc['family_name']}) - {npc['classification']}")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Extract tameable NPCs from Wowhead family pages')
    parser.add_argument('--delay', type=float, default=REQUEST_DELAY, help='Delay between requests in seconds')
    parser.add_argument('--refresh', action='store_true', help='Refresh all data from Wowhead (skip prompt)')
    args = parser.parse_args()
    
    if args.refresh:
        # Force refresh by removing cached file
        if os.path.exists(WOWHEAD_NPCS_CSV):
            os.remove(WOWHEAD_NPCS_CSV)
    
    main()
