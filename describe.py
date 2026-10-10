"""English one-line descriptions for events.

Without an API key every event gets a short line built from its facts ("Rock gig at Nobel.
Tickets from €29.90."). With the `anthropic` package installed and a Claude API key available,
new events get a proper sentence written by Claude from the Dutch source text. Those are cached
in data/descriptions.json, so each event is only written once.
"""
import json
import os
import re

CATS = ["Film", "Music", "Comedy", "Talks", "Theatre", "Culture", "Exhibition", "Outdoors"]
MODEL = os.environ.get("UIL_MODEL", "claude-opus-5-5")
BATCH = 25

NOUN = {
    "Music": "Live music", "Comedy": "Comedy", "Theatre": "Theatre", "Talks": "A talk",
    "Film": "A film screening", "Culture": "Cultural event", "Exhibition": "An exhibition",
    "Outdoors": "An outdoor outing",
}
GENRE = {
    "klassieke muziek": "Classical concert", "muziek": "Concert", "cabaret": "Dutch-language cabaret",
    "toneel": "Drama", "muziektheater": "Music theatre", "musical en show": "Musical",
    "dans": "Dance performance", "theatercollege": "Theatre lecture", "specials": "Special performance",
    "gastprogramma": "Guest performance", "rock": "Rock gig", "metal": "Metal gig", "jazz": "Jazz",
    "pop": "Pop gig", "indie": "Indie night", "hits": "Club night", "tribute": "Tribute show",
    "funk": "Funk night", "hiphop": "Hip-hop", "hip-hop": "Hip-hop", "punk": "Punk gig",
    "folk": "Folk", "blues": "Blues", "singer-songwriter": "Singer-songwriter", "soul": "Soul",
    "elektronisch": "Electronic night", "electronic": "Electronic night", "dance": "Dance night",
    "country": "Country", "wereld": "World music", "world": "World music", "r&b": "R&B",
}


KIND = [  # what the title says the thing is, for when there's no genre
    (r"workshop|cursus|masterclass", "Workshop"), (r"rondleiding|excursie|tour\b|wandeling|walk", "Guided walk or tour"),
    (r"markt|beurs|fair|ruil", "Market"), (r"festival", "Festival"), (r"quiz|bingo", "Quiz night"),
    (r"\bloop\b|\brun\b|marathon", "Run"), (r"feest|party|disco", "Party"), (r"lezing|lecture|talk|caf[eé]\b", "Talk"),
    (r"concert|koor|choir|orkest|zang", "Concert"), (r"film|cinema", "Film screening"),
]


def template(ev: dict) -> str:
    title = ev["t"].lower()
    kind = next((name for pattern, name in KIND if re.search(pattern, title)), None)
    head = GENRE.get((ev.get("genre") or "").lower()) or kind or NOUN.get(ev["cat"], "Event")
    where = ev["where"]
    line = f"{head} at {where}" if not re.search(r"\d", where) else f"{head}, {where}"
    if ev.get("town", "Leiden") != "Leiden" and ev["town"].lower() not in ev["where"].lower():
        line += f", {ev['town']}"
    line += "."
    if ev.get("dates"):
        line += f" On {len(ev['dates'])} dates."
    elif ev.get("s") and ev["s"] != ev.get("e"):
        line += " Runs over several days."
    price = ev.get("price")
    if price == 0:
        line += " Free."
    elif price:
        line += f" Tickets from €{price:.2f}.".replace(".00.", ".")
    return line


SYSTEM = """You write the descriptions for a personal what's-on page about Leiden, read by a couple looking for things to do together.

For each event you get its title, venue, a category guess and the organiser's Dutch text. Return:
- description: one English sentence of at most 22 words, in your own words, saying what it is and why someone might go. Don't translate the Dutch line by line or quote it, and don't add facts that aren't in the input (no invented performers, dates or prices). Plain and specific, no hype, no exclamation marks, no emojis. If the event is in Dutch only, you may say so.
- category: the best fit from the allowed list."""

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "description": {"type": "string"},
                    "category": {"type": "string", "enum": CATS},
                },
                "required": ["id", "description", "category"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def with_claude(events: list) -> dict:
    """Return {event id: {"d": ..., "cat": ...}} for as many events as Claude could do."""
    try:
        import anthropic
    except ImportError:
        print("  Descriptions: using templates (run `pip3 install anthropic` and set ANTHROPIC_API_KEY for written ones)")
        return {}
    client = anthropic.Anthropic()
    out = {}
    for i in range(0, len(events), BATCH):
        chunk = events[i:i + BATCH]
        payload = [{"id": e["id"], "title": e["t"], "venue": e["where"], "town": e.get("town", "Leiden"),
                    "category_guess": e["cat"], "genre": e.get("genre", ""), "dutch_text": (e.get("nl") or "")[:600]}
                   for e in chunk]
        try:
            resp = client.beta.messages.create(
                model=MODEL,
                max_tokens=16000,
                # If the model declines a batch, the API retries it on a fallback model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
                system=SYSTEM,
                messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            )
        except anthropic.AuthenticationError:
            print("  Descriptions: the API key was rejected; using templates")
            return out
        except anthropic.RateLimitError:
            print("  Descriptions: rate limited; the rest get templates this run")
            return out
        except anthropic.APIStatusError as e:
            print(f"  Descriptions: API error {e.status_code} on one batch; it gets templates this run")
            continue
        except anthropic.APIConnectionError:
            print("  Descriptions: couldn't reach the API; using templates")
            return out
        except TypeError as e:
            # No credentials at all, or an SDK too old for these parameters.
            why = "no API key found" if "authentication" in str(e) else str(e)
            print(f"  Descriptions: using templates ({why})")
            return out
        if resp.stop_reason == "refusal":
            continue
        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            items = json.loads(text)["items"]
        except (json.JSONDecodeError, KeyError):
            continue
        for it in items:
            if it.get("id") and it.get("description"):
                out[it["id"]] = {"d": it["description"].strip(), "cat": it.get("category")}
        print(f"  Descriptions: written {len(out)}/{len(events)}", end="\r")
    if out:
        print(f"  Descriptions: Claude wrote {len(out)} new ones" + " " * 10)
    return out
