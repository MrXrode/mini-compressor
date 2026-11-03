"""
theme.py — ชุดสีและการทาสีหน้าต่าง

แยกออกมาเพราะการทาสี ttk มันยาวและน่าเบื่อ ไม่ควรไปปนกับโค้ดหน้าตาหลัก
อยากเพิ่มธีมใหม่ก็แค่ก๊อป dict ใน PALETTES แล้วเปลี่ยนรหัสสี ไม่ต้องแตะที่อื่นเลย

ข้อจำกัดของ tkinter ที่ต้องรู้ไว้:
  - ทำมุมโค้งมน (border-radius) ไม่ได้ ทุกอย่างเป็นสี่เหลี่ยม
  - ทำเงา (shadow) ไม่ได้
  - ธีมเริ่มต้นบน Windows คือ 'vista' ซึ่ง "ล็อก" สีปุ่มกับตารางไว้ สั่งเปลี่ยนไปก็ไม่ขยับ
    เลยต้องสลับฐานเป็น 'clam' ก่อน ถึงจะทาสีได้ครบทุกชิ้น
"""

import tkinter as tk
from tkinter import ttk
import tkinter.font as tkfont


# ชื่อธีม -> ชุดสี   (โทนอ่อนทั้งหมด)
PALETTES = {
    "ขาวมินิมอล": {
        "bg": "#F7F8FA", "surface": "#FFFFFF", "border": "#E3E6EB",
        "text": "#1F2430", "muted": "#6B7280",
        "accent": "#3B6FF5", "accent_hover": "#2F5CD6", "accent_fg": "#FFFFFF",
        "hover": "#EDF0F5", "input": "#FFFFFF", "head": "#F2F4F8",
        "stripe": "#FAFBFD", "sel": "#DCE7FF", "track": "#E6EAF1",
        "zone": "#FBFCFE", "zone_active": "#E8F0FF",
        "ok": "#15803D", "err": "#B91C1C", "run": "#1D4ED8", "wait": "#6B7280",
    },
    "ครีมอบอุ่น": {
        "bg": "#FAF6EF", "surface": "#FFFDF8", "border": "#E8DFCE",
        "text": "#3A332A", "muted": "#8A7F6D",
        "accent": "#C98A2E", "accent_hover": "#AE7524", "accent_fg": "#FFFFFF",
        "hover": "#F3ECDF", "input": "#FFFDF8", "head": "#F5EEE1",
        "stripe": "#FDFAF3", "sel": "#F3E3C4", "track": "#EDE4D2",
        "zone": "#FDFBF5", "zone_active": "#F6EAD3",
        "ok": "#4D7C0F", "err": "#B4451F", "run": "#B07219", "wait": "#8A7F6D",
    },
    "มิ้นต์": {
        "bg": "#F2F9F6", "surface": "#FFFFFF", "border": "#D6E8E0",
        "text": "#1E3A32", "muted": "#6B8C81",
        "accent": "#10957A", "accent_hover": "#0C7B64", "accent_fg": "#FFFFFF",
        "hover": "#E6F3EE", "input": "#FFFFFF", "head": "#EAF5F0",
        "stripe": "#F8FCFA", "sel": "#CCEDE1", "track": "#DDEDE6",
        "zone": "#FAFDFC", "zone_active": "#D9F0E8",
        "ok": "#0F766E", "err": "#B91C1C", "run": "#0E8A72", "wait": "#6B8C81",
    },
    "ลาเวนเดอร์": {
        "bg": "#F7F5FC", "surface": "#FFFFFF", "border": "#E2DCF0",
        "text": "#2D2640", "muted": "#7A7191",
        "accent": "#7C5CD6", "accent_hover": "#6749BC", "accent_fg": "#FFFFFF",
        "hover": "#EFEBF9", "input": "#FFFFFF", "head": "#F1EDFA",
        "stripe": "#FBF9FE", "sel": "#E0D7F7", "track": "#E7E1F3",
        "zone": "#FCFBFE", "zone_active": "#E8E1F9",
        "ok": "#15803D", "err": "#B91C1C", "run": "#6D4FC9", "wait": "#7A7191",
    },
    "พีช": {
        "bg": "#FEF6F3", "surface": "#FFFFFF", "border": "#F5DDD3",
        "text": "#42302A", "muted": "#997F75",
        "accent": "#E2714A", "accent_hover": "#C85B36", "accent_fg": "#FFFFFF",
        "hover": "#FBEBE4", "input": "#FFFFFF", "head": "#FCEDE6",
        "stripe": "#FFFAF8", "sel": "#FADACB", "track": "#F3E2DA",
        "zone": "#FFFCFA", "zone_active": "#FCE3D8",
        "ok": "#4D7C0F", "err": "#B91C1C", "run": "#D2603A", "wait": "#997F75",
    },
    "ฟ้าหม่น": {
        "bg": "#F4F7FA", "surface": "#FFFFFF", "border": "#DCE4ED",
        "text": "#22303F", "muted": "#6E8096",
        "accent": "#2E7FA8", "accent_hover": "#246889", "accent_fg": "#FFFFFF",
        "hover": "#E9EFF5", "input": "#FFFFFF", "head": "#EDF2F7",
        "stripe": "#F9FBFD", "sel": "#D3E5F1", "track": "#E1E9F0",
        "zone": "#FAFCFD", "zone_active": "#DFEDF6",
        "ok": "#0F766E", "err": "#B91C1C", "run": "#2E7FA8", "wait": "#6E8096",
    },
}

DEFAULT_THEME = "ขาวมินิมอล"

# ฟอนต์ที่อ่านภาษาไทยสวย ไล่จากดีสุดลงมา เครื่องไหนมีตัวไหนก็ใช้ตัวนั้น
FONT_CANDIDATES = ["Leelawadee UI", "Leelawadee", "Noto Sans Thai", "IBM Plex Sans Thai",
                   "Tahoma", "Segoe UI", "TH Sarabun New", "DejaVu Sans"]
MONO_CANDIDATES = ["Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Courier New"]


def pick_font(root, candidates, fallback):
    """เลือกฟอนต์ตัวแรกที่เครื่องนี้มีจริง"""
    have = {f.lower() for f in tkfont.families(root)}
    for name in candidates:
        if name.lower() in have:
            return name
    return fallback


class Theme:
    """ถือชุดสี + ฟอนต์ที่เลือกได้ และทาสีให้ widget ทั้งหมด"""

    def __init__(self, root, name=DEFAULT_THEME):
        self.root = root
        self.font = pick_font(root, FONT_CANDIDATES, "TkDefaultFont")
        self.mono = pick_font(root, MONO_CANDIDATES, "TkFixedFont")
        self.style = ttk.Style(root)
        # ต้องสลับเป็น clam ก่อน ไม่งั้นธีมพื้นเมืองของ Windows จะไม่ยอมให้เปลี่ยนสี
        self.style.theme_use("clam")
        self.name = name
        self.c = PALETTES[name]
        self.apply(name)

    # ---------- ขนาดฟอนต์ ----------
    def f(self, size=10, bold=False):
        return (self.font, size, "bold") if bold else (self.font, size)

    def apply(self, name):
        """ทาสีใหม่ทั้งหน้าต่าง เรียกซ้ำได้ตอนผู้ใช้เปลี่ยนธีม"""
        self.name = name
        c = self.c = PALETTES[name]
        s = self.style
        F = self.font

        self.root.configure(bg=c["bg"])

        # ---- พื้นหลังทั่วไป ----
        s.configure(".", background=c["bg"], foreground=c["text"],
                    font=(F, 10), borderwidth=0, focuscolor=c["accent"])
        s.configure("TFrame", background=c["bg"])
        s.configure("Card.TFrame", background=c["surface"])
        s.configure("Zone.TFrame", background=c["zone"])

        s.configure("TLabel", background=c["bg"], foreground=c["text"], font=(F, 10))
        s.configure("Card.TLabel", background=c["surface"], foreground=c["text"])
        s.configure("Muted.TLabel", background=c["bg"], foreground=c["muted"], font=(F, 9))
        s.configure("CardMuted.TLabel", background=c["surface"], foreground=c["muted"], font=(F, 9))
        s.configure("Title.TLabel", background=c["bg"], foreground=c["text"], font=(F, 15, "bold"))
        s.configure("Sub.TLabel", background=c["bg"], foreground=c["muted"], font=(F, 9))
        s.configure("ZoneBig.TLabel", background=c["zone"], foreground=c["text"], font=(F, 13, "bold"))
        s.configure("ZoneSm.TLabel", background=c["zone"], foreground=c["muted"], font=(F, 10))

        # ---- ปุ่มธรรมดา ----
        s.configure("TButton", background=c["surface"], foreground=c["text"],
                    bordercolor=c["border"], lightcolor=c["surface"], darkcolor=c["surface"],
                    borderwidth=1, relief="flat", padding=(12, 7), font=(F, 10))
        s.map("TButton",
              background=[("pressed", c["hover"]), ("active", c["hover"]), ("disabled", c["bg"])],
              foreground=[("disabled", c["muted"])],
              bordercolor=[("active", c["accent"])])

        # ---- ปุ่มหลัก (เริ่มทำคิว) ----
        s.configure("Accent.TButton", background=c["accent"], foreground=c["accent_fg"],
                    bordercolor=c["accent"], lightcolor=c["accent"], darkcolor=c["accent"],
                    borderwidth=1, relief="flat", padding=(20, 9), font=(F, 11, "bold"))
        s.map("Accent.TButton",
              background=[("pressed", c["accent_hover"]), ("active", c["accent_hover"]),
                          ("disabled", c["track"])],
              foreground=[("disabled", c["muted"])],
              bordercolor=[("disabled", c["track"])])

        # ---- ปุ่มชิป (ชุดค่าสำเร็จรูป) ----
        # ปุ่มพวกนี้วางบนการ์ดสีขาว ถ้าใช้พื้นขาวเหมือน TButton จะกลืนหายไปเลย
        # เลยให้พื้นเป็นสี hover ไว้ จะได้เห็นว่าเป็นปุ่มกดได้
        s.configure("Chip.TButton", background=c["hover"], foreground=c["text"],
                    bordercolor=c["border"], lightcolor=c["hover"], darkcolor=c["hover"],
                    borderwidth=1, relief="flat", padding=(11, 6), font=(F, 9))
        s.map("Chip.TButton",
              background=[("active", c["sel"]), ("pressed", c["sel"])],
              bordercolor=[("active", c["accent"])])

        # ---- ปุ่มหยุด ----
        s.configure("Danger.TButton", background=c["surface"], foreground=c["err"],
                    bordercolor=c["border"], lightcolor=c["surface"], darkcolor=c["surface"],
                    borderwidth=1, relief="flat", padding=(16, 9), font=(F, 10, "bold"))
        s.map("Danger.TButton",
              background=[("active", c["hover"]), ("disabled", c["bg"])],
              foreground=[("disabled", c["muted"])],
              bordercolor=[("active", c["err"]), ("disabled", c["border"])])

        # ---- ตาราง ----
        s.configure("Treeview", background=c["surface"], fieldbackground=c["surface"],
                    foreground=c["text"], borderwidth=0, relief="flat",
                    rowheight=30, font=(F, 10))
        s.configure("Treeview.Heading", background=c["head"], foreground=c["muted"],
                    relief="flat", borderwidth=0, padding=(8, 9), font=(F, 9, "bold"))
        s.map("Treeview.Heading", background=[("active", c["hover"])])
        s.map("Treeview",
              background=[("selected", c["sel"])],
              foreground=[("selected", c["text"])])

        # ---- แท็บ ----
        s.configure("TNotebook", background=c["bg"], borderwidth=0, tabmargins=(0, 0, 0, 0))
        s.configure("TNotebook.Tab", background=c["bg"], foreground=c["muted"],
                    padding=(18, 9), borderwidth=0, font=(F, 10))
        s.map("TNotebook.Tab",
              background=[("selected", c["surface"])],
              foreground=[("selected", c["accent"])],
              expand=[("selected", (0, 0, 0, 0))])

        # ---- ช่องกรอก ----
        for st in ("TEntry", "TSpinbox", "TCombobox"):
            s.configure(st, fieldbackground=c["input"], background=c["input"],
                        foreground=c["text"], bordercolor=c["border"],
                        lightcolor=c["border"], darkcolor=c["border"],
                        arrowcolor=c["muted"], insertcolor=c["text"],
                        borderwidth=1, padding=(7, 5), font=(F, 10))
            s.map(st, bordercolor=[("focus", c["accent"])],
                  fieldbackground=[("readonly", c["input"]), ("disabled", c["bg"])],
                  foreground=[("disabled", c["muted"])])

        # รายการที่ร่วงลงมาของ combobox เป็น widget ของ tk ตัวเก่า ต้องสั่งผ่าน option ของ Tcl
        self.root.option_add("*TCombobox*Listbox.background", c["surface"])
        self.root.option_add("*TCombobox*Listbox.foreground", c["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", c["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", c["accent_fg"])
        self.root.option_add("*TCombobox*Listbox.font", (F, 10))

        # ---- ติ๊กถูก ----
        s.configure("TCheckbutton", background=c["bg"], foreground=c["text"],
                    indicatorcolor=c["input"], bordercolor=c["border"], font=(F, 10))
        s.map("TCheckbutton",
              background=[("active", c["bg"])],
              indicatorcolor=[("selected", c["accent"]), ("pressed", c["accent_hover"])])

        # ---- หลอดความคืบหน้า ----
        s.configure("TProgressbar", background=c["accent"], troughcolor=c["track"],
                    bordercolor=c["track"], lightcolor=c["accent"], darkcolor=c["accent"],
                    borderwidth=0, thickness=9)

        # ---- สกrollbar ----
        s.configure("Vertical.TScrollbar", background=c["track"], troughcolor=c["bg"],
                    bordercolor=c["bg"], arrowcolor=c["muted"], borderwidth=0)
        s.map("Vertical.TScrollbar", background=[("active", c["muted"])])

        # ---- เส้นคั่น ----
        s.configure("TSeparator", background=c["border"])

    # ---------- สีของแถวในตาราง ----------
    def row_tags(self, tree):
        """
        ตั้งสีแถวตามสถานะ + แถบสลับสี

        ttk ไม่ยอมให้แถวหนึ่งเอาสีพื้นจากแท็กหนึ่งและสีตัวอักษรจากอีกแท็กหนึ่ง
        เลยต้องสร้างแท็กรวมไว้ทุกคู่ (สถานะ x คู่/คี่) ให้มันชัดเจนไปเลย
        """
        c = self.c
        fg = {"queued": c["wait"], "running": c["run"],
              "done": c["ok"], "error": c["err"], "cancelled": c["muted"]}
        for status, color in fg.items():
            for parity, bgc in (("odd", c["surface"]), ("even", c["stripe"])):
                tree.tag_configure(f"{status}_{parity}", foreground=color, background=bgc)

    def style_text(self, widget):
        """tk.Text ไม่ใช่ ttk ต้องทาสีเอง"""
        c = self.c
        widget.configure(bg=c["surface"], fg=c["muted"], insertbackground=c["text"],
                         selectbackground=c["sel"], selectforeground=c["text"],
                         relief="flat", borderwidth=0, font=(self.mono, 9),
                         padx=10, pady=8, highlightthickness=0)


class Check(tk.Frame):
    """
    ช่องติ๊กถูกที่วาดเอง

    ทำไมไม่ใช้ ttk.Checkbutton: ธีม clam วาดเครื่องหมายตอนติ๊กแล้วเป็น "x"
    ซึ่งสื่อผิดความหมาย (ดูเหมือนปิดอยู่หรือถูกยกเลิก) และ tkinter เปลี่ยน
    เครื่องหมายนั้นไม่ได้ เลยวาดสี่เหลี่ยมกับเครื่องหมายถูกเองบน Canvas
    ได้ทั้งความถูกต้องและคุมสีตามธีมได้ครบ
    """

    def __init__(self, parent, text, variable, th, on_card=True, command=None):
        self.th, self.var, self.on_card, self.command = th, variable, on_card, command
        bg = th.c["surface"] if on_card else th.c["bg"]
        super().__init__(parent, bg=bg)
        self.cv = tk.Canvas(self, width=17, height=17, highlightthickness=0, bg=bg)
        self.cv.pack(side="left")
        self.lb = tk.Label(self, text=text, bg=bg, fg=th.c["text"], font=(th.font, 10))
        self.lb.pack(side="left", padx=(8, 0))
        for w in (self, self.cv, self.lb):
            w.bind("<Button-1>", self.toggle)
            w.configure(cursor="hand2")
        self.repaint()

    def toggle(self, _=None):
        self.var.set(not self.var.get())
        self.repaint()
        if self.command:
            self.command()

    def repaint(self):
        """วาดใหม่ ใช้ทั้งตอนกดติ๊กและตอนผู้ใช้เปลี่ยนธีม"""
        c = self.th.c
        bg = c["surface"] if self.on_card else c["bg"]
        self.configure(bg=bg)
        self.cv.configure(bg=bg)
        self.lb.configure(bg=bg, fg=c["text"], font=(self.th.font, 10))
        self.cv.delete("all")
        if self.var.get():
            self.cv.create_rectangle(2, 2, 15, 15, fill=c["accent"], outline=c["accent"])
            self.cv.create_line(5, 9, 7.5, 11.5, 12, 5.5, fill=c["accent_fg"],
                                width=2, capstyle="round", joinstyle="round")
        else:
            self.cv.create_rectangle(2, 2, 15, 15, fill=c["input"], outline=c["border"])
