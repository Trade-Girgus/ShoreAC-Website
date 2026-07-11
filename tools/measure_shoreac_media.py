#!/usr/bin/env python3
"""Measure the deduplicated media set before importing it into GitHub Pages."""

from __future__ import annotations

import argparse
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests


USER_AGENT = "ShoreACMigrationAudit/1.0"
THREAD_LOCAL = threading.local()


def session() -> requests.Session:
    if not hasattr(THREAD_LOCAL, "session"):
        current = requests.Session()
        current.headers.update({"User-Agent": USER_AGENT})
        THREAD_LOCAL.session = current
    return THREAD_LOCAL.session


def logical_key(url: str) -> str:
    parsed = urlsplit(url)
    path = re.sub(r"_orig(?=\.[^.]+$)", "", parsed.path.lower())
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, "", ""))


def select_variant(urls: list[str]) -> str:
    def score(url: str) -> tuple[int, int, int]:
        path = urlsplit(url).path.lower()
        is_original = 1 if re.search(r"_orig\.[^.]+$", path) else 0
        has_query = 1 if urlsplit(url).query else 0
        return (is_original, has_query, len(url))

    return min(urls, key=score)


def measure(url: str) -> dict:
    current = session()
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = current.head(url, timeout=30, allow_redirects=True)
            if response.status_code >= 400 or not response.headers.get("content-length"):
                response = current.get(
                    url,
                    timeout=45,
                    allow_redirects=True,
                    headers={"Range": "bytes=0-0"},
                    stream=True,
                )
            response.raise_for_status()
            size_header = response.headers.get("content-range") or response.headers.get("content-length") or "0"
            if "/" in size_header:
                size_header = size_header.rsplit("/", 1)[-1]
            size = int(size_header) if size_header.isdigit() else 0
            return {
                "url": url,
                "final_url": response.url,
                "size": size,
                "content_type": response.headers.get("content-type", "").split(";", 1)[0],
            }
        except (requests.RequestException, ValueError) as error:
            last_error = error
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    return {"url": url, "size": 0, "error": str(last_error)}


def human_size(size: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", default="/tmp/shoreac-crawl/inventory.json")
    parser.add_argument("--output", default="/tmp/shoreac-crawl/media-manifest.json")
    parser.add_argument("--workers", type=int, default=16)
    arguments = parser.parse_args()

    inventory = json.loads(Path(arguments.inventory).read_text(encoding="utf-8"))
    grouped: dict[str, list[str]] = {}
    for page in inventory["pages"]:
        for url in page["media"]:
            grouped.setdefault(logical_key(url), []).append(url)

    selected = [select_variant(sorted(set(urls))) for urls in grouped.values()]
    measured: list[dict] = []
    with ThreadPoolExecutor(max_workers=arguments.workers) as executor:
        futures = {executor.submit(measure, url): url for url in selected}
        for index, future in enumerate(as_completed(futures), start=1):
            measured.append(future.result())
            if index % 250 == 0 or index == len(selected):
                print(f"Measured {index}/{len(selected)} assets", flush=True)

    measured.sort(key=lambda item: item["url"])
    total_size = sum(item.get("size", 0) for item in measured)
    failed = [item for item in measured if item.get("error")]
    payload = {
        "asset_count": len(measured),
        "measured_count": len(measured) - len(failed),
        "failed_count": len(failed),
        "total_size": total_size,
        "total_size_human": human_size(total_size),
        "assets": measured,
    }
    Path(arguments.output).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({key: payload[key] for key in payload if key != "assets"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
