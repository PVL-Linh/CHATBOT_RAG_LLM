# vinai_stt.py
import os, wave, contextlib, audioop, json
from typing import List, Tuple, Dict, Optional

import speech_recognition as srec

# ============ cấu hình =============
LANG_MAP = {"vi": "vi", "en": "en"}  # cho Whisper; Google dùng vi-VN/en-US
GOOGLE_LANG = {"vi": "vi-VN", "en": "en-US"}
FRAME_MS, MIN_SPEECH_MS, MIN_SIL_MS, MAX_SEG_MS = 30, 150, 350, 25000

def _read_wav_mono16(path: str):
    with contextlib.closing(wave.open(path, "rb")) as wf:
        ch, sw, sr, n = wf.getnchannels(), wf.getsampwidth(), wf.getframerate(), wf.getnframes()
        raw = wf.readframes(n)
    if sw != 2:
        raw = audioop.lin2lin(raw, sw, 2)
    if ch != 1:
        if ch == 2:
            raw = audioop.tomono(raw, 2, 0.5, 0.5)
        else:
            frame = 2; frames = len(raw)//(ch*frame)
            mono = bytearray(frames*frame)
            for i in range(frames):
                acc = b"\x00\x00"
                for c in range(ch):
                    start = (i*ch+c)*frame
                    acc = audioop.add(acc, raw[start:start+frame], 2)
                mono[i*frame:(i+1)*frame] = audioop.mul(acc, 2, 1.0/ch)
            raw = bytes(mono)
    return raw, sr

def _simple_vad_intervals(raw: bytes, sr: int) -> List[Tuple[int,int]]:
    fb = max(320, int(sr * (FRAME_MS/1000.0)) * 2)
    total = max(1, len(raw)//fb)
    base_frames = min(total, int(1000/FRAME_MS))
    rms0 = [audioop.rms(raw[i*fb:(i+1)*fb], 2) for i in range(base_frames)] or [200]
    base = max(150, sum(rms0)/len(rms0))
    thresh = base * 1.4  # mềm hơn

    intervals, in_speech, s0, sil, cur = [], False, 0, 0, 0
    min_sp = max(1, int(MIN_SPEECH_MS/FRAME_MS))
    min_sil= max(1, int(MIN_SIL_MS/FRAME_MS))
    max_seg= max(1, int(MAX_SEG_MS/FRAME_MS))

    for i in range(total):
        b0, b1 = i*fb, (i+1)*fb
        voiced = audioop.rms(raw[b0:b1], 2) >= thresh
        if not in_speech and voiced:
            in_speech, s0, sil, cur = True, i, 0, 0
        elif in_speech:
            cur += 1
            sil = 0 if voiced else sil+1
            if sil >= min_sil or cur >= max_seg:
                if (i - s0 - sil) >= min_sp:
                    intervals.append((s0*FRAME_MS, (i-sil)*FRAME_MS))
                in_speech, sil, cur = False, 0, 0

    if in_speech:
        i = total
        if (i - s0 - sil) >= min_sp:
            intervals.append((s0*FRAME_MS, (i-sil)*FRAME_MS))

    if not intervals:
        dur_ms = int(len(raw)/(2*sr)*1000)
        intervals = [(0, dur_ms)]
    return intervals

def _to_ad(raw: bytes, sr: int, s_ms: int, e_ms: int) -> srec.AudioData:
    a = int(s_ms * sr / 1000) * 2
    b = int(e_ms * sr / 1000) * 2
    return srec.AudioData(raw[a:b], sr, 2)

def _google_try(ad: srec.AudioData, user_lang: str) -> str:
    r = srec.Recognizer()
    # google dạng web API: ngôn ngữ kiểu vi-VN / en-US
    cand = []
    if user_lang in ("vi","en"):
        cand = [GOOGLE_LANG[user_lang], GOOGLE_LANG["en" if user_lang=="vi" else "vi"]]
    else:
        cand = ["vi-VN","en-US"]
    last = None
    for lg in cand:
        try:
            txt = r.recognize_google(ad, language=lg, show_all=False)
            if txt: return txt
        except srec.UnknownValueError:
            continue
        except srec.RequestError as e:
            last = e
            continue
    if last:
        raise RuntimeError(f"Google SR request failed: {last}")
    return ""

def _vosk_transcribe(raw: bytes, sr: int, user_lang: str) -> str:
    try:
        import vosk
    except Exception:
        return ""
    model_dir = os.environ.get("VOSK_VI_DIR") if (user_lang or "").startswith("vi") else os.environ.get("VOSK_EN_DIR")
    if not model_dir or not os.path.isdir(model_dir):
        return ""
    model = vosk.Model(model_dir)
    rec = vosk.KaldiRecognizer(model, sr)
    out = []
    step = 4000
    for i in range(0, len(raw), step):
        if rec.AcceptWaveform(raw[i:i+step]):
            j = json.loads(rec.Result())
            if j.get("text"): out.append(j["text"])
    j = json.loads(rec.FinalResult())
    if j.get("text"): out.append(j["text"])
    return " ".join(out).strip()

def _whisper_available() -> bool:
    try:
        import faster_whisper  # noqa
        return True
    except Exception:
        return False

def _whisper_transcribe(path: str, user_lang: str) -> Tuple[str, List[Dict]]:
    """
    Dùng faster-whisper nếu có (nhanh/ổn định, không phụ thuộc mạng).
    Tuỳ chỉnh qua biến môi trường:
      WHISPER_MODEL   = tiny|base|small|medium|large-v3 (mặc định: small)
      WHISPER_DEVICE  = auto|cpu|cuda                 (mặc định: auto)
      WHISPER_COMPUTE = int8|int8_float16|float16|float32 (mặc định: float16 nếu cuda, int8 nếu cpu)
    """
    from faster_whisper import WhisperModel
    model_name = os.getenv("WHISPER_MODEL", "small")
    device_env = os.getenv("WHISPER_DEVICE", "auto")
    try:
        import torch
        has_cuda = torch.cuda.is_available()
    except Exception:
        has_cuda = False
    device = ("cuda" if has_cuda else "cpu") if device_env == "auto" else device_env
    compute_type = os.getenv("WHISPER_COMPUTE", "float16" if (device=="cuda") else "int8")

    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    lang = None if user_lang in ("auto", "", None) else LANG_MAP.get(user_lang[:2], None)

    segments_gen, info = model.transcribe(
        path,
        language=lang,          # None → autodetect
        vad_filter=True,
        beam_size=5,
        best_of=5,
        temperature=0.0
    )
    texts, segs = [], []
    for seg in segments_gen:
        txt = (seg.text or "").strip()
        if txt:
            texts.append(txt)
            segs.append({
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "text": txt
            })
    return " ".join(texts).strip(), segs

def transcribe_file(path: str, lang: str = "vi") -> Tuple[str, List[Dict]]:
    """
    Trả về (full_text, segments[{start,end,text}])
    Ưu tiên faster-whisper (nếu cài), fallback Google SR/Vosk (có VAD cục bộ).
    """
    # 1) Nếu có faster-whisper: dùng trực tiếp trên file WAV (nhanh/ổn định)
    if _whisper_available():
        try:
            return _whisper_transcribe(path, lang)
        except Exception:
            pass  # rơi xuống fallback

    # 2) Fallback Google SR + VAD cục bộ (ổn hơn với file dài)
    if not path.lower().endswith(".wav"):
        raise RuntimeError("transcribe_file chỉ nhận WAV 16k mono.")

    raw, sr = _read_wav_mono16(path)
    intervals = _simple_vad_intervals(raw, sr)

    texts: List[str] = []
    segs: List[Dict] = []

    def recog_segment(ad: srec.AudioData) -> str:
        # Google trước, nếu mạng/quota fail → thử Vosk (nếu có model)
        try:
            txt = _google_try(ad, lang or "vi")
            if txt: return txt
        except Exception:
            pass
        return _vosk_transcribe(ad.get_raw_data(convert_rate=None, convert_width=2), ad.sample_rate, lang or "vi")

    for s_ms, e_ms in intervals:
        ad = _to_ad(raw, sr, s_ms, e_ms)
        txt = (recog_segment(ad) or "").strip()
        if txt:
            texts.append(txt)
            segs.append({"start": round(s_ms/1000.0,3), "end": round(e_ms/1000.0,3), "text": txt})

    if not texts:
        ad_full = srec.AudioData(raw, sr, 2)
        txt_all = (recog_segment(ad_full) or "").strip()
        if txt_all:
            return txt_all, [{"start": 0.0, "end": round(len(raw)/(2*sr), 3), "text": txt_all}]
    return " ".join(texts).strip(), segs
