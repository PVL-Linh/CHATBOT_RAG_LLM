import fitz  # PyMuPDF
import os

def pdf_to_txt(input_pdf: str, output_txt: str = None):
    if not os.path.exists(input_pdf):
        raise FileNotFoundError(f"Không tìm thấy file PDF: {input_pdf}")

    if output_txt is None:
        base, _ = os.path.splitext(input_pdf)
        output_txt = base + ".txt"

    text_content = []
    with fitz.open(input_pdf) as doc:
        for page_num, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
            if not text.strip():
                blocks = page.get_text("blocks")
                try:
                    text = "\n".join(b[4] for b in blocks if isinstance(b, (list, tuple)) and len(b) >= 5)
                except:
                    text = ""
            text_content.append(f"=== Page {page_num} ===\n{text.strip()}\n")

    full_text = "\n".join(text_content)

    with open(output_txt, "w", encoding="utf-8") as f:
        f.write(full_text)

    return {"text": full_text, "txt_path": output_txt}
