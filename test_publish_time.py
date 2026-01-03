import argparse
import asyncio
from collections import Counter
from typing import Optional
from urllib.parse import parse_qs, quote_plus, urlparse

from playwright.async_api import async_playwright, TimeoutError

from boss_crawler import BASE_URL, extract_job_list


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="测试 Boss 列表接口的发布时间字段")
    parser.add_argument("--query", required=True, help="岗位关键词，例如：aiinfra")
    parser.add_argument("--city", default="101010100", help="城市代码，默认北京")
    parser.add_argument("--page", type=int, default=1, help="页码")
    parser.add_argument("--headful", action="store_true", help="使用有界面模式")
    parser.add_argument("--wait-secs", type=int, default=0, help="打开页面后等待秒数")
    parser.add_argument("--channel", default="", help="使用系统浏览器内核，例如 chrome 或 msedge")
    parser.add_argument(
        "--storage-state",
        default="",
        help="加载已登录的 storage state 文件（Playwright storage_state.json）",
    )
    return parser.parse_args()


async def fetch_publish_time_fields(
    query: str,
    city: str,
    page: int,
    headful: bool,
    wait_secs: int,
    channel: str,
    storage_state: str,
) -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=not headful,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            chromium_sandbox=False,
            channel=channel or None,
        )
        context_kwargs = {"locale": "zh-CN"}
        if storage_state:
            context_kwargs["storage_state"] = storage_state
        context = await browser.new_context(**context_kwargs)
        page_obj = await context.new_page()

        job_list_future: asyncio.Future = asyncio.get_event_loop().create_future()

        async def maybe_capture_joblist(resp) -> None:
            if job_list_future.done():
                return
            if resp.request.resource_type not in ("xhr", "fetch"):
                return
            content_type = resp.headers.get("content-type", "")
            if "application/json" not in content_type:
                return
            if "job" not in resp.url and "search" not in resp.url:
                return
            try:
                payload = await resp.json()
            except Exception:
                return
            job_list = extract_job_list(payload)
            if not job_list:
                return
            parsed = urlparse(resp.url)
            qs = parse_qs(parsed.query)
            if city and qs.get("city") and qs.get("city", [""])[0] != city:
                return
            if qs.get("query") and qs.get("query", [""])[0] != query:
                return
            if qs.get("page") and qs.get("page", [""])[0] != str(page):
                return
            job_list_future.set_result(job_list)

        def handle_response(resp) -> None:
            asyncio.create_task(maybe_capture_joblist(resp))

        page_obj.on("response", handle_response)
        url = f"{BASE_URL}/web/geek/job?query={quote_plus(query)}&city={city}&page={page}"
        print(f"[open] {url}")
        await page_obj.goto(url, wait_until="domcontentloaded", timeout=20000)
        if wait_secs > 0:
            await page_obj.wait_for_timeout(wait_secs * 1000)
        try:
            await page_obj.wait_for_selector(
                ".job-card-wrapper, .job-list-box, .search-job-list, .job-card-box, .job-card-wrap",
                timeout=12000,
            )
        except TimeoutError:
            print("[warn] 未命中列表选择器，可能被风控或 DOM 变更")
            await page_obj.close()
            await browser.close()
            return

        try:
            job_list = await asyncio.wait_for(job_list_future, timeout=4)
        except asyncio.TimeoutError:
            job_list = None

        if not job_list:
            print("[warn] 未拿到 jobList（接口可能被拦）")
            await page_obj.close()
            await browser.close()
            return

        time_key_counts: Counter[str] = Counter()
        example: Optional[dict] = None
        for item in job_list:
            if example is None:
                example = item
            for key in item.keys():
                if "time" in key.lower():
                    time_key_counts[key] += 1

        print("[time keys]")
        for key, cnt in time_key_counts.most_common():
            print(f"{key}: {cnt}")
        if example is not None:
            print("\n[example time values]")
            for key in sorted(k for k in example.keys() if "time" in k.lower()):
                print(f"{key} = {example.get(key)}")

        await page_obj.close()
        await browser.close()


def main() -> None:
    args = parse_args()
    asyncio.run(
        fetch_publish_time_fields(
            args.query,
            args.city,
            args.page,
            args.headful,
            args.wait_secs,
            args.channel,
            args.storage_state,
        )
    )


if __name__ == "__main__":
    main()
