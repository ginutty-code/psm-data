"""
Generate addon Models data file (flat format by npcId)
"""

import csv
import os

from config import (
    COMBINED_PET_DATA_CSV,
    MODELS_LUA,
    SKIP_DISPLAY_IDS_CSV,
    ensure_dirs,
    sync_output_to_addon,
)


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
        except (OSError, csv.Error) as e:
            print(f"Warning: Could not read {filepath} as {encoding}: {e}")
            continue
    
    return []


def load_skip_display_ids():
    """Load skip display IDs from CSV file."""
    skip_ids = set()
    if os.path.exists(SKIP_DISPLAY_IDS_CSV):
        try:
            with open(SKIP_DISPLAY_IDS_CSV, 'r', encoding='utf-8-sig', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    for key in row:
                        clean_key = key.strip().replace('\ufeff', '')
                        if clean_key in ('id', 'display_id'):
                            id_value = row.get(key)
                            if id_value:
                                skip_ids.add(str(id_value).strip())
                            break
        except (OSError, csv.Error) as e:
            print(f"Warning: Could not read skip list {SKIP_DISPLAY_IDS_CSV}: {e}")
    return skip_ids


def main():
    ensure_dirs()

    print(f"Loading CSV from {COMBINED_PET_DATA_CSV}...")
    if not os.path.exists(COMBINED_PET_DATA_CSV):
        print(f"Error: CSV file not found: {COMBINED_PET_DATA_CSV}")
        return
    
    print("Loading skip display IDs...")
    skip_display_ids = load_skip_display_ids()
    print(f"Found {len(skip_display_ids)} display IDs to skip")

    # Read CSV and build flat data structure keyed by npc_id (integer)
    npcs = {}
    rows = load_csv(COMBINED_PET_DATA_CSV)

    for row in rows:
        raw_npc_id = row.get("npc_id", "").strip()
        if not raw_npc_id:
            continue

        try:
            npc_id = int(raw_npc_id)
        except ValueError:
            continue

        if npc_id not in npcs:
            npcs[npc_id] = {
                "name": row.get("npc_name", "").strip(),
                "displayIds": set(),
                "uiMapId": None,
                "uiMapName": None,
                "family": row.get("family_name", "").strip(),
                "expansion": row.get("expansion", "").strip() or "Unknown",
                "react": row.get("react", "").strip(),
                "classification": row.get("classification_name", "").strip() or "Normal",
                "nameKeeper": row.get("name_keeper", "").strip() == "True",
                "taming": set(),
                "conditions": set(),
            }

        entry = npcs[npc_id]

        # Extract map information (first valid map ID > 0)
        mid_str = row.get("uiMapId", "").strip()
        mname_str = row.get("uiMapName", "").strip()
        if entry["uiMapId"] is None and mid_str and mid_str != "0":
            try:
                entry["uiMapId"] = int(mid_str)
                entry["uiMapName"] = mname_str
            except ValueError:
                pass

        # Extract display IDs
        display_ids_str = row.get("display_ids", "").strip()
        if display_ids_str:
            for d in display_ids_str.split('|'):
                d_clean = d.strip()
                if d_clean and d_clean not in skip_display_ids:
                    try:
                        entry["displayIds"].add(int(d_clean))
                    except ValueError:
                        pass

        # Extract taming requirements
        taming_csv = row.get("taming_requirements", "").strip()
        if taming_csv:
            for t in taming_csv.split('|'):
                if t.strip():
                    entry["taming"].add(t.strip())

        # Extract special conditions
        conditions_csv = row.get("special_conditions", "").strip()
        if conditions_csv:
            for c in conditions_csv.split('|'):
                if c.strip():
                    entry["conditions"].add(c.strip())

    print(f"Processed {len(npcs)} unique NPCs")

    # Generate Lua file
    print(f"Generating Lua file to {MODELS_LUA}...")
    
    def lua_quote(s):
        if s is None:
            s = ""
        return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'

    with open(MODELS_LUA, 'w', encoding='utf-8') as f:
        f.write("-- Models Data Export\n")
        f.write("-- Generated automatically\n")
        f.write("-- Flat table structure: ModelsData[npcId] = { ... }\n\n")
        f.write("ModelsData = {\n")

        sorted_npc_ids = sorted(npcs.keys())
        for npc_id in sorted_npc_ids:
            entry = npcs[npc_id]

            sorted_dids = sorted(entry["displayIds"])
            dids_str = "{ " + ", ".join(str(d) for d in sorted_dids) + " }"

            f.write(f"    [{npc_id}] = {{\n")
            f.write(f"        name = {lua_quote(entry['name'])},\n")
            f.write(f"        displayIds = {dids_str},\n")

            if entry["uiMapId"] is not None:
                f.write(f"        uiMapId = {entry['uiMapId']},\n")
            if entry["uiMapName"]:
                f.write(f"        uiMapName = {lua_quote(entry['uiMapName'])},\n")

            f.write(f"        family = {lua_quote(entry['family'])},\n")
            f.write(f"        expansion = {lua_quote(entry['expansion'])},\n")
            f.write(f"        react = {lua_quote(entry['react'])},\n")
            f.write(f"        classification = {lua_quote(entry['classification'])},\n")

            nk_str = "true" if entry["nameKeeper"] else "false"
            f.write(f"        nameKeeper = {nk_str},\n")

            if entry["taming"]:
                sorted_taming = sorted(entry["taming"])
                taming_str = "{ " + ", ".join(lua_quote(t) for t in sorted_taming) + " }"
                f.write(f"        taming = {taming_str},\n")

            f.write("    },\n")

        f.write("}\n")

    print(f"Done! Lua file saved to: {MODELS_LUA}")
    sync_output_to_addon(MODELS_LUA)


if __name__ == "__main__":
    main()