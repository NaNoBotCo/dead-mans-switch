#!/usr/bin/env python3
"""Dead-man's switch — local, offline, stdlib-only.

You check in on a schedule. A background checker (launchd, hourly) watches
the clock. If the deadline passes without a check-in, it fires the payload
you configured, once, then disarms itself.

Run with no arguments for the numbered menu. The background checker runs
`deadman.py --check` (quiet; logs to deadman.log).
"""

import datetime as dt
import json
import os
import subprocess
import sys

HOME = os.environ.get("DEADMAN_HOME") or os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(HOME, "state.json")
LOG_PATH = os.path.join(HOME, "deadman.log")
PLIST_LABEL = "com.annika.deadman"
PLIST_PATH = os.path.expanduser("~/Library/LaunchAgents/%s.plist" % PLIST_LABEL)

DEFAULT_STATE = {
    "armed": False,
    "fired": False,
    "interval_days": 7,
    "warn_days": 2,
    "last_checkin": None,
    "last_warn": None,
    "payload": {"type": "none"},
}

WARN_EVERY_HOURS = 6  # at most one warning notification per this many hours


# ---------------------------------------------------------------- state

def load_state():
    state = dict(DEFAULT_STATE)
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH) as f:
                state.update(json.load(f))
        except (ValueError, OSError):
            log("WARNING: state.json unreadable, using defaults")
    return state


def save_state(state):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_PATH)


def log(msg):
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOG_PATH, "a") as f:
            f.write("%s  %s\n" % (stamp, msg))
    except OSError:
        pass


def now():
    return dt.datetime.now()


def parse_ts(s):
    return dt.datetime.fromisoformat(s) if s else None


def fmt_ts(t):
    return t.strftime("%a %d %b %Y, %H:%M") if t else "never"


def deadline_of(state):
    last = parse_ts(state["last_checkin"])
    if last is None:
        return None
    return last + dt.timedelta(days=state["interval_days"])


# ---------------------------------------------------------------- payload

def notify(title, text):
    try:
        subprocess.run(
            ["osascript", "-e",
             'display notification "%s" with title "%s" sound name "Sosumi"'
             % (text.replace('"', "'"), title.replace('"', "'"))],
            capture_output=True, timeout=15)
    except Exception as e:
        log("notify failed: %s" % e)


def send_mail(recipient, subject, body):
    script = '''
    tell application "Mail"
        set msg to make new outgoing message with properties {subject:"%s", content:"%s", visible:false}
        tell msg to make new to recipient at end of to recipients with properties {address:"%s"}
        send msg
    end tell
    ''' % (subject.replace('"', "'"), body.replace('"', "'").replace("\\", ""), recipient)
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError("Mail send failed: %s" % result.stderr.strip())


def fire_payload(state, test=False):
    """Execute the configured payload. Returns a human-readable result line."""
    p = state.get("payload", {"type": "none"})
    ptype = p.get("type", "none")
    prefix = "[TEST] " if test else ""

    if ptype == "email":
        subject = prefix + p.get("subject", "Dead-man's switch triggered")
        body = p.get("message", "")
        if test:
            body = ("THIS IS A TEST of the dead-man's switch. No action needed.\n\n"
                    "--- the real message would read: ---\n\n") + body
        send_mail(p["recipient"], subject, body)
        return "email sent to %s" % p["recipient"]

    if ptype == "file":
        path = os.path.expanduser(p["path"])
        with open(path, "a") as f:
            f.write("\n===== %sDEAD-MAN'S SWITCH FIRED %s =====\n%s\n"
                    % (prefix, now().isoformat(sep=" ", timespec="minutes"),
                       p.get("message", "")))
        return "message written to %s" % path

    if ptype == "command":
        if test:
            return "command payload NOT run in test mode: %s" % p["command"]
        subprocess.run(p["command"], shell=True, timeout=300)
        return "command executed: %s" % p["command"]

    return "no payload configured — nothing fired"


# ---------------------------------------------------------------- checker

def run_check():
    """Quiet hourly pass, driven by launchd."""
    state = load_state()
    if not state["armed"] or state["fired"]:
        return
    deadline = deadline_of(state)
    if deadline is None:
        return
    t = now()

    if t >= deadline:
        log("DEADLINE PASSED (was %s) — firing payload" % fmt_ts(deadline))
        notify("Dead-man's switch", "Deadline passed. Firing payload now.")
        try:
            result = fire_payload(state)
            log("FIRED: %s" % result)
        except Exception as e:
            log("FIRE FAILED: %s — will retry next hour" % e)
            return  # leave armed so the next hourly run retries
        state["fired"] = True
        state["armed"] = False
        save_state(state)
        return

    warn_start = deadline - dt.timedelta(days=state["warn_days"])
    if t >= warn_start:
        last_warn = parse_ts(state.get("last_warn"))
        if last_warn is None or (t - last_warn) >= dt.timedelta(hours=WARN_EVERY_HOURS):
            remaining = deadline - t
            hours = int(remaining.total_seconds() // 3600)
            notify("Dead-man's switch — check in soon",
                   "About %dh %dm left. Open Dead Mans Switch on the Desktop and press 1."
                   % (hours, int(remaining.total_seconds() % 3600 // 60)))
            state["last_warn"] = t.isoformat()
            save_state(state)
            log("warned: %dh remaining" % hours)


# ---------------------------------------------------------------- launchd

def plist_xml():
    python = sys.executable or "/usr/bin/python3"
    script = os.path.join(HOME, "deadman.py")
    return """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>%s</string>
    <key>ProgramArguments</key>
    <array><string>%s</string><string>%s</string><string>--check</string></array>
    <key>StartInterval</key><integer>3600</integer>
    <key>RunAtLoad</key><true/>
</dict>
</plist>
""" % (PLIST_LABEL, python, script)


def checker_installed():
    return os.path.exists(PLIST_PATH)


def install_checker():
    os.makedirs(os.path.dirname(PLIST_PATH), exist_ok=True)
    with open(PLIST_PATH, "w") as f:
        f.write(plist_xml())
    subprocess.run(["launchctl", "unload", PLIST_PATH], capture_output=True)
    subprocess.run(["launchctl", "load", PLIST_PATH], capture_output=True)
    log("background checker installed")


def uninstall_checker():
    subprocess.run(["launchctl", "unload", PLIST_PATH], capture_output=True)
    if os.path.exists(PLIST_PATH):
        os.remove(PLIST_PATH)
    log("background checker removed")


# ---------------------------------------------------------------- menu

def line():
    print("-" * 46)


def describe_payload(p):
    t = p.get("type", "none")
    if t == "email":
        return "EMAIL to %s  (subject: %s)" % (p.get("recipient", "?"), p.get("subject", "?"))
    if t == "file":
        return "WRITE MESSAGE to file %s" % p.get("path", "?")
    if t == "command":
        return "RUN COMMAND: %s" % p.get("command", "?")
    return "NOT CONFIGURED"


def show_status(state):
    line()
    print("  DEAD-MAN'S SWITCH — STATUS")
    line()
    if state["fired"]:
        print("  *** SWITCH HAS FIRED ***  (see deadman.log)")
    print("  Armed:          %s" % ("YES" if state["armed"] else "no (safe)"))
    print("  Check-in every: %s days (warnings start %s days before deadline)"
          % (state["interval_days"], state["warn_days"]))
    print("  Last check-in:  %s" % fmt_ts(parse_ts(state["last_checkin"])))
    deadline = deadline_of(state)
    print("  Deadline:       %s" % fmt_ts(deadline))
    if deadline and state["armed"]:
        remaining = deadline - now()
        if remaining.total_seconds() > 0:
            print("  Time left:      %d days, %d hours"
                  % (remaining.days, remaining.seconds // 3600))
        else:
            print("  Time left:      OVERDUE — payload fires on next hourly check")
    print("  Payload:        %s" % describe_payload(state.get("payload", {})))
    print("  Background checker: %s"
          % ("installed (hourly)" if checker_installed() else "NOT INSTALLED — switch cannot fire"))
    line()


def ask(prompt, default=None):
    suffix = " [%s]" % default if default is not None else ""
    val = input("  %s%s: " % (prompt, suffix)).strip()
    return val if val else (str(default) if default is not None else "")


def configure_payload(state):
    print()
    print("  What should happen if you fail to check in?")
    print("   1. Send an email (via the Mail app)")
    print("   2. Write a message into a file")
    print("   3. Run a custom command")
    print("   4. Clear payload (switch can't fire)")
    choice = input("  Choose 1-4: ").strip()
    if choice == "1":
        recipient = ask("Recipient email address")
        if not recipient:
            print("  Cancelled."); return
        subject = ask("Subject", "Message from Annika (automated dead-man's switch)")
        print("  Message body (finish with a single '.' on its own line):")
        lines = []
        while True:
            row = input("  ")
            if row.strip() == ".":
                break
            lines.append(row)
        state["payload"] = {"type": "email", "recipient": recipient,
                            "subject": subject, "message": "\n".join(lines)}
    elif choice == "2":
        path = ask("File to write to", os.path.expanduser("~/Desktop/IF_YOU_ARE_READING_THIS.txt"))
        print("  Message (finish with a single '.' on its own line):")
        lines = []
        while True:
            row = input("  ")
            if row.strip() == ".":
                break
            lines.append(row)
        state["payload"] = {"type": "file", "path": path, "message": "\n".join(lines)}
    elif choice == "3":
        cmd = ask("Shell command to run")
        if not cmd:
            print("  Cancelled."); return
        state["payload"] = {"type": "command", "command": cmd}
    elif choice == "4":
        state["payload"] = {"type": "none"}
    else:
        print("  Cancelled."); return
    save_state(state)
    print("  Payload saved: %s" % describe_payload(state["payload"]))


def menu():
    while True:
        state = load_state()
        show_status(state)
        print("   1. CHECK IN  (resets the clock)")
        print("   2. Arm / disarm")
        print("   3. Set check-in interval")
        print("   4. Configure payload")
        print("   5. Test payload now")
        print("   6. %s background checker"
              % ("Reinstall" if checker_installed() else "Install"))
        print("   7. Uninstall background checker")
        print("   8. View log")
        print("   9. Quit")
        choice = input("  Choose 1-9 (Enter = check in): ").strip()

        if choice in ("", "1"):
            state["last_checkin"] = now().isoformat()
            state["last_warn"] = None
            state["fired"] = False
            save_state(state)
            log("checked in")
            print("\n  ✓ Checked in. Clock reset.\n")
        elif choice == "2":
            if state["armed"]:
                state["armed"] = False
                save_state(state)
                log("disarmed")
                print("\n  Switch DISARMED. It cannot fire.\n")
            else:
                problems = []
                if state.get("payload", {}).get("type", "none") == "none":
                    problems.append("no payload configured (option 4)")
                if not checker_installed():
                    problems.append("background checker not installed (option 6)")
                if problems:
                    print("\n  Cannot arm yet: " + "; ".join(problems) + "\n")
                else:
                    state["armed"] = True
                    state["fired"] = False
                    state["last_checkin"] = now().isoformat()
                    save_state(state)
                    log("armed (interval %s days)" % state["interval_days"])
                    print("\n  Switch ARMED. Clock started now.\n")
        elif choice == "3":
            days = ask("Check in every how many days?", state["interval_days"])
            warn = ask("Start warning how many days before the deadline?", state["warn_days"])
            try:
                state["interval_days"] = max(1, int(days))
                state["warn_days"] = max(0, min(int(warn), state["interval_days"] - 1))
                save_state(state)
                print("  Saved.")
            except ValueError:
                print("  Not a number — unchanged.")
        elif choice == "4":
            configure_payload(state)
        elif choice == "5":
            print("\n  Running payload in TEST mode...")
            try:
                print("  → %s\n" % fire_payload(state, test=True))
            except Exception as e:
                print("  ✗ Test failed: %s\n" % e)
        elif choice == "6":
            install_checker()
            print("\n  Background checker installed (runs hourly, and at login).\n")
        elif choice == "7":
            uninstall_checker()
            print("\n  Background checker removed. Switch cannot fire.\n")
        elif choice == "8":
            print()
            if os.path.exists(LOG_PATH):
                with open(LOG_PATH) as f:
                    for row in f.readlines()[-15:]:
                        print("  " + row.rstrip())
            else:
                print("  (log is empty)")
            print()
        elif choice == "9":
            return
        if choice not in ("9",):
            input("  Press Enter to continue...")


if __name__ == "__main__":
    if "--check" in sys.argv:
        run_check()
    else:
        try:
            menu()
        except (KeyboardInterrupt, EOFError):
            print()
