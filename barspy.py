#!/usr/bin/env python3
"""Bar Spy — Menu bar agent monitor. Colored stars, one per Claude Code session.

Single composite image approach: all session stars rendered into one menu bar icon.
No separate NSStatusItems, no PID heartbeat. Uses session_id from Claude Code hooks.
Status set directly by hooks — no timestamp-based guessing.
Cleanup via session-end events + 30-minute inactivity timeout.
"""

import json
import math
import os
import sys
import time
from pathlib import Path

import rumps
from AppKit import (
    NSApplication,
    NSBezierPath,
    NSBitmapImageRep,
    NSCalibratedRGBColorSpace,
    NSColor,
    NSGraphicsContext,
    NSImage,
)
from Foundation import NSSize

STATE_FILE = Path.home() / ".barspy" / "sessions.json"
CONFIG_FILE = Path.home() / ".barspy" / "config.json"
DEAD_THRESHOLD = 1800.0  # 30 min no activity = assume session crashed

# Default palette
DEFAULT_WORKING = (0.0, 0.85, 0.85)       # Teal — actively working
DEFAULT_IDLE = (0.706, 0.624, 0.863)      # Pastel lavender #B49FDC — session alive, waiting

STAR_SIZE = 18
STAR_GAP = 3

DEFAULT_CONFIG = {
    "shape": "star",
    "emoji": None,
    "color_working": list(DEFAULT_WORKING),
    "color_idle": list(DEFAULT_IDLE),
    "throb_speed": "medium",
    "notifications": True,
    "app_icon": "spy-girl",
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
            if not _valid_color(data.get("color_idle")):
                data["color_idle"] = list(DEFAULT_IDLE)
            if data.get("throb_speed") not in THROB_SPEEDS:
                data["throb_speed"] = "medium"
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
        color_rgb = c_working if status == "working" else c_idle
        alpha = working_alpha if status == "working" else 1.0
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


def get_session_status(info):
    """Read status directly from the hook-set field."""
    return info.get("status", "idle")


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

        sessions = read_sessions()

        # Dedup: if multiple sessions share a PID, keep only the most recently active
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

        # Cleanup: remove sessions whose process is dead OR inactive 30+ min
        dead_ids = [sid for sid, info in sessions.items()
                     if is_session_dead(info) or not is_pid_alive(info.get("pid", 0))]
        if dead_ids:
            for sid in dead_ids:
                del sessions[sid]
            write_sessions(sessions)

        # Build status list (sorted by started time for stable ordering)
        sorted_sessions = sorted(sessions.items(), key=lambda x: x[1].get("started", ""))
        statuses = [get_session_status(info) for _, info in sorted_sessions]
        self._current_statuses = statuses
        self._has_working = "working" in statuses

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

        # Notifications: detect working → idle transitions
        if self._config.get("notifications", True):
            for sid, info in sorted_sessions:
                status = get_session_status(info)
                prev = self._prev_session_statuses.get(sid)
                if prev == "working" and status == "idle":
                    project = info.get("project", "Unknown")
                    rumps.notification(
                        title=project,
                        subtitle="Session ready",
                        message="Waiting for your input",
                        sound=True,
                    )
        self._prev_session_statuses = {
            sid: get_session_status(info) for sid, info in sorted_sessions
        }

        # Tooltip
        if not sessions:
            self._nsapp.nsstatusitem.setToolTip_("No active Claude sessions")
        else:
            working = statuses.count("working")
            idle = len(statuses) - working
            parts = []
            if working:
                parts.append(f"{working} working")
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
            working = sum(1 for _, s in sorted_sessions if get_session_status(s) == "working")
            idle = len(sorted_sessions) - working
            if working:
                header = f"{working} working, {idle} idle"
            else:
                header = f"{len(sorted_sessions)} session{'s' if len(sorted_sessions) > 1 else ''} idle"
            self.menu.add(rumps.MenuItem(header, callback=None))
            self.menu.add(rumps.separator)

            for _, info in sorted_sessions:
                project = info.get("project", "Unknown")
                started = info.get("started", "")
                status = get_session_status(info)
                icon = "●" if status == "working" else "○"
                label = f"{icon}  {project}  —  {started}"
                self.menu.add(rumps.MenuItem(label, callback=None))

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
