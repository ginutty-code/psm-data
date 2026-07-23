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
    # Hierarchy: expansion -> continent -> family -> display_id -> npcs
    hierarchy = {}
    processed_count = 0

    rows = load_csv(COMBINED_PET_DATA_CSV)
    for row in rows:
        npc_id = row.get("npc_id", "").strip()
        if not npc_id:
            continue
        
        family_name = row.get("family_name", "").strip()
        npc_name = row.get("npc_name", "").strip()
        exp = row.get("expansion", "").strip()
        class_name = row.get("classification_name", "").strip()
        react = row.get("react", "").strip()
        name_keeper = row.get("name_keeper", "").strip()
        continent_name = row.get("continent_name", "").strip()

        taming_csv = row.get("taming_requirements", "").strip()
        
        # Parse display_ids pipe-separated string
        display_ids_str = row.get("display_ids", "").strip()
        display_ids = [d.strip() for d in display_ids_str.split('|') if d.strip()]

        # Parse taming requirements into list
        taming_skills = []
        if taming_csv:
            taming_skills = [s.strip() for s in taming_csv.split('|') if s.strip()]
        
        # Fallback for empty expansion
        if not exp:
            exp = "Unknown"

        # Default class to "Normal" if empty
        class_value = class_name or "Normal"

        # Fallback for empty continent
        if not continent_name:
            continent_name = "Unknown"

        for display_id in display_ids:
            if display_id in skip_display_ids:
                continue

            # Initialize hierarchy levels
            if exp not in hierarchy:
                hierarchy[exp] = {}
            if continent_name not in hierarchy[exp]:
                hierarchy[exp][continent_name] = {}
            if family_name not in hierarchy[exp][continent_name]:
                hierarchy[exp][continent_name][family_name] = {}
            if display_id not in hierarchy[exp][continent_name][family_name]:
                hierarchy[exp][continent_name][family_name][display_id] = {
                    "taming": set()
                }

            did_entry = hierarchy[exp][continent_name][family_name][display_id]

            # Aggregate taming at display ID level
            if taming_skills:
                did_entry["taming"].update(taming_skills)

            # Add NPC entry (aggregating if same NPC appears in multiple rows)
            if npc_id not in did_entry:
                did_entry[npc_id] = {
                    "name": npc_name,
                    "class": class_value,
                    "react": react,
                    "name_keeper": name_keeper,
                }

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
        f.write("-- Hierarchical format: Expansion -> Continent -> Family -> Display IDs -> NPCs\n")
        f.write("-- NPC tuple: {name, classification, react, is_name_keeper}\n")
        f.write("\n")
        f.write("ModelsData = {\n")
        
        # Sort expansions in WoW release order
        expansion_order = [
            "Vanilla", "The Burning Crusade", "Wrath of the Lich King",
            "Cataclysm", "Mists of Pandaria", "Warlords of Draenor",
            "Legion", "Battle for Azeroth", "Shadowlands",
            "Dragonflight", "The War Within", "Unknown"
        ]
        sorted_expansions = sorted(
            hierarchy.keys(),
            key=lambda x: (expansion_order.index(x) if x in expansion_order else 999, x)
        )
        
        for ei, exp in enumerate(sorted_expansions):
            if ei > 0:
                f.write(",\n")
            f.write(f'    ["{exp}"] = {{\n')
            
            continents = hierarchy[exp]
            sorted_continents = sorted(continents.keys())
            
            for ci, continent in enumerate(sorted_continents):
                if ci > 0:
                    f.write(",\n")
                f.write(f'        ["{continent}"] = {{\n')
                
                families = continents[continent]
                sorted_families = sorted(families.keys())
                
                for fi, family in enumerate(sorted_families):
                    if fi > 0:
                        f.write(",\n")
                    f.write(f'            ["{family}"] = {{\n')
                    
                    display_data = families[family]
                    sorted_dids = sorted(display_data.keys(), key=lambda x: int(x) if x.isdigit() else float('inf'))
                    
                    for di, did in enumerate(sorted_dids):
                        if di > 0:
                            f.write(",\n")
                        f.write(f'                [{did}] = {{\n')
                        
                        did_entry = display_data[did]
                        taming_set = did_entry.get("taming")
                        
                        # Write taming if present
                        if taming_set:
                            sorted_taming = sorted(taming_set)
                            taming_lua = '{' + ','.join(f'"{s}"' for s in sorted_taming) + '}'
                            f.write(f'                    taming = {taming_lua},\n')
                        
                        # NPC entries (exclude taming key)
                        npc_entries = {k: v for k, v in did_entry.items() if k != "taming"}
                        sorted_npc_ids = sorted(npc_entries.keys(), key=lambda x: int(x) if x.isdigit() else float('inf'))
                        
                        for ni, npc_id in enumerate(sorted_npc_ids):
                            if ni > 0:
                                f.write(",\n")
                            
                            npc = npc_entries[npc_id]
                            name_lua = lua_quote(npc.get("name", ""))
                            class_lua = lua_quote(npc.get("class", ""))
                            react_lua = lua_quote(npc.get("react", ""))
                            nk_lua = "true" if npc.get("name_keeper", "") == "True" else "false"
                            
                            # 4-element tuple: {name, class, react, nameKeeper}
                            # expansion and continent are implied by tree keys
                            f.write(f'                    [{npc_id}] = {{{name_lua}, {class_lua}, {react_lua}, {nk_lua}}}')
                        
                        f.write('\n                }')
                    
                    f.write('\n            }')
                
                f.write('\n        }')
            
            f.write('\n    }')
        
        f.write("\n}\n")
    
    # Print summary (unique counts across the entire hierarchy)
    total_expansions = len(hierarchy)
    unique_continents = set()
    unique_families = set()
    unique_dids = set()
    unique_npcs = set()
    for exp_name, cont_dict in hierarchy.items():
        for cont_name, fam_dict in cont_dict.items():
            unique_continents.add(cont_name)
            for fam_name, did_dict in fam_dict.items():
                unique_families.add(fam_name)
                for did_key, did_entry in did_dict.items():
                    unique_dids.add(did_key)
                    for k in did_entry:
                        if k != "taming":
                            unique_npcs.add(k)
    
    print(f"Done! Lua file saved to: {MODELS_LUA}")
    print(f"Summary: {total_expansions} expansions, {len(unique_continents)} continents, {len(unique_families)} families, {len(unique_dids)} display IDs, {len(unique_npcs)} NPCs")


if __name__ == "__main__":
    main()