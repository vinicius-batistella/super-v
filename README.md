# Super-V — Clipboard History for Linux

A lightweight clipboard history manager for Linux (X11) that brings Windows' **Win+V** experience to your desktop.  
Press **Super+V** to open a searchable popup of everything you've copied — text **and** images.

![Platform](https://img.shields.io/badge/platform-Linux%20(X11)-blue)
![Language](https://img.shields.io/badge/python-3.x-green)
![License](https://img.shields.io/badge/license-MIT-orange)

---

## Features

- **Super+V hotkey** — global shortcut opens the clipboard history popup
- **Text + Image support** — both text and image clipboard content are tracked
- **Thumbnail previews** — images are displayed as scaled-down thumbnails in the history list
- **Search** — type to instantly filter through your history
- **Pin entries** — keep frequently used clips at the top
- **Auto-paste** — selecting an entry copies it to clipboard and pastes it into the active window
- **Terminal-aware paste** — detects terminal emulators and uses Ctrl+Shift+V automatically
- **Persistent history** — clipboard entries survive restarts
- **Image deduplication** — identical images are stored only once (content-hash based)
- **Dark theme** — clean Catppuccin Mocha-inspired UI with glow-on-hover effects

---

## Quick Install

> **Requirements:** Debian/Ubuntu-based distro running X11 (Xorg). Wayland is not supported.

```bash
git clone https://github.com/vinicius-batistella/super-v
cd super-v
sudo ./install.sh
```

The installer will:

1. Install all system dependencies (`python3-gi`, `xdotool`, `xclip`, etc.)
2. Copy Super-V to `/opt/super-v/`
3. Add it to your application menu
4. Set it to autostart on login

### Start it now

```bash
python3 /opt/super-v/super-v.py
```

Then press **Super+V** to open the clipboard history popup.

### Manual dependency install (if not using the installer)

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-gdkpixbuf-2.0 python3-xlib xdotool xclip
```

---

## Uninstall

```bash
cd super-v
sudo ./uninstall.sh
```

To also remove your saved clipboard history:

```bash
rm -rf ~/.local/share/super-v/
```

---

## Keyboard Shortcuts

| Key               | Action                         |
|-------------------|--------------------------------|
| **Super+V**       | Open / close clipboard history |
| **Escape**        | Close popup                    |
| **Type anything** | Filter clipboard entries       |

---

## How It Works

1. A background process monitors the X11 clipboard every 500 ms
2. **Text** content is saved to a JSON file; **images** are saved as PNG files in `~/.local/share/super-v/images/`
3. Images are deduplicated by content hash — copying the same image again moves it to the top without creating a duplicate file
4. When **Super+V** is pressed, a GTK popup displays your history with thumbnails for images
5. Clicking an entry copies it back to the clipboard (text or image) and auto-pastes via `xdotool`

---

## File Locations

| Path                                    | Description                              |
|-----------------------------------------|------------------------------------------|
| `/opt/super-v/super-v.py`              | Main application (after install)         |
| `~/.local/share/super-v/history.json`  | Persistent clipboard history (metadata)  |
| `~/.local/share/super-v/images/`       | Stored clipboard images (PNG files)      |
| `~/.config/autostart/super-v.desktop`  | Autostart entry (created by installer)   |


---

## Notes

- Requires **X11** (Xorg). Wayland is not supported.
- The Super key grab may conflict with your desktop environment's own Super key binding. If Super+V doesn't work, check your DE's shortcut settings.
- Image files are automatically cleaned up when entries are deleted or when history overflows.
- History is capped at 50 entries.

---

## License

MIT License — free to use, modify, and distribute.
