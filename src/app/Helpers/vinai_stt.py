import os
import wave
import json
import audioop
import contextlib
import multiprocessing as mp
from typing import List, Tuple, Dict, Optional

import speech_recognition as srec

LANG_MAP = {"vi": "vi", "en": "en"}
GOOGLE_LANG = {"vi": "vi-VN", "en": "en-US"}
FRAME_MS = 30
MIN_SPEECH_MS = 150
MIN_SIL_MS = 350
MAX_SEG_MS = 25000

os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("CT2_NUM_THREADS", "4")


def _read_wav_mono16(path: str):
    """Đọc WAV và bảo đảm mono 16-bit. Trả về (raw_bytes, sample_rate)."""
    with contextlib.closing(wave.open(path, "rb")) as wf:
        ch, sw, sr, n = wf.getnchannels(), wf.getsampwidth(), wf.getframerate(), wf.getnframes()
        raw = wf.readframes(n)
    if sw != 2:
        raw = audioop.lin2lin(raw, sw, 2)
    if ch != 1:
        if ch == 2:
            raw = audioop.tomono(raw, 2, 0.5, 0.5)
        else:
            frame = 2
            frames = len(raw) // (ch * frame)
            mono = bytearray(frames * frame)
            for i in range(frames):
                acc = b"\x00\x00"
                for c in range(ch):
                    start = (i * ch + c) * frame
                    acc = audioop.add(acc, raw[start:start + frame], 2)
                mono[i * frame:(i + 1) * frame] = audioop.mul(acc, 2, 1.0 / ch)
            raw = bytes(mono)
    return raw, sr


def _to_ad(raw: bytes, sr: int, s_ms: int, e_ms: int) -> srec.AudioData:
    a = int(s_ms * sr / 1000) * 2
    b = int(e_ms * sr / 1000) * 2
    return srec.AudioData(raw[a:b], sr, 2)

def _simple_vad_intervals(raw: bytes, sr: int) -> List[Tuple[int, int]]:
    fb = max(320, int(sr * (FRAME_MS / 1000.0)) * 2)
    total = max(1, len(raw) // fb)
    base_frames = min(total, int(1000 / FRAME_MS))
    rms0 = [audioop.rms(raw[i * fb:(i + 1) * fb], 2) for i in range(base_frames)] or [200]
    base = max(150, sum(rms0) / len(rms0))
    thresh = base * 1.4

    intervals = []
    in_speech, s0, sil, cur = False, 0, 0, 0
    min_sp = max(1, int(MIN_SPEECH_MS / FRAME_MS))
    min_sil = max(1, int(MIN_SIL_MS / FRAME_MS))
    max_seg = max(1, int(MAX_SEG_MS / FRAME_MS))

    for i in range(total):
        b0, b1 = i * fb, (i + 1) * fb
        voiced = audioop.rms(raw[b0:b1], 2) >= thresh
        if not in_speech and voiced:
            in_speech, s0, sil, cur = True, i, 0, 0
        elif in_speech:
            cur += 1
            sil = 0 if voiced else sil + 1
            if sil >= min_sil or cur >= max_seg:
                if (i - s0 - sil) >= min_sp:
                    intervals.append((s0 * FRAME_MS, (i - sil) * FRAME_MS))
                in_speech, sil, cur = False, 0, 0

    if in_speech:
        i = total
        if (i - s0 - sil) >= min_sp:
            intervals.append((s0 * FRAME_MS, (i - sil) * FRAME_MS))

    if not intervals:
        dur_ms = int(len(raw) / (2 * sr) * 1000)
        intervals = [(0, dur_ms)]
    return intervals

def _google_try(ad: srec.AudioData, user_lang: str) -> str:
    """Thử Google Speech Recognition (yêu cầu mạng)."""
    r = srec.Recognizer()
    if user_lang in ("vi", "en"):
        cand = [GOOGLE_LANG[user_lang], GOOGLE_LANG["en" if user_lang == "vi" else "vi"]]
    else:
        cand = ["vi-VN", "en-US"]
    last = None
    for lg in cand:
        try:
            txt = r.recognize_google(ad, language=lg, show_all=False)
            if txt:
                return txt
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
        if rec.AcceptWaveform(raw[i:i + step]):
            j = json.loads(rec.Result())
            if j.get("text"):
                out.append(j["text"])
    j = json.loads(rec.FinalResult())
    if j.get("text"):
        out.append(j["text"])
    return " ".join(out).strip()

def _fw_worker(path: str, user_lang: str, model_name: str, compute_type: str, conn):
    try:
        os.environ["CT2_USE_CPU_ONLY"] = "1"
        os.environ["CUDA_VISIBLE_DEVICES"] = ""

        from faster_whisper import WhisperModel
        os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

        device = "cpu"
        compute = compute_type or "int8"

        model = WhisperModel(model_name or "small", device=device, compute_type=compute)

        LANG_MAP = {"vi": "vi", "en": "en"}
        lang = None if user_lang in ("auto", "", None) else LANG_MAP.get((user_lang or "")[:2], None)

        segments_gen, info = model.transcribe(
            path, language=lang, vad_filter=True, beam_size=5, best_of=5, temperature=0.0
        )
        texts, segs = [], []
        for seg in segments_gen:
            t = (seg.text or "").strip()
            if t:
                texts.append(t)
                segs.append({"start": round(seg.start, 3), "end": round(seg.end, 3), "text": t})

        conn.send({"ok": True, "text": " ".join(texts).strip(), "segs": segs})
    except Exception as e:
        conn.send({"ok": False, "err": str(e)})
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _fw_transcribe_subprocess(path: str, user_lang: str, timeout: int = 300) -> Tuple[str, List[Dict]]:
    ctx = mp.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    model_name = os.getenv("WHISPER_MODEL", "small")
    compute_type = os.getenv("WHISPER_COMPUTE", "int8")

    p = ctx.Process(target=_fw_worker, args=(path, user_lang, model_name, compute_type, child_conn))
    p.daemon = True
    p.start()
    child_conn.close()

    try:
        if parent_conn.poll(timeout):
            msg = parent_conn.recv()
        else:
            p.terminate()
            raise TimeoutError(f"faster-whisper timeout after {timeout}s")
    finally:
        try:
            parent_conn.close()
        except Exception:
            pass
        p.join(timeout=5)

    if not msg.get("ok"):
        raise RuntimeError(msg.get("err") or "faster-whisper failed")
    return msg["text"], msg["segs"]


def _whisper_enabled() -> bool:
    return not bool(os.getenv("DISABLE_FASTER_WHISPER"))

def transcribe_file(path: str, lang: str = "vi") -> Tuple[str, List[Dict]]:
    if _whisper_enabled():
        try:
            text_fw, segs_fw = _fw_transcribe_subprocess(path, lang, timeout=300)
            if (text_fw or "").strip():
                return text_fw, segs_fw
        except Exception:
            pass

    if not path.lower().endswith(".wav"):
        raise RuntimeError("transcribe_file (fallback) chỉ nhận WAV 16k mono.")

    raw, sr = _read_wav_mono16(path)
    intervals = _simple_vad_intervals(raw, sr)

    texts: List[str] = []
    segs: List[Dict] = []

    def recog_segment(ad: srec.AudioData) -> str:
        try:
            txt_g = _google_try(ad, lang or "vi")
            if txt_g:
                return txt_g
        except Exception:
            pass
        return _vosk_transcribe(ad.get_raw_data(convert_rate=None, convert_width=2), ad.sample_rate, lang or "vi")

    for s_ms, e_ms in intervals:
        ad = _to_ad(raw, sr, s_ms, e_ms)
        txt = (recog_segment(ad) or "").strip()
        if txt:
            texts.append(txt)
            segs.append({"start": round(s_ms / 1000.0, 3), "end": round(e_ms / 1000.0, 3), "text": txt})

    if not texts:
        ad_full = srec.AudioData(raw, sr, 2)
        txt_all = (recog_segment(ad_full) or "").strip()
        if txt_all:
            return txt_all, [{"start": 0.0, "end": round(len(raw) / (2 * sr), 3), "text": txt_all}]

    return " ".join(texts).strip(), segs
