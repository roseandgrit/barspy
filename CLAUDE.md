# Bar Spy

Menu bar agent monitor for Claude Code sessions. Shows colored indicators — one per active session.

## How It Works

**Hook-driven status:**
- Hooks in `~/.claude/settings.json` fire on Claude Code events
- Hook script (`~/.claude/scripts/barspy_hook.py`) writes status directly to state file
- App (`barspy.py`) polls state file every 1 second, renders indicators

**No timestamp-based guessing.** Status is set explicitly by the hook:
- `prompt-submit`, `tool-start`, `tool-complete` → `"working"` (teal)
- `stop` → `"idle"` (pastel lavender)
- `session-start` → `"idle"` (just opened, waiting for input)
- `session-end` → removes session

## Architecture

| Component | Path | What it does |
|-----------|------|-------------|
| App | `barspy.py` | rumps menu bar app, polls state, renders indicators |
| Hook | `~/.claude/scripts/barspy_hook.py` | Sets session status on hook events |
| State | `~/.barspy/sessions.json` | JSON with session_id → status/pid/project |
| Settings | `~/.claude/settings.json` | Hook wiring (6 events) |
| Bundle | `/Applications/Bar Spy.app` | py2app build, signed with Apple Dev cert |
| LaunchAgent | `~/Library/LaunchAgents/com.barspy.plist` | Auto-start on login |
| Icon | `assets/BarSpy.icns` | App icon (beret spy girl) |

## Colors

- **Teal** `(0.0, 0.85, 0.85)` — working (tool running, processing prompt)
- **Pastel lavender** `(0.706, 0.624, 0.863)` / `#B49FDC` — idle (waiting for user input)
- **Black outline** — 0.75pt stroke for visibility

## Shape Picker

Users pick their indicator shape from the menu bar dropdown: **Shape >** submenu.

| Shape | How it's drawn |
|-------|---------------|
| **Star** (default) | 5-pointed NSBezierPath, filled + outlined |
| **Dot** | Circle via `bezierPathWithOvalInRect_`, filled + outlined |
| **Heart** | 4-segment cubic Bezier, filled + outlined |
| **Check** | Stroked polyline (3 points), thick colored stroke over black |
| **Emoji** | Any emoji via NSAttributedString — no color tinting, native emoji colors |

**Color picker:** "Working Color" and "Idle Color" submenus with 8 presets + custom hex input + reset to default.

Config stored at `~/.barspy/config.json`:
```json
{
  "shape": "star",
  "emoji": null,
  "color_working": [0.0, 0.85, 0.85],
  "color_idle": [0.706, 0.624, 0.863],
  "throb_speed": "medium",
  "notifications": true
}
```
Validated on load; bad values fall back to defaults.

## Safety Features

- **PID liveness check:** Every poll checks if session PID is alive. Dead process → indicator removed within 1s.
- **PID dedup:** If multiple session IDs share a PID (from /exit + resume), keeps only the most recently active.
- **30-min timeout:** Fallback cleanup for sessions that somehow survive both SessionEnd hook and PID death.

## Throb Animation

Working indicators pulse smoothly when `throb_speed` is not `"off"`. The fill color alpha cycles on a sine wave (0.35–1.0) while the black outline stays solid. A 20fps animation timer (`@rumps.timer(0.05)`) handles rendering when throbbing; the 1s poll timer handles icon updates when not throbbing.

| Speed | Period |
|-------|--------|
| Off | No animation |
| Slow | 3 seconds |
| Medium (default) | 2 seconds |
| Fast | 1 second |

Emoji shapes skip the throb (native colors can't be alpha-tinted).

## Notifications

Desktop notification fires when a session transitions from working → idle ("Session ready — Waiting for your input"). Toggle on/off from the menu bar dropdown. Uses `rumps.notification()` with sound.

## Build & Deploy

```bash
cd ~/ClaudeProjects/Personal/KizWatch
.venv/bin/python setup.py py2app
kill -9 $(pgrep -f "Bar Spy") 2>/dev/null
rm -rf "/Applications/Bar Spy.app"
cp -R "dist/Bar Spy.app" "/Applications/Bar Spy.app"
codesign --force --deep --sign "Apple Development: buytheclouds@gmail.com (SU2P3GG54F)" "/Applications/Bar Spy.app"
open "/Applications/Bar Spy.app"
```

**Important:** Must rebuild with py2app after any code change — the bundle is self-contained. Hook changes (`barspy_hook.py`) take effect immediately (no rebuild needed).

## Repo

**GitHub:** `roseandgrit/barspy` (private) — https://github.com/roseandgrit/barspy

## Dependencies

- Python 3.14 (venv at `.venv/`)
- rumps, pyobjc (AppKit, Foundation)
- py2app (build only)
