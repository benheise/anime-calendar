#!/usr/bin/env python3
"""
build_calendar.py — rebuild the standalone anime calendar HTML from the xlsx data store.

Usage
-----
  python build_calendar.py
        Rebuild using the defaults:
          data     anime-calendar-data.xlsx
          template calendar-template.html
          output   anime-calendar-<year>.html

  python build_calendar.py --data other.xlsx --out mypage.html --year 2026

  python build_calendar.py --new-year 2027
        Roll over to a new season year:
          1. copies the workbook to anime-calendar-data-2027.xlsx
          2. keeps only shows still running into 2027, drops the finished ones
          3. resets every "Last Checked" to today so the research cooldown restarts
          4. builds anime-calendar-2027.html from the new copy

  python build_calendar.py --check
        Validate the workbook and report problems without writing anything.

  python build_calendar.py --news
        Scan Crunchyroll's news RSS for articles about tracked titles and flag
        schedule changes — hiatuses, finales, episode counts, premiere dates —
        plus anime articles matching nothing you track (possible additions).
        Reports only; it never edits the workbook. --news-days N widens the
        window (default 21). Requires network access to crunchyrollsvc.com.

Requires: Python 3.8+ and openpyxl.  No Node, no network, no other files at runtime —
the generated HTML is fully self-contained and works even with JavaScript disabled.
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
    from openpyxl import load_workbook
except ImportError:
    sys.exit("openpyxl is required:  pip install openpyxl")

MNAME = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
# 1-indexed to match datetime.date(). JS Date() is 0-indexed, so anything emitted into
# JS subtracts 1 (see build_markers) — mixing the two conventions is an easy silent bug.
MONTHS = {m: i + 1 for i, m in enumerate(MNAME)}
WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAYMAP = {}
for _i, _d in enumerate(WD):
    for _v in (_d, _d + "s", _d + "day", _d + "days"):
        DAYMAP[_v] = _d
DAYMAP.update({"Tuesday": "Tue", "Tuesdays": "Tue", "Wednesday": "Wed", "Wednesdays": "Wed",
               "Thursday": "Thu", "Thursdays": "Thu", "Saturday": "Sat", "Saturdays": "Sat",
               "Sunday": "Sun", "Sundays": "Sun"})
UNDATED_RE = re.compile(
    r"^(Winter|Spring|Summer|Fall|Autumn|January|February|March|April|May|June|July|"
    r"August|September|October|November|December)\s+\d{4}$")
DATED_RE = re.compile(r"^([A-Za-z]{3,9})\s*·\s*([A-Za-z]{3})\s+(\d{1,2})$")
# One-off drops. "Released <Mon D>" reads right after the fact; "All at once · <Mon D>"
# reads right for a batch release still in the future. Both mean: one date, no weekly run.
ONCE_RE = re.compile(r"^(?:Released|All at once\s*·)\s*([A-Za-z]{3})\s+(\d{1,2})$")

PLAT_VAR = {"Crunchyroll": "--cr", "HIDIVE": "--hidive", "Netflix": "--netflix",
            "Hulu": "--hulu", "Prime Video": "--prime", "Disney+": "--disney", "TBA": "--tba", "Continuing": "--cont"}
TAB_ORDER = ["All", "Crunchyroll", "HIDIVE", "Netflix", "Hulu", "Prime Video", "Disney+", "TBA", "Continuing"]

# Column headers -> index, resolved by name so re-ordering the sheet cannot silently
# shift the wrong values into the wrong fields.
REQUIRED_COLS = ["Title", "Platform", "Schedule", "Time (ET)", "US-anchored", "Type / Studio",
                 "Genres", "Episodes", "Count confirmed", "Explicit end", "Multi-day",
                 "Start ISO", "URL", "Note", "Caveat / likely", "Synopsis", "Last Checked"]
# Optional — absent in older workbooks, so missing is not an error.
# "Skip dates": comma-separated ISO dates a weekly show does NOT air (broadcast
# breaks). Common enough in practice that modelling a run as unbroken weeks
# puts phantom episodes on the grid.
# The research-cooldown columns live here too. They do not affect the built page, but
# leaving them out of read_rows() silently handed None to every audit script that asked
# for an interval, so overdue reports were computed against a flat 30-day default
# instead of each row's real cadence.
OPTIONAL_COLS = ["Skip dates", "Extra dates", "Time confirmed",
                 "Check Interval (days)", "Why this interval"]


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


# ---------------------------------------------------------------- schedule model
# Mirrors parseWhen() in the page so the build and the page agree on what a
# schedule string means. Kinds: dated / once / weekly / undated / multi / unparsed.


def parse_when(r, year):
    d = str(r["Schedule"]).strip()
    if r["Multi-day"]:
        days = [x.strip() for x in str(r["Multi-day"]).split(",") if x.strip()]
        start = parse_iso(r["Start ISO"])
        return {"kind": "multi", "days": days, "start": start, "wd": None}
    m = DATED_RE.match(d)
    if m:
        mon, day = m.group(2), int(m.group(3))
        if mon in MONTHS and 1 <= day <= 31:
            start = datetime.date(year, MONTHS[mon], day)
            once = bool(re.search(r"\bfilm\b", str(r["Type / Studio"]), re.I))
            return {"kind": "once" if once else "dated", "start": start,
                    "wd": WD[start.weekday()], "declared": DAYMAP.get(m.group(1))}
    m = ONCE_RE.match(d)
    if m:
        mon, day = m.group(1), int(m.group(2))
        if mon in MONTHS and 1 <= day <= 31:
            start = datetime.date(year, MONTHS[mon], day)
            return {"kind": "once", "start": start, "wd": WD[start.weekday()]}
    if d in DAYMAP:
        return {"kind": "weekly", "start": None, "wd": DAYMAP[d]}
    if UNDATED_RE.match(d):
        return {"kind": "undated", "start": None, "wd": None}
    return {"kind": "unparsed", "start": None, "wd": None}


def parse_skips(v):
    """'2026-09-23, 2026-10-07' -> ['2026-09-23', '2026-10-07'] (validated)."""
    out = []
    for part in str(v or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        d = parse_iso(part)
        if d:
            out.append(d.isoformat())
    return out


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


def finale_of(r, w, year):
    """Same rule the page uses: explicit end wins, else premiere + (eps-1) weeks."""
    end = parse_iso(r["Explicit end"])
    if end:
        return end
    if r["Platform"] == "Continuing":
        return None
    if w["kind"] == "once":
        return w["start"]
    if w["kind"] == "multi":
        return None
    if w["start"]:
        eps = int(r["Episodes"]) if str(r["Episodes"]).strip() else 12
        extras = parse_skips(r.get("Extra dates"))
        skips = set(parse_skips(r.get("Skip dates")))
        # Episodes delivered off-cadence come out of the weekly run's total;
        # skipped weeks push the finale later. Mirrors runFinale() in the page.
        remaining = eps - len(extras)
        if remaining <= 0:
            return max(datetime.date.fromisoformat(e) for e in extras) if extras else w["start"]
        d, aired = w["start"], 0
        for _ in range(520):            # bound: no run spans 10 years of weeks
            if d.isoformat() not in skips:
                aired += 1
                if aired == remaining:
                    return d
            d += datetime.timedelta(weeks=1)
    return None


# ---------------------------------------------------------------- validation


def validate(rows, year):
    errors, warnings = [], []
    seen = {}
    for i, r in enumerate(rows, start=2):
        t = r["Title"]
        if t in seen:
            errors.append(f'row {i}: duplicate title "{t}" (also row {seen[t]})')
        else:
            seen[t] = i
        if r["Platform"] not in PLAT_VAR:
            errors.append(f'row {i} "{t}": unknown platform "{r["Platform"]}" '
                          f'(expected one of {", ".join(PLAT_VAR)})')
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
        if str(r["Episodes"]).strip():
            try:
                if int(r["Episodes"]) <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                errors.append(f'row {i} "{t}": Episodes must be a positive whole number')
        for iso in parse_skips(r.get("Skip dates")):
            d = parse_iso(iso)
            if w.get("wd") and WD[d.weekday()] != w["wd"]:
                warnings.append(f'row {i} "{t}": skip date {iso} is a {WD[d.weekday()]} '
                                f'but the show airs {w["wd"]}')
        if str(r.get("Skip dates") or "").strip() and not parse_skips(r.get("Skip dates")):
            errors.append(f'row {i} "{t}": Skip dates "{r["Skip dates"]}" could not be read')
        extras = parse_skips(r.get("Extra dates"))
        if str(r.get("Extra dates") or "").strip() and not extras:
            errors.append(f'row {i} "{t}": Extra dates "{r["Extra dates"]}" could not be read')
        for iso in extras:
            d = parse_iso(iso)
            # An extra date on the show's own weekday inside its run is already
            # covered by the weekly cadence, so it would double-list the title.
            if w.get("wd") and WD[d.weekday()] == w["wd"] and w.get("start") and d >= w["start"]:
                warnings.append(f'row {i} "{t}": extra date {iso} already falls on the '
                                f'regular {w["wd"]} cadence — remove it or it adds nothing')
            if w.get("start") and d > w["start"]:
                warnings.append(f'row {i} "{t}": extra date {iso} is after the run starts '
                                f'({w["start"].isoformat()}) — Extra dates is for off-cadence '
                                f'airings such as an early premiere')
        if r["Explicit end"] and not parse_iso(r["Explicit end"]):
            errors.append(f'row {i} "{t}": Explicit end "{r["Explicit end"]}" is not a date')
        # Long runs are the calendar's worst failure mode. A 2-cour show is NOT reliably
        # an unbroken weekly sequence: it may split with a months-long gap between cours
        # (Slime S4 cour 2 ended Sep 25, cour 3 is July 2027) or take a recap week at the
        # cour boundary (Sorry About My Little Brothers skipped Sep 25). Both silently
        # project phantom episodes. Demand an explicit end or a deliberate skip/no-split note.
        try:
            n_eps = int(r["Episodes"]) if str(r["Episodes"]).strip() else 0
        except (TypeError, ValueError):
            n_eps = 0
        if (n_eps >= 22 and not r["Explicit end"] and r["Platform"] != "Continuing"
                and not parse_skips(r.get("Skip dates"))
                and "cour" not in str(r["Caveat / likely"] or "").lower()):
            warnings.append(
                f'row {i} "{t}": {n_eps} episodes with no Explicit end and no Skip dates — '
                f'projects an unbroken run to {finale_of(r, w, year)}. Confirm whether the '
                f'cours are continuous, then note it in Caveat to silence this.')
        # Stored times are EDT references: the page subtracts an hour for any row not marked
        # US-anchored once DST ends. A show that only STARTS after that date was almost
        # certainly entered from an EST source, so the page would shift it an extra hour.
        # (Demons' Crest: entered as 10:01 AM EST, displayed 9:01 AM.)
        dst_end = datetime.date(year, 11, 1)
        dst_end += datetime.timedelta(days=(6 - dst_end.weekday()) % 7)   # first Sunday of Nov
        if (w.get("start") and w["start"] >= dst_end and str(r["Time (ET)"] or "").strip()
                and not str(r["US-anchored"] or "").lower().startswith("y")):
            warnings.append(
                f'row {i} "{t}": starts {w["start"]} (after DST ends {dst_end}) but is not '
                f'US-anchored, so the page will show {r["Time (ET)"]} one hour EARLIER. If that time '
                f'came from a post-DST (EST) source, mark the row US-anchored.')
        if r["Platform"] == "Continuing" and not r["Explicit end"] and not r["Last Checked"]:
            warnings.append(f'row {i} "{t}": Continuing with no end date and never checked — '
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


# ---------------------------------------------------------------- JS emission


def js(v):
    return json.dumps(v, ensure_ascii=False)


def build_data_js(rows, year):
    out = []
    for r in rows:
        w = parse_when(r, year)
        o = [f't:{js(r["Title"])}', f'u:{js(r["URL"])}', f'p:{js(r["Platform"])}',
             f'd:{js(r["Schedule"])}', f'ti:{js(str(r["Time (ET)"]))}',
             f'ty:{js(r["Type / Studio"])}', f'g:{js(r["Genres"])}']
        if str(r["US-anchored"]).lower().startswith("y"):
            o.append("us:1")
        if w["kind"] == "multi":
            o.append(f'days:{js(w["days"])}')
            o.append(f'startISO:{js(w["start"].isoformat())}')
        skips = parse_skips(r.get("Skip dates"))
        if skips:
            o.append(f'skip:{js(skips)}')
        extras = parse_skips(r.get("Extra dates"))
        if extras:
            o.append(f'add:{js(extras)}')
        if r["Note"]:
            o.append(f'note:{js(r["Note"])}')
        if r["Caveat / likely"]:
            o.append(f'likely:{js(r["Caveat / likely"])}')
        o.append(f'syn:{js(r["Synopsis"])}')
        out.append(" {" + ",".join(o) + "}")
    return "const DATA = [\n" + ",\n".join(out) + "\n];"


def build_ep_js(rows):
    out = []
    for r in rows:
        parts = []
        if str(r["Episodes"]).strip():
            parts.append(f'ep:{int(r["Episodes"])}')
        if str(r["Count confirmed"]).lower().startswith("y"):
            parts.append("ec:1")
        end = parse_iso(r["Explicit end"])
        if end:
            parts.append(f'end:{js(end.isoformat())}')
        if parts:
            out.append(f'  {js(r["Title"])}:{{{",".join(parts)}}},')
    return "const EP = {\n" + "\n".join(out) + "\n};"


# ---------------------------------------------------------------- static fallback
# Mirrors card() in the page. This is what renders when scripts are blocked
# (iOS Quick Look, sandboxed previewers); JS replaces it with identical markup.


def esc(s):
    return _html.escape(str(s if s is not None else ""), quote=True)


def build_cards(rows, year, today):
    out = []
    for r in rows:
        w = parse_when(r, year)
        fin = finale_of(r, w, year)
        pc = f'var({PLAT_VAR.get(r["Platform"], "--tba")})'
        title = (f'<a href="{esc(r["URL"])}" target="_blank" rel="noopener">{esc(r["Title"])}</a>'
                 if r["URL"] else esc(r["Title"]))
        plat_label = "PRIME" if r["Platform"] == "Prime Video" else r["Platform"].upper()
        time_chip = (f'<span class="time">{esc(r["Time (ET)"])} ET</span>'
                     if r["Time (ET)"] else '<span class="time tba">TBA</span>')
        tag_bits = ' <span class="sep">/</span> '.join(
            esc(x) for x in [r["Type / Studio"], r["Genres"]] if x)
        run = ""
        eps = str(r["Episodes"]).strip()
        confirmed = str(r["Count confirmed"]).lower().startswith("y")
        if eps:
            ends = f"{MNAME[fin.month - 1]} {fin.day}" if fin else ""
            tilde = "" if confirmed else "~"
            est = "" if confirmed else " est."
            if ends:
                tail = (f" · ended {ends} — complete" if fin and fin < today
                        else f" · ends {tilde}{ends}")
            else:
                tail = ""
            run = f'<div class="runline">{tilde}{eps} eps{est}{tail}</div>'
        elif r["Platform"] == "Continuing":
            if fin:
                run = (f'<div class="runline">ended {MNAME[fin.month - 1]} {fin.day} '
                       f'— season complete</div>' if fin < today else
                       f'<div class="runline">ongoing · ends ~{MNAME[fin.month - 1]} {fin.day}</div>')
            else:
                run = '<div class="runline">ongoing</div>'
        note = f'<div><span class="badge">{esc(r["Note"])}</span></div>' if r["Note"] else ""
        likely = (f'<div class="tagline" style="color:var(--faint)">{esc(r["Caveat / likely"])}</div>'
                  if r["Caveat / likely"] else "")
        search = esc(f'{r["Title"]} {r["Type / Studio"]} {r["Genres"]}'.lower())
        out.append(
            f'<article class="card" style="--pc:{pc}" data-plat="{esc(r["Platform"])}" '
            f'data-search="{search}">\n'
            f'    <div class="chips">\n'
            f'      <span class="plat" style="background:{pc}">{esc(plat_label)}</span>\n'
            f'      <span class="when"><b>{esc(r["Schedule"])}</b></span>\n'
            f'      {time_chip}\n'
            f'    </div>\n'
            f'    <h3>{title}</h3>\n'
            f'    <div class="tagline">{tag_bits}</div>\n'
            f'    {run}\n'
            f'    {note}\n'
            f'    <p class="syn clamp">{esc(r["Synopsis"])}</p>\n'
            f'    <button class="more" type="button">Read more</button>\n'
            f'    {likely}\n'
            f'  </article>')
    return "\n".join(out)


def build_tabs(rows):
    counts = {t: 0 for t in TAB_ORDER}
    for r in rows:
        counts[r["Platform"]] = counts.get(r["Platform"], 0) + 1
        counts["All"] += 1
    out = []
    for i, name in enumerate(TAB_ORDER):
        if name != "All" and not counts.get(name):
            continue
        on = " on" if name == "All" else ""
        dot = "" if name == "All" else \
            f'<span class="tdot" style="background:var({PLAT_VAR[name]})"></span>'
        out.append(f'<button class="tab{on}" role="tab" aria-selected="{"true" if name=="All" else "false"}" '
                   f'tabindex="{0 if name=="All" else -1}" data-plat="{esc(name)}">'
                   f'{dot}{esc(name)}<span class="tnum">{counts.get(name,0)}</span></button>')
    return "".join(out), counts["All"]


def build_markers(year):
    """Crunchyroll's seasonal-lineup announcements, per the observed cadence."""
    plan = [(datetime.date(year, 9, 18), f"Fall {year}", "Sep 25"),
            (datetime.date(year, 12, 14), f"Winter {year+1}", "Dec 21"),
            (datetime.date(year, 3, 24), f"Spring {year}", "Mar 31"),
            (datetime.date(year, 6, 17), f"Summer {year}", "Jun 24")]
    items = [f'  {{date:new Date({d.year},{d.month-1},{d.day}), season:{js(s)}, sweepBy:{js(b)}}}'
             for d, s, b in sorted(plan)]
    return "[\n" + ",\n".join(items) + "\n]"


# ---------------------------------------------------------------- build


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
    for token in ["/*<<DATA>>*/", "/*<<EP>>*/", "<!--<<CARDS>>-->", "<!--<<TABS>>-->",
                  "/*<<YEAR>>*/", "/*<<MARKERS>>*/", "<!--<<COUNT>>-->"]:
        if token not in tpl:
            sys.exit(f"template is missing the {token} placeholder")

    tabs_html, total = build_tabs(rows)
    out = (tpl
           .replace("/*<<DATA>>*/", build_data_js(rows, year))
           .replace("/*<<EP>>*/", build_ep_js(rows))
           .replace("<!--<<CARDS>>-->", build_cards(rows, year, today))
           .replace("<!--<<TABS>>-->", tabs_html)
           .replace("/*<<YEAR>>*/", str(year))
           .replace("/*<<MARKERS>>*/", build_markers(year))
           .replace("<!--<<COUNT>>-->", str(total)))

    Path(out_path).write_text(out, encoding="utf-8")
    kinds = {}
    for r in rows:
        k = parse_when(r, year)["kind"]
        kinds[k] = kinds.get(k, 0) + 1
    print(f"\nBuilt {out_path}")
    print(f"  {total} titles · {round(len(out)/1024,1)} KB · season year {year}")
    print(f"  schedule kinds: {kinds}")
    print("  self-contained: no external data file needed at runtime")


# ---------------------------------------------------------------- new year


def new_year(src_xlsx, target_year, today):
    src = Path(src_xlsx)
    dst = src.with_name(f"{src.stem}-{target_year}{src.suffix}")
    shutil.copy2(src, dst)

    wb = load_workbook(dst)
    ws = wb["Shows"]
    headers = [c.value for c in ws[1]]
    col = {n: headers.index(n) + 1 for n in headers if n}
    cutoff = datetime.date(target_year, 1, 1)

    rows = read_rows(src)
    keep_titles = set()
    for r in rows:
        w = parse_when(r, target_year - 1)
        fin = finale_of(r, w, target_year - 1)
        # carry over anything still running into the new year, plus anything not yet dated
        if fin is None or fin >= cutoff or w["kind"] in ("undated", "unparsed"):
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
    if "W" in [c for c in ("W",)]:
        ws["W1"] = today
        ws["W1"].number_format = "yyyy-mm-dd"
    wb.save(dst)

    kept = ws.max_row - 1
    print(f"Created {dst}")
    print(f"  carried over {kept} show(s) still running into {target_year}; dropped {removed} finished")
    print(f"  reset 'Last Checked' to {today} so the research cooldown restarts")
    return dst


# ---------------------------------------------------------------- news monitor
# Crunchyroll's news RSS is the one first-party feed that returns full article
# text, and CR carries the large majority of the calendar. This scans it for the
# two failure modes that silently corrupt the schedule and that no chart site
# publishes reliably: a run going on hiatus, and a finale landing earlier or
# later than the episode count implies.
#
# It REPORTS ONLY. Nothing here edits the workbook — every hit is a candidate for
# you to confirm, because a headline is not a schedule.

CR_NEWS_RSS = "https://cr-news-api-service.prd.crunchyrollsvc.com/v1/en-US/rss"

# (label, regex) — ordered roughly by how much a hit should worry you.
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
# strip trailing season/cour/part qualifiers so "X Season 3" still matches an
# article that just says "X"
_QUALIFIER_RE = re.compile(
    r"\s*(?:[-–—:]\s*)?\b(?:season|cour|part|stage|arc)\b\s*\d*\s*$", re.I)


def _norm(s):
    """Lowercase, punctuation to spaces, collapse whitespace."""
    s = _TAG_RE.sub(" ", str(s or ""))
    s = re.sub(r"[^0-9a-z]+", " ", s.lower())
    return _WS_RE.sub(" ", s).strip()


def _core_title(title):
    """'The Apothecary Diaries Season 3' -> 'the apothecary diaries'."""
    t = str(title or "")
    prev = None
    while prev != t:                      # strip repeated qualifiers
        prev = t
        t = _QUALIFIER_RE.sub("", t)
    return _norm(t)


def fetch_news(url=CR_NEWS_RSS, days=21, timeout=30):
    """Return [{title, link, published, text}] for items newer than `days`."""
    import urllib.request
    from email.utils import parsedate_to_datetime
    import xml.etree.ElementTree as ET

    req = urllib.request.Request(url, headers={"User-Agent": "anime-calendar-build/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    # An XML declaration must be the first thing in the document: a BOM or stray
    # leading whitespace makes ET raise "not at start of entity". Cheap to guard.
    raw = raw.lstrip(codecs.BOM_UTF8).lstrip()
    root = ET.fromstring(raw)
    CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)

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
                    when = when.replace(tzinfo=datetime.timezone.utc)
            except (TypeError, ValueError):
                when = None
        if when and when < cutoff:
            continue
        items.append({"title": title, "link": link, "published": when,
                      "text": _norm(title + " " + body)})
    return items


def scan_news(rows, items):
    """Match feed items to calendar rows. Returns (hits, unmatched, skipped)."""
    # Build matchers. Word-boundary regex, not substring: a bare `in` test is how
    # "Mao" once matched "Maomao" inside another show's synopsis and corrupted it.
    matchers, skipped = [], []
    for r in rows:
        core = _core_title(r["Title"])
        if len(core) < 5:                 # too generic to match safely
            skipped.append(r["Title"])
            continue
        matchers.append((r, core, re.compile(r"\b" + re.escape(core) + r"\b")))

    hits = {}
    matched_items = set()
    for idx, item in enumerate(items):
        for r, core, pat in matchers:
            if not pat.search(item["text"]):
                continue
            matched_items.add(idx)
            sigs = []
            for label, rx in NEWS_SIGNALS:
                m = re.search(rx, item["text"], re.I)
                if m:
                    sigs.append((label, m.group(0)))
            hits.setdefault(r["Title"], []).append({"item": item, "signals": sigs})

    # Articles that look anime-ish but match nothing we track — possible additions.
    unmatched = []
    for idx, item in enumerate(items):
        if idx in matched_items:
            continue
        if re.search(r"\b(anime|season|episode|premiere|simulcast|streaming)\b",
                     item["text"], re.I):
            unmatched.append(item)
    return hits, unmatched, skipped


def report_news(rows, days=21, url=CR_NEWS_RSS, show_unmatched=True):
    try:
        items = fetch_news(url, days=days)
    except Exception as e:                # network is optional; never break a build
        print(f"  news: could not fetch feed ({e.__class__.__name__}: {e})")
        return 1
    print(f"  fetched {len(items)} item(s) from the last {days} day(s)\n")
    hits, unmatched, skipped = scan_news(rows, items)

    # Rank: hiatus/finale first, they are the ones that silently break the grid.
    def weight(entries):
        labels = {l for e in entries for l, _ in e["signals"]}
        return (("HIATUS/DELAY" in labels) * 2) + ("FINALE" in labels)

    if not hits:
        print("  no tracked titles mentioned in this window.")
    else:
        for title in sorted(hits, key=lambda t: -weight(hits[t])):
            entries = hits[title]
            labels = sorted({l for e in entries for l, _ in e["signals"]})
            flag = "  <-- REVIEW" if {"HIATUS/DELAY", "FINALE"} & set(labels) else ""
            print(f"  {title}{flag}")
            for e in entries:
                when = e["item"]["published"]
                when = when.strftime("%Y-%m-%d") if when else "?"
                tags = ", ".join(f"{l}:{v}" for l, v in e["signals"]) or "mention"
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
        print(f"\n  not monitored (title too short to match safely, would false-positive): "
              f"{', '.join(skipped)}")
    print("\n  Nothing was written. Confirm anything above before editing the workbook.")
    return 0


# ---------------------------------------------------------------- cli


def main():
    ap = argparse.ArgumentParser(description="Rebuild the anime calendar HTML from the xlsx data store.")
    ap.add_argument("--data", default="anime-calendar-data.xlsx", help="source workbook")
    ap.add_argument("--template", default="calendar-template.html", help="HTML template")
    ap.add_argument("--out", help="output HTML (default anime-calendar-<year>.html)")
    ap.add_argument("--year", type=int, help="season year (default: current year)")
    ap.add_argument("--new-year", type=int, metavar="YYYY",
                    help="roll the workbook over to a new year, then build it")
    ap.add_argument("--check", action="store_true", help="validate only; write nothing")
    ap.add_argument("--news", action="store_true",
                    help="scan Crunchyroll's news feed for schedule changes affecting "
                         "tracked titles; reports only, never edits")
    ap.add_argument("--news-days", type=int, default=21, metavar="N",
                    help="how far back to scan with --news (default 21)")
    ap.add_argument("--news-url", default=CR_NEWS_RSS, help="override the news feed URL")
    a = ap.parse_args()

    today = datetime.date.today()
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

    out = a.out or f"anime-calendar-{year}.html"
    build(data, a.template, out, year, today)


if __name__ == "__main__":
    main()
