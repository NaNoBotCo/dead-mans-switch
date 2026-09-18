# Dead-Man's Switch

Local, offline, stdlib-only. You check in on a schedule; if you ever stop,
a payload you configured fires — once — and the switch disarms.

## How to use

Double-click **Dead Mans Switch.command** on the Desktop.

- **Press Enter (or 1)** — check in. That's the whole daily/weekly ritual.
- **4** — configure the payload: email someone via Mail.app, write a
  message into a file, or run a command.
- **5** — test the payload safely (email tests are clearly marked [TEST];
  command payloads are never run in test mode).
- **6** — install the background checker (hourly launchd job).
- **2** — arm. Arming requires a payload AND the checker installed, and
  resets the clock to now.

## How it fires

A launchd agent (`~/Library/LaunchAgents/com.annika.deadman.plist`) runs
`deadman.py --check` every hour and at login. Starting `warn_days` before
the deadline it posts macOS notifications (at most every 6 h) reminding
you to check in. If the deadline passes, it fires the payload, logs it,
and disarms. If firing fails (e.g. Mail unavailable) it retries hourly.

## Safety properties

- Ships **disarmed**; cannot arm without a payload + checker.
- Fires at most once, then disarms.
- Everything is local: `state.json` (config + clock), `deadman.log` (audit).
- Uninstall: menu option 7, or
  `launchctl unload ~/Library/LaunchAgents/com.annika.deadman.plist && rm ~/Library/LaunchAgents/com.annika.deadman.plist`

## Limits to know about

- The Mac must be **on and awake** for the checker to run; a machine that
  is off cannot fire the switch. For a switch that must survive your
  machine, you'd want a server/cloud version — this one is deliberately
  local-only.
- Email payload sends through the Mail app, so Mail must be set up with a
  working account. Use option 5 to verify before relying on it.


## Licence

Records, prose and pages: CC BY-SA 4.0. Code: AGPL-3.0-or-later. Anything
carried in from elsewhere keeps its own terms — see [LICENSE](LICENSE) and [NOTICE.txt](NOTICE.txt).

**Commercial licence.** If share-alike doesn't fit your use — a corpus, a
product, a model — a commercial licence is available.
[Open an issue](https://github.com/NaNoBotCo/dead-mans-switch/issues) and say what you need.

---

Contact: Nan · nan@motdang.net · Sponsor: [Ko-fi](https://ko-fi.com/defiantchiangmai) · [Patreon](https://www.patreon.com/nanobotco)
