#!/usr/bin/env python3
"""Bar Spy — Menu bar agent monitor for Claude Code and Codex sessions.

Single composite image approach: all session indicators rendered into one menu bar icon.
Claude Code: hook-driven status via ~/.barspy/sessions.json.
Codex: SQLite polling of ~/.codex/logs_1.sqlite + state_5.sqlite (no config changes needed).
Cleanup via session-end events + 30-minute inactivity timeout.
"""

import json
import math
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import objc
import rumps
from AppKit import (
    NSApplication,
    NSApplicationActivateIgnoringOtherApps,
    NSBezierPath,
    NSBitmapImageRep,
    NSCalibratedRGBColorSpace,
    NSColor,
    NSGraphicsContext,
    NSImage,
    NSRunningApplication,
    NSSound,
)
from Foundation import NSSize
from UserNotifications import (
    UNMutableNotificationContent,
    UNNotificationRequest,
    UNNotificationSound,
    UNUserNotificationCenter,
    UNAuthorizationOptionAlert,
    UNAuthorizationOptionSound,
)

STATE_FILE = Path.home() / ".barspy" / "sessions.json"
CONFIG_FILE = Path.home() / ".barspy" / "config.json"
DEAD_THRESHOLD = 1800.0  # 30 min no activity = assume session crashed

# Codex SQLite paths
CODEX_LOGS_DB = Path.home() / ".codex" / "logs_1.sqlite"
CODEX_STATE_DB = Path.home() / ".codex" / "state_5.sqlite"
ET = ZoneInfo("America/New_York")

ATTENTION_DELAYS = {
    "off": 0.0,
    "2min": 120.0,
    "5min": 300.0,
    "10min": 600.0,
}

ATTENTION_DELAY_LABELS = [
    ("off", "Off"),
    ("2min", "2 minutes"),
    ("5min", "5 minutes (default)"),
    ("10min", "10 minutes"),
]

LOG_FILE = Path.home() / ".barspy" / "debug.log"

# Default palette
DEFAULT_WORKING = (0.0, 0.85, 0.85)       # Teal — actively working
DEFAULT_ATTENTION = (1.0, 0.75, 0.18)     # Amber — needs user input (permission prompt, etc.)
DEFAULT_IDLE = (0.706, 0.624, 0.863)      # Pastel lavender #B49FDC — session alive, waiting

STAR_SIZE = 18
STAR_GAP = 3

DEFAULT_CONFIG = {
    "shape": "star",
    "emoji": None,
    "color_working": list(DEFAULT_WORKING),
    "color_attention": list(DEFAULT_ATTENTION),
    "color_idle": list(DEFAULT_IDLE),
    "throb_speed": "medium",
    "notifications": True,
    "app_icon": "spy-girl",
    "attention_delay": "5min",
}

APP_ICON_CHOICES = [
    ("spy-girl", "Spy Girl"),
    ("spy-guy", "Spy Guy"),
]

# Preset color swatches: (label, rgb_tuple)
COLOR_PRESETS = [
    ("Teal", (0.0, 0.85, 0.85)),
    ("Lavender", (0.706, 0.624, 0.863)),
    ("Green", (0.298, 0.788, 0.388)),
    ("Coral", (1.0, 0.44, 0.37)),
    ("Gold", (1.0, 0.78, 0.20)),
    ("Sky Blue", (0.40, 0.69, 1.0)),
    ("Pink", (1.0, 0.47, 0.66)),
    ("Orange", (1.0, 0.58, 0.0)),
]

BUILTIN_SHAPES = [
    ("star", "Star"),
    ("dot", "Dot"),
    ("heart", "Heart"),
    ("check", "Check"),
]

THROB_SPEEDS = {
    "off": 0.0,
    "slow": 2 * math.pi / 3.0,    # 3s period
    "medium": 2 * math.pi / 2.0,  # 2s period
    "fast": 2 * math.pi / 1.0,    # 1s period
}

THROB_LABELS = [
    ("off", "Off"),
    ("slow", "Slow"),
    ("medium", "Medium"),
    ("fast", "Fast"),
]


def _colors_close(a, b, tol=0.02):
    """Check if two RGB tuples are approximately equal."""
    return all(abs(x - y) < tol for x, y in zip(a, b))


def _valid_color(val):
    """Check if val is a valid RGB tuple/list of 3 floats in 0.0-1.0."""
    if not isinstance(val, (list, tuple)) or len(val) != 3:
        return False
    return all(isinstance(v, (int, float)) and 0.0 <= v <= 1.0 for v in val)


def load_config():
    try:
        if CONFIG_FILE.exists():
            data = json.loads(CONFIG_FILE.read_text())
            valid = {k for k, _ in BUILTIN_SHAPES} | {"emoji"}
            if data.get("shape") not in valid:
                data["shape"] = "star"
            if data["shape"] == "emoji" and not data.get("emoji"):
                data["shape"] = "star"
            # Ensure color fields exist and are valid
            if not _valid_color(data.get("color_working")):
                data["color_working"] = list(DEFAULT_WORKING)
            if not _valid_color(data.get("color_attention")):
                data["color_attention"] = list(DEFAULT_ATTENTION)
            if not _valid_color(data.get("color_idle")):
                data["color_idle"] = list(DEFAULT_IDLE)
            if data.get("throb_speed") not in THROB_SPEEDS:
                data["throb_speed"] = "medium"
            if data.get("attention_delay") not in ATTENTION_DELAYS:
                data["attention_delay"] = "5min"
            valid_icons = {k for k, _ in APP_ICON_CHOICES}
            if data.get("app_icon") not in valid_icons:
                data["app_icon"] = "spy-girl"
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return dict(DEFAULT_CONFIG)


def save_config(config):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False))


def make_star_path(cx, cy, outer_r, inner_r, points=5):
    """Create a star-shaped NSBezierPath."""
    path = NSBezierPath.bezierPath()
    angle_step = math.pi / points
    for i in range(points * 2):
        r = outer_r if i % 2 == 0 else inner_r
        angle = -math.pi / 2 + i * angle_step
        x = cx + r * math.cos(angle)
        y = cy + r * math.sin(angle)
        if i == 0:
            path.moveToPoint_((x, y))
        else:
            path.lineToPoint_((x, y))
    path.closePath()
    return path


def draw_star(cx, cy, color_rgb, size=STAR_SIZE, alpha=1.0):
    """Draw a star at the given center (must be in a graphics context)."""
    outer_r = size * 0.45
    inner_r = size * 0.18
    # Black outline
    NSColor.blackColor().set()
    outline = make_star_path(cx, cy, outer_r + 0.5, inner_r + 0.25)
    outline.setLineWidth_(0.75)
    outline.stroke()
    # Filled star
    color = NSColor.colorWithCalibratedRed_green_blue_alpha_(
        color_rgb[0], color_rgb[1], color_rgb[2], alpha
    )
    color.set()
    star = make_star_path(cx, cy, outer_r, inner_r)
    star.fill()


def draw_dot(cx, cy, color_rgb, size=STAR_SIZE, alpha=1.0):
    """Draw a filled circle at the given center."""
    radius = size * 0.34
    # Black outline
    NSColor.blackColor().set()
    or_ = radius + 0.375
    outline = NSBezierPath.bezierPathWithOvalInRect_(
        ((cx - or_, cy - or_), (or_ * 2, or_ * 2))
    )
    outline.setLineWidth_(0.75)
    outline.stroke()
    # Filled circle
    color = NSColor.colorWithCalibratedRed_green_blue_alpha_(
        color_rgb[0], color_rgb[1], color_rgb[2], alpha
    )
    color.set()
    path = NSBezierPath.bezierPathWithOvalInRect_(
        ((cx - radius, cy - radius), (radius * 2, radius * 2))
    )
    path.fill()


def make_heart_path(cx, cy, size):
    """Create a heart-shaped NSBezierPath using 4 cubic Bezier segments."""
    s = size * 0.42
    bx, by = cx, cy - s * 0.9   # bottom tip
    tx, ty = cx, cy + s * 0.15  # top center dip

    path = NSBezierPath.bezierPath()
    path.moveToPoint_((bx, by))
    # Right half: bottom tip -> right lobe peak
    path.curveToPoint_controlPoint1_controlPoint2_(
        (cx + s * 0.95, cy + s * 0.45),
        (cx + s * 0.15, cy - s * 0.6),
        (cx + s * 1.0, cy - s * 0.15),
    )
    # Right lobe peak -> top center dip
    path.curveToPoint_controlPoint1_controlPoint2_(
        (tx, ty),
        (cx + s * 0.9, cy + s * 0.9),
        (cx + s * 0.25, cy + s * 0.85),
    )
    # Left half: top center dip -> left lobe peak
    path.curveToPoint_controlPoint1_controlPoint2_(
        (cx - s * 0.95, cy + s * 0.45),
        (cx - s * 0.25, cy + s * 0.85),
        (cx - s * 0.9, cy + s * 0.9),
    )
    # Left lobe peak -> bottom tip
    path.curveToPoint_controlPoint1_controlPoint2_(
        (bx, by),
        (cx - s * 1.0, cy - s * 0.15),
        (cx - s * 0.15, cy - s * 0.6),
    )
    path.closePath()
    return path


def draw_heart(cx, cy, color_rgb, size=STAR_SIZE, alpha=1.0):
    """Draw a heart at the given center."""
    # Black outline
    NSColor.blackColor().set()
    outline = make_heart_path(cx, cy, size + 1)
    outline.setLineWidth_(0.75)
    outline.stroke()
    # Filled heart
    color = NSColor.colorWithCalibratedRed_green_blue_alpha_(
        color_rgb[0], color_rgb[1], color_rgb[2], alpha
    )
    color.set()
    heart = make_heart_path(cx, cy, size)
    heart.fill()


def draw_check(cx, cy, color_rgb, size=STAR_SIZE, alpha=1.0):
    """Draw a check mark at the given center."""
    s = size * 0.40
    # Three vertices: left start, bottom vertex, top-right end
    x0, y0 = cx - s * 0.85, cy + s * 0.05
    x1, y1 = cx - s * 0.15, cy - s * 0.65
    x2, y2 = cx + s * 0.95, cy + s * 0.7

    # Black outline (wider stroke behind)
    NSColor.blackColor().set()
    outline = NSBezierPath.bezierPath()
    outline.moveToPoint_((x0, y0))
    outline.lineToPoint_((x1, y1))
    outline.lineToPoint_((x2, y2))
    outline.setLineWidth_(3.5)
    outline.setLineCapStyle_(1)   # NSRoundLineCapStyle
    outline.setLineJoinStyle_(1)  # NSRoundLineJoinStyle
    outline.stroke()

    # Colored stroke on top
    color = NSColor.colorWithCalibratedRed_green_blue_alpha_(
        color_rgb[0], color_rgb[1], color_rgb[2], alpha
    )
    color.set()
    path = NSBezierPath.bezierPath()
    path.moveToPoint_((x0, y0))
    path.lineToPoint_((x1, y1))
    path.lineToPoint_((x2, y2))
    path.setLineWidth_(2.5)
    path.setLineCapStyle_(1)
    path.setLineJoinStyle_(1)
    path.stroke()


def draw_emoji(cx, cy, emoji_char, size=STAR_SIZE):
    """Draw an emoji character centered at (cx, cy) in the current graphics context."""
    from AppKit import NSFont, NSFontAttributeName
    from Foundation import NSAttributedString

    font_size = size * 0.85
    font = NSFont.systemFontOfSize_(font_size)
    attrs = {NSFontAttributeName: font}
    attr_str = NSAttributedString.alloc().initWithString_attributes_(emoji_char, attrs)
    str_size = attr_str.size()
    draw_x = cx - str_size.width / 2
    draw_y = cy - str_size.height / 2
    attr_str.drawAtPoint_((draw_x, draw_y))


SHAPE_DRAW_FUNCTIONS = {
    "dot": draw_dot,
    "star": draw_star,
    "heart": draw_heart,
    "check": draw_check,
}


def make_composite_image(session_statuses, config=None, working_alpha=1.0):
    """Render all session indicators into one menu bar image."""
    if not session_statuses:
        return None
    if config is None:
        config = DEFAULT_CONFIG

    count = len(session_statuses)
    c_working = tuple(config.get("color_working", DEFAULT_WORKING))
    c_attention = tuple(config.get("color_attention", DEFAULT_ATTENTION))
    c_idle = tuple(config.get("color_idle", DEFAULT_IDLE))
    shape = config.get("shape", "star")
    emoji_char = config.get("emoji")

    total_width = count * STAR_SIZE + max(0, count - 1) * STAR_GAP
    height = STAR_SIZE

    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, total_width, height, 8, 4, True, False, NSCalibratedRGBColorSpace, 0, 0
    )
    ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    NSGraphicsContext.setCurrentContext_(ctx)

    for i, status in enumerate(session_statuses):
        cx = i * (STAR_SIZE + STAR_GAP) + STAR_SIZE / 2
        cy = height / 2
        if status == "working":
            color_rgb = c_working
        elif status == "attention":
            color_rgb = c_attention
        else:
            color_rgb = c_idle
        alpha = working_alpha if status in ("working", "attention") else 1.0
        if shape == "emoji" and emoji_char:
            draw_emoji(cx, cy, emoji_char)
        else:
            draw_fn = SHAPE_DRAW_FUNCTIONS.get(shape, draw_star)
            draw_fn(cx, cy, color_rgb, alpha=alpha)

    NSGraphicsContext.setCurrentContext_(None)

    img = NSImage.alloc().initWithSize_(NSSize(total_width, height))
    img.addRepresentation_(rep)
    img.setTemplate_(False)
    return img


def read_sessions():
    try:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text())
            return data.get("sessions", {})
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def write_sessions(sessions):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({"sessions": sessions}, indent=2))


def _log(msg):
    """Append a debug line to ~/.barspy/debug.log."""
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except OSError:
        pass


def scan_codex_sessions():
    """Scan Codex SQLite databases for active threads. Returns dict of session entries.

    Reads ~/.codex/logs_1.sqlite for activity and ~/.codex/state_5.sqlite for
    thread metadata (cwd, title). No Codex config changes needed.
    """
    if not CODEX_LOGS_DB.exists() or not CODEX_STATE_DB.exists():
        return {}

    now = time.time()
    cutoff = int(now) - int(DEAD_THRESHOLD)
    sessions = {}

    try:
        conn = sqlite3.connect(f"file:{CODEX_LOGS_DB}?mode=ro", uri=True, timeout=1)
        conn.execute(f"ATTACH DATABASE 'file:{CODEX_STATE_DB}?mode=ro' AS state_db")

        # Find threads with recent log activity
        rows = conn.execute("""
            SELECT
                l.thread_id,
                t.cwd,
                t.title,
                MAX(l.ts) as last_ts,
                t.created_at
            FROM logs l
            JOIN state_db.threads t ON l.thread_id = t.id
            WHERE l.thread_id IS NOT NULL
              AND l.ts > ?
              AND t.archived = 0
            GROUP BY l.thread_id
            ORDER BY last_ts DESC
        """, (cutoff,)).fetchall()

        for thread_id, cwd, title, last_ts, created_at in rows:
            # Get the last significant log entry for state detection
            event_row = conn.execute("""
                SELECT target, message
                FROM logs
                WHERE thread_id = ?
                  AND target IN (
                    'codex_app_server::outgoing_message',
                    'codex_core::codex',
                    'codex_core::stream_events_utils',
                    'codex_api::sse::responses',
                    'codex_api::endpoint::responses_websocket'
                  )
                ORDER BY ts DESC, ts_nanos DESC
                LIMIT 1
            """, (thread_id,)).fetchone()

            status = _codex_status_from_log(last_ts, event_row, now)
            if status is None:
                continue  # dead, skip

            project = Path(cwd).name if cwd else "Unknown"
            started = datetime.fromtimestamp(created_at, tz=ET).strftime("%-I:%M %p")

            sid = f"codex:{thread_id}"
            sessions[sid] = {
                "agent_type": "codex",
                "pid": 0,  # filled in below
                "project": project,
                "cwd": cwd or "",
                "started": started,
                "status": status,
                "last_active": float(last_ts),
                "last_event": _codex_last_event(event_row),
                "thread_id": thread_id,
            }

        conn.close()
    except (sqlite3.Error, OSError) as e:
        _log(f"Codex scan error: {e}")
        return {}

    # Find Codex app-server PID for liveness check
    if sessions:
        codex_pid = _find_codex_pid()
        for info in sessions.values():
            info["pid"] = codex_pid

    return sessions


def _codex_status_from_log(last_ts, event_row, now):
    """Determine Codex session status from the last significant log entry."""
    age = now - last_ts

    # Dead: no activity in 30 min
    if age > DEAD_THRESHOLD:
        return None

    if event_row:
        target, message = event_row
        msg = (message or "").lower()

        # Explicit idle: model finished responding
        if ("response.completed" in msg or "turn/completed" in msg
                or message == "post sampling token usage"):
            return "idle"

        # Explicit working: user just submitted a prompt
        if message == "Submission":
            return "working"

    # Recent activity = working (streaming, tool calls, etc.)
    if age < 10:
        return "working"

    # Stale with no completion marker = idle
    return "idle"


def _codex_last_event(event_row):
    """Map Codex log entry to a last_event string for attention logic."""
    if not event_row:
        return ""
    target, message = event_row
    msg = (message or "").lower()
    if ("response.completed" in msg or "turn/completed" in msg
            or message == "post sampling token usage"):
        return "turn-complete"
    if message == "Submission":
        return "submission"
    if "toolcall" in msg.replace(" ", "").lower():
        return "tool-call"
    return "streaming"


def _find_codex_pid():
    """Find the Codex app-server PID (or main Codex.app PID)."""
    try:
        output = subprocess.check_output(
            ["pgrep", "-f", "codex app-server"],
            text=True, stderr=subprocess.DEVNULL,
        )
        pids = [int(p) for p in output.strip().split("\n") if p.strip()]
        if pids:
            return pids[0]
    except (subprocess.CalledProcessError, ValueError):
        pass
    # Fallback: look for main Codex process
    try:
        output = subprocess.check_output(
            ["pgrep", "-x", "Codex"],
            text=True, stderr=subprocess.DEVNULL,
        )
        pids = [int(p) for p in output.strip().split("\n") if p.strip()]
        if pids:
            return pids[0]
    except (subprocess.CalledProcessError, ValueError):
        pass
    return 0


def get_session_status(info, config=None):
    """Promote idle to attention after threshold. Works for both Claude and Codex.

    Claude: promotes after tool-complete with no follow-up for configured delay.
    Codex: promotes after turn-complete (idle) with no new activity for configured delay.
    Dismissed: if user clicked notification/session, suppress until new activity.
    """
    status = info.get("status", "idle")
    last_event = info.get("last_event", "")

    # Attention promotion for idle sessions (both agents)
    # Claude: after tool-complete; Codex: after turn-complete
    promotable_events = ("tool-complete", "turn-complete")
    if status in ("working", "idle") and last_event in promotable_events:
        delay_key = (config or {}).get("attention_delay", "5min")
        threshold = ATTENTION_DELAYS.get(delay_key, 0.0)
        if threshold > 0:
            last_active = info.get("last_active", 0.0)
            if last_active > 0 and (time.time() - last_active) > threshold:
                dismissed_at = info.get("attention_dismissed_at", 0.0)
                if dismissed_at < last_active:
                    return "attention"
    return status


def is_pid_alive(pid):
    """Check if a process is still running."""
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists, we just can't signal it


def is_session_dead(info):
    last_active = info.get("last_active", 0.0)
    if last_active == 0.0:
        return False
    return (time.time() - last_active) > DEAD_THRESHOLD


def _get_icon_path(icon_key):
    """Get path to the icon PNG for the given app_icon key.

    Checks the py2app bundle first, then falls back to local assets/.
    """
    icon_filename = f"{icon_key}.png"
    # py2app bundle: Contents/Resources/icons/
    if getattr(sys, "frozen", False):
        bundle_dir = Path(sys.executable).parent.parent / "Resources" / "icons"
    else:
        bundle_dir = Path(__file__).parent / "assets"
    return bundle_dir / icon_filename


def _apply_app_icon(icon_key):
    """Set the app icon (About window, Activity Monitor) to the chosen character."""
    icon_path = _get_icon_path(icon_key)
    if icon_path.exists():
        img = NSImage.alloc().initByReferencingFile_(str(icon_path))
        if img:
            NSApplication.sharedApplication().setApplicationIconImage_(img)


def _find_owning_app(pid):
    """Walk up the process tree from a PID to find the macOS GUI application.

    Claude Code runs inside a terminal (Warp, Terminal) or IDE (VS Code, Cursor).
    Starting from the Claude Code PID, walk up parent PIDs until we find a process
    that's registered as a macOS app (has a bundle identifier).
    """
    current = pid
    visited = set()
    while current > 1 and current not in visited:
        visited.add(current)
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(current)
        if app and app.bundleIdentifier():
            return app
        try:
            output = subprocess.check_output(
                ["ps", "-o", "ppid=", "-p", str(current)],
                text=True, stderr=subprocess.DEVNULL,
            )
            current = int(output.strip())
        except (subprocess.CalledProcessError, ValueError):
            break
    return None


def _activate_via_applescript(bundle_id):
    """Fallback activation using AppleScript — more reliable on macOS 14+."""
    try:
        subprocess.run(
            ["osascript", "-e", f'tell application id "{bundle_id}" to activate'],
            check=True, timeout=5, capture_output=True,
        )
        return True
    except Exception:
        return False


def _dismiss_attention_for_pid(pid):
    """Mark attention as dismissed for the session with this PID."""
    if not pid:
        return
    sessions = read_sessions()
    changed = False
    for info in sessions.values():
        if info.get("pid") == pid:
            info["attention_dismissed_at"] = time.time()
            changed = True
    if changed:
        write_sessions(sessions)


def _activate_codex():
    """Bring the Codex desktop app to the foreground."""
    _log("Activating Codex.app")
    apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_("com.openai.codex")
    if apps and len(apps) > 0:
        apps[0].activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
    else:
        _activate_via_applescript("com.openai.codex")


def _handle_notification_click(pid):
    """Bring the session's terminal/IDE to front given the Claude Code PID."""
    _log(f"Handling click for PID {pid}")
    if not pid:
        return
    _dismiss_attention_for_pid(pid)
    app = _find_owning_app(pid)
    if app:
        bundle_id = app.bundleIdentifier()
        _log(f"Found app: {app.localizedName()} ({bundle_id})")
        result = app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
        _log(f"activateWithOptions_ result: {result}")
        if not result:
            _log("Trying AppleScript fallback")
            ok = _activate_via_applescript(bundle_id)
            _log(f"AppleScript result: {ok}")
    else:
        _log(f"No owning app found for PID {pid}")


# --- UNUserNotificationCenter delegate (modern macOS notification clicks) ---

class NotificationDelegate(objc.lookUpClass("NSObject")):
    """Handles notification click responses via UNUserNotificationCenter."""

    def userNotificationCenter_didReceiveNotificationResponse_withCompletionHandler_(
        self, center, response, handler
    ):
        """Called when user clicks a notification."""
        try:
            user_info = response.notification().request().content().userInfo()
            agent_type = user_info.get("agent_type", "claude") if user_info else "claude"
            pid = user_info.get("session_pid", 0) if user_info else 0
            _log(f"UN click - agent={agent_type} pid={pid}")
            if agent_type == "codex":
                _activate_codex()
            elif pid:
                _handle_notification_click(int(pid))
        except Exception as e:
            _log(f"UN click error: {e}")
        handler()

    def userNotificationCenter_willPresentNotification_withCompletionHandler_(
        self, center, notification, handler
    ):
        """Show notifications even when app is in foreground (menu bar app)."""
        # UNNotificationPresentationOptionBanner | UNNotificationPresentationOptionSound
        handler(0x10 | 0x02)


def _setup_notifications():
    """Initialize UNUserNotificationCenter with our delegate and request auth."""
    center = UNUserNotificationCenter.currentNotificationCenter()
    delegate = NotificationDelegate.alloc().init()
    center.setDelegate_(delegate)
    # Request authorization (needed once; macOS remembers the choice)
    center.requestAuthorizationWithOptions_completionHandler_(
        UNAuthorizationOptionAlert | UNAuthorizationOptionSound,
        lambda granted, error: _log(f"Notification auth: granted={granted} error={error}"),
    )
    return delegate  # prevent GC


def _send_notification(title, subtitle, message, session_pid=0, agent_type="claude"):
    """Send a notification via UNUserNotificationCenter with click-to-activate data."""
    content = UNMutableNotificationContent.alloc().init()
    content.setTitle_(title)
    content.setSubtitle_(subtitle)
    content.setBody_(message)
    content.setSound_(UNNotificationSound.defaultSound())
    user_info = {"agent_type": agent_type}
    if session_pid:
        user_info["session_pid"] = session_pid
    content.setUserInfo_(user_info)

    request = UNNotificationRequest.requestWithIdentifier_content_trigger_(
        f"barspy-{time.time()}", content, None
    )
    center = UNUserNotificationCenter.currentNotificationCenter()
    center.addNotificationRequest_withCompletionHandler_(
        request,
        lambda error: _log(f"Notification send error: {error}") if error else None,
    )
    _log(f"Sent notification: {title} / {subtitle} (pid={session_pid})")


class BarSpyApp(rumps.App):
    def __init__(self):
        super().__init__(
            name="Bar Spy",
            title=None,
            quit_button="Quit Bar Spy",
        )
        self._initialized = False
        self._last_icon_key = None
        self._config = load_config()
        self._throb_phase = 0.0
        self._current_statuses = []
        self._has_working = False
        self._prev_session_statuses = {}  # session_id -> status, for transition detection
        self._notif_delegate = _setup_notifications()  # keep ref to prevent GC
        _apply_app_icon(self._config.get("app_icon", "spy-girl"))

    @rumps.timer(1)
    def poll_sessions(self, _):
        if not self._initialized:
            try:
                from AppKit import NSApp, NSApplicationActivationPolicyAccessory
                NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
            except Exception:
                pass
            self._nsapp.nsstatusitem.setTitle_("")
            self._initialized = True

        # --- Claude Code sessions (from hook-driven JSON) ---
        sessions = read_sessions()

        # Dedup: if multiple Claude sessions share a PID, keep most recently active
        pid_best = {}
        for sid, info in sessions.items():
            pid = info.get("pid", 0)
            if pid in pid_best:
                existing_sid, existing_info = pid_best[pid]
                if info.get("last_active", 0) > existing_info.get("last_active", 0):
                    pid_best[pid] = (sid, info)
            else:
                pid_best[pid] = (sid, info)
        best_sids = {sid for sid, _ in pid_best.values()}
        dup_ids = [sid for sid in sessions if sid not in best_sids]
        if dup_ids:
            for sid in dup_ids:
                del sessions[sid]
            write_sessions(sessions)

        # Cleanup: remove Claude sessions whose process is dead OR inactive 30+ min
        dead_ids = [sid for sid, info in sessions.items()
                     if is_session_dead(info) or not is_pid_alive(info.get("pid", 0))]
        if dead_ids:
            for sid in dead_ids:
                del sessions[sid]
            write_sessions(sessions)

        # --- Codex sessions (from SQLite polling) ---
        codex_sessions = scan_codex_sessions()
        sessions.update(codex_sessions)

        # Build status list (sorted by started time for stable ordering)
        sorted_sessions = sorted(sessions.items(), key=lambda x: x[1].get("started", ""))
        statuses = [get_session_status(info, self._config) for _, info in sorted_sessions]
        self._current_statuses = statuses
        self._has_working = any(s in ("working", "attention") for s in statuses)

        # Determine if animation timer handles icon updates
        throb_speed = self._config.get("throb_speed", "medium")
        throbbing = throb_speed != "off" and self._has_working

        if throbbing:
            # Animation timer handles icon; invalidate cache for when throbbing stops
            self._last_icon_key = None
        else:
            # Reset phase so next throb starts from full brightness
            self._throb_phase = 0.0
            # Only redraw if something changed
            shape_key = (
                self._config.get("shape", "star"),
                self._config.get("emoji", ""),
                tuple(self._config.get("color_working", DEFAULT_WORKING)),
                tuple(self._config.get("color_idle", DEFAULT_IDLE)),
            )
            icon_key = (shape_key, tuple(statuses)) if statuses else ("none",)
            if icon_key != self._last_icon_key:
                self._last_icon_key = icon_key
                img = make_composite_image(statuses, self._config)
                self._nsapp.nsstatusitem.setImage_(img)

        # Notifications: detect status transitions
        if self._config.get("notifications", True):
            for sid, info in sorted_sessions:
                status = get_session_status(info, self._config)
                prev = self._prev_session_statuses.get(sid)
                if prev == "working" and status == "attention":
                    project = info.get("project", "Unknown")
                    agent_type = info.get("agent_type", "claude")
                    agent = "Codex" if agent_type == "codex" else "Claude"
                    _send_notification(
                        title=project,
                        subtitle="Needs attention",
                        message=f"{agent} may be waiting for your input",
                        session_pid=info.get("pid", 0),
                        agent_type=agent_type,
                    )
                elif prev in ("working", "attention") and status == "idle":
                    project = info.get("project", "Unknown")
                    agent_type = info.get("agent_type", "claude")
                    agent = "Codex" if agent_type == "codex" else "Claude"
                    _send_notification(
                        title=project,
                        subtitle="Session ready",
                        message=f"{agent} is waiting for your input",
                        session_pid=info.get("pid", 0),
                        agent_type=agent_type,
                    )
        self._prev_session_statuses = {
            sid: get_session_status(info, self._config) for sid, info in sorted_sessions
        }

        # Tooltip
        if not sessions:
            self._nsapp.nsstatusitem.setToolTip_("No active sessions")
        else:
            working = statuses.count("working")
            attention = statuses.count("attention")
            idle = len(statuses) - working - attention
            parts = []
            if working:
                parts.append(f"{working} working")
            if attention:
                parts.append(f"{attention} waiting")
            if idle:
                parts.append(f"{idle} idle")
            self._nsapp.nsstatusitem.setToolTip_(", ".join(parts))

        self._rebuild_menu(sorted_sessions)

    @rumps.timer(0.05)
    def animate(self, _):
        """Throb working indicators by cycling their alpha."""
        if not self._initialized:
            return
        throb_speed = self._config.get("throb_speed", "medium")
        if throb_speed == "off" or not self._has_working or not self._current_statuses:
            return

        omega = THROB_SPEEDS.get(throb_speed, THROB_SPEEDS["medium"])
        self._throb_phase += 0.05 * omega
        alpha = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(self._throb_phase))

        img = make_composite_image(self._current_statuses, self._config, working_alpha=alpha)
        if img:
            self._nsapp.nsstatusitem.setImage_(img)

    def _rebuild_menu(self, sorted_sessions):
        self.menu.clear()

        if not sorted_sessions:
            self.menu.add(rumps.MenuItem("No active sessions", callback=None))
        else:
            working = sum(1 for _, s in sorted_sessions if get_session_status(s, self._config) == "working")
            attention = sum(1 for _, s in sorted_sessions if get_session_status(s, self._config) == "attention")
            idle = len(sorted_sessions) - working - attention
            parts = []
            if working:
                parts.append(f"{working} working")
            if attention:
                parts.append(f"{attention} waiting")
            if idle:
                parts.append(f"{idle} idle")
            header = ", ".join(parts) if parts else f"{len(sorted_sessions)} sessions"
            self.menu.add(rumps.MenuItem(header, callback=None))
            self.menu.add(rumps.separator)

            for sid, info in sorted_sessions:
                project = info.get("project", "Unknown")
                started = info.get("started", "")
                agent_tag = "Codex" if info.get("agent_type") == "codex" else "Claude"
                status = get_session_status(info, self._config)
                if status == "working":
                    icon = "●"
                elif status == "attention":
                    icon = "◆"
                else:
                    icon = "○"
                label = f"{icon}  {project} ({agent_tag})  —  {started}"
                pid = info.get("pid", 0)
                if info.get("agent_type") == "codex":
                    cb = (lambda s: lambda _: _activate_codex())(sid)
                else:
                    cb = (lambda p: lambda _: _dismiss_attention_for_pid(p))(pid)
                self.menu.add(rumps.MenuItem(label, callback=cb))

        self.menu.add(rumps.separator)

        # Shape submenu
        shape_menu = rumps.MenuItem("Shape")
        current_shape = self._config.get("shape", "star")
        for shape_key, shape_label in BUILTIN_SHAPES:
            item = rumps.MenuItem(shape_label, callback=self._on_shape_select)
            if current_shape == shape_key:
                item.state = 1
            shape_menu[shape_label] = item

        shape_menu.add(rumps.separator)

        emoji_label = "Emoji..."
        if current_shape == "emoji" and self._config.get("emoji"):
            emoji_label = f"Emoji ({self._config['emoji']})..."
        emoji_item = rumps.MenuItem(emoji_label, callback=self._on_emoji_select)
        if current_shape == "emoji":
            emoji_item.state = 1
        shape_menu[emoji_label] = emoji_item

        if self._config.get("emoji"):
            clear_item = rumps.MenuItem("Clear Emoji", callback=self._on_clear_emoji)
            shape_menu["Clear Emoji"] = clear_item

        self.menu.add(shape_menu)

        # Color submenus
        self._build_color_submenu("Working Color", "color_working", DEFAULT_WORKING)
        self._build_color_submenu("Attention Color", "color_attention", DEFAULT_ATTENTION)
        self._build_color_submenu("Idle Color", "color_idle", DEFAULT_IDLE)

        # Notifications toggle
        notif_enabled = self._config.get("notifications", True)
        notif_item = rumps.MenuItem(
            "Notifications", callback=self._on_toggle_notifications
        )
        notif_item.state = 1 if notif_enabled else 0
        self.menu.add(notif_item)

        # Throb speed submenu
        throb_menu = rumps.MenuItem("Throb Speed")
        current_throb = self._config.get("throb_speed", "medium")
        for speed_key, speed_label in THROB_LABELS:
            item = rumps.MenuItem(speed_label, callback=self._on_throb_select)
            if current_throb == speed_key:
                item.state = 1
            throb_menu[speed_label] = item
        self.menu.add(throb_menu)

        # Attention delay submenu
        attn_menu = rumps.MenuItem("Attention Delay")
        current_attn = self._config.get("attention_delay", "5min")
        for delay_key, delay_label in ATTENTION_DELAY_LABELS:
            item = rumps.MenuItem(delay_label, callback=self._on_attention_delay_select)
            if current_attn == delay_key:
                item.state = 1
            attn_menu[delay_label] = item
        self.menu.add(attn_menu)

        # App icon submenu
        icon_menu = rumps.MenuItem("App Icon")
        current_icon = self._config.get("app_icon", "spy-girl")
        for icon_key, icon_label in APP_ICON_CHOICES:
            item = rumps.MenuItem(icon_label, callback=self._on_icon_select)
            if current_icon == icon_key:
                item.state = 1
            icon_menu[icon_label] = item
        self.menu.add(icon_menu)

        self.menu.add(rumps.separator)

    def _build_color_submenu(self, label, config_key, default_color):
        """Build a color picker submenu with presets + custom hex input."""
        menu = rumps.MenuItem(label)
        current = tuple(self._config.get(config_key, default_color))

        for preset_name, preset_rgb in COLOR_PRESETS:
            item = rumps.MenuItem(preset_name, callback=lambda s, k=config_key, c=preset_rgb: self._on_color_preset(k, c))
            if _colors_close(current, preset_rgb):
                item.state = 1
            menu[preset_name] = item

        menu.add(rumps.separator)
        custom_item = rumps.MenuItem("Custom (hex)...", callback=lambda s, k=config_key: self._on_color_custom(k))
        menu["Custom (hex)..."] = custom_item

        # Reset option
        reset_item = rumps.MenuItem("Reset to Default", callback=lambda s, k=config_key, d=default_color: self._on_color_preset(k, d))
        menu["Reset to Default"] = reset_item

        self.menu.add(menu)

    def _on_color_preset(self, config_key, color_rgb):
        self._config[config_key] = list(color_rgb)
        save_config(self._config)
        self._last_icon_key = None

    def _on_color_custom(self, config_key):
        current = self._config.get(config_key, [0, 0, 0])
        current_hex = "#{:02X}{:02X}{:02X}".format(
            int(current[0] * 255), int(current[1] * 255), int(current[2] * 255)
        )
        window = rumps.Window(
            message="Enter a hex color (e.g. #FF6B5E or FF6B5E):",
            title="Bar Spy — Custom Color",
            default_text=current_hex,
            ok="Save",
            cancel=True,
            dimensions=(200, 24),
        )
        response = window.run()
        if response.clicked == 1:
            text = response.text.strip().lstrip("#")
            if len(text) == 6:
                try:
                    r = int(text[0:2], 16) / 255.0
                    g = int(text[2:4], 16) / 255.0
                    b = int(text[4:6], 16) / 255.0
                    self._config[config_key] = [r, g, b]
                    save_config(self._config)
                    self._last_icon_key = None
                except ValueError:
                    pass

    def _on_toggle_notifications(self, sender):
        current = self._config.get("notifications", True)
        self._config["notifications"] = not current
        save_config(self._config)

    def _on_throb_select(self, sender):
        for speed_key, speed_label in THROB_LABELS:
            if speed_label == sender.title:
                self._config["throb_speed"] = speed_key
                save_config(self._config)
                self._last_icon_key = None
                return

    def _on_attention_delay_select(self, sender):
        for delay_key, delay_label in ATTENTION_DELAY_LABELS:
            if delay_label == sender.title:
                self._config["attention_delay"] = delay_key
                save_config(self._config)
                return

    def _on_icon_select(self, sender):
        for icon_key, icon_label in APP_ICON_CHOICES:
            if icon_label == sender.title:
                self._config["app_icon"] = icon_key
                save_config(self._config)
                _apply_app_icon(icon_key)
                return

    def _on_shape_select(self, sender):
        for shape_key, shape_label in BUILTIN_SHAPES:
            if shape_label == sender.title:
                self._config["shape"] = shape_key
                self._config["emoji"] = None
                save_config(self._config)
                self._last_icon_key = None
                return

    def _on_emoji_select(self, sender):
        window = rumps.Window(
            message="Enter a single emoji to use as your indicator:",
            title="Bar Spy — Choose Emoji",
            default_text=self._config.get("emoji") or "",
            ok="Save",
            cancel=True,
            dimensions=(200, 24),
        )
        response = window.run()
        if response.clicked == 1:
            text = response.text.strip()
            if text:
                self._config["shape"] = "emoji"
                self._config["emoji"] = text
                save_config(self._config)
                self._last_icon_key = None

    def _on_clear_emoji(self, sender):
        self._config["shape"] = "star"
        self._config["emoji"] = None
        save_config(self._config)
        self._last_icon_key = None


if __name__ == "__main__":
    # Timeout cleanup on startup
    sessions = read_sessions()
    if sessions:
        alive = {k: v for k, v in sessions.items() if not is_session_dead(v)}
        if alive != sessions:
            write_sessions(alive)

    BarSpyApp().run()
