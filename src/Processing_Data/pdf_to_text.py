import fitz
import os
from main import clean_page_text
from all_path import *
def process_pdf_documents(input_folder: str, output_folder: str = "src/Data") -> dict:
    """
    Xử lý toàn bộ PDF trong thư mục đầu vào.
    Lưu bản .txt vào output_folder.
    Trả về dict chứa tên file và nội dung đã làm sạch.
    """
    input_folder = os.path.abspath(input_folder)
    os.makedirs(output_folder, exist_ok=True)

    dataset = {}  # Lưu nội dung văn bản đã xử lý

    for filename in os.listdir(input_folder):
        if filename.endswith(".pdf"):
            pdf_path = os.path.join(input_folder, filename)
            txt_filename = os.path.splitext(filename)[0] + ".txt"
            txt_path = os.path.join(output_folder, txt_filename)

            print(f"🔍 Đang xử lý: {filename}")
            doc = fitz.open(pdf_path)

            full_text = []

            for page in doc:
                text = page.get_text()
                cleaned_text = clean_page_text(text)
                full_text.append(cleaned_text)

            combined_text = "\n\n".join(full_text)

            # Ghi ra file txt
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(combined_text)
                

            # Lưu vào dataset trả về
            dataset[filename] = combined_text
            doc.close()

    print("✅ Hoàn tất xử lý tất cả file PDF.")
    return dataset

# documents_folder, output_folder = path_Documents_folder()
# process_pdf_documents(documents_folder, output_folder)
