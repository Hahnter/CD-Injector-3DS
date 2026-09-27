"""Tkinter app: choose the console, the game and its BIOS, pick a banner, and make the CIA."""

import json
import os
import queue
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from . import APP_NAME, VERSION
from . import banner as bn
from . import nsui
from .builder import BuildError, BuildOptions, build, check, clean_title, is_picture, resolve_cue
from .disc import SYSTEMS

SETTINGS = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME / "settings.json"
IMAGE_TYPES = [("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"), ("All files", "*.*")]
OK, BAD, MUTED = "#1b7a2b", "#b3261e", "#666"
PICTURES = "*.png *.jpg *.jpeg *.bmp *.gif *.webp"
STYLES = ["Title screen in a colored frame", "3D console + TV banner from NSUI"]
CW, CH = 320, 160                                   # the banner preview area

BIOS_HINTS = {
    "pce": "PC Engine CD needs the System Card 3.0 file, named syscard3.pce (256 KB).",
    "segacd": "Sega CD needs a BIOS file that matches the game's region: bios_CD_U.bin (USA), "
              "bios_CD_E.bin (Europe) or bios_CD_J.bin (Japan).",
}
BIOS_DEFAULT = "Leave this empty and the app looks for it next to the game."

HELP = [
    ("h1", "How to use CD Injector 3DS"),
    ("p", "This turns a PC Engine CD (TurboGrafx-CD) or Sega CD (Mega CD) game into a CIA: a single file that "
          "installs on your 3DS as its own Home Menu icon, with the game and its BIOS packed inside. "
          "It runs on the original 3DS and 2DS as well as the New models."),
    ("h2", "What you need"),
    ("b", "The game, as a .cue file with its .bin files in the same folder (a backup of a disc you own). "
          "A .chd file won't work directly: convert it first with chdman (extractcd)."),
    ("b", "The console's BIOS file: System Card 3.0 (syscard3.pce) for PC Engine CD, or bios_CD_U.bin / "
          "bios_CD_E.bin / bios_CD_J.bin for Sega CD. This app includes neither games nor BIOS files."),
    ("b", "A 3DS with custom firmware, and FBI (or a similar tool) to install the CIA."),
    ("h2", "The five steps"),
    ("n", "1  Console: choose PC Engine CD or Sega CD. The rest of the window unlocks."),
    ("n", "2  Game: choose the .cue file, or the folder that contains it. The app checks it and tells you if it "
          "looks like a different console."),
    ("n", "3  BIOS: choose the BIOS file or the folder holding it. If you leave it empty, the app searches next to "
          "the game."),
    ("n", "4  Banner and icon: optional, see below. Everything has a default."),
    ("n", "5  Create the CIA: choose where it goes (empty = next to the game's folder) and press Create CIA. It takes "
          "about a minute."),
    ("p", "Then copy the .cia to your 3DS's SD card and install it with FBI: open FBI, choose SD, find the file, "
          "and choose Install CIA."),
    ("h2", "Your options (step 4)"),
    ("b", "Game title, Publisher, Year: shown on the banner and under the icon. The title is filled in from the "
          "file name, and you can change it."),
    ("b", "Picture: a title screen or box art. It becomes the picture on the banner and the icon."),
    ("b", "Banner: \"Title screen in a colored frame\" makes a banner from your picture, and you choose the frame "
          "color. \"3D console + TV banner from NSUI\" uses a banner and icon you exported from NSUI (New Super "
          "Ultimate Injector): make a Genesis or TurboGrafx game there, export its banner and icon, and choose "
          "them here. You get NSUI's 3D console, controller and TV, and its sound."),
    ("b", "More options: how the picture fits the icon, your own banner sound, and the font used on the title "
          "plate."),
    ("h2", "Good to know"),
    ("b", "The CIA is about as big as the disc. FBI needs that much free space again while installing, and you "
          "can delete the .cia afterwards."),
    ("b", "Making the same game again keeps its ID, so installing it again updates the earlier copy."),
    ("b", "Saves go to sdmc:/emus3ds/saves/<game>/ on the SD card."),
    ("b", "If a game freezes or glitches, touch the bottom screen for the emulator menu and try the other CPU Core "
          "setting (PC Engine CD). It is remembered per game."),
    ("b", "Never share a CIA you made: it contains the game and the BIOS."),
    ("h2", "Privacy and safety"),
    ("b", "This app never connects to the internet and collects nothing. It reads only the files you choose and "
          "writes only the CIA and a small settings file (the paths and colors you picked) in your user profile."),
    ("b", "Files you choose are checked before use: a damaged or oversized file gives an error message instead of "
          "being used."),
]

ABOUT = [
    ("h1", f"{APP_NAME} {VERSION}"),
    ("p", "Makes per-game 3DS CIAs from PC Engine CD and Sega CD games, with the emulator, the game and the BIOS "
          "all inside one file."),
    ("h2", "Built on"),
    ("b", "emus3ds by bubble2k16, continued by R-YaTian (TemperPCE and PicoDrive for the 3DS)"),
    ("b", "Temper by Exophase, and PicoDrive by notaz, irixxxx and contributors"),
    ("b", "bannertool by Steveice10, and makerom by 3DSGuy"),
    ("h2", "Licence"),
    ("p", "The app's own code is MIT-licensed. PicoDrive's licence, though, makes the download as a whole free "
          "and non-commercial, and the complete source of the modified emulators is published with every release. "
          "Full notices are in THIRD-PARTY-NOTICES.md and LICENSE, next to the app."),
    ("p", "Not affiliated with or endorsed by Nintendo, Sega or NEC. No games or BIOS files are included. Never "
          "share the CIAs you make."),
]


class Tooltip:
    """A small hover label (Tk has none built in)."""

    def __init__(self, widget, text):
        self.widget, self.text, self.tip, self._job = widget, text, None, None
        widget.bind("<Enter>", self._later, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _later(self, _):
        self._job = self.widget.after(450, self._show)

    def _show(self):
        if self.tip:
            return
        x, y = self.widget.winfo_rootx() + 10, self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, bg="#ffffe1", fg="#000", relief="solid", bd=1, padx=6, pady=2,
                 font=("Segoe UI", 9)).pack()

    def _hide(self, _=None):
        if self._job:
            self.widget.after_cancel(self._job)
            self._job = None
        if self.tip:
            self.tip.destroy()
            self.tip = None


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {VERSION}")
        self.settings = self._load_settings()
        self.q = queue.Queue()
        self.busy = False
        self.ready = False
        self.image = None
        self._photos = {}
        self._check_job = None
        self._check_seq = 0
        self._game_ok = False
        self._steps = {}                                   # step number -> (text variable, label)

        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Big.TButton", padding=(24, 10), font=("Segoe UI", 10, "bold"))
        style.configure("Step.TLabel", font=("Segoe UI", 11, "bold"))
        style.configure("Hint.TLabel", foreground=MUTED)

        # the whole window scrolls when the screen is too short to show it all
        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True)
        self._canvas = tk.Canvas(outer, highlightthickness=0, bd=0)
        self._vbar = ttk.Scrollbar(outer, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._vbar.set)
        self._vbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        root = ttk.Frame(self._canvas, padding=(14, 10, 14, 10))
        self.content = root
        self._canvas_window = self._canvas.create_window((0, 0), window=root, anchor="nw")
        root.bind("<Configure>", lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", lambda e: self._canvas.itemconfigure(self._canvas_window, width=e.width))
        self._canvas.bind("<Enter>", lambda e: self.bind_all("<MouseWheel>", self._wheel))
        self._canvas.bind("<Leave>", lambda e: self.unbind_all("<MouseWheel>"))

        # ---- header
        head = ttk.Frame(root)
        head.pack(fill="x")
        ttk.Label(head, text=APP_NAME, font=("Segoe UI", 16, "bold")).pack(side="left")
        ttk.Label(head, text="Turn a PC Engine CD or Sega CD game into an installable 3DS app (a CIA).",
                  style="Hint.TLabel").pack(side="left", padx=(14, 0), pady=(6, 0))
        ttk.Button(head, text="About", command=self.show_about).pack(side="right")
        ttk.Button(head, text="How to use", command=self.show_help).pack(side="right", padx=(0, 6))
        ttk.Frame(root, height=6).pack()

        # ---- 1. console
        self.v_sys = tk.StringVar(value="")
        f1 = self._section(root, 1, "Console: which console is the game for?", None)
        cards = ttk.Frame(f1)
        cards.pack(fill="x", pady=(2, 0))
        cards.columnconfigure(0, weight=1, uniform="cards")
        cards.columnconfigure(1, weight=1, uniform="cards")
        for col, (key, name, sub, tint) in enumerate([
                ("pce", "PC Engine CD", "PC Engine CD-ROM² / TurboGrafx-CD games", "#f7c79c"),
                ("segacd", "Sega CD", "Sega CD / Mega CD games", "#a9c1f2")]):
            cell = ttk.Frame(cards)
            cell.grid(row=0, column=col, sticky="ew", padx=(0, 10) if col == 0 else 0)
            tk.Radiobutton(cell, text=name, variable=self.v_sys, value=key, indicatoron=False,
                           font=("Segoe UI", 12, "bold"), pady=5, bd=2, relief="raised", bg="#f0f0f0",
                           activebackground=tint, selectcolor=tint, cursor="hand2",
                           command=self._system_changed).pack(fill="x")
            ttk.Label(cell, text=sub, style="Hint.TLabel").pack(pady=(1, 0))

        body = ttk.Frame(root)                              # steps 2 to 5, locked until a console is chosen
        body.pack(fill="x")
        self.body = body

        # ---- 2. game
        self.v_game = tk.StringVar()
        f2 = self._section(body, 2, "Game", "Choose the game's .cue file (its .bin files must be in the same "
                                            "folder), or the folder that holds it.")
        row = ttk.Frame(f2)
        row.pack(fill="x", pady=(4, 0))
        row.columnconfigure(0, weight=1)
        ttk.Entry(row, textvariable=self.v_game).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(row, text="Choose .cue file…", command=self.pick_cue).grid(row=0, column=1)
        ttk.Button(row, text="Choose folder…", command=self.pick_game_folder).grid(row=0, column=2, padx=(4, 0))
        self.l_game = f2.hint                               # shows the hint, then the result of the check
        self._game_hint = f2.hint.cget("text")

        # ---- 3. BIOS
        self.v_bios = tk.StringVar(value=self.settings.get("bios", ""))
        f3 = self._section(body, 3, "BIOS", BIOS_DEFAULT)
        self.l_bios = f3.hint                               # shows the hint, then the result of the check
        self._bios_hint = BIOS_DEFAULT
        row = ttk.Frame(f3)
        row.pack(fill="x", pady=(4, 0))
        row.columnconfigure(0, weight=1)
        ttk.Entry(row, textvariable=self.v_bios).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(row, text="Choose file…", command=self.pick_bios_file).grid(row=0, column=1)
        ttk.Button(row, text="Choose folder…", command=self.pick_bios_folder).grid(row=0, column=2, padx=(4, 0))

        # ---- 4. banner and icon
        f4 = self._section(body, 4, "Banner and icon (optional)",
                           "This is how the game looks on the Home Menu. Everything has a default, so you can skip it.")
        cols = ttk.Frame(f4)
        cols.pack(fill="x", pady=(4, 0))
        left = ttk.Frame(cols)
        left.grid(row=0, column=0, sticky="new")
        left.columnconfigure(1, weight=1)
        cols.columnconfigure(0, weight=1)

        self.v_title, self.v_pub, self.v_year = tk.StringVar(), tk.StringVar(), tk.StringVar()
        ttk.Label(left, text="Game title").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Entry(left, textvariable=self.v_title).grid(row=0, column=1, sticky="ew", padx=8, pady=2)
        ttk.Label(left, text="Publisher").grid(row=1, column=0, sticky="w", pady=2)
        pf = ttk.Frame(left)
        pf.grid(row=1, column=1, sticky="ew", padx=8, pady=2)
        pf.columnconfigure(0, weight=1)
        ttk.Entry(pf, textvariable=self.v_pub).grid(row=0, column=0, sticky="ew")
        ttk.Label(pf, text="Year").grid(row=0, column=1, padx=(10, 6))
        ttk.Entry(pf, textvariable=self.v_year, width=7).grid(row=0, column=2)
        for var in (self.v_title, self.v_pub, self.v_year):
            var.trace_add("write", lambda *a: self._schedule_preview())

        ttk.Label(left, text="Picture").grid(row=2, column=0, sticky="w", pady=(6, 2))
        ib = ttk.Frame(left)
        ib.grid(row=2, column=1, sticky="w", padx=8, pady=(6, 2))
        ttk.Button(ib, text="Choose a picture…", command=self.pick_image).pack(side="left")
        ttk.Button(ib, text="Clear", command=self.clear_image).pack(side="left", padx=(4, 0))
        ttk.Label(ib, text="a title screen or box art", style="Hint.TLabel").pack(side="left", padx=(8, 0))

        ttk.Label(left, text="Banner").grid(row=3, column=0, sticky="w", pady=(8, 2))
        self.v_style = tk.StringVar(value=STYLES[1] if self.settings.get("banner_style") == "nsui" else STYLES[0])
        cb = ttk.Combobox(left, textvariable=self.v_style, values=STYLES, state="readonly")
        cb.grid(row=3, column=1, sticky="ew", padx=8, pady=(8, 2))
        cb.bind("<<ComboboxSelected>>", lambda e: self._style_changed())

        # the frame colour ("" means the system's own colour)
        self.v_banner_file, self.v_icon_file = tk.StringVar(), tk.StringVar()
        self.v_color = tk.StringVar(value=self.settings.get("color", ""))
        cf = ttk.Frame(left)
        cf.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.f_color = cf
        ttk.Label(cf, text="Frame color").pack(side="left")
        sw_row = ttk.Frame(cf)
        sw_row.pack(side="left", padx=(8, 0))
        self.swatches = []
        for name, rgb in bn.COLOR_PRESETS:
            sw = tk.Canvas(sw_row, width=24, height=24, highlightthickness=0, cursor="hand2")
            sw.pack(side="left", padx=(0, 3))
            sw.bind("<Button-1>", lambda e, c=rgb: self._set_color(c))
            Tooltip(sw, name)
            self.swatches.append((sw, rgb))
        ttk.Button(cf, text="Custom…", command=self.pick_color).pack(side="left", padx=(8, 0))
        ttk.Button(cf, text="Reset", command=lambda: self._set_color(None)).pack(side="left", padx=(4, 0))

        # a banner and icon exported from NSUI (or your own files)
        nf = ttk.Frame(left)
        nf.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        nf.columnconfigure(1, weight=1)
        self.f_nsui = nf
        ttk.Label(nf, text="In NSUI, export a Genesis or TurboGrafx game's banner and icon, then choose them.",
                  style="Hint.TLabel").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 3))
        for r, (label, var, types) in enumerate([
                ("Banner file", self.v_banner_file, [("3DS banner or picture", "*.bin *.bnr " + PICTURES)]),
                ("Icon file", self.v_icon_file, [("3DS icon or picture", "*.bin *.icn *.smdh " + PICTURES)])], start=1):
            ttk.Label(nf, text=label).grid(row=r, column=0, sticky="w", pady=2)
            ttk.Entry(nf, textvariable=var).grid(row=r, column=1, sticky="ew", padx=8)
            ttk.Button(nf, text="Choose…", command=lambda v=var, t=types: self._pick_banner_file(v, t)).grid(
                row=r, column=2)
            ttk.Button(nf, text="Clear", command=lambda v=var: v.set("")).grid(row=r, column=3, padx=(4, 0))
            var.trace_add("write", lambda *a: (self._schedule_preview(), self._update_export()))
        self._apply_style()

        self.v_fit = tk.StringVar(value="height")
        self.v_sound = tk.StringVar()
        self.v_font = tk.StringVar(value=self.settings.get("plate_font", ""))
        for var in (self.v_fit, self.v_sound, self.v_font):
            var.trace_add("write", lambda *a: self._schedule_preview())
        self.v_font.trace_add("write", lambda *a: self._remember_font())

        # the preview: banner and icon as they'll look on the Home Menu
        prev = ttk.Frame(cols)
        prev.grid(row=0, column=1, sticky="ne", padx=(16, 0))
        ttk.Label(prev, text="Preview of the Home Menu banner (top screen)", style="Hint.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Label(prev, text="Icon", style="Hint.TLabel").grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.c_banner = tk.Canvas(prev, width=CW, height=CH, highlightthickness=1, highlightbackground="#bbb",
                                  bg="#dfe5ec")
        self.c_banner.grid(row=1, column=0, sticky="n")
        self.c_icon = tk.Canvas(prev, width=96, height=96, highlightthickness=1, highlightbackground="#bbb")
        self.c_icon.grid(row=1, column=1, sticky="n", padx=(12, 0))
        ttk.Button(prev, text="More options…", command=self.show_more).grid(row=2, column=0, sticky="w", pady=(8, 0))

        # ---- 5. save
        self.v_out = tk.StringVar(value=self.settings.get("out", ""))
        f5 = self._section(body, 5, "Create the CIA", "Choose the folder to save it in. Empty means next to the "
                                                     "game's folder.")
        row = ttk.Frame(f5)
        row.pack(fill="x", pady=(4, 0))
        row.columnconfigure(0, weight=1)
        ttk.Entry(row, textvariable=self.v_out).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(row, text="Choose folder…", command=self.pick_out).grid(row=0, column=1)
        act = ttk.Frame(f5)
        act.pack(fill="x", pady=(10, 0))
        act.columnconfigure(0, weight=1)
        self.pb = ttk.Progressbar(act, maximum=1000)
        self.pb.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        self.b_export = ttk.Button(act, text="Create CIA", style="Big.TButton", command=self.export)
        self.b_export.grid(row=0, column=1)
        self.l_status = ttk.Label(f5, text="Choose a console to begin.", style="Hint.TLabel")
        self.l_status.pack(anchor="w", pady=(6, 0))
        self.b_export.state(["disabled"])

        self.v_game.trace_add("write", lambda *a: self._game_changed())
        self.v_bios.trace_add("write", lambda *a: self._game_changed())
        self._set_body_enabled(False)          # locked until a console is chosen
        self._update_steps()
        self._update_export()
        self._fit_to_screen()
        self.after(100, self._poll)
        self.after(200, self.refresh_preview)

    def _fit_to_screen(self):
        """Open at the height the content needs, but never taller than the screen; a scrollbar covers the rest."""
        self.update_idletasks()
        w = self.content.winfo_reqwidth() + self._vbar.winfo_reqwidth()
        h = min(self.content.winfo_reqheight() + 2, max(420, self.winfo_screenheight() - 110))
        self.geometry(f"{w}x{h}")
        self.minsize(min(w, 760), 380)

    def _wheel(self, event):
        if self._vbar.get() != (0.0, 1.0):                   # only when there is something to scroll
            self._canvas.yview_scroll(int(-event.delta / 120), "units")

    # ---------------------------------------------------------------- building blocks
    def _section(self, parent, n, title, hint):
        """A framed step with a numbered heading. Returns the frame; `.hint` is its hint label."""
        var = tk.StringVar(value=f"{n}  {title}")
        lab = ttk.Label(parent, textvariable=var, style="Step.TLabel")
        frame = ttk.LabelFrame(parent, labelwidget=lab, padding=(12, 2, 12, 6))
        frame.pack(fill="x", pady=(0, 6))
        frame.hint = ttk.Label(frame, text=hint or "", style="Hint.TLabel", wraplength=880, justify="left")
        if hint:
            frame.hint.pack(anchor="w")
        self._steps[n] = (var, lab, title)
        return frame

    def _mark(self, n, state):
        """state: 'done' puts a green check on step n's heading, 'bad' a red cross, None clears it."""
        var, lab, title = self._steps[n]
        mark = {"done": "  ✓", "bad": "  ✗"}.get(state, "")
        var.set(f"{n}  {title}{mark}")
        lab.config(foreground={"done": OK, "bad": BAD}.get(state, "#000"))

    def _update_steps(self):
        self._mark(1, "done" if self.system_choice() else None)
        if not self.system_choice():
            for n in (2, 3):
                self._mark(n, None)
            return
        self._mark(2, "done" if self._game_ok else (None if not self.v_game.get().strip() else "bad"))
        self._mark(3, "done" if self.ready else (None if not self._game_ok else "bad"))

    def _text_dialog(self, title, blocks, width=84, height=30):
        win = tk.Toplevel(self)
        win.title(title)
        win.transient(self)
        frame = ttk.Frame(win, padding=10)
        frame.pack(fill="both", expand=True)
        txt = tk.Text(frame, wrap="word", width=width, height=height, padx=10, pady=8, relief="flat", bg="#fafafa",
                      font=("Segoe UI", 10), cursor="arrow", spacing3=4)
        bar = ttk.Scrollbar(frame, command=txt.yview)
        txt.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)
        txt.tag_configure("h1", font=("Segoe UI", 15, "bold"), spacing3=8)
        txt.tag_configure("h2", font=("Segoe UI", 11, "bold"), spacing1=12, spacing3=4)
        txt.tag_configure("b", lmargin1=18, lmargin2=34)
        txt.tag_configure("n", lmargin1=18, lmargin2=36)
        for style, text in blocks:
            if style == "b":
                txt.insert("end", "•  " + text + "\n", "b")
            elif style == "n":
                txt.insert("end", text + "\n", "n")
            else:
                txt.insert("end", text + "\n", style)
        txt.configure(state="disabled")
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=(0, 10))
        win.bind("<Escape>", lambda e: win.destroy())
        win.focus_set()

    def show_help(self):
        self._text_dialog("How to use", HELP, height=26)

    def show_about(self):
        self._text_dialog("About", ABOUT, width=70, height=18)

    def show_more(self):
        """The rarely needed options, in their own small window."""
        win = tk.Toplevel(self)
        win.title("More options")
        win.transient(self)
        win.resizable(False, False)
        f = ttk.Frame(win, padding=14)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)

        ttk.Label(f, text="Icon picture", style="Step.TLabel").grid(row=0, column=0, sticky="w")
        fit = ttk.Frame(f)
        fit.grid(row=0, column=1, columnspan=3, sticky="w", padx=8)
        for t, v in (("Fill top to bottom", "height"), ("Fill side to side", "width")):
            ttk.Radiobutton(fit, text=t, value=v, variable=self.v_fit).pack(side="left", padx=(0, 12))
        ttk.Label(f, text="How your picture fits the square icon. The other direction gets black bars.",
                  style="Hint.TLabel").grid(row=1, column=1, columnspan=3, sticky="w", padx=8, pady=(0, 10))

        rows = [("Banner sound", self.v_sound, [("Sound", "*.wav *.bcwav")],
                 "A .wav or .bcwav that plays on the Home Menu. Empty means a short built-in chime. "
                 "An NSUI banner keeps its own sound."),
                ("Title plate font", self.v_font, [("Font", "*.ttf *.otf")],
                 "A .ttf or .otf file for the title and year on the Virtual Console plate. Empty means "
                 "Arial Bold. Official banners look closest with Sony's Rodin Bold, which you'd supply yourself.")]
        for i, (label, var, types, note) in enumerate(rows):
            r = 2 + i * 2
            ttk.Label(f, text=label, style="Step.TLabel").grid(row=r, column=0, sticky="w")
            ttk.Entry(f, textvariable=var, width=52).grid(row=r, column=1, sticky="ew", padx=8)
            ttk.Button(f, text="Choose…", command=lambda v=var, t=types: self._browse_into(v, t)).grid(row=r, column=2)
            ttk.Button(f, text="Clear", command=lambda v=var: v.set("")).grid(row=r, column=3, padx=(4, 0))
            ttk.Label(f, text=note, style="Hint.TLabel", wraplength=560, justify="left").grid(
                row=r + 1, column=1, columnspan=3, sticky="w", padx=8, pady=(0, 10))
        ttk.Button(f, text="Close", command=win.destroy).grid(row=6, column=3, sticky="e", pady=(4, 0))
        win.bind("<Escape>", lambda e: win.destroy())
        win.grab_set()
        win.focus_set()

    def _pick_banner_file(self, var, types):
        """Choose a banner or icon file; NSUI names them <game>_banner.bin and <game>_icon.bin, so the other
        file of the pair is filled in too when it's next to it."""
        p = filedialog.askopenfilename(title="Choose the file", filetypes=types + [("All files", "*.*")],
                                       initialdir=self.settings.get("nsui_dir"))
        if not p:
            return
        self.settings["nsui_dir"] = str(Path(p).parent)
        self._save_settings()
        var.set(p)
        other = nsui.sibling(p)
        if other:
            target = self.v_icon_file if var is self.v_banner_file else self.v_banner_file
            if not target.get().strip():
                target.set(str(other))
        self._schedule_preview()

    def nsui_mode(self):
        return self.v_style.get() == STYLES[1]

    def _apply_style(self):
        """Show the controls of the chosen banner: the frame colour, or the NSUI banner and icon files."""
        if self.nsui_mode():
            self.f_color.grid_remove()
            self.f_nsui.grid()
        else:
            self.f_nsui.grid_remove()
            self.f_color.grid()

    def _style_changed(self):
        self.settings["banner_style"] = "nsui" if self.nsui_mode() else "frame"
        self._save_settings()
        self._apply_style()
        self._update_export()
        self.refresh_preview()

    def _remember_font(self):
        self.settings["plate_font"] = self.v_font.get().strip()
        self._save_settings()

    def font_file(self):
        """The title plate's font file if one is chosen and exists, else None (the default font is used)."""
        p = self.v_font.get().strip()
        return Path(p) if p and Path(p).is_file() else None

    def _browse_into(self, var, types):
        p = filedialog.askopenfilename(filetypes=types + [("All files", "*.*")])
        if p:
            var.set(p)

    def system_choice(self):
        return self.v_sys.get()

    def _system_changed(self):
        """A console was picked: unlock the rest of the window and tailor it to that console."""
        system = self.system_choice()
        self._set_body_enabled(True)
        self._bios_hint = BIOS_HINTS[system] + " " + BIOS_DEFAULT
        self.l_bios.config(text=self._bios_hint, foreground=MUTED)
        self.schedule_check()
        self.refresh_preview()
        self._update_steps()
        self._update_export()

    def _set_body_enabled(self, enabled):
        """Grey out (or restore) every control below the console choice."""
        def walk(w):
            for child in w.winfo_children():
                if isinstance(child, (ttk.Entry, ttk.Button, ttk.Combobox, ttk.Radiobutton, ttk.Checkbutton)):
                    child.state(["!disabled"] if enabled else ["disabled"])
                walk(child)
        walk(self.body)

    # ---------------------------------------------------------------- pickers
    def pick_cue(self):
        p = filedialog.askopenfilename(title="Choose the game's .cue file", filetypes=[("CUE sheet", "*.cue")],
                                       initialdir=self.settings.get("game_dir"))
        if p:
            self.settings["game_dir"] = str(Path(p).parent.parent)
            self.v_game.set(p)

    def pick_game_folder(self):
        p = filedialog.askdirectory(title="Choose the game's folder", initialdir=self.settings.get("game_dir"))
        if p:
            self.settings["game_dir"] = str(Path(p).parent)
            self.v_game.set(p)

    def pick_bios_file(self):
        p = filedialog.askopenfilename(title="Choose the BIOS file", filetypes=[("BIOS", "*.pce *.bin"), ("All files", "*.*")])
        if p:
            self.v_bios.set(p)

    def pick_bios_folder(self):
        p = filedialog.askdirectory(title="Choose a folder with BIOS files")
        if p:
            self.v_bios.set(p)

    def pick_image(self):
        p = filedialog.askopenfilename(title="Title screen or box art", filetypes=IMAGE_TYPES)
        if p:
            self.image = p
            self.refresh_preview()

    def clear_image(self):
        self.image = None
        self.refresh_preview()

    def pick_out(self):
        p = filedialog.askdirectory(title="Save the CIA to")
        if p:
            self.v_out.set(p)

    # ---------------------------------------------------------------- checks
    def _game_changed(self):
        self._game_ok = False
        self.ready = False
        self._update_steps()
        self.schedule_check()

    def schedule_check(self):
        if self._check_job:
            self.after_cancel(self._check_job)
        self._check_job = self.after(300, self._start_check)

    def _start_check(self):
        self._check_job = None
        game = self.v_game.get().strip()
        if not self.system_choice() or not game:
            self.ready = False
            self.l_game.config(text=self._game_hint, foreground=MUTED)
            self.l_bios.config(text=self._bios_hint, foreground=MUTED)
            self._update_steps()
            self._update_export()
            return
        self._check_seq += 1
        opt = BuildOptions(game=Path(game), bios=Path(self.v_bios.get()) if self.v_bios.get().strip() else None,
                           system=self.system_choice())
        self.l_game.config(text="Checking…", foreground=MUTED)
        threading.Thread(target=self._run_check, args=(opt, self._check_seq), daemon=True).start()

    def _run_check(self, opt, seq):
        result = {}
        try:
            cue = resolve_cue(opt.game)
            result["cue"] = cue
            disc, system, bios_files, notes = check(opt)
            result.update(disc=disc, system=system, notes=notes)
        except BuildError as e:
            result["error"] = str(e)
        except Exception as e:                                   # a check must always answer, or the window waits for ever
            result["error"] = f"Couldn't check this file ({type(e).__name__}: {e})."
        self.q.put(("check", seq, result))

    def _show_check(self, r):
        disc = r.get("disc")
        if disc:
            self.l_game.config(foreground=OK, text=f"✓ {SYSTEMS[r['system']]['name']} game found · "
                                                    f"{len(disc.tracks)} files · {disc.total_bytes / 1048576:.0f} MB")
            self.l_bios.config(foreground=OK, text="✓ " + "  ·  ".join(r["notes"]))
            if not self.v_title.get() and "cue" in r:
                self.v_title.set(clean_title(r["cue"].stem))
            self._game_ok = True
            self.ready = True
        else:
            err = r.get("error", "")
            self.ready = False
            if "BIOS" in err or "System Card" in err:
                self._game_ok = True
                self.l_game.config(foreground=OK, text="✓ Game found")
                self.l_bios.config(foreground=BAD, text="✗ " + err)
            else:
                self._game_ok = False
                self.l_game.config(foreground=BAD, text="✗ " + err.splitlines()[0])
                self.l_bios.config(text=self._bios_hint, foreground=MUTED)
        self._update_steps()
        self._update_export()
        self.refresh_preview()

    def _update_export(self):
        missing = self.ready and self.nsui_mode() and not self.v_banner_file.get().strip()
        if self.busy or not self.ready or missing:
            self.b_export.state(["disabled"])
            if not self.busy:
                if not self.system_choice():
                    msg = "Start with step 1: choose PC Engine CD or Sega CD."
                elif not self.v_game.get().strip():
                    msg = "Next, step 2: choose the game."
                elif not self._game_ok:
                    msg = "Fix the problem shown under step 2."
                elif not self.ready:
                    msg = "Fix the problem shown under step 3."
                elif missing:
                    msg = "Choose the banner file you exported from NSUI (step 4), or switch Banner back to the colored frame."
                else:
                    msg = "Fix the items marked ✗."
                self.l_status.config(text=msg, foreground=MUTED)
        else:
            self.b_export.state(["!disabled"])
            self.l_status.config(text="Ready. Press Create CIA.", foreground=OK)

    # ---------------------------------------------------------------- preview
    _preview_job = None

    def _schedule_preview(self):
        if self._preview_job:
            self.after_cancel(self._preview_job)
        self._preview_job = self.after(250, self.refresh_preview)

    def effective_color(self):
        """The frame colour in use: the chosen one, else the current system's own."""
        return bn.parse_color(self.v_color.get()) or bn.DEFAULT_COLORS.get(self.system_choice() or "pce")

    def _set_color(self, rgb):
        self.v_color.set(bn.color_hex(rgb) if rgb else "")
        self.settings["color"] = self.v_color.get()
        self._save_settings()
        self._refresh_swatches()
        self._schedule_preview()

    def pick_color(self):
        from tkinter import colorchooser
        rgb, _ = colorchooser.askcolor(color=bn.color_hex(self.effective_color()), title="Frame color")
        if rgb:
            self._set_color(tuple(round(c) for c in rgb))

    def _refresh_swatches(self):
        current = self.effective_color()
        for sw, rgb in self.swatches:
            sw.delete("all")
            picked = tuple(rgb) == tuple(current)
            sw.create_rectangle(2, 2, 22, 22, fill=bn.color_hex(rgb), outline="#000" if picked else "#999",
                                width=3 if picked else 1)

    def _draw_nsui_preview(self, path, title):
        """The 3D console, TV and title plate inside an NSUI banner, as they'll look on the Home Menu (a still picture)."""
        try:
            img = nsui.preview_image(path, title, self.v_year.get().strip(), (CW, CH), font_file=self.font_file())
        except nsui.NSUIError as e:
            self.c_banner.create_text(CW // 2, CH // 2, width=340, justify="center", fill=BAD, text=str(e))
            return
        except Exception as e:                                   # a preview must never crash the app
            self.c_banner.create_text(CW // 2, CH // 2, width=340, justify="center", fill=BAD,
                                      text=f"Couldn't draw this banner's preview ({type(e).__name__}).")
            return
        self._photos["nsui"] = ImageTk.PhotoImage(img)
        self.c_banner.create_image(CW // 2, CH // 2, image=self._photos["nsui"])

    def refresh_preview(self):
        self._preview_job = None
        self._refresh_swatches()
        system = self.system_choice()
        if not system:
            self.c_banner.delete("all")
            self.c_icon.delete("all")
            self.c_banner.create_text(CW // 2, CH // 2, width=340, justify="center", fill=MUTED, font=("Segoe UI", 11),
                                      text="The preview appears here once you choose a console in step 1.")
            return
        title = self.v_title.get() or "Game title"
        nsui_on = self.nsui_mode()
        banner_file = self.v_banner_file.get().strip() if nsui_on else ""
        icon_file = self.v_icon_file.get().strip() if nsui_on else ""
        try:
            self.c_banner.delete("all")
            nl = chr(10)
            if nsui_on and not banner_file:
                self.c_banner.create_text(CW // 2, CH // 2, width=320, justify="center", fill=MUTED,
                                          text="Choose the banner file you exported from NSUI to see it here.")
            elif banner_file and not Path(banner_file).is_file():
                self.c_banner.create_text(CW // 2, CH // 2, width=340, justify="center", fill=BAD,
                                          text="Banner file not found:" + nl + banner_file)
            elif banner_file and not is_picture(banner_file):
                self._draw_nsui_preview(banner_file, title)
            else:
                if banner_file:
                    img = bn.draw_custom_banner(banner_file).convert("RGBA")
                else:
                    img = bn.draw_vc_banner(self.image, title, self.v_year.get().strip(), system,
                                            bn.parse_color(self.v_color.get()), self.font_file())
                bg = Image.new("RGBA", img.size, (223, 229, 236, 255))
                bg.alpha_composite(img)
                self._photos["banner"] = ImageTk.PhotoImage(bg.resize((CW, CH), Image.LANCZOS))
                self.c_banner.create_image(CW // 2, CH // 2, image=self._photos["banner"])

            icon = None
            if icon_file and is_picture(icon_file):
                icon = bn.fit_image(icon_file, (48, 48), self.v_fit.get())
            elif icon_file:
                try:
                    icon = bn.read_smdh_icon(icon_file)
                except (OSError, ValueError):
                    icon = None
            if icon is None:
                if self.image:
                    icon = bn.fit_image(self.image, (48, 48), self.v_fit.get())
                else:
                    icon = bn._gradient((48, 48), *bn.frame_colors(self.effective_color()))
            self._photos["icon"] = ImageTk.PhotoImage(icon.resize((96, 96), Image.NEAREST))
            self.c_icon.delete("all")
            self.c_icon.create_image(48, 48, image=self._photos["icon"])
        except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as e:
            self.l_status.config(text=f"Couldn't read the image: {e}", foreground=BAD)

    # ---------------------------------------------------------------- export
    def export(self):
        if self.busy or not self.ready:
            return
        opt = BuildOptions(
            game=Path(self.v_game.get().strip()),
            bios=Path(self.v_bios.get()) if self.v_bios.get().strip() else None,
            title=self.v_title.get(), publisher=self.v_pub.get(), year=self.v_year.get(),
            system=self.system_choice(), out_dir=Path(self.v_out.get()) if self.v_out.get().strip() else None,
            image=self.image, icon_fit=self.v_fit.get(),
            icon_file=Path(self.v_icon_file.get()) if self.nsui_mode() and self.v_icon_file.get().strip() else None,
            banner_file=Path(self.v_banner_file.get()) if self.nsui_mode() and self.v_banner_file.get().strip() else None,
            frame_color=bn.parse_color(self.v_color.get()),
            sound_file=Path(self.v_sound.get()) if self.v_sound.get().strip() else None,
            plate_font=self.font_file())
        self.settings.update(bios=self.v_bios.get(), out=self.v_out.get())
        self._save_settings()
        self.busy = True
        self.pb["value"] = 0
        self._update_export()
        threading.Thread(target=self._run_build, args=(opt,), daemon=True).start()

    def _run_build(self, opt):
        try:
            cia = build(opt, lambda f, m: self.q.put(("progress", f, m)))
            self.q.put(("done", cia, opt.info))
        except (BuildError, OSError, RuntimeError) as e:
            self.q.put(("error", str(e)))
        except Exception as e:                                   # never leave the window stuck on "working"
            self.q.put(("error", f"Something unexpected went wrong ({type(e).__name__}: {e}). Nothing was changed "
                                 "except the temporary files, which are removed."))

    def _poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                if item[0] == "check":
                    if item[1] == self._check_seq:
                        self._show_check(item[2])
                elif item[0] == "progress":
                    self.pb["value"] = int(item[1] * 1000)
                    self.l_status.config(text=item[2], foreground=MUTED)
                elif item[0] == "done":
                    self.busy = False
                    self._update_export()
                    cia, info = item[1], item[2]
                    self.l_status.config(text=f"✓ Saved {cia}", foreground=OK)
                    if messagebox.askyesno(APP_NAME, f"{info['title']} is ready:\n{cia}\n\n"
                                                     "Copy it to your 3DS's SD card, then open FBI, choose SD, "
                                                     "find the file and install it. Please don't share it: it "
                                                     "contains the game and the BIOS.\n\n"
                                                     "Show the file now?"):
                        if os.name == "nt":                      # the full path, so nothing else called explorer can run
                            explorer = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "explorer.exe")
                            subprocess.Popen([explorer, "/select,", str(cia)])
                elif item[0] == "error":
                    self.busy = False
                    self.pb["value"] = 0
                    self._update_export()
                    self.l_status.config(text="The CIA couldn't be made. See the message for why.", foreground=BAD)
                    messagebox.showerror(APP_NAME, item[1])
        except queue.Empty:
            pass
        self.after(100, self._poll)

    # ---------------------------------------------------------------- settings
    def _load_settings(self):
        """The saved preferences, or {} if the file is missing or isn't what this app wrote (only plain text values
        are kept, so a damaged or edited file can't cause odd behaviour)."""
        try:
            data = json.loads(SETTINGS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str) and len(v) < 2000}

    def _save_settings(self):
        try:
            SETTINGS.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        except OSError:
            pass


def enable_dpi_awareness():
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass


def main():
    enable_dpi_awareness()
    App().mainloop()
