# # -*- coding: utf-8 -*-
# """
# Bounded writer cho longform ~2000 từ (an toàn MAX_TOKENS, không 500):
# - Pass 1: viết trọn bài (bám outline nếu có), ép [[END]] + WORD_COUNT.
# - Nếu thiếu [[END]] / MAX_TOKENS / SDK không có Part -> cắt mềm; nếu vẫn rỗng -> MINI BODY FALLBACK (prompt rút gọn).
# - Nếu kết thúc lưng chừng -> chêm 'Kết luận + CTA' ngắn (call nhỏ, có fallback offline).
# - Nếu lệch mục tiêu -> micro-shrink/expand 1 call (có fallback).
# - Mọi call LLM đều safe (không raise). Hàm luôn return (text, wc, did_micro_edit).
# """

# from __future__ import annotations
# import os
# import re
# from typing import List, Tuple

# from ..config_MKT import call_text, tokens_for_words
# from .text_postprocess import (
#     strip_after_marker,
#     sanitize_blog_article,
#     strip_toc_from_output,
# )

# # ======== CẤU HÌNH AN TOÀN (override qua ENV nếu muốn) ========
# OUTPUT_CAP: int = int(os.getenv("PLANNER_OUTPUT_CAP", "2800"))         # trần output mỗi call
# TOKEN_BOOST: float = float(os.getenv("PLANNER_TOKEN_BOOST", "1.10"))   # ước lượng token chặt
# ENDING_CAP: int = int(os.getenv("PLANNER_ENDING_CAP", "240"))          # token cho kết luận nhỏ
# MINIBODY_CAP: int = int(os.getenv("PLANNER_MINIBODY_CAP", "720"))      # token cho mini body fallback

# # ======== REGEX & UTILS ========
# _SENT_END = re.compile(
#     r"(?<=[\.\!\?…])\s+|\n(?=#{1,3}\s)|\n(?=[A-ZÀ-Ỵ].+\n[-=]{2,})",
#     re.U | re.M,
# )
# _WORD_RE = re.compile(r"[A-Za-zÀ-ỹ0-9\-]+", re.U)
# _CONCL_RE = re.compile(r"(?im)^\s*(#{1,6}\s*)?(kết\s*luận|kết\s*luận\s*\+\s*cta)\b", re.U)

# def _wc_vi(s: str) -> int:
#     return len(_WORD_RE.findall(s or ""))

# def _budget_tokens_for_target(words: int) -> int:
#     est = int(tokens_for_words(words) * TOKEN_BOOST)
#     est = max(512, est)
#     return min(est, OUTPUT_CAP)

# def _safe_call(prompt: str, *, max_output_tokens: int, system_instruction: str | None) -> str:
#     """Gọi LLM an toàn: không raise, luôn trả về string (có thể rỗng)."""
#     try:
#         out = call_text(
#             prompt=prompt,
#             max_output_tokens=max_output_tokens,
#             system_instruction=system_instruction,
#         )
#         return (out or "").strip()
#     except Exception as e:
#         print("[bounded_writer] LLM call error:", e)
#         return ""

# def _truncate_soft_by_sentence(md: str, target_hi_words: int) -> str:
#     if not md:
#         return md
#     last_good_idx = None
#     for m in _SENT_END.finditer(md):
#         chunk = md[: m.end()]
#         if _wc_vi(chunk) <= target_hi_words:
#             last_good_idx = m.end()
#         else:
#             break
#     if last_good_idx is None:
#         out = md.strip()
#     else:
#         out = md[:last_good_idx].rstrip()
#     # Nếu đang dở 1 bullet, gọt bớt dòng lẻ
#     out = re.sub(r"\n[^\S\r\n]*[-*]\s.*?$", "", out, flags=re.M)
#     out = re.sub(r"\n{3,}", "\n\n", out)
#     return out.strip()

# def _has_conclusion(md: str) -> bool:
#     return bool(_CONCL_RE.search(md or ""))

# def _looks_abrupt(md: str) -> bool:
#     """Phát hiện kết thúc 'lưng chừng' (heading/bullet/dứt câu)."""
#     if not md:
#         return True
#     if re.search(r"(?:\n|\A)#{1,6}\s*[^\n]*\s*$", md):
#         return True
#     if re.search(r"(?:\n|\A)[ \t]*[-*]\s+\S[^\n]*\s*$", md):
#         return True
#     if not re.search(r"[\.!\?…]\s*$", md.strip()):
#         return True
#     return False

# def _build_singlepass_prompt(up_body: str, outline: List[str] | None, target_words: int, include_toc: bool) -> str:
#     blocks = [up_body.strip(), ""]
#     if outline:
#         outline_list = "\n".join(f"- {t.strip()}" for t in outline if t and t.strip())
#         blocks.append(
#             f"""Dàn ý PHẢI bám theo (không tạo TOC/Mục lục trong đầu ra):
# {outline_list}
# """
#         )
#     no_toc_line = "Không tạo Mục lục/TOC trong đầu ra." if not include_toc else ""
#     blocks.append(
#         f"""YÊU CẦU ĐỘ DÀI:
# - Viết khoảng {target_words} từ (±6%). {no_toc_line}
# - Trả về Markdown sạch.
# - Ở dòng cuối cùng, in "WORD_COUNT: <số>" rồi ghi "[[END]]".
# (Chỉ trả về nội dung; không thêm lời giải thích ngoài lề.)"""
#     )
#     return "\n".join(blocks).strip()

# def _trim_text_center(s: str, max_chars: int) -> str:
#     """Rút gọn chuỗi dài: lấy phần giữa/đuôi để giữ 'ngữ cảnh' hiện tại."""
#     s = (s or "").strip()
#     if len(s) <= max_chars:
#         return s
#     # lấy 1/3 đầu + 2/3 cuối để giữ bối cảnh hiện tại
#     head = max_chars // 3
#     tail = max_chars - head
#     return (s[:head] + "\n...\n" + s[-tail:]).strip()

# def _build_minibody_prompt(up_body: str, outline: List[str] | None, target_words: int, include_toc: bool) -> str:
#     # Rút gọn input để đảm bảo sinh được nội dung dù CAP nhỏ
#     compact_body = _trim_text_center(up_body, 1200)
#     parts = [
#         (compact_body or "(không có mô tả chi tiết)"),
#         "",
#         "Viết một bài tóm lược NGẮN có cấu trúc (Markdown, KHÔNG TOC):",
#         "- Mở bài 2–3 câu (nêu bối cảnh/vấn đề).",
#         "- 2–3 mục chính (H2/H3) với các gạch đầu dòng ngắn.",
#         "- TRÁNH viết quá dài; không cần ví dụ rườm rà.",
#         f"- Tổng ~{max(600, int(target_words*0.35))}–{max(800, int(target_words*0.45))} từ.",
#     ]
#     if outline:
#         outline_list = "\n".join(f"- {t.strip()}" for t in outline if t and t.strip())
#         parts += [
#             "",
#             "Tham khảo dàn ý (được phép rút gọn ý, không cần đầy đủ):",
#             outline_list,
#         ]
#     parts += [
#         "",
#         "Kết thúc nội dung bằng chuỗi ký tự [[END]] (không in WORD_COUNT).",
#     ]
#     return "\n".join(parts).strip()

# def _micro_conclusion(context_md: str) -> str:
#     """Sinh '## Kết luận + CTA' ngắn; nếu call lỗi -> fallback offline."""
#     tail_ctx = (context_md or "")[-1600:]
#     prompt = f"""Viết phần **Kết luận + CTA** ngắn gọn cho bài viết sau.
# - Tiêu đề: "## Kết luận + CTA"
# - 2–4 câu, súc tích, không lặp heading cũ, không tạo TOC.
# - Ngôn ngữ/giọng điệu khớp văn bản.
# - Trả về Markdown sạch, CHỈ phần kết luận.

# <<<BỐI CẢNH CUỐI BÀI>>>
# {tail_ctx}
# <<<HẾT>>>
# """
#     out = _safe_call(prompt, max_output_tokens=min(ENDING_CAP, OUTPUT_CAP), system_instruction=None)
#     out = strip_after_marker(out, "[[END]]").strip()
#     if not out:
#         # Fallback offline
#         out = (
#             "## Kết luận + CTA\n\n"
#             "Tóm lại, lựa chọn phương án phù hợp giúp cân bằng chi phí, thời gian và độ tin cậy. "
#             "Nếu bạn cần lộ trình tối ưu cho nhu cầu cụ thể, hãy liên hệ đội ngũ Tiximax để được tư vấn và báo giá nhanh."
#         )
#     elif not re.match(r"(?im)^\s*#{2,6}\s", out):
#         out = "## Kết luận + CTA\n\n" + out
#     return out.strip()

# def _shrink_to_target(md: str, target_words: int) -> str:
#     prompt = f"""Rút gọn văn bản sau xuống gần {target_words} từ (±4%) mà vẫn giữ nguyên bố cục heading,
# giọng điệu và ý chính. Ưu tiên:
# - Giữ phần mở bài, các mục chính, kết luận và CTA.
# - Giữ 1 block FAQ đầu tiên; lược bớt ví dụ lặt vặt, câu trùng lặp, tính từ sáo rỗng.
# - Không tạo TOC. Không thêm heading mới bất hợp lý.
# - Trả về Markdown sạch. Kết thúc bằng "[[END]]".

# ---BEGIN---
# {md}
# ---END---
# """
#     out = _safe_call(prompt, max_output_tokens=_budget_tokens_for_target(target_words), system_instruction=None)
#     out2 = strip_after_marker(out, "[[END]]")
#     return (out2.strip() or md).strip()

# def _expand_to_target(md: str, target_words: int) -> str:
#     prompt = f"""Mở rộng văn bản sau cho đạt ~{target_words} từ (±4%) bằng cách bổ sung dẫn chứng/ngữ cảnh
# ở các mục CHÍNH, không viết lan man. Không tạo TOC. Giữ nguyên giọng điệu, heading, CTA.
# Trả về Markdown sạch và kết thúc bằng "[[END]]".

# ---BEGIN---
# {md}
# ---END---
# """
#     out = _safe_call(prompt, max_output_tokens=_budget_tokens_for_target(target_words), system_instruction=None)
#     out2 = strip_after_marker(out, "[[END]]")
#     return (out2.strip() or md).strip()

# def generate_bounded_longform(
#     *,
#     system_instruction: str,
#     up_body: str,
#     outline: List[str] | None,
#     include_toc: bool,
#     target_words: int = 2000,
#     tolerance_pct: int = 6,
#     micro_edit: bool = True,
# ) -> Tuple[str, int, bool]:
#     """
#     1) Single-pass -> 2) cắt mềm nếu thiếu [[END]] -> 3) nếu vẫn rỗng -> MINI BODY FALLBACK
#     4) sanitize/strip TOC -> 5) Micro-fix độ dài -> 6) Kết luận nếu lưng chừng
#     7) Nếu hơi vượt -> cắt mềm lần cuối. Luôn return (text, wc, did_micro_edit).
#     """
#     lo = int(target_words * (1 - tolerance_pct / 100.0))
#     hi = int(target_words * (1 + tolerance_pct / 100.0))
#     hard_hi = int(target_words * 1.15)

#     # ---- 1) Single pass (safe) ----
#     sp = _build_singlepass_prompt(up_body, outline, target_words, include_toc)
#     raw = _safe_call(sp, max_output_tokens=_budget_tokens_for_target(target_words), system_instruction=system_instruction)

#     # ---- 2) Cắt mềm nếu thiếu [[END]] ----
#     stripped = strip_after_marker(raw, "[[END]]")
#     if "[[END]]" not in raw and stripped == raw:
#         raw = _truncate_soft_by_sentence(raw, hi)
#     else:
#         raw = stripped

#     # ---- 3) MINI BODY FALLBACK nếu vẫn rỗng (do SDK không có Part/ bị MAX_TOKENS sớm) ----
#     if not raw.strip():
#         mini_prompt = _build_minibody_prompt(up_body, outline, target_words, include_toc)
#         raw = _safe_call(mini_prompt, max_output_tokens=min(MINIBODY_CAP, OUTPUT_CAP), system_instruction=None)
#         raw = strip_after_marker(raw, "[[END]]").strip()

#     # Safety: nếu vẫn rỗng, tạo khung offline
#     if not raw:
#         raw = (
#             "# Giới thiệu\n\n"
#             "Bài viết tóm lược các điểm chính theo yêu cầu.\n\n"
#             "## Điểm chính\n\n"
#             "- Ý 1\n- Ý 2\n- Ý 3\n"
#         )

#     # ---- 4) Sanitize & strip TOC ----
#     try:
#         text = sanitize_blog_article(raw)
#     except Exception as e:
#         print("[bounded_writer] sanitize error:", e)
#         text = (raw or "").strip()
#     if not include_toc:
#         try:
#             text = strip_toc_from_output(text)
#         except Exception as e:
#             print("[bounded_writer] strip_toc error:", e)

#     wc = _wc_vi(text)
#     did_microfix = False

#     # ---- 5) Micro-fix độ dài ----
#     try:
#         if not (lo <= wc <= hi) and micro_edit:
#             if wc > hi and wc <= hard_hi:
#                 # cắt mềm trước
#                 text_trim = _truncate_soft_by_sentence(text, hi)
#                 wc_trim = _wc_vi(text_trim)
#                 if lo <= wc_trim <= hi:
#                     text, wc = text_trim, wc_trim
#                 else:
#                     text = _shrink_to_target(text_trim, target_words)
#                     try:
#                         text = sanitize_blog_article(text)
#                     except Exception:
#                         pass
#                     if not include_toc:
#                         try:
#                             text = strip_toc_from_output(text)
#                         except Exception:
#                             pass
#                     wc = _wc_vi(text)
#                     did_microfix = True
#             elif wc > hi:
#                 text = _shrink_to_target(text, target_words)
#                 try:
#                     text = sanitize_blog_article(text)
#                 except Exception:
#                     pass
#                 if not include_toc:
#                     try:
#                         text = strip_toc_from_output(text)
#                     except Exception:
#                         pass
#                 wc = _wc_vi(text)
#                 did_microfix = True
#             elif wc < lo:
#                 text = _expand_to_target(text, target_words)
#                 try:
#                     text = sanitize_blog_article(text)
#                 except Exception:
#                     pass
#                 if not include_toc:
#                     try:
#                         text = strip_toc_from_output(text)
#                     except Exception:
#                         pass
#                 wc = _wc_vi(text)
#                 did_microfix = True
#     except Exception as e:
#         print("[bounded_writer] micro_edit error:", e)

#     # ---- 6) Nếu kết thúc lưng chừng/thiếu kết luận -> chêm ----
#     try:
#         if _looks_abrupt(text) or not _has_conclusion(text):
#             concl = _micro_conclusion(text)
#             text = (text.rstrip() + "\n\n" + concl.strip()).strip()
#             try:
#                 text = sanitize_blog_article(text)
#             except Exception:
#                 pass
#             if not include_toc:
#                 try:
#                     text = strip_toc_from_output(text)
#                 except Exception:
#                     pass
#             wc = _wc_vi(text)
#     except Exception as e:
#         print("[bounded_writer] conclusion error:", e)

#     # ---- 7) Hơi vượt -> cắt mềm lần cuối ----
#     try:
#         if wc > hi:
#             text = _truncate_soft_by_sentence(text, hi)
#             wc = _wc_vi(text)
#     except Exception as e:
#         print("[bounded_writer] final trim error:", e)

#     # Safety cuối: nếu vẫn trống, trả khung cơ bản
#     if not text:
#         text = (
#             "# Bài viết\n\n"
#             "Mở bài ngắn gọn nêu bối cảnh và vấn đề chính.\n\n"
#             "## Nội dung chính\n\n"
#             "- Ý 1\n- Ý 2\n- Ý 3\n\n"
#             "## Kết luận + CTA\n\n"
#             "Tổng kết ngắn gọn và mời liên hệ Tiximax để được tư vấn & báo giá."
#         )
#         wc = _wc_vi(text)

#     return text, wc, did_microfix



from __future__ import annotations
import os
import re
from typing import List, Tuple

from ..config_MKT import call_text, tokens_for_words
from .text_postprocess import (
    strip_after_marker,
    sanitize_blog_article,
    strip_toc_from_output,
)

# ======== CẤU HÌNH ========
PLANNER_OUTPUT_CAP = int(os.getenv("PLANNER_OUTPUT_CAP", "2048"))   # tổng ngân sách cho thân bài
PLANNER_MINIBODY_CAP = int(os.getenv("PLANNER_MINIBODY_CAP", "600"))
PLANNER_ENDING_CAP = int(os.getenv("PLANNER_ENDING_CAP", "200"))
PLANNER_TOKEN_BOOST = float(os.getenv("PLANNER_TOKEN_BOOST", "1.10"))  # boost nhẹ phòng tiếng Việt dài hơn

# ======== TIỆN ÍCH ========
def _wc_vi(s: str) -> int:
    s = (s or "").strip()
    if not s:
        return 0
    # đếm thô theo khoảng trắng (ổn cho clamp cuối)
    return len(re.findall(r"\S+", s, re.M))

def _truncate_soft_by_sentence(md: str, max_words: int) -> str:
    """Cắt mềm theo câu để <= max_words."""
    words = re.findall(r"\S+", md or "", re.M)
    if len(words) <= max_words:
        return (md or "").strip()
    cut = " ".join(words[:max_words])
    # cố gắng cắt ở dấu chấm gần nhất
    m = re.search(r"^(.+?[.!?…])(?:\s|$)", cut, re.S)
    return (m.group(1) if m else cut).strip()

def _has_conclusion(md: str) -> bool:
    """Rà xem có section kết luận chưa (tiêu đề, CTA)."""
    s = (md or "").lower()
    return any(
        k in s
        for k in (
            "## kết luận",
            "## tong ket",
            "## tổng kết",
            "## conclusion",
            "### kết luận",
            "### conclusion",
            "kêu gọi hành động",
            "call to action",
            "cta:",
        )
    )

def _looks_abrupt(md: str) -> bool:
    """Heuristic: kết thúc lưng chừng (không dấu chấm, markdown hở, vv.)."""
    s = (md or "").rstrip()
    if not s:
        return False
    # thiếu dấu kết câu
    if not re.search(r"[.!?…]\s*$", s):
        return True
    # kết thúc bằng dấu gạch đầu dòng / heading
    if re.search(r"(?m)^(?:\s*[-*]\s+|\s*#{1,6}\s+\S.*)$", s.splitlines()[-1]):
        return True
    return False

def _micro_conclusion(context_md: str) -> str:
    """Sinh '## Kết luận + CTA' ngắn; nếu call lỗi -> fallback offline."""
    prompt = f"""Viết phần **Kết luận + CTA** ngắn gọn cho bài viết sau.
- Tiêu đề: "## Kết luận + CTA"
- Dài khoảng 2–3 câu, súc tích, có CTA rõ ràng phù hợp ngữ cảnh.
- Không lặp lại toàn bộ nội dung trước đó, chỉ chốt lại 1–2 ý chính.
- Trả về Markdown hợp lệ.
- thêm icon hợp lý
[ Bài viết ]
{context_md}
"""
    try:
        out = call_text(prompt, max_output_tokens=PLANNER_ENDING_CAP)
        out = (out or "").strip()
        if not out:
            # fallback cực ngắn
            out = (
                "## Kết luận + CTA\n\n"
                "Chốt lại lợi ích cốt lõi. Hành động ngay hôm nay để nhận tư vấn và ưu đãi phù hợp."
            )
        if not out.strip().lower().startswith("##"):
            out = "## Kết luận + CTA\n\n" + out
        return out.strip()
    except Exception:
        return (
            "## Kết luận + CTA\n\n"
            "Tóm tắt ngắn gọn giá trị chính. Liên hệ ngay để được tư vấn chi tiết và nhận ưu đãi."
        ).strip()

# ======== CHÍNH ========
def generate_bounded_longform(
    *,
    system_instruction: str,
    up_body: str,
    outline: List[str] | None,
    include_toc: bool,
    target_words: int = 2000,
    tolerance_pct: int = 6,
    micro_edit: bool = True,
) -> Tuple[str, int, bool]:
    """
    1) Single-pass -> 2) cắt mềm nếu thiếu [[END]] -> 3) nếu vẫn rỗng -> MINI BODY FALLBACK
    4) sanitize/strip TOC -> 5) Micro-fix độ dài -> 6) Kết luận nếu lưng chừng
    7) Nếu hơi vượt -> cắt mềm lần cuối. Luôn return (text, wc, did_micro_edit).
    """
    target_words = max(50, int(target_words or 2000))
    tolerance_pct = max(1, min(25, int(tolerance_pct or 6)))
    lo = int(target_words * (1 - tolerance_pct / 100.0))
    hi = int(target_words * (1 + tolerance_pct / 100.0))
    hard_hi = int(hi * 1.1)

    # ---- 1) PASS viết thân bài ----
    max_out_tokens = int(PLANNER_OUTPUT_CAP * PLANNER_TOKEN_BOOST)
    user_prompt = f"""{up_body}

(Kết thúc bài bằng [[END]] ở cuối, không thêm nội dung sau đó. Ghi số từ thực tế ở dòng cuối dạng WORD_COUNT: <số>.)"""

    try:
        raw = call_text(
            prompt=user_prompt,
            max_output_tokens=max_out_tokens,
            system_instruction=system_instruction,
        )
        raw = (raw or "").strip()
    except Exception:
        raw = ""

    # ---- 2) Nếu thiếu [[END]] hoặc quá dài -> cắt mềm và strip after [[END]] ----
    if raw:
        try:
            raw = strip_after_marker(raw, marker="[[END]]")
        except Exception:
            pass
        # cắt mềm nếu quá cao so với hard_hi
        if _wc_vi(raw) > hard_hi:
            raw = _truncate_soft_by_sentence(raw, hard_hi)

    # ---- 3) MINI BODY FALLBACK khi rỗng thật ----
    if not raw:
        mini_prompt = f"""Viết phần thân chính, độ dài gần {target_words} từ (±{tolerance_pct}%).
- Ngắn gọn, đi thẳng lợi ích chính, không chèn mục lục hay tiêu đề quá dài.
- Kết thúc tự nhiên, không cần [[END]].

{up_body}
"""
        try:
            raw = call_text(mini_prompt, max_output_tokens=PLANNER_MINIBODY_CAP)
            raw = (raw or "").strip()
        except Exception:
            raw = ""

    # ---- 4) Sanitize & strip TOC ----
    try:
        text = sanitize_blog_article(raw)
    except Exception as e:
        print("[bounded_writer] sanitize error:", e)
        text = (raw or "").strip()
    if not include_toc:
        try:
            text = strip_toc_from_output(text)
        except Exception as e:
            print("[bounded_writer] strip_toc error:", e)

    wc = _wc_vi(text)
    did_microfix = False

    # ---- 5) Micro-fix độ dài ----
    try:
        if not (lo <= wc <= hi) and micro_edit:
            if wc > hi and wc <= hard_hi:
                # cắt mềm trước
                text_trim = _truncate_soft_by_sentence(text, hi)
                wc_trim = _wc_vi(text_trim)
                if lo <= wc_trim <= hi:
                    text, wc = text_trim, wc_trim
                else:
                    text = _shrink_to_target(text_trim, target_words)
                    try:
                        text = sanitize_blog_article(text)
                    except Exception:
                        pass
                    if not include_toc:
                        try:
                            text = strip_toc_from_output(text)
                        except Exception:
                            pass
                    wc = _wc_vi(text)
                    did_microfix = True
            elif wc > hard_hi:
                # shrink mạnh tay khi vượt quá xa
                text = _shrink_to_target(text, target_words)
                try:
                    text = sanitize_blog_article(text)
                except Exception:
                    pass
                if not include_toc:
                    try:
                        text = strip_toc_from_output(text)
                    except Exception:
                        pass
                wc = _wc_vi(text)
                did_microfix = True
            else:
                # expand nhe khi quá ngắn
                text = _expand_to_target(text, target_words)
                try:
                    text = sanitize_blog_article(text)
                except Exception:
                    pass
                if not include_toc:
                    try:
                        text = strip_toc_from_output(text)
                    except Exception:
                        pass
                wc = _wc_vi(text)
                did_microfix = True
    except Exception as e:
        print("[bounded_writer] micro_edit error:", e)

    # ---- 6) Nếu kết thúc lưng chừng/thiếu kết luận -> chêm ----
    try:
        # ✅ CHỈ chêm khi bài DÀI (>= 600 từ) để tránh đội word-count cho bài ngắn
        if target_words >= 600 and (_looks_abrupt(text) or not _has_conclusion(text)):
            concl = _micro_conclusion(text)
            text = (text.rstrip() + "\n\n" + concl.strip()).strip()
            try:
                text = sanitize_blog_article(text)
            except Exception:
                pass
            if not include_toc:
                try:
                    text = strip_toc_from_output(text)
                except Exception:
                    pass
            wc = _wc_vi(text)
    except Exception as e:
        print("[bounded_writer] conclusion error:", e)

    # ---- 7) Hơi vượt -> cắt mềm lần cuối ----
    if wc > hi and wc <= hard_hi:
        text = _truncate_soft_by_sentence(text, hi)
        wc = _wc_vi(text)

    return text.strip(), wc, did_microfix


# ======== SHRINK/EXPAND (dùng 1 call nhỏ, có fallback) ========
def _shrink_to_target(md: str, target_words: int) -> str:
    prompt = f"""Rút gọn nội dung về khoảng {target_words} từ (không vượt quá {int(target_words*1.06)} từ).
- Giữ cấu trúc mạch lạc, ưu tiên lợi ích & CTA.
- Trả về Markdown hợp lệ.

[ Nội dung ]
{md}
"""
    try:
        return (call_text(prompt, max_output_tokens=PLANNER_OUTPUT_CAP) or "").strip() or md
    except Exception:
        # fallback: cắt mềm
        return _truncate_soft_by_sentence(md, int(target_words * 1.06))

def _expand_to_target(md: str, target_words: int) -> str:
    prompt = f"""Mở rộng nội dung về gần {target_words} từ (±6%).
- Bổ sung ý cụ thể, không lan man, không lặp.
- Trả về Markdown hợp lệ.

[ Nội dung ]
{md}
"""
    try:
        return (call_text(prompt, max_output_tokens=PLANNER_OUTPUT_CAP) or "").strip() or md
    except Exception:
        # fallback: giữ nguyên
        return md