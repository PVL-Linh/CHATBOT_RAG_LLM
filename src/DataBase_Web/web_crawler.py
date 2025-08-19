"""
Tiximax.net crawler (enhanced for full "All posts / News / Categories / Tags" coverage)
- Discovers URLs via sitemap.xml, smart seeds (news/blog/archive paths), and in-site crawling
- Follows pagination (/page/N, ?paged=, rel=next) and all internal links
- Respects robots.txt
- Extracts title, meta description, publish time, author, h1s, and main text
- Saves to CSV and JSONL

Usage:
    pip install -U requests beautifulsoup4 lxml
    python tiximax_crawler_full.py --base https://tiximax.net/ --out tiximax_full
"""

import argparse
import concurrent.futures
import csv
import json
import re
import time
from dataclasses import dataclass, asdict
from html import unescape
from typing import Iterable, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse, urldefrag

import pandas as pd
import sys
import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
import urllib.robotparser as robotparser

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TiximaxCrawler/1.1; +https://tiximax.net)"
}

# Common paths for "All posts", "News", "Categories", etc.
COMMON_SEEDS = [
    "/", "/news/", "/tin-tuc/", "/bai-viet/", "/tat-ca-bai-viet/",
    "/blog/", "/blogs/", "/category/", "/chuyen-muc/", "/tags/", "/tag/", "/archive/"
]

PAGINATION_PATTERNS = [
    re.compile(r"/page/\d+/?$", re.I),
    re.compile(r"[?&](?:page|paged|pagenum|pagination)=\d+", re.I),
]

@dataclass
class PageData:
    url: str
    status: int
    title: str
    meta_description: str
    published_time: str
    author: str
    h1: str
    text: str

def normalize_url(u: str) -> str:
    u, _ = urldefrag(u)
    # remove default ports
    parsed = urlparse(u)
    if parsed.path != "/" and u.endswith("/"):
        u = u[:-1]
    if parsed.netloc.endswith(":80"):
        u = u.replace(":80", "")
    if parsed.netloc.endswith(":443"):
        u = u.replace(":443", "")
    return u

def same_domain(u: str, base_netloc: str) -> bool:
    return urlparse(u).netloc == base_netloc

def load_robots(base: str) -> robotparser.RobotFileParser:
    rp = robotparser.RobotFileParser()
    robots_url = urljoin(base, "/robots.txt")
    try:
        rp.set_url(robots_url)
        rp.read()
    except Exception:
        pass
    return rp

def get_sitemap_urls(base: str) -> List[str]:
    sitemap_url = urljoin(base, "/sitemap.xml")
    urls: List[str] = []
    try:
        resp = requests.get(sitemap_url, headers=DEFAULT_HEADERS, timeout=20)
        if resp.status_code != 200 or not resp.text.strip():
            return urls
        root = ET.fromstring(resp.content)
        ns = ""
        if root.tag.startswith("{"):
            ns = root.tag.split("}")[0].strip("{")
        def tag(name): return f"{{{ns}}}{name}" if ns else name

        if root.tag.endswith("sitemapindex"):
            for sm in root.findall(tag("sitemap")):
                loc_el = sm.find(tag("loc"))
                if loc_el is not None and loc_el.text:
                    r = requests.get(loc_el.text.strip(), headers=DEFAULT_HEADERS, timeout=20)
                    if r.status_code == 200:
                        rroot = ET.fromstring(r.content)
                        for url_el in rroot.findall(f".//{tag('url')}"):
                            loc = url_el.find(tag("loc"))
                            if loc is not None and loc.text:
                                urls.append(loc.text.strip())
        else:
            for url_el in root.findall(f".//{tag('url')}"):
                loc = url_el.find(tag("loc"))
                if loc is not None and loc.text:
                    urls.append(loc.text.strip())
    except Exception:
        pass
    base_netloc = urlparse(base).netloc
    urls = [normalize_url(u) for u in urls if urlparse(u).netloc == base_netloc]
    return sorted(set(urls))

def extract_main_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    for tag in soup.find_all(["nav", "footer", "header", "aside"]):
        tag.decompose()

    candidates = []
    for sel in ["article", "[role=main]", ".entry-content", ".post-content", ".single-content", ".content", ".post", "#content", ".article-body"]:
        for c in soup.select(sel):
            text = c.get_text(separator="\n", strip=True)
            if text and len(text) > 200:
                candidates.append(text)
    if candidates:
        candidates.sort(key=len, reverse=True)
        return candidates[0]
    body = soup.body.get_text(separator="\n", strip=True) if soup.body else soup.get_text(separator="\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", body)

def extract_metadata(html: str, url: str) -> PageData:
    soup = BeautifulSoup(html, "lxml")
    title = unescape(soup.title.get_text(strip=True)) if soup.title else ""
    meta_desc = ""
    published_time = ""
    author = ""
    h1_text = ""

    md = soup.find("meta", attrs={"name": "description"})
    if md and md.get("content"):
        meta_desc = md["content"].strip()
    if not meta_desc:
        ogd = soup.find("meta", property="og:description")
        if ogd and ogd.get("content"):
            meta_desc = ogd["content"].strip()

    for prop in ["article:published_time", "og:updated_time", "article:modified_time", "date", "publish_date"]:
        m = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        if m and m.get("content"):
            published_time = m["content"].strip()
            break

    for prop in ["author", "article:author"]:
        m = soup.find("meta", attrs={"name": prop}) or soup.find("meta", attrs={"property": prop})
        if m and m.get("content"):
            author = m["content"].strip()
            break

    h1 = soup.find("h1")
    if h1:
        h1_text = h1.get_text(strip=True)

    text = extract_main_text(soup)
    return PageData(
        url=url, status=200, title=title, meta_description=meta_desc,
        published_time=published_time, author=author, h1=h1_text, text=text
    )

def discover_links(html: str, base_url: str, base_netloc: str) -> List[str]:
    soup = BeautifulSoup(html, "lxml")
    out = []

    # All anchor links
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        u = urljoin(base_url, href)
        if same_domain(u, base_netloc):
            out.append(u)

    # rel="next" pagination
    for link in soup.find_all("link", rel=True, href=True):
        rels = " ".join(link.get("rel") or [])
        if "next" in rels.lower():
            u = urljoin(base_url, link["href"].strip())
            if same_domain(u, base_netloc):
                out.append(u)

    # Heuristic pagination in-page
    for a in soup.select("a[href*='page'], a[href*='paged'], .pagination a[href], .page-numbers a[href]"):
        href = a.get("href")
        if href:
            u = urljoin(base_url, href.strip())
            if same_domain(u, base_netloc):
                out.append(u)

    # Deduplicate, keep normalized
    return sorted(set(normalize_url(u) for u in out))

def looks_like_listing(url: str) -> bool:
    p = urlparse(url).path.lower()
    return any(seg in p for seg in ["news", "tin-tuc", "bai-viet", "blog", "category", "chuyen-muc", "archive", "tag", "/page/"]) or any(pt.search(url) for pt in PAGINATION_PATTERNS)

def fetch_and_parse(url: str, session: requests.Session, rp: robotparser.RobotFileParser, base_netloc: str, delay: float) -> Tuple[str, Optional[PageData], List[str], int, str]:
    """Return (url, PageData|None, outlinks, status, html_snippet)"""
    if not rp.can_fetch(DEFAULT_HEADERS["User-Agent"], url):
        return url, None, [], 0, ""
    try:
        r = session.get(url, headers=DEFAULT_HEADERS, timeout=25)
        status = r.status_code
        ctype = r.headers.get("Content-Type", "")
        html = r.text if "text/html" in ctype else ""
        outlinks = discover_links(html, url, base_netloc) if html else []
        if status == 200 and html:
            pd = extract_metadata(html, url)
            pd.status = status
        else:
            pd = PageData(url=url, status=status, title="", meta_description="", published_time="", author="", h1="", text="")
        time.sleep(delay)
        return url, pd, outlinks, status, html[:5000] if html else ""
    except Exception:
        return url, None, [], 0, ""

def crawl(base: str, out_prefix: str, max_pages: int = 10000, workers: int = 12, delay: float = 0.3, use_sitemap_first: bool = True):
    base = base.strip()
    if not base.endswith("/"):
        base += "/"
    base_netloc = urlparse(base).netloc

    rp = load_robots(base)
    session = requests.Session()

    # Seed URLs: sitemap + smart seeds
    seeds: Set[str] = set()
    if use_sitemap_first:
        print("[*] Fetching sitemap URLs...")
        seeds.update(get_sitemap_urls(base))
    for path in COMMON_SEEDS:
        seeds.add(normalize_url(urljoin(base, path)))

    if not seeds:
        seeds.add(normalize_url(base))

    visited: Set[str] = set()
    frontier: List[str] = list(sorted(seeds))
    all_seen: Set[str] = set(frontier)

    results: List[PageData] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        while frontier and len(visited) < max_pages:
            # schedule a batch
            batch = []
            while frontier and len(batch) < workers * 3:
                u = frontier.pop(0)
                if u in visited:
                    continue
                if urlparse(u).netloc != base_netloc:
                    continue
                visited.add(u)
                batch.append(u)

            futures = {executor.submit(fetch_and_parse, url, session, rp, base_netloc, delay): url for url in batch}

            for future in concurrent.futures.as_completed(futures):
                url = futures[future]
                try:
                    fetched_url, pdata, outlinks, status, _html = future.result()
                except Exception:
                    continue

                if pdata is not None:
                    results.append(pdata)

                # Always queue discovered links on same domain
                for link in outlinks:
                    if urlparse(link).netloc != base_netloc:
                        continue
                    if link in visited or link in all_seen:
                        continue
                    all_seen.add(link)
                    frontier.append(link)

                if len(visited) >= max_pages:
                    break

    # Save outputs
    csv_path = f"src/Data/{out_prefix}.csv"
    jsonl_path = f"{out_prefix}.jsonl"
    urls_path = f"{out_prefix}_urls.txt"
    txt_path = f"src/Data/{out_prefix}.txt"  # Thêm file txt ghép thông tin từ CSV

    # Lưu CSV
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["url", "status", "title", "meta_description", "published_time", "author", "h1", "text"])
        for pd in results:
            writer.writerow([pd.url, pd.status, pd.title, pd.meta_description, pd.published_time, pd.author, pd.h1, pd.text])

    # Lưu JSONL
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for pd in results:
            f.write(json.dumps(asdict(pd), ensure_ascii=False) + "\n")

    # Lưu danh sách URL
    with open(urls_path, "w", encoding="utf-8") as f:
        for u in sorted(all_seen):
            f.write(u + "\n")

    # Lưu TXT chứa toàn bộ thông tin CSV, cách nhau bằng dấu tab
    with open(txt_path, "w", encoding="utf-8") as f:
        for pd in results:
            # Ghép toàn bộ dữ liệu thành 1 dòng
            row = [pd.url, pd.status, pd.title, pd.meta_description, pd.published_time, pd.author, pd.h1, pd.text]
            # Chuyển về string, bỏ xuống dòng trong text
            line = "\t".join(str(x).replace("\n", " ").strip() for x in row)
            f.write(line + "\n")

    print(f"[*] Done. Crawled {len(visited)} pages, saved {len(results)} records.")
    print(f"    CSV:   {csv_path}")
    print(f"    JSONL: {jsonl_path}")
    print(f"    URLs:  {urls_path}")
    print(f"    TXT:   {txt_path}")





def main():
    ap = argparse.ArgumentParser(description="Crawl tiximax.net (full coverage for posts/news/categories/tags).")
    ap.add_argument("--base", type=str, default="https://tiximax.net/", help="Base site URL")
    ap.add_argument("--out", type=str, default="tiximax_full", help="Output file prefix (without extension)")
    ap.add_argument("--max-pages", type=int, default=10000, help="Max number of pages to fetch")
    ap.add_argument("--workers", type=int, default=12, help="Number of parallel workers")
    ap.add_argument("--delay", type=float, default=0.3, help="Delay between requests per thread (seconds)")
    ap.add_argument("--no-sitemap", action="store_true", help="Skip sitemap.xml discovery")
    args = ap.parse_args()

    crawl(
        base=args.base,
        out_prefix=args.out,
        max_pages=args.max_pages,
        workers=args.workers,
        delay=args.delay,
        use_sitemap_first=not args.no_sitemap
    )

if __name__ == "__main__":
    main()
