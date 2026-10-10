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
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "games.json"
API = "https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/scoreboard?dates={a}-{b}&limit=1000"
PAST_DAYS, AHEAD_DAYS, CHUNK = 10, 75, 15


STATS = {"requests": 0, "failed": 0, "errors": []}


def fetch(url, tries=2):
    STATS["requests"] += 1
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "europe-football-updater/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.load(r)
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


def toks(name):
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


def main():
    doc = json.loads(DATA.read_text(encoding="utf-8"))
    countries = doc["countries"]
    now = datetime.now(timezone.utc)
    start, end = (now - timedelta(days=PAST_DAYS)).date(), (now + timedelta(days=AHEAD_DAYS)).date()
    games = doc["games"]
    by_id = {g["id"]: g for g in games}
    changes = {"results": 0, "moved": 0, "timed": 0, "postponed": 0, "live": 0}

    for lg in doc["leagues"]:
        events, d = [], start
        while d <= end:
            e2 = min(end, d + timedelta(days=CHUNK - 1))
            js = fetch(API.format(lg=lg, a=d.strftime("%Y%m%d"), b=e2.strftime("%Y%m%d")))
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
            apply(g, ev, countries, changes)

    games.sort(key=lambda g: (g["t"], g["h"]))
    doc["updated"] = iso_z(now)
    DATA.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("changes:", changes)
    (ROOT / "data" / "update-status.json").write_text(json.dumps(
        {"ran": iso_z(now), "changes": changes, "events_per_league": EVENTS, **STATS},
        ensure_ascii=False, indent=1), encoding="utf-8")


def apply(g, ev, countries, ch):
    # results / live / postponed
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
    # schedule changes (only future, only confirmed times)
    if ev["state"] != "pre" or not ev["timeValid"] or not ev["date"]:
        return
    evt = iso_z(datetime.fromisoformat(ev["date"].replace("Z", "+00:00")))
    if evt == g["t"] and not g.get("nt"):
        return
    tz = ZoneInfo(countries.get(g["c"], {}).get("tz", "Europe/Paris"))
    local = datetime.fromisoformat(evt.replace("Z", "+00:00")).astimezone(tz)
    was_tbd = g.pop("nt", None)
    g["t"], g["ld"], g["lt"] = evt, local.strftime("%Y-%m-%d"), local.strftime("%H:%M")
    g["ok"] = True
    g["note"] = "מועד עודכן אוטומטית " + datetime.now(timezone.utc).strftime("%d.%m.%Y") + " לפי פרסום עדכני"
    ch["timed" if was_tbd else "moved"] += 1


if __name__ == "__main__":
    sys.exit(main())
