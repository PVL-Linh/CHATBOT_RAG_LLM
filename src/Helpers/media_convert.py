# Helpers/media_convert.py
import subprocess
try:
    import imageio_ffmpeg
except ImportError:
    imageio_ffmpeg = None

def convert_to_wav16k_mono(src_path: str, dst_path: str, timeout: int = 300) -> str:
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        exe, "-hide_banner", "-loglevel", "error",
        "-y", "-i", src_path, "-vn",
        "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le",
        dst_path
    ]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode("utf-8", "ignore"))
    return dst_path