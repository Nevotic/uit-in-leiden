"""Visit Leiden UITagenda (https://www.visitleiden.nl/nl/agenda).

Every listing page embeds a schema.org ItemList of Events as JSON-LD, including the real
show times (eventSchedule), the venue and ticket prices. Categories aren't in the JSON-LD,
so we also walk the keyword-filtered listings and tag what shows up there.
"""
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from urllib.parse import quote

from .common import clean, get, guess_category, ld_json, nice_title, parse_price, shape_dates, town_name

NAME = "Visit Leiden"
BASE = "https://www.visitleiden.nl/nl/agenda"
MAX_PAGES = 60

# Visit Leiden keyword filter -> our category. None = useful for nothing but tagging.
KEYWORDS = {
    "Muziek": "Music",
    "Theater en Toneel": "Theatre",
    "Tentoonstellingen": "Exhibition",
    "Wandelen": "Outdoors",
    "Wetenschap": "Talks",
    "Festivals": None,
    "Kids": "kids",
}


def _items(page_html: str):
    for block in ld_json(page_html):
        if block.get("@type") == "ItemList":
            return [el.get("item", {}) for el in block.get("itemListElement", [])]
    return []


def _walk(url_for_page) -> list:
    """Fetch listing pages until one comes back empty."""
    out, seen = [], set()
    for page in range(1, MAX_PAGES + 1):
        items = _items(get(url_for_page(page)))
        new = [it for it in items if it.get("URL") and it["URL"] not in seen]
        if not new:
            break
        seen.update(it["URL"] for it in new)
        out.extend(new)
    return out


def _local(dt: str):
    """'2026-10-11T15:00:00' (+offset or not) -> (date, 'HH:MM' or None)."""
    d = datetime.fromisoformat(dt[:19])
    return d.date(), (d.strftime("%H:%M") if (d.hour, d.minute) != (0, 0) else None)


def fetch(today: date, horizon: date) -> list:
    raw = {it["URL"]: it for it in _walk(lambda p: f"{BASE}?page={p}")}
    tags = defaultdict(set)
    for kw in KEYWORDS:
        for it in _walk(lambda p, kw=kw: f"{BASE}?keyword%5B%5D={quote(kw)}&page={p}"):
            tags[it["URL"]].add(kw)
            raw.setdefault(it["URL"], it)

    events = []
    for url, it in raw.items():
        ev = _normalise(url, it, tags[url], today, horizon)
        if ev:
            events.append(ev)
    return events


def _normalise(url, it, kw, today, horizon):
    title = nice_title(it.get("name", ""))
    text = clean(it.get("description"))
    if not title or "Kids" in kw or re.search(r"\(\d+\+\)", title):
        return None   # children's programme
    loc = it.get("location") or {}
    addr = loc.get("address") or {}
    where = clean(loc.get("name")) or clean(addr.get("streetAddress")) or "Leiden"
    cats = [KEYWORDS[k] for k in kw if KEYWORDS.get(k) not in (None, "kids")]
    is_expo = "Exhibition" in cats or (not it.get("eventSchedule") and re.search(r"tentoonstelling|expositie", text.lower() + title.lower()))

    ev = {
        "id": "vl-" + (re.search(r"/agenda/(\d+)", url) or re.search(r"(.{1,40})$", url)).group(1),
        "t": title,
        "where": where,
        "town": town_name(addr.get("addressLocality")),
        "url": url,
        "src": NAME,
        "nl": text[:700],
    }
    prices = [p for p in (parse_price(o.get("price")) for o in it.get("offers") or []) if p is not None]
    if prices:
        ev["price"] = min(prices)

    if is_expo:
        if not it.get("endDate"):
            return None
        end = datetime.fromisoformat(it["endDate"][:19])
        # Visit Leiden stores "until midnight of the next day".
        last = (end - timedelta(days=1)).date() if (end.hour, end.minute) == (0, 0) else end.date()
        if last < today:
            return None
        ev.update(e=last.isoformat(), cat="Exhibition", catSure=True)
        return ev

    sessions = [_local(s["startDate"]) for s in it.get("eventSchedule") or [] if s.get("startDate")]
    shaped = shape_dates(sessions, today, horizon)
    if not shaped:
        return None
    ev.update(shaped)
    guess = guess_category(title, text)
    if cats and guess not in ("Comedy", "Film", "Talks"):
        ev.update(cat=cats[0], catSure=True)
    else:
        # Visit Leiden files cabaret under theatre and film nights under music;
        # the more specific text cue wins.
        ev.update(cat=guess, catSure=bool(cats))
    return ev
