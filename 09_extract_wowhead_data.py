"""
Extract npc metadata for each npc in npcs.csv, except the npcs in skip_npcs.csv
"""

import os
import re
import sys
import time
import csv
import json

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import random
from config import PROCESSED_NPCS_CSV, WOWHWEAD_DATA_CSV, SKIP_NPC_IDS_CSV, ensure_dirs, get_random_headers

# Concurrency and pacing settings; adjust as needed to balance speed with risk of rate-limiting.  Note that Wowhead has aggressive rate-limiting, and even a few concurrent requests can trigger it, so we use a conservative default here.
CONCURRENCY_RANGE = (1, 5)
CONCURRENCY = random.randint(*CONCURRENCY_RANGE)
REQUEST_DELAY_RANGE = (4.0, 10.0) # Range for base request delay
BATCH_SIZE = 10              
BATCH_SECONDS = 30         
COOLDOWN_SECONDS = 120        # Initial penalty; if we still get rate-limited after this, we exponentially increase the backoff time up to MAX_BACKOFF_SECONDS seconds.
MAX_BACKOFF_SECONDS = 600

# Signal for graceful shutdown
stop_event = threading.Event()

def load_skip_npc_ids():
    skip_ids = set()
    if os.path.exists(SKIP_NPC_IDS_CSV):
        try:
            with open(SKIP_NPC_IDS_CSV, 'r', encoding='utf-8-sig', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    for key in row.keys():
                        clean_key = key.strip().replace('\ufeff', '')
                        if clean_key == 'npc_id':
                            id_value = row.get(key)
                            if id_value:
                                skip_ids.add(str(id_value).strip())
                            break
        except Exception:
            pass
    return skip_ids


def load_npcs():
    if not os.path.exists(PROCESSED_NPCS_CSV):
        print(f"Error: {PROCESSED_NPCS_CSV} not found. Run steps 7 and 8 first to produce the corrected NPC CSV.")
        sys.exit(1)
    records = []
    with open(PROCESSED_NPCS_CSV, 'r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append({
                'npc_id': str(row.get('npc_id', '')).strip(),
                'npc_name': (row.get('npc_name') or '').strip(),
                'classification': (row.get('classification') or '').strip(),
                'classification_id': int(row.get('classification_id', '0')) if str(row.get('classification_id', '0')).isdigit() else 0,
                'family_id': str(row.get('family_id', '')).strip(),
                'family_name': (row.get('family_name') or '').strip(),
                'zone_id': str(row.get('zone_id', '')).strip(),
                'react': str(row.get('react', '')).strip(),
            })
    return records


def load_progress():
    """
    Returns classified sets of npc_ids found in the output CSV.
    """
    successful_ids = set()
    skipped_ids = set()
    retry_ids = set()

    if os.path.exists(WOWHWEAD_DATA_CSV):
        with open(WOWHWEAD_DATA_CSV, 'r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                npc_id = str(row.get('npc_id', '')).strip()
                status = (row.get('status') or '').strip().lower()
                if not npc_id:
                    continue
                if status == 'successful':
                    successful_ids.add(npc_id)
                elif status == 'skipped':
                    skipped_ids.add(npc_id)
                elif status == 'retry':
                    retry_ids.add(npc_id)

    # Priority cleanup: if an ID is successful in any row, it's not a retry/skip candidate
    skipped_ids -= successful_ids
    retry_ids -= (successful_ids | skipped_ids)

    return successful_ids, skipped_ids, retry_ids


def save_progress(results, original_data, append=True):
    """
    Save progress to CSV.  results is a dict of npc_id -> data_dict.
    data_dict may be a full result or an empty dict (for skipped NPCs).

    Creates separate rows for each zone/spawn combination for successful NPCs,
    and a single 'skipped' row for NPCs that returned no usable data.
    """
    ensure_dirs()

    # Load existing rows, keyed by (npc_id, zone_name, layer)
    existing = {}
    if append and os.path.exists(WOWHWEAD_DATA_CSV):
        try:
            with open(WOWHWEAD_DATA_CSV, 'r', encoding='utf-8', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    npc_id = str(row.get('npc_id', '')).strip()
                    zone_id = str(row.get('zone_id', '')).strip()
                    spawn_id = str(row.get('layer', '')).strip()
                    if npc_id:
                        key = (npc_id, zone_id, spawn_id)
                        existing[key] = row
        except Exception:
            pass

    for npc_id, data in results.items():
        # Remove any and all existing rows for this NPC ID to ensure a clean replacement.
        # This prevents 'retry' or 'skipped' status markers from co-existing with actual data.
        keys_to_remove = [k for k in existing.keys() if k[0] == npc_id]
        for k in keys_to_remove:
            existing.pop(k)

        original = original_data.get(npc_id, {})

        # Handle Skipped NPC (confirmed empty or 404)
        if not data:
            key = (npc_id, '', '')
            existing[key] = {
                'npc_id': npc_id,
                'npc_name': original.get('npc_name', ''),
                'bulk_classification': original.get('classification', ''),
                'bulk_classification_id': original.get('classification_id', ''),
                'bulk_family_id': original.get('family_id', ''),
                'bulk_family_name': original.get('family_name', ''),
                'bulk_zone_id': original.get('zone_id', ''),
                'bulk_react': original.get('react', ''),
                'display_ids': '',
                'zone_name': '',
                'zone_id': '',
                'layer': '',
                'coords': '',
                'uiMapId': '',
                'uiMapName': '',
                'patch_id': '',
                'patch_name': '',
                'classification_id': '',
                'displayName': '',
                'family_id': '',
                'react': '[]',
                'type': '',
                'status': 'skipped',
            }
            continue

        # Handle NPCs marked for retry (403, 429, or transient errors)
        if data.get('error') == 'retry':
            key = (npc_id, '', '')
            existing[key] = {
                'npc_id': npc_id,
                'npc_name': original.get('npc_name', ''),
                'bulk_classification': original.get('classification', ''),
                'bulk_classification_id': original.get('classification_id', ''),
                'bulk_family_id': original.get('family_id', ''),
                'bulk_family_name': original.get('family_name', ''),
                'bulk_zone_id': original.get('zone_id', ''),
                'bulk_react': original.get('react', ''),
                'display_ids': '',
                'zone_name': '',
                'zone_id': '',
                'layer': '',
                'coords': '',
                'uiMapId': '',
                'uiMapName': '',
                'patch_id': '',
                'patch_name': '',
                'classification_id': '',
                'displayName': '',
                'family_id': '',
                'react': '[]',
                'type': '',
                'status': 'retry',
            }
            continue

        display_ids = '|'.join(map(str, data.get('display_ids', [])))
        zone_name = data.get('location', '') or ''
        patch_id = data.get('patch_id', '') or ''
        patch_name = data.get('patch_name', '') or ''
        obsolete = data.get('obsolete', 'No')
        zone_id_map = data.get('zone_id_map', {})
        coords_list = data.get('coords', [])
        zone_ids = data.get('zone_ids', [])
        additional_data = data.get('additional_data', {})
        classification_id = str(additional_data.get('classification_id', ''))
        display_name = additional_data.get('displayName', '') or ''
        family_id = str(additional_data.get('family_id', ''))
        react = additional_data.get('react', '[]')
        type_ = additional_data.get('type', '')

        handled_zones = set()
        if coords_list:
            for zone_id, spawn_id, uiMapName, uiMapId, coords_str in coords_list:
                if str(zone_id) in ("-1", "0"):
                    continue
                handled_zones.add(str(zone_id))
                key = (npc_id, zone_id, spawn_id)
                # Main approach: use mapped zone name for this specific zone_id, fallback to uiMapName
                row_location = zone_id_map.get(str(zone_id)) or uiMapName or zone_name
                existing[key] = {
                    'npc_id': npc_id,
                    'npc_name': original.get('npc_name', ''),
                    'bulk_classification': original.get('classification', ''),
                    'bulk_classification_id': original.get('classification_id', ''),
                    'bulk_family_id': original.get('family_id', ''),
                    'bulk_family_name': original.get('family_name', ''),
                    'bulk_zone_id': original.get('zone_id', ''),
                    'bulk_react': original.get('react', ''),
                    'display_ids': display_ids,
                    'zone_name': row_location,
                    'zone_id': zone_id,
                    'layer': str(spawn_id),
                    'coords': coords_str,
                    'uiMapId': uiMapId,
                    'uiMapName': uiMapName,
                    'patch_id': patch_id,
                    'patch_name': patch_name,
                    'classification_id': classification_id,
                    'displayName': display_name,
                    'family_id': family_id,
                    'react': react,
                    'type': type_,
                    'status': 'successful',
                    'obsolete': obsolete,
                }

        for zid in zone_ids:
            szid = str(zid)
            if szid not in ("-1", "0") and szid not in handled_zones:
                handled_zones.add(szid)
                key = (npc_id, szid, '')
                row_location = zone_id_map.get(szid, zone_name)
                existing[key] = {
                    'npc_id': npc_id,
                    'npc_name': original.get('npc_name', ''),
                    'bulk_classification': original.get('classification', ''),
                    'bulk_classification_id': original.get('classification_id', ''),
                    'bulk_family_id': original.get('family_id', ''),
                    'bulk_family_name': original.get('family_name', ''),
                    'bulk_zone_id': original.get('zone_id', ''),
                    'bulk_react': original.get('react', ''),
                    'display_ids': display_ids,
                    'zone_name': row_location or zone_name,
                    'zone_id': szid,
                    'layer': '',
                    'coords': '',
                    'uiMapId': '',
                    'uiMapName': '',
                    'patch_id': patch_id,
                    'patch_name': patch_name,
                    'classification_id': classification_id,
                    'displayName': display_name,
                    'family_id': family_id,
                    'react': react,
                    'type': type_,
                    'status': 'successful',
                    'obsolete': obsolete,
                }
        
        # Ensure even NPCs without coordinate data are properly updated with available metadata
        if not handled_zones:
            key = (npc_id, '', '')
            existing[key] = {
                'npc_id': npc_id,
                'npc_name': original.get('npc_name', ''),
                'bulk_classification': original.get('classification', ''),
                'bulk_classification_id': original.get('classification_id', ''),
                'bulk_family_id': original.get('family_id', ''),
                'bulk_family_name': original.get('family_name', ''),
                'bulk_zone_id': original.get('zone_id', ''),
                'bulk_react': original.get('react', ''),
                'display_ids': display_ids,
                'zone_name': zone_name,
                'zone_id': '',
                'layer': '',
                'coords': '',
                'uiMapId': '',
                'uiMapName': '',
                'patch_id': patch_id,
                'patch_name': patch_name,
                'classification_id': classification_id,
                'displayName': display_name,
                'family_id': family_id,
                'react': react,
                'type': type_,
                'status': 'successful',
                'obsolete': obsolete,
            }

    with open(WOWHWEAD_DATA_CSV, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(
            f,
            fieldnames=['npc_id', 'npc_name', 'bulk_classification', 'bulk_classification_id', 'bulk_family_id', 'bulk_family_name', 'bulk_zone_id', 'bulk_react', 'display_ids', 'zone_name', 'zone_id', 'layer', 'coords', 'uiMapId', 'uiMapName', 'patch_id', 'patch_name', 'classification_id', 'displayName', 'family_id', 'react', 'type', 'status', 'obsolete'],
        )
        writer.writeheader()
        for key in sorted(existing.keys(), key=lambda x: (int(x[0]) if x[0].isdigit() else 0, x[1], x[2])):
            writer.writerow(existing[key])


def robust_json_loads(json_str):
    """Parses JavaScript-style objects with unquoted keys into Python dicts."""
    if not json_str:
        return {}
    try:
        # Quote unquoted keys (e.g., {id: 123} -> {"id": 123})
        json_str = re.sub(r'([{,])\s*(\w+):', r'\1"\2":', json_str)
        return json.loads(json_str)
    except Exception:
        return {}


def extract_location_and_coords_from_html(html_content):
    """
    Extract zone name and g_mapperData (zone coordinates) from page source.
    Returns tuple: (zone_name, coords_list, zone_id_map)
    where coords_list is list of tuples: (zone_id, spawn_id, uiMapName, uiMapId, coords_string)
    """
    zone_name = ""
    coords_list = []
    zone_id_map = {}

    # MAIN APPROACH: Extract all ID/Name pairs from the 'locations' span
    try:
        locations_match = re.search(r'<span id="locations"[^>]*>(.*?)</span>', html_content, re.DOTALL)
        if locations_match:
            span_content = locations_match.group(1)
            for m in re.finditer(r'zone:\s*(\d+).*?>\s*([^<]+?)\s*</a>', span_content, re.DOTALL):
                zid, zname = m.group(1), m.group(2).strip()
                if zid not in ("-1", "0"):
                    zone_id_map[zid] = zname
                    if not zone_name:
                        zone_name = zname
            # Pattern 2: Links with href="/zone=ID/zone-name"
            for m in re.finditer(r'href="/zone=(\d+)/[^"]*?"[^>]*?>\s*([^<]+?)\s*</a>', span_content, re.DOTALL):
                zid, zname = m.group(1), m.group(2).strip()
                if zid not in ("-1", "0"):
                    zone_id_map[zid] = zname
                    if not zone_name: # Set the first found zone_name as the primary
                        zone_name = zname

    except Exception:
        pass

    # FALLBACK: Use existing patterns if map extraction above didn't yield anything
    if not zone_name:
        try:
            location_match = re.search(
                r'zone:\s*(\d+).*?WH\.setSelectedLink.*?>\s*([^<]+?)\s*</a>',
                html_content, re.DOTALL
            )
            if location_match:
                zone_name = location_match.group(2).strip()
                zone_id_map[location_match.group(1)] = zone_name
        except Exception:
            pass

    try:
        mapper_match = re.search(r'var\s+g_mapperData\s*=\s*(\{.*?\});', html_content, re.DOTALL)
        if mapper_match:
            mapper_data = robust_json_loads(mapper_match.group(1))
            for zone_id, zone_value in mapper_data.items():
                if str(zone_id) in ("-1", "0"): continue
                if isinstance(zone_value, list):
                    for idx, spawn_info in enumerate(zone_value):
                        if not isinstance(spawn_info, dict):
                            continue
                        uiMapName = spawn_info.get('uiMapName', '')
                        uiMapId = str(spawn_info.get('uiMapId', ''))
                        coords = spawn_info.get('coords', [])
                        if isinstance(coords, list) and coords:
                            coord_strings = [
                                f"{cp[0]},{cp[1]}"
                                for cp in coords
                                if isinstance(cp, list) and len(cp) == 2
                            ]
                            if coord_strings:
                                coords_list.append((zone_id, str(idx), uiMapName, uiMapId, '|'.join(coord_strings)))
                elif isinstance(zone_value, dict):
                    for spawn_id, spawn_info in zone_value.items():
                        if not isinstance(spawn_info, dict):
                            continue
                        uiMapName = spawn_info.get('uiMapName', '')
                        uiMapId = str(spawn_info.get('uiMapId', ''))
                        coords = spawn_info.get('coords', [])
                        if isinstance(coords, list) and coords:
                            coord_strings = [
                                f"{cp[0]},{cp[1]}"
                                for cp in coords
                                if isinstance(cp, list) and len(cp) == 2
                            ]
                            if coord_strings:
                                coords_list.append((zone_id, spawn_id, uiMapName, uiMapId, '|'.join(coord_strings)))
    except Exception:
        pass

    return zone_name, coords_list, zone_id_map


def extract_additional_data_from_html(html_content):
    """
    Extract additional NPC data from various JavaScript patterns.
    Returns dict with extracted data (location, level, etc.)
    """
    additional_data = {}

    try:
        extend_match = re.search(
            r'\$\.extend\(g_npcs\[(\d+)\],\s*(\{.*?\})\);',
            html_content, re.DOTALL
        )
        if extend_match:
            data_dict = robust_json_loads(extend_match.group(2))
            if 'location' in data_dict and isinstance(data_dict['location'], list):
                location_ids = [str(lid) for lid in data_dict['location'] if isinstance(lid, int) and lid not in (-1, 0)]
                if location_ids:
                    additional_data['location'] = '|'.join(location_ids)
            if 'maxlevel' in data_dict:
                additional_data['maxlevel'] = data_dict['maxlevel']
            if 'minlevel' in data_dict:
                additional_data['minlevel'] = data_dict['minlevel']
            if 'react' in data_dict and isinstance(data_dict['react'], list):
                additional_data['react'] = json.dumps(data_dict['react'], separators=(',', ':'))
            if 'classification' in data_dict:
                additional_data['classification_id'] = data_dict['classification']
            if 'displayName' in data_dict:
                additional_data['displayName'] = data_dict['displayName']
            if 'family' in data_dict:
                additional_data['family_id'] = data_dict['family']
            if 'type' in data_dict:
                additional_data['type'] = data_dict['type']

        if not additional_data.get('location'):
            for pattern in [
                r'g_npcs\[(\d+)\]\s*=\s*\{[^}]*"location"\s*:\s*\[([^\]]+)\][^}]*\}',
                r'location\s*:\s*\[([^\]]+)\]',
            ]:
                matches = re.findall(pattern, html_content)
                for match in matches:
                    if isinstance(match, tuple):
                        location_str = match[1] if len(match) > 1 else (match[0] if len(match) > 0 else "")
                    else:
                        location_str = match
                    if not location_str:
                        continue
                    location_ids = [lid for lid in re.findall(r'-?\d+', location_str) if lid not in ("-1", "0")]
                    if location_ids:
                        additional_data['location'] = '|'.join(location_ids)
                        break
                if additional_data.get('location'):
                    break

    except Exception:
        pass

    return additional_data


def extract_patch_info_from_html(html_content):
    try:
        for pattern in [
            r'Added in patch \[acronym=\\\"([^\"]+)\\\"\]([^\[]+)\[\\/acronym\]\s*\\\"([^\"]+)\\\"',
            r'Added in patch \[acronym=\"([^\"]+)\"\]([^\[]+)\[\\/acronym\]\s*\"([^\"]+)\"',
        ]:
            match = re.search(pattern, html_content, re.IGNORECASE)
            if match:
                full_version = match.group(1).strip()
                patch_name = match.group(3).strip() if len(match.groups()) > 2 else ""
                version_parts = full_version.split('.')
                patch_id = '.'.join(version_parts[:3]) if len(version_parts) >= 3 else full_version
                if re.match(r'^[0-9]+\.[0-9]+\.[0-9]+$', patch_id):
                    return patch_id, patch_name

        for pattern in [
            r'Added in patch \[acronym=\\\"([^\"]+)\\\"\]([^\[]+)\[\\/acronym\]',
            r'Added in patch \[acronym=\"([^\"]+)\"\]([^\[]+)\[\\/acronym\]',
            r'Added in patch[^0-9]*([0-9]+\.[0-9]+\.[0-9]+)',
        ]:
            patch_match = re.search(pattern, html_content)
            if patch_match:
                patch_id = patch_match.group(1).strip()
                if re.match(r'^[0-9]+\.[0-9]+\.[0-9]+$', patch_id):
                    return patch_id, ""

    except Exception:
        pass

    return "", ""


_tls = threading.local()

# Global state for thread coordination
rate_limit_lock = threading.Lock()
request_stagger_lock = threading.Lock()
global_backoff_until = 0  # Timestamp
global_last_request_time = 0


def get_session():
    if getattr(_tls, 'session', None) is None:
        s = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retries, pool_connections=CONCURRENCY * 2, pool_maxsize=CONCURRENCY * 2)
        s.mount('http://', adapter)
        s.mount('https://', adapter)
        _tls.session = s
    return _tls.session


def fetch_npc_data(npc_id, npc_name, family_name):
    global global_backoff_until
    url = f"https://www.wowhead.com/npc={npc_id}"
    max_attempts = 3
    attempt = 0

    while attempt < max_attempts:
        if stop_event.is_set():
            return {'error': 'interrupted'}

        # 1. Check Global Backoff - if any thread hit a limit, we all wait
        with rate_limit_lock:
            wait_time = global_backoff_until - time.time()
        if wait_time > 0:
            # Sleep in small increments to remain responsive to Ctrl+C
            for _ in range(int(wait_time) + 1):
                if stop_event.is_set(): return {'error': 'interrupted'}
                time.sleep(1)
            time.sleep(random.uniform(1, 5)) # Jitter to prevent burst-firing after cooldown
            continue

        try:
            sess = get_session()
            hdr_idx, hdrs = get_random_headers()
            
            # Randomize delay per request for better evasion
            time.sleep(random.uniform(*REQUEST_DELAY_RANGE))
            
            attempt += 1
            response = sess.get(url, headers=hdrs, timeout=(5, 25))
            status = response.status_code

            if status in (403, 429):
                if hasattr(_tls, 'session'): del _tls.session
                return {'error': 'retry', 'header_idx': hdr_idx}

            response.raise_for_status()
            html_content = response.text

            # Detect "This NPC is not in game." status
            obsolete = "Yes" if '<b style="color: red">This NPC is not in game.</b>' in html_content else "No"

            # Process successful data
            display_ids = set()
            for did in re.findall(r'"npcmodel"\s*:\s*(\d+)', html_content):
                if did != '0':
                    display_ids.add(did)

            if not display_ids:
                for pattern in [r'data-mv-display-id="(\d+)"', r'"display_id"\s*:\s*(\d+)', r'data-display-id="(\d+)"']:
                    for did in re.findall(pattern, html_content):
                        if did != '0':
                            display_ids.add(did)

            zone_name, coords_list, zone_id_map = extract_location_and_coords_from_html(html_content)
            patch_id, patch_name = extract_patch_info_from_html(html_content)
            additional_data = extract_additional_data_from_html(html_content)

            zone_ids = []
            if 'location' in additional_data:
                zone_ids = additional_data['location'].split('|') if additional_data['location'] else []
            else:
                zone_ids = list(zone_id_map.keys())

            return {
                'display_ids': sorted(display_ids, key=int),
                'zone_name': zone_name,
                'coords': coords_list,
                'zone_ids': zone_ids,
                'zone_id_map': zone_id_map,
                'patch_id': patch_id,
                'patch_name': patch_name,
                'additional_data': additional_data,
                'obsolete': obsolete,
                'header_idx': hdr_idx,
            }

        except requests.RequestException as e:
            # Check if it's a 404 - if so, we can skip it permanently
            if hasattr(e, 'response') and e.response is not None and e.response.status_code == 404:
                return {'error': 'not_found'}

            if attempt >= max_attempts:
                print(f"  Error fetching NPC {npc_id} after {attempt} tries: {e}")
                return {'error': 'retry'}
            time.sleep(2)

    return {'error': 'retry'}


def filter_skipped_npcs(npcs, skip_ids):
    return [npc for npc in npcs if str(npc.get('npc_id')) not in skip_ids]


def main():
    ensure_dirs()

    print("=" * 60)
    print("Step 3: Enriching NPC Data (Display IDs, Location, Patch)")
    print("=" * 60)
    print(f"Concurrency: {CONCURRENCY}")
    print(f"Request delay: Random {REQUEST_DELAY_RANGE[0]}-{REQUEST_DELAY_RANGE[1]}s per request")
    print(f"Batch flush: every {BATCH_SIZE} NPCs or {BATCH_SECONDS}s")
    print()

    print("Loading skip list...")
    skip_ids = load_skip_npc_ids()
    print(f"Found {len(skip_ids)} NPC IDs to skip" if skip_ids else "No skip list found")
    print()

    print(f"Loading corrected NPCs from {PROCESSED_NPCS_CSV}...")
    all_npcs = load_npcs()
    original_data = {npc['npc_id']: npc for npc in all_npcs}
    print(f"Loaded {len(all_npcs)} total NPCs")

    npcs = filter_skipped_npcs(all_npcs, skip_ids)
    skipped_count = len(all_npcs) - len(npcs)
    if skipped_count > 0:
        print(f"Skipped {skipped_count} NPCs from skip list")

    print(f"Processing {len(npcs)} NPCs (zone data extracted from web pages)")
    print()

    print("Loading previous progress...")
    successful_ids, skipped_ids, retry_ids = load_progress()
    
    valid_ids = {str(npc.get('npc_id')) for npc in npcs}
    successful_ids &= valid_ids
    skipped_ids &= valid_ids
    retry_ids &= valid_ids

    print(f"  Already Successful: {len(successful_ids)}")
    print(f"  Already Skipped:    {len(skipped_ids)}")
    print(f"  Marked for Retry:   {len(retry_ids)}")

    # We only skip NPCs that are finished (successful or confirmed empty/skipped)
    done_ids = successful_ids | skipped_ids
    npcs_to_process = [npc for npc in npcs if str(npc.get('npc_id')) not in done_ids]
    
    retries_in_batch = [npc for npc in npcs_to_process if str(npc.get('npc_id')) in retry_ids]
    new_in_batch = [npc for npc in npcs_to_process if str(npc.get('npc_id')) not in retry_ids]

    print(f"\nTotal NPCs to process: {len(npcs_to_process)} ({len(retries_in_batch)} retries, {len(new_in_batch)} new)")
    print()

    if not npcs_to_process:
        print("All non-skipped NPCs have already been processed!")
        processed = 0
    else:
        start_time = time.time()
        last_flush = start_time
        processed = 0
        consecutive_403_count = 0

        def _task(npc):
            npc_id = str(npc.get('npc_id'))
            npc_name = npc.get('npc_name', 'Unknown')
            family_name = npc.get('family_name', 'Unknown')
            if stop_event.is_set():
                return 'skip', npc_id, npc_name, family_name, {'error': 'interrupted'}
            
            data = fetch_npc_data(npc_id, npc_name, family_name)
            error = data.get('error')
            
            if error == 'retry':
                return 'retry', npc_id, npc_name, family_name, data
            
            has_data = (
                data
                and isinstance(data, dict)
                and not error
                and (data.get('display_ids') or data.get('location') or data.get('patch_id'))
            )
            
            if has_data:
                return 'success', npc_id, npc_name, family_name, data
            else:
                # This is a confirmed "Empty" page or 404
                return 'skip', npc_id, npc_name, family_name, {}

        executor = ThreadPoolExecutor(max_workers=CONCURRENCY)
        futures = [executor.submit(_task, npc) for npc in npcs_to_process]
        total = len(futures)
        batch_results = {}

        try:
            for future in as_completed(futures):
                if stop_event.is_set():
                    break

                status, npc_id, npc_name, family_name, data = future.result()
                processed += 1

                # Always record the result (success or skip) so it won't be retried
                batch_results[npc_id] = data

                if status == 'success':
                    h_idx = data.get('header_idx', '?')
                    print(
                        f"[{processed}/{total}] {npc_id}: {npc_name} ({family_name}) -> OK (Header #{h_idx}) "
                        f"(display_ids={len(data.get('display_ids', []))}, "
                        f"zone_name={data.get('zone_name') or 'missing'}, "
                        f"coords={len(data.get('coords', []))}, "
                        f"patch={data.get('patch_id') or 'missing'})"
                    )
                    consecutive_403_count = 0
                elif status == 'retry':
                    h_idx = data.get('header_idx', '?')
                    consecutive_403_count += 1
                    print(f"[{processed}/{total}] {npc_id}: {npc_name} -> 403 Forbidden (Header Set #{h_idx}, Retry #{consecutive_403_count})")
                    
                    # Trigger global cooldown only if we hit a full "batch" of failures
                    if consecutive_403_count >= CONCURRENCY:
                        with rate_limit_lock:
                            global_backoff_until = time.time() + COOLDOWN_SECONDS
                            print(f"  ! Global rate limit threshold reached. Cooling down for {COOLDOWN_SECONDS}s...")
                        
                        # Actually pause the main thread so you see the countdown/pause
                        for _ in range(COOLDOWN_SECONDS):
                            if stop_event.is_set(): break
                            time.sleep(1)
                        consecutive_403_count = 0
                elif data.get('error') == 'interrupted':
                    continue
                else:
                    print(f"[{processed}/{total}] {npc_id}: {npc_name} ({family_name}) -> Skipped (no data)")
                    # Skips/404s are now neutral; they don't reset the 403 counter to prevent "stuttering" through blocks

                now = time.time()
                if (processed % BATCH_SIZE == 0) or (now - last_flush >= BATCH_SECONDS):
                    save_progress(batch_results, original_data)
                    batch_results = {}
                    last_flush = now
        except KeyboardInterrupt:
            print("\n[!] Cancellation requested. Shutting down gracefully...")
            stop_event.set()
            executor.shutdown(wait=False, cancel_futures=True)
        finally:
            if batch_results:
                save_progress(batch_results, original_data)
            executor.shutdown(wait=False)

        # Final flush for any remaining results
        total_time = time.time() - start_time
        print()
        print(f"Processed {processed} NPCs in {total_time / 60:.1f} minutes")

    complete_count = len(done_ids) + processed

    print()
    print("=" * 60)
    print("ENRICHMENT COMPLETE")
    print("=" * 60)
    print(f"Total NPCs: {len(all_npcs)}")
    print(f"Skipped NPCs (skip list): {skipped_count}")
    print(f"Non-skipped NPCs:         {len(npcs)}")
    print(f"Successfully processed:   {complete_count}")
    print(f"\nProgress CSV saved to: {WOWHWEAD_DATA_CSV}")
    print("=" * 60)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Enrich NPC data with display IDs, location, patch info, classification, displayName, and family')
    parser.add_argument('--delay', type=float, default=REQUEST_DELAY_RANGE[0], help='Delay between requests in seconds')
    parser.add_argument('--reset', action='store_true', help='Reset progress and start fresh')
    args = parser.parse_args()

    if args.reset:
        if os.path.exists(WOWHWEAD_DATA_CSV):
            os.remove(WOWHWEAD_DATA_CSV)
            print("Progress file reset.")

    main()