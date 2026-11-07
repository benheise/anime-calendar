# Anime Release Calendar

**[Open the calendar](https://benheise.github.io/anime-calendar/)**

A self-contained web page that shows when new anime episodes release on Crunchyroll,
HIDIVE, Netflix, Hulu, Prime Video and Disney+ in North America, in the viewer's own
time zone. It covers the Summer and Fall 2026 seasons, through December 31, 2026.

`anime-calendar-2026.html` is the finished page: one flat file with every release
embedded, no server and no external data. It is published to GitHub Pages at the link
above, and the same file also works opened locally or sent as an attachment.

## What the page does

- **Schedule.** A week grid in hour rows, so releases line up by time of day across the
  week, after Japanese TV listings. Today's column, a current-time line, dimmed releases
  that are already out, and a Next up strip with countdowns. On a phone it becomes a day
  picker with a single-day list.
- **Up next.** The next seven days in order, with what came out in the last 24 hours.
- **All shows.** Every title grouped by status (airing now, starting soon, date not
  announced, finished), with episode progress and sorting.
- **Guide.** How to read the schedule, time zones and daylight saving time, labels,
  platforms, sources and update cadence.
- **Cover art.** Each release shows the show's cover behind it, from AniList. The overlay
  behind the text is measured per cover so white text keeps at least 4.5:1 contrast (WCAG AA);
  dark covers stay vivid, bright ones get more overlay. Posters also appear in Up next, All
  shows and the show sheet. Art can be turned off, and is off by default when the system asks
  for more contrast. If AniList can't be reached, slots fall back to the plain design.
- **Show sheet.** Upcoming episodes, watch link, MyAnimeList and AniList links, research
  notes, and an **Add to calendar** .ics download (RFC 5545).
- **Filters.** Platform chips, a starred **My list**, and search, shared by every view.
- **Settings.** Time zone (automatic or chosen) and 12- or 24-hour clock. Settings and
  My list are stored in the browser only.
- **Works without JavaScript.** Where scripts are blocked (iOS Quick Look, mail previews),
  the page shows a snapshot of the build week in Eastern Time, the full show directory
  and the guide.
- Deep links (`#show:devils-crest`, `#schedule:2026-12-21`), keyboard shortcuts
  (`/` to search, ← → to change week), and a print stylesheet for the week.

## How it's built

```
anime-calendar-data.xlsx ──► build_calendar.py ──► anime-calendar-2026.html
                                    ▲
                     calendar-template.html
```

The workbook is the source of record, one row per title. `build_calendar.py` validates
it, computes every release (date, exact instant, episode numbers, premiere and finale
flags), and embeds that list in the template. The page only renders: it converts each
instant to the viewer's time zone. All scheduling rules live in one place, the build.

| File | Role |
|---|---|
| `anime-calendar-data.xlsx` | Source of record, plus research-cooldown columns |
| `build_calendar.py` | Validates the workbook, computes releases, builds the page |
| `calendar-template.html` | Page template: styles, platform colours, rendering |
| `covers.py`, `covers.json` | Cover art: AniList matching and per-cover overlay measurement; the cached result the build embeds |
| `anime-calendar-2026.html` | Built output (committed; CI checks it is current and publishes it to Pages) |
| `tests/test_build.py` | Unit tests for the schedule model, validation and rendering |
| `verify.js` | Runs the built page in jsdom and checks views, routing, export and placements |
| `CLAUDE.md` | Operating notes for research sweeps: source hierarchy, DST rules, past failures |

## Usage

Requires Python 3.9+ and Node 22.

```sh
make install       # pip install -r requirements.txt && npm ci
make check         # validate the workbook
make               # rebuild anime-calendar-2026.html
make test          # unit tests, validation, and the jsdom check (what CI runs)
```

Or call the script directly:

```sh
python3 build_calendar.py --check
python3 build_calendar.py --today 2026-11-06 --out /tmp/page.html   # reproducible build
python3 build_calendar.py --dump-airings "Devils' Crest"            # every computed release
python3 build_calendar.py --news                                    # scan Crunchyroll news
python3 build_calendar.py --fetch-covers                            # match new rows on AniList, measure covers
python3 build_calendar.py --new-year 2027                           # roll over to a new year
```

## Publishing

Every push to `main` runs CI (`.github/workflows/ci.yml`). When it passes, the committed
`anime-calendar-2026.html` is deployed to GitHub Pages as `index.html`, so merging a data
update is all it takes to publish it. The page computes "now" in the viewer's browser, so
it stays current between updates. A failing check blocks the deploy and leaves the last
good version live.

## Workbook columns

The required columns are listed in `REQUIRED_COLS` in `build_calendar.py`. The ones that
shape the schedule:

| Column | Meaning |
|---|---|
| `Schedule` | `Fri · Oct 2` premiere date, `Saturdays` open weekly slot, `Fall 2026` no date yet, `Released Jun 19` past one-off, `All at once · Nov 26` batch drop |
| `Time (ET)` | Release time as a US Eastern **summer** (EDT) reference; blank for time TBA |
| `US-anchored` | `yes` when the release is pinned to a US clock (Netflix midnight Pacific) instead of Japan's |
| `Episodes`, `Count confirmed` | Run length; without a count a run is assumed to be 12 episodes and the last is a likely finale |
| `Explicit end` | Last release date; overrides the count |
| `Skip dates`, `Extra dates`, `Double dates` | Break weeks, off-cadence airings, two-episode releases (ISO dates) |
| `First episode` | Starting number for the second half of a split season |
| `Carryover` | `yes` for a series continuing from an earlier season |
| `Also on` | A second supported platform carrying the same show |
| `AniList ID` | The show's AniList entry (`anilist.co/anime/<id>`), for cover art and links; `none` if it isn't on AniList |

## Contributing a correction

Release times change often. If a release doesn't match what you see on the platform,
open an issue with the title, platform, and the date and time you saw it. Observed
releases outrank every other source (see `CLAUDE.md` §6).

## License

MIT. An unofficial fan reference, not affiliated with any streaming service or studio.
