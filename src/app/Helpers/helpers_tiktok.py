# helpers_tiktok.py (hoặc ngay dưới route cho nhanh)
import re
from math import floor
from typing import List, Tuple
from prompts_extra import prompt_tiktok_vi
def _fmt_ms(s: int) -> str:
    # s = seconds
    m = s // 60
    ss = s % 60
    return f"{m:02d}:{ss:02d}"

def _build_plan(total: int) -> List[int]:
    """
    Trả về list thời lượng từng cảnh (giây), tổng = total.
    Quy ước:
      - intro 2–4s, outro 2–4s
      - số cảnh ~ total/6.5, clamp 5..10
    """
    total = int(total)
    intro = max(2, min(4, round(total * 0.07)))   # 7% tổng
    outro = max(2, min(4, round(total * 0.07)))

    n = int(round(total / 6.5))
    n = max(5, min(10, n))  # 5..10 cảnh
    if n < 3:  # an toàn
        n = 5

    mid_slots = n - 2
    core = total - intro - outro
    base = max(2, core // mid_slots)
    rem = core - base * mid_slots

    plan = [intro] + [base] * mid_slots + [outro]
    # rải phần dư vào các cảnh giữa
    i = 1
    while rem > 0 and i < len(plan) - 1:
        plan[i] += 1
        rem -= 1
        i += 1

    # đảm bảo tổng khớp
    diff = total - sum(plan)
    if diff != 0:
        plan[-2] += diff  # dồn vào cảnh áp chót
    return plan

def _stamp_timeline(scenes_text: List[str], plan: List[int]) -> str:
    # Nếu LLM trả nhiều/ít cảnh, co/bổ sung cho khớp độ dài plan
    if len(scenes_text) < len(plan):
        # bổ sung cảnh trống
        scenes_text += ["(Bổ sung nội dung cho cảnh này)"] * (len(plan) - len(scenes_text))
    elif len(scenes_text) > len(plan):
        # gộp phần dư vào cảnh cuối
        extra = "\n\n".join(scenes_text[len(plan)-1:])
        scenes_text = scenes_text[:len(plan)-1] + [scenes_text[len(plan)-1] + "\n\n" + extra]

    t = 0
    out_lines = ["## Kịch bản TikTok (Có mốc thời gian)"]
    for i, secs in enumerate(plan, start=1):
        start = _fmt_ms(t)
        t += secs
        end = _fmt_ms(t)
        out_lines.append(f"### Cảnh {i} [{start}–{end}]")
        out_lines.append(scenes_text[i-1].strip() or "(điền nội dung)")
        out_lines.append("")  # dòng trống
    out_lines.append(f"**Tổng thời lượng:** {sum(plan)} giây")
    return "\n".join(out_lines)

def _extract_scenes(model_text: str) -> List[str]:
    # Chuẩn hoá
    system_prompt = prompt_tiktok_vi.strip()
    txt = model_text.strip()
    # Tách theo 'SCENE X:' hoặc 'CẢNH X:'
    parts = re.split(r'(?im)^\s*(?:SCENE|CẢNH)\s+(\d+)\s*:\s*', txt)
    if len(parts) > 1:
        # parts: [prefix, idx1, content1, idx2, content2, ...]
        scenes = []
        # Bỏ parts[0] (prefix trước cảnh 1)
        for j in range(2, len(parts), 2):
            scenes.append(parts[j].strip())
        return [s for s in scenes if s]
    # Fallback: tách theo tiêu đề markdown "## Cảnh X"
    blocks = re.split(r'(?im)^\s*#{1,3}\s*(?:SCENE|CẢNH)\s+\d+.*$', txt)
    if len(blocks) > 1:
        return [b.strip() for b in blocks if b.strip()]
    # Fallback cuối: tách theo 2 dòng trống
    return [b.strip() for b in re.split(r'\n\s*\n', txt) if b.strip()]