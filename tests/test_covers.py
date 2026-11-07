"""Tests for cover art: AniList matching, overlay (scrim) measurement, and build wiring.

No network: AniList responses are faked as plain dicts.
"""
import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build_calendar as bc  # noqa: E402
import covers  # noqa: E402
from test_build import row  # noqa: E402

WHITE, BLACK = (255, 255, 255), (0, 0, 0)


def band(h=60, w=40, fill=BLACK):
    return np.full((h, w, 3), fill, dtype=np.uint8)


def composite(a, rgb):
    return tuple(round(a * i + (1 - a) * c) for i, c in zip(covers.INK, rgb))


# ---------------------------------------------------------------- overlay maths

def test_pure_white_needs_the_strongest_overlay_and_still_passes_aa():
    a, worst = covers.scrim_for(band(fill=WHITE))
    assert 0.55 <= a <= 0.62
    assert worst >= 4.5
    assert covers.contrast(1.0, covers.luminance(composite(a, WHITE))) >= 4.5


def test_dark_cover_gets_the_floor():
    a, worst = covers.scrim_for(band(fill=(30, 30, 40)))
    assert a == pytest.approx(covers.SCRIM_FLOOR, abs=0.011)
    assert worst > 7


def test_one_bright_text_line_strip_drives_the_overlay():
    """A dark cover with a white band one text-line tall must be treated like a white cover."""
    img = band(h=66)
    img[30:34] = WHITE                       # ~5% of the cover's height, full width
    a_strip, _ = covers.scrim_for(img)
    a_white, _ = covers.scrim_for(band(fill=WHITE))
    assert a_strip == pytest.approx(a_white, abs=0.011)


def test_a_tiny_bright_speck_does_not_darken_the_whole_slot():
    img = band(h=66)
    img[30, 0] = WHITE                       # far under 2% of any strip
    a, _ = covers.scrim_for(img)
    assert a == pytest.approx(covers.SCRIM_FLOOR, abs=0.011)


def test_overlay_is_monotonic_in_brightness():
    alphas = [covers.scrim_for(band(fill=(v, v, v)))[0] for v in (40, 120, 180, 230, 255)]
    assert alphas == sorted(alphas)


def test_target_includes_the_margin():
    lim = covers.max_background_luminance()
    assert covers.contrast(1.0, lim) == pytest.approx(4.5 * covers.MARGIN, rel=1e-6)


# ---------------------------------------------------------------- matching

def media(mid, en=None, ro=None, syn=(), year=2026, fmt="TV"):
    return {"id": mid, "title": {"english": en, "romaji": ro}, "synonyms": list(syn),
            "format": fmt, "startDate": {"year": year}, "seasonYear": year}


def test_exact_title_scores_highest():
    good = media(1, en="Blue Box Season 2")
    other = media(2, en="Blue Box")
    assert covers.score("Blue Box Season 2", good, 2026, False, False) >= 1.0
    assert covers.score("Blue Box Season 2", other, 2026, False, False) < covers.ACCEPT


def test_wrong_season_is_penalised():
    s2 = media(1, en="Grand Blue Dreaming Season 2")
    assert covers.score("Grand Blue Dreaming Season 3", s2, 2026, False, False) < covers.ACCEPT


def test_synonym_match_counts_as_exact():
    m = media(1, en="Please Excuse My Younger Brothers", syn=["Sorry About My Little Brothers"])
    assert covers.score("Sorry About My Little Brothers", m, 2026, False, False) >= 1.0


def test_old_entry_for_a_new_show_is_penalised_but_not_for_a_carryover():
    old = media(1, en="Dreamland", year=2018, fmt="MOVIE")
    assert covers.score("Dreamland", old, 2026, False, False) < covers.ACCEPT
    conan = media(235, en="Detective Conan", syn=["Case Closed"], year=1996)
    assert covers.score("Case Closed", conan, 2026, True, False) >= 1.0


def test_season_numbers():
    assert covers.season_no("Mushoku Tensei Season 3") == 3
    assert covers.season_no("Ao no Hako 2nd Season") == 2
    assert covers.season_no("The Iceblade Sorcerer Shall Rule the World II") == 2
    assert covers.season_no("Red River") is None


def test_search_terms_handle_quotes_parentheses_and_hyphens():
    assert "KERORO☆" in covers.search_terms("Sgt. Frog (KERORO☆)")
    assert "Let's go Kaikigumi" in covers.search_terms("Let’s go Kaiki-gumi")
    assert covers.search_terms("Even Though I’m Timid")[0] == "Even Though I'm Timid"


# ---------------------------------------------------------------- build wiring

ART = {"235": {"large": "https://img/l.jpg", "xl": "https://img/x.jpg", "scrim": 0.57, "color": "#e4a15d"},
       "21": {"large": None, "xl": None, "scrim": None}}


@pytest.mark.parametrize("value, expected", [(235, "235"), ("235", "235"), (235.0, "235"), ("none", None), ("", None), ("abc", None)])
def test_anilist_id_parsing(value, expected):
    assert bc.anilist_id(row(AniList_ID=value)) == expected


def test_art_fields():
    assert bc.art_fields(row(AniList_ID=235), ART) == {"ai": 235, "im": "https://img/l.jpg", "ix": "https://img/x.jpg", "sa": 0.57, "ic": "#e4a15d"}
    assert bc.art_fields(row(AniList_ID=21), ART) == {"ai": 21}          # linked, no usable image
    assert bc.art_fields(row(AniList_ID="none"), ART) == {}


def test_check_covers_warnings():
    rows = [row(Title="A", AniList_ID=235), row(Title="B", AniList_ID=""), row(Title="C", AniList_ID=999),
            row(Title="D", AniList_ID="none"), row(Title="E", AniList_ID="x1")]
    w = bc.check_covers(rows, ART)
    assert len(w) == 3
    assert any(x.startswith("B:") and "no AniList ID" in x for x in w)
    assert any(x.startswith("C:") and "not in covers.json" in x for x in w)
    assert any(x.startswith("E:") and "not a number" in x for x in w)


def test_static_slot_carries_the_art_and_measured_overlay():
    payload = bc.build_payload([row(Schedule="Fri · Nov 6", Episodes=1, AniList_ID=235)], 2026, dt.date(2026, 11, 6), ART)
    _, _, html = bc.static_week(payload, dt.date(2026, 11, 6))
    assert 'class="ep-art"' in html and 'referrerpolicy="no-referrer"' in html and 'alt=""' in html
    assert "--scrim:0.57" in html and "has-art" in html


def test_build_without_covers_file_still_works(tmp_path):
    assert bc.load_art(tmp_path / "missing.xlsx") == {}


def test_committed_covers_cover_every_linked_row():
    rows = bc.read_rows(ROOT / "anime-calendar-data.xlsx")
    art = bc.load_art(ROOT / "anime-calendar-data.xlsx")
    assert bc.check_covers(rows, art) == []
    for e in art.values():
        if e.get("scrim") is not None:
            assert covers.SCRIM_FLOOR <= e["scrim"] <= covers.SCRIM_CEIL + 0.01
            assert e["worst_title_contrast"] >= 4.5
