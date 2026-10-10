'use strict';
/* כדורגל באירופה — בוחרים תאריכים, רואים איפה משחקים: לפי מדינה או על המפה */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } }
};

/* ---------- dates ---------- */
const IL_TZ = 'Asia/Jerusalem';
const todayIL = () => new Intl.DateTimeFormat('en-CA', { timeZone: IL_TZ }).format(new Date());
const fmtIL = new Intl.DateTimeFormat('he-IL', { timeZone: IL_TZ, hour: '2-digit', minute: '2-digit', hour12: false });
const fmtILDay = new Intl.DateTimeFormat('en-CA', { timeZone: IL_TZ });
const fmtDay = new Intl.DateTimeFormat('he-IL', { timeZone: 'UTC', weekday: 'long', day: 'numeric', month: 'long' });
const fmtShort = new Intl.DateTimeFormat('he-IL', { timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'numeric' });
const MONTHS = ['ינואר', 'פברואר', 'מרץ', 'אפריל', 'מאי', 'יוני', 'יולי', 'אוגוסט', 'ספטמבר', 'אוקטובר', 'נובמבר', 'דצמבר'];
const MON3 = ['ינו׳', 'פבר׳', 'מרץ', 'אפר׳', 'מאי', 'יוני', 'יולי', 'אוג׳', 'ספט׳', 'אוק׳', 'נוב׳', 'דצמ׳'];
const utc = ld => new Date(ld + 'T12:00:00Z');
const addDays = (ld, n) => { const d = utc(ld); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
const daysBetween = (a, b) => Math.round((utc(b) - utc(a)) / 864e5);
const dm = ld => { const [, m, d] = ld.split('-'); return +d + '.' + +m; };
const dow = ld => utc(ld).getUTCDay();
const isWeekend = ld => [5, 6, 0].includes(dow(ld));
function rangeLabel(a, b) {
  const [ya, ma, da] = a.split('-').map(Number), [yb, mb, db] = b.split('-').map(Number);
  if (a === b) return da + ' ב' + MONTHS[ma - 1];
  if (ya === yb && ma === mb) return da + '–' + db + ' ב' + MONTHS[ma - 1];
  return da + ' ' + MON3[ma - 1] + ' – ' + db + ' ' + MON3[mb - 1] + (ya !== yb ? ' ' + yb : '');
}

/* ---------- helpers ---------- */
const flagImg = (c, cls = '') => c && c.flag
  ? `<img class="flag ${cls}" src="https://flagcdn.com/w160/${c.flag}.png" alt="" loading="lazy" onerror="this.style.visibility='hidden'">`
  : `<span class="flag ${cls}"></span>`;
const LG_COLOR = { 'uefa.champions': 'var(--ucl)', 'uefa.europa': 'var(--uel)', 'uefa.europa.conf': 'var(--uecl)', 'uefa.nations': 'var(--unl)' };
const isEuro = lg => lg.startsWith('uefa.');
const REGIONS = [['הכול', 'כל אירופה'], ['מערב', 'מערב'], ['מרכז', 'מרכז'], ['דרום', 'דרום'], ['צפון', 'צפון'], ['מזרח', 'מזרח']];
const PAGE = 120;
const ICON = {
  cal: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>',
  pin: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 21s-7-6.2-7-12a7 7 0 0 1 14 0c0 5.8-7 12-7 12z"/><circle cx="12" cy="9" r="2.5"/></svg>'
};

let DB = null, BY_COUNTRY = {}, COORDS = {}, TEAM_PT = {};
const S = {
  from: null, to: null, region: 'הכול', cq: '',
  lg: new Set(), city: '', q: '', okOnly: false, weOnly: false, past: false, shown: PAGE,
  mapKind: 'all', mapSel: null
};
let favs = new Set(store.get('ef_favs', []));

/* ---------- data ---------- */
async function load() {
  const [games, coords] = await Promise.all([
    fetch('data/games.json', { cache: 'no-cache' }).then(r => r.json()),
    fetch('data/coords.json', { cache: 'no-cache' }).then(r => r.ok ? r.json() : {}).catch(() => ({}))
  ]);
  DB = games; COORDS = coords;
  for (const g of DB.games) {
    (BY_COUNTRY[g.c] ||= []).push(g);
    const p = COORDS[g.v + '|' + g.city + '|' + g.c];
    if (p && !TEAM_PT[g.h]) TEAM_PT[g.h] = p;
  }
  const t = todayIL();
  S.from = t > DB.range[0] ? t : DB.range[0];
  S.to = addDays(S.from, 13);
  footer();
  route();
}
const isPast = g => new Date(g.t).getTime() < Date.now() - 2.2 * 3600e3;
const inRange = g => g.ld >= S.from && g.ld <= S.to;
const visible = g => inRange(g) && (S.past || !isPast(g));
const leagueName = slug => DB.leagues[slug]?.he || slug;
const ptOf = g => COORDS[g.v + '|' + g.city + '|' + g.c] || TEAM_PT[g.h] || null;

/* ---------- routing ---------- */
let current = { view: 'home' };
function parseHash() {
  const h = decodeURIComponent(location.hash.slice(1) || '/');
  const [path, qs] = h.split('?');
  const p = new URLSearchParams(qs || '');
  if (p.get('from') && p.get('to')) { S.from = p.get('from'); S.to = p.get('to'); }
  S.lg = new Set((p.get('lg') || '').split(',').filter(Boolean));
  S.city = p.get('city') || '';
  const m = path.match(/^\/c\/(.+)$/);
  if (m) return { view: 'country', key: m[1] };
  if (path === '/map') return { view: 'map' };
  return { view: 'home' };
}
function hashFor(r) {
  const p = new URLSearchParams({ from: S.from, to: S.to });
  if (r.view === 'country') { if (S.lg.size) p.set('lg', [...S.lg].join(',')); if (S.city) p.set('city', S.city); }
  const base = r.view === 'country' ? '#/c/' + encodeURIComponent(r.key) : r.view === 'map' ? '#/map' : '#/';
  return base + '?' + p.toString();
}
const syncHash = () => history.replaceState(null, '', hashFor(current));
function route() {
  if (!DB) return;
  const prev = current;
  current = parseHash();
  if (current.view !== prev.view || current.key !== prev.key) {
    S.shown = PAGE; S.q = ''; S.okOnly = false; S.weOnly = false; S.mapSel = null;
    window.scrollTo(0, 0);
  }
  $$('.views a').forEach(a => {
    const on = a.dataset.view === (current.view === 'map' ? 'map' : 'home');
    on ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current');
    a.href = a.dataset.view === 'map' ? hashFor({ view: 'map' }) : hashFor({ view: 'home' });
  });
  renderTrip();
  render();
}
function render() {
  if (current.view !== 'map') destroyMap();
  if (current.view === 'country' && DB.countries[current.key]) renderCountry(current.key);
  else if (current.view === 'map') renderMap();
  else renderHome();
}
addEventListener('hashchange', route);
function setRange(a, b) {
  S.from = a; S.to = b; S.shown = PAGE; S.mapSel = null;
  syncHash(); renderTrip(); render();
}

/* ---------- trip ticket + quick ranges ---------- */
function nextWeekend(t) {
  const d = dow(t);
  const fri = d === 6 ? addDays(t, -1) : d === 0 ? addDays(t, -2) : addDays(t, (5 - d + 7) % 7);
  return [fri < t ? t : fri, addDays(fri, 2)];
}
function renderTrip() {
  const n = daysBetween(S.from, S.to) + 1;
  $('#rangeText').textContent = rangeLabel(S.from, S.to);
  $('#rangeSub').textContent = (n === 1 ? 'יום אחד' : n + ' ימים') + ' · לשינוי התאריכים';
  const t = todayIL(), w1 = nextWeekend(t), w2 = [addDays(w1[0], 7), addDays(w1[1], 7)];
  const q = [['הסופ״ש הקרוב', ...w1], ['הסופ״ש שאחריו', ...w2], ['שבוע', t, addDays(t, 6)], ['חודש', t, addDays(t, 29)]];
  $('#quick').innerHTML = q.map(([l, a, b]) => `<button class="chip" data-range="${a},${b}" aria-pressed="${S.from === a && S.to === b}">${l}</button>`).join('');
}
document.addEventListener('click', e => {
  const b = e.target.closest('[data-range]');
  if (b) { const [a, c] = b.dataset.range.split(','); setRange(a, c); }
});

/* ---------- calendar (one popover, start then end) ---------- */
const CAL = { open: false, start: null, end: null, hover: null, offset: 0 };
function calMonths() {
  const out = []; let [y, m] = DB.range[0].split('-').map(Number);
  const [ey, em] = DB.range[1].split('-').map(Number);
  while (y < ey || (y === ey && m <= em)) { out.push([y, m]); m++; if (m > 12) { m = 1; y++; } }
  return out;
}
function dayDensity() {
  const src = current.view === 'country' ? (BY_COUNTRY[current.key] || []) : DB.games;
  const n = {}; src.forEach(g => { n[g.ld] = (n[g.ld] || 0) + 1; });
  return n;
}
function openCal() {
  CAL.open = true; CAL.start = null; CAL.end = null; CAL.hover = null;
  const months = calMonths(), [y, m] = S.from.split('-').map(Number);
  CAL.offset = Math.max(0, months.findIndex(([a, b]) => a === y && b === m));
  $('#cal').hidden = false; $('#rangeBtn').setAttribute('aria-expanded', 'true');
  drawCal();
}
function closeCal() { CAL.open = false; $('#cal').hidden = true; $('#rangeBtn').setAttribute('aria-expanded', 'false'); }
function drawCal() {
  const months = calMonths(), dens = dayDensity(), max = Math.max(1, ...Object.values(dens));
  const t = todayIL(), min = t > DB.range[0] ? t : DB.range[0];
  const show = months.slice(CAL.offset, CAL.offset + 2);
  const a = CAL.start || S.from, b = CAL.start ? (CAL.end || (CAL.hover && CAL.hover >= CAL.start ? CAL.hover : CAL.start)) : S.to;
  $('#calHint').textContent = CAL.start ? 'יציאה: ' + dm(CAL.start) + ' · עכשיו בוחרים יום חזרה' : 'בוחרים יום יציאה';
  $('#calPrev').disabled = CAL.offset === 0;
  $('#calNext').disabled = CAL.offset >= months.length - 1;
  $('#calMonths').innerHTML = show.map(([y, m]) => {
    const first = new Date(Date.UTC(y, m - 1, 1)), days = new Date(Date.UTC(y, m, 0)).getUTCDate();
    let cells = '<span></span>'.repeat(first.getUTCDay());
    for (let d = 1; d <= days; d++) {
      const ld = `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`, n = dens[ld] || 0;
      const off = ld < min || ld > DB.range[1];
      const cls = [ld === a && 's', ld === b && 'e', ld > a && ld < b && 'in', ld === t && 'today'].filter(Boolean).join(' ');
      const w = n ? Math.round(6 + 22 * Math.min(1, n / max)) : 0;
      cells += `<button class="d ${cls}" data-day="${ld}" ${off ? 'disabled' : ''} aria-label="${fmtDay.format(utc(ld))}, ${n} משחקים">${d}${w ? `<i style="width:${w}px"></i>` : '<i style="width:0"></i>'}</button>`;
    }
    return `<div class="month"><h3>${MONTHS[m - 1]} ${y}</h3><div class="wdays">${['א', 'ב', 'ג', 'ד', 'ה', 'ו', 'ש'].map(x => `<span>${x}</span>`).join('')}</div><div class="days">${cells}</div></div>`;
  }).join('');
}
$('#rangeBtn').onclick = e => { e.stopPropagation(); CAL.open ? closeCal() : openCal(); };
$('#calClose').onclick = closeCal;
$('#calPrev').onclick = () => { CAL.offset = Math.max(0, CAL.offset - 1); drawCal(); };
$('#calNext').onclick = () => { CAL.offset = Math.min(calMonths().length - 1, CAL.offset + 1); drawCal(); };
$('#calMonths').addEventListener('click', e => {
  const d = e.target.closest('[data-day]'); if (!d || d.disabled) return;
  const ld = d.dataset.day;
  if (!CAL.start || ld < CAL.start) { CAL.start = ld; drawCal(); return; }
  closeCal(); setRange(CAL.start, ld);
});
$('#calMonths').addEventListener('mouseover', e => {
  const d = e.target.closest('[data-day]'); if (!d || !CAL.start || CAL.hover === d.dataset.day) return;
  CAL.hover = d.dataset.day; drawCal();
});
document.addEventListener('click', e => { if (CAL.open && e.target.isConnected && !e.target.closest('#cal') && !e.target.closest('#rangeBtn')) closeCal(); });
addEventListener('keydown', e => { if (e.key === 'Escape') { if (CAL.open) closeCal(); else if ($('#favDrawer').classList.contains('open')) openDrawer(false); } });

/* ---------- home: countries ---------- */
function renderHome() {
  document.title = 'כדורגל באירופה';
  const rows = Object.entries(DB.countries).map(([key, c]) => {
    const list = (BY_COUNTRY[key] || []).filter(visible);
    return { key, c, n: list.length, next: list[0] };
  }).filter(r => (S.region === 'הכול' || r.c.region === S.region) && (!S.cq || (r.c.he + ' ' + r.key).toLowerCase().includes(S.cq.toLowerCase())))
    .sort((a, b) => (a.key === 'TBD') - (b.key === 'TBD') || b.n - a.n || a.c.he.localeCompare(b.c.he, 'he'));
  const max = Math.max(1, ...rows.map(r => r.n)), total = rows.reduce((s, r) => s + r.n, 0), active = rows.filter(r => r.n).length;
  $('#app').innerHTML = `
    <div class="pageHead"><div><h1>לאן טסים?</h1>
      <p>${total.toLocaleString('he-IL')} משחקים ב־${active} מדינות בתאריכים שבחרת. בוחרים מדינה ורואים את כל המשחקים בה, או עוברים למפה ומחפשים משחקים קרובים בין מדינות.</p></div>
      <a class="btn solid" href="${hashFor({ view: 'map' })}" style="text-decoration:none">פתיחת המפה</a></div>
    <div class="tools"><input class="search" id="cq" type="search" placeholder="חיפוש מדינה" value="${esc(S.cq)}" aria-label="חיפוש מדינה">
      <div class="seg">${REGIONS.map(([k, l]) => `<button class="chip" data-region="${k}" aria-pressed="${S.region === k}">${l}</button>`).join('')}</div></div>
    <div class="countries">${rows.map(r => {
      const href = '#/c/' + encodeURIComponent(r.key) + '?from=' + S.from + '&to=' + S.to;
      return `<a class="country ${r.n ? '' : 'none'}" href="${href}">${flagImg(r.c)}<span class="name">${esc(r.c.he)}</span>
        <span class="cnt" aria-label="${r.n} משחקים">${r.n}</span><span class="meter"><i style="width:${Math.round(100 * r.n / max)}%"></i></span>
        <span class="next">${r.next ? 'הבא ב־' + dm(r.next.ld) + ': <bdi>' + esc(r.next.h) + '</bdi> – <bdi>' + esc(r.next.a) + '</bdi>' : 'אין משחקים בתאריכים האלה'}</span></a>`;
    }).join('') || '<div class="empty">לא נמצאה מדינה בשם הזה.</div>'}</div>`;
  const cq = $('#cq');
  cq.oninput = () => { S.cq = cq.value; const p = cq.selectionStart; renderHome(); const n = $('#cq'); n.focus(); n.setSelectionRange(p, p); };
  $$('[data-region]').forEach(b => b.onclick = () => { S.region = b.dataset.region; renderHome(); });
}

/* ---------- country page ---------- */
function filtered(key) {
  const q = S.q.trim().toLowerCase();
  return (BY_COUNTRY[key] || []).filter(visible).filter(g =>
    (!S.lg.size || S.lg.has(g.lg)) && (!S.city || g.city === S.city) && (!S.okOnly || g.ok) && (!S.weOnly || isWeekend(g.ld)) &&
    (!q || (g.h + ' ' + g.a + ' ' + g.v + ' ' + g.city).toLowerCase().includes(q)));
}
function renderCountry(key) {
  const c = DB.countries[key], all = BY_COUNTRY[key] || [], base = all.filter(visible);
  document.title = c.he + ' · כדורגל באירופה';
  const lgCount = {}, cityCount = {};
  base.forEach(g => { lgCount[g.lg] = (lgCount[g.lg] || 0) + 1; if (g.city) cityCount[g.city] = (cityCount[g.city] || 0) + 1; });
  const okN = base.filter(g => g.ok).length;
  const wk = {};
  all.filter(g => !isPast(g) && isWeekend(g.ld)).forEach(g => { const f = addDays(g.ld, -((dow(g.ld) + 2) % 7)); wk[f] = (wk[f] || 0) + 1; });
  const wkList = Object.entries(wk).sort((a, b) => a[0].localeCompare(b[0])).slice(0, 14);
  const ns = wkList.map(x => x[1]).sort((a, b) => a - b), med = ns[Math.floor(ns.length / 2)] || 0;
  $('#app').innerHTML = `
    <a class="back" href="${hashFor({ view: 'home' })}">כל המדינות</a>
    <div class="pageHead"><div><div class="cTitle">${flagImg(c, 'lg')}<h1>${esc(c.he)}</h1></div>
      <p class="facts"><b>${base.length}</b> משחקים בתאריכים שבחרת, ב־<b>${Object.keys(cityCount).length}</b> ערים. ל־<b>${okN}</b> מהם יש כבר מועד סופי.</p></div>
      <button class="btn" id="shareCountry">שיתוף הדף</button></div>
    ${wkList.length ? `<div class="weekends" aria-label="סופי שבוע">${wkList.map(([f, n]) => {
      const sun = addDays(f, 2);
      return `<button class="wk ${n >= Math.max(4, med * 1.25) ? 'hot' : ''}" data-range="${f},${sun}" aria-pressed="${S.from === f && S.to === sun}"><b>${n}</b><span>${dm(f)}–${dm(sun)}</span></button>`;
    }).join('')}</div>` : ''}
    <div class="seg" style="margin-bottom:10px">
      <button class="chip" data-lg="" aria-pressed="${!S.lg.size}">כל המפעלים<small>${base.length}</small></button>
      ${Object.entries(lgCount).sort((a, b) => b[1] - a[1]).map(([lg, n]) => `<button class="chip" data-lg="${esc(lg)}" aria-pressed="${S.lg.has(lg)}">${esc(leagueName(lg))}<small>${n}</small></button>`).join('')}
    </div>
    <div class="filters">
      <input class="search" id="q" type="search" placeholder="חיפוש קבוצה או אצטדיון" value="${esc(S.q)}" aria-label="חיפוש קבוצה או אצטדיון">
      <select id="city" aria-label="עיר"><option value="">כל הערים</option>${Object.entries(cityCount).sort((a, b) => b[1] - a[1]).map(([ci, n]) => `<option value="${esc(ci)}" ${S.city === ci ? 'selected' : ''}>${esc(ci)} (${n})</option>`).join('')}</select>
      <button class="toggle" id="weOnly" aria-pressed="${S.weOnly}">רק בסופ״ש</button>
      <button class="toggle" id="okOnly" aria-pressed="${S.okOnly}">רק מועד סופי</button>
      <button class="toggle" id="past" aria-pressed="${S.past}">כולל משחקים שהיו</button>
    </div>
    <div id="list"></div>`;
  $('#shareCountry').onclick = () => share(c.he + ' – משחקי כדורגל', location.href);
  $$('[data-lg]').forEach(b => b.onclick = () => {
    const v = b.dataset.lg; if (!v) S.lg.clear(); else S.lg.has(v) ? S.lg.delete(v) : S.lg.add(v);
    S.shown = PAGE; syncHash(); renderCountry(key);
  });
  $('#city').onchange = e => { S.city = e.target.value; S.shown = PAGE; syncHash(); renderList(key); };
  $('#q').oninput = e => { S.q = e.target.value; S.shown = PAGE; renderList(key); };
  for (const id of ['weOnly', 'okOnly', 'past']) $('#' + id).onclick = () => { S[id] = !S[id]; S.shown = PAGE; renderCountry(key); };
  renderList(key);
}
function renderList(key) {
  const list = filtered(key), shown = list.slice(0, S.shown), days = [];
  for (const g of shown) { const l = days.at(-1); l && l.ld === g.ld ? l.games.push(g) : days.push({ ld: g.ld, games: [g] }); }
  const per = {}; list.forEach(g => per[g.ld] = (per[g.ld] || 0) + 1);
  const active = S.lg.size || S.city || S.q || S.okOnly || S.weOnly;
  $('#list').innerHTML = `<div class="count"><span>${list.length} משחקים</span>${active ? '<button class="link" id="clearF">ניקוי הסינון</button>' : ''}</div>
    ${days.map(d => `<section class="day"><div class="dayHead"><h2>${fmtDay.format(utc(d.ld))}</h2>${isWeekend(d.ld) ? '<span class="tag">סופ״ש</span>' : ''}<span class="n">${per[d.ld]} משחקים</span></div>
      ${d.games.map(gameRow).join('')}</section>`).join('') || '<div class="empty">אין משחקים שמתאימים לסינון. אפשר להרחיב את התאריכים או לנקות את הסינון.</div>'}
    ${list.length > S.shown ? `<button class="btn more" id="more">עוד ${Math.min(PAGE, list.length - S.shown)} משחקים</button>` : ''}`;
  $('#more') && ($('#more').onclick = () => { S.shown += PAGE; renderList(key); });
  $('#clearF') && ($('#clearF').onclick = () => { S.lg.clear(); S.city = ''; S.q = ''; S.okOnly = S.weOnly = false; syncHash(); renderCountry(key); });
}
function statusOf(g) {
  if (g.pp) return '<span class="st pp">נדחה</span>';
  if (g.live) return '<span class="st live">משחק חי' + (g.s ? ' ' + g.s[0] + '–' + g.s[1] : '') + '</span>';
  if (isPast(g)) return '';
  return g.ok ? '<span class="st ok">מועד סופי</span>' : '<span class="st est">מועד משוער</span>';
}
function timeBlock(g) {
  if (g.s && !g.live) return `<b class="res">${g.s[0]}–${g.s[1]}</b><small>תוצאה סופית</small>`;
  if (g.nt) return '<span class="tbd">השעה<br>טרם נקבעה</span>';
  const il = fmtIL.format(new Date(g.t)), ild = fmtILDay.format(new Date(g.t));
  return `<b>${g.lt}</b><small>${il} בישראל${ild !== g.ld ? ' (' + dm(ild) + ')' : ''}</small>`;
}
function gameRow(g) {
  const fav = favs.has(g.id), past = isPast(g);
  const place = [g.v, g.city].filter(Boolean).join(', ') || 'האצטדיון טרם פורסם';
  const mapQ = encodeURIComponent([g.v, g.city, g.c !== 'TBD' ? g.c : ''].filter(Boolean).join(', '));
  const src = [g.note ? esc(g.note) : '', g.src ? `<a href="${esc(g.src)}" target="_blank" rel="noopener">לוח המשחקים הרשמי</a>` : '',
    g.site ? `<a href="${esc(g.site)}" target="_blank" rel="noopener">האתר של הקבוצה המארחת</a>` : ''].filter(Boolean).join(' · ');
  return `<article class="game ${past ? 'past' : ''}">
    <div class="when">${timeBlock(g)}</div>
    <div class="who">
      <div class="team">${g.hl ? `<img src="${esc(g.hl)}" alt="" loading="lazy" onerror="this.remove()">` : ''}<span dir="auto">${esc(g.h)}</span></div>
      <div class="team">${g.al ? `<img src="${esc(g.al)}" alt="" loading="lazy" onerror="this.remove()">` : ''}<span dir="auto">${esc(g.a)}</span></div>
      <div class="meta"><span class="lg" style="--dot:${LG_COLOR[g.lg] || '#94a3b8'}">${esc(leagueName(g.lg))}</span>${statusOf(g)}<span>${esc(place)}</span></div>
    </div>
    <div class="acts">
      <button class="ib ${fav ? 'on' : ''}" data-fav="${esc(g.id)}" aria-label="${fav ? 'הסרה מהרשימה' : 'שמירה ברשימה'}" title="${fav ? 'הסרה מהרשימה' : 'שמירה ברשימה'}">${fav ? '♥' : '♡'}</button>
      ${!past && !g.nt ? `<a class="ib" href="${gcal(g)}" target="_blank" rel="noopener" title="הוספה ליומן Google" aria-label="הוספה ליומן">${ICON.cal}</a>` : ''}
      ${mapQ ? `<a class="ib" href="https://www.google.com/maps/search/?api=1&query=${mapQ}" target="_blank" rel="noopener" title="פתיחה במפות Google" aria-label="פתיחה במפות Google">${ICON.pin}</a>` : ''}
    </div>
    ${src ? `<details class="src"><summary>מקור המועד</summary>${src}</details>` : ''}
  </article>`;
}

/* ---------- map ---------- */
let MAP = null, CLUSTER = null, GROUPS = {}, MARKERS = {};
function destroyMap() { if (MAP) { MAP.remove(); MAP = null; CLUSTER = null; } }
const km = (a, b) => { const R = 6371, r = x => x * Math.PI / 180, dLa = r(b[0] - a[0]), dLo = r(b[1] - a[1]);
  const h = Math.sin(dLa / 2) ** 2 + Math.cos(r(a[0])) * Math.cos(r(b[0])) * Math.sin(dLo / 2) ** 2; return 2 * R * Math.asin(Math.sqrt(h)); };
function mapGames() {
  return DB.games.filter(g => visible(g) && (S.mapKind === 'all' || (S.mapKind === 'eu') === isEuro(g.lg)));
}
function renderMap() {
  document.title = 'מפת משחקים · כדורגל באירופה';
  const games = mapGames();
  GROUPS = {};
  let noPt = 0;
  for (const g of games) {
    const p = ptOf(g); if (!p) { noPt++; continue; }
    const k = p[0].toFixed(3) + ',' + p[1].toFixed(3);
    (GROUPS[k] ||= { k, p, games: [] }).games.push(g);
  }
  if (!window.L) {
    $('#app').innerHTML = '<div class="empty">המפה לא נטענה. בודקים את החיבור לאינטרנט ומרעננים את הדף.</div>'; return;
  }
  if (!MAP) {
    $('#app').innerHTML = `
      <div class="pageHead mapHead"><div><h1>מפת המשחקים</h1><p>כל המשחקים בתאריכים שבחרת. לחיצה על אצטדיון מציגה את המשחקים בו ואת המשחקים הקרובים אליו, גם במדינות שכנות.</p></div>
        <div class="seg">${[['all', 'כל המשחקים'], ['eu', 'מפעלים אירופיים'], ['dom', 'ליגות מקומיות']].map(([k, l]) => `<button class="chip" data-kind="${k}" aria-pressed="${S.mapKind === k}">${l}</button>`).join('')}</div></div>
      <div class="mapWrap"><div class="panel"><div class="panelHead" id="pHead"></div><div class="panelBody" id="pBody"></div></div><div id="map"></div></div>
      <p class="mapNote" id="mapNote"></p>`;
    $$('[data-kind]').forEach(b => b.onclick = () => { S.mapKind = b.dataset.kind; S.mapSel = null; $$('[data-kind]').forEach(x => x.setAttribute('aria-pressed', String(x === b))); drawMarkers(true); });
    MAP = L.map('map', { zoomControl: true, attributionControl: true, worldCopyJump: false }).setView([50, 10], 4);
    L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
      maxZoom: 18, subdomains: 'abcd', attribution: '&copy; OpenStreetMap &copy; CARTO'
    }).addTo(MAP);
    MAP.on('moveend', () => { if (!S.mapSel) drawPanel(); });
    MAP.on('click', () => { if (S.mapSel) { S.mapSel = null; highlight(); drawPanel(); } });
  }
  drawMarkers(true);
  $('#mapNote').textContent = noPt ? `${noPt} משחקים לא מופיעים על המפה כי מיקום האצטדיון שלהם עדיין לא ידוע.` : '';
}
function drawMarkers(fit) {
  if (current.view !== 'map' || !MAP) return;
  if (fit !== 'keep') {
    // recompute groups for the current kind filter
    GROUPS = {};
    for (const g of mapGames()) { const p = ptOf(g); if (!p) continue; const k = p[0].toFixed(3) + ',' + p[1].toFixed(3); (GROUPS[k] ||= { k, p, games: [] }).games.push(g); }
  }
  if (CLUSTER) MAP.removeLayer(CLUSTER);
  CLUSTER = L.markerClusterGroup({ maxClusterRadius: 46, showCoverageOnHover: false, spiderfyOnMaxZoom: true,
    iconCreateFunction: cl => {
      const n = cl.getAllChildMarkers().reduce((s, m) => s + m.options.n, 0);
      return L.divIcon({ html: `<div>${n}</div>`, className: 'marker-cluster', iconSize: [40, 40] });
    } });
  MARKERS = {};
  for (const grp of Object.values(GROUPS)) {
    const n = grp.games.length, sz = n > 9 ? 34 : 28, eu = grp.games.some(g => isEuro(g.lg));
    const m = L.marker(grp.p, { n, icon: L.divIcon({ className: '', html: `<div class="pin ${eu ? 'eu' : ''}" style="width:${sz}px;height:${sz}px">${n}</div>`, iconSize: [sz, sz] }),
      title: grp.games[0].v || grp.games[0].city });
    m.on('click', e => { L.DomEvent.stopPropagation(e); select(grp.k); });
    MARKERS[grp.k] = m; CLUSTER.addLayer(m);
  }
  MAP.addLayer(CLUSTER);
  const pts = Object.values(GROUPS).map(g => g.p).filter(p => p[1] < 35 && p[0] > 34); // keep the view on Europe; far venues still have pins
  if (fit && pts.length) MAP.fitBounds(L.latLngBounds(pts).pad(0.08), { maxZoom: 9 });
  drawPanel();
}
function select(k) {
  S.mapSel = k; highlight(); drawPanel();
  const m = MARKERS[k]; if (m) CLUSTER.zoomToShowLayer(m, () => {});
}
function highlight() {
  for (const [k, m] of Object.entries(MARKERS)) { const el = m.getElement()?.querySelector('.pin'); if (el) el.classList.toggle('sel', k === S.mapSel); }
}
function mapRow(g, dist) {
  const c = DB.countries[g.c], k = (ptOf(g) || []).map(x => x.toFixed(3)).join(',');
  return `<button class="mg" data-sel="${k}"><div class="r1"><span class="t">${g.nt ? '—' : g.lt}</span><span><bdi>${esc(g.h)}</bdi> – <bdi>${esc(g.a)}</bdi></span></div>
    <div class="r2">${flagImg(c, 'sm')}<span>${esc(g.city || c.he)}</span><span class="lg" style="--dot:${LG_COLOR[g.lg] || '#94a3b8'}">${esc(leagueName(g.lg))}</span>${dist != null ? `<span class="km">${dist < 1 ? 'אותו אצטדיון' : Math.round(dist) + ' ק״מ'}</span>` : ''}</div></button>`;
}
function byDay(list, rowFn) {
  let out = '', last = '';
  for (const g of list) {
    if (g.ld !== last) { out += `<div class="dayHead"><h2>${fmtShort.format(utc(g.ld))}</h2>${isWeekend(g.ld) ? '<span class="tag">סופ״ש</span>' : ''}</div>`; last = g.ld; }
    out += rowFn(g);
  }
  return out;
}
function drawPanel() {
  if (!MAP || !$('#pBody')) return;
  const head = $('#pHead'), body = $('#pBody');
  if (S.mapSel && GROUPS[S.mapSel]) {
    const grp = GROUPS[S.mapSel], g0 = grp.games[0], c = DB.countries[g0.c];
    const near = [];
    for (const o of Object.values(GROUPS)) {
      if (o.k === grp.k) continue;
      const d = km(grp.p, o.p); if (d <= 350) o.games.forEach(g => near.push({ g, d }));
    }
    near.sort((a, b) => a.g.t.localeCompare(b.g.t) || a.d - b.d);
    head.innerHTML = `<button class="back2" id="unsel">כל המשחקים במפה</button><h2><bdi>${esc(g0.v || g0.city)}</bdi></h2><p>${flagImg(c, 'sm')} ${esc(g0.city)}, ${esc(c.he)} · ${grp.games.length} משחקים כאן</p>`;
    body.innerHTML = byDay(grp.games, g => mapRow(g)) +
      `<div class="dayHead" style="margin-top:22px"><h2>משחקים קרובים, עד 350 ק״מ</h2><span class="n">${near.length}</span></div>` +
      (near.length ? byDay(near.map(x => Object.assign(Object.create(x.g), { _d: x.d })), g => mapRow(g, g._d)) : '<p class="n" style="padding:8px 4px;color:var(--muted)">אין משחקים קרובים בתאריכים האלה.</p>');
    $('#unsel').onclick = () => { S.mapSel = null; highlight(); drawPanel(); };
  } else {
    const b = MAP.getBounds();
    const list = Object.values(GROUPS).filter(o => b.contains(o.p)).flatMap(o => o.games).sort((a, x) => a.t.localeCompare(x.t));
    head.innerHTML = `<h2>${list.length} משחקים באזור שעל המפה</h2><p>מזיזים או מגדילים את המפה כדי לצמצם. לחיצה על משחק מציגה את מה שקרוב אליו.</p>`;
    body.innerHTML = list.length ? byDay(list.slice(0, 300), g => mapRow(g)) + (list.length > 300 ? `<p style="padding:10px 4px;color:var(--muted);font-size:13px">מוצגים 300 הראשונים. מגדילים את המפה כדי לראות את השאר.</p>` : '')
      : '<p style="padding:16px 4px;color:var(--muted)">אין משחקים באזור הזה בתאריכים שבחרת.</p>';
  }
  $$('[data-sel]', body).forEach(x => x.onclick = () => x.dataset.sel && select(x.dataset.sel));
}

/* ---------- saved games ---------- */
const byId = id => DB.games.find(g => g.id === id);
const favGames = () => [...favs].map(byId).filter(Boolean).sort((a, b) => a.t.localeCompare(b.t));
function saveFavs() { store.set('ef_favs', [...favs]); $('#favCount').textContent = favs.size; }
document.addEventListener('click', e => {
  const b = e.target.closest('[data-fav]'); if (!b) return;
  const id = b.dataset.fav, on = !favs.has(id);
  on ? favs.add(id) : favs.delete(id); saveFavs();
  $$(`[data-fav="${CSS.escape(id)}"]`).forEach(x => { x.classList.toggle('on', on); x.textContent = on ? '♥' : '♡'; });
  toast(on ? 'נשמר ברשימה' : 'הוסר מהרשימה');
  if ($('#favDrawer').classList.contains('open')) renderFavs();
});
function renderFavs() {
  const a = favGames();
  $('#favList').innerHTML = a.length ? a.map(g => {
    const c = DB.countries[g.c];
    return `<div class="favRow">${flagImg(c, 'sm')}<div><b><bdi>${esc(g.h)}</bdi> – <bdi>${esc(g.a)}</bdi></b>
      <small>${fmtShort.format(utc(g.ld))} · ${g.nt ? 'השעה טרם נקבעה' : g.lt + ' שעון מקומי'} · ${esc(g.city || c.he)}</small></div>
      <button class="ib on" data-fav="${esc(g.id)}" aria-label="הסרה מהרשימה">♥</button></div>`;
  }).join('') : '<div class="empty" style="margin-top:12px">הרשימה ריקה. לוחצים על ♡ ליד משחק כדי לשמור אותו כאן.</div>';
}
function openDrawer(open) {
  $('#favDrawer').classList.toggle('open', open); $('#scrim').classList.toggle('open', open);
  $('#favDrawer').setAttribute('aria-hidden', String(!open));
  if (open) renderFavs();
}
$('#favBtn').onclick = () => openDrawer(true);
$('#scrim').onclick = () => openDrawer(false);
$('[data-close]').onclick = () => openDrawer(false);
$('#favShare').onclick = () => {
  const a = favGames(); if (!a.length) return toast('הרשימה ריקה');
  share('המשחקים שלי באירופה', '', 'המשחקים שלי באירופה ⚽\n\n' + a.map(g =>
    `${dm(g.ld)} ${g.nt ? '(השעה טרם נקבעה)' : g.lt} | ${g.h} – ${g.a}\n${leagueName(g.lg)} · ${[g.v, g.city].filter(Boolean).join(', ')}${g.ok ? '' : ' · מועד משוער'}`).join('\n\n'));
};
$('#favClear').onclick = () => { if (favs.size && confirm('לנקות את כל הרשימה?')) { favs.clear(); saveFavs(); renderFavs(); render(); } };
const stamp = d => d.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '');
const icsText = s => String(s).replace(/[\\,;]/g, m => '\\' + m).replace(/\n/g, '\\n');
$('#favIcs').onclick = () => {
  const a = favGames().filter(g => !g.nt); if (!a.length) return toast('אין ברשימה משחקים עם שעה ידועה');
  const L2 = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//europe-football//HE', 'CALSCALE:GREGORIAN'];
  a.forEach(g => { const s = new Date(g.t); L2.push('BEGIN:VEVENT', 'UID:' + g.id + '@europe-football', 'DTSTAMP:' + stamp(new Date()),
    'DTSTART:' + stamp(s), 'DTEND:' + stamp(new Date(s.getTime() + 2 * 3600e3)), 'SUMMARY:' + icsText('⚽ ' + g.h + ' – ' + g.a),
    'LOCATION:' + icsText([g.v, g.city].filter(Boolean).join(', ')), 'DESCRIPTION:' + icsText(leagueName(g.lg) + (g.ok ? '' : ' · מועד משוער')), 'END:VEVENT'); });
  L2.push('END:VCALENDAR');
  const url = URL.createObjectURL(new Blob([L2.join('\r\n')], { type: 'text/calendar' }));
  Object.assign(document.createElement('a'), { href: url, download: 'משחקים_באירופה.ics' }).click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
};
function gcal(g) {
  const s = new Date(g.t), e = new Date(s.getTime() + 2 * 3600e3);
  return 'https://calendar.google.com/calendar/render?action=TEMPLATE&text=' + encodeURIComponent('⚽ ' + g.h + ' – ' + g.a) +
    '&dates=' + stamp(s) + '/' + stamp(e) + '&location=' + encodeURIComponent([g.v, g.city].filter(Boolean).join(', ')) +
    '&details=' + encodeURIComponent(leagueName(g.lg) + (g.ok ? '' : ' · מועד משוער'));
}

/* ---------- misc ---------- */
async function share(title, url, text) {
  try { if (navigator.share) { await navigator.share({ title, url: url || undefined, text }); return; } } catch (e) { if (e.name === 'AbortError') return; }
  try { await navigator.clipboard.writeText(text ? text + (url ? '\n' + url : '') : url); toast('הועתק'); } catch { prompt('להעתקה:', url || text); }
}
let toastT;
function toast(msg) { const t = $('#toast'); t.textContent = msg; t.classList.add('show'); clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove('show'), 1600); }
function footer() {
  const up = new Date(DB.updated).toLocaleString('he-IL', { timeZone: IL_TZ, dateStyle: 'short', timeStyle: 'short' });
  $('#foot').innerHTML = `<b>מועד סופי</b>: התאריך והשעה פורסמו. <b>מועד משוער</b>: עלול להשתנות, כדאי לבדוק שוב לפני שמזמינים טיסה או כרטיס.
    השעה הגדולה היא לפי השעון המקומי, ומתחתיה שעון ישראל. הלוח מתעדכן פעמיים ביום, העדכון האחרון: ${up}.`;
}
saveFavs();
if ('serviceWorker' in navigator && location.protocol === 'https:') navigator.serviceWorker.register('sw.js').catch(() => {});
load().catch(err => { $('#app').innerHTML = '<div class="empty">לוח המשחקים לא נטען. מרעננים את הדף כדי לנסות שוב.</div>'; console.error(err); });
