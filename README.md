Boss直聘爬虫
==========

一个简单的命令行爬虫，使用 Playwright 抓取 Boss 直聘职位数据，输出为 CSV。后续可扩展为多站点模块。

特性
----
- 多关键词/多城市抓取，支持全国范围
- 支持抓详情页，可选跳过详情以提高速度
- 断点续抓、循环抓取、随机等待降低风控
- 可保存/复用登录态（storage state）

准备
----
- Python 3.9+
- 安装依赖：
  - `pip install -r requirements.txt`
  - 安装浏览器内核（首次执行）：`python -m playwright install chromium`

使用
----
- 示例：最简用法（默认多城市抓取，默认抓详情）  
  `python boss_crawler.py --query 数据分析`
- 示例：指定城市（支持中文城市名）  
  `python boss_crawler.py --queries aiinfra,mlops --cities 北京、上海、杭州`
- 示例：多关键词单次输入（并集搜索，逐个关键词抓取）  
  `python boss_crawler.py --queries aiinfra,高性能计算,推理引擎,rust --cities 北京,杭州`
- 示例：合并为一个 query（平台搜索逻辑决定效果）  
  `python boss_crawler.py --query "aiinfra 高性能计算 推理引擎 rust" --cities 北京,杭州`
- 示例：只抓 1 页（更快、风控更低）  
  `python boss_crawler.py --query 数据分析 --cities 北京 --pages 1 --skip-detail`
- 示例：全国范围  
  `python boss_crawler.py --query 数据分析 --nationwide`
- 示例：断点续抓  
  `python boss_crawler.py --query 数据分析 --resume --progress-file progress_state.json`

参数
----
- `--query`/`--queries`（必填）：岗位关键词（支持逗号分隔多个关键词）。
- `--city`/`--cities`：城市代码或中文名称（支持逗号分隔多个城市），默认使用 北京/上海/杭州/苏州/深圳/广州/西安。
- `--nationwide`：全国范围抓取（不传 city 参数）。
- `--pages`：抓取页数，默认 30（每个城市上限）。
- `--out`：CSV 输出路径，默认按 `jobs_{关键词}_{城市}.csv` 自动命名。
- `--headful`：可选，使用有界面模式（默认无界面）。
- `--headless`：可选，使用无界面模式。
- `--auto-login`：可选，先打开页面等待人工登录/验证并保存状态，再自动抓取。
- `--channel`：可选，使用系统浏览器内核（如 `chrome` 或 `msedge`），可解决无中文字库导致的乱码。
- `--skip-detail`：可选，跳过进入详情页，仅抓列表（更快，风控风险更低）。
- `--with-detail`：可选，抓取详情页内容（默认开启）。
- `--debug-dump`：可选，当页面未命中列表选择器时保存 HTML 和截图的前缀路径（如 `debug/boss`）。
- `--wait-secs`：可选，页面打开后额外等待秒数（方便手动登录/验证码处理）。
- `--storage-state`：可选，加载已登录的 storage state 文件（如 `storage_state.json`）。
- `--save-state`：可选，保存当前会话的 storage state 到文件，便于后续复用。

字段
----
- 基础：公司、岗位、薪资、地点、岗位要求/介绍、链接
- 扩展：security_id、encrypt_job_id、encrypt_brand_id、lid、boss_name、boss_title、boss_online、boss_cert、gold_hunter、brand_name、brand_stage_name、brand_industry、brand_scale_name、job_name、salary_desc、job_labels、skills、job_experience、job_degree、city_name、area_district、business_district、welfare_list、job_valid_status、job_type

测试
----
- 运行单元测试：
  `python -m unittest discover -s tests -v`

目录结构
--------
- `boss_crawler.py`：主爬虫脚本
- `test_publish_time.py`：列表接口字段调试脚本
- `city_map.json`：城市名称与编码映射
- `tests/`：单元测试

使用手册
--------
- 先完成一次登录态保存（推荐）  
  `python boss_crawler.py --query 数据分析 --headful --wait-secs 30 --save-state storage_state.json`
- 之后复用登录态抓取  
  `python boss_crawler.py --query 数据分析 --storage-state storage_state.json`
- 需要系统浏览器内核（避免中文乱码）  
  `python boss_crawler.py --query 数据分析 --channel chrome`
- 只抓列表（更快、风控更低）  
  `python boss_crawler.py --query 数据分析 --skip-detail`
- Ctrl+C 暂停（处理完当前条目后暂停并允许改参数/停止）  
  在运行中按 Ctrl+C 后会进入交互选择。

开发建议
--------
- 优先走接口 `jobList` 抽取路径，DOM 仅作兜底
- 新增字段时，保持 `raw_item` 原样写入，便于回溯
- 选择器更新时，先用 `--headful --debug-dump` 保存 HTML/截图再调整
- 尽量在小页数范围内调试，避免触发风控

反爬说明
--------
- 站点可能触发登录/验证码/风控，建议降低页数并增加随机等待
- 推荐使用 `--storage-state` 复用登录态，减少重复验证
- 如遇列表为空或 selector 超时，先用 `--headful` 观察页面状态

常见问题
--------
- Q: 运行后列表为空？  
  A: 可能被风控或 DOM 变更，先用 `--headful` 打开页面确认是否被验证码拦截，再用 `--debug-dump` 保存页面内容。
- Q: 中文乱码？  
  A: 使用系统浏览器内核，例如 `--channel chrome`。
- Q: 想中断后继续？  
  A: 使用 `--resume --progress-file progress_state.json`。

免责声明
--------
- 本项目仅供学习与研究用途，请勿用于任何违反法律法规或平台条款的行为。
- 使用者需自行承担使用本工具产生的风险与后果。
- 如因使用本工具导致账号风控、限制或其他损失，作者不承担任何责任。

注意
----
- Boss 直聘存在反爬，适当控制页数与频率，个人学习/私用即可。
- 选择器可能随官网更新而变化，如遇空数据，可使用 `--headful` 打开浏览器观察 DOM 并调整选择器。
- 如果抓取结果为 0，先尝试常见关键词（如“Java”）确认能否抓到列表；若仍为空，可能触发登录/验证码或 DOM 变更，可用 `--headful` 查看页面状态并调整选择器。
- 如怀疑被风控，可用 `--headful --wait-secs 30 --debug-dump debug/boss`，先手动完成验证，再把保存的 HTML/截图发我，我帮你适配选择器。
- 也可先手动登录后保存状态，再在后续任务中复用：`--headful --wait-secs 30 --save-state storage_state.json`，之后加 `--storage-state storage_state.json`。
- 想减少手动操作，可用 `--auto-login --wait-secs 60 --save-state storage_state.json`，先完成一次验证后自动开始抓取。
