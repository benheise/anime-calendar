# Anime Calendar — operating notes

Working rules for the Summer/Fall 2026 anime calendar (`anime-calendar-data.xlsx` →
`build_calendar.py` → `anime-calendar-2026.html`). Every rule here was written after a
specific failure that Ben caught, not from theory. Read this before any sweep.

---

## 0. The one-line summary

**Almost every error in this project came from treating one source's silence or one
source's number as the whole truth.** Absence of a listing is not absence of the thing.
A broadcast time is not a stream time. A lineup post is not the final lineup.

---

## 1. Source hierarchy

For each fact, prefer in this order. Do not stop at the first source that answers.

| Fact | Best source | Known trap |
|---|---|---|
| Streaming time | **AnimeSchedule** seasonal/per-show (sub time) | **LiveChart publishes the JAPANESE BROADCAST time**, not the stream |
| Streaming time, non-CR | The platform's own lineup post | AnimeSchedule tracks CR sub times best |
| Premiere date | The platform's own lineup announcement | Aggregator dates can be the JST date, a day off |
| Episode count | ANN / Wikipedia episode list | "Expected to have N" ≠ confirmed |
| Whether it ended | Wikipedia episode list, LiveChart status | Carryover rows run forever if unchecked |
| Day of week | Compute it from the date yourself | AnimeSchedule's weekday labels are often wrong |

**Verify any day-of-week claim by computing it from the date.** AnimeSchedule has labelled
Oct 2 as "Thu" and Oct 7 as "Tue". The dates were right, the labels were not.

**AnimeSchedule is best for times, not for dates.** When it and the platform disagree on a
DATE, the platform wins; when they disagree on a TIME, AnimeSchedule wins. Record the
conflict in `Caveat`, set a 7-day interval, and let the air date settle it.

### Do not overturn AnimeSchedule's time with a third site

A Certain Dark Item is the worked example, and it is a self-inflicted one. AnimeSchedule
said **Oct 8, 11:30 AM**. Crunchyroll's lineup said **Oct 9**. The rule above resolves this
exactly: take Oct 9 from the platform and 11:30 AM from AnimeSchedule. Instead a third
site (anime-calendar.net) was fetched, its "13:30 UTC" was converted to 9:30 AM ET, and
that was written in as `Time confirmed: yes` — discarding the correct time from the
correct source, and marking a guess as verified. It did not air at 9:30.

Two hard rules out of it:
1. When the hierarchy already answers, **stop**. A third source is for breaking a tie the
   hierarchy cannot, not for re-opening one it has settled.
2. `Time confirmed = yes` means an **observed release** or a **first-party platform
   listing**, and nothing else. Never an aggregator, however precise its number looks.
   (As of Oct 9 only 7 rows qualify — that is the right order of magnitude, not a gap.)

### Early-stream services shift the apparent date

A Certain Dark Item streams on **ABEMA a day before the TV broadcast**, so listings
legitimately disagree by one day: Oct 8 for the early stream, Oct 9 for the broadcast the
Crunchyroll sub follows. A listing one day early is often this, not an error — and it is
the same shape as Overgeared's Prime-Video-Japan early stream. Check for an early-stream
note before "correcting" a date.

### The broadcast-vs-stream trap (cost: 10+ wrong times)

LiveChart's time is when it airs on Japanese TV. The Crunchyroll sub lands **30–90 minutes
later**, and the gap is per-show, not constant:

- Magic Repo Man — broadcast 12:30 PM ET, stream **2:00 PM** (90 min)
- The Exiled Heavy Knight — broadcast 11:26 AM, stream **12:30 PM** (64 min)
- TOUGEN ANKI — broadcast 11:30 PM JST, stream **12:00 PM ET**

A bulk time-diff against LiveChart will show lots of "matches" that are all wrong in the
same direction. **Diff against AnimeSchedule.**

~~Netflix/Prime/Disney+ are platform drops on a US clock (midnight PT = 3:00 AM ET).~~
**That rule was wrong for weekly simulcasts and has been withdrawn (Nov 6).** It put
*Ramparts of Ice S2* at 3:00 AM (real: right after the 23:56 JST broadcast, 10:30 AM EST)
and *Tokyo Revengers* at 3:00 AM (real: 2:00 AM JST Saturday = noon EST Friday) for five
weeks. Neither 3:00 AM was ever observed — the rule supplied the number. What actually holds:
- **All-at-once originals** (Cyberpunk: Edgerunners 2, Fool Night, Bass X Machina) drop at
  midnight PT = 3:00 AM ET. `US-anchored`.
- **Weekly simulcasts of a Japanese TV show** on Netflix, Disney+ or Prime drop shortly
  after the Japanese broadcast, on Japan's clock. Unanchored. Take the time from
  AnimeSchedule's SUB column, exactly as for Crunchyroll.

**But do not assume AnimeSchedule is wrong for non-CR platforms — check.** The Oct 9
Saturday audit went both ways:
- *Ranma ½ S3* (Netflix) — calendar 11:55 AM was RIGHT, AnimeSchedule's 1:00 PM wrong
- *Seven Knights of the Marronnier Kingdom* (Prime) — AnimeSchedule's 11:00 AM was RIGHT,
  the calendar's 5:25 AM wrong by nearly six hours

So "non-CR means distrust AnimeSchedule" is too crude. Treat AnimeSchedule as the default
for every platform, and confirm non-CR entries against a platform-specific source
(whats-on-netflix, a Prime/Disney listing, a release-time article) before accepting or
rejecting it.

### A pre-premiere date is a placeholder too — the platform's date wins

*Devils' Crest* sat on **Thu Nov 5, 10:01 AM** because that was AnimeSchedule's
pre-premiere entry. Prime Video had announced **Friday Nov 6** since July, and every source
(Prime's own PR, ANN, Wikipedia) said so. It premiered Nov 6 at 7:01 AM EST with two
episodes. The rule already said "platform wins on dates"; the row broke it because the
aggregator's number looked more precise. A pre-premiere AnimeSchedule row is a guess at
both the date and the time.

### Read the JPN column and the SUB column separately

*Blue Box S2* and *Yozakura S2 P2* both carried the Japanese broadcast time as the platform
drop, with a caveat that said the opposite ("AnimeSchedule reads 4:00 AM (Japanese
broadcast); 3:30 AM here is the Netflix drop"). AnimeSchedule's 4:00 was the SUB column and
3:30 the JPN column — the labels were swapped when reading. Quote the column name when
copying a time.

### The week timetable is the fastest full sweep

`animeschedule.net/?year=2026&week=NN` lists every show on every day with JPN / SUB / DUB
times. One fetch per week covers the whole grid, and it shows the **weekday** as well as
the time — that is how *Genso Suikoden* turned up on Tuesday while the calendar had it on
Saturday, and how *Battle Spirits [Re] ZEKKAI NO KU* (airing since Oct 6, in no lineup
reprint) was found. Diff it three ways: wrong time, wrong day, and any SUB entry not on the
calendar at all. Then confirm writes on the per-show page.
Two cautions: pick a week entirely on one side of a DST change (week 44 was labelled "EDT"
while its Sunday Nov 1 values were already EST), and remember some entries are "hidden by
filters", so absence from the timetable is not evidence a show stopped.

### Re-read AnimeSchedule AFTER a show has aired

Its pre-premiere numbers are estimates; it corrects them once episodes actually drop. The
whole Oct 3 Saturday cohort was entered from a pre-premiere read and **seven of those
times were wrong**. A re-read a week later matched the observed times. Build the habit:
for anything entered before it aired, re-check the time once it has.

### Use the PER-SHOW page, not the seasonal list

The seasonal list is one fetch covering everything, which makes it tempting for bulk
diffs. It is also the less reliable view: it gives a single number per title, and that
number is sometimes the raw and sometimes the sub, and **it changes between reads**.
VERTEX FORCE read 11:00 AM on Oct 9 and 12:00 PM on Oct 10; its per-show page says raw
10:30 AM, **sub 12:00 PM**. HORROR COLLECTOR read 10:45 AM then 1:15 PM; per-show says
10:45 AM is the raw.

The per-show page lists raw and subs separately, so you can see which you are reading.
Use the seasonal list to find candidates and spot gaps; confirm every time you actually
write from the per-show page.

### Only an observed airing is really reliable

Paw & Palaces aired at **7:00 AM ET** — hours before anything predicted, and AnimeSchedule
has no entry for it at all. Every aggregator figure is an estimate until a show airs. When
Ben reports a time, that is the single best datum available; set `Time confirmed = yes`
and stop chasing it.

### A schedule-grid entry is not proof a show aired

LiveChart's daily schedule still lists "One Piece EP1181" every Sunday while the anime is
on break until 2027. Grids project forward from a slot; they do not know about hiatuses.
Confirm against an episode list or a news item before concluding a show is back — and
before concluding a calendar row that says "ended" is wrong.

---

## 2. Absence is not evidence

When an aggregator shows no streaming platform, that means **unknown**, not **unlicensed**.

This cost four separate misses:
- *I'm Dating a Dark Summoner* — LiveChart blank, HIDIVE was carrying it
- *Mission: Yozakura Family S2 P2* — LiveChart blank, Disney+ was carrying it
- *Magic Repo Man* + 6 others — researched and dropped on Sep 30, Crunchyroll announced
  them as acquisitions **that same day**

**Rule:** an in-window title with no announced platform goes in as `Platform = TBA` with a
caveat — never omitted. A TBA row is visible and gets rechecked; an omitted row is
invisible and silently wrong. Only *remove* a title confirmed on an unsupported service
(e.g. Duel Masters LOST → YouTube).

The TBA rows do resolve, in both directions. In the Oct 9 sweep: TANK CHAIR → Prime Video,
Dragon Ball Super: Beerus → Crunchyroll (both kept), while *Even the Student Council Has
Its Holes!*, *Magical Girl Raising Project: Restart* and *My Girlfriend's Friend* all
turned out to be **OceanVeil** exclusives and were removed.

**OceanVeil is a real competitor now picking up fall simulcasts, and it is not a supported
platform.** Check it before assuming a title is unlicensed — and watch for it taking
titles that would previously have gone to Crunchyroll. (As of mid-October it was reported
to have payment-processor trouble; if it folds, its exclusives may move somewhere
supported, so re-check them.)

**Unsupported services seen so far:** YouTube (Duel Masters LOST, *Genso Suikoden*,
*Welsh & Shedar*, *Ghost Meets Gal!*), OceanVeil (fall titles incl. *Even the Student
Council Has Its Holes!*, *Kamui: He's Behind You*, *The Lonely Snow Widow and the Cursed
Ring*, *Now That I Can Control Reality With a Mouse Cursor*), iQIYI (donghua), and
**Ani-One Asia** — a YouTube-channel licensor whose titles are Asia-only and show "may be
unavailable in your region". An OceanVeil title getting an English dub (Student Council,
Nov 7) is still OceanVeil — Aniplex of America produces the dub *for* OceanVeil.

### Crunchyroll News covering a show is not Crunchyroll streaming it

*Genso Suikoden* was a Crunchyroll row for a month. Crunchyroll News had run its visuals
and trailers, and an Italian site said "in arrivo su Crunchyroll". It streams free on
Konami's own YouTube channel (ANN, Oct 3) plus Ani-One Asia. Crunchyroll News reports on
the whole industry, including other services' shows. A platform is confirmed only by its
lineup post, a title page, or a licence announcement.

### The TBA rule cuts both ways — don't invent a platform either

*With Vengeance, Sincerely, Your Broken Saintess Season 2* was added to the calendar as a
Crunchyroll title on Oct 16 and removed a day later: it is an **Ani-One Asia** licence,
streaming in parts of Asia only.

This was avoidable and is the §1 mistake wearing different clothes. The Anime UK News
thread — the documented best cross-platform source — listed it under *"Also broadcasting
(platform not listed)"*, i.e. explicitly **not** under Crunchyroll. That answer was then
overturned by thereviewgeek, a site this very file already flags for getting ET
conversions wrong. One weak secondary source beat the strong one, again.

So: when a title is absent from every platform's list, the rule in this section says enter
it as **TBA** — it does not license assigning a platform on thin evidence. TBA would have
been correct here and harmless. Assigning "Crunchyroll" put a show on the calendar that
Ben cannot watch.

**Prime Video stealth-adds titles with no announcement.** TANK CHAIR and The Seven Knights
of the Marronnier Kingdom both appeared there unannounced; only the Anime UK News thread
caught it. Prime will not tell you.

---

## 3. Lineups get amended

Crunchyroll announced Fall 2026 on **Sep 15** and added **nine more titles on Sep 30**.
A sweep diffing only against the original post misses them — this happened even during a
full 141-row audit.

Each sweep must also search for:
`"<platform> adds <season> <year> anime"` · `"new simulcast acquisitions"` · `"lineup update"`

---

## 4. Check every platform's own source

Sweeps were Crunchyroll-centric for weeks. HIDIVE published its Fall lineup on Sep 21 and
it was missed through two subsequent sweeps because nothing ever read HIDIVE's own page.

- **Crunchyroll** — `crunchyroll.com/news/seasonal-lineup/` (JS-rendered; use a reprint).
  News RSS *is* directly fetchable: `cr-news-api-service.prd.crunchyrollsvc.com/v1/en-US/rss`
  (~4-day window; works via WebFetch, **not** from the shell — the proxy blocks that host)
- **HIDIVE** — `news.hidive.com` (JS-rendered SPA, no RSS; use comicbook.com or Anime UK News)
- **Netflix** — whats-on-netflix.com, ANN
- **Disney+ / Hulu** — whatsondisneyplus.com (carries titles CR does not)
- **Prime Video** — ANN / LiveChart licence notes
- **Best single cross-platform stop:** the Anime UK News forum "Autumn 20XX Simulcast
  Line-up" thread — it caught HIDIVE, Netflix and Disney+ gaps in one pass

---

## 5. Long runs are not unbroken

`finale = premiere + (episodes − 1) weeks` is wrong for multi-cour shows in two ways:

1. **Split cours** — *Slime S4* cour 2 ended Sep 25; cour 3 is July 2027
2. **Recap/break week** — *Sorry About My Little Brothers* skipped Sep 25, shifting every
   later episode by a week

Both silently project episodes that do not exist. `--check` now warns on any run of 22+
episodes with no `Explicit end` and no `Skip dates`. Resolve the warning by actually
checking, then note what you found in `Caveat` (mentioning "cour") to silence it.

**A cour-2 trailer in the news feed is a signal to check for a break** — it appeared for
both Slime and Sorry About My Little Brothers before each gap, and was read past both times.
It is *not* proof of a break: Red River ran straight through its own "2nd part" promo.

### One show, two titles

*TEMPAL ~Item no Chikara~* sat on the calendar beside *Overgeared* from Sep 27 to Oct 22,
showing the same show twice every Sunday. TEMPAL is the Japanese broadcast title (from the
Korean webtoon 템빨); Overgeared is Crunchyroll's English title. The Sep 27 LiveChart
result literally read "OVERGEARED (TEMPAL ~Item no Chikara~)" and it was still added as
a separate row. Before adding any title found under a romaji or original-language name,
check LiveChart's English-title line and search the sheet for the English title. A new
row landing on the same platform, day and time as an existing one is the tell — though
plenty of genuinely different simulcasts share a slot, so it is a prompt to check, not
proof.

### Use the platform's English title, exactly

*Devils' Crest* was on the calendar as **"Demons' Crest"** from the day it was added until
Ben caught it on Nov 6, through two sweeps that researched the row's date and time. Prime
Video and ANN both say *Devils' Crest*, and the Nov 6 searches returned that title while
the row was being edited, but nobody compared it with the row. The `Title` must match
the platform's listing character for character, because that is what Ben searches for in
the app. When you research a row, check its title against the platform's own listing as
well as its date and time. When you rename a row, add the old name to the caveat so
searching for it still finds the row.

### Saturday-morning JP shows are FRIDAY evening Eastern

*Sgt. Frog* airs Saturday morning on TV Tokyo, which is Friday ~9:00 PM ET. It sat on the
Saturday grid for three weeks. Any JP morning slot lands on the previous evening in ET —
compute the ET date from the JST time; never copy the JST weekday.

### Carryover rows end silently
Three shows had finished weeks earlier and were still projecting episodes: *The Drops of
God* (ended Sep 18), *The Classroom of a Black Cat and a Witch* (Sep 20), *Liar Game*
(Sep 28). Any `Carryover` row with no `Explicit end` needs a periodic liveness check
(these were `Platform = Continuing` rows before Nov 6; see §7).
It happened again on Nov 6: *MAO* ended Sep 26 (26 eps) and was still projecting six weeks
later. Its caveat said "cour 2 confirmed airing (ending-theme MV released Sep 26)". An MV
on the finale date is a finale signal, not proof the show continues.
*Link Click S3* Part 1 ended Oct 23, a week before the 12-episode estimate. When the dub
keeps running on the same platform, the sub's ending is easy to miss.

### Recap weeks
*Psyren* aired a recap instead of episode 5 on Nov 2. A recap is a `Skip date`, since it is
not in the episode count. AnimeSchedule's per-show page flags these as "Delayed" / "On
break this week".

---

## 6. Ben's reports are primary sources

He watches these on the actual platforms. He has been right **every single time** —
Victoria of Many Faces, Chainsmoker Cat, Tomb Raider King, Ramparts of Ice, Overgeared,
HIDIVE's lineup, Exiled Heavy Knight's time, Slime, Magic Repo Man's date, and its time,
A Certain Dark Item's time, Paw & Palaces, Broken Saintess's platform, and Devils' Crest's
premiere day (Nov 6) and its title. When he says "some shows are still on the wrong day", the Nov 6
sweep found two: Devils' Crest and Genso Suikoden.

When his observation conflicts with a source, **the source is wrong.** Fix the data first,
then work out which source misled and write the lesson down here.

Don't correct a date while keeping the reasoning that produced it. Overgeared was moved
Sep 27 → Oct 2 → Sep 27 → Friday → Sunday, because each fix addressed the symptom and kept
the bad premise (that Crunchyroll follows the Japanese TV broadcast — it follows the early
stream track).

---

## 7. Schema notes

| Column | Meaning |
|---|---|
| `Platform` | One of Crunchyroll, HIDIVE, Netflix, Hulu, Prime Video, Disney+, TBA. **`Continuing` is retired** (Nov 6): it hid where a show streams. Put the real platform here and `yes` in `Carryover`. `--check` errors on it. |
| `Schedule` | `Wed · Jul 8` dated · `Saturdays` weekly · `Fall 2026` undated · `Released Jun 19` past one-off · `All at once · Oct 20` scheduled batch drop (always tagged "All episodes", count or not) |
| `Skip dates` | ISO dates the show does NOT air. Each pushes the finale a week later. |
| `Extra dates` | ISO dates it airs OUTSIDE its weekly slot (early premiere). Each comes out of the run's total. |
| `Double dates` | ISO release dates that carry two episodes (two-episode premiere). Each counts 2 toward `Episodes`, so the run ends a week sooner. Replaces the old "Two-episode premiere" note. |
| `First episode` | Starting episode number. Needed only for the second half of a split season (`Part 2`, `Cour 2`, `final part`, `Continuing cour` in `Type / Studio`), whose numbers are otherwise hidden because they may continue the first half's count. |
| `Carryover` | `yes` for a series running in from an earlier season. Carryover rows show no episode numbers and no Premiere tag. |
| `Also on` | A second supported platform carrying the same show (comma list). The platform filter matches it too. |
| `US-anchored` | `yes` for US-clock drops (Netflix midnight PT) so they don't shift at DST |
| `Time confirmed` | `yes` only when verified against an observed release or a first-party platform listing |
| `Explicit end` | Overrides the computed finale. Set it whenever a run is known to stop. |
| `Note` | One short fact shown under the title in the show sheet ("Prime exclusive"). Not a place for hype ("Major return") or anything the page already shows (episode counts, "Now airing"). |
| `Type / Studio` | `Kind · Studio` (e.g. `Sequel (S2) · MAPPA`). The page splits it at the last ` · ` into Series and Studio. |

Episode numbers, premiere/finale tags and finale dates are all **computed** by
`releases()` in `build_calendar.py` from these columns. Never type them into a note.
`--dump-airings "Title"` prints exactly what the page will show for a row.

`Shows!W1` holds "today" for the Status formulas — **not U1**, whatever older docs say.

**Deleting a row breaks every later row's Status formula.** openpyxl's `delete_rows()` does
not rewrite references. By Nov 6, 56 rows were computing Next Check Due / Status from the
row below them (Sgt. Frog on row 149 read Q152), so the Status column in Excel was wrong
for over a third of the sheet. `--check` now warns on any cooldown formula that points at
another row. After deleting a row, rewrite S/T for every row so each points at its own row
(`=IF(Q{r}="","",Q{r}+R{r})` and the matching Status formula), then re-run `--check`.

### DST: stored times are EDT references

`Time (ET)` is always the **EDT** time. From the first Sunday of November the page subtracts
an hour from every row **not** marked `US-anchored`. Two rules follow:

1. **Decide the anchor per row, by what the release follows.**
   - Follows the Japanese broadcast → leave unanchored, it steps back an hour. This is every
     Crunchyroll and HIDIVE simulcast, and Netflix weeklies that drop "right after" the JP
     broadcast (Ranma ½).
   - Pinned to a US clock → `US-anchored = yes`. Netflix all-at-once originals (midnight PT).
   - ~~Prime titles announced at a Pacific time (Marronnier: "8:00 AM PT")~~ — **wrong,
     withdrawn Nov 6.** Prime Video Japan's own press release says Marronnier releases
     "毎週日曜日午前0時(日本時間)", every Sunday at 0:00 JST. 8:00 AM PDT is just that time
     converted during summer. **A Pacific-time figure quoted during PDT is not evidence of
     US anchoring.** Look for the Japanese-language release, which states the JST anchor.
     Corroborated: Devils' Crest (21:00 JST) and TANK CHAIR both moved with Japan.
   - Anchored to a European clock (Dreamland, 19:00 Paris): Europe and the US both leave
     summer time by Nov 1, so the ET time is the same before and after. Mark `US-anchored`
     so the page does not subtract an hour.
   - Unknown → leave the default and flag it; the first post-DST episode settles it.
2. **A time copied from an EST source for a show starting after DST would be shifted an
   extra hour.** Devils' Crest was entered as "10:01 AM EST" and would have displayed 9:01.
   `--check` now warns on any unanchored row whose run starts after DST ends.

Verified Oct 23 across the Nov 1 boundary: TOUGEN ANKI 12:00 → 11:00, Ranma 11:55 → 10:55,
Dark Summoner flips on Nov 1 itself; Ramparts, Marronnier, Devils' Crest and Fool Night hold.

**Unsupported services, continued:** It's Anime (YouTube channel) — Magical Sisters
LuluttoLilly Cour 2 streams there and was removed Oct 23.

### Platform colours are validated — don't hand-edit them

The `--cr/--hidive/…` vars at the top of `calendar-template.html` were chosen with
the dataviz skill's `scripts/validate_palette.js` against the card surface `#211934`,
not by eye. Ben reported HIDIVE and Prime as hard to tell apart; the measurement found
the real problem was **three blues** (HIDIVE cyan, Prime blue, Disney+ light blue) with a
worst all-pairs normal-vision ΔE of **9.3**, far under the 15 floor.

HIDIVE → magenta `#c94f9e`, Disney+ → teal `#199e70`. Worst pair is now **15.0**
(Crunchyroll↔Netflix) and HIDIVE↔Prime went 17.1 → 27.7. Crunchyroll, Netflix, Hulu and
Prime keep their brand hues.

Two deviations are deliberate and should stay: `--tba` is near-neutral because it means
"platform unknown" and should read as absence (so it fails the chroma floor by design),
and cr/hulu/cont sit above the strict dark lightness band because the brighter steps
measurably separate better while still clearing 3:1 contrast.

When `Continuing` was retired (Nov 6), its validated amber `#ffc24b` became `--live`, the
page's single accent for now, next and today. It is never a platform colour, so no
platform is identified by it; it was already measured against all seven platform hues.

If you change any platform colour, re-run the validator on all eight and check the
all-pairs normal-vision floor — a single "nicer" hue can collapse a pair. Note the
method's own limit: with 8 slots **no ordering passes all-pairs CVD**, which is fine
here only because every colour sits beside its platform name (tabs, cards, legend), so
identity is never carried by colour alone.

---

## 8. Workflow

```
make install                               # once: pip install -r requirements.txt && npm ci
python3 build_calendar.py --check          # validate; fix every error, read every warning
python3 build_calendar.py --dump-airings "Title"   # what the page will show for a row
python3 build_calendar.py                  # rebuild the HTML
make test                                  # pytest + --check + build pinned + verify.js
```

### Architecture (since the Nov 6 redesign)

The build owns every scheduling rule. `releases()` turns each row into a list of releases —
ET date, exact UTC instant (or a date when the time is TBA), episode range, flags — and
`build_payload()` embeds them as `PAYLOAD` in the page. The page has **no schedule logic**:
it converts instants to the viewer's time zone with `Intl` and groups them by local day and
hour. Before Nov 6 the rules existed twice (Python validation, JS rendering) and drifted.
If a placement is wrong, fix `releases()` or the data, never the template.

The page has four views — Schedule (hour-banded week), Up next, All shows, Guide — plus a
show sheet with an .ics export. The no-JS fallback (`static_week()`, `static_shows()`) is a
snapshot in ET of the build week, so `--today` decides what Quick Look shows.

### Tests

- `tests/test_build.py` — unit tests on synthetic rows: skips, extras, doubles, multi-day,
  batch drops, carryovers, mid-cour numbering, DST in both anchoring modes, midnight
  crossings, validation messages, formula checks, rendering. Add a test when `releases()`
  or `validate()` changes. They don't depend on the sheet's data, except one test that
  the live sheet validates.
- `verify.js` — runs the built page in jsdom with the clock pinned to 10:00 AM ET on the
  sweep date and `TZ=America/New_York`. Checks the no-JS fallback, views and routing,
  filters, search, My list, the show sheet, settings (Tokyo, 24-hour), .ics format (CRLF,
  75-octet folding, UIDs), then **sweep placements**: the right weekday and displayed ET
  time for every row a sweep changed, plus finished shows being absent. Add an assertion
  for each row a sweep changes and bump `SWEEP_DATE` in the Makefile and `ci.yml`.
  Weeks run **Mon–Sun**, so Nov 2–8 is one week.
- CI (`.github/workflows/ci.yml`) runs all of it on every push and PR, and fails if the
  committed `anime-calendar-2026.html` is not what the workbook and template build.
  Commit the rebuilt page with every data change.
- **Publishing:** a passing push to `main` deploys the committed page to GitHub Pages
  (https://benheise.github.io/anime-calendar/, as `index.html` and under its own name).
  A sweep is not live until its PR is merged and that run's `deploy` job succeeds.

Always run the jsdom check before shipping. It has caught real bugs that `--check` cannot
see — a DST shift silently moving a Netflix batch drop to 2:00 AM, duplicate tabs, and
finished shows still appearing on the grid.

### The page must work inside an embedded preview

Ben opens the file in the app's file viewer, which shows it in an iframe built from the
file's contents (`about:srcdoc`). On the first redesign build, Up next, All shows and Guide
did nothing there. In a srcdoc frame a bare `href="#upcoming"` resolves against the
**host** page's URL, so each tab click navigated the frame away to a blank page, and
`history.pushState` throws a SecurityError. The tests never saw it because they ran the page
top-level and drove it by setting `location.hash`.

Rules:
- Every `href="#…"` link is handled by the document click handler (`go()`), with the
  default prevented. Don't add a link the handler doesn't route.
- `setUrl()` wraps every history call in try/catch. Views never depend on the URL changing,
  and `route(hash)` takes the hash as an argument rather than reading `location`.
- The "embedded preview safety" section of `verify.js` checks both: link clicks are
  cancelled, and tabs and the show sheet still work while `pushState` throws. For a real
  browser check, load the page in Playwright inside `<iframe sandbox="allow-scripts"
  srcdoc="…">` and click through every tab and a show.

The HTML is fully self-contained: it embeds every release as data plus a static snapshot,
needs no external file at runtime, and renders where scripts are blocked (iOS Quick Look).
The only external request is Google Fonts, with system-font fallbacks.

---

## 9. Environment

- Shell network is allowlisted to package registries + GitHub. **WebFetch reaches sites the
  shell cannot** — including the Crunchyroll RSS feed. Use WebFetch, don't retry with curl.
- Crunchyroll News, HIDIVE News and ANN are JS-rendered or 403 to WebFetch. Go to reprints.
- Attachments are at `/root/.claude/uploads/<session>/`.
