from sentence_transformers import SentenceTransformer

model = SentenceTransformer("intfloat/e5-large-v2")
model.save("./src/models/local_e5_large_v2")
 