"""
Daily auto-update of data/games.json from ESPN's public scoreboard API.

What it does for every league in the file:
  * fills in results (s=[home, away]) for finished games and marks live ones;
  * marks postponed games (pp=1);
  * moves games whose date/time changed, and fills in times that were "TBD"
    once ESPN publishes a confirmed kickoff (timeValid);
  * matches by ESPN event id, or — for games imported from other sources —
    by team names within a few days of the stored date.

Games marked "ok" with an official schedule source (src) are never moved to an
unconfirmed time; if ESPN shows a different confirmed time it is applied and noted.
Standard library only, so the GitHub Action needs no installs.
"""
import json, pathlib, re, sys, time, unicodedata, urllib.request, urllib.error
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "games.json"
BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/scoreboard"
# URL styles, tried in order until one answers; the working one is reused for every league
STYLES = [
    ("range", "?dates={a}-{b}&limit=300", 15),
    ("range-nolimit", "?dates={a}-{b}", 15),
    ("day", "?dates={a}", 1),
]
PAST_DAYS, AHEAD_DAYS = 10, 75
DAY_PAST, DAY_AHEAD = 4, 45  # narrower window when only day-by-day requests work


STATS = {"requests": 0, "failed": 0, "errors": []}


def fetch(url, tries=2):
    STATS["requests"] += 1
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "europe-football-updater/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code < 500 or i == tries - 1:
                body = e.read()[:160].decode("utf-8", "replace")
                STATS["failed"] += 1
                if len(STATS["errors"]) < 5:
                    STATS["errors"].append(f"{url.split('/soccer/')[-1][:60]}: HTTP {e.code} {body}")
                return None
            time.sleep(2 + 3 * i)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            if i == tries - 1:
                print("  ! failed", url, e)
                STATS["failed"] += 1
                if len(STATS["errors"]) < 5:
                    STATS["errors"].append(f"{url.split('/soccer/')[-1][:40]}: {e}")
                return None
            time.sleep(2 + 3 * i)


STOP = {"fc", "cf", "sc", "ac", "afc", "ssc", "sk", "fk", "nk", "bk", "if", "kv", "krc", "rc", "cd", "ud", "sd", "rcd",
        "club", "de", "the", "1", "calcio", "football", "futbol", "sporting", "and", "as", "us", "vfl", "vfb", "tsg",
        "sv", "spvgg", "bsc", "1.", "cs", "cfr", "pfc", "ofk", "gnk", "hnk"}


TRANS = str.maketrans({"ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae", "å": "a", "ß": "ss", "ł": "l", "Ł": "l", "đ": "d",
                       "Đ": "d", "ı": "i", "ð": "d", "þ": "th"})


def toks(name):
    name = name.translate(TRANS).replace("Be'er", "Beer").replace("Be’er", "Beer")
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    t = {w for w in re.split(r"[^a-z0-9]+", n) if w and w not in STOP and not w.isdigit()}
    return t or {n}


def same_team(a, b):
    ta, tb = toks(a), toks(b)
    return bool(ta & tb)


def parse_event(ev):
    comp = (ev.get("competitions") or [{}])[0]
    teams = {c.get("homeAway"): c for c in comp.get("competitors", [])}
    h, a = teams.get("home"), teams.get("away")
    if not h or not a:
        return None
    st = (ev.get("status") or comp.get("status") or {}).get("type", {})
    return {
        "id": str(ev.get("id")),
        "date": ev.get("date"),
        "timeValid": ev.get("timeValid", comp.get("timeValid", True)),
        "home": h.get("team", {}).get("displayName", ""),
        "away": a.get("team", {}).get("displayName", ""),
        "hs": h.get("score"), "as": a.get("score"),
        "state": st.get("state"), "completed": st.get("completed"), "name": st.get("name", ""),
    }


def iso_z(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


EVENTS = {}


def tag_source(g):
    """Where the date/time of a game comes from: the league itself, ESPN, or another data site."""
    if g.get("by") and g["by"] != "data":
        return
    note = g.get("note", "")
    if "ESPN" in note:
        g["by"] = "espn"
    elif "UEFA" in note:
        g["by"], g["byn"] = "league", "UEFA"
    elif g.get("src"):
        g["by"] = "league"
    elif g["id"].isdigit():
        g["by"] = "espn"
    elif g["id"].startswith("es-"):
        g["by"] = "escore"  # where the original file took it from
    elif g["id"].startswith("of-"):
        g["by"], g["byn"] = "league", "לוח העונה של הליגה"  # placeholder dates from the season fixture release
    elif g["id"].startswith("uefa-"):
        g["by"], g["byn"] = "league", "UEFA"
    else:
        g["by"] = "data"


def main():
    doc = json.loads(DATA.read_text(encoding="utf-8"))
    for g in doc["games"]:
        tag_source(g)
    countries = doc["countries"]
    now = datetime.now(timezone.utc)
    style = pick_style(list(doc["leagues"])[0], now)
    STATS["style"] = style[0] if style else None
    if not style:
        print("ESPN did not answer any URL style; nothing updated")
    else:
        q, chunk = style[1], style[2]
        if style[0] == "day":
            start, end = (now - timedelta(days=DAY_PAST)).date(), (now + timedelta(days=DAY_AHEAD)).date()
        else:
            start, end = (now - timedelta(days=PAST_DAYS)).date(), (now + timedelta(days=AHEAD_DAYS)).date()
    games = doc["games"]
    by_id = {g["id"]: g for g in games}
    changes = {"results": 0, "moved": 0, "timed": 0, "postponed": 0, "live": 0}

    official_ok = run_official(doc, now, changes)

    for lg in (doc["leagues"] if style else []):
        results_only = lg in official_ok  # schedule comes from the league; ESPN may only add scores
        events, d = [], start
        while d <= end:
            e2 = min(end, d + timedelta(days=chunk - 1))
            js = fetch(BASE.format(lg=lg) + q.format(a=d.strftime("%Y%m%d"), b=e2.strftime("%Y%m%d")))
            events += (js or {}).get("events", [])
            d = e2 + timedelta(days=1)
        evs = [e for e in map(parse_event, events) if e]
        print(f"{lg}: {len(evs)} events")
        EVENTS[lg] = len(evs)
        pool = [g for g in games if g["lg"] == lg]
        for ev in evs:
            g = by_id.get(ev["id"])
            if g is None:  # imported from another source: match by teams + nearby date
                evd = datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
                for c in pool:
                    gd = datetime.fromisoformat(c["t"].replace("Z", "+00:00"))
                    if abs((gd - evd).days) <= 6 and same_team(c["h"], ev["home"]) and same_team(c["a"], ev["away"]):
                        g = c
                        break
            if g is None:
                continue
            apply(g, ev, countries, changes, results_only)

    games.sort(key=lambda g: (g["t"], g["h"]))
    if sum(EVENTS.values()) or official_ok:
        doc["updated"] = iso_z(now)
    DATA.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("changes:", changes)
    (ROOT / "data" / "update-status.json").write_text(json.dumps(
        {"ran": iso_z(now), "changes": changes, "official": OFFICIAL, "espn_events_per_league": EVENTS, **STATS},
        ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------- official league sources ----------------
OFFICIAL = {}


SYN = {"ob": "odense", "hamkam": "hamarkameratene", "thoune": "thun", "utd": "united", "man": "manchester", "atleti": "atletico", "rennais": "rennes", "kobenhavn": "copenhagen", "zvezda": "star", "crvena": "red", "sheva": "beer", "beersheva": "beer",
       "praha": "prague", "plzen": "pilsen", "bodo": "bodo", "glimt": "glimt", "koln": "cologne", "munchen": "munich", "inter": "internazionale", "roma": "roma", "hamburger": "hamburg",
       "nurnberg": "nuremberg", "athletic": "athletic", "brighton": "brighton", "wolverhampton": "wolves",
       "nottm": "nottingham", "spurs": "tottenham", "deportivo": "deportivo", "coruna": "deportivo"}


def _norm_toks(name):
    return {SYN.get(t, t) for t in toks(name)}


def _tok_eq(x, y):
    return x == y or (min(len(x), len(y)) >= 4 and (x.startswith(y) or y.startswith(x)))


def sim(names_a, names_b):
    best = 0.0
    for x in names_a:
        for y in names_b:
            if not x or not y:
                continue
            a, b = _norm_toks(x), _norm_toks(y)
            if not a or not b:
                continue
            hit = sum(1 for t in a if any(_tok_eq(t, u) for u in b))
            best = max(best, hit / max(len(a), len(b)))
    return best


def run_official(doc, now, ch):
    import official
    games, countries, done = doc["games"], doc["countries"], set()
    stamp = now.strftime("%d.%m.%Y")
    for lg, (label, url, fn) in official.SOURCES.items():
        if lg not in doc["leagues"]:
            continue
        try:
            fixtures = fn(now)
        except Exception as e:  # keep going: one broken site must not stop the others
            OFFICIAL[lg] = {"ok": False, "error": str(e)[:300]}
            print(f"official {lg}: FAILED {e}")
            continue
        pool = [g for g in games if g["lg"] == lg]
        used, matched, unmatched, added = set(), 0, [], 0
        # score every plausible (fixture, game) pair, then take the best pairs first
        cands = []
        for i, fx in enumerate(fixtures):
            ref = fx["utc"] or (datetime.fromisoformat(fx["day"] + "T12:00:00+00:00") if fx["day"] else None)
            for g in pool:
                gd = datetime.fromisoformat(g["t"].replace("Z", "+00:00"))
                if ref and abs((gd - ref).days) > 21:
                    continue
                sh = sim([fx["home"], *fx["alt_home"]], [g["h"]])
                sa = sim([fx["away"], *fx["alt_away"]], [g["a"]])
                if sh == 0 or sa == 0:
                    continue
                cands.append((sh + sa - (abs((gd - ref).total_seconds()) / 86400 * 0.03 if ref else 0), i, g["id"]))
        cands.sort(reverse=True)
        by_id = {g["id"]: g for g in pool}
        taken = {}
        for score, i, gid in cands:
            if i in taken or gid in used:
                continue
            taken[i] = gid; used.add(gid)
        for i, fx in enumerate(fixtures):
            if i in taken:
                matched += 1
                apply_official(by_id[taken[i]], fx, countries, label, url, stamp, ch)
                continue
            new = add_fixture(doc, lg, fx, now)
            if new:
                added += 1; used.add(new["id"]); pool.append(new)
                apply_official(new, fx, countries, label, url, stamp, ch)
            elif len(unmatched) < 12 and str(fx["utc"] or fx["day"])[:10] >= doc["range"][0]:
                unmatched.append(f'{fx["home"]} - {fx["away"]} {fx["utc"] or fx["day"]}')
        ours_left = [f'{g["ld"]} {g["h"]} - {g["a"]}' for g in pool if g["id"] not in used and g["ld"] >= now.strftime("%Y-%m-%d")
                     and not g["id"].startswith("uefa-general")][:10]
        OFFICIAL[lg] = {"ok": True, "fixtures": len(fixtures), "matched": matched, "added": added,
                        "unmatched_sample": unmatched, "ours_not_found": ours_left}
        if added:
            drop_placeholders(doc, lg)
        print(f"official {lg}: {len(fixtures)} fixtures, {matched} matched")
        if fixtures and matched >= min(len(pool), len(fixtures)) * 0.6:
            done.add(lg)
    return done


def add_fixture(doc, lg, fx, now):
    """New fixtures are added only for competitions whose pairings appear during the season (UEFA knockouts)."""
    if not fx.get("ext_id") or not fx.get("country") or fx["country"] not in doc["countries"]:
        return None
    when = fx["utc"] or (datetime.fromisoformat(fx["day"] + "T12:00:00+00:00") if fx["day"] else None)
    lo, hi = doc["range"]
    if not when or not (lo <= when.strftime("%Y-%m-%d") <= hi) or when < now - timedelta(days=3):
        return None
    if any(g["id"] == fx["ext_id"] for g in doc["games"]):
        return None
    for g in doc["games"]:  # never add a second copy of a game we already list under another spelling
        if g["lg"] == lg and abs((datetime.fromisoformat(g["t"].replace("Z", "+00:00")) - when).days) <= 2 and \
                (sim([fx["home"], *fx["alt_home"]], [g["h"]]) > 0 or sim([fx["away"], *fx["alt_away"]], [g["a"]]) > 0
                 or (fx["city"] and g.get("city") and sim([fx["city"]], [g["city"]]) > 0) or g["c"] == fx["country"]):
            return None
    g = {"id": fx["ext_id"], "lg": lg, "c": fx["country"], "t": iso_z(when), "ld": when.strftime("%Y-%m-%d"),
         "lt": when.strftime("%H:%M"), "ok": False, "h": fx["home"], "a": fx["away"],
         "hl": (fx.get("logos") or ["", ""])[0], "al": (fx.get("logos") or ["", ""])[1],
         "v": fx["venue"], "city": fx["city"]}
    doc["games"].append(g)
    return g


def drop_placeholders(doc, lg):
    """Remove 'pairing not drawn yet' placeholders on days that now have real fixtures."""
    real = {g["ld"] for g in doc["games"] if g["lg"] == lg and not g["id"].startswith("uefa-general")}
    doc["games"][:] = [g for g in doc["games"] if not (g["lg"] == lg and g["id"].startswith("uefa-general") and g["ld"] in real)]


def apply_official(g, fx, countries, label, url, stamp, ch):
    tz = ZoneInfo(countries.get(g["c"], {}).get("tz", "Europe/Paris"))
    g["by"], g["byn"] = "league", label
    if fx["state"] == "pp":
        if not g.get("pp"):
            g["pp"] = 1; ch["postponed"] += 1
        g["note"] = f"נדחה לפי {label} ({stamp})"; g["src"] = url
        return
    g.pop("pp", None)
    if fx["state"] == "live":
        g["live"] = 1; ch["live"] += 1
    else:
        g.pop("live", None)
    if fx["score"] and fx["state"] in ("post", "live"):
        s = [int(fx["score"][0]), int(fx["score"][1])]
        if g.get("s") != s and fx["state"] == "post":
            ch["results"] += 1
        g["s"] = s
    if fx["state"] != "pre":
        return
    if fx["confirmed"] and fx["utc"] and fx["utc"].astimezone(tz).hour < 6:
        # a "kickoff" in the small hours is a placeholder for "time not set yet"
        fx = dict(fx, confirmed=False, day=fx["utc"].astimezone(tz).strftime("%Y-%m-%d"), utc=None)
    if fx["confirmed"] and fx["utc"]:
        evt = iso_z(fx["utc"])
        if evt != g["t"] or g.get("nt") or not g.get("ok"):
            ch["timed" if g.get("nt") else "moved"] += 1 if (evt != g["t"] or g.get("nt")) else 0
            local = fx["utc"].astimezone(tz)
            g.pop("nt", None)
            g["t"], g["ld"], g["lt"] = evt, local.strftime("%Y-%m-%d"), local.strftime("%H:%M")
        g["ok"] = True
        g["note"] = f"סופי – לפי {label} (נבדק {stamp})"
        g["src"] = url
    elif fx["day"]:
        local = datetime.fromisoformat(fx["day"] + "T15:00:00").replace(tzinfo=tz)
        if g["ld"] != fx["day"] or not g.get("nt"):
            g["t"], g["ld"], g["lt"] = iso_z(local), fx["day"], "15:00"
            g["nt"] = 1
        g["ok"] = False
        g["note"] = f"יום משוער לפי {label}; השעה טרם נקבעה (נבדק {stamp})"
        g["src"] = url
    if not g.get("v") and fx["venue"]:
        g["v"] = fx["venue"]
    if not g.get("city") and fx["city"]:
        g["city"] = fx["city"]


def pick_style(lg, now):
    a = (now - timedelta(days=3)).strftime("%Y%m%d")
    b = (now + timedelta(days=3)).strftime("%Y%m%d")
    for st in STYLES:
        js = fetch(BASE.format(lg=lg) + st[1].format(a=a, b=b))
        if js is not None and "events" in js:
            print("using URL style", st[0])
            return st
    return None


def apply(g, ev, countries, ch, results_only=False):
    # results / live / postponed
    if results_only and ev["state"] == "pre":
        return  # the league decides about postponements and kickoff times
    if ev["name"] in ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_ABANDONED"):
        if not g.get("pp"):
            g["pp"] = 1; ch["postponed"] += 1
        return
    g.pop("pp", None)
    if ev["state"] == "in":
        g["live"] = 1; ch["live"] += 1
        if ev["hs"] is not None:
            g["s"] = [int(ev["hs"]), int(ev["as"])]
        return
    g.pop("live", None)
    if ev["completed"] and ev["hs"] is not None:
        s = [int(ev["hs"]), int(ev["as"])]
        if g.get("s") != s:
            g["s"] = s; ch["results"] += 1
        return
    # schedule (only future games)
    if results_only or ev["state"] != "pre" or not ev["date"]:
        return
    stamp = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    if not ev["timeValid"]:
        if g.get("by") != "league":  # ESPN has no fixed time yet
            g["by"], g["ok"] = "espn", False
            g["note"] = f"לפי ESPN: השעה טרם נקבעה (נבדק {stamp})"
        return
    evt = iso_z(datetime.fromisoformat(ev["date"].replace("Z", "+00:00")))
    if evt == g["t"] and not g.get("nt"):
        if g.get("by") != "league":  # ESPN confirms the time we already have
            g["by"], g["ok"] = "espn", True
            g["note"] = f"סופי לפי ESPN (נבדק {stamp})"
        return
    tz = ZoneInfo(countries.get(g["c"], {}).get("tz", "Europe/Paris"))
    local = datetime.fromisoformat(evt.replace("Z", "+00:00")).astimezone(tz)
    was_tbd = g.pop("nt", None)
    g["t"], g["ld"], g["lt"] = evt, local.strftime("%Y-%m-%d"), local.strftime("%H:%M")
    g["by"], g["ok"] = "espn", True
    g.pop("byn", None)
    g["note"] = f"מועד עודכן לפי ESPN (נבדק {stamp})"
    ch["timed" if was_tbd else "moved"] += 1


if __name__ == "__main__":
    sys.exit(main())
