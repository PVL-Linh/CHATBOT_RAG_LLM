from sentence_transformers import SentenceTransformer

# Tải multilingual-e5-large từ HuggingFace Hub
model = SentenceTransformer("intfloat/multilingual-e5-base")

# Lưu xuống thư mục local
model.save("./src/app/models/local_multilingual_e5_base")
