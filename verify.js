// jsdom check of the built calendar. Usage: node verify.js [html] [YYYY-MM-DD "today"]
// Executes the page with a pinned clock, walks the weekly view, and asserts the
// specific placements this sweep changed, plus the no-JS static fallback.
const fs = require('fs');
const { JSDOM, VirtualConsole } = require('jsdom');

const file = process.argv[2] || 'anime-calendar-2026.html';
const todayIso = process.argv[3] || '2026-11-06';
const html = fs.readFileSync(file, 'utf8');

let fails = 0, passes = 0;
const ok = (cond, msg) => { if (cond) { passes++; } else { fails++; console.log('  FAIL:', msg); } };

// ---- no-JS fallback: static cards are in the markup itself
{
  const dom = new JSDOM(html);              // scripts NOT run
  const cards = dom.window.document.querySelectorAll('#grid article.card');
  const m = html.match(/<b id="s-titles">(\d+)<\/b>/);
  console.log(`static fallback: ${cards.length} cards`);
  ok(cards.length > 100, 'static fallback has cards');
}

// ---- scripted run with a pinned "today"
const errors = [];
const vc = new VirtualConsole();
vc.on('jsdomError', e => errors.push(String(e && e.message || e)));
vc.on('error', e => errors.push(String(e)));
const [Y, M, D] = todayIso.split('-').map(Number);
const dom = new JSDOM(html, {
  runScripts: 'dangerously', pretendToBeVisual: true, virtualConsole: vc,
  beforeParse(win) {
    const Real = win.Date, fixed = new Real(Y, M - 1, D, 10, 0, 0).getTime();
    class FakeDate extends Real {
      constructor(...a) { if (a.length === 0) super(fixed); else super(...a); }
      static now() { return fixed; }
    }
    win.Date = FakeDate;
  },
});
const { document: doc } = dom.window;
ok(errors.length === 0, 'no script errors: ' + errors.join(' | '));

doc.getElementById('view-weekly').click();
const today = () => doc.getElementById('wk-today').click();
const next = () => doc.getElementById('wk-next').click();
const prev = () => doc.getElementById('wk-prev').click();

function week() {
  const out = {};
  doc.querySelectorAll('#cal section.day').forEach(sec => {
    const name = sec.querySelector('.dname').textContent;
    out[name] = sec.querySelector('.day-list').textContent.replace(/\s+/g, ' ');
  });
  out._range = doc.getElementById('wk-range').textContent;
  out._count = doc.getElementById('wk-count').textContent;
  return out;
}
// "<title> ... <time>" within one day's text — the slot row prints time before or after
// the title depending on layout, so accept either order within a short window.
function has(dayText, title, time) {
  const i = dayText.indexOf(title);
  if (i < 0) return false;
  if (!time) return true;
  const win = dayText.slice(Math.max(0, i - 40), i + title.length + 160);
  return win.includes(time);
}

today();
let w = week();
console.log(`this week: ${w._range} — ${w._count}`);
ok(has(w.Fri, "Demons' Crest", '7:00 AM'), "Demons' Crest on Fri Nov 6 at 7:00 AM");
ok(!has(w.Thu, "Demons' Crest"), "Demons' Crest NOT on Thursday");
ok(!JSON.stringify(w).includes('Genso Suikoden'), 'Genso Suikoden removed');
ok(has(w.Tue, 'Battle Spirits', '9:30 AM'), 'Battle Spirits Tue 9:30 AM (EST)');
ok(has(w.Thu, 'The Ramparts of Ice Season 2', '10:30 AM'), 'Ramparts S2 Thu 10:30 AM');
ok(has(w.Fri, 'Tokyo Revengers', '12:00 PM'), 'Tokyo Revengers Fri 12:00 PM');
ok(has(w.Sat, 'Marronnier', '10:00 AM'), 'Marronnier Sat 10:00 AM');
ok(has(w.Sat, 'Dreamland', '1:00 PM'), 'Dreamland Sat 1:00 PM');
ok(!has(w.Fri, 'Dreamland'), 'Dreamland NOT on Friday');
ok(has(w.Sun, 'Blue Box Season 2', '3:00 AM'), 'Blue Box Sun 3:00 AM');
ok(has(w.Sun, 'Yozakura', '3:30 AM'), 'Yozakura Sun 3:30 AM');
ok(!has(w.Mon, 'Psyren'), 'Psyren not on Mon Nov 2 (recap week)');
ok(!JSON.stringify(w).includes('Mao '), 'MAO no longer projecting');
ok(!JSON.stringify(w).includes('Link Click'), 'Link Click S3 Part 1 ended');
ok(has(w.Fri, 'STEEL BALL RUN', '3:00 AM'), 'SBR Fri 3:00 AM');
ok(has(w.Sun, 'TANK CHAIR', '9:30 AM'), 'TANK CHAIR Sun 9:30 AM');
ok(has(w.Thu, 'The Exiled Heavy Knight', '11:30 AM'), 'Exiled Heavy Knight Thu 11:30 AM (Ben-observed 12:30 EDT)');
ok(has(w.Fri, 'Cardfight', ''), 'Cardfight!! Vanguard (TBA) on Fri');

next(); w = week();
console.log(`next week: ${w._range} — ${w._count}`);
ok(has(w.Mon, 'Psyren', '10:30 AM'), 'Psyren back Mon Nov 9 at 10:30 AM');
ok(has(w.Fri, "Demons' Crest", '7:00 AM'), "Demons' Crest weekly Fri Nov 13");

// jump to Dec 21 week
for (let i = 0; i < 6; i++) next();
w = week();
console.log(`Dec week: ${w._range} — ${w._count}`);
ok(has(w.Wed, 'Twisted-Wonderland', '9:45 AM'), 'Savanaclaw Wed Dec 23 9:45 AM');
ok(!has(w.Sat, 'Dreamland'), 'Dreamland finished by Dec 26 (10 eps → Dec 19)');

// weeks run Mon–Sun, so Tue Nov 3 is in the current week
today(); w = week();
ok(has(w.Tue, 'Bass X Machina', '3:00 AM'), 'Bass X Machina Tue Nov 3 3:00 AM');
prev(); w = week();
console.log(`last week: ${w._range} — ${w._count}`);
ok(has(w.Sat, 'Marronnier', '11:00 AM'), 'Marronnier Sat Oct 31 still 11:00 AM (EDT)');
ok(has(w.Sun, 'Overgeared', '9:30 AM'), 'Overgeared Sun Nov 1 9:30 AM (EST day)');

// undated TBA list mentions Spirit Circle somewhere on the page (browse view card)
doc.getElementById('view-browse').click();
ok(doc.getElementById('grid').textContent.includes('Spirit Circle'), 'Spirit Circle card present');

console.log(`\n${passes} passed, ${fails} failed`);
process.exit(fails ? 1 : 0);
