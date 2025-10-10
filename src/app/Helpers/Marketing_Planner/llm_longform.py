# Helpers/llm_longform.py
import re
from app.config.config_MKT import call_text, MAX_TOKENS_MKT, tokens_for_words

def _word_count_vi(s: str) -> int:
    return len(re.findall(r"[A-Za-zÀ-ỹ0-9\-]+", s or ""))

def _extract_body(md: str) -> str:
    # Đếm phần thân bài: sau H1 đến trước FAQ
    m = re.search(r"^#\s.+?\n(.*?)(?=\n#\s*(?:Phần Hỏi|FAQ)|\Z)", md or "", flags=re.S|re.M|re.I|re.U)
    return (m.group(1) if m else (md or "")).strip()

def _tail_context(s: str, n_chars: int = 1800) -> str:
    s = s or ""
    return s[-n_chars:] if len(s) > n_chars else s

def generate_longform(system_instruction: str,
                      up_body: str,
                      *,
                      target_words: int = 2200,
                      tolerance_pct: int = 7,
                      max_turns: int = 5) -> str:
    """
    Gọi model nhiều lần để viết đủ số từ:
    - Turn 1: gọi thẳng với up_body
    - Turn 2..N: tiếp tục từ chỗ dở dang, truyền tail context để tránh lặp
    - Dừng khi WORD_COUNT(body) đạt target ± tolerance hoặc khi model hết ý
    """
    out = ""
    lo = int(target_words*(1 - tolerance_pct/100))
    hi = int(target_words*(1 + tolerance_pct/100))

    for turn in range(1, max_turns+1):
        if turn == 1:
            piece = call_text(
                prompt=up_body,
                max_output_tokens=min(MAX_TOKENS_MKT, int(tokens_for_words(target_words) * 2.2)),
                system_instruction=system_instruction
            )
        else:
            cont_prompt = f"""{up_body}

[CHỈ TIẾP TỤC NỘI DUNG BÀI, KHÔNG LẶP LẠI.
Đây là phần đã viết (CHỈ THAM CHIẾU, KHÔNG NHẮC LẠI):
<<<BEGIN_CONTEXT>>>
{_tail_context(out, 1800)}
<<<END_CONTEXT>>>]"""
            piece = call_text(
                prompt=cont_prompt,
                max_output_tokens=MAX_TOKENS_MKT,
                system_instruction=system_instruction
            )

        piece = (piece or "").strip()
        if not piece:
            break
        # tránh lặp vô tận khi model lặp lại
        if piece in out:
            break

        out += ("\n\n" if out else "") + piece

        wc = _word_count_vi(_extract_body(out))
        if lo <= wc <= hi:
            break
        # nếu tăng quá ít (model hết ý), dừng
        if turn > 1 and _word_count_vi(piece) < 120:
            break

    return out
