#!/opt/homebrew/opt/python@3.13/bin/python3.13
"""MTS → MP4 (H.265) converter for JVC GZ-E600-N camcorder footage."""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import subprocess
import threading
import os
import json
from typing import List, Optional
from pathlib import Path

def _find_bin(name: str) -> str:
    """Find ffmpeg/ffprobe in Homebrew or standard locations, regardless of shell PATH."""
    candidates = [
        f"/opt/homebrew/bin/{name}",   # Apple Silicon Homebrew
        f"/usr/local/bin/{name}",       # Intel Homebrew
        f"/opt/local/bin/{name}",       # MacPorts
        f"/usr/bin/{name}",
    ]
    for p in candidates:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return name  # fall back and let the OS try

FFMPEG  = _find_bin("ffmpeg")
FFPROBE = _find_bin("ffprobe")

PRESETS = {
    "Stream Copy (no re-encode)": ("copy",      0),
    "Fast (larger file)":         ("ultrafast", 28),
    "Balanced (recommended)":     ("medium",    23),
    "High Quality (slower)":      ("slow",      20),
    "Archival (very slow)":       ("veryslow",  18),
    "Lossless H.265 (huge file)": ("lossless",  0),
}

AUDIO_OPTIONS = {
    "AAC 128k":  ["-c:a", "aac", "-b:a", "128k"],
    "AAC 192k":  ["-c:a", "aac", "-b:a", "192k"],
    "AAC 256k":  ["-c:a", "aac", "-b:a", "256k"],
    "Copy audio": ["-c:a", "copy"],
}


def probe_duration(path: str) -> float:
    """Return duration in seconds via ffprobe, or 0.0 on failure."""
    try:
        result = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "json", path],
            capture_output=True, text=True, timeout=30
        )
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except Exception:
        return 0.0


def build_ffmpeg_cmd(input_path: str, output_path: str,
                     preset: str, crf: int, audio_args: list,
                     use_hw: bool, apple_compat: bool) -> list:
    cmd = [FFMPEG, "-y", "-i", input_path]
    if preset == "copy":
        # Remux only — no re-encode, zero quality loss, same file size
        cmd += ["-c:v", "copy"]
        # Stream copy ignores audio_args; always copy audio too
        cmd += ["-c:a", "copy"]
        cmd += ["-movflags", "+faststart", "-progress", "pipe:1", "-nostats", output_path]
        return cmd
    elif preset == "lossless":
        cmd += ["-c:v", "libx265", "-x265-params", "lossless=1"]
    elif use_hw:
        cmd += ["-c:v", "hevc_videotoolbox", "-q:v", str(max(20, 80 - crf * 2))]
    else:
        cmd += ["-c:v", "libx265", "-crf", str(crf), "-preset", preset]
    if apple_compat and preset != "copy":
        cmd += ["-tag:v", "hvc1"]
    cmd += audio_args
    cmd += ["-movflags", "+faststart", "-progress", "pipe:1", "-nostats", output_path]
    return cmd


class ConverterApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MTS → MP4 H.265 Converter  ·  JVC GZ-E600-N")
        self.resizable(True, True)
        self.minsize(700, 520)

        self._files: List[str] = []
        self._converting = False
        self._cancel_flag = threading.Event()
        self._current_proc: Optional[subprocess.Popen] = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self):
        pad = {"padx": 10, "pady": 4}

        # ── File list frame ──
        file_frame = ttk.LabelFrame(self, text="Input Files (.MTS)")
        file_frame.pack(fill="both", expand=True, **pad)

        list_scroll = ttk.Scrollbar(file_frame)
        list_scroll.pack(side="right", fill="y")
        self._listbox = tk.Listbox(file_frame, selectmode="extended",
                                   yscrollcommand=list_scroll.set,
                                   height=8, activestyle="none",
                                   bg="#1e1e1e", fg="#d4d4d4",
                                   selectbackground="#264f78",
                                   font=("Menlo", 11))
        self._listbox.pack(fill="both", expand=True, padx=(4, 0), pady=4)
        list_scroll.config(command=self._listbox.yview)

        btn_row = ttk.Frame(file_frame)
        btn_row.pack(fill="x", padx=4, pady=(0, 4))
        ttk.Button(btn_row, text="Add Files…",      command=self._add_files).pack(side="left", padx=(0, 4))
        ttk.Button(btn_row, text="Add Folder…",     command=self._add_folder).pack(side="left", padx=(0, 4))
        ttk.Button(btn_row, text="Type Path…",      command=self._type_path).pack(side="left", padx=(0, 4))
        ttk.Button(btn_row, text="Detect Camera",   command=self._detect_camera).pack(side="left", padx=(0, 12))
        ttk.Button(btn_row, text="Remove Selected", command=self._remove_selected).pack(side="left", padx=(0, 4))
        ttk.Button(btn_row, text="Clear All",       command=self._clear_files).pack(side="left")

        # ── Output dir ──
        out_frame = ttk.LabelFrame(self, text="Output Directory")
        out_frame.pack(fill="x", **pad)
        self._out_var = tk.StringVar(value=str(Path.home() / "Movies" / "Converted"))
        ttk.Entry(out_frame, textvariable=self._out_var, font=("Menlo", 11)).pack(
            side="left", fill="x", expand=True, padx=4, pady=4)
        ttk.Button(out_frame, text="Browse…", command=self._browse_output).pack(
            side="right", padx=(0, 4), pady=4)

        # ── Settings row ──
        settings_frame = ttk.LabelFrame(self, text="Encoding Settings")
        settings_frame.pack(fill="x", **pad)

        sf = ttk.Frame(settings_frame)
        sf.pack(fill="x", padx=4, pady=4)

        ttk.Label(sf, text="Quality Preset:").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self._preset_var = tk.StringVar(value="Balanced (recommended)")
        preset_cb = ttk.Combobox(sf, textvariable=self._preset_var,
                                 values=list(PRESETS.keys()), state="readonly", width=26)
        preset_cb.grid(row=0, column=1, padx=(0, 20))

        ttk.Label(sf, text="Audio:").grid(row=0, column=2, sticky="w", padx=(0, 4))
        self._audio_var = tk.StringVar(value="AAC 192k")
        audio_cb = ttk.Combobox(sf, textvariable=self._audio_var,
                                values=list(AUDIO_OPTIONS.keys()), state="readonly", width=14)
        audio_cb.grid(row=0, column=3, padx=(0, 20))

        self._hw_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(sf, text="Hardware encode (VideoToolbox, faster)",
                        variable=self._hw_var).grid(row=0, column=4, padx=(0, 10))

        self._apple_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(sf, text="Apple/QuickTime compatible tag",
                        variable=self._apple_var).grid(row=0, column=5)

        # ── Progress ──
        prog_frame = ttk.LabelFrame(self, text="Progress")
        prog_frame.pack(fill="x", **pad)

        self._file_label = ttk.Label(prog_frame, text="Idle", anchor="w")
        self._file_label.pack(fill="x", padx=4, pady=(4, 0))

        self._file_prog = ttk.Progressbar(prog_frame, mode="determinate", length=100)
        self._file_prog.pack(fill="x", padx=4, pady=2)

        self._overall_label = ttk.Label(prog_frame, text="", anchor="w")
        self._overall_label.pack(fill="x", padx=4)

        self._overall_prog = ttk.Progressbar(prog_frame, mode="determinate", length=100)
        self._overall_prog.pack(fill="x", padx=4, pady=(2, 4))

        # ── Log ──
        log_frame = ttk.LabelFrame(self, text="Log")
        log_frame.pack(fill="both", expand=True, **pad)

        log_scroll = ttk.Scrollbar(log_frame)
        log_scroll.pack(side="right", fill="y")
        self._log = tk.Text(log_frame, height=6, state="disabled",
                            yscrollcommand=log_scroll.set,
                            bg="#0d0d0d", fg="#9cdcfe",
                            font=("Menlo", 10), wrap="word")
        self._log.pack(fill="both", expand=True, padx=(4, 0), pady=4)
        log_scroll.config(command=self._log.yview)
        self._log.tag_config("ok",    foreground="#4ec9b0")
        self._log.tag_config("error", foreground="#f44747")
        self._log.tag_config("info",  foreground="#9cdcfe")

        # ── Action buttons ──
        action_row = ttk.Frame(self)
        action_row.pack(fill="x", padx=10, pady=(0, 10))
        self._convert_btn = ttk.Button(action_row, text="Convert", width=16,
                                       command=self._start_conversion)
        self._convert_btn.pack(side="left", padx=(0, 8))
        self._cancel_btn = ttk.Button(action_row, text="Cancel", width=10,
                                      command=self._cancel, state="disabled")
        self._cancel_btn.pack(side="left")
        self._status_lbl = ttk.Label(action_row, text="Add files and press Convert.")
        self._status_lbl.pack(side="left", padx=12)

    # ── File management ────────────────────────────────────────────────────

    def _add_files(self):
        # Use osascript so the picker can navigate inside AVCHD packages
        initial = self._best_initial_dir()
        paths = self._osascript_pick_files(initial)
        if paths is None:
            # Fall back to tkinter picker if osascript unavailable
            paths = list(filedialog.askopenfilenames(
                title="Select MTS files", initialdir=initial,
                filetypes=[("AVCHD video", "*.MTS *.mts"), ("All files", "*.*")]
            ))
        for p in paths:
            if p and p not in self._files:
                self._files.append(p)
                self._listbox.insert("end", os.path.basename(p))

    def _add_folder(self):
        initial = self._best_initial_dir()
        folder = self._osascript_pick_folder(initial)
        if folder is None:
            folder = filedialog.askdirectory(
                title="Select folder containing MTS files",
                initialdir=initial,
            )
        if not folder:
            return
        self._scan_and_add(folder)

    @staticmethod
    def _osascript_pick_files(initial: str) -> Optional[List[str]]:
        """Native macOS file picker via AppleScript — navigates into AVCHD packages."""
        script = (
            f'set startFolder to POSIX file "{initial}" as alias\n'
            'set chosen to choose file with prompt "Select .MTS files" '
            'of type {"MTS", "mts", "com.public.movie"} '
            'default location startFolder with multiple selections allowed '
            'showing package contents'
        )
        try:
            r = subprocess.run(["osascript", "-e", script],
                               capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                return None
            # AppleScript returns alias paths separated by ", "
            raw = r.stdout.strip()
            if not raw:
                return []
            # Convert "alias MacHD:Volumes:JVCCAM_SD:..." → POSIX paths
            posix_script = f'set x to {{{raw}}}\nset out to ""\nrepeat with a in x\n  set out to out & POSIX path of a & "\\n"\nend repeat\nout'
            r2 = subprocess.run(["osascript", "-e", posix_script],
                                capture_output=True, text=True, timeout=10)
            return [p for p in r2.stdout.splitlines() if p.strip()]
        except Exception:
            return None

    @staticmethod
    def _osascript_pick_folder(initial: str) -> Optional[str]:
        """Native macOS folder picker via AppleScript."""
        script = (
            f'set startFolder to POSIX file "{initial}" as alias\n'
            'POSIX path of (choose folder with prompt "Select folder containing MTS files" '
            'default location startFolder showing package contents)'
        )
        try:
            r = subprocess.run(["osascript", "-e", script],
                               capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                return None
            return r.stdout.strip() or None
        except Exception:
            return None

    def _type_path(self):
        """Show a dialog so the user can paste any path — bypasses the file picker."""
        win = tk.Toplevel(self)
        win.title("Add by path")
        win.resizable(True, False)
        win.grab_set()

        ttk.Label(win, text="Paste a folder path or .MTS file path:").pack(
            padx=12, pady=(12, 4), anchor="w")

        var = tk.StringVar()
        # Pre-fill with detected camera path if available
        detected = self._jvc_stream_path()
        if detected:
            var.set(detected)

        entry = ttk.Entry(win, textvariable=var, width=60, font=("Menlo", 11))
        entry.pack(padx=12, fill="x")
        entry.select_range(0, "end")
        entry.focus_set()

        def _ok():
            p = var.get().strip()
            if not p:
                win.destroy()
                return
            path = Path(p)
            if path.is_file():
                if str(path) not in self._files:
                    self._files.append(str(path))
                    self._listbox.insert("end", path.name)
                    self._log_msg(f"Added 1 file: {path.name}", "info")
            elif path.is_dir():
                self._scan_and_add(str(path))
            else:
                messagebox.showerror("Not found", f"Path does not exist:\n{p}", parent=win)
                return
            win.destroy()

        btn_row = ttk.Frame(win)
        btn_row.pack(padx=12, pady=12, fill="x")
        ttk.Button(btn_row, text="Add", command=_ok, width=10).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Cancel", command=win.destroy, width=8).pack(side="left")
        win.bind("<Return>", lambda _: _ok())
        win.bind("<Escape>", lambda _: win.destroy())

    def _detect_camera(self):
        """Scan /Volumes for JVC / AVCHD STREAM folders and add all MTS files found."""
        paths = self._find_avchd_streams()
        if not paths:
            messagebox.showinfo(
                "No camera found",
                "No JVC camera or AVCHD card detected.\n\n"
                "Make sure the SD card is inserted and mounted, then try again.",
            )
            return
        total = 0
        for stream_dir in paths:
            before = len(self._files)
            self._scan_and_add(stream_dir)
            total += len(self._files) - before
        if total == 0:
            self._log_msg("Camera detected but no new MTS files found.", "info")

    # ── Helpers ────────────────────────────────────────────────────────────

    def _scan_and_add(self, folder: str):
        found = sorted(Path(folder).rglob("*.MTS")) + sorted(Path(folder).rglob("*.mts"))
        # Skip macOS resource-fork ghost files (._filename)
        found = [f for f in found if not f.name.startswith("._")]
        added = 0
        for f in found:
            s = str(f)
            if s not in self._files:
                self._files.append(s)
                self._listbox.insert("end", f.name)
                added += 1
        self._log_msg(f"Added {added} file(s) from {Path(folder).name}", "info")

    def _jvc_stream_path(self) -> str:
        """Return the STREAM path for a mounted JVC card, or empty string."""
        paths = self._find_avchd_streams()
        return paths[0] if paths else ""

    def _find_avchd_streams(self) -> List[str]:
        """Walk /Volumes looking for AVCHD BDMV/STREAM directories."""
        results = []
        volumes = Path("/Volumes")
        for vol in volumes.iterdir():
            # Check both PRIVATE (JVC) and AVCHD (generic AVCHD card) layouts
            candidates = [
                vol / "PRIVATE" / "AVCHD" / "BDMV" / "STREAM",
                vol / "private" / "AVCHD" / "BDMV" / "STREAM",
                vol / "AVCHD" / "BDMV" / "STREAM",
            ]
            for c in candidates:
                if c.is_dir():
                    results.append(str(c))
        return results

    def _best_initial_dir(self) -> str:
        """Pick the most useful starting directory for the file dialog."""
        # If JVC camera is mounted, start there
        stream = self._jvc_stream_path()
        if stream:
            return stream
        # Otherwise start at /Volumes so external drives are visible
        vols = [v for v in Path("/Volumes").iterdir()
                if v.is_dir() and v.name not in ("Macintosh HD",)]
        if vols:
            return "/Volumes"
        return str(Path.home())

    def _remove_selected(self):
        for idx in reversed(self._listbox.curselection()):
            self._listbox.delete(idx)
            self._files.pop(idx)

    def _clear_files(self):
        self._listbox.delete(0, "end")
        self._files.clear()

    def _browse_output(self):
        d = filedialog.askdirectory(title="Select output directory")
        if d:
            self._out_var.set(d)

    # ── Conversion ─────────────────────────────────────────────────────────

    def _start_conversion(self):
        if not self._files:
            messagebox.showwarning("No files", "Add at least one .MTS file.")
            return
        out_dir = self._out_var.get().strip()
        if not out_dir:
            messagebox.showwarning("No output", "Select an output directory.")
            return
        Path(out_dir).mkdir(parents=True, exist_ok=True)

        self._converting = True
        self._cancel_flag.clear()
        self._convert_btn.config(state="disabled")
        self._cancel_btn.config(state="normal")
        self._overall_prog["value"] = 0
        self._file_prog["value"] = 0

        preset_name = self._preset_var.get()
        ff_preset, crf = PRESETS[preset_name]
        audio_args = AUDIO_OPTIONS[self._audio_var.get()]
        use_hw = self._hw_var.get()
        apple = self._apple_var.get()

        files_snapshot = list(self._files)
        threading.Thread(
            target=self._conversion_worker,
            args=(files_snapshot, out_dir, ff_preset, crf, audio_args, use_hw, apple),
            daemon=True
        ).start()

    def _conversion_worker(self, files, out_dir, preset, crf, audio_args, use_hw, apple):
        total = len(files)
        done = 0
        errors = 0

        for idx, src in enumerate(files):
            if self._cancel_flag.is_set():
                self._log_msg("Conversion cancelled.", "error")
                break

            stem = Path(src).stem
            dst = str(Path(out_dir) / f"{stem}.mp4")
            # avoid overwriting existing file
            if Path(dst).exists():
                counter = 1
                while Path(out_dir, f"{stem}_{counter}.mp4").exists():
                    counter += 1
                dst = str(Path(out_dir) / f"{stem}_{counter}.mp4")

            self._update_file_label(f"[{idx+1}/{total}] {Path(src).name}")
            self._log_msg(f"→ {Path(src).name}", "info")
            duration = probe_duration(src)
            cmd = build_ffmpeg_cmd(src, dst, preset, crf, audio_args, use_hw, apple)

            success = self._run_ffmpeg(cmd, duration, idx, total)
            if success:
                done += 1
                size_mb = Path(dst).stat().st_size / 1024 / 1024
                self._log_msg(f"  ✓ Saved {Path(dst).name} ({size_mb:.1f} MB)", "ok")
            else:
                errors += 1
                if Path(dst).exists():
                    Path(dst).unlink(missing_ok=True)
                if not self._cancel_flag.is_set():
                    self._log_msg(f"  ✗ Failed: {Path(src).name}", "error")

        self._after_conversion(done, errors, total)

    def _run_ffmpeg(self, cmd: list, duration: float, file_idx: int, total: int) -> bool:
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1
            )
            self._current_proc = proc
        except FileNotFoundError:
            self._log_msg("ffmpeg not found. Install via: brew install ffmpeg", "error")
            return False

        # Drain stderr in background thread to prevent pipe buffer deadlock.
        stderr_lines: List[str] = []
        def _drain_stderr():
            for ln in proc.stderr:
                stderr_lines.append(ln)
        drain_thread = threading.Thread(target=_drain_stderr, daemon=True)
        drain_thread.start()

        for line in proc.stdout:
            if self._cancel_flag.is_set():
                proc.terminate()
                proc.wait()
                drain_thread.join(timeout=2)
                return False
            line = line.strip()
            if line.startswith("out_time_ms="):
                try:
                    out_time_us = int(line.split("=")[1])
                    elapsed_s = out_time_us / 1_000_000
                    if duration > 0:
                        pct = min(100.0, elapsed_s / duration * 100)
                        self._update_file_prog(pct)
                        overall = (file_idx / total + pct / total / 100) * 100
                        self._update_overall_prog(overall)
                except ValueError:
                    pass

        proc.wait()
        drain_thread.join(timeout=5)
        self._current_proc = None
        if proc.returncode != 0 and not self._cancel_flag.is_set():
            last = "\n".join(stderr_lines[-5:]).strip()
            self._log_msg(f"  ffmpeg error: {last}", "error")
            return False
        self._update_file_prog(100)
        overall = ((file_idx + 1) / total) * 100
        self._update_overall_prog(overall)
        return proc.returncode == 0

    def _cancel(self):
        self._cancel_flag.set()
        if self._current_proc:
            try:
                self._current_proc.terminate()
            except Exception:
                pass

    def _after_conversion(self, done, errors, total):
        self._converting = False
        self._current_proc = None
        self.after(0, lambda: self._convert_btn.config(state="normal"))
        self.after(0, lambda: self._cancel_btn.config(state="disabled"))
        summary = f"Done: {done}/{total} converted"
        if errors:
            summary += f", {errors} error(s)"
        self.after(0, lambda: self._status_lbl.config(text=summary))
        self.after(0, lambda: self._file_label.config(text="Idle"))
        self._log_msg(summary, "ok" if not errors else "error")

    # ── Thread-safe UI helpers ─────────────────────────────────────────────

    def _log_msg(self, msg: str, tag: str = "info"):
        def _do():
            self._log.config(state="normal")
            self._log.insert("end", msg + "\n", tag)
            self._log.see("end")
            self._log.config(state="disabled")
        self.after(0, _do)

    def _update_file_prog(self, pct: float):
        self.after(0, lambda: self._file_prog.__setitem__("value", pct))

    def _update_overall_prog(self, pct: float):
        self.after(0, lambda: self._overall_prog.__setitem__("value", pct))

    def _update_file_label(self, text: str):
        self.after(0, lambda: self._file_label.config(text=text))

    def _on_close(self):
        if self._converting:
            if not messagebox.askyesno("Quit", "Conversion in progress. Cancel and quit?"):
                return
            self._cancel()
        self.destroy()


if __name__ == "__main__":
    app = ConverterApp()
    app.mainloop()
