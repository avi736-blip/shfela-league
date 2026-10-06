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
  return hits.filter(h => !hits.some(o => o !== h && h.el.contains(o.el))).map(h => ({text: h.text, order: h.order}));
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

def parse_row(text, order):
    a, b = order
    if (a, b) in GAME_ID:
        gid, swap = GAME_ID[(a, b)], False
    elif (b, a) in GAME_ID:
        gid, swap = GAME_ID[(b, a)], True
    else:
        return None, None
    g = {}
    work = text
    d = DATE_RE.search(work)
    if d:
        dd, mm, yy = d.groups()
        yy = yy if len(yy) == 4 else "20" + yy
        g["date"] = f"{int(dd):02d}/{int(mm):02d}/{yy}"
        work = work.replace(d.group(0), " ")
    t = TIME_RE.search(work)
    if t:
        g["time"] = f"{t.group(1)}:{t.group(2)}"
        work = work.replace(t.group(0), " ")
    sc = SCORE_RE.search(work)
    if sc:
        x, y = int(sc.group(1)), int(sc.group(2))
        g["score"] = [y, x] if swap else [x, y]
    for line in text.splitlines():
        line = line.strip()
        if line and VENUE_WORDS.search(line) and not any(tn and tn in norm(line) for tn in TEAMS):
            v = re.sub(r"^(מגרש|אצטדיון|איצטדיון)\s*[:：]\s*", "", line).strip()
            if 2 < len(v) < 120:
                g["venue"] = v
                break
    return gid, g

async def main():
    from playwright.async_api import async_playwright
    DEBUG.mkdir(exist_ok=True)
    games, xhr_log = {}, []
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
            await page.wait_for_timeout(3000)
            collect(await page.evaluate(FIND_ROWS, TEAMS))
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
                    if n == 0 and label.endswith(" 1"):
                        (DEBUG / "round1.txt").write_text(
                            "\n\n=====\n\n".join(r["text"] for r in rows) or await page.inner_text("body"),
                            encoding="utf-8")
        await browser.close()

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
