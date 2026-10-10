"""
Fill data/coords.json with map coordinates for every stadium in data/games.json.

Key: "<venue>|<city>|<country>". Tries the stadium first, then the city.
Uses OpenStreetMap Nominatim (1 request per second, per its usage policy).
Only missing keys are looked up, so after the first run it takes seconds.
"""
import json, pathlib, time, urllib.parse, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
GAMES = ROOT / "data" / "games.json"
OUT = ROOT / "data" / "coords.json"
UA = {"User-Agent": "europe-football-map/1.0 (github.com/avi736-blip/shfela-league)"}
CC = {"England": "gb", "Scotland": "gb", "Wales": "gb", "Northern Ireland": "gb", "Ireland": "ie", "Germany": "de",
      "Italy": "it", "Spain": "es", "France": "fr", "Portugal": "pt", "Netherlands": "nl", "Belgium": "be",
      "Austria": "at", "Switzerland": "ch", "Denmark": "dk", "Norway": "no", "Sweden": "se", "Finland": "fi",
      "Iceland": "is", "Faroe Islands": "fo", "Estonia": "ee", "Latvia": "lv", "Lithuania": "lt", "Poland": "pl",
      "Czechia": "cz", "Slovakia": "sk", "Hungary": "hu", "Romania": "ro", "Bulgaria": "bg", "Greece": "gr",
      "Cyprus": "cy", "Türkiye": "tr", "Croatia": "hr", "Serbia": "rs", "Slovenia": "si",
      "Bosnia and Herzegovina": "ba", "Montenegro": "me", "Albania": "al", "North Macedonia": "mk", "Kosovo": "xk",
      "Malta": "mt", "Gibraltar": "gi", "Andorra": "ad", "San Marino": "sm", "Liechtenstein": "li",
      "Luxembourg": "lu", "Moldova": "md", "Belarus": "by", "Georgia": "ge", "Armenia": "am", "Azerbaijan": "az",
      "Kazakhstan": "kz"}


def search(q, cc):
    params = {"q": q, "format": "json", "limit": 1}
    if cc and cc != "xk":
        params["countrycodes"] = cc
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(params)
    time.sleep(1.1)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            js = json.load(r)
        return [round(float(js[0]["lat"]), 4), round(float(js[0]["lon"]), 4)] if js else None
    except Exception as e:  # network hiccup: try again next run
        print("  !", q, e)
        return None


def main():
    games = json.loads(GAMES.read_text(encoding="utf-8"))["games"]
    coords = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    keys = sorted({f'{g["v"]}|{g["city"]}|{g["c"]}' for g in games if g["c"] != "TBD" and (g["v"] or g["city"])})
    todo = [k for k in keys if k not in coords]
    print(f"{len(keys)} places, {len(todo)} to look up")
    for i, k in enumerate(todo):
        v, city, c = k.split("|")
        cc = CC.get(c, "")
        city_q = city.strip(" ,")
        v = v.strip(" '\"")
        pt = (search(f"{v}, {city_q}", cc) if v and city_q else None) or (search(city_q, cc) if city_q else None) \
            or (search(f"{v}, {city_q}".strip(", "), "") if v or city_q else None)
        if pt:
            coords[k] = pt
        print(f"[{i + 1}/{len(todo)}] {k} -> {pt}")
        if i % 25 == 0:
            OUT.write_text(json.dumps(coords, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
    OUT.write_text(json.dumps(coords, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main()
