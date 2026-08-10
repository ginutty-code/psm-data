"""
Clean and filter Wowhead records before combining with Petopia data.

This step performs the following cleaning operations:
1. Filters out records that are not 'successful' or are marked as obsolete.
2. Filters out NPC IDs specified in the NPC skip list.
3. Filters individual display IDs against the display ID skip list. If a record has no display IDs left, it is dropped.
4. Performs row-level deduplication to ensure unique entries.
5. Standardizes and cleans fields.
6. Applies location updates from Manual/location_updates.csv to fill in or correct
   zone_id, layer, uiMapId, uiMapName, and coords.
7. Thins coordinates in the 'coords' column by removing points that are too close to each other (minimum distance: 2.0).
"""

import csv
import os
import sys

from config import (
    LOCATION_UPDATES_CSV,
    PROCESSED_WOWHEAD_DATA_CSV,
    SKIP_DISPLAY_IDS_CSV,
    SKIP_NPC_IDS_CSV,
    WOWHEAD_DATA_CSV,
    ensure_dirs,
)

# Minimum allowed distance between any two kept coordinate points.
# Increase for more aggressive thinning, decrease to keep more points.
COORD_MIN_DISTANCE = 2.0


def thin_points(points, min_distance):
    """Return a list of points where no two points are closer than min_distance."""
    kept = []
    for p in points:
        x, y = p
        if all(((x - kx) ** 2 + (y - ky) ** 2) ** 0.5 >= min_distance for kx, ky in kept):
            kept.append(p)
    return kept


def thin_coord_string(coord_str, min_distance, densest_first=True):
    """Thin a coordinate string of format 'x1,y1|x2,y2|...' or 'x1 y1|x2 y2|...'."""
    if not coord_str.strip():
        return coord_str

    # Handle both comma and space separators in coordinate pairs
    raw_pairs = coord_str.split('|')
    pairs = []
    for p in raw_pairs:
        p = p.strip()
        if not p:
            continue
        # Split by comma or whitespace
        if ',' in p:
            x_str, y_str = p.split(',', 1)
        else:
            parts = p.split()
            if len(parts) >= 2:
                x_str, y_str = parts[0], parts[1]
            else:
                continue
        try:
            pairs.append((float(x_str), float(y_str)))
        except ValueError:
            continue

    if densest_first:
        def neighbor_count(p):
            x, y = p
            return sum(
                1 for x2, y2 in pairs
                if ((x - x2) ** 2 + (y - y2) ** 2) ** 0.5 < min_distance
            )
        pairs = sorted(pairs, key=neighbor_count, reverse=True)

    thinned = thin_points(pairs, min_distance)
    return '|'.join(f"{x:g},{y:g}" for x, y in thinned)



def load_skip_ids(filepath, col_names):
    """Load stripped string values from the specified column in a CSV file."""
    result = set()
    if not os.path.exists(filepath):
        print(f"Warning: Skip list file not found: {filepath}")
        return result
    with open(filepath, 'r', encoding='utf-8-sig', newline='', errors='replace') as f:
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


def load_skip_npc_data(filepath):
    """
    Load global, zone-specific, and zone+layer-specific NPC skip rules.

    Matching hierarchy (most specific wins):
      - npc_id only (zone_id empty)            -> global skip: all records for this NPC
      - npc_id + zone_id (layer empty)         -> zone skip: all records for this NPC in this zone
      - npc_id + zone_id + layer               -> layer skip: only the record matching this exact zone/layer combination
    """
    global_skips = set()       # {npc_id}
    zone_skips = set()         # {(npc_id, zone_id)}
    layer_skips = set()        # {(npc_id, zone_id, layer)}
    if not os.path.exists(filepath):
        print(f"Warning: NPC skip list file not found: {filepath}")
        return global_skips, zone_skips, layer_skips
    with open(filepath, 'r', encoding='utf-8-sig', newline='', errors='replace') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        has_zone_col = 'zone_id' in fieldnames
        has_layer_col = 'layer' in fieldnames
        for row in reader:
            npc_id = row.get('npc_id', '').strip()
            if not npc_id:
                continue
            zone_id = row.get('zone_id', '').strip() if has_zone_col else ''
            layer = row.get('layer', '').strip() if has_layer_col else ''
            if zone_id and layer:
                layer_skips.add((npc_id, zone_id, layer))
            elif zone_id:
                zone_skips.add((npc_id, zone_id))
            else:
                global_skips.add(npc_id)
    return global_skips, zone_skips, layer_skips


def load_location_updates(filepath):
    """
    Load location updates from the manual CSV file.

    Returns two lookup structures:
      exact_updates: dict of (npc_id, zone_id, layer) -> list of update dicts
      npc_only_updates: dict of npc_id -> list of update dicts (for Scenario 1)

    Blank layer values are treated as "0" for matching purposes.
    """
    exact_updates = {}   # key: (npc_id, zone_id, layer) -> [row, ...]
    npc_only_updates = {}  # key: npc_id -> [row, ...]

    if not os.path.exists(filepath):
        print(f"Warning: Location updates file not found: {filepath}")
        return exact_updates, npc_only_updates

    with open(filepath, 'r', encoding='utf-8-sig', newline='', errors='replace') as f:
        reader = csv.DictReader(f)
        for row in reader:
            npc_id = row.get('npc_id', '').strip()
            if not npc_id:
                continue

            zone_id = row.get('zone_id', '').strip()
            layer = row.get('layer', '').strip()
            # Treat blank layer as "0"
            if layer == '':
                layer = '0'

            # Build the update record with only the fields we want to apply
            update = {
                'zone_id': zone_id,
                'layer': layer,
                'uiMapId': row.get('uiMapId', '').strip(),
                'uiMapName': row.get('uiMapName', '').strip(),
                'coords': row.get('coords', '').strip(),
            }

            # Index by (npc_id, zone_id, layer) for exact matching (Scenarios 2-5)
            key = (npc_id, zone_id, layer)
            if key not in exact_updates:
                exact_updates[key] = []
            exact_updates[key].append(update)

            # Also index by npc_id only for Scenario 1 matching
            if npc_id not in npc_only_updates:
                npc_only_updates[npc_id] = []
            npc_only_updates[npc_id].append(update)

    print(f"Loaded {len(exact_updates)} exact location update keys and {len(npc_only_updates)} NPC-only keys.")
    return exact_updates, npc_only_updates


def apply_location_updates(record, exact_updates, npc_only_updates):
    """
    Check if a source record has matching location updates and apply them.

    Returns a list of updated record dicts (may be multiple if one source row
    matches multiple updates, e.g. different layers). If no match, returns
    a list containing the original record unchanged.

    Matching logic:
      Scenario 1: Source has valid npc_id but empty zone_id AND empty layer
                  -> match by npc_id only
      Scenarios 2-5: Source has valid npc_id + zone_id + layer
                  -> match by (npc_id, zone_id, layer) exactly
    """
    npc_id = record.get('npc_id', '')
    zone_id = record.get('zone_id', '').strip()
    layer = record.get('layer', '').strip()
    if layer == '':
        layer = '0'

    matches = []

    # Try exact match by (npc_id, zone_id, layer) first (Scenarios 2-5)
    if zone_id:
        key = (npc_id, zone_id, layer)
        if key in exact_updates:
            matches = exact_updates[key]

    # If no exact match and source has empty zone_id+layer, try npc_id-only (Scenario 1)
    if not matches and not zone_id and npc_id in npc_only_updates:
        matches = npc_only_updates[npc_id]

    if not matches:
        # No update applies — return the original record unchanged
        return [record]

    # Apply each matching update, creating one output row per match
    results = []
    for update in matches:
        new_record = dict(record)  # shallow copy
        # Overwrite fields from the update
        new_record['zone_id'] = update['zone_id']
        new_record['layer'] = update['layer']
        new_record['uiMapId'] = update['uiMapId']
        new_record['uiMapName'] = update['uiMapName']
        # Only overwrite coords if the update provides them
        if update['coords']:
            new_record['coords'] = update['coords']
        results.append(new_record)

    return results


def clean_record_fields(row):
    """Clean fields in the record (stripping whitespace, etc.)."""
    cleaned = {}
    for k, v in row.items():
        cleaned[k] = str(v).strip() if v is not None else ""
    return cleaned


def main():
    print("=" * 60)
    print("Step 10: Clean Wowhead Data")
    print("=" * 60)
    ensure_dirs()

    # Load skip lists
    skip_npc_ids, skip_npc_zones, skip_npc_layers = load_skip_npc_data(SKIP_NPC_IDS_CSV)
    print(f"Loaded {len(skip_npc_ids)} global, {len(skip_npc_zones)} zone-specific, and {len(skip_npc_layers)} layer-specific NPC rules to skip.")

    skip_display_ids = load_skip_ids(SKIP_DISPLAY_IDS_CSV, {'id', 'display_id'})
    print(f"Loaded {len(skip_display_ids)} Display IDs to skip.")

    # Load location updates
    exact_updates, npc_only_updates = load_location_updates(LOCATION_UPDATES_CSV)

    if not os.path.exists(WOWHEAD_DATA_CSV):
        print(f"Error: {WOWHEAD_DATA_CSV} not found. Please run Step 09 (extract_wowhead_data) first.")
        sys.exit(1)

    print(f"Reading records from {WOWHEAD_DATA_CSV}...")
    
    # Read headers first to ensure we write the exact same columns
    with open(WOWHEAD_DATA_CSV, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.reader(f)
        headers = next(reader) if reader else []

    if not headers:
        print("Error: Input CSV file is empty or has no headers.")
        sys.exit(1)

    # Statistics tracking
    total_loaded = 0
    skipped_status = 0
    skipped_obsolete = 0
    skipped_npc_skip = 0
    skipped_display_skip = 0
    skipped_duplicates = 0
    location_updates_applied = 0
    location_rows_split = 0

    seen_records = set()
    cleaned_rows = []

    with open(WOWHEAD_DATA_CSV, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f)
        for row in reader:
            total_loaded += 1
            record = clean_record_fields(row)

            npc_id = record.get('npc_id')
            if not npc_id:
                continue

            # 1. Filter by status
            if record.get('status') != 'successful':
                skipped_status += 1
                continue

            # 2. Filter by obsolete flag
            if record.get('obsolete') == 'Yes':
                skipped_obsolete += 1
                continue

            # 3. Filter by NPC skip list (global, zone-specific, or zone+layer-specific)
            zone_id = record.get('zone_id', '')
            layer = record.get('layer', '')
            if (
                npc_id in skip_npc_ids
                or (npc_id, zone_id) in skip_npc_zones
                or (npc_id, zone_id, layer) in skip_npc_layers
            ):
                skipped_npc_skip += 1
                continue

            # 4. Filter Display IDs against display ID skip list
            display_ids_str = record.get('display_ids', '')
            display_ids = [d.strip() for d in display_ids_str.split('|') if d.strip()]
            allowed_display_ids = [d for d in display_ids if d not in skip_display_ids]

            if not allowed_display_ids:
                skipped_display_skip += 1
                continue

            # Update the record with the filtered display IDs
            record['display_ids'] = '|'.join(allowed_display_ids)

            # 5. Apply location updates (may split one source row into multiple)
            updated_records = apply_location_updates(record, exact_updates, npc_only_updates)

            if len(updated_records) > 1:
                location_rows_split += 1
            if updated_records != [record]:
                location_updates_applied += 1

            # 6. Apply coordinate thinning to the coords field
            for updated_record in updated_records:
                if updated_record.get('coords'):
                    updated_record['coords'] = thin_coord_string(
                        updated_record['coords'],
                        COORD_MIN_DISTANCE
                    )

            # 7. Row deduplication based on key fields
            for updated_record in updated_records:
                zone_id = updated_record.get('zone_id', '')
                coords = updated_record.get('coords', '')
                display_signature = updated_record['display_ids']
                sig = (npc_id, zone_id, display_signature, coords)

                if sig in seen_records:
                    skipped_duplicates += 1
                    continue

                seen_records.add(sig)
                cleaned_rows.append(updated_record)

    # Write cleaned rows
    print(f"Writing {len(cleaned_rows)} cleaned records to {PROCESSED_WOWHEAD_DATA_CSV}...")
    with open(PROCESSED_WOWHEAD_DATA_CSV, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(cleaned_rows)

    # Print summary of findings
    print("\n" + "-" * 40)
    print("Cleaning Statistics Summary:")
    print(f"  Total records loaded:              {total_loaded}")
    print(f"  Skipped (status != successful):     {skipped_status}")
    print(f"  Skipped (obsolete == 'Yes'):       {skipped_obsolete}")
    print(f"  Skipped (NPC skip list):           {skipped_npc_skip}")
    print(f"  Skipped (no display IDs left):     {skipped_display_skip}")
    print(f"  Location updates applied:          {location_updates_applied}")
    print(f"  Source rows split into multiple:   {location_rows_split}")
    print(f"  Skipped (duplicate rows):          {skipped_duplicates}")
    print(f"  Final records written:             {len(cleaned_rows)}")
    print("-" * 40 + "\n")
    print("Wowhead data cleaning step completed successfully.")

if __name__ == "__main__":
    main()