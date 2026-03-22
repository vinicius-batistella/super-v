#!/usr/bin/env python3
"""
Super-V v4: Clipboard History Manager for Linux (X11)

Replicates Windows' Win+V clipboard history functionality.
Press Super+V to open the clipboard history popup.

v3 additions: image clipboard support — copies of images are stored
as PNG files and shown as thumbnails in the history popup.
v4 additions: white glow shadow on entry boxes when hovered.
"""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango
from Xlib import X, XK, display
from Xlib.ext import record
from Xlib.protocol import rq

MAX_HISTORY = 50
DATA_DIR = os.path.expanduser("~/.local/share/super-v")
IMAGE_DIR = os.path.join(DATA_DIR, "images")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
POLL_INTERVAL_MS = 500
WINDOW_WIDTH = 420
WINDOW_HEIGHT = 520
THUMB_MAX_H = 87


# ---------------------------------------------------------------------------
#  Persistent clipboard history storage (text + images)
# ---------------------------------------------------------------------------

class HistoryStore:
    def __init__(self):
        self.entries = []
        self._load()

    def _load(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        os.makedirs(IMAGE_DIR, exist_ok=True)
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r") as f:
                    self.entries = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.entries = []
        self._prune_orphan_images()

    def _save(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        try:
            with open(HISTORY_FILE, "w") as f:
                json.dump(self.entries, f, indent=2)
        except IOError:
            pass

    def _prune_orphan_images(self):
        """Remove image files on disk that no longer belong to any entry."""
        referenced = {
            e.get("image_path")
            for e in self.entries
            if e.get("type") == "image" and e.get("image_path")
        }
        try:
            for fname in os.listdir(IMAGE_DIR):
                fpath = os.path.join(IMAGE_DIR, fname)
                if fpath not in referenced:
                    os.remove(fpath)
        except OSError:
            pass

    # -- add ----------------------------------------------------------------

    def add_text(self, text):
        if not text or not text.strip():
            return
        self.entries = [
            e for e in self.entries
            if not (e.get("type", "text") == "text" and e.get("text") == text)
        ]
        entry = {
            "type": "text",
            "text": text,
            "timestamp": datetime.now().isoformat(),
            "pinned": False,
        }
        self._insert_after_pinned(entry)

    def add_image(self, pixbuf):
        """Save a GdkPixbuf as PNG, deduplicate by content hash."""
        ok, png_data = pixbuf.save_to_bufferv("png", [], [])
        if not ok:
            return
        img_hash = hashlib.sha256(png_data).hexdigest()[:16]
        self.entries = [
            e for e in self.entries
            if not (e.get("type") == "image" and e.get("image_hash") == img_hash)
        ]
        filename = f"{img_hash}.png"
        filepath = os.path.join(IMAGE_DIR, filename)
        os.makedirs(IMAGE_DIR, exist_ok=True)
        try:
            with open(filepath, "wb") as f:
                f.write(png_data)
        except IOError:
            return

        w = pixbuf.get_width()
        h = pixbuf.get_height()
        entry = {
            "type": "image",
            "image_path": filepath,
            "image_hash": img_hash,
            "width": w,
            "height": h,
            "timestamp": datetime.now().isoformat(),
            "pinned": False,
        }
        self._insert_after_pinned(entry)

    def _insert_after_pinned(self, entry):
        pinned_count = sum(1 for e in self.entries if e.get("pinned"))
        self.entries.insert(pinned_count, entry)
        self._enforce_limit()
        self._save()

    # -- remove / pin / clear -----------------------------------------------

    def remove(self, index):
        if 0 <= index < len(self.entries):
            entry = self.entries.pop(index)
            self._delete_image_file(entry)
            self._save()

    def toggle_pin(self, index):
        if 0 <= index < len(self.entries):
            self.entries[index]["pinned"] = not self.entries[index].get("pinned", False)
            pinned = [e for e in self.entries if e.get("pinned")]
            unpinned = [e for e in self.entries if not e.get("pinned")]
            self.entries = pinned + unpinned
            self._save()

    def clear_unpinned(self):
        removed = [e for e in self.entries if not e.get("pinned")]
        self.entries = [e for e in self.entries if e.get("pinned")]
        for e in removed:
            self._delete_image_file(e)
        self._save()

    # -- search -------------------------------------------------------------

    def search(self, query):
        if not query:
            return [(i, e) for i, e in enumerate(self.entries)]
        q = query.lower()
        results = []
        for i, e in enumerate(self.entries):
            if e.get("type") == "image":
                if q in "image" or q in "picture" or q in "screenshot":
                    results.append((i, e))
            else:
                if q in e.get("text", "").lower():
                    results.append((i, e))
        return results

    # -- helpers ------------------------------------------------------------

    def _enforce_limit(self):
        pinned = [e for e in self.entries if e.get("pinned")]
        unpinned = [e for e in self.entries if not e.get("pinned")]
        overflow = unpinned[MAX_HISTORY:]
        for e in overflow:
            self._delete_image_file(e)
        self.entries = pinned + unpinned[:MAX_HISTORY]

    @staticmethod
    def _delete_image_file(entry):
        if entry.get("type") == "image" and entry.get("image_path"):
            try:
                os.remove(entry["image_path"])
            except OSError:
                pass


# ---------------------------------------------------------------------------
#  GTK CSS Theme (Catppuccin Mocha-inspired dark palette)
# ---------------------------------------------------------------------------

CSS = """
window.super-v-popup {
    background-color: #1e1e2e;
    border: 1px solid #45475a;
}
.sv-header {
    padding: 14px 16px 8px 16px;
}
.sv-title {
    color: #cdd6f4;
    font-size: 15px;
    font-weight: bold;
    letter-spacing: 0.5px;
}
.sv-search {
    margin: 0 16px 8px 16px;
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 8px;
    color: #cdd6f4;
    padding: 8px 12px;
    font-size: 13px;
    caret-color: #89b4fa;
}
.sv-search image {
    color: #6c7086;
}
.sv-list {
    background-color: transparent;
}
.sv-list row {
    padding: 2px 12px;
    background-color: transparent;
}
.sv-list row:hover {
    background-color: transparent;
}
.sv-entry {
    background-color: #181825;
    border-radius: 8px;
    padding: 10px 14px;
    border: 1px solid #313244;
}
.sv-entry.hovered {
    border: 1px solid rgba(205, 214, 244, 0.4);
    box-shadow: 0 0 8px rgba(205, 214, 244, 0.25);
}
.sv-entry-text {
    color: #cdd6f4;
    font-size: 13px;
}
.sv-entry-meta {
    color: #6c7086;
    font-size: 11px;
}
.sv-pin-label {
    color: #f9e2af;
    font-size: 11px;
    font-weight: bold;
}
.sv-action-btn {
    background: transparent;
    border: none;
    border-radius: 4px;
    padding: 2px 6px;
    min-height: 0;
    min-width: 0;
    color: #6c7086;
    font-size: 13px;
}
.sv-action-btn:hover {
    background-color: #313244;
}
.sv-action-btn.pin-active {
    color: #f9e2af;
}
.sv-action-btn.del-hover:hover {
    color: #f38ba8;
}
.sv-empty {
    color: #6c7086;
    font-size: 14px;
    padding: 40px;
}
.sv-thumb {
    border: 1px solid #45475a;
    border-radius: 4px;
}
"""


# ---------------------------------------------------------------------------
#  Popup window
# ---------------------------------------------------------------------------

class PopupWindow(Gtk.Window):
    FOCUS_GRACE_MS = 800

    def __init__(self, store, on_select):
        super().__init__()
        self.store = store
        self.on_select = on_select
        self._show_time = 0.0
        self._prev_window_id = None

        self.set_title("Super-V")
        self.set_default_size(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_above(True)
        self.set_type_hint(Gdk.WindowTypeHint.POPUP_MENU)
        self.get_style_context().add_class("super-v-popup")

        self._build_ui()
        self.connect("key-press-event", self._on_key_press)
        self.connect("button-press-event", self._on_button_press)

    # -- UI construction -----------------------------------------------------

    def _build_ui(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(vbox)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        header.get_style_context().add_class("sv-header")

        title = Gtk.Label(label="Clipboard History")
        title.get_style_context().add_class("sv-title")
        title.set_halign(Gtk.Align.START)
        header.pack_start(title, True, True, 0)

        vbox.pack_start(header, False, False, 0)

        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Type to search\u2026")
        self.search.get_style_context().add_class("sv-search")
        self.search.connect("search-changed", self._on_search)
        vbox.pack_start(self.search, False, False, 0)

        self.stack = Gtk.Stack()
        vbox.pack_start(self.stack, True, True, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.get_style_context().add_class("sv-list")
        scroll.add(self.listbox)
        self.stack.add_named(scroll, "list")

        empty = Gtk.Label(label="No clipboard entries yet.\nCopy something to get started!")
        empty.get_style_context().add_class("sv-empty")
        empty.set_justify(Gtk.Justification.CENTER)
        self.stack.add_named(empty, "empty")

    def _build_row(self, real_idx, entry):
        entry_type = entry.get("type", "text")
        if entry_type == "image":
            return self._build_image_row(real_idx, entry)
        return self._build_text_row(real_idx, entry)

    def _build_text_row(self, real_idx, entry):
        row = Gtk.ListBoxRow()
        ebox = Gtk.EventBox()
        ebox.set_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        ebox.connect(
            "button-press-event",
            lambda w, ev, idx=real_idx: self._select(idx),
        )

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.get_style_context().add_class("sv-entry")

        ebox.connect("enter-notify-event", self._on_row_enter, card)
        ebox.connect("leave-notify-event", self._on_row_leave, card)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        preview = entry.get("text", "").replace("\n", " \u23ce ").strip()
        if len(preview) > 80:
            preview = preview[:77] + "\u2026"
        lbl = Gtk.Label(label=preview)
        lbl.set_halign(Gtk.Align.START)
        lbl.set_hexpand(True)
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
        lbl.set_max_width_chars(45)
        lbl.get_style_context().add_class("sv-entry-text")
        top.pack_start(lbl, True, True, 0)

        self._append_action_buttons(top, real_idx, entry)
        card.pack_start(top, False, False, 0)

        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        time_str = self._format_time(entry)
        text = entry.get("text", "")
        meta = Gtk.Label(label=f"{time_str}  \u00b7  {len(text)} chars")
        meta.set_halign(Gtk.Align.START)
        meta.get_style_context().add_class("sv-entry-meta")
        bottom.pack_start(meta, True, True, 0)

        if entry.get("pinned"):
            pin_lbl = Gtk.Label(label="PINNED")
            pin_lbl.get_style_context().add_class("sv-pin-label")
            bottom.pack_end(pin_lbl, False, False, 0)

        card.pack_start(bottom, False, False, 0)
        ebox.add(card)
        row.add(ebox)
        return row

    def _build_image_row(self, real_idx, entry):
        row = Gtk.ListBoxRow()
        ebox = Gtk.EventBox()
        ebox.set_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        ebox.connect(
            "button-press-event",
            lambda w, ev, idx=real_idx: self._select(idx),
        )

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.get_style_context().add_class("sv-entry")

        ebox.connect("enter-notify-event", self._on_row_enter, card)
        ebox.connect("leave-notify-event", self._on_row_leave, card)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        thumb = self._make_thumbnail(entry)
        if thumb:
            thumb.set_halign(Gtk.Align.START)
            thumb.get_style_context().add_class("sv-thumb")
            top.pack_start(thumb, True, True, 0)

        self._append_action_buttons(top, real_idx, entry)
        card.pack_start(top, False, False, 0)

        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        time_str = self._format_time(entry)
        meta = Gtk.Label(label=time_str)
        meta.set_halign(Gtk.Align.START)
        meta.get_style_context().add_class("sv-entry-meta")
        bottom.pack_start(meta, True, True, 0)

        if entry.get("pinned"):
            pin_lbl = Gtk.Label(label="PINNED")
            pin_lbl.get_style_context().add_class("sv-pin-label")
            bottom.pack_end(pin_lbl, False, False, 0)

        card.pack_start(bottom, False, False, 0)
        ebox.add(card)
        row.add(ebox)
        return row

    def _make_thumbnail(self, entry):
        image_path = entry.get("image_path", "")
        if not image_path or not os.path.exists(image_path):
            return None
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(image_path)
            pixbuf = self._scale_pixbuf(pixbuf, THUMB_MAX_H)
            img = Gtk.Image.new_from_pixbuf(pixbuf)
            return img
        except Exception:
            return None

    @staticmethod
    def _scale_pixbuf(pixbuf, max_h):
        w = pixbuf.get_width()
        h = pixbuf.get_height()
        if h <= max_h:
            return pixbuf
        ratio = max_h / h
        new_w = max(int(w * ratio), 1)
        new_h = max(int(h * ratio), 1)
        return pixbuf.scale_simple(new_w, new_h, GdkPixbuf.InterpType.BILINEAR)

    def _append_action_buttons(self, box, real_idx, entry):
        del_btn = Gtk.Button(label="\u2715")
        del_btn.get_style_context().add_class("sv-action-btn")
        del_btn.get_style_context().add_class("del-hover")
        del_btn.set_tooltip_text("Delete")
        del_btn.set_can_focus(False)
        del_btn.connect("clicked", lambda w, idx=real_idx: self._delete(idx))
        box.pack_end(del_btn, False, False, 0)

        pin_char = "\u2605" if entry.get("pinned") else "\u2606"
        pin_btn = Gtk.Button(label=pin_char)
        pin_btn.get_style_context().add_class("sv-action-btn")
        if entry.get("pinned"):
            pin_btn.get_style_context().add_class("pin-active")
        pin_btn.set_tooltip_text("Unpin" if entry.get("pinned") else "Pin")
        pin_btn.set_can_focus(False)
        pin_btn.connect("clicked", lambda w, idx=real_idx: self._pin(idx))
        box.pack_end(pin_btn, False, False, 0)

    @staticmethod
    def _on_row_enter(widget, event, card):
        card.get_style_context().add_class("hovered")

    @staticmethod
    def _on_row_leave(widget, event, card):
        card.get_style_context().remove_class("hovered")

    @staticmethod
    def _format_time(entry):
        try:
            ts = datetime.fromisoformat(entry["timestamp"])
            return ts.strftime("%b %d, %H:%M")
        except (ValueError, KeyError):
            return ""

    # -- Refresh / populate --------------------------------------------------

    def refresh(self, query=""):
        for child in self.listbox.get_children():
            self.listbox.remove(child)
        results = self.store.search(query)
        if not results:
            self.stack.set_visible_child_name("empty")
            return
        self.stack.set_visible_child_name("list")
        for real_idx, entry in results:
            self.listbox.add(self._build_row(real_idx, entry))
        self.listbox.show_all()

    def show_popup(self):
        try:
            result = subprocess.run(
                ["xdotool", "getactivewindow"],
                capture_output=True, text=True, timeout=1,
            )
            self._prev_window_id = result.stdout.strip() or None
        except Exception:
            self._prev_window_id = None

        self.search.set_text("")
        self.refresh()
        screen = self.get_screen()
        monitor_nr = screen.get_primary_monitor()
        geo = screen.get_monitor_geometry(monitor_nr)
        win_x = geo.x + (geo.width - WINDOW_WIDTH) // 2
        win_y = geo.y + (geo.height - WINDOW_HEIGHT) // 2 - 40
        self.move(win_x, win_y)
        self._show_time = time.monotonic()
        self.show_all()
        self.present()
        self.search.grab_focus()
        GLib.timeout_add(100, self._grab_seat)

    # -- Event handlers ------------------------------------------------------

    def _select(self, idx):
        if 0 <= idx < len(self.store.entries):
            self.on_select(self.store.entries[idx])
            self.dismiss()

    def _delete(self, idx):
        self.store.remove(idx)
        self.refresh(self.search.get_text())

    def _pin(self, idx):
        self.store.toggle_pin(idx)
        self.refresh(self.search.get_text())

    def _on_search(self, entry):
        self.refresh(entry.get_text())

    def _on_key_press(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.dismiss()
            return True
        return False

    def _on_button_press(self, widget, event):
        alloc = self.get_allocation()
        if event.x < 0 or event.y < 0 or event.x > alloc.width or event.y > alloc.height:
            self.dismiss()
            return True
        return False

    def _grab_seat(self):
        gdk_window = self.get_window()
        if not gdk_window:
            return False
        seat = Gdk.Display.get_default().get_default_seat()
        status = seat.grab(
            gdk_window,
            Gdk.SeatCapabilities.ALL,
            True,
            None, None, None,
        )
        if status != Gdk.GrabStatus.SUCCESS:
            GLib.timeout_add(100, self._grab_seat)
        return False

    def _ungrab_seat(self):
        seat = Gdk.Display.get_default().get_default_seat()
        seat.ungrab()

    def dismiss(self):
        self._ungrab_seat()
        self.hide()


# ---------------------------------------------------------------------------
#  Global hotkey listener (X11 XRecord – passive, no key grabbing)
# ---------------------------------------------------------------------------

class XHotkeyThread(threading.Thread):
    """Monitors Super+V via the XRecord extension without grabbing the key."""

    MOD4_KEYSYMS = {"Super_L", "Super_R"}

    def __init__(self, callback):
        super().__init__(daemon=True)
        self.callback = callback

    def run(self):
        local_dpy = display.Display()
        record_dpy = display.Display()

        self._v_keycode = local_dpy.keysym_to_keycode(XK.string_to_keysym("v"))
        self._super_keycodes = set()
        for name in self.MOD4_KEYSYMS:
            kc = local_dpy.keysym_to_keycode(XK.string_to_keysym(name))
            if kc:
                self._super_keycodes.add(kc)

        self._super_held = False
        self._local_dpy = local_dpy

        ctx = record_dpy.record_create_context(
            0,
            [record.AllClients],
            [
                {
                    "core_requests": (0, 0),
                    "core_replies": (0, 0),
                    "ext_requests": (0, 0, 0, 0),
                    "ext_replies": (0, 0, 0, 0),
                    "delivered_events": (0, 0),
                    "device_events": (X.KeyPress, X.KeyRelease),
                    "errors": (0, 0),
                    "client_started": False,
                    "client_died": False,
                }
            ],
        )

        record_dpy.record_enable_context(ctx, self._record_callback)

    def _record_callback(self, reply):
        if reply.category != record.FromServer:
            return
        if reply.client_swapped:
            return

        data = reply.data
        while len(data):
            event, data = rq.EventField(None).parse_binary_value(
                data, self._local_dpy.display, None, None
            )

            if event.type == X.KeyPress:
                if event.detail in self._super_keycodes:
                    self._super_held = True
                elif event.detail == self._v_keycode and self._super_held:
                    GLib.idle_add(self.callback)

            elif event.type == X.KeyRelease:
                if event.detail in self._super_keycodes:
                    self._super_held = False


# ---------------------------------------------------------------------------
#  Application
# ---------------------------------------------------------------------------

class SuperVApp:
    TERMINAL_WM_CLASSES = {
        "gnome-terminal-server", "gnome-terminal",
        "xterm", "uxterm",
        "konsole",
        "terminator",
        "alacritty",
        "kitty",
        "xfce4-terminal",
        "tilix",
        "mate-terminal",
        "lxterminal",
        "sakura",
        "urxvt", "rxvt",
        "st", "st-256color",
        "wezterm", "org.wezfurlong.wezterm",
        "foot",
        "guake",
        "tilda",
        "yakuake",
        "cool-retro-term",
        "terminology",
        "hyper",
        "tabby",
        "rio",
        "contour",
        "black-box",
        "kgx",
        "deepin-terminal",
        "qterminal",
        "terminal", "x-terminal-emulator",
    }

    def __init__(self):
        self.store = HistoryStore()
        self.clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        self.last_text = self.clipboard.wait_for_text() or ""
        self.last_image_hash = self._current_image_hash()
        self._skip_next_poll = False

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        self.popup = PopupWindow(self.store, self._on_paste)
        self.popup.connect("delete-event", lambda w, e: w.dismiss() or True)

        GLib.timeout_add(POLL_INTERVAL_MS, self._poll_clipboard)

        self.hotkey_thread = XHotkeyThread(self._toggle_popup)
        self.hotkey_thread.start()

    def _current_image_hash(self):
        pixbuf = self.clipboard.wait_for_image()
        if pixbuf is None:
            return None
        ok, png_data = pixbuf.save_to_bufferv("png", [], [])
        if not ok:
            return None
        return hashlib.sha256(png_data).hexdigest()[:16]

    @classmethod
    def _is_terminal(cls, window_id):
        try:
            result = subprocess.run(
                ["xprop", "-id", window_id, "WM_CLASS"],
                capture_output=True, text=True, timeout=1,
            )
            line = result.stdout.strip()
            if "=" not in line:
                return False
            raw = line.split("=", 1)[1]
            parts = [p.strip().strip('"').lower() for p in raw.split(",")]
            return any(p in cls.TERMINAL_WM_CLASSES for p in parts)
        except Exception:
            return False

    def _poll_clipboard(self):
        if self._skip_next_poll:
            self._skip_next_poll = False
            return True

        text = self.clipboard.wait_for_text()
        if text and text != self.last_text:
            self.last_text = text
            self.last_image_hash = None
            self.store.add_text(text)
            return True

        img_hash = self._current_image_hash()
        if img_hash and img_hash != self.last_image_hash:
            self.last_image_hash = img_hash
            self.last_text = ""
            pixbuf = self.clipboard.wait_for_image()
            if pixbuf:
                self.store.add_image(pixbuf)

        return True

    def _toggle_popup(self):
        if self.popup.get_visible():
            self.popup.dismiss()
        else:
            self.popup.show_popup()

    def _on_paste(self, entry):
        entry_type = entry.get("type", "text")
        self._skip_next_poll = True

        if entry_type == "image":
            image_path = entry.get("image_path", "")
            if image_path and os.path.exists(image_path):
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(image_path)
                self.clipboard.set_image(pixbuf)
                self.clipboard.store()
                self.last_image_hash = entry.get("image_hash")
                self.last_text = ""
        else:
            text = entry.get("text", "")
            self.last_text = text
            self.last_image_hash = None
            self.clipboard.set_text(text, -1)
            self.clipboard.store()

        prev_win = self.popup._prev_window_id
        threading.Thread(
            target=self._paste_sequence, args=(prev_win,), daemon=True,
        ).start()

    def _paste_sequence(self, window_id):
        time.sleep(0.15)

        if window_id:
            subprocess.run(
                ["xdotool", "windowactivate", "--sync", window_id],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=2,
            )
            time.sleep(0.3)

        is_term = window_id and self._is_terminal(window_id)
        keys = "ctrl+shift+v" if is_term else "ctrl+v"

        subprocess.run(
            ["xdotool", "key", "--clearmodifiers", keys],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=2,
        )

    def run(self):
        Gtk.main()


# ---------------------------------------------------------------------------
#  Entry point
# ---------------------------------------------------------------------------

def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    if not os.environ.get("DISPLAY"):
        print("Error: No X11 display found. Super-V requires X11.", file=sys.stderr)
        sys.exit(1)

    print("Super-V v4 clipboard history manager started.")
    print("Press Super+V to open clipboard history.")
    print("Text and image clipboard content is now tracked.")
    app = SuperVApp()
    app.run()


if __name__ == "__main__":
    main()
