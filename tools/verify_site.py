#!/usr/bin/env python3
"""Verify local content fidelity, media references, and site navigation links."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def normalized_text(element) -> str:
    copy = BeautifulSoup(str(element), "html.parser")
    for node in copy.select("script, style, noscript"):
        node.decompose()
    text = copy.get_text("\n", strip=True)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def local_target(source_file: Path, reference: str) -> Path | None:
    if not reference or reference.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return None
    parsed = urlsplit(reference)
    if parsed.scheme or parsed.netloc:
        return None
    path = unquote(parsed.path)
    if not path:
        return None
    target = (source_file.parent / path).resolve()
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", default="/tmp/shoreac-crawl/inventory.json")
    parser.add_argument("--runsignup", default="/tmp/shoreac-crawl/runsignup/inventory.json")
    parser.add_argument("--report", default=str(PROJECT_ROOT / "site-audit.json"))
    arguments = parser.parse_args()

    source_inventory = json.loads(Path(arguments.inventory).read_text(encoding="utf-8"))
    runsignup_inventory = json.loads(Path(arguments.runsignup).read_text(encoding="utf-8"))
    migration_report = json.loads((PROJECT_ROOT / "migration-report.json").read_text(encoding="utf-8"))
    page_lookup = {item["source_url"]: item["local_url"] for item in migration_report["pages"]}

    text_mismatches: list[dict] = []
    missing_archive_pages: list[str] = []
    for page in source_inventory["pages"]:
        relative = page_lookup.get(page["url"])
        if not relative:
            missing_archive_pages.append(page["url"])
            continue
        local_path = PROJECT_ROOT / relative
        if not local_path.exists():
            missing_archive_pages.append(relative)
            continue
        soup = BeautifulSoup(local_path.read_bytes(), "html.parser")
        content = soup.select_one(".archive-content")
        if content is None:
            text_mismatches.append({"source": page["url"], "local": relative, "reason": "missing archive content"})
            continue
        local_text = normalized_text(content)
        if text_hash(local_text) != page["text_sha256"]:
            text_mismatches.append(
                {
                    "source": page["url"],
                    "local": relative,
                    "source_words": page["word_count"],
                    "local_words": len(local_text.split()),
                    "source_hash": page["text_sha256"],
                    "local_hash": text_hash(local_text),
                }
            )

    runsignup_mismatches: list[dict] = []
    source_page_to_local = {
        Path(urlsplit(source_url).path).name: local_url
        for source_url, local_url in page_lookup.items()
    }
    for registration in runsignup_inventory.get("registrations", []):
        if registration["kind"] == "program":
            relative = f"archive/{registration['id']}.html"
            selector = ".archive-content"
        else:
            relative = source_page_to_local.get(registration["source_page"], "")
            selector = ".runsignup-content"
        local_path = PROJECT_ROOT / relative
        if not relative or not local_path.exists():
            runsignup_mismatches.append({"id": registration["id"], "reason": "missing local page"})
            continue
        soup = BeautifulSoup(local_path.read_bytes(), "html.parser")
        content = soup.select_one(selector)
        if content is None:
            runsignup_mismatches.append({"id": registration["id"], "reason": "missing registration content"})
            continue
        local_text = normalized_text(content)
        if text_hash(local_text) != registration["text_sha256"]:
            runsignup_mismatches.append(
                {
                    "id": registration["id"],
                    "source_words": registration["word_count"],
                    "local_words": len(local_text.split()),
                    "source_hash": registration["text_sha256"],
                    "local_hash": text_hash(local_text),
                }
            )

    html_files = sorted(PROJECT_ROOT.glob("*.html")) + sorted((PROJECT_ROOT / "archive").glob("*.html"))
    broken_local_links: list[dict] = []
    old_site_attributes: list[dict] = []
    missing_navigation: list[str] = []
    for html_file in html_files:
        soup = BeautifulSoup(html_file.read_bytes(), "html.parser")
        scripts = [node.get("src", "") for node in soup.select("script[src]")]
        if html_file.name != "index.html" and not any("site-nav.js" in source for source in scripts):
            missing_navigation.append(str(html_file.relative_to(PROJECT_ROOT)))
        for tag in soup.find_all(True):
            for attribute in ("href", "src", "poster"):
                reference = tag.get(attribute)
                if not isinstance(reference, str):
                    continue
                if re.match(r"https?://(?:www\.)?shoreac\.org/", reference, re.I):
                    old_site_attributes.append(
                        {
                            "file": str(html_file.relative_to(PROJECT_ROOT)),
                            "attribute": attribute,
                            "value": reference,
                        }
                    )
                target = local_target(html_file, reference)
                if target is not None and not target.exists():
                    broken_local_links.append(
                        {
                            "file": str(html_file.relative_to(PROJECT_ROOT)),
                            "attribute": attribute,
                            "value": reference,
                        }
                    )

    css_missing: list[dict] = []
    for css_file in PROJECT_ROOT.glob("*.css"):
        source = css_file.read_text(encoding="utf-8")
        for reference in re.findall(r"url\(['\"]?([^'\")]+)", source):
            target = local_target(css_file, reference)
            if target is not None and not target.exists():
                css_missing.append({"file": css_file.name, "value": reference})

    gallery_source = (PROJECT_ROOT / "gallery-data.js").read_text(encoding="utf-8")
    gallery_match = re.search(r"window\.SHORE_GALLERIES\s*=\s*(\[.*\])\s*;?\s*$", gallery_source, re.S)
    galleries = json.loads(gallery_match.group(1)) if gallery_match else []
    gallery_images = [image for gallery in galleries for image in gallery.get("images", [])]
    missing_gallery_images = [image for image in gallery_images if not (PROJECT_ROOT / image).exists()]

    album_source = (PROJECT_ROOT / "album-data.js").read_text(encoding="utf-8")
    album_match = re.search(r"window\.SHORE_EXTERNAL_ALBUMS\s*=\s*(\[.*\])\s*;?\s*$", album_source, re.S)
    albums = json.loads(album_match.group(1)) if album_match else []
    missing_album_contexts = [
        album["context"]
        for album in albums
        if not (PROJECT_ROOT / album["context"]).exists()
    ]

    report = {
        "source_pages_expected": len(source_inventory["pages"]),
        "source_pages_verified": len(source_inventory["pages"]) - len(text_mismatches) - len(missing_archive_pages),
        "text_mismatches": text_mismatches,
        "missing_archive_pages": missing_archive_pages,
        "runsignup_pages_expected": len(runsignup_inventory.get("registrations", [])),
        "runsignup_pages_verified": len(runsignup_inventory.get("registrations", [])) - len(runsignup_mismatches),
        "runsignup_mismatches": runsignup_mismatches,
        "html_files_checked": len(html_files),
        "broken_local_links": broken_local_links,
        "old_site_attributes": old_site_attributes,
        "missing_navigation": missing_navigation,
        "css_missing_assets": css_missing,
        "gallery_images_checked": len(gallery_images),
        "missing_gallery_images": missing_gallery_images,
        "external_media_links_indexed": len(albums),
        "missing_album_contexts": missing_album_contexts,
        "local_media_files": len(list((PROJECT_ROOT / "assets" / "archive").glob("*"))),
    }
    report["passed"] = not any(
        (
            text_mismatches,
            missing_archive_pages,
            runsignup_mismatches,
            broken_local_links,
            old_site_attributes,
            missing_navigation,
            css_missing,
            missing_gallery_images,
            missing_album_contexts,
        )
    )
    Path(arguments.report).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        json.dumps(
            {key: value if not isinstance(value, list) else len(value) for key, value in report.items()},
            indent=2,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
