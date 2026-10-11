"""
Readers for official league sources. Each returns a list of fixtures:

  {"home", "away", "alt_home", "alt_away",   # names (alt_* = extra spellings for matching)
   "utc": datetime | None,                   # kickoff in UTC when known
   "day": "YYYY-MM-DD" | None,               # local date when only the day is known
   "confirmed": bool,                        # exact day+time published by the league
   "state": "pre" | "live" | "post" | "pp",
   "score": [h, a] | None,
   "venue", "city"}

Everything here uses the league's own website or its official data feed.
"""
import gzip, html, json, re, time, urllib.error, urllib.request, zlib
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"


def get(url, headers=None, as_json=True, tries=2):
    h = {"User-Agent": UA, "Accept": "application/json, text/html;q=0.9, */*;q=0.5", "Accept-Encoding": "gzip, deflate",
         "Accept-Language": "en-GB,en;q=0.8"}
    h.update(headers or {})
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30) as r:
                raw = r.read()
                enc = r.headers.get("Content-Encoding", "")
                raw = gzip.decompress(raw) if enc == "gzip" else zlib.decompress(raw) if enc == "deflate" else raw
                txt = raw.decode("utf-8", "replace")
                return json.loads(txt) if as_json else txt
        except Exception as e:  # noqa: BLE001 - reported by caller
            last = e
            time.sleep(2 + 2 * i)
    raise RuntimeError(f"{url[:90]}: {last}")


def season_year(now):
    return now.year if now.month >= 7 else now.year - 1


def _fx(**kw):
    base = {"alt_home": [], "alt_away": [], "utc": None, "day": None, "confirmed": False, "state": "pre",
            "score": None, "venue": "", "city": ""}
    base.update(kw)
    return base


def _round_confirmed(kickoffs):
    """A round counts as scheduled once its kickoffs are spread over several distinct slots
    (before TV picks every game sits in the same placeholder slot)."""
    return len(set(kickoffs)) >= 3


# ---------------- Premier League (premierleague.com data feed) ----------------
def premier_league(now):
    yr = season_year(now)
    base = f"https://sdp-prem-prod.premier-league-prod.pulselive.com/api/v2/matches?competition=8&season={yr}&_limit=100"
    hdr = {"Origin": "https://www.premierleague.com", "Referer": "https://www.premierleague.com/"}
    items, nxt, guard = [], None, 0
    while guard < 20:
        js = get(base + (f"&_next={nxt}" if nxt else ""), hdr)
        items += js.get("data", [])
        nxt = (js.get("pagination") or {}).get("_next")
        guard += 1
        if not nxt:
            break
    by_week = {}
    for m in items:
        by_week.setdefault(m.get("matchWeek"), []).append(m.get("kickoff"))
    out = []
    for m in items:
        tz = ZoneInfo(m.get("kickoffTimezoneString") or "Europe/London")
        loc = datetime.strptime(m["kickoff"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
        period = (m.get("period") or "").lower()
        state = "post" if period == "fulltime" else "pre" if period in ("prematch", "") else \
            "pp" if "postpon" in period or "abandon" in period or "cancel" in period else "live"
        h, a = m["homeTeam"], m["awayTeam"]
        score = [h.get("score"), a.get("score")] if state in ("post", "live") and h.get("score") is not None else None
        conf = _round_confirmed(by_week.get(m.get("matchWeek"), []))
        ground = m.get("ground") or ""
        out.append(_fx(home=h["name"], away=a["name"], alt_home=[h.get("shortName", "")], alt_away=[a.get("shortName", "")],
                       utc=loc.astimezone(timezone.utc) if conf or state != "pre" else None,
                       day=None if conf or state != "pre" else loc.strftime("%Y-%m-%d"),
                       confirmed=conf or state != "pre", state=state, score=score,
                       venue=ground.split(",")[0].strip(), city=ground.split(",")[-1].strip() if "," in ground else ""))
    return out


# ---------------- LaLiga (laliga.com public API) ----------------
LALIGA_KEY = "c13c3a8e2f6b46da9c5c425cf61fab3e"  # public key used by laliga.com itself


def laliga(now):
    yr = season_year(now)
    hdr = {"Ocp-Apim-Subscription-Key": LALIGA_KEY, "Origin": "https://www.laliga.com", "Referer": "https://www.laliga.com/"}
    out = []
    for week in range(1, 39):
        js = get(f"https://apim.laliga.com/public-service/api/v1/matches?subscriptionSlug=laliga-easports-{yr}&week={week}&limit=50", hdr)
        for m in js.get("matches", []):
            st = (m.get("status") or "").lower()
            state = "post" if st == "fulltime" else "pre" if st in ("prematch", "") else \
                "pp" if "postpon" in st or "suspend" in st or "cancel" in st else "live"
            t = m.get("time")
            h, a, v = m.get("home_team") or {}, m.get("away_team") or {}, m.get("venue") or {}
            utc = datetime.fromisoformat(t).astimezone(timezone.utc) if t else None
            day = None if t else (m.get("date") or "")[:10] or None
            score = [m.get("home_score"), m.get("away_score")] if state in ("post", "live") and m.get("home_score") is not None else None
            out.append(_fx(home=h.get("nickname") or h.get("name", ""), away=a.get("nickname") or a.get("name", ""),
                           alt_home=[h.get("name", ""), h.get("boundname", "")], alt_away=[a.get("name", ""), a.get("boundname", "")],
                           utc=utc, day=day, confirmed=bool(t), state=state, score=score, venue=v.get("name", ""), city=v.get("city", "")))
    return out


# ---------------- Bundesliga / 2. Bundesliga (bundesliga.com matchday pages) ----------------
ROW = re.compile(r'class="matchRow[^"]*"(.*?)<script type="application/ld\+json">(.*?)</script>', re.S)


def _bundesliga(now, comp):
    yr = season_year(now)
    out = []
    for md in range(1, 35):
        page = get(f"https://www.bundesliga.com/en/{comp}/matchday/{yr}-{yr + 1}/{md}", {"Accept": "text/html"}, as_json=False)
        for body, ld in ROW.findall(page):
            try:
                j = json.loads(html.unescape(ld))
            except json.JSONDecodeError:
                continue
            name = j.get("name", "")
            m = re.match(r"Matchday \d+: (.+?) - (.+?)(?:, ([^,]+))?$", name)
            if not m:
                continue
            start = j.get("startDate")
            utc = datetime.strptime(start, "%Y-%m-%dT%H:%M:%S%z").astimezone(timezone.utc) if start else None
            ks = re.search(r'class="kickoff-time ([^"]*)"', body)
            kcls = ks.group(1) if ks else ""
            scores = re.findall(r'class="[^"]*score[^"]*"[^>]*>\s*(\d+)\s*<', body)
            ev = j.get("eventStatus", "")
            if "Postponed" in ev or "Cancelled" in ev:
                state = "pp"
            elif len(scores) >= 2 and "prematch" not in kcls and "date-quality" not in kcls:
                state = "live" if "live" in kcls else "post"
            else:
                state = "pre"
            conf = "date-quality" not in kcls
            out.append(_fx(home=m.group(1), away=m.group(2), utc=utc if conf else None,
                           day=None if conf else (utc.strftime("%Y-%m-%d") if utc else None),
                           confirmed=conf, state=state,
                           score=[int(scores[0]), int(scores[1])] if state in ("post", "live") else None,
                           venue=(m.group(3) or "").strip()))
        time.sleep(0.5)
    return out


def bundesliga(now):
    return _bundesliga(now, "bundesliga")


def bundesliga2(now):
    return _bundesliga(now, "2bundesliga")


# ---------------- Serie A (legaseriea.it data feed) ----------------
SERIE_A_SEASONS = {2026: "serie-a::Football_Season::ed7fdc2a3e7b408b942ec177b7b956b5"}


def serie_a(now):
    sid = SERIE_A_SEASONS[season_year(now)]
    js = get(f"https://api-sdp.legaseriea.it/v1/serie-a/football/seasons/{urllib.request.quote(sid, safe='')}/matches?locale=en-GB",
             {"Origin": "https://en.legaseriea.it", "Referer": "https://en.legaseriea.it/"})
    out = []
    for m in js.get("matches", []):
        st = (m.get("status") or "").upper()
        state = "post" if st == "FINISHED" else "pre" if st in ("UPCOMING", "") else \
            "pp" if st in ("POSTPONED", "SUSPENDED", "CANCELLED", "ABANDONED") else "live"
        unknown = bool(m.get("isUnknownKickOffTime"))
        utc = datetime.fromisoformat(m["matchDateUtc"].replace("Z", "+00:00")) if m.get("matchDateUtc") else None
        h, a = m.get("home") or {}, m.get("away") or {}
        hs, as_ = m.get("providerHomeScore"), m.get("providerAwayScore")
        out.append(_fx(home=h.get("officialName", ""), away=a.get("officialName", ""),
                       alt_home=[h.get("shortName", ""), h.get("mediaName", "")], alt_away=[a.get("shortName", ""), a.get("mediaName", "")],
                       utc=None if unknown and state == "pre" else utc,
                       day=(m.get("matchDateLocal") or "")[:10] if unknown and state == "pre" else None,
                       confirmed=not unknown or state != "pre", state=state,
                       score=[hs, as_] if state in ("post", "live") and hs is not None else None,
                       venue=m.get("stadiumName") or "", city=m.get("cityName") or ""))
    return out


# ---------------- Eredivisie (eredivisie.com fixtures feed) ----------------
def eredivisie(now):
    js = get("https://eredivisie.com/cache/site/EredivisieEN/json/fixtures.json")
    out = []
    for rnd in js.values():
        ms = rnd.get("matches", [])
        conf_round = _round_confirmed([m.get("date") for m in ms])
        for m in ms:
            st, pr = (m.get("status") or "").lower(), (m.get("progress") or "").lower()
            state = "post" if st == "played" else "pp" if "postpon" in st or "postpon" in pr or "cancel" in st else \
                "live" if st in ("playing", "live") or pr in ("first_half", "second_half", "half_time", "extra_time") else "pre"
            loc = datetime.fromisoformat(m["date"]) if m.get("date") else None
            h, a = m.get("home") or {}, m.get("away") or {}
            conf = conf_round or state != "pre"
            out.append(_fx(home=h.get("name", ""), away=a.get("name", ""),
                           alt_home=[h.get("sportsAllianceTeam", "")], alt_away=[a.get("sportsAllianceTeam", "")],
                           utc=loc.astimezone(timezone.utc) if loc and conf else None,
                           day=loc.strftime("%Y-%m-%d") if loc and not conf else None,
                           confirmed=conf, state=state,
                           score=[h.get("score"), a.get("score")] if state in ("post", "live") and h.get("score") is not None else None))
    return out


SOURCES = {
    "eng.1": ("פרמייר ליג", "https://www.premierleague.com/en/matches", premier_league),
    "esp.1": ("LALIGA", "https://www.laliga.com/en-GB/laliga-easports/calendar", laliga),
    "ger.1": ("Bundesliga", "https://www.bundesliga.com/en/bundesliga/matchday", bundesliga),
    "ger.2": ("2. Bundesliga", "https://www.bundesliga.com/en/2bundesliga/matchday", bundesliga2),
    "ita.1": ("Lega Serie A", "https://en.legaseriea.it/serie-a/fixtures-results", serie_a),
    "ned.1": ("Eredivisie", "https://eredivisie.com/competition/fixtures/", eredivisie),
}
