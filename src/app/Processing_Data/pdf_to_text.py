import os
from typing import Dict
import fitz
from Data_processing import clean_page_text

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

def process_pdf_documents(input_folder: str, output_folder: str = "src/app/Data/Data_All") -> Dict[str, str]:
    input_folder = os.path.abspath(input_folder)
    output_folder = os.path.abspath(output_folder)
    os.makedirs(output_folder, exist_ok=True)

    for filename in os.listdir(input_folder):
        if not filename.lower().endswith(".pdf"):
            continue

        pdf_path = os.path.join(input_folder, filename)
        txt_filename = os.path.splitext(filename)[0] + ".txt"
        txt_path = os.path.join(output_folder, txt_filename)

        print(f"🔍 Đang xử lý: {filename}")
        doc = fitz.open(pdf_path)
        page_texts = []

        for page in doc:
            raw = _extract_text(page)

            if USE_OCR_FALLBACK and len(raw.strip()) < MIN_OCR_LEN:
                try:
                    pix = page.get_pixmap(dpi=200)
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
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(combined)
        doc.close()

    print("✅ Hoàn tất xử lý tất cả file PDF.")
