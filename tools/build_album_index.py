#!/usr/bin/env python3
"""Build a local directory of third-party photo albums linked by ShoreAC."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROVIDERS = {
    "photos.google.com": "Google Photos",
    "photos.app.goo.gl": "Google Photos",
    "sourceathletics.com": "Source Athletics",
    "jackmccoyphotography.com": "Jack McCoy Photography",
    "finisherpix.com": "FinisherPix",
    "irievibesphotobooth.pic-time.com": "Irie Vibes Photo Booth",
    "boothpics.com": "Photo Booth",
    "lane1photos.com": "Lane 1 Photos",
    "drive.google.com": "Google Drive",
    "dropbox.com": "Dropbox Video",
    "youtube.com": "YouTube",
    "m.youtube.com": "YouTube",
    "youtu.be": "YouTube",
}
GENERIC_LABELS = {
    "click here",
    "here",
    "link",
    "photo",
    "photo album",
    "photos",
    "picture album",
    "race photos",
    "youtube",
}


def clean_label(value: str) -> str:
    label = re.sub(r"[\s\u200b]+", " ", value).strip(" .:-")
    return "" if label.casefold() in GENERIC_LABELS else label


def event_year(*values: str) -> str:
    for value in values:
        match = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", value)
        if match:
            return match.group(1)
    for value in values:
        match = re.search(r"(?<!\d)\d{1,2}/\d{1,2}/(\d{2})(?!\d)", value)
        if match:
            return f"20{match.group(1)}"
    return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", default="/tmp/shoreac-crawl/inventory.json")
    parser.add_argument("--migration", default=str(PROJECT_ROOT / "migration-report.json"))
    parser.add_argument("--output", default=str(PROJECT_ROOT / "album-data.js"))
    arguments = parser.parse_args()

    inventory = json.loads(Path(arguments.inventory).read_text(encoding="utf-8"))
    migration = json.loads(Path(arguments.migration).read_text(encoding="utf-8"))
    local_pages = {item["source_url"]: item["local_url"] for item in migration["pages"]}
    albums: dict[str, dict] = {}
    for page in inventory["pages"]:
        context = local_pages.get(page["url"], "archive.html")
        context_path = PROJECT_ROOT / context
        context_soup = BeautifulSoup(context_path.read_bytes(), "html.parser") if context_path.exists() else None
        for url in page.get("links", []):
            parsed = urlsplit(url)
            host = parsed.netloc.lower().removeprefix("www.")
            provider = PROVIDERS.get(host)
            if not provider and host == "runsignup.com" and "/Race/Photos" in parsed.path:
                provider = "RunSignup Photos"
            if not provider:
                continue
            anchor = context_soup.find("a", href=url) if context_soup else None
            label = clean_label(anchor.get_text(" ", strip=True)) if anchor else ""
            albums.setdefault(
                url,
                {
                    "title": page["title"],
                    "label": label,
                    "provider": provider,
                    "url": url,
                    "context": context,
                    "year": event_year(url, label, page["title"]),
                },
            )

    values = sorted(albums.values(), key=lambda item: (item["year"], item["title"]), reverse=True)
    Path(arguments.output).write_text(
        "window.SHORE_EXTERNAL_ALBUMS = " + json.dumps(values, indent=2, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    print(json.dumps({"external_media_links": len(values), "providers": len({item['provider'] for item in values})}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
