#!/usr/bin/env python3
"""Build a repeatable content and media inventory of the public ShoreAC site."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


SITE_ROOT = "https://www.shoreac.org/"
SITEMAP_URL = urljoin(SITE_ROOT, "sitemap.xml")
USER_AGENT = "ShoreACMigrationAudit/1.0"
MEDIA_EXTENSIONS = {
    ".avif",
    ".gif",
    ".jpeg",
    ".jpg",
    ".m4v",
    ".mov",
    ".mp3",
    ".mp4",
    ".pdf",
    ".png",
    ".svg",
    ".webm",
    ".webp",
}
THREAD_LOCAL = threading.local()


def session() -> requests.Session:
    if not hasattr(THREAD_LOCAL, "session"):
        current = requests.Session()
        current.headers.update({"User-Agent": USER_AGENT})
        THREAD_LOCAL.session = current
    return THREAD_LOCAL.session


def fetch(url: str, attempts: int = 3) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = session().get(url, timeout=45, allow_redirects=True)
            response.raise_for_status()
            return response
        except requests.RequestException as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(0.75 * (attempt + 1))
    assert last_error is not None
    raise last_error


def clean_url(url: str, base_url: str) -> str:
    absolute = urljoin(base_url, url.strip())
    clean, _fragment = urldefrag(absolute)
    return clean


def is_media_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(path.endswith(extension) for extension in MEDIA_EXTENSIONS)


def page_key(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def page_category(url: str) -> str:
    path = urlparse(url).path.lower()
    if "/shore-ac-news/" in path:
        return "news"
    if "/store/" in path:
        return "store"
    if "probables" in path:
        return "team-roster"
    if re.search(r"(results|scoring)\.html$", path):
        return "results"
    if any(term in path for term in ("photo", "millrose-2020", "85th-anniversary")):
        return "photos"
    return "page"


def sitemap_entries(xml_text: str) -> list[dict[str, str]]:
    root = ET.fromstring(xml_text)
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    entries: list[dict[str, str]] = []
    for node in root.findall("sm:url", namespace):
        location = node.findtext("sm:loc", default="", namespaces=namespace).strip()
        modified = node.findtext("sm:lastmod", default="", namespaces=namespace).strip()
        if location:
            entries.append({"url": location, "lastmod": modified})
    return entries


def media_from_element(element, page_url: str) -> list[str]:
    candidates: list[str] = []
    for attribute in ("src", "data-src", "data-image", "data-background", "poster"):
        value = element.get(attribute)
        if value and not value.startswith(("data:", "javascript:")):
            candidates.append(clean_url(value, page_url))
    srcset = element.get("srcset") or element.get("data-srcset")
    if srcset:
        for part in srcset.split(","):
            value = part.strip().split(" ")[0]
            if value:
                candidates.append(clean_url(value, page_url))
    return candidates


def parse_page(entry: dict[str, str], raw_dir: Path) -> dict:
    url = entry["url"]
    key = page_key(url)
    raw_path = raw_dir / f"{key}.html"
    response = fetch(url)
    raw_path.write_bytes(response.content)

    soup = BeautifulSoup(response.content, "html.parser")
    content = soup.select_one("#wsite-content") or soup.select_one("main") or soup.body
    if content is None:
        raise ValueError("No page content container found")

    for node in content.select("script, style, noscript"):
        node.decompose()

    title_node = soup.select_one("meta[property='og:title']")
    title = title_node.get("content", "").strip() if title_node else ""
    if not title:
        title = soup.title.get_text(" ", strip=True) if soup.title else urlparse(url).path

    content_text = content.get_text("\n", strip=True)
    content_text = re.sub(r"[ \t]+", " ", content_text)
    content_text = re.sub(r"\n{3,}", "\n\n", content_text).strip()

    links: set[str] = set()
    media: set[str] = set()
    videos: set[str] = set()
    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "").strip()
        if not href or href.startswith(("javascript:", "tel:", "mailto:")):
            continue
        absolute = clean_url(href, response.url)
        links.add(absolute)
        if is_media_url(absolute):
            media.add(absolute)

    for element in content.select("img, iframe, video, source, audio"):
        for candidate in media_from_element(element, response.url):
            if element.name in {"iframe", "video", "source"} and (
                "youtube.com" in candidate
                or "youtu.be" in candidate
                or urlparse(candidate).path.lower().endswith((".mp4", ".mov", ".webm", ".m4v"))
            ):
                videos.add(candidate)
            if is_media_url(candidate) or "/uploads/" in candidate:
                media.add(candidate)

    for styled in content.select("[style*='background']"):
        for match in re.findall(r"url\(['\"]?([^'\")]+)", styled.get("style", "")):
            media.add(clean_url(match, response.url))

    return {
        "url": url,
        "final_url": response.url,
        "lastmod": entry.get("lastmod", ""),
        "category": page_category(url),
        "title": title,
        "text": content_text,
        "text_sha256": hashlib.sha256(content_text.encode("utf-8")).hexdigest(),
        "word_count": len(content_text.split()),
        "links": sorted(links),
        "media": sorted(media),
        "videos": sorted(videos),
        "raw_file": raw_path.name,
    }


def write_lines(path: Path, values: list[str]) -> None:
    path.write_text("\n".join(values) + ("\n" if values else ""), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="/tmp/shoreac-crawl")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0)
    arguments = parser.parse_args()

    output_dir = Path(arguments.output)
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    sitemap_response = fetch(SITEMAP_URL)
    entries = sitemap_entries(sitemap_response.text)
    if arguments.limit:
        entries = entries[: arguments.limit]

    pages: list[dict] = []
    failures: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=arguments.workers) as executor:
        future_map = {executor.submit(parse_page, entry, raw_dir): entry for entry in entries}
        for index, future in enumerate(as_completed(future_map), start=1):
            entry = future_map[future]
            try:
                pages.append(future.result())
            except Exception as error:  # Keep the audit moving and report each gap.
                failures.append({"url": entry["url"], "error": str(error)})
            if index % 50 == 0 or index == len(entries):
                print(f"Audited {index}/{len(entries)} pages", flush=True)

    pages.sort(key=lambda page: page["url"])
    all_links = sorted({link for page in pages for link in page["links"]})
    all_media = sorted({item for page in pages for item in page["media"]})
    all_videos = sorted({item for page in pages for item in page["videos"]})
    runsignup_links = sorted(link for link in all_links if "runsignup.com" in urlparse(link).netloc)
    internal_links = sorted(link for link in all_links if urlparse(link).netloc.endswith("shoreac.org"))
    external_links = sorted(set(all_links) - set(internal_links))

    payload = {
        "source": SITE_ROOT,
        "sitemap": SITEMAP_URL,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "counts": {
            "sitemap_pages": len(entries),
            "successful_pages": len(pages),
            "failed_pages": len(failures),
            "links": len(all_links),
            "internal_links": len(internal_links),
            "external_links": len(external_links),
            "media": len(all_media),
            "videos": len(all_videos),
            "runsignup_links": len(runsignup_links),
        },
        "failures": failures,
        "pages": pages,
    }
    (output_dir / "inventory.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    write_lines(output_dir / "page-urls.txt", [entry["url"] for entry in entries])
    write_lines(output_dir / "links.txt", all_links)
    write_lines(output_dir / "internal-links.txt", internal_links)
    write_lines(output_dir / "external-links.txt", external_links)
    write_lines(output_dir / "media-urls.txt", all_media)
    write_lines(output_dir / "video-urls.txt", all_videos)
    write_lines(output_dir / "runsignup-urls.txt", runsignup_links)
    print(json.dumps(payload["counts"], indent=2))
    if failures:
        print(f"Failures are listed in {output_dir / 'inventory.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
