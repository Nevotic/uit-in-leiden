# Uit in Leiden

A one-file website (`index.html`) with what's on in and around Leiden, plus a date planner that checks the weather.
`update_events.py` refreshes the events inside `index.html`; upload that file to your host afterwards.

## Hosting (GitHub Pages)

`.github/workflows/publish.yml` runs every morning on GitHub (03:17 UTC, with a backup run at 06:47 UTC because GitHub sometimes starts scheduled runs late): it runs `update_events.py`, commits the new data and publishes `index.html` to GitHub Pages. A push of your own changes republishes the page straight away (without fetching events). To refresh by hand: the repository's **Actions** tab → **Update and publish** → **Run workflow**.

`.github/workflows/venues.yml` runs `update_venues.py` on the 1st of every month (02:00 UTC) and commits `data/venues.json`; the next daily run uses the new names. Run it by hand from the Actions tab → **Refresh venue names**.

For Claude-written descriptions, add your key under **Settings → Secrets and variables → Actions → New repository secret**, named `ANTHROPIC_API_KEY`.

## Update the events

```bash
python3 update_events.py
```

It takes about two minutes: it waits 1.5 seconds between requests to each site and follows their robots.txt. At the end it prints how many events each source returned, how many land in each section of the page, and any source that failed.

Options:

| | |
|---|---|
| `--dry-run` | fetch and report, but don't change any files |
| `--days 120` | look further ahead (default 90 days) |
| `--no-ai` | don't use Claude for descriptions (see below) |
| `--debug` | show the full error when a source fails |

No packages are needed; it runs on the Python 3 that comes with macOS.

### Better descriptions (optional)

The sources are in Dutch. By default each new event gets a short English line built from its details ("Rock gig at Nobel. Tickets from €29.90."). For a proper sentence per event, install the Claude SDK and set an API key:

```bash
pip3 install anthropic
export ANTHROPIC_API_KEY=sk-ant-...
python3 update_events.py
```

Claude (model `claude-opus-5-5`, override with `UIL_MODEL`) writes each description once; they're saved in `data/descriptions.json` and reused on later runs, so a daily update only pays for new events. The first run, with a few hundred events, costs roughly a dollar or two; after that it's cents.

## Your own edits: the `data/` folder

The script never overwrites these, except that it adds new entries to `descriptions.json`.

- **`data/evergreen.json`**: the "Always good" places. Same fields as an event, without dates. Optional planner hints: `c` (cost 0–3), `io` (`"in"`/`"out"`), `v` (vibes: `cosy`, `active`, `cultural`, `surprise`), `dry: 1` (only when it's dry), `calm: 1` (only when it's not windy), `months` (0 = January, e.g. `[3,4,5,6,7,8,9]` for April–October).
- **`data/manual.json`**:
  - `events`: events the sources don't have (LIFF, things from other sites). Needs at least `id`, `t` (title), `s`/`e` (dates `YYYY-MM-DD`), `cat`, `where`, `d` (description), `url`. Optional: `time`, `town`, `hl: 1` (show as the Highlight), `weekly: 0` (every Sunday; 0 = Sunday … 6 = Saturday), `dates: [...]` (scattered dates).
  - `patch`: change something about a scraped event, keyed by its URL or id, e.g. `{"https://www.visitleiden.nl/nl/agenda/123/foo": {"cat": "Comedy", "hl": 1}}`.
  - `hide`: URLs or ids of events to leave out.
- **`data/descriptions.json`**: English one-liners by event URL. Edit any text you don't like; your version wins.
- **`data/venues.json`**: street address → venue name. Visit Leiden often only gives an address. `python3 update_venues.py` (about 12 minutes; run it now and then) fills this from Visit Leiden's own venue pages, `update_events.py` also learns names from events that have both, and you can add your own (`"Middelstegracht 123": "…"`). Your entries are never overwritten.
- `data/events.json` is generated (the full list, including the Dutch source text). If a source fails, the script falls back to its events from here.

Categories: `Film`, `Music`, `Comedy`, `Talks`, `Theatre`, `Culture`, `Exhibition`, `Outdoors`.

## Sources

One file per source in `sources/`, tried in this order (when two list the same event, the first one wins and the others only fill in missing times or prices):

| File | Site | How |
|---|---|---|
| `visitleiden.py` | Visit Leiden UITagenda | schema.org Event data on the agenda pages, plus the keyword filters for categories |
| `schouwburg.py` | Leidse Schouwburg & Stadsgehoorzaal | their public WordPress API (`/wp-json/wp/v2/show`) |
| `scheltema.py` | Scheltema | schema.org Event data on the agenda page |
| `nobel.py` | Nobel | the agenda page's HTML |

Left out on purpose: **DagjeWeg.NL** (blocks automated visitors), **Kijkhuis/Trianon/Lido** (their robots.txt forbids fetching the film times; films still come in through Visit Leiden), **LVC** (closed; Nobel took over).

## When a source breaks

The summary will say e.g. `Nobel FAILED, kept 63 events from the last good run (...)`. The page keeps working with the old data, so there's no rush.

1. Run `python3 update_events.py --dry-run --debug` to see the full error.
2. Open that source's file in `sources/`. The docstring at the top says what the code expects from the site.
3. Open the site in a browser and compare. Usually a class name or URL changed:
   - `visitleiden.py`, `scheltema.py`: view the page source and search for `application/ld+json`.
   - `schouwburg.py`: open the API URL at the top of the file in a browser.
   - `nobel.py`: the `CARD` pattern and the `<h3>`/`<p>`/`genre` lookups.
4. Test just that source:
   ```bash
   python3 -c "from datetime import date,timedelta; from sources import nobel; ev=nobel.fetch(date.today(), date.today()+timedelta(90)); print(len(ev)); print(ev[:2])"
   ```
5. If a site starts forbidding automated access (robots.txt or a bot check), the script reports `robots.txt disallows ...`. Remove the source from `sources/__init__.py` rather than working around it.

To add a source: copy one of the files, keep `NAME` and `fetch(today, horizon)` returning the same kind of dicts, and add it to `SOURCES` in `sources/__init__.py`.
