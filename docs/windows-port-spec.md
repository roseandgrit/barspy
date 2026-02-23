# Windows Port Spec

macOS-only for now. If there's demand, a Windows version is feasible.

## What Ports Directly

- **Hook/state architecture** — `sessions.json`, `config.json`, hook script, PID cleanup logic all work cross-platform. This is the bulk of the app's brain.
- **Shape math** — star path generation, heart Bezier curves, check mark geometry. Same trigonometry, different drawing API.
- **Config system** — `load_config()` / `save_config()`, validation, presets.

## What Needs Rewriting

| macOS | Windows replacement |
|-------|-------------------|
| rumps (system tray) | pystray |
| AppKit/NSBezierPath (drawing) | Pillow/PIL ImageDraw |
| py2app (bundling) | PyInstaller |
| `os.kill(pid, 0)` (PID check) | psutil |
| `~/.kizwatch/` | `%APPDATA%/kizwatch/` |

## Architecture Options

**Option A: Separate codebases** (recommended for now)
- macOS version stays native Cocoa — pixel-perfect menu bar integration
- Windows version uses pystray + Pillow
- Shared: hook script, state file format, config format
- Con: features get implemented twice

**Option B: Single pystray codebase**
- One codebase for both platforms
- Pro: new features ship everywhere at once
- Con: loses native macOS polish (raster vs vector rendering, no native checkmarks in menus)
- Con: tends to accumulate `if platform == "darwin"` blocks anyway

## Menu System Notes

pystray's menu is more basic than rumps:
- No `state = 1` checkmark support natively — use "✓ " prefix in label text
- Submenus supported via `pystray.Menu` nesting
- No modal dialogs (like rumps.Window) — would need tkinter or similar for emoji/hex input

## Estimated Scope

Not a ground-up rewrite. It's translating `kizwatch.py` against a different rendering backend — same structure, different imports. The hook script (`kizwatch_hook.py`) works as-is on Windows with minor path adjustments.
