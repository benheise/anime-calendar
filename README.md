# Anime Calendar

A self-contained HTML release calendar for simulcast anime on Crunchyroll, HIDIVE,
Netflix, Hulu, Prime Video and Disney+. It covers the Summer through Fall 2026 seasons,
ending December 31, 2026.

`anime-calendar-2026.html` is the finished page. It is a single flat file with no
external data, and it renders even where scripts are blocked (iOS Quick Look).

## Files

| File | Role |
|---|---|
| `anime-calendar-data.xlsx` | Source of record: one row per title, plus research-cooldown columns |
| `build_calendar.py` | Validates the workbook and builds the page |
| `calendar-template.html` | Page template (styles, platform colours, weekly-view logic) |
| `anime-calendar-2026.html` | Built output |
| `verify.js` | Headless (jsdom) check of the built page |
| `CLAUDE.md` | Operating notes: source hierarchy, DST rules, and lessons from past sweeps |

## Usage

```sh
pip install openpyxl
python3 build_calendar.py --check     # validate the workbook
python3 build_calendar.py             # rebuild anime-calendar-2026.html

npm install                           # once, for jsdom
node verify.js                        # execute the page and check placements
```

Other modes: `--news` scans Crunchyroll's news feed for changes to tracked titles, and
`--new-year YYYY` rolls the workbook over to a new season year.

Read `CLAUDE.md` before a sweep. Most of its rules exist because a specific error got through.
