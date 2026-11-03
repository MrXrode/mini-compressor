"""
Mini Compressor — แอปบีบอัดไฟล์ส่วนตัว

ลากรูป วิดีโอ และไฟล์อะไรก็ได้มาวางรวมกัน แอปแยกประเภทให้เองแล้วทำเป็นคิว

ติดตั้ง:
    pip install pillow tkinterdnd2
    pip install pillow-heif        (ถ้าจะเปิด .heic จาก iPhone)
    winget install ffmpeg          (จำเป็นเฉพาะโหมดวิดีโอ)

รัน:  python compressor.py
ต้องมี 4 ไฟล์อยู่ด้วยกัน: compressor.py / engine.py / theme.py (+ README.md)
"""

import os
import sys
import json
import queue
import threading
import subprocess
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    HAS_TK = True
except ImportError:
    HAS_TK = False

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    HAS_DND = False

import engine as E
from theme import Theme, Check, PALETTES, DEFAULT_THEME


# เก็บค่าที่ผู้ใช้ตั้งไว้ ไม่ต้องตั้งใหม่ทุกครั้งที่เปิด
CONFIG = Path.home() / ".mini_compressor.json"

COLS = ("kind", "status", "pct", "before", "after", "saved", "msg")
HEAD = {
    "kind":   ("ประเภท", 76),
    "status": ("สถานะ", 84),
    "pct":    ("%", 48),
    "before": ("ก่อน", 92),
    "after":  ("หลัง", 92),
    "saved":  ("ลดลง", 76),
    "msg":    ("รายละเอียด", 250),
}


def load_config():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(data):
    try:
        CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass          # เซฟไม่ได้ก็ไม่เป็นไร ไม่ใช่เรื่องคอขาดบาดตาย


def open_in_explorer(path):
    path = Path(path)
    try:
        if os.name == "nt":
            os.startfile(path if path.is_dir() else path.parent)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path if path.is_dir() else path.parent)])
        else:
            subprocess.Popen(["xdg-open", str(path if path.is_dir() else path.parent)])
    except Exception:
        pass


class App:
    def __init__(self, root):
        self.root = root
        root.title("Mini Compressor")
        root.geometry("1140x860")
        root.minsize(1000, 720)

        self.cfg = load_config()
        tname = self.cfg.get("theme", DEFAULT_THEME)
        if tname not in PALETTES:
            tname = DEFAULT_THEME
        self.th = Theme(root, tname)

        self.msgq = queue.Queue()
        self.jobs = {}
        self.order = []
        self.engine = None
        self.paths = []
        self.outdir = self.cfg.get("outdir", str(Path.home() / "Downloads"))

        # ลำดับสำคัญมาก: ชิ้นที่ความสูงคงที่ต้องจอง "จากล่างขึ้นบน" ก่อน
        # แล้วค่อยให้ตารางขยายกินที่เหลือตรงกลาง
        # ถ้าปล่อยให้ตารางขยายก่อน ชิ้นที่ pack ทีหลัง (log) จะโดนบีบจนหายไป
        self._build_header()
        self._build_log()
        self._build_footer()
        self._build_settings()
        self._build_list()
        self._restore_fields()

        self.show_zone()
        self.log("พร้อมใช้งาน")
        self.log(f"ซีพียู {E.CPU} คอร์  ·  รูปทำพร้อมกัน {E.DEF_WORKERS[E.KIND_IMG]}  ·  "
                 f"วิดีโอ {E.DEF_WORKERS[E.KIND_VID]}")
        if not E.HAS_PIL:
            self.log("! ยังไม่ได้ลง Pillow  →  pip install pillow   (โหมดรูปใช้ไม่ได้)")
        if not E.ffmpeg_ready():
            self.log("! ยังไม่เจอ ffmpeg  →  winget install ffmpeg   (โหมดวิดีโอใช้ไม่ได้)")
        if not HAS_DND:
            self.log("! ลากไฟล์มาวางยังใช้ไม่ได้  →  pip install tkinterdnd2  แล้วเปิดแอปใหม่")

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(80, self._pump)

    # ==================== หัวหน้าต่าง ====================
    def _build_header(self):
        h = ttk.Frame(self.root, padding=(20, 16, 20, 10))
        h.pack(fill="x")

        left = ttk.Frame(h)
        left.pack(side="left")
        ttk.Label(left, text="Mini Compressor", style="Title.TLabel").pack(anchor="w")
        ttk.Label(left, text="ลากไฟล์มาวางได้เลย — รูป วิดีโอ และไฟล์อื่นคลุกกันได้",
                  style="Sub.TLabel").pack(anchor="w", pady=(2, 0))

        right = ttk.Frame(h)
        right.pack(side="right")
        ttk.Label(right, text="ธีมสี", style="Muted.TLabel").pack(side="left", padx=(0, 8))
        self.theme_box = ttk.Combobox(right, values=list(PALETTES), width=13,
                                      state="readonly")
        self.theme_box.set(self.th.name)
        self.theme_box.pack(side="left")
        self.theme_box.bind("<<ComboboxSelected>>", self.change_theme)

        ttk.Separator(self.root, orient="horizontal").pack(fill="x", padx=20)

    def change_theme(self, _=None):
        name = self.theme_box.get()
        self.th.apply(name)
        self.th.row_tags(self.tree)
        self.th.style_text(self.logbox)
        self.chk_aspect.repaint()
        self._paint_plain()
        for jid in self.order:
            self._redraw(jid)
        self.cfg["theme"] = name
        save_config(self.cfg)

    def _paint_plain(self):
        """widget ที่ไม่ใช่ ttk ต้องทาสีเองทุกครั้งที่เปลี่ยนธีม"""
        c = self.th.c
        self.zone.configure(bg=c["zone"], highlightbackground=c["border"],
                            highlightcolor=c["border"])
        for w in self.zone_labels:
            w.configure(bg=c["zone"])
        self.zone_labels[0].configure(fg=c["text"])
        for w in self.zone_labels[1:]:
            w.configure(fg=c["muted"])
        self.listwrap.configure(bg=c["border"])

    # ==================== ลิสต์ไฟล์ / โซนลากวาง ====================
    def _build_list(self):
        box = ttk.Frame(self.root, padding=(20, 12, 20, 0))
        box.pack(fill="both", expand=True)

        # กล่องเนื้อหาแยกจากแถวปุ่ม ไม่งั้นพอ show_zone() สั่ง pack ทีหลัง
        # โซนลากวางจะไปโผล่ "ใต้" แถวปุ่ม
        content = ttk.Frame(box)        # pack ทีหลัง หลังแถวปุ่มจองที่เสร็จแล้ว

        # --- โซนลากวาง (โชว์ตอนยังไม่มีไฟล์) ---
        c = self.th.c
        self.zone = tk.Frame(content, bg=c["zone"], highlightthickness=2,
                             highlightbackground=c["border"], highlightcolor=c["border"],
                             cursor="hand2")
        inner = tk.Frame(self.zone, bg=c["zone"])
        inner.place(relx=0.5, rely=0.5, anchor="center")
        l1 = tk.Label(inner, text="⬇", bg=c["zone"], fg=c["text"],
                      font=(self.th.font, 30))
        l2 = tk.Label(inner, text="ลากไฟล์มาวางตรงนี้", bg=c["zone"], fg=c["text"],
                      font=(self.th.font, 15, "bold"))
        l3 = tk.Label(inner, text="หรือคลิกเพื่อเลือกไฟล์", bg=c["zone"], fg=c["muted"],
                      font=(self.th.font, 10))
        l4 = tk.Label(inner, text="รูป · วิดีโอ · เอกสาร · อะไรก็ได้ ใส่รวมกันได้เลย",
                      bg=c["zone"], fg=c["muted"], font=(self.th.font, 9))
        for w in (l1, l2, l3, l4):
            w.pack(pady=2)
        self.zone_labels = [l2, l1, l3, l4]
        for w in (self.zone, inner, l1, l2, l3, l4):
            w.bind("<Button-1>", lambda e: self.pick_files())

        # --- ตาราง (โชว์ตอนมีไฟล์) ---
        # กรอบนอกใช้สีเส้นขอบ แล้วเว้น padding 1px เพื่อแกล้งทำเป็นเส้นขอบบาง ๆ
        self.listwrap = tk.Frame(content, bg=c["border"])
        inner2 = ttk.Frame(self.listwrap, style="Card.TFrame")
        inner2.pack(fill="both", expand=True, padx=1, pady=1)

        self.tree = ttk.Treeview(inner2, columns=COLS, show="tree headings",
                                 selectmode="extended", height=8)
        self.tree.heading("#0", text="  ไฟล์", anchor="w")
        self.tree.column("#0", width=252, minwidth=150, anchor="w")
        for col in COLS:
            text, w = HEAD[col]
            self.tree.heading(col, text=text, anchor="center")
            anchor = "w" if col == "msg" else ("center" if col in ("kind", "status", "pct") else "e")
            self.tree.column(col, width=w, anchor=anchor, stretch=(col == "msg"))
        vs = ttk.Scrollbar(inner2, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.th.row_tags(self.tree)
        self.tree.bind("<Double-1>", self.on_double)

        self._register_drop(self.tree)
        self._register_drop(self.zone)

        # --- แถวปุ่ม ---
        # ต้อง pack ก่อน content และยึดด้านล่าง ไม่งั้นตารางขอความสูงตามค่าเริ่มต้น
        # (10 แถว) จนไม่เหลือที่ แล้วแถวปุ่มจะโดนบีบหายไปเลย
        bar = ttk.Frame(box, padding=(0, 10, 0, 0))
        bar.pack(fill="x", side="bottom")
        ttk.Button(bar, text="เพิ่มไฟล์", command=self.pick_files).pack(side="left")
        ttk.Button(bar, text="เพิ่มโฟลเดอร์", command=self.pick_folder).pack(side="left", padx=6)
        ttk.Button(bar, text="ลบที่เลือก", command=self.remove_selected).pack(side="left")
        ttk.Button(bar, text="ลบที่เสร็จแล้ว", command=self.remove_done).pack(side="left", padx=6)
        ttk.Button(bar, text="ล้างทั้งหมด", command=self.clear).pack(side="left")
        ttk.Button(bar, text="รวมไฟล์ .001 คืน", command=self.do_join).pack(side="right")
        self.count_lbl = ttk.Label(bar, text="", style="Muted.TLabel")
        self.count_lbl.pack(side="right", padx=14)

        content.pack(fill="both", expand=True)

    def _register_drop(self, widget):
        if not HAS_DND:
            return
        widget.drop_target_register(DND_FILES)
        widget.dnd_bind("<<Drop>>", self._on_drop)
        widget.dnd_bind("<<DropEnter>>", lambda e: self._zone_hl(True))
        widget.dnd_bind("<<DropLeave>>", lambda e: self._zone_hl(False))

    def _zone_hl(self, on):
        c = self.th.c
        self.zone.configure(bg=c["zone_active"] if on else c["zone"],
                            highlightbackground=c["accent"] if on else c["border"])
        for w in self.zone_labels:
            w.configure(bg=c["zone_active"] if on else c["zone"])
        for w in self.zone.winfo_children():
            w.configure(bg=c["zone_active"] if on else c["zone"])

    def _on_drop(self, event):
        self._zone_hl(False)
        self.add(self.root.tk.splitlist(event.data))

    def show_zone(self):
        """สลับระหว่างโซนลากวางกับตาราง ตามว่ามีไฟล์หรือยัง"""
        if self.paths or self.jobs:
            self.zone.pack_forget()
            self.listwrap.pack(fill="both", expand=True)
        else:
            self.listwrap.pack_forget()
            self.zone.pack(fill="both", expand=True)

    def on_double(self, _):
        sel = self.tree.selection()
        if not sel:
            return
        j = self.jobs.get(sel[0])
        if j and j.out:
            open_in_explorer(j.out)

    # ==================== ตั้งค่า ====================
    def _build_settings(self):
        wrap = ttk.Frame(self.root, padding=(20, 14, 20, 0))
        wrap.pack(fill="x", side="bottom")
        nb = ttk.Notebook(wrap)
        nb.pack(fill="x")

        def card(title):
            f = ttk.Frame(nb, style="Card.TFrame", padding=16)
            nb.add(f, text=f"  {title}  ")
            return f

        def lab(parent, text, r, muted=False):
            ttk.Label(parent, text=text,
                      style="CardMuted.TLabel" if muted else "Card.TLabel"
                      ).grid(row=r, column=0, sticky="w", pady=5, padx=(0, 14))

        def hint(parent, text, r, col=2, span=2):
            ttk.Label(parent, text=text, style="CardMuted.TLabel"
                      ).grid(row=r, column=col, columnspan=span, sticky="w", padx=12)

        # ---------- รูปภาพ ----------
        f = card("รูปภาพ")
        lab(f, "ขนาดไฟล์สูงสุด (MB)", 0)
        self.img_mb = ttk.Entry(f, width=10); self.img_mb.grid(row=0, column=1, sticky="w")
        hint(f, "เว้นว่าง = ไม่จำกัดขนาดไฟล์", 0)

        lab(f, "ขนาดภาพ กว้าง × สูง (px)", 1)
        g = ttk.Frame(f, style="Card.TFrame"); g.grid(row=1, column=1, columnspan=3, sticky="w")
        self.img_w = ttk.Entry(g, width=8); self.img_w.pack(side="left")
        ttk.Label(g, text="  ×  ", style="Card.TLabel").pack(side="left")
        self.img_h = ttk.Entry(g, width=8); self.img_h.pack(side="left")
        self.keep_aspect = tk.BooleanVar(value=True)
        self.chk_aspect = Check(g, "ไม่ให้รูปยืด (ย่อให้พอดีกรอบ)",
                                self.keep_aspect, self.th)
        self.chk_aspect.pack(side="left", padx=16)

        lab(f, "ฟอร์แมต", 2)
        self.img_fmt = ttk.Combobox(f, values=["JPEG", "WEBP", "PNG"], width=9, state="readonly")
        self.img_fmt.current(0); self.img_fmt.grid(row=2, column=1, sticky="w")
        hint(f, "WEBP เล็กกว่า JPEG ~25-30% ที่คุณภาพเท่ากัน", 2)

        lab(f, "ชุดค่าสำเร็จรูป", 3, muted=True)
        p = ttk.Frame(f, style="Card.TFrame"); p.grid(row=3, column=1, columnspan=3, sticky="w")
        for name, mb, w, h, fmt in [
            ("แนบอีเมล", "2", "", "", "JPEG"),
            ("ลงเว็บ", "0.5", "1920", "1920", "WEBP"),
            ("ลงโซเชียล", "1", "1080", "1080", "JPEG"),
            ("รูปโปรไฟล์", "0.3", "600", "600", "JPEG"),
        ]:
            ttk.Button(p, text=name, style="Chip.TButton",
                       command=lambda a=mb, b=w, d=h, e=fmt:
                       self._preset_img(a, b, d, e)).pack(side="left", padx=(0, 6))

        # ---------- วิดีโอ ----------
        f = card("วิดีโอ")
        lab(f, "ขนาดไฟล์สูงสุด (MB)", 0)
        self.vid_mb = ttk.Entry(f, width=10); self.vid_mb.insert(0, "25")
        self.vid_mb.grid(row=0, column=1, sticky="w")
        hint(f, "two-pass x264 — ขนาดออกมาราว 93-95% ของเป้า ไม่เคยเกิน", 0)

        lab(f, "ความสูง (px)", 1)
        self.vid_h = ttk.Combobox(f, values=["ไม่เปลี่ยน", "1080", "720", "480", "360"],
                                  width=12, state="readonly")
        self.vid_h.current(0); self.vid_h.grid(row=1, column=1, sticky="w")
        hint(f, "ความกว้างคำนวณให้เอง อัตราส่วนคงเดิม", 1)

        lab(f, "บิตเรตเสียง (kbps)", 2)
        self.vid_a = ttk.Entry(f, width=10); self.vid_a.insert(0, "128")
        self.vid_a.grid(row=2, column=1, sticky="w")
        hint(f, "คลิปที่ไม่มีเสียงจะข้ามค่านี้ให้เอง", 2)

        lab(f, "ชุดค่าสำเร็จรูป", 3, muted=True)
        p = ttk.Frame(f, style="Card.TFrame"); p.grid(row=3, column=1, columnspan=3, sticky="w")
        for name, mb, h in [("Discord 10MB", "10", "720"), ("LINE 25MB", "25", "720"),
                            ("ส่งอีเมล 5MB", "5", "480"), ("เก็บไว้ดู 100MB", "100", "1080")]:
            ttk.Button(p, text=name, style="Chip.TButton",
                       command=lambda a=mb, b=h:
                       self._preset_vid(a, b)).pack(side="left", padx=(0, 6))

        # ---------- ไฟล์ทั่วไป ----------
        f = card("ไฟล์ทั่วไป")
        lab(f, "ชื่อไฟล์ zip", 0)
        self.arc_name = ttk.Entry(f, width=26); self.arc_name.insert(0, "archive.zip")
        self.arc_name.grid(row=0, column=1, sticky="w")
        hint(f, "ไฟล์ที่ไม่ใช่รูป/วิดีโอทั้งหมดจะถูกรวบเป็น zip ก้อนนี้", 0)

        lab(f, "หั่นไฟล์ทุก ๆ (MB)", 1)
        self.arc_mb = ttk.Entry(f, width=10); self.arc_mb.grid(row=1, column=1, sticky="w")
        hint(f, "เว้นว่าง = ไม่หั่น", 1)

        ttk.Label(f, style="CardMuted.TLabel", wraplength=820,
                  text="ไฟล์ทั่วไปการันตีขนาดหลังบีบไม่ได้ — jpg / mp4 / exe ถูกบีบมาแล้ว "
                       'จึงแทบไม่ลดเลย การหั่นเป็นส่วนย่อยจึงเป็นวิธีเดียวที่ทำให้ '
                       '"ทุกไฟล์ไม่เกิน X MB" ได้จริง'
                  ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(10, 0))

        # ---------- คิว ----------
        f = card("คิว")
        lab(f, "รูปทำพร้อมกัน", 0)
        self.w_img = tk.IntVar(value=self.cfg.get("w_img", E.DEF_WORKERS[E.KIND_IMG]))
        ttk.Spinbox(f, from_=1, to=E.MAX_WORKERS[E.KIND_IMG], width=6,
                    textvariable=self.w_img).grid(row=0, column=1, sticky="w")
        hint(f, "Pillow เข้ารหัสด้วยโค้ด C ที่ปล่อย GIL เธรดจึงวิ่งขนานได้จริง "
                "ยิ่งหลายคอร์ยิ่งเร็ว", 0)

        lab(f, "วิดีโอทำพร้อมกัน", 1)
        self.w_vid = tk.IntVar(value=self.cfg.get("w_vid", E.DEF_WORKERS[E.KIND_VID]))
        ttk.Spinbox(f, from_=1, to=E.MAX_WORKERS[E.KIND_VID], width=6,
                    textvariable=self.w_vid).grid(row=1, column=1, sticky="w")
        hint(f, "แนะนำ 1 — ffmpeg ใช้ครบทุกคอร์อยู่แล้ว เปิดหลายตัวคือแย่งคอร์กันเอง", 1)

        ttk.Label(f, style="CardMuted.TLabel", wraplength=820,
                  text=f"คิวไม่จำกัดความยาว โยนเข้าไปกี่ไฟล์ก็ได้ — ตัวเลขข้างบนคุมแค่ว่า "
                       f"ดึงออกมาทำพร้อมกันทีละกี่งาน  (เครื่องนี้ {E.CPU} คอร์)"
                  ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(10, 0))

    def _preset_img(self, mb, w, h, fmt):
        for e, v in ((self.img_mb, mb), (self.img_w, w), (self.img_h, h)):
            e.delete(0, "end"); e.insert(0, v)
        self.img_fmt.set(fmt)
        self.keep_aspect.set(True)

    def _preset_vid(self, mb, h):
        self.vid_mb.delete(0, "end"); self.vid_mb.insert(0, mb)
        self.vid_h.set(h)

    # ==================== ส่วนล่าง ====================
    def _build_footer(self):
        wrap = ttk.Frame(self.root, padding=(20, 14, 20, 0))
        wrap.pack(fill="x", side="bottom")

        row = ttk.Frame(wrap)
        row.pack(fill="x")
        ttk.Label(row, text="เก็บผลลัพธ์ไว้ที่", style="Muted.TLabel").pack(side="left")
        self.out_lbl = ttk.Label(row, text=self._short(self.outdir), style="Muted.TLabel")
        self.out_lbl.pack(side="left", padx=8)
        ttk.Button(row, text="เปลี่ยน", command=self.pick_outdir).pack(side="left")
        ttk.Button(row, text="เปิดโฟลเดอร์",
                   command=lambda: open_in_explorer(self.outdir)).pack(side="left", padx=6)

        row2 = ttk.Frame(wrap, padding=(0, 12, 0, 0))
        row2.pack(fill="x")
        self.btn_start = ttk.Button(row2, text="เริ่มทำคิว", style="Accent.TButton",
                                    command=self.start)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(row2, text="หยุด", style="Danger.TButton",
                                   command=self.stop, state="disabled")
        self.btn_stop.pack(side="left", padx=8)
        self.prog_lbl = ttk.Label(row2, text="", style="Muted.TLabel", width=20, anchor="e")
        self.prog_lbl.pack(side="right")
        self.prog = ttk.Progressbar(row2, mode="determinate", maximum=100)
        self.prog.pack(side="left", fill="x", expand=True, padx=16)

        # log สูงคงที่ ไม่ใส่ expand ไม่งั้นมันจะไปแย่งพื้นที่ของตาราง

    @staticmethod
    def _short(path, keep=58):
        """path ยาว ๆ ตัดหัวทิ้ง ไม่ให้ดันปุ่มตกขอบหน้าต่าง"""
        p = str(path)
        return p if len(p) <= keep else "…" + p[-(keep - 1):]

    def _build_log(self):
        logwrap = ttk.Frame(self.root, padding=(20, 12, 20, 16))
        logwrap.pack(fill="x", side="bottom")
        border = tk.Frame(logwrap, bg=self.th.c["border"])
        border.pack(fill="x")
        self.logbox = tk.Text(border, height=6, wrap="word")
        self.logbox.pack(fill="x", padx=1, pady=1)
        self.th.style_text(self.logbox)
        self.logborder = border

    def pick_outdir(self):
        d = filedialog.askdirectory(title="เลือกโฟลเดอร์ปลายทาง", initialdir=self.outdir)
        if d:
            self.outdir = d
            self.out_lbl.config(text=self._short(d))
            self.cfg["outdir"] = d
            save_config(self.cfg)

    # ==================== จัดการไฟล์ ====================
    def add(self, paths):
        added = 0
        for p in paths:
            p = Path(p)
            if p.is_dir():
                for f in sorted(p.rglob("*")):
                    if f.is_file() and f not in self.paths:
                        self.paths.append(f); added += 1
            elif p.is_file() and p not in self.paths:
                self.paths.append(p); added += 1
        if added:
            self.refresh_pending()
            self.log(f"เพิ่ม {added} ไฟล์")

    def pick_files(self):
        self.add(filedialog.askopenfilenames(title="เลือกไฟล์ (เลือกหลายไฟล์พร้อมกันได้)"))

    def pick_folder(self):
        d = filedialog.askdirectory(title="เลือกโฟลเดอร์")
        if d:
            self.add([d])

    def _busy(self):
        if self.engine and self.engine.running:
            messagebox.showinfo("กำลังทำงานอยู่", "กดหยุดก่อน ถ้าอยากแก้รายการ")
            return True
        return False

    def remove_selected(self):
        if self._busy():
            return
        sel = set(self.tree.selection())
        if not sel:
            return
        drop_idx = {int(i[1:]) for i in sel if i.startswith("p")}
        drop_path = {p for jid in sel if jid.startswith("j") and jid in self.jobs
                     for p in self.jobs[jid].paths}
        self.paths = [p for i, p in enumerate(self.paths)
                      if i not in drop_idx and p not in drop_path]
        self.jobs = {}
        self.refresh_pending()

    def remove_done(self):
        """
        เอางานที่เสร็จแล้วออก

        จำเป็นจริง ๆ เพราะพอคิวจบ ไฟล์เดิมยังค้างในลิสต์
        ถ้ากดเริ่มอีกรอบมันจะบีบไฟล์เดิมซ้ำทั้งกอง
        """
        if self._busy():
            return
        done = {p for j in self.jobs.values() if j.status == E.DONE for p in j.paths}
        if not done:
            messagebox.showinfo("ไม่มีอะไรให้ลบ", "ยังไม่มีงานที่เสร็จแล้ว")
            return
        before = len(self.paths)
        self.paths = [p for p in self.paths if p not in done]
        self.jobs = {}
        self.refresh_pending()
        self.log(f"เอาออก {before - len(self.paths)} ไฟล์ที่เสร็จแล้ว")

    def clear(self):
        if self._busy():
            return
        self.paths.clear()
        self.jobs.clear()
        self.refresh_pending()

    def refresh_pending(self):
        self.tree.delete(*self.tree.get_children())
        self.order = []
        n = {E.KIND_IMG: 0, E.KIND_VID: 0, E.KIND_ARC: 0}
        for i, p in enumerate(self.paths):
            k = E.detect_kind(p)
            n[k] += 1
            iid = f"p{i}"
            par = "even" if i % 2 else "odd"
            self.tree.insert("", "end", iid=iid, text=f"  {p.name}",
                             tags=(f"queued_{par}",),
                             values=(E.KIND_LABEL[k], E.STATUS_TEXT[E.QUEUED], "",
                                     E.human(p.stat().st_size), "", "", ""))
            self.order.append(iid)
        self.count_lbl.config(
            text=f"รูป {n[E.KIND_IMG]}  ·  วิดีโอ {n[E.KIND_VID]}  ·  ไฟล์ {n[E.KIND_ARC]}"
                 f"   รวม {len(self.paths)}")
        self.prog.config(value=0)
        self.prog_lbl.config(text="")
        self.show_zone()

    # ==================== เริ่ม / หยุด ====================
    def read_settings(self):
        def num(entry, cast=float):
            s = entry.get().strip()
            return cast(s) if s else None

        st = E.default_settings(self.outdir)
        st["img"] = {"target_mb": num(self.img_mb),
                     "width": num(self.img_w, int), "height": num(self.img_h, int),
                     "keep_aspect": self.keep_aspect.get(), "fmt": self.img_fmt.get()}
        hv = self.vid_h.get()
        st["vid"] = {"target_mb": num(self.vid_mb) or 25.0,
                     "height": None if hv == "ไม่เปลี่ยน" else int(hv),
                     "audio_kbps": int(num(self.vid_a) or 128)}
        st["arc"] = {"split_mb": num(self.arc_mb),
                     "name": self.arc_name.get().strip() or "archive.zip"}
        return st

    def start(self):
        if self.engine and self.engine.running:
            return
        if not self.paths:
            messagebox.showinfo("ยังไม่มีไฟล์", "ลากไฟล์มาวาง หรือกดเพิ่มไฟล์ก่อนนะ")
            return
        if not Path(self.outdir).is_dir():
            messagebox.showinfo("โฟลเดอร์ปลายทางไม่มีอยู่", "เลือกโฟลเดอร์ปลายทางใหม่")
            self.pick_outdir()
            if not Path(self.outdir).is_dir():
                return
        try:
            st = self.read_settings()
        except ValueError:
            messagebox.showerror("ค่าไม่ถูกต้อง", "ช่องตัวเลขต้องกรอกเป็นตัวเลขเท่านั้น")
            return

        jobs = E.Engine.build_jobs(self.paths, arc_name=st["arc"]["name"])
        if not jobs:
            messagebox.showinfo("ไม่มีงาน", "ไม่พบไฟล์ที่ทำได้")
            return

        self.tree.delete(*self.tree.get_children())
        self.order, self.jobs = [], {}
        for i, j in enumerate(jobs):
            self.jobs[j.jid] = j
            self.order.append(j.jid)
            par = "even" if i % 2 else "odd"
            self.tree.insert("", "end", iid=j.jid, text=f"  {j.label}",
                             tags=(f"queued_{par}",),
                             values=(E.KIND_LABEL[j.kind], E.STATUS_TEXT[j.status], "",
                                     E.human(j.before), "", "", ""))
        self.show_zone()
        self._save_fields()

        self.engine = E.Engine(
            st,
            workers={E.KIND_IMG: self.w_img.get(), E.KIND_VID: self.w_vid.get()},
            on_update=lambda job: self.msgq.put(("job", job.jid)),
            on_log=lambda s: self.msgq.put(("log", s)),
            on_finish=lambda stats: self.msgq.put(("finish", stats)),
        )
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.log(f"\n── เริ่มคิว {len(jobs)} งาน → {self.outdir}")
        self.engine.start(jobs)

    def stop(self):
        if self.engine:
            self.log("กำลังหยุด… ยกเลิกคิวที่เหลือและปิด ffmpeg ที่กำลังวิ่ง")
            self.btn_stop.config(state="disabled")
            threading.Thread(target=self.engine.stop, daemon=True).start()

    # ==================== อัปเดตหน้าจอ ====================
    def log(self, text):
        self.logbox.insert("end", str(text) + "\n")
        self.logbox.see("end")

    def _pump(self):
        """
        ดึงข้อความจากเธรดงานมาอัปเดตหน้าจอ

        tkinter ห้ามแตะ widget จากเธรดอื่นโดยตรง เลยส่งผ่าน queue
        แล้วให้เธรดหลักมาเก็บเองเป็นรอบ ๆ
        """
        dirty = set()
        try:
            while True:
                kind, payload = self.msgq.get_nowait()
                if kind == "job":
                    dirty.add(payload)
                elif kind == "log":
                    self.log(payload)
                elif kind == "finish":
                    self._finish(payload)
        except queue.Empty:
            pass
        for jid in dirty:
            self._redraw(jid)
        if dirty:
            self._redraw_progress()
        self.root.after(80, self._pump)

    @staticmethod
    def _saved_text(saved):
        """
        ช่อง "ลดลง"

        ไฟล์ที่บีบไม่ลง (ข้อมูลสุ่ม, zip ซ้อน zip) จะโตขึ้นนิดหน่อยจาก header
        ค่าจะติดลบนิด ๆ แล้วโชว์เป็น "-0%" ซึ่งน่าเกลียด
        เลยปัดช่วงใกล้ศูนย์เป็น "เท่าเดิม" และถ้าโตขึ้นจริงก็บอกตรง ๆ
        """
        if saved is None:
            return ""
        if saved >= 0.5:
            return f"{saved:.0f}%"
        if saved > -0.5:
            return "เท่าเดิม"
        return f"โต {-saved:.0f}%"

    def _redraw(self, jid):
        j = self.jobs.get(jid)
        if not j or not self.tree.exists(jid):
            return
        par = "even" if self.order.index(jid) % 2 else "odd"
        self.tree.item(
            jid,
            tags=(f"{j.status}_{par}",),
            values=(E.KIND_LABEL[j.kind],
                    E.STATUS_TEXT[j.status],
                    f"{j.pct:.0f}" if j.status == E.RUNNING else
                    ("100" if j.status == E.DONE else ""),
                    E.human(j.before),
                    E.human(j.after) if j.after is not None else "",
                    self._saved_text(j.saved_pct),
                    j.msg),
        )

    def _redraw_progress(self):
        if not self.jobs:
            return
        total = len(self.jobs)
        acc = sum(100 if j.status in (E.DONE, E.ERROR, E.CANCELLED) else j.pct
                  for j in self.jobs.values())
        done = sum(1 for j in self.jobs.values()
                   if j.status in (E.DONE, E.ERROR, E.CANCELLED))
        self.prog.config(value=acc / total)
        self.prog_lbl.config(text=f"{done}/{total} งาน · {acc / total:.0f}%")

    def _finish(self, s):
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self._redraw_progress()
        parts = [f"เสร็จ {s['done']}"]
        if s["error"]:
            parts.append(f"ผิดพลาด {s['error']}")
        if s["cancelled"]:
            parts.append(f"ยกเลิก {s['cancelled']}")
        self.log(f"── จบคิว: {' · '.join(parts)}  ใช้เวลา {s['seconds']:.1f} วินาที")
        if s["before"]:
            self.log(f"   รวม {E.human(s['before'])} → {E.human(s['after'])} "
                     f"(ลด {100 - s['after'] / s['before'] * 100:.1f}%)")

    # ==================== อื่น ๆ ====================
    def do_join(self):
        p = filedialog.askopenfilename(title="เลือกไฟล์ .001",
                                       filetypes=[("ไฟล์ส่วนย่อย", "*.001"),
                                                  ("ทั้งหมด", "*.*")])
        if not p:
            return

        def work():
            self.msgq.put(("log", "\n── รวมไฟล์คืน"))
            try:
                out = E.join_parts(p, log=lambda s: self.msgq.put(("log", s)))
                self.msgq.put(("log", f"   เสร็จ → {out.name} "
                                      f"({E.human(out.stat().st_size)})"))
            except Exception as e:
                self.msgq.put(("log", f"   ผิดพลาด: {e}"))
        threading.Thread(target=work, daemon=True).start()

    def _save_fields(self):
        self.cfg.update({
            "theme": self.th.name, "outdir": self.outdir,
            "w_img": self.w_img.get(), "w_vid": self.w_vid.get(),
            "img": [self.img_mb.get(), self.img_w.get(), self.img_h.get(),
                    self.img_fmt.get(), self.keep_aspect.get()],
            "vid": [self.vid_mb.get(), self.vid_h.get(), self.vid_a.get()],
            "arc": [self.arc_name.get(), self.arc_mb.get()],
        })
        save_config(self.cfg)

    def _restore_fields(self):
        try:
            if "img" in self.cfg:
                mb, w, h, fmt, keep = self.cfg["img"]
                for e, v in ((self.img_mb, mb), (self.img_w, w), (self.img_h, h)):
                    e.delete(0, "end"); e.insert(0, v)
                if fmt in ("JPEG", "WEBP", "PNG"):
                    self.img_fmt.set(fmt)
                self.keep_aspect.set(bool(keep))
            if "vid" in self.cfg:
                mb, h, a = self.cfg["vid"]
                self.vid_mb.delete(0, "end"); self.vid_mb.insert(0, mb)
                self.vid_h.set(h)
                self.vid_a.delete(0, "end"); self.vid_a.insert(0, a)
            if "arc" in self.cfg:
                name, mb = self.cfg["arc"]
                self.arc_name.delete(0, "end"); self.arc_name.insert(0, name)
                self.arc_mb.delete(0, "end"); self.arc_mb.insert(0, mb)
        except Exception:
            pass          # ไฟล์ตั้งค่าเก่าคนละรูปแบบก็ช่างมัน ใช้ค่าเริ่มต้นไป

    def on_close(self):
        self._save_fields()
        if self.engine and self.engine.running:
            self.engine.stop()
        self.root.destroy()


def main():
    if not HAS_TK:
        sys.exit("ไม่พบ tkinter — บน Linux ให้รัน: sudo apt install python3-tk")
    root = TkinterDnD.Tk() if HAS_DND else tk.Tk()
    try:
        root.call("tk", "scaling", 1.25)
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
