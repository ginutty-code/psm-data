"""
Generate addon Abilities data file
"""

import csv
import os
from config import WOWHEAD_FAMILIES_CSV, WOWHEAD_SPELLS_CSV, ABILITIES_LUA, ensure_dirs

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
    print(f"Loading families CSV from {WOWHEAD_FAMILIES_CSV}...")
    if not os.path.exists(WOWHEAD_FAMILIES_CSV):
        print(f"Error: Families CSV file not found: {WOWHEAD_FAMILIES_CSV}")
        return

    print(f"Loading spells CSV from {WOWHEAD_SPELLS_CSV}...")
    if not os.path.exists(WOWHEAD_SPELLS_CSV):
        print(f"Error: Spells CSV file not found: {WOWHEAD_SPELLS_CSV}")
        return

    # Load families
    families_rows = load_csv(WOWHEAD_FAMILIES_CSV)
    families = {}
    for row in families_rows:
        family_id = row.get("family_id", "").strip()
        if not family_id:
            continue
        name = row.get("family_name", "").strip()
        icon = row.get("icon", "").strip()
        spells_str = row.get("spells", "").strip()
        spell_ids = [s.strip() for s in spells_str.split(";") if s.strip()]
        families[family_id] = {
            "name": name,
            "icon": icon,
            "spells": spell_ids
        }

    # Load spells
    spells_rows = load_csv(WOWHEAD_SPELLS_CSV)
    spells = {}
    for row in spells_rows:
        spell_id = row.get("spell_id", "").strip()
        if not spell_id:
            continue
        name = row.get("spell_name", "").strip() or f"Spell {spell_id}"
        icon = row.get("spell_icon", "").strip()
        rank = row.get("spell_rank", "").strip()
        category = row.get("spell_category", "").strip()
        tag = row.get("spell_tag", "").strip()
        spells[spell_id] = {
            "name": name,
            "icon": icon,
            "rank": rank,
            "category": category,
            "tag": tag
        }

    # Find all spell_ids that are linked to families
    linked_spells = set()
    for family_data in families.values():
        linked_spells.update(family_data["spells"])

    # Build the hierarchy: family_id -> data, with Spec for unlinked
    abilities_data = {}

    # First, process families
    for family_id, family_data in families.items():
        family_name = family_data["name"]
        family_icon = family_data["icon"]
        spell_ids = family_data["spells"]

        ranks = {}
        for spell_id in spell_ids:
            if spell_id in spells:
                spell_data = spells[spell_id]
                rank = spell_data["rank"]
                name = spell_data["name"]
                icon = spell_data["icon"]
                category = spell_data["category"]
                tag = spell_data["tag"]

                if rank not in ranks:
                    ranks[rank] = {}
                ranks[rank][spell_id] = {
                    "name": name,
                    "icon": icon,
                    "category": category,
                    "tag": tag
                }

        abilities_data[family_id] = {
            "name": family_name,
            "icon": family_icon,
            "ranks": ranks
        }

    # Now, process unlinked spells into "Spec"
    spec_ranks = {}
    for spell_id, spell_data in spells.items():
        if spell_id not in linked_spells:
            rank = spell_data["rank"]
            name = spell_data["name"]
            icon = spell_data["icon"]
            category = spell_data["category"]
            tag = spell_data["tag"]

            if rank not in spec_ranks:
                spec_ranks[rank] = {}
            spec_ranks[rank][spell_id] = {
                "name": name,
                "icon": icon,
                "category": category,
                "tag": tag
            }

    if spec_ranks:
        abilities_data["Spec"] = {
            "name": "Spec abilities",
            "icon": "",
            "ranks": spec_ranks
        }

    # Generate Lua file
    print(f"Generating Lua file to {ABILITIES_LUA}...")

    def lua_quote(s):
        if s is None:
            s = ""
        # Escape backslashes and double quotes for safe Lua string literals
        return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'

    with open(ABILITIES_LUA, 'w', encoding='utf-8') as f:
        f.write("-- Abilities Data Export\n")
        f.write("-- Generated automatically\n")
        f.write("-- Format: AbilitiesData[family_id] = {name = \"family_name\", icon = \"family_icon\", ranks = {[rank] = {[ability_id] = {name = \"ability_name\", icon = \"ability_icon\", category = \"category\", tag = \"tag\"}, ...}}}\n")
        f.write("\n")
        f.write("AbilitiesData = {\n")

        # Sort family_ids, put "Spec" last
        sorted_family_ids = sorted([k for k in abilities_data.keys() if k != "Spec"], key=lambda x: int(x) if x.isdigit() else float('inf'))
        if "Spec" in abilities_data:
            sorted_family_ids.append("Spec")

        for i, family_id in enumerate(sorted_family_ids):
            family_data = abilities_data[family_id]
            family_name = family_data["name"]
            family_icon = family_data["icon"]
            ranks = family_data["ranks"]

            # Add comma before family (except first)
            if i > 0:
                f.write(",\n")

            # Write family entry
            if family_id.isdigit():
                f.write(f'    [{family_id}] = {{\n')
            else:
                f.write(f'    [{lua_quote(family_id)}] = {{\n')
            f.write(f'        name = {lua_quote(family_name)},\n')
            f.write(f'        icon = {lua_quote(family_icon)},\n')
            f.write('        ranks = {\n')

            # Sort ranks alphabetically
            sorted_ranks = sorted(ranks.keys())

            for j, rank in enumerate(sorted_ranks):
                rank_data = ranks[rank]

                # Add comma before rank (except first)
                if j > 0:
                    f.write(',\n')

                # Write rank entry
                f.write(f'            [{lua_quote(rank)}] = {{\n')

                # Sort ability_ids numerically
                sorted_ability_ids = sorted(rank_data.keys(), key=lambda x: int(x) if x.isdigit() else float('inf'))

                for k, ability_id in enumerate(sorted_ability_ids):
                    ability_data = rank_data[ability_id]
                    name = ability_data["name"]
                    icon = ability_data["icon"]
                    category = ability_data["category"]
                    tag = ability_data["tag"]

                    # Add comma before ability (except first)
                    if k > 0:
                        f.write(',\n')

                    # Write ability entry
                    f.write(f'                [{ability_id}] = {{\n')
                    f.write(f'                    name = {lua_quote(name)},\n')
                    f.write(f'                    icon = {lua_quote(icon)},\n')
                    f.write(f'                    category = {lua_quote(category)},\n')
                    f.write(f'                    tag = {lua_quote(tag)}\n')
                    f.write('                }')

                f.write('\n            }')

            f.write('\n        }\n')
            f.write('    }')

        f.write("\n}\n")

    # Print summary
    total_families = len(abilities_data)
    total_ranks = sum(len(family_data["ranks"]) for family_data in abilities_data.values())
    total_abilities = sum(len(rank_data) for family_data in abilities_data.values() for rank_data in family_data["ranks"].values())

    print(f"Done! Lua file saved to: {ABILITIES_LUA}")
    print(f"Summary: {total_families} families, {total_ranks} ranks, {total_abilities} abilities")


if __name__ == "__main__":
    main()