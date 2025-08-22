# file: pdf_to_txt.py
import fitz  # PyMuPDF
import os

def pdf_to_txt(input_pdf: str, output_txt: str = None) -> str:
    """
    Chuyển file PDF sang file TXT.
    - input_pdf: đường dẫn PDF đầu vào
    - output_txt: đường dẫn TXT đầu ra (nếu None thì tự tạo cùng tên với PDF)

    Trả về đường dẫn file TXT được tạo ra.
    """
    if not os.path.exists(input_pdf):
        raise FileNotFoundError(f"Không tìm thấy file PDF: {input_pdf}")

    if output_txt is None:
        base, _ = os.path.splitext(input_pdf)
        output_txt = base + ".txt"

    text_content = []
    with fitz.open(input_pdf) as doc:
        for page_num, page in enumerate(doc, start=1):
            text = page.get_text("text")  # lấy text gốc
            if not text.strip():
                text = page.get_text("blocks")  # fallback lấy block text
            text_content.append(f"=== Page {page_num} ===\n{text.strip()}\n")

    with open(output_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(text_content))

    return output_txt

if __name__ == "__main__":
    pdf_path = "input.pdf"
    txt_path = pdf_to_txt(pdf_path)
    print(f"Đã chuyển PDF -> TXT: {txt_path}")
