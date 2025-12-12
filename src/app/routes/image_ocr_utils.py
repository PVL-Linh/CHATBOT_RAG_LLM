# app/Model_LLM/image_ocr_utils.py
from __future__ import annotations

import os
import re
from typing import List, Tuple, Optional

from PIL import Image, ImageEnhance
from torchvision import transforms as T
from torchvision.transforms.functional import InterpolationMode
try:
    import pytesseract
    import os  # giữ lại hoặc để ngoài cũng được

    # Ưu tiên env var → Docker sẽ dùng /usr/bin/tesseract, local Windows có thể set env nếu muốn
    tesseract_cmd = os.getenv("TESSERACT_PATH", "tesseract")
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    print(f"[OCR] Using tesseract at: {pytesseract.pytesseract.tesseract_cmd}")
    print(f"[OCR] Version: {pytesseract.get_tesseract_version()}")

except Exception as e:
    print("=" * 60)
    print("CẢNH BÁO: Tesseract OCR chưa hoạt động trong image_ocr_utils.py!")
    print(f"Lỗi: {e}")
    print("→ Docker/Linux: phải có package tesseract-ocr + tesseract-ocr-vie")
    print("→ Windows local: set env TESSERACT_PATH='C:\\Program Files\\Tesseract-OCR\\tesseract.exe'")
    print("   hoặc thêm đường dẫn vào PATH")
    print("=" * 60)



# ======================================================================
# 1. TRANSFORM / TILE ẢNH
# ======================================================================

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def build_transform(input_size: int):
    MEAN, STD = IMAGENET_MEAN, IMAGENET_STD
    transform = T.Compose([
        T.Lambda(lambda img: img.convert('RGB') if img.mode != 'RGB' else img),
        T.Resize((input_size, input_size), interpolation=InterpolationMode.BICUBIC),
        T.ToTensor(),
        T.Normalize(mean=MEAN, std=STD),
    ])
    return transform


def find_closest_aspect_ratio(aspect_ratio, target_ratios, width, height, image_size):
    best_ratio_diff = float('inf')
    best_ratio = (1, 1)
    area = width * height
    for ratio in target_ratios:
        target_aspect_ratio = ratio[0] / ratio[1]
        ratio_diff = abs(aspect_ratio - target_aspect_ratio)
        if ratio_diff < best_ratio_diff:
            best_ratio_diff = ratio_diff
            best_ratio = ratio
        elif ratio_diff == best_ratio_diff:
            if area > 0.5 * image_size * image_size * ratio[0] * ratio[1]:
                best_ratio = ratio
    return best_ratio


def dynamic_preprocess(
    image: Image.Image,
    min_num: int = 1,
    max_num: int = 12,
    image_size: int = 448,
    use_thumbnail: bool = True,
):
    orig_width, orig_height = image.size
    aspect_ratio = orig_width / orig_height

    target_ratios = set(
        (i, j)
        for n in range(min_num, max_num + 1)
        for i in range(1, n + 1)
        for j in range(1, n + 1)
        if i * j <= max_num and i * j >= min_num
    )
    target_ratios = sorted(target_ratios, key=lambda x: x[0] * x[1])

    target_aspect_ratio = find_closest_aspect_ratio(
        aspect_ratio, target_ratios, orig_width, orig_height, image_size
    )

    target_width = image_size * target_aspect_ratio[0]
    target_height = image_size * target_aspect_ratio[1]
    blocks = target_aspect_ratio[0] * target_aspect_ratio[1]

    resized_img = image.resize((target_width, target_height), Image.LANCZOS)
    processed_images = []
    for i in range(blocks):
        box = (
            (i % (target_width // image_size)) * image_size,
            (i // (target_width // image_size)) * image_size,
            ((i % (target_width // image_size)) + 1) * image_size,
            ((i // (target_width // image_size)) + 1) * image_size,
        )
        split_img = resized_img.crop(box)
        processed_images.append(split_img)

    assert len(processed_images) == blocks

    if use_thumbnail and len(processed_images) != 1:
        thumbnail_img = image.resize((image_size, image_size), Image.LANCZOS)
        processed_images.append(thumbnail_img)

    return processed_images

# ======================================================================
# 2. CHUẨN HÓA SỐ / HÓA ĐƠN
# ======================================================================

DIGIT_LIKE_MAP = {
    "O": "0", "o": "0",
    "D": "0",
    "I": "1", "l": "1", "|": "1",
    "Z": "2",
    "S": "5", "s": "5",
    "B": "8",
    "g": "9", "q": "9",
}


def _fix_ocr_letter_digit_confusion(text: str) -> str:
    if not text:
        return text

    tokens = re.split(r'(\s+)', text)

    def _fix_token(tok: str) -> str:
        if re.fullmatch(r'[0-9.,]+', tok):
            return tok
        if re.search(r'[A-Za-zÀ-Ỵà-ỵĐđ]', tok) and re.search(r'\d', tok):
            tok = tok.replace('1', 'I')
        return tok

    fixed = ''.join(_fix_token(t) if not t.isspace() else t for t in tokens)
    return fixed


def _normalize_ocr_numbers(text: str) -> str:
    if not text:
        return text

    text = re.sub(
        r'(?<!\d)(\d{1,3}(?:\s\d{3})+)(?!\d)',
        lambda m: m.group(1).replace(" ", ""),
        text
    )

    def _fix_digit_like(m: re.Match) -> str:
        s = m.group(0)
        return "".join(DIGIT_LIKE_MAP.get(ch, ch) for ch in s)

    text = re.sub(
        r'(?<!\d)[0-9OIoOl|ZSBsqg]+(?:[.,][0-9OIoOl|ZSBsqg]+)*(?!\d)',
        _fix_digit_like,
        text,
    )

    text = re.sub(r'\s*([.,])\s*', r'\1', text)

    return text


def _parse_vn_amount_to_int(s: str) -> Optional[int]:
    if not s:
        return None
    digits = re.sub(r'\D', '', s)
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _fmt_vn_amount(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _fix_electric_invoice(text: str) -> str:
    if not text:
        return text

    upper = text.upper()
    if (
        "HÓA ĐƠN GTGT" not in upper
        and "HOA DON GTGT" not in upper
        and "TIỀN ĐIỆN" not in upper
        and "TIEN DIEN" not in upper
        and "ĐIỆN LỰC" not in upper
        and "DIEN LUC" not in upper
    ):
        return text

    m_total = re.search(
        r'T[ỔO]NG\s+(?:C[ỘO]NG\s+)?(?:TI[ỀE]N\s+)?(?:THANH\s+TO[ÁA]N)?[^0-9]*'
        r'(\d{1,3}(?:[.,]\d{3})+)',
        text,
        flags=re.IGNORECASE,
    )
    if not m_total:
        return text

    total_ocr = _parse_vn_amount_to_int(m_total.group(1))
    if total_ocr is None:
        return text

    m_pre = re.search(
        r'(C[ỘO]NG|TI[ỀE]N\s*ĐI[ÊE]N)[^\n]*?(\d{1,3}(?:[.,]\d{3})+)',
        text,
        flags=re.IGNORECASE,
    )
    m_vat = re.search(
        r'(THU[ÊE][^\n]{0,20}?GTGT[^\n]*?)(\d{1,3}(?:[.,]\d{3})+)',
        text,
        flags=re.IGNORECASE,
    )

    pre = _parse_vn_amount_to_int(m_pre.group(2)) if m_pre else None
    vat = _parse_vn_amount_to_int(m_vat.group(2)) if m_vat else None

    m_rate = re.search(
        r'THU[ÊE]\s*SU[ÂA]T\s*GTGT[^\n]*?(\d{1,2})',
        text,
        flags=re.IGNORECASE,
    )
    if m_rate:
        rate = int(m_rate.group(1)) / 100.0
    else:
        rate = 0.1

    use_formula = False
    if pre is None or vat is None:
        use_formula = True
    else:
        if pre + vat != total_ocr:
            use_formula = True

    if use_formula:
        pre = int(round(total_ocr / (1.0 + rate)))
        vat = total_ocr - pre

    pre_str = _fmt_vn_amount(pre)
    vat_str = _fmt_vn_amount(vat)
    total_str = _fmt_vn_amount(total_ocr)

    if m_pre:
        def _repl_pre(m: re.Match) -> str:
            prefix = m.group(1)
            return prefix + " " + pre_str

        text = re.sub(
            r'(C[ỘO]NG|TI[ỀE]N\s*ĐI[ÊE]N)[^\n]*?(\d{1,3}(?:[.,]\d{3})+)',
            _repl_pre,
            text,
            flags=re.IGNORECASE,
        )

    if m_vat:
        def _repl_vat(m: re.Match) -> str:
            prefix = m.group(1)
            return prefix + " " + vat_str

        text = re.sub(
            r'(THU[ÊE][^\n]{0,20}?GTGT[^\n]*?)(\d{1,3}(?:[.,]\d{3})+)',
            _repl_vat,
            text,
            flags=re.IGNORECASE,
        )

    s, e = m_total.span(1)
    text = text[:s] + total_str + text[e:]
    return text


def _fix_water_invoice(text: str) -> str:
    upper = text.upper()
    if (
        "GIẤY BÁO TIỀN NƯỚC" not in upper
        and "GIAY BAO TIEN NUOC" not in upper
        and "TIỀN NƯỚC" not in upper
        and "TIEN NUOC" not in upper
    ):
        return text

    m_water = re.search(
        r'TIỀN\s*NƯỚC[^0-9]*(\d{1,3}(?:[.,]\d{3})+)',
        text, flags=re.IGNORECASE
    )
    m_vat = re.search(
        r'THU[ÊE]\s*GTGT[^0-9]*(\d{1,3}(?:[.,]\d{3})+)',
        text, flags=re.IGNORECASE
    )
    m_fee = re.search(
        r'PHÍ\s*B[ẢA]O\s*V[ỆE]\s*M[ÔO]I\s*TRƯỜNG[^0-9]*(\d{1,3}(?:[.,]\d{3})+)'
        r'|PHÍ\s*BVMT[^0-9]*(\d{1,3}(?:[.,]\d{3})+)',
        text, flags=re.IGNORECASE
    )
    m_total = re.search(
        r'TỔNG\s*CỘNG[^0-9]*(\d{1,3}(?:[.,]\d{3})+)',
        text, flags=re.IGNORECASE
    )

    if not (m_water and m_vat and m_fee and m_total):
        return text

    fee_str = m_fee.group(1) or m_fee.group(2)

    water = _parse_vn_amount_to_int(m_water.group(1))
    vat = _parse_vn_amount_to_int(m_vat.group(1))
    fee = _parse_vn_amount_to_int(fee_str)
    total_ocr = _parse_vn_amount_to_int(m_total.group(1))

    if None in (water, vat, fee, total_ocr):
        return text

    total_expected = water + vat + fee
    if total_expected != total_ocr:
        new_total_str = _fmt_vn_amount(total_expected)
        start, end = m_total.span(1)
        text = text[:start] + new_total_str + text[end:]

    return text


def cleanup_ocr_text(text: str) -> str:
    if not text:
        return text

    text = _normalize_ocr_numbers(text)
    text = _fix_electric_invoice(text)
    text = _fix_water_invoice(text)
    text = _fix_ocr_letter_digit_confusion(text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    print(f"text.strip(): {text.strip()}")
    return text.strip()

# ======================================================================
# 3. TRÍCH SỐ TIỀN TỔNG CỘNG
# ======================================================================

AMOUNT_PATTERN = re.compile(
    r'(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)'
)

KEYWORDS_AMOUNT = [
    "tổng cộng", "tổng số tiền", "cần thanh toán",
    "amount due", "total amount", "balance due",
]


def extract_amount_candidates(text: str) -> List[Tuple[str, str]]:
    lines = text.splitlines()
    results: List[Tuple[str, str]] = []

    for line in lines:
        lower = line.lower()
        if any(kw in lower for kw in KEYWORDS_AMOUNT):
            for m in AMOUNT_PATTERN.finditer(line):
                amt = m.group(1)
                results.append((amt, line.strip()))
    return results

# ======================================================================
# 4. PUBLIC: OCR ẢNH
# ======================================================================

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp")


def is_image_path(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    return ext in IMAGE_EXTS


def extract_text_from_image(path: str) -> str:
    if not os.path.exists(path):
        return ""

    try:
        raw_image = Image.open(path).convert("RGB")
    except Exception as e:
        print(f"[OCR] Không mở được ảnh: {path} | {e}")
        return ""

    try:
        tiles = dynamic_preprocess(
            raw_image,
            image_size=448,
            max_num=12,
            use_thumbnail=True,
        )

        full_text_parts: List[str] = []

        for i, tile in enumerate(tiles):
            scale = 3
            big = tile.resize(
                (tile.width * scale, tile.height * scale),
                Image.LANCZOS,
            )

            big = ImageEnhance.Contrast(big).enhance(3.0)
            gray = big.convert("L")
            bin_img = gray.point(lambda x: 0 if x < 165 else 255, "1")

            text = pytesseract.image_to_string(
                bin_img,
                lang="vie+eng",
                config="--oem 3 --psm 6",
            )

            if text and text.strip():
                full_text_parts.append(f"[Tile {i+1}]\n{text.strip()}")

        result = "\n\n".join(full_text_parts)
        print(
            f"[OCR DYNAMIC] Đọc được {len(result)} ký tự từ {len(tiles)} tiles ← {os.path.basename(path)}"
        )

        if len(result.strip()) < 50:
            big = raw_image.resize(
                (int(raw_image.width * 3), int(raw_image.height * 3)),
                Image.LANCZOS,
            )
            gray = big.convert("L")
            bin_img = gray.point(lambda x: 0 if x < 165 else 255, "1")
            result = pytesseract.image_to_string(
                bin_img,
                lang="vie+eng",
                config="--oem 3 --psm 3",
            )

        return cleanup_ocr_text(result)

    except Exception as e:
        print(f"[OCR DYNAMIC FAIL] {path}: {e}")
        return ""
