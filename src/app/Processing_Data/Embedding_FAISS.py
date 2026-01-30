import os
import re
import sys
from typing import Dict, List
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from pinecone import Pinecone, ServerlessSpec
from langchain_pinecone import PineconeVectorStore
import torch
import time

# Import các module xử lý documents của bạn
from pdf_to_text import process_documents
from xlxs_to_txt import batch_convert_to_txt

try:
    from .Prosessing_HR.pdf_to_text_HR import processing_Data_doclinkToText
    # from .DataBase_Web.web_crawler import web_crawler
except ImportError:
    try:
        # from DataBase_Web.web_crawler import web_crawler
        from Prosessing_HR.pdf_to_text_HR import processing_Data_doclinkToText
    except:
        print("⚠️  Warning: Some import modules not found, skipping...")
        web_crawler = None
        processing_Data_doclinkToText = None

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("⚠️  python-dotenv not installed. Using system environment variables.")

# ============================================================================
# CONFIGURATION
# ============================================================================

CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", 1000))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", 300))
if CHUNK_OVERLAP >= CHUNK_SIZE:
    CHUNK_OVERLAP = max(0, CHUNK_SIZE // 4)

SEPARATORS = ["\n\n", "\n", ". ", " ", ""]

# Directories
DOCS_DIR = "./Documents/Data_All"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.abspath(os.path.join(BASE_DIR, "../Data/Data_All/"))

# Pinecone configuration
PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.environ.get("PINECONE_INDEX_NAME", "vietnamese-chatbot")
PINECONE_DIMENSION = 384 

# Embedding model
EMBED_MODEL_NAME = os.environ.get(
    "EMBED_MODEL_DIR", 
    "intfloat/multilingual-e5-small"
)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _select_device() -> str:
    """Chọn device tối ưu cho embedding"""
    if torch.backends.mps.is_available():
        print("🟢 Using MPS (Apple GPU)")
        return "mps"
    elif torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        print(f"🟢 Using CUDA GPU: {gpu_name}")
        return "cuda"
    else:
        print("🟡 Using CPU")
        return "cpu"


def _clean_text(s: str) -> str:
    """Làm sạch văn bản"""
    if not s:
        return ""
    s = re.sub(r"\s+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()


def _load_text_files(folder: str) -> Dict[str, str]:
    """
    Đọc đệ quy toàn bộ *.txt trong `folder`, bỏ qua mọi file tên 'urls.txt'.
    Trả về dict: {relative_path: text_content}
    """
    data: Dict[str, str] = {}
    folder = os.path.abspath(folder)
    if not os.path.isdir(folder):
        print(f"⚠️  Không tìm thấy thư mục: {folder}", file=sys.stderr)
        return data

    excluded = {"urls.txt"}
    loaded, skipped = 0, 0

    for root, _dirs, files in os.walk(folder):
        for fn in files:
            if not fn.lower().endswith(".txt"):
                continue
            if fn.lower() in excluded:
                skipped += 1
                continue

            path = os.path.join(root, fn)
            rel_name = os.path.relpath(path, folder)

            try:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        txt = f.read()
                except UnicodeDecodeError:
                    with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
                        txt = f.read()
                if txt:
                    data[rel_name] = txt
                    loaded += 1
                else:
                    skipped += 1
            except Exception as e:
                skipped += 1
                print(f"⚠️  Lỗi đọc file {rel_name}: {e}", file=sys.stderr)

    print(f"📄 Loaded {loaded} .txt files (skipped {skipped}) from {folder}")
    return data


def create_embedding_model() -> HuggingFaceEmbeddings:
    """Tạo embedding model"""
    device = _select_device()
    batch_size = 64 if device == 'cuda' else 16
    
    model_kwargs = {"device": device}
    
    # Optional quantization
    if os.environ.get("EMBED_QUANTIZE", "0") == "1":
        try:
            from transformers import BitsAndBytesConfig
            model_kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_8bit=True
            )
            print("✅ Using 8-bit quantization")
        except ImportError:
            print("⚠️  BitsAndBytes not available, skipping quantization")
    
    # Khởi tạo embedding, fallback nếu phiên bản sentence-transformers
    # không hỗ trợ tham số `quantization_config`.
    try:
        embedding = HuggingFaceEmbeddings(
            model_name=EMBED_MODEL_NAME,
            model_kwargs=model_kwargs,
            encode_kwargs={
                "normalize_embeddings": True,
                "batch_size": batch_size
            }
        )
    except TypeError as e:
        # Trường hợp phổ biến: SentenceTransformer.__init__() không chấp nhận
        # keyword argument 'quantization_config'. Khi đó bỏ quantization và chạy lại.
        if "quantization_config" in str(e):
            print("⚠️  Current sentence-transformers version does not support "
                  "`quantization_config`. Retrying without quantization...")
            model_kwargs.pop("quantization_config", None)
            embedding = HuggingFaceEmbeddings(
                model_name=EMBED_MODEL_NAME,
                model_kwargs=model_kwargs,
                encode_kwargs={
                    "normalize_embeddings": True,
                    "batch_size": batch_size
                }
            )
        else:
            raise
    
    print(f"✅ Embedding model loaded: {EMBED_MODEL_NAME} on {device}")
    return embedding


# ============================================================================
# PINECONE FUNCTIONS
# ============================================================================

def initialize_pinecone():
    """
    Khởi tạo Pinecone client và tạo index nếu cần
    """
    if not PINECONE_API_KEY:
        raise ValueError(
            "❌ PINECONE_API_KEY not found!\n"
            "Please set it in .env file or environment:\n"
            "export PINECONE_API_KEY='your-api-key-here'"
        )
    
    print("\n" + "="*70)
    print("🔌 INITIALIZING PINECONE")
    print("="*70)
    print(f"📍 Index Name: {PINECONE_INDEX_NAME}")
    print(f"📐 Dimension: {PINECONE_DIMENSION}")
    
    # Khởi tạo Pinecone client
    pc = Pinecone(api_key=PINECONE_API_KEY)
    
    # Kiểm tra xem index đã tồn tại chưa
    existing_indexes = pc.list_indexes().names()
    
    if PINECONE_INDEX_NAME in existing_indexes:
        print(f"✅ Index '{PINECONE_INDEX_NAME}' already exists")
        
        # Kiểm tra thông tin index
        index_stats = pc.Index(PINECONE_INDEX_NAME).describe_index_stats()
        print(f"📊 Current vectors: {index_stats.get('total_vector_count', 0)}")
        
        # Hỏi user có muốn xóa index cũ không
        response = input("\n⚠️  Do you want to DELETE existing index and create new? (yes/no): ")
        if response.lower() in ['yes', 'y']:
            print(f"🗑️  Deleting index '{PINECONE_INDEX_NAME}'...")
            pc.delete_index(PINECONE_INDEX_NAME)
            time.sleep(5)  # Wait for deletion
            existing_indexes = []
    
    # Tạo index mới nếu chưa có
    if PINECONE_INDEX_NAME not in existing_indexes:
        print(f"\n📝 Creating new Pinecone index: {PINECONE_INDEX_NAME}")
        print("⏳ This may take 1-2 minutes...")
        
        pc.create_index(
            name=PINECONE_INDEX_NAME,
            dimension=PINECONE_DIMENSION,
            metric='cosine',
            spec=ServerlessSpec(
                cloud='aws',
                region='us-east-1'  # Free tier region
            )
        )
        
        # Wait for index to be ready
        print("⏳ Waiting for index to be ready...")
        max_wait = 120  # 2 minutes
        waited = 0
        while waited < max_wait:
            try:
                index_info = pc.describe_index(PINECONE_INDEX_NAME)
                if index_info.status.get('ready', False):
                    print("✅ Index is ready!")
                    break
            except:
                pass
            time.sleep(5)
            waited += 5
            print(f"⏳ Still waiting... ({waited}s)")
        
        if waited >= max_wait:
            print("⚠️  Warning: Index creation timeout, but continuing...")
    
    print("="*70 + "\n")
    return pc


def upload_to_pinecone(chunks: List[Document], embedding_model: HuggingFaceEmbeddings):
    """
    Upload documents lên Pinecone
    """
    print("\n" + "="*70)
    print("⬆️  UPLOADING TO PINECONE")
    print("="*70)
    print(f"📦 Total chunks: {len(chunks)}")
    
    # Khởi tạo Pinecone
    pc = initialize_pinecone()
    
    # Tạo vectorstore
    print("\n🔗 Creating PineconeVectorStore...")
    vectorstore = PineconeVectorStore(
        index_name=PINECONE_INDEX_NAME,
        embedding=embedding_model
    )
    
    # Upload documents (có progress)
    print("\n⬆️  Uploading documents to Pinecone...")
    print("⏳ This may take several minutes depending on the number of chunks...")
    
    try:
        # Upload với batch để hiển thị progress
        batch_size = 100
        total_batches = (len(chunks) + batch_size - 1) // batch_size
        
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            batch_num = i // batch_size + 1
            
            print(f"📤 Uploading batch {batch_num}/{total_batches} ({len(batch)} chunks)...")
            vectorstore.add_documents(batch)
            
            # Show progress
            progress = (i + len(batch)) / len(chunks) * 100
            print(f"✅ Progress: {progress:.1f}% ({i + len(batch)}/{len(chunks)} chunks)")
        
        print("\n✅ All documents uploaded successfully!")
        
    except Exception as e:
        print(f"\n❌ Error uploading to Pinecone: {e}")
        raise
    
    # Verify upload
    print("\n🔍 Verifying upload...")
    index = pc.Index(PINECONE_INDEX_NAME)
    stats = index.describe_index_stats()
    total_vectors = stats.get('total_vector_count', 0)
    
    print(f"📊 Total vectors in Pinecone: {total_vectors}")
    
    if total_vectors == 0:
        print("⚠️  Warning: No vectors found in index. Upload may have failed.")
    elif total_vectors < len(chunks):
        print(f"⚠️  Warning: Expected {len(chunks)} vectors, but found {total_vectors}")
    else:
        print(f"✅ Upload verified! All {total_vectors} vectors are in Pinecone.")
    
    print("="*70 + "\n")
    
    return vectorstore


# ============================================================================
# MAIN FUNCTION
# ============================================================================

def main_All():
    """
    Main function - Build vectorstore với Pinecone
    """
    print("\n" + "="*70)
    print("🚀 VIETNAMESE CHATBOT - PINECONE VECTORSTORE BUILDER")
    print("="*70)
    print(f"📂 Data Directory: {DATA_DIR}")
    print(f"☁️  Database: Pinecone")
    print(f"📍 Index: {PINECONE_INDEX_NAME}")
    print("="*70 + "\n")
    
    # Check API key
    if not PINECONE_API_KEY:
        print("\n❌ ERROR: PINECONE_API_KEY not found!")
        print("\nPlease set it:")
        print("1. Create .env file with: PINECONE_API_KEY=your-key")
        print("2. Or export: export PINECONE_API_KEY='your-key'")
        return
    
    # Tạo thư mục
    os.makedirs(DATA_DIR, exist_ok=True)
    
    # ========================================================================
    # BƯỚC 1: PROCESS DOCUMENTS
    # ========================================================================
    print("\n📄 BƯỚC 1: PROCESSING DOCUMENTS")
    print("-" * 70)
    
    process_documents(DOCS_DIR, DATA_DIR)
    
    # batch_convert_to_txt(
    #     input_dir="./Documents/Sales",
    #     output_dir="./src/app/Data/Data_All/Sales"
    # )
    
    # process_documents(
    #     input_folder="./Documents/Regulation",
    #     output_folder="./src/app/Data/Data_All/Regulation"
    # )
    # process_documents(
    #     input_folder="./Documents/Warehouse",
    #     output_folder="./src/app/Data/Data_All/Warehouse"
    # )
    process_documents(
        input_folder="./Documents/Accountant",
        output_folder="./src/app/Data/Data_All/Accountant"
    )
    # process_documents(
    #     input_folder="./Documents/Operate",
    #     output_folder="./src/app/Data/Data_All/Operate"
    # )
    
    # if web_crawler:
    #     web_crawler("Data_All")
    
    if processing_Data_doclinkToText:
        processing_Data_doclinkToText(
            input_dir="./Documents/HR/txt",
            output_dir="./src/app/Data/Data_All/txt",
            input_txt_diagram="./Documents/HR/Diagram/documents_workflowAndText",
            output_txt_diagram="./src/app/Data/Data_All/Diagram/documents_workflowAndText",
            input_dir_org_tree="./Documents/HR/Diagram/procedure",
            output_dir_org_tree="./src/app/Data/Data_All/Diagram/procedure"
        )
    
    # ========================================================================
    # BƯỚC 2: LOAD TEXT FILES
    # ========================================================================
    print("\n📂 BƯỚC 2: LOADING TEXT FILES")
    print("-" * 70)
    
    raw = _load_text_files(DATA_DIR)
    if not raw:
        raise RuntimeError(f"Không có TXT trong {DATA_DIR}")
    
    # ========================================================================
    # BƯỚC 3: CREATE DOCUMENTS
    # ========================================================================
    print("\n📝 BƯỚC 3: CREATING DOCUMENTS")
    print("-" * 70)
    
    docs: List[Document] = []
    for fname, text in raw.items():
        t = _clean_text(text)
        if not t:
            continue
        docs.append(Document(
            page_content=t,
            metadata={"source": fname, "page": -1}
        ))
    
    print(f"✅ Created {len(docs)} documents")
    
    # ========================================================================
    # BƯỚC 4: SPLIT DOCUMENTS
    # ========================================================================
    print("\n✂️  BƯỚC 4: SPLITTING DOCUMENTS")
    print("-" * 70)
    
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=SEPARATORS,
        add_start_index=True,
    )
    chunks = splitter.split_documents(docs)
    
    for i, d in enumerate(chunks):
        d.metadata["chunk_id"] = i
    
    print(f"✅ Created {len(chunks)} chunks")
    print(f"   - Chunk size: {CHUNK_SIZE}")
    print(f"   - Overlap: {CHUNK_OVERLAP}")
    
    # ========================================================================
    # BƯỚC 5: CREATE EMBEDDING MODEL
    # ========================================================================
    print("\n🤖 BƯỚC 5: LOADING EMBEDDING MODEL")
    print("-" * 70)
    
    embedding = create_embedding_model()
    
    # ========================================================================
    # BƯỚC 6: UPLOAD TO PINECONE
    # ========================================================================
    vectorstore = upload_to_pinecone(chunks, embedding)
    
    # ========================================================================
    # HOÀN THÀNH
    # ========================================================================
    print("\n" + "="*70)
    print("✅ HOÀN THÀNH!")
    print("="*70)
    print(f"☁️  Database: Pinecone")
    print(f"📍 Index: {PINECONE_INDEX_NAME}")
    print(f"📄 Total chunks: {len(chunks)}")
    print(f"🌐 Region: us-east-1 (AWS)")
    print("\n💡 Next steps:")
    print("   1. Test search: python test_pinecone_search.py")
    print("   2. Integrate with your chatbot")
    print("="*70 + "\n")


if __name__ == "__main__":
    main_All()



# import os
# import re
# import sys
# from typing import Dict, List
# from langchain_core.documents import Document
# from langchain_text_splitters import RecursiveCharacterTextSplitter
# from langchain_community.vectorstores import FAISS
# from langchain_huggingface import HuggingFaceEmbeddings 
# from pdf_to_text import process_documents
# import torch

# from xlxs_to_txt import batch_convert_to_txt
# try:
#     from .Prosessing_HR.pdf_to_text_HR import processing_Data_doclinkToText #, processing_Data_dockinkToText_v2
#     from .DataBase_Web.web_crawler import web_crawler
# except ImportError:
#     from DataBase_Web.web_crawler import web_crawler
#     from Prosessing_HR.pdf_to_text_HR import processing_Data_doclinkToText #, processing_Data_dockinkToText_v2

# CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", 1000))
# CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", 300))
# if CHUNK_OVERLAP >= CHUNK_SIZE:
#     CHUNK_OVERLAP = max(0, CHUNK_SIZE // 4)

# SEPARATORS = ["\n\n", "\n", ". ", " ", ""]
# DOCS_DIR = "./Documents/Data_All"
# BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# DATA_DIR = os.path.abspath(os.path.join(BASE_DIR, "../Data/Data_All"))
# INDEX_DIR = os.path.abspath(os.path.join(BASE_DIR, "../vectorstore/FAISS_Vector_Data_All"))
# EMBED_MODEL_NAME = os.environ.get("EMBED_MODEL_DIR", "./src/app/models/local_multilingual_e5_large")

# def _select_device() -> str:
#     if torch.backends.mps.is_available():
#         print("🟢 Using MPS (Apple GPU)")
#         return "mps"
#     elif torch.cuda.is_available():
#         gpu_name = torch.cuda.get_device_name(0)
#         print(f"🟢 Using CUDA GPU: {gpu_name}")
#         return "cuda"
#     else:
#         print("🟡 Defaulting to CPU")
#         return "cpu"

# def _clean_text(s: str) -> str:
#     if not s:
#         return ""
#     s = re.sub(r"\s+\n", "\n", s)
#     s = re.sub(r"\n{3,}", "\n\n", s)
#     s = re.sub(r"[ \t]{2,}", " ", s)
#     return s.strip()

# def _load_text_files(folder: str) -> Dict[str, str]:
#     """
#     Đọc đệ quy toàn bộ *.txt trong `folder`, bỏ qua mọi file tên 'urls.txt'.
#     Trả về dict: {relative_path: text_content}
#     """
#     data: Dict[str, str] = {}
#     folder = os.path.abspath(folder)
#     if not os.path.isdir(folder):
#         print(f"⚠️  Không tìm thấy thư mục: {folder}", file=sys.stderr)
#         return data

#     excluded = {"urls.txt"}
#     loaded, skipped = 0, 0

#     for root, _dirs, files in os.walk(folder):
#         for fn in files:
#             if not fn.lower().endswith(".txt"):
#                 continue
#             if fn.lower() in excluded:
#                 skipped += 1
#                 continue

#             path = os.path.join(root, fn)
#             rel_name = os.path.relpath(path, folder)

#             try:
#                 try:
#                     with open(path, "r", encoding="utf-8") as f:
#                         txt = f.read()
#                 except UnicodeDecodeError:
#                     with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
#                         txt = f.read()
#                 if txt:
#                     data[rel_name] = txt
#                     loaded += 1
#                 else:
#                     skipped += 1
#             except Exception as e:
#                 skipped += 1
#                 print(f"⚠️  Lỗi đọc file {rel_name}: {e}", file=sys.stderr)

#     print(f"📄 Loaded {loaded} .txt files (skipped {skipped}, excluded: {', '.join(sorted(excluded))}) from {folder}")
#     return data

# def main_All():
#     os.makedirs(INDEX_DIR, exist_ok=True)
#     os.makedirs(DATA_DIR, exist_ok=True)
#     process_documents(DOCS_DIR, DATA_DIR)
#     batch_convert_to_txt(input_dir="./Documents/Sales", output_dir="./src/app/Data/Data_All/Sales")
#     process_documents(input_folder="./Documents/Regulation", output_folder="./src/app/Data/Data_All/Regulation")
#     process_documents(input_folder="./Documents/Warehouse", output_folder="./src/app/Data/Data_All/Warehouse")
#     process_documents(input_folder="./Documents/Accountant", output_folder="./src/app/Data/Data_All/Accountant")
#     process_documents(input_folder="./Documents/Operate", output_folder="./src/app/Data/Data_All/Operate")
#     web_crawler("Data_All")
#     processing_Data_doclinkToText(input_dir = "./Documents/HR/txt", output_dir = "./src/app/Data/Data_All/txt", 
#                                 input_txt_diagram = "./Documents/HR/Diagram/documents_workflowAndText", output_txt_diagram = "./src/app/Data/Data_All/Diagram/documents_workflowAndText",
#                                 input_dir_org_tree = "./Documents/HR/Diagram/procedure", output_dir_org_tree = "./src/app/Data/Data_All/Diagram/procedure")
#     # processing_Data_dockinkToText_v2(input_dir="./Documents/Accountant", output_dir="./src/app/Data/Data_All/Accountant")
#     raw = _load_text_files(DATA_DIR)
#     if not raw:
#         raise RuntimeError(f"Không có TXT/CSV trong {DATA_DIR}")
#     docs: List[Document] = []
#     for fname, text in raw.items():
#         t = _clean_text(text)
#         if not t:
#             continue
#         docs.append(Document(page_content=t, metadata={"source": fname, "page": -1}))

#     splitter = RecursiveCharacterTextSplitter(
#         chunk_size=CHUNK_SIZE,
#         chunk_overlap=CHUNK_OVERLAP,
#         separators=SEPARATORS,
#         add_start_index=True,
#     )
#     chunks = splitter.split_documents(docs)
#     for i, d in enumerate(chunks):
#         d.metadata["chunk_id"] = i

#     device = _select_device()
#     batch = 64 if device=='cuda' and torch.cuda.mem_get_info()[0] > 8e9 else 16

#     device = _select_device()
#     model_kwargs = {"device": device}
#     if os.environ.get("EMBED_QUANTIZE", "0") == "1":
#         from transformers import BitsAndBytesConfig
#         model_kwargs["quantization_config"] = BitsAndBytesConfig(load_in_8bit=True)
#     emb = HuggingFaceEmbeddings(
#         model_name=EMBED_MODEL_NAME,
#         model_kwargs=model_kwargs,
#         encode_kwargs={"normalize_embeddings": True, "batch_size": batch},
#     )

#     print(f"⚙️ Building FAISS… (chunks={len(chunks)}, size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP}, device={device}, batch={batch})")
#     vs = FAISS.from_documents(chunks, emb)
#     vs.save_local(INDEX_DIR)
#     print(f"✅ FAISS index saved at: {INDEX_DIR}")
