"""
probe_api.py
Intercepts all XHR/fetch calls made by the Starbucks careers SPA
so we can identify the correct API endpoint + payload structure.
"""
import json, asyncio
from playwright.async_api import async_playwright

TARGET = (
    "https://apply.starbucks.com/careers"
    "?start=0&location=Seattle%2C+WA%2C+US"
    "&sort_by=distance&filter_distance=25"
)

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await ctx.new_page()

        captured = []

        async def handle_request(req):
            url = req.url
            if any(k in url for k in ["jobs", "positions", "eightfold", "apply", "careers"]):
                if req.method in ("GET", "POST"):
                    captured.append({
                        "method": req.method,
                        "url":    url,
                        "headers": dict(req.headers),
                        "post_data": req.post_data,
                    })

        async def handle_response(resp):
            url = resp.url
            # Cast wide net on first probe
            if "eightfold" in url or "starbucks" in url:
                ct = resp.headers.get("content-type", "")
                if "json" in ct:
                    try:
                        body = await resp.text()
                        print(f"\n[RESPONSE {resp.status}] {url}")
                        print(body[:2000])
                    except Exception as e:
                        print(f"[RESPONSE ERR] {e}")

        page.on("request",  handle_request)
        page.on("response", handle_response)

        print(f"Loading: {TARGET}")
        try:
            await page.goto(TARGET, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"[WARN] goto: {e}")
        await asyncio.sleep(8)

        print(f"\n{'='*60}")
        print(f"CAPTURED {len(captured)} matching requests:\n")
        for r in captured:
            print(f"  [{r['method']}] {r['url']}")
            if r["post_data"]:
                print(f"    body: {r['post_data'][:300]}")

        await browser.close()

asyncio.run(main())
