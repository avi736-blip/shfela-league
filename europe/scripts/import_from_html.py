"""One-time import: turn the original HTML data into data/games.json (country-centric)."""
import json, re, sys, datetime
from zoneinfo import ZoneInfo

raw = json.load(open(sys.argv[1], encoding="utf-8"))
out_path = sys.argv[2]
DATA = raw["DATA"]

# canonical country key -> (hebrew, flag code, tz, region)
C = {
 "England": ("אנגליה", "gb-eng", "Europe/London", "מערב"),
 "Scotland": ("סקוטלנד", "gb-sct", "Europe/London", "מערב"),
 "Wales": ("ויילס", "gb-wls", "Europe/London", "מערב"),
 "Northern Ireland": ("צפון אירלנד", "gb-nir", "Europe/London", "מערב"),
 "Ireland": ("אירלנד", "ie", "Europe/Dublin", "מערב"),
 "Germany": ("גרמניה", "de", "Europe/Berlin", "מרכז"),
 "Italy": ("איטליה", "it", "Europe/Rome", "דרום"),
 "Spain": ("ספרד", "es", "Europe/Madrid", "דרום"),
 "France": ("צרפת", "fr", "Europe/Paris", "מערב"),
 "Portugal": ("פורטוגל", "pt", "Europe/Lisbon", "דרום"),
 "Netherlands": ("הולנד", "nl", "Europe/Amsterdam", "מערב"),
 "Belgium": ("בלגיה", "be", "Europe/Brussels", "מערב"),
 "Austria": ("אוסטריה", "at", "Europe/Vienna", "מרכז"),
 "Switzerland": ("שווייץ", "ch", "Europe/Zurich", "מרכז"),
 "Denmark": ("דנמרק", "dk", "Europe/Copenhagen", "צפון"),
 "Norway": ("נורווגיה", "no", "Europe/Oslo", "צפון"),
 "Sweden": ("שוודיה", "se", "Europe/Stockholm", "צפון"),
 "Finland": ("פינלנד", "fi", "Europe/Helsinki", "צפון"),
 "Iceland": ("איסלנד", "is", "Atlantic/Reykjavik", "צפון"),
 "Faroe Islands": ("איי פארו", "fo", "Atlantic/Faroe", "צפון"),
 "Estonia": ("אסטוניה", "ee", "Europe/Tallinn", "צפון"),
 "Latvia": ("לטביה", "lv", "Europe/Riga", "צפון"),
 "Lithuania": ("ליטא", "lt", "Europe/Vilnius", "צפון"),
 "Poland": ("פולין", "pl", "Europe/Warsaw", "מזרח"),
 "Czechia": ("צ׳כיה", "cz", "Europe/Prague", "מרכז"),
 "Slovakia": ("סלובקיה", "sk", "Europe/Bratislava", "מרכז"),
 "Hungary": ("הונגריה", "hu", "Europe/Budapest", "מרכז"),
 "Romania": ("רומניה", "ro", "Europe/Bucharest", "מזרח"),
 "Bulgaria": ("בולגריה", "bg", "Europe/Sofia", "מזרח"),
 "Greece": ("יוון", "gr", "Europe/Athens", "דרום"),
 "Cyprus": ("קפריסין", "cy", "Asia/Nicosia", "דרום"),
 "Türkiye": ("טורקיה", "tr", "Europe/Istanbul", "מזרח"),
 "Croatia": ("קרואטיה", "hr", "Europe/Zagreb", "דרום"),
 "Serbia": ("סרביה", "rs", "Europe/Belgrade", "מזרח"),
 "Slovenia": ("סלובניה", "si", "Europe/Ljubljana", "מרכז"),
 "Bosnia and Herzegovina": ("בוסניה והרצגובינה", "ba", "Europe/Sarajevo", "דרום"),
 "Montenegro": ("מונטנגרו", "me", "Europe/Podgorica", "דרום"),
 "Albania": ("אלבניה", "al", "Europe/Tirane", "דרום"),
 "North Macedonia": ("צפון מקדוניה", "mk", "Europe/Skopje", "דרום"),
 "Kosovo": ("קוסובו", "xk", "Europe/Belgrade", "דרום"),
 "Malta": ("מלטה", "mt", "Europe/Malta", "דרום"),
 "Gibraltar": ("גיברלטר", "gi", "Europe/Gibraltar", "דרום"),
 "Andorra": ("אנדורה", "ad", "Europe/Andorra", "דרום"),
 "San Marino": ("סן מרינו", "sm", "Europe/San_Marino", "דרום"),
 "Liechtenstein": ("ליכטנשטיין", "li", "Europe/Vaduz", "מרכז"),
 "Luxembourg": ("לוקסמבורג", "lu", "Europe/Luxembourg", "מערב"),
 "Moldova": ("מולדובה", "md", "Europe/Chisinau", "מזרח"),
 "Belarus": ("בלארוס", "by", "Europe/Minsk", "מזרח"),
 "Georgia": ("גאורגיה", "ge", "Asia/Tbilisi", "מזרח"),
 "Armenia": ("ארמניה", "am", "Asia/Yerevan", "מזרח"),
 "Azerbaijan": ("אזרבייג׳ן", "az", "Asia/Baku", "מזרח"),
 "Kazakhstan": ("קזחסטן", "kz", "Asia/Almaty", "מזרח"),
 "TBD": ("מארחת טרם נקבעה", "", "Europe/Paris", ""),
}
HE2EN = {v[0]: k for k, v in C.items()}
HE2EN.update({"צ׳כיה": "Czechia"})
ALIAS = {"Czech Republic": "Czechia", "Turkey": "Türkiye", "Republic of Ireland": "Ireland"}

def country_of(x):
    v = x.get("venueCountry") or ""
    if v in ("כללי", ""):
        return "TBD"
    if v == "אירופה":
        if x.get("city") == "Dublin":
            return "Ireland"
        return "TBD"
    v = ALIAS.get(v, v)
    if v in HE2EN:
        return HE2EN[v]
    if v in C:
        return v
    raise SystemExit("unknown country " + v)

def is_english_espn_status(s):
    return bool(re.match(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun), ", s or "")) or s in ("TBD",) or (s or "").startswith("Matchday")

games, bad_local = [], 0
for x in DATA:
    c = country_of(x)
    tz = ZoneInfo(C[c][2])
    d = x["date"].replace("Z", "+00:00")
    dt = datetime.datetime.fromisoformat(d)
    local = dt.astimezone(tz)
    lt = local.strftime("%H:%M")
    if x.get("localTime") and x["localTime"] != lt and c != "TBD":
        bad_local += 1
    st = x.get("status") or ""
    note = "" if is_english_espn_status(st) else st
    g = {
        "id": str(x["id"]),
        "lg": x["league"],
        "c": c,
        "t": dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "ld": local.strftime("%Y-%m-%d"),
        "lt": lt,
        "ok": bool(x.get("timeValid")),
        "h": x["home"], "a": x["away"],
        "hl": x.get("homeLogo") or "", "al": x.get("awayLogo") or "",
        "v": x.get("venue") or "", "city": x.get("city") or "",
    }
    if note: g["note"] = note
    if not g["ok"] and (st.startswith("Matchday") or st == "TBD"):
        g["nt"] = 1  # placeholder time only: show date, "time TBD"
        g["note"] = "מחזור " + re.sub(r"\D.*", "", st[9:]) + " — מועד מדויק טרם נקבע" if st.startswith("Matchday") else "מועד מדויק טרם נקבע"
    if x.get("officialSite"): g["site"] = x["officialSite"]
    if x.get("scheduleSource"): g["src"] = x["scheduleSource"]
    games.append(g)

games.sort(key=lambda g: (g["t"], g["h"]))
countries = {k: {"he": v[0], "flag": v[1], "tz": v[2], "region": v[3]} for k, v in C.items()
             if any(g["c"] == k for g in games)}
leagues = {m["slug"]: {"he": m["label"], "country": m["country"]} for m in raw["META"]}
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
doc = {"updated": now, "verifiedOn": "2026-10-02", "range": ["2026-10-01", "2027-04-30"],
       "countries": countries, "leagues": leagues, "games": games}
json.dump(doc, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print(len(games), "games,", len(countries), "countries; localTime mismatches:", bad_local)
