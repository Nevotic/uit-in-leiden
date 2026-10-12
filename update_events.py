#!/usr/bin/env python3
"""Refresh the agenda in index.html from the event sources.

    python3 update_events.py            # fetch everything, update index.html
    python3 update_events.py --no-ai    # skip Claude, use template descriptions for new events
    python3 update_events.py --dry-run  # fetch and report, but don't write anything

Your own edits live in data/ (see README.md); this script never overwrites them.
"""
import argparse
import json
import re
import sys
import traceback
from datetime import date, timedelta
from pathlib import Path

import describe
from sources import SOURCES
from sources.common import Blocked, title_key

ROOT = Path(__file__).resolve().parent
PAGE = ROOT / "index.html"
DATA = ROOT / "data"
EVENTS = DATA / "events.json"              # last generated agenda; also the fallback when a source fails
DESCRIPTIONS = DATA / "descriptions.json"  # event URL -> English one-liner (edit freely)
MANUAL = DATA / "manual.json"              # your own events, tweaks and hidden events
EVERGREEN = DATA / "evergreen.json"        # "Always good" places
VENUES = DATA / "venues.json"              # street address -> venue name (learned automatically; add your own)

# Fields the page uses. Everything else (Dutch text, source name...) stays in data/events.json.
PAGE_FIELDS = ["id", "t", "s", "e", "dates", "time", "weekly", "cat", "where", "town", "d", "auto", "url", "img", "price",
               "c", "io", "slot", "v", "hl", "isNew", "noIdea", "dry", "calm", "long", "short", "months", "cost", "priceNote"]
START, END = "/* AGENDA:START", "/* AGENDA:END */"


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def days_of(ev):
    if ev.get("dates"):
        return set(ev["dates"])
    if not ev.get("s"):
        return {"expo"}
    s, e = date.fromisoformat(ev["s"]), date.fromisoformat(ev.get("e") or ev["s"])
    return {(s + timedelta(n)).isoformat() for n in range(min((e - s).days, 60) + 1)}


def merge(lists):
    """Combine sources in order of preference; a later duplicate only fills in missing details."""
    merged = []
    for events in lists:
        for ev in events:
            key, days = title_key(ev["t"]), days_of(ev)
            twin = None
            for m in merged:
                mk = title_key(m["t"])
                same = mk == key or (min(len(mk), len(key)) >= 8 and (mk.startswith(key) or key.startswith(mk)))
                if same and days & days_of(m):
                    twin = m
                    break
            if twin is None:
                merged.append(ev)
                continue
            for field in ("time", "price", "genre", "img"):
                if twin.get(field) is None and ev.get(field) is not None:
                    twin[field] = ev[field]
            if len(ev.get("nl") or "") > len(twin.get("nl") or ""):
                twin["nl"] = ev["nl"]
            if not twin.get("catSure") and ev.get("catSure"):
                twin["cat"], twin["catSure"] = ev["cat"], True
    return merged


def cost_level(price):
    if price is None:
        return None
    return 0 if price == 0 else 1 if price <= 15 else 2 if price <= 40 else 3


def windows(today):
    """Same date windows as the page, for the summary."""
    dow = (today.weekday() + 1) % 7  # Sunday = 0, like JavaScript
    if dow in (5, 6, 0):
        wk = (today, today + timedelta((7 - dow) % 7))
    else:
        wk = (today + timedelta(6 - dow), today + timedelta(7 - dow))
    wn_start = today if 1 <= dow <= 4 else today + timedelta(((8 - dow) % 7) or 7)
    wn = (wn_start, wn_start + timedelta(4 - (wn_start.weekday() + 1) % 7))
    soon = (max(wk[1], wn[1]) + timedelta(1), today + timedelta(60))
    return {"This weekend": wk, "Weeknights": wn, "Coming up": soon}


def in_window(ev, a, b):
    return any(a.isoformat() <= d <= b.isoformat() for d in days_of(ev) if d != "expo")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=90, help="how far ahead to collect events (default 90)")
    ap.add_argument("--no-ai", action="store_true", help="don't call Claude for descriptions")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    ap.add_argument("--debug", action="store_true", help="print the full error when a source fails")
    args = ap.parse_args()

    today = date.today()
    horizon = today + timedelta(days=args.days)
    previous = load(EVENTS, [])
    descriptions = load(DESCRIPTIONS, {})
    manual = load(MANUAL, {"events": [], "patch": {}, "hide": []})
    evergreen = load(EVERGREEN, [])

    print(f"Collecting events from {today} to {horizon}")
    collected, problems = [], []
    for src in SOURCES:
        try:
            events = src.fetch(today, horizon)
            if not events:
                raise RuntimeError("returned no events; the page layout may have changed")
            print(f"  {src.NAME:<30} {len(events):>4} events")
        except Blocked as e:
            events, why = [], f"robots.txt disallows {e}"
        except Exception as e:  # keep going: one broken source shouldn't stop the rest
            events, why = [], f"{type(e).__name__}: {e}"
            if args.debug:
                traceback.print_exc()
        else:
            why = None
        if why:
            kept = [ev for ev in previous if ev.get("src") == src.NAME and (ev.get("e") or ev.get("s") or "") >= today.isoformat()]
            events = kept
            problems.append(f"{src.NAME}: {why}")
            print(f"  {src.NAME:<30} FAILED, kept {len(kept)} events from the last good run ({why})")
        collected.append(events)

    # Your own events come first, so they win over a scraped duplicate.
    mine = [{"src": "manual", "catSure": True, **ev} for ev in manual.get("events", [])
            if (ev.get("e") or ev.get("s") or "9999") >= today.isoformat() or ev.get("weekly") is not None]
    events = merge([mine] + collected)
    hidden = set(manual.get("hide", []))
    events = [ev for ev in events if ev["id"] not in hidden and ev.get("url") not in hidden]

    # Venue names: Visit Leiden often gives only a street address. Learn address -> name from
    # events that have both, keep what you've added by hand, and fill in the rest.
    venues = load(VENUES, {})
    for ev in events:
        a = ev.get("addr")
        if a and ev["where"] != a and a not in venues:
            venues[a] = ev["where"]
    for ev in events:
        if ev.get("addr") and ev["where"] == ev["addr"] and ev["addr"] in venues:
            ev["where"] = venues[ev["addr"]]
    for ev in events:
        patch = manual.get("patch", {}).get(ev.get("url")) or manual.get("patch", {}).get(ev["id"])
        if patch:
            ev.update(patch)

    # Descriptions: yours/cached first, then Claude for new events, then templates.
    need = [ev for ev in events if not ev.get("d") and ev.get("url") not in descriptions]
    written = describe.with_claude(need) if need and not args.no_ai and not args.dry_run else {}
    for ev in events:
        w = written.get(ev["id"])
        if w:
            descriptions[ev["url"]] = w["d"]
            if not ev.get("catSure") and w.get("cat"):
                ev["cat"] = w["cat"]
        if not ev.get("d"):
            ev["d"] = descriptions.get(ev.get("url"))
        if not ev.get("d"):
            ev["d"], ev["auto"] = describe.template(ev), 1  # the page hides these in lists
        level = cost_level(ev.get("price"))
        if level is not None and "c" not in ev:
            ev["c"] = level
        if ev.get("town") == "Leiden":
            ev.pop("town")
    events.sort(key=lambda ev: (ev.get("s") or ev.get("e") or "", ev["t"]))

    # Summary per section, like the page shows it.
    print(f"\n{len(events)} events after merging duplicates")
    for name, (a, b) in windows(today).items():
        print(f"  {name:<14} {sum(1 for ev in events if ev['cat'] != 'Exhibition' and in_window(ev, a, b)):>4}")
    print(f"  {'Exhibitions':<14} {sum(1 for ev in events if ev['cat'] == 'Exhibition'):>4}")
    print(f"  {'Always good':<14} {len(evergreen):>4}")
    if problems:
        print("\nProblems (see README.md, 'When a source breaks'):")
        for p in problems:
            print("  - " + p)

    if args.dry_run:
        print("\nDry run: nothing written.")
        return
    save(EVENTS, events)
    save(DESCRIPTIONS, dict(sorted(descriptions.items())))
    save(VENUES, dict(sorted(venues.items())))

    page = PAGE.read_text(encoding="utf-8")
    a, b = page.find(START), page.find(END)
    if a < 0 or b < 0:
        sys.exit("index.html has no AGENDA:START/AGENDA:END markers; can't update it.")
    slim = lambda ev: {k: ev[k] for k in PAGE_FIELDS if ev.get(k) is not None}
    js = lambda rows: "[\n" + ",\n".join(json.dumps(slim(r), ensure_ascii=False).replace("</", "<\\/") for r in rows) + "\n]"
    sources = ", ".join(src.NAME for src in SOURCES)
    block = (f"{START} (written by update_events.py; edit data/*.json instead) */\n"
             f"const UPDATED = {json.dumps(today.isoformat())};\n"
             f"const SOURCES = {json.dumps(sources, ensure_ascii=False)};\n"
             f"const AGENDA = {js(events)};\n"
             f"const EVERGREEN = {js(evergreen)};\n")
    PAGE.write_text(page[:a] + block + page[b:], encoding="utf-8")
    print(f"\nUpdated {PAGE.name}. Upload it to your host to publish.")


if __name__ == "__main__":
    main()
