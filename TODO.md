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
12. (low) Show a privacy-reduced Agent ETA summary on the locked screen if a supported route keeps it simple. Proposed
    content: counts per state, the nearest ETA and usage percentages with reset times, with no session titles,
    labels, paths, prompts or account names. Candidate routes on Plasma 6.3.6, none tested yet, are an MPRIS player,
    which the lock screen's media controls (`lockscreen/MediaControls.qml` in the `org.kde.plasma.desktop` shell)
    already show and which would also appear in the panel's media widget; a wallpaper plugin selected for the lock
    screen that renders the summary; or a user-level override of the shell's lockscreen QML, which Plasma updates can
    break. Drop the item if every route needs patched system files or a privileged helper. Evaluate the routes first
    (ca. 1 hour).
13. (low) Two handoff cases stay open. A handoff killed with SIGKILL while its source is frozen leaves it frozen;
    `status.json` names `systemctl --user thaw` in `resume_source`, but nothing runs it. An account row's batch to a
    Claude account without a registered name passes no `--account`, so `choose_account()` may pick another eligible
    account than the clicked one. Proposal: report dead handoffs with recovery instructions on the next
    `agent-eta list`, requiring confirmed destination cancellation before any thaw, and pass the account directory
    to the batch (ca. 2 hours).
15. (low) A Claude Code session that a handoff started holds no ExitPlanMode approval, so moving it on to Codex forks
    a summary and plans again. Proposal: count such a session as approved from the completed handoff record that
    started it with an approved plan (ca. 2 hours).

Waiting: counter-test for the agent-eta Codex permission fix of 0.66.7 (ca. 15 Minuten). The Codex weekly limit is
used up until 2026-10-08 03:22. In a Codex thread with the reviewer set to `user`, an escalated `sleep 60` must show
`waiting (permission)` until the click and `working` after it. In an `auto_review` thread the same command must show
`working` within about 10 seconds. It confirms that auto-review requests rarely reach the user, which so far rests on
the log database only.

## Bug follow-up (2026-10-18)

- Live Codex setup: Laptop handlers reviewed; both intended chats registered and appeared in the modal. Native
  working, idle and SessionEnd removal observed, with the independent reminder retained. Laptop Plasma reload and
  QML suite passed after sandbox access was changed. Laptop 1.1.2 red question status was confirmed
  live by the user; answering cleared the wait. Desktop native hook review and QML dependency installation remain
  pending. Confirm idle display after the current turn ends.
- 2026-10-22, TODO #17 completed locally on `fix/codex-cli-navigation`: Codex navigation is inferred from verified
  current process ownership. All 218 Python tests (including QML) and 27 JavaScript tests pass. After installation
  and Plasma reload, the live row action switched from a temporary shell tab to the existing CLI's Konsole tab and
  raised its window; the desktop thread URL was accepted and activated the desktop app. The temporary tab was closed.
  No Agent ETA QML errors appeared in the reload journal. Shared/remote servers without a proven local UI association
  explain that navigation is unavailable; the inspected native protocol exposes no terminal PID mapping.
