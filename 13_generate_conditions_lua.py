"""
Generate addon Special Conditions data file
"""

import csv
import os
from config import COMBINED_PET_DATA_CSV, CONDITIONS_LUA, ensure_dirs

def main():
    ensure_dirs()
    print(f"Loading CSV from {COMBINED_PET_DATA_CSV}...")
    if not os.path.exists(COMBINED_PET_DATA_CSV):
        print(f"Error: CSV file not found: {COMBINED_PET_DATA_CSV}")
        return

    # npc_id -> [list of conditions]
    conditions_map = {}
    unique_conditions = set()

    with open(COMBINED_PET_DATA_CSV, 'r', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            npc_id = row.get('npc_id')
            conditions_raw = row.get('special_conditions', '').strip()
            
            if not npc_id or not conditions_raw:
                continue
                
            conditions = [c.strip() for c in conditions_raw.split('|') if c.strip()]
            if conditions:
                conditions_map[npc_id] = conditions
                for c in conditions:
                    unique_conditions.add(c)

    if not conditions_map:
        print("No special conditions data found. Skipping file generation.")
        return

    print(f"Generating Lua file to {CONDITIONS_LUA}...")

    with open(CONDITIONS_LUA, 'w', encoding='utf-8') as f:
        f.write("-- ConditionsData.lua\n")
        f.write("-- Maps NPC IDs to condition-specific taming requirements.\n")
        f.write("-- These are used for filtering in the Special Tames panel.\n\n")
        
        f.write("local conditions = {\n")
        sorted_conditions = sorted(list(unique_conditions))
        condition_to_idx = {}
        for i, c in enumerate(sorted_conditions):
            f.write(f'    [{i+1}] = "{c}",\n')
            condition_to_idx[c] = i + 1
        f.write("}\n\n")

        f.write("PSM.ConditionsData = {\n")
        # Sort NPC IDs numerically
        sorted_npc_ids = sorted(conditions_map.keys(), key=lambda x: int(x) if x.isdigit() else 0)
        
        for npc_id in sorted_npc_ids:
            c_list = conditions_map[npc_id]
            # Map names to their indices in the local 'conditions' table
            indices = [str(condition_to_idx[c]) for c in c_list]
            
            # Format as: [npcID] = {conditions[1], conditions[2]}
            ref_strings = [f"conditions[{idx}]" for idx in indices]
            f.write(f'    [{npc_id}] = {{{", ".join(ref_strings)}}},\n')
            
        f.write("}\n\n")
        f.write("function PSM.ConditionsData.Get(npcID)\n")
        f.write("    return PSM.ConditionsData[npcID]\n")
        f.write("end\n")

    print(f"Done! {len(conditions_map)} NPCs mapped to special conditions.")
    print(f"Lua file saved to: {CONDITIONS_LUA}")

if __name__ == "__main__":
    main()