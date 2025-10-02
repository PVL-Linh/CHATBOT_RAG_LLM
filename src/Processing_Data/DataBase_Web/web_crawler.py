
"""
Multi-site web crawler (single-file)
- Đọc sites.txt (mỗi dòng 1 URL gốc) HOẶC --base cho 1 site
- Tôn trọng robots.txt (+ đọc các dòng Sitemap:)
- Lấy sitemap: /sitemap.xml, /sitemap_index.xml, *.xml.gz, và sitemap trong robots
- Chuẩn hoá URL & domain (bỏ www., bỏ :80/:443, path gọn)
- Ưu tiên các trang listing (news/blog/category/tag/page)
- Politeness: limiter RPS toàn cục + delay per-thread
- Retry/backoff cho lỗi mạng
- Đánh dấu visited SAU khi fetch (để URL lỗi còn được retry)
- Ghi dần: mỗi trang 1 file .txt + index.csv/jsonl/urls.txt/all_text.txt

Cách dùng:
    python web_crawler.py --url-file sites.txt --out crawl_out --max-pages 10000 --workers 8 --rps 1.5 --delay 0.5
    python web_crawler.py --base https://tiximax.net/ --out crawl_out_one

Windows PowerShell:
    & E:\ChatAll\venv\Scripts\python.exe E:\ChatAll\src\DataBase_Web\web_crawler.py `
      --url-file E:\ChatAll\src\DataBase_Web\sites.txt `
      --out crawl_out --workers 8 --rps 1.0 --delay 0.5
"""

import argparse
import concurrent.futures as cf
import csv
import gzip
import io
import json
import os
import re
import time
from dataclasses import dataclass, asdict
from html import unescape
from time import perf_counter, sleep
from typing import List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
import urllib.robotparser as robotparser

# ---------- cấu hình ----------
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MultiSiteCrawler/1.3; +contact@example.com)"
}
COMMON_SEEDS = [
    "/", "/news/", "/tin-tuc/", "/bai-viet/", "/tat-ca-bai-viet/",
    "/blog/", "/blogs/", "/category/", "/chuyen-muc/", "/tags/", "/tag/", "/archive/"
]
PAGINATION_PATTERNS = [
    re.compile(r"/page/\d+/?$", re.I),
    re.compile(r"[?&](?:page|paged|pagenum|pagination)=\d+", re.I),
]

# ---------- tiện ích ----------
def _canon_host(host: str) -> str:
    host = (host or "").lower().strip()
    return host[4:] if host.startswith("www.") else host

def normalize_url(u: str) -> str:
    u, _ = urldefrag(u or "")
    p = urlparse(u)
    scheme = (p.scheme or "https").lower()
    netloc = _canon_host(p.netloc.replace(":80", "").replace(":443", ""))
    path = p.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    query = p.query
    return f"{scheme}://{netloc}{path}" + (f"?{query}" if query else "")

def same_domain(u: str, base_netloc: str) -> bool:
    return _canon_host(urlparse(u).netloc) == _canon_host(base_netloc)

def slugify_path(u: str) -> str:
    p = urlparse(u).path or "/"
    core = "home" if p == "/" else p.lstrip("/").replace("/", "--")
    core = re.sub(r"[^a-zA-Z0-9_.\-]+", "_", core)
    return core[:180] or "page"

def ensure_dir(p: str):
    os.makedirs(p, exist_ok=True)

# ---------- polite limiter ----------
class RateLimiter:
    """Giới hạn RPS toàn cục (token-bucket đơn giản)."""
    def __init__(self, rps=1.5):
        self.min_interval = 1.0 / max(0.1, rps)
        self._last = 0.0
    def wait(self):
        now = perf_counter()
        delta = now - self._last
        if delta < self.min_interval:
            sleep(self.min_interval - delta)
        self._last = perf_counter()

# ---------- HTTP session ----------
def build_session(workers: int) -> requests.Session:
    s = requests.Session()
    try:
        from requests.adapters import HTTPAdapter
        a = HTTPAdapter(pool_connections=workers*2, pool_maxsize=workers*4, max_retries=0)
        s.mount("http://", a)
        s.mount("https://", a)
    except Exception:
        pass
    return s

# ---------- dữ liệu ----------
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
    file_path: str = ""

# ---------- robots & sitemap ----------
def load_robots(base: str) -> Tuple[robotparser.RobotFileParser, List[str]]:
    rp = robotparser.RobotFileParser()
    robots_url = urljoin(base, "/robots.txt")
    sitemaps = []
    try:
        resp = requests.get(robots_url, headers=DEFAULT_HEADERS, timeout=15)
        if resp.status_code == 200 and resp.text:
            rp.parse(resp.text.splitlines())
            for line in resp.text.splitlines():
                if line.lower().startswith("sitemap:"):
                    sm = line.split(":", 1)[1].strip()
                    if sm:
                        sitemaps.append(sm)
        else:
            rp.set_url(robots_url)
            rp.read()
    except Exception:
        pass
    return rp, sitemaps

def _parse_sitemap_xml(content: bytes) -> Tuple[List[str], List[str]]:
    """Trả về (urls, sitemap_children)."""
    urls, sitemaps = [], []
    root = ET.fromstring(content)
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0].strip("{")
    def tag(name): return f"{{{ns}}}{name}" if ns else name

    if root.tag.endswith("sitemapindex"):
        for sm in root.findall(tag("sitemap")):
            loc_el = sm.find(tag("loc"))
            if loc_el is not None and loc_el.text:
                sitemaps.append(loc_el.text.strip())
    else:
        for url_el in root.findall(f".//{tag('url')}"):
            loc = url_el.find(tag("loc"))
            if loc is not None and loc.text:
                urls.append(loc.text.strip())
    return urls, sitemaps

def fetch_sitemap_urls(base: str, extra_sitemaps: List[str]) -> List[str]:
    candidates = [
        urljoin(base, "/sitemap.xml"),
        urljoin(base, "/sitemap_index.xml"),
        *extra_sitemaps
    ]
    # thêm .gz
    for c in list(candidates):
        if not c.endswith(".gz"):
            candidates.append(c + ".gz")

    urls: List[str] = []
    queue = candidates[:]
    seen = set(queue)

    while queue:
        sm_url = queue.pop(0)
        try:
            r = requests.get(sm_url, headers=DEFAULT_HEADERS, timeout=20)
            if r.status_code != 200 or not r.content:
                continue
            content = r.content
            if sm_url.endswith(".gz"):
                try:
                    content = gzip.decompress(content)
                except Exception:
                    continue
            ulist, children = _parse_sitemap_xml(content)
            urls.extend(ulist)
            for ch in children:
                if ch not in seen:
                    seen.add(ch)
                    queue.append(ch)
        except Exception:
            continue

    base_netloc = urlparse(base).netloc
    urls = [normalize_url(u) for u in urls if same_domain(u, base_netloc)]
    return sorted(set(urls))

# ---------- trích xuất ----------
def extract_main_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    # ưu tiên vùng nội dung
    candidates = []
    for sel in ["article", "[role=main]", ".entry-content", ".post-content", ".single-content",
                ".content", ".post", "#content", ".article-body"]:
        for c in soup.select(sel):
            t = c.get_text(separator="\n", strip=True)
            if t and len(t) > 200:
                candidates.append(t)
    if candidates:
        candidates.sort(key=len, reverse=True)
        return candidates[0]
    # fallback: loại layout
    for tag in soup.find_all(["nav", "footer", "header", "aside"]):
        tag.decompose()
    body = soup.body.get_text(separator="\n", strip=True) if soup.body else soup.get_text(separator="\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", body)

def extract_metadata(html: str, url: str) -> PageData:
    soup = BeautifulSoup(html, "lxml")
    title = unescape(soup.title.get_text(strip=True)) if soup.title else ""
    meta_desc, published_time, author, h1_text = "", "", "", ""

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
            published_time = m["content"].strip(); break

    for prop in ["author", "article:author"]:
        m = soup.find("meta", attrs={"name": prop}) or soup.find("meta", attrs={"property": prop})
        if m and m.get("content"):
            author = m["content"].strip(); break

    h1 = soup.find("h1")
    if h1:
        h1_text = h1.get_text(strip=True)

    text = extract_main_text(soup)
    return PageData(
        url=url, status=200, title=title, meta_description=meta_desc,
        published_time=published_time, author=author, h1=h1_text, text=text, file_path=""
    )

def discover_links(html: str, base_url: str, base_netloc: str) -> List[str]:
    soup = BeautifulSoup(html, "lxml")
    out = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        u = urljoin(base_url, href)
        if same_domain(u, base_netloc):
            out.append(u)

    for link in soup.find_all("link", rel=True, href=True):
        rels = " ".join(link.get("rel") or [])
        if "next" in rels.lower():
            u = urljoin(base_url, link["href"].strip())
            if same_domain(u, base_netloc):
                out.append(u)

    for a in soup.select("a[href*='page'], a[href*='paged'], .pagination a[href], .page-numbers a[href]"):
        href = a.get("href")
        if href:
            u = urljoin(base_url, href.strip())
            if same_domain(u, base_netloc):
                out.append(u)

    return sorted(set(normalize_url(u) for u in out))

def looks_like_listing(url: str) -> bool:
    p = urlparse(url).path.lower()
    return any(seg in p for seg in
               ["news", "tin-tuc", "bai-viet", "blog", "category", "chuyen-muc", "archive", "tag", "/page/"]) \
           or any(pt.search(url) for pt in PAGINATION_PATTERNS)

# ---------- fetch ----------
def fetch_and_parse(url: str, session: requests.Session, rp: robotparser.RobotFileParser,
                    base_netloc: str, delay: float, limiter: RateLimiter) -> Tuple[str, Optional[PageData], List[str], int, str]:
    """Return: (url, PageData|None, outlinks, status, html_snippet)"""
    if not rp.can_fetch(DEFAULT_HEADERS["User-Agent"], url):
        return url, None, [], 0, ""
    tries, back = 3, 0.6
    for attempt in range(tries):
        try:
            limiter.wait()  # RPS toàn cục
            r = session.get(url, headers=DEFAULT_HEADERS, timeout=25)
            status = r.status_code
            ctype = r.headers.get("Content-Type", "") or ""
            html = r.text if "text/html" in ctype else ""
            outlinks = discover_links(html, url, base_netloc) if html else []
            if status == 200 and html:
                pd = extract_metadata(html, url)
                pd.status = status
            else:
                pd = PageData(url=url, status=status, title="", meta_description="",
                              published_time="", author="", h1="", text="")
            time.sleep(max(0.0, delay))  # lịch sự theo thread
            return url, pd, outlinks, status, html[:5000] if html else ""
        except requests.RequestException:
            if attempt < tries - 1:
                time.sleep(back); back *= 2
                continue
            return url, None, [], 0, ""

# ---------- lưu ----------
def save_page_text(site_dir: str, idx: int, url: str, text: str) -> str:
    pages_dir = os.path.join(site_dir, "pages")
    ensure_dir(pages_dir)
    slug = slugify_path(url)
    fname = f"{idx:06d}--{slug}.txt"
    fpath = os.path.join(pages_dir, fname)
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(text or "")
    return fpath

# ---------- crawl một site ----------
def crawl_site(base: str, out_root: str, max_pages: int, workers: int, delay: float, rps: float, use_sitemap_first: bool):
    base = base.strip()
    if not base.endswith("/"): base += "/"
    base = normalize_url(base)
    base_netloc = urlparse(base).netloc
    domain_dir = os.path.join("src", "Data", out_root, _canon_host(base_netloc))
    ensure_dir(domain_dir)
    ensure_dir(os.path.join(domain_dir, "pages"))

    rp, robots_sitemaps = load_robots(base)
    session = build_session(workers)
    limiter = RateLimiter(rps=rps)

    # seeds
    seeds: Set[str] = set()
    if use_sitemap_first:
        print("[*] Fetching sitemap URLs...")
        seeds.update(fetch_sitemap_urls(base, robots_sitemaps))
    for path in COMMON_SEEDS:
        seeds.add(normalize_url(urljoin(base, path)))
    if not seeds:
        seeds.add(normalize_url(base))

    visited: Set[str] = set()
    frontier: List[str] = list(sorted(seeds))
    all_seen: Set[str] = set(frontier)

    # outputs
    index_csv = os.path.join(domain_dir, "index.csv")
    index_jsonl = os.path.join(domain_dir, "index.jsonl")
    urls_txt = os.path.join(domain_dir, "urls.txt")
    all_text = os.path.join(domain_dir, "all_text.txt")

    f_csv  = open(index_csv, "w", newline="", encoding="utf-8")
    f_jl   = open(index_jsonl, "w", encoding="utf-8")
    f_urls = open(urls_txt, "w", encoding="utf-8")
    f_all  = open(all_text, "w", encoding="utf-8")
    cw = csv.writer(f_csv)
    cw.writerow(["url","status","title","meta_description","published_time","author","h1","file_path"])

    page_idx = 0
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        while frontier and len(visited) < max_pages:
            batch = []
            while frontier and len(batch) < workers * 3:
                u = frontier.pop(0)
                if urlparse(u).netloc != base_netloc: 
                    continue
                if u in visited:
                    continue
                batch.append(u)

            futs = {ex.submit(fetch_and_parse, url, session, rp, base_netloc, delay, limiter): url for url in batch}

            for fut in cf.as_completed(futs):
                u = futs[fut]
                try:
                    fetched_url, pdata, outlinks, status, _html = fut.result()
                except Exception:
                    continue

                # Đánh dấu visited SAU khi fetch
                visited.add(u)
                f_urls.write(u + "\n")

                # Thêm link mới
                for link in outlinks:
                    if urlparse(link).netloc != base_netloc: 
                        continue
                    if link in visited or link in all_seen: 
                        continue
                    all_seen.add(link)
                    if looks_like_listing(link):
                        frontier.insert(0, link)  # ưu tiên
                    else:
                        frontier.append(link)

                # Lưu trang
                if pdata is not None:
                    page_idx += 1
                    fpath = save_page_text(domain_dir, page_idx, pdata.url, pdata.text)
                    rel = os.path.relpath(fpath, domain_dir)
                    pdata.file_path = rel

                    cw.writerow([pdata.url, pdata.status, pdata.title, pdata.meta_description,
                                 pdata.published_time, pdata.author, pdata.h1, pdata.file_path])
                    f_jl.write(json.dumps(asdict(pdata), ensure_ascii=False) + "\n")
                    f_all.write(f"URL: {pdata.url}\nTITLE: {pdata.title}\n\n{pdata.text}\n\n{'='*80}\n\n")

                if len(visited) >= max_pages:
                    break

    f_csv.close(); f_jl.close(); f_urls.close(); f_all.close()
    print(f"[*] Done. {_canon_host(base_netloc)}: visited={len(visited)}, saved={page_idx}")
    print(f"    DIR: {domain_dir}")

# ---------- đọc file danh sách URL gốc ----------
def read_url_file(path: str) -> List[str]:
    urls = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if not line.startswith(("http://","https://")):
                line = "https://" + line
            if not line.endswith("/"):
                line += "/"
            urls.append(line)
    return urls

# ---------- main ----------
def web_crawler():
    ap = argparse.ArgumentParser(description="Crawl multiple sites into per-site folders (each page = one file).")
    ap.add_argument("--base", type=str, help="Single base URL (e.g., https://tiximax.net/)")
    ap.add_argument("--url-file", type=str, help="Path to sites.txt (one base URL per line)")
    ap.add_argument("--out", type=str, default="crawl_out", help="Output group folder under src/Data/")
    ap.add_argument("--max-pages", type=int, default=10000)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--delay", type=float, default=0.5)
    ap.add_argument("--rps", type=float, default=1.5, help="Global requests/sec cap per site")
    ap.add_argument("--no-sitemap", action="store_true")
    args = ap.parse_args()

    # --- AUTO-DETECT sites.txt nếu không truyền --base / --url-file ---
    from pathlib import Path
    # Ưu tiên biến môi trường nếu có
    env_sites = os.environ.get("SITES_FILE", "").strip()
    if not args.base and not args.url_file:
        candidates = []
        if env_sites:
            candidates.append(Path(env_sites))
        # CWD trước, rồi tới cùng thư mục với file .py
        candidates += [Path(os.getcwd()) / "sites.txt", Path(__file__).with_name("sites.txt")]
        for p in candidates:
            if p.is_file():
                args.url_file = str(p.resolve())
                print(f"[*] Using default sites file: {args.url_file}")
                break
        if not args.url_file:
            print("[!] Missing --base or --url-file and no sites.txt found "
                  "(checked SITES_FILE, CWD, and script folder).")
            return

    ensure_dir(os.path.join("src", "Data", args.out))

    if args.url_file:
        bases = read_url_file(args.url_file)
        if not bases:
            print(f"[!] No URLs found in {args.url_file}")
            return
        for base in bases:
            try:
                crawl_site(
                    base=base,
                    out_root=args.out,
                    max_pages=args.max_pages,
                    workers=args.workers,
                    delay=args.delay,
                    rps=args.rps,
                    use_sitemap_first=not args.no_sitemap
                )
            except Exception as e:
                print(f"[ERROR] {base}: {e}")
    else:
        # Chế độ 1 site
        crawl_site(
            base=args.base,
            out_root=args.out,
            max_pages=args.max_pages,
            workers=args.workers,
            delay=args.delay,
            rps=args.rps,
            use_sitemap_first=not args.no_sitemap
        )

