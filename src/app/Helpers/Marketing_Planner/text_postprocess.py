import re

# ===== Regex & utils =====
_HEAD_RE = re.compile(
    r'^\s*(#{1,6}\s+.*|[A-ZÀ-Ỵ].{0,120}\n[-=]{2,})\s*$',
    re.M | re.U
)

def _remove_debug_lines(s: str) -> str:
    """Bỏ các dòng debug kiểu FINISH / TOKENS / WORD_COUNT."""
    if not s:
        return s
    s = re.sub(r'^\s*FINISH:\s*\w+\s*\|\s*TOKENS:\s*\d+\s*$', '', s, flags=re.M)
    s = re.sub(r'(?im)^\s*WORD_COUNT:\s*\d+\s*$', '', s)
    return s.strip()

def strip_after_marker(s: str, marker: str = "[[END]]") -> str:
    """Nếu prompt yêu cầu kết thúc bằng [[END]], cắt phần sau marker."""
    s = s or ""
    idx = s.find(marker)
    return s[:idx].strip() if idx != -1 else s.strip()

def cut_on_repeated_headings(s: str, max_repeat: int = 2) -> str:
    """
    Nếu cùng một heading (sau normalize) xuất hiện > max_repeat lần, cắt tại lần dư.
    Chặn tình trạng model “viết lại bài mới” bên dưới.
    """
    if not s:
        return s
    seen = {}
    for m in _HEAD_RE.finditer(s):
        head = re.sub(r'\s+', ' ', m.group(1)).strip().lower()
        seen[head] = seen.get(head, 0) + 1
        if seen[head] > max_repeat:
            return s[:m.start()].rstrip()
    return s.strip()

def truncate_words(s: str, limit: int = 2400) -> str:
    """Cắt an toàn theo số từ (giữ lại cho nơi khác nếu cần)."""
    if not s:
        return s
    words = re.findall(r'\S+', s)
    if len(words) <= limit:
        return s.strip()
    count = 0
    cutoff = None
    for m in re.finditer(r'\S+', s):
        count += 1
        if count > limit:
            cutoff = m.start()
            break
    if cutoff is None:
        return s.strip()
    return (s[:cutoff].rstrip() + "\n\n[Đã rút gọn theo giới hạn từ.]").strip()

def _remove_all_meta_blocks(s: str) -> str:
    """
    Bỏ toàn bộ các dòng Meta/Slug thừa trong phần nội dung sinh.
    (Sau này sẽ patch meta cố định ở đầu).
    """
    if not s:
        return s
    s = re.sub(r'(?im)^\s*Meta\s*Title\s*:\s*.*$', '', s)
    s = re.sub(r'(?im)^\s*Meta\s*Description\s*:\s*.*$', '', s)
    s = re.sub(r'(?im)^\s*URL\s*Slug\s*:\s*.*$', '', s)
    s = re.sub(r'\n{3,}', '\n\n', s)
    return s.strip()

def _keep_only_first_section(s: str, heading_re: re.Pattern) -> str:
    """
    Giữ lại duy nhất section đầu tiên trùng heading pattern; xoá các lần sau (từ heading đó đến heading kế).
    """
    if not s:
        return s
    matches = list(heading_re.finditer(s))
    if len(matches) <= 1:
        return s

    cut_ranges = []
    for i in range(1, len(matches)):
        start_i = matches[i].start()
        after = s[start_i:]
        nxt = _HEAD_RE.search(after[1:])  # bỏ 1 char để không match chính nó
        if nxt:
            end_i = start_i + 1 + nxt.start()
        else:
            end_i = len(s)
        cut_ranges.append((start_i, end_i))

    out = s
    for a, b in reversed(cut_ranges):
        out = out[:a].rstrip() + "\n"
    return out.strip()

def sanitize_blog_article(s: str) -> str:
    """
    Hậu xử lý mạnh tay:
    - Gỡ FINISH/TOKENS/WORD_COUNT
    - Gỡ META/SLUG rác trong thân
    - Giữ 1 block FAQ & 1 block Kết luận
    - Nén khoảng trắng
    - Chặn lặp heading lớn
    """
    if not s:
        return s
    orig = (s or "").strip()            # <--- giữ bản gốc

    s = _remove_debug_lines(s)           # gỡ FINISH/TOKENS/WORD_COUNT  :contentReference[oaicite:0]{index=0}
    s = _remove_all_meta_blocks(s)       # gỡ META rác                 :contentReference[oaicite:1]{index=1}

    # Giữ 1 block FAQ/Kết luận, chặn lặp heading, nén khoảng trắng
    faq_re = re.compile(r'(?im)^\s*(?:#{1,6}\s*)?(?:phần\s*hỏi[\-–]\s*đáp|faq)\b.*$')
    s = _keep_only_first_section(s, faq_re)                                # :contentReference[oaicite:2]{index=2}
    kl_re  = re.compile(r'(?im)^\s*(?:#{1,6}\s*)?(?:kết\s*luận|kết\s*luận\s*\+\s*cta)\b.*$')
    s = _keep_only_first_section(s, kl_re)                                 # :contentReference[oaicite:3]{index=3}
    s = cut_on_repeated_headings(s, max_repeat=2)                          # :contentReference[oaicite:4]{index=4}
    s = re.sub(r'[ \t]+\n', '\n', s)
    s = re.sub(r'\n{3,}', '\n\n', s)
    s = s.strip()
    return s or orig


def strip_toc_from_output(s: str) -> str:
    """
    Xoá 'Mục lục' / 'Nội dung' / 'Table of Contents' nếu có (đến heading kế tiếp).
    """
    if not s:
        return s
    toc = re.compile(r'(?im)^\s*(mục\s*lục|nội\s*dung|table\s+of\s+contents)\s*$')
    m = toc.search(s)
    if not m:
        return s.strip()

    start = m.start()
    after = s[start:]
    nxt = _HEAD_RE.search(after[1:])
    if nxt:
        end = start + 1 + nxt.start()
    else:
        end = len(s)
    out = (s[:start] + s[end:]).strip()
    out = re.sub(r'\n{3,}', '\n\n', out)
    return out

def patch_meta(body: str, meta_title: str = "", meta_desc: str = "", slug: str = "") -> str:
    """
    Ghim Meta/Slug vào đầu output (1 lần duy nhất).
    """
    lines = []
    if meta_title:
        lines.append(f"Meta Title: {meta_title.strip()}")
    if meta_desc:
        lines.append(f"Meta Description: {meta_desc.strip()}")
    if slug:
        lines.append(f"URL Slug: {slug.strip()}")
    if lines:
        meta_block = "\n".join(lines) + "\n\n"
        return meta_block + (body or "").lstrip()
    return (body or "").strip()
