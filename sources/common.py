"""Shared helpers for the event sources: polite fetching and text cleanup."""
import html
import json
import re
import time
import unicodedata
import urllib.error
import urllib.request
import urllib.robotparser
from datetime import date
from typing import Optional
from urllib.parse import urlsplit

USER_AGENT = "UitInLeiden/1.0 (personal what's-on page; fetches once a day)"
DELAY_SECONDS = 1.5      # pause between requests to the same host
TIMEOUT_SECONDS = 30

_last_request = {}       # host -> time of last request
_robots = {}             # host -> RobotFileParser (or None if robots.txt was unreachable)


class Blocked(Exception):
    """robots.txt disallows this URL."""


def _robots_for(url: str):
    parts = urlsplit(url)
    host = f"{parts.scheme}://{parts.netloc}"
    if host not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(host + "/robots.txt", headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as r:
                rp.parse(r.read().decode("utf-8", "replace").splitlines())
        except urllib.error.HTTPError as e:
            # 4xx means "no robots.txt": everything is allowed. 5xx: be careful and stop.
            rp.parse([] if e.code < 500 else ["User-agent: *", "Disallow: /"])
        except (urllib.error.URLError, TimeoutError):
            rp = None
        _robots[host] = rp
    return _robots[host]


def get(url: str, retries: int = 2) -> str:
    """GET a URL as text, respecting robots.txt and a per-host delay."""
    rp = _robots_for(url)
    if rp is not None and not rp.can_fetch(USER_AGENT, url):
        raise Blocked(url)
    host = urlsplit(url).netloc
    wait = DELAY_SECONDS - (time.monotonic() - _last_request.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "nl,en;q=0.8"})
    for attempt in range(retries + 1):
        try:
            _last_request[host] = time.monotonic()
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as r:
                return r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == retries:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries:
                raise
        time.sleep(DELAY_SECONDS * (attempt + 2))
    raise RuntimeError("unreachable")


def get_json(url: str):
    return json.loads(get(url))


def ld_json(page: str) -> list:
    """All JSON-LD objects on a page (lists flattened); malformed blocks are skipped."""
    out = []
    for raw in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        out.extend(data if isinstance(data, list) else [data])
    return out


def clean(text: Optional[str]) -> str:
    """Strip tags, unescape entities (twice: some sites double-escape) and collapse whitespace."""
    if not text:
        return ""
    text = html.unescape(html.unescape(str(text)))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def nice_title(title: str) -> str:
    """Tame SHOUTING TITLES into sentence case; leave normal titles alone."""
    title = clean(title)
    letters = [c for c in title if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.8 and len(letters) > 6:
        title = title.lower().capitalize()
    return title


def fold(text: str) -> str:
    return unicodedata.normalize("NFD", text.lower()).encode("ascii", "ignore").decode()


def title_key(title: str) -> str:
    """Loose key for spotting the same event listed by two sources."""
    t = fold(title)
    t = re.sub(r"\(.*?\)", " ", t)
    t = re.sub(r"\b(concert|voorstelling|premiere|leiden|live|in|de|het|een|the|a)\b", " ", t)
    return re.sub(r"[^a-z0-9]+", "", t)[:32]


def parse_price(value) -> Optional[float]:
    """'€ 15,00', '12.50 pin/cash', 'Gratis', 'Vanaf € 15' -> number (0 for free)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).lower()
    if "gratis" in s or "free" in s or s.strip() in ("0", "0.00", "0,00"):
        return 0.0
    m = re.search(r"(\d+)(?:[.,](\d{1,2}))?", s)
    return float(f"{m.group(1)}.{m.group(2) or 0}") if m else None


def town_name(locality: Optional[str]) -> str:
    if not locality:
        return "Leiden"
    return " ".join(w if w in ("aan", "den", "de", "op") else w.capitalize() for w in locality.strip().lower().split())


def iso(d: date) -> str:
    return d.isoformat()


def shape_dates(sessions, today: date, horizon: date, max_dates: int = 8) -> Optional[dict]:
    """Turn (date, "HH:MM" or None) sessions into the page's date fields.

    One day -> s == e. Consecutive days -> an s..e range. Scattered days -> a `dates` list.
    Returns None when nothing falls in the window, or when there are so many dates that it's
    really a standing activity (a weekly workshop, daily tours) rather than an event.
    """
    sessions = sorted({(d, t) for d, t in sessions if today <= d <= horizon}, key=lambda x: (x[0], x[1] or ""))
    if not sessions:
        return None
    days = sorted({d for d, _ in sessions})
    if len(days) > max_dates:
        return None
    out = {"s": iso(days[0]), "e": iso(days[-1])}
    first_time = next((t for _, t in sessions if t), None)
    if first_time:
        out["time"] = first_time
    if len(days) > 1 and (days[-1] - days[0]).days + 1 != len(days):
        out["dates"] = [iso(d) for d in days]
    return out


TEXT_HINTS = [
    ("Comedy", r"\b(comedy|cabaret|stand-?up|comedian|open mic|improv|pubquiz|pub quiz)\b"),
    ("Film", r"\b(film|cinema|bioscoop|filmhuis|screening|documentaire)\b"),
    ("Talks", r"\b(lezing|lecture|talk|debat|science caf|filosofie|college|symposium|pitch)\b"),
    ("Theatre", r"\b(theater|toneel|voorstelling|musical|dans|opera|ballet)\b"),
    ("Music", r"\b(concert|band|koor|choir|orkest|jazz|rock|dj|zang|muziek|music|live)\b"),
    ("Outdoors", r"\b(wandel|wandeling|walk|fiets|run|hardloop|natuur|tuin|boot|varen|excursie)\b"),
    ("Exhibition", r"\b(tentoonstelling|expositie|exhibition)\b"),
]


def guess_category(*texts: str) -> str:
    blob = fold(" ".join(t for t in texts if t))
    for cat, pattern in TEXT_HINTS:
        if re.search(pattern, blob):
            return cat
    return "Culture"
