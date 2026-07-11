#!/usr/bin/env python3
"""Import audited ShoreAC content into designed local archive pages."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import unquote, urldefrag, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup, Comment


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = "https://www.shoreac.org/"
USER_AGENT = "ShoreACMigrationImport/1.0"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
COPY_EXTENSIONS = {".avif", ".gif", ".m4v", ".mov", ".mp3", ".mp4", ".pdf", ".pptx", ".svg", ".webm", ".webp"}
BLOCKED_HOSTS = {"motegi-kk.com", "maquinandoysubastando.com"}
EXTERNAL_MEDIA_HOSTS = {"dropbox.com"}
MEDIA_DOWNLOAD_OVERRIDES = {
    "https://oceanbreezenyc.org/documents/2020/2/10/scores.pdf":
        "https://s3.us-east-2.amazonaws.com/sidearm.nextgen.sites/obp.sidearmsports.com/documents/2020/2/10/scores.pdf",
}
EXTERNAL_MEDIA_ASSETS = [
    {
        "url": "https://www.dropbox.com/scl/fi/swgwa1nwp4osbajcynf8f/Big-Bang-Mile-Science-Talks-Lecture-_1-Cosmology_-_From-Dark-Ages-to-Dark-Energy_.mp4?rlkey=goex745eif1thue9ds37mknly&e=1&st=w68qn2lj&dl=0",
        "size": 2491692375,
        "reason": "Hosted on Dropbox because the 2.49 GB source exceeds GitHub's 100 MB per-file limit.",
    },
    {
        "url": "https://www.dropbox.com/scl/fi/i1mf0s2jv5x3vri4pu72b/Big-Bang-Mile-Science-Talks-Lecture-_2_-Nuclear-Fusion_-_The-Fastest-Route-to-Fusion-Energy_.mp4?rlkey=ae34kl267thy5jhptht9igup7&e=2&st=wzkq3ftw&dl=0",
        "size": 2538082928,
        "reason": "Hosted on Dropbox because the 2.54 GB source exceeds GitHub's 100 MB per-file limit.",
    },
]
KNOWN_UNAVAILABLE_URLS = {
    "https://villanova.com/documents/2021/3/17//MURPHY_Liam.pdf?id=11625",
    "https://www.shoreac.org/uploads/1/1/5/0/115007939/background-images/702799340.png",
    "https://www.shoreac.org/uploads/1/1/5/0/115007939/int_meet_program_1.4.pdf",
}
THREAD_LOCAL = threading.local()
CATEGORY_LABELS = {
    "news": "News and Blog",
    "results": "Results",
    "team-roster": "Competition Teams",
    "store": "Historical Store",
    "photos": "Photos",
    "page": "Club Archive",
}
CATEGORY_HUBS = {
    "news": "../news.html",
    "results": "../results.html",
    "team-roster": "../programs.html#compete",
    "store": "../support.html",
    "photos": "../media.html",
    "page": "../archive.html",
}


def session() -> requests.Session:
    if not hasattr(THREAD_LOCAL, "session"):
        current = requests.Session()
        current.headers.update({"User-Agent": USER_AGENT})
        THREAD_LOCAL.session = current
    return THREAD_LOCAL.session


def ascii_slug(value: str, fallback: str = "page") -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower().replace("'", "")
    normalized = re.sub(r"[^a-z0-9._-]+", "-", normalized).strip("-._")
    return normalized or fallback


def clean_absolute_url(value: str, base_url: str) -> str:
    absolute = urljoin(base_url, value.strip())
    clean, _fragment = urldefrag(absolute)
    return clean


def canonical_page_url(value: str) -> str:
    parsed = urlsplit(value)
    host = parsed.netloc.lower().removeprefix("www.")
    path = unquote(parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit(("https", host, path, "", ""))


def logical_media_key(value: str) -> str:
    parsed = urlsplit(value)
    path = re.sub(r"_orig(?=\.[^.]+$)", "", unquote(parsed.path).lower())
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, "", ""))


def select_media_variant(urls: list[str]) -> str:
    def score(url: str) -> tuple[int, int, int]:
        parsed = urlsplit(url)
        original = 1 if re.search(r"_orig\.[^.]+$", parsed.path.lower()) else 0
        query = 1 if parsed.query else 0
        return (original, query, len(url))

    return min(urls, key=score)


def archive_filename(url: str) -> str:
    path = unquote(urlsplit(url).path).strip("/") or "home"
    path = path.removesuffix(".html")
    return f"{ascii_slug(path.replace('/', '--'))}.html"


def build_page_map(pages: list[dict]) -> dict[str, str]:
    page_map: dict[str, str] = {}
    used: dict[str, str] = {}
    for page in pages:
        filename = archive_filename(page["url"])
        if filename in used and used[filename] != page["url"]:
            stem = Path(filename).stem
            suffix = hashlib.sha1(page["url"].encode("utf-8")).hexdigest()[:8]
            filename = f"{stem}-{suffix}.html"
        used[filename] = page["url"]
        page_map[canonical_page_url(page["url"])] = filename
        page["archive_file"] = filename
    return page_map


def parse_gallery_urls(path: Path) -> tuple[list[dict], list[str]]:
    if not path.exists():
        return [], []
    source = path.read_text(encoding="utf-8")
    match = re.search(r"window\.SHORE_GALLERIES\s*=\s*(\[.*\])\s*;?\s*$", source, re.S)
    if not match:
        return [], []
    galleries = json.loads(match.group(1))
    urls = [url for gallery in galleries for url in gallery.get("images", [])]
    return galleries, urls


def media_filename(key: str, selected_url: str) -> str | None:
    parsed = urlsplit(selected_url)
    extension = Path(parsed.path).suffix.lower()
    if extension in IMAGE_EXTENSIONS:
        output_extension = ".webp"
    elif extension in COPY_EXTENSIONS:
        output_extension = extension
    else:
        return None
    stem = Path(unquote(parsed.path)).stem
    stem = re.sub(r"_orig$", "", stem, flags=re.I)
    stem = ascii_slug(stem, "asset")[:72]
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
    return f"{stem}-{digest}{output_extension}"


def media_plan(source_inventory: dict, runsignup_inventory: dict, gallery_urls: list[str]) -> dict[str, dict]:
    grouped: dict[str, set[str]] = {}
    for page in source_inventory["pages"]:
        for url in page.get("media", []):
            grouped.setdefault(logical_media_key(url), set()).add(url)
        for url in page.get("links", []):
            if Path(urlsplit(url).path).suffix.lower() in COPY_EXTENSIONS:
                grouped.setdefault(logical_media_key(url), set()).add(url)
    for registration in runsignup_inventory.get("registrations", []):
        for url in registration.get("media", []):
            grouped.setdefault(logical_media_key(url), set()).add(url)
    for url in gallery_urls:
        if urlsplit(url).scheme not in {"http", "https"}:
            continue
        grouped.setdefault(logical_media_key(url), set()).add(url)

    plan: dict[str, dict] = {}
    used_names: set[str] = set()
    for key, variants in sorted(grouped.items()):
        selected = select_media_variant(sorted(variants))
        host = urlsplit(selected).netloc.lower().removeprefix("www.")
        if host in BLOCKED_HOSTS | EXTERNAL_MEDIA_HOSTS or "youtube.com" in host or "youtu.be" in host:
            continue
        filename = media_filename(key, selected)
        if not filename:
            continue
        if filename in used_names:
            stem = Path(filename).stem
            filename = f"{stem}-{hashlib.sha1(selected.encode('utf-8')).hexdigest()[:6]}{Path(filename).suffix}"
        used_names.add(filename)
        plan[key] = {
            "selected_url": selected,
            "variants": sorted(variants),
            "relative_path": f"assets/archive/{filename}",
        }
    return plan


def download_asset(item: dict, project_root: Path, temp_dir: Path) -> dict:
    url = item["selected_url"]
    download_url = MEDIA_DOWNLOAD_OVERRIDES.get(url, url)
    if url in KNOWN_UNAVAILABLE_URLS:
        return {**item, "status": "failed", "size": 0, "error": "Source file is no longer available"}
    destination = project_root / item["relative_path"]
    if destination.exists() and destination.stat().st_size > 0:
        return {**item, "status": "existing", "size": destination.stat().st_size}
    destination.parent.mkdir(parents=True, exist_ok=True)
    extension = Path(urlsplit(url).path).suffix.lower()
    temporary = temp_dir / f"{hashlib.sha1(url.encode('utf-8')).hexdigest()}{extension}"
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = session().get(download_url, timeout=60, allow_redirects=True, stream=True)
            response.raise_for_status()
            with temporary.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        handle.write(chunk)
            if extension in IMAGE_EXTENSIONS:
                quality = "84" if extension == ".png" else "78"
                result = subprocess.run(
                    ["cwebp", "-quiet", "-mt", "-m", "4", "-q", quality, str(temporary), "-o", str(destination)],
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                if result.returncode != 0:
                    raise RuntimeError(result.stderr.strip() or "cwebp conversion failed")
            else:
                shutil.copyfile(temporary, destination)
            temporary.unlink(missing_ok=True)
            return {**item, "status": "downloaded", "size": destination.stat().st_size}
        except (requests.RequestException, OSError, RuntimeError, subprocess.SubprocessError) as error:
            last_error = error
            temporary.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            if attempt < 2:
                time.sleep(0.75 * (attempt + 1))
    return {**item, "status": "failed", "size": 0, "error": str(last_error)}


def download_media(plan: dict[str, dict], project_root: Path, workers: int) -> tuple[dict[str, str], list[dict]]:
    results: list[dict] = []
    temporary_root = Path(tempfile.mkdtemp(prefix="shoreac-media-"))
    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(download_asset, item, project_root, temporary_root): key
                for key, item in plan.items()
            }
            for index, future in enumerate(as_completed(futures), start=1):
                key = futures[future]
                result = future.result()
                result["key"] = key
                results.append(result)
                if index % 100 == 0 or index == len(futures):
                    print(f"Imported {index}/{len(futures)} media assets", flush=True)
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)

    media_map = {
        result["key"]: result["relative_path"]
        for result in results
        if result["status"] in {"downloaded", "existing"}
    }
    return media_map, results


def deduplicate_media(media_map: dict[str, str], project_root: Path) -> tuple[dict[str, str], int]:
    hashes: dict[tuple[str, str], str] = {}
    replacements: dict[str, str] = {}
    removed = 0
    for relative_path in sorted(set(media_map.values())):
        path = project_root / relative_path
        if not path.exists():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        identity = (path.suffix.lower(), digest)
        if identity in hashes:
            replacements[relative_path] = hashes[identity]
            path.unlink()
            removed += 1
        else:
            hashes[identity] = relative_path
    updated = {key: replacements.get(path, path) for key, path in media_map.items()}
    return updated, removed


def rewrite_reference(
    value: str,
    base_url: str,
    page_map: dict[str, str],
    media_map: dict[str, str],
    asset_prefix: str = "../",
) -> str:
    value = value.strip()
    if not value or value.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return value
    absolute = urljoin(base_url, value)
    clean, fragment = urldefrag(absolute)
    if clean in KNOWN_UNAVAILABLE_URLS:
        return "../unavailable.html"
    media_path = media_map.get(logical_media_key(clean))
    if media_path:
        return f"{asset_prefix}{media_path}" + (f"#{fragment}" if fragment else "")

    parsed = urlsplit(clean)
    host = parsed.netloc.lower().removeprefix("www.")
    if host == "shoreac.org":
        extension = Path(parsed.path).suffix.lower()
        if parsed.path.startswith("/uploads/") or extension in IMAGE_EXTENSIONS | COPY_EXTENSIONS:
            return "../unavailable.html"
        canonical = canonical_page_url(clean)
        filename = page_map.get(canonical)
        if filename:
            return filename + (f"#{fragment}" if fragment else "")
        alias_match = re.search(r"/1/post/\d{4}/\d{2}/([^/]+?)(?:\.html)?$", parsed.path)
        if alias_match:
            alias = canonical_page_url(f"https://www.shoreac.org/shore-ac-news/{alias_match.group(1)}")
            filename = page_map.get(alias)
            if filename:
                return filename + (f"#{fragment}" if fragment else "")
        if parsed.path in {"", "/", "/index.html"}:
            return "../index.html"
        if parsed.path.rstrip("/") in {"/shore-ac-news", "/shore-ac-news.html"}:
            return "../news.html"
        return "../archive.html"
    return absolute


def safe_style(value: str, base_url: str, media_map: dict[str, str], asset_prefix: str) -> str:
    value = re.sub(
        r"(?i)(?:^|;)\s*(?:position\s*:\s*fixed|z-index\s*:[^;]+|left\s*:[^;]+|right\s*:[^;]+)\s*;?",
        ";",
        value,
    )

    def replace(match: re.Match) -> str:
        original = match.group(1)
        absolute = clean_absolute_url(original, base_url)
        media_path = media_map.get(logical_media_key(absolute))
        return f"url('{asset_prefix}{media_path}')" if media_path else match.group(0)

    return re.sub(r"url\(['\"]?([^'\")]+)", replace, value)


def sanitize_fragment(
    element,
    base_url: str,
    page_map: dict[str, str],
    media_map: dict[str, str],
    asset_prefix: str = "../",
) -> str:
    fragment = BeautifulSoup(str(element), "html.parser")
    root = fragment.select_one("#wsite-content") or fragment.select_one("#mainContent") or fragment
    for node in root.select("script, style, noscript, link[rel='stylesheet']"):
        node.decompose()
    for comment in root.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()
    for node in root.select(".blog-social, .blog-social-item, .wsite-share-buttons"):
        node.decompose()
    for node in root.select(".wsite-spacer"):
        node.decompose()

    for tag in root.find_all(True):
        for attribute in list(tag.attrs):
            if attribute.lower().startswith("on") or attribute in {"contenteditable", "draggable"}:
                del tag.attrs[attribute]
        if tag.has_attr("style"):
            tag["style"] = safe_style(str(tag["style"]), base_url, media_map, asset_prefix)
        if tag.name == "a" and tag.get("href"):
            tag["href"] = rewrite_reference(tag["href"], base_url, page_map, media_map, asset_prefix)
            if urlsplit(tag["href"]).scheme in {"http", "https"}:
                tag["rel"] = "noopener noreferrer"
            else:
                tag.attrs.pop("target", None)
        if tag.name in {"img", "iframe", "video", "source", "audio"}:
            for attribute in ("src", "data-src", "data-image", "poster"):
                if tag.get(attribute):
                    rewritten = rewrite_reference(tag[attribute], base_url, page_map, media_map, asset_prefix)
                    if attribute == "src" or not tag.get("src"):
                        tag["src"] = rewritten
                    if attribute != "src":
                        del tag.attrs[attribute]
            tag.attrs.pop("srcset", None)
            tag.attrs.pop("data-srcset", None)
        if tag.name == "img":
            tag["loading"] = "lazy"
            tag["decoding"] = "async"
            if not tag.get("alt") or tag.get("alt") == "Picture":
                tag["alt"] = "Shore A.C. archive image"
        if tag.name == "iframe":
            source = tag.get("src", "")
            if "youtube.com" not in source and "youtu.be" not in source:
                tag.decompose()
                continue
            tag["loading"] = "lazy"
            tag["title"] = tag.get("title") or "Shore A.C. archive video"
            tag["allowfullscreen"] = ""
        if tag.name == "form":
            tag.attrs.pop("action", None)
            tag.attrs.pop("method", None)
            tag["class"] = list(tag.get("class", [])) + ["archive-static-form"]
            tag["aria-disabled"] = "true"
        if tag.name in {"input", "button", "select", "textarea"}:
            tag["disabled"] = ""

    for table in list(root.find_all("table")):
        if table.parent and "archive-table-wrap" in table.parent.get("class", []):
            continue
        wrapper = fragment.new_tag("div", attrs={"class": "archive-table-wrap"})
        table.wrap(wrapper)

    if getattr(root, "name", None) in {"div", "main"}:
        return root.decode_contents()
    return str(root)


def format_event_date(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    hour = parsed.strftime("%I").lstrip("0") or "12"
    return f"{parsed.strftime('%A, %B')} {parsed.day}, {parsed.year} at {hour}:{parsed.strftime('%M %p')}"


def format_location(schema: dict) -> str:
    location = schema.get("location", {}) if isinstance(schema, dict) else {}
    if isinstance(location, str):
        return location
    address = location.get("address", {}) if isinstance(location, dict) else {}
    if isinstance(address, str):
        return address
    parts = [
        location.get("name", "") if isinstance(location, dict) else "",
        address.get("streetAddress", "") if isinstance(address, dict) else "",
        " ".join(
            part
            for part in (
                address.get("addressLocality", "") if isinstance(address, dict) else "",
                address.get("addressRegion", "") if isinstance(address, dict) else "",
                address.get("postalCode", "") if isinstance(address, dict) else "",
            )
            if part
        ),
    ]
    return ", ".join(part for part in parts if part)


def registration_markup(registration: dict, raw_dir: Path, page_map: dict, media_map: dict) -> str:
    raw_path = raw_dir / registration["raw_file"]
    soup = BeautifulSoup(raw_path.read_bytes(), "html.parser")
    main = soup.select_one("#mainContent") or soup.select_one("main")
    if main is None:
        return ""
    content = sanitize_fragment(main, registration["final_url"], page_map, media_map)
    return f"""
    <section class="section registration-section" id="registration-details">
      <div class="wrap">
        <div class="section-head">
          <span class="eyebrow">Current registration information</span>
          <h2>{escape(registration['title'])}</h2>
        </div>
        <div class="runsignup-content">{content}</div>
      </div>
    </section>"""


def page_template(page: dict, source_content: str, registration: dict | None, registration_html: str) -> str:
    title = page["title"]
    category = CATEGORY_LABELS.get(page["category"], "Club Archive")
    hub = CATEGORY_HUBS.get(page["category"], "../archive.html")
    updated = page.get("lastmod", "")[:10]
    action = ""
    event_meta = ""
    if registration:
        schema = registration.get("schema", {})
        date = format_event_date(schema.get("startDate", ""))
        location = format_location(schema)
        if date or location:
            event_meta = (
                '<dl class="event-facts">'
                + (f"<div><dt>Date</dt><dd>{escape(date)}</dd></div>" if date else "")
                + (f"<div><dt>Location</dt><dd>{escape(location)}</dd></div>" if location else "")
                + "</dl>"
            )
        action = f'<a class="button primary" href="{escape(registration["final_url"], quote=True)}">Register on RunSignup</a>'
    metadata = f"Source updated {escape(updated)}" if updated else "Shore A.C. archive"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" type="image/png" href="../assets/shore-ac.png">
  <title>{escape(title)} | Shore Athletic Club</title>
  <meta name="description" content="Archived Shore Athletic Club information for {escape(title)}.">
  <link rel="stylesheet" href="../interior.css?v=20260711-7">
  <link rel="stylesheet" href="../archive.css?v=20260711-7">
</head>
<body>
  <header class="site-header">
    <div class="header-inner">
      <a class="brand" href="../index.html"><img src="../assets/shore-ac.png" alt="Shore A.C."><span>Shore Athletic Club</span></a>
      <nav class="nav" aria-label="Primary">
        <a class="button light" href="../index.html">Home</a>
        <a class="button secondary" href="../events.html">Races</a>
        <a class="button primary" href="https://runsignup.com/MemberOrg/ShoreAthleticClub/Register">Join</a>
      </nav>
    </div>
  </header>
  <main>
    <section class="archive-hero">
      <div class="wrap">
        <a class="archive-back" href="{hub}">Back to {escape(category)}</a>
        <span class="eyebrow">{escape(category)}</span>
        <h1>{escape(title)}</h1>
        <p>{metadata} &middot; {page['word_count']:,} words</p>
        {event_meta}
        <div class="button-row">
          {action}
          <a class="button secondary" href="../archive.html">Search full archive</a>
        </div>
      </div>
    </section>
    <section class="section white">
      <div class="wrap archive-shell">
        <article class="archive-content">{source_content}</article>
      </div>
    </section>
    {registration_html}
  </main>
  <footer class="site-footer">
    <div class="wrap footer-inner">
      <div><strong>Shore Athletic Club</strong><br>P.O. Box 74, Belford, NJ 07718-9998</div>
      <nav class="footer-links" aria-label="Footer links">
        <a href="../index.html">Home</a><a href="../events.html">Races</a><a href="../archive.html">Archive</a><a href="../contact.html">Contact</a>
      </nav>
    </div>
  </footer>
  <script src="../site-nav.js?v=20260711-7"></script>
</body>
</html>
"""


def standalone_registration_page(registration: dict, raw_dir: Path, page_map: dict, media_map: dict) -> tuple[str, str]:
    filename = f"{ascii_slug(registration['id'])}.html"
    pseudo_page = {
        "title": registration["title"],
        "category": "page",
        "lastmod": registration.get("generated_at", ""),
        "word_count": registration["word_count"],
    }
    raw_path = raw_dir / registration["raw_file"]
    soup = BeautifulSoup(raw_path.read_bytes(), "html.parser")
    main = soup.select_one("#mainContent") or soup.select_one("main")
    content = sanitize_fragment(main, registration["final_url"], page_map, media_map) if main else ""
    return filename, page_template(pseudo_page, content, registration, "")


def rewrite_galleries(galleries: list[dict], media_map: dict[str, str], output_path: Path) -> tuple[int, int]:
    total = 0
    missing = 0
    for gallery in galleries:
        images: list[str] = []
        seen: set[str] = set()
        for url in gallery.get("images", []):
            if urlsplit(url).scheme not in {"http", "https"}:
                if (PROJECT_ROOT / url).exists() and url not in seen:
                    seen.add(url)
                    images.append(url)
                continue
            key = logical_media_key(url)
            relative = media_map.get(key)
            if not relative:
                missing += 1
                continue
            if relative in seen:
                continue
            seen.add(relative)
            images.append(relative)
        gallery["images"] = images
        total += len(images)
    output_path.write_text(
        "window.SHORE_GALLERIES = " + json.dumps(galleries, indent=2, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    return total, missing


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", default="/tmp/shoreac-crawl/inventory.json")
    parser.add_argument("--runsignup", default="/tmp/shoreac-crawl/runsignup/inventory.json")
    parser.add_argument("--source-raw", default="/tmp/shoreac-crawl/raw")
    parser.add_argument("--runsignup-raw", default="/tmp/shoreac-crawl/runsignup/raw")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--skip-media", action="store_true")
    arguments = parser.parse_args()

    source_inventory = json.loads(Path(arguments.inventory).read_text(encoding="utf-8"))
    runsignup_inventory = json.loads(Path(arguments.runsignup).read_text(encoding="utf-8"))
    pages = source_inventory["pages"]
    page_map = build_page_map(pages)
    galleries, gallery_urls = parse_gallery_urls(PROJECT_ROOT / "gallery-data.js")
    plan = media_plan(source_inventory, runsignup_inventory, gallery_urls)

    if arguments.skip_media:
        media_map = {
            key: item["relative_path"]
            for key, item in plan.items()
            if (PROJECT_ROOT / item["relative_path"]).exists()
        }
        media_results: list[dict] = []
        deduplicated = 0
    else:
        media_map, media_results = download_media(plan, PROJECT_ROOT, arguments.workers)
        media_map, deduplicated = deduplicate_media(media_map, PROJECT_ROOT)

    archive_dir = PROJECT_ROOT / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    source_raw_dir = Path(arguments.source_raw)
    runsignup_raw_dir = Path(arguments.runsignup_raw)
    registrations = runsignup_inventory.get("registrations", [])
    registration_by_source = {
        registration["source_page"]: registration
        for registration in registrations
        if registration["kind"] in {"race", "membership"}
    }

    index_entries: list[dict] = []
    report_pages: list[dict] = []
    for page in pages:
        raw_path = source_raw_dir / page["raw_file"]
        soup = BeautifulSoup(raw_path.read_bytes(), "html.parser")
        content_node = soup.select_one("#wsite-content") or soup.select_one("main") or soup.body
        if content_node is None:
            continue
        source_content = sanitize_fragment(content_node, page["final_url"], page_map, media_map)
        source_name = Path(urlsplit(page["url"]).path).name
        registration = registration_by_source.get(source_name)
        registration_html = (
            registration_markup(registration, runsignup_raw_dir, page_map, media_map)
            if registration
            else ""
        )
        output = archive_dir / page["archive_file"]
        output.write_text(page_template(page, source_content, registration, registration_html), encoding="utf-8")
        excerpt = re.sub(r"\s+", " ", page["text"]).strip()[:240]
        index_entries.append(
            {
                "title": page["title"],
                "category": page["category"],
                "categoryLabel": CATEGORY_LABELS.get(page["category"], "Club Archive"),
                "url": f"archive/{page['archive_file']}",
                "lastmod": page.get("lastmod", ""),
                "year": page.get("lastmod", "")[:4],
                "excerpt": excerpt,
            }
        )
        report_pages.append(
            {
                "source_url": page["url"],
                "local_url": f"archive/{page['archive_file']}",
                "text_sha256": page["text_sha256"],
                "word_count": page["word_count"],
            }
        )

    for registration in registrations:
        if registration["kind"] != "program":
            continue
        filename, markup = standalone_registration_page(registration, runsignup_raw_dir, page_map, media_map)
        (archive_dir / filename).write_text(markup, encoding="utf-8")
        index_entries.append(
            {
                "title": registration["title"],
                "category": "page",
                "categoryLabel": "Programs",
                "url": f"archive/{filename}",
                "lastmod": runsignup_inventory.get("generated_at", ""),
                "year": runsignup_inventory.get("generated_at", "")[:4],
                "excerpt": re.sub(r"\s+", " ", registration["text"]).strip()[:240],
            }
        )

    index_entries.sort(key=lambda entry: (entry["lastmod"], entry["title"]), reverse=True)
    (PROJECT_ROOT / "archive-index.js").write_text(
        "window.SHORE_ARCHIVE = " + json.dumps(index_entries, indent=2, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    if arguments.skip_media:
        gallery_count = sum(len(gallery.get("images", [])) for gallery in galleries)
        gallery_missing = 0
    else:
        gallery_count, gallery_missing = rewrite_galleries(galleries, media_map, PROJECT_ROOT / "gallery-data.js")

    failed_media = [result for result in media_results if result.get("status") == "failed"]
    imported_size = sum(
        path.stat().st_size
        for path in (PROJECT_ROOT / "assets" / "archive").glob("*")
        if path.is_file()
    )
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": SOURCE_ROOT,
        "source_pages": len(pages),
        "local_archive_pages": len(report_pages),
        "runsignup_pages_imported": len(registrations),
        "runsignup_failures": runsignup_inventory.get("failures", []),
        "media_planned": len(plan) + len(EXTERNAL_MEDIA_ASSETS),
        "media_planned_local": len(plan),
        "media_imported": len(set(media_map.values())),
        "media_failed": failed_media,
        "media_external": EXTERNAL_MEDIA_ASSETS,
        "media_deduplicated": deduplicated,
        "media_bytes": imported_size,
        "gallery_images": gallery_count,
        "gallery_missing_variants": gallery_missing,
        "pages": report_pages,
    }
    (PROJECT_ROOT / "migration-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(
        json.dumps(
            {key: value for key, value in report.items() if key not in {"pages", "media_failed"}},
            indent=2,
        )
    )
    if failed_media:
        print(f"Media failures: {len(failed_media)} (see migration-report.json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
