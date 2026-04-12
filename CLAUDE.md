# Bar Spy

Menu bar agent monitor for Claude Code and Codex sessions. Shows colored indicators — one per active session.

## How It Works

**Two agent types, one unified display:**

### Claude Code (hook-driven)
- Hooks in `~/.claude/settings.json` fire on Claude Code events
- Hook script (`~/.claude/scripts/barspy_hook.py`) writes status to `~/.barspy/sessions.json`
- Events: `prompt-submit`, `tool-start`, `tool-complete` → working; `stop` → idle; `session-end` → removed

### Codex (SQLite polling)
- App polls `~/.codex/logs_1.sqlite` + `state_5.sqlite` every 1 second
- No Codex configuration changes needed — reads existing log data
- State detection from log entries: `response.completed` / `turn/completed` → idle; streaming/tool events → working
- Sessions are in-memory only (not written to sessions.json)
- If `~/.codex/` doesn't exist, Codex scanning is silently skipped

## Architecture

| Component | Path | What it does |
|-----------|------|-------------|
| App | `barspy.py` | rumps menu bar app, polls state, renders indicators |
| Claude Hook | `~/.claude/scripts/barspy_hook.py` | Sets Claude session status on hook events |
| Claude State | `~/.barspy/sessions.json` | JSON with session_id → status/pid/project |
| Codex Logs | `~/.codex/logs_1.sqlite` | Codex activity logs (read-only) |
| Codex State | `~/.codex/state_5.sqlite` | Codex thread metadata (read-only) |
| Settings | `~/.claude/settings.json` | Claude hook wiring (6 events) |
| Bundle | `/Applications/Bar Spy.app` | py2app build, signed with Apple Dev cert |
| LaunchAgent | `~/Library/LaunchAgents/com.barspy.plist` | Auto-start on login |
| Icon | `assets/BarSpy.icns` | App icon (beret spy girl) |

## Colors

- **Teal** `(0.0, 0.85, 0.85)` — working (tool running, processing prompt)
- **Amber** `(1.0, 0.75, 0.18)` — attention (likely waiting for permission prompt or user input)
- **Pastel lavender** `(0.706, 0.624, 0.863)` / `#B49FDC` — idle (waiting for user input)
- **Black outline** — 0.75pt stroke for visibility

### Attention State

Timer-based promotion to "attention" (amber) when a session has been idle too long:
- **Claude:** promotes after `tool-complete` with no new events for configured delay
- **Codex:** promotes after `turn-complete` (response finished) with no new activity for configured delay
- Never promotes during active work (streaming, tool calls, extended thinking)

Configurable via **Attention Delay** menu: Off / 2 minutes / 5 minutes (default) / 10 minutes.

**Dismissal:** Attention resets when the user clicks the notification or clicks a session item in the menu. Tracked via `attention_dismissed_at` in session state — suppresses attention until new `last_active` activity arrives.

## Shape Picker

Users pick their indicator shape from the menu bar dropdown: **Shape >** submenu.

| Shape | How it's drawn |
|-------|---------------|
| **Star** (default) | 5-pointed NSBezierPath, filled + outlined |
| **Dot** | Circle via `bezierPathWithOvalInRect_`, filled + outlined |
| **Heart** | 4-segment cubic Bezier, filled + outlined |
| **Check** | Stroked polyline (3 points), thick colored stroke over black |
| **Emoji** | Any emoji via NSAttributedString — no color tinting, native emoji colors |

**Color picker:** "Working Color", "Attention Color", and "Idle Color" submenus with 8 presets + custom hex input + reset to default.

Config stored at `~/.barspy/config.json`:
```json
{
  "shape": "star",
  "emoji": null,
  "color_working": [0.0, 0.85, 0.85],
  "color_attention": [1.0, 0.75, 0.18],
  "color_idle": [0.706, 0.624, 0.863],
  "throb_speed": "medium",
  "notifications": true,
  "attention_delay": "5min"
}
```
Validated on load; bad values fall back to defaults.

## Safety Features

- **PID liveness check:** Every poll checks if session PID is alive. Dead Claude process → indicator removed within 1s. Codex sessions track the app-server PID — if Codex.app quits, all Codex indicators are removed.
- **PID dedup:** If multiple Claude session IDs share a PID (from /exit + resume), keeps only the most recently active.
- **30-min timeout:** Fallback cleanup for sessions with no activity. Applies to both Claude (JSON) and Codex (SQLite log age).
- **Graceful degradation:** If `~/.codex/` doesn't exist or SQLite is locked/corrupt, Codex scanning is silently skipped.

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

Desktop notifications fire on status transitions. Toggle on/off from the menu bar dropdown. Uses `rumps.notification()` with sound.

- **working → attention**: "Needs attention — [Claude/Codex] may be waiting for your input"
- **working/attention → idle**: "Session ready — [Claude/Codex] is waiting for your input"

**Click-to-activate:** Clicking a notification brings the session's app to the foreground.
- **Claude sessions:** Walks the process tree from the Claude Code PID to find the owning terminal/IDE (Warp, Cursor, VS Code, etc.).
- **Codex sessions:** Activates `Codex.app` directly via bundle ID (`com.openai.codex`).

Uses `activateWithOptions_` with AppleScript fallback for macOS 14+ compatibility. Debug logging at `~/.barspy/debug.log`.

## Build & Deploy

```bash
cd ~/ClaudeProjects/Personal/BarSpy
.venv/bin/python setup.py py2app
kill -9 $(pgrep -f "Bar Spy") 2>/dev/null
mv "/Applications/Bar Spy.app" "/tmp/BarSpy_old_$(date +%s).app"
cp -R "dist/Bar Spy.app" "/Applications/Bar Spy.app"
codesign --force --deep --sign "Your Developer ID" "/Applications/Bar Spy.app"
open "/Applications/Bar Spy.app"
```

**Note:** `rm -rf` is blocked by delete_guardian. Use `mv` to `/tmp` instead.

**Important:** Must rebuild with py2app after any code change — the bundle is self-contained. Hook changes (`barspy_hook.py`) take effect immediately (no rebuild needed).

## Repo

**GitHub:** `roseandgrit/barspy` (public) — https://github.com/roseandgrit/barspy

## Session Management

Each session in the dropdown is a submenu with:
- **Activate** — brings the session's terminal/IDE to the foreground
- **Remove** — dismisses the session from display (Claude: removed from JSON; Codex: in-memory ignore until restart)

**Quit Bar Spy** item at the bottom of the menu (explicit item, not rumps built-in — `menu.clear()` on every poll was swallowing the rumps quit button).

## Dependencies

- Python 3.14 (venv at `.venv/`)
- rumps, pyobjc (AppKit, Foundation)
- py2app (build only)

## Current Status

Fully working. Session removal + quit menu item on branch `feat/session-management`, pushed to origin. App rebuilt and running.

## Last Session

**2026-04-12** — Added session management: per-session Activate/Remove submenu, explicit Quit item. Fixed rumps quit button being swallowed by `menu.clear()`. Built, deployed, tested.

## Next Steps

- Merge `feat/session-management` to master
- Consider: "Kill Process" option (sends SIGTERM) in addition to "Remove" (display-only)
