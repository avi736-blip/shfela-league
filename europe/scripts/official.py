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


# ---------------- UEFA competitions (uefa.com match feed) ----------------
FIFA3 = {"ENG": "England", "SCO": "Scotland", "WAL": "Wales", "NIR": "Northern Ireland", "IRL": "Ireland", "GER": "Germany",
         "ITA": "Italy", "ESP": "Spain", "FRA": "France", "POR": "Portugal", "NED": "Netherlands", "BEL": "Belgium",
         "AUT": "Austria", "SUI": "Switzerland", "DEN": "Denmark", "NOR": "Norway", "SWE": "Sweden", "FIN": "Finland",
         "ISL": "Iceland", "FRO": "Faroe Islands", "EST": "Estonia", "LVA": "Latvia", "LTU": "Lithuania", "POL": "Poland",
         "CZE": "Czechia", "SVK": "Slovakia", "HUN": "Hungary", "ROU": "Romania", "BUL": "Bulgaria", "GRE": "Greece",
         "CYP": "Cyprus", "TUR": "Türkiye", "CRO": "Croatia", "SRB": "Serbia", "SVN": "Slovenia", "BIH": "Bosnia and Herzegovina",
         "MNE": "Montenegro", "ALB": "Albania", "MKD": "North Macedonia", "KOS": "Kosovo", "MLT": "Malta", "GIB": "Gibraltar",
         "AND": "Andorra", "SMR": "San Marino", "LIE": "Liechtenstein", "LUX": "Luxembourg", "MDA": "Moldova",
         "BLR": "Belarus", "GEO": "Georgia", "ARM": "Armenia", "AZE": "Azerbaijan", "KAZ": "Kazakhstan"}


def _uefa(now, comp_id):
    yr = season_year(now) + 1  # UEFA names the season by the year it ends
    out, offset = [], 0
    while offset < 2000:
        js = get(f"https://match.uefa.com/v5/matches?competitionId={comp_id}&seasonYear={yr}&order=ASC&offset={offset}&limit=200")
        if not js:
            break
        for m in js:
            h, a = m.get("homeTeam") or {}, m.get("awayTeam") or {}
            if h.get("isPlaceHolder") or a.get("isPlaceHolder"):
                continue
            ko = m.get("kickOffTime") or {}
            st = (m.get("status") or "").upper()
            state = "post" if st == "FINISHED" else "live" if st == "LIVE" else \
                "pp" if st in ("POSTPONED", "CANCELLED", "ABANDONED", "SUSPENDED") else "pre"
            sc = ((m.get("score") or {}).get("total") or {})
            stad = m.get("stadium") or {}
            tr = (stad.get("translations") or {})
            vname = ((tr.get("officialName") or tr.get("name") or {}).get("EN")) or ""
            city = (((stad.get("city") or {}).get("translations") or {}).get("name") or {}).get("EN", "")
            utc = datetime.fromisoformat(ko["dateTime"].replace("Z", "+00:00")) if ko.get("dateTime") else None
            out.append(_fx(home=h.get("internationalName", ""), away=a.get("internationalName", ""),
                           alt_home=[h.get("teamCode", "")], alt_away=[a.get("teamCode", "")],
                           utc=utc, day=None if utc else ko.get("date"), confirmed=bool(utc), state=state,
                           score=[sc.get("home"), sc.get("away")] if state in ("post", "live") and sc.get("home") is not None else None,
                           venue=vname, city=city, ext_id="uefa-" + str(m.get("id")),
                           country=FIFA3.get(stad.get("countryCode") or ""),
                           logos=[h.get("logoUrl", ""), a.get("logoUrl", "")]))
        if len(js) < 200:
            break
        offset += 200
    return out


def ucl(now): return _uefa(now, 1)
def uel(now): return _uefa(now, 14)
def uecl(now): return _uefa(now, 2019)
def unl(now): return _uefa(now, 2014)


# ---------------- Ekstraklasa, Poland (ekstraklasa.org match centre) ----------------
EKSTRAKLASA_SEASONS = {2026: "efed6802-8252-44a1-9d1b-943d224c4b50"}


def ekstraklasa(now):
    sid = EKSTRAKLASA_SEASONS[season_year(now)]
    out = []
    for week in range(1, 35):
        js = get(f"https://api.centrum-meczowe.ekstraklasa.org/v1/matches?season_id={sid}&week={week}",
                 {"Referer": "https://ekstraklasa.org/", "Origin": "https://ekstraklasa.org"})
        for m in js.get("data", []):
            st = (m.get("status") or "").lower()
            if m.get("postponed"):
                state = "pp"
            else:
                state = "post" if st == "played" else "live" if st in ("playing", "live", "in_play") else "pre"
            dt = m.get("match_datetime")
            utc = datetime.fromisoformat(dt).astimezone(timezone.utc) if dt else None
            out.append(_fx(home=m.get("home_team_name", ""), away=m.get("away_team_name", ""),
                           alt_home=[m.get("home_team_official_name", "")], alt_away=[m.get("away_team_official_name", "")],
                           utc=utc, day=None if utc else m.get("date"), confirmed=bool(utc), state=state,
                           score=[m.get("home_score"), m.get("away_score")] if state in ("post", "live") else None))
        time.sleep(0.3)
    return out


# ---------------- Allsvenskan, Sweden (allsvenskan.se data service) ----------------
SWE_QUERY = """query matchesForLeague($configLeagueName: String!, $configSeasonStartYear: Int!, $startDate: String, $endDate: String) {
  matchesForLeague(configLeagueName: $configLeagueName, configSeasonStartYear: $configSeasonStartYear, startDate: $startDate, endDate: $endDate) {
    matches { id startDate homeTeamName visitingTeamName homeTeamScore visitingTeamScore status extendedStatus round arenaName }
  }
}"""


def allsvenskan(now):
    yr = now.year
    body = json.dumps({"query": SWE_QUERY, "operationName": "matchesForLeague",
                       "variables": {"configLeagueName": "allsvenskan", "configSeasonStartYear": yr,
                                     "startDate": f"{yr}-01-01", "endDate": f"{yr}-12-31"}}).encode()
    req = urllib.request.Request("https://gql.sportomedia.se/graphql", data=body, method="POST",
                                 headers={"User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json",
                                          "Origin": "https://allsvenskan.se", "Referer": "https://allsvenskan.se/"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                js = json.loads(r.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 3:
                raise
            time.sleep(20 * (attempt + 1))  # rate limited: wait and try again
    out = []
    for m in js["data"]["matchesForLeague"]["matches"]:
        st = (m.get("extendedStatus") or m.get("status") or "").upper()
        state = "post" if st == "FINISHED" else "pre" if st in ("UPCOMING", "NOT_STARTED", "") else \
            "pp" if "POSTPON" in st or "CANCEL" in st else "live"
        utc = datetime.fromisoformat(m["startDate"].replace("Z", "+00:00")) if m.get("startDate") else None
        out.append(_fx(home=m.get("homeTeamName", ""), away=m.get("visitingTeamName", ""), utc=utc, confirmed=bool(utc),
                       state=state, score=[m.get("homeTeamScore"), m.get("visitingTeamScore")] if state in ("post", "live") else None,
                       venue=(m.get("arenaName") or "").strip()))
    return out


# ---------------- Eliteserien, Norway (eliteserien.no fixture list) ----------------
NOR_ROW = re.compile(r'<tr class="[^"]*schedule__match[^"]*">(.*?)</tr>', re.S)


def eliteserien(now):
    page = get("https://www.eliteserien.no/terminliste", {"Accept": "text/html"}, as_json=False)
    tz, out = ZoneInfo("Europe/Oslo"), []
    for row in NOR_ROW.findall(page):
        tm = re.search(r'--teams">\s*(.*?)\s+-\s+<span class="schedule__team--opponent">\s*(.*?)\s*</span>', row, re.S)
        dt = re.search(r'<span>(\d{1,2})\.(\d{1,2})\.<span[^>]*>(\d{4})</span>', row)
        if not tm or not dt:
            continue
        hm = re.search(r'schedule__time">\s*(\d{1,2}):(\d{2})', row)
        venue = re.search(r'<br\s*/?>\s*([^<]+?)\s*</td>', row)
        d, mth, y = int(dt.group(1)), int(dt.group(2)), int(dt.group(3))
        utc = datetime(y, mth, d, int(hm.group(1)), int(hm.group(2)), tzinfo=tz).astimezone(timezone.utc) if hm else None
        out.append(_fx(home=html.unescape(tm.group(1)).strip(), away=html.unescape(tm.group(2)).strip(), utc=utc,
                       day=None if utc else f"{y}-{mth:02d}-{d:02d}", confirmed=bool(utc),
                       venue=html.unescape(venue.group(1)).strip() if venue else ""))
    return out


# ---------------- Erovnuli Liga, Georgia (erovnuliliga.ge calendar) ----------------
GEO_GAME = re.compile(r'<div class="e-game-teaser[^"]*"\s+data-id="\d+"\s+data-status="([a-z]+)">(.*?)class="col-auto gt-arrow"', re.S)


def erovnuli(now):
    page = get("https://erovnuliliga.ge/en/calendar", {"Accept": "text/html"}, as_json=False)
    out = []
    for status, blk in GEO_GAME.findall(page):
        names = re.findall(r'class="grs-name normal[^"]*">([^<]+)<', blk)
        if len(names) < 2:
            continue
        t = re.search(r'<time datetime="([^"]+)"', blk)
        utc = datetime.fromisoformat(t.group(1).replace("Z", "+00:00")) if t else None
        sc = re.findall(r'class="[^"]*score[^"]*"[^>]*>\s*(\d+)\s*<', blk)
        state = "post" if status in ("finished", "ended") else "live" if status in ("live", "playing") else \
            "pp" if "postpon" in status else "pre"
        out.append(_fx(home=html.unescape(names[0]).strip(), away=html.unescape(names[1]).strip(), utc=utc, confirmed=bool(utc),
                       state=state, score=[int(sc[0]), int(sc[1])] if state in ("post", "live") and len(sc) >= 2 else None))
    return out


# ---------------- Ligue 1, France (ligue1.com data feed) ----------------
def ligue1(now):
    cal = get(f"https://ma-api.ligue1.fr/championship-calendar/1?season={season_year(now)}",
              {"Origin": "https://ligue1.com", "Referer": "https://ligue1.com/"})
    lo, hi = now - timedelta(days=4), now + timedelta(days=120)
    out = []
    for gw in (cal.get("gameWeeks") or {}).values():
        start = datetime.fromisoformat(gw["startDate"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(gw["endDate"].replace("Z", "+00:00"))
        if end < lo or start > hi:
            continue
        ms = []
        for mid in gw.get("matchesIds", []):
            try:
                ms.append(get(f"https://ma-api.ligue1.fr/championship-match/{mid}", {"Origin": "https://ligue1.com", "Referer": "https://ligue1.com/"}))
            except RuntimeError:
                continue
        conf_round = _round_confirmed([m.get("date") for m in ms])
        for m in ms:
            per = (m.get("period") or "").lower()
            state = "post" if per in ("fullTime".lower(), "ended", "postmatch") else "pre" if per in ("prematch", "") else \
                "pp" if "postpon" in per or "cancel" in per else "live"
            h, a = (m.get("home") or {}).get("clubIdentity") or {}, (m.get("away") or {}).get("clubIdentity") or {}
            utc = datetime.fromisoformat(m["date"].replace("Z", "+00:00")) if m.get("date") else None
            conf = conf_round or state != "pre"
            st = m.get("stadium") or {}
            out.append(_fx(home=h.get("name", ""), away=a.get("name", ""), alt_home=[h.get("officialName", "")],
                           alt_away=[a.get("officialName", "")], utc=utc if conf else None,
                           day=None if conf or not utc else utc.strftime("%Y-%m-%d"), confirmed=conf, state=state,
                           venue=(st.get("name") or "").title(), city=((st.get("address") or {}).get("city") or "").title()))
    return out


# ---------------- Liga Portugal (ligaportugal.pt data feed) ----------------
def liga_portugal(now):
    yr = season_year(now)
    base = f"https://www.ligaportugal.pt/api/v1/competition/matches?season={yr}{yr + 1}&competition=ligaportugalbetclic"
    hdr = {"Accept": "*/*", "Accept-Language": "en", "Referer": "https://www.ligaportugal.pt/"}
    # the feed returns one matchweek at a time; find which parameter selects the matchweek
    param = None
    for cand in ("round", "matchweek", "matchweekNumber", "jornada"):
        js = get(f"{base}&{cand}=2", hdr)
        if js and all(m.get("matchweekNumber") == 2 for m in js):
            param = cand
            break
    print(f"  liga portugal: matchweek parameter = {param}")
    if not param:
        raise RuntimeError("liga portugal: no matchweek parameter works")
    rows = []
    for mw in range(1, 35):
        rows += get(f"{base}&{param}={mw}", hdr) or []
        time.sleep(0.3)
    out = []
    for m in rows:
        if m.get("canceledFixture") or m.get("postponedFixture") or m.get("notPlayedFixture"):
            state = "pp"
        elif m.get("homeTeamGoals") is not None and m.get("fixtureStateTypeId") in (5, 6):
            state = "post"
        else:
            state = "pre"
        d = m.get("fixtureDate") or m.get("matchDate")
        utc = datetime.fromisoformat(d.replace("Z", "+00:00")) if d else None
        conf = bool(m.get("fixtureDateIsDefined")) and utc is not None
        h, a = m.get("homeTeam") or {}, m.get("awayTeam") or {}
        out.append(_fx(home=h.get("name", ""), away=a.get("name", ""), alt_home=[h.get("fullName", "")], alt_away=[a.get("fullName", "")],
                       utc=utc if conf else None, day=None if conf or not utc else utc.strftime("%Y-%m-%d"), confirmed=conf, state=state,
                       score=[m.get("homeTeamGoals"), m.get("awayTeamGoals")] if state == "post" else None))
    return out


# ---------------- EFL Championship (efl.com data feed) ----------------
def efl_championship(now):
    url = f"https://multi-club-matches.webapi.gc.eflservices.co.uk/v2/matches?competitionID=10&seasonID={season_year(now)}"
    hdr = {"Origin": "https://www.efl.com", "Referer": "https://www.efl.com/"}
    out, guard = [], 0
    while url and guard < 80:
        js = get(url, hdr)
        for m in js.get("data", []):
            at = m.get("attributes") or {}
            per = (at.get("matchPeriod") or "").lower()
            state = "post" if per == "fulltime" else "pre" if per in ("prematch", "", "none") else \
                "pp" if at.get("postponementReason") or "postpon" in per else "live"
            k = at.get("kickOffDateUTC")
            utc = datetime.strptime(k, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) if k else None
            conf = utc is not None and not at.get("TBC")
            h, a = at.get("homeTeam") or {}, at.get("awayTeam") or {}
            out.append(_fx(home=h.get("name", ""), away=a.get("name", ""), alt_home=[h.get("shortName") or ""], alt_away=[a.get("shortName") or ""],
                           utc=utc if conf else None, day=None if conf or not utc else utc.strftime("%Y-%m-%d"), confirmed=conf, state=state,
                           score=[h.get("score"), a.get("score")] if state in ("post", "live") and h.get("score") is not None else None))
        url = (js.get("links") or {}).get("next")
        guard += 1
    return out


# ---------------- Swiss Super League (sfl.ch data feed) ----------------
SFL_COMP = "e0lck99w8meo9qoalfrxgo33o"


def swiss_super_league(now):
    base = "https://origins-webex-orchestrator.origins-digital.com/trpc/"
    hdr = {"Origin": "https://sfl.ch", "Referer": "https://sfl.ch/", "x-account-key": "Os-hXumIK",
           "Content-Type": "application/json"}  # public key used by sfl.ch itself
    q = lambda d: urllib.request.quote(json.dumps(d, separators=(",", ":")))
    days = get(base + "matchDays.getList?input=" + q({"competitionProviderId": SFL_COMP}), hdr)["result"]["data"]
    out = []
    for md in days:
        evs = get(base + "matchDays.getEvents?input=" + q({"competitionProviderId": SFL_COMP, "matchDay": str(md), "language": "de"}), hdr)
        for m in evs["result"]["data"]:
            gs = (m.get("gameStatus") or "").lower()
            state = "post" if gs in ("post-game", "final", "ended") else "pre" if gs in ("pre-game", "scheduled", "") else \
                "pp" if "postpon" in gs or "cancel" in gs else "live"
            day, tm = (m.get("date") or "")[:10], m.get("time")
            utc = datetime.fromisoformat(f"{day}T{tm.replace('Z', '')}+00:00") if day and tm else None
            out.append(_fx(home=m.get("homeTeamName", ""), away=m.get("awayTeamName", ""), utc=utc, day=None if utc else day or None,
                           confirmed=utc is not None, state=state,
                           score=[m.get("homeScore"), m.get("awayScore")] if state in ("post", "live") and m.get("homeScore") is not None else None,
                           venue=m.get("stadiumName") or ""))
        time.sleep(0.3)
    return out


# ---------------- Scottish Premiership (spfl.co.uk fixtures widget, Opta feed) ----------------
SPFL_FEED = "https://omo.akamai.opta.net/auth/competition.php?feed_type=f1&competition=14&season_id={yr}&user=OW2017&psw=dXWg5gVZ&sps=widgets&jsoncallback=f1_14_{yr}"


def spfl(now):
    yr = season_year(now)
    raw = get(SPFL_FEED.format(yr=yr), {"Referer": "https://spfl.co.uk/", "Accept": "*/*"}, as_json=False)
    doc = json.loads(raw[raw.index("(") + 1:raw.rindex(")")])["SoccerFeed"]["SoccerDocument"]
    teams = {t["@attributes"]["uID"]: t for t in doc.get("Team", [])}
    rows, by_md = [], {}
    for m in doc.get("MatchData", []):
        info = m["MatchInfo"]; at = info["@attributes"]
        by_md.setdefault(at.get("MatchDay"), []).append(info.get("DateUtc"))
        rows.append(m)
    out = []
    for m in rows:
        info = m["MatchInfo"]; at = info["@attributes"]
        side = {td["@attributes"]["Side"]: td for td in m.get("TeamData", [])}
        h, a = teams.get(side["Home"]["@attributes"]["TeamRef"], {}), teams.get(side["Away"]["@attributes"]["TeamRef"], {})
        per = (at.get("Period") or "").lower()
        state = "post" if per == "fulltime" else "pre" if per == "prematch" else "pp" if "postpon" in per or "abandon" in per else "live"
        utc = datetime.strptime(info["DateUtc"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) if info.get("DateUtc") else None
        conf = _round_confirmed(by_md.get(at.get("MatchDay"), [])) or state != "pre"
        stats = {s["@attributes"]["Type"]: s.get("@value", "") for s in m.get("Stat", []) if isinstance(s, dict)}
        hs, as_ = side["Home"].get("@value", ""), side["Away"].get("@value", "")
        out.append(_fx(home=h.get("Name", ""), away=a.get("Name", ""), alt_home=[h.get("OfficialTeamName", "")], alt_away=[a.get("OfficialTeamName", "")],
                       utc=utc if conf else None, day=None if conf or not utc else utc.strftime("%Y-%m-%d"), confirmed=conf, state=state,
                       score=[int(hs), int(as_)] if state in ("post", "live") and str(hs).isdigit() and str(as_).isdigit() else None,
                       venue=stats.get("Venue", ""), city=stats.get("City", "")))
    return out


# ---------------- Danish Superliga (superliga.dk data feed) ----------------
SUPERLIGA_TOKEN = "5b6ab6f5eb84c60031bbbd24"  # public token used by superliga.dk itself


def superliga(now):
    q = f"appName=dk.releaze.livecenter.spdk&access_token={SUPERLIGA_TOKEN}&env=production&locale=da"
    t = get(f"https://api.superliga.dk/tournaments/46?appName=superligadk&access_token={SUPERLIGA_TOKEN}&env=production&locale=da",
            {"Origin": "https://superliga.dk", "Referer": "https://superliga.dk/"})
    season = None
    for key in ("seasonId", "currentSeasonId", "activeSeasonId"):
        season = season or (t.get(key) if isinstance(t, dict) else None)
    season = season or (((t.get("seasons") or [{}])[0]).get("id") if isinstance(t, dict) and t.get("seasons") else None) or 35802
    js = get(f"https://api.superliga.dk/events-v2?{q}&seasonId={season}", {"Origin": "https://superliga.dk", "Referer": "https://superliga.dk/"})
    out = []
    for m in js.get("events", []):
        st = (m.get("statusType") or "").lower()
        state = "post" if st == "finished" else "pre" if st == "notstarted" else "pp" if st in ("postponed", "cancelled", "canceled", "interrupted") else "live"
        utc = datetime.fromisoformat(m["startDate"].replace("Z", "+00:00")) if m.get("startDate") else None
        tbd = (m.get("properties") or {}).get("startDateTimeToBeDecided") == "yes"
        sc = m.get("score") or {}
        out.append(_fx(home=m.get("homeName", ""), away=m.get("awayName", ""), utc=None if tbd else utc,
                       day=utc.strftime("%Y-%m-%d") if tbd and utc else None, confirmed=not tbd and utc is not None, state=state,
                       score=[sc.get("home"), sc.get("away")] if state in ("post", "live") else None,
                       venue=(m.get("properties") or {}).get("venueName", "")))
    return out


# ---------------- SuperSport HNL, Croatia (hnl.hr schedule) ----------------
def hnl(now):
    page = get("https://hnl.hr/supersport-hnl/raspored-i-rezultati/", {"Accept": "text/html"}, as_json=False)
    tz, out, rnd = ZoneInfo("Europe/Zagreb"), [], 0
    rows = []
    for m in re.finditer(r'<tr class="th"><th[^>]*>(\d+)\. kolo|<tr><td>(\d{2})\.(\d{2})\.(\d{4})\.\s*(\d{1,2}):(\d{2})'
                         r'<div class="natjecanje">[^<]*</div><div class="mjesto">([^<]*)</div></td><td>([^<]+)</td><td>([^<]*)</td>'
                         r'<td>\s*:\s*</td><td>([^<]*)</td><td>([^<]+)</td>', page):
        if m.group(1):
            rnd = int(m.group(1)); continue
        d, mo, y, hh, mi = (int(m.group(i)) for i in range(2, 7))
        utc = datetime(y, mo, d, hh, mi, tzinfo=tz).astimezone(timezone.utc)
        rows.append((rnd, utc, m))
    by_r = {}
    for rnd, utc, _ in rows:
        by_r.setdefault(rnd, []).append(utc)
    for rnd, utc, m in rows:
        hs, as_ = m.group(9).strip(), m.group(10).strip()
        state = "post" if hs.isdigit() and as_.isdigit() else "pre"
        conf = _round_confirmed(by_r.get(rnd, [])) or state != "pre"
        place = html.unescape(m.group(7)).rsplit(",", 1)
        out.append(_fx(home=html.unescape(m.group(8)).strip(), away=html.unescape(m.group(11)).strip(),
                       utc=utc if conf else None, day=None if conf else utc.astimezone(tz).strftime("%Y-%m-%d"), confirmed=conf,
                       state=state, score=[int(hs), int(as_)] if state == "post" else None,
                       venue=place[0].strip(), city=place[1].strip() if len(place) > 1 else ""))
    return out


SOURCES = {
    "uefa.champions": ("UEFA", "https://www.uefa.com/uefachampionsleague/fixtures-results/", ucl),
    "uefa.europa": ("UEFA", "https://www.uefa.com/uefaeuropaleague/fixtures-results/", uel),
    "uefa.europa.conf": ("UEFA", "https://www.uefa.com/uefaconferenceleague/fixtures-results/", uecl),
    "uefa.nations": ("UEFA", "https://www.uefa.com/uefanationsleague/fixtures-results/", unl),
    "eng.1": ("פרמייר ליג", "https://www.premierleague.com/en/matches", premier_league),
    "esp.1": ("LALIGA", "https://www.laliga.com/en-GB/laliga-easports/calendar", laliga),
    "ger.1": ("Bundesliga", "https://www.bundesliga.com/en/bundesliga/matchday", bundesliga),
    "ger.2": ("2. Bundesliga", "https://www.bundesliga.com/en/2bundesliga/matchday", bundesliga2),
    "ita.1": ("Lega Serie A", "https://en.legaseriea.it/serie-a/fixtures-results", serie_a),
    "ned.1": ("Eredivisie", "https://eredivisie.com/competition/fixtures/", eredivisie),
    "pol.1": ("Ekstraklasa", "https://ekstraklasa.org/terminarz", ekstraklasa),
    "swe.1": ("Allsvenskan", "https://allsvenskan.se/matcher", allsvenskan),
    "nor.1": ("Eliteserien", "https://www.eliteserien.no/terminliste", eliteserien),
    "geo.1": ("Erovnuli Liga", "https://erovnuliliga.ge/en/calendar", erovnuli),
    "fra.1": ("Ligue 1", "https://ligue1.com/fr/competitions/ligue1mcdonalds/calendar", ligue1),
    "por.1": ("Liga Portugal", "https://www.ligaportugal.pt/pt/liga/calendario/", liga_portugal),
    "eng.2": ("EFL", "https://www.efl.com/competitions/sky-bet-championship/fixtures/", efl_championship),
    "sui.1": ("Swiss Football League", "https://www.sfl.ch/superleague/", swiss_super_league),
    "sco.1": ("SPFL", "https://spfl.co.uk/league/premiership/fixtures", spfl),
    "den.1": ("Superliga", "https://superliga.dk/kampprogram", superliga),
    "cro.1": ("HNL", "https://hnl.hr/supersport-hnl/raspored-i-rezultati/", hnl),
}
