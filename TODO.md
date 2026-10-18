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
- Pending live setup: the two current Codex chats were absent because no agent-eta hooks were installed in
  `~/.codex/hooks.json` and no hook registrations existed. The existing handlers already support tracking and
  SessionEnd; no discovery redesign is justified. A concrete hook file is prepared, but the sandbox mount error
  blocked installation. Complete native review and verify fresh events in both chats, including working, waiting,
  idle and SessionEnd, before marking this resolved. Historical database rows alone are insufficient.
