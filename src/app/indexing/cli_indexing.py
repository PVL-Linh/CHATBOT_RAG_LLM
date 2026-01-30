from __future__ import annotations
import os, argparse
from .config_indexing import DEPTS_ROOT_DEFAULT
from .paths_indexing import list_departments
from .list_cmd import list_index_sources
from .add_indexing import add_files_to_index
from .delete_indexing import delete_sources_from_index

def _cmd_list(args):
    root = os.path.abspath(args.root or DEPTS_ROOT_DEFAULT)
    if args.all:
        depts = list_departments(root)
        if not depts:
            print("(no departments found)")
            return
        for d in depts:
            print(f"\n== {d} ==")
            rows = list_index_sources(root, d)
            if not rows:
                print("(empty or not initialized)")
                continue
            w = max(6, max(len(src) for src, _ in rows))
            print(f"{'source'.ljust(w)} | chunks")
            print(f"{'-'*w}-+-------")
            for src, n in rows:
                print(f"{src.ljust(w)} | {n}")
    else:
        if not args.dept:
            print("Please provide --dept or use --all"); return
        rows = list_index_sources(root, args.dept)
        if not rows:
            print("(empty or not initialized)")
            return
        w = max(6, max(len(src) for src, _ in rows))
        print(f"{'source'.ljust(w)} | chunks")
        print(f"{'-'*w}-+-------")
        for src, n in rows:
            print(f"{src.ljust(w)} | {n}")

def _cmd_add(args):
    root = os.path.abspath(args.root or DEPTS_ROOT_DEFAULT)
    if not args.dept:
        print("Please provide --dept"); return
    if not args.paths:
        print("Provide at least one TXT/PDF path"); return
    add_files_to_index(root, args.dept, args.paths)

def _cmd_delete(args):
    root = os.path.abspath(args.root or DEPTS_ROOT_DEFAULT)
    if not args.dept:
        print("Please provide --dept"); return
    if not args.sources:
        print("Provide at least one source (relative inside Data_All)"); return
    delete_sources_from_index(root, args.dept, args.sources)

def main():
    parser = argparse.ArgumentParser(description="Indexing CLI (multi-department FAISS manager)")
    parser.add_argument("--root", help="Root that contains department folders (defaults to src/app/vectorstore)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List sources of a department or all")
    p_list.add_argument("--dept", help="Department name (e.g., hr)")
    p_list.add_argument("--all", action="store_true", help="List all departments")
    p_list.set_defaults(func=_cmd_list)

    p_add = sub.add_parser("add", help="Add TXT/PDF into a department's index")
    p_add.add_argument("--dept", required=True, help="Department name (e.g., hr)")
    p_add.add_argument("paths", nargs="+", help="Paths to TXT/PDF files")
    p_add.set_defaults(func=_cmd_add)

    p_del = sub.add_parser("delete", help="Delete by sources from a department")
    p_del.add_argument("--dept", required=True, help="Department name (e.g., hr)")
    p_del.add_argument("sources", nargs="+", help="Relative sources inside Data_All")
    p_del.set_defaults(func=_cmd_delete)

    args = parser.parse_args()
    args.func(args)
