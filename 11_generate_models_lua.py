"""
Generate addon Models data file
"""

import csv
import os
from config import COMBINED_PET_DATA_CSV, SKIP_DISPLAY_IDS_CSV, MODELS_LUA, ensure_dirs



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


def load_skip_display_ids():
    """Load skip display IDs from CSV file."""
    skip_ids = set()
    if os.path.exists(SKIP_DISPLAY_IDS_CSV):
        try:
            with open(SKIP_DISPLAY_IDS_CSV, 'r', encoding='utf-8-sig', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    for key in row.keys():
                        clean_key = key.strip().replace('\ufeff', '')
                        if clean_key in ('id', 'display_id'):
                            id_value = row.get(key)
                            if id_value:
                                skip_ids.add(str(id_value).strip())
                            break
        except Exception:
            pass
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

    # Read CSV and build hierarchical data structure
    family_data = {}
    processed_count = 0

    rows = load_csv(COMBINED_PET_DATA_CSV)
    for row in rows:
        npc_id = row.get("npc_id", "").strip()
        if not npc_id:
            continue
        
        family_name = row.get("family_name", "").strip()
        npc_name = row.get("npc_name", "").strip()
        loc = row.get("zone_name", "").strip()
        exp = row.get("expansion", "").strip()
        class_name = row.get("classification_name", "").strip()
        react = row.get("react", "").strip()
        name_keeper = row.get("name_keeper", "").strip()

        taming_csv = row.get("taming_requirements", "").strip()
        
        # Parse display_ids pipe-separated string
        display_ids_str = row.get("display_ids", "").strip()
        display_ids = [d.strip() for d in display_ids_str.split('|') if d.strip()]

        taming_lua = ""
        if taming_csv:
            skills = [s.strip() for s in taming_csv.split('|') if s.strip()]
            if skills:
                # Format as a Lua array table string: {"Skill1","Skill2"}
                taming_lua = '{' + ','.join(f'"{s}"' for s in skills) + '}'
        
        # Fallback for empty expansion
        if not exp:
            exp = "Unknown"

        # Default class to "Normal" if empty
        class_value = class_name or "Normal"

        # Initialize family if not exists
        if family_name not in family_data:
            family_data[family_name] = {}

        for display_id in display_ids:
            if display_id in skip_display_ids:
                continue

            # Initialize display ID entry if not exists
            if display_id not in family_data[family_name]:
                family_data[family_name][display_id] = {}

            # Set taming at display ID level (assume consistency across NPCs with same display ID)
            if taming_lua and "taming" not in family_data[family_name][display_id]:
                family_data[family_name][display_id]["taming"] = taming_lua

            # Add NPC entry under display ID, aggregating locations across multiple CSV rows
            if npc_id not in family_data[family_name][display_id]:
                family_data[family_name][display_id][npc_id] = {
                    "name": npc_name,
                    "locs": {loc} if loc else set(),
                    "exp": exp,
                    "class": class_value,
                    "react": react,
                    "name_keeper": name_keeper,
                }
                    

            else:
                if loc:
                    family_data[family_name][display_id][npc_id]["locs"].add(loc)

        processed_count += 1

    print(f"Processed {processed_count} NPCs")

    # Generate Lua file
    print(f"Generating Lua file to {MODELS_LUA}...")
    
    def lua_quote(s):
        if s is None:
            s = ""
        # Escape backslashes and double quotes for safe Lua string literals
        return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'

    with open(MODELS_LUA, 'w', encoding='utf-8') as f:
        f.write("-- Models Data Export\n")
        f.write("-- Generated automatically\n")
        f.write("-- Hierarchical format: Family -> Display IDs -> NPCs\n")
        f.write("\n")
        f.write("ModelsData = {\n")
        
        # Sort family names alphabetically
        sorted_families = sorted(family_data.keys())
        
        for i, family_name in enumerate(sorted_families):
            family = family_data[family_name]
            if not family:
                continue
            
            # Add comma before family (except first)
            if i > 0:
                f.write(",\n")
            
            # Format family name as Lua string key
            f.write(f'    ["{family_name}"] = {{\n')
            
            # Sort display IDs numerically
            sorted_display_ids = sorted(family.keys(), key=lambda x: int(x) if x.isdigit() else float('inf'))
            
            for j, display_id in enumerate(sorted_display_ids):
                data = family[display_id]
                taming = data.get("taming")

                # Add comma before display ID (except first in family)
                if j > 0:
                    f.write(",\n")

                # Format display ID as numeric key
                f.write(f'        [{display_id}] = {{\n')

                # Add taming if present
                if taming:
                    f.write(f'            taming = {taming},\n')

                # Get NPC entries (exclude taming key)
                npc_entries = {k: v for k, v in data.items() if k != "taming"}

                # Sort NPC IDs numerically
                sorted_npc_ids = sorted(npc_entries.keys(), key=lambda x: int(x) if x.isdigit() else float('inf'))

                for k, npc_id in enumerate(sorted_npc_ids):
                    npc = npc_entries[npc_id]

                    # Add comma before NPC (except first)
                    if k > 0:
                        f.write(",\n")

                    # Write NPC entry
                    name_lua = lua_quote(npc.get("name", ""))
                    
                    # Join aggregated locations into a single string for Lua
                    locs_list = sorted(list(npc.get("locs", [])))
                    loc_lua = lua_quote("|".join(locs_list))
                    
                    exp_lua = lua_quote(npc.get("exp", ""))
                    class_lua = lua_quote(npc.get("class", ""))
                    react_lua = lua_quote(npc.get("react", ""))

                    nk_lua = npc.get("name_keeper", "") == "True" and "true" or "false"

                    f.write(f'            [{npc_id}] = {{{name_lua}, {loc_lua}, {exp_lua}, {class_lua}, {react_lua}, {nk_lua}}}')

                f.write('\n        }')
            
            f.write('\n    }')
        
        f.write("\n}\n")
    
    # Print summary
    total_families = len([f for f in family_data.values() if f])
    total_display_ids = sum(len(f) for f in family_data.values() if f)
    total_npcs = sum(
        len([k for k in display_data.keys() if k != "taming"])
        for family in family_data.values()
        if family
        for display_data in family.values()
    )
    
    print(f"Done! Lua file saved to: {MODELS_LUA}")
    print(f"Summary: {total_families} families, {total_display_ids} display IDs, {total_npcs} NPCs")


if __name__ == "__main__":
    main()
