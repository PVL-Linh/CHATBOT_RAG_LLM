#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Tiximax Chatbot CLI
- Test chat với /api/chat
- Upload nhiều file với /api/upload
- Giữ session_id + cookie để doc_qa hoạt động đúng
"""

import os
import sys
import uuid
import json
import textwrap
import requests

# =========================
# CẤU HÌNH
# =========================
API_BASE = os.environ.get("TIXIMAX_API_BASE", "http://localhost:5000")
CHAT_URL = f"{API_BASE.rstrip('/')}/api/chat"
UPLOAD_URL = f"{API_BASE.rstrip('/')}/api/upload"

# =========================
# ANSI COLOR (ĐƠN GIẢN, KHÔNG CẦN THƯ VIỆN NGOÀI)
# =========================
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"

    FG_CYAN = "\033[96m"
    FG_GREEN = "\033[92m"
    FG_YELLOW = "\033[93m"
    FG_RED = "\033[91m"
    FG_MAGENTA = "\033[95m"
    FG_BLUE = "\033[94m"
    FG_GREY = "\033[90m"


def color(text, code):
    return f"{code}{text}{C.RESET}"


# =========================
# TIỆN ÍCH IN ĐẸP
# =========================
def print_banner(session_id):
    line = "=" * 60
    print(color(line, C.FG_CYAN))
    print(color("   TIXIMAX AI CHATBOT CLI", C.FG_CYAN + C.BOLD))
    print(color(f"   API_BASE   : {API_BASE}", C.FG_GREY))
    print(color(f"   SESSION_ID : {session_id}", C.FG_GREY))
    print(color(line, C.FG_CYAN))
    print(
        color(
            "Gõ câu hỏi để chat.\n"
            "Lệnh đặc biệt:\n"
            "  :help        - xem hướng dẫn\n"
            "  :upload PATH1 PATH2 ...  - upload nhiều file\n"
            "  :files       - xem danh sách file đã upload (theo CLI)\n"
            "  :newsession  - tạo session_id mới\n"
            "  :exit        - thoát\n",
            C.FG_GREY,
        )
    )


def wrap_text(text, width=80, indent=""):
    text = text or ""
    lines = text.splitlines()
    out_lines = []
    for line in lines:
        if not line.strip():
            out_lines.append("")
            continue
        wrapped = textwrap.wrap(line, width=width)
        for w in wrapped:
            out_lines.append(indent + w)
    return "\n".join(out_lines)


def print_assistant_answer(data):
    branch = data.get("branch", "?")
    answer = data.get("answer", "")
    timing = data.get("timing") or {}
    meta = data.get("meta")

    print(color(f"\n[Branch] {branch}", C.FG_YELLOW + C.BOLD))

    if timing:
        t_total = timing.get("total")
        if t_total is not None:
            print(color(f"[Timing] {t_total}s", C.FG_GREY))

    if meta and isinstance(meta, dict):
        # In meta gọn gàng nếu có
        meta_str = json.dumps(meta, ensure_ascii=False)
        print(color(f"[Meta] {meta_str}", C.FG_GREY))

    print(color("\nAssistant:", C.FG_GREEN + C.BOLD))
    print(wrap_text(answer, width=88, indent="  "))
    print()


# =========================
# LỚP CLIENT
# =========================
class TiximaxCLI:
    def __init__(self, chat_url, upload_url):
        self.chat_url = chat_url
        self.upload_url = upload_url
        self.session = requests.Session()  # giữ cookie cho Flask session
        self.session_id = str(uuid.uuid4())
        self.uploaded_files = []  # chỉ là list local để hiển thị cho đẹp
        self.debug = False

    # ---------- API GỌI CHAT ----------
    def ask(self, text):
        payload = {
            "message": text,
            "session_id": self.session_id,
        }
        try:
            resp = self.session.post(self.chat_url, json=payload, timeout=600)
        except Exception as e:
            print(color(f"❌ Lỗi khi gọi API chat: {e}", C.FG_RED))
            return

        if resp.status_code != 200:
            print(
                color(
                    f"❌ API trả về status {resp.status_code}: {resp.text}", C.FG_RED
                )
            )
            return

        try:
            data = resp.json()
        except Exception as e:
            print(color(f"❌ Không parse được JSON: {e}", C.FG_RED))
            print(resp.text)
            return

        if self.debug:
            print(color("\n--- RAW RESPONSE ---", C.FG_GREY))
            print(json.dumps(data, ensure_ascii=False, indent=2))
            print(color("--- END RAW ---\n", C.FG_GREY))

        print_assistant_answer(data)

    # ---------- API UPLOAD ----------
    def upload_files(self, paths):
        if not paths:
            print(color("⚠ Chưa truyền đường dẫn file.", C.FG_YELLOW))
            return

        real_paths = []
        for p in paths:
            p = os.path.expanduser(p)
            if not os.path.isfile(p):
                print(color(f"⚠ File không tồn tại: {p}", C.FG_YELLOW))
            else:
                real_paths.append(p)

        if not real_paths:
            print(color("⚠ Không có file hợp lệ để upload.", C.FG_YELLOW))
            return

        files = []
        for p in real_paths:
            fname = os.path.basename(p)
            # Lưu ý: type 'application/octet-stream' là generic, server không cần cũng được
            files.append(("file", (fname, open(p, "rb"), "application/octet-stream")))

        try:
            resp = self.session.post(self.upload_url, files=files, timeout=600)
        finally:
            # Đóng file handle
            for _, (fname, fh, _) in files:
                try:
                    fh.close()
                except Exception:
                    pass

        if resp.status_code != 200:
            print(
                color(
                    f"❌ Upload lỗi, status {resp.status_code}: {resp.text}",
                    C.FG_RED,
                )
            )
            return

        try:
            data = resp.json()
        except Exception as e:
            print(color(f"❌ Không parse được JSON từ upload: {e}", C.FG_RED))
            print(resp.text)
            return

        ok = data.get("ok", False)
        files_info = data.get("files", [])
        errors = data.get("errors", [])

        if ok:
            print(color("✅ Upload thành công các file:", C.FG_GREEN))
            for f in files_info:
                name = f.get("name")
                stored = f.get("stored_name") or f.get("path")
                print(color(f"  - {name}  → {stored}", C.FG_GREEN))
            # lưu lại list local
            self.uploaded_files.extend(files_info)
        else:
            print(color("⚠ Upload không thành công.", C.FG_YELLOW))

        if errors:
            print(color("Chi tiết lỗi:", C.FG_YELLOW))
            for e in errors:
                print("  -", json.dumps(e, ensure_ascii=False))

    # ---------- HIỂN THỊ FILE ----------
    def show_files(self):
        if not self.uploaded_files:
            print(color("⚠ Chưa có file nào được upload từ CLI này.", C.FG_YELLOW))
            print(
                color(
                    "   (Có thể server vẫn đang giữ file từ phiên khác, nhưng CLI không biết.)",
                    C.FG_GREY,
                )
            )
            return

        print(color("📄 Danh sách file đã upload (theo CLI):", C.FG_CYAN))
        for idx, f in enumerate(self.uploaded_files, start=1):
            name = f.get("name") or "?"
            stored = f.get("stored_name") or f.get("path")
            print(f"  [{idx}] {name}  → {stored}")

    # ---------- ĐỔI SESSION ----------
    def new_session(self):
        old = self.session_id
        self.session_id = str(uuid.uuid4())
        print(
            color(
                f"🔁 Đã tạo session_id mới.\n   Cũ: {old}\n   Mới: {self.session_id}",
                C.FG_MAGENTA,
            )
        )

    # ---------- BẬT/TẮT DEBUG ----------
    def toggle_debug(self):
        self.debug = not self.debug
        print(color(f"🐞 Debug = {self.debug}", C.FG_MAGENTA))


# =========================
# VÒNG LẶP CHÍNH
# =========================
def main():
    cli = TiximaxCLI(CHAT_URL, UPLOAD_URL)
    print_banner(cli.session_id)

    while True:
        try:
            user_input = input(color("You: ", C.FG_BLUE + C.BOLD)).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n" + color("👋 Thoát CLI.", C.FG_GREY))
            break

        if not user_input:
            continue

        # Lệnh đặc biệt bắt đầu bằng :
        if user_input.startswith(":"):
            parts = user_input.split()
            cmd = parts[0].lower()

            if cmd in (":exit", ":quit"):
                print(color("👋 Thoát CLI.", C.FG_GREY))
                break
            elif cmd == ":help":
                print(
                    color(
                        "\nLệnh hỗ trợ:\n"
                        "  :help                 - xem hướng dẫn\n"
                        "  :upload PATH1 PATH2   - upload nhiều file 1 lần\n"
                        "  :files                - xem danh sách file upload (theo CLI)\n"
                        "  :newsession           - tạo session_id mới\n"
                        "  :debug                - bật/tắt in raw JSON response\n"
                        "  :exit                 - thoát\n",
                        C.FG_GREY,
                    )
                )
            elif cmd == ":upload":
                paths = parts[1:]
                if not paths:
                    print(
                        color(
                            "⚠ Dùng: :upload path1 path2 ...", C.FG_YELLOW
                        )
                    )
                else:
                    cli.upload_files(paths)
            elif cmd == ":files":
                cli.show_files()
            elif cmd == ":newsession":
                cli.new_session()
            elif cmd == ":debug":
                cli.toggle_debug()
            else:
                print(color(f"⚠ Lệnh không hỗ trợ: {cmd}", C.FG_YELLOW))
            continue

        # Còn lại là câu chat bình thường
        cli.ask(user_input)


if __name__ == "__main__":
    main()
