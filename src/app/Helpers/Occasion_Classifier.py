import re
import unicodedata

def _strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return s

def classify_occasion_1(subject: str) -> str:
    if not subject:
        return "none"

    raw = subject.strip()
    s = _strip_accents(raw).lower()
    two_nine_regex = r"(?<!\d)(0?2)[\s./\-](0?9)(?!\d)"
    if (re.search(two_nine_regex, s) or
        "quoc khanh" in s or
        "quốc khánh" in raw.lower() or
        "vietnam national day" in s or
        "vn national day" in s or
        "national day of vietnam" in s):
        return "national_day"

    if ("tet" in s or "tết" in raw.lower() or
        "tet nguyen dan" in s or
        "lunar new year" in s or
        "mung xuan" in s or
        "don xuan" in s):
        return "tet"

    if ("giang sinh" in s or "giáng sinh" in raw.lower() or
        "christmas" in s or
        "noel" in s):
        return "xmas"

    if "black friday" in s or re.search(r"\bbf\b", s):
        return "bf"

    womens_regex = r"(?<!\d)(0?8)[\s./\-](0?3)(?!\d)"
    if (re.search(womens_regex, s) or
        "phu nu" in s or "phụ nữ" in raw.lower() or
        "women's day" in s or "international women's day" in s):
        return "womens"

    return "none"


def build_image_prompt(subject: str, aspect_ratio: str = "1:1") -> str:
    occ = classify_occasion_1(subject)
    if occ == "national_day":
        extras = [
            "Vietnamese national flags",
            "fireworks over Ho Chi Minh City",
            "crowds celebrating in the streets",
            "red and gold festive palette"
        ]
    elif occ == "tet":
        extras = ["peach blossoms and red lanterns", "family gathering vibe", "firecrackers ambiance"]
    elif occ == "xmas":
        extras = ["twinkling lights and ornaments", "cozy winter market setting", "warm, festive ambiance"]
    elif occ == "bf":
        extras = ["dynamic shopping crowds", "bold contrast lighting", "high-energy retail vibes"]
    elif occ == "womens":
        extras = ["bouquets and celebratory ribbons", "uplifting urban scenes", "soft, elegant accents"]
    else:
        extras = ["contextual elements that clearly reflect the topic"]

    extras_text = ", ".join(extras)
    return (
        f"A highly detailed, modern semi-realistic illustration featuring the official Tiximax Logistics logo "
        f"integrated naturally into the scene. Main subject: {subject}. "
        f"Background: {extras_text}. Mood: vivid, celebratory, culturally immersive. "
        f"Lighting: bright, cinematic, realistic shadows and highlights. "
        f"Style: polished, soft depth of field, production-ready. "
        f"No text, no watermark. Aspect ratio {aspect_ratio}."
    )
