# import os
# from typing import Dict
# import fitz
# from Data_processing import clean_page_text
# import docx

# USE_OCR_FALLBACK = True
# try:
#     import pytesseract
#     from PIL import Image
#     import io
# except Exception:
#     USE_OCR_FALLBACK = False

# MIN_OCR_LEN = int(os.getenv("MIN_OCR_LEN", 40))
# OCR_DPI = int(os.getenv("OCR_DPI", 200))

# def _extract_text(page: fitz.Page) -> str:
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


# def _process_docx(docx_path: str) -> str:
#     """DOCX → text, có cả paragraph và bảng, rồi đưa qua clean_page_text."""
#     document = docx.Document(docx_path)
#     lines = []

#     # Paragraph thường
#     for p in document.paragraphs:
#         t = (p.text or "").strip()
#         if t:
#             lines.append(t)

#     # Bảng: gộp ô bằng tab
#     for tbl in document.tables:
#         for row in tbl.rows:
#             cells = [(cell.text or "").strip() for cell in row.cells]
#             line = "\t".join(c for c in cells if c)
#             if line:
#                 lines.append(line)

#     raw = "\n".join(lines)

#     cleaned = clean_page_text(
#         raw,
#         drop_headers=True,
#         keep_tables=True,
#         table_mode="flatten",
#         latex_math=True,
#     )
#     return cleaned


# # def process_pdf_documents(input_folder: str, output_folder: str = "src/app/Data/Data_All") -> Dict[str, str]:
# #     input_folder = os.path.abspath(input_folder)
# #     output_folder = os.path.abspath(output_folder)
# #     os.makedirs(output_folder, exist_ok=True)

# #     for filename in os.listdir(input_folder):
# #         if not filename.lower().endswith(".pdf"):
# #             continue

# #         pdf_path = os.path.join(input_folder, filename)
# #         txt_filename = os.path.splitext(filename)[0] + ".txt"
# #         txt_path = os.path.join(output_folder, txt_filename)

# #         print(f"🔍 Đang xử lý: {filename}")
# #         doc = fitz.open(pdf_path)
# #         page_texts = []

# #         for page in doc:
# #             raw = _extract_text(page)

# #             if USE_OCR_FALLBACK and len(raw.strip()) < MIN_OCR_LEN:
# #                 try:
# #                     pix = page.get_pixmap(dpi=200)
# #                     img = Image.open(io.BytesIO(pix.tobytes("png")))
# #                     ocr = pytesseract.image_to_string(img, lang="vie+eng")
# #                     raw = (raw + "\n" + (ocr or "")).strip()
# #                 except Exception:
# #                     pass

# #             cleaned = clean_page_text(
# #                 raw,
# #                 drop_headers=True,
# #                 keep_tables=True,
# #                 table_mode="flatten",
# #                 latex_math=True,
# #             )
# #             page_texts.append(cleaned)

# #         combined = "\n\n".join(page_texts)
# #         with open(txt_path, "w", encoding="utf-8") as f:
# #             f.write(combined)
# #         doc.close()

# #     print("✅ Hoàn tất xử lý tất cả file PDF.")


# def process_documents(input_folder: str, output_folder: str = "src/app/Data/Data_All") -> Dict[str, str]:
#     """
#     Xử lý toàn bộ PDF + DOCX trong input_folder (chỉ cấp hiện tại),
#     convert → .txt trong output_folder, dùng clean_page_text.
#     Trả về dict {txt_filename: text}.
#     """
#     input_folder = os.path.abspath(input_folder)
#     output_folder = os.path.abspath(output_folder)
#     os.makedirs(output_folder, exist_ok=True)

#     results: Dict[str, str] = {}

#     for filename in os.listdir(input_folder):
#         if filename.startswith("~$"):
#             continue

#         ext = os.path.splitext(filename)[1].lower()
#         if ext not in [".pdf", ".docx"]:
#             continue

#         in_path = os.path.join(input_folder, filename)
#         txt_filename = os.path.splitext(filename)[0] + ".txt"
#         txt_path = os.path.join(output_folder, txt_filename)

#         print(f"🔍 Đang xử lý: {filename}")

#         # ====== PDF ======
#         if ext == ".pdf":
#             doc = fitz.open(in_path)
#             page_texts = []

#             for page in doc:
#                 raw = _extract_text(page)

#                 if USE_OCR_FALLBACK and len(raw.strip()) < MIN_OCR_LEN:
#                     try:
#                         pix = page.get_pixmap(dpi=OCR_DPI)
#                         img = Image.open(io.BytesIO(pix.tobytes("png")))
#                         ocr = pytesseract.image_to_string(img, lang="vie+eng")
#                         raw = (raw + "\n" + (ocr or "")).strip()
#                     except Exception:
#                         pass

#                 cleaned = clean_page_text(
#                     raw,
#                     drop_headers=True,
#                     keep_tables=True,
#                     table_mode="flatten",
#                     latex_math=True,
#                 )
#                 page_texts.append(cleaned)

#             combined = "\n\n".join(page_texts)
#             doc.close()

#         # ====== DOCX ======
#         else:  # .docx
#             combined = _process_docx(in_path)

#         # Ghi file txt
#         with open(txt_path, "w", encoding="utf-8") as f:
#             f.write(combined)

#         results[txt_filename] = combined

#     print("✅ Hoàn tất xử lý tất cả file PDF/DOCX.")
#     return results



import os
from typing import Dict
import fitz
from Data_processing import clean_page_text
import docx

USE_OCR_FALLBACK = True
try:
    import pytesseract
    from PIL import Image
    import io
except Exception:
    USE_OCR_FALLBACK = False

MIN_OCR_LEN = int(os.getenv("MIN_OCR_LEN", 40))
OCR_DPI = int(os.getenv("OCR_DPI", 200))


def _extract_text(page: fitz.Page) -> str:
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


def _process_docx(docx_path: str) -> str:
    """DOCX → text (paragraph + bảng) → clean_page_text."""
    document = docx.Document(docx_path)
    lines = []

    # Paragraph
    for p in document.paragraphs:
        t = (p.text or "").strip()
        if t:
            lines.append(t)

    # Table
    for tbl in document.tables:
        for row in tbl.rows:
            cells = [(cell.text or "").strip() for cell in row.cells]
            line = "\t".join(c for c in cells if c)
            if line:
                lines.append(line)

    raw = "\n".join(lines)

    cleaned = clean_page_text(
        raw,
        drop_headers=True,
        keep_tables=True,
        table_mode="flatten",
        latex_math=True,
    )
    return cleaned


def process_documents(input_folder: str, output_folder: str = "src/app/Data/Data_All") -> Dict[str, str]:
    """
    Duyệt đệ quy toàn bộ thư mục input_folder,
    xử lý mọi file .pdf và .docx → .txt trong output_folder,
    giữ lại cấu trúc thư mục tương đối.
    """
    input_folder = os.path.abspath(input_folder)
    output_folder = os.path.abspath(output_folder)
    os.makedirs(output_folder, exist_ok=True)

    results: Dict[str, str] = {}

    for root, _, files in os.walk(input_folder):
        for filename in files:
            if filename.startswith("~$"):  # file tạm của Word
                continue

            ext = os.path.splitext(filename)[1].lower()
            if ext not in [".pdf", ".docx"]:
                continue

            in_path = os.path.join(root, filename)

            # Tính đường dẫn tương đối để mirror cấu trúc thư mục
            rel_root = os.path.relpath(root, input_folder)  # "" nếu cùng level
            out_dir = os.path.join(output_folder, rel_root) if rel_root != "." else output_folder
            os.makedirs(out_dir, exist_ok=True)

            base_name, _ = os.path.splitext(filename)
            txt_filename = base_name + ".txt"
            txt_path = os.path.join(out_dir, txt_filename)

            print(f"🔍 Đang xử lý: {os.path.join(rel_root, filename)}")

            # ====== PDF ======
            if ext == ".pdf":
                doc = fitz.open(in_path)
                page_texts = []

                for page in doc:
                    raw = _extract_text(page)

                    if USE_OCR_FALLBACK and len(raw.strip()) < MIN_OCR_LEN:
                        try:
                            pix = page.get_pixmap(dpi=OCR_DPI)
                            img = Image.open(io.BytesIO(pix.tobytes("png")))
                            ocr = pytesseract.image_to_string(img, lang="vie+eng")
                            raw = (raw + "\n" + (ocr or "")).strip()
                        except Exception:
                            pass

                    cleaned = clean_page_text(
                        raw,
                        drop_headers=True,
                        keep_tables=True,
                        table_mode="flatten",
                        latex_math=True,
                    )
                    page_texts.append(cleaned)

                combined = "\n\n".join(page_texts)
                doc.close()

            # ====== DOCX ======
            else:  # .docx
                combined = _process_docx(in_path)

            # Ghi file txt
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(combined)

            # key là đường dẫn txt tương đối để tiện debug
            results[os.path.join(rel_root, txt_filename)] = combined

    print("✅ Hoàn tất xử lý tất cả file PDF/DOCX (đệ quy).")
    return results
