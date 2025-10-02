# Helpers/llm_longform_sectioned.py
import re, math
from typing import List
from ..config_MKT import call_text, MAX_TOKENS_MKT, tokens_for_words
from .repeat_guard import dedup_paragraphs

def _wc_vi(s: str) -> int:
    return len(re.findall(r"[A-Za-zÀ-ỹ0-9\-]+", s or ""))

def _tail(s: str, n=1800) -> str:
    s = s or ""
    return s[-n:] if len(s) > n else s

def _build_section_prompt(up_body: str, outline: List[str], done: List[str], current: str, tail_ctx: str) -> str:
    done_list = "\n".join(f"- {t}" for t in done) if done else "- (chưa có)"
    outline_list = "\n".join(f"{i+1}. {t}" for i, t in enumerate(outline))
    return f"""{up_body}

Bạn đang viết một bài longform theo dàn ý sau (KHÔNG tạo Mục lục/TOC trong đầu ra):

Outline:
{outline_list}

Các mục đã hoàn thành:
{done_list}

CHỈ viết TIẾP mục sau: "{current}"
- Không lặp lại bất kỳ câu/đoạn nào đã có ở phần trước.
- Bắt đầu bằng heading phù hợp (H2/H3) cho mục này.
- Nếu cần, dùng H3 cho các ý nhỏ; KHÔNG viết FAQ/Kết luận; KHÔNG quay lại các mục đã xong.
- Phần tham chiếu (đừng lặp lại, chỉ để bạn biết ngữ cảnh):
<<<BEGIN_CONTEXT>>>
{tail_ctx}
<<<END_CONTEXT>>>
"""

def generate_sectioned_longform(system_instruction: str,
                                up_body: str,
                                outline: List[str],
                                target_words: int = 2200,
                                tolerance_pct: int = 7,
                                max_retries_per_section: int = 1) -> str:
    """Viết lần lượt theo outline; mỗi lượt chỉ 1 mục, hạn chế lặp."""
    outline = [t.strip() for t in outline if t and t.strip()]
    if not outline:
        # fallback: nếu không có outline, trả về rỗng để caller xử lý cách khác
        return ""

    total_budget = min(MAX_TOKENS_MKT, int(tokens_for_words(target_words) * 2.2))
    per_sec_budget = max(1200, int(total_budget / max(1, len(outline))))  # phân bổ đều

    out = ""
    done: List[str] = []
    lo = int(target_words * (1 - tolerance_pct/100))
    hi = int(target_words * (1 + tolerance_pct/100))

    for sec in outline:
        # dừng nếu đã đủ chữ
        if _wc_vi(out) >= lo:
            break

        # chuẩn bị prompt cho mục hiện tại
        tail_ctx = _tail(out, 1800)
        prompt = _build_section_prompt(up_body, outline, done, sec, tail_ctx)

        best = ""
        for _try in range(max_retries_per_section + 1):
            piece = call_text(
                prompt=prompt,
                max_output_tokens=per_sec_budget,
                system_instruction=system_instruction
            )
            piece = (piece or "").strip()
            if not piece:
                continue
            # chặn lặp: loại đoạn trùng với out
            piece_dedup = dedup_paragraphs(out, piece, overlap_threshold=0.55)
            if len(piece_dedup) >= max(80, int(len(piece) * 0.35)):
                best = piece_dedup
                break
            # lần thử tiếp theo: siết chặt yêu cầu không lặp
            prompt += "\n\n[LƯU Ý: Bạn vừa lặp lại nội dung cũ. Viết lại mục này bằng diễn đạt mới, KHÔNG lặp câu/đoạn đã xuất hiện.]"

        if best:
            # tránh thêm nếu nó vẫn hầu như trùng
            if dedup_paragraphs(out, best, 0.45):
                out += ("\n\n" if out else "") + best
                done.append(sec)

        # dừng nếu vượt quá hi nhiều
        if _wc_vi(out) >= hi:
            break

    return out.strip()
