#!/usr/bin/env python3
"""Capture current public RunSignup details for Shore A.C.-owned registrations."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urldefrag, urljoin

import requests
from bs4 import BeautifulSoup


USER_AGENT = "ShoreACMigrationAudit/1.0"
REGISTRATIONS = [
    {
        "id": "membership",
        "source_page": "membership.html",
        "url": "https://runsignup.com/Club/NJ/SpringLake/ShoreAthleticClub",
        "kind": "membership",
    },
    {
        "id": "workout-wednesday",
        "source_page": "membership.html",
        "url": "https://runsignup.com/Race/NJ/Middletown/WorkoutWednesday",
        "kind": "program",
    },
    {
        "id": "captain-zinn",
        "source_page": "captain-zinn.html",
        "url": "https://runsignup.com/Race/NJ/SpringLake/THE52NDANNUALCAPTAINRONALDZINNMEMORIALRACES",
        "kind": "race",
    },
    {
        "id": "big-bang-mile",
        "source_page": "big-bang-mile.html",
        "url": "https://runsignup.com/Race/NJ/Holmdel/BigBangMile",
        "kind": "race",
    },
    {
        "id": "lake-takanassee",
        "source_page": "lake-takanassee-series.html",
        "url": "https://runsignup.com/Race/NJ/LongBranch/LakeTakanasseeSummerSeries",
        "kind": "race",
    },
    {
        "id": "sheehan-classic",
        "source_page": "sheehan-classic.html",
        "url": "https://runsignup.com/Race/NJ/AsburyPark/AsburyPark5K",
        "kind": "race",
    },
    {
        "id": "jersey-shore-half",
        "source_page": "jersey-shore-half.html",
        "url": "https://runsignup.com/Race/NJ/Highlands/JSHM",
        "kind": "race",
    },
    {
        "id": "polar-bear",
        "source_page": "polar-bear-races.html",
        "url": "https://runsignup.com/Race/NJ/AsburyPark/AsburyParkPolarBearRaces",
        "kind": "race",
    },
    {
        "id": "youth-xc",
        "source_page": "youth-xc-series.html",
        "url": "https://runsignup.com/Race/NJ/Holmdel/ShoreACYouthXCSeries",
        "kind": "race",
    },
    {
        "id": "adult-xc",
        "source_page": "cross-country-series.html",
        "url": "https://runsignup.com/Race/NJ/Holmdel/AdultCrossCountrySeries",
        "kind": "race",
    },
    {
        "id": "alumni-xc",
        "source_page": "alumni-xc-run1.html",
        "url": "https://runsignup.com/Race/NJ/Holmdel/AlumniXCRun",
        "kind": "race",
    },
]


def fetch(url: str) -> requests.Response:
    current = requests.Session()
    current.headers.update({"User-Agent": USER_AGENT})
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = current.get(url, timeout=45, allow_redirects=True)
            response.raise_for_status()
            return response
        except requests.RequestException as error:
            last_error = error
            if attempt < 2:
                time.sleep(0.75 * (attempt + 1))
    assert last_error is not None
    raise last_error


def clean_url(value: str, base_url: str) -> str:
    absolute = urljoin(base_url, value.strip())
    clean, _fragment = urldefrag(absolute)
    return clean


def schema_items(soup: BeautifulSoup) -> list[dict]:
    items: list[dict] = []
    for script in soup.select("script[type='application/ld+json']"):
        try:
            value = json.loads(script.get_text(strip=True))
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = value if isinstance(value, list) else [value]
        for candidate in candidates:
            if isinstance(candidate, dict):
                items.append(candidate)
    return items


def parse_registration(config: dict[str, str], raw_dir: Path) -> dict:
    response = fetch(config["url"])
    raw_name = f"{config['id']}.html"
    (raw_dir / raw_name).write_bytes(response.content)
    soup = BeautifulSoup(response.content, "html.parser")
    main = soup.select_one("#mainContent") or soup.select_one("main")
    if main is None:
        raise ValueError("No RunSignup main content found")

    for node in main.select("script, style, noscript"):
        node.decompose()
    text = main.get_text("\n", strip=True)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    links: set[str] = set()
    media: set[str] = set()
    for anchor in main.select("a[href]"):
        href = anchor.get("href", "").strip()
        if href and not href.startswith(("javascript:", "mailto:", "tel:")):
            links.add(clean_url(href, response.url))
    for element in main.select("img, iframe, video, source"):
        for attribute in ("src", "data-src", "data-image", "poster"):
            value = element.get(attribute)
            if value and not value.startswith("data:"):
                media.add(clean_url(value, response.url))

    sports_event = next(
        (
            item
            for item in schema_items(soup)
            if item.get("@type") in {"SportsEvent", "Event"}
        ),
        {},
    )
    title = sports_event.get("name") or (soup.title.get_text(" ", strip=True) if soup.title else config["id"])
    return {
        **config,
        "url": config["url"],
        "final_url": response.url,
        "title": title,
        "schema": sports_event,
        "text": text,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "word_count": len(text.split()),
        "links": sorted(links),
        "media": sorted(media),
        "raw_file": raw_name,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="/tmp/shoreac-crawl/runsignup")
    parser.add_argument("--workers", type=int, default=5)
    arguments = parser.parse_args()

    output_dir = Path(arguments.output)
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    registrations: list[dict] = []
    failures: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=arguments.workers) as executor:
        futures = {
            executor.submit(parse_registration, config, raw_dir): config
            for config in REGISTRATIONS
        }
        for future in as_completed(futures):
            config = futures[future]
            try:
                registrations.append(future.result())
            except Exception as error:
                failures.append({"id": config["id"], "url": config["url"], "error": str(error)})

    registrations.sort(key=lambda item: item["id"])
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "successful": len(registrations),
        "failed": len(failures),
        "failures": failures,
        "registrations": registrations,
    }
    (output_dir / "inventory.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps({"successful": len(registrations), "failed": len(failures)}, indent=2))
    for item in registrations:
        schema = item.get("schema", {})
        print(f"{item['id']}: {item['title']} | {schema.get('startDate', 'no date')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
