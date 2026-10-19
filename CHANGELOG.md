# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- TODO item 10 records the agreed Python model and widget contract refactor with its acceptance criteria
- TODO items 11 and 12 record the reset countdown fix and the lock screen summary
- QML tests in `test_qml/` for `WindowJumper.qml` and `SessionRow.qml` with Qt Quick Test, a stub
  `org.kde.taskmanager`, `test_qml.py` and a CI job in a `debian:trixie` container

## [1.1.2] - 2026-10-18

### Fixed

- Discard unfinished Codex hook pairs after Stop or Interrupt so rejected commands cannot keep an idle chat working;
  manual reminders and verified PID or lock jobs remain intact
- Recognize native asynchronous questions until every requested answer arrives, including after Stop; the immediate
  accepted result does not clear the waiting state

## [1.1.1] - 2026-10-18

### Fixed

- Manual reminders without a verified live owner or holder remain unknown in the non-working group, preserving
  deadlines and Mark done without contributing working counts, tray activity or progress
- Idle sessions count as working only with verified running background tasks

### Changed

- Document the existing Codex hook setup including SessionEnd, native review and fresh-event verification

## [1.1.0] - 2026-10-18

### Added

- `agent-eta tab PID...` makes the Konsole tab running one of the pids current over D-Bus and prints its window's
  caption titles; `AGENT_ETA_QDBUS_BIN` overrides qdbus

### Fixed

- The tray's jump raises the Konsole window the session runs in, not the first window of the Konsole process

## [1.0.0] - 2026-10-17

### Added

- Repository of its own, split from [bestcodename/ai](https://github.com/bestcodename/ai) 0.99.1 with the history of
  `scripts/agent-eta`; README, TODO, `composer.json` and a GitHub Actions workflow

### Changed

- `claude-account` is found through `AGENT_ETA_CLAUDE_ACCOUNT_BIN`, `~/.local/bin/claude-account` or `PATH`, no longer
  in a sibling folder of the checkout
- `docs/agent-eta.md` moved here; links into bestcodename/ai are absolute

## Before 1.0.0

agent-eta was versioned with bestcodename/ai until the split. The entries below are the agent-eta lines of that
repository's changelog, under its version numbers.

### bestcodename/ai 0.99.1 - 2026-10-17

#### Changed

- agent-eta plasmoid: a left or right click anywhere on an account's usage row opens the account menu, not only a right
  click on its name; account and session rows show a hand pointer where a click does something

### bestcodename/ai 0.99.0 - 2026-10-17

#### Added

- agent-eta: account menu item "Move all sessions here"

### bestcodename/ai 0.98.2 - 2026-10-16

#### Changed

- TODO.md: the live sync carries the agent-eta modal across both machines, with no cross-host code in agent-eta

### bestcodename/ai 0.97.0 - 2026-10-16

#### Added

- host-sync: `installs` area compares the copies made by this repo's installers with the checkout on each side and
  shows both HEADs; `--apply` reruns stale user installers and their follow-up, such as the plasmashell restart for
  the agent-eta widget, and lists stale root installs with their `sudo -A` command
- host-sync: `installs.json` manifest for the agent-eta widget, the git-guard hooks, dgpu, inference-fan-curve and
  nvidia-runfile, overridable with `HOST_SYNC_INSTALLS`

### bestcodename/ai 0.93.1 - 2026-10-15

#### Changed

- `scripts/agent-eta/agent-eta`: the Codex memory-consolidation sub-agent is never listed and its hook record is
  removed, instead of showing as "Codex memories" until its job finished

#### Removed

- `scripts/agent-eta/agent-eta`: the `internal` field of a session in `--json`
- `scripts/agent-eta/plasmoid`: the jump and copy guard for internal Codex threads

### bestcodename/ai 0.92.5 - 2026-10-15

#### Fixed

- agent-eta: a Codex thread whose usage limit has reset counts as idle since its failed turn ended, as the Codex app
  shows its age, instead of since the reset

### bestcodename/ai 0.92.3 - 2026-10-15

#### Changed

- agent-eta plasmoid: the usage headline (`56% · resets in …`, `blocked · resets in …`) moved from the account name
  row to the status line under it, beside `read Xm ago`, so it no longer reads as part of the entry above

### bestcodename/ai 0.92.2 - 2026-10-15

#### Changed

- TODO.md: item 4.7 records the missing `agent-eta set` for revising the ETA of an existing entry

### bestcodename/ai 0.92.1 - 2026-10-15

#### Fixed

- `scripts/agent-eta/agent-eta`: the Codex memory-consolidation sub-agent, which never fires `Stop`, leaves the list
  once its `memory_consolidate_global` job has finished instead of staying "working" for six hours; it is listed as
  "Codex memories" and marked `internal` in `--json`
- `scripts/agent-eta/plasmoid`: an internal Codex thread offers no `codex://threads/` jump or copy link
- `scripts/agent-eta/plasmoid`: an idle session that holds a running task shows a green dot and keeps the tray orb
  green, matching its place among the working sessions, instead of a yellow one

### bestcodename/ai 0.92.0 - 2026-10-15

#### Changed

- `scripts/agent-eta/agent-eta`: idle sessions turn dormant after 2h instead of 12h, so finished threads leave
  "Needs you"; the `--all` help names the threshold from the constant
- `scripts/agent-eta/agent-eta`: Codex threads archived in the app are left out until unarchived

#### Fixed

- `scripts/agent-eta/agent-eta`: a Codex turn stopped by `usage_limit_exceeded` before any window read 100% waits for
  the reset of the fullest window instead of staying stopped without a due time under "Needs you"

### bestcodename/ai 0.87.0 - 2026-10-15

#### Changed

- The agent-eta guide documents account actions, cache behavior and measured validation limits.

### bestcodename/ai 0.80.0 - 2026-10-06

#### Added

- agent-eta: faint ticks at every hour on the 5h usage bar and at every day on the 7d bar

### bestcodename/ai 0.78.0 - 2026-10-06

#### Added

- agent-eta: a tray widget setting for the half-width of a usage bar's yellow band, as a share of the usage past the
  tick, 66% by default

#### Fixed

- agent-eta: no thin gap of the track between the colour bands of a usage bar

### bestcodename/ai 0.77.0 - 2026-10-06

#### Added

- agent-eta: a tray widget setting that fades the yellow band of a usage bar into green and red, on by default, with
  the width of the fade

#### Changed

- agent-eta: the tray widget's usage bars fill in traffic-light bands, green below the tick, yellow around it and red
  where the usage runs far ahead of the time, and a reached limit yellow up to the tick and red after it

### bestcodename/ai 0.76.2 - 2026-10-06

#### Fixed

- agent-eta: blocked usage accounts ordered by the end of their block again, in table and tray widget

### bestcodename/ai 0.74.1 - 2026-10-05

#### Added

- TODO 2.1 (high): agent-eta keeps a logged-out account in the usage section as `Not logged in`, with an *X* and a
  *Log in* button

### bestcodename/ai 0.74.0 - 2026-10-05

#### Changed

- agent-eta: the usage table and the tray widget order the accounts by the 7-day reset first and the 5-hour reset
  second, instead of by whichever window resets first or the reset that ends a block

### bestcodename/ai 0.73.0 - 2026-10-05

#### Changed

- agent-eta tray widget: the line beside an account with room left names the reset that comes first next to its used
  share, as in `56% · resets in 49m (18:30)`

### bestcodename/ai 0.71.0 - 2026-10-05

#### Added

- agent-eta tray widget: the orb on the icon is a traffic light. It is red with the number of waiting sessions, yellow
  with the number of idle and overdue ones, green while all others work and absent when only dormant sessions exist
- agent-eta tray widget: every usage reset carries its countdown, as in `resets in 49m (18:30)` and
  `blocked · resets in 12h 13m (24:00)`
- agent-eta tray widget: a session's state shows when it began, as in `idle for 1h 5m (17:25)`

#### Changed

- agent-eta tray widget: session rows mark their state with a coloured dot instead of play, pause and stop icons
- agent-eta tray widget: the notification for a session that starts waiting is off by default
- agent-eta tray widget: only a waiting session makes the tray pulse, an overdue one turns the orb yellow

#### Fixed

- agent-eta tray widget: the popup no longer shows a horizontal scrollbar when everything fits

### bestcodename/ai 0.68.0 - 2026-10-05

#### Added

- `agent-eta` lists dsh sessions from dsh's own session logs, every session a running dsh process holds the lock of
  and nobody archived in the web UI, with its state, its waiting reason, its model and its web UI address. A turn that
  fails waits for you as `turn failed (<code>)` and goes dormant after twelve hours. A bash call open for ten seconds
  shows as a task without an ETA.
- `DSH_SESSION_ID` attaches `agent-eta add`, `run` and `turn` to the calling dsh session.
- Tray widget action *Open dsh web UI*, and the model in the detail line of a session.

### bestcodename/ai 0.67.0 - 2026-10-05

#### Added

- `agent-eta` tray widget for Plasma 6 in `scripts/agent-eta/plasmoid`. The icon carries a badge with the sessions that
  need you and a bar for the next ETA, hovering lists the sessions, and the popup shows every session and task with a
  progress bar in agent-eta's sections, dormant ones folded, followed by usage bars with an elapsed-time tick.
- Tray widget row actions to jump to the session's window, open the thread in Codex, open the project in PhpStorm, open
  the folder, copy the resume command and mark an `add` entry done.
- Tray widget notifications for a session that starts waiting, an ETA that turns overdue and a usage limit that resets,
  each switchable, sent once across both panel trays.
- `agent-eta list --json` fields `progress` on tasks and `eta_started`, `progress`, `section`, `pids`, `project_root`
  and `project_name` on sessions.
- `test_install.py` for `install.sh`, and node tests for the widget logic in `test_plasmoid.mjs`, run by the Python suite.

#### Changed

- `install.sh` copies the tray widget into `~/.local/share/plasma/plasmoids` and adds it to every system tray through
  plasmashell's scripting interface.
- `docs/agent-eta.md` describes the tray widget, the new JSON fields and the measurements of 2026-10-05, and
  `README.md` mentions the widget.

### bestcodename/ai 0.66.9 - 2026-10-05

#### Fixed

- `agent-eta` usage keeps the Codex row when the most recently written rollouts carry only null usage readings. It
  searches the five latest rollouts that hold a reading, at most 50 back, instead of the five latest rollouts.

#### Changed

- `docs/agent-eta.md` describes the wider search for the Codex usage reading.

### bestcodename/ai 0.66.7 - 2026-10-05

#### Fixed

- `agent-eta` no longer keeps a Codex thread at `waiting (permission)` after the request was decided. The reader ends
  the wait once the rollout transcript holds the output of the script that was open at the request, which also covers
  requests the auto-review agent decided without asking.

#### Changed

- `docs/agent-eta.md` explains how a permission wait ends, records the auto-review measurements and narrows the
  limit to scripts that wait long for an approved command.

### bestcodename/ai 0.66.6 - 2026-10-05

#### Changed

- `TODO.md` cross-project ranking re-ranked. The agent-eta tray overview moves ahead of the progress bar, sdwa5-vps
  deployment and the desktop off-site backup move up, every unranked item is ranked, the yt-dlp Mac test waits for an
  in-person Mac, the notebook's stable address waits for the second laptop-desktop sync, and the history rewrite is
  scheduled with agent-eta item 1.1.

### bestcodename/ai 0.65.0 - 2026-10-04

#### Changed

- `agent-eta` reads sessions, transcript titles and usage windows from every registered account. With at least two
  accounts the AGENT column reads `claude/<name>`, and the usage table has a row per account.
- `agent-eta` lists a session whose account has a reached usage limit as stopped until that limit resets, unless it
  is working or dormant.
- `agent-eta` separates the session table from the usage table with a blank line instead of `---`.

### bestcodename/ai 0.64.0 - 2026-10-04

#### Added

- `agent-eta` ends with a usage table. For every Claude Code and Codex usage window it shows the used share against
  the share of the window that has passed, the pace as their difference in percentage points with `ahead` or `ok`,
  the time until the reset as REMAINING and DUE, and the age of the reading. Each agent has a row with the worst value
  per column and its windows as `└` rows below. Agents with room left come first and agents with a reached limit follow in a section of their own,
  each sorted by the soonest reset. `--json` carries the windows as `usage`.

### bestcodename/ai 0.63.2 - 2026-10-04

#### Added

- `docs/agent-eta.md` records the first live Codex `PermissionRequest`, which showed the thread as waiting.

#### Changed

- `agent-eta` shows every section of the session table, and an empty one says so, for example
  `(no working sessions)`. This replaces `No agent sessions.` and `(no active sessions)`.

### bestcodename/ai 0.63.1 - 2026-10-04

#### Changed

- `agent-eta` separates its sections with a `---` line. Waiting and idle sessions form the first section, working
  sessions the second, threads stopped by a usage limit the third and dormant sessions the last. The dormant section
  under `--all` no longer has a heading of its own.

### bestcodename/ai 0.63.0 - 2026-10-04

#### Added

- `agent-eta --all` lists dormant sessions, which are idle for more than 12 hours without a running task, in a section
  of their own. `--json` marks every session with `dormant`.

#### Changed

- `agent-eta` leaves dormant sessions out of the list and ends it with a line that counts them.
- `agent-eta` sorts sessions by how soon they need you. Waiting sessions come first, then idle ones, then working ones
  by remaining time, then threads stopped by a usage limit and last the dormant ones, also in `--json`.

### bestcodename/ai 0.62.0 - 2026-10-03

#### Added

- `agent-eta` lists every running agent session with its state, waiting, working or idle, how long it has been in that
  state in a column of its own, its ETA and its background tasks underneath. Sessions waiting for an answer come first. Claude Code sessions
  come from the registry Claude Code writes itself, including `waitingFor`, so they need no hook. Codex threads get
  their state from new `UserPromptSubmit`, `PermissionRequest`, `Stop` and `Interrupt` hooks, and a question asked
  through `request_user_input` or a plan waiting for approval, which no hook sees, from the thread's rollout
  transcript.
- `agent-eta turn --eta DUR [--label TEXT]` sets an ETA for the current turn of the calling session, and it ends on its
  own with the turn. The agent rules ask for it on turns longer than ca. 10 minutes.
- `agent-eta --tasks` keeps the flat task list, and `--json` carries `sessions` next to `tasks`.

#### Changed

- `docs/claude-code-config.md` allows `agent-eta turn` and says where the Claude Code session state comes from.

### bestcodename/ai 0.61.0 - 2026-10-03

#### Added

- `scripts/agent-eta/agent-eta`, which lists the background tasks of every Claude Code, Codex and local-model session
  with their ETAs, shortest first and overdue tasks on top. A Claude Code `PostToolUse` hook records every background
  Bash command with the ETA from its description, and a Codex `PreToolUse` and `PostToolUse` pair records every shell
  call with the ETA from a trailing `# ETA` comment. Neither hook lists a command that already goes through `agent-eta
  run`. `run`, `add` and `done` cover everything else. The reader decides
  for itself whether a task still runs, through its pid and starttime, an `flock` that works across the Codex sandbox's
  pid namespace, or an expiry. `install.sh` links it into `~/.local/bin`, 25 tests cover it, and
  `docs/agent-eta.md` describes it.
- `TODO.md` item 1 now holds the agent-eta follow-ups, which are a progress bar per task, further surfaces such as a
  tray icon, phone notifications and a web app, and process matching for Codex tasks. The Codex hooks passed their
  live counter-test, including the shell calls Codex nests in its code-mode `exec`, and a cross-test with three Claude
  Code and five Codex tasks in parallel passed as well.

#### Changed

- `scripts/llm-handoff/run-local.sh` lists each run in agent-eta with its timeout as the ETA, when the tool is
  installed. The selftest checks the registration through a stub and has 21 checks now.
- `docs/claude-code-config.md` documents the agent-eta hook and the permission rules for `list`, `add` and `done`.
- CI runs the agent-eta tests and lints its installer at the default shellcheck severity.

#### Removed

- `TODO.md` priority item 1.1, the ETA list of background tasks across all agent sessions, which agent-eta now provides.

