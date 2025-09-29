#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
from rag_hr.engine_hr import answer_with_rag, build_lex_query

def main():
    q = " ".join(sys.argv[1:]).strip() or "sơ đồ nhân viên công ty tiximax"
    info = build_lex_query(q)
    print("[Expanded]", info.get("lex_query"))
    ans, _ = answer_with_rag(q)
    print("\n===== ANSWER =====\n" + ans)

if __name__ == "__main__":
    main()
