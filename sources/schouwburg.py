"""Leidse Schouwburg & Stadsgehoorzaal (https://leidseschouwburg-stadsgehoorzaal.nl).

Their WordPress site has an open REST API. Each "show" carries its performances
(acf.events: start_date YYYYMMDD + start_time), genre, room and prices.
"""
from datetime import date, datetime

from .common import clean, get_json, nice_title, parse_price, shape_dates

NAME = "Schouwburg & Stadsgehoorzaal"
API = "https://leidseschouwburg-stadsgehoorzaal.nl/wp-json/wp/v2/show?per_page=100&_fields=id,link,title,excerpt,acf&page={}"

GENRES = {
    "cabaret": "Comedy",
    "klassieke muziek": "Music",
    "muziek": "Music",
    "jazz": "Music",
    "pop": "Music",
    "toneel": "Theatre",
    "muziektheater": "Theatre",
    "musical en show": "Theatre",
    "dans": "Theatre",
    "theatercollege": "Talks",
    "film": "Film",
}
SKIP_GENRES = {"jeugd en familie"}
SKIP_STATUS = ("geannuleerd", "afgelast", "cancel", "verplaatst")


def fetch(today: date, horizon: date) -> list:
    shows = []
    for page in range(1, 20):
        batch = get_json(API.format(page))
        if not batch:
            break
        shows.extend(batch)
        if len(batch) < 100:
            break

    events = []
    for show in shows:
        acf = show.get("acf") or {}
        genre = (acf.get("genre") or "").strip()
        if acf.get("hide") or genre.lower() in SKIP_GENRES:
            continue
        sessions = []
        for perf in acf.get("events") or []:
            if any(w in (perf.get("status") or "").lower() for w in SKIP_STATUS):
                continue
            try:
                day = datetime.strptime(perf["start_date"], "%Y%m%d").date()
            except (KeyError, ValueError):
                continue
            sessions.append((day, (perf.get("start_time") or "")[:5] or None))
        shaped = shape_dates(sessions, today, horizon)
        if not shaped:
            continue

        artist, name = clean(acf.get("artist")), clean(acf.get("title"))
        title = nice_title(f"{artist}: {name}" if artist and name and artist.lower() not in name.lower() else (name or artist or clean(show["title"]["rendered"])))
        room = clean(acf.get("room")) or "Leidse Schouwburg"
        # "Stadsgehoorzaal - Café Caat" -> "Café Caat (Stadsgehoorzaal)"
        hall, _, sub = room.partition(" - ")
        where = f"{sub} ({hall})" if sub and sub.lower() not in ("grote zaal",) else hall
        prices = [p for p in (parse_price(x.get("price")) for x in acf.get("prices") or []) if p]

        ev = {
            "id": f"ls-{show['id']}",
            "t": title,
            "where": where,
            "town": "Leiden",
            "url": show.get("link"),
            "src": NAME,
            "cat": GENRES.get(genre.lower(), "Theatre"),
            "catSure": genre.lower() in GENRES,
            "genre": genre,
            "nl": clean((show.get("excerpt") or {}).get("rendered"))[:700],
            **shaped,
        }
        if prices:
            ev["price"] = min(prices)
        events.append(ev)
    return events
