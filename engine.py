"""
engine.py — ส่วนตรรกะทั้งหมดของ Mini Compressor (ไม่มี GUI เลย)

แยกไฟล์ออกมาเพราะ:
  1. เทสต์ได้โดยไม่ต้องเปิดหน้าต่าง
  2. เอาไปทำ CLI / เว็บ / เรียกใน Jupyter ต่อได้ทันที

โครงสร้าง
  - ฟังก์ชันบีบอัด: compress_image / compress_video / make_archive / join_parts
  - Job     : งาน 1 ชิ้นในคิว
  - Engine  : คิวไม่จำกัด + พูลเวิร์กเกอร์แยกตามประเภท + ยกเลิกกลางทางได้
"""

import io
import os
import re
import json
import math
import time
import shutil
import zipfile
import subprocess
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

try:
    from PIL import Image, ImageOps
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

MB = 1024 * 1024

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".mpg", ".mpeg"}

KIND_IMG, KIND_VID, KIND_ARC = "img", "vid", "arc"
KIND_LABEL = {KIND_IMG: "รูปภาพ", KIND_VID: "วิดีโอ", KIND_ARC: "ไฟล์"}

# ---- จำนวนเวิร์กเกอร์เริ่มต้น คิดจากซีพียูจริงของเครื่อง ไม่ฮาร์ดโค้ด ----
#
# ทำไมรูปกับวิดีโอใช้ค่าต่างกัน (วัดจริงมาแล้ว ไม่ได้เดา):
#
#   รูป   -> Pillow เข้ารหัสด้วยโค้ด C ที่ "ปล่อย GIL" ระหว่างทำงาน
#            เธรดหลายตัวจึงวิ่งขนานกันได้จริง -> ยิ่งหลายคอร์ยิ่งเร็วขึ้น
#
#   วิดีโอ -> ffmpeg เป็นโปรเซสแยก และตัวมันเองใช้ครบทุกคอร์อยู่แล้ว
#            เปิด 5 ตัวพร้อมกันคือแย่งคอร์กันเอง + กิน RAM 5 เท่า
#            วัดได้ 1 ตัว 11.8s / 2 ตัว 10.1s / 4 ตัว 10.6s  (แทบไม่ต่าง แล้วเริ่มแย่ลง)
#            -> ค่าที่ถูกคือ 1 เรียงคิวไปทีละตัว
CPU = os.cpu_count() or 4
DEF_WORKERS = {
    KIND_IMG: max(2, min(6, CPU)),
    KIND_VID: 1,
    KIND_ARC: 1,          # zip เดียว และคอขวดคือดิสก์ ไม่ใช่ซีพียู
}
MAX_WORKERS = {KIND_IMG: 16, KIND_VID: 4, KIND_ARC: 1}


def human(nbytes):
    """แปลง bytes เป็นข้อความอ่านง่าย เช่น 2.41 MB"""
    if nbytes is None:
        return "-"
    n = float(nbytes)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{int(n)} B" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024


def detect_kind(path):
    """ดูนามสกุลแล้วบอกว่าไฟล์นี้ควรเข้าโหมดไหน"""
    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXT:
        return KIND_IMG
    if ext in VIDEO_EXT:
        return KIND_VID
    return KIND_ARC


def unique_path(p):
    """ถ้าไฟล์ชื่อนี้มีอยู่แล้ว เติม _1 _2 ต่อท้ายให้ ไม่ทับของเดิม"""
    p = Path(p)
    if not p.exists():
        return p
    for i in range(1, 10000):
        cand = p.with_name(f"{p.stem}_{i}{p.suffix}")
        if not cand.exists():
            return cand
    return p


class Cancelled(Exception):
    """โยนขึ้นมาเมื่อผู้ใช้กดหยุดกลางทาง"""


# ============================================================
# รูปภาพ
# ============================================================

def _encode(im, fmt, quality):
    """เซฟรูปลงหน่วยความจำแล้วคืน bytes — ใช้ลองขนาดโดยไม่ต้องเขียนดิสก์"""
    buf = io.BytesIO()
    if fmt == "JPEG":
        im.save(buf, "JPEG", quality=quality, optimize=True,
                progressive=True, subsampling=2 if quality < 90 else 0)
    elif fmt == "WEBP":
        im.save(buf, "WEBP", quality=quality, method=6)
    elif fmt == "PNG":
        # PNG ไม่มี quality จริง ๆ อยากให้เล็กลงต้องลดจำนวนสี
        # ปิด dither ด้วย เพราะ dither ใส่ noise กลับเข้าไปทำให้ไฟล์ใหญ่ขึ้น
        work = im
        if quality < 95:
            colors = max(4, int(256 * (quality / 95)))
            work = im.convert("RGB").quantize(colors=colors,
                                              method=Image.Quantize.MEDIANCUT,
                                              dither=Image.Dither.NONE)
        work.save(buf, "PNG", optimize=True, compress_level=9)
    else:
        raise ValueError(f"ไม่รองรับฟอร์แมต {fmt}")
    return buf.getvalue()


def _flatten(im, fmt):
    """JPEG ไม่รองรับความโปร่งใส ต้องเอาพื้นขาวรองก่อน"""
    if fmt == "JPEG" and im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        return bg
    if fmt == "JPEG" and im.mode != "RGB":
        return im.convert("RGB")
    return im


def compress_image(src, dst, target_mb=None, width=None, height=None,
                   keep_aspect=True, fmt="JPEG", min_quality=20,
                   cancel=None, on_pct=None):
    """
    บีบรูป 1 ไฟล์

    target_mb   : ขนาดไฟล์สูงสุดที่ต้องการ (None = ไม่จำกัด ใช้ quality 85)
    width/height: ขนาดพิกเซลที่ต้องการ (None = ไม่ย่อ)
    keep_aspect : True  = fit ในกรอบ WxH ไม่ยืด
                  False = บังคับ WxH เป๊ะ รูปอาจยืด
    """
    def tick(p):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        if on_pct:
            on_pct(p)

    tick(2)
    im = Image.open(src)
    im = ImageOps.exif_transpose(im)        # หมุนตาม EXIF ของกล้อง/มือถือ
    original_size = (im.width, im.height)

    # --- ขั้นที่ 1: ปรับขนาดพิกเซล ---
    if width or height:
        w = width or im.width
        h = height or im.height
        if keep_aspect:
            im.thumbnail((w, h), Image.LANCZOS)
        else:
            im = im.resize((w, h), Image.LANCZOS)
    tick(15)

    im = _flatten(im, fmt)

    # --- ขั้นที่ 2: ไม่กำหนดขนาดไฟล์ ก็จบตรงนี้ ---
    if not target_mb:
        data = _encode(im, fmt, 85)
        tick(90)
        Path(dst).write_bytes(data)
        return {"ok": True, "bytes": len(data), "quality": 85,
                "size": (im.width, im.height), "original_size": original_size,
                "downscaled": False}

    target = int(target_mb * MB)
    floor_data = None

    for attempt in range(10):
        # --- 3a: เช็คพื้น ---
        # ลอง quality ต่ำสุดก่อน ถ้ายังเกินเป้า แปลว่าปรับ quality ยังไงก็ไม่พอ
        # ต้องลดจำนวนพิกเซลสถานเดียว
        tick(20 + attempt * 7)
        floor_data = _encode(im, fmt, min_quality)

        if len(floor_data) <= target:
            # --- 3b: binary search หา quality สูงสุดที่ยังไม่เกินเป้า ---
            # ขนาดไฟล์โตตาม quality แบบ monotonic -> หาร 2 ไปเรื่อย ๆ
            # ใช้แค่ ~7 รอบ แทนไล่ทีละ 1 (75 รอบ)
            lo, hi = min_quality, 95
            best = (min_quality, floor_data)
            while lo <= hi:
                tick(None if on_pct is None else 60)
                mid = (lo + hi) // 2
                data = _encode(im, fmt, mid)
                if len(data) <= target:
                    best = (mid, data)      # ผ่าน -> ดันคุณภาพขึ้นอีก
                    lo = mid + 1
                else:
                    hi = mid - 1            # เกิน -> ลดคุณภาพลง
            q, data = best
            tick(95)
            Path(dst).write_bytes(data)
            return {"ok": True, "bytes": len(data), "quality": q,
                    "size": (im.width, im.height), "original_size": original_size,
                    "downscaled": attempt > 0}

        # --- 3c: ย่อรูป คำนวณอัตราย่อจากขนาดไฟล์จริง ---
        # ขนาดไฟล์ ~ แปรผันตามจำนวนพิกเซล (= ด้าน^2)
        # อยากเล็กลง k เท่า -> ย่อความยาวด้านลง sqrt(k)
        # x0.92 = เผื่อ เพราะ resize สร้างสีใหม่ ไฟล์อาจไม่เล็กลงตามสูตรเป๊ะ
        ratio = math.sqrt(target / len(floor_data)) * 0.92
        ratio = min(0.9, max(0.3, ratio))
        new_w, new_h = max(32, int(im.width * ratio)), max(32, int(im.height * ratio))
        if (new_w, new_h) == (im.width, im.height):
            break
        im = im.resize((new_w, new_h), Image.LANCZOS)

    # ยอมแพ้ -> เซฟเล็กสุดเท่าที่ทำได้ แล้วบอกว่าไม่ถึงเป้า
    Path(dst).write_bytes(floor_data)
    return {"ok": False, "bytes": len(floor_data), "quality": min_quality,
            "size": (im.width, im.height), "original_size": original_size,
            "downscaled": True}


# ============================================================
# วิดีโอ
# ============================================================

def ffmpeg_ready():
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


_NOWIN = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
_TIME_RE = re.compile(r"time=(\d+):(\d\d):(\d\d(?:\.\d+)?)")


def _run(cmd):
    """รันสั้น ๆ รอผล (ใช้กับ ffprobe)"""
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", creationflags=_NOWIN)


def _split_stream(pipe):
    """
    อ่าน stderr ของ ffmpeg แบบทีละบรรทัด

    ffmpeg ขึ้นบรรทัดความคืบหน้าด้วย \r ไม่ใช่ \n
    ถ้าใช้ for line in pipe ปกติจะไม่ได้อะไรเลยจนจบงาน เลยต้องตัดเองทั้ง \r และ \n
    """
    buf = ""
    while True:
        chunk = pipe.read(256)
        if not chunk:
            break
        buf += chunk
        while True:
            idx = [buf.find(c) for c in ("\r", "\n")]
            idx = [i for i in idx if i >= 0]
            if not idx:
                break
            i = min(idx)
            yield buf[:i]
            buf = buf[i + 1:]
    if buf:
        yield buf


def _ffmpeg(cmd, duration=None, on_pct=None, pct_lo=0.0, pct_hi=100.0,
            cancel=None, procs=None):
    """
    รัน ffmpeg แบบอ่านความคืบหน้าได้ และฆ่าได้กลางทาง

    คืน (returncode, บรรทัดท้าย ๆ ของ stderr สำหรับดูตอน error)
    """
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                         text=True, encoding="utf-8", errors="replace",
                         bufsize=1, creationflags=_NOWIN)
    if procs is not None:
        procs.append(p)

    tail, killed = [], False
    try:
        for line in _split_stream(p.stderr):
            if len(tail) > 30:
                tail.pop(0)
            tail.append(line)

            if cancel is not None and cancel.is_set():
                killed = True
                p.kill()
                break

            if on_pct and duration:
                m = _TIME_RE.search(line)
                if m:
                    secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                    frac = max(0.0, min(1.0, secs / duration))
                    on_pct(pct_lo + (pct_hi - pct_lo) * frac)
    finally:
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
        if procs is not None and p in procs:
            procs.remove(p)

    if killed:
        raise Cancelled()
    return p.returncode, "\n".join(tail)


def video_info(src):
    """อ่าน duration / ความกว้างสูง / มีเสียงไหม"""
    r = _run(["ffprobe", "-v", "quiet", "-print_format", "json",
              "-show_format", "-show_streams", str(src)])
    if r.returncode != 0:
        raise RuntimeError("ffprobe อ่านไฟล์นี้ไม่ได้ (ไฟล์เสียหรือไม่ใช่วิดีโอ)")
    info = json.loads(r.stdout)
    dur = float(info["format"]["duration"])
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    return {"duration": dur,
            "width": int(v["width"]) if v else 0,
            "height": int(v["height"]) if v else 0,
            "has_audio": any(s["codec_type"] == "audio" for s in info["streams"])}


def compress_video(src, dst, target_mb, height=None, audio_kbps=128,
                   log=print, cancel=None, on_pct=None, procs=None):
    """
    บีบวิดีโอให้ได้ขนาดตามต้องการ ด้วย two-pass x264

    สูตร: bitrate(kbps) = ขนาดเป้าหมาย(kbit) / ความยาว(วินาที)
    two-pass = รอบแรก ffmpeg สแกนดูว่าฉากไหนยาก/ง่าย
               รอบสองค่อยแบ่ง bitrate ให้แม่น -> ขนาดตรงเป้ากว่า one-pass มาก
    """
    info = video_info(src)
    dur = info["duration"]
    if not info["has_audio"]:
        audio_kbps = 0

    # 0.97 = กันเผื่อ container overhead (metadata, index)
    total_kbps = (target_mb * 8192 * 0.97) / dur
    video_kbps = int(total_kbps - audio_kbps)

    if video_kbps < 80:
        return {"ok": False, "error":
                f"เป้า {target_mb} MB เล็กเกินไปสำหรับคลิปยาว {dur:.0f} วินาที "
                f"(เหลือ bitrate แค่ {video_kbps} kbps) — เพิ่มขนาดเป้า หรือตัดคลิปให้สั้นลง"}

    scale = ["-vf", f"scale=-2:{height}"] if height else []
    passlog = str(Path(dst).with_suffix("")) + f"_pass{os.getpid()}_{threading.get_ident()}"
    null = "NUL" if os.name == "nt" else "/dev/null"

    def cleanup():
        for junk in Path(dst).parent.glob(Path(passlog).name + "*"):
            junk.unlink(missing_ok=True)

    try:
        log("Pass 1/2 วิเคราะห์วิดีโอ...")
        rc, err = _ffmpeg(["ffmpeg", "-y", "-i", str(src), *scale,
                           "-c:v", "libx264", "-b:v", f"{video_kbps}k",
                           "-pass", "1", "-passlogfile", passlog,
                           "-preset", "medium", "-an", "-f", "mp4", null],
                          duration=dur, on_pct=on_pct, pct_lo=0, pct_hi=45,
                          cancel=cancel, procs=procs)
        if rc != 0:
            cleanup()
            return {"ok": False, "error": err[-600:]}

        log("Pass 2/2 เข้ารหัสจริง...")
        audio_args = ["-c:a", "aac", "-b:a", f"{audio_kbps}k"] if audio_kbps else ["-an"]
        rc, err = _ffmpeg(["ffmpeg", "-y", "-i", str(src), *scale,
                           "-c:v", "libx264", "-b:v", f"{video_kbps}k",
                           "-pass", "2", "-passlogfile", passlog,
                           "-preset", "medium", *audio_args,
                           "-movflags", "+faststart", str(dst)],
                          duration=dur, on_pct=on_pct, pct_lo=45, pct_hi=99,
                          cancel=cancel, procs=procs)
        if rc != 0:
            cleanup()
            return {"ok": False, "error": err[-600:]}
    except Cancelled:
        cleanup()
        Path(dst).unlink(missing_ok=True)
        raise

    cleanup()
    return {"ok": True, "bytes": Path(dst).stat().st_size,
            "bitrate": video_kbps, "duration": dur}


# ============================================================
# ไฟล์ทั่วไป (zip + หั่น/รวม)
# ============================================================

def make_archive(paths, dst, split_mb=None, log=print, cancel=None, on_pct=None):
    """
    รวมไฟล์/โฟลเดอร์เป็น .zip (deflate ระดับ 9)

    split_mb: หั่น zip เป็น .001 .002 ... ตามขนาดที่กำหนด
              เพราะไฟล์ทั่วไป "การันตีขนาดหลังบีบไม่ได้" การหั่นคือทางที่ได้ผลจริง
    """
    dst = Path(dst)

    # กางรายการไฟล์ทั้งหมดก่อน เพื่อคิด % ได้
    items = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            items += [(f, f.relative_to(p.parent)) for f in sorted(p.rglob("*")) if f.is_file()]
        elif p.is_file():
            items.append((p, Path(p.name)))

    total = len(items) or 1
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for i, (f, arc) in enumerate(items, 1):
            if cancel is not None and cancel.is_set():
                z.close()
                dst.unlink(missing_ok=True)
                raise Cancelled()
            z.write(f, arc)
            log(f"  + {arc}")
            if on_pct:
                on_pct(i / total * 90)

    size = dst.stat().st_size
    if not split_mb or size <= split_mb * MB:
        if on_pct:
            on_pct(100)
        return {"ok": True, "bytes": size, "parts": [dst.name], "files": len(items)}

    # ---- หั่นเป็นส่วน ๆ ----
    chunk = int(split_mb * MB)
    parts = []
    with open(dst, "rb") as f:
        i = 1
        while True:
            data = f.read(chunk)
            if not data:
                break
            part = dst.with_suffix(dst.suffix + f".{i:03d}")
            part.write_bytes(data)
            parts.append(part.name)
            log(f"  -> {part.name} ({human(len(data))})")
            i += 1
    dst.unlink()
    if on_pct:
        on_pct(100)
    return {"ok": True, "bytes": size, "parts": parts, "files": len(items)}


def join_parts(first_part, log=print):
    """รวมไฟล์ .001 .002 ... กลับเป็นไฟล์เดียว"""
    first = Path(first_part)
    base = first.with_suffix("")
    pattern = first.name.rsplit(".", 1)[0] + ".*"
    parts = sorted(p for p in first.parent.glob(pattern) if p.suffix[1:].isdigit())
    if not parts:
        raise RuntimeError("ไม่เจอไฟล์ส่วนย่อย (.001, .002, ...)")
    base = unique_path(base)
    with open(base, "wb") as out:
        for p in parts:
            out.write(p.read_bytes())
            log(f"  + {p.name}")
    return base


# ============================================================
# คิว + พูลเวิร์กเกอร์
# ============================================================

QUEUED, RUNNING, DONE, ERROR, CANCELLED = "queued", "running", "done", "error", "cancelled"

STATUS_TEXT = {
    QUEUED: "รอคิว",
    RUNNING: "กำลังทำ",
    DONE: "เสร็จ",
    ERROR: "ผิดพลาด",
    CANCELLED: "ยกเลิก",
}


class Job:
    """งาน 1 ชิ้นในคิว — รูป 1 ใบ, วิดีโอ 1 คลิป, หรือ zip 1 ก้อน (รวมหลายไฟล์)"""

    _seq = 0
    _seq_lock = threading.Lock()

    def __init__(self, kind, paths, label=None):
        with Job._seq_lock:
            Job._seq += 1
            self.jid = f"j{Job._seq}"
        self.kind = kind
        self.paths = [Path(p) for p in paths]
        self.label = label or self.paths[0].name
        self.status = QUEUED
        self.pct = 0.0
        self.msg = ""
        self.before = sum(p.stat().st_size for p in self.paths if p.is_file()) or None
        self.after = None
        self.out = None

    @property
    def saved_pct(self):
        if self.before and self.after is not None and self.before > 0:
            return 100 - self.after / self.before * 100
        return None

    def __repr__(self):
        return f"<Job {self.jid} {self.kind} {self.label} {self.status}>"


class Engine:
    """
    คิวไม่จำกัดความยาว + ดึงออกมาทำพร้อมกันตามจำนวนเวิร์กเกอร์ของแต่ละประเภท

    ทำไมแยกพูลตามประเภท ไม่ใช้พูลรวมอันเดียว:
        ถ้าใช้พูลรวม 5 ช่อง แล้วจำกัดวิดีโอไว้ 1 ตัวด้วย semaphore
        เวลามีวิดีโอ 5 คลิปเข้าคิว เธรดทั้ง 5 จะไปนอนรอ semaphore ของวิดีโอกันหมด
        รูปที่ต่อคิวอยู่ข้างหลังจะไม่ได้ทำเลยทั้งที่ว่าง (starvation)
        แยกพูลแล้วรูปกับวิดีโอมีช่องของตัวเอง ไม่แย่งกัน
    """

    def __init__(self, settings, workers=None,
                 on_update=None, on_log=None, on_finish=None):
        self.settings = settings
        self.workers = dict(DEF_WORKERS)
        if workers:
            for k, v in workers.items():
                self.workers[k] = max(1, min(MAX_WORKERS[k], int(v)))

        self.on_update = on_update or (lambda job: None)
        self.on_log = on_log or (lambda text: None)
        self.on_finish = on_finish or (lambda stats: None)

        self.cancel = threading.Event()
        self._procs = []              # Popen ที่กำลังวิ่ง เอาไว้ฆ่าตอนกดหยุด
        self._lock = threading.Lock()
        self.jobs = []
        self._running = False

    # ---------- สร้างคิวจากรายการไฟล์ ----------
    @staticmethod
    def build_jobs(paths, arc_name="archive.zip"):
        """
        แปลงรายการไฟล์คลุก ๆ เป็นคิวงาน

        รูปกับวิดีโอ -> ไฟล์ละ 1 งาน (ทำขนานกันได้)
        ไฟล์ทั่วไป   -> รวบเป็น zip ก้อนเดียว 1 งาน (เพราะ zip คือไฟล์ผลลัพธ์เดียว)
        """
        jobs, arc = [], []
        for p in paths:
            p = Path(p)
            if not p.exists():
                continue
            k = detect_kind(p)
            if k == KIND_ARC:
                arc.append(p)
            else:
                jobs.append(Job(k, [p]))
        if arc:
            jobs.append(Job(KIND_ARC, arc, label=f"{arc_name}  ({len(arc)} ไฟล์)"))
        return jobs

    # ---------- ควบคุม ----------
    def stop(self):
        """ยกเลิกคิวที่เหลือ + ฆ่า ffmpeg ที่กำลังวิ่ง"""
        self.cancel.set()
        with self._lock:
            for p in list(self._procs):
                try:
                    p.kill()
                except Exception:
                    pass

    @property
    def running(self):
        return self._running

    def start(self, jobs, block=False):
        """เริ่มทำคิว (ไม่ block = คืนทันที ใช้กับ GUI)"""
        self.jobs = jobs
        self.cancel.clear()
        self._running = True
        t = threading.Thread(target=self._dispatch, daemon=True)
        t.start()
        if block:
            t.join()
        return t

    # ---------- ภายใน ----------
    def _dispatch(self):
        t0 = time.perf_counter()
        pools, futures = {}, []
        try:
            for kind in (KIND_IMG, KIND_VID, KIND_ARC):
                batch = [j for j in self.jobs if j.kind == kind]
                if not batch:
                    continue
                n = self.workers[kind]
                self.on_log(f"[{KIND_LABEL[kind]}] {len(batch)} งาน / ทำพร้อมกัน {n}")
                pools[kind] = ThreadPoolExecutor(max_workers=n,
                                                 thread_name_prefix=f"w-{kind}")
                futures += [pools[kind].submit(self._do, j) for j in batch]

            for f in futures:
                f.result()
        finally:
            for p in pools.values():
                p.shutdown(wait=True)
            self._running = False

        stats = {
            "done": sum(1 for j in self.jobs if j.status == DONE),
            "error": sum(1 for j in self.jobs if j.status == ERROR),
            "cancelled": sum(1 for j in self.jobs if j.status == CANCELLED),
            "before": sum(j.before or 0 for j in self.jobs if j.status == DONE),
            "after": sum(j.after or 0 for j in self.jobs if j.status == DONE),
            "seconds": time.perf_counter() - t0,
        }
        self.on_finish(stats)

    def _set(self, job, **kw):
        for k, v in kw.items():
            setattr(job, k, v)
        self.on_update(job)

    def _do(self, job):
        """ทำงาน 1 ชิ้น — จับ error ไว้ทั้งหมด งานหนึ่งพังไม่ลากทั้งคิวตาย"""
        if self.cancel.is_set():
            self._set(job, status=CANCELLED, msg="ยกเลิกก่อนเริ่ม")
            return

        self._set(job, status=RUNNING, pct=0)
        pct_cb = lambda p: self._set(job, pct=max(job.pct, min(99.0, p)))

        try:
            if job.kind == KIND_IMG:
                self._do_image(job, pct_cb)
            elif job.kind == KIND_VID:
                self._do_video(job, pct_cb)
            else:
                self._do_archive(job, pct_cb)
        except Cancelled:
            self._set(job, status=CANCELLED, pct=0, msg="ยกเลิก")
        except Exception as e:
            self._set(job, status=ERROR, msg=f"{type(e).__name__}: {e}")
            self.on_log(f"[ผิดพลาด] {job.label}: {e}")

    def _do_image(self, job, pct_cb):
        if not HAS_PIL:
            raise RuntimeError("ยังไม่ได้ลง Pillow (pip install pillow)")
        s = self.settings["img"]
        src = job.paths[0]
        ext = {"JPEG": ".jpg", "WEBP": ".webp", "PNG": ".png"}[s["fmt"]]
        dst = unique_path(Path(self.settings["outdir"]) / (src.stem + ext))

        r = compress_image(src, dst, s.get("target_mb"), s.get("width"), s.get("height"),
                           s.get("keep_aspect", True), s["fmt"],
                           cancel=self.cancel, on_pct=pct_cb)
        note = f"{r['size'][0]}x{r['size'][1]} q{r['quality']}"
        if not r["ok"]:
            note += " (เล็กกว่าเป้าไม่ได้)"
        self._set(job, status=DONE, pct=100, after=r["bytes"], out=str(dst), msg=note)
        self.on_log(f"[รูป] {src.name}: {human(job.before)} -> {human(r['bytes'])}  {note}")

    def _do_video(self, job, pct_cb):
        if not ffmpeg_ready():
            raise RuntimeError("ยังไม่เจอ ffmpeg ในเครื่อง")
        s = self.settings["vid"]
        src = job.paths[0]
        dst = unique_path(Path(self.settings["outdir"]) / (src.stem + "_compressed.mp4"))

        r = compress_video(src, dst, s["target_mb"], s.get("height"),
                           s.get("audio_kbps", 128),
                           log=lambda m: self._set(job, msg=m),
                           cancel=self.cancel, on_pct=pct_cb, procs=self._procs)
        if not r["ok"]:
            raise RuntimeError(r["error"].strip().splitlines()[-1] if r["error"].strip() else "ffmpeg ล้มเหลว")
        note = f"{r['bitrate']} kbps"
        self._set(job, status=DONE, pct=100, after=r["bytes"], out=str(dst), msg=note)
        self.on_log(f"[วิดีโอ] {src.name}: {human(job.before)} -> {human(r['bytes'])}  {note}")

    def _do_archive(self, job, pct_cb):
        s = self.settings["arc"]
        dst = unique_path(Path(self.settings["outdir"]) / s.get("name", "archive.zip"))
        r = make_archive(job.paths, dst, s.get("split_mb"),
                         log=lambda m: None, cancel=self.cancel, on_pct=pct_cb)
        note = f"{r['files']} ไฟล์"
        if len(r["parts"]) > 1:
            note += f" / หั่น {len(r['parts'])} ส่วน"
        self._set(job, status=DONE, pct=100, after=r["bytes"], out=str(dst), msg=note)
        self.on_log(f"[zip] {dst.name}: {human(job.before)} -> {human(r['bytes'])}  {note}")


def default_settings(outdir="."):
    return {
        "outdir": str(outdir),
        "img": {"target_mb": None, "width": None, "height": None,
                "keep_aspect": True, "fmt": "JPEG"},
        "vid": {"target_mb": 25.0, "height": None, "audio_kbps": 128},
        "arc": {"split_mb": None, "name": "archive.zip"},
    }
