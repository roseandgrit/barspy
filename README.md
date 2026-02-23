# KizWatch

A tiny menu bar app that keeps an eye on your [Claude Code](https://docs.anthropic.com/en/docs/claude-code) sessions.

One indicator per session. Colored by status. Glanceable.

```
 Working ──  teal
 Idle    ──  lavender
```

## What It Does

KizWatch sits in your macOS menu bar and shows a small shape for each active Claude Code session. When a session is thinking or running tools, its indicator lights up. When it's waiting for you, it dims.

Click it to see which projects are running and when each session started.

No polling Claude. No API calls. Status comes directly from Claude Code's hook system — instant and accurate.

## Customize Everything

**Pick your shape** — Star, dot, heart, check mark, or any emoji you want.

**Pick your colors** — 8 built-in presets for working and idle states, or enter any hex color. Make it yours.

All preferences persist between launches.

## How It Works

Claude Code fires [hooks](https://docs.anthropic.com/en/docs/claude-code/hooks) on events like prompt submission, tool execution, and session end. A small Python script catches those hooks and writes session status to a JSON file. KizWatch reads that file once per second and draws the indicators.

That's it. No daemon, no background process polling your terminal, no timestamp guessing.

## Install

**Requirements:** macOS, Python 3.12+, an active [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installation.

```bash
# Clone and set up
git clone https://github.com/roseandgrit/KizWatch.git
cd KizWatch
python3 -m venv .venv
.venv/bin/pip install rumps pyobjc py2app

# Build the app
.venv/bin/python setup.py py2app

# Copy to Applications and sign (replace with your cert)
cp -R dist/KizWatch.app /Applications/
codesign --force --deep --sign "Your Developer ID" /Applications/KizWatch.app

# Launch
open /Applications/KizWatch.app
```

Then add the hooks to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [{ "type": "command", "command": "python3 ~/.claude/scripts/kizwatch_hook.py session-start" }],
    "UserPromptSubmit": [{ "type": "command", "command": "python3 ~/.claude/scripts/kizwatch_hook.py prompt-submit" }],
    "PreToolUse": [{ "type": "command", "command": "python3 ~/.claude/scripts/kizwatch_hook.py tool-start" }],
    "PostToolUse": [{ "type": "command", "command": "python3 ~/.claude/scripts/kizwatch_hook.py tool-complete" }],
    "Stop": [{ "type": "command", "command": "python3 ~/.claude/scripts/kizwatch_hook.py stop" }],
    "SessionEnd": [{ "type": "command", "command": "python3 ~/.claude/scripts/kizwatch_hook.py session-end" }]
  }
}
```

Copy `kizwatch_hook.py` to `~/.claude/scripts/` and you're set.

## Auto-Start on Login

Create `~/Library/LaunchAgents/com.kizwatch.plist` to launch KizWatch when you log in. See the repo for an example plist.

## Files

| What | Where |
|------|-------|
| App | `kizwatch.py` |
| Hook script | `~/.claude/scripts/kizwatch_hook.py` |
| Session state | `~/.kizwatch/sessions.json` |
| Preferences | `~/.kizwatch/config.json` |
| Built app | `/Applications/KizWatch.app` |

## License

MIT
