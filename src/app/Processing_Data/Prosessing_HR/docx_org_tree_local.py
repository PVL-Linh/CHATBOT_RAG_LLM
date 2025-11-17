from __future__ import annotations
import re, zipfile, os
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
from pathlib import Path
from lxml import etree

FALLBACK_TOP_LABEL = "Nhánh {i}"
UTF8_BOM_DEFAULT = True
@dataclass
class Node:
    num: str
    title: str
    children: List["Node"] = field(default_factory=list)

def num_key(n: str):
    parts = re.split(r'[.]', n)
    key = []
    for p in parts:
        if p.isdigit():
            key.append(int(p))
        elif p.isalpha():
            key.append(ord(p.upper()) - ord('A') + 1)
        else:
            key.append(0)
    return key

def parent_num(n: str) -> Optional[str]:
    return n.rsplit(".", 1)[0] if "." in n else None

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()

def _find_ceo_title(raw: str) -> Optional[str]:
    s = _norm(raw)
    if "giám đốc điều hành (ceo)" in s:
        return "Giám đốc điều hành (CEO)"
    if "giám đốc điều hành" in s and "ceo" in s:
        return "Giám đốc điều hành (CEO)"
    if "giám đốc điều hành" in s:
        return "Giám đốc điều hành"
    if "tổng giám đốc" in s:
        return "Tổng giám đốc"
    if "chủ tịch" in s:
        return "Chủ tịch"
    if re.search(r"\bceo\b", s, flags=re.I):
        return "CEO"
    return None


def get_core_title_from_docx(z: zipfile.ZipFile) -> Optional[str]:
    try:
        core = z.read("docProps/core.xml")
        root = etree.fromstring(core)
        ns = {"dc": "http://purl.org/dc/elements/1.1/"}
        t = root.xpath("string(.//dc:title)", namespaces=ns).strip()
        return t or None
    except Exception:
        return None


def friendly_title_from_filename(path: str) -> str:
    base = os.path.splitext(os.path.basename(path))[0]
    base = re.sub(r"[_\-]+", " ", base).strip()
    return base if base else "Sơ đồ tổ chức"


def extract_items_from_docx(path: str) -> Tuple[List[Tuple[str, int, str]], str, Optional[str]]:
    """Trích toàn văn, bắt các mục đánh số; KHỬ LẶP THEO NUM (giữ title dài nhất)."""
    with zipfile.ZipFile(path) as z:
        try:
            xml = z.read("word/document.xml")
        except KeyError:
            return [], "", get_core_title_from_docx(z)
        doc_title = get_core_title_from_docx(z)
    root_xml = etree.fromstring(xml)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    raw = "".join(root_xml.xpath(".//w:t/text()", namespaces=ns)).strip()
    if not raw:
        return [], "", doc_title

    matches = list(re.finditer(r"(\d+(?:\.\d+)*)(?:\.\s*|\s+)", raw))
    items: List[Tuple[str, int, str]] = []
    for i, m in enumerate(matches):
        num = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        title = re.sub(r"\s+", " ", raw[start:end]).strip()
        if title:
            level = num.count(".") + 1
            items.append((num, level, title))

    best: Dict[str, Tuple[int, str]] = {}
    for n, l, t in items:
        t2 = re.sub(r"\s+", " ", t).strip()
        if (n not in best) or (len(t2) > len(best[n][1])):
            best[n] = (l, t2)
    clean = [(n, best[n][0], best[n][1]) for n in sorted(best.keys(), key=num_key)]
    return clean, raw, doc_title

def extract_heading_from_raw(raw: str) -> Optional[str]:
    m = re.search(r"(\d+(?:\.\d+)*)(?:\.\s*|\s+)", raw)
    prefix = raw[: m.start()] if m else raw
    heading = re.sub(r"\s+", " ", prefix).strip().strip("–-—:·•* ")
    if any(ch.isalpha() for ch in heading) and len(heading) >= 3:
        return heading
    return None

def resolve_doc_title(doc_title: Optional[str], path: str, raw: str) -> str:
    return extract_heading_from_raw(raw) or doc_title or friendly_title_from_filename(path)

def _capture_top_title_from_raw(top: str, raw: str) -> Optional[str]:
    pat = re.compile(
        rf"(?<!\d){re.escape(top)}(?:\s*[\.\)])?\s*"
        rf"([^\d]+?)"
        rf"(?=(\d+(?:\.\d+)*)\s|$)",
        flags=re.DOTALL,
    )
    m = pat.search(raw)
    if not m:
        return None
    cand = re.sub(r"\s+", " ", m.group(1)).strip()
    cand = re.sub(r"\s*(?:–|-|:)\s*$", "", cand).strip()
    return cand or None

def ensure_top_nodes_with_titles(items: List[Tuple[str, int, str]], raw: str) -> List[Tuple[str, int, str]]:
    """Đảm bảo node đầu cho mỗi chỉ số top (1,2,3...). 1->CEO nếu thiếu tiêu đề level-1."""
    tops = sorted({n.split(".")[0] for n, _, _ in items}, key=lambda x: int(x))
    titles: Dict[str, str] = {}
    for top in tops:
        t = next((t for (n, l, t) in items if n == top and l == 1), None)
        if not t:
            t = _capture_top_title_from_raw(top, raw)
        if not t and top == "1":
            t = _find_ceo_title(raw)
        titles[top] = t or FALLBACK_TOP_LABEL.format(i=top)

    result: Dict[str, Tuple[int, str]] = {}
    for top in tops:
        result[top] = (1, titles[top])
    for n, l, t in items:
        if n.isdigit():
            result[n] = (1, titles[n])
        else:
            result[n] = (l, t)

    return [(n, result[n][0], result[n][1]) for n in sorted(result.keys(), key=num_key)]

def build_tree(items: List[Tuple[str, int, str]]) -> Dict[str, Node]:
    nodes: Dict[str, Node] = {n: Node(n, t) for n, l, t in items}
    for n, l, t in items:
        p = parent_num(n)
        if p and p in nodes:
            parent, child = nodes[p], nodes[n]
            if all(c.num != child.num for c in parent.children):
                parent.children.append(child)

    def sort_subtree(nd: Node):
        nd.children.sort(key=lambda c: num_key(c.num))
        for ch in nd.children:
            sort_subtree(ch)

    for nd in nodes.values():
        sort_subtree(nd)
    return nodes

def render_tree(nodes: Dict[str, Node], *, single_tree: bool = False, title_line: Optional[str] = None, print_num: bool = True) -> str:
    nums = set(nodes.keys())

    def has_parent(n: str) -> bool:
        p = parent_num(n)
        while p:
            if p in nums:
                return True
            p = parent_num(p)
        return False

    top_nums = sorted([n for n in nums if not has_parent(n)], key=num_key)
    top_nodes = [nodes[n] for n in top_nums]

    def show(n: Node) -> str:
        return f"{n.num} {n.title}" if print_num else (n.title if n.num.isdigit() else n.title)

    lines: List[str] = []
    if title_line:
        lines.append(title_line)

    def rec(n: Node, prefix=""):
        for i, ch in enumerate(n.children):
            last = i == len(n.children) - 1
            lines.append(prefix + ("└─ " if last else "├─ ") + show(ch))
            rec(ch, prefix + ("   " if last else "│  "))

    if not top_nodes:
        lines.append("(Không tìm thấy node đầu)")
        return "\n".join(lines)

    for tn in top_nodes:
        lines.append(show(tn))
        rec(tn, "")
    return "\n".join(lines)

def process_one_docx_file(docx_path: Path, out_dir: Path, *, print_num: bool = True, single_tree: bool = False, utf8_bom: bool = UTF8_BOM_DEFAULT) -> Path:
    items, raw, core_title = extract_items_from_docx(str(docx_path))
    if not items:
        tree_txt = "(Không trích được mục nào — có thể file là ảnh.)"
    else:
        items = ensure_top_nodes_with_titles(items, raw)
        nodes = build_tree(items)
        title_line = resolve_doc_title(core_title, str(docx_path), raw)
        tree_txt = render_tree(nodes, single_tree=single_tree, title_line=title_line, print_num=print_num)

    out_dir.mkdir(parents=True, exist_ok=True)
    base = docx_path.stem
    out_path = out_dir / f"{base}_tree.txt"
    data = ("\ufeff" + tree_txt).encode("utf-8") if utf8_bom else tree_txt.encode("utf-8")
    with open(out_path, "wb") as f:
        f.write(data)
    return out_path


def org_tree_run(input_path: str, output_path: str, *, print_num: bool = True, single_tree: bool = False, utf8_bom: bool = UTF8_BOM_DEFAULT, recurse: bool = True) -> dict:
    in_p = Path(input_path).resolve()
    out_p = Path(output_path).resolve()
    out_p.mkdir(parents=True, exist_ok=True)

    if in_p.is_file():
        if in_p.suffix.lower() != ".docx":
            return {"ok": 0, "fail": 1, "count": 0, "results": [], "input": str(in_p), "output": str(out_p), "error": "Chỉ hỗ trợ .docx"}
        try:
            outp = process_one_docx_file(in_p, out_p, print_num=print_num, single_tree=single_tree, utf8_bom=utf8_bom)
            return {"ok": 1, "fail": 0, "count": 1, "results": [{"src": str(in_p), "out": str(outp)}], "input": str(in_p), "output": str(out_p)}
        except Exception as e:
            return {"ok": 0, "fail": 1, "count": 1, "results": [], "input": str(in_p), "output": str(out_p), "error": str(e)}

    if in_p.is_dir():
        pattern = "**/*.docx" if recurse else "*.docx"
        files = sorted(in_p.glob(pattern))
        ok = fail = 0
        results: List[dict] = []
        for f in files:
            try:
                outp = process_one_docx_file(f, out_p, print_num=print_num, single_tree=single_tree, utf8_bom=utf8_bom)
                ok += 1
                results.append({"src": str(f), "out": str(outp)})
            except Exception as e:
                fail += 1
        return {"ok": ok, "fail": fail, "count": len(files), "results": results, "input": str(in_p), "output": str(out_p)}

    return {"ok": 0, "fail": 1, "count": 0, "results": [], "input": str(in_p), "output": str(out_p), "error": "input_path không tồn tại"}

def org_tree_run_simple(input_path: str, output_path: str, *, print_num: bool = True, single_tree: bool = False, utf8_bom: bool = UTF8_BOM_DEFAULT, recurse: bool = True, quiet: bool = False) -> None:
    res = org_tree_run(
        input_path,
        output_path,
        print_num=print_num,
        single_tree=single_tree,
        utf8_bom=utf8_bom,
        recurse=recurse,
    )
    if quiet:
        return
    try:
        from pathlib import Path as _P
        if _P(input_path).is_dir():
            print(f"🎯 Hoàn tất. Thành công: {res.get('ok',0)} | Lỗi: {res.get('fail',0)} | 📁 Out: {res.get('output')}")
        else:
            rs = res.get('results') or []
            if rs:
                print(f"✅ {os.path.basename(rs[0]['src'])} → {os.path.basename(rs[0]['out'])}")
            print(f"📁 Out: {res.get('output')}")
    except Exception:
        pass

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="DOCX → TXT Org-Tree (local)")
    p.add_argument("input", type=str, help="Đường dẫn FILE .docx hoặc THƯ MỤC chứa .docx")
    p.add_argument("output", type=str, help="Thư mục xuất TXT")
    p.add_argument("--no-num", action="store_true", help="Không in kèm số cho node")
    p.add_argument("--single", action="store_true", help="In trực tiếp node đầu (không root ảo)")
    p.add_argument("--no-bom", action="store_true", help="Không ghi UTF-8 BOM")
    p.add_argument("--no-recurse", action="store_true", help="Không duyệt đệ quy nếu là thư mục")
    args = p.parse_args()

    stats = org_tree_run(
        args.input,
        args.output,
        print_num=not args.no_num,
        single_tree=args.single,
        utf8_bom=not args.no_bom,
        recurse=not args.no_recurse,
    )
    print(stats)
