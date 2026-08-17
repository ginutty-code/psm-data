"""
Generate addon Models data file (structure-of-arrays, backed by a dense
npcId<->index backbone -- see ../DATA_STRUCTURE_OPTIMIZATION_PLAN.md, Target
schema for ModelsData).
"""

import os
import re

from config import (
    COMBINED_PET_DATA_CSV,
    MODELS_LUA,
    SKIP_DISPLAY_IDS_CSV,
    ensure_dirs,
    load_csv,
    read_first_col,
    sync_output_to_addon,
)

REACT_PATTERN = re.compile(r'\[\s*(-?\d+)\s*,\s*(-?\d+)\s*\]')




def parse_react(react_str):
    """Parse a '[a,b]' faction-reaction string into two ints. Defaults to (0, 0)."""
    if not react_str:
        return 0, 0
    match = REACT_PATTERN.match(react_str.strip())
    if not match:
        return 0, 0
    return int(match.group(1)), int(match.group(2))


def format_display_ids(display_ids_set):
    """Bare number if exactly one, else a Lua array; {} if none."""
    sorted_dids = sorted(display_ids_set)
    if not sorted_dids:
        return "{}"
    if len(sorted_dids) == 1:
        return str(sorted_dids[0])
    return "{ " + ", ".join(str(d) for d in sorted_dids) + " }"


def lua_quote(s):
    if s is None:
        s = ""
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def write_dense_column(f, name, values, per_line=10):
    """A column present for every index -- plain positional list, chunked for readability."""
    f.write(f"ModelsData.{name} = {{\n")
    for i in range(0, len(values), per_line):
        chunk = values[i:i + per_line]
        f.write("    " + ", ".join(chunk) + ",\n")
    f.write("}\n\n")


def write_sparse_column(f, name, sorted_npc_ids, npc_id_to_index, value_fn):
    """A column only some indices have -- explicit [i] = value, one per line,
    index simply omitted (implicit nil, still array-part-eligible) when absent."""
    f.write(f"ModelsData.{name} = {{\n")
    for npc_id in sorted_npc_ids:
        value = value_fn(npc_id)
        if value is not None:
            f.write(f"    [{npc_id_to_index[npc_id]}] = {value},\n")
    f.write("}\n\n")


def main():
    ensure_dirs()

    print(f"Loading CSV from {COMBINED_PET_DATA_CSV}...")
    if not os.path.exists(COMBINED_PET_DATA_CSV):
        print(f"Error: CSV file not found: {COMBINED_PET_DATA_CSV}")
        return

    print("Loading skip display IDs...")
    skip_display_ids = read_first_col(SKIP_DISPLAY_IDS_CSV, {'id', 'display_id'})
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
                "nameKeeper": row.get("name_keeper", "").strip().lower() == "true",
                "taming": set(),
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

    print(f"Processed {len(npcs)} unique NPCs")

    # Dense npcId <-> index backbone
    sorted_npc_ids = sorted(npcs.keys())
    npc_id_to_index = {npc_id: i + 1 for i, npc_id in enumerate(sorted_npc_ids)}

    # Internal-only ID maps for enum-like fields. Sorted alphabetically for
    # reproducible diffs across regenerations -- NOT for cross-version stability,
    # these IDs are never persisted (see ModelsData.lua's own header comment).
    distinct_families = sorted({npcs[nid]["family"] for nid in npcs})
    distinct_expansions = sorted({npcs[nid]["expansion"] for nid in npcs})
    distinct_classifications = sorted({npcs[nid]["classification"] for nid in npcs})

    family_to_id = {name: i + 1 for i, name in enumerate(distinct_families)}
    expansion_to_id = {name: i + 1 for i, name in enumerate(distinct_expansions)}
    classification_to_id = {name: i + 1 for i, name in enumerate(distinct_classifications)}

    # uiMapId -> uiMapName is a clean 1:1 mapping in the source data (verified), so
    # this ships as one small lookup joined through UiMapId[i], instead of repeating
    # the name string as its own per-record column.
    uimapid_to_name = {}
    for nid in sorted_npc_ids:
        mid = npcs[nid]["uiMapId"]
        mname = npcs[nid]["uiMapName"]
        if mid is not None and mname:
            uimapid_to_name[mid] = mname

    react_by_npc_id = {nid: parse_react(npcs[nid]["react"]) for nid in sorted_npc_ids}

    print(f"Generating Lua file to {MODELS_LUA}...")

    with open(MODELS_LUA, 'w', encoding='utf-8') as f:
        f.write("-- Models Data Export\n")
        f.write("-- Generated automatically\n")
        f.write("-- Structure-of-arrays layout, backed by a dense npcId<->index backbone.\n")
        f.write("-- ModelsData.Index[npcId] = denseIndex; ModelsData.NpcId[denseIndex] = npcId.\n")
        f.write("-- Every per-record column (Name, DisplayIds, UiMapId, FamilyId,\n")
        f.write("-- ExpansionId, ReactA, ReactH, ClassificationId, NameKeeper, Taming) is\n")
        f.write("-- ModelsData.<Column>[denseIndex] = value.\n")
        f.write("-- Families/Expansions/Classifications are separate lookups keyed by their\n")
        f.write("-- own internal-only IDs (NOT denseIndex, NOT stable across regenerations --\n")
        f.write("-- resolve display strings through them, never persist the raw ID).\n")
        f.write("-- UiMapNames is also a separate lookup, but keyed by uiMapId directly (via\n")
        f.write("-- the UiMapId column above) -- Blizzard's own stable zone ID, not one of\n")
        f.write("-- ours, safe to treat as stable.\n\n")

        f.write("ModelsData = {}\n\n")

        # Index: npcId -> denseIndex. Sparse keys, stays hash-part -- but it's the
        # only hash-keyed table left, instead of every record being one.
        f.write("ModelsData.Index = {\n")
        for npc_id in sorted_npc_ids:
            f.write(f"    [{npc_id}] = {npc_id_to_index[npc_id]},\n")
        f.write("}\n\n")

        write_dense_column(f, "NpcId", [str(nid) for nid in sorted_npc_ids])
        write_dense_column(f, "Name", [lua_quote(npcs[nid]["name"]) for nid in sorted_npc_ids])
        write_dense_column(
            f, "DisplayIds",
            [format_display_ids(npcs[nid]["displayIds"]) for nid in sorted_npc_ids],
        )

        write_sparse_column(
            f, "UiMapId", sorted_npc_ids, npc_id_to_index,
            lambda nid: npcs[nid]["uiMapId"] if npcs[nid]["uiMapId"] is not None else None,
        )

        write_dense_column(
            f, "FamilyId",
            [str(family_to_id[npcs[nid]["family"]]) for nid in sorted_npc_ids],
        )
        write_dense_column(
            f, "ExpansionId",
            [str(expansion_to_id[npcs[nid]["expansion"]]) for nid in sorted_npc_ids],
        )
        write_dense_column(f, "ReactA", [str(react_by_npc_id[nid][0]) for nid in sorted_npc_ids])
        write_dense_column(f, "ReactH", [str(react_by_npc_id[nid][1]) for nid in sorted_npc_ids])
        write_dense_column(
            f, "ClassificationId",
            [str(classification_to_id[npcs[nid]["classification"]]) for nid in sorted_npc_ids],
        )
        write_dense_column(
            f, "NameKeeper",
            ["true" if npcs[nid]["nameKeeper"] else "false" for nid in sorted_npc_ids],
        )

        def taming_value(nid):
            if not npcs[nid]["taming"]:
                return None
            sorted_taming = sorted(npcs[nid]["taming"])
            return "{ " + ", ".join(lua_quote(t) for t in sorted_taming) + " }"

        write_sparse_column(f, "Taming", sorted_npc_ids, npc_id_to_index, taming_value)

        f.write("ModelsData.Families = {\n")
        f.writelines(f"    [{fid}] = {lua_quote(name)},\n" for name, fid in family_to_id.items())
        f.write("}\n\n")

        f.write("ModelsData.Expansions = {\n")
        f.writelines(f"    [{eid}] = {lua_quote(name)},\n" for name, eid in expansion_to_id.items())
        f.write("}\n\n")

        f.write("ModelsData.Classifications = {\n")
        f.writelines(f"    [{cid}] = {lua_quote(name)},\n" for name, cid in classification_to_id.items())
        f.write("}\n\n")

        f.write("ModelsData.UiMapNames = {\n")
        f.writelines(
            f"    [{mid}] = {lua_quote(name)},\n"
            for mid, name in sorted(uimapid_to_name.items())
        )
        f.write("}\n")

    print(f"Done! Lua file saved to: {MODELS_LUA}")
    sync_output_to_addon(MODELS_LUA)


if __name__ == "__main__":
    main()
