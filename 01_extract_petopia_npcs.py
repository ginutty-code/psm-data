"""
Extract list of npc models from Petopia's available pets gallery page.
"""
import csv
import os
import re
import sys
from typing import List, Dict

import requests
from config import PETOPIA_NPCS_CSV, ensure_dirs, get_random_headers


URL = "https://www.wow-petopia.com/gallery.php?id=available"

# Patterns tailored to the structure in Petopia's HTML
# One record example (condensed):
# <div class='pettablename'><a href='/npc.php?id=250637'>Shredclaw</a></div></td>
# <td class='level'><span class='nowrap'>80-90</span></td>
# <td class='zone'>The Gorging Pit, Voidstorm</td></tr>
# <tr><td class='name'><div class='tameableicon'><img class='inline' src='/css/check.png' alt='Can Be Tamed' title='Can Be Tamed' /></div>

# We'll parse sequentially: find each pettablename anchor, then look ahead for nearest 'zone' cell and 'tameableicon' in the same row group.

ANCHOR_RE = re.compile(r"<div class='pettablename'>\s*<a href='/npc\.php\?id=(\d+)'>(.*?)</a>", re.IGNORECASE | re.DOTALL)
ZONE_RE = re.compile(r"<td class='zone'>(.*?)</td>", re.IGNORECASE | re.DOTALL)
TAMEABLE_ICON_RE = re.compile(r"<div class=['\"]tameableicon['\"][^>]*>.*?<img[^>]*src=['\"]([^'\"]+)['\"][^>]*alt=['\"]([^'\"]*)['\"][^>]*>", re.IGNORECASE | re.DOTALL)

# Fallback: some rows may use double quotes; handle both when searching around the anchor chunk
ANCHOR_RE_DQ = re.compile(r"<div class=\"pettablename\">\s*<a href=\"/npc\.php\?id=(\d+)\">(.*?)</a>", re.IGNORECASE | re.DOTALL)
ZONE_RE_DQ = re.compile(r"<td class=\"zone\">(.*?)</td>", re.IGNORECASE | re.DOTALL)

HTML_TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def clean_text(html_fragment: str) -> str:
    text = HTML_TAG_RE.sub(" ", html_fragment)
    text = WS_RE.sub(" ", text)
    return text.strip()


def fetch_page(url: str) -> str:
    _, headers = get_random_headers()
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_records(html: str) -> List[Dict[str, str]]:
    records: List[Dict[str, str]] = []

    # Combine matches from single- and double-quoted attribute styles
    anchor_matches = []
    for m in ANCHOR_RE.finditer(html):
        anchor_matches.append((m.start(), m.end(), m.group(1), clean_text(m.group(2))))
    for m in ANCHOR_RE_DQ.finditer(html):
        anchor_matches.append((m.start(), m.end(), m.group(1), clean_text(m.group(2))))

    # Sort by position to maintain document order
    anchor_matches.sort(key=lambda x: x[0])

    for idx, (start, end, npc_id, name) in enumerate(anchor_matches):
        # Look ahead until the start of the next record to keep the search bounded across multiple rows
        next_start = anchor_matches[idx + 1][0] if idx + 1 < len(anchor_matches) else len(html)
        chunk = html[end:next_start]

        # Try single-quoted then double-quoted variants
        zone_match = ZONE_RE.search(chunk) or ZONE_RE_DQ.search(chunk)
        zone = clean_text(zone_match.group(1)) if zone_match else ""

        # Detect tameable by the icon src or alt text within the tameableicon div
        icon_m = TAMEABLE_ICON_RE.search(chunk)
        tameable = ""
        if icon_m:
            src = icon_m.group(1).lower()
            alt = clean_text(icon_m.group(2))
            if "check.png" in src:
                tameable = alt or "Can Be Tamed"
            elif "redx.png" in src:
                tameable = alt or "Cannot Be Tamed"
            else:
                tameable = alt

        records.append({
            "npc_id": npc_id,
            "npc_name": name,
            "zone": zone,
            "tameable": tameable,
        })

    return records


def write_csv(rows: List[Dict[str, str]], path: str) -> None:
    fieldnames = ["npc_id", "npc_name", "zone", "tameable"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fieldnames})


def main() -> int:
    ensure_dirs()

    try:
        html = fetch_page(URL)
    except Exception as e:
        print(f"Failed to fetch {URL}: {e}", file=sys.stderr)
        return 1

    rows = parse_records(html)
    if not rows:
        print("No records parsed; the page structure might have changed.", file=sys.stderr)

    # Deduplicate by npc_id
    seen = set()
    unique_rows = []
    for r in rows:
        npc_id = r.get('npc_id')
        if npc_id and npc_id not in seen:
            seen.add(npc_id)
            unique_rows.append(r)

    write_csv(unique_rows, PETOPIA_NPCS_CSV)
    print(f"Wrote {len(unique_rows)} unique rows to {PETOPIA_NPCS_CSV} (removed {len(rows) - len(unique_rows)} duplicates)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
