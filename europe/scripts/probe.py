"""Fetch candidate official schedule pages/APIs and save raw samples to debug/probe/ (development helper)."""
import gzip, json, pathlib, sys, urllib.request, urllib.error, zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "debug" / "probe"
OUT.mkdir(parents=True, exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
TARGETS = json.loads((pathlib.Path(__file__).parent / "probe_targets.json").read_text(encoding="utf-8"))
LIMIT = 400_000

summary = []
for t in TARGETS:
    name, url = t["name"], t["url"]
    h = {"User-Agent": UA, "Accept": t.get("accept", "*/*"), "Accept-Encoding": "gzip, deflate", "Accept-Language": "en"}
    h.update(t.get("headers", {}))
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=25) as r:
            raw = r.read()
            enc = r.headers.get("Content-Encoding", "")
            if enc == "gzip": raw = gzip.decompress(raw)
            elif enc == "deflate": raw = zlib.decompress(raw)
            code, ctype, final = r.status, r.headers.get("Content-Type", ""), r.geturl()
    except urllib.error.HTTPError as e:
        raw, code, ctype, final = e.read(), e.code, e.headers.get("Content-Type", ""), url
    except Exception as e:
        raw, code, ctype, final = str(e).encode(), 0, "", url
    text = raw.decode("utf-8", "replace")
    (OUT / f"{name}.txt").write_text(f"URL: {url}\nFINAL: {final}\nSTATUS: {code}\nTYPE: {ctype}\nBYTES: {len(raw)}\n\n" + text[:LIMIT], encoding="utf-8")
    summary.append(f"{code}\t{len(raw)}\t{name}\t{url}")
    print(summary[-1])
(OUT / "_summary.txt").write_text("\n".join(summary), encoding="utf-8")
