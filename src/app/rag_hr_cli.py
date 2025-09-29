import sys
from rag_hr.engine_hr import answer_with_rag

def main():
    q = " ".join(sys.argv[1:]).strip() or "sơ đồ nhân viên công ty tixmax"
    ans, _ = answer_with_rag(q)
    print("\n===== ANSWER =====\n" + ans)

if __name__ == "__main__":
    main()