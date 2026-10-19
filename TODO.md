# TODO

Open work on agent-eta. Moved from the global TODO of
[bestcodename/ai](https://github.com/bestcodename/ai) on 2026-10-17, where this list was item 6 of the cross-project
priority.

1. (next) Check the widget's *Open thread in Codex* click visually. The desktop handler accepted the current
   thread's `codex://` link on 2026-10-14, but the click itself has not been watched yet (ca. 5 Minuten)
2. (low) Match a Codex task to its process through `CODEX_THREAD_ID` in `/proc/*/environ`. Only worth it if Codex
   entries whose process ended unpolled stay listed until they expire often enough to mislead, see
   [docs/agent-eta.md](docs/agent-eta.md) "Limits" (ca. 3 Stunden)
3. (low) Further surfaces for `agent-eta list --json`, proposed and not evaluated yet. They are phone notifications
   when a task turns overdue (ca. 2 Stunden) and a web app (ca. 8 Stunden)
4. (low) Show a turn that ends with a question in plain text as waiting rather than idle. Neither agent marks such a
   turn, so the candidate is a `Stop` hook that reads the last assistant message from `transcript_path` and checks
   whether it ends with a question mark. It is a heuristic and was left out of 0.62.0 on purpose (ca. 2 Stunden)
5. (next) Investigate the reported `/effort effort max` session title appearing as command-name markup.
   Reproduce it and trace the title through the native registry, transcript title, CLI and widget.
   Confirm the source before proposing a fix, then preserve the reproduction as a regression fixture
   (ca. 1 hour).
6. (low) Make *Jump to window* select the PhpStorm terminal tab a Claude Code session runs in. Today it only
   raises the project window, and PhpStorm has no action that selects a terminal tab by name, which
   `search_ide_actions "terminal"` showed on 2026-10-15. Spike the routes without a plugin in this order. First, a
   startup `.kts` script under `extensions/com.intellij/startup/` that watches a jump file and selects the tab whose
   shell process is an ancestor of the session's pid, if PhpStorm 2026.2 still runs startup scripts. Second,
   `run_inspection_kts` through the PhpStorm MCP server calling `contentManager.setSelectedContent`. Third,
   `ActivateTerminalToolWindow` through MCP, which shows the terminal but not the tab. A plugin is the last
   resort (spike ca. 2 Stunden)
7. (next) Add `agent-eta set <id> --eta <duration> [--label …]`, which rewrites the ETA of an existing entry.
   Today `claude_post` records a background task's ETA once from its description, and `add`/`done` can only
   create or delete entries, so a revised ETA becomes a second entry beside the stale one. On 2026-10-15 a
   Kochan watcher kept its 8-hour worst case while the Stage deploy it waited for was ten minutes out. Cover
   hook-recorded (`claude-<task>`) and `add` entries in `test_agent_eta.py`, document it in
   [docs/agent-eta.md](docs/agent-eta.md), and change the global CLAUDE.md ETA rule from "add a new entry" to
   "update with `set`" (ca. 1 Stunde)
8. Add a UI setting, enabled by default, for time labels on the Agent ETA modal's usage progress bars.
   Show weekdays for the 7-day bars and hours for the 5-hour bars, aligned with each window's start and
   reset time in the local timezone. Keep the labels readable at the modal's supported widths.
9. Show an estimated quota exhaustion time for each usage progress bar in the Agent ETA modal, or at least
   for each account. Derive the average consumption rate from the quota already used and the elapsed time
   in the current window. Estimate the remaining time as `(100 - usedPercent) / (usedPercent / elapsedTime)`.
   Prefer a separate estimate per window; an account summary should use the earliest projected exhaustion.
   Label the result as an estimate at the current average rate and distinguish it from the reset time.
   Handle zero usage, zero elapsed time, missing or stale readings, and exhausted quotas explicitly.
   If the window resets before projected exhaustion, show that the quota is estimated to last until reset.
10. (next) Make Python authoritative for shared Agent ETA rules, following the refactor agreed on 2026-10-19.
    Keep the native Plasma widget, Python backend, polling model, layout and color policy. QML and small
    JavaScript helpers retain presentation and interactions. Correct inconsistent activity labels across surfaces.
    Implementation and acceptance criteria:

    - Extract a pure, typed Python model for effective activity, stable identities, sections, summary counts,
      progress selection and usage grouping. Keep process inspection, hooks, storage and account refresh outside
      the model. Build one snapshot with one timestamp for terminal and JSON output, without mutating inputs.
    - Preserve the reported agent state for diagnosis; derive effective activity separately. An idle owner with
      verified background work displays as working. Unattached reminders remain unknown and contribute no work.
    - Extend `list --json --all` additively with `schema_version: 1`, stable session/window keys, `activity_state`,
      semantic light values, `summary`, ordered `sections`, ordered `usage_groups` and `notification_signals`.
      Preserve existing fields, section numbers and task references. Groups reference existing entities by key.
      Summary supplies counts, tray status, badge count and the selected progress-session key.
    - Compute notification eligibility in Python. Signals describe identity, active condition, rising/falling
      edge, new-item behavior, deduplication key and message parameters for waiting, overdue and usage-reset events.
      The widget compares successive signals and handles formatting, preferences, delivery and duplicate
      suppression. Preserve first-poll suppression and existing notification behavior.
    - Validate the contract in the widget and remove duplicate activity/count/order rules. Keep date/duration
      formatting, usage-bar geometry, window selection, clipboard, menus and folding in QML/JavaScript. Render
      backend decisions consistently in the CLI, rows, tooltips, summaries and notifications.
    - Retain the last valid snapshot and its update time on malformed/incompatible output or timeout; show an
      explicit failure, including an update-required message for an older CLI. Notify only between valid snapshots.
      Retain polling intervals and menu pauses; use unique request identities, bounded lifetimes and rejection of
      late completions so stale responses cannot replace newer data.
    - Move domain assertions into Python tests and share Python-produced contract fixtures with JavaScript/QML
      tests. Cover reminder retention, verified jobs, missing PostToolUse, Stop/Interrupt/SessionEnd, partial async
      answers, dormant sessions, account limits, usage ordering, stale/missing readings, resets, multiple trays,
      malformed contracts, timeouts and out-of-order completions. Keep UI and formatting coverage in JS/QML.
    - Run Python, JavaScript, QML and installer suites. Verify live working, red question wait, answered/working
      and idle states; compare CLI/widget classifications, counts and progress. Test Mark done on disposable
      entries only. Recheck both checkouts and preserve unrelated work, including desktop `.idea/`.
    - Continue the existing feature branch unless its state has changed; release as 1.2.0 or the next unused minor.
      Update README, architecture/contract documentation, changelog and TODO records. Install the same tested
      version on laptop and desktop, reload Plasma and verify the modal. Preserve storage formats, ownership,
      expiry, hook definitions and native trust records. Desktop native hook review remains a user step.
      Remote push and integration merge require separate authorization. Implementation remains pending.

Waiting: counter-test for the agent-eta Codex permission fix of 0.66.7 (ca. 15 Minuten). The Codex weekly limit is
used up until 2026-10-08 03:22. In a Codex thread with the reviewer set to `user`, an escalated `sleep 60` must show
`waiting (permission)` until the click and `working` after it. In an `auto_review` thread the same command must show
`working` within about 10 seconds. It confirms that auto-review requests rarely reach the user, which so far rests on
the log database only.

## Bug follow-up (2026-10-18)

- Fixed in 1.1.1: Prevent orphaned Claude ETA tasks from appearing as working sessions after handoff or completion.
  Reproduction: the Claude session is absent, but its retained manual SEC reminder (`add-afa18602`) creates a
  synthetic working row. The reminder now remains unknown and keeps its deadline and Mark done action; verified
  running background tasks remain working. No reminders are automatically completed.
- Fixed in 1.1.2: A rejected Codex command missed PostToolUse and kept this idle chat in the working section despite
  its native Stop event. Discard completed-turn hook pairs while preserving reminders and verified jobs.
- Fixed in 1.1.2: Native request_user_input_async questions were not recognized. Track delivery separately from
  answers, retain waiting after Stop and clear each question only from its matching native reply.
- Live Codex setup: Laptop handlers reviewed; both intended chats registered and appeared in the modal. Native
  working, idle and SessionEnd removal observed, with the independent reminder retained. Laptop Plasma reload and
  QML suite passed after sandbox access was changed. Laptop 1.1.2 red question status was confirmed
  live by the user; answering cleared the wait. Desktop native hook review and QML dependency installation remain
  pending. Confirm idle display after the current turn ends.
