"""
עדכון אוטומטי של ליגת טרום ילדים ב' שפלה מאתר ההתאחדות.
טוען את עמוד הליגה בדפדפן אמיתי (Playwright), עובר על כל המחזורים,
מזהה כל משחק לפי שתי הקבוצות, ושומר שעה, מגרש ותוצאה ל-data.json.
"""
import asyncio, json, re, datetime, pathlib

ROOT = pathlib.Path(__file__).parent
CFG = json.loads((ROOT / "league.json").read_text(encoding="utf-8"))
L, S = CFG["league_id"], CFG["season_id"]
URLS = [
    f"https://www.football.org.il/leagues/league/?league_id={L}&season_id={S}",
    f"https://www.football.org.il/leagues/games/game/?league_id={L}&season_id={S}",
]
DEBUG = ROOT / "debug"

def norm(s):
    s = re.sub(r"[\"'״׳`”“]", "", s)
    s = re.sub(r"\bצו פיוס\b", "", s)
    return re.sub(r"\s+", " ", s).strip()

TEAMS = [norm(t) for t in CFG["teams"]]
GAME_ID = {}
for r, rnd in enumerate(CFG["pairs"]):
    for i, (h, a) in enumerate(rnd):
        GAME_ID[(h, a)] = f"{r}-{i}"

VENUE_WORDS = re.compile(r"(מגרש|אצטדיון|איצטדיון|מתחם|ספורטק|פארק|סינטטי|קאנטרי|מרכז ספורט|אולם)")
TIME_RE = re.compile(r"(?<![\d:])((?:0[7-9]|1\d|2[0-3])):([0-5]\d)(?![\d:])")
DATE_RE = re.compile(r"(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})")
SCORE_RE = re.compile(r"(?<![\d:/.])(\d{1,2})\s*[-–:]\s*(\d{1,2})(?![\d:/.])")

# JS שרץ בדף: מוצא את האלמנט הקטן ביותר שמכיל בדיוק שתי קבוצות מהליגה
FIND_ROWS = r"""
(teams) => {
  const n = s => s.replace(/["'״׳`”“]/g,'').replace(/צו פיוס/g,'').replace(/\s+/g,' ').trim();
  const hits = [];
  for (const el of document.querySelectorAll('body *')) {
    const t = el.innerText || '';
    if (t.length < 10 || t.length > 700) continue;
    const nt = n(t);
    const found = teams.map((name,i)=>[i, nt.indexOf(name)]).filter(x=>x[1]>=0);
    if (found.length === 2) hits.push({el, text: t, order: found.sort((a,b)=>a[1]-b[1]).map(x=>x[0])});
  }
  // משאירים רק את המינימליים (בלי צאצא שגם הוא שורת משחק)
  const minimal = hits.filter(h => !hits.some(o => o !== h && h.el.contains(o.el)));
  // מטפסים לשורה המלאה: ההורה הגבוה ביותר שעדיין מכיל רק את שתי הקבוצות האלה
  const count = t => { const nt = n(t); return teams.filter(name => nt.includes(name)).length; };
  return minimal.map(h => {
    let el = h.el;
    while (el.parentElement && el.parentElement !== document.body && count(el.parentElement.innerText || '') === 2) el = el.parentElement;
    return {text: el.innerText, order: h.order};
  });
}
"""

CLICK_ROUNDS = r"""
() => {
  const items = [...document.querySelectorAll('a, li, option, button, span, div')]
    .filter(e => /^\s*מחזור\s+\d+\s*$/.test(e.textContent || '') && e.children.length === 0);
  const seen = new Set(), out = [];
  for (const e of items) { const k = e.textContent.trim(); if (!seen.has(k)) { seen.add(k); out.push(k); } }
  return out;
}
"""

CLICK_ONE = r"""
(label) => {
  const els = [...document.querySelectorAll('a, li, option, button, span, div')]
    .filter(e => (e.textContent||'').trim() === label && e.children.length === 0);
  for (const e of els) {
    if (e.tagName === 'OPTION') { const s = e.closest('select'); s.value = e.value; s.dispatchEvent(new Event('change',{bubbles:true})); return true; }
  }
  if (els.length) { (els[0].closest('a,li,button') || els[0]).click(); return true; }
  return false;
}
"""

LABELS = {"תאריך": "date", "שעה": "time", "שעת משחק": "time", "מגרש": "venue",
          "אצטדיון": "venue", "איצטדיון": "venue", "תוצאה": "score"}

def parse_row(text, order):
    a, b = order
    if (a, b) in GAME_ID:
        gid, swap = GAME_ID[(a, b)], False
    elif (b, a) in GAME_ID:
        gid, swap = GAME_ID[(b, a)], True
    else:
        return None, None
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    # 1) לפי תוויות ("שעה" ואחריה הערך)
    raw = {}
    for i, line in enumerate(lines):
        key = LABELS.get(line.rstrip(":").strip())
        if key and i + 1 < len(lines) and lines[i + 1].rstrip(":") not in LABELS and key not in raw:
            raw[key] = lines[i + 1]
    # שורות שאינן שמות קבוצות – לחיפוש לפי תבנית
    other = [l for l in lines if l.rstrip(":").strip() not in LABELS and l != "משחק"
             and not any(tn and tn in norm(l) for tn in TEAMS)]
    other_txt = "\n".join(other)
    g = {}
    d = DATE_RE.search(raw.get("date", "") or other_txt)
    if d:
        dd, mm, yy = d.groups()
        yy = yy if len(yy) == 4 else "20" + yy
        g["date"] = f"{int(dd):02d}/{int(mm):02d}/{yy}"
    t_src = raw.get("time", "") or DATE_RE.sub(" ", other_txt)
    t = TIME_RE.search(t_src)
    if t:
        g["time"] = f"{t.group(1)}:{t.group(2)}"
    s_src = raw.get("score")
    if s_src is None:
        s_src = TIME_RE.sub(" ", DATE_RE.sub(" ", other_txt))
    sc = SCORE_RE.search(s_src)
    if sc:
        x, y = int(sc.group(1)), int(sc.group(2))
        g["score"] = [y, x] if swap else [x, y]
    v = raw.get("venue", "")
    if not v:
        for line in other:
            if VENUE_WORDS.search(line):
                v = re.sub(r"^(מגרש|אצטדיון|איצטדיון)\s*[:：]\s*", "", line).strip()
                break
    if v and 1 < len(v) < 120 and not TIME_RE.fullmatch(v):
        g["venue"] = v
    return gid, g

async def main():
    from playwright.async_api import async_playwright
    DEBUG.mkdir(exist_ok=True)
    games, xhr_log, all_rows = {}, [], []
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(locale="he-IL", user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"))

        async def on_resp(r):
            if r.request.resource_type in ("xhr", "fetch") and "football.org.il" in r.url:
                try:
                    xhr_log.append({"url": r.url, "body": (await r.text())[:150000]})
                except Exception:
                    pass
        page.on("response", on_resp)

        def collect(rows):
            for row in rows:
                gid, g = parse_row(row["text"], row["order"])
                if gid:
                    games.setdefault(gid, {}).update({k: v for k, v in g.items() if v})

        for n, url in enumerate(URLS):
            try:
                await page.goto(url, wait_until="networkidle", timeout=90000)
            except Exception as e:
                print("טעינה נכשלה:", url, e)
                continue
            await page.wait_for_timeout(6000)
            first = await page.evaluate(FIND_ROWS, TEAMS)
            collect(first)
            all_rows.extend(first)
            (DEBUG / f"page{n}.txt").write_text(await page.inner_text("body"), encoding="utf-8")
            for label in await page.evaluate(CLICK_ROUNDS):
                if await page.evaluate(CLICK_ONE, label):
                    try:
                        await page.wait_for_load_state("networkidle", timeout=20000)
                    except Exception:
                        pass
                    await page.wait_for_timeout(1500)
                    rows = await page.evaluate(FIND_ROWS, TEAMS)
                    collect(rows)
                    all_rows.extend(rows)
                    if n == 0 and label.endswith(" 1"):
                        (DEBUG / "round1.txt").write_text(
                            "\n\n=====\n\n".join(r["text"] for r in rows) or await page.inner_text("body"),
                            encoding="utf-8")
        await browser.close()

    (DEBUG / "rows.txt").write_text("\n\n=====\n\n".join(r["text"] for r in all_rows[:40]), encoding="utf-8")
    (DEBUG / "xhr.json").write_text(json.dumps(xhr_log[:40], ensure_ascii=False, indent=1), encoding="utf-8")
    out_path = ROOT / "data.json"
    old = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    print(f"נמצאו {len(games)} משחקים")
    if not games:
        print("לא נמצאו משחקים — שומרים את הנתונים הקודמים")
        return
    if old.get("games") == games:
        print("אין שינוי")
        return
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="minutes")
    out_path.write_text(json.dumps({"updated": now, "source": URLS[0], "games": games},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    print("data.json עודכן")

if __name__ == "__main__":
    asyncio.run(main())
