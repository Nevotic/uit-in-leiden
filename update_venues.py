#!/usr/bin/env python3
"""Fill data/venues.json (street address -> venue name) from Visit Leiden's location pages.

Visit Leiden's event listings often give only a street address. Its location pages (listed in
its location sitemap) give the venue's name and address. This walks those pages once and adds
every address that belongs to exactly one venue. Names you've added yourself are kept.

    python3 update_venues.py        # takes ~12 minutes (one polite request per 1.5 s)

Run it now and then; update_events.py picks the names up on its next run.
"""
import json
import re
from collections import defaultdict
from pathlib import Path

from sources.common import clean, get, ld_json

SITEMAP = "https://www.visitleiden.nl/nl/sitemap/location.xml"
VENUES = Path(__file__).resolve().parent / "data" / "venues.json"


def main():
    pages = re.findall(r"<loc>(.*?)</loc>", get(SITEMAP))
    urls = [u for p in pages for u in re.findall(r"<loc>(.*?)</loc>", get(p))]
    print(f"{len(urls)} location pages")
    names = defaultdict(set)
    for i, url in enumerate(urls, 1):
        try:
            blocks = ld_json(get(url))
        except Exception as e:  # one broken page shouldn't stop the run
            print(f"  skipped {url}: {e}")
            continue
        for b in blocks:
            addr = b.get("address")
            if b.get("name") and isinstance(addr, dict) and addr.get("streetAddress"):
                names[clean(addr["streetAddress"])].add(clean(b["name"]))
        if i % 50 == 0:
            print(f"  {i}/{len(urls)}")

    venues = json.loads(VENUES.read_text(encoding="utf-8")) if VENUES.exists() else {}
    added = shared = 0
    for addr, found in sorted(names.items()):
        if addr in venues:
            continue
        if len(found) == 1:
            venues[addr] = found.pop()
            added += 1
        else:
            shared += 1  # several venues at one address: leave it to you
    VENUES.write_text(json.dumps(dict(sorted(venues.items())), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Added {added} venue names ({shared} addresses with several venues skipped). {len(venues)} in total.")


if __name__ == "__main__":
    main()
