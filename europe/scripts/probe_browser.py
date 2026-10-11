"""Dev helper: open official league pages in a real browser, save rendered HTML and every JSON response."""
import asyncio, json, pathlib, re
from playwright.async_api import async_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
import os
OUT = ROOT / "debug" / os.environ.get("PROBE_OUT", "probe2")
OUT.mkdir(parents=True, exist_ok=True)
PAGES = json.loads((pathlib.Path(__file__).parent / os.environ.get("PROBE_PAGES", "probe_pages.json")).read_text(encoding="utf-8"))


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(locale="en-GB", timezone_id="UTC",
                                  user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36")
        summary = []
        for t in PAGES:
            name, url = t["name"], t["url"]
            page = await ctx.new_page()
            jsons = []

            async def on_resp(r, jsons=jsons):
                ct = r.headers.get("content-type", "")
                if "json" in ct and r.request.resource_type in ("xhr", "fetch"):
                    try:
                        body = await r.text()
                    except Exception:
                        body = ""
                    jsons.append({"url": r.url, "status": r.status, "method": r.request.method,
                                  "req_headers": {k: v for k, v in r.request.headers.items() if k.lower() not in ("cookie",)},
                                  "body": body[:60000]})
            page.on("response", on_resp)
            try:
                resp = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(9000)
                for sel in t.get("click", []):
                    try:
                        await page.click(sel, timeout=4000); await page.wait_for_timeout(1500)
                    except Exception:
                        pass
                html = await page.content()
                status = resp.status if resp else 0
            except Exception as e:
                html, status = f"ERROR {e}", 0
            (OUT / f"{name}.html").write_text(html[:600000], encoding="utf-8")
            (OUT / f"{name}.xhr.json").write_text(json.dumps(jsons, ensure_ascii=False, indent=1), encoding="utf-8")
            summary.append(f"{status}\t{len(html)}\t{len(jsons)} json\t{name}\t{page.url}")
            print(summary[-1])
            await page.close()
        (OUT / "_summary.txt").write_text("\n".join(summary), encoding="utf-8")
        await b.close()

asyncio.run(main())
