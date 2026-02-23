# KizWatch

Menu bar agent monitor for Claude Code sessions. Shows colored stars — one per active session.

## How It Works

**Hook-driven status** (learned from AgentWatch/cc-status-bar source):
- Hooks in `~/.claude/settings.json` fire on Claude Code events
- Hook script (`~/.claude/scripts/kizwatch_hook.py`) writes status directly to state file
- App (`kizwatch.py`) polls state file every 1 second, renders stars

**No timestamp-based guessing.** Status is set explicitly by the hook:
- `prompt-submit`, `tool-start`, `tool-complete` → `"working"` (teal)
- `stop` → `"idle"` (pastel lavender)
- `session-start` → `"idle"` (just opened, waiting for input)
- `session-end` → removes session

## Architecture

| Component | Path | What it does |
|-----------|------|-------------|
| App | `kizwatch.py` | rumps menu bar app, polls state, renders stars |
| Hook | `~/.claude/scripts/kizwatch_hook.py` | Sets session status on hook events |
| State | `~/.kizwatch/sessions.json` | JSON with session_id → status/pid/project |
| Settings | `~/.claude/settings.json` | Hook wiring (6 events) |
| Bundle | `/Applications/KizWatch.app` | py2app build, signed with Apple Dev cert |
| LaunchAgent | `~/Library/LaunchAgents/com.kizwatch.plist` | Auto-start on login |

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

Config stored at `~/.kizwatch/config.json`:
```json
{
  "shape": "star",
  "emoji": null,
  "color_working": [0.0, 0.85, 0.85],
  "color_idle": [0.706, 0.624, 0.863]
}
```
Validated on load; bad values fall back to defaults.

## Safety Features

- **PID liveness check:** Every poll checks if session PID is alive. Dead process → star removed within 1s.
- **PID dedup:** If multiple session IDs share a PID (from /exit + resume), keeps only the most recently active.
- **30-min timeout:** Fallback cleanup for sessions that somehow survive both SessionEnd hook and PID death.

## Build & Deploy

```bash
cd ~/ClaudeProjects/Personal/KizWatch
.venv/bin/python setup.py py2app
# Kill running instance, swap bundle, sign, launch:
kill -9 $(pgrep -f KizWatch)
mv /Applications/KizWatch.app /Applications/KizWatch.old.app
cp -R dist/kizwatch.app /Applications/KizWatch.app
codesign --force --deep --sign "Apple Development: buytheclouds@gmail.com (SU2P3GG54F)" /Applications/KizWatch.app
# Trash old, launch new
osascript -e 'tell application "Finder" to delete POSIX file "/Applications/KizWatch.old.app"'
open /Applications/KizWatch.app
```

**Important:** Must rebuild with py2app after any code change — the bundle is self-contained. Hook changes (`kizwatch_hook.py`) take effect immediately (no rebuild needed).

## Dependencies

- Python 3.14 (venv at `.venv/`)
- rumps, pyobjc (AppKit, Foundation)
- py2app (build only)

## History

Built 2026-02-22 as replacement for AgentWatch (cc-status-bar) which had a stale indicator bug (menu bar icons persisting after sessions end). Key insight from reading AgentWatch source: status should be set directly by hooks, not guessed from timestamps.

## Current State (2026-02-23)

Working. Shape picker (star/dot/heart/check/emoji) and color picker (8 presets + custom hex) added. App launches from Finder (py2app + Apple Dev signing). LaunchAgent enabled for auto-start on login.

## Known Issues / Next Steps

- Name TBD — "KizWatch" is a working title. Candidates: Glint, Blipbeat, Flicker.
- The `cc-status-bar-1.8.7/` folder in this repo is AgentWatch source used as reference — can be deleted.
