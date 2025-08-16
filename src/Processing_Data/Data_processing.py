import re


def is_unwanted_line(line):
    """Loại bỏ dòng nếu:
    - Chỉ chứa số (số trang)
    - Là dòng gạch ngang như -----, _____, =====, v.v.
    - Là dòng header chứa tên tài liệu và số trang
    """
    stripped = line.strip()

    # Dòng chỉ chứa số
    if stripped.isdigit():
        return True

    # Dòng gạch ngang
    if re.fullmatch(r"[-_=\u2500\u2014\s]{3,}", stripped):
        return True

    # Dòng chứa tiêu đề và số trang (như trong hình)
    if re.search(r"giáo trình.*\d{1,3}$", stripped.lower()):
        return True

    return False

def latexify_line(line):
    """Nếu dòng chứa công thức toán học, chuyển sang định dạng LaTeX."""
    math_symbols = ["∑", "^", "_", "/", "Q", "N", "K_d"]
    if any(sym in line for sym in math_symbols):
        return f"$$ {line.strip()} $$"
    return line.strip()

def clean_page_text(text):
    """Làm sạch văn bản từ trang: lọc dòng, gộp đoạn và xử lý các bullet - + * và công thức."""
    lines = text.splitlines()
    filtered_lines = [line.strip() for line in lines if not is_unwanted_line(line)]

    paragraph = ""
    result = []

    for line in filtered_lines:
        line = latexify_line(line)  # Áp dụng latex hóa nếu cần

        # Nếu là dòng danh sách bắt đầu bằng - + *
        if re.match(r"^[-+*]\s+", line):
            if paragraph:
                result.append(paragraph.strip())
                paragraph = ""
            result.append(line)  # Bullet xuống dòng riêng
            continue

        # Nếu là dòng công thức LaTeX thì cho xuống dòng riêng
        if line.startswith("$$") and line.endswith("$$"):
            if paragraph:
                result.append(paragraph.strip())
                paragraph = ""
            result.append(line)
            continue

        # Nếu là dòng trắng
        if not line:
            if paragraph:
                result.append(paragraph.strip())
                paragraph = ""
            continue

        # Nếu dòng kết thúc bằng dấu chấm hoặc ! ?
        if re.search(r"[.!?]$", line):
            paragraph += line + " "
            result.append(paragraph.strip())
            paragraph = ""
        else:
            paragraph += line + " "

    if paragraph:
        result.append(paragraph.strip())

    return "\n\n".join(result)