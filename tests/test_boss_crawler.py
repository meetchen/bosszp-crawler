import csv
import json
import tempfile
import unittest
from pathlib import Path

import boss_crawler


class TestBossCrawlerUtils(unittest.TestCase):
    def test_parse_csv_list(self) -> None:
        value = "北京、上海，杭州, 深圳"
        self.assertEqual(
            boss_crawler.parse_csv_list(value),
            ["北京", "上海", "杭州", "深圳"],
        )

    def test_sanitize_filename(self) -> None:
        value = 'ai/infra:测试, 深圳'
        self.assertEqual(
            boss_crawler.sanitize_filename(value),
            "ai_infra_测试--深圳",
        )

    def test_list_to_str(self) -> None:
        self.assertEqual(boss_crawler.list_to_str(["A", "B", " C "]), "A;B;C")
        self.assertEqual(boss_crawler.list_to_str(None), "")
        self.assertEqual(boss_crawler.list_to_str("x"), "x")

    def test_extract_job_list(self) -> None:
        payload = {
            "data": {
                "jobList": [
                    {"jobName": "A"},
                    {"jobName": "B"},
                ]
            }
        }
        self.assertEqual(boss_crawler.extract_job_list(payload), payload["data"]["jobList"])

    def test_build_location(self) -> None:
        item = {
            "cityName": "北京",
            "areaDistrict": "海淀区",
            "businessDistrict": "西北旺",
        }
        self.assertEqual(boss_crawler.build_location(item), "北京·海淀区·西北旺")

    def test_resolve_city(self) -> None:
        self.assertEqual(boss_crawler.resolve_city("北京"), "101010100")
        self.assertEqual(boss_crawler.resolve_city("101020100"), "101020100")

    def test_resolve_cities(self) -> None:
        self.assertEqual(
            boss_crawler.resolve_cities(["北京", "上海"]),
            ["101010100", "101020100"],
        )

    def test_build_default_out(self) -> None:
        path = boss_crawler.build_default_out(["aiinfra"], ["101010100"])
        self.assertEqual(path, Path("jobs_aiinfra_北京.csv"))

    def test_raw_item_written_to_csv(self) -> None:
        sample = {
            "bossName": "李女士",
            "jobName": "AI Infra",
            "cityName": "北京",
            "salaryDesc": "25-35K",
        }
        item = boss_crawler.JobItem(
            company="华为",
            title="AI Infra",
            salary="25-35K",
            location="北京·海淀区·西北旺",
            description="",
            link="",
            raw_item=json.dumps(sample, ensure_ascii=False),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "jobs.csv"
            writer, handle = boss_crawler.open_csv_writer(out_path, overwrite=True)
            writer.writerow(boss_crawler.asdict(item))
            handle.close()

            with out_path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
        self.assertEqual(len(rows), 1)
        self.assertIn("李女士", rows[0]["raw_item"])
        self.assertEqual(json.loads(rows[0]["raw_item"])["jobName"], "AI Infra")


if __name__ == "__main__":
    unittest.main()
