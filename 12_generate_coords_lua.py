"""
Generate addon Coordinates data file
"""

import csv
import os
from config import COMBINED_PET_DATA_CSV, COORDS_LUA, ensure_dirs


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

    # Group data by npc_id
    npc_data = {}

    for row in rows:
        uiMapId = row.get("uiMapId", "").strip()
        if not uiMapId:
            continue

        location = row.get("zone_name", "").strip()
        npc_id = row.get("npc_id", "").strip()

        coords = row.get("coords", "").strip()

        # Skip records with empty coordinates
        if not coords:
            continue

        # Initialize npc entry if not exists
        if npc_id not in npc_data:
            npc_data[npc_id] = {}

        # Store location data
        npc_data[npc_id][location] = {
            'coords': coords,
            'uiMapId': uiMapId
        }

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
        f.write("-- Format: CoordsData[npc_id] = {[location] = {coords = \"coords\", uiMapId = uiMapId}, ...}\n")
        f.write("\n")
        f.write("CoordsData = {\n")

        # Sort NPC IDs numerically
        sorted_npc_ids = sorted(npc_data.keys(), key=lambda x: int(x) if x.isdigit() else float('inf'))

        for i, npc_id in enumerate(sorted_npc_ids):
            locations = npc_data[npc_id]

            # Add comma before NPC (except first)
            if i > 0:
                f.write(",\n")

            # Write NPC entry
            f.write(f'    [{npc_id}] = {{\n')

            # Sort locations alphabetically
            sorted_locations = sorted(locations.keys())

            for j, location in enumerate(sorted_locations):
                data = locations[location]
                coords_lua = lua_quote(data['coords'])
                uiMapId = data['uiMapId']
                location_lua = lua_quote(location)

                # Add comma before location (except first)
                if j > 0:
                    f.write(',\n')

                f.write(f'        [{location_lua}] = {{coords = {coords_lua}, uiMapId = {uiMapId}}}')

            f.write('\n    }')

        f.write("\n}\n")

    # Print summary
    total_npcs = len(npc_data)

    print(f"Done! Lua file saved to: {COORDS_LUA}")
    print(f"Summary: {total_npcs} NPCs")


if __name__ == "__main__":
    main()