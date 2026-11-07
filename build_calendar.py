#!/usr/bin/env python3
"""
build_calendar.py — build the self-contained anime release calendar from the xlsx data store.

Usage
-----
  python3 build_calendar.py
        Validate, then build anime-calendar-<year>.html from:
          data      anime-calendar-data.xlsx
          template  calendar-template.html

  python3 build_calendar.py --check
        Validate the workbook and report problems without writing anything.

  python3 build_calendar.py --today 2026-11-06 --out /tmp/page.html
        Pin "today" (the snapshot date for the no-JS fallback and the stamp in the page) so
        builds are reproducible in tests and CI.

  python3 build_calendar.py --dump-airings "Devils' Crest"
        Print every computed release for one title: ET time, UTC instant, episode, flags.

  python3 build_calendar.py --new-year 2027
        Roll over to a new season year: copies the workbook, keeps shows still running into
        the new year, resets the research cooldown, then builds.

  python3 build_calendar.py --news
        Scan Crunchyroll's news RSS for articles about tracked titles. Reports only.

How the schedule is modelled
----------------------------
The build owns every scheduling rule. For each row it computes the full list of releases
(date, exact instant, episode number(s), premiere / finale / batch flags) and embeds that
list in the page. The page only renders: it converts each instant to the viewer's time
zone and groups by local day. There is no second copy of the rules in JavaScript.

Instants. `Time (ET)` is a US Eastern *summer* (EDT) reference time. A row that follows
Japan's broadcast clock (the default) is therefore a fixed UTC instant every week — Japan
has no daylight saving — and moves one hour earlier on US clocks when DST ends. A row
marked `US-anchored` is a wall-clock time in America/New_York and does not move.

Requires: Python 3.9+ (zoneinfo) and openpyxl. On Windows also `pip install tzdata`.
The generated HTML is fully self-contained and still renders a snapshot with JavaScript off.
"""

import argparse
import codecs
import datetime
import html as _html
import json
import re
import shutil
import sys
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    sys.exit("Python 3.9+ is required (zoneinfo).")

try:
    from openpyxl import load_workbook
except ImportError:  # pragma: no cover
    sys.exit("openpyxl is required:  pip install openpyxl")

ET = ZoneInfo("America/New_York")
EDT = datetime.timezone(datetime.timedelta(hours=-4))
UTC = datetime.timezone.utc

MNAME = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTHS = {m: i + 1 for i, m in enumerate(MNAME)}
WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
WD_FULL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAYMAP = {}
for _i, _d in enumerate(WD):
    for _v in (_d, _d + "s", WD_FULL[_i], WD_FULL[_i] + "s"):
        DAYMAP[_v] = _d
UNDATED_RE = re.compile(
    r"^(Winter|Spring|Summer|Fall|Autumn|January|February|March|April|May|June|July|"
    r"August|September|October|November|December)\s+\d{4}$")
DATED_RE = re.compile(r"^([A-Za-z]{3,9})\s*·\s*([A-Za-z]{3})\s+(\d{1,2})$")
# One-off drops. "Released <Mon D>" reads right after the fact; "All at once · <Mon D>"
# reads right for a batch release still in the future. Both mean: one date, no weekly run.
ONCE_RE = re.compile(r"^(?:Released|All at once\s*·)\s*([A-Za-z]{3})\s+(\d{1,2})$")
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})\s*(AM|PM)$", re.I)
# A row that is the second half of a season. Its episodes may continue the first half's
# numbering, so the page shows no episode numbers unless "First episode" says where to start.
MID_COUR_RE = re.compile(r"\b(part\s*[2-9]|cour\s*[2-9]|continuing cour|sequel cour|final part)\b",
                         re.I)

# Supported platforms, in display order, with the CSS variable holding each validated colour.
PLATFORMS = ["Crunchyroll", "HIDIVE", "Netflix", "Hulu", "Prime Video", "Disney+", "TBA"]
PLAT_VAR = {"Crunchyroll": "--cr", "HIDIVE": "--hidive", "Netflix": "--netflix", "Hulu": "--hulu",
            "Prime Video": "--prime", "Disney+": "--disney", "TBA": "--tba"}
PLAT_SHORT = {"Crunchyroll": "Crunchyroll", "HIDIVE": "HIDIVE", "Netflix": "Netflix",
              "Hulu": "Hulu", "Prime Video": "Prime Video", "Disney+": "Disney+",
              "TBA": "Platform TBA"}

DEFAULT_EPISODES = 12          # assumed single-cour length when no count is announced

# Airing flags (bit field shared with the page).
F_PREMIERE, F_FINALE, F_EST, F_BATCH, F_RETURN, F_FILM, F_EXTRA = 1, 2, 4, 8, 16, 32, 64

REQUIRED_COLS = ["Title", "Platform", "Schedule", "Time (ET)", "US-anchored", "Type / Studio",
                 "Genres", "Episodes", "Count confirmed", "Explicit end", "Multi-day",
                 "Start ISO", "URL", "Note", "Caveat / likely", "Synopsis", "Last Checked"]
# Optional — absent in older workbooks, so missing is not an error.
#   Skip dates     ISO dates a weekly show does NOT air (recaps, breaks).
#   Extra dates    ISO dates it airs OUTSIDE its weekly slot (an early premiere).
#   Double dates   ISO dates two episodes release together (two-episode premieres).
#   First episode  episode number of the row's first release (default 1).
#   Carryover      yes = the show began in an earlier season (was Platform "Continuing").
#   Also on        other supported platforms carrying the same release, comma-separated.
# The research-cooldown columns are read too: they don't affect the page, but audit scripts
# that read intervals through read_rows() got None when they were left out.
OPTIONAL_COLS = ["Skip dates", "Extra dates", "Double dates", "First episode", "Carryover",
                 "Also on", "Time confirmed", "Check Interval (days)", "Why this interval"]


# ---------------------------------------------------------------- reading


def read_rows(path):
    wb = load_workbook(path, data_only=True)
    if "Shows" not in wb.sheetnames:
        sys.exit(f"{path}: no 'Shows' sheet found")
    ws = wb["Shows"]
    headers = [c.value for c in ws[1]]
    idx = {}
    for name in REQUIRED_COLS:
        if name not in headers:
            sys.exit(f"{path}: missing required column '{name}'")
        idx[name] = headers.index(name)
    for name in OPTIONAL_COLS:
        if name in headers:
            idx[name] = headers.index(name)

    def cell(row, name):
        if name not in idx or idx[name] >= len(row):
            return ""
        v = row[idx[name]]
        if v is None:
            return ""
        if isinstance(v, str):
            return v.strip()
        return v

    rows = []
    for raw in ws.iter_rows(min_row=2, values_only=True):
        if not raw or not raw[idx["Title"]]:
            continue
        rows.append({k: cell(raw, k) for k in REQUIRED_COLS + OPTIONAL_COLS})
    return rows


def yes(v):
    return str(v or "").strip().lower().startswith("y")


def parse_iso(v):
    if not v:
        return None
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    try:
        return datetime.date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def parse_dates(v):
    """'2026-09-23, 2026-10-07' -> ['2026-09-23', '2026-10-07'] (invalid parts dropped)."""
    out = []
    for part in str(v or "").replace(";", ",").split(","):
        d = parse_iso(part.strip())
        if d:
            out.append(d.isoformat())
    return out


parse_skips = parse_dates     # older name, kept for scripts that import it


def parse_time(v):
    """'9:30 AM' -> (9, 30); blank or unreadable -> None."""
    m = TIME_RE.match(str(v or "").strip())
    if not m:
        return None
    h, mi = int(m.group(1)) % 12, int(m.group(2))
    if m.group(3).upper() == "PM":
        h += 12
    return h, mi


def episodes_of(r):
    s = str(r["Episodes"]).strip()
    return int(s) if s else None


def first_episode(r):
    s = str(r.get("First episode") or "").strip()
    return int(float(s)) if s else None


def also_on(r):
    return [p.strip() for p in str(r.get("Also on") or "").split(",") if p.strip()]


def is_carryover(r):
    return yes(r.get("Carryover"))


def is_numbered(r):
    """Show episode numbers? Only when the row's numbering is known to start at First episode."""
    if first_episode(r):
        return True
    return not is_carryover(r) and not MID_COUR_RE.search(str(r["Type / Studio"]))


# ---------------------------------------------------------------- schedule model


def parse_when(r, year):
    """Classify a row's Schedule. Kinds: dated / once / weekly / multi / undated / unparsed."""
    d = str(r["Schedule"]).strip()
    if r["Multi-day"]:
        days = [x.strip() for x in str(r["Multi-day"]).split(",") if x.strip()]
        return {"kind": "multi", "days": days, "start": parse_iso(r["Start ISO"]), "wd": None}
    m = DATED_RE.match(d)
    if m:
        mon, day = m.group(2), int(m.group(3))
        if mon in MONTHS and 1 <= day <= 31:
            start = datetime.date(year, MONTHS[mon], day)
            film = bool(re.search(r"\bfilm\b", str(r["Type / Studio"]), re.I))
            return {"kind": "once" if film else "dated", "start": start, "film": film,
                    "wd": WD[start.weekday()], "declared": DAYMAP.get(m.group(1))}
    m = ONCE_RE.match(d)
    if m:
        mon, day = m.group(1), int(m.group(2))
        if mon in MONTHS and 1 <= day <= 31:
            start = datetime.date(year, MONTHS[mon], day)
            return {"kind": "once", "start": start, "wd": WD[start.weekday()], "film": False,
                    "batch": d.startswith("All at once")}
    if d in DAYMAP:
        return {"kind": "weekly", "start": None, "wd": DAYMAP[d]}
    if UNDATED_RE.match(d):
        return {"kind": "undated", "start": None, "wd": None}
    return {"kind": "unparsed", "start": None, "wd": None}


def instant(day, hm, us_anchored):
    """UTC datetime of a release on ET reference `day` at `hm`, or None when the time is TBA."""
    if not hm:
        return None
    t = datetime.time(hm[0], hm[1])
    tz = ET if us_anchored else EDT
    return datetime.datetime.combine(day, t, tzinfo=tz).astimezone(UTC)


def window(rows, year):
    """(first Monday shown, last day shown): from the earliest release through Dec 31."""
    starts = [w["start"] for w in (parse_when(r, year) for r in rows) if w.get("start")]
    first = min(starts) if starts else datetime.date(year, 1, 1)
    first -= datetime.timedelta(days=first.weekday())
    return first, datetime.date(year, 12, 31)


def releases(r, year, win_start=None, horizon=None):
    """Every release of one row, in order.

    Returns a list of dicts: {day (ET reference date), utc (datetime|None), a, b (episode
    range, 0 when unnumbered), flags}. Runs are generated until their end — explicit end,
    episode count, or (for open-ended carryover shows) the horizon.
    """
    w = parse_when(r, year)
    kind = w["kind"]
    if kind in ("undated", "unparsed"):
        return []
    horizon = horizon or datetime.date(year + 1, 3, 31)
    hm = parse_time(r["Time (ET)"])
    us = yes(r["US-anchored"])
    eps = episodes_of(r)
    end = parse_iso(r["Explicit end"])

    if kind == "once":
        flags = F_FILM if w.get("film") else 0
        if (eps and eps > 1) or w.get("batch"):
            flags |= F_BATCH
        return [{"day": w["start"], "utc": instant(w["start"], hm, us), "a": 0, "b": 0,
                 "flags": flags}]

    skips = set(parse_dates(r.get("Skip dates")))
    doubles = set(parse_dates(r.get("Double dates")))
    extras = sorted(parse_dates(r.get("Extra dates")))
    numbered = is_numbered(r)
    first_no = first_episode(r) or 1

    if kind == "weekly":                                   # open-ended, no premiere in window
        wd = WD.index(w["wd"])
        d = (win_start or datetime.date(year, 1, 1))
        d += datetime.timedelta(days=(wd - d.weekday()) % 7)
        out = []
        while d <= (end or horizon) and len(out) < 200:
            if d.isoformat() not in skips:
                out.append({"day": d, "utc": instant(d, hm, us), "a": 0, "b": 0, "flags": 0})
            d += datetime.timedelta(weeks=1)
        if end and out:
            out[-1]["flags"] |= F_FINALE
        return out

    start = w["start"]
    if not start:
        return []
    if kind == "multi":
        wdset = {WD.index(x) for x in w["days"] if x in WD}
    else:
        wdset = {start.weekday()}
    total = eps or (None if kind == "multi" else DEFAULT_EPISODES)
    confirmed = yes(r["Count confirmed"]) or bool(end)

    days = [parse_iso(x) for x in extras if parse_iso(x) < start]
    d = start
    while len(days) < 400 and d <= horizon:
        if d.weekday() in wdset and d.isoformat() not in skips:
            days.append(d)
        d += datetime.timedelta(days=1)
        if end and d > end:
            break

    out, n = [], 0
    for d in days:
        if end and d > end:
            break
        if not end and total is not None and n >= total:
            break
        k = 2 if d.isoformat() in doubles else 1
        a = first_no + n
        flags = F_EXTRA if d.isoformat() in extras else 0
        out.append({"day": d, "utc": instant(d, hm, us),
                    "a": a if numbered else 0, "b": (a + k - 1) if numbered else 0,
                    "flags": flags})
        n += k
    if not out:
        return out
    out[0]["flags"] |= F_PREMIERE if first_no == 1 and not is_carryover(r) and numbered else F_RETURN
    ended = bool(end) or (total is not None and n >= total)
    if ended and len(out) > 1:
        out[-1]["flags"] |= F_FINALE | (0 if confirmed else F_EST)
    return out


def finale_of(r, w, year):
    """Date of the last release, or None for open-ended runs. Used by validation and rollover."""
    if w["kind"] in ("undated", "unparsed"):
        return None
    end = parse_iso(r["Explicit end"])
    if end and w["kind"] != "once":
        return end
    if w["kind"] == "weekly":
        return None
    rel = releases(r, year, horizon=datetime.date(year + 3, 12, 31))
    if not rel:
        return None
    if w["kind"] == "multi" and not episodes_of(r):
        return None
    return rel[-1]["day"]


def season_label(rows, year):
    """'Summer & Fall 2026' — the seasons holding at least 15% of the dated premieres."""
    names = ["Winter", "Spring", "Summer", "Fall"]
    count = [0, 0, 0, 0]
    for r in rows:
        w = parse_when(r, year)
        if w["kind"] in ("dated", "multi") and w.get("start") and not is_carryover(r):
            count[(w["start"].month - 1) // 3] += 1
    total = sum(count) or 1
    picked = [names[i] for i in range(4) if count[i] / total >= 0.15]
    if not picked:
        return str(year)
    return (" & ".join(picked) if len(picked) <= 2 else ", ".join(picked)) + f" {year}"


# ---------------------------------------------------------------- validation


def validate(rows, year):
    errors, warnings = [], []
    seen = {}
    dst_end = datetime.date(year, 11, 1)
    dst_end += datetime.timedelta(days=(6 - dst_end.weekday()) % 7)   # first Sunday of Nov
    for i, r in enumerate(rows, start=2):
        t = r["Title"]
        if t in seen:
            errors.append(f'row {i}: duplicate title "{t}" (also row {seen[t]})')
        else:
            seen[t] = i
        if r["Platform"] == "Continuing":
            errors.append(f'row {i} "{t}": Platform "Continuing" is retired — set the real '
                          f'platform and put yes in Carryover')
        elif r["Platform"] not in PLAT_VAR:
            errors.append(f'row {i} "{t}": unknown platform "{r["Platform"]}" '
                          f'(expected one of {", ".join(PLATFORMS)})')
        for p in also_on(r):
            if p not in PLAT_VAR or p == "TBA":
                errors.append(f'row {i} "{t}": Also on "{p}" is not a supported platform')
        w = parse_when(r, year)
        if w["kind"] == "unparsed":
            errors.append(f'row {i} "{t}": schedule "{r["Schedule"]}" not understood '
                          f'— it would never appear on the grid')
        if w["kind"] == "multi":
            if not w["start"]:
                errors.append(f'row {i} "{t}": Multi-day set but Start ISO missing/invalid')
            for d in w["days"]:
                if d not in WD:
                    errors.append(f'row {i} "{t}": unknown weekday "{d}" in Multi-day')
        if w["kind"] == "dated" and w.get("declared") and w["declared"] != w["wd"]:
            warnings.append(f'row {i} "{t}": listed as {w["declared"]} but '
                            f'{r["Schedule"]} falls on {w["wd"]} in {year}')
        if str(r["Time (ET)"]).strip() and not parse_time(r["Time (ET)"]):
            errors.append(f'row {i} "{t}": Time (ET) "{r["Time (ET)"]}" is not like "9:30 AM"')
        for col in ("Episodes", "First episode"):
            s = str(r.get(col) or "").strip()
            if s:
                try:
                    if int(float(s)) <= 0 or float(s) != int(float(s)):
                        raise ValueError
                except (TypeError, ValueError):
                    errors.append(f'row {i} "{t}": {col} must be a positive whole number')
        for col in ("Skip dates", "Extra dates", "Double dates"):
            raw = str(r.get(col) or "").strip()
            if raw and not parse_dates(raw):
                errors.append(f'row {i} "{t}": {col} "{raw}" could not be read')
        for iso in parse_dates(r.get("Skip dates")):
            d = parse_iso(iso)
            if w.get("wd") and WD[d.weekday()] != w["wd"]:
                warnings.append(f'row {i} "{t}": skip date {iso} is a {WD[d.weekday()]} '
                                f'but the show airs {w["wd"]}')
        for iso in parse_dates(r.get("Extra dates")):
            d = parse_iso(iso)
            if w.get("wd") and WD[d.weekday()] == w["wd"] and w.get("start") and d >= w["start"]:
                warnings.append(f'row {i} "{t}": extra date {iso} already falls on the '
                                f'regular {w["wd"]} cadence — remove it or it adds nothing')
            if w.get("start") and d > w["start"]:
                warnings.append(f'row {i} "{t}": extra date {iso} is after the run starts '
                                f'({w["start"].isoformat()}) — Extra dates is for off-cadence '
                                f'airings such as an early premiere')
        rel_days = {x["day"].isoformat() for x in releases(r, year)}
        for iso in parse_dates(r.get("Double dates")):
            if iso not in rel_days:
                warnings.append(f'row {i} "{t}": double date {iso} is not one of the show\'s '
                                f'release days, so it changes nothing')
        if r["Explicit end"] and not parse_iso(r["Explicit end"]):
            errors.append(f'row {i} "{t}": Explicit end "{r["Explicit end"]}" is not a date')
        # Long runs are the calendar's worst failure mode: a 2-cour show may split with a
        # months-long gap or take a recap week at the cour boundary. Both silently project
        # phantom episodes. Demand an explicit end, a skip date, or a deliberate cour note.
        n_eps = episodes_of(r) if str(r["Episodes"]).strip().isdigit() else 0
        if (n_eps and n_eps >= 22 and not r["Explicit end"] and not is_carryover(r)
                and not parse_dates(r.get("Skip dates"))
                and "cour" not in str(r["Caveat / likely"] or "").lower()):
            warnings.append(
                f'row {i} "{t}": {n_eps} episodes with no Explicit end and no Skip dates — '
                f'projects an unbroken run to {finale_of(r, w, year)}. Confirm whether the '
                f'cours are continuous, then note it in Caveat to silence this.')
        # Stored times are EDT references. A show that only STARTS after DST ends was
        # probably entered from an EST source, which would display an hour early.
        # (Devils' Crest: entered as 10:01 AM EST, would have displayed 9:01 AM.)
        if (w.get("start") and w["start"] >= dst_end and str(r["Time (ET)"] or "").strip()
                and not yes(r["US-anchored"])):
            warnings.append(
                f'row {i} "{t}": starts {w["start"]} (after DST ends {dst_end}) but is not '
                f'US-anchored, so the page will show {r["Time (ET)"]} one hour EARLIER. If that '
                f'time came from a post-DST (EST) source, mark the row US-anchored.')
        if is_carryover(r) and not r["Explicit end"] and not r["Last Checked"]:
            warnings.append(f'row {i} "{t}": Carryover with no end date and never checked — '
                            f'it will run on the grid forever')
    return errors, warnings


def check_formulas(path):
    """Every row's cooldown formulas must reference that same row.

    openpyxl's delete_rows() does not rewrite formula references, so removing a title
    leaves every later row computing its Next Check Due / Status from the row below it
    (Sgt. Frog on row 149 was reading Q152). Returns a list of warnings.
    """
    wb = load_workbook(path)  # formulas, not cached values
    ws = wb["Shows"]
    headers = [c.value for c in ws[1]]
    out = []
    for name in ("Next Check Due", "Status"):
        if name not in headers:
            continue
        ci = headers.index(name) + 1
        for r in range(2, ws.max_row + 1):
            if not ws.cell(r, 1).value:
                continue
            f = ws.cell(r, ci).value
            if not (isinstance(f, str) and f.startswith("=")):
                continue
            refs = {int(n) for n in re.findall(r"(?<![$\d])[A-Z]{1,2}(\d+)", f)}
            if refs and refs != {r}:
                out.append(f'row {r} "{ws.cell(r, 1).value}": {name} formula references row(s) '
                           f'{sorted(refs)} — rewrite it to point at row {r}')
    return out


# ---------------------------------------------------------------- payload


def slugify(title, taken):
    s = re.sub(r"[^a-z0-9]+", "-", title.lower())[:60].strip("-") or "show"
    base, n = s, 2
    while s in taken:
        s, n = f"{base}-{n}", n + 1
    taken.add(s)
    return s


def split_type(value):
    """'Sequel (S3) · donghua · LAN Studio' -> ('Sequel (S3), donghua', 'LAN Studio').

    The sheet's Type / Studio column joins the kind of release and the studio with ' · '.
    The page shows them as separate facts."""
    parts = [x.strip() for x in str(value or "").split("·") if x.strip()]
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return ", ".join(parts[:-1]), parts[-1]


def genre_list(value):
    """'Action · Sci-Fi' or 'Action, Sci-Fi' -> 'Action, Sci-Fi'."""
    parts = [x.strip() for x in re.split(r"[·,]", str(value or "")) if x.strip()]
    return ", ".join(parts) or None


def build_payload(rows, year, today):
    """Everything the page needs, as one JSON-able dict."""
    win_start, win_end = window(rows, year)
    shows, airs, taken = [], [], set()
    for i, r in enumerate(rows):
        w = parse_when(r, year)
        rel = releases(r, year, win_start)
        eps = episodes_of(r)
        fin = finale_of(r, w, year)
        s = {"i": slugify(r["Title"], taken), "t": r["Title"], "p": r["Platform"],
             "s": r["Synopsis"], "k": w["kind"]}
        kind, studio = split_type(r["Type / Studio"])
        opt = {"ty": kind, "st": studio, "g": genre_list(r["Genres"]), "al": also_on(r), "c": 1 if is_carryover(r) else 0, "u": r["URL"], "n": r["Note"],
               "e": eps, "ec": 1 if yes(r["Count confirmed"]) else 0,
               "tc": 1 if yes(r.get("Time confirmed")) else 0,
               "us": 1 if yes(r["US-anchored"]) else 0, "cv": r["Caveat / likely"],
               "nt": 1 if not parse_time(r["Time (ET)"]) else 0,
               "fin": fin.isoformat() if fin else None,
               "w": r["Schedule"] if w["kind"] == "undated" else None,
               "num": 1 if is_numbered(r) else 0}
        s.update({k: v for k, v in opt.items() if v})
        shows.append(s)
        for x in rel:
            when = int(x["utc"].timestamp() * 1000) if x["utc"] else x["day"].isoformat()
            airs.append([i, when, x["a"], x["b"], x["flags"]])
    return {
        "built": today.isoformat(), "year": year, "label": season_label(rows, year),
        "win": [win_start.isoformat(), win_end.isoformat()],
        "platforms": [p for p in PLATFORMS if any(r["Platform"] == p for r in rows)],
        "shows": shows, "airs": airs, "markers": build_markers(year),
    }


def build_markers(year):
    """Crunchyroll's seasonal-lineup announcements, per the observed cadence (2020, 2023-26)."""
    plan = [(datetime.date(year, 3, 24), f"Spring {year}", "Mar 31"),
            (datetime.date(year, 6, 17), f"Summer {year}", "Jun 24"),
            (datetime.date(year, 9, 18), f"Fall {year}", "Sep 25"),
            (datetime.date(year, 12, 14), f"Winter {year + 1}", "Dec 21")]
    return [{"date": d.isoformat(), "season": s, "sweepBy": b} for d, s, b in plan]


# ---------------------------------------------------------------- static fallback
# What renders when scripts are blocked (iOS Quick Look, sandboxed previewers): a snapshot of
# the build week in Eastern Time and the full show directory. The page replaces both with live
# versions in the viewer's time zone. Markup mirrors the page's renderers.


def esc(s):
    return _html.escape(str(s if s is not None else ""), quote=True)


def fmt_time(dt_et):
    h = dt_et.hour % 12 or 12
    return f"{h}:{dt_et.minute:02d} {'AM' if dt_et.hour < 12 else 'PM'}"


def hour_label(h):
    return f"{h % 12 or 12} {'AM' if h < 12 else 'PM'}"


def ep_label(a, b):
    if not a:
        return ""
    return f"Ep {a}" if a == b else f"Ep {a}–{b}"


def tags_html(flags, eps=None):
    out = []
    if flags & F_PREMIERE:
        out.append('<span class="tag tag-new">Premiere</span>')
    if flags & F_RETURN:
        out.append('<span class="tag tag-new">Returns</span>')
    if flags & F_FINALE:
        out.append('<span class="tag tag-end est">Likely finale</span>' if flags & F_EST
                   else '<span class="tag tag-end">Finale</span>')
    if flags & F_BATCH:
        out.append(f'<span class="tag tag-batch">All {eps} episodes</span>' if eps
                   else '<span class="tag tag-batch">All episodes</span>')
    if flags & F_FILM:
        out.append('<span class="tag tag-batch">Film</span>')
    return "".join(out)


def entry_html(show, x_time, a, b, flags, past=False):
    p = show["p"]
    pv = PLAT_VAR.get(p, "--tba")
    ep = ep_label(a, b)
    tm = x_time or "Time TBA"
    meta = "".join(filter(None, [
        f'<span class="ep-num">{esc(ep)}</span>' if ep else "",
        f'<span class="ep-plat">{esc(PLAT_SHORT.get(p, p))}</span>',
        tags_html(flags, show.get("e"))]))
    return (f'<li class="ep{" is-past" if past else ""}" style="--pc:var({pv})">'
            f'<a class="ep-btn" href="#show:{esc(show["i"])}">'
            f'<span class="ep-time{"" if x_time else " tba"}">{esc(tm)}</span>'
            f'<span class="ep-title">{esc(show["t"])}</span>'
            f'<span class="ep-meta">{meta}</span></a></li>')


def static_week(payload, today):
    """Hour-banded week grid for the build week, in Eastern Time."""
    mon = today - datetime.timedelta(days=today.weekday())
    days = [mon + datetime.timedelta(days=k) for k in range(7)]
    cells = {}   # (day_index, band) -> [html]
    bands = set()
    count = 0
    now_et = datetime.datetime.combine(today, datetime.time(0, 0), tzinfo=ET)
    for si, when, a, b, flags in payload["airs"]:
        show = payload["shows"][si]
        if isinstance(when, int):
            dt_et = datetime.datetime.fromtimestamp(when / 1000, UTC).astimezone(ET)
            day, band, tm = dt_et.date(), dt_et.hour, fmt_time(dt_et)
            key_t = dt_et.hour * 60 + dt_et.minute
        else:
            day, band, tm, key_t = datetime.date.fromisoformat(when), 99, None, 9999
        if not (days[0] <= day <= days[6]):
            continue
        k = (day - mon).days
        past = day < today
        cells.setdefault((k, band), []).append((key_t, show["t"], entry_html(show, tm, a, b, flags, past)))
        bands.add(band)
        count += 1
    bands = sorted(bands)
    rows = "".join(
        f'<div class="band-label" style="grid-row:{n + 2}">'
        f'{"Time TBA" if band == 99 else hour_label(band)}</div>'
        for n, band in enumerate(bands))
    cols = []
    for k, day in enumerate(days):
        is_today = day == today
        groups = []
        for n, band in enumerate(bands):
            items = sorted(cells.get((k, band), []))
            if not items:
                continue
            lbl = "Time TBA" if band == 99 else hour_label(band)
            groups.append(f'<div class="band" style="grid-row:{n + 2}"><h4 class="band-h">{lbl}</h4>'
                          f'<ol class="eps">{"".join(h for _, _, h in items)}</ol></div>')
        n_day = sum(len(cells.get((k, band), [])) for band in bands)
        cols.append(
            f'<section class="day{" is-today" if is_today else ""}" data-day="{day.isoformat()}" '
            f'aria-labelledby="d{k}">'
            f'<h3 class="day-h" id="d{k}"><span class="day-name">{WD[k]}</span> '
            f'<span class="day-date">{MNAME[day.month - 1]} {day.day}</span>'
            f'<span class="day-count">{n_day}</span></h3>'
            f'{"".join(groups) or "<p class=day-empty>No releases</p>"}</section>')
    head = (f'{MNAME[days[0].month - 1]} {days[0].day} – {MNAME[days[6].month - 1]} {days[6].day}, '
            f'{days[6].year}')
    return head, count, (f'<div class="week" style="--bands:{len(bands)}">'
                         f'<div class="band-labels" aria-hidden="true">{rows}</div>'
                         f'{"".join(cols)}</div>')


def show_status(payload, si, today):
    """('airing'|'upcoming'|'finished'|'tba', next release or None) as of `today` (ET date)."""
    rel = [x for x in payload["airs"] if x[0] == si]
    show = payload["shows"][si]
    if not rel:
        return "tba", None

    def day_of(when):
        if isinstance(when, int):
            return datetime.datetime.fromtimestamp(when / 1000, UTC).astimezone(ET).date()
        return datetime.date.fromisoformat(when)

    days = [day_of(x[1]) for x in rel]
    nxt = next((x for x, d in zip(rel, days) if d >= today), None)
    if days[0] > today:
        return "upcoming", nxt
    if nxt is None and (show.get("fin") or show["k"] == "once"):
        return "finished", None
    return ("airing", nxt) if nxt else ("finished", None)


STATUS_ORDER = [("airing", "Airing now"), ("upcoming", "Starting soon"),
                ("tba", "Date not announced"), ("finished", "Finished")]


def static_shows(payload, today):
    groups = {k: [] for k, _ in STATUS_ORDER}
    for si, show in enumerate(payload["shows"]):
        st, nxt = show_status(payload, si, today)
        groups[st].append((show["t"].lower(), row_html(payload, si, st, nxt)))
    out = []
    for key, label in STATUS_ORDER:
        if not groups[key]:
            continue
        items = "".join(h for _, h in sorted(groups[key]))
        out.append(f'<section class="dir-group" data-status="{key}"><h3 class="dir-h">{label} '
                   f'<span class="dir-count">{len(groups[key])}</span></h3>'
                   f'<ul class="dir">{items}</ul></section>')
    return "".join(out)


def row_html(payload, si, st, nxt):
    show = payload["shows"][si]
    pv = PLAT_VAR.get(show["p"], "--tba")
    if st == "tba":
        sched = show.get("w") or "Date not announced"
    elif nxt and isinstance(nxt[1], int):
        dt_et = datetime.datetime.fromtimestamp(nxt[1] / 1000, UTC).astimezone(ET)
        sched = f'Next {WD[dt_et.weekday()]} {MNAME[dt_et.month - 1]} {dt_et.day}, {fmt_time(dt_et)} ET'
    elif nxt:
        d = datetime.date.fromisoformat(nxt[1])
        sched = f'Next {WD[d.weekday()]} {MNAME[d.month - 1]} {d.day}, time TBA'
    elif st == "finished" and show.get("fin"):
        d = datetime.date.fromisoformat(show["fin"])
        sched = f'Ended {MNAME[d.month - 1]} {d.day}'
    else:
        sched = "Finished"
    sub = "".join(f'<span>{esc(x)}</span>' for x in (show.get("ty"), show.get("g")) if x)
    return (f'<li class="dir-row" id="show:{esc(show["i"])}" style="--pc:var({pv})">'
            f'<a class="dir-link" href="#show:{esc(show["i"])}">'
            f'<span class="dir-title">{esc(show["t"])}</span>'
            f'<span class="dir-sub">{sub}</span></a>'
            f'<span class="dir-plat">{esc(PLAT_SHORT.get(show["p"], show["p"]))}</span>'
            f'<span class="dir-when">{esc(sched)}</span></li>')


# ---------------------------------------------------------------- build


TOKENS = ["/*<<PAYLOAD>>*/", "<!--<<STATIC_WEEK>>-->", "<!--<<STATIC_WEEK_RANGE>>-->",
          "<!--<<STATIC_WEEK_COUNT>>-->", "<!--<<STATIC_SHOWS>>-->", "<!--<<LABEL>>-->",
          "<!--<<BUILT>>-->", "<!--<<BUILT_ISO>>-->", "<!--<<COUNT>>-->"]


def render(rows, template_text, year, today):
    payload = build_payload(rows, year, today)
    for token in TOKENS:
        if token not in template_text:
            sys.exit(f"template is missing the {token} placeholder")
    head, wcount, week_html = static_week(payload, today)
    built = f"{MNAME[today.month - 1]} {today.day}, {today.year}"
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    data = data.replace("</", "<\\/")      # never let a string close the <script> element
    out = (template_text
           .replace("/*<<PAYLOAD>>*/", f"const PAYLOAD = {data};")
           .replace("<!--<<STATIC_WEEK>>-->", week_html)
           .replace("<!--<<STATIC_WEEK_RANGE>>-->", esc(head))
           .replace("<!--<<STATIC_WEEK_COUNT>>-->", str(wcount))
           .replace("<!--<<STATIC_SHOWS>>-->", static_shows(payload, today))
           .replace("<!--<<LABEL>>-->", esc(payload["label"]))
           .replace("<!--<<BUILT>>-->", built)
           .replace("<!--<<BUILT_ISO>>-->", today.isoformat())
           .replace("<!--<<COUNT>>-->", str(len(rows))))
    return out, payload


def build(data_path, template_path, out_path, year, today):
    rows = read_rows(data_path)
    errors, warnings = validate(rows, year)
    for w in warnings:
        print(f"  warning: {w}")
    if errors:
        print(f"\n{len(errors)} error(s) found — nothing was written:")
        for e in errors:
            print(f"  ERROR: {e}")
        sys.exit(1)
    tpl = Path(template_path).read_text(encoding="utf-8")
    out, payload = render(rows, tpl, year, today)
    Path(out_path).write_text(out, encoding="utf-8")
    kinds = {}
    for r in rows:
        k = parse_when(r, year)["kind"]
        kinds[k] = kinds.get(k, 0) + 1
    print(f"\nBuilt {out_path}")
    print(f"  {len(rows)} titles · {len(payload['airs'])} releases · "
          f"{round(len(out) / 1024, 1)} KB · {payload['label']}")
    print(f"  schedule kinds: {kinds}")
    print("  self-contained: no external data file needed at runtime")


def dump_airings(rows, year, title):
    hits = [r for r in rows if title.lower() in r["Title"].lower()]
    if not hits:
        sys.exit(f'no title matches "{title}"')
    win_start, _ = window(rows, year)
    names = {F_PREMIERE: "premiere", F_FINALE: "finale", F_EST: "est", F_BATCH: "batch",
             F_RETURN: "returns", F_FILM: "film", F_EXTRA: "extra"}
    for r in hits:
        print(f"\n{r['Title']}  [{r['Platform']}]  {r['Schedule']}  {r['Time (ET)'] or 'time TBA'}"
              f"{'  US-anchored' if yes(r['US-anchored']) else ''}")
        for x in releases(r, year, win_start):
            et = x["utc"].astimezone(ET).strftime("%a %b %d %I:%M %p %Z") if x["utc"] else \
                x["day"].strftime("%a %b %d") + " (time TBA)"
            utc = x["utc"].strftime("%Y-%m-%dT%H:%MZ") if x["utc"] else ""
            fl = ",".join(v for k, v in names.items() if x["flags"] & k)
            print(f"  {et:<28} {utc:<18} {ep_label(x['a'], x['b']):<10} {fl}")


# ---------------------------------------------------------------- new year


def new_year(src_xlsx, target_year, today):
    src = Path(src_xlsx)
    dst = src.with_name(f"{src.stem}-{target_year}{src.suffix}")
    shutil.copy2(src, dst)

    wb = load_workbook(dst)
    ws = wb["Shows"]
    headers = [c.value for c in ws[1]]
    col = {n: headers.index(n) + 1 for n in headers if isinstance(n, str)}
    cutoff = datetime.date(target_year, 1, 1)

    rows = read_rows(src)
    keep_titles = set()
    for r in rows:
        w = parse_when(r, target_year - 1)
        fin = finale_of(r, w, target_year - 1)
        # carry over anything still running into the new year, plus anything not yet dated
        if fin is None or fin >= cutoff or w["kind"] in ("undated", "unparsed"):
            if w["kind"] != "once" or (w["start"] and w["start"] >= cutoff):
                keep_titles.add(r["Title"])

    removed = 0
    for row_i in range(ws.max_row, 1, -1):
        t = ws.cell(row=row_i, column=col["Title"]).value
        if t and t not in keep_titles:
            ws.delete_rows(row_i)
            removed += 1

    for row_i in range(2, ws.max_row + 1):
        if ws.cell(row=row_i, column=col["Title"]).value:
            ws.cell(row=row_i, column=col["Last Checked"]).value = today
            ws.cell(row=row_i, column=col["Last Checked"]).number_format = "yyyy-mm-dd"
            if "Carryover" in col:
                ws.cell(row=row_i, column=col["Carryover"]).value = "yes"
    ws["W1"] = today
    ws["W1"].number_format = "yyyy-mm-dd"
    wb.save(dst)

    kept = ws.max_row - 1
    print(f"Created {dst}")
    print(f"  carried over {kept} show(s) still running into {target_year}; dropped {removed} finished")
    print(f"  reset 'Last Checked' to {today} so the research cooldown restarts")
    print("  NOTE: rows were deleted — rewrite the S/T cooldown formulas (see CLAUDE.md §7)")
    return dst


# ---------------------------------------------------------------- news monitor
# Crunchyroll's news RSS is the one first-party feed that returns full article
# text, and CR carries the large majority of the calendar. This scans it for the
# two failure modes that silently corrupt the schedule and that no chart site
# publishes reliably: a run going on hiatus, and a finale landing earlier or
# later than the episode count implies. It REPORTS ONLY.

CR_NEWS_RSS = "https://cr-news-api-service.prd.crunchyrollsvc.com/v1/en-US/rss"

NEWS_SIGNALS = [
    ("HIATUS/DELAY", r"\b(hiatus|delayed|postpone[ds]?|pushed back|rescheduled|"
                     r"on (?:a )?break|will not air|skip(?:ping)? (?:a )?week)\b"),
    ("FINALE",       r"\b(final episode|finale|last episode|concludes?|comes to a close|"
                     r"wraps? up|final season)\b"),
    ("EP COUNT",     r"\b(\d{1,3})\s*(?:total\s*)?episodes?\b"),
    ("DATE/PREMIERE", r"\b(premieres?|debuts?|begins? streaming|will stream|"
                      r"streaming (?:on|from)|release date)\b"),
    ("NEW SEASON",   r"\b(season\s*\d|sequel|second season|third season|new season|"
                     r"announced for)\b"),
]

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_QUALIFIER_RE = re.compile(
    r"\s*(?:[-–—:]\s*)?\b(?:season|cour|part|stage|arc)\b\s*\d*\s*$", re.I)


def _norm(s):
    s = _TAG_RE.sub(" ", str(s or ""))
    s = re.sub(r"[^0-9a-z]+", " ", s.lower())
    return _WS_RE.sub(" ", s).strip()


def _core_title(title):
    t = str(title or "")
    prev = None
    while prev != t:
        prev = t
        t = _QUALIFIER_RE.sub("", t)
    return _norm(t)


def fetch_news(url=CR_NEWS_RSS, days=21, timeout=30):
    """Return [{title, link, published, text}] for items newer than `days`."""
    import urllib.request
    from email.utils import parsedate_to_datetime
    import xml.etree.ElementTree as ET_XML

    req = urllib.request.Request(url, headers={"User-Agent": "anime-calendar-build/2.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    raw = raw.lstrip(codecs.BOM_UTF8).lstrip()
    root = ET_XML.fromstring(raw)
    CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"
    cutoff = datetime.datetime.now(UTC) - datetime.timedelta(days=days)
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        body = it.findtext(CONTENT) or it.findtext("description") or ""
        when = None
        pd = it.findtext("pubDate")
        if pd:
            try:
                when = parsedate_to_datetime(pd)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=UTC)
            except (TypeError, ValueError):
                when = None
        if when and when < cutoff:
            continue
        items.append({"title": title, "link": link, "published": when,
                      "text": _norm(title + " " + body)})
    return items


def scan_news(rows, items):
    """Match feed items to calendar rows. Returns (hits, unmatched, skipped)."""
    # Word-boundary regex, not substring: a bare `in` test is how "Mao" once matched
    # "Maomao" inside another show's synopsis.
    matchers, skipped = [], []
    for r in rows:
        core = _core_title(r["Title"])
        if len(core) < 5:
            skipped.append(r["Title"])
            continue
        matchers.append((r, core, re.compile(r"\b" + re.escape(core) + r"\b")))
    hits, matched_items = {}, set()
    for idx, item in enumerate(items):
        for r, core, pat in matchers:
            if not pat.search(item["text"]):
                continue
            matched_items.add(idx)
            sigs = [(label, m.group(0)) for label, rx in NEWS_SIGNALS
                    for m in [re.search(rx, item["text"], re.I)] if m]
            hits.setdefault(r["Title"], []).append({"item": item, "signals": sigs})
    unmatched = [item for idx, item in enumerate(items) if idx not in matched_items and
                 re.search(r"\b(anime|season|episode|premiere|simulcast|streaming)\b",
                           item["text"], re.I)]
    return hits, unmatched, skipped


def report_news(rows, days=21, url=CR_NEWS_RSS, show_unmatched=True):
    try:
        items = fetch_news(url, days=days)
    except Exception as e:                # network is optional; never break a build
        print(f"  news: could not fetch feed ({e.__class__.__name__}: {e})")
        return 1
    print(f"  fetched {len(items)} item(s) from the last {days} day(s)\n")
    hits, unmatched, skipped = scan_news(rows, items)

    def weight(entries):
        labels = {lb for e in entries for lb, _ in e["signals"]}
        return (("HIATUS/DELAY" in labels) * 2) + ("FINALE" in labels)

    if not hits:
        print("  no tracked titles mentioned in this window.")
    for title in sorted(hits, key=lambda t: -weight(hits[t])):
        entries = hits[title]
        labels = sorted({lb for e in entries for lb, _ in e["signals"]})
        flag = "  <-- REVIEW" if {"HIATUS/DELAY", "FINALE"} & set(labels) else ""
        print(f"  {title}{flag}")
        for e in entries:
            when = e["item"]["published"]
            when = when.strftime("%Y-%m-%d") if when else "?"
            tags = ", ".join(f"{lb}:{v}" for lb, v in e["signals"]) or "mention"
            print(f"      [{when}] {e['item']['title'][:76]}")
            print(f"              {tags}")
            if e["item"]["link"]:
                print(f"              {e['item']['link']}")
        print()
    if show_unmatched and unmatched:
        print(f"  {len(unmatched)} anime-related article(s) matched no tracked title "
              f"(possible additions):")
        for item in unmatched[:15]:
            when = item["published"]
            when = when.strftime("%Y-%m-%d") if when else "?"
            print(f"      [{when}] {item['title'][:84]}")
    if skipped:
        print(f"\n  not monitored (title too short to match safely): {', '.join(skipped)}")
    print("\n  Nothing was written. Confirm anything above before editing the workbook.")
    return 0


# ---------------------------------------------------------------- cli


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the anime release calendar from the xlsx data store.")
    ap.add_argument("--data", default="anime-calendar-data.xlsx", help="source workbook")
    ap.add_argument("--template", default="calendar-template.html", help="HTML template")
    ap.add_argument("--out", help="output HTML (default anime-calendar-<year>.html)")
    ap.add_argument("--year", type=int, help="season year (default: the --today year)")
    ap.add_argument("--today", type=datetime.date.fromisoformat, metavar="YYYY-MM-DD",
                    help="pin the build date (snapshot week and page stamp); default today")
    ap.add_argument("--new-year", type=int, metavar="YYYY",
                    help="roll the workbook over to a new year, then build it")
    ap.add_argument("--check", action="store_true", help="validate only; write nothing")
    ap.add_argument("--dump-airings", metavar="TITLE",
                    help="print every computed release for titles containing TITLE")
    ap.add_argument("--news", action="store_true",
                    help="scan Crunchyroll's news feed for schedule changes; reports only")
    ap.add_argument("--news-days", type=int, default=21, metavar="N",
                    help="how far back to scan with --news (default 21)")
    ap.add_argument("--news-url", default=CR_NEWS_RSS, help="override the news feed URL")
    a = ap.parse_args(argv)

    today = a.today or datetime.date.today()
    print(f"build_calendar.py — {today.isoformat()}")
    data = a.data
    year = a.year or today.year
    if a.new_year:
        year = a.new_year
        data = new_year(data, year, today)
    if not Path(data).exists():
        sys.exit(f"data file not found: {data}")

    if a.news:
        rows = read_rows(data)
        print(f"scanning news for {len(rows)} tracked titles\n")
        sys.exit(report_news(rows, days=a.news_days, url=a.news_url))
    if a.dump_airings:
        dump_airings(read_rows(data), year, a.dump_airings)
        return
    if a.check:
        rows = read_rows(data)
        errors, warnings = validate(rows, year)
        warnings += check_formulas(data)
        print(f"checked {len(rows)} rows for season year {year}")
        for w in warnings:
            print(f"  warning: {w}")
        for e in errors:
            print(f"  ERROR: {e}")
        print("OK — no errors" if not errors else f"{len(errors)} error(s)")
        sys.exit(1 if errors else 0)

    build(data, a.template, a.out or f"anime-calendar-{year}.html", year, today)


if __name__ == "__main__":
    main()
