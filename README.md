getJD - 职位抓取与分析看板
==========================

项目介绍
--------
getJD 是一个面向个人学习/求职调研的职位数据工具链，覆盖「采集 → 清洗 → 看板分析」的完整流程。它的目标是用可控、可解释的方式快速获取 JD 信息，并在本地完成可视化洞察，帮助你把注意力放在技能与趋势判断上。

本项目包含两部分：
- `boss_crawler.py`：基于 Playwright 的 Boss 直聘职位抓取脚本，输出 CSV。
- `job-analytics-dashboard.html`：本地可视化看板，导入 CSV 即可分析。

可选工具：
- `analyze_jobs.py`：命令行统计与 JSON 输出（不再生成 HTML）。

环境准备
--------
- Python 3.9+
- 安装依赖：`pip install -r requirements.txt`
- 安装浏览器内核（首次执行）：`python -m playwright install chromium`

字体/乱码提示（Linux）
---------------------
如果页面中文出现方框，可选其一：
- 使用系统浏览器内核：`--channel chrome` 或 `--channel msedge`
- 安装中文字体：`sudo apt-get install -y fonts-noto-cjk`

抓取快速开始
------------
- 最小示例：
  `python boss_crawler.py --query 数据分析`
- 指定城市（城市名或代码，逗号分隔）：
  `python boss_crawler.py --query aiinfra --cities 北京,杭州`
- 只抓列表（更快、风控更低）：
  `python boss_crawler.py --query aiinfra --pages 1 --skip-detail`
- 保存登录态再复用（推荐）：
  `python boss_crawler.py --query aiinfra --auto-login --wait-secs 60 --save-state storage_state.json`
  `python boss_crawler.py --query aiinfra --storage-state storage_state.json --pages 2`

看板使用
--------
- 打开 `job-analytics-dashboard.html`
- 点击“导入数据 (CSV)”选择本地 CSV 文件

注意：看板依赖 CDN（ECharts / WordCloud / PapaParse / Tailwind / Google Fonts），需联网才能完整显示。

主要参数
--------
查询与范围
- `--query` / `--queries`：关键词（`--queries` 支持逗号分隔，优先级更高）。
- `--city` / `--cities`：城市名或代码（逗号分隔，优先级更高）。
- `--nationwide`：全国抓取（忽略城市参数）。
- `--pages`：页数（0 表示不限，直到连续空页停止）。
- `--empty-stop`：连续空页阈值（仅在 `--pages=0` 时生效）。

输出与续抓
- `--out`：CSV 输出路径（默认按关键词/城市命名）。
- `--overwrite`：覆盖写入（默认追加）。
- `--resume`：继续上次进度（需配合 `--progress-file`）。
- `--progress-file`：进度文件路径（JSON）。

浏览器与登录
- `--headless`：无界面模式（默认有界面）。
- `--headful`：有界面模式。
- `--auto-login`：先打开页面等待人工登录/验证后再抓取。
- `--storage-state` / `--save-state`：加载/保存登录态。
- `--wait-secs`：打开页面后额外等待秒数（手动验证用）。
- `--channel`：使用系统浏览器内核（如 `chrome` / `msedge`）。
- `--debug-dump`：保存页面 HTML + 截图（选择器未命中时）。

抓取节流与稳定性
- `--page-sleep-min` / `--page-sleep-max`：页面/详情访问间隔随机等待。
- `--max-retries` / `--retry-sleep-min` / `--retry-sleep-max`：失败重试策略。
- `--max-consecutive-errors`：连续失败阈值，达到后重建浏览器上下文。
- `--cycles` / `--loop`：按周期循环抓取（`--loop` 为无限循环）。
- `--cycle-sleep-min` / `--cycle-sleep-max`：周期间隔等待时间。

详情抓取
- `--skip-detail`：仅抓列表，不进入详情。
- `--with-detail`：抓取详情页（默认开启）。

CSV 字段
---------
基础字段：
- `company`, `title`, `salary`, `location`, `description`, `link`

扩展字段：
- `raw_item`, `security_id`, `encrypt_job_id`, `encrypt_brand_id`, `lid`
- `boss_name`, `boss_title`, `boss_online`, `boss_cert`, `gold_hunter`
- `brand_name`, `brand_stage_name`, `brand_industry`, `brand_scale_name`
- `job_name`, `salary_desc`, `job_labels`, `skills`
- `job_experience`, `job_degree`, `city_name`, `area_district`, `business_district`
- `welfare_list`, `job_valid_status`, `job_type`

常见问题
--------
- 列表为空/无数据：可能触发风控或验证码，先用 `--headful` 查看页面状态，再用 `--debug-dump` 保存 HTML/截图。
- 中文乱码：优先使用 `--channel chrome`；或安装中文字体。
- 需要稳定跑：降低页数、增加等待区间、先保存登录态再跑。

免责声明
--------
- 仅用于学习和个人研究，请遵守网站条款与当地法律法规。
- 因使用本工具导致的账号风控或其他后果，需自行承担。
