# Bar Spy

<p align="center">
  <img src="logo-concepts/beret-trenchcoat-v1.png" width="128" alt="Bar Spy logo">
  &nbsp;&nbsp;&nbsp;&nbsp;
  <img src="logo-concepts/spy-guy-v1-flipped.png" width="128" alt="Bar Spy guy">
</p>

A menu bar app that keeps a watchful eye on your [Claude Code](https://docs.anthropic.com/en/docs/claude-code) sessions.

One indicator per session. Colored by status. Glanceable.

```
 Working ──  teal
 Idle    ──  lavender
```

## What It Does

Bar Spy sits in your macOS menu bar and shows a small shape for each active Claude Code session. When a session is thinking or running tools, its indicator lights up and throbs. When it's waiting for you, it dims — and optionally sends a desktop notification.

Click it to see which projects are running and when each session started.

No polling Claude. No API calls. Status comes directly from Claude Code's hook system — instant and accurate.

## Customize Everything

**Pick your shape** — Star, dot, heart, check mark, or any emoji you want.

**Pick your colors** — 8 built-in presets for working and idle states, or enter any hex color.

**Pick your throb** — Off, slow, medium, or fast pulse animation on working indicators.

**Notifications** — Get a desktop notification when a session transitions from working to idle.

All preferences persist between launches.

## How It Works

Claude Code fires [hooks](https://docs.anthropic.com/en/docs/claude-code/hooks) on events like prompt submission, tool execution, and session end. A small Python script catches those hooks and writes session status to a JSON file. Bar Spy reads that file once per second and draws the indicators.

That's it. No daemon, no background process polling your terminal, no timestamp guessing.

## Install

**Requirements:** macOS, Python 3.12+, an active [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installation.

```bash
# Clone and set up
git clone https://github.com/roseandgrit/barspy.git
cd barspy
python3 -m venv .venv
.venv/bin/pip install rumps pyobjc py2app

# Build the app
.venv/bin/python setup.py py2app

# Copy to Applications and sign (replace with your cert)
cp -R dist/barspy.app /Applications/BarSpy.app
codesign --force --deep --sign "Your Developer ID" /Applications/BarSpy.app

# Launch
open /Applications/BarSpy.app
```

Then add the hooks to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [{ "type": "command", "command": "python3 ~/.claude/scripts/barspy_hook.py session-start" }],
    "UserPromptSubmit": [{ "type": "command", "command": "python3 ~/.claude/scripts/barspy_hook.py prompt-submit" }],
    "PreToolUse": [{ "type": "command", "command": "python3 ~/.claude/scripts/barspy_hook.py tool-start" }],
    "PostToolUse": [{ "type": "command", "command": "python3 ~/.claude/scripts/barspy_hook.py tool-complete" }],
    "Stop": [{ "type": "command", "command": "python3 ~/.claude/scripts/barspy_hook.py stop" }],
    "SessionEnd": [{ "type": "command", "command": "python3 ~/.claude/scripts/barspy_hook.py session-end" }]
  }
}
```

Copy `barspy_hook.py` to `~/.claude/scripts/` and you're set.

## Auto-Start on Login

Create `~/Library/LaunchAgents/com.barspy.plist` to launch Bar Spy when you log in. See the repo for an example plist.

## Files

| What | Where |
|------|-------|
| App | `barspy.py` |
| Hook script | `~/.claude/scripts/barspy_hook.py` |
| Session state | `~/.barspy/sessions.json` |
| Preferences | `~/.barspy/config.json` |
| Built app | `/Applications/BarSpy.app` |

## License

MIT
