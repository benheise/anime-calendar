"""Unit tests for build_calendar.py's schedule model, validation and rendering.

Run with:  python3 -m pytest -q
These use synthetic rows, so they don't break when the sheet's data changes. Checks that
depend on the live data (a specific show on a specific day) belong in verify.js.
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build_calendar as bc  # noqa: E402

Y = 2026
D = dt.date
UTC = dt.timezone.utc


def row(**kw):
    """A sheet row with every column present, overridden by keyword (spaces as underscores)."""
    r = {k: "" for k in bc.REQUIRED_COLS + bc.OPTIONAL_COLS}
    r.update({"Title": "Test Show", "Platform": "Crunchyroll", "Schedule": "Fri · Oct 2",
              "Time (ET)": "11:00 AM", "Type / Studio": "New series · Studio X",
              "Last Checked": "2026-11-06"})
    alias = {"Time_ET": "Time (ET)", "US_anchored": "US-anchored", "Multi_day": "Multi-day"}
    for k, v in kw.items():
        key = alias.get(k, k.replace("__", " / ").replace("_", " "))
        assert key in r, f"unknown column {key}"
        r[key] = v
    return r


def rel(r, **kw):
    return bc.releases(r, Y, **kw)


def flags(x):
    return {n for n, b in [("premiere", bc.F_PREMIERE), ("finale", bc.F_FINALE),
                           ("est", bc.F_EST), ("batch", bc.F_BATCH), ("returns", bc.F_RETURN),
                           ("film", bc.F_FILM), ("extra", bc.F_EXTRA)] if x["flags"] & b}


# ---------------------------------------------------------------- weekly runs

def test_default_run_is_twelve_weeks_with_likely_finale():
    out = rel(row())
    assert len(out) == 12
    assert out[0]["day"] == D(Y, 10, 2) and out[-1]["day"] == D(Y, 12, 18)
    assert [x["a"] for x in out] == list(range(1, 13))
    assert flags(out[0]) == {"premiere"}
    assert flags(out[-1]) == {"finale", "est"}


def test_confirmed_count_ends_without_estimate_flag():
    out = rel(row(Episodes=10, Count_confirmed="yes"))
    assert len(out) == 10
    assert flags(out[-1]) == {"finale"}


def test_skip_date_pushes_the_finale_a_week():
    out = rel(row(Episodes=12, Skip_dates="2026-10-30"))
    days = [x["day"] for x in out]
    assert D(Y, 10, 30) not in days
    assert out[-1]["day"] == D(Y, 12, 25) and out[-1]["a"] == 12
    assert out[4]["day"] == D(Y, 11, 6) and out[4]["a"] == 5   # numbering continues


def test_extra_date_is_an_early_premiere_counted_in_the_total():
    out = rel(row(Episodes=12, Extra_dates="2026-09-27"))
    assert out[0]["day"] == D(Y, 9, 27) and "extra" in flags(out[0]) and "premiere" in flags(out[0])
    assert len(out) == 12 and out[-1]["day"] == D(Y, 12, 11)


def test_double_episode_date_covers_two_episodes():
    out = rel(row(Episodes=12, Double_dates="2026-10-02"))
    assert (out[0]["a"], out[0]["b"]) == (1, 2)
    assert (out[1]["a"], out[1]["b"]) == (3, 3)
    assert len(out) == 11 and out[-1]["b"] == 12


def test_explicit_end_overrides_the_count():
    out = rel(row(Episodes=24, Explicit_end="2026-11-13"))
    assert out[-1]["day"] == D(Y, 11, 13)
    assert flags(out[-1]) == {"finale"}


def test_multi_day_cadence():
    r = row(Schedule="Tue & Fri", Multi_day="Tue, Fri", Start_ISO="2026-07-03",
            Episodes=6, Count_confirmed="yes")
    days = [x["day"] for x in rel(r)]
    assert days == [D(Y, 7, 3), D(Y, 7, 7), D(Y, 7, 10), D(Y, 7, 14), D(Y, 7, 17), D(Y, 7, 21)]


def test_multi_day_without_count_runs_to_explicit_end():
    r = row(Schedule="Tue & Fri", Multi_day="Tue, Fri", Start_ISO="2026-07-03",
            Explicit_end="2026-07-14")
    assert [x["day"] for x in rel(r)][-1] == D(Y, 7, 14)


# ---------------------------------------------------------------- one-off and batch drops

def test_all_at_once_is_a_batch_even_without_a_count():
    out = rel(row(Schedule="All at once · Nov 26", Time_ET="3:00 AM", US_anchored="yes"))
    assert len(out) == 1 and flags(out[0]) == {"batch"}


def test_released_single_episode_is_not_a_batch():
    out = rel(row(Schedule="Released Jun 19", Episodes=1))
    assert len(out) == 1 and flags(out[0]) == set()


def test_film_is_a_single_release():
    out = rel(row(Schedule="Fri · Oct 16", Type__Studio="Film · Studio X"))
    assert len(out) == 1 and flags(out[0]) == {"film"}


# ---------------------------------------------------------------- carryovers and numbering

def test_carryover_weekly_is_unnumbered_and_stops_at_its_end():
    r = row(Schedule="Saturdays", Carryover="yes", Type__Studio="Continuing series · TMS",
            Explicit_end="2026-09-26")
    out = rel(r, win_start=D(Y, 6, 15))
    assert out[0]["day"] == D(Y, 6, 20)
    assert all(x["a"] == 0 for x in out)
    assert out[-1]["day"] == D(Y, 9, 26) and "finale" in flags(out[-1])


def test_open_carryover_runs_to_the_horizon():
    r = row(Schedule="Sundays", Carryover="yes")
    out = rel(r, win_start=D(Y, 6, 15), horizon=D(Y, 8, 1))
    assert out[-1]["day"] == D(Y, 7, 26) and not flags(out[-1])


@pytest.mark.parametrize("kind", ["Sequel (Part 2) · Studio", "Continuing cour (sports) · S",
                                  "Sequel (Cour 2) · S", "Sequel (final part) · S"])
def test_second_half_of_a_season_hides_episode_numbers(kind):
    out = rel(row(Type__Studio=kind))
    assert all(x["a"] == 0 for x in out)
    assert "returns" in flags(out[0]) and "premiere" not in flags(out[0])


def test_first_episode_restores_numbering_for_a_second_half():
    out = rel(row(Type__Studio="Sequel (Part 2) · S", First_episode=13, Episodes=12))
    assert out[0]["a"] == 13 and out[-1]["a"] == 24
    assert "returns" in flags(out[0])


def test_sequel_season_is_numbered_from_one():
    out = rel(row(Type__Studio="Sequel (S2) · S"))
    assert out[0]["a"] == 1 and "premiere" in flags(out[0])


# ---------------------------------------------------------------- time zones

def test_unanchored_release_follows_japan_across_dst():
    """Stored times are EDT references; an unanchored row is a fixed UTC instant."""
    out = rel(row(Time_ET="12:00 PM"))
    before = next(x for x in out if x["day"] == D(Y, 10, 30))
    after = next(x for x in out if x["day"] == D(Y, 11, 6))
    assert before["utc"].time() == after["utc"].time() == dt.time(16, 0)
    assert after["utc"].astimezone(bc.ET).hour == 11        # 11:00 AM EST


def test_us_anchored_release_keeps_its_wall_clock():
    out = rel(row(Time_ET="7:00 AM", US_anchored="yes"))
    before = next(x for x in out if x["day"] == D(Y, 10, 30))
    after = next(x for x in out if x["day"] == D(Y, 11, 6))
    assert before["utc"].hour == 11 and after["utc"].hour == 12
    assert before["utc"].astimezone(bc.ET).hour == after["utc"].astimezone(bc.ET).hour == 7


def test_midnight_release_after_dst_lands_on_the_previous_evening():
    """12:00 AM EDT reference on a Friday is 11:00 PM EST Thursday once clocks fall back."""
    out = rel(row(Schedule="Fri · Nov 6", Time_ET="12:00 AM"))
    et = out[0]["utc"].astimezone(bc.ET)
    assert (et.date(), et.hour) == (D(Y, 11, 5), 23)


def test_time_tba_has_no_instant():
    out = rel(row(Time_ET=""))
    assert all(x["utc"] is None for x in out)


def test_static_week_places_releases_on_their_eastern_date():
    rows = [row(Schedule="Fri · Nov 6", Time_ET="12:00 AM", Episodes=1)]
    payload = bc.build_payload(rows, Y, D(Y, 11, 6))
    _, count, html = bc.static_week(payload, D(Y, 11, 6))
    assert count == 1
    thu = re.search(r'data-day="2026-11-05".*?</section>', html, re.S).group(0)
    assert "Test Show" in thu and "11:00 PM" in thu


# ---------------------------------------------------------------- parsing helpers

def test_parse_time():
    assert bc.parse_time("9:30 AM") == (9, 30)
    assert bc.parse_time("12:00 AM") == (0, 0)
    assert bc.parse_time("12:15 PM") == (12, 15)
    assert bc.parse_time("") is None and bc.parse_time("noon") is None


def test_split_type_and_genres():
    assert bc.split_type("New series · J.C.STAFF") == ("New series", "J.C.STAFF")
    assert bc.split_type("Sequel (S3) · donghua · LAN Studio") == ("Sequel (S3), donghua", "LAN Studio")
    assert bc.split_type("New series") == ("New series", None)
    assert bc.genre_list("Action · Sci-Fi · Super Power") == "Action, Sci-Fi, Super Power"
    assert bc.genre_list("") is None


def test_parse_when_kinds():
    assert bc.parse_when(row(Schedule="Saturdays"), Y)["kind"] == "weekly"
    assert bc.parse_when(row(Schedule="Fall 2026"), Y)["kind"] == "undated"
    assert bc.parse_when(row(Schedule="Released Jun 19"), Y)["kind"] == "once"
    assert bc.parse_when(row(Schedule="sometime"), Y)["kind"] == "unparsed"


def test_season_label():
    rows = [row(Title=f"S{i}", Schedule="Wed · Jul 8") for i in range(5)]
    rows += [row(Title=f"F{i}", Schedule="Fri · Oct 2") for i in range(5)]
    assert bc.season_label(rows, Y) == "Summer & Fall 2026"


# ---------------------------------------------------------------- validation

def errors_of(rows):
    return bc.validate(rows, Y)[0]


def warnings_of(rows):
    return bc.validate(rows, Y)[1]


def test_valid_row_passes():
    assert errors_of([row()]) == []


@pytest.mark.parametrize("kw, needle", [
    ({"Platform": "Continuing"}, "retired"),
    ({"Platform": "YouTube"}, "unknown platform"),
    ({"Also_on": "TBA"}, "Also on"),
    ({"Time_ET": "11am"}, "Time (ET)"),
    ({"Schedule": "soonish"}, "not understood"),
    ({"Episodes": "0"}, "positive whole number"),
    ({"Skip_dates": "next week"}, "could not be read"),
    ({"Explicit_end": "soon"}, "not a date"),
])
def test_validation_errors(kw, needle):
    errs = errors_of([row(**kw)])
    assert any(needle in e for e in errs), errs


def test_duplicate_titles_are_an_error():
    assert any("duplicate" in e for e in errors_of([row(), row()]))


def test_long_run_without_end_warns():
    assert any("Explicit end" in w for w in warnings_of([row(Episodes=24)]))
    assert not any("Explicit end" in w for w in warnings_of([row(Episodes=24, Caveat__likely="2 cours, continuous")]))


def test_post_dst_start_without_anchor_warns():
    ws = warnings_of([row(Schedule="Fri · Nov 6")])
    assert any("after DST ends" in w for w in ws)
    assert not any("after DST ends" in w for w in warnings_of([row(Schedule="Fri · Nov 6", US_anchored="yes")]))


def test_double_date_off_cadence_warns():
    assert any("double date" in w for w in warnings_of([row(Double_dates="2026-10-03")]))


def test_declared_weekday_mismatch_warns():
    assert any("falls on" in w for w in warnings_of([row(Schedule="Thu · Oct 2")]))


def test_formula_check_catches_shifted_references(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Shows"
    ws.append(["Title", "Last Checked", "Check Interval (days)", "Next Check Due", "Status"])
    ws.append(["Good", None, 7, "=IF(B2=\"\",\"\",B2+C2)", "=IF(D2=\"\",\"\",\"ok\")"])
    ws.append(["Shifted", None, 7, "=IF(B4=\"\",\"\",B4+C4)", "=IF(D3=\"\",\"\",\"ok\")"])
    p = tmp_path / "f.xlsx"
    wb.save(p)
    out = bc.check_formulas(p)
    assert len(out) == 1 and "Shifted" in out[0] and "row 3" in out[0]


# ---------------------------------------------------------------- rendering

def test_render_fills_every_placeholder_and_escapes_script_close():
    tpl = (ROOT / "calendar-template.html").read_text(encoding="utf-8")
    rows = [row(Synopsis="Ends with </script><b>x</b>"), row(Title="Other", Schedule="Fall 2026")]
    html, payload = bc.render(rows, tpl, Y, D(Y, 11, 6))
    for token in bc.TOKENS:
        assert token not in html
    assert "</script><b>" not in html
    m = re.search(r"const PAYLOAD = (\{.*?\});\n", html, re.S)
    data = json.loads(m.group(1))
    assert data["label"] == "Fall 2026"
    assert data["shows"][1]["w"] == "Fall 2026" and not any(a[0] == 1 for a in data["airs"])
    assert "Summer 2026 Anime Guide" not in html


def test_payload_release_encoding():
    payload = bc.build_payload([row(Time_ET=""), row(Title="Timed")], Y, D(Y, 11, 6))
    untimed = [a for a in payload["airs"] if a[0] == 0]
    timed = [a for a in payload["airs"] if a[0] == 1]
    assert isinstance(untimed[0][1], str) and untimed[0][1] == "2026-10-02"
    assert timed[0][1] == int(dt.datetime(Y, 10, 2, 15, 0, tzinfo=UTC).timestamp() * 1000)


def test_live_sheet_validates():
    """The checked-in sheet must build: no errors, and every row on a supported platform."""
    rows = bc.read_rows(ROOT / "anime-calendar-data.xlsx")
    errs, _ = bc.validate(rows, Y)
    assert errs == []
    assert bc.check_formulas(ROOT / "anime-calendar-data.xlsx") == []
