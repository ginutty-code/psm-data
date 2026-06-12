"""
Replace/add NPCs from npcs_correct.csv to npcs.csv
"""

import os
import csv
import sys
from config import WOWHEAD_NPCS_CSV, UPDATE_NPC_CSV, ensure_dirs

def load_corrections():
    """Load corrections from the corrections file."""
    corrections = {}
    if not os.path.exists(UPDATE_NPC_CSV):
        print(f"Corrections file not found: {UPDATE_NPC_CSV}")
        print("No corrections will be applied.")
        return corrections
    
    with open(UPDATE_NPC_CSV, 'r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            npc_id = str(row.get('npc_id', '')).strip()
            if not npc_id or npc_id.startswith('#'):
                continue
            
            # Store all columns from the corrections file
            corrections[npc_id] = {
                'npc_id': npc_id,
                'npc_name': str(row.get('npc_name', '')).strip(),
                'classification': str(row.get('classification', '')).strip(),
                'classification_id': str(row.get('classification_id', '')).strip(),
                'family_id': str(row.get('family_id', '')).strip(),
                'family_name': str(row.get('family_name', '')).strip(),
                'zone_id': str(row.get('zone_id', '')).strip(),
                'react': str(row.get('react', '')).strip()
            }
    
    return corrections


def load_npcs():
    """Load NPCs from the main CSV file."""
    npcs = []
    if not os.path.exists(WOWHEAD_NPCS_CSV):
        print(f"Error: {WOWHEAD_NPCS_CSV} not found. Run step2a_extract_npcs.py first.")
        sys.exit(1)
    
    with open(WOWHEAD_NPCS_CSV, 'r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            npcs.append(row)
    
    return npcs


def save_npcs(npcs):
    """Save NPCs back to the CSV file."""
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
    
    with open(WOWHEAD_NPCS_CSV, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        for rec in npcs:
            row = {k: ('' if rec.get(k) is None else rec.get(k)) for k in columns}
            writer.writerow(row)
    
    print(f"NPCs CSV saved to {WOWHEAD_NPCS_CSV}")


def apply_corrections():
    """Main function to apply NPC corrections."""
    print("=" * 60)
    print("Applying NPC Corrections")
    print("=" * 60)
    print()
    
    # Load corrections
    corrections = load_corrections()
    if not corrections:
        print("No corrections to apply.")
        return
    
    print(f"Loaded {len(corrections)} correction(s)")
    print()
    
    # Show corrections
    print("Corrections to apply:")
    for npc_id, correction in corrections.items():
        print(f"  NPC {npc_id}: family_id={correction["family_id"]}, family_name={correction["family_name"]}")
    print()
    
    # Load NPCs
    npcs = load_npcs()
    print(f"Loaded {len(npcs)} NPCs from {WOWHEAD_NPCS_CSV}")
    print()
    
    # Build a lookup dict for existing NPCs by npc_id
    existing_npc_map = {str(npc.get("npc_id", "")).strip(): npc for npc in npcs}
    
    # Apply corrections: replace entire record if exists, mark as new if not
    replaced_count = 0
    new_npcs_to_add = []
    
    for npc_id, correction in corrections.items():
        if npc_id in existing_npc_map:
            # Replace entire record with correction data
            existing_npc = existing_npc_map[npc_id]
            existing_npc["npc_id"] = correction.get("npc_id", npc_id)
            existing_npc["npc_name"] = correction.get("npc_name", "")
            existing_npc["classification"] = correction.get("classification", "")
            existing_npc["classification_id"] = correction.get("classification_id", "")
            existing_npc["family_id"] = correction.get("family_id", "")
            existing_npc["family_name"] = correction.get("family_name", "")
            existing_npc["zone_id"] = correction.get("zone_id", "")
            existing_npc["react"] = correction.get("react", "")
            
            replaced_count += 1
            print(f"  Replaced NPC {npc_id}: {correction.get("npc_name", "Unknown")}")
            print(f"    family: {correction["family_id"]}/{correction["family_name"]}, zone_id: {correction.get("zone_id", "")}")
        else:
            # Add as new NPC
            new_npc = {
                "npc_id": correction.get("npc_id", npc_id),
                "npc_name": correction.get("npc_name", ""),
                "classification": correction.get("classification", ""),
                "classification_id": correction.get("classification_id", ""),
                "family_id": correction.get("family_id", ""),
                "family_name": correction.get("family_name", ""),
                "zone_id": correction.get("zone_id", ""),
                "react": correction.get("react", "")
            }
            new_npcs_to_add.append(new_npc)
            print(f"  New NPC to add: {npc_id} - {correction.get("npc_name", "Unknown")}")
    
    # Add new NPCs to the list
    if new_npcs_to_add:
        npcs.extend(new_npcs_to_add)
        print(f"  Added {len(new_npcs_to_add)} new NPC(s) to the list")
    
    if replaced_count == 0 and len(new_npcs_to_add) == 0:
        print("No corrections were applied and no new NPCs to add.")
        return
    
    print()
    print(f"Total records replaced: {replaced_count}")
    print(f"Total new NPCs added: {len(new_npcs_to_add)}")
    
    # Save corrected NPCs
    save_npcs(npcs)
    
    print()
    print("=" * 60)
    print("Corrections applied successfully!")
    print("=" * 60)


if __name__ == '__main__':
    apply_corrections()
