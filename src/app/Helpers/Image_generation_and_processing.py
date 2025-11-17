import os, io, threading, base64
from typing import List, Optional, Tuple
from io import BytesIO
from PIL import Image, ImageOps, ImageDraw, ImageFont, ImageColor
import math
from google.genai import types as genai_types
from app.config.config_FB_contents import  CLIENT_MKT, GEMINI_IMAGE_MODEL_MKT, IMAGEN_MODEL_MKT
from .Occasion_Classifier import classify_occasion_1
from .rate_limit import get_img_limiter


IMG_SEM = threading.Semaphore(int(os.getenv("SEM_IMG", "16")))
IMG_LIMITER = get_img_limiter()

ALLOWED_ASPECTS = {"1:1", "16:9", "4:3", "9:16", "3:4"}

def _parse_ratio(r: str) -> Optional[float]:
    try:
        a, b = r.split(":")
        return float(a) / float(b)
    except Exception:
        return None

def conform_aspect(img: Image.Image, ratio_str: str, mode: str = "crop", bg: str = "#FFFFFF") -> Image.Image:
    r = _parse_ratio(ratio_str)
    if not r:
        return img
    w, h = img.size
    cur = w / h
    if abs(cur - r) < 1e-3:
        return img

    if mode == "crop":
        if cur > r:
            new_w = int(h * r)
            x = (w - new_w) // 2
            return img.crop((x, 0, x + new_w, h))
        else:
            new_h = int(w / r)
            y = (h - new_h) // 2
            return img.crop((0, y, w, y + new_h))
    else:
        rgb = ImageColor.getcolor(bg, "RGB")
        if cur > r:
            new_h = int(w / r)
            canvas = Image.new("RGB", (w, new_h), rgb)
            y = (new_h - h) // 2
            canvas.paste(img, (0, y))
            return canvas
        else:
            new_w = int(h * r)
            canvas = Image.new("RGB", (new_w, h), rgb)
            x = (new_w - w) // 2
            canvas.paste(img, (x, 0))
            return canvas

def build_image_prompt(
    subject: str,
    aspect_ratio: str,
    style: str = "Semi-realistic",
    composition: str = "Lifestyle scene",
    include_logo: bool = True
) -> str:
    occasion = classify_occasion_1(subject)
    occasion_extras = {
        "national_day": [
            "Vietnamese national flags",
            "fireworks over Ho Chi Minh City skyline",
            "celebratory red and gold palette",
            "modern Saigon street vibe"
        ],
        "tet": [
            "peach blossoms", "red lanterns", "family gathering vibe", "firecrackers ambiance"
        ],
        "xmas": ["twinkling lights", "ornaments", "cozy market", "warm ambiance"],
        "bf": ["dynamic shopping crowds", "high-contrast lighting", "retail energy"],
        "womens": ["bouquets", "elegant ribbons", "uplifting mood"]
    }
    extras = occasion_extras.get(occasion, ["contextual elements that clearly reflect the topic"])

    comp_styles = {
        "Centered product": "single main subject centered, clean background, symmetrical layout",
        "Lifestyle scene": "natural candid scene with people interacting, depth and environment context",
        "Festive crowd": "wide crowd scene, dynamic motion, confetti and fireworks, city backdrop",
        "Minimal poster": "minimalist composition, lots of negative space, graphic layout"
    }

    style_map = {
        "Semi-realistic": "modern semi-realistic illustration, soft depth of field",
        "Photoreal": "highly detailed photorealistic look, physically based rendering",
        "3D render": "high-quality CGI render, studio lighting, smooth materials",
        "Flat illustration": "flat vector illustration, clean shapes, simple shading"
    }

    logo_line = (
        "Accurately integrate the official Tiximax rocket logo; keep exact colors/shapes; do not stylize. "
        if include_logo else ""
    )

    prompt = (
        "Create a high-quality campaign visual. "
        f"Main subject: {subject}. Occasion context: {', '.join(extras)}. "
        f"Composition: {comp_styles.get(composition, comp_styles['Lifestyle scene'])}. "
        f"Style: {style_map.get(style, style_map['Semi-realistic'])}. " + logo_line +
        "Lighting: bright, cinematic, realistic shadows and highlights. "
        "Background: polished, clean, production-ready. No text, no watermark. "
        f"Aspect ratio {aspect_ratio}."
    )
    return prompt

def _estimate_img_tokens(prompt: str, n_images: int) -> int:
    return int(0.8 * len((prompt or "").split())) + 800 * max(1, n_images)

def generate_image_via_gemini_api(
    prompt_en: str,
    engine: str = "gemini2",
    aspect_ratio: str = "1:1",
    n_images: int = 1
) -> List[Image.Image]:
    images: List[Image.Image] = []
    degraded = False
    try:
        IMG_LIMITER.acquire(_estimate_img_tokens(prompt_en, n_images))
    except TimeoutError:
        n_images = 1
        engine = "gemini2"
        degraded = True
        IMG_LIMITER.acquire(_estimate_img_tokens(prompt_en, n_images))

    try:
        with IMG_SEM:
            if engine == "imagen4":
                resp = CLIENT_MKT.models.generate_images(
                    model=IMAGEN_MODEL_MKT,
                    prompt=prompt_en,
                    config=genai_types.GenerateImagesConfig(
                        number_of_images=max(1, min(n_images, 4)),
                        aspect_ratio=aspect_ratio
                    )
                )
                for giw in getattr(resp, "generated_images", []):
                    gi = giw.image
                    if isinstance(gi, Image.Image):
                        images.append(gi)
                    else:
                        b = getattr(gi, "image_bytes", None)
                        if b:
                            try:
                                images.append(Image.open(BytesIO(b)))
                            except Exception:
                                pass
            else:
                loops = max(1, min(n_images, 3))
                for _ in range(loops):
                    resp = CLIENT_MKT.models.generate_content(
                        model=GEMINI_IMAGE_MODEL_MKT,
                        contents=prompt_en,
                        config=genai_types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"])
                    )
                    cand = resp.candidates[0] if getattr(resp, "candidates", None) else None
                    parts = cand.content.parts if cand and getattr(cand, "content", None) else []
                    for p in parts:
                        if getattr(p, "inline_data", None) and getattr(p.inline_data, "data", None):
                            try:
                                images.append(Image.open(BytesIO(p.inline_data.data)))
                                break
                            except Exception:
                                pass

        IMG_LIMITER.on_success()
        return images
    except Exception as e:
        if "429" in str(e) or "quota" in str(e).lower() or "rate" in str(e).lower():
            IMG_LIMITER.on_429()
        raise

def add_logo_to_images(
    images: List[Image.Image],
    logo_img: Image.Image,
    margin: int = 20,
    keep_original: bool = True,
    scale: float = 0.15
) -> List[Image.Image]:
    out = []
    logo = logo_img.convert("RGBA")
    for img in images:
        bg = img.convert("RGBA")
        if keep_original:
            logo_processed = logo
        else:
            logo_width = max(1, int(bg.width * scale))
            logo_height = int(logo_width * logo.height / logo.width)
            logo_processed = logo.resize((logo_width, logo_height), Image.LANCZOS)
        bg.paste(logo_processed, (int(margin), int(margin)), logo_processed)
        out.append(bg)
    return out

def pil_to_base64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")

def load_default_logo(app_root_path: str) -> Optional[Image.Image]:
    default_path = os.path.join(app_root_path, "static", "images", "logo.png")
    if os.path.exists(default_path):
        try:
            return Image.open(default_path).convert("RGBA")
        except Exception:
            return None
    return None




def file_storage_to_pil(fs) -> Optional[Image.Image]:
    if not fs:
        return None
    try:
        img = Image.open(getattr(fs, "stream", fs)).convert("RGBA")
        return ImageOps.exif_transpose(img)
    except Exception:
        return None

def exif_safe(img: Image.Image) -> Image.Image:
    try:
        return ImageOps.exif_transpose(img)
    except Exception:
        return img

def pil_to_base64_fmt(img: Image.Image, fmt: str = "PNG", jpeg_quality: int = 95) -> str:
    buf = io.BytesIO()
    fmt = (fmt or "PNG").upper()
    im = img
    if fmt in ("JPG", "JPEG"):
        if im.mode not in ("RGB", "L"):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1] if im.mode == "RGBA" else None)
            im = bg
        im.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
    elif fmt == "WEBP":
        im.save(buf, format="WEBP")
    else:
        im.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")

def infer_output_format_from_upload(fs, default: str = "png") -> str:
    try:
        mime = (getattr(fs, "mimetype", "") or "").lower()
    except Exception:
        mime = ""
    name = (getattr(fs, "filename", "") or getattr(fs, "name", "") or "").lower()

    if "jpeg" in mime or "jpg" in mime or name.endswith((".jpg", ".jpeg")):
        return "jpeg"
    if "webp" in mime or name.endswith(".webp"):
        return "webp"
    if "png" in mime or name.endswith(".png"):
        return "png"
    return (default or "png").lower()

def _place_logo_exact(
    base_rgba: Image.Image,
    logo_img: Image.Image,
    scale: float = 0.15,
    margin_px: int = 20,
    position: str = "br",
) -> Tuple[Image.Image, Tuple[int, int, int, int]]:
    """
    Dán logo theo tỉ lệ bề rộng ảnh, giữ tỉ lệ logo. position ∈ {br, bl, tr, tl, center}
    """
    base = base_rgba.copy()
    w, h = base.size
    lw = max(1, int(w * float(scale)))
    ratio = max(1e-6, logo_img.width / max(1, logo_img.height))
    lh = max(1, int(lw / ratio))
    logo_resized = logo_img.resize((lw, lh), Image.LANCZOS)

    pos = (position or "br").lower()
    if pos in ("tr", "rt"):
        x = w - lw - margin_px
        y = margin_px
    elif pos in ("br", "rb"):
        x = w - lw - margin_px
        y = h - lh - margin_px
    elif pos in ("bl", "lb"):
        x = margin_px
        y = h - lh - margin_px
    elif pos in ("center", "c"):
        x = (w - lw) // 2
        y = (h - lh) // 2
    else:  # "tl"
        x = margin_px
        y = margin_px

    base.alpha_composite(logo_resized, (x, y))
    bbox = (x, y, x + lw, y + lh)
    return base, bbox

def overlay_exact_from_upload(
    image_file,
    *,
    add_logo: bool = True,
    logo_file=None,
    logo_scale: float = 0.15,
    logo_margin: int = 20,
    logo_pos: str = "br",
    output_format: Optional[str] = None,
    app_root_path: Optional[str] = None,
    ) -> Tuple[str, dict]:

    base = file_storage_to_pil(image_file)
    if base is None:
        raise ValueError("Ảnh không hợp lệ")

    out = exif_safe(base.convert("RGBA"))
    bbox = (0, 0, 0, 0)

    if add_logo:
        logo = file_storage_to_pil(logo_file) if logo_file else load_default_logo(app_root_path or os.getcwd())
        if logo is not None:
            out, bbox = _place_logo_exact(
                base_rgba=out,
                logo_img=logo,
                scale=float(logo_scale),
                margin_px=int(logo_margin),
                position=str(logo_pos or "br").lower(),
            )

    fmt = (output_format or infer_output_format_from_upload(image_file, "png")).lower()
    b64 = pil_to_base64_fmt(out, fmt=fmt)
    meta = {
        "flow": "image-exact/overlay-only",
        "format": fmt,
        "logo_pos": logo_pos,
        "logo_scale": logo_scale,
        "logo_margin": logo_margin,
        "logo_bbox": bbox,
    }
    return b64, meta

def generate_image_simple_fallback(
    idea_text: str = "",
    *,
    aspect: str = "1:1",
    add_logo: bool = True,
    logo_file=None,
    logo_scale: float = 0.15,
    logo_margin: int = 20,
    logo_pos: str = "br",
    app_root_path: Optional[str] = None,
    output_format: str = "png",
    ) -> Tuple[str, dict]:
    if aspect == "16:9":
        size = (1280, 720)
    elif aspect == "9:16":
        size = (720, 1280)
    elif aspect == "4:5":
        size = (1080, 1350)
    elif aspect in ("3:4", "4:3"):
        size = (1200, 1600) if aspect == "3:4" else (1600, 1200)
    else:
        size = (1024, 1024)

    img = Image.new("RGBA", size, (237, 242, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 40)
    except Exception:
        font = ImageFont.load_default()

    txt = (idea_text or "Generated Image (demo)\n— Replace with your AI pipeline —").strip()
    lines = []
    for line in txt.splitlines():
        while len(line) > 0:
            lines.append(line[:36])
            line = line[36:]
    y = 40
    for ln in lines[:16]:
        draw.text((40, y), ln, font=font, fill=(30, 30, 30, 255))
        y += 46

    if add_logo:
        logo = file_storage_to_pil(logo_file) if logo_file else load_default_logo(app_root_path or os.getcwd())
        if logo is not None:
            img, bbox = _place_logo_exact(
                base_rgba=img,
                logo_img=logo,
                scale=float(logo_scale),
                margin_px=int(logo_margin),
                position=str(logo_pos or "br").lower(),
            )
        else:
            bbox = (0, 0, 0, 0)
    else:
        bbox = (0, 0, 0, 0)

    b64 = pil_to_base64_fmt(img, fmt=(output_format or "png"))
    meta = {
        "flow": "demo-generate",
        "format": (output_format or "png").lower(),
        "aspect": aspect,
        "logo_pos": logo_pos,
        "logo_scale": logo_scale,
        "logo_margin": logo_margin,
        "logo_bbox": bbox,
    }
    return b64, meta


def _rgb_to_color_name(r, g, b):
    """Quy RGB về tên màu đơn giản (tiếng Việt)."""
    def dist(a,b): return sum((x - y) ** 2 for x, y in zip(a,b))
    palette = {
        "trắng": (245,245,245),
        "đen": (15,15,15),
        "xám": (128,128,128),
        "đỏ": (200,40,40),
        "cam": (230,120,30),
        "vàng": (235,200,60),
        "xanh lá": (60,160,60),
        "xanh dương": (60,100,200),
        "tím": (130,70,160),
        "hồng": (235,120,170),
        "nâu": (110,70,40),
    }
    name = min(palette.items(), key=lambda kv: dist((r,g,b), kv[1]))[0]
    return name

def analyze_image_features(pil_img):
    img = pil_img.convert("RGB")
    w, h = img.size

    # Orientation
    if w == h:
        orientation = "vuông"
    elif w > h:
        orientation = "ngang"
    else:
        orientation = "dọc"

    # Aspect
    ratio = w / h if h else 1.0
    def near(x, y, eps=0.04):  # ±4%
        return abs(x - y) / y <= eps
    if near(ratio, 1.0):
        aspect_label = "1:1"
    elif near(ratio, 16/9):
        aspect_label = "16:9"
    elif near(ratio, 4/3):
        aspect_label = "4:3"
    elif near(ratio, 3/4):
        aspect_label = "3:4"
    elif near(ratio, 9/16):
        aspect_label = "9:16"
    else:
        num = int(round(ratio * 100))
        den = 100
        g = math.gcd(num, den)
        aspect_label = f"{num//g}:{den//g}"

    small = img.resize((64, 64))
    colors = small.getcolors(64*64) or []
    def weight(c):
        _, (r,g,b) = c
        if r>240 and g>240 and b>240: return 0.2
        if r<20 and g<20 and b<20:   return 0.2
        return 1.0
    if colors:
        best = max(colors, key=lambda c: c[0] * weight(c))
        dominant_rgb = best[1]
    else:
        dominant_rgb = small.getpixel((32,32))
    dom_name = _rgb_to_color_name(*dominant_rgb)

    lum = small.convert("L")
    px = list(lum.getdata())
    mean_l = sum(px)/len(px) if px else 128
    if mean_l >= 190:
        brightness = "rất sáng"
    elif mean_l >= 150:
        brightness = "sáng"
    elif mean_l >= 110:
        brightness = "trung tính"
    elif mean_l >= 70:
        brightness = "hơi tối"
    else:
        brightness = "tối"

    return {
        "width": w,
        "height": h,
        "orientation": orientation,
        "aspect_label": aspect_label,
        "dominant_color_name": dom_name,
        "brightness": brightness,
    }