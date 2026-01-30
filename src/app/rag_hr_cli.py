from __future__ import annotations
import os
import sys
import argparse
import json
import re
from typing import Any, Dict, List

CUR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CUR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

init_app = os.path.join(CUR, "__init__.py")
if not os.path.exists(init_app):
    try:
        open(init_app, "a", encoding="utf-8").close()
    except Exception:
        pass

try:
    from rag_hr.engine_hr import answer_with_rag, continue_with_last
except Exception as e_a:
    try:
        from app.Model_LLM.hr import answer_with_rag, continue_with_last
    except Exception as e_b:
        print("[ERR] Không import được engine HR.")
        print("Hãy đảm bảo một trong hai layout sau tồn tại:")
        print("  A) <project_root>/rag_hr/engine_hr.py  (khuyên dùng)")
        print("  B) <project_root>/app/Model_LLM/hr/engine_hr.py")
        print("\nChi tiết lỗi:")
        print(" - rag_hr.engine_hr:", repr(e_a))
        print(" - app.Model_LLM.hr:", repr(e_b))
        sys.exit(1)

def _color(s: str, name: str) -> str:
    if not sys.stdout.isatty():
        return s
    C = {"cyan":"\033[36m","green":"\033[32m","yellow":"\033[33m","magenta":"\033[35m","reset":"\033[0m"}
    c = C.get(name, ""); r = C["reset"] if c else ""
    return f"{c}{s}{r}"

def _truncate(s: str, n: int) -> str:
    return s if not s or len(s) <= n else s[: n - 1] + "…"

def _print_header(title: str):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)

def _print_answer(ans: str):
    print(_color("Answer:", "green"))
    print(ans if ans else "(empty)")

def _print_trace(trace: List[Dict[str, Any]], max_text: int = 240):
    if not trace:
        print("(trace rỗng)")
        return
    print(_color(f"Trace ({len(trace)} items):", "yellow"))
    for i, t in enumerate(trace[:50]):
        src = t.get("source"); cid = t.get("chunk_id"); sc  = t.get("score")
        txt = _truncate((t.get("text") or "").replace("\n", " "), max_text)
        h = f"  {i+1:02d}. [{src}|{cid}]"
        if sc is not None:
            h += f" score={sc:.4f}"
        print(h)
        print(f"      {txt}")

FOLLOWUP_REDRAW_PAT = re.compile(
    r"\b(v[eê]̃?\s*l[ạ]i|ve lai|draw\s*again|redraw|show\s*again|hi[ẹ]n thị lại|v[ẽ]\s*ti[ế]p)\b", re.I)
FOLLOWUP_BRANCH_PAT = re.compile(
    r"(?:nh[á]nh|branch|ph[à]n|b[ộ]\s*ph[ậ]n|team)\s*[a-zA-Z0-9À-ỹ \-_]+", re.I)

def _as_json(ans: str, trace: List[Dict[str, Any]]):
    print(json.dumps({"answer": ans, "trace": trace}, ensure_ascii=False, indent=2))

BANNER = _color(
    r"""
        HR RAG CLI (app/)
        ────────────
        Lệnh nhanh:
        --ask  "Câu hỏi"          Hỏi 1 câu
        --cont "Câu follow-up"    Tiếp tục/vẽ lại (giữ cùng nguồn lần trước)
        Gợi ý chạy:
        python app/rag_hr_cli.py --ask "Sơ đồ tổ chức"
        """,
            "cyan",
        )

def build_parser():
    p = argparse.ArgumentParser(description="CLI test cho HR RAG (app/)")
    p.add_argument("--ask", "-q", type=str, help="Câu hỏi đầu vào")
    p.add_argument("--cont", type=str, help="Câu follow-up (vẽ lại/nhánh)")
    p.add_argument("--json", action="store_true", help="In kết quả dạng JSON")
    p.add_argument("--trace", action="store_true", help="Hiển thị trace")
    p.add_argument("--max-trace-text", type=int, default=240, help="Giới hạn ký tự mỗi dòng trace")
    p.add_argument("--rebuild-corpus", action="store_true", help="FORCE_REBUILD_CORPUS_HR=1 (BM25)")
    p.add_argument("--dotenv", type=str, default=os.environ.get("DOTENV_PATH", ""), help="Chỉ định .env (nếu cần)")
    return p

def _apply_env(args: argparse.Namespace):
    if args.dotenv:
        os.environ["DOTENV_PATH"] = args.dotenv
    if args.rebuild_corpus:
        os.environ["FORCE_REBUILD_CORPUS_HR"] = "1"

def run_once_ask(q: str, show_json: bool, show_trace: bool, max_trace_text: int):
    _print_header("ASK")
    print(_color(f"Q: {q}", "magenta"))
    ans, trace = answer_with_rag(q)
    if show_json:
        _as_json(ans, trace)
    else:
        _print_answer(ans)
        if show_trace:
            _print_trace(trace, max_text=max_trace_text)

def run_once_cont(q: str, show_json: bool, show_trace: bool, max_trace_text: int):
    _print_header("CONTINUE")
    print(_color(f"Follow-up: {q}", "magenta"))
    ans, trace = continue_with_last(q)
    if show_json:
        _as_json(ans, trace)
    else:
        _print_answer(ans)
        if show_trace:
            _print_trace(trace, max_text=max_trace_text)

def repl(show_trace_default: bool, max_trace_text: int):
    print(BANNER)
    while True:
        try:
            raw = input(_color("hr> ", "cyan")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not raw:
            continue
        if raw in (":q", ":quit", ":exit"):
            break
        if raw.startswith(":cont"):
            _, _, tail = raw.partition(" ")
            q = tail.strip() or "vẽ lại"
            ans, trace = continue_with_last(q)
            _print_answer(ans)
            if show_trace_default:
                _print_trace(trace, max_trace_text)
            continue
        if FOLLOWUP_REDRAW_PAT.search(raw) or FOLLOWUP_BRANCH_PAT.search(raw):
            ans, trace = continue_with_last(raw)
            _print_answer(ans)
            if show_trace_default:
                _print_trace(trace, max_trace_text)
            continue
        ans, trace = answer_with_rag(raw)
        _print_answer(ans)
        if show_trace_default:
            _print_trace(trace, max_trace_text)

def main():
    parser = build_parser()
    args = parser.parse_args()
    _apply_env(args)

    if args.ask:
        run_once_ask(args.ask, args.json, args.trace, args.max_trace_text)
        return
    if args.cont:
        run_once_cont(args.cont, args.json, args.trace, args.max_trace_text)
        return
    repl(show_trace_default=args.trace, max_trace_text=args.max_trace_text)

if __name__ == "__main__":
    main()
