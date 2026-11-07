// End-to-end check of the built calendar in jsdom.
//
//   node verify.js [html] [YYYY-MM-DD]      (default: anime-calendar-2026.html, 2026-11-06)
//
// Runs the page with the clock pinned to 10:00 AM US Eastern on the given day, then checks:
//   1. the no-JS fallback (what iOS Quick Look shows): static week, directory, guide;
//   2. the scripted page: views, routing, filters, search, the show sheet, settings,
//      calendar (.ics) export;
//   3. specific placements that recent sweeps changed (weekday + displayed ET time).
//      Add an assertion here for every row a sweep changes — see CLAUDE.md §8.
process.env.TZ = 'America/New_York';            // the page reads the viewer's zone from Intl
const fs = require('fs');
const { JSDOM, VirtualConsole } = require('jsdom');

const file = process.argv[2] || 'anime-calendar-2026.html';
const todayIso = process.argv[3] || '2026-11-06';
const html = fs.readFileSync(file, 'utf8');

let fails = 0, passes = 0;
const ok = (cond, msg) => { if (cond) passes++; else { fails++; console.log('  FAIL:', msg); } };
const section = name => console.log(`\n${name}`);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const text = el => (el ? el.textContent : '').replace(/\s+/g, ' ').trim();

// ---------------------------------------------------------------- 1. no-JS fallback
section('static fallback (scripts off)');
{
  const { document: d } = new JSDOM(html).window;
  const days = d.querySelectorAll('#week-wrap section.day');
  const eps = d.querySelectorAll('#week-wrap li.ep');
  const rows = d.querySelectorAll('#dir-wrap li.dir-row');
  const count = Number(text(d.querySelector('.tab-n')));
  console.log(`  ${days.length} days, ${eps.length} releases, ${rows.length} directory rows`);
  ok(days.length === 7, 'static week has 7 days');
  ok(eps.length > 30, 'static week has releases');
  ok(rows.length === count && count > 100, `directory lists every title (${rows.length} of ${count})`);
  ok(d.querySelector('#guide h2') && text(d.querySelector('#guide')).includes('Times and time zones'), 'guide is in the page');
  ok(!/Summer 2026 Anime Guide|How to read this<\/h/.test(html), 'old title and footer heading are gone');
  ok(/<title>Anime Release Calendar · /.test(html), 'page title names the calendar');
  ok(!/<<[A-Z_]+>>/.test(html), 'no unfilled template placeholders');
  // every static entry links to an existing directory row
  const ids = new Set([...rows].map(r => r.id));
  const dangling = [...d.querySelectorAll('#week-wrap a.ep-btn')].filter(a => !ids.has(a.getAttribute('href').slice(1)));
  ok(dangling.length === 0, `static entries link to directory rows (${dangling.length} dangling)`);
  const staticArt = d.querySelectorAll('#week-wrap li.ep.has-art img.ep-art');
  ok(staticArt.length > 20, `static snapshot carries cover art (${staticArt.length} slots)`);
}

// ---------------------------------------------------------------- 2. scripted page
const errors = [];
const vc = new VirtualConsole();
vc.on('jsdomError', e => { const m = String(e && e.message || e); if (!/Not implemented/.test(m)) errors.push(m); });
vc.on('error', e => errors.push(String(e)));
const [Y, M, D] = todayIso.split('-').map(Number);
const dom = new JSDOM(html, {
  url: 'https://calendar.test/', runScripts: 'dangerously', pretendToBeVisual: true, virtualConsole: vc,
  beforeParse(win) {
    const Real = win.Date, fixed = new Real(Y, M - 1, D, 10, 0, 0).getTime();
    class FakeDate extends Real {
      constructor(...a) { if (a.length === 0) super(fixed); else super(...a); }
      static now() { return fixed; }
    }
    win.Date = FakeDate;
  },
});
const win = dom.window, doc = win.document;
const $ = s => doc.querySelector(s), $$ = s => [...doc.querySelectorAll(s)];
const go = async hash => { win.location.hash = hash; await sleep(30); };
const isOpen = d => !!(d && (d.open || d.hasAttribute('open')));
const click = async sel => { const el = typeof sel === 'string' ? $(sel) : sel; el.click(); await sleep(10); };

// Week as {Mon: [{time, title, meta}], ...}
function week() {
  const out = { _range: text($('#wk-range')), _meta: text($('#wk-meta')) };
  $$('#week-wrap section.day').forEach(sec => {
    out[text(sec.querySelector('.day-name'))] = [...sec.querySelectorAll('li.ep')].map(li => ({
      time: text(li.querySelector('.ep-time')), title: text(li.querySelector('.ep-title')),
      meta: text(li.querySelector('.ep-meta')), past: li.classList.contains('is-past'),
    }));
  });
  return out;
}
const find = (day, title) => (day || []).find(e => e.title.includes(title));
const has = (day, title, time) => { const e = find(day, title); return !!e && (!time || e.time === time); };
const anywhere = (w, title) => Object.keys(w).some(k => Array.isArray(w[k]) && find(w[k], title));

(async () => {
  section('scripted page');
  ok(doc.documentElement.classList.contains('js'), 'html.js class set');
  ok(errors.length === 0, 'no script errors: ' + errors.join(' | '));
  ok(text($('#tz-label')) === 'EST', `time zone label reads EST (got ${text($('#tz-label'))})`);
  ok($$('#filters .chip[data-plat]').length === 1 + JSON.parse(html.match(/"platforms":(\[[^\]]*\])/)[1]).length, 'one chip per platform plus All');

  // ---- this week
  section(`this week`);
  let w = week();
  console.log(`  ${w._range} — ${w._meta}`);
  ok(w._range === 'Nov 2 – 8, 2026', 'opens on the current week');
  ok($('section.day.is-today') && $('section.day.is-today').dataset.day === todayIso, 'today column highlighted');
  ok($('#week-wrap .nowline'), 'now line drawn in today\'s column');
  ok(find(w.Fri, "Devils' Crest").past, 'releases before now are dimmed');
  ok(!find(w.Fri, 'A Certain Dark Item').past, 'releases after now are not dimmed');
  ok(!$('#nextup').hidden && text($('#nextup .nu-title')) === 'A Certain Dark Item', 'Next up strip leads with the next release');
  ok(has(w.Fri, "Devils' Crest", '7:00 AM') && find(w.Fri, "Devils' Crest").meta.includes('Ep 1–2'), "Devils' Crest Fri Nov 6, 7:00 AM, Ep 1–2");
  ok(find(w.Fri, "Devils' Crest").meta.includes('Premiere'), "Devils' Crest tagged Premiere");
  ok(!has(w.Thu, "Devils' Crest"), "Devils' Crest NOT on Thursday");
  ok(!anywhere(w, 'Demons'), 'old title "Demons\' Crest" gone');
  ok(!anywhere(w, 'Genso Suikoden'), 'Genso Suikoden removed (YouTube)');
  ok(has(w.Tue, 'Battle Spirits', '9:30 AM'), 'Battle Spirits Tue 9:30 AM (EST)');
  ok(has(w.Thu, 'The Ramparts of Ice Season 2', '10:30 AM'), 'Ramparts S2 Thu 10:30 AM');
  ok(has(w.Fri, 'Tokyo Revengers', '12:00 PM'), 'Tokyo Revengers Fri 12:00 PM');
  ok(has(w.Sat, 'Marronnier', '10:00 AM'), 'Marronnier Sat 10:00 AM (follows JST across DST)');
  ok(has(w.Sat, 'Dreamland', '1:00 PM'), 'Dreamland Sat 1:00 PM (US-anchored)');
  ok(has(w.Sun, 'Blue Box Season 2', '3:00 AM'), 'Blue Box Sun 3:00 AM');
  ok(has(w.Sun, 'Yozakura', '3:30 AM'), 'Yozakura Sun 3:30 AM');
  ok(!has(w.Mon, 'Psyren'), 'Psyren not on Mon Nov 2 (recap week)');
  ok(!anywhere(w, 'Mao'), 'Mao no longer projecting (ended Sep 26)');
  ok(!anywhere(w, 'Link Click'), 'Link Click S3 Part 1 ended');
  ok(has(w.Fri, 'STEEL BALL RUN', '3:00 AM') && find(w.Fri, 'STEEL BALL RUN').meta.includes('Ep 7'), 'SBR Fri 3:00 AM, Ep 7');
  ok(has(w.Sun, 'TANK CHAIR', '9:30 AM'), 'TANK CHAIR Sun 9:30 AM');
  ok(has(w.Thu, 'The Exiled Heavy Knight', '11:30 AM') && find(w.Thu, 'Exiled').meta.includes('Ep 19'), 'Exiled Heavy Knight Thu 11:30 AM, Ep 19');
  ok(has(w.Fri, 'Sorry About My Little Brothers', '11:30 AM') && find(w.Fri, 'Sorry About').meta.includes('Ep 18'), 'Sorry About My Little Brothers Ep 18 (after the Sep 25 break)');
  ok(has(w.Tue, 'Red River', '12:40 PM') && find(w.Tue, 'Red River').meta.includes('Ep 18'), 'Red River Tue Ep 18');
  ok(has(w.Tue, 'Bass X Machina', '3:00 AM') && find(w.Tue, 'Bass X').meta.includes('All 6 episodes'), 'Bass X Machina batch drop Tue 3:00 AM');
  ok(has(w.Fri, 'Cardfight', 'Time TBA'), 'Cardfight!! Vanguard listed as Time TBA');
  ok(has(w.Sat, 'Case Closed', '6:30 AM') && !/Ep \d/.test(find(w.Sat, 'Case Closed').meta), 'Case Closed carryover, unnumbered');
  ok(text($('#unscheduled')).includes('Spirit Circle'), 'Spirit Circle listed as announced without a date');

  // ---- other weeks
  section('other weeks');
  await click('#wk-next'); w = week();
  console.log(`  ${w._range} — ${w._meta}`);
  ok(has(w.Mon, 'Psyren', '10:30 AM') && find(w.Mon, 'Psyren').meta.includes('Ep 5'), 'Psyren back Mon Nov 9, 10:30 AM, Ep 5');
  ok(has(w.Fri, "Devils' Crest", '7:00 AM') && find(w.Fri, "Devils' Crest").meta.includes('Ep 3'), "Devils' Crest Fri Nov 13, Ep 3");
  ok($('#nextup').hidden, 'Next up strip only on the current week');
  await click('#wk-today'); await click('#wk-prev'); w = week();
  console.log(`  ${w._range} — ${w._meta}`);
  ok(has(w.Sat, 'Marronnier', '11:00 AM'), 'Marronnier Sat Oct 31 at 11:00 AM (EDT)');
  ok(has(w.Sun, 'Overgeared', '9:30 AM'), 'Overgeared Sun Nov 1 9:30 AM (first EST day)');
  await go('#schedule:2026-12-21'); w = week();
  console.log(`  ${w._range} — ${w._meta}`);
  ok(w._range === 'Dec 21 – 27, 2026', 'hash route #schedule:YYYY-MM-DD opens that week');
  ok(has(w.Wed, 'Twisted-Wonderland', '9:45 AM'), 'Savanaclaw Wed Dec 23 9:45 AM');
  ok(!has(w.Sat, 'Dreamland'), 'Dreamland finished by Dec 26');
  await click('#wk-next');
  ok(text($('#wk-range')) === 'Dec 28 – Jan 3, 2027' && $('#wk-next').disabled, 'last page is the week holding Dec 31');
  await go('#schedule:2026-12-14');
  ok(!$('#sweep').hidden && text($('#sweep')).includes('Winter 2027'), 'sweep reminder in the week of Dec 14');
  await go('#schedule'); await click('#wk-today');

  // ---- filters and search
  section('filters and search');
  await click('#filters .chip[data-plat="Netflix"]');
  w = week();
  const all = Object.keys(w).filter(k => Array.isArray(w[k])).flatMap(k => w[k]);
  ok(all.length > 0 && all.every(e => /Netflix/.test(e.meta) || ['Daemons of the Shadow Realm', 'One Piece'].some(t => e.title.includes(t))), 'Netflix filter keeps only Netflix releases (and shows also on Netflix)');
  ok(text($('#wk-meta')).startsWith(`${all.length} release`), 'release count follows the filter');
  ok($('#clear-filters'), 'Clear filters appears when a filter is on');
  await click('#clear-filters');
  ok(!$('#clear-filters') && week().Fri.length > 5, 'Clear filters restores everything');
  await go('#shows');
  const q = $('#q'); q.value = 'devils'; q.dispatchEvent(new win.Event('input')); await sleep(200);
  let rows = $$('#dir-wrap li.dir-row');
  ok(rows.length === 1 && text(rows[0].querySelector('.dir-title')) === "Devils' Crest", 'search finds Devils\' Crest');
  q.value = ''; q.dispatchEvent(new win.Event('input')); await sleep(200);

  // ---- all shows
  section('all shows');
  rows = $$('#dir-wrap li.dir-row');
  ok(rows.length === Number(text($('.tab-n'))), 'directory lists every title');
  const groups = $$('#dir-wrap .dir-group').map(g => g.dataset.status);
  ok(groups.join() === 'airing,upcoming,tba,finished', `status groups in order (${groups.join()})`);
  ok(text($('.dir-group[data-status="tba"]')).includes('Spirit Circle'), 'Spirit Circle under Date not announced');
  ok(text($('.dir-group[data-status="finished"]')).includes('Mao'), 'Mao under Finished');
  ok(!/ · /.test(text($('#dir-wrap'))), 'no middle-dot joined meta strings in the directory');
  await click('#status-seg button[data-status="upcoming"]');
  ok($$('#dir-wrap .dir-group').length === 1, 'status filter shows one group');
  await click('#status-seg button[data-status="all"]');
  await click('.dir-row .star');
  ok(win.__arc.state.mine.size === 1 && text($('#mine-chip .n')) === '1', 'starring a show adds it to My list');
  await click('#mine-chip');
  ok($$('#dir-wrap li.dir-row').length === 1, 'My list filter shows only starred shows');
  ok(!$('#export-mine').hidden, 'Export my list appears once something is starred');
  await click('#mine-chip'); await click('.dir-row .star[aria-pressed="true"]');
  ok(win.__arc.state.mine.size === 0, 'unstarring removes it');
  let saved = null; try { saved = win.localStorage.getItem('arc.mine'); } catch (e) { /* ignore */ }
  ok(saved === '[]', 'My list persisted to localStorage');

  // ---- up next
  section('up next');
  await go('#upcoming');
  ok(!$('#upcoming').hidden && $('#schedule').hidden, 'Up next view shown, schedule hidden');
  const heads = $$('#agenda .agenda-h').map(text);
  ok(heads[0] === 'Out in the last 24 hours' && heads[1].startsWith('Today'), `agenda starts with recent, then Today (${heads.slice(0, 2).join(' / ')})`);
  ok(text($$('#agenda .agenda-day')[1].querySelector('.ag-title')) === 'A Certain Dark Item', 'first upcoming release is A Certain Dark Item');
  ok(text($('#agenda .agenda-day')).includes("Devils' Crest"), "Devils' Crest under Out in the last 24 hours");
  ok(text($$('#agenda .agenda-day')[1].querySelector('.ag-cd')) === 'in 30 min', 'countdown reads in 30 min');

  // ---- show sheet
  section('show sheet');
  await go('#show:devils-crest');
  const dlg = $('#detail');
  ok(dlg.open || dlg.hasAttribute('open'), 'deep link #show:id opens the sheet');
  ok(text($('#sh-title')) === "Devils' Crest", 'sheet title');
  const relRows = $$('#detail .rel li').map(text);
  ok(relRows[0] && relRows[0].startsWith('Fri Nov 13, 7:00 AM') && relRows[0].endsWith('Ep 3'), `next release row (${relRows[0]})`);
  ok($('#detail a.btn-primary') && /amazon\.com\/s\?k=Devils/.test($('#detail a.btn-primary').href), 'Watch on Prime Video links to a search');
  ok(/Prime exclusive/.test(text($('.sh-status'))), 'note shown under the title');
  ok(!/ · /.test(text($('#detail .facts'))), 'facts list has no middle-dot strings');
  await click('#detail [data-close]');
  ok(!(dlg.open || dlg.hasAttribute('open')) && !win.location.hash.startsWith('#show:'), 'closing clears the show hash');

  // ---- calendar export
  section('calendar export');
  const ics = win.__arc.buildIcs(['devils-crest']);
  const lines = ics.text.split('\r\n');
  const bytes = s => Buffer.byteLength(s, 'utf8');
  ok(ics.text.startsWith('BEGIN:VCALENDAR\r\nVERSION:2.0\r\n') && ics.text.endsWith('END:VCALENDAR\r\n'), 'VCALENDAR wrapper with CRLF');
  ok(!/[^\r]\n/.test(ics.text), 'every line ends in CRLF');
  ok(lines.every(l => bytes(l) <= 75), 'no physical line longer than 75 octets');
  ok(ics.count === 10, `10 upcoming releases exported (got ${ics.count})`);
  ok(ics.text.includes('DTSTART:20261113T120000Z') && ics.text.includes('SUMMARY:Devils\' Crest (Ep 3)'), 'Nov 13 7:00 AM EST = 12:00Z, Ep 3');
  const uids = ics.text.match(/^UID:.*$/gm);
  ok(uids.length === new Set(uids).size, 'UIDs are unique');
  ok(/^DTSTAMP:\d{8}T\d{6}Z$/m.test(ics.text) && /PRODID:/.test(ics.text), 'DTSTAMP and PRODID present');
  const long = 'SUMMARY:' + '★ Ultra-long title with commas, semicolons; and stars '.repeat(4);
  const folded = win.__arc.icsFold(long);
  ok(folded.split('\r\n').every(l => bytes(l) <= 75) && folded.replace(/\r\n /g, '') === long, 'folding keeps UTF-8 intact and unfolds to the original');
  const tba = win.__arc.buildIcs(['cardfight-vanguard-divinez-unmei-seisen-hen']);
  ok(tba.count === 0 || /DTSTART;VALUE=DATE:\d{8}/.test(tba.text), 'time-TBA releases export as all-day events');

  // ---- settings: time zone and clock
  section('settings');
  await go('#schedule');
  await click('#tz-btn');
  const sel = $('#tz-select');
  sel.value = 'Asia/Tokyo'; sel.dispatchEvent(new win.Event('change')); await sleep(10);
  w = week();
  ok(has(w.Sat, 'A Certain Dark Item', '12:30 AM'), 'in Tokyo, A Certain Dark Item moves to Sat 12:30 AM');
  ok(has(w.Fri, "Devils' Crest", '9:00 PM'), "in Tokyo, Devils' Crest is Fri 9:00 PM");
  ok(text($('#tz-label')) !== 'EST', 'time zone label follows the setting');
  const h24 = $('input[name="clock"][value="24"]'); h24.checked = true; h24.dispatchEvent(new win.Event('change')); await sleep(10);
  ok(has(week().Sat, 'A Certain Dark Item', '00:30'), '24-hour clock');
  sel.value = 'auto'; sel.dispatchEvent(new win.Event('change'));
  const h12 = $('input[name="clock"][value="12"]'); h12.checked = true; h12.dispatchEvent(new win.Event('change')); await sleep(10);
  ok(has(week().Fri, "Devils' Crest", '7:00 AM'), 'back to automatic Eastern time');

  // ---- guide
  section('guide');
  await go('#guide');
  ok(!$('#guide').hidden && $('#filters').parentElement.hidden, 'guide shown without the filter bar');
  await go('#g-time');
  ok(!$('#guide').hidden, 'contents links open the guide');

  // ---- cover art
  section('cover art');
  await go('#schedule');
  const artSlots = $$('#week-wrap li.ep.has-art');
  ok(artSlots.length > 40, `most slots carry cover art (${artSlots.length})`);
  ok(artSlots.every(li => /--scrim:0\.\d+/.test(li.getAttribute('style'))), 'every art slot carries its measured overlay strength');
  ok(artSlots.every(li => { const im = li.querySelector('img.ep-art'); return im && im.getAttribute('alt') === '' && im.getAttribute('referrerpolicy') === 'no-referrer' && im.getAttribute('loading') === 'lazy'; }),
     'art images are decorative, lazy, and send no referrer');
  const scrims = artSlots.map(li => Number(li.getAttribute('style').match(/--scrim:([\d.]+)/)[1]));
  ok(scrims.every(v => v >= 0.4 && v <= 0.85), `overlays within 0.40–0.85 (${Math.min(...scrims)}–${Math.max(...scrims)})`);
  ok(!find(week().Tue, 'Bass X Machina') || !$$('#week-wrap li.ep').find(li => text(li.querySelector('.ep-title')) === 'Bass X Machina').classList.contains('has-art'),
     'a show with no AniList entry keeps the plain slot');
  const victim = artSlots.find(li => text(li.querySelector('.ep-title')) === 'A Certain Dark Item');
  victim.querySelector('img.ep-art').dispatchEvent(new win.Event('error'));
  ok(!victim.classList.contains('has-art') && !victim.querySelector('img'), 'an image that fails to load falls back to the plain slot');
  await click('#wk-next'); await click('#wk-today');
  const again = $$('#week-wrap li.ep').find(li => text(li.querySelector('.ep-title')) === 'A Certain Dark Item');
  ok(again && !again.classList.contains('has-art'), 'a failed image is not retried on re-render');
  await click('#tz-btn');
  const artToggle = $('#art-toggle');
  ok(artToggle.checked, 'cover art is on by default');
  artToggle.checked = false; artToggle.dispatchEvent(new win.Event('change')); await sleep(10);
  ok(doc.documentElement.classList.contains('no-art'), 'turning art off switches the page to plain slots');
  artToggle.checked = true; artToggle.dispatchEvent(new win.Event('change')); await sleep(10);
  ok(!doc.documentElement.classList.contains('no-art'), 'and back on');
  await go('#show:devils-crest');
  ok($('#detail .sh-hero .thumb.lg img'), 'show sheet leads with the cover');
  const al = [...doc.querySelectorAll('#detail .links a')].find(a => text(a) === 'AniList');
  ok(al && /^https:\/\/anilist\.co\/anime\/\d+$/.test(al.href), `AniList link goes straight to the show (${al && al.href})`);
  await click('#detail [data-close]');
  await go('#upcoming');
  ok($$('#agenda .ag .thumb img').length > 5, 'Up next rows show poster thumbnails');
  await go('#shows');
  ok($$('#dir-wrap .dir-row .thumb img').length > 100, 'All shows rows show poster thumbnails');
  await go('#guide');
  ok(/AniList/.test(text($('#guide'))), 'Guide credits AniList for cover art');

  // ---- embedded previews (file viewers, mail apps)
  // Inside an iframe built from the file's contents, a bare "#view" link resolves against
  // the HOST page and navigates the preview away, and history.pushState throws. So every
  // in-page link must be handled in script (default prevented), views must switch without
  // waiting for hashchange, and nothing may depend on the URL actually changing.
  section('embedded preview safety');
  await go('#schedule');
  const cancelled = el => { const ev = new win.MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }); el.dispatchEvent(ev); return ev.defaultPrevented; };
  const linkKinds = {
    'tab': '#tab-shows', 'brand': '.brand', 'footer link': '.foot a[href="#guide"]', 'skip link': '.skip',
    'schedule entry': '#week-wrap a.ep-btn', 'Next up card': '#nextup a.nu', 'guide contents': '.toc a',
  };
  for (const [kind, sel] of Object.entries(linkKinds)) {
    const el = $(sel);
    ok(el && cancelled(el), `${kind} click is handled in script, not by the browser`);
    if (isOpen($('#detail'))) await click('#detail [data-close]');
    await go('#schedule');
  }
  $('#tab-upcoming').click();
  ok(!$('#upcoming').hidden && $('#schedule').hidden, 'a tab switches views immediately, without waiting for hashchange');
  $('#tab-schedule').click();
  const realPush = win.history.pushState, realReplace = win.history.replaceState;
  win.history.pushState = win.history.replaceState = () => { throw new win.DOMException('Blocked in sandboxed preview', 'SecurityError'); };
  const errsBefore = errors.length;
  $('#tab-guide').click();
  ok(!$('#guide').hidden, 'tabs still work when the browser refuses URL changes');
  $('#tab-shows').click();
  $('#dir-wrap a.dir-link').click();
  ok(isOpen($('#detail')) && !$('#shows').hidden, 'show sheet still opens when the browser refuses URL changes');
  $('#detail [data-close]').click();
  ok(!isOpen($('#detail')), 'and closes');
  ok(errors.length === errsBefore, 'no errors when history changes are refused');
  win.history.pushState = realPush; win.history.replaceState = realReplace;
  $('#tab-schedule').click();

  ok(errors.length === 0, 'no script errors after interaction: ' + errors.join(' | '));
  console.log(`\n${passes} passed, ${fails} failed`);
  win.close();
  process.exit(fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
