# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.1.0] - 2026-10-26

### Added

- The private tmux server loads agent-eta's own `tmux.conf` with mouse support, 50000 lines of scrollback and agent titles in the status line
- Each viewer gets its own grouped tmux session, so several agents can be shown in separate windows

### Changed

- Navigation focuses the window already showing an agent, or opens a new one instead of switching the existing window
- A handoff moves every window showing its source to the destination

## [2.0.0] - 2026-10-26

### Added

- Managed tmux launch, CLI resume and attachment navigation for Claude Code and Codex
- A private tmux server service and individual agent scopes with verified process identities

### Changed

- Cross-provider handoffs require managed tmux sessions; unmanaged sessions remain visible and can be closed and resumed through the managed launcher
- Konsole is the default attachment viewer and no longer controls handoff lifetime; Codex desktop launches remain available
- The installer requires tmux, and local Claude-account migration reuses its native terminal extension

### Fixed

- Successful handoffs remove the source process and pane before reporting completion
- Failed or cancelled destinations must be confirmed stopped before the source thaws; uncertain ownership keeps the source paused
- Claude receives access to its private handoff folder so reading the plan needs no extra permission approval
- Python test failures include their tracebacks in CI annotations
- tmux's automatic pane scopes cannot move agents out of their owned scopes

## [1.3.2] - 2026-10-25

### Fixed

- Codex CLI rows focus their existing terminal window and Konsole tab instead of opening the desktop app;
  desktop rows keep their thread links. The additive `navigation` field in `list --json` identifies the target
  from verified current process ownership. Shared or remote hosts without a proven UI association explain why
  navigation is unavailable, and older listings retain their existing behaviour
- The QML CI job installs the Plasma5Support QML module and executable data engine required by the runner tests

## [1.3.1] - 2026-10-25

### Fixed

- Handoff destinations start in their own transient systemd user service and a separate Konsole process, so
  controller service cleanup does not terminate them after the source exits
- Terminal execution failures fail the move and thaw the source without ending it

### Changed

- Cross-provider handoffs require systemd 254+; terminal overrides use the same independent service

## [1.3.0] - 2026-10-20

### Added

- A handoff refuses a destination folder that Claude Code or Codex does not trust yet, before
  the source is paused and again before the launch, and names the remedy
- A refused handoff sends a notification outside `--dry-run`
- TODO items 14 to 16 record the late-registration race, the approval lost on a second hop and the plan read
  that asks permission in Manual mode

### Changed

- An approved Claude Code destination starts with `--permission-mode manual`, and its prompt says not to ask for
  approval again

### Fixed

- A native plan the source writes while the handoff waits replaces a forked summary
- `plan_origin` names the plan that was handed over

## [1.2.2] - 2026-10-20

### Fixed

- A handoff to Codex starts the desktop app's bundled CLI with `--no-daemon`, without which it exited at once

## [1.2.1] - 2026-10-20

### Added

- `test_handoff_e2e.py` runs a handoff end to end against a real bash job in a pty with the real collectors and
  the cgroup freezer
- `AGENT_ETA_HANDOFF_REGISTER_TIMEOUT` and `AGENT_ETA_HANDOFF_POLL`
- TODO item 13 records the handoff cases left open

### Fixed

- Countdowns count whole clock minutes, so the widget's `resets in`, `for` and row ETAs and the CLI's REMAINING
  and FOR equal the difference of the clock times beside them; a 06:55 reset read `2h 32m` at 04:22
- The handoff pauses its source with the cgroup freezer in a transient user scope instead of SIGSTOP, which
  handed the terminal of a foreground job back to its shell
- Any error, and SIGHUP to the handoff, thaws the source and records the move
- The handoff resolves the Codex CLI off PATH and refuses before the pause when it is missing
- A Codex destination registers by its first user message, beyond the first 64 KiB of its rollout
- The handoff refreshes progress, next step, git state and command once the source is paused
- The owner of tasks without a live session offers no handoff
- A test meant to turn the source busy after the pause turned it busy before

### Removed

- TODO item 11, the reset countdown

## [1.2.0] - 2026-10-20

### Added

- TODO item 10 records the agreed Python model and widget contract refactor with its acceptance criteria
- TODO items 11 and 12 record the reset countdown fix and the lock screen summary
- QML tests in `test_qml/` for `WindowJumper.qml` and `SessionRow.qml` with Qt Quick Test, a stub
  `org.kde.taskmanager`, `test_qml.py` and a CI job in a `debian:trixie` container
- `agent_eta_model.py`, a pure model that builds one snapshot per listing with effective activity, ETAs, order,
  sections, tray summary, usage groups and notification signals, covered by `test_model.py`
- `list --json` contract schema 1 with `schema_version`, stable keys, `reported_state`, `activity_state`,
  `activity_label`, semantic `light`, `summary`, `sections`, `usage_groups`, `notification_signals` and `labels`
- Contract fixtures in `test_fixtures/contract-v1/`, written by the model and read by the JavaScript and QML tests
- QML tests for contract rendering and for `Runner.qml` timeouts and late answers
- `agent-eta handoff SOURCE... --to claude|codex` hands Claude Code sessions and Codex CLI threads over to the
  other provider with their plan, phase, progress, branch and dirty paths, gated by SIGSTOP and confirmed by the
  destination's registration; Claude to Claude delegates to `claude-account handoff --only`
- `agent_eta_handoff.py` with `test_handoff.py`, which drives the gate with real processes
- Contract sessions carry `handoff` with `available`, `reason`, `targets` and the latest move's `status`
- The Codex Stop hook hands a thread to Claude Code at 90 % of its 5-hour or 95 % of its weekly window, once per
  window, with `codex_handoff` settings in `~/.config/agent-eta/config.json`
- The session menu offers a handoff to the other provider, disabled with the reason, and rows show a pending or
  failed handoff
- Account rows move all Codex sessions to a Claude account and all Claude sessions to Codex, through
  `account handoff ID --from claude|codex`

### Changed

- The widget validates each listing, keeps the last valid one on a failure and names an outdated CLI
- The widget takes order, sections, counts, usage groups and notification eligibility from the contract
- Rows, tooltips, detail lines and the CLI STATE column show the activity label, so an idle owner of a running
  job reads working and a Codex turn with an open async question reads "working, question open"
- `Runner.qml` gives every run its own source and reports a timeout with exit code 124
- The dsh collectors moved to `agent_eta_dsh.py` and the state-file helpers to `agent_eta_store.py`
- `docs/agent-eta.md` documents contract schema 1, the handoff and its triggers

### Fixed

- The dormant toggle names the real 2-hour threshold instead of 12 hours
- A late answer to a timed-out run can no longer reach the callback of a newer run
- A Codex turn that runs on with an open async question is no longer marked stopped by a reached account limit

### Removed

- TODO item 10, done with this release

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

