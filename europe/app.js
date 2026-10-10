'use strict';
/* כדורגל באירופה — בוחרים מדינה, רואים משחקים */
const $ = (s, el = document) => el.querySelector(s);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } }
};

const IL_TZ = 'Asia/Jerusalem';
const todayIL = () => new Intl.DateTimeFormat('en-CA', { timeZone: IL_TZ }).format(new Date());
const fmtIL = new Intl.DateTimeFormat('he-IL', { timeZone: IL_TZ, hour: '2-digit', minute: '2-digit', hour12: false });
const fmtILDay = new Intl.DateTimeFormat('en-CA', { timeZone: IL_TZ });
const fmtDay = new Intl.DateTimeFormat('he-IL', { timeZone: 'UTC', weekday: 'long', day: 'numeric', month: 'long' });
const fmtDayShort = new Intl.DateTimeFormat('he-IL', { timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'numeric' });
const utcDate = ld => new Date(ld + 'T12:00:00Z');
const addDays = (ld, n) => { const d = utcDate(ld); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
const dm = ld => { const [, m, d] = ld.split('-'); return +d + '.' + +m; };
const dmy = ld => { const [y, m, d] = ld.split('-'); return +d + '.' + +m + '.' + y; };
const dow = ld => utcDate(ld).getUTCDay();
const isWeekend = ld => [5, 6, 0].includes(dow(ld));
const flagImg = (c, cls = '') => c.flag
  ? `<img class="flag ${cls}" src="https://flagcdn.com/w160/${c.flag}.png" alt="" loading="lazy" onerror="this.style.visibility='hidden'">`
  : `<span class="flag ${cls}" style="display:grid;place-items:center">🌍</span>`;
const LG_COLOR = { 'uefa.champions': 'var(--ucl)', 'uefa.europa': 'var(--uel)', 'uefa.europa.conf': 'var(--uecl)', 'uefa.nations': 'var(--unl)' };
const REGIONS = ['הכול', 'מערב', 'מרכז', 'דרום', 'צפון', 'מזרח'];
const PAGE = 120;

let DB = null, BY_COUNTRY = {};
const S = {
  from: null, to: null, region: 'הכול', cq: '',
  lg: new Set(), city: '', q: '', okOnly: false, weOnly: false, past: false, shown: PAGE
};
let favs = new Set(store.get('ef_favs', []));

/* ---------- data ---------- */
async function load() {
  const res = await fetch('data/games.json', { cache: 'no-cache' });
  DB = await res.json();
  for (const g of DB.games) (BY_COUNTRY[g.c] ||= []).push(g);
  const today = todayIL();
  S.from = today > DB.range[0] ? today : DB.range[0];
  S.to = DB.range[1];
  footer();
  route();
}
const isPast = g => new Date(g.t).getTime() < Date.now() - 2.2 * 3600e3;
const inRange = g => g.ld >= S.from && g.ld <= S.to;
const visible = g => inRange(g) && (S.past || !isPast(g));
const leagueName = slug => DB.leagues[slug]?.he || slug;

/* ---------- routing ---------- */
function parseHash() {
  const h = decodeURIComponent(location.hash.slice(1) || '/');
  const [path, qs] = h.split('?');
  const p = new URLSearchParams(qs || '');
  if (p.get('from')) S.from = p.get('from');
  if (p.get('to')) S.to = p.get('to');
  S.lg = new Set((p.get('lg') || '').split(',').filter(Boolean));
  S.city = p.get('city') || '';
  const m = path.match(/^\/c\/(.+)$/);
  return m ? { view: 'country', key: m[1] } : { view: 'home' };
}
function syncHash(r) {
  const p = new URLSearchParams();
  p.set('from', S.from); p.set('to', S.to);
  if (r.view === 'country') { if (S.lg.size) p.set('lg', [...S.lg].join(',')); if (S.city) p.set('city', S.city); }
  const base = r.view === 'country' ? '#/c/' + encodeURIComponent(r.key) : '#/';
  history.replaceState(null, '', base + '?' + p.toString());
}
let current = { view: 'home' };
function route() {
  if (!DB) return;
  const prev = current;
  current = parseHash();
  if (current.view !== prev.view || current.key !== prev.key) {
    S.shown = PAGE; S.q = ''; S.okOnly = false; S.weOnly = false;
    window.scrollTo(0, 0);
  }
  current.view === 'country' && DB.countries[current.key] ? renderCountry(current.key) : renderHome();
}
addEventListener('hashchange', route);

/* ---------- date bar (shared) ---------- */
function dateBar() {
  const t = todayIL(), next = nextWeekend(t);
  const quick = [
    ['הסופ״ש הקרוב', next[0], next[1]],
    ['7 ימים', t, addDays(t, 6)],
    ['30 יום', t, addDays(t, 29)],
    ['כל העונה', t > DB.range[0] ? t : DB.range[0], DB.range[1]]
  ];
  return `<section class="when">
    <div class="whenRow">
      <label class="field"><span>מתאריך</span><input type="date" id="from" value="${S.from}" min="${DB.range[0]}" max="${DB.range[1]}"></label>
      <label class="field"><span>עד תאריך</span><input type="date" id="to" value="${S.to}" min="${DB.range[0]}" max="${DB.range[1]}"></label>
      <div class="field grow"><span>טווח מהיר</span><div class="chips">${quick.map(([l, f, to]) =>
        `<button class="chip" data-range="${f},${to}" aria-pressed="${S.from === f && S.to === to}">${l}</button>`).join('')}</div></div>
    </div></section>`;
}
function nextWeekend(t) {
  const d = dow(t); // Fri=5 Sat=6 Sun=0
  const fri = d === 6 ? addDays(t, -1) : d === 0 ? addDays(t, -2) : addDays(t, (5 - d + 7) % 7);
  return [fri < t ? t : fri, addDays(fri, 2)];
}
function bindDateBar(rerender) {
  const apply = () => { if (S.to < S.from) S.to = S.from; S.shown = PAGE; syncHash(current); rerender(); };
  $('#from').onchange = e => { if (e.target.value) { S.from = e.target.value; apply(); } };
  $('#to').onchange = e => { if (e.target.value) { S.to = e.target.value; apply(); } };
  document.querySelectorAll('[data-range]').forEach(b => b.onclick = () => { [S.from, S.to] = b.dataset.range.split(','); apply(); });
}

/* ---------- home ---------- */
function renderHome() {
  document.title = 'כדורגל באירופה • איפה משחקים';
  const rows = Object.entries(DB.countries).map(([key, c]) => {
    const list = (BY_COUNTRY[key] || []).filter(visible);
    const leagues = [...new Set(list.map(g => g.lg))].map(leagueName);
    return { key, c, n: list.length, leagues, next: list[0] };
  }).filter(r => (S.region === 'הכול' || r.c.region === S.region) &&
    (!S.cq || (r.c.he + ' ' + r.key).toLowerCase().includes(S.cq.toLowerCase())))
    .sort((a, b) => (a.key === 'TBD') - (b.key === 'TBD') || b.n - a.n || a.c.he.localeCompare(b.c.he, 'he'));
  const total = rows.reduce((s, r) => s + r.n, 0);
  const withGames = rows.filter(r => r.n).length;

  $('#app').innerHTML = `
  <section class="hero">
    <div class="eyebrow">מצא משחק בכל מדינה באירופה</div>
    <h1>לאן טסים?</h1>
    <p>בוחרים תאריכים ומדינה ורואים את כל המשחקים בה: ליגות מקומיות, ליגת האלופות, הליגה האירופית, הקונפרנס וליגת האומות. השעות מוצגות לפי השעון המקומי וגם לפי שעון ישראל.</p>
  </section>
  ${dateBar()}
  <div class="whenRow" style="margin-top:4px">
    <label class="field grow"><span>חיפוש מדינה</span><input id="cq" type="search" placeholder="למשל: ספרד, Germany…" value="${esc(S.cq)}"></label>
  </div>
  <div class="chips scroll quick" role="group" aria-label="אזור">${REGIONS.map(r =>
    `<button class="chip" data-region="${r}" aria-pressed="${S.region === r}">${r === 'הכול' ? 'כל אירופה' : r + ' אירופה'}</button>`).join('')}</div>
  <div class="sectionHead"><h2>${withGames} מדינות עם משחקים</h2><span class="muted">${total.toLocaleString('he-IL')} משחקים · ${dmy(S.from)}–${dmy(S.to)}</span></div>
  <div class="grid">${rows.map(card).join('') || '<div class="empty">לא נמצאה מדינה.</div>'}</div>`;

  bindDateBar(renderHome);
  const cq = $('#cq');
  cq.oninput = () => { S.cq = cq.value; const pos = cq.selectionStart; renderHome(); const n = $('#cq'); n.focus(); n.setSelectionRange(pos, pos); };
  document.querySelectorAll('[data-region]').forEach(b => b.onclick = () => { S.region = b.dataset.region; renderHome(); });
}
function card(r) {
  const href = '#/c/' + encodeURIComponent(r.key) + '?from=' + S.from + '&to=' + S.to;
  const nx = r.next ? `<div class="ccNext">הבא: <b>${dm(r.next.ld)}</b> · <bdi>${esc(r.next.h)}</bdi> – <bdi>${esc(r.next.a)}</bdi></div>` : '<div class="ccNext">אין משחקים בתאריכים האלה</div>';
  return `<a class="cc ${r.n ? '' : 'zero'}" href="${href}">
    <div class="ccTop">${flagImg(r.c)}<div class="ccName">${esc(r.c.he)}</div>
      <div class="ccCount"><b>${r.n}</b><span>משחקים</span></div></div>
    <div class="ccLeagues">${esc(r.leagues.join(' · ') || '—')}</div>${nx}</a>`;
}

/* ---------- country ---------- */
function countryBase(key) { return (BY_COUNTRY[key] || []).filter(visible); }
function filtered(key) {
  const q = S.q.trim().toLowerCase();
  return countryBase(key).filter(g =>
    (!S.lg.size || S.lg.has(g.lg)) && (!S.city || g.city === S.city) &&
    (!S.okOnly || g.ok) && (!S.weOnly || isWeekend(g.ld)) &&
    (!q || (g.h + ' ' + g.a + ' ' + g.v + ' ' + g.city).toLowerCase().includes(q)));
}
function renderCountry(key) {
  const c = DB.countries[key];
  document.title = c.he + ' • כדורגל באירופה';
  const base = countryBase(key);
  const all = BY_COUNTRY[key] || [];
  const lgCount = {}; base.forEach(g => lgCount[g.lg] = (lgCount[g.lg] || 0) + 1);
  const cityCount = {}; base.forEach(g => g.city && (cityCount[g.city] = (cityCount[g.city] || 0) + 1));
  const okPct = base.length ? Math.round(100 * base.filter(g => g.ok).length / base.length) : 0;

  // weekends (independent of the date filter, upcoming only)
  const t = todayIL(), wk = {};
  all.filter(g => !isPast(g) && isWeekend(g.ld)).forEach(g => {
    const d = dow(g.ld), fri = addDays(g.ld, -((d + 2) % 7));
    wk[fri] = (wk[fri] || 0) + 1;
  });
  const wkList = Object.entries(wk).sort((a, b) => a[0].localeCompare(b[0])).slice(0, 12);
  const ns = wkList.map(x => x[1]).sort((a, b) => a - b), med = ns[Math.floor(ns.length / 2)] || 0;
  const hot = new Set(wkList.filter(x => x[1] >= Math.max(4, med * 1.25)).map(x => x[0]));

  $('#app').innerHTML = `
  <a class="back" href="#/?from=${S.from}&to=${S.to}">→ כל המדינות</a>
  <div class="cHead">${flagImg(c, 'big')}<h1>${esc(c.he)}</h1>
    <button class="btn share" id="shareCountry">שיתוף הדף</button></div>
  <div class="stats">
    <div class="stat"><b>${base.length}</b><span>משחקים בטווח</span></div>
    <div class="stat"><b>${Object.keys(lgCount).length}</b><span>מפעלים וליגות</span></div>
    <div class="stat"><b>${Object.keys(cityCount).length}</b><span>ערים</span></div>
    <div class="stat"><b>${okPct}%</b><span>מועד סופי</span></div>
  </div>
  ${wkList.length ? `<div class="weekends"><div class="label">סופי שבוע (שישי–ראשון) · לחיצה בוחרת את התאריכים</div>
    <div class="chips scroll">${wkList.map(([fri, n]) => {
      const sun = addDays(fri, 2), on = S.from === fri && S.to === sun;
      return `<button class="chip wk ${hot.has(fri) ? 'hot' : ''}" data-range="${fri},${sun}" aria-pressed="${on}"><b>${n}</b><span>${dm(fri)}–${dm(sun)}</span></button>`;
    }).join('')}</div></div>` : ''}
  ${dateBar()}
  <section class="filters" id="filters">
    <div class="chips scroll" role="group" aria-label="ליגות">
      <button class="chip" data-lg="" aria-pressed="${!S.lg.size}">הכול <small>${base.length}</small></button>
      ${Object.entries(lgCount).sort((a, b) => b[1] - a[1]).map(([lg, n]) =>
        `<button class="chip" data-lg="${esc(lg)}" aria-pressed="${S.lg.has(lg)}">${esc(leagueName(lg))} <small>${n}</small></button>`).join('')}
    </div>
    <div class="filterRow" style="margin-top:8px">
      <label class="field grow"><span>קבוצה או אצטדיון</span><input id="q" type="search" placeholder="חיפוש…" value="${esc(S.q)}"></label>
      <label class="field"><span>עיר</span><select id="city"><option value="">כל הערים</option>${Object.entries(cityCount).sort((a, b) => b[1] - a[1]).map(([ci, n]) =>
        `<option value="${esc(ci)}" ${S.city === ci ? 'selected' : ''}>${esc(ci)} (${n})</option>`).join('')}</select></label>
      <button class="toggle" id="weOnly" aria-pressed="${S.weOnly}">סופ״ש בלבד</button>
      <button class="toggle" id="okOnly" aria-pressed="${S.okOnly}">מועד סופי בלבד</button>
      <button class="toggle" id="past" aria-pressed="${S.past}">כולל משחקים שהיו</button>
    </div>
  </section>
  <div id="list"></div>`;

  bindDateBar(() => renderCountry(key));
  $('#shareCountry').onclick = () => share(c.he + ' — משחקי כדורגל', location.href);
  document.querySelectorAll('[data-lg]').forEach(b => b.onclick = () => {
    const v = b.dataset.lg;
    if (!v) S.lg.clear(); else S.lg.has(v) ? S.lg.delete(v) : S.lg.add(v);
    S.shown = PAGE; syncHash(current); renderCountry(key);
  });
  $('#city').onchange = e => { S.city = e.target.value; S.shown = PAGE; syncHash(current); renderList(key); };
  $('#q').oninput = e => { S.q = e.target.value; S.shown = PAGE; renderList(key); };
  for (const id of ['weOnly', 'okOnly', 'past']) $('#' + id).onclick = () => { S[id] = !S[id]; S.shown = PAGE; renderCountry(key); };
  renderList(key);
}

function renderList(key) {
  const list = filtered(key);
  const shown = list.slice(0, S.shown);
  const days = [];
  for (const g of shown) { const last = days.at(-1); if (last && last.ld === g.ld) last.games.push(g); else days.push({ ld: g.ld, games: [g] }); }
  const dayCount = {}; list.forEach(g => dayCount[g.ld] = (dayCount[g.ld] || 0) + 1);
  const active = S.lg.size || S.city || S.q || S.okOnly || S.weOnly;
  $('#list').innerHTML = `
    <div class="resultLine"><span>${list.length} משחקים · ${dmy(S.from)}–${dmy(S.to)}</span>
      ${active ? '<button class="linkBtn" id="clearF">ניקוי סינון</button>' : ''}</div>
    ${days.map(d => `<section class="day"><div class="dayHead"><h3>${fmtDay.format(utcDate(d.ld))}</h3>
      ${isWeekend(d.ld) ? '<span class="we">סופ״ש</span>' : ''}<span class="muted">${dayCount[d.ld]} משחקים</span></div>
      ${d.games.map(gameCard).join('')}</section>`).join('') ||
      `<div class="empty">אין משחקים שמתאימים לסינון.<br>אפשר להרחיב את התאריכים או לבחור סוף שבוע אחר.</div>`}
    ${list.length > S.shown ? `<button class="btn showMore" id="more">הצגת עוד ${Math.min(PAGE, list.length - S.shown)} משחקים (${list.length - S.shown} נותרו)</button>` : ''}`;
  $('#more') && ($('#more').onclick = () => { S.shown += PAGE; renderList(key); });
  $('#clearF') && ($('#clearF').onclick = () => { S.lg.clear(); S.city = ''; S.q = ''; S.okOnly = S.weOnly = false; syncHash(current); renderCountry(key); });
}

function gameCard(g) {
  const past = isPast(g), hasScore = Array.isArray(g.s);
  const ilTime = fmtIL.format(new Date(g.t)), ilDay = fmtILDay.format(new Date(g.t));
  const ilNote = ilDay !== g.ld ? ' (' + dm(ilDay) + ')' : '';
  let time;
  if (hasScore && !g.live) time = `<b class="score">${g.s[0]}–${g.s[1]}</b><span class="il">הסתיים</span>`;
  else if (g.nt) time = `<span class="tbd">שעה<br>תיקבע</span>`;
  else time = `<b>${g.lt}</b><span class="il">🇮🇱 ${ilTime}${ilNote}</span>`;
  const badge = g.pp ? '<span class="badge pp">נדחה</span>'
    : g.live ? '<span class="badge live">● חי' + (hasScore ? ' ' + g.s[0] + '–' + g.s[1] : '') + '</span>'
    : past ? '' : g.ok ? '<span class="badge ok">✓ מועד סופי</span>' : '<span class="badge est">משוער</span>';
  const place = [g.v, g.city].filter(Boolean).join(' · ') || 'אצטדיון טרם פורסם';
  const fav = favs.has(g.id);
  const mapQ = encodeURIComponent([g.v, g.city, DB.countries[g.c]?.he && g.c !== 'TBD' ? g.c : ''].filter(Boolean).join(', '));
  const info = [g.note ? esc(g.note) : '', g.src ? `<a href="${esc(g.src)}" target="_blank" rel="noopener">מקור הלוח</a>` : '',
    g.site ? `<a href="${esc(g.site)}" target="_blank" rel="noopener">אתר הקבוצה המארחת</a>` : ''].filter(Boolean).join(' · ');
  return `<article class="game ${past ? 'past' : ''}">
    <div class="time">${time}</div>
    <div class="teams">
      <div class="team">${g.hl ? `<img src="${esc(g.hl)}" alt="" loading="lazy" onerror="this.remove()">` : ''}<span dir="auto">${esc(g.h)}</span></div>
      <div class="team">${g.al ? `<img src="${esc(g.al)}" alt="" loading="lazy" onerror="this.remove()">` : ''}<span dir="auto">${esc(g.a)}</span></div>
      <div class="meta"><span class="lg" style="--dot:${LG_COLOR[g.lg] || '#8aa396'}">${esc(leagueName(g.lg))}</span>${badge}<span>📍 ${esc(place)}</span></div>
    </div>
    <div class="acts">
      <button class="iconBtn ${fav ? 'on' : ''}" data-fav="${esc(g.id)}" aria-label="${fav ? 'הסרה מהמועדפים' : 'הוספה למועדפים'}" title="מועדפים">${fav ? '♥' : '♡'}</button>
      ${!past && !g.nt ? `<a class="iconBtn" href="${gcal(g)}" target="_blank" rel="noopener" title="הוספה ליומן Google" aria-label="הוספה ליומן">📅</a>` : ''}
      ${mapQ ? `<a class="iconBtn" href="https://www.google.com/maps/search/?api=1&query=${mapQ}" target="_blank" rel="noopener" title="מפה" aria-label="מפה">🗺️</a>` : ''}
    </div>
    ${info ? `<details class="info"><summary>ⓘ פרטים ומקורות</summary>${info}</details>` : ''}
  </article>`;
}

/* ---------- favorites ---------- */
const byId = id => DB.games.find(g => g.id === id);
function favGames() { return [...favs].map(byId).filter(Boolean).sort((a, b) => a.t.localeCompare(b.t)); }
function saveFavs() { store.set('ef_favs', [...favs]); $('#favCount').textContent = favs.size; }
document.addEventListener('click', e => {
  const b = e.target.closest('[data-fav]');
  if (!b) return;
  const id = b.dataset.fav, on = !favs.has(id);
  on ? favs.add(id) : favs.delete(id);
  saveFavs();
  b.classList.toggle('on', on); b.textContent = on ? '♥' : '♡';
  toast(on ? 'נוסף למועדפים' : 'הוסר מהמועדפים');
  if ($('#favDrawer').classList.contains('open')) renderFavs();
});
function renderFavs() {
  const a = favGames();
  $('#favList').innerHTML = a.length ? a.map(g => {
    const c = DB.countries[g.c];
    return `<div class="favRow">${flagImg(c, 'sm')}<div><b><bdi>${esc(g.h)}</bdi> – <bdi>${esc(g.a)}</bdi></b>
      <small>${fmtDayShort.format(utcDate(g.ld))} · ${g.nt ? 'שעה תיקבע' : g.lt + ' מקומי'} · ${esc(g.city || c.he)} · ${esc(leagueName(g.lg))}</small></div>
      <button class="iconBtn on" data-fav="${esc(g.id)}" aria-label="הסרה">♥</button></div>`;
  }).join('') : '<div class="empty">עדיין לא סימנת משחקים.<br>לחיצה על ♡ ליד משחק שומרת אותו כאן.</div>';
}
function openDrawer(open) {
  $('#favDrawer').classList.toggle('open', open); $('#scrim').classList.toggle('open', open);
  $('#favDrawer').setAttribute('aria-hidden', String(!open));
  if (open) renderFavs(); else route();
}
$('#favBtn').onclick = () => openDrawer(true);
$('#scrim').onclick = () => openDrawer(false);
$('[data-close]').onclick = () => openDrawer(false);
addEventListener('keydown', e => e.key === 'Escape' && $('#favDrawer').classList.contains('open') && openDrawer(false));
$('#favShare').onclick = () => {
  const a = favGames(); if (!a.length) return toast('אין משחקים מסומנים');
  share('המשחקים שלי באירופה ⚽', '', 'המשחקים שלי באירופה ⚽\n\n' + a.map(g =>
    `${dmy(g.ld)} ${g.nt ? '(שעה תיקבע)' : g.lt} | ${g.h} – ${g.a}\n${leagueName(g.lg)} · ${[g.v, g.city].filter(Boolean).join(', ')}${g.ok ? '' : ' · מועד משוער'}`).join('\n\n'));
};
$('#favClear').onclick = () => { if (favs.size && confirm('לנקות את כל המועדפים?')) { favs.clear(); saveFavs(); renderFavs(); } };
$('#favIcs').onclick = () => {
  const a = favGames().filter(g => !g.nt); if (!a.length) return toast('אין משחקים עם שעה ידועה');
  const st = t => t.replace(/[-:]/g, '').replace('Z', '00Z');
  const en = t => new Date(new Date(t).getTime() + 2 * 3600e3).toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '');
  const L = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//europe-football//HE', 'CALSCALE:GREGORIAN'];
  a.forEach(g => L.push('BEGIN:VEVENT', 'UID:' + g.id + '@europe-football', 'DTSTAMP:' + new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, ''),
    'DTSTART:' + st(g.t), 'DTEND:' + en(g.t), 'SUMMARY:' + icsText('⚽ ' + g.h + ' – ' + g.a),
    'LOCATION:' + icsText([g.v, g.city].filter(Boolean).join(', ')),
    'DESCRIPTION:' + icsText(leagueName(g.lg) + (g.ok ? '' : ' · מועד משוער – לבדוק לפני הזמנה')), 'END:VEVENT'));
  L.push('END:VCALENDAR');
  const url = URL.createObjectURL(new Blob([L.join('\r\n')], { type: 'text/calendar' }));
  Object.assign(document.createElement('a'), { href: url, download: 'משחקים_באירופה.ics' }).click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
};
const icsText = s => String(s).replace(/[\\,;]/g, m => '\\' + m).replace(/\n/g, '\\n');
function gcal(g) {
  const s = g.t.replace(/[-:]/g, '').replace('Z', '00Z');
  const e = new Date(new Date(g.t).getTime() + 2 * 3600e3).toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '');
  return 'https://calendar.google.com/calendar/render?action=TEMPLATE&text=' + encodeURIComponent('⚽ ' + g.h + ' – ' + g.a) +
    '&dates=' + s + '/' + e + '&location=' + encodeURIComponent([g.v, g.city].filter(Boolean).join(', ')) +
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
  const up = new Date(DB.updated);
  $('#foot').innerHTML = `<b>מקרא:</b> <b style="color:#7ff0bf">✓ מועד סופי</b> — התאריך והשעה פורסמו ע״י הגוף המארגן או מקור נתונים מוכר. <b style="color:var(--gold)">משוער</b> — המועד עלול להשתנות, יש לבדוק שוב לפני הזמנת טיסה או כרטיס.
  השעה הגדולה היא לפי השעון המקומי במדינה, ומתחתיה שעון ישראל.<br>
  הנתונים עודכנו לאחרונה: ${up.toLocaleString('he-IL', { timeZone: IL_TZ, dateStyle: 'short', timeStyle: 'short' })} · ${DB.games.length.toLocaleString('he-IL')} משחקים בלוח · עדכון אוטומטי יומי של תוצאות ושעות.`;
}
saveFavs();
if ('serviceWorker' in navigator && location.protocol === 'https:') navigator.serviceWorker.register('sw.js').catch(() => {});
load().catch(err => { $('#app').innerHTML = '<div class="empty">לא הצלחנו לטעון את לוח המשחקים. נסו לרענן.</div>'; console.error(err); });
