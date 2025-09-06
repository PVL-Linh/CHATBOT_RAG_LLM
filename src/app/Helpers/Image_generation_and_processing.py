import os, io, threading, base64
from typing import List, Optional
from io import BytesIO
from PIL import Image, ImageColor

from google.genai import types as genai_types
from .Marketing_Planner.config_FB_contents import  CLIENT_MKT, GEMINI_IMAGE_MODEL_MKT, IMAGEN_MODEL_MKT
from .Occasion_Classifier import classify_occasion_1
from .rate_limit import get_img_limiter

# ====== Semaphore đồng thời riêng cho ảnh
IMG_SEM = threading.Semaphore(int(os.getenv("SEM_IMG", "16")))
IMG_LIMITER = get_img_limiter()

# ====== Aspect helpers
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

# ====== Prompt Builder (giữ nguyên API)
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

# ====== Image Generation (đã thêm limiter + semaphore + degrade)
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

    # Shaping: nếu hàng đợi quá lâu -> tự hạ còn 1 ảnh + dùng model nhanh
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

# ====== Logo & utils (giữ nguyên API)
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
