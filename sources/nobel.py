"""Nobel (https://nobel.nl/agenda), Leiden's pop venue.

No feed, so we read the agenda page. Each show is a link like
/agenda/audrey-horne-13-oct-2026 with a title, a one-line tagline and a genre.
The date comes from the end of the link.
"""
import re
from datetime import date

from .common import clean, get, nice_title

NAME = "Nobel"
URL = "https://nobel.nl/agenda"
MONTHS = {m: i for i, names in enumerate([
    ("jan",), ("feb",), ("mar", "mrt", "maa"), ("apr",), ("may", "mei"), ("jun",),
    ("jul",), ("aug",), ("sep",), ("oct", "okt"), ("nov",), ("dec",)], 1) for m in names}
SKIP = re.compile(r"geannuleerd|afgelast|cancelled|verplaatst", re.I)
CARD = re.compile(
    r'<a href="(/agenda/[^"]+)" class="event[^"]*">(.*?)</a>', re.S)


def fetch(today: date, horizon: date) -> list:
    events = []
    for href, body in CARD.findall(get(URL)):
        m = re.search(r"-(\d{1,2})-([a-z]{3})-(\d{4})$", href)
        if not m or m.group(2) not in MONTHS:
            continue
        day = date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))
        title = nice_title((re.search(r"<h3>(.*?)</h3>", body, re.S) or [None, ""])[1])
        if not title or SKIP.search(title) or not (today <= day <= horizon):
            continue
        tagline = clean((re.search(r"<p>(.*?)</p>", body, re.S) or [None, ""])[1])
        genre = clean((re.search(r'<span class="genre">(.*?)</span>', body, re.S) or [None, ""])[1])
        events.append({
            "id": "nb-" + href.rsplit("/", 1)[-1][:48],
            "t": title,
            "where": "Nobel",
            "town": "Leiden",
            "url": "https://nobel.nl" + href,
            "src": NAME,
            "cat": "Music",
            "catSure": True,
            "genre": genre,
            "nl": tagline,
            "s": day.isoformat(),
            "e": day.isoformat(),
        })
    return events
