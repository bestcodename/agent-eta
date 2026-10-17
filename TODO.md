# TODO

Open work on agent-eta. Moved from the global TODO of
[bestcodename/ai](https://github.com/bestcodename/ai) on 2026-10-17, where this list was item 6 of the cross-project
priority.

1. (next) Test the widget's QML wiring headlessly. Use Qt Quick Test (`qmltestrunner`, offscreen) with stub
   `org.kde.taskmanager` and `Runner` modules on the test import path, load the real `WindowJumper.qml` and
   `SessionRow.qml`, and assert that a click runs `agent-eta tab`, picks the window and calls `requestActivate`. The
   hover and the context menu actions follow the same way. Run it in GitHub CI with the Qt 6 test packages, since
   stefan-notebook has only the qtchooser wrapper. It replaces most of the hand checks in item 3 and the
   [docs/agent-eta.md](docs/agent-eta.md) "Limits" note on `xdotool`; a containerized Plasma with fake input was
   rejected as too heavy for what it adds (ca. 4 Stunden)
2. (next) Probe whether the TasksModel `DisplayRole` of a Konsole window equals its KWin caption, such as
   "Handoff 3d — Konsole". `pickWindow` matches the titles of `agent-eta tab` against it, and so far only the KWin
   caption was measured. A small `qml` script that prints `AppPid` and `DisplayRole` per window settles it
   (ca. 20 Minuten)
3. (next) Check *Jump to window* of the tray widget on stefan-notebook, which runs Wayland. The widget of 0.71.0
   was installed there on 2026-10-05, but so far it was only seen working on the desktop under X11. The check
   needs a running Claude Code session on the notebook (ca. 10 Minuten)
   The desktop handler accepted the current thread's `codex://` link on 2026-10-14. The widget's actual
   *Open thread in Codex* click still needs a visual target check (ca. 5 Minuten).
4. (low) Match a Codex task to its process through `CODEX_THREAD_ID` in `/proc/*/environ`. Only worth it if Codex
   entries whose process ended unpolled stay listed until they expire often enough to mislead, see
   [docs/agent-eta.md](docs/agent-eta.md) "Limits" (ca. 3 Stunden)
5. (low) Further surfaces for `agent-eta list --json`, proposed and not evaluated yet. They are phone notifications
   when a task turns overdue (ca. 2 Stunden) and a web app (ca. 8 Stunden)
6. (low) Show a turn that ends with a question in plain text as waiting rather than idle. Neither agent marks such a
   turn, so the candidate is a `Stop` hook that reads the last assistant message from `transcript_path` and checks
   whether it ends with a question mark. It is a heuristic and was left out of 0.62.0 on purpose (ca. 2 Stunden)
7. (next) Investigate the reported `/effort effort max` session title appearing as command-name markup.
   Reproduce it and trace the title through the native registry, transcript title, CLI and widget.
   Confirm the source before proposing a fix, then preserve the reproduction as a regression fixture
   (ca. 1 hour).
8. (low) Make *Jump to window* select the PhpStorm terminal tab a Claude Code session runs in. Today it only
   raises the project window, and PhpStorm has no action that selects a terminal tab by name, which
   `search_ide_actions "terminal"` showed on 2026-10-15. Spike the routes without a plugin in this order. First, a
   startup `.kts` script under `extensions/com.intellij/startup/` that watches a jump file and selects the tab whose
   shell process is an ancestor of the session's pid, if PhpStorm 2026.2 still runs startup scripts. Second,
   `run_inspection_kts` through the PhpStorm MCP server calling `contentManager.setSelectedContent`. Third,
   `ActivateTerminalToolWindow` through MCP, which shows the terminal but not the tab. A plugin is the last
   resort (spike ca. 2 Stunden)
9. (next) Add `agent-eta set <id> --eta <duration> [--label …]`, which rewrites the ETA of an existing entry.
   Today `claude_post` records a background task's ETA once from its description, and `add`/`done` can only
   create or delete entries, so a revised ETA becomes a second entry beside the stale one. On 2026-10-15 a
   Kochan watcher kept its 8-hour worst case while the Stage deploy it waited for was ten minutes out. Cover
   hook-recorded (`claude-<task>`) and `add` entries in `test_agent_eta.py`, document it in
   [docs/agent-eta.md](docs/agent-eta.md), and change the global CLAUDE.md ETA rule from "add a new entry" to
   "update with `set`" (ca. 1 Stunde)
10. Add a UI setting, enabled by default, for time labels on the Agent ETA modal's usage progress bars.
   Show weekdays for the 7-day bars and hours for the 5-hour bars, aligned with each window's start and
   reset time in the local timezone. Keep the labels readable at the modal's supported widths.
11. Show an estimated quota exhaustion time for each usage progress bar in the Agent ETA modal, or at least
   for each account. Derive the average consumption rate from the quota already used and the elapsed time
   in the current window. Estimate the remaining time as `(100 - usedPercent) / (usedPercent / elapsedTime)`.
   Prefer a separate estimate per window; an account summary should use the earliest projected exhaustion.
   Label the result as an estimate at the current average rate and distinguish it from the reset time.
   Handle zero usage, zero elapsed time, missing or stale readings, and exhausted quotas explicitly.
   If the window resets before projected exhaustion, show that the quota is estimated to last until reset.

Waiting: counter-test for the agent-eta Codex permission fix of 0.66.7 (ca. 15 Minuten). The Codex weekly limit is
used up until 2026-10-08 03:22. In a Codex thread with the reviewer set to `user`, an escalated `sleep 60` must show
`waiting (permission)` until the click and `working` after it. In an `auto_review` thread the same command must show
`working` within about 10 seconds. It confirms that auto-review requests rarely reach the user, which so far rests on
the log database only.
