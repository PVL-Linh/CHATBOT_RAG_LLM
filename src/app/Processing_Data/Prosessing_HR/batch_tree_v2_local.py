import argparse
import io
import logging
import os
import re
import sys
import zipfile
from pathlib import Path
from typing import Dict, List, Tuple

try:
    import fitz
except Exception as e:
    print("[FATAL] PyMuPDF (fitz) chưa cài. Hãy: pip install pymupdf", file=sys.stderr)
    raise

try:
    from pdfminer.high_level import extract_text as pdfminer_extract
except Exception as e:
    print("[FATAL] pdfminer.six chưa cài. Hãy: pip install pdfminer.six", file=sys.stderr)
    raise
try:
    from docx import Document
    DOCX_AVAILABLE = True
except Exception:
    DOCX_AVAILABLE = False

import xml.etree.ElementTree as ET
PATH_DOCUMENTS = Path("./documents_workflowAndText").resolve() and "./Documents/HR/Diagram/documents_workflowAndText"
PATH_OUTPUT = Path("./output_txt").resolve() and "./src/app/Data/HR/Diagram/documents_workflowAndText"

def configure_paths(path_documents: str = None, path_output: str = None) -> tuple[Path, Path]:
    """
    Đặt (hoặc thay đổi) 2 đường dẫn dùng chung:
      - path_documents: thư mục chứa tài liệu đầu vào
      - path_output   : thư mục chứa kết quả .txt
    Trả về (in_dir, out_dir) là Path đã chuẩn hoá. Có thể gọi trực tiếp khi import module.
    """
    global PATH_DOCUMENTS, PATH_OUTPUT
    if path_documents is not None:
        PATH_DOCUMENTS = Path(path_documents).resolve()
    if path_output is not None:
        PATH_OUTPUT = Path(path_output).resolve()
    PATH_OUTPUT.mkdir(parents=True, exist_ok=True)
    return PATH_DOCUMENTS, PATH_OUTPUT

def space_score(s: str) -> float:
    """Đánh giá chất lượng khoảng trắng: tỉ lệ space/độ dài + số từ/1000 ký tự."""
    if not s:
        return 0.0
    L = len(s)
    spaces = s.count(" ")
    words = len(re.findall(r"\b\w+\b", s, flags=re.UNICODE))
    return (spaces / max(L, 1)) * 0.6 + (words / max(L / 6, 1)) * 0.4


def normalize_text(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\r", "\n").replace("\xa0", " ")
    s = re.sub(r"(\w)-\n(\w)", r"\1\2", s)
    s = re.sub(r"(?m)(^|\s)-(\S)", r"\1- \2", s)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in s.split("\n")]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines)


def uniq_keep_order(lines: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for x in lines:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def extract_pdf_text_fitz_words(pdf_path: Path) -> str:
    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return ""
    blocks_all: List[str] = []
    for page in doc:
        words = page.get_text("words")
        if not words:
            continue
        words.sort(key=lambda w: (w[5], w[6], w[0], w[1]))
        last_blk, last_line = None, None
        line_buf: List[str] = []
        for (x0, y0, x1, y1, word, blk, ln, wn) in words:
            if (blk, ln) != (last_blk, last_line):
                if line_buf:
                    blocks_all.append(" ".join(line_buf))
                    line_buf = []
                last_blk, last_line = blk, ln
            line_buf.append(word)
        if line_buf:
            blocks_all.append(" ".join(line_buf))
        blocks_all.append("")
    return "\n".join(blocks_all)


def extract_pdf_text_pdfminer(pdf_path: Path) -> str:
    try:
        return pdfminer_extract(str(pdf_path)) or ""
    except Exception:
        return ""


def ocr_pdf_easyocr(pdf_path: Path, reader, dpi: int = 220) -> str:
    if reader is None:
        return ""
    out: List[str] = []
    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return ""
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    from PIL import Image
    import numpy as np

    for page in doc:
        try:
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            img_np = np.array(img)
            results = reader.readtext(img_np, detail=0, paragraph=True)
            if results:
                out.append("\n".join(results))
        except Exception:
            continue
    return "\n\n".join([x for x in out if x and x.strip()])


def read_txt_text(txt_path: Path) -> str:
    for enc in ("utf-8", "cp1258", "latin-1"):
        try:
            return txt_path.read_text(encoding=enc, errors="ignore")
        except Exception:
            pass
    return ""


def extract_docx_text(docx_path: Path) -> str:
    if not DOCX_AVAILABLE:
        return ""

    lines: List[str] = []
    try:
        doc = Document(str(docx_path))
    except Exception:
        return ""

    for p in doc.paragraphs:
        t = (p.text or "").strip()
        if t:
            lines.append(t)

    for tbl in doc.tables:
        for row in tbl.rows:
            cells: List[str] = []
            for cell in row.cells:
                cells.append((cell.text or "").strip())
            row_txt = " \t ".join([c for c in cells if c])
            if row_txt.strip():
                lines.append(row_txt)

    try:
        with zipfile.ZipFile(str(docx_path)) as zf:
            if "word/document.xml" in zf.namelist():
                root = ET.fromstring(zf.read("word/document.xml"))
                ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                for p in root.findall(".//w:p", ns):
                    t = "".join([t_.text for t_ in p.findall(".//w:t", ns) if t_.text]).strip()
                    if t:
                        lines.append(t)
    except Exception:
        pass

    lines = uniq_keep_order([ln for ln in lines if ln and ln.strip()])
    return "\n".join(lines)


def slice_body(full_text: str):
    text = full_text
    idx_mota = re.search(r"mô tả\s*chi tiết", text, flags=re.I)
    idx_time = re.search(r"\bthời gian\b", text, flags=re.I)
    idx_forms = re.search(r"(biểu mẫu|tài liệu(?:\s*/\s*biểu mẫu)?)", text, flags=re.I)

    def pos(m, default):
        return m.span()[0] if m else default

    start_mo = pos(idx_mota, 0)
    start_tg = pos(idx_time, len(text))
    start_bm = pos(idx_forms, len(text))

    mota = text[start_mo : min(start_tg, start_bm)] if idx_mota else text[: min(start_tg, start_bm)]
    thoi_gian = text[start_tg:start_bm] if idx_time else ""
    bieumau = text[start_bm:] if idx_forms else ""
    return mota.strip(), thoi_gian.strip(), bieumau.strip()


def collect_numbered_sections(mota_text: str) -> Dict[str, str]:
    pat = re.compile(r"^\s*(\d+(?:\.\d+)*)\s*[)\.-]\s*(.*)$")
    out: Dict[str, List[str]] = {}
    cur = None
    for raw in mota_text.split("\n"):
        ln = raw.strip()
        if not ln:
            continue
        m = pat.match(ln)
        if m:
            key, rest = m.group(1), m.group(2).strip()
            cur = key
            out.setdefault(key, [])
            if rest:
                out[key].append(rest)
        else:
            if cur:
                out[cur].append(ln)
    return {k: " ".join(v).strip() for k, v in out.items()}


def parse_durations(tg_text: str) -> Dict[str, str]:
    res: Dict[str, str] = {}
    for ln in tg_text.split("\n"):
        ln = ln.strip()
        m = re.match(r"^(\d+(?:\+\d+)*)\.\s*(.+)$", ln)  # '4+5. nội dung' hoặc '2. nội dung'
        if not m:
            continue
        steps, content = m.group(1), m.group(2).strip()
        for s in steps.split("+"):
            res[s] = content
    return res


def parse_forms(bm_text: str) -> List[str]:
    body = re.sub(r"(?is)^.*?(biểu mẫu|tài liệu(?:\s*/\s*biểu mẫu)?)", "", bm_text, flags=re.I).strip()
    items: List[str] = []
    for ln in body.split("\n"):
        x = ln.strip(" •-\t")
        if x:
            items.append(x)
    if not items and body:
        items = [s.strip() for s in re.split(r"\.\s+", body) if s.strip()]
    return items


def sentences_to_bullets(paragraph: str, cap: int = 3) -> List[str]:
    if not paragraph:
        return []
    tmp = re.sub(r"\bTH\b", " |TH", paragraph)
    parts = re.split(r"[\.•;]|[|]| - ", tmp)  # coi " - " như điểm ngắt bullet
    parts = [re.sub(r"\s+", " ", p).strip(" -") for p in parts if p and p.strip()]
    return parts[:cap] if parts else [paragraph]


# ---------- Render TREE_V2 ----------

def render_fixed_format_txt(title: str, src_path: str, sections: Dict[str, str], durations: Dict[str, str], forms: List[str]) -> str:
    lines: List[str] = []
    lines.append("FORMAT_VERSION: TREE_V2")
    lines.append(f"FILE: {Path(src_path).name}")
    lines.append(f"SOURCE_PATH: {src_path}")
    lines.append(f"TITLE: {title}")
    lines.append("LANG: vi")
    lines.append("")
    lines.append("STEPS:")

    top = sorted({k.split(".")[0] for k in sections}, key=lambda x: int(x)) if sections else []
    if not top:
        lines.append("- (none)")
    else:
        for k in top:
            lines.append(f"- STEP {k}")
            step_text = sections.get(k, "")
            bullets = sentences_to_bullets(step_text, cap=3) if step_text else []
            if not bullets:
                lines.append("  - ITEM: (trống)")
            else:
                for b in bullets:
                    b = re.sub(r"\s+", " ", b).strip()
                    if len(b) > 200:
                        b = b[:197] + "..."
                    lines.append(f"  - ITEM: {b}")
            subs = [
                (kk, sections[kk])
                for kk in sorted(
                    [x for x in sections if x.startswith(f"{k}.")],
                    key=lambda x: [int(t) for t in x.split(".")],
                )
            ]
            for subk, subtxt in subs:
                subtxt = re.sub(r"\s+", " ", subtxt).strip()
                if len(subtxt) > 200:
                    subtxt = subtxt[:197] + "..."
                lines.append(f"  - SUBSTEP {subk}: {subtxt if subtxt else '(trống)'}")

    lines.append("")
    lines.append("TIMELINE:")
    if durations:
        for s_no, dur in sorted(durations.items(), key=lambda kv: [int(x) for x in kv[0].split('.')]):
            lines.append(f"- STEP {s_no}: {dur}")
    else:
        lines.append("- (none)")

    lines.append("")
    lines.append("FORMS:")
    if forms:
        for item in forms:
            item = re.sub(r"\s+", " ", item).strip()
            if len(item) > 200:
                item = item[:197] + "..."
            lines.append(f"- {item}")
    else:
        lines.append("- (none)")

    return "\n".join(lines)


def extract_text_any(path: Path, use_ocr: bool, ocr_reader, ocr_dpi: int) -> str:
    ext = path.suffix.lower()
    if ext in (".txt", ".md"):
        return normalize_text(read_txt_text(path))

    if ext == ".docx":
        return normalize_text(extract_docx_text(path))

    if ext != ".pdf":
        return ""

    t1 = normalize_text(extract_pdf_text_fitz_words(path))
    sc1 = space_score(t1)
    t2 = normalize_text(extract_pdf_text_pdfminer(path))
    sc2 = space_score(t2)

    best_text, best_score = (t1, sc1) if sc1 >= sc2 else (t2, sc2)
    if best_score < 0.08 and use_ocr and ocr_reader is not None:
        logging.info(f"  ⚠️ {path.name}: spacing kém (score={best_score:.3f}) → thử EasyOCR ...")
        t3 = normalize_text(ocr_pdf_easyocr(path, ocr_reader, dpi=ocr_dpi))
        sc3 = space_score(t3)
        if sc3 > best_score:
            best_text, best_score = t3, sc3

    return best_text


def process_one_file(fp: Path, out_dir: Path, use_ocr: bool, ocr_reader, ocr_dpi: int) -> Path:
    raw = extract_text_any(fp, use_ocr=use_ocr, ocr_reader=ocr_reader, ocr_dpi=ocr_dpi)
    if not raw.strip():
        raise RuntimeError("Không đọc được text (cần OCR hoặc file scan).")

    mota, tg, bm = slice_body(raw)
    sections = collect_numbered_sections(mota)
    durations = parse_durations(tg)
    forms = parse_forms(bm)

    title = re.sub(r"_+", " ", fp.stem).strip()
    out_txt = render_fixed_format_txt(title, str(fp), sections, durations, forms)
    out_path = out_dir / f"{fp.stem}_tree.txt"
    out_path.write_text(out_txt, encoding="utf-8")
    return out_path


def run_one_file(in_file: Path, out_dir: Path, *, use_ocr: bool = False, ocr_langs: list | None = None, ocr_dpi: int = 220, log_level: str = "INFO") -> dict:
    """Xử lý DUY NHẤT 1 file và xuất TXT TREE_V2. Trả về dict {'ok','fail','results':[{'src','out'}], 'input','output'}"""
    logging.basicConfig(level=getattr(logging, (log_level or "INFO").upper(), logging.INFO), format="%(levelname)s - %(message)s")

    in_file = Path(in_file).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not in_file.exists() or not in_file.is_file():
        return {"ok": 0, "fail": 1, "results": [], "input": str(in_file), "output": str(out_dir)}

    ocr_reader = None
    if use_ocr:
        try:
            import easyocr
            langs = ocr_langs or ["vi", "en"]
            logging.info(f"Khởi tạo EasyOCR với ngôn ngữ: {langs}")
            ocr_reader = easyocr.Reader(langs)
        except Exception as e:
            logging.error("Không khởi tạo được EasyOCR (bỏ qua OCR). Lý do: %s", e)
            ocr_reader = None

    try:
        outp = process_one_file(in_file, out_dir, use_ocr=use_ocr, ocr_reader=ocr_reader, ocr_dpi=ocr_dpi)
        return {"ok": 1, "fail": 0, "results": [{"src": str(in_file), "out": str(outp)}], "input": str(in_file), "output": str(out_dir)}
    except Exception as e:
        logging.error("Lỗi xử lý file %s: %s", in_file.name, e)
        return {"ok": 0, "fail": 1, "results": [], "input": str(in_file), "output": str(out_dir)}


def main_one_file(path_input_file: str, path_output: str, *, ocr: bool = False, langs: str = "vi,en", dpi: int = 220, log: str = "INFO") -> dict:
    """API tiện dụng để chạy 1 file (wrapper). Vẫn xuất TXT TREE_V2."""
    langs_list = [x.strip() for x in (langs or "").split(",") if x.strip()] or ["vi", "en"]
    return run_one_file(Path(path_input_file), Path(path_output), use_ocr=ocr, ocr_langs=langs_list, ocr_dpi=dpi, log_level=log)



def run_batch(in_dir: Path, out_dir: Path, *, use_ocr: bool = False, ocr_langs: list | None = None, ocr_dpi: int = 220, exts: set | str | None = None, log_level: str = "INFO") -> dict:
    logging.basicConfig(level=getattr(logging, (log_level or "INFO").upper(), logging.INFO), format="%(levelname)s - %(message)s")
    configure_paths(str(in_dir), str(out_dir))
    if exts is None:
        exts_set = {".pdf", ".docx", ".txt", ".md"}
    elif isinstance(exts, str):
        exts_set = {"." + x.strip().lower().lstrip(".") for x in exts.split(",") if x.strip()}
    else:
        exts_set = {"." + x.strip().lower().lstrip(".") for x in exts}
    ocr_reader = None
    if use_ocr:
        try:
            import easyocr
            langs = ocr_langs or ["vi", "en"]
            logging.info(f"Khởi tạo EasyOCR với ngôn ngữ: {langs}")
            ocr_reader = easyocr.Reader(langs)
        except Exception as e:
            logging.error("Không khởi tạo được EasyOCR (bỏ qua OCR). Lý do: %s", e)
            ocr_reader = None

    all_files = sorted([p for p in PATH_DOCUMENTS.rglob("*") if p.is_file() and p.suffix.lower() in exts_set])
    print(f"🔎 Tìm thấy {len(all_files)} file trong {PATH_DOCUMENTS}")

    results: list[dict] = []
    ok = fail = 0
    for f in all_files:
        rel = f.relative_to(PATH_DOCUMENTS)
        try:
            outp = process_one_file(f, PATH_OUTPUT, use_ocr=use_ocr, ocr_reader=ocr_reader, ocr_dpi=ocr_dpi)
            ok += 1
            results.append({"src": str(f), "out": str(outp)})
            print(f"✅ {rel}  →  {outp.name}")
        except Exception as e:
            fail += 1
            print(f"❌ {rel}  →  {e}")

    print("🎯 Hoàn tất.")
    print(f"   Thành công: {ok} | Lỗi: {fail}")
    print(f"📁 Kết quả TXT: {PATH_OUTPUT}")

    return {"ok": ok, "fail": fail, "count": len(all_files), "results": results, "input": str(PATH_DOCUMENTS), "output": str(PATH_OUTPUT)}


def main_to_pdf(path_input: str, path_output: str, *, ocr: bool = False, langs: str = "vi,en", dpi: int = 220, exts: str = "pdf,docx,txt,md", log: str = "INFO") -> dict:
    in_dir = Path(path_input).resolve()
    out_dir = Path(path_output).resolve()
    langs_list = [x.strip() for x in (langs or "").split(",") if x.strip()] or ["vi", "en"]
    return run_batch(in_dir, out_dir, use_ocr=ocr, ocr_langs=langs_list, ocr_dpi=dpi, exts=exts, log_level=log)

def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Batch TREE_V2 extractor (local)")
    p.add_argument("--input", "-i", type=str, default="./documents_workflowAndText", help="Thư mục đầu vào (đệ quy)")
    p.add_argument("--output", "-o", type=str, default="./output_txt", help="Thư mục kết quả TXT")
    p.add_argument("--file", "-f", type=str, help="Đường dẫn tới 1 FILE duy nhất (ưu tiên, sẽ bỏ qua --input)")
    p.add_argument("--exts", type=str, default="pdf,docx,txt,md", help="Phần mở rộng xử lý, ngăn cách dấu phẩy")
    p.add_argument("--ocr", action="store_true", help="Bật EasyOCR cho PDF scan (tùy chọn)")
    p.add_argument("--langs", type=str, default="vi,en", help="Ngôn ngữ OCR, ví dụ: vi,en")
    p.add_argument("--dpi", type=int, default=220, help="DPI khi render trang PDF cho OCR")
    p.add_argument("--log", type=str, default="INFO", help="Mức log: DEBUG/INFO/WARN/ERROR")
    return p


def main():
    args = build_argparser().parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log.upper(), logging.INFO),
        format="%(levelname)s - %(message)s",
    )

    configure_paths(args.input, args.output)
    in_dir, out_dir = PATH_DOCUMENTS, PATH_OUTPUT

    if args.file:
        stats = main_one_file(args.file, args.output, ocr=args.ocr, langs=args.langs, dpi=args.dpi, log=args.log)
        if stats.get("ok"):
            for r in stats.get("results", []):
                try:
                    print(f"✅ {Path(r['src']).name}  →  {Path(r['out']).name}")
                except Exception:
                    print(f"✅ {r.get('src')}  →  {r.get('out')}")
        else:
            print("❌ Không xử lý được file.")
        print("🎯 Hoàn tất.")
        print(f"   Thành công: {stats.get('ok',0)} | Lỗi: {stats.get('fail',0)}")
        print(f"📁 Kết quả TXT: {stats.get('output')}")
        return

    if not in_dir.exists() or not in_dir.is_dir():
        print(f"[ERROR] Thư mục đầu vào không tồn tại: {in_dir}", file=sys.stderr)
        sys.exit(2)

    ocr_reader = None
    if args.ocr:
        try:
            import easyocr
            langs = [x.strip() for x in args.langs.split(",") if x.strip()]
            logging.info(f"Khởi tạo EasyOCR với ngôn ngữ: {langs}")
            ocr_reader = easyocr.Reader(langs)
        except Exception as e:
            logging.error("Không khởi tạo được EasyOCR (bỏ qua OCR). Lý do: %s", e)
            ocr_reader = None

    exts = {"." + x.strip().lower().lstrip(".") for x in args.exts.split(",") if x.strip()}
    all_files = sorted([p for p in in_dir.rglob("*") if p.is_file() and p.suffix.lower() in exts])
    print(f"🔎 Tìm thấy {len(all_files)} file trong {in_dir}")

    ok, fail = 0, 0
    for f in all_files:
        rel = f.relative_to(in_dir)
        try:
            outp = process_one_file(f, out_dir, use_ocr=args.ocr, ocr_reader=ocr_reader, ocr_dpi=args.dpi)
            ok += 1
            print(f"✅ {rel}  →  {outp.name}")
        except Exception as e:
            fail += 1
            print(f"❌ {rel}  →  {e}")

    print("🎯 Hoàn tất.")
    print(f"   Thành công: {ok} | Lỗi: {fail}")
    print(f"📁 Kết quả TXT: {out_dir}")


if __name__ == "__main__":
    main()


def tree_run(input_path: str, output_path: str) -> dict:
    in_p = Path(input_path).resolve()
    out_p = Path(output_path).resolve()

    # Tự phát hiện OCR
    use_ocr = False
    ocr_langs = ["vi", "en"]
    try:
        import easyocr
        use_ocr = True
    except Exception:
        use_ocr = False

    if in_p.is_dir():
        return run_batch(in_p, out_p, use_ocr=use_ocr, ocr_langs=ocr_langs, ocr_dpi=220, exts="pdf,docx,txt,md", log_level="INFO")
    elif in_p.is_file():
        return run_one_file(in_p, out_p, use_ocr=use_ocr, ocr_langs=ocr_langs, ocr_dpi=220, log_level="INFO")
    else:
        return {"ok": 0, "fail": 1, "results": [], "input": str(in_p), "output": str(out_p), "error": "input_path không tồn tại"}
