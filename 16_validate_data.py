"""
Validate pipeline outputs and report outliers.

Runs a growing set of independent sanity checks across the pipeline's
CSVs, meant to catch data that silently fell through the cracks between
stages (e.g. an NPC scraped from Petopia that never made it into the
final combined dataset, and isn't accounted for by a Manual/ skip list).

Each check is a standalone function registered in CHECKS; add new checks
there as the validation suite grows. A check prints a short summary (a
few count lines -- no per-npc_id dumps, those belong in the CSV, not the
terminal) and returns a list of (npc_id, description) action items (empty
list = clean). main() collects those across all checks into a numbered
Action List printed up front, and writes the full list to
Processed/action_list.csv (config.ACTION_LIST_CSV) for anything longer
than a glance.
"""

import csv
import io
import os
from contextlib import redirect_stdout

from config import (
    ACTION_LIST_CSV,
    COMBINED_PET_DATA_CSV,
    NOTES_UPDATES_CSV,
    NPC_UPDATES_CSV,
    PETOPIA_NPCS_CSV,
    SKIP_NPC_IDS_CSV,
    WOWHEAD_DATA_CSV,
    WOWHEAD_NPCS_CSV,
)

# Columns every pet_data.csv row is expected to have populated. continent_id
# and continent_name are handled separately below since 11_combine_data.py
# fills continent_name with the literal 'Unknown' (rather than leaving it
# blank) when a row's uiMapId isn't found in Manual/continent_data.csv.
REQUIRED_NON_EMPTY_FIELDS = [
    'family_id', 'family_name', 'uiMapId', 'uiMapName', 'patch_id', 'expansion',
]

# wowhead_data.csv columns that together describe an NPC's location.
LOCATION_FIELDS = ('uiMapId', 'uiMapName', 'zone_id', 'zone_name')


def _load_ids(path, id_col='npc_id'):
    """Returns the set of non-empty values in id_col across path."""
    ids = set()
    if not os.path.exists(path):
        return ids
    with open(path, 'r', encoding='utf-8-sig', newline='', errors='replace') as f:
        for row in csv.DictReader(f):
            val = (row.get(id_col) or '').strip()
            if val:
                ids.add(val)
    return ids


def _load_skip_reasons(path):
    """Returns npc_id -> sorted list of distinct reasons (rows can repeat per zone/layer)."""
    reasons = {}
    if not os.path.exists(path):
        return reasons
    with open(path, 'r', encoding='utf-8-sig', newline='', errors='replace') as f:
        for row in csv.DictReader(f):
            npc_id = (row.get('npc_id') or '').strip()
            if not npc_id:
                continue
            reason = (row.get('reason') or '').strip()
            reasons.setdefault(npc_id, set())
            if reason:
                reasons[npc_id].add(reason)
    return {k: sorted(v) for k, v in reasons.items()}


def check_petopia_npcs_missing_from_pet_data():
    """
    Every npc_id Petopia knows about (Extracted/petopia_npcs.csv — the
    rawest, earliest-stage NPC list) should end up in the final combined
    dataset unless it's explicitly accounted for in Manual/skip_npc_ids.csv.

    An npc_id missing from pet_data.csv AND absent from the skip list splits
    two ways, and the Wowhead extracts (wowhead_npcs.csv, then
    wowhead_data.csv) are what tells them apart — being absent from
    pet_data.csv alone doesn't prove the Wowhead side never picked the NPC
    up, only that it isn't in the *final* table:
      - Present in either Wowhead extract: the Wowhead pipeline *does* carry
        it, so pet_data.csv is just stale (validation run before
        11_combine_data.py) or the NPC is being dropped somewhere in
        10/11 — regenerate and re-check before touching Manual/ files.
      - In neither extract: the Wowhead side genuinely never picked it up —
        add it to Manual/npcs_updates.csv so 08_update_npcs.py injects it.
    """
    petopia_ids = _load_ids(PETOPIA_NPCS_CSV)
    pet_data_ids = _load_ids(COMBINED_PET_DATA_CSV)
    skip_reasons = _load_skip_reasons(SKIP_NPC_IDS_CSV)
    wowhead_pipeline_ids = _load_ids(WOWHEAD_NPCS_CSV) | _load_ids(WOWHEAD_DATA_CSV)

    missing = sorted(petopia_ids - pet_data_ids, key=lambda x: int(x) if x.isdigit() else 0)
    unexplained = [npc_id for npc_id in missing if npc_id not in skip_reasons]
    in_wowhead = [npc_id for npc_id in unexplained if npc_id in wowhead_pipeline_ids]
    absent_from_wowhead = [npc_id for npc_id in unexplained if npc_id not in wowhead_pipeline_ids]

    print(f"Petopia npc_ids: {len(petopia_ids)}")
    print(f"pet_data.csv npc_ids: {len(pet_data_ids)}")
    print(f"Missing from pet_data.csv: {len(missing)}")
    print(f"  - Accounted for in skip_npc_ids.csv: {len(missing) - len(unexplained)}")
    print(f"  - In a Wowhead extract already (stale pet_data.csv or 10/11 drop): {len(in_wowhead)}")
    print(f"  - UNEXPLAINED (needs a Manual/npcs_updates.csv entry): {len(absent_from_wowhead)}")

    actions = [
        (npc_id,
         f"npc_id {npc_id} is in the Wowhead pipeline (wowhead_npcs.csv/wowhead_data.csv) but not "
         f"pet_data.csv - regenerate pet_data.csv (re-run 11_combine_data.py) and re-check; if it "
         f"persists, it's being dropped in 10/11")
        for npc_id in in_wowhead
    ]
    actions += [
        (npc_id, f"Add npc_id {npc_id} to Manual/npcs_updates.csv (Petopia lists it, Wowhead pipeline doesn't)")
        for npc_id in absent_from_wowhead
    ]
    return actions


def check_pet_data_required_fields():
    """
    Every row in pet_data.csv should carry family/location/patch metadata.
    Flags rows missing any of REQUIRED_NON_EMPTY_FIELDS, plus rows where
    continent resolution fell back to the 'Unknown' placeholder (meaning
    their uiMapId isn't in Manual/continent_data.csv).
    """
    if not os.path.exists(COMBINED_PET_DATA_CSV):
        print(f"{COMBINED_PET_DATA_CSV} not found - skipping.")
        return []

    missing_field = {fld: [] for fld in REQUIRED_NON_EMPTY_FIELDS}
    missing_continent_id = []
    unresolved_continent_name = []

    with open(COMBINED_PET_DATA_CSV, 'r', encoding='utf-8-sig', newline='', errors='replace') as f:
        reader = csv.DictReader(f)
        total = 0
        for row in reader:
            total += 1
            npc_id = (row.get('npc_id') or '').strip()

            for fld in REQUIRED_NON_EMPTY_FIELDS:
                if not (row.get(fld) or '').strip():
                    missing_field[fld].append(npc_id)

            if not (row.get('continent_id') or '').strip():
                missing_continent_id.append(npc_id)
            if (row.get('continent_name') or '').strip() == 'Unknown':
                unresolved_continent_name.append(npc_id)

    print(f"pet_data.csv rows checked: {total}")
    for fld in REQUIRED_NON_EMPTY_FIELDS:
        print(f"  - Missing {fld}: {len(missing_field[fld])}")
    print(f"  - Missing continent_id: {len(missing_continent_id)}")
    print(f"  - continent_name unresolved ('Unknown'): {len(unresolved_continent_name)}")

    actions = []
    for fld in REQUIRED_NON_EMPTY_FIELDS:
        for npc_id in missing_field[fld]:
            actions.append((npc_id, f"Fill missing {fld} for npc_id {npc_id} in pet_data.csv"))
    for npc_id in missing_continent_id:
        actions.append((npc_id, f"Add npc_id {npc_id}'s uiMapId to Manual/continent_data.csv (continent_id is blank)"))
    for npc_id in unresolved_continent_name:
        actions.append((npc_id, f"Add npc_id {npc_id}'s uiMapId to Manual/continent_data.csv (continent unresolved)"))
    return actions


def _load_note_update_targets(path):
    """
    npc_id -> note text, for rows that add a note outright (empty search, non-empty
    replace). Mirrors 11_combine_data.py's load_note_additions; rows carrying a `search`
    are search/replace edits that harmlessly do nothing when their NPC is absent, so
    only the outright additions can be orphaned.
    """
    targets = {}
    if not os.path.exists(path):
        return targets
    with open(path, 'r', encoding='utf-8-sig', newline='', errors='replace') as f:
        for row in csv.DictReader(f):
            npc_id = (row.get('npc_id') or '').strip()
            search = (row.get('search') or '').strip()
            replace = (row.get('replace') or '').strip()
            if npc_id and not search and replace:
                targets[npc_id] = replace
    return targets


def check_orphan_note_updates():
    """
    Every note added by Manual/notes_updates.csv should land on a real NPC.

    A note is attached in one of two places: 03_clean_petopia_data.py applies it to the
    NPCs Petopia carries, and 11_combine_data.py fills in for NPCs that reached the
    combined dataset from the Wowhead side instead. An npc_id in neither is an orphan --
    it was skipped from both sources, or never existed.

    This is worth a check rather than a shrug because the failure is **silent**.
    15_generate_notes_lua.py reads only pet_data.csv, so an orphaned note is not
    reported, not emitted, and not recoverable from the output -- it simply is not there.
    03 used to hide this by fabricating a blank Petopia record so the note always had
    something to sit on, which made an orphan indistinguishable from a real NPC with no
    scraped data.
    """
    targets = _load_note_update_targets(NOTES_UPDATES_CSV)
    pet_data_ids = _load_ids(COMBINED_PET_DATA_CSV)
    skip_reasons = _load_skip_reasons(SKIP_NPC_IDS_CSV)

    orphans = sorted(
        (npc_id for npc_id in targets if npc_id not in pet_data_ids),
        key=lambda x: int(x) if x.isdigit() else 0,
    )

    print(f"Note additions in notes_updates.csv: {len(targets)}")
    print(f"  - Landed on a pet_data.csv record: {len(targets) - len(orphans)}")
    print(f"  - ORPHANED (note will not be emitted): {len(orphans)}")

    actions = []
    for npc_id in orphans:
        if npc_id not in skip_reasons:
            why = "not in skip list - NPC missing from both sources"
        elif skip_reasons[npc_id]:
            why = f"skipped: {'; '.join(skip_reasons[npc_id])}"
        else:
            why = "skipped (no reason given)"
        note = targets[npc_id]
        preview = note if len(note) <= 60 else note[:57] + "..."
        actions.append((
            npc_id,
            (f"Note for npc_id {npc_id} in Manual/notes_updates.csv matches no pet_data.csv "
             f"record ({why}) - remove the note, or stop skipping the NPC. Note: {preview}")
        ))
    return actions


def _load_petopia_tameable(path):
    """npc_id -> npc_name, for Petopia NPCs whose tameable field isn't 'Tameability Unknown'."""
    tameable = {}
    if not os.path.exists(path):
        return tameable
    with open(path, 'r', encoding='utf-8-sig', newline='', errors='replace') as f:
        for row in csv.DictReader(f):
            npc_id = (row.get('npc_id') or '').strip()
            if npc_id and (row.get('tameable') or '').strip() != 'Tameability Unknown':
                tameable[npc_id] = (row.get('npc_name') or '').strip()
    return tameable


def _load_npcs_updates(path):
    """
    Returns (all_ids, add_entries): all_ids is every npc_id in the file
    regardless of tag, add_entries is [(npc_id, npc_name), ...] for rows
    tagged action=add.

    The 'action' column (add/update) is a human-maintained note only --
    08_update_npcs.py itself decides add-vs-replace dynamically each run,
    from whether the npc_id is currently in wowhead_npcs.csv, not from
    this column. So any row here, tagged either way, already counts as
    "accounted for" from the pipeline's perspective.
    """
    all_ids = set()
    add_entries = []
    if not os.path.exists(path):
        return all_ids, add_entries
    with open(path, 'r', encoding='utf-8-sig', newline='', errors='replace') as f:
        for row in csv.DictReader(f):
            npc_id = (row.get('npc_id') or '').strip()
            if not npc_id:
                continue
            all_ids.add(npc_id)
            if (row.get('action') or '').strip().lower() == 'add':
                add_entries.append((npc_id, (row.get('npc_name') or '').strip()))
    return all_ids, add_entries


def check_npcs_updates_freshness():
    """
    Manual/npcs_updates.csv feeds 08_update_npcs.py: a row becomes a new
    NPC if its npc_id isn't currently in wowhead_npcs.csv, or replaces the
    existing record otherwise. Only the "add" side is checked here -- rows
    tagged 'update' are left alone, since validating a correction needs
    more context than a membership check (and they're presumed to target a
    real, already-existing wowhead_npcs.csv record on purpose).

    Fresh Petopia/Wowhead extracts can make two things go stale:
      1. A tameable Petopia NPC still missing from both wowhead_npcs.csv
         and npcs_updates.csv -- needs a new 'add' row, or, if it doesn't
         belong, a Manual/skip_npc_ids.csv entry.
      2. An 'add'-tagged row whose npc_id now exists in wowhead_npcs.csv on
         its own -- Wowhead caught up, so the row is redundant, and worse:
         since 08_update_npcs.py never reads the 'action' column, it'll
         silently start behaving as an *update* (replacing the now-real
         wowhead record with this row's possibly-stale field values) on
         the next run instead of being the harmless no-op its 'add' tag
         implies.
    """
    wowhead_ids = _load_ids(WOWHEAD_NPCS_CSV)
    petopia_tameable = _load_petopia_tameable(PETOPIA_NPCS_CSV)
    npcs_updates_ids, add_entries = _load_npcs_updates(NPC_UPDATES_CSV)
    skip_reasons = _load_skip_reasons(SKIP_NPC_IDS_CSV)

    missing = sorted(
        (nid for nid in petopia_tameable if nid not in wowhead_ids and nid not in npcs_updates_ids),
        key=lambda x: int(x) if x.isdigit() else 0,
    )
    unaccounted = [nid for nid in missing if nid not in skip_reasons]

    stale_add = sorted(
        ((nid, name) for nid, name in add_entries if nid in wowhead_ids),
        key=lambda pair: int(pair[0]) if pair[0].isdigit() else 0,
    )

    print(f"wowhead_npcs.csv npc_ids: {len(wowhead_ids)}")
    print(f"Petopia tameable npc_ids: {len(petopia_tameable)}")
    print(f"npcs_updates.csv entries: {len(npcs_updates_ids)} ({len(add_entries)} tagged 'add')")
    print(f"Missing from wowhead_npcs.csv and npcs_updates.csv: {len(missing)}")
    print(f"  - Accounted for in skip_npc_ids.csv: {len(missing) - len(unaccounted)}")
    print(f"  - UNACCOUNTED (needs an add-or-skip decision): {len(unaccounted)}")
    print(f"Stale 'add' entries (npc_id now native to wowhead_npcs.csv): {len(stale_add)}")

    actions = []
    for nid in unaccounted:
        actions.append((
            nid,
            (f"Resolve npc_id {nid} ({petopia_tameable[nid]}): add to Manual/npcs_updates.csv "
             f"(action=add) if tameable, or to Manual/skip_npc_ids.csv if not")
        ))
    for nid, name in stale_add:
        actions.append((
            nid,
            (f"Remove npc_id {nid} ({name}) from Manual/npcs_updates.csv - action=add but it's "
             f"now natively in wowhead_npcs.csv")
        ))
    return actions


def _load_wowhead_rows_by_npc():
    """Returns npc_id -> list of its raw wowhead_data.csv rows."""
    rows_by_npc = {}
    if not os.path.exists(WOWHEAD_DATA_CSV):
        return rows_by_npc
    with open(WOWHEAD_DATA_CSV, 'r', encoding='utf-8-sig', newline='', errors='replace') as f:
        for row in csv.DictReader(f):
            npc_id = (row.get('npc_id') or '').strip()
            if npc_id:
                rows_by_npc.setdefault(npc_id, []).append(row)
    return rows_by_npc


def _load_petopia_zones():
    """npc_id -> Petopia's free-text zone column, e.g. 'Stoneplow, Valley of the Four Winds'."""
    zones = {}
    if not os.path.exists(PETOPIA_NPCS_CSV):
        return zones
    with open(PETOPIA_NPCS_CSV, 'r', encoding='utf-8-sig', newline='', errors='replace') as f:
        for row in csv.DictReader(f):
            npc_id = (row.get('npc_id') or '').strip()
            zone = (row.get('zone') or '').strip()
            if npc_id and zone:
                zones[npc_id] = zone
    return zones


def _load_wowhead_npc_zone_ids(path):
    """
    npc_id -> zone_id string from wowhead_npcs.csv (may be pipe-delimited for
    NPCs that spawn in several zones). Excludes the literal 'unknown' sentinel
    07_extract_wowhead_npcs.py writes when Wowhead itself has no zone on file
    -- that string is not a real lead, just a recorded absence.
    """
    zones = {}
    if not os.path.exists(path):
        return zones
    with open(path, 'r', encoding='utf-8-sig', newline='', errors='replace') as f:
        for row in csv.DictReader(f):
            npc_id = (row.get('npc_id') or '').strip()
            zone_id = (row.get('zone_id') or '').strip()
            if npc_id and zone_id and zone_id.lower() != 'unknown':
                zones[npc_id] = zone_id
    return zones


def _location_lead_text(wowhead_zone, petopia_zone):
    """
    Plain-fact summary of whatever location lead is on file, or None.
    Deliberately doesn't guess a remedy -- a wowhead_npcs.csv lead usually
    means 09_extract_wowhead_data.py just needs a re-run to pick it up, a
    Petopia-only lead usually means a manual Manual/location_updates.csv
    entry, and a human is better placed to tell those apart than a check.
    """
    bits = []
    if wowhead_zone:
        bits.append(f"wowhead zone_id={wowhead_zone}")
    if petopia_zone:
        bits.append(f"Petopia zone={petopia_zone}")
    return "; ".join(bits) if bits else None


def check_location_healing():
    """
    Location healing: cross-checks wowhead_data.csv npc_ids missing every
    LOCATION_FIELDS value against the final pet_data.csv, rather than only
    Manual/location_updates.csv — a gap can be closed by location_updates.csv,
    by Manual/record_overrides.csv, or by anything else upstream, so whether
    the npc_id (with real location) reaches pet_data.csv is what actually
    matters, not which file did the fixing.

    npc_ids that still never reach pet_data.csv are split further:
      - already accounted for in Manual/skip_npc_ids.csv (fine, on purpose)
      - UNACCOUNTED: no skip entry either. Flagged with whatever location
        lead is on file now (wowhead_npcs.csv's zone_id and/or Petopia's
        zone) so a human can judge the next step -- see _location_lead_text.
    """
    rows_by_npc = _load_wowhead_rows_by_npc()
    pet_data_ids = _load_ids(COMBINED_PET_DATA_CSV)
    skip_reasons = _load_skip_reasons(SKIP_NPC_IDS_CSV)
    wowhead_zones = _load_wowhead_npc_zone_ids(WOWHEAD_NPCS_CSV)
    petopia_zones = _load_petopia_zones()

    missing = sorted(
        (nid for nid, rows in rows_by_npc.items()
         if all(not any((r.get(f) or '').strip() for f in LOCATION_FIELDS) for r in rows)),
        key=lambda x: int(x) if x.isdigit() else 0,
    )

    healed_in_final = [nid for nid in missing if nid in pet_data_ids]
    absent = [nid for nid in missing if nid not in pet_data_ids]
    unaccounted = [nid for nid in absent if nid not in skip_reasons]

    print(f"wowhead_data.csv npc_ids: {len(rows_by_npc)}")
    print(f"Missing all location data: {len(missing)}")
    print(f"  - Healed (now present in pet_data.csv): {len(healed_in_final)}")
    print(f"  - Absent from pet_data.csv entirely: {len(absent)}")
    print(f"      - Accounted for in skip_npc_ids.csv: {len(absent) - len(unaccounted)}")
    print(f"      - UNACCOUNTED (needs a heal-or-skip decision): {len(unaccounted)}")

    actions = []
    for nid in unaccounted:
        npc_name = rows_by_npc[nid][0].get('npc_name', '')
        lead = _location_lead_text(wowhead_zones.get(nid), petopia_zones.get(nid))
        if lead:
            desc = f"npc_id {nid} ({npc_name}) now has a location lead ({lead}) - review and resolve"
        else:
            desc = (f"npc_id {nid} ({npc_name}) has no location lead yet - needs research, "
                     "or a Manual/skip_npc_ids.csv entry")
        actions.append((nid, desc))
    return actions


def check_skip_npc_ids_freshness():
    """
    Manual/skip_npc_ids.csv rows reasoned 'unknown location' were skipped
    because no zone data existed anywhere at the time. That can stop being
    true as fresh extracts land: wowhead_npcs.csv's zone_id can go from the
    'unknown' sentinel to a real value, or petopia_npcs.csv's zone column
    can fill in. Either means the skip reason is stale -- the NPC should be
    reconsidered (via Location healing, once un-skipped) rather than stay
    skipped forever on a reason that's no longer accurate.
    """
    skip_reasons = _load_skip_reasons(SKIP_NPC_IDS_CSV)
    wowhead_zones = _load_wowhead_npc_zone_ids(WOWHEAD_NPCS_CSV)
    petopia_zones = _load_petopia_zones()

    unknown_location_ids = sorted(
        (nid for nid, reasons in skip_reasons.items()
         if any(r.lower() == 'unknown location' for r in reasons)),
        key=lambda x: int(x) if x.isdigit() else 0,
    )

    stale = [
        (nid, _location_lead_text(wowhead_zones.get(nid), petopia_zones.get(nid)))
        for nid in unknown_location_ids
    ]
    stale = [(nid, lead) for nid, lead in stale if lead]

    print(f"skip_npc_ids.csv entries reasoned 'unknown location': {len(unknown_location_ids)}")
    print(f"  - Now have a location lead: {len(stale)}")

    return [
        (nid, f"npc_id {nid} is still skipped as 'unknown location' but now has a lead ({lead}) - review")
        for nid, lead in stale
    ]


# Registry of (title, check_fn) pairs. See module docstring for the
# check_fn contract (prints a short summary, returns (npc_id, description)
# action items).
CHECKS = [
    ("Petopia NPCs missing from pet_data.csv", check_petopia_npcs_missing_from_pet_data),
    ("pet_data.csv required fields present", check_pet_data_required_fields),
    ("Location healing", check_location_healing),
    ("Orphan note updates", check_orphan_note_updates),
    ("npcs_updates.csv freshness", check_npcs_updates_freshness),
    ("skip_npc_ids.csv freshness", check_skip_npc_ids_freshness),
]


def _write_action_list_csv(action_items, path):
    """action_items: list of (check_title, npc_id, description)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['npc_id', 'check', 'description'])
        for title, npc_id, description in action_items:
            writer.writerow([npc_id, title, description])


def main():
    # Run every check first, capturing its short printed summary so the
    # Action List (built from what each check returns) can be shown up
    # front, ahead of the per-check summaries that explain the counts.
    action_items = []
    check_reports = []
    for title, check in CHECKS:
        buf = io.StringIO()
        with redirect_stdout(buf):
            actions = check()
        check_reports.append((title, buf.getvalue()))
        action_items.extend((title, npc_id, description) for npc_id, description in actions)

    print("=" * 60)
    print("Step 16: Validate Data")
    print("=" * 60)

    print(f"\nAction List ({len(action_items)} open)")
    print("-" * 60)
    if action_items:
        for i, (title, npc_id, description) in enumerate(action_items, start=1):
            print(f"Action {i}: [{title}] {description}")
    else:
        print("No open actions - all checks clear.")

    for title, report in check_reports:
        print(f"\n{'-' * 60}\n{title}\n{'-' * 60}")
        print(report, end="")

    _write_action_list_csv(action_items, ACTION_LIST_CSV)

    print("\n" + "=" * 60)
    if action_items:
        print(f"Validation complete: {len(action_items)} open action(s) - full detail in {ACTION_LIST_CSV}")
    else:
        print("Validation complete: all checks clear.")
    print("=" * 60)


if __name__ == "__main__":
    main()
