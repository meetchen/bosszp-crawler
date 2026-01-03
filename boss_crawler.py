import argparse
import asyncio
import csv
import datetime
import json
import random
import signal
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, List, Optional
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse, parse_qsl

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, TimeoutError, Error


BASE_URL = "https://www.zhipin.com"
DEFAULT_CITIES = ["101010100", "101020100", "101210100", "101190400", "101280600", "101280100", "101110100"]
CITY_CODE_MAP = {
    "北京": "101010100",
    "上海": "101020100",
    "南京": "101190100",
    "苏州": "101190400",
    "西安": "101110100",
    "杭州": "101210100",
    "深圳": "101280600",
    "广州": "101280100",
}
CITY_NAME_MAP = {code: name for name, code in CITY_CODE_MAP.items()}
CITY_MAP_PATH = Path(__file__).with_name("city_map.json")
_CITY_MAP_CACHE: Optional[dict[str, str]] = None
_CITY_NAME_CACHE: Optional[dict[str, str]] = None
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]

PAUSE_REQUESTED = False
LOG_FILE_HANDLE = None
LOG_DIR = Path("log")
DATA_DIR = Path("data")


@dataclass
class JobItem:
    company: str
    title: str
    salary: str
    location: str
    description: str
    link: str
    raw_item: str
    security_id: str = ""
    encrypt_job_id: str = ""
    encrypt_brand_id: str = ""
    lid: str = ""
    boss_name: str = ""
    boss_title: str = ""
    boss_online: str = ""
    boss_cert: str = ""
    gold_hunter: str = ""
    brand_name: str = ""
    brand_stage_name: str = ""
    brand_industry: str = ""
    brand_scale_name: str = ""
    job_name: str = ""
    salary_desc: str = ""
    job_labels: str = ""
    skills: str = ""
    job_experience: str = ""
    job_degree: str = ""
    city_name: str = ""
    area_district: str = ""
    business_district: str = ""
    welfare_list: str = ""
    job_valid_status: str = ""
    job_type: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Boss直聘职位爬虫（Playwright）")
    parser.add_argument(
        "-q",
        "--queries",
        default="",
        help="多个关键词，逗号分隔",
    )
    parser.add_argument(
        "-c",
        "--cities",
        default="",
        help="多个城市代码或名称，逗号分隔，默认北京/上海/杭州/苏州/深圳/广州/西安",
    )
    parser.add_argument(
        "--nationwide",
        action="store_true",
        help="全国范围抓取（不传 city 参数）",
    )
    parser.add_argument(
        "-p",
        "--pages",
        type=int,
        default=30,
        help="抓取页数（0 表示不限，直到空页停止）",
    )
    parser.add_argument("--out", default="", help="CSV 输出路径（默认按关键词/城市命名）")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="覆盖输出 CSV（默认追加写入）",
    )
    parser.add_argument("--headful", action="store_true", help="使用有界面模式（默认无界面）")
    parser.add_argument("--headless", action="store_true", help="使用无界面模式")
    parser.add_argument(
        "--auto-login",
        action="store_true",
        help="先打开页面等待人工登录/验证并保存状态，再自动抓取",
    )
    parser.add_argument(
        "--channel",
        default="",
        help="使用系统浏览器内核，例如 chrome 或 msedge（需本机已安装）",
    )
    parser.add_argument("--skip-detail", action="store_true", help="仅抓列表不进详情页（默认抓详情）")
    parser.add_argument("--with-detail", action="store_true", help="抓取详情页内容（默认开启）")
    parser.add_argument(
        "--debug-dump",
        default="",
        help="当页面未命中列表选择器时，保存 HTML 与截图的前缀路径（如 debug/boss）",
    )
    parser.add_argument(
        "--wait-secs",
        type=int,
        default=0,
        help="打开页面后额外等待秒数（便于手动登录/验证码处理）",
    )
    parser.add_argument(
        "--page-sleep-min",
        type=float,
        default=3.0,
        help="页面/详情访问间隔的随机等待最小秒数（降低风控）",
    )
    parser.add_argument(
        "--page-sleep-max",
        type=float,
        default=8.0,
        help="页面/详情访问间隔的随机等待最大秒数（降低风控）",
    )
    parser.add_argument(
        "--dedupe-on-the-fly",
        action="store_true",
        help="写入 CSV 时去重；若连续两页无新增则停止当前查询",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="单页抓取失败后的最大重试次数",
    )
    parser.add_argument(
        "--retry-sleep-min",
        type=float,
        default=5.0,
        help="单页失败重试的随机等待最小秒数",
    )
    parser.add_argument(
        "--retry-sleep-max",
        type=float,
        default=15.0,
        help="单页失败重试的随机等待最大秒数",
    )
    parser.add_argument(
        "--max-consecutive-errors",
        type=int,
        default=5,
        help="连续失败次数达到阈值后重建浏览器上下文",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="从上次进度继续抓取（需配合 --progress-file）",
    )
    parser.add_argument(
        "--progress-file",
        default="progress_state.json",
        help="保存抓取进度的文件路径（JSON）",
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=1,
        help="循环抓取次数（多城市/关键词完成一次算一个周期）",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="持续循环抓取（忽略 --cycles）",
    )
    parser.add_argument(
        "--cycle-sleep-min",
        type=float,
        default=120.0,
        help="每个周期结束后的随机等待最小秒数",
    )
    parser.add_argument(
        "--cycle-sleep-max",
        type=float,
        default=300.0,
        help="每个周期结束后的随机等待最大秒数",
    )
    parser.add_argument(
        "--empty-stop",
        type=int,
        default=2,
        help="连续空页达到该次数时停止（仅在 --pages=0 时生效）",
    )
    parser.add_argument(
        "--storage-state",
        default="",
        help="加载已登录的 storage state 文件（Playwright storage_state.json）",
    )
    parser.add_argument(
        "--save-state",
        default="",
        help="保存当前会话的 storage state 到文件，便于后续复用",
    )
    return parser.parse_args()


async def get_text(page_or_element, selector: str) -> str:
    """Extract trimmed text content for a selector."""
    node = await page_or_element.query_selector(selector)
    if not node:
        return ""
    text = await node.inner_text()
    return text.strip()


def extract_job_list(payload) -> Optional[List[dict]]:
    def find(node):
        if isinstance(node, dict):
            job_list = node.get("jobList")
            if isinstance(job_list, list):
                return job_list
            for value in node.values():
                found = find(value)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = find(value)
                if found is not None:
                    return found
        return None

    return find(payload)


def build_location(item: dict) -> str:
    city = item.get("cityName") or item.get("jobCity") or item.get("city") or ""
    district = (
        item.get("jobArea")
        or item.get("jobAreaDistrict")
        or item.get("areaDistrict")
        or item.get("area")
        or ""
    )
    business = item.get("businessDistrict") or item.get("jobAreaBusiness") or item.get("business") or ""
    parts = [p for p in (city, district, business) if p]
    return "·".join(parts)


def format_item_log(item: JobItem) -> str:
    parts: list[str] = []
    if item.company:
        parts.append(item.company)
    if item.title:
        parts.append(item.title)
    if item.location:
        parts.append(item.location)
    if item.salary:
        parts.append(item.salary)
    if not parts:
        return "[item]"
    return f"[item] {' | '.join(parts)}"


def is_intern_role(title: str) -> bool:
    if not title:
        return False
    lowered = title.lower()
    return "实习" in title or "intern" in lowered or "trainee" in lowered


async def randomized_sleep(min_s: float, max_s: float) -> None:
    if max_s <= 0:
        return
    min_s, max_s = normalized_range(min_s, max_s)
    await asyncio.sleep(random.uniform(min_s, max_s))


def randomized_timeout_ms(min_ms: int, max_ms: int) -> int:
    if max_ms <= 0:
        return 0
    if min_ms > max_ms:
        min_ms, max_ms = max_ms, min_ms
    return int(random.uniform(min_ms, max_ms))


async def scrape_detail(
    context: BrowserContext,
    url: str,
    sleep_min: float,
    sleep_max: float,
) -> str:
    if should_pause_after_item():
        return ""
    detail_page: Page = await context.new_page()
    try:
        log(f"[open] detail {url}")
        await randomized_sleep(sleep_min, sleep_max)
        try:
            await detail_page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await detail_page.wait_for_timeout(randomized_timeout_ms(500, 900))
        except (TimeoutError, Error, asyncio.TimeoutError):
            if should_pause_after_item():
                return ""
            raise
        # Boss直聘的详情正文区域常见类名，若为空可在有界面模式观察后调整
        for selector in [".job-sec-text", ".text", ".job-detail", ".job-detail-body .desc", ".desc"]:
            try:
                text = await get_text(detail_page, selector)
            except Error as exc:
                log(f"[warn] detail page context lost: {exc}")
                return ""
            if text:
                return text.replace("\n", " ").strip()
        return ""
    finally:
        await detail_page.close()


async def process_job_list_items(
    job_list: list,
    context: BrowserContext,
    skip_detail: bool,
    visit_sleep_min: float,
    visit_sleep_max: float,
    on_item,
    dedupe_keys: Optional[set[str]] = None,
    dedupe_log: bool = False,
) -> tuple[List[JobItem], int]:
    items: List[JobItem] = []
    dup_skipped = 0
    for item in job_list:
        title = (item.get("jobName") or item.get("positionName") or "").strip()
        salary = (item.get("salaryDesc") or item.get("salary") or "").strip()
        location = build_location(item)
        if is_intern_role(title):
            continue
        company = (
            item.get("brandName")
            or item.get("companyName")
            or item.get("brand")
            or item.get("company")
            or ""
        ).strip()

        encrypt_job_id = item.get("encryptJobId") or item.get("encryptId") or item.get("jobEncryptId")
        security_id = item.get("securityId") or ""
        link = ""
        if encrypt_job_id and security_id:
            link = f"{BASE_URL}/job_detail/{encrypt_job_id}.html?securityId={security_id}"
        elif encrypt_job_id:
            link = f"{BASE_URL}/job_detail/{encrypt_job_id}.html"
        if dedupe_keys is not None:
            key = build_item_key_from_fields(company, title, location, str(encrypt_job_id or ""), link)
            if key in dedupe_keys:
                dup_skipped += 1
                if dedupe_log:
                    log(f"[dedupe] skip {company} | {title} | {location}")
                continue
            dedupe_keys.add(key)

        description = (item.get("jobDesc") or item.get("jobDescription") or "").strip()
        if link and not skip_detail and not description:
            if should_pause_after_item():
                return items, dup_skipped
            description = await scrape_detail(context, link, visit_sleep_min, visit_sleep_max)

        items.append(
            JobItem(
                company=company,
                title=title,
                salary=salary,
                location=location,
                description=description,
                link=link,
                raw_item=json.dumps(item, ensure_ascii=False),
                security_id=list_to_str(security_id),
                encrypt_job_id=list_to_str(encrypt_job_id),
                encrypt_brand_id=list_to_str(item.get("encryptBrandId")),
                lid=list_to_str(item.get("lid")),
                boss_name=list_to_str(item.get("bossName")),
                boss_title=list_to_str(item.get("bossTitle")),
                boss_online=list_to_str(item.get("bossOnline")),
                boss_cert=list_to_str(item.get("bossCert")),
                gold_hunter=list_to_str(item.get("goldHunter")),
                brand_name=list_to_str(item.get("brandName")),
                brand_stage_name=list_to_str(item.get("brandStageName")),
                brand_industry=list_to_str(item.get("brandIndustry")),
                brand_scale_name=list_to_str(item.get("brandScaleName")),
                job_name=list_to_str(item.get("jobName") or item.get("positionName")),
                salary_desc=list_to_str(item.get("salaryDesc") or item.get("salary")),
                job_labels=list_to_str(item.get("jobLabels") or item.get("jobLabel")),
                skills=list_to_str(item.get("skills")),
                job_experience=list_to_str(item.get("jobExperience")),
                job_degree=list_to_str(item.get("jobDegree")),
                city_name=list_to_str(item.get("cityName") or item.get("jobCity") or item.get("city")),
                area_district=list_to_str(
                    item.get("areaDistrict")
                    or item.get("jobAreaDistrict")
                    or item.get("jobArea")
                    or item.get("area")
                ),
                business_district=list_to_str(
                    item.get("businessDistrict")
                    or item.get("jobAreaBusiness")
                    or item.get("business")
                ),
                welfare_list=list_to_str(item.get("welfareList")),
                job_valid_status=list_to_str(item.get("jobValidStatus")),
                job_type=list_to_str(item.get("jobType")),
            )
        )
        if on_item:
            on_item(items[-1])
        if items[-1].company or items[-1].title:
            log(format_item_log(items[-1]))
        if should_pause_after_item():
            return items, dup_skipped

    return items, dup_skipped


async def fetch_joblist_api(
    context: BrowserContext,
    template: dict,
    page_num: int,
    skip_detail: bool,
    visit_sleep_min: float,
    visit_sleep_max: float,
    on_item,
    dedupe_keys: Optional[set[str]] = None,
    dedupe_log: bool = False,
) -> tuple[List[JobItem], int]:
    url = template.get("url", "")
    if not url:
        return [], 0
    payload = update_page_payload(template.get("payload", {}), page_num)
    headers = template.get("headers", {})
    kind = template.get("kind", "form")
    if kind == "json":
        resp = await context.request.post(url, headers=headers, json=payload)
    else:
        resp = await context.request.post(url, headers=headers, data=payload)
    if resp.status != 200:
        return [], 0
    try:
        data = await resp.json()
    except Exception:
        return [], 0
    job_list = extract_job_list(data)
    if not job_list:
        return [], 0
    return await process_job_list_items(
        job_list,
        context,
        skip_detail,
        visit_sleep_min,
        visit_sleep_max,
        on_item,
        dedupe_keys,
        dedupe_log,
    )


async def scrape_list_page(
    context: BrowserContext,
    query: str,
    city: str,
    page_num: int,
    skip_detail: bool,
    debug_dump: str,
    wait_secs: int,
    visit_sleep_min: float,
    visit_sleep_max: float,
    on_item,
    page: Optional[Page] = None,
    dedupe_keys: Optional[set[str]] = None,
    dedupe_log: bool = False,
    template_holder: Optional[dict] = None,
) -> tuple[List[JobItem], int]:
    if city:
        url = f"{BASE_URL}/web/geek/job?query={quote_plus(query)}&city={city}&page={page_num}"
    else:
        url = f"{BASE_URL}/web/geek/job?query={quote_plus(query)}&page={page_num}"
    owns_page = page is None
    page = page or await context.new_page()

    job_list_future: asyncio.Future = asyncio.get_event_loop().create_future()
    joblist_request_info: dict = {}
    joblist_request_info: dict = {}

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
        if qs.get("page") and qs.get("page", [""])[0] != str(page_num):
            return
        job_list_future.set_result(job_list)

    def handle_response(resp) -> None:
        asyncio.create_task(maybe_capture_joblist(resp))

    def handle_request(req) -> None:
        if "joblist.json" not in req.url:
            return
        try:
            joblist_request_info["url"] = req.url
            joblist_request_info["headers"] = req.headers
            joblist_request_info["post_data"] = req.post_data or ""
        except Exception:
            pass

    page.on("response", handle_response)
    page.on("request", handle_request)
    try:
        log(f"[open] list {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        if wait_secs > 0:
            await page.wait_for_timeout(wait_secs * 1000)
        try:
            await page.wait_for_selector(
                ".job-card-wrapper, .job-list-box, .search-job-list, .job-card-box, .job-card-wrap",
                timeout=12000,
            )
        except TimeoutError:
            print(f"[warn] 页面未找到职位卡片选择器，可能被风控或 DOM 变更：{url}")
            html = await page.content()
            if "geetest" in html or "verify" in html or "captcha" in html:
                print("[warn] 检测到验证码相关内容，可能需要人工验证/登录。")
            if debug_dump:
                dump_prefix = f"{debug_dump}-page{page_num}"
                html_path = Path(f"{dump_prefix}.html")
                png_path = Path(f"{dump_prefix}.png")
                html_path.parent.mkdir(parents=True, exist_ok=True)
                html_path.write_text(html, encoding="utf-8")
                await page.screenshot(path=str(png_path), full_page=True)
                print(f"[debug] 已保存 HTML: {html_path}，截图: {png_path}")
            return [], 0
        await page.wait_for_timeout(randomized_timeout_ms(800, 1200))

        items: List[JobItem] = []
        dup_skipped = 0
        try:
            job_list = await asyncio.wait_for(job_list_future, timeout=4)
        except asyncio.TimeoutError:
            job_list = None

        if job_list:
            items, dup_skipped = await process_job_list_items(
                job_list,
                context,
                skip_detail,
                visit_sleep_min,
                visit_sleep_max,
                on_item,
                dedupe_keys,
                dedupe_log,
            )
            if template_holder is not None and joblist_request_info and not template_holder:
                template_holder.update(build_joblist_template(joblist_request_info))
            return items, dup_skipped

        cards = await page.query_selector_all(".job-card-wrapper, .search-job-card, .job-card-box")
        for card in cards:
            title = await get_text(card, ".job-name")
            salary = await get_text(card, ".salary") or await get_text(card, ".job-salary")
            location = await get_text(card, ".job-area") or await get_text(card, ".company-location")
            company = (
                await get_text(card, ".company-name")
                or await get_text(card, ".company-info a")
                or await get_text(card, ".boss-name")
            )
            if is_intern_role(title):
                continue

            link_node = await card.query_selector("a.job-name") or await card.query_selector("a")
            href = await link_node.get_attribute("href") if link_node else ""
            link = urljoin(BASE_URL, href) if href else ""
            if dedupe_keys is not None:
                key = build_item_key_from_fields(company, title, location, "", link)
                if key in dedupe_keys:
                    dup_skipped += 1
                    if dedupe_log:
                        log(f"[dedupe] skip {company} | {title} | {location}")
                    continue
                dedupe_keys.add(key)

            description = ""
            if link and not skip_detail:
                if should_pause_after_item():
                    items.append(
                        JobItem(
                            company=company,
                            title=title,
                            salary=salary,
                            location=location,
                            description=description,
                            link=link,
                            raw_item=json.dumps(
                                {
                                    "company": company,
                                    "title": title,
                                    "salary": salary,
                                    "location": location,
                                    "description": description,
                                    "link": link,
                                },
                                ensure_ascii=False,
                            ),
                        )
                    )
                    if on_item:
                        on_item(items[-1])
                    if items[-1].company or items[-1].title:
                        log(format_item_log(items[-1]))
                    return items, dup_skipped
                description = await scrape_detail(context, link, visit_sleep_min, visit_sleep_max)

            items.append(
                JobItem(
                    company=company,
                    title=title,
                    salary=salary,
                    location=location,
                    description=description,
                    link=link,
                    raw_item=json.dumps(
                        {
                            "company": company,
                            "title": title,
                            "salary": salary,
                            "location": location,
                            "description": description,
                            "link": link,
                        },
                        ensure_ascii=False,
                    ),
                )
            )
            if on_item:
                on_item(items[-1])
            if items[-1].company or items[-1].title:
                log(format_item_log(items[-1]))
            if should_pause_after_item():
                return items, dup_skipped

            await page.wait_for_timeout(randomized_timeout_ms(300, 500))

        if template_holder is not None and joblist_request_info and not template_holder:
            template_holder.update(build_joblist_template(joblist_request_info))
        return items, dup_skipped
    finally:
        try:
            page.remove_listener("response", handle_response)
        except Exception:
            pass
        try:
            page.remove_listener("request", handle_request)
        except Exception:
            pass
        try:
            if owns_page and not page.is_closed():
                await page.close()
        except Exception:
            pass


def build_context_kwargs(storage_state: str) -> dict:
    kwargs = {
        "user_agent": random.choice(USER_AGENTS),
        "viewport": {"width": 1280, "height": 800},
        "locale": "zh-CN",
    }
    if storage_state:
        kwargs["storage_state"] = storage_state
    return kwargs


def log(message: str) -> None:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_message = clean_text(message)
    line = f"[{now}] {safe_message}"
    print(line, flush=True)
    if LOG_FILE_HANDLE:
        try:
            LOG_FILE_HANDLE.write(line + "\n")
            LOG_FILE_HANDLE.flush()
        except Exception:
            pass


def handle_sigint(signum, frame) -> None:
    global PAUSE_REQUESTED
    if PAUSE_REQUESTED:
        return
    PAUSE_REQUESTED = True
    log("[signal] 收到 Ctrl+C，当前条目处理完后将暂停并询问参数。")


def should_pause_after_item() -> bool:
    return PAUSE_REQUESTED


def load_progress(progress_file: str) -> Optional[dict]:
    try:
        path = Path(progress_file)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return data
    except Exception:
        return None


def save_progress(progress_file: str, progress: dict) -> None:
    try:
        path = Path(progress_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def parse_csv_list(value: str) -> List[str]:
    normalized = (
        clean_text(value)
        .replace("，", ",")
        .replace("、", ",")
        .replace("[", "")
        .replace("]", "")
        .replace("（", "(")
        .replace("）", ")")
        .replace("(", "")
        .replace(")", "")
    )
    return [item.strip() for item in normalized.split(",") if item.strip()]


def clean_text(value: object) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    text = text.encode("utf-8", "replace").decode("utf-8")
    return "".join(ch for ch in text if ch.isprintable() or ch in "\t ")

def list_to_str(value: object) -> str:
    if isinstance(value, list):
        return ";".join(str(item).strip() for item in value if str(item).strip())
    if value is None:
        return ""
    return str(value).strip()


def build_item_key(item: JobItem) -> str:
    if item.encrypt_job_id:
        return f"job:{item.encrypt_job_id}"
    if item.link:
        return f"link:{item.link}"
    city = item.city_name or item.location
    return f"fallback:{item.company}|{item.title}|{city}"


def build_item_key_from_fields(
    company: str,
    title: str,
    city: str,
    encrypt_job_id: str,
    link: str,
) -> str:
    if encrypt_job_id:
        return f"job:{encrypt_job_id}"
    if link:
        return f"link:{link}"
    return f"fallback:{company}|{title}|{city}"


def normalize_headers(headers: dict) -> dict:
    cleaned = {}
    for key, value in headers.items():
        key_lower = key.lower()
        if key_lower in {"content-length", "host", "cookie"}:
            continue
        cleaned[key_lower] = value
    return cleaned


def parse_post_data(post_data: str) -> tuple[str, dict]:
    if not post_data:
        return "form", {}
    try:
        parsed = json.loads(post_data)
        if isinstance(parsed, dict):
            return "json", parsed
    except Exception:
        pass
    payload = {k: v for k, v in parse_qsl(post_data, keep_blank_values=True)}
    return "form", payload


def update_page_payload(payload: dict, page_num: int) -> dict:
    updated = dict(payload)
    for key in ("page", "pageNum", "pageNo", "pageIndex"):
        if key in updated:
            updated[key] = str(page_num)
            return updated
    updated["page"] = str(page_num)
    return updated


def build_joblist_template(request_info: dict) -> dict:
    kind, payload = parse_post_data(request_info.get("post_data", ""))
    return {
        "url": request_info.get("url", ""),
        "headers": normalize_headers(request_info.get("headers", {})),
        "kind": kind,
        "payload": payload,
    }


def get_city_map() -> dict[str, str]:
    global _CITY_MAP_CACHE
    if _CITY_MAP_CACHE is not None:
        return _CITY_MAP_CACHE
    mapping = dict(CITY_CODE_MAP)
    try:
        data = json.loads(CITY_MAP_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            mapping.update({str(k): str(v) for k, v in data.items()})
    except FileNotFoundError:
        pass
    except Exception:
        pass
    _CITY_MAP_CACHE = mapping
    return mapping


def get_city_name_map() -> dict[str, str]:
    global _CITY_NAME_CACHE
    if _CITY_NAME_CACHE is not None:
        return _CITY_NAME_CACHE
    name_map = dict(CITY_NAME_MAP)
    for name, code in get_city_map().items():
        name_map.setdefault(str(code), str(name))
    _CITY_NAME_CACHE = name_map
    return name_map

def sanitize_filename(value: str) -> str:
    sanitized = value.strip()
    for ch in ['\\', '/', ':', '*', '?', '"', '<', '>', '|']:
        sanitized = sanitized.replace(ch, "_")
    sanitized = sanitized.replace(" ", "-").replace("\t", "-")
    sanitized = sanitized.replace(",", "-").replace("，", "-").replace("、", "-")
    return sanitized


def resolve_city(value: str) -> str:
    city = clean_text(value).strip()
    if not city:
        return city
    return get_city_map().get(city, city)


def resolve_cities(values: Iterable[str]) -> List[str]:
    return [resolve_city(value) for value in values]


def city_to_label(city: str) -> str:
    if not city:
        return "全国"
    return get_city_name_map().get(city, city)


def build_default_out(queries: List[str], cities: List[str]) -> Path:
    query_label = "-".join([q for q in queries if q]) or "all"
    city_label = "-".join([city_to_label(c) for c in cities if c]) or "全国"
    filename = f"jobs_{sanitize_filename(query_label)}_{sanitize_filename(city_label)}.csv"
    return Path(filename)


def normalized_range(min_value: float, max_value: float) -> tuple[float, float]:
    if min_value <= max_value:
        return min_value, max_value
    return max_value, min_value


def open_csv_writer(out_path: Path, overwrite: bool) -> tuple[csv.DictWriter, object]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if overwrite:
        write_header = True
        mode = "w"
    else:
        write_header = not out_path.exists() or out_path.stat().st_size == 0
        mode = "a"
    encoding = "utf-8-sig" if write_header else "utf-8"
    f = out_path.open(mode, encoding=encoding, newline="")
    writer = csv.DictWriter(
        f,
        fieldnames=[
            "company",
            "title",
            "salary",
            "location",
            "description",
            "link",
            "security_id",
            "encrypt_job_id",
            "encrypt_brand_id",
            "lid",
            "boss_name",
            "boss_title",
            "boss_online",
            "boss_cert",
            "gold_hunter",
            "brand_name",
            "brand_stage_name",
            "brand_industry",
            "brand_scale_name",
            "job_name",
            "salary_desc",
            "job_labels",
            "skills",
            "job_experience",
            "job_degree",
            "city_name",
            "area_district",
            "business_district",
            "welfare_list",
            "job_valid_status",
            "job_type",
            "raw_item",
        ],
    )
    if write_header:
        writer.writeheader()
    return writer, f


async def bootstrap_login(
    query: str,
    city: str,
    wait_secs: int,
    save_state: str,
    channel: str,
) -> None:
    if wait_secs <= 0:
        wait_secs = 60
    save_path = Path(save_state)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    if city:
        url = f"{BASE_URL}/web/geek/job?query={quote_plus(query)}&city={city}&page=1"
    else:
        url = f"{BASE_URL}/web/geek/job?query={quote_plus(query)}&page=1"

    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            chromium_sandbox=False,
            handle_sigint=False,
            handle_sigterm=False,
            handle_sighup=False,
            channel=channel or None,
        )
        context: BrowserContext = await browser.new_context(**build_context_kwargs(""))
        page: Page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        print(f"[login] 请在 {wait_secs} 秒内完成登录/验证：{url}")
        await page.wait_for_timeout(wait_secs * 1000)
        await context.storage_state(path=str(save_path))
        await browser.close()
        print(f"[login] 已保存登录态：{save_path}")

async def run(
    queries: List[str],
    cities: List[str],
    pages: int,
    out_path: Path,
    headful: bool,
    skip_detail: bool,
    debug_dump: str,
    wait_secs: int,
    storage_state: str,
    save_state: str,
    channel: str,
    overwrite: bool,
    dedupe_on_the_fly: bool,
    page_sleep_min: float,
    page_sleep_max: float,
    cycles: int,
    loop: bool,
    cycle_sleep_min: float,
    cycle_sleep_max: float,
    empty_stop: int,
    max_retries: int,
    retry_sleep_min: float,
    retry_sleep_max: float,
    max_consecutive_errors: int,
    resume: bool,
    progress_file: str,
) -> None:
    effective_storage_state = storage_state or save_state
    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch(
            headless=not headful,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            chromium_sandbox=False,
            handle_sigint=False,
            handle_sigterm=False,
            handle_sighup=False,
            channel=channel or None,
        )
        context: BrowserContext = await browser.new_context(
            **build_context_kwargs(effective_storage_state)
        )

        writer, file_handle = open_csv_writer(out_path, overwrite)
        total_written = 0
        page_sleep_min, page_sleep_max = normalized_range(page_sleep_min, page_sleep_max)
        cycle_sleep_min, cycle_sleep_max = normalized_range(cycle_sleep_min, cycle_sleep_max)
        if empty_stop < 1:
            empty_stop = 1
        if max_retries < 0:
            max_retries = 0
        if max_consecutive_errors < 1:
            max_consecutive_errors = 1

        async def prompt_input(message: str) -> str:
            raw = await asyncio.to_thread(input, message)
            return clean_text(raw).strip()

        async def maybe_pause() -> str:
            nonlocal pages, queries, cities
            global PAUSE_REQUESTED
            if not PAUSE_REQUESTED:
                return "continue"
            PAUSE_REQUESTED = False
            log("[pause] 已暂停。可修改参数或继续。")
            choice = await prompt_input(
                "选项：1继续 2改页数上限 3改城市 4改关键词 5停止 > "
            )
            if choice == "2":
                value = await prompt_input("新的 --pages（空保持，0 表示不限）： ")
                if value:
                    try:
                        pages = max(0, int(value))
                        log(f"[pause] 已更新 pages = {pages}")
                    except ValueError:
                        log("[warn] pages 输入无效，保持不变")
                return "continue"
            if choice == "3":
                value = await prompt_input("新的城市列表（逗号分隔，空保持）： ")
                if value:
                    updated = resolve_cities(parse_csv_list(value))
                    if updated:
                        cities = updated
                        log(f"[pause] 已更新 cities = {','.join(cities)}")
                        return "restart"
                    log("[warn] 城市列表无效，保持不变")
                return "continue"
            if choice == "4":
                value = await prompt_input("新的关键词列表（逗号分隔，空保持）： ")
                if value:
                    updated = parse_csv_list(value)
                    if updated:
                        queries = updated
                        log(f"[pause] 已更新 queries = {','.join(queries)}")
                        return "restart"
                    log("[warn] 关键词列表无效，保持不变")
                return "continue"
            if choice == "5":
                log("[pause] 已选择停止")
                return "stop"
            return "continue"

        async def reset_context(reason: str) -> None:
            nonlocal context
            log(f"[warn] 重建浏览器上下文：{reason}")
            if save_state:
                try:
                    await context.storage_state(path=save_state)
                except Exception:
                    pass
            try:
                await context.close()
            except Exception:
                pass
            context = await browser.new_context(
                **build_context_kwargs(effective_storage_state)
            )

        progress = load_progress(progress_file) if resume else None
        start_cycle_index = 0
        start_query_index = 0
        start_city_index = 0
        start_page_num = 1
        if progress:
            saved_query = str(progress.get("query", ""))
            saved_city = str(progress.get("city", ""))
            saved_page = int(progress.get("page", 1) or 1)
            saved_cycle = int(progress.get("cycle_index", 0) or 0)
            if saved_query in queries and saved_city in cities:
                start_cycle_index = max(0, saved_cycle)
                start_query_index = queries.index(saved_query)
                start_city_index = cities.index(saved_city)
                start_page_num = max(1, saved_page)
                if pages > 0 and start_page_num > pages:
                    if start_city_index + 1 < len(cities):
                        start_city_index += 1
                        start_page_num = 1
                    elif start_query_index + 1 < len(queries):
                        start_query_index += 1
                        start_city_index = 0
                        start_page_num = 1
                    else:
                        start_cycle_index += 1
                        start_query_index = 0
                        start_city_index = 0
                        start_page_num = 1

        try:
            cycle_index = start_cycle_index
            consecutive_errors = 0
            joblist_templates: dict[tuple[str, str], dict] = {}
            while loop or cycle_index < cycles:
                query_index = 0
                if resume and cycle_index == start_cycle_index:
                    query_index = start_query_index
                while query_index < len(queries):
                    query = queries[query_index]
                    city_index = 0
                    if resume and cycle_index == start_cycle_index and query_index == start_query_index:
                        city_index = start_city_index
                    restart_all = False
                    while city_index < len(cities):
                        city = cities[city_index]
                        page_num = 1
                        list_page: Optional[Page] = None
                        if (
                            resume
                            and cycle_index == start_cycle_index
                            and query_index == start_query_index
                            and city_index == start_city_index
                        ):
                            page_num = start_page_num
                        empty_pages = 0
                        no_new_pages = 0
                        seen_keys = set()
                        try:
                            while True:
                                if pages > 0 and page_num > pages:
                                    break
                                city_label = city_to_label(city)
                                log(f"Scraping {query} | {city_label} | page {page_num} ...")
                                new_written = 0
                                dup_skipped = 0
                                template_key = (query, city)
                                use_api = page_num > 1 and template_key in joblist_templates
                                if use_api:
                                    prev_page = list_page
                                    list_page = await context.new_page()
                                    if prev_page:
                                        try:
                                            if not prev_page.is_closed():
                                                await prev_page.close()
                                        except Exception:
                                            pass
                                    list_url = (
                                        f"{BASE_URL}/web/geek/job?query={quote_plus(query)}&city={city}&page={page_num}"
                                        if city
                                        else f"{BASE_URL}/web/geek/job?query={quote_plus(query)}&page={page_num}"
                                    )
                                    try:
                                        await list_page.goto(list_url, wait_until="domcontentloaded", timeout=20000)
                                    except Exception:
                                        pass
                                def handle_item(item: JobItem) -> None:
                                    nonlocal total_written, new_written
                                    writer.writerow(asdict(item))
                                    file_handle.flush()
                                    total_written += 1
                                    new_written += 1
                                attempt = 0
                                items: List[JobItem] = []
                                while True:
                                    try:
                                        if use_api:
                                            items, dup_skipped = await fetch_joblist_api(
                                                context,
                                                joblist_templates[template_key],
                                                page_num,
                                                skip_detail,
                                                page_sleep_min,
                                                page_sleep_max,
                                                handle_item,
                                                seen_keys if dedupe_on_the_fly else None,
                                                dedupe_on_the_fly,
                                            )
                                        else:
                                            prev_page = list_page
                                            list_page = await context.new_page()
                                            if prev_page:
                                                try:
                                                    if not prev_page.is_closed():
                                                        await prev_page.close()
                                                except Exception:
                                                    pass
                                            template_holder: dict = {}
                                            items, dup_skipped = await scrape_list_page(
                                                context,
                                                query,
                                                city,
                                                page_num,
                                                skip_detail,
                                                debug_dump,
                                                wait_secs,
                                                page_sleep_min,
                                                page_sleep_max,
                                                handle_item,
                                                list_page,
                                                seen_keys if dedupe_on_the_fly else None,
                                                dedupe_on_the_fly,
                                                template_holder,
                                            )
                                            if template_holder:
                                                joblist_templates[template_key] = template_holder
                                        consecutive_errors = 0
                                        break
                                    except (TimeoutError, Error, asyncio.TimeoutError) as exc:
                                        attempt += 1
                                        consecutive_errors += 1
                                        log(f"[warn] 抓取失败，{exc}（{attempt}/{max_retries}）")
                                    except Exception as exc:
                                        attempt += 1
                                        consecutive_errors += 1
                                        log(f"[warn] 抓取异常，{exc}（{attempt}/{max_retries}）")
                                    if attempt > max_retries:
                                        log("[warn] 超过最大重试次数，跳过该页")
                                        break
                                    if consecutive_errors >= max_consecutive_errors:
                                        await reset_context("连续失败次数过多")
                                        consecutive_errors = 0
                                        try:
                                            if list_page and not list_page.is_closed():
                                                await list_page.close()
                                        except Exception:
                                            pass
                                        list_page = None
                                    await randomized_sleep(retry_sleep_min, retry_sleep_max)
                                if dedupe_on_the_fly:
                                    log(
                                        f"[page] {query} | {city_label} | page {page_num} -> "
                                        f"{len(items)} items ({new_written} new, {dup_skipped} dup)"
                                    )
                                else:
                                    log(f"[page] {query} | {city_label} | page {page_num} -> {len(items)} items")
                                save_progress(
                                    progress_file,
                                    {
                                        "query": query,
                                        "city": city,
                                        "page": page_num + 1,
                                        "cycle_index": cycle_index,
                                    },
                                )
                                if not items:
                                    empty_pages += 1
                                    log(
                                        f"[warn] empty page {page_num} ({empty_pages}/{empty_stop})"
                                    )
                                else:
                                    empty_pages = 0
                                if dedupe_on_the_fly:
                                    if new_written == 0:
                                        no_new_pages += 1
                                        log(f"[warn] no new items page {page_num} ({no_new_pages}/2)")
                                    else:
                                        no_new_pages = 0
                                    if no_new_pages >= 2:
                                        log("[stop] no new items for 2 consecutive pages")
                                        break
                                if pages == 0 and empty_pages >= empty_stop:
                                    log(f"[stop] reached {empty_stop} consecutive empty pages")
                                    break
                                page_num += 1
                                pause_action = await maybe_pause()
                                if pause_action == "stop":
                                    return
                                if pause_action == "restart":
                                    restart_all = True
                                    break
                                await randomized_sleep(page_sleep_min, page_sleep_max)
                        finally:
                            try:
                                if list_page and not list_page.is_closed():
                                    await list_page.close()
                            except Exception:
                                pass
                        resume = False
                        if restart_all:
                            break
                        city_index += 1
                    if restart_all:
                        query_index = 0
                        continue
                    query_index += 1
                cycle_index += 1
                if loop or cycle_index < cycles:
                    sleep_secs = randomized_timeout_ms(
                        int(cycle_sleep_min * 1000),
                        int(cycle_sleep_max * 1000),
                    )
                    log(f"[cycle] completed {cycle_index}, sleeping {sleep_secs / 1000:.1f}s ...")
                    await asyncio.sleep(sleep_secs / 1000)
        finally:
            if save_state:
                await context.storage_state(path=save_state)
            await browser.close()
            file_handle.close()

    log(f"Saved {total_written} jobs to {out_path}")


def main() -> None:
    global LOG_FILE_HANDLE
    signal.signal(signal.SIGINT, handle_sigint)
    args = parse_args()
    if args.headful and args.headless:
        raise SystemExit("不能同时指定 --headful 和 --headless")
    if args.skip_detail and args.with_detail:
        raise SystemExit("不能同时指定 --skip-detail 和 --with-detail")
    if args.headless:
        headful = False
    else:
        headful = True
    storage_state = args.storage_state
    save_state = args.save_state
    if save_state and not storage_state:
        storage_state = save_state

    queries = parse_csv_list(args.queries) if args.queries else []
    if args.nationwide:
        cities = [""]
    else:
        if args.cities:
            cities = resolve_cities(parse_csv_list(args.cities))
        else:
            cities = [""]
    if not queries:
        raise SystemExit("必须提供 --queries")
    if args.out:
        out_path = Path(args.out)
    else:
        out_path = DATA_DIR / build_default_out(queries, cities)
    if args.skip_detail:
        skip_detail = True
    else:
        skip_detail = False

    if args.auto_login:
        if not save_state:
            save_state = "storage_state.json"
        asyncio.run(
            bootstrap_login(queries[0], cities[0], args.wait_secs, save_state, args.channel)
        )
        storage_state = save_state
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        LOG_FILE_HANDLE = (LOG_DIR / f"run_{timestamp}.log").open("a", encoding="utf-8")
    except Exception:
        LOG_FILE_HANDLE = None
    asyncio.run(
        run(
            queries,
            cities,
            max(0, args.pages),
            out_path,
            headful,
            skip_detail,
            args.debug_dump,
            args.wait_secs,
            storage_state,
            save_state,
            args.channel,
            args.overwrite,
            args.dedupe_on_the_fly,
            args.page_sleep_min,
            args.page_sleep_max,
            max(1, args.cycles),
            args.loop,
            args.cycle_sleep_min,
            args.cycle_sleep_max,
            args.empty_stop,
            args.max_retries,
            args.retry_sleep_min,
            args.retry_sleep_max,
            args.max_consecutive_errors,
            args.resume,
            args.progress_file,
        )
    )
    if LOG_FILE_HANDLE:
        try:
            LOG_FILE_HANDLE.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
