# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Optional, Tuple, List

from PIL import Image, ImageOps, ImageDraw, ImageChops

from flask import current_app

# Dùng lại loader + base64 có sẵn của bạn
from ..Image_generation_and_processing import load_default_logo, pil_to_base64


def _exif_safe(img: Image.Image) -> Image.Image:
    """Tôn trọng EXIF orientation nhưng KHÔNG thay đổi kích thước."""
    try:
        return ImageOps.exif_transpose(img)
    except Exception:
        return img


def _place_logo(
    base_rgba: Image.Image,
    logo_img: Image.Image,
    scale: float = 0.12,           # 0..1 theo min(w,h) ảnh gốc
    margin_px: int = 20,
    position: str = "br",          # 'br','bl','tr','tl'
) -> Tuple[Image.Image, Tuple[int, int, int, int]]:
    """
    Dán logo lên ảnh gốc (không đổi kích thước/cắt ảnh gốc).
    Trả về (ảnh sau khi dán, bbox vùng logo).
    """
    if base_rgba.mode != "RGBA":
        base_rgba = base_rgba.convert("RGBA")
    L = logo_img.convert("RGBA")

    bw, bh = base_rgba.size
    s = max(0.02, min(0.35, float(scale)))  # clamp an toàn theo min(w,h)
    target = int(min(bw, bh) * s)
    if target < 4:
        return base_rgba, (0, 0, 0, 0)

    lw, lh = L.size
    if lw >= lh:
        new_w = target
        new_h = max(1, int(lh * target / max(1, lw)))
    else:
        new_h = target
        new_w = max(1, int(lw * target / max(1, lh)))
    L = L.resize((new_w, new_h), Image.LANCZOS)

    m = int(margin_px)
    if position == "bl":
        x = m
        y = bh - new_h - m
    elif position == "tr":
        x = bw - new_w - m
        y = m
    elif position == "tl":
        x = m
        y = m
    else:  # 'br'
        x = bw - new_w - m
        y = bh - new_h - m

    out = base_rgba.copy()
    out.alpha_composite(L, (x, y))
    bbox = (x, y, x + new_w, y + new_h)
    return out, bbox


def _similarity_outside_bbox(
    img_before: Image.Image,
    img_after: Image.Image,
    exclude_bbox: Tuple[int, int, int, int],
) -> float:
    """
    Tính % pixel giống nhau bên ngoài bbox (vùng logo), trong không gian RGBA.
    1.0 = giống tuyệt đối.
    """
    a = img_before.convert("RGBA")
    b = img_after.convert("RGBA")
    if a.size != b.size:
        return 0.0

    w, h = a.size

    # Tạo mask = 255 ở mọi nơi TRỪ bbox logo
    mask = Image.new("L", (w, h), 255)
    if exclude_bbox and exclude_bbox != (0, 0, 0, 0):
        x1, y1, x2, y2 = [max(0, v) for v in exclude_bbox]
        x1, y1 = min(x1, w), min(y1, h)
        x2, y2 = min(x2, w), min(y2, h)
        d = ImageDraw.Draw(mask)
        d.rectangle([x1, y1, x2, y2], fill=0)

    # Sai khác pixel
    diff = ImageChops.difference(a, b).convert("L")
    # Áp mask để chỉ xét bên ngoài bbox
    diff_masked = ImageChops.multiply(diff, mask)

    # Đếm pixel khác biệt
    nonzero = sum(1 for px in diff_masked.getdata() if px != 0)
    total = w * h - (exclude_bbox[2] - exclude_bbox[0]) * (exclude_bbox[3] - exclude_bbox[1])
    total = max(1, total)  # tránh chia 0
    same = total - nonzero
    return same / total


def exact_logo_overlay(
    ref: Image.Image,
    add_logo: bool = True,
    logo_img: Optional[Image.Image] = None,
    logo_scale: float = 0.12,
    logo_margin: int = 20,
    logo_pos: str = "br",
    min_similarity: float = 0.99,
    output_format: str = "png",   # << thêm
):
    base = _exif_safe(ref)
    before = base.copy()

    if add_logo:
        if logo_img is None:
            logo_img = load_default_logo(current_app.root_path)
        if logo_img is None:
            out = base
            bbox = (0, 0, 0, 0)
        else:
            out, bbox = _place_logo(
                base_rgba=base,
                logo_img=logo_img,
                scale=float(logo_scale),
                margin_px=int(logo_margin),
                position=str(logo_pos).lower(),
            )
    else:
        out = base
        bbox = (0, 0, 0, 0)

    sim = _similarity_outside_bbox(before, out, bbox)
    note = "OK" if sim >= float(min_similarity) else f"SIM<{min_similarity:.2f}: {sim:.4f}"

    # giữ định dạng theo yêu cầu
    return pil_to_base64(out, fmt=output_format), sim, note
