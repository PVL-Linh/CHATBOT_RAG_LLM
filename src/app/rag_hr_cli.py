import os, sys
from rag_hr.engine_hr import answer_with_rag

def main():
    q = " ".join(sys.argv[1:]).strip() or input("Hỏi gì: ").strip()
    print("[CFG] INDEX_DIR_HR =", os.environ.get("INDEX_DIR_HR"))
    print("[CFG] DATA_DIR_HR  =", os.environ.get("DATA_DIR_HR"))
    print("[CFG] FAISS_DIR_HR =", os.environ.get("FAISS_DIR_HR") or os.environ.get("INDEX_DIR_HR"))
    print("[CFG] FORCE_REBUILD_CORPUS_HR =", os.environ.get("FORCE_REBUILD_CORPUS_HR","0"))
    ans, trace = answer_with_rag(q)
    print("\n===== ANSWER =====\n" + ans)

if __name__ == "__main__":
    main()
