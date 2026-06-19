import os
import re
import sys
import struct
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox


ENCODING_INFO = {
    "Signed 8-bit PCM"  : (1,  8,  1),
    "Signed 16-bit PCM" : (1, 16,  2),
    "Signed 24-bit PCM" : (1, 24,  3),
    "Signed 32-bit PCM" : (1, 32,  4),
    "Unsigned 8-bit PCM": (1,  8,  1),
    "32-bit float"      : (3, 32,  4),
    "64-bit float"      : (3, 64,  8),
}

ENCODINGS       = list(ENCODING_INFO.keys())
BYTE_ORDERS     = ["Default endianness", "Little-endian", "Big-endian"]
CHANNEL_OPTIONS = ["2 Channels (Stereo)", "1 Channel (Mono)"]
SAMPLE_RATES    = ["8000","11025","16000","22050","32000","44100","48000","96000","192000"]

STRUCTURE_MODES = [
    "Multi-segment (Silence/tag alternating)",
    "Single label per track",
]

MIDDLE_TAGS = [
    "— No renaming (already named) —",
    "Aug_Barge_Podcast",
    "Aug_Barge_Music",
    "Aug_Babble",
    "Aug_Bus",
    "Aug_Metro",
    "Aug_Studio",
    "Aug_Windy_Bicycle",
    "Aug_Windy_Metro",
    "Cafeteria_Babble",
    "Cafeteria_Babble_Podcast",
    "Cafeteria_Babble_Music",
    "Indoor_Podcast",
    "Indoor_Music",
    "Street_Normal",
    "Studio_Normal",
]

BG  = "#1e1e2e"
FG  = "#cdd6f4"
ACC = "#89b4fa"
EB  = "#313244"


def natural_sort_key(path: str):
    """
    Sort key that treats embedded digit runs as numbers, not characters.
    Fixes the classic "_10 sorts before _2" alphabetical-sort bug for
    filenames like NonSpeech_..._1.pcm, ..._2.pcm, ..._10.pcm.
    """
    name = os.path.basename(path)
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r'(\d+)', name)]


# ── Audio helpers ──────────────────────────────────────────────────────────────

def _wav_header(num_channels, sample_rate, bits_per_sample, audio_format, data_size):
    byte_rate   = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_size, b"WAVE",
        b"fmt ", 16,
        audio_format, num_channels, sample_rate,
        byte_rate, block_align, bits_per_sample,
        b"data", data_size,
    )

def write_mono_wav(path, pcm_bytes, sample_rate, bits_per_sample, audio_format):
    header = _wav_header(1, sample_rate, bits_per_sample, audio_format, len(pcm_bytes))
    with open(path, "wb") as f:
        f.write(header)
        f.write(pcm_bytes)

def split_stereo_pcm(raw, bps):
    left, right = bytearray(), bytearray()
    i = 0
    while i + bps * 2 <= len(raw):
        left  += raw[i      : i + bps]
        right += raw[i + bps: i + bps * 2]
        i += bps * 2
    return bytes(left), bytes(right)


# ── Macro builder ──────────────────────────────────────────────────────────────

def db_to_ratio(db: float) -> float:
    """Convert a dB amplification value to Audacity's linear Ratio parameter."""
    return 10 ** (db / 20)


def build_macro(file_groups, amplify_db: float = 40.1):
    ratio = db_to_ratio(amplify_db)
    lines = []
    for name, wav_paths in file_groups:
        lines.append(f'Import2: Filename="{wav_paths[0].replace(chr(92), "/")}"')
        # Explicitly select the full length of the just-imported track before
        # amplifying — without this, Amplify reuses whatever selection range
        # was active from the very first import, amplifying only that same
        # stretch of time on every subsequent track instead of each track's
        # own full duration.
        lines.append("SelTrackStartToEnd:")
        lines.append(f"Amplify: Ratio={ratio:.6f} AllowClipping=1")
        if len(wav_paths) > 1:
            lines.append(f'Import2: Filename="{wav_paths[1].replace(chr(92), "/")}"')
        lines.append("NewLabelTrack:")
        lines.append(f'SetTrackStatus: Name="{name}"')
    lines.append("MuteAllTracks:")
    return "\n".join(lines)


# ── Label splitter ─────────────────────────────────────────────────────────────

def split_labels(combined_txt_path: str, pcm_folder: str, single_label_mode: bool = False) -> list[str]:
    """
    Parse Audacity combined label export into per-track blocks.

    Multi-segment mode (single_label_mode=False):
      Handles blank-line separator, backslash separator, or no separator
      (detected by start time resetting to 0.0). Each block can contain
      multiple label lines (the traditional Silence/tag alternating format).

    Single-label mode (single_label_mode=True):
      Each track has exactly ONE label line. Tracks are still separated
      by a blank line or backslash if present; if there is no separator
      at all, each line IS its own block (one label = one track).
    """
    with open(combined_txt_path, "r", encoding="utf-8") as f:
        raw = f.read()

    raw = raw.replace("\r\n", "\n").replace("\r", "\n")

    if single_label_mode:
        blocks: list[list[str]] = []
        current: list[str] = []

        for line in raw.splitlines():
            stripped = line.strip()
            if stripped == "" or stripped == "\\":
                if current:
                    blocks.append(current)
                    current = []
                continue

            parts = stripped.split("\t")
            try:
                float(parts[0])
            except (ValueError, IndexError):
                continue

            # In single-label mode, every data line is its own track
            # (no separator needed between single-label tracks)
            current.append(stripped)
            blocks.append(current)
            current = []

        if current:
            blocks.append(current)

        return ["\n".join(b) for b in blocks if b]

    # ── Multi-segment mode (original logic) ──
    blocks: list[list[str]] = []
    current: list[str] = []
    last_start = -1.0

    for line in raw.splitlines():
        stripped = line.strip()
        if stripped == "" or stripped == "\\":
            if current:
                blocks.append(current)
                current = []
            last_start = -1.0
            continue
        parts = stripped.split("\t")
        try:
            start = float(parts[0])
        except (ValueError, IndexError):
            continue
        if start <= 0.0 and current:
            blocks.append(current)
            current = []
            last_start = -1.0
        current.append(stripped)
        last_start = start

    if current:
        blocks.append(current)

    return ["\n".join(b) for b in blocks if b]


# All known valid tag names (named tags are kept as-is)
KNOWN_TAGS = {
    "Silence", "Aug_Barge_Podcast", "Aug_Barge_Music", "Aug_Babble",
    "Aug_Bus", "Aug_Metro", "Aug_Windy_Bicycle", "Aug_Windy_Metro",
    "Cafeteria_Babble", "Street_Normal", "Studio_Normal",
}

def rename_numeric_tags(block: str, middle_tag: str) -> tuple[str, list[str]]:
    """
    Process each line individually:
      - Tag is already a known name        → keep as-is
      - Tag is a number                    → rename by position
      - Tag is empty/unnamed (no 3rd field,
        or an empty 3rd field)             → rename by position
            (both numeric and unnamed tags use the same positional rule:
             index 0 or last → Silence, odd middle → middle_tag,
             even middle → Silence)
      - Tag is any other unrecognized text → keep as-is, record a warning

    Returns (renamed_block, warnings_list).
    """
    lines = [l for l in block.splitlines() if l.strip()]
    parsed = []
    for line in lines:
        parts = line.split("\t")
        if len(parts) >= 2:
            parsed.append(parts)

    if not parsed:
        return block, []

    last_idx = len(parsed) - 1
    result   = []
    warnings = []

    for idx, parts in enumerate(parsed):
        start, end = parts[0], parts[1]
        raw_tag = parts[2].strip() if len(parts) >= 3 else ""

        if raw_tag == "" or raw_tag.lstrip("-").isdigit():
            # Numeric OR completely unnamed — rename by position
            if idx == 0 or idx == last_idx:
                tag = "Silence"
            elif idx % 2 == 1:
                tag = middle_tag
            else:
                tag = "Silence"
        else:
            # Any deliberately typed name (known or custom) — keep as-is
            tag = raw_tag

        result.append(f"{start}\t{end}\t{tag}")

    return "\n".join(result), warnings


def rename_single_label(block: str, middle_tag: str | None, pcm_name: str) -> tuple[str, list[str]]:
    """
    Single-label mode: block contains exactly one label line.
      - If the tag is empty/unnamed (including lines with no third field
        at all, e.g. Audacity exports "start\\tend" with no trailing tab
        when a label has no name) OR purely numeric (1, 2, 3…):
            use middle_tag if one is selected, otherwise fall back to pcm_name
      - If the tag is any other deliberately typed text → keep as-is
    Returns (renamed_block, warnings_list).
    """
    lines = [l for l in block.splitlines() if l.strip()]
    if not lines:
        return block, []

    parts = lines[0].split("\t")
    if len(parts) < 2:
        return block, []

    start, end = parts[0], parts[1]
    raw_tag = parts[2].strip() if len(parts) >= 3 else ""
    warnings = []

    if raw_tag == "" or raw_tag.lstrip("-").isdigit():
        tag = middle_tag if middle_tag else pcm_name
    else:
        tag = raw_tag

    new_line = f"{start}\t{end}\t{tag}"
    return new_line, warnings


def export_labels(combined_txt_path, pcm_files, out_dir, log_fn,
                  middle_tag=None, single_label_mode=False):
    """
    Split combined label export into individual .txt files with optional
    tag renaming. Dispatches to multi-segment or single-label logic based
    on single_label_mode.
    """
    try:
        blocks = split_labels(combined_txt_path, os.path.dirname(combined_txt_path),
                              single_label_mode=single_label_mode)
    except Exception as e:
        log_fn(f"  ✗  Could not read label file: {e}", "err")
        return False

    if not blocks:
        log_fn("  ✗  No label tracks found in the file.", "err")
        return False

    pcm_names = [os.path.splitext(os.path.basename(p))[0] for p in pcm_files]

    if len(blocks) != len(pcm_names):
        log_fn(
            f"  ⚠  Found {len(blocks)} label track(s) but {len(pcm_names)} PCM file(s).\n"
            f"     Matched in order; extras named label_track_N.", "warn",
        )

    os.makedirs(out_dir, exist_ok=True)
    ok_count = 0

    for i, block in enumerate(blocks):
        name = pcm_names[i] if i < len(pcm_names) else f"label_track_{i+1}"

        warnings = []
        if single_label_mode:
            block, warnings = rename_single_label(block, middle_tag, name)
        elif middle_tag:
            block, warnings = rename_numeric_tags(block, middle_tag)

        out_path = os.path.join(out_dir, name + ".txt")
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(block + "\n")
            lc = len([l for l in block.splitlines() if l.strip()])
            log_fn(f"  ✓  {name}.txt  ({lc} label(s))", "ok")
            for w in warnings:
                log_fn(f"  ⚠  {w}", "warn")
            ok_count += 1
        except Exception as e:
            log_fn(f"  ✗  {name}.txt: {e}", "err")

    return ok_count > 0


# ── Duration checker ───────────────────────────────────────────────────────────

def parse_label_file(path: str) -> list[tuple[float, float, str]]:
    """Read a label .txt and return list of (start, end, tag)."""
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) >= 3:
                try:
                    entries.append((float(parts[0]), float(parts[1]), parts[2].strip()))
                except ValueError:
                    continue
    return entries


def compute_durations(entries: list[tuple[float, float, str]]) -> list[tuple[str, float]]:
    """Return list of (tag, duration_seconds) for each entry."""
    return [(tag, end - start) for start, end, tag in entries]


def run_duration_check(exported_labels_dir: str, output_base_dir: str, log_fn,
                       single_label_mode: bool = False) -> bool:
    """
    Process all .txt files in exported_labels_dir and write output folders.

    Multi-segment mode: writes Duration Individual, Duration Compiled,
      and Duration Middle (sum of all tags except first and last).

    Single-label mode: writes only Duration Individual and Duration Compiled.
      Each file has exactly one label; its duration is simply end - start
      of that single label (not the full track), so the "middle" concept
      does not apply and that folder is skipped.
    """
    txt_files = sorted([
        f for f in os.listdir(exported_labels_dir)
        if f.lower().endswith(".txt")
    ], key=natural_sort_key)

    if not txt_files:
        log_fn("  ✗  No .txt files found in Exported Labels folder.", "err")
        return False

    dir_individual = os.path.join(output_base_dir, "Duration Individual")
    dir_compiled   = os.path.join(output_base_dir, "Duration Compiled")
    os.makedirs(dir_individual, exist_ok=True)
    os.makedirs(dir_compiled, exist_ok=True)

    if not single_label_mode:
        dir_middle = os.path.join(output_base_dir, "Duration Middle")
        os.makedirs(dir_middle, exist_ok=True)
        middle_lines = []

    compiled_lines = []

    for fname in txt_files:
        fpath    = os.path.join(exported_labels_dir, fname)
        basename = os.path.splitext(fname)[0]

        try:
            entries   = parse_label_file(fpath)
            durations = compute_durations(entries)
        except Exception as e:
            log_fn(f"  ✗  {fname}: {e}", "err")
            continue

        if not durations:
            log_fn(f"  ⚠  {fname}: no valid entries, skipped.", "warn")
            continue

        if single_label_mode and len(durations) > 1:
            log_fn(
                f"  ⚠  {fname}: found {len(durations)} labels, expected 1 "
                f"for single-label mode — using all of them anyway.", "warn",
            )

        # ── Individual — tag\tduration per line ──
        indiv_lines = [f"{tag}\t{dur:.6f}" for tag, dur in durations]
        indiv_path  = os.path.join(dir_individual, basename + ".txt")
        with open(indiv_path, "w", encoding="utf-8") as f:
            f.write("\n".join(indiv_lines) + "\n")

        # ── Compiled — accumulated into one big file ──
        compiled_lines.append(basename)
        compiled_lines.extend(indiv_lines)
        compiled_lines.append("")
        compiled_lines.append("")

        if single_label_mode:
            total_dur = sum(d for _, d in durations)
            log_fn(f"  ✓  {basename}  (label duration={total_dur:.3f}s)", "ok")
        else:
            # ── Middle — sum of all tags except first and last ──
            if len(durations) <= 2:
                middle_dur = 0.0
            else:
                middle_dur = sum(d for _, d in durations[1:-1])
            middle_lines.append(f"{basename}\t{middle_dur:.6f}")
            log_fn(f"  ✓  {basename}  ({len(durations)} tag(s), middle={middle_dur:.3f}s)", "ok")

    # Write compiled file
    compiled_path = os.path.join(dir_compiled, "All_Durations.txt")
    with open(compiled_path, "w", encoding="utf-8") as f:
        f.write("\n".join(compiled_lines).rstrip() + "\n")

    log_fn(f"\n  Individual files  →  Duration Individual\\", "warn")
    log_fn(f"  Compiled file     →  Duration Compiled\\All_Durations.txt", "warn")

    if not single_label_mode:
        middle_path = os.path.join(dir_middle, "Middle_Durations.txt")
        with open(middle_path, "w", encoding="utf-8") as f:
            f.write("\n".join(middle_lines) + "\n")
        log_fn(f"  Middle file       →  Duration Middle\\Middle_Durations.txt", "warn")

    return True


# ── CSV generator ──────────────────────────────────────────────────────────────

def convert_label_txt_to_csv(txt_path: str) -> tuple[bool, int, str]:
    """
    Convert a single label .txt (tab-separated: start, end, tag) into a
    .csv with header "Start point,End point,Category" saved alongside it
    with the same base name.

    Auto-detects format purely by line count:
      - 1 valid data line  → new single-label format
      - 3, 5, 7… lines     → traditional multi-segment format
    Both are written identically (the conversion is the same either way —
    only the line count differs), so no branching is actually needed beyond
    reading whatever lines are present.

    Returns (success, line_count, message).
    """
    try:
        with open(txt_path, "r", encoding="utf-8") as f:
            raw = f.read()
    except Exception as e:
        return False, 0, f"could not read file: {e}"

    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    rows = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split("\t")
        if len(parts) < 3:
            continue
        try:
            start = float(parts[0])
            end   = float(parts[1])
        except ValueError:
            continue
        tag = parts[2].strip()
        rows.append((start, end, tag))

    if not rows:
        return False, 0, "no valid label rows found"

    csv_path = os.path.splitext(txt_path)[0] + ".csv"
    try:
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            f.write("Start point,End point,Category\n")
            for start, end, tag in rows:
                f.write(f"{start:.6f},{end:.6f},{tag}\n")
    except Exception as e:
        return False, len(rows), f"could not write csv: {e}"

    return True, len(rows), csv_path


def run_csv_generator(labels_dir: str, log_fn) -> bool:
    """
    Convert every .txt file in labels_dir into a matching .csv saved in
    the same folder. Auto-detects single-label vs multi-segment per file
    purely by how many valid rows it contains — no mode flag needed.
    """
    txt_files = sorted([
        f for f in os.listdir(labels_dir) if f.lower().endswith(".txt")
    ], key=natural_sort_key)

    if not txt_files:
        log_fn("  ✗  No .txt files found in the selected folder.", "err")
        return False

    ok_count = 0

    for fname in txt_files:
        fpath = os.path.join(labels_dir, fname)
        ok, line_count, result = convert_label_txt_to_csv(fpath)

        if ok:
            fmt = "single-label" if line_count == 1 else f"multi-segment, {line_count} rows"
            log_fn(f"  ✓  {fname}  →  {os.path.basename(result)}  ({fmt})", "ok")
            ok_count += 1
        else:
            log_fn(f"  ✗  {fname}: {result}", "err")

    return ok_count > 0


# ── OS paths ───────────────────────────────────────────────────────────────────

def get_macro_dir():
    if sys.platform == "win32":
        return os.path.join(os.environ.get("APPDATA", ""), "Audacity", "Macros")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/audacity/Macros")
    return os.path.expanduser("~/.audacity-data/Macros")

def get_desktop():
    if sys.platform == "win32":
        return os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Desktop")
    return os.path.expanduser("~/Desktop")


# ── Combobox colour fix ────────────────────────────────────────────────────────

def _style_comboboxes(root):
    def _walk(widget):
        for child in widget.winfo_children():
            if isinstance(child, ttk.Combobox):
                try:
                    entry_path = str(child) + ".entry"
                    child.tk.eval(
                        f'catch {{.{entry_path} configure '
                        f'-background {EB} -foreground {FG} '
                        f'-selectbackground {EB} -selectforeground {FG}}}'
                    )
                    child.configure(style="Dark.TCombobox")
                except Exception:
                    pass
            _walk(child)
    _walk(root)


# ── Shared log helpers ─────────────────────────────────────────────────────────

def make_log(parent) -> scrolledtext.ScrolledText:
    log = scrolledtext.ScrolledText(
        parent, height=12, font=("Consolas", 9),
        bg="#181825", fg=FG, insertbackground=FG,
        state=tk.DISABLED, bd=0, relief=tk.FLAT,
    )
    for tag, color, bold in [
        ("ok",   "#a6e3a1", False),
        ("warn", "#f9e2af", False),
        ("err",  "#f38ba8", False),
        ("head", "#89b4fa", True ),
        ("step", "#cba6f7", False),
    ]:
        log.tag_config(tag, foreground=color,
                       font=("Consolas", 9, "bold") if bold else ("Consolas", 9))
    return log

def log_write(log, msg, tag=""):
    log.config(state=tk.NORMAL)
    log.insert(tk.END, msg + "\n", tag)
    log.see(tk.END)
    log.config(state=tk.DISABLED)

def log_clear(log):
    log.config(state=tk.NORMAL)
    log.delete("1.0", tk.END)
    log.config(state=tk.DISABLED)


# ── Tab 1: PCM Importer ────────────────────────────────────────────────────────

class ImporterTab(ttk.Frame):
    def __init__(self, parent, make_combo_fn):
        super().__init__(parent)
        self.files: list[str] = []
        self._make_combo = make_combo_fn
        self._build()

    def _build(self):
        pad = dict(padx=10, pady=5)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        ff = ttk.LabelFrame(self, text="  PCM Files  ")
        ff.grid(row=0, column=0, columnspan=2, sticky="nsew", **pad)
        self.grid_rowconfigure(0, weight=1)

        bc = tk.Frame(ff, bg=BG)
        bc.pack(side=tk.LEFT, fill=tk.Y, padx=(6, 4), pady=6)
        for txt, cmd in [
            ("Add Files…",  self._add_files),
            ("↑ Move Up",   self._move_up),
            ("↓ Move Down", self._move_down),
            ("Remove",      self._remove_files),
            ("Clear All",   self._clear_files),
        ]:
            ttk.Button(bc, text=txt, command=cmd, width=13).pack(pady=2)

        lf = tk.Frame(ff, bg=BG)
        lf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6), pady=6)

        self.file_listbox = tk.Listbox(
            lf, width=55, height=7, selectmode=tk.EXTENDED,
            bg=EB, fg=FG, selectbackground=ACC, selectforeground=BG,
            font=("Consolas", 9), bd=0, relief=tk.FLAT,
        )
        self.file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = tk.Scrollbar(lf, orient=tk.VERTICAL, command=self.file_listbox.yview)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        self.file_listbox.config(yscrollcommand=sb.set)


        sf = ttk.LabelFrame(self, text="  Import Settings  ")
        sf.grid(row=1, column=0, columnspan=2, sticky="ew", **pad)

        self.encoding_var    = tk.StringVar(value="Signed 16-bit PCM")
        self.byteorder_var   = tk.StringVar(value="Default endianness")
        self.channels_var    = tk.StringVar(value="2 Channels (Stereo)")
        self.offset_var      = tk.StringVar(value="0")
        self.amount_var      = tk.StringVar(value="100")
        self.sample_rate_var = tk.StringVar(value="16000")

        self._make_combo(sf, 0, "Encoding:",       self.encoding_var,   ENCODINGS)
        self._make_combo(sf, 1, "Byte order:",     self.byteorder_var,  BYTE_ORDERS)
        self._make_combo(sf, 2, "Channels:",       self.channels_var,   CHANNEL_OPTIONS)

        ttk.Label(sf, text="Start offset:").grid(row=3, column=0, sticky="w", **pad)
        of = tk.Frame(sf, bg=BG)
        of.grid(row=3, column=1, sticky="w", **pad)
        tk.Entry(of, textvariable=self.offset_var, width=10,
                 bg=EB, fg=FG, insertbackground=FG, relief=tk.FLAT,
                 font=("Segoe UI", 9)).pack(side=tk.LEFT)
        ttk.Label(of, text=" bytes").pack(side=tk.LEFT)

        ttk.Label(sf, text="Amount to import:").grid(row=4, column=0, sticky="w", **pad)
        af = tk.Frame(sf, bg=BG)
        af.grid(row=4, column=1, sticky="w", **pad)
        tk.Entry(af, textvariable=self.amount_var, width=10,
                 bg=EB, fg=FG, insertbackground=FG, relief=tk.FLAT,
                 font=("Segoe UI", 9)).pack(side=tk.LEFT)
        ttk.Label(af, text=" %").pack(side=tk.LEFT)

        self._make_combo(sf, 5, "Sample rate:", self.sample_rate_var, SAMPLE_RATES,
                         readonly=False, width=14)

        ttk.Label(sf, text="Amplification (dB):").grid(row=6, column=0, sticky="w", **pad)
        amp_f = tk.Frame(sf, bg=BG)
        amp_f.grid(row=6, column=1, sticky="w", **pad)
        self.amplify_db_var = tk.StringVar(value="40.1")
        amp_entry = tk.Entry(amp_f, textvariable=self.amplify_db_var, width=10,
                             bg=EB, fg=FG, insertbackground=FG, relief=tk.FLAT,
                             font=("Segoe UI", 9))
        amp_entry.pack(side=tk.LEFT)
        ttk.Label(amp_f, text=" dB").pack(side=tk.LEFT)
        amp_entry.bind("<KeyRelease>", lambda e: self._update_amp_banner())

        self.amp_banner = tk.Label(
            self,
            text="⚡  Left channel (Track 1) per file → Amplify +40.1 dB  |  Allow Clipping ✓",
            bg="#1e3a1e", fg="#a6e3a1", font=("Segoe UI", 9, "bold"), pady=6,
        )
        self.amp_banner.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=4)

        tk.Button(
            self, text="▶  Convert PCMs & Generate Audacity Macro",
            command=self._run,
            bg=ACC, fg=BG, font=("Segoe UI", 10, "bold"),
            relief=tk.FLAT, padx=12, pady=8, cursor="hand2",
            activebackground="#74c7ec", activeforeground=BG,
        ).grid(row=3, column=0, columnspan=2, padx=10, pady=6, sticky="ew")

        olf = ttk.LabelFrame(self, text="  Output / Instructions  ")
        olf.grid(row=4, column=0, columnspan=2, sticky="nsew", **pad)
        self.grid_rowconfigure(4, weight=1)
        self.log = make_log(olf)
        self.log.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

    def _log(self, msg, tag=""): log_write(self.log, msg, tag)
    def _clear(self):            log_clear(self.log)

    def _update_amp_banner(self):
        val = self.amplify_db_var.get().strip()
        try:
            db = float(val)
            self.amp_banner.config(
                text=f"⚡  Left channel (Track 1) per file → Amplify +{db:g} dB  |  Allow Clipping ✓"
            )
        except ValueError:
            self.amp_banner.config(
                text="⚡  Left channel (Track 1) per file → Amplify (enter a valid dB value)  |  Allow Clipping ✓"
            )

    def _add_files(self):
        paths = filedialog.askopenfilenames(
            title="Select PCM files",
            filetypes=[("PCM files", "*.pcm"), ("All files", "*.*")],
        )
        for p in paths:
            if p not in self.files:
                self.files.append(p)
                self.file_listbox.insert(tk.END, os.path.basename(p))

    def _remove_files(self):
        for i in reversed(self.file_listbox.curselection()):
            self.file_listbox.delete(i)
            del self.files[i]

    def _clear_files(self):
        self.file_listbox.delete(0, tk.END)
        self.files.clear()

    def _move_up(self):
        sel = self.file_listbox.curselection()
        if not sel or sel[0] == 0: return
        i = sel[0]
        self.files[i-1], self.files[i] = self.files[i], self.files[i-1]
        txt = self.file_listbox.get(i)
        self.file_listbox.delete(i); self.file_listbox.insert(i-1, txt)
        self.file_listbox.selection_set(i-1)

    def _move_down(self):
        sel = self.file_listbox.curselection()
        if not sel or sel[0] >= self.file_listbox.size()-1: return
        i = sel[0]
        self.files[i], self.files[i+1] = self.files[i+1], self.files[i]
        txt = self.file_listbox.get(i)
        self.file_listbox.delete(i); self.file_listbox.insert(i+1, txt)
        self.file_listbox.selection_set(i+1)

    def _run(self):
        self._clear()
        if not self.files:
            messagebox.showwarning("No files", "Add at least one .pcm file first.")
            return
        try:
            sample_rate = int(self.sample_rate_var.get().split()[0])
        except ValueError:
            messagebox.showerror("Invalid", "Sample rate must be a whole number.")
            return

        try:
            amplify_db = float(self.amplify_db_var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid", "Amplification (dB) must be a number.")
            return

        num_channels = int(self.channels_var.get().split()[0])
        encoding     = self.encoding_var.get()
        audio_fmt, bps, bytes_ps = ENCODING_INFO[encoding]

        self._log("Step 1 — Converting PCM → WAV…", "head")
        file_groups = []

        for pcm_path in self.files:
            name    = os.path.splitext(os.path.basename(pcm_path))[0]
            out_dir = os.path.join(os.path.dirname(pcm_path), "Converted Files")
            os.makedirs(out_dir, exist_ok=True)
            try:
                with open(pcm_path, "rb") as f:
                    raw = f.read()
                if num_channels == 2:
                    left_raw, right_raw = split_stereo_pcm(raw, bytes_ps)
                    lp = os.path.join(out_dir, name + "_L.wav")
                    rp = os.path.join(out_dir, name + "_R.wav")
                    write_mono_wav(lp, left_raw,  sample_rate, bps, audio_fmt)
                    write_mono_wav(rp, right_raw, sample_rate, bps, audio_fmt)
                    file_groups.append((name, [lp, rp]))
                    self._log(f"  ✓  {name}.pcm  →  {name}_L.wav  +  {name}_R.wav", "ok")
                else:
                    wp = os.path.join(out_dir, name + "_mono.wav")
                    write_mono_wav(wp, raw, sample_rate, bps, audio_fmt)
                    file_groups.append((name, [wp]))
                    self._log(f"  ✓  {name}.pcm  →  {name}_mono.wav", "ok")
            except Exception as e:
                self._log(f"  ✗  {name}: {e}", "err")

        if not file_groups:
            self._log("No files converted — cannot continue.", "err")
            return

        self._log(f"  Saved to:  [source folder]\\Converted Files\\", "warn")
        self._log("\nStep 2 — Building Audacity macro…", "head")
        macro_text = build_macro(file_groups, amplify_db=amplify_db)
        macro_name = "PCM_Importer"
        macro_dir  = get_macro_dir()
        auto_ok    = False

        if os.path.isdir(macro_dir):
            try:
                saved_path = os.path.join(macro_dir, f"{macro_name}.txt")
                with open(saved_path, "w", encoding="utf-8") as f:
                    f.write(macro_text)
                auto_ok = True
                self._log(f"  ✓  Macro installed to Audacity Macros folder:", "ok")
                self._log(f"     {saved_path}", "ok")
            except Exception as e:
                self._log(f"  Could not write to Audacity folder ({e}); saving to Desktop.", "warn")

        if not auto_ok:
            saved_path = os.path.join(get_desktop(), f"{macro_name}.txt")
            try:
                with open(saved_path, "w", encoding="utf-8") as f:
                    f.write(macro_text)
                self._log(f"  ✓  Macro saved to Desktop: {saved_path}", "ok")
            except Exception as e:
                self._log(f"  ✗  Could not save macro: {e}", "err")
                return

        self._log("\nExpected track order in Audacity:", "head")
        for name, wav_paths in file_groups:
            self._log(f"  {name}  ← +{amplify_db:g} dB, Allow Clipping ✓", "ok")
            if len(wav_paths) > 1:
                self._log(f"  {name}", "")
            self._log(f"  [Label track: {name}]", "warn")

        self._log("\n" + "─" * 58, "head")
        self._log("Step 3 — Run the macro in Audacity", "head")
        self._log("─" * 58, "head")

        if auto_ok:
            self._log(
                "\n"
                "  1. Open Audacity  (restart if already open)\n"
                "  2. Go to  Tools → Macros…\n"
                '  3. Select  "PCM_Importer"  in the list on the left\n'
                '  4. Click  "Apply to Project"\n'
                "  5. Done ✓\n", "step")
        else:
            self._log(
                "\n"
                "  1. Open Audacity\n"
                "  2. Go to  Tools → Macros…\n"
                '  3. Click  "Import…"  at the bottom of the macro list\n'
                "  4. Select  PCM_Importer.txt  from your Desktop\n"
                '  5. Select  "PCM_Importer"  in the list\n'
                '  6. Click  "Apply to Project"\n', "step")

        self._log("")


# ── Tab 2: Label Exporter ──────────────────────────────────────────────────────

class LabelExporterTab(ttk.Frame):
    def __init__(self, parent, make_combo_fn):
        super().__init__(parent)
        self.combined_txt_var = tk.StringVar()
        self.pcm_folder_var   = tk.StringVar()
        self.middle_tag_var   = tk.StringVar(value=MIDDLE_TAGS[0])
        self.structure_mode_var = tk.StringVar(value="Multi-segment (Silence/tag alternating)")
        self.pcm_files: list[str] = []
        self._make_combo = make_combo_fn
        self._build()

    def _build(self):
        pad = dict(padx=10, pady=6)
        self.grid_columnconfigure(0, weight=1)

        tk.Label(
            self,
            text=(
                "How to use this tab:\n"
                "  1. Finish labelling in Audacity\n"
                "  2. File → Export → Export Labels…  →  save anywhere as a .txt\n"
                "  3. Pick that exported .txt below\n"
                "  4. Pick the folder where your original .pcm files are\n"
                "  5. Select the middle tag if your labels are numbered\n"
                "  6. Click Export"
            ),
            bg="#1a1a2e", fg="#a6adc8", font=("Segoe UI", 9),
            justify=tk.LEFT, anchor="w", padx=12, pady=10,
        ).grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))

        # Label file picker
        lf1 = ttk.LabelFrame(self, text="  Audacity Exported Labels File (.txt)  ")
        lf1.grid(row=1, column=0, sticky="ew", **pad)
        lf1.grid_columnconfigure(0, weight=1)
        tk.Entry(lf1, textvariable=self.combined_txt_var,
                 bg=EB, fg=FG, insertbackground=FG, relief=tk.FLAT,
                 font=("Consolas", 9)).grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        ttk.Button(lf1, text="Browse…", command=self._pick_labels).grid(
            row=0, column=1, padx=(0, 8), pady=8)

        # PCM folder picker
        lf2 = ttk.LabelFrame(self, text="  PCM Source Folder  ")
        lf2.grid(row=2, column=0, sticky="ew", **pad)
        lf2.grid_columnconfigure(0, weight=1)
        tk.Entry(lf2, textvariable=self.pcm_folder_var,
                 bg=EB, fg=FG, insertbackground=FG, relief=tk.FLAT,
                 font=("Consolas", 9)).grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        ttk.Button(lf2, text="Browse…", command=self._pick_pcm_folder).grid(
            row=0, column=1, padx=(0, 8), pady=8)

        # Structure mode selector
        lf_mode = ttk.LabelFrame(self, text="  Label Structure  ")
        lf_mode.grid(row=3, column=0, sticky="ew", **pad)
        lf_mode.grid_columnconfigure(1, weight=1)
        self._make_combo(lf_mode, 0, "Structure type:", self.structure_mode_var, STRUCTURE_MODES, width=42)

        # Middle tag selector
        lf_tag = ttk.LabelFrame(self, text="  Middle / Replacement Tag  ")
        lf_tag.grid(row=4, column=0, sticky="ew", **pad)
        lf_tag.grid_columnconfigure(1, weight=1)
        self._make_combo(lf_tag, 0, "Middle tag:", self.middle_tag_var, MIDDLE_TAGS, width=30)

        # PCM file order list
        lf3 = ttk.LabelFrame(self, text="  PCM Files (must match label track order in Audacity)  ")
        lf3.grid(row=5, column=0, sticky="nsew", **pad)
        self.grid_rowconfigure(5, weight=1)

        bc = tk.Frame(lf3, bg=BG)
        bc.pack(side=tk.LEFT, fill=tk.Y, padx=(6, 4), pady=6)
        for txt, cmd in [
            ("Add Files…",   self._add_pcm),
            ("↑ Move Up",    self._move_up),
            ("↓ Move Down",  self._move_down),
            ("Remove",       self._remove_pcm),
            ("Clear All",    self._clear_pcm),
        ]:
            ttk.Button(bc, text=txt, command=cmd, width=13).pack(pady=2)

        list_frame = tk.Frame(lf3, bg=BG)
        list_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6), pady=6)

        self.pcm_listbox = tk.Listbox(
            list_frame, width=50, height=5, selectmode=tk.EXTENDED,
            bg=EB, fg=FG, selectbackground=ACC, selectforeground=BG,
            font=("Consolas", 9), bd=0, relief=tk.FLAT,
        )
        self.pcm_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = tk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.pcm_listbox.yview)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        self.pcm_listbox.config(yscrollcommand=sb.set)

        tk.Button(
            self, text="▶  Export Labels as Individual .txt Files",
            command=self._run,
            bg="#cba6f7", fg=BG, font=("Segoe UI", 10, "bold"),
            relief=tk.FLAT, padx=12, pady=8, cursor="hand2",
            activebackground="#b4a0e0", activeforeground=BG,
        ).grid(row=6, column=0, padx=10, pady=6, sticky="ew")

        olf = ttk.LabelFrame(self, text="  Output  ")
        olf.grid(row=7, column=0, sticky="nsew", **pad)
        self.grid_rowconfigure(7, weight=1)
        self.log = make_log(olf)
        self.log.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

    def _log(self, msg, tag=""): log_write(self.log, msg, tag)
    def _clear(self):            log_clear(self.log)

    def _pick_labels(self):
        p = filedialog.askopenfilename(
            title="Select Audacity exported labels file",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if p:
            self.combined_txt_var.set(p)

    def _pick_pcm_folder(self):
        d = filedialog.askdirectory(title="Select folder containing your .pcm files")
        if d:
            self.pcm_folder_var.set(d)
            pcm_found = sorted([
                os.path.join(d, f) for f in os.listdir(d)
                if f.lower().endswith(".pcm")
            ], key=natural_sort_key)
            if pcm_found:
                self.pcm_files.clear()
                self.pcm_listbox.delete(0, tk.END)
                for p in pcm_found:
                    self.pcm_files.append(p)
                    self.pcm_listbox.insert(tk.END, os.path.basename(p))

    def _add_pcm(self):
        paths = filedialog.askopenfilenames(
            title="Select PCM files (in label track order)",
            filetypes=[("PCM files", "*.pcm"), ("All files", "*.*")],
        )
        for p in paths:
            if p not in self.pcm_files:
                self.pcm_files.append(p)
                self.pcm_listbox.insert(tk.END, os.path.basename(p))

    def _remove_pcm(self):
        for i in reversed(self.pcm_listbox.curselection()):
            self.pcm_listbox.delete(i)
            del self.pcm_files[i]

    def _clear_pcm(self):
        self.pcm_listbox.delete(0, tk.END)
        self.pcm_files.clear()

    def _move_up(self):
        sel = self.pcm_listbox.curselection()
        if not sel or sel[0] == 0: return
        i = sel[0]
        self.pcm_files[i-1], self.pcm_files[i] = self.pcm_files[i], self.pcm_files[i-1]
        txt = self.pcm_listbox.get(i)
        self.pcm_listbox.delete(i); self.pcm_listbox.insert(i-1, txt)
        self.pcm_listbox.selection_set(i-1)

    def _move_down(self):
        sel = self.pcm_listbox.curselection()
        if not sel or sel[0] >= self.pcm_listbox.size()-1: return
        i = sel[0]
        self.pcm_files[i], self.pcm_files[i+1] = self.pcm_files[i+1], self.pcm_files[i]
        txt = self.pcm_listbox.get(i)
        self.pcm_listbox.delete(i); self.pcm_listbox.insert(i+1, txt)
        self.pcm_listbox.selection_set(i+1)

    def _run(self):
        self._clear()

        combined = self.combined_txt_var.get().strip()
        if not combined or not os.path.isfile(combined):
            messagebox.showwarning("Missing file", "Please select the Audacity exported labels .txt file.")
            return

        pcm_folder = self.pcm_folder_var.get().strip()
        if not pcm_folder or not os.path.isdir(pcm_folder):
            messagebox.showwarning("Missing folder", "Please select the PCM source folder.")
            return

        if not self.pcm_files:
            messagebox.showwarning("No PCM files", "Please add PCM files in the order they appear as label tracks in Audacity.")
            return

        selected_tag = self.middle_tag_var.get()
        middle_tag   = None if selected_tag == MIDDLE_TAGS[0] else selected_tag
        single_mode  = self.structure_mode_var.get() == STRUCTURE_MODES[1]

        out_dir = os.path.join(pcm_folder, "Exported Labels")
        self._log("Splitting label tracks…", "head")
        self._log(f"  Structure:  {self.structure_mode_var.get()}", "warn")
        if middle_tag:
            self._log(f"  Middle/replacement tag:  {middle_tag}", "warn")
        self._log(f"  Output folder:  ...\\Exported Labels\\", "warn")
        self._log("")

        ok = export_labels(
            combined_txt_path=combined,
            pcm_files=self.pcm_files,
            out_dir=out_dir,
            log_fn=self._log,
            middle_tag=middle_tag,
            single_label_mode=single_mode,
        )

        if ok:
            self._log(f"\n✓  Done!  Files saved to:", "ok")
            self._log(f"   {out_dir}", "ok")
        else:
            self._log("\nExport failed — check errors above.", "err")

        self._log("")


# ── Tab 3: Duration Checker ────────────────────────────────────────────────────

class DurationCheckerTab(ttk.Frame):
    def __init__(self, parent, make_combo_fn):
        super().__init__(parent)
        self.labels_folder_var  = tk.StringVar()
        self.output_base_var    = tk.StringVar()
        self.structure_mode_var = tk.StringVar(value=STRUCTURE_MODES[0])
        self._make_combo = make_combo_fn
        self._build()

    def _build(self):
        pad = dict(padx=10, pady=6)
        self.grid_columnconfigure(0, weight=1)

        tk.Label(
            self,
            text=(
                "How to use this tab:\n"
                "  1. Run the Label Exporter tab first to generate individual label .txt files\n"
                "  2. Point to the  'Exported Labels'  folder below\n"
                "  3. Set the output base folder, choose the label structure, then click Run\n\n"
                "  Multi-segment mode creates:\n"
                "    Duration Individual\\  — one .txt per file:  tag  ⇥  seconds\n"
                "    Duration Compiled\\    — all files in one .txt with 2 blank lines between\n"
                "    Duration Middle\\      — one line per file:  filename  ⇥  middle tags total\n\n"
                "  Single-label mode creates only:\n"
                "    Duration Individual\\  and  Duration Compiled\\"
            ),
            bg="#1a1a2e", fg="#a6adc8", font=("Segoe UI", 9),
            justify=tk.LEFT, anchor="w", padx=12, pady=10,
        ).grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))

        # Exported Labels folder
        lf1 = ttk.LabelFrame(self, text="  Exported Labels Folder  ")
        lf1.grid(row=1, column=0, sticky="ew", **pad)
        lf1.grid_columnconfigure(0, weight=1)
        tk.Entry(lf1, textvariable=self.labels_folder_var,
                 bg=EB, fg=FG, insertbackground=FG, relief=tk.FLAT,
                 font=("Consolas", 9)).grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        ttk.Button(lf1, text="Browse…", command=self._pick_labels_folder).grid(
            row=0, column=1, padx=(0, 8), pady=8)

        # Output base folder
        lf2 = ttk.LabelFrame(self, text="  Output Base Folder (subfolders created here)  ")
        lf2.grid(row=2, column=0, sticky="ew", **pad)
        lf2.grid_columnconfigure(0, weight=1)
        tk.Entry(lf2, textvariable=self.output_base_var,
                 bg=EB, fg=FG, insertbackground=FG, relief=tk.FLAT,
                 font=("Consolas", 9)).grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        ttk.Button(lf2, text="Browse…", command=self._pick_output_folder).grid(
            row=0, column=1, padx=(0, 8), pady=8)

        # Structure mode selector
        lf3 = ttk.LabelFrame(self, text="  Label Structure  ")
        lf3.grid(row=3, column=0, sticky="ew", **pad)
        lf3.grid_columnconfigure(1, weight=1)
        self._make_combo(lf3, 0, "Structure type:", self.structure_mode_var, STRUCTURE_MODES, width=42)

        tk.Button(
            self, text="▶  Calculate Durations & Export",
            command=self._run,
            bg="#a6e3a1", fg=BG, font=("Segoe UI", 10, "bold"),
            relief=tk.FLAT, padx=12, pady=8, cursor="hand2",
            activebackground="#89d4a0", activeforeground=BG,
        ).grid(row=4, column=0, padx=10, pady=6, sticky="ew")

        olf = ttk.LabelFrame(self, text="  Output  ")
        olf.grid(row=5, column=0, sticky="nsew", **pad)
        self.grid_rowconfigure(5, weight=1)
        self.log = make_log(olf)
        self.log.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

    def _log(self, msg, tag=""): log_write(self.log, msg, tag)
    def _clear(self):            log_clear(self.log)

    def _pick_labels_folder(self):
        d = filedialog.askdirectory(title="Select Exported Labels folder")
        if d:
            self.labels_folder_var.set(d)
            # Auto-fill output base to parent of Exported Labels
            parent = os.path.dirname(d)
            if not self.output_base_var.get():
                self.output_base_var.set(parent)

    def _pick_output_folder(self):
        d = filedialog.askdirectory(title="Select output base folder")
        if d:
            self.output_base_var.set(d)

    def _run(self):
        self._clear()

        labels_folder = self.labels_folder_var.get().strip()
        if not labels_folder or not os.path.isdir(labels_folder):
            messagebox.showwarning("Missing folder", "Please select the Exported Labels folder.")
            return

        output_base = self.output_base_var.get().strip()
        if not output_base or not os.path.isdir(output_base):
            messagebox.showwarning("Missing folder", "Please select the output base folder.")
            return

        single_mode = self.structure_mode_var.get() == STRUCTURE_MODES[1]

        self._log("Calculating durations…", "head")
        self._log(f"  Source:     {labels_folder}", "")
        self._log(f"  Output:     {output_base}", "")
        self._log(f"  Structure:  {self.structure_mode_var.get()}", "")
        self._log("")

        ok = run_duration_check(
            exported_labels_dir=labels_folder,
            output_base_dir=output_base,
            log_fn=self._log,
            single_label_mode=single_mode,
        )

        if ok:
            self._log("\n✓  Done!", "ok")
        else:
            self._log("\nFailed — check errors above.", "err")

        self._log("")


# ── Tab 4: CSV Generator ───────────────────────────────────────────────────────

class CsvGeneratorTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.labels_folder_var = tk.StringVar()
        self._build()

    def _build(self):
        pad = dict(padx=10, pady=6)
        self.grid_columnconfigure(0, weight=1)

        tk.Label(
            self,
            text=(
                "How to use this tab:\n"
                "  1. Point to the folder containing your label .txt files\n"
                "     (usually the 'Exported Labels' folder)\n"
                "  2. Click Run\n\n"
                "  Each .txt is converted to a matching .csv saved in the same\n"
                "  folder, with header:  Start point,End point,Category\n"
                "  Format is auto-detected per file — works for both single-label\n"
                "  files and traditional multi-segment files (3, 5, 7… rows)."
            ),
            bg="#1a1a2e", fg="#a6adc8", font=("Segoe UI", 9),
            justify=tk.LEFT, anchor="w", padx=12, pady=10,
        ).grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))

        lf1 = ttk.LabelFrame(self, text="  Label .txt Files Folder  ")
        lf1.grid(row=1, column=0, sticky="ew", **pad)
        lf1.grid_columnconfigure(0, weight=1)
        tk.Entry(lf1, textvariable=self.labels_folder_var,
                 bg=EB, fg=FG, insertbackground=FG, relief=tk.FLAT,
                 font=("Consolas", 9)).grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        ttk.Button(lf1, text="Browse…", command=self._pick_folder).grid(
            row=0, column=1, padx=(0, 8), pady=8)

        tk.Button(
            self, text="▶  Generate CSV Files",
            command=self._run,
            bg="#f9e2af", fg=BG, font=("Segoe UI", 10, "bold"),
            relief=tk.FLAT, padx=12, pady=8, cursor="hand2",
            activebackground="#e0cc94", activeforeground=BG,
        ).grid(row=2, column=0, padx=10, pady=6, sticky="ew")

        olf = ttk.LabelFrame(self, text="  Output  ")
        olf.grid(row=3, column=0, sticky="nsew", **pad)
        self.grid_rowconfigure(3, weight=1)
        self.log = make_log(olf)
        self.log.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

    def _log(self, msg, tag=""): log_write(self.log, msg, tag)
    def _clear(self):            log_clear(self.log)

    def _pick_folder(self):
        d = filedialog.askdirectory(title="Select folder containing label .txt files")
        if d:
            self.labels_folder_var.set(d)

    def _run(self):
        self._clear()

        labels_folder = self.labels_folder_var.get().strip()
        if not labels_folder or not os.path.isdir(labels_folder):
            messagebox.showwarning("Missing folder", "Please select the folder containing label .txt files.")
            return

        self._log("Generating CSV files…", "head")
        self._log(f"  Source:  {labels_folder}", "")
        self._log("")

        ok = run_csv_generator(labels_dir=labels_folder, log_fn=self._log)

        if ok:
            self._log(f"\n✓  Done!  CSV files saved alongside the source .txt files.", "ok")
        else:
            self._log("\nFailed — check errors above.", "err")

        self._log("")


# ── Main App ───────────────────────────────────────────────────────────────────

def resource_path(relative_path: str) -> str:
    """
    Resolve a path to a bundled resource (like the .ico file) so it works
    both when running as a plain .py script and when running as a
    PyInstaller-built .exe (where files are unpacked to a temp folder
    referenced by sys._MEIPASS).
    """
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Pikapika v1.2")
        self.configure(bg=BG)
        self.resizable(True, True)

        try:
            self.iconbitmap(resource_path("pikapika.ico"))
        except Exception:
            pass  # fall back to default icon if not found — never crash over this

        self.option_add("*TCombobox*Listbox.Background",       EB)
        self.option_add("*TCombobox*Listbox.Foreground",       FG)
        self.option_add("*TCombobox*Listbox.selectBackground", ACC)
        self.option_add("*TCombobox*Listbox.selectForeground", BG)

        self._setup_styles()
        self._build_ui()
        self.minsize(680, 680)
        self.after(100, lambda: _style_comboboxes(self))

    def _setup_styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TFrame",            background=BG)
        s.configure("TLabel",            background=BG,  foreground=FG,  font=("Segoe UI", 9))
        s.configure("TLabelframe",       background=BG,  foreground=ACC, font=("Segoe UI", 9, "bold"))
        s.configure("TLabelframe.Label", background=BG,  foreground=ACC)
        s.configure("TButton",           background=EB,  foreground=FG,  font=("Segoe UI", 9))
        s.configure("TNotebook",         background=BG,  borderwidth=0)
        s.configure("TNotebook.Tab",     background=EB,  foreground=FG,
                     font=("Segoe UI", 9, "bold"), padding=(14, 6))
        s.map("TButton",      background=[("active", "#45475a")])
        s.map("TNotebook.Tab",
              background=[("selected", ACC), ("active", "#45475a")],
              foreground=[("selected", BG),  ("active", FG)])

        s.configure("Dark.TCombobox",
                     fieldbackground=EB, background=EB, foreground=FG,
                     selectbackground=EB, selectforeground=FG,
                     arrowcolor=FG, bordercolor="#45475a",
                     lightcolor=EB, darkcolor=EB)
        s.map("Dark.TCombobox",
              fieldbackground=[("readonly", EB), ("disabled", EB), ("focus", EB), ("", EB)],
              foreground      =[("readonly", FG), ("disabled", FG), ("focus", FG), ("", FG)],
              selectbackground=[("readonly", EB), ("focus",    EB), ("",      EB)],
              selectforeground=[("readonly", FG), ("focus",    FG), ("",      FG)],
              background      =[("readonly", EB), ("active",   EB), ("",      EB)])

    def _make_combo(self, parent, row, label_text, var, values, readonly=True, width=26):
        ttk.Label(parent, text=label_text).grid(row=row, column=0, sticky="w", padx=10, pady=5)
        cb = ttk.Combobox(parent, textvariable=var, values=values, width=width,
                          style="Dark.TCombobox",
                          state="readonly" if readonly else "normal")
        cb.grid(row=row, column=1, sticky="w", padx=10, pady=5)
        return cb

    def _build_ui(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        nb = ttk.Notebook(self)
        nb.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        self.tab1 = ImporterTab(nb, self._make_combo)
        self.tab2 = LabelExporterTab(nb, self._make_combo)
        self.tab3 = DurationCheckerTab(nb, self._make_combo)
        self.tab4 = CsvGeneratorTab(nb)

        nb.add(self.tab1, text="  PCM Importer  ")
        nb.add(self.tab2, text="  Label Exporter  ")
        nb.add(self.tab4, text="  CSV Generator  ")
        nb.add(self.tab3, text="  Duration Checker  ")

        tk.Label(
            self,
            text="Created and Designed with love  ·  All Rights Reserved  ©  Priyangshu Swarnakar",
            bg="#181825", fg="#6c7086", font=("Segoe UI", 8), pady=5,
        ).grid(row=1, column=0, sticky="ew")


if __name__ == "__main__":
    App().mainloop()
