"""
Extract npc metadata for each npc in petopia.csv
"""

import csv
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import (
    PETOPIA_DATA_CSV,
    PETOPIA_NPCS_CSV,
    SKIP_NPC_IDS_CSV,
    ensure_dirs,
    get_random_headers,
)

CONCURRENCY = 2  # Adjust as needed, lower if rate limited
REQUEST_DELAY_RANGE = (1.0, 3.0)  # Randomized delay before each request
FETCH_MAX_ATTEMPTS = 3
FETCH_RETRY_DELAY = 3  # Seconds to wait between retry attempts for a single NPC
COOLDOWN_SECONDS = 120  # Pause the whole run when the site appears to be rate-limiting us

# Signal for graceful shutdown (e.g. Ctrl+C mid-batch)
stop_event = threading.Event()

_tls = threading.local()
rate_limit_lock = threading.Lock()
global_backoff_until = 0  # Timestamp; workers pause while time.time() < this


def get_session() -> requests.Session:
    """Return a thread-local session that retries transient connection/server errors."""
    if getattr(_tls, 'session', None) is None:
        s = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retries, pool_connections=CONCURRENCY * 2, pool_maxsize=CONCURRENCY * 2)
        s.mount('http://', adapter)
        s.mount('https://', adapter)
        _tls.session = s
    return _tls.session


def fetch_page(url: str) -> str:
    _, headers = get_random_headers()
    resp = get_session().get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.text


def load_skip_npc_ids(path: str) -> set[str]:
    """Load NPC IDs to skip from the provided CSV file."""
    skip_ids = set()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    for key in row:
                        if key.strip().replace("\ufeff", "") == "npc_id":
                            val = row.get(key)
                            if val:
                                skip_ids.add(str(val).strip())
                            break
        except (OSError, csv.Error) as e:
            print(f"Failed to read skip list {path}: {e}", file=sys.stderr)
    return skip_ids


def extract_npc_info(html: str) -> dict[str, str]:
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
                elif key == 'Name':
                    info['name_keeper'] = bool(value and 'retains original name' in value.lower())
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


def write_batch(rows: list[dict[str, str]], fieldnames: list[str], output_path: str, write_header: bool = False):
    mode = 'w' if write_header else 'a'
    with open(output_path, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fieldnames})


def fetch_npc_data(npc_id: str, url: str) -> tuple[str, dict[str, str]]:
    """
    Fetch and parse a single NPC page, retrying transient connection failures.

    Returns (status, extra_info):
      'success' - page fetched and parsed; extra_info has the scraped fields.
      'skip'    - page confirmed missing (404) or unparseable; extra_info is
                  empty, but the NPC is still considered done.
      'retry'   - fetch failed after all attempts; caller should leave this
                  NPC out of the written CSV so a future run retries it.
    """
    attempt = 0
    while attempt < FETCH_MAX_ATTEMPTS:
        if stop_event.is_set():
            return 'retry', {}

        with rate_limit_lock:
            wait_time = global_backoff_until - time.time()
        if wait_time > 0:
            for _ in range(int(wait_time) + 1):
                if stop_event.is_set():
                    return 'retry', {}
                time.sleep(1)
            continue

        attempt += 1
        try:
            time.sleep(random.uniform(*REQUEST_DELAY_RANGE))
            html = fetch_page(url)
        except requests.RequestException as e:
            if hasattr(e, 'response') and e.response is not None and e.response.status_code == 404:
                print(f"  {npc_id}: page not found (404), keeping bulk row only", file=sys.stderr)
                return 'skip', {}
            if attempt >= FETCH_MAX_ATTEMPTS:
                print(f"  {npc_id}: failed to fetch after {attempt} attempts: {e}", file=sys.stderr)
                return 'retry', {}
            print(f"  {npc_id}: fetch error, retrying ({attempt}/{FETCH_MAX_ATTEMPTS}): {e}", file=sys.stderr)
            time.sleep(FETCH_RETRY_DELAY)
            continue

        try:
            return 'success', extract_npc_info(html)
        except (AttributeError, KeyError, ValueError) as e:
            print(f"  {npc_id}: failed to parse page, keeping bulk row only: {e}", file=sys.stderr)
            return 'skip', {}

    return 'retry', {}


def process_single(row: dict[str, str]) -> tuple[str, dict[str, str]]:
    npc_id = row.get('npc_id', '') or ''
    url = f"https://www.wow-petopia.com/npc.php?id={npc_id}"
    status, extra_info = fetch_npc_data(npc_id, url)
    if status == 'retry':
        return 'retry', row
    return 'success', {**row, **extra_info}


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
            processed_npcs = {row['npc_id'] for row in reader if row.get('npc_id')}
        print(f"Resuming from {len(processed_npcs)} already processed NPCs.")

    # Load skip list
    skip_ids = load_skip_npc_ids(SKIP_NPC_IDS_CSV)
    if skip_ids:
        print(f"Loaded {len(skip_ids)} NPC IDs to skip.")

    fieldnames = ["npc_id", "npc_name", "zone", "tameable", "family", "level", "name_keeper", "wowhead_url", "tamingskillname1", "tamingskilldesc1", "tamingskillname2", "tamingskilldesc2", "notes", "appearance"]

    # Collect rows to process
    to_process = [row for row in rows if row.get('npc_id') and row['npc_id'] not in processed_npcs and row['npc_id'] not in skip_ids]

    global global_backoff_until

    batch = []
    processed_count = 0
    retried_count = 0
    consecutive_failures = 0

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        try:
            for i in range(0, len(to_process), CONCURRENCY):
                if stop_event.is_set():
                    break
                batch_rows = to_process[i:i + CONCURRENCY]
                print(f"Processing batch of {len(batch_rows)} NPCs...")
                futures = [executor.submit(process_single, row) for row in batch_rows]
                for future in as_completed(futures):
                    status, result = future.result()
                    if status == 'retry':
                        consecutive_failures += 1
                        retried_count += 1
                        print(f"  {result.get('npc_id')}: will retry on a future run")
                        if consecutive_failures >= CONCURRENCY:
                            with rate_limit_lock:
                                global_backoff_until = time.time() + COOLDOWN_SECONDS
                            print(f"  ! Repeated connection failures detected. Cooling down for {COOLDOWN_SECONDS}s...")
                            for _ in range(COOLDOWN_SECONDS):
                                if stop_event.is_set():
                                    break
                                time.sleep(1)
                            consecutive_failures = 0
                    else:
                        consecutive_failures = 0
                        batch.append(result)
                        processed_count += 1
                # Write the batch (size of CONCURRENCY)
                if batch:
                    write_batch(batch, fieldnames, PETOPIA_DATA_CSV, write_header)
                    write_header = False
                    print(f"Processed and wrote batch of {len(batch)} NPCs. Total processed: {processed_count}")
                    batch = []
        except KeyboardInterrupt:
            print("\n[!] Cancellation requested. Shutting down gracefully...")
            stop_event.set()
            executor.shutdown(wait=False, cancel_futures=True)
        finally:
            if batch:
                write_batch(batch, fieldnames, PETOPIA_DATA_CSV, write_header)

    suffix = f" ({retried_count} deferred for a future run)" if retried_count else ""
    print(f"Processing complete. Total new NPCs processed: {processed_count}{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())