#!/usr/bin/env python3
import argparse
import csv
from pathlib import Path


def build_key(row):
    for key in ("encrypt_job_id", "encryptJobId", "encrypt_id"):
        value = (row.get(key) or "").strip()
        if value:
            return f"job:{value}"
    link = (row.get("link") or "").strip()
    if link:
        return f"link:{link}"
    company = (row.get("company") or "").strip()
    title = (row.get("title") or "").strip()
    city = (row.get("city_name") or row.get("location") or "").strip()
    return f"fallback:{company}|{title}|{city}"


def dedupe_csv(input_path, output_path):
    with open(input_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    seen = set()
    kept = []
    for row in rows:
        key = build_key(row)
        if key in seen:
            continue
        seen.add(key)
        kept.append(row)

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(kept)

    return len(rows), len(kept)


def main():
    parser = argparse.ArgumentParser(description="Deduplicate job CSV by job id/link.")
    parser.add_argument("input", help="Input CSV path")
    parser.add_argument("--out", help="Output CSV path (default: <input>_deduped.csv)")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.out) if args.out else input_path.with_name(f"{input_path.stem}_deduped.csv")
    total, kept = dedupe_csv(input_path, output_path)
    print(f"rows: {total} -> {kept}, output: {output_path}")


if __name__ == "__main__":
    main()
