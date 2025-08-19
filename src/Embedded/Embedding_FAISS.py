import os
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from Processing_Data.pdf_to_text import process_pdf_documents
from Processing_Data.all_path import path_Documents_folder


def create_faiss_index():
    documents_folder, output_folder = path_Documents_folder()

    print("📄 Đang xử lý và làm sạch các file PDF...")
    raw_data = process_pdf_documents(documents_folder, output_folder)

    print("📚 Đang chuyển đổi dữ liệu sang định dạng Document...")
    documents = [
        Document(page_content=content, metadata={"source": filename})
        for filename, content in raw_data.items()
    ]

    # 4. Cắt nhỏ tài liệu
    print("✂️ Đang chia tài liệu thành các đoạn nhỏ...")
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=200)
    chunks = splitter.split_documents(documents)

    # 5. Tạo embedding model
    print("🔍 Đang tạo embedding model...")
    embedding_model = HuggingFaceEmbeddings(
        model_name="intfloat/e5-large-v2",
        encode_kwargs={"normalize_embeddings": True}
    )

    # 6. Tạo FAISS index từ các đoạn văn bản
    print("⚙️ Đang tạo FAISS index...")
    faiss_index = FAISS.from_documents(chunks, embedding_model)

    # 7. Lưu FAISS index ra thư mục
    index_path = "../FAISS_Vector"
    faiss_index.save_local(index_path)
    print(f"✅ FAISS Index đã được lưu thành công tại: {index_path}")


if __name__ == "__main__":
    create_faiss_index()
