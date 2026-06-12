"""
Extract npc metadata for each npc in petopia.csv
"""

import csv
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Set

import requests
from bs4 import BeautifulSoup
from config import PETOPIA_NPCS_CSV, PETOPIA_DATA_CSV, SKIP_NPC_IDS_CSV, ensure_dirs, get_random_headers

CONCURRENCY = 10  # Adjust as needed, lower if rate limited


def fetch_page(url: str) -> str:
    _, headers = get_random_headers()
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.text


def load_skip_npc_ids(path: str) -> Set[str]:
    """Load NPC IDs to skip from the provided CSV file."""
    skip_ids = set()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    for key in row.keys():
                        if key.strip().replace("\ufeff", "") == "npc_id":
                            val = row.get(key)
                            if val:
                                skip_ids.add(str(val).strip())
                            break
        except Exception:
            pass
    return skip_ids


def extract_npc_info(html: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, 'html.parser')
    content_div = soup.find('div', id='content2')
    if not content_div:
        return {}

    info = {}

    # Name
    h1 = content_div.find('h1')
    info['npc_name'] = h1.text.strip() if h1 else ""

    # Tameable status
    petstatus = content_div.find('p', class_='petstatus')
    if petstatus:
        info['tameable'] = "Can be tamed" if 'tameable' in (petstatus.get('class') or []) else "Cannot be tamed"

    # Extract from npc_data_panel table
    table = content_div.find('table', class_='npc_data_panel')
    if table:
        rows = table.find_all('tr')
        for row in rows:
            tds = row.find_all('td')
            if len(tds) == 2:
                key = tds[0].text.strip().rstrip(':')
                value = tds[1].text.strip()
                if key == 'Family':
                    # Extract link if present
                    a = tds[1].find('a')
                    info['family'] = a.text.strip() if a else value
                elif key == 'Level':
                    if '-' in value:
                        info['level'] = f'="{value}"'
                    else:
                        info['level'] = value
                elif key == 'Zone':
                    info['zone'] = value
                elif key == 'Wowhead':
                    a = tds[1].find('a')
                    info['wowhead_url'] = a['href'] if a and 'href' in a.attrs else ""

    # Taming skills
    taming_notes = content_div.find_all('div', class_='taming_skill_notes')
    for i, note in enumerate(taming_notes[:2]):  # Up to 2 taming skills
        title_div = note.find('div', class_='modeldetailstamingskilltitle')
        if title_div:
            skill_name = title_div.find('span', class_='modeldetailstamingskillname')
            if skill_name:
                info[f'tamingskillname{i+1}'] = skill_name.text.strip()
        desc_div = note.find('div', class_='modeldetailstamingskilldesc')
        if desc_div:
            info[f'tamingskilldesc{i+1}'] = desc_div.text.strip()

    # Notes (location & notes)
    notes_div = content_div.find('div', class_='npc_notes_div')
    if notes_div:
        p_notes = notes_div.find('p', class_='pet_notes')
        if p_notes:
            info['notes'] = p_notes.text.strip()

    # Appearance: list of image src
    looks_panel = content_div.find('div', class_='npc_looks_panel')
    images = []
    if looks_panel:
        imgs = looks_panel.find_all('img', class_='npc_portrait')
        for img in imgs:
            src = img.get('src')
            if src:
                images.append(f"https://www.wow-petopia.com{src}")
    info['appearance'] = '; '.join(images)

    return info


def write_batch(rows: List[Dict[str, str]], fieldnames: List[str], output_path: str, write_header: bool = False):
    mode = 'w' if write_header else 'a'
    with open(output_path, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fieldnames})


def process_single(row: Dict[str, str]) -> Dict[str, str]:
    npc_id = row.get('npc_id')
    name = row.get('npc_name', 'Unknown')
    url = f"https://www.wow-petopia.com/npc.php?id={npc_id}"
    try:
        html = fetch_page(url)
        extra_info = extract_npc_info(html)
        return {**row, **extra_info}
    except Exception as e:
        print(f"Failed to fetch or parse {url}: {e}", file=sys.stderr)
        return row  # Return original row to keep in CSV, but with empty extra fields


def main() -> int:
    ensure_dirs()

    try:
        with open(PETOPIA_NPCS_CSV, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except FileNotFoundError:
        print(f"Input CSV {PETOPIA_NPCS_CSV} not found.", file=sys.stderr)
        return 1

    # Check existing progress
    processed_npcs = set()
    write_header = not os.path.exists(PETOPIA_DATA_CSV)
    if not write_header:
        with open(PETOPIA_DATA_CSV, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            processed_npcs = set(row['npc_id'] for row in reader if row.get('npc_id'))
        print(f"Resuming from {len(processed_npcs)} already processed NPCs.")

    # Load skip list
    skip_ids = load_skip_npc_ids(SKIP_NPC_IDS_CSV)
    if skip_ids:
        print(f"Loaded {len(skip_ids)} NPC IDs to skip.")

    fieldnames = ["npc_id", "npc_name", "zone", "tameable", "family", "level", "wowhead_url", "tamingskillname1", "tamingskilldesc1", "tamingskillname2", "tamingskilldesc2", "notes", "appearance"]

    # Collect rows to process
    to_process = [row for row in rows if row.get('npc_id') and row['npc_id'] not in processed_npcs and row['npc_id'] not in skip_ids]

    batch = []
    processed_count = 0
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        for i in range(0, len(to_process), CONCURRENCY):
            batch_rows = to_process[i:i + CONCURRENCY]
            print(f"Processing batch of {len(batch_rows)} NPCs...")
            futures = [executor.submit(process_single, row) for row in batch_rows]
            for future in futures:
                result = future.result()
                if result:
                    batch.append(result)
                    processed_count += 1
            # Write the batch (size of CONCURRENCY)
            if batch:
                write_batch(batch, fieldnames, PETOPIA_DATA_CSV, write_header)
                write_header = False
                print(f"Processed and wrote batch of {len(batch)} NPCs. Total processed: {processed_count}")
                batch = []

    print(f"Processing complete. Total new NPCs processed: {processed_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())