"""Cover art for the calendar, from AniList.

    python3 build_calendar.py --fetch-covers            # match new rows, refresh missing covers
    python3 build_calendar.py --fetch-covers --refresh  # re-download and re-measure every cover

Two outputs:
  * the `AniList ID` column in the workbook — the reviewed link from a row to its AniList
    entry. The fetch fills it only for confident matches and prints the rest for review.
    Fix a wrong match by typing the right ID (the number in anilist.co/anime/<id>).
  * covers.json — derived data the build embeds: cover URLs, AniList's dominant colour,
    and `scrim`, the overlay strength each cover needs behind the slot text.

Why measure every cover: a schedule slot puts white text on top of the art. A dark cover
needs little overlay; a bright, busy one needs a lot. Instead of one heavy overlay for all
(which buries dark art) or one light overlay (which fails on bright art), the fetch
downloads each cover, takes the band the slot actually shows, and finds the lightest
overlay at which every text-line-high strip of that band, at its brightest 2% of pixels,
still gives the white slot text 4.5:1 contrast (WCAG AA), with a 3% margin. Dark covers get
a light overlay (floor 0.40) and stay vivid; covers with white areas get up to 0.85.

The build never touches the network: it only reads covers.json, so builds stay
reproducible and CI needs no API access. Images are not stored in the repo; the page loads
them from AniList's CDN and falls back to the plain slot if they fail to load.
"""
import datetime as dt
import difflib
import io
import json
import re
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

API = "https://graphql.anilist.co"
UA = "anime-release-calendar/2.0 (+https://github.com/benheise/anime-calendar)"
COVERS_FILE = "covers.json"

# Overlay drawn over the art: the page ink colour, in sRGB. Must match --ink in the template.
INK = (21, 16, 31)
# Text drawn on art is all white (time, title and meta line), and every line must reach
# WCAG AA, 4.5:1, against the composited background. Tags sit on their own solid chips.
TITLE_RGB, TITLE_MIN = (255, 255, 255), 4.5
META_RGB, META_MIN = (255, 255, 255), 4.5
SCRIM_FLOOR, SCRIM_CEIL = 0.40, 0.85
# The part of a portrait cover a slot shows. Slots use object-fit:cover with the focus 22%
# from the top; across desktop, laptop and phone widths the visible part falls within about
# 6%–72% of the cover's height. Measuring a wider band is the safe direction.
BAND = (0.06, 0.72)
# Text is read line by line, so a bright patch behind one line matters even when the band as
# a whole is dark. The overlay is sized for the worst full-width strip one text line tall
# (about 5% of a cover's height in a slot), at its brightest 2% of pixels.
STRIP, STEP = 0.05, 0.01
PERCENTILE = 98
MARGIN = 1.03       # aim 3% above 4.5:1 to absorb resampling and browser compositing

FIELDS = """id title { romaji english native } synonyms format status season seasonYear
            startDate { year month day } episodes siteUrl
            coverImage { extraLarge large medium color }"""


# ---------------------------------------------------------------- contrast maths

def _lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb):
    r, g, b = (_lin(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(l1, l2):
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def max_background_luminance():
    """The brightest background that still meets both text targets (with MARGIN)."""
    lt, lm = luminance(TITLE_RGB), luminance(META_RGB)
    return min((lt + 0.05) / (TITLE_MIN * MARGIN) - 0.05, (lm + 0.05) / (META_MIN * MARGIN) - 0.05)


def scrim_for(pixels, percentile=PERCENTILE):
    """Lightest ink overlay alpha that keeps every text-line strip of `pixels` legible.

    `pixels` is the slot band as an H×W×3 sRGB array (an N×3 array is treated as one strip).
    Browsers composite in sRGB space: out = a·ink + (1−a)·pixel, per channel. For a given
    alpha the score is the brightest strip's `percentile` luminance after compositing.
    Returns (alpha, worst_contrast_for_white_text), alpha clamped to [SCRIM_FLOOR, SCRIM_CEIL].
    """
    import numpy as np
    px = np.asarray(pixels, dtype=np.float64)
    if px.ndim == 2:
        px = px.reshape(1, -1, 3)
    h = px.shape[0]
    full_h = h / (BAND[1] - BAND[0])                     # the cover's height in these rows
    sh = max(1, round(STRIP * full_h))
    step = max(1, round(STEP * full_h))
    strips = [px[y:y + sh].reshape(-1, 3) for y in range(0, max(1, h - sh + 1), step)]
    ink = np.asarray(INK, dtype=np.float64)
    target = max_background_luminance()
    lut = np.array([_lin(v) for v in range(256)])

    def worst(a):
        top = 0.0
        for st in strips:
            out = np.clip(np.rint(a * ink + (1 - a) * st), 0, 255).astype(int)
            lum = 0.2126 * lut[out[:, 0]] + 0.7152 * lut[out[:, 1]] + 0.0722 * lut[out[:, 2]]
            top = max(top, float(np.percentile(lum, percentile)))
        return top

    lo, hi = 0.0, 1.0
    if worst(lo) <= target:
        a = 0.0
    else:
        for _ in range(18):
            mid = (lo + hi) / 2
            if worst(mid) <= target:
                hi = mid
            else:
                lo = mid
        a = hi
    a = min(SCRIM_CEIL, max(SCRIM_FLOOR, a))
    a = min(1.0, round(a + 0.005, 2))      # round up, never below what was measured
    return a, round(contrast(luminance(TITLE_RGB), worst(a)), 2)


def band_pixels(img_bytes, width=115):
    """Decode a cover, scale it to `width`, and return the slot band as an H×W×3 array."""
    import numpy as np
    from PIL import Image
    im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    h = max(1, round(im.height * width / im.width))
    im = im.resize((width, h), Image.LANCZOS)
    top, bottom = round(h * BAND[0]), max(round(h * BAND[1]), round(h * BAND[0]) + 1)
    return np.asarray(im.crop((0, top, width, bottom)))


# ---------------------------------------------------------------- matching

_SEASON_WORDS = {"second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ").replace("½", " 1/2")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def season_no(title):
    """Season number named in a title ('Season 2', 'S2', '2nd Season', 'II'), else None."""
    t = str(title or "")
    m = re.search(r"\b(?:season|s)\s*(\d+)\b", t, re.I) or re.search(r"\b(\d+)(?:st|nd|rd|th)\s+season\b", t, re.I)
    if m:
        return int(m.group(1))
    for w, n in _SEASON_WORDS.items():
        if re.search(rf"\b{w}\s+season\b", t, re.I):
            return n
    m = re.search(r"\b(II|III|IV)\b", t)
    return {"II": 2, "III": 3, "IV": 4}[m.group(1)] if m else None


def names(media):
    t = media.get("title") or {}
    return [x for x in [t.get("english"), t.get("romaji"), *(media.get("synonyms") or [])] if x]


def score(row_title, media, year, carryover, is_film):
    """0..~1.2: title similarity plus season/year/format agreement."""
    nt = norm(row_title)
    sims = [difflib.SequenceMatcher(None, nt, norm(n)).ratio() for n in names(media)]
    best = max(sims) if sims else 0.0
    if any(norm(n) == nt for n in names(media)):
        best = 1.0
    s = best
    sy = (media.get("startDate") or {}).get("year") or media.get("seasonYear")
    if not carryover and sy:
        s += 0.12 if sy >= year - 1 else -0.25
    rs = season_no(row_title)
    ms = {season_no(n) for n in names(media)} - {None}
    if rs and ms and rs not in ms:
        s -= 0.3
    if rs and rs > 1 and not ms:
        s -= 0.15
    if is_film != (media.get("format") == "MOVIE"):
        s -= 0.1
    return round(s, 3)


# ---------------------------------------------------------------- AniList

class AniList:
    """Tiny GraphQL client that respects AniList's per-minute rate limit."""

    def __init__(self, min_gap=2.1):
        self.min_gap, self.last = min_gap, 0.0

    def query(self, q, variables):
        for attempt in range(5):
            wait = self.min_gap - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            req = urllib.request.Request(API, data=json.dumps({"query": q, "variables": variables}).encode(),
                                         headers={"Content-Type": "application/json", "Accept": "application/json",
                                                  "User-Agent": UA})
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.loads(r.read())["data"]
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    time.sleep(int(e.headers.get("Retry-After") or 60) + 1)
                    continue
                if e.code == 404:
                    return None
                raise
        raise RuntimeError("AniList kept rate-limiting; try again later")

    def search(self, text, n=8):
        q = f"query($s:String,$n:Int){{Page(perPage:$n){{media(search:$s,type:ANIME,sort:SEARCH_MATCH){{{FIELDS}}}}}}}"
        d = self.query(q, {"s": text, "n": n})
        return (d or {}).get("Page", {}).get("media", []) or []

    def by_id(self, mid):
        d = self.query(f"query($id:Int){{Media(id:$id,type:ANIME){{{FIELDS}}}}}", {"id": int(mid)})
        return (d or {}).get("Media")


def fetch_bytes(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def search_terms(title):
    """The title, then simpler forms. AniList's search misses on curly quotes, on text in
    parentheses ("Sgt. Frog (KERORO☆)"), and on hyphenated romaji ("Kaiki-gumi")."""
    t = title.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    paren = re.findall(r"\(([^)]+)\)", t)
    no_paren = re.sub(r"\s*\([^)]*\)", "", t).strip()
    cands = [t, no_paren, *paren,
             re.split(r"\s*[:–—]\s+|\s+-\s+", no_paren)[0],
             re.sub(r"\b(season|part|cour)\s*\d+\b|\b\d+(st|nd|rd|th)\s+season\b", "", no_paren, flags=re.I).strip(" :-–—"),
             re.sub(r"(?<=\w)-(?=\w)", "", no_paren),
             " ".join(no_paren.split()[:4])]
    out = []
    for c in cands:
        c = c.strip()
        if c and c not in out:
            out.append(c)
    return out


def best_match(client, title, year, carryover, is_film):
    cands, seen = [], set()
    for term in search_terms(title):
        for m in client.search(term):
            if m["id"] not in seen:
                seen.add(m["id"])
                cands.append(m)
        if cands and max(score(title, m, year, carryover, is_film) for m in cands) >= 1.0:
            break
    ranked = sorted(cands, key=lambda m: -score(title, m, year, carryover, is_film))
    return [(score(title, m, year, carryover, is_film), m) for m in ranked[:3]]


def entry_for(media, fetched):
    t = media.get("title") or {}
    ci = media.get("coverImage") or {}
    return {"title": t.get("english") or t.get("romaji"), "romaji": t.get("romaji"),
            "format": media.get("format"), "year": (media.get("startDate") or {}).get("year"),
            "url": media.get("siteUrl"), "large": ci.get("large"), "xl": ci.get("extraLarge"),
            "color": ci.get("color"), "fetched": fetched}


def load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def save(path, data):
    Path(path).write_text(json.dumps(dict(sorted(data.items(), key=lambda kv: int(kv[0]))),
                                     indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


ACCEPT = 0.97      # auto-fill the AniList ID at or above this score
NO_ENTRY = {"none", "-", "n/a"}   # AniList ID values meaning "checked, not on AniList"


def run(xlsx, year, refresh=False, log=print):
    """Match rows, write IDs to the workbook, refresh covers.json. Returns a review list."""
    import openpyxl
    from build_calendar import is_carryover, parse_when, read_rows

    xlsx = Path(xlsx)
    cache_path = xlsx.with_name(COVERS_FILE)
    cache = load(cache_path)
    rows = read_rows(xlsx)
    wb = openpyxl.load_workbook(xlsx)
    ws = wb["Shows"]
    hdr = [c.value for c in ws[1]]
    if "AniList ID" not in hdr:
        ws.cell(row=1, column=ws.max_column + 1, value="AniList ID")
        hdr = [c.value for c in ws[1]]
    col = hdr.index("AniList ID") + 1
    by_title = {ws.cell(row=r, column=1).value: r for r in range(2, ws.max_row + 1) if ws.cell(row=r, column=1).value}

    client, today, review, changed = AniList(), dt.date.today().isoformat(), [], False
    for r in rows:
        title = r["Title"]
        mid = str(r.get("AniList ID") or "").strip()
        if mid.endswith(".0"):
            mid = mid[:-2]
        if mid.lower() in NO_ENTRY:          # checked: not on AniList, keep the plain slot
            continue
        media = None
        if not mid:
            w = parse_when(r, year)
            matches = best_match(client, title, year, is_carryover(r), w.get("film", False))
            if not matches:
                review.append((title, None, "no AniList result"))
                continue
            sc, media = matches[0]
            note = " | ".join(f"{s:.2f} {m['id']} {names(m)[0]!r} ({(m.get('startDate') or {}).get('year')}, {m.get('format')})"
                              for s, m in matches)
            if sc < ACCEPT:
                review.append((title, media["id"], note))
                continue
            mid = str(media["id"])
            ws.cell(row=by_title[title], column=col, value=int(mid))
            changed = True
            log(f"  matched  {title!r} -> {mid} {names(media)[0]!r}")
        e = cache.get(mid)
        if e and not refresh and e.get("scrim") is not None:
            continue
        if not e or refresh:
            media = media if media and str(media["id"]) == mid else client.by_id(mid)
            if not media:
                review.append((title, mid, "AniList ID not found"))
                continue
            e = entry_for(media, today)
        try:
            img = fetch_bytes(e["large"] or e["xl"])
            e["scrim"], e["worst_title_contrast"] = scrim_for(band_pixels(img))
        except Exception as ex:          # no cover, or the CDN failed: keep the link, skip the art
            e["scrim"], e["error"] = None, str(ex)[:120]
        cache[mid] = e
        log(f"  cover    {title!r}: overlay {e['scrim']}")
    if changed:
        wb.save(xlsx)
    used = set()                                   # drop covers no row points at any more
    for r in read_rows(xlsx):
        v = str(r.get("AniList ID") or "").strip()
        used.add(v[:-2] if v.endswith(".0") else v)
    save(cache_path, {k: v for k, v in cache.items() if k in used})
    return review
