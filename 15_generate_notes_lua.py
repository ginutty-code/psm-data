"""
Generate addon Notes data file
"""

import csv
import os
from config import COMBINED_PET_DATA_CSV, NOTES_LUA, ensure_dirs

def main():
    ensure_dirs()
    print(f"Loading CSV from {COMBINED_PET_DATA_CSV}...")
    if not os.path.exists(COMBINED_PET_DATA_CSV):
        print(f"Error: CSV file not found: {COMBINED_PET_DATA_CSV}")
        return

    # Read the CSV file
    with open(COMBINED_PET_DATA_CSV, 'r', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        npc_notes = list(reader)

    # Generate the Lua file
    lua_content = '''-- NotesData.lua
-- Curated seed notes for notable tameable NPCs, keyed by NPC ID.
-- These are read-only. User-edited notes are stored separately in PSM_UserNotes (SavedVariables).
-- At runtime, seed notes and user notes are merged by the Notes UI layer.

PSM.NotesData = {
'''

    processed_ids = set()
    for row in npc_notes:
        npc_id = row.get('npc_id')
        note = (row.get('notes') or '').strip()
        if npc_id and note and npc_id not in processed_ids:
            # Lua long brackets [[ ]] safely handle newlines and quotes.
            lua_content += f'    [{npc_id}] = [[{note}]],\n'
            processed_ids.add(npc_id)

    lua_content += '''}

function PSM.NotesData.Get(npcID)
    local seed = PSM.NotesData[npcID]
    local user = PSM_UserNotes and PSM_UserNotes[npcID]
    if seed and user and user ~= "" then
        return seed .. "\\n\\n" .. user
    end
    return seed or (user ~= "" and user) or nil
end
function PSM.NotesData.GetUserNote(npcID)
    return (PSM_UserNotes and PSM_UserNotes[npcID]) or ""
end
function PSM.NotesData.SetUserNote(npcID, text)
    PSM_UserNotes = PSM_UserNotes or {}
    if not text or text == "" then
        PSM_UserNotes[npcID] = nil
    else
        PSM_UserNotes[npcID] = text
    end
end
'''

    # Write the Lua file
    with open(NOTES_LUA, 'w', encoding='utf-8') as luafile:
        luafile.write(lua_content)

    print(f"Done! Lua file saved to: {NOTES_LUA}")

if __name__ == "__main__":
    main()