"""
nerux_uploader.py
-----------------
GUI tool by Nerux-Network.de for uploading your own Steam Workshop items
for MushDash (App ID 3026250).

Start:    python nerux_uploader.py     (or double-click start.bat)
Requires: customtkinter  (pip install -r requirements.txt)
          steam_api64.dll next to this file
          Steam running + an account that owns MushDash
"""

import os
import shutil
import tempfile
import threading
import traceback

import customtkinter as ctk
from tkinter import filedialog, messagebox

from steam_ugc import SteamUGC, SteamError

try:
    from PIL import Image
    _PIL_OK = True
except Exception:
    _PIL_OK = False

from steam_uploader_text import language_object

SIGNATURE_TEXT = ""
SIGNATURE = "\n\n" + SIGNATURE_TEXT
MUSHDASH_APP_ID = 3026250

# Automatic preview-image generation
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")
PREVIEW_MAX_SIDE = 512            # max edge length, aspect ratio is preserved
PREVIEW_MAX_BYTES = 950 * 1024   # stay under Steam's 1 MB limit

VIS_LABELS = {
    "Public": "public",
    "Friends only": "friends",
    "Private": "private",
    "Unlisted": "unlisted",
}

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

ACCENT = "#5b8cff"
BG_DARK = "#12141c"


class UploaderApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.langObj = language_object()
        self.title("Nerux-Network - Mush Dash Workshop Uploader")
        self.geometry("780x860")
        self.minsize(700, 760)

        self.content_files = []       # individual files (e.g. PNGs)
        self.content_folder = None    # or a whole folder
        self.preview_path = None
        self._temp_dir = None
        self._temp_previews = []

        self._build_ui()

    # ------------------------------------------------------------------ #
    # UI setup
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        header = ctk.CTkFrame(self, corner_radius=0, fg_color=BG_DARK)
        header.pack(fill="x")
        self.language_entry = ctk.CTkOptionMenu(
            header, values=self.langObj.get_language_list(), command=self._set_language
        ).pack(side="right", padx=(0, 8))
        ctk.CTkLabel(
            header, textvariable=self.langObj.get_text_value("header"),
            font=ctk.CTkFont(size=24, weight="bold"),
        ).pack(padx=20, pady=(16, 0), anchor="w")
        ctk.CTkLabel(
            header, textvariable=self.langObj.get_text_value("headerDesc"), text_color=ACCENT,
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(padx=20, pady=(0, 16), anchor="w")

        body = ctk.CTkScrollableFrame(self)
        body.pack(fill="both", expand=True, padx=4, pady=4)

        # App ID
        self._label(body, textvariable=self.langObj.get_text_value("appId"))
        self.app_id_entry = ctk.CTkEntry(body, height=36)
        self.app_id_entry.insert(0, str(MUSHDASH_APP_ID))
        self.app_id_entry.pack(fill="x", padx=16, pady=(0, 12))

        # File ID
        self._label(body, textvariable=self.langObj.get_text_value("fileId"))
        self.file_id_entry = ctk.CTkEntry(body, height=36)
        self.file_id_entry.insert(0, "")
        self.file_id_entry.pack(fill="x", padx=16, pady=(0, 12))

        # Title
        self._label(body, textvariable=self.langObj.get_text_value("title"))
        self.title_entry = ctk.CTkEntry(body, height=36,
                                        placeholder_text="Name of your item")
        self.title_entry.pack(fill="x", padx=16, pady=(0, 12))

        # Description
        self._label(body, textvariable=self.langObj.get_text_value("desc"))
        self.desc_box = ctk.CTkTextbox(body, height=130)
        self.desc_box.pack(fill="x", padx=16, pady=(0, 4))
        ctk.CTkLabel(
            body, text="Automatically appended at the end:  \u201c"
                       + SIGNATURE_TEXT + "\u201d",
            text_color="#8a8f9c", font=ctk.CTkFont(size=11),
        ).pack(anchor="w", padx=18, pady=(0, 12))

        # Content (files / folder)
        self._label(body, textvariable=self.langObj.get_text_value("content"))
        btn_row = ctk.CTkFrame(body, fg_color="transparent")
        btn_row.pack(fill="x", padx=8, pady=(0, 4))
        ## ctk.CTkButton(btn_row, text="Choose files ...",
        ##               command=self._choose_files).pack(side="left")
        ctk.CTkButton(btn_row, textvariable=self.langObj.get_text_value("chooseFolder"),
                      fg_color="#2b2f3a", hover_color="#3a3f4d",
                      command=self._choose_folder).pack(side="left", padx=8)
        ctk.CTkButton(btn_row, textvariable=self.langObj.get_text_value("clear"), width=70,
                      fg_color="#3a2b2b", hover_color="#4d3a3a",
                      command=self._clear_content).pack(side="left")
        self.content_label = ctk.CTkLabel(
            body, text="Nothing selected yet.", text_color="#8a8f9c",
            font=ctk.CTkFont(size=11), justify="left", wraplength=680,
        )
        self.content_label.pack(anchor="w", padx=18, pady=(2, 12))

        # Preview image
        self._label(body, textvariable=self.langObj.get_text_value("previewImg"))
        prev_row = ctk.CTkFrame(body, fg_color="transparent")
        prev_row.pack(fill="x", padx=16, pady=(0, 4))
        ctk.CTkButton(prev_row, textvariable=self.langObj.get_text_value("choPrevImg"),
                      command=self._choose_preview).pack(side="left")
        self.preview_label = ctk.CTkLabel(
            body, text="No preview image selected.", text_color="#8a8f9c",
            font=ctk.CTkFont(size=11), wraplength=680, justify="left",
        )
        self.preview_label.pack(anchor="w", padx=18, pady=(2, 2))
        ctk.CTkLabel(
            body, text="Leave empty = generated automatically from the first image.",
            text_color="#8a8f9c", font=ctk.CTkFont(size=11),
        ).pack(anchor="w", padx=18, pady=(0, 12))

        # Visibility + tags
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 12))
        left = ctk.CTkFrame(row, fg_color="transparent")
        left.pack(side="left", expand=True, fill="x")
        self._label(left, textvariable=self.langObj.get_text_value("visibility"), pad_x=0)
        self.vis_menu = ctk.CTkOptionMenu(left, values=list(VIS_LABELS.keys()))
        self.vis_menu.set("Public")
        self.vis_menu.pack(fill="x")
        right = ctk.CTkFrame(row, fg_color="transparent")
        right.pack(side="left", expand=True, fill="x", padx=(12, 0))
        self._label(right, textvariable=self.langObj.get_text_value("tags"), pad_x=0)
        self.tags_entry = ctk.CTkEntry(right, placeholder_text="e.g. Skin, Custom")
        self.tags_entry.pack(fill="x")

        # DLL path (optional)
        self._label(body, textvariable=self.langObj.get_text_value("apiDll"))
        self.dll_entry = ctk.CTkEntry(
            body, height=36, placeholder_text="leave empty = automatic")
        self.dll_entry.pack(fill="x", padx=16, pady=(0, 16))

        # Upload button row
        update_upload_row = ctk.CTkFrame(body, fg_color="transparent")
        update_upload_row.pack(fill="x", padx=16, pady=(0, 10))

        # Update content only button
        self.update_btn:ctk.CTkButton = ctk.CTkButton(
            update_upload_row, textvariable=self.langObj.get_text_value("updateContOnly"), height=46, fg_color=ACCENT,
            hover_color="#4a76e0", font=ctk.CTkFont(size=16, weight="bold"),
            command=self._start_update,
        )
        self.update_btn.pack(fill="both", side="left", expand=True)
        
        # Upload button
        self.upload_btn:ctk.CTkButton = ctk.CTkButton(
            update_upload_row, textvariable=self.langObj.get_text_value("upload"), height=46, fg_color=ACCENT,
            hover_color="#4a76e0", font=ctk.CTkFont(size=16, weight="bold"),
            command=self._start_upload,
        )
        self.upload_btn.pack(fill="both", side="left", padx=(8,0), expand=True)

        # Progress
        self.progress = ctk.CTkProgressBar(body, height=14)
        self.progress.set(0)
        self.progress.pack(fill="x", padx=16, pady=(0, 12))

        # Log
        self._label(body, textvariable=self.langObj.get_text_value("log"))
        self.log_box = ctk.CTkTextbox(body, height=170)
        self.log_box.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.log_box.configure(state="disabled")
        self._append_log("Ready. Make sure Steam is running and your account "
                         "owns Mush Dash.")

    def _label(self, parent, text="", textvariable="", pad_x=16):
        ctk.CTkLabel(parent, text=text, textvariable=textvariable,
                     font=ctk.CTkFont(size=13, weight="bold")).pack(
            anchor="w", padx=pad_x, pady=(6, 2))

    # ------------------------------------------------------------------ #
    # Language
    # ------------------------------------------------------------------ #
    def _set_language(self, out_language):
        self.langObj.set_language(language=out_language)

    # ------------------------------------------------------------------ #
    # File selection
    # ------------------------------------------------------------------ #
    def _choose_files(self):
        paths = filedialog.askopenfilenames(
            title="Choose content files",
            filetypes=[("Images", "*.png *.jpg *.jpeg"), ("All files", "*.*")],
        )
        if paths:
            self.content_files = list(paths)
            self.content_folder = None
            self.content_label.configure(
                text="%d file(s): %s" % (
                    len(paths), ", ".join(os.path.basename(p) for p in paths)))

    def _choose_folder(self):
        folder = filedialog.askdirectory(title="Choose content folder")
        if folder:
            self.content_folder = folder
            self.content_files = []
            self.content_label.configure(text="Folder: " + folder)

    def _clear_content(self):
        self.content_files = []
        self.content_folder = None
        self.content_label.configure(text="Nothing selected yet.")

    def _choose_preview(self):
        path = filedialog.askopenfilename(
            title="Choose preview image",
            filetypes=[("Images", "*.png *.jpg *.jpeg"), ("All files", "*.*")],
        )
        if path:
            self.preview_path = path
            size_kb = os.path.getsize(path) / 1024
            warn = "  (WARNING: > 1 MB!)" if size_kb > 1024 else ""
            self.preview_label.configure(
                text="%s  (%.0f KB)%s" % (os.path.basename(path), size_kb, warn))

    # ------------------------------------------------------------------ #
    # Upload flow
    # ------------------------------------------------------------------ #
    def _start_update(self):
        if not self.content_folder and not self.content_files:
            messagebox.showwarning(
                "Missing", "Please choose content files or a folder.")
            return

        try:
            app_id = int(self.app_id_entry.get().strip())
        except ValueError:
            messagebox.showwarning("Error", "App ID must be a number.")
            return

        try:
            file_id = int(self.file_id_entry.get().strip())
        except ValueError:
            messagebox.showwarning("Error", "File ID must be a number. Abort! ")
            return

        params = {
            "only_content": True,
            "app_id": app_id,
            "file_id": file_id,
            "title": "",
            "description": "",
            "visibility": VIS_LABELS.get(self.vis_menu.get(), "public"),
            "tags": "",
            "dll": self.dll_entry.get().strip(),
        }

        self.update_btn.configure(state="disabled")
        self.upload_btn.configure(state="disabled")
        self.progress.set(0)
        threading.Thread(target=self._worker, args=(params,), daemon=True).start()

    def _start_upload(self):
        if not self.content_folder and not self.content_files:
            messagebox.showwarning(
                "Missing", "Please choose content files or a folder.")
            return

        title = self.title_entry.get().strip()
        if not title:
            # No title given -> use the first image's file name (without extension)
            src = self._first_image()
            if src:
                title = os.path.splitext(os.path.basename(src))[0]
                self.log("No title entered - using image name: '%s'." % title)
            else:
                messagebox.showwarning(
                    "Missing",
                    "Please enter a title (or add an image to use its file name).")
                return

        try:
            app_id = int(self.app_id_entry.get().strip())
        except ValueError:
            messagebox.showwarning("Error", "App ID must be a number.")
            return
        
        description = self.desc_box.get("1.0", "end").rstrip()
        if not description.endswith(SIGNATURE_TEXT):
            description = (description + SIGNATURE) if description else SIGNATURE.strip()

        tags = [t.strip() for t in self.tags_entry.get().split(",") if t.strip()]

        params = {
            "only_content": False,
            "app_id": app_id,
            "file_id": 0,
            "title": title,
            "description": description,
            "visibility": VIS_LABELS.get(self.vis_menu.get(), "public"),
            "tags": tags,
            "dll": self.dll_entry.get().strip(),
        }

        self.update_btn.configure(state="disabled")
        self.upload_btn.configure(state="disabled")
        self.progress.set(0)
        threading.Thread(target=self._worker, args=(params,), daemon=True).start()

    def _resolve_content(self):
        if self.content_folder and os.path.isdir(self.content_folder):
            return self.content_folder
        if self.content_files:
            self._temp_dir = tempfile.mkdtemp(prefix="nerux_ws_")
            for path in self.content_files:
                if os.path.isfile(path):
                    shutil.copy2(path, self._temp_dir)
            return self._temp_dir
        return None

    def _collect_images(self):
        """All image files from the selected content, in order."""
        images = []
        if self.content_files:
            images = [p for p in self.content_files
                      if os.path.isfile(p) and p.lower().endswith(IMAGE_EXTS)]
        elif self.content_folder and os.path.isdir(self.content_folder):
            for name in sorted(os.listdir(self.content_folder)):
                full = os.path.join(self.content_folder, name)
                if os.path.isfile(full) and name.lower().endswith(IMAGE_EXTS):
                    images.append(full)
        return images

    def _first_image(self):
        images = self._collect_images()
        return images[0] if images else None

    def _make_preview_copy(self, src, max_side=PREVIEW_MAX_SIDE):
        """Downscaled copy of 'src' kept under Steam's 1 MB limit. Returns a path."""
        if not _PIL_OK:
            self.log("NOTE: Pillow is not installed - cannot process preview "
                     "images (pip install pillow).")
            return None
        try:
            img = Image.open(src)
            img.load()
            img.thumbnail((max_side, max_side))

            fd, out = tempfile.mkstemp(prefix="nerux_prev_", suffix=".png")
            os.close(fd)

            save_img = img if img.mode in ("RGB", "RGBA", "L", "P") \
                else img.convert("RGBA")
            save_img.save(out, format="PNG", optimize=True)

            # If the PNG is too large -> save as JPEG with decreasing quality
            if os.path.getsize(out) > PREVIEW_MAX_BYTES:
                rgb = img.convert("RGB")
                jpg = out[:-4] + ".jpg"
                for quality in (85, 75, 65, 55, 45):
                    rgb.save(jpg, format="JPEG", quality=quality, optimize=True)
                    if os.path.getsize(jpg) <= PREVIEW_MAX_BYTES:
                        break
                try:
                    os.remove(out)
                except OSError:
                    pass
                out = jpg

            self._temp_previews.append(out)
            return out
        except Exception as exc:
            self.log("NOTE: Could not process image '%s': %s"
                     % (os.path.basename(src), exc))
            return None

    def _worker(self, params):
        steam = None
        try:
            steam = SteamUGC(app_id=params["app_id"],
                             dll_path=params["dll"] or None, log=self.log)
            steam.init()

            content = self._resolve_content()
            if not content:
                raise SteamError("No content found.")

            # Preview image + gallery: show ALL images on the item page.
            MAX_GALLERY = 20
            images = self._collect_images()
            main_preview = None
            gallery_sources = []

            if self.preview_path:
                # User picked their own main preview; all content images go to gallery.
                main_preview = self.preview_path
                if _PIL_OK and os.path.getsize(self.preview_path) > 950 * 1024:
                    main_preview = self._make_preview_copy(self.preview_path) \
                        or self.preview_path
                gallery_sources = images[:MAX_GALLERY]
            elif images:
                # No preview chosen: first image becomes the main preview,
                # the rest fill the gallery.
                main_preview = self._make_preview_copy(images[0])
                self.log("No preview chosen - using '%s' as the main image."
                         % os.path.basename(images[0]))
                gallery_sources = images[1:MAX_GALLERY]
            else:
                self.log("No image found for a preview.")

            extra_previews = []
            for src in gallery_sources:
                copy = self._make_preview_copy(src)
                if copy:
                    extra_previews.append(copy)

            if len(images) > MAX_GALLERY:
                self.log("Note: only the first %d images are shown in the gallery "
                         "(all files are still uploaded as content)." % MAX_GALLERY)

            bUploadSuccess, _pid, url = steam.upload(
                only_content=params["only_content"],
                file_id=params["file_id"],
                title=params["title"],
                description=params["description"],
                content_folder=content,
                preview_file=main_preview,
                extra_previews=extra_previews,
                visibility=params["visibility"],
                tags=params["tags"],
                progress_cb=self.set_progress,
            )
            self.after(0, lambda u=url,S=bUploadSuccess: self._on_finish(bSuccess=S, url=u))
        except Exception as exc:
            self.log("ERROR: %s" % exc)
            self.log(traceback.format_exc())
            self.after(0, lambda e=exc: messagebox.showerror("Error", str(e)))
        finally:
            if steam:
                steam.shutdown()
            self._cleanup_temp()
            self.after(0, lambda: self._on_worker_finish())

    def _on_worker_finish(self):
        self.upload_btn.configure(state="normal")
        self.update_btn.configure(state="normal")

    def _on_finish(self, bSuccess, url):
        self.progress.set(1)
        if bSuccess == True:
            if messagebox.askyesno(
                "Success",
                "Item uploaded successfully!\n\n%s\n\nOpen the item page in your browser?" % url,
            ):
                import webbrowser
                webbrowser.open(url)
        else:
            messagebox.showerror("Error", "Item id is not valid, update content failed.")

    def _cleanup_temp(self):
        if self._temp_dir and os.path.isdir(self._temp_dir):
            shutil.rmtree(self._temp_dir, ignore_errors=True)
        self._temp_dir = None
        for path in self._temp_previews:
            if os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        self._temp_previews = []

    # ------------------------------------------------------------------ #
    # Thread-safe GUI updates
    # ------------------------------------------------------------------ #
    def log(self, msg):
        self.after(0, self._append_log, msg)

    def _append_log(self, msg):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", str(msg) + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def set_progress(self, processed, total):
        frac = 0 if not total else min(1.0, processed / total)
        self.after(0, lambda: self.progress.set(frac))


if __name__ == "__main__":
    UploaderApp().mainloop()
