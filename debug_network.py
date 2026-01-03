#!/usr/bin/env python3
import argparse
import asyncio
import datetime
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from playwright.async_api import async_playwright, TimeoutError, Error


def now_tag() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Capture list page HTML and network logs.")
    parser.add_argument("-q", "--query", required=True, help="Query keyword")
    parser.add_argument("-c", "--city", default="", help="City code (optional)")
    parser.add_argument("--storage-state", default="storage_state.json", help="Storage state file")
    parser.add_argument("--out-dir", default="debug/network", help="Output directory")
    parser.add_argument("--timeout", type=int, default=20000, help="Page load timeout ms")
    args = parser.parse_args()

    out_dir = Path(args.out_dir) / now_tag()
    out_dir.mkdir(parents=True, exist_ok=True)
    events_path = out_dir / "network_events.jsonl"
    html_path = out_dir / "page.html"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            chromium_sandbox=False,
        )
        context = await browser.new_context(storage_state=args.storage_state)
        page = await context.new_page()

        async def log_event(event):
            with events_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")

        async def handle_response(resp):
            try:
                url = resp.url
                if resp.request.resource_type not in ("xhr", "fetch"):
                    return
                content_type = resp.headers.get("content-type", "")
                parsed = urlparse(url)
                entry = {
                    "url": url,
                    "status": resp.status,
                    "content_type": content_type,
                    "query": parse_qs(parsed.query),
                }
                if "application/json" in content_type:
                    try:
                        body = await resp.json()
                        entry["json"] = body
                    except Exception:
                        try:
                            entry["text"] = await resp.text()
                        except Exception:
                            pass
                await log_event(entry)
            except Exception:
                pass

        page.on("response", lambda resp: asyncio.create_task(handle_response(resp)))

        url = f"https://www.zhipin.com/web/geek/job?query={args.query}"
        if args.city:
            url += f"&city={args.city}"
        url += "&page=1"

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=args.timeout)
            await page.wait_for_timeout(8000)
        except (TimeoutError, Error) as exc:
            await log_event({"error": str(exc)})

        html = await page.content()
        html_path.write_text(html, encoding="utf-8")

        await context.close()
        await browser.close()

    print(f"saved: {out_dir}")


if __name__ == "__main__":
    asyncio.run(main())
