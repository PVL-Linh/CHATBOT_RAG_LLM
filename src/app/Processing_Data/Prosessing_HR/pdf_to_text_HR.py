# import os
# import zipfile
# from typing import Dict, List, Tuple

# import fitz  # PyMuPDF
# from Data_processing import clean_page_text  # sử dụng hàm clean của bạn

# # XML parsers
# try:
#     from lxml import etree
#     LXML_OK = True
# except Exception:
#     LXML_OK = False

# import xml.etree.ElementTree as ET  # dùng cho helper bóc bảng đầu trang
# from .batch_tree_v2_local import tree_run
# from .docx_org_tree_local import org_tree_run
# try:
#     import docx as _docx  # đảm bảo import trong môi trường runtime
# except Exception:
#     raise ImportError("Chưa cài python-docx. Cài: pip install python-docx lxml")
# # ========================
# # Cấu hình
# # ========================
# USE_OCR_FALLBACK = True         # Bật OCR fallback cho PDF
# DOCX_DROP_HEADERS = False       # QUAN TRỌNG: False để GIỮ head/header/footer của DOCX
# PDF_DROP_HEADERS = True         # PDF thường lặp header theo trang -> nên True
# TABLE_MODE = "flatten"          # 'flatten' như bạn đang dùng
# KEEP_TABLES = True
# LATEX_MATH = True

# # ========================
# # OCR (EasyOCR) — tùy chọn
# # ========================
# try:
#     import easyocr
#     import numpy as np
#     from PIL import Image
#     import io
#     _easyocr_reader = easyocr.Reader(["vi", "en"])
# except Exception:
#     USE_OCR_FALLBACK = False
#     _easyocr_reader = None


# # ========================
# # PDF helpers
# # ========================
# def _extract_text(page: fitz.Page) -> str:
#     """Ưu tiên trích xuất dict/spans để hạn chế rớt ký tự."""
#     try:
#         data = page.get_text("dict")
#         out = []
#         for b in data.get("blocks", []):
#             for ln in b.get("lines", []):
#                 out.append("".join(sp.get("text", "") for sp in ln.get("spans", [])))
#         txt = "\n".join(out)
#         if txt.strip():
#             return txt
#     except Exception:
#         pass
#     return page.get_text() or ""


# def _ocr_image(pix: fitz.Pixmap) -> str:
#     """OCR 1 trang PDF bằng EasyOCR."""
#     if not USE_OCR_FALLBACK or _easyocr_reader is None:
#         return ""
#     img_bytes = pix.tobytes("png")
#     img = np.array(Image.open(io.BytesIO(img_bytes)))
#     try:
#         results = _easyocr_reader.readtext(img, detail=0, paragraph=True)
#     except Exception:
#         results = []
#     return "\n".join(results)


# def _process_pdf(pdf_path: str) -> str:
#     """Xử lý file PDF → text (có OCR fallback)."""
#     doc = fitz.open(pdf_path)
#     page_texts: List[str] = []

#     for page in doc:
#         raw = _extract_text(page)

#         # OCR fallback nếu trang gần như rỗng
#         if USE_OCR_FALLBACK and len(raw.strip()) < 40:
#             try:
#                 raw = (raw + "\n" + _ocr_image(page.get_pixmap(dpi=200))).strip()
#             except Exception as e:
#                 print(f"⚠️ OCR lỗi tại {pdf_path}: {e}")

#         cleaned = clean_page_text(
#             raw,
#             drop_headers=PDF_DROP_HEADERS,
#             keep_tables=KEEP_TABLES,
#             table_mode=TABLE_MODE,
#             latex_math=LATEX_MATH,
#         )
#         page_texts.append(cleaned)

#     doc.close()
#     combined = "\n\n".join([p for p in page_texts if p.strip()])

#     # Nếu cả file rỗng → OCR toàn file
#     if not combined.strip() and USE_OCR_FALLBACK:
#         print(f"⚠️ File PDF rỗng, chạy OCR toàn file: {pdf_path}")
#         all_text = []
#         for page in fitz.open(pdf_path):
#             ocr = _ocr_image(page.get_pixmap(dpi=200))
#             if ocr.strip():
#                 all_text.append(ocr)
#         combined = "\n\n".join(all_text)

#     return combined


# # ========================
# # DOCX helpers
# # ========================
# def _table_lines(tbl) -> List[str]:
#     lines = []
#     for row in tbl.rows:
#         txt = "\t".join((cell.text or "").strip() for cell in row.cells).strip()
#         if txt:
#             lines.append(txt)
#     return lines


# def _hf_to_lines(hf) -> List[str]:
#     """Lấy text từ 1 header/footer: paragraphs + tables."""
#     if hf is None:
#         return []
#     lines = []
#     for p in hf.paragraphs:
#         t = (p.text or "").strip()
#         if t:
#             lines.append(t)
#     for tbl in hf.tables:
#         lines.extend(_table_lines(tbl))
#     return lines


# def _extract_hf_python_docx(document) -> Tuple[List[str], List[str]]:
#     """Quét tất cả header/footer của mọi section (default/first/even)."""
#     headers, footers = [], []
#     for sec in document.sections:
#         # default
#         headers += _hf_to_lines(sec.header)
#         footers += _hf_to_lines(sec.footer)
#         # first page
#         try:
#             headers += _hf_to_lines(sec.first_page_header)
#             footers += _hf_to_lines(sec.first_page_footer)
#         except Exception:
#             pass
#         # even pages
#         try:
#             headers += _hf_to_lines(sec.even_page_header)
#             footers += _hf_to_lines(sec.even_page_footer)
#         except Exception:
#             pass
#     return headers, footers


# def _uniq_keep_order(lines: List[str]) -> List[str]:
#     seen = set()
#     out = []
#     for s in lines:
#         if s not in seen:
#             seen.add(s)
#             out.append(s)
#     return out


# def _extract_hf_xml(docx_path: str) -> Tuple[List[str], List[str]]:
#     """
#     Fallback: bóc zip và đọc trực tiếp header*.xml/footer*.xml để bắt text (kể cả trong shapes/textboxes).
#     """
#     if not LXML_OK:
#         return [], []
#     ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
#     headers, footers = [], []
#     with zipfile.ZipFile(docx_path) as z:
#         for name in z.namelist():
#             if name.startswith("word/header") and name.endswith(".xml"):
#                 root = etree.fromstring(z.read(name))
#                 for p in root.xpath(".//w:p", namespaces=ns):
#                     txt = "".join(p.xpath(".//w:t/text()", namespaces=ns)).strip()
#                     if txt:
#                         headers.append(txt)
#             if name.startswith("word/footer") and name.endswith(".xml"):
#                 root = etree.fromstring(z.read(name))
#                 for p in root.xpath(".//w:p", namespaces=ns):
#                     txt = "".join(p.xpath(".//w:t/text()", namespaces=ns)).strip()
#                     if txt:
#                         footers.append(txt)
#     return headers, footers


# def _extract_body_textboxes_xml(docx_path: str) -> List[str]:
#     """
#     Bắt thêm text trong shapes/textboxes ở phần thân tài liệu (document.xml).
#     python-docx thường không thấy text này.
#     """
#     if not LXML_OK:
#         return []
#     ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
#     lines = []
#     with zipfile.ZipFile(docx_path) as z:
#         if "word/document.xml" not in z.namelist():
#             return []
#         root = etree.fromstring(z.read("word/document.xml"))
#         # Tất cả đoạn văn (kể cả nằm trong w:txbxContent) sẽ được bắt qua w:p
#         for p in root.xpath(".//w:p", namespaces=ns):
#             txt = "".join(p.xpath(".//w:t/text()", namespaces=ns)).strip()
#             if txt:
#                 lines.append(txt)
#     return lines


# def _extract_top_tables_as_rows(docx_path: str, max_tables: int = 2) -> List[str]:
#     """
#     BẮT "head" dạng BẢNG ở đầu tài liệu (document.xml).
#     Lấy N bảng đầu tiên; trả về từng hàng nối bằng '\t' để giữ cột.
#     Dùng ET (stdlib) cho chắc chắn kể cả khi lxml không có.
#     """
#     try:
#         ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
#         with zipfile.ZipFile(docx_path) as zf:
#             root = ET.fromstring(zf.read('word/document.xml'))
#         tables = root.findall('.//w:tbl', ns)[:max_tables]

#         def norm(s: str) -> str:
#             return ' '.join((s or '').split())

#         lines = []
#         for tbl in tables:
#             for tr in tbl.findall('.//w:tr', ns):
#                 cells = []
#                 for tc in tr.findall('.//w:tc', ns):
#                     texts = [t.text for t in tc.findall('.//w:t', ns) if t.text]
#                     cells.append(norm(''.join(texts)))
#                 line = ' \t '.join(c for c in cells if c)
#                 if line.strip():
#                     lines.append(line)
#         return lines
#     except Exception:
#         # Không có bảng/không đọc được -> trả rỗng
#         return []


# def _process_docx(docx_path: str) -> str:
#     """Xử lý file DOCX → text (paragraph + bảng + header/footer, có XML fallback + head từ bảng)."""

#     document = _docx.Document(docx_path)

#     # 1) Header/Footer bằng python-docx (đủ default/first/even, tables)
#     hdr_lines, ftr_lines = _extract_hf_python_docx(document)

#     # 2) Fallback: nếu thiếu, đọc XML thẳng từ .docx
#     if LXML_OK and (not hdr_lines or not ftr_lines):
#         hdr2, ftr2 = _extract_hf_xml(docx_path)
#         if not hdr_lines:
#             hdr_lines = hdr2
#         if not ftr_lines:
#             ftr_lines = ftr2

#     # 3) BẮT RIÊNG “HEAD” dạng BẢNG ở đầu tài liệu (nằm trong body)
#     top_table_head = _extract_top_tables_as_rows(docx_path, max_tables=1)

#     # 4) Thân tài liệu: paragraphs + tables (python-docx)
#     para_lines = [(p.text or "").strip() for p in document.paragraphs if (p.text or "").strip()]
#     body_tables = []
#     for tbl in document.tables:
#         body_tables.extend(_table_lines(tbl))

#     # 5) Bắt thêm textboxes/shapes (body) qua XML
#     body_from_xml = _extract_body_textboxes_xml(docx_path)
#     if body_from_xml:
#         # Trộn và khử trùng lặp để tránh lặp lại nội dung
#         para_lines = _uniq_keep_order(para_lines + body_from_xml)

#     # 6) Ghép: prepend “head từ bảng”, rồi header (nếu có), thân, bảng, footer
#     all_lines = _uniq_keep_order([*top_table_head, *hdr_lines, *para_lines, *body_tables, *ftr_lines])
#     combined = "\n".join(all_lines)

#     # 7) Clean: KHÔNG drop header với DOCX (để giữ “head” này)
#     return clean_page_text(
#         combined,
#         drop_headers=DOCX_DROP_HEADERS,   # False
#         keep_tables=KEEP_TABLES,
#         table_mode=TABLE_MODE,
#         latex_math=LATEX_MATH,
#     )


# # ========================
# # Orchestrator
# # ========================
# def process_documents(input_folder: str, output_folder: str = None) -> Dict[str, str]:
#     """
#     Trích xuất toàn bộ PDF/DOCX → TXT (duyệt cả thư mục con).
#     Nếu output_folder=None thì file TXT sẽ được lưu cùng thư mục với file gốc.
#     Nếu có output_folder thì giữ nguyên cấu trúc thư mục con bên trong.
#     Trả về dict {txt_relpath: content}.
#     """
#     input_folder = os.path.abspath(input_folder)
#     if output_folder:
#         output_folder = os.path.abspath(output_folder)

#     results: Dict[str, str] = {}

#     for root, _, files in os.walk(input_folder):
#         for filename in files:
#             # Bỏ qua file tạm của Word (~$...)
#             if filename.startswith("~$"):
#                 continue
#             if not filename.lower().endswith((".pdf", ".docx")):
#                 continue

#             file_path = os.path.join(root, filename)
#             rel_path = os.path.relpath(root, input_folder)  # giữ cấu trúc thư mục
#             txt_filename = os.path.splitext(filename)[0] + ".txt"

#             # Thư mục đích
#             if output_folder:
#                 target_dir = os.path.join(output_folder, rel_path)
#             else:
#                 target_dir = root

#             os.makedirs(target_dir, exist_ok=True)
#             txt_path = os.path.join(target_dir, txt_filename)

#             print(f"🔍 Đang xử lý: {file_path}")

#             if filename.lower().endswith(".pdf"):
#                 combined = _process_pdf(file_path)
#             else:  # .docx
#                 combined = _process_docx(file_path)

#             with open(txt_path, "w", encoding="utf-8") as f:
#                 f.write(combined)

#             results[os.path.join(rel_path, txt_filename)] = combined

#     print("✅ Hoàn tất xử lý tất cả file PDF/DOCX.")
#     return results


# # ========================
# # CLI
# # ========================

# def processing_Data_doclinkToText ():
#     # CHỈNH LẠI ĐƯỜNG DẪN CHO PHÙ HỢP
#     # Ví dụ: input_dir = "Documents" hoặc "Documents/HR" hoặc r"E:\Chatbot\documents"
#     input_dir = "./Documents/HR/txt"
#     output_dir = "./src/app/Data/HR/txt"

#     process_documents(input_dir, output_dir)

#     # Txt and Diagram
#     input_txt_diagram ="./Documents/HR/Diagram/documents_workflowAndText"
#     output_txt_diagram = "./src/app/Data/HR/Diagram/documents_workflowAndText" 
#     stats = tree_run(input_txt_diagram, output_txt_diagram)
#     # diagram -> txt
#     input_dir_org_tree =  "./Documents/HR/Diagram/procedure"
#     output_dir_org_tree = "./src/app/Data/HR/Diagram/procedure"
#     org_tree_run(input_dir_org_tree, output_dir_org_tree)




# # if __name__ == "__main__":
# #     # CHỈNH LẠI ĐƯỜNG DẪN CHO PHÙ HỢP
# #     # Ví dụ: input_dir = "Documents" hoặc "Documents/HR" hoặc r"E:\Chatbot\documents"
# #     input_dir = "Documents/HR/txt"
# #     output_dir = "Documents_output/HR/txt"

# #     process_documents(input_dir, output_dir)

# #     # Txt and Diagram
# #     stats = tree_run(r"Documents/HR/Diagram/documents_workflowAndText", r"Documents_output/HR/Diagram/documents_workflowAndText")

# #     # diagram -> txt
# #     org_tree_run(r"Documents/HR/Diagram/procedure", r"Documents_output/HR/Diagram/procedure")




import os
import zipfile
from typing import Dict, List, Tuple

import fitz  # PyMuPDF
from Data_processing import clean_page_text

# XML parsers
try:
    from lxml import etree
    LXML_OK = True
except Exception:
    LXML_OK = False

import xml.etree.ElementTree as ET  # dùng cho helper bóc bảng đầu trang
from .batch_tree_v2_local import tree_run
from .docx_org_tree_local import org_tree_run
try:
    import docx as _docx  # đảm bảo import trong môi trường runtime
except Exception:
    raise ImportError("Chưa cài python-docx. Cài: pip install python-docx lxml")

# ========================
# Cấu hình
# ========================
USE_OCR_FALLBACK = True         # Bật OCR fallback cho PDF
DOCX_DROP_HEADERS = False       # GIỮ header/footer của DOCX (như yêu cầu hiện tại)
PDF_DROP_HEADERS = True         # PDF thường lặp header theo trang -> nên True
TABLE_MODE = "flatten"          # 'flatten' như bạn đang dùng
KEEP_TABLES = True
LATEX_MATH = True

# De-dup nâng cao
DEDUP_NORMALIZE = True          # chuẩn hoá chuỗi khi khử trùng lặp
DEDUP_LOWERCASE = True          # so sánh ở dạng lowercase

# ========================
# OCR (EasyOCR) — tùy chọn
# ========================
try:
    import easyocr
    import numpy as np
    from PIL import Image
    import io
    _easyocr_reader = easyocr.Reader(["vi", "en"])
except Exception:
    USE_OCR_FALLBACK = False
    _easyocr_reader = None


# ========================
# Chuẩn hoá & khử trùng lặp
# ========================
import re
def _normalize_line(s: str) -> str:
    """Chuẩn hoá nhẹ để khử trùng lặp “gần giống”."""
    if s is None:
        return ""
    x = s
    # chuẩn hoá các ký tự thường gây chênh lệch
    x = x.replace("\u00A0", " ")   # non-breaking space
    x = x.replace("–", "-").replace("—", "-").replace("’", "'").replace("“", '"').replace("”", '"')
    x = re.sub(r"[ \t]+", " ", x)  # gộp khoảng trắng
    x = re.sub(r"\s+\n", "\n", x)
    x = re.sub(r"\n\s+", "\n", x)
    x = x.strip()
    if DEDUP_LOWERCASE:
        x = x.lower()
    return x

def _uniq_keep_order_norm(lines: List[str]) -> List[str]:
    """Khử trùng lặp theo khoá chuẩn hoá, giữ bản gốc đầu tiên."""
    if not DEDUP_NORMALIZE:
        seen = set()
        out = []
        for s in lines:
            if s not in seen:
                seen.add(s)
                out.append(s)
        return out

    seen_norm = set()
    out = []
    for s in lines:
        key = _normalize_line(s)
        if key and key not in seen_norm:
            seen_norm.add(key)
            out.append(s.strip())
    return out


# ========================
# PDF helpers
# ========================
def _extract_text(page: fitz.Page) -> str:
    """Ưu tiên trích xuất dict/spans để hạn chế rớt ký tự."""
    try:
        data = page.get_text("dict")
        out = []
        for b in data.get("blocks", []):
            for ln in b.get("lines", []):
                out.append("".join(sp.get("text", "") for sp in ln.get("spans", [])))
        txt = "\n".join(out)
        if txt.strip():
            return txt
    except Exception:
        pass
    return page.get_text() or ""


def _ocr_image(pix: fitz.Pixmap) -> str:
    """OCR 1 trang PDF bằng EasyOCR."""
    if not USE_OCR_FALLBACK or _easyocr_reader is None:
        return ""
    img_bytes = pix.tobytes("png")
    img = np.array(Image.open(io.BytesIO(img_bytes)))
    try:
        results = _easyocr_reader.readtext(img, detail=0, paragraph=True)
    except Exception:
        results = []
    return "\n".join(results)


def _process_pdf(pdf_path: str) -> str:
    """Xử lý file PDF → text (có OCR fallback)."""
    doc = fitz.open(pdf_path)
    page_texts: List[str] = []

    for page in doc:
        raw = _extract_text(page)

        # OCR fallback nếu trang gần như rỗng
        if USE_OCR_FALLBACK and len(raw.strip()) < 40:
            try:
                raw = (raw + "\n" + _ocr_image(page.get_pixmap(dpi=200))).strip()
            except Exception as e:
                print(f"⚠️ OCR lỗi tại {pdf_path}: {e}")

        cleaned = clean_page_text(
            raw,
            drop_headers=PDF_DROP_HEADERS,
            keep_tables=KEEP_TABLES,
            table_mode=TABLE_MODE,
            latex_math=LATEX_MATH,
        )
        page_texts.append(cleaned)

    doc.close()
    combined = "\n\n".join([p for p in page_texts if p.strip()])

    # Nếu cả file rỗng → OCR toàn file
    if not combined.strip() and USE_OCR_FALLBACK:
        print(f"⚠️ File PDF rỗng, chạy OCR toàn file: {pdf_path}")
        all_text = []
        for page in fitz.open(pdf_path):
            ocr = _ocr_image(page.get_pixmap(dpi=200))
            if ocr.strip():
                all_text.append(ocr)
        combined = "\n\n".join(all_text)

    return combined


# ========================
# DOCX helpers
# ========================
def _table_lines(tbl) -> List[str]:
    lines = []
    for row in tbl.rows:
        txt = "\t".join((cell.text or "").strip() for cell in row.cells).strip()
        if txt:
            lines.append(txt)
    return lines


def _hf_to_lines(hf) -> List[str]:
    """Lấy text từ 1 header/footer: paragraphs + tables."""
    if hf is None:
        return []
    lines = []
    for p in hf.paragraphs:
        t = (p.text or "").strip()
        if t:
            lines.append(t)
    for tbl in hf.tables:
        lines.extend(_table_lines(tbl))
    return lines


def _extract_hf_python_docx(document) -> Tuple[List[str], List[str]]:
    """Quét tất cả header/footer của mọi section (default/first/even)."""
    headers, footers = [], []
    for sec in document.sections:
        # default
        headers += _hf_to_lines(sec.header)
        footers += _hf_to_lines(sec.footer)
        # first page
        try:
            headers += _hf_to_lines(sec.first_page_header)
            footers += _hf_to_lines(sec.first_page_footer)
        except Exception:
            pass
        # even pages
        try:
            headers += _hf_to_lines(sec.even_page_header)
            footers += _hf_to_lines(sec.even_page_footer)
        except Exception:
            pass
    return headers, footers


def _uniq_keep_order(lines: List[str]) -> List[str]:
    seen = set()
    out = []
    for s in lines:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _extract_hf_xml(docx_path: str) -> Tuple[List[str], List[str]]:
    """
    Fallback: bóc zip và đọc trực tiếp header*.xml/footer*.xml để bắt text (kể cả trong shapes/textboxes).
    """
    if not LXML_OK:
        return [], []
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    headers, footers = [], []
    with zipfile.ZipFile(docx_path) as z:
        for name in z.namelist():
            if name.startswith("word/header") and name.endswith(".xml"):
                root = etree.fromstring(z.read(name))
                for p in root.xpath(".//w:p", namespaces=ns):
                    txt = "".join(p.xpath(".//w:t/text()", namespaces=ns)).strip()
                    if txt:
                        headers.append(txt)
            if name.startswith("word/footer") and name.endswith(".xml"):
                root = etree.fromstring(z.read(name))
                for p in root.xpath(".//w:p", namespaces=ns):
                    txt = "".join(p.xpath(".//w:t/text()", namespaces=ns)).strip()
                    if txt:
                        footers.append(txt)
    return headers, footers


def _extract_body_textboxes_xml(docx_path: str) -> List[str]:
    """
    Bắt thêm text trong shapes/textboxes ở phần thân tài liệu (document.xml).
    CHỈ lấy đoạn văn bên trong w:txbxContent để tránh trùng với paragraphs thường.
    """
    if not LXML_OK:
        return []
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    lines = []
    with zipfile.ZipFile(docx_path) as z:
        if "word/document.xml" not in z.namelist():
            return []
        root = etree.fromstring(z.read("word/document.xml"))
        # CHỈ bắt p bên trong textbox content
        for p in root.xpath(".//w:txbxContent//w:p", namespaces=ns):
            txt = "".join(p.xpath(".//w:t/text()", namespaces=ns)).strip()
            if txt:
                lines.append(txt)
    return lines


def _extract_top_tables_as_rows(docx_path: str, max_tables: int = 2) -> List[str]:
    """
    BẮT "head" dạng BẢNG ở đầu tài liệu (document.xml).
    Lấy N bảng đầu tiên; trả về từng hàng nối bằng '\t' để giữ cột.
    Dùng ET (stdlib) cho chắc chắn kể cả khi lxml không có.
    """
    try:
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        with zipfile.ZipFile(docx_path) as zf:
            root = ET.fromstring(zf.read('word/document.xml'))
        tables = root.findall('.//w:tbl', ns)[:max_tables]

        def norm(s: str) -> str:
            s = s or ''
            s = s.replace("\u00A0", " ")
            s = ' '.join(s.split())
            return s

        lines = []
        for tbl in tables:
            for tr in tbl.findall('.//w:tr', ns):
                cells = []
                for tc in tr.findall('.//w:tc', ns):
                    texts = [t.text for t in tc.findall('.//w:t', ns) if t.text]
                    cells.append(norm(''.join(texts)))
                line = ' \t '.join(c for c in cells if c)
                if line.strip():
                    lines.append(line)
        return lines
    except Exception:
        # Không có bảng/không đọc được -> trả rỗng
        return []


def _process_docx(docx_path: str) -> str:
    """Xử lý file DOCX → text (paragraph + bảng + header/footer, có XML fallback + head từ bảng)."""
    document = _docx.Document(docx_path)

    # 1) Header/Footer bằng python-docx (đủ default/first/even, tables)
    hdr_lines, ftr_lines = _extract_hf_python_docx(document)

    # 2) Fallback: nếu thiếu, đọc XML thẳng từ .docx (chỉ bổ sung phần thiếu)
    if LXML_OK and (not hdr_lines or not ftr_lines):
        hdr2, ftr2 = _extract_hf_xml(docx_path)
        if not hdr_lines:
            hdr_lines = hdr2
        if not ftr_lines:
            ftr_lines = ftr2

    # 3) BẮT RIÊNG “HEAD” dạng BẢNG ở đầu tài liệu (nằm trong body)
    top_table_head = _extract_top_tables_as_rows(docx_path, max_tables=1)

    # 4) Thân tài liệu: paragraphs + tables (python-docx)
    para_lines = [(p.text or "").strip() for p in document.paragraphs if (p.text or "").strip()]
    body_tables = []
    for tbl in document.tables:
        body_tables.extend(_table_lines(tbl))

    # 5) Textboxes/shapes (body) chỉ từ w:txbxContent
    body_from_xml = _extract_body_textboxes_xml(docx_path)

    # 6) GHÉP + KHỬ TRÙNG LẶP TOÀN CỤM
    #    Thứ tự ưu tiên: head(bảng) -> header -> paragraphs -> bảng thân -> textbox -> footer
    #    Dùng de-dup chuẩn hoá để loại bỏ lặp do khác khoảng trắng/ký tự.
    parts = []
    if top_table_head:
        parts.extend(top_table_head)
    if not DOCX_DROP_HEADERS and hdr_lines:
        parts.extend(hdr_lines)
    parts.extend(para_lines)
    if body_tables:
        parts.extend(body_tables)
    if body_from_xml:
        parts.extend(body_from_xml)
    if not DOCX_DROP_HEADERS and ftr_lines:
        parts.extend(ftr_lines)

    all_lines = _uniq_keep_order_norm([ln for ln in parts if ln and ln.strip()])
    combined = "\n".join(all_lines)

    # 7) Clean cuối: vẫn không drop header với DOCX (giữ head)
    return clean_page_text(
        combined,
        drop_headers=DOCX_DROP_HEADERS,   # False -> GIỮ header/footer
        keep_tables=KEEP_TABLES,
        table_mode=TABLE_MODE,
        latex_math=LATEX_MATH,
    )


# ========================
# Orchestrator
# ========================
def process_documents(input_folder: str, output_folder: str = None) -> Dict[str, str]:
    """
    Trích xuất toàn bộ PDF/DOCX → TXT (duyệt cả thư mục con).
    Nếu output_folder=None thì file TXT sẽ được lưu cùng thư mục với file gốc.
    Nếu có output_folder thì giữ nguyên cấu trúc thư mục con bên trong.
    Trả về dict {txt_relpath: content}.
    """
    input_folder = os.path.abspath(input_folder)
    if output_folder:
        output_folder = os.path.abspath(output_folder)

    results: Dict[str, str] = {}

    for root, _, files in os.walk(input_folder):
        for filename in files:
            # Bỏ qua file tạm của Word (~$...)
            if filename.startswith("~$"):
                continue
            if not filename.lower().endswith((".pdf", ".docx")):
                continue

            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(root, input_folder)  # giữ cấu trúc thư mục
            txt_filename = os.path.splitext(filename)[0] + ".txt"

            # Thư mục đích
            if output_folder:
                target_dir = os.path.join(output_folder, rel_path)
            else:
                target_dir = root

            os.makedirs(target_dir, exist_ok=True)
            txt_path = os.path.join(target_dir, txt_filename)

            print(f"🔍 Đang xử lý: {file_path}")

            if filename.lower().endswith(".pdf"):
                combined = _process_pdf(file_path)
            else:  # .docx
                combined = _process_docx(file_path)

            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(combined)

            results[os.path.join(rel_path, txt_filename)] = combined

    print("✅ Hoàn tất xử lý tất cả file PDF/DOCX.")
    return results


# ========================
# CLI wrapper theo layout của bạn
# ========================
def processing_Data_doclinkToText(input_dir = "./Documents/HR/txt", output_dir = "./src/app/Data/HR/txt", 
                                input_txt_diagram = "./Documents/HR/Diagram/documents_workflowAndText", 
                                output_txt_diagram = "./src/app/Data/HR/Diagram/documents_workflowAndText",
                                input_dir_org_tree = "./Documents/HR/Diagram/procedure",
                                output_dir_org_tree = "./src/app/Data/HR/Diagram/procedure"):
    process_documents(input_dir, output_dir)
    stats = tree_run(input_txt_diagram, output_txt_diagram)
    org_tree_run(input_dir_org_tree, output_dir_org_tree)

def processing_Data_dockinkToText_v2 (input_dir, output_dir):
    process_documents(input_dir, output_dir)

