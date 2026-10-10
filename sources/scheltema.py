"""Scheltema (https://www.scheltemaleiden.nl/agenda/).

The agenda page embeds one schema.org Event per date as JSON-LD.
"""
import re
from datetime import date

from .common import clean, get, guess_category, ld_json, nice_title, parse_price, shape_dates

NAME = "Scheltema"
URL = "https://www.scheltemaleiden.nl/agenda/"


def fetch(today: date, horizon: date) -> list:
    grouped = {}   # the same event on several dates arrives as several blocks
    for block in ld_json(get(URL)):
        if block.get("@type") != "Event" or not block.get("startDate"):
            continue
        title = nice_title(block.get("name") or "")
        if not title:
            continue
        offers = block.get("offers") if isinstance(block.get("offers"), dict) else {}
        url = block.get("url") or offers.get("url") or URL
        loc = block.get("location") or {}
        g = grouped.setdefault((title, url), {"block": block, "loc": loc, "offers": offers, "sessions": []})
        start = date.fromisoformat(block["startDate"][:10])
        end = date.fromisoformat((block.get("endDate") or block["startDate"])[:10])
        # A party running past midnight ends the next day; only the start date counts.
        g["sessions"].append((start, None))
        if (end - start).days > 1:
            g["sessions"] += [(date.fromordinal(o), None) for o in range(start.toordinal() + 1, end.toordinal() + 1)]

    events = []
    for (title, url), g in grouped.items():
        shaped = shape_dates(g["sessions"], today, horizon)
        if not shaped:
            continue
        text = clean(g["block"].get("description"))
        text = re.sub(r"^\d{1,2} \w+: ", "", text)
        venue = clean(g["loc"].get("name")) or "Scheltema"
        ev = {
            "id": "sc-" + re.sub(r"[^a-z0-9]+", "-", url.lower().rstrip("/").rsplit("/", 1)[-1])[:48],
            "t": re.sub(r"\s*[–-]\s*Scheltema Leiden$", "", title),
            "where": venue if venue.lower() != "scheltema leiden" else "Scheltema",
            "town": "Leiden",
            "url": url,
            "src": NAME,
            "cat": guess_category(title, text),
            "catSure": False,
            "nl": text[:700],
            **shaped,
        }
        price = parse_price(g["offers"].get("price"))
        if price is not None:
            ev["price"] = price
        events.append(ev)
    return events
