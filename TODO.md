# TODO

Open work on agent-eta. Moved from the global TODO of
[bestcodename/ai](https://github.com/bestcodename/ai) on 2026-10-17, where this list was item 6 of the cross-project
priority.

1. (next) Check the widget's *Open thread in Codex* click visually. The desktop handler accepted the current
   thread's `codex://` link on 2026-10-14, but the click itself has not been watched yet (ca. 5 Minuten)
2. (low) Match a Codex task to its process through `CODEX_THREAD_ID` in `/proc/*/environ`. Only worth it if Codex
   entries whose process ended unpolled stay listed until they expire often enough to mislead, see
   [docs/agent-eta.md](docs/agent-eta.md) "Limits" (ca. 1 Stunde 30 Minuten)
3. (low) Further surfaces for `agent-eta list --json`, proposed and not evaluated yet. They are phone notifications
   when a task turns overdue (ca. 1 Stunde) and a web app (ca. 4 Stunden)
4. (low) Show a turn that ends with a question in plain text as waiting rather than idle. Neither agent marks such a
   turn, so the candidate is a `Stop` hook that reads the last assistant message from `transcript_path` and checks
   whether it ends with a question mark. It is a heuristic and was left out of 0.62.0 on purpose (ca. 1 Stunde)
5. (next) Investigate the reported `/effort effort max` session title appearing as command-name markup.
   Reproduce it and trace the title through the native registry, transcript title, CLI and widget.
   Confirm the source before proposing a fix, then preserve the reproduction as a regression fixture
   (ca. 30 minutes). On 2026-11-13 no current registry showed this title and no raw registry fixture was found.
   On recurrence, capture `name`, `nameSource` and `sessionId` from the registry alongside the CLI row before
   the native title changes; a transcript's `/effort` command alone does not establish the displayed title
6. (low) Make *Jump to window* select the PhpStorm terminal tab a Claude Code session runs in. Today it only
   raises the project window, and PhpStorm has no action that selects a terminal tab by name, which
   `search_ide_actions "terminal"` showed on 2026-10-15. Spike the routes without a plugin in this order. First, a
   startup `.kts` script under `extensions/com.intellij/startup/` that watches a jump file and selects the tab whose
   shell process is an ancestor of the session's pid, if PhpStorm 2026.2 still runs startup scripts. Second,
   `run_inspection_kts` through the PhpStorm MCP server calling `contentManager.setSelectedContent`. Third,
   `ActivateTerminalToolWindow` through MCP, which shows the terminal but not the tab. A plugin is the last
   resort (spike ca. 1 Stunde)
12. (low) Show a privacy-reduced Agent ETA summary on the locked screen if a supported route keeps it simple. Proposed
    content: counts per state, the nearest ETA and usage percentages with reset times, with no session titles,
    labels, paths, prompts or account names. Candidate routes on Plasma 6.3.6, none tested yet, are an MPRIS player,
    which the lock screen's media controls (`lockscreen/MediaControls.qml` in the `org.kde.plasma.desktop` shell)
    already show and which would also appear in the panel's media widget; a wallpaper plugin selected for the lock
    screen that renders the summary; or a user-level override of the shell's lockscreen QML, which Plasma updates can
    break. Drop the item if every route needs patched system files or a privileged helper. Evaluate the routes first
    (ca. 30 minutes).
15. (low) A Claude Code session that a handoff started holds no ExitPlanMode approval, so moving it on to Codex forks
    a summary and plans again. Proposal: count such a session as approved from the completed handoff record that
    started it with an approved plan (ca. 1 hour).
16. (next) Investigate the modal still showing *Log in* after login. The original 2026-11-03 report says
    "shows login even after logging in"; the recorded interpretation was that the button failed while `/login`
    worked. On 2026-11-13 the user confirmed that the account-menu login for `sri@ndcom.de` opened a terminal and
    browser, and the native auth-status classification was authenticated. Browser authorization was not completed
    for this check, so the reported post-login state remains unverified. On recurrence, compare native auth status,
    account identity and the widget's cached state after login before changing the launch path (ca. 30 Minuten)
17. (low) Add a toggle for Claude Code's claude.ai push of permission prompts and questions
    (`inputNeededNotifEnabled`, off since 2026-11-04) next to the *Notify when* checkboxes. The key lives in
    `claude/settings.json` of bestcodename/ai, so a flip shows up there as a diff, like a `/config` change.
    Proposal: an `agent-eta claude-push on|off|status` subcommand behind the checkbox (ca. 1 hour 30 minutes)
18. (next, bug) The tray icon's notification badge seemed to show a wrong number, reported on 2026-11-05. No
    snapshot of that moment exists. Until 2.14.0 the badge left out every remote host's sessions, measured on
    2026-11-14; remote hosts shipped in 2.3.0 on the day of the report, so this presumably explains it.
    `summary()` in `agent_eta_model.py` sets `badge_count` to the waiting sessions as soon as one waits, otherwise
    to idle plus overdue, and leaves out dormant sessions and those in state `unknown`. So the badge never counts all sessions and switches meaning with the light. Next time it looks
    wrong, save `agent-eta list --json` and a screenshot of the badge and popup, then decide whether the count
    or the expectation is off. The same snapshot settles a Claude Code session shown under Needs you between
    turns while its background task ran (2026-11-12, not reproduced on 2.1.323 on 2026-11-13, where the registry
    reported `shell` and the session stayed in Working). Fix with a regression case in `test_model.py`
    (ca. 30 Minuten)
20. (low, proposal) Rename sessions from agent-eta, requested on 2026-11-05. Names are only read today, from
    Claude Code's `custom-title` or `ai-title` and Codex's thread name (see [docs/agent-eta.md](docs/agent-eta.md)).
    1. **`agent-eta rename <session> <name>`** plus a row action in the widget. It renames the session in its agent,
       for Claude Code presumably by typing `/rename <name>` into it rather than writing its transcript, and sets
       the Konsole tab title over D-Bus (`/Sessions/<n>`, next to `title` in `agent_eta_konsole.py`), which the
       window caption follows. A PhpStorm terminal tab has no such route, see #6 (ca. 1 Stunde 30 Minuten)
    2. **`agent-eta rename --all`**, which asks each idle session for the shortest fitting name of its current work,
       checks that the answer differs from every other session's name, and applies it through 1. A working session
       is skipped rather than interrupted, and the answer must not land in the session's own work as a turn of
       substance. Delivering the prompt needs the same input route as 1, through Konsole, tmux or dsh
       (ca. 2 Stunden)
22. (low, proposal) A desktop Codex thread drops out of the list while the desktop app is closed. Since 2.4.1 a
    `codex exec resume` of a desktop thread keeps it listed through the app's app-server, but with the app closed
    the exec's `SessionEnd` still removes it. On 2026-11-06 the thread "Deploy Docmost on Proxmox", which a Claude
    session drives with `codex exec resume`, vanished after each turn that way. Proposal: keep a thread with
    `source` `vscode` after a client's `SessionEnd` without a holder, idle until `SESSION_IDLE_TTL`, and let its row
    open `codex://threads/<id>`, which starts the app. It contradicts the rule in
    [docs/agent-eta.md](docs/agent-eta.md) that navigation never falls back to a desktop link without a verified
    Codex process, so decide that rule first (ca. 1 Stunde)
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
       macOS; a `macos-latest` job in `.github/workflows/tests.yml` runs the suite (ca. 4 hours)
    2. **Menu bar frontend.** A SwiftBar plugin under `macos/` renders `agent-eta list --json --all` and is tested
       against the contract fixtures; a native SwiftUI app follows only if the plugin falls short, and it gets a
       repository of its own only if its signing and release cycle demand one (ca. 2 hours)
    3. **Managed sessions and handoff.** tmux runs on macOS, but the owned systemd scopes and `systemctl --user
       freeze` have no launchd equivalent; candidates are a process-group `SIGSTOP`/`SIGCONT` and a Terminal.app or
       iTerm2 viewer through `osascript`. These stay Linux-only until 1 and 2 run (ca. 8 hours)
    4. **Distribution beyond this workstation.** On 2026-11-12 the skills marketplace Agensi.io offered by mail to
       list agent-eta's skills and commands for Claude Code, Cursor, Copilot and other agents, non-exclusive and free
       to list with 70 % of each sale. agent-eta ships no skill, command or plugin manifest today, since `install.sh`
       links the tool and the hooks are wired by hand in `~/.claude/settings.json` and `~/.codex/hooks.json`, and the
       public repository has no license. Proposal: a license first; then a Claude Code plugin in this repository whose
       `hooks/hooks.json` replaces the hand wiring and whose `.claude-plugin/marketplace.json` makes it installable
       with `/plugin marketplace add bestcodename/agent-eta`; Codex keeps its hand-wired hooks; a third-party listing
       such as Agensi only once 1 and 2 run, because the tool is Linux- and KDE-bound until then. Before listing,
       survey the other marketplaces for skills and plugins and record for each the share of a sale that goes to the
       author and to the platform, requested on 2026-11-13 (ca. 2 hours; the license ca. 10 minutes; the survey
       ca. 30 minutes)
24. (low, proposal) Install tmux 3.7c from trixie-backports on stefan-desktop and stefan-notebook and add it to the
    workstation setup of [bestcodename/ai](https://github.com/bestcodename/ai). On 2026-11-11 at 17:41:45
    `tmux detach-client -t /dev/pts/5`, run against a duplicate Konsole viewer, crashed the tmux 3.5a server and all
    four Claude sessions in its panes died. The backtrace of core 3000632 (Debian debuginfod) shows the SIGSEGV in
    `server_client_check_modes`, which reads `c->session->curw->window`; the crashing client is `/dev/pts/5` with
    `CLIENT_EXIT_DETACH`, and its session `view-80b5f2bfc101` was already destroyed (`curw` NULL, no references).
    In 3.5a `server_client_detach` leaves `c->session` set and `server_check_unattached` destroys the
    `destroy-unattached` session without taking clients off it. tmux 3.7c guards that read; only master also takes the
    clients off first. agent-eta never detaches a client, and its viewers now close through `kill-session`, which takes
    clients off before destroying. The private server keeps 3.5a until it restarts, which ends every agent, so switch
    while none runs and run the test suite against 3.7c first (ca. 15 Minuten). On 2026-11-13 a viewer on the desktop's
    3.5a server closed twice while its agent ran, right after another window's pane died (16:30:56, 16:32:17); on
    3.7c on 2026-11-17 an isolated server closed only the dead window's viewer. On recurrence capture
    `/proc/<server pid>/exe -V`, `list-clients`, `show-hooks -w -t <dead window>` and `journalctl --user` around it
27. (low) Install Qt 6's `qmltestrunner` on stefan-desktop and add it to the workstation setup of
    [bestcodename/ai](https://github.com/bestcodename/ai). `test_qml.Qml.test_widget_qml` is skipped here on
    2026-11-11 for lack of it, so widget changes are only tested on the notebook (ca. 10 Minuten)
29. (next, proposal) Audit user-facing defaults and make useful behavior configurable through the existing widget
    settings and CLI configuration, requested on 2026-11-11. New widget sessions already have a CLI/desktop default
    and a one-launch menu override. Review session-click behavior, terminal and IDE commands, session visibility,
    notification rules and the model, effort and permission settings in #21. Reuse native client settings and
    existing environment overrides; keep process ownership and live-writer checks mandatory. Propose the remaining
    options and their implementation effort after this audit (ca. 1 hour)
30. (next, proposal) Split widget configuration into sections, requested on 2026-11-11. Use Plasma's existing
    configuration categories in `plasmoid/contents/config/config.qml`; proposed sections are General, Sessions
    and Launching, Appearance, and Notifications. Preserve existing setting keys, defaults and saved values,
    and test that each section loads and saves its controls (ca. 30 minutes)
32. (next, proposal) Apply the global tooltip rule across Agent ETA, requested on 2026-11-11. Prioritize settings
    in `configGeneral.qml` and the sections proposed in #30, plus account and session context-menu actions in
    `FullRepresentation.qml`; then cover remaining controls and unclear icons, status indicators and abbreviations.
    Explain purpose, effect or disabled state instead of repeating labels. Keep essential information visible and
    provide accessible names. Reuse Qt/Plasma tooltip facilities and native timing, with pointer hover and keyboard
    focus; verify that disabled-action explanations remain discoverable. Add focused QML coverage for settings and
    both context menus, including focus and disabled states, and check them in Plasma (ca. 1 hour)
33. (low, proposal) Offer Claude the same configurable CLI/desktop launch default and one-launch context-menu
    override as Codex, requested on 2026-11-11. Support both the saved default directory and a chosen directory,
    keep CLI as the initial default, and store each provider's preference independently. First verify the native
    desktop launch route on the target OS and whether it preserves the selected Claude account and project folder.
    If that route is unavailable, explain why instead of silently opening a different account. Reuse the existing
    launch pipeline and configuration; add focused command and QML tests for defaults, overrides, directory choice
    and account isolation, plus tooltips under #32 (ca. 1 hour 30 minutes)
34. (low, proposal) A flaky Python test. On 2026-11-12 one full run of `python3 -m unittest discover -s .` on
    stefan-notebook ended with `FAILED (failures=1)` and four reruns passed; the failing test was not captured. On the
    next failure, record its name with `python3 -m unittest discover -s . 2>&1 | grep -E '^(FAIL|ERROR):'` and fix
    the race behind it (ca. 30 minutes)
36. (proposal) Expand the usage progress bar's time span across repeated quota resets, requested on
    2026-11-12. For `n` seven-day usage periods, show a span of `n × 7 days` instead of always showing seven
    days. Anchor the expanded timeline to the actual reset deadlines of all relevant usage limits, including
    different accounts, reset times and window lengths, rather than multiplying nominal durations alone.
    Define how the period count initializes, increments and persists, and keep every reset boundary and the
    current period's usage readable. Cover differing deadlines, the first period, multiple resets and missing
    history with tests (ca. 1 hour)
37. (next) Configurable block cutoffs per usage window, requested on 2026-11-12 and again on 2026-11-19, so an
    account deliberately parked at 99% weekly counts as blocked everywhere, not only in the modal (ca. 1 hour).
    Pre-plan from measured code on 2026-11-19:
    - **Where.** `reached` is computed once in `agent_eta_model.usage_view()` (`used >= 100`) and drives
      `usage_sections()`, `usage_groups()`, `limit_stops()` (session stopped with `resume_at`), the `reset:` signal
      and the CLI usage table. So the cutoff lives in `~/.config/agent-eta/config.json`, read through
      `AccountStore().settings()` like `codex_handoff`, not in the widget's `main.xml`, which only the widget sees.
      A widget settings field that writes it stays out of scope
    - **Config.** `{"usage_block": {"five_hour_percent": 100, "weekly_percent": 99}}`. Defaults 100 and 100 keep
      today's behaviour. A new `usage_block_settings()` in `agent-eta` beside `handoff_trigger_settings()` takes
      ints or floats in 1..100, rejects bools and other types per key, and maps the keys to window minutes
      `{300: …, 10080: …}`. `codex_handoff` stays separate, since it triggers a handoff, not a block
    - **Model.** `usage_view(now, windows, block_at=None)` sets `window["block_at"]` (the cutoff, 100 without
      one), `reached = used is not None and used >= block_at` and `window["blocked_by"]` as `"limit"` at
      `used >= 100`, `"cutoff"` below 100 but at the cutoff, else `None`. Unknown, stale and past-reset windows
      keep `used = None` and so never block. `quota_exhaustion()` keeps 100. `agent-eta`'s `usage_view()` passes
      the settings in, so `list --json`, the CLI table and remote merges after local recomputation all agree.
      Check in `agent_eta_remote.py` that a peer's windows are re-viewed locally and not taken with their
      `reached`
    - **JSON.** `block_at` and `blocked_by` are additive fields of each usage window in contract v1; extend
      `test_fixtures/contract-v1/mixed.json` with one cutoff-blocked window
    - **Widget.** `logic.mjs` `usageHeadline()` reads `blocked at 99% cutoff · resets in …` for `"cutoff"` and
      keeps `blocked · resets in …` for `"limit"`. `UsageRow.qml` gets a tooltip naming the window, its cutoff and
      that the provider limit is not reached yet. Bar colours keep following `reached`
    - **CLI.** The usage table marks a cutoff block as `cutoff 99%` next to the reset time
    - **Tests.** `test_model.py`: 98.9, 99 and 100 against a 99 cutoff, only the weekly window over its cutoff,
      both windows, `used None`, a reset in the past, and `limit_stops()` stopping a session until the weekly
      reset. `test_agent_eta.py`: settings parsing with missing, bool, string and out-of-range values.
      `test_plasmoid.mjs`: both headline variants. Run `python3 -m unittest` and `node --test test_plasmoid.mjs`
    - **Docs.** `docs/agent-eta.md` config section next to `codex_handoff`, README line, CHANGELOG, minor bump
38. (low, proposal) Rename the project to Agent Desk and the repository slug to `agent-desk`, requested on
    2026-11-13. The name should cover sessions, accounts, usage limits and handoffs. Verify the GitHub repository
    and any GitLab mirror mapping before renaming either service. Introduce `agent-desk` as the primary command
    while retaining `agent-eta` compatibility. Update package and widget display names, repository URLs,
    installation, hooks and external callers without losing saved settings or runtime ownership (ca. 2 hours)
39. (proposal) Collapsible subtask bars in active session rows, requested on 2026-11-13. `SessionRow.qml` shows a
    `TaskRow` for every entry of `session.taskItems`. A widget setting chooses what a collapsed row keeps: all subtask
    bars, the longest and the earliest ETA, only the longest, or only the earliest; a click expands the row to all
    bars. Default all, placed in the Appearance section of #30; test each mode, equal ETAs and a single entry
    (ca. 30 minutes)
40. (proposal) Open sessions on the device the user is using, requested on 2026-11-13. A click opens or raises a
    viewer on the machine whose widget was clicked, and a remote session opens through `ssh -t HOST agent-eta attach`
    (docs/agent-eta.md, Remote hosts).
    1. **Default device setting.** This machine, a host from `remote_hosts` or automatic, for new launches and for
       attach; stored in `config.json` and the widget settings, default this machine (ca. 30 minutes)
    2. **Automatic detection.** The current device is the one whose graphical session is unlocked and not idle
       (`loginctl show-session <id> -p Type -p LockedHint -p IdleHint`), read locally and over the existing BatchMode
       SSH; an ambiguous result falls back to the default, and `DISPLAY` is never forced on another host
       (ca. 1 hour)
41. (proposal) Close the gaps between the Codex and Claude Code integrations, requested on 2026-11-13. Known
    gaps are filed as #2 (Codex process match), #15 (handoff without ExitPlanMode approval), #22 (desktop Codex thread
    drops out) and #33 (Claude lacks the CLI/desktop launch default), and docs/agent-eta.md names more: Claude Code
    background agents and Monitor tasks are not recorded, a Codex thread shows only after its first hook, the Claude
    desktop app opens no specific session, and Codex has no plan-mode flag or command description. Proposal: a parity
    table per feature and provider in docs/agent-eta.md, each gap closed in agent-eta or marked as an upstream limit
    with its evidence, and closable gaps filed or joined to the items above (ca. 1 hour for the table)
42. (low, proposal) Compact `docs/agent-eta.md`, which passed 1000 lines with 2.14.0 (1005 on 2026-11-14) and grows
    further with the parity table of #41. Delete resolved notes, drop text later measurements superseded and merge
    sections that repeat each other, such as the remote-host facts spread over the contract, CLI and widget parts;
    keep it one file (ca. 25 Minuten)
44. (low, proposal) Show the source host of shared Claude usage in the account tooltip. Version 2.14.1
    selects newer peer readings for the same authenticated identity; source attribution is not displayed yet.
    Preserve the native reading timestamp and local account actions (ca. 30 Minuten)
47. (proposal) An `agent-eta add` reminder stays with a session that moved or was continued under a new ID, as a
    grey `unknown` task-only row under the old name, while the continuation sinks to Dormant without it. On
    2026-11-17 the desktop listed `unknown … claude migrate-sri-servers-proxmox` at 18:55 after an account move. At
    22:15 the notebook listed reminder `add-ff9d1cc5` (vm104 balloon reboot, due 09:45) as `stefanr-98`, bound to
    session `63b1cb88`, whose pid 4095252 ended at 19:38:31. A `claude bg-spare` process (pid 76691, ndcnet) started
    the same second and continued it as `1703c3ed`, which listed as dormant "SRI servers Proxmox migration". The
    continuation's transcript holds all 868 entry `uuid`s of the old one but no lineage key, and rewrites
    `sessionId`. Proposal: for a reminder whose session has no live process, look for a live Claude session whose
    transcript contains the old transcript's last `uuid` and re-own the reminder to it. `agent-eta handoff` and
    `account-tabs` re-own directly, and a host move carries reminders in the tabs file (ca. 1 Stunde 15 Minuten)
48. (low, proposal) Split `agent-eta`, which is past the 2000-line refactor mark, by moving the Claude and Codex
    collectors into `agent_eta_collect.py` (ca. 1 Stunde)
49. (proposal) Show a plan completion meter with the percentage and completed step count in each applicable
    session row of the Agent ETA modal. Reuse the progress data behind the Claude Code CLI status line so both
    displays agree. Check whether the Codex CLI can show the same meter for Codex sessions, and add it if a
    supported integration is available. See item 28 in the [AI backlog](https://github.com/bestcodename/ai/blob/main/TODO.md)
    for the related plan-progress work.
50. (proposal) Declutter the Agent ETA modal, requested on 2026-11-19 and widened from the usage section. By
    default each session and account row shows only what a decision needs, such as name, state, ETA or reset
    and quota bar. Advanced and additional information and controls, such as time labels, pace, project path,
    handoff and secondary actions, appear on pointer hover or keyboard focus of that row, and permanently once
    the popup is wide or tall enough. Take the breakpoints from the popup's own width and height (`FullRepresentation.qml`)
    instead of a fixed screen size, keep one place per piece of information, and leave nothing reachable only
    by hover, so tooltips (#32) and context menus still expose it. In the usage section, also remove redundant
    labels and repeated values across account rows. Inventory every row element first and sort it into
    essential, hover and wide; cover both layouts and hover or focus states with QML tests (ca. 1 hour 30 minutes)
51. (medium) Support PhpStorm's JetBrains AI agents like Claude Code and Codex, requested on 2026-11-19, with the
    same list, ETA and *Jump to window* behaviour (ca. 2 Stunden). Pre-plan from PhpStorm 2026.3 on 2026-11-19:
    - **Route.** The AI chat runs agents over ACP. A Claude chat is `npm exec @agentclientprotocol/claude-agent-acp`
      → `node claude-agent-acp` → the SDK's own `claude` binary under
      `~/.cache/JetBrains/PhpStorm2026.3/acp-agents/claude-acp/<version>/`, a child of `phpstorm`. It writes a normal
      transcript to `~/.claude/projects/<dir>/<session>.jsonl` and runs the Claude hooks (`session-start/` record
      seen), so the Claude integration already covers turns, waiting questions and ETAs. No new provider is needed
      for Claude
    - **IDE side.** `~/.config/JetBrains/<IDE>/aia-task-history/<chat uuid>.*` per chat: `.agentsession` holds
      `<agent>:<session id>` (`acp.registry.claude-acp:<claude session>` or `codex:<thread>`), `.events` is
      `AUI_EVENTS_V1` plus one base64 JSON event per line (`ChatSessionUserPromptEvent`,
      `ChatSessionMessageBlockEvent`), `.unread` holds `true` while the chat has unread output, `.usage` holds
      `{"used", "size", "cost"}` of the context window. Treat the format as internal and unversioned
    - **Gaps measured.** `list --json` already lists both live ACP chats with their transcript titles and the
      right `stopped` state of a limit-blocked account. *Jump to window* misses, because `project_root()` cuts at
      the first level below `~/PhpstormProjects` (`private`, `ndcom`) while the PhpStorm windows are captioned
      `ai` and `components`; this hits nested CLI sessions too. `handoff_gate()` gives the chats CLI advice, and
      nothing marks a row as a PhpStorm chat. An idle chat already sits under *Needs you*, so `.unread` adds nothing
    - **Changes.** Project root from the deepest matching key in PhpStorm's `options/recentProjects.xml`, a
      `client: "phpstorm"` field for a `claude` binary under `acp-agents/` with a `phpstorm` ancestor (`host`
      already means the remote machine), an own handoff reason and a widget label. Executable plan in
      `~/.claude/plans/agent-eta-phpstorm-chats-and-usage-cutoff.md`
    - **Open.** The four `codex:` chats from 2026-11-05 have no rollout under `~/.codex/sessions`, so check where the
      IDE's Codex keeps them before covering Codex. Junie (`~/.junie/instances/`, `history.jsonl`) and the other
      ACP registry agents stay out until someone uses them
