"""
Generate addon Coordinates data file
"""

import csv
import os
from config import COMBINED_PET_DATA_CSV, COORDS_LUA, ensure_dirs, sync_output_to_addon


def load_csv(filepath):
    """Load CSV file with encoding fallback and return all rows."""
    encodings = ['utf-8', 'utf-8-sig', 'cp1252', 'latin-1']

    for encoding in encodings:
        try:
            with open(filepath, 'r', encoding=encoding, errors='replace') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                if rows:
                    return rows
        except Exception:
            continue

    return []


def main():
    print(f"Loading CSV from {COMBINED_PET_DATA_CSV}...")
    if not os.path.exists(COMBINED_PET_DATA_CSV):
        print(f"Error: CSV file not found: {COMBINED_PET_DATA_CSV}")
        return

    # Read the coords CSV
    rows = load_csv(COMBINED_PET_DATA_CSV)

    # Group data by uiMapId -> location_name -> npcs with coords
    zone_data = {}

    for row in rows:
        uiMapId = row.get("uiMapId", "").strip()
        if not uiMapId:
            continue

        location = row.get("uiMapName", "").strip()
        continent = row.get("continent_name", "").strip()
        npc_id = row.get("npc_id", "").strip()
        coords = row.get("coords", "").strip()

        # Initialize zone entry if not exists
        if uiMapId not in zone_data:
            zone_data[uiMapId] = {
                'name': location,
                'continent': continent,
                'npcs': {}
            }

        # Store NPC under this zone, even if coords are empty
        if npc_id not in zone_data[uiMapId]['npcs']:
            zone_data[uiMapId]['npcs'][npc_id] = {'coords': coords}
        else:
            # If multiple coords entries exist for same npc_id in same zone, merge them
            existing = zone_data[uiMapId]['npcs'][npc_id]['coords']
            if coords and coords not in existing:
                zone_data[uiMapId]['npcs'][npc_id]['coords'] = existing + '|' + coords if existing else coords

    # Generate Lua file
    print(f"Generating Lua file to {COORDS_LUA}...")

    def lua_quote(s):
        if s is None:
            s = ""
        # Escape backslashes and double quotes for safe Lua string literals
        return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'

    with open(COORDS_LUA, 'w', encoding='utf-8') as f:
        f.write("-- Coords Data Export\n")
        f.write("-- Generated automatically\n")
        f.write("-- Format: CoordsData[uiMapId] = {name = \"ZoneName\", npcs = {[npc_id] = {coords = \"...\"}, ...}}\n")
        f.write("\n")
        f.write("CoordsData = {\n")

        # Sort zone IDs numerically
        sorted_zone_ids = sorted(zone_data.keys(), key=lambda x: int(x) if x.isdigit() else float('inf'))

        for i, uiMapId in enumerate(sorted_zone_ids):
            zone = zone_data[uiMapId]
            zone_name_lua = lua_quote(zone['name'])

            # Add comma before zone (except first)
            if i > 0:
                f.write(",\n")

            # Write zone entry
            f.write(f'    [{uiMapId}] = {{\n')
            f.write(f'        name = {zone_name_lua},\n')
            if zone.get('continent'):
                f.write(f'        continent = {lua_quote(zone["continent"])},\n')
            f.write(f'        npcs = {{\n')

            # Sort NPC IDs numerically
            sorted_npc_ids = sorted(zone['npcs'].keys(), key=lambda x: int(x) if x.isdigit() else float('inf'))

            for j, npc_id in enumerate(sorted_npc_ids):
                npc_coords = zone['npcs'][npc_id]['coords']
                coords_lua = lua_quote(npc_coords)

                # Add comma before NPC (except first)
                if j > 0:
                    f.write(",\n")

                f.write(f'            [{npc_id}] = {{coords = {coords_lua}}}')

            f.write('\n        }\n    }')

        f.write("\n}\n")

    # Print summary
    total_zones = len(zone_data)
    unique_npcs = set()
    for z in zone_data.values():
        unique_npcs.update(z['npcs'].keys())
    total_npcs = len(unique_npcs)

    print(f"Done! Lua file saved to: {COORDS_LUA}")
    print(f"Summary: {total_zones} zones, {total_npcs} NPC entries")
    sync_output_to_addon(COORDS_LUA)


if __name__ == "__main__":
    main()