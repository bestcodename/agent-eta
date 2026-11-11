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
16. (next) The modal's *Log in* button did not log in on 2026-11-03, while `/login` in Claude Code worked. The
    button runs `agent-eta account login <id>`, which spawns `claude auth login` in a separate terminal
    (`agent_eta_providers.launch`). Reproduce from a shell and from the button, and confirm the cause before a
    fix (ca. 1 Stunde)
17. (low) Add a toggle for Claude Code's claude.ai push of permission prompts and questions
    (`inputNeededNotifEnabled`, off since 2026-11-04) next to the *Notify when* checkboxes. The key lives in
    `claude/settings.json` of bestcodename/ai, so a flip shows up there as a diff, like a `/config` change.
    Proposal: an `agent-eta claude-push on|off|status` subcommand behind the checkbox (ca. 3 hours)
18. (next, bug) The tray icon's notification badge seemed to show a wrong number, reported on 2026-11-05. No
    snapshot of that moment exists. `summary()` in `agent_eta_model.py` sets `badge_count` to the waiting
    sessions as soon as one waits, otherwise to idle plus overdue, and leaves out dormant sessions and those in
    state `unknown`. So the badge never counts all sessions and switches meaning with the light. Next time it looks
    wrong, save `agent-eta list --json` and a screenshot of the badge and popup, then decide whether the count
    or the expectation is off. Fix with a regression case in `test_model.py` (ca. 1 Stunde)
19. (low, bug) A remote viewer that agent-eta did not open with its own argv is never focused. `viewer()` in
    `agent_eta_remote.py` compares every argument after `ssh` exactly against
    `ssh -t HOST ~/.local/bin/agent-eta attach SOURCE`. On 2026-11-05 a Konsole on stefan-desktop, opened at 16:16:20
    before 2.3.0 was installed there, ran `ssh -t notebook /home/stefanr/.local/bin/agent-eta attach claude:<id>`, and
    the lookup returned no viewer for it, so a click opens a new terminal instead. A viewer opened by hand with the
    documented `ssh -t HOST agent-eta attach claude:<session>` misses the same way. Proposal: compare the CLI
    argument by its basename too, with a case in `test_remote.py` (ca. 30 Minuten)

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
20. (low, proposal) Rename sessions from agent-eta, requested on 2026-11-05. Names are only read today, from
    Claude Code's `custom-title` or `ai-title` and Codex's thread name (see [docs/agent-eta.md](docs/agent-eta.md)).
    1. **`agent-eta rename <session> <name>`** plus a row action in the widget. It renames the session in its agent,
       for Claude Code presumably by typing `/rename <name>` into it rather than writing its transcript, and sets
       the Konsole tab title over D-Bus (`/Sessions/<n>`, next to `title` in `agent_eta_konsole.py`), which the
       window caption follows. A PhpStorm terminal tab has no such route, see #6 (ca. 3 Stunden)
    2. **`agent-eta rename --all`**, which asks each idle session for the shortest fitting name of its current work,
       checks that the answer differs from every other session's name, and applies it through 1. A working session
       is skipped rather than interrupted, and the answer must not land in the session's own work as a turn of
       substance. Delivering the prompt needs the same input route as 1, through Konsole, tmux or dsh
       (ca. 4 Stunden)
21. (low, proposal) `agent-eta account launch --cli` cannot carry a session's settings or a first prompt, so
    sessions still start outside managed tmux. On 2026-11-06 four sessions on stefan-desktop were moved into managed
    tmux by an ad-hoc script that wrote `claude-account run … --resume ID --model … --effort … --permission-mode …`
    into a tabs file for `agent-eta account-tabs`, because `account launch --resume` drops the model, effort and
    mode. The same day a takeover session started the Docmost driver from a hand-written
    `konsole --tabs-from-file`, which left it unmanaged and unreachable from the other machine's widget. Proposal:
    `account launch` takes `--model`, `--effort`, `--permission-mode` and an optional first prompt and passes them
    to `claude_command()` in `agent_eta_providers.py`, with cases in `test_accounts.py`; the takeover routine then
    starts its session through it (ca. 2 Stunden)
22. (low, proposal) A desktop Codex thread drops out of the list while the desktop app is closed. Since 2.4.1 a
    `codex exec resume` of a desktop thread keeps it listed through the app's app-server, but with the app closed
    the exec's `SessionEnd` still removes it. On 2026-11-06 the thread "Deploy Docmost on Proxmox", which a Claude
    session drives with `codex exec resume`, vanished after each turn that way. Proposal: keep a thread with
    `source` `vscode` after a client's `SessionEnd` without a holder, idle until `SESSION_IDLE_TTL`, and let its row
    open `codex://threads/<id>`, which starts the app. It contradicts the rule in
    [docs/agent-eta.md](docs/agent-eta.md) that navigation never falls back to a desktop link without a verified
    Codex process, so decide that rule first (ca. 2 Stunden)
23. (low, proposal) Support macOS in this repository rather than in a second one, asked on 2026-11-11. The hooks,
    the state directory, the Claude Code and Codex registry parsers, the usage windows and `list --json` (contract
    schema 1, fixtures in `test_fixtures/contract-v1/`) are standard-library Python without OS calls, and they
    change with every agent release, so a copy would need each fix twice. Linux-bound are 21 `/proc` reads in
    `agent-eta`, `agent_eta_tmux.py`, `agent_eta_handoff.py`, `agent_eta_dsh.py` and `agent_eta_remote.py`, 14
    `systemd-run` and `systemctl --user` calls for the managed scopes and the handoff freeze, the Konsole viewer with
    its D-Bus calls and the Plasma widget. Claude Code 2.1.322 holds the string `lstart=` next to its
    `/proc/<pid>/stat` reader, so its `procStart` on macOS is presumably `ps -o lstart=` output, which `proc_start()`
    has to match; read a session registry on a Mac before building on it.
    1. **Platform module.** `agent_eta_platform.py` holds the process probes (`proc_start`, `parent_of`, `comm_of`,
       the cmdline reads and the fd scan of `find_task_pid`), from `/proc` on Linux and from `ps` and `lsof` on
       macOS; a `macos-latest` job in `.github/workflows/tests.yml` runs the suite (ca. 8 hours)
    2. **Menu bar frontend.** A SwiftBar plugin under `macos/` renders `agent-eta list --json --all` and is tested
       against the contract fixtures; a native SwiftUI app follows only if the plugin falls short, and it gets a
       repository of its own only if its signing and release cycle demand one (ca. 4 hours)
    3. **Managed sessions and handoff.** tmux runs on macOS, but the owned systemd scopes and `systemctl --user
       freeze` have no launchd equivalent; candidates are a process-group `SIGSTOP`/`SIGCONT` and a Terminal.app or
       iTerm2 viewer through `osascript`. These stay Linux-only until 1 and 2 run (ca. 16 hours)
24. (next, proposal) Keep one tmux crash from killing every managed agent. On 2026-11-11 at 17:41:45
    `tmux detach-client -t /dev/pts/5`, run against a duplicate Konsole viewer of a grouped `destroy-unattached`
    view session, made the tmux 3.5a server dump core (`systemd-coredump`, process `tmux: server`), and all four
    Claude sessions in its panes died. The crash is measured; that the detach of a grouped viewer triggers it is
    inferred from the timing and needs a repro on a throwaway socket (`test_tmux.py` style). Proposals are to close a
    duplicate viewer by ending its Konsole process instead of `detach-client` and to document that (ca. 30 Minuten),
    and to give each agent its own tmux socket so a server crash takes one session, not all (ca. 4 Stunden)
