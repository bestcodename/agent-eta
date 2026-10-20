# Agent ETA overview

`agent-eta` lists every running Claude Code, Codex, dsh and local-model session on this machine with its
state, its ETA and its background tasks. Sessions waiting for an answer come first. Hooks and Claude Code's own session
registry fill the list, so an agent only has to write down the ETA it states anyway.

Written 2026-10-03 in [bestcodename/ai](https://github.com/bestcodename/ai), and a repository of its own since
2026-10-17 (1.0.0). Until then every ETA existed only as chat text in the session that stated it, and finding the
session that waits for an answer meant opening each one.

## Why it exists

Claude Code, Codex and the local goose runs of [`scripts/llm-handoff/run-local.sh`](https://github.com/bestcodename/ai/blob/main/scripts/llm-handoff/run-local.sh) in bestcodename/ai work side by side. The rule in
`~/.claude/CLAUDE.md` and its copy in `~/.codex/AGENTS.md` makes each of them state an ETA for every long or background
command. Nothing outside the chat could read that ETA, so finding out which session waits on what, and which of them is
overdue, meant opening every session in turn.

## How it works

Every task is one JSON file in `/tmp/agent-eta-<uid>`, or in `AGENT_ETA_DIR` when that is set. The directory has mode
0700, and the tool refuses one that another user owns. `/tmp` is the only directory that a command inside the Codex
sandbox and a process on the host can both write. Losing the files at reboot costs nothing, because every session they
describe ends with it.

`agent-eta` (or `agent-eta list`) reads every file, deletes the ones whose task has ended and prints each session with
its tasks underneath:

```
STATE    FOR   REMAINING  DUE    AGENT   SESSION
waiting  3m    -          -      claude  PSL and Innschleife speaker realism (input needed)
waiting  <1m   -          -      codex   Fix checkout (plan approval)
idle     3h00  0          -      claude  sdwa5-db
---
working  7m    -12m       21:40  claude  ETA overview · Session view for agent-eta
               -17m       21:35          └ Run the test suite
working  2m    9m         22:01  codex   Fix payment mail
               9m         22:01          └ composer install
working  40m   1h13       23:05  local   ai
               1h13       23:05          └ qwen3-coder:30b-a3b-q4_K_M on ai
working  1m    ?          ?      claude  stereo-tops-spacing-fix
---
stopped  4m    6m         21:58  codex   Add display settings (usage limit)
---
1 dormant session, idle for more than 2h. agent-eta --all lists it.

USAGE   USED  ELAPSED  PACE        REMAINING  DUE           READ
claude  88%   -        ahead +65%  2h46       07:10         <1m
└ 5h    43%   44%      ok -1%      2h46       07:10
└ 7d    88%   23%      ahead +65%  5d8h       09.10. 13:00
codex   92%   -        ahead +49%  3h09       07:32         3m
└ 5h    54%   37%      ahead +17%  3h09       07:32
└ 7d    92%   43%      ahead +49%  3d22h      08.10. 03:22
---
(no usage limit reached)
```

The FOR column says how long a session has been in its state. The order follows how soon a session needs you.
**waiting** means it needs you for a permission prompt, a question dialog or another dialog, and those sessions come
first. **idle** sessions follow, most recently active first, because each of them waits for your next prompt.
**working** sessions come next, overdue ones first, then by remaining time and then those without an ETA. An idle
session that still has a verified background task running counts as working. A manual reminder alone does not
establish activity. Without a live owner or holder it appears as **unknown** in the non-working group, keeping its
label, deadline and Mark done action. It contributes no working count, tray activity or progress indicator. A **stopped** Codex thread ended its turn with an
error, and the reason stands in brackets. When the reason is a usage limit, REMAINING and DUE count down to the reset
of the exhausted window, and the thread comes last, because nothing can be done before the reset. Once the reset has
passed, the thread shows as idle, counted from the reset. A thread stopped by another error has nothing to count down
to and sorts with the idle ones. A session whose account has a reached limit in the usage table below is stopped the
same way, with `(usage limit)` and the reset of that limit, unless it is working or dormant. A working one stays,
since it may run on extra usage, and a dormant one stays among the dormant. Dormant sessions follow after all of these, see below. A `---` line separates the
sessions that need you from the working ones, those from the sessions stopped by a usage limit, and all of them from
the dormant ones. A blank line separates the session table from the usage table. Every section is always shown, and an empty one says so in a line such as `(no working sessions)`.

A session's ETA is the turn ETA its agent set with `agent-eta turn`, shown with the turn's label after a `·`. Without
one, it is the latest due time among its tasks. Without either, REMAINING reads `0` for an idle session, `?` for a
working one and `-` for one that waits for you. DUE reads `?` wherever REMAINING does, for tasks too. Due times are Europe/Berlin.
REMAINING, FOR and every countdown of the widget count whole clock minutes, so they equal the difference of the clock
times beside them: a reset at 06:55:06 reads `2h 33m` from 04:22:00 to 04:22:59. Names
are resolved at read time, so a renamed session shows its current name. A Claude Code session shows the name in
`~/.claude/sessions/<pid>.json`, unless that name is only derived from the directory (`nameSource: "derived"`, as in
`ai-0b`). Then the latest `custom-title` or `ai-title` in its transcript wins, which is the title Claude Code itself
displays. A Codex thread shows its name from `~/.codex/session_index.jsonl` or the `threads` table of
`~/.codex/state_<n>.sqlite`. A thread Codex has not named yet shows the first line of its first prompt, as the app does. A task whose session is unknown, such as a local run, stands as a session of its own.

**Dormant sessions.** An idle session without a running task counts as dormant once it has been idle for more than two
hours. The list leaves it out and ends with a line that counts the dormant sessions. `agent-eta --all` lists them in a
last section below the active ones, and `--json` marks every session with `dormant`. Time is the only signal,
because neither agent says whether anyone still looks at a session. A Claude Code session parked in a PhpStorm terminal
tab and a background job of the Claude Code daemon both stay alive for days, and the daemon also runs sessions that are
in active use, so neither the process nor its kind tells a forgotten session from a live one. The Codex app runs every
thread in one app-server that lives as long as the app, so a finished thread stays listed as well. Until 0.92.0 the
threshold was twelve hours, which on 2026-10-15 kept six finished Codex threads of the night under "Needs you".

The one exception is a Claude session that never ran a turn. PhpStorm starts an agent-SDK process per open project
ahead of use, and its registry record carries no `status` while no transcript exists for its session id. Such a
session is listed as idle and counts as dormant from the start. A record without a status that does have a transcript
stays `unknown`, because whether those processes ever report a running turn is unmeasured. Measured on
claude-agent-sdk 2.1.220 on 2026-10-15.

`agent-eta --tasks` prints the flat task list of version 0.61.0, overdue first. `agent-eta --json` prints both, as
`sessions` with the ids of their tasks and `tasks` with every field, for the tray widget and for the phone notification
and the web app that TODO.md proposes. Since 0.67.0 it carries what the widget would otherwise have to work out itself.

- A task has `progress`, the share of its ETA that has passed, from 0 to 1, or `null` without an ETA.
- A session has `eta_started`, the start of the span its ETA counts from, and `progress` over that span. The start is
  the turn's start for a turn ETA, the start of the task due last for a task ETA, and the time the limit was hit for a
  usage stop.
- A session has `section`, which is 0 for the ones that need you, 1 for working, 2 for stopped by a usage limit and
  3 for dormant, in the order the text list prints them.
- A session has `pids`, its own pid or its first task's holder followed by their ancestors, ending before pid 1 and
  the user's `systemd`. Codex threads have none.
- A session has `project_root` and `project_name`. The root is the first directory below `~/PhpstormProjects`, else the
  nearest repository root, else the working directory. The name is PhpStorm's `.idea/.name` when the project was
  renamed there, else the root's directory name.
- The top-level `accounts` array inventories monitored accounts even without readings. Each entry carries `id`,
  `provider`, `agent`, `name`, `can_remove`, `default_directory`, `auth_state`, `usage_status`, `seen_at`, `checked_at`
  and a safe `error` message. Authentication is `authenticated`, `logged_out`, `mismatch` or `unknown`; usage is
  `current`, `stale` or `unavailable`. The existing `usage` array remains, with additive account and freshness metadata.

### Where the session state comes from

**Claude Code** writes the state of every session to `~/.claude/sessions/<pid>.json` itself, as `status` with
`statusUpdatedAt`, and `waitingFor` while it waits. agent-eta maps `busy` and `shell` to working, `waiting` to waiting
and `idle` to idle, and shows `waitingFor` in brackets. No hook is involved, so every running session is listed,
including the ones started before agent-eta existed.

With at least two accounts in the registry of [claude-account](https://github.com/bestcodename/ai/blob/main/docs/claude-account.md), agent-eta reads the `sessions/` and
`projects/` of every registered directory, and the AGENT column reads `claude/<name>`. With one account or none it reads
`CLAUDE_CONFIG_DIR`, or `~/.claude`, and the column reads `claude`. The hook always writes for the directory of its own
session.

**Codex** reports nothing outside its app. Its hooks therefore keep one file per thread in `sessions/` under the state
directory. `UserPromptSubmit`, `PreToolUse` and `PostToolUse` set working, `PermissionRequest` sets waiting, and `Stop`
and `Interrupt` set idle. Nothing fires when the request is decided, so the reader ends the wait itself. Code mode runs
every command inside a script that the rollout transcript records as a tool call, and that call's output only follows
once each approval inside it was decided, by the user or by the auto-review agent. Once the call that was open at the
request has its output, the thread counts as working again from that moment. A question the model puts through the `request_user_input` tool reaches no hook, so the reader
also looks at the end of the thread's rollout transcript in `~/.codex/sessions/`. A thread that is not idle and has a
`request_user_input` call there without its matching output waits for an answer, shown as `(question)` and counted from
the moment it asked. Native `request_user_input_async` questions also wait after Stop. Their immediate
`accepted` result only acknowledges delivery; the matching `send_user_message_question_reply` envelope clears each
answered question by call id and question index. A partial answer leaves the other questions waiting.
In plan mode a turn ends with an `item_completed` event of type `Plan` before its `task_complete`,
and the app then asks whether to implement the plan. An idle thread whose last finished turn carries such a plan
therefore waits as well, shown as `(plan approval)` and counted from the end of that turn. A turn that fails fires no
`Stop` either. When the last `task_complete` in the transcript carries an `error`, the thread is stopped, counted from
that event. Its reason is the error's `codex_error_info`, and `usage_limit_exceeded` reads `usage limit`. The reset
time comes from the last `token_count` event whose `rate_limits` carry windows, as the latest `resets_at` among the
windows at 100 percent. Codex also stops a turn before any reading shows a full window, and on 2026-10-14 two threads
stopped with the 5-hour window at 99 and 97 percent. Without a full window the reset of the fullest one counts instead,
so such a thread turns idle at that reset rather than staying stopped without an end. From the reset on, the idle
thread counts from the end of its failed turn, which is the age the Codex app shows for it. On 2026-10-15 a thread
stopped at 11:27:35 with a reset at 13:54:30 showed as idle for 37 minutes at 14:31, while the app showed 3 hours,
matching `updated_at` in its `threads` row. The next `task_started` or `user_message` ends the stop. A command started before the stop
gets no `PostToolUse`, because Codex polls it no more, and its app-server lives on. The reader therefore deletes the
entries of an idle or stopped thread that predate the end of its turn, so rejected commands missing PostToolUse
cannot keep a completed chat in the working section. Manual reminders and live PID or lock jobs are retained. On
2026-10-04 at 02:27 the one command of the failed turn had no process left. A thread appears with its first hook call, and it disappears with its Codex app-server, after
`SessionEnd`, or after twelve hours without any hook call. One that claims to work or wait but has been silent for six
hours most likely missed its `Stop`, and it counts as idle. A thread archived in the app, marked by `archived` in the
`threads` table of `~/.codex/state_<n>.sqlite`, is left out while it stays archived, and it comes back once unarchived.
Codex consolidates its memories in a sub-agent thread that works in `~/.codex/memories`. That thread has no row in
the `threads` table and no rollout, and it fires `UserPromptSubmit` and tool hooks but never `Stop`. It is no session
anyone works in, so it is never listed, and its hook record is removed whenever the list is read. A thread that works
in that directory but has a row in the `threads` table is an ordinary thread and stays listed.

**Turn ETAs** live in `turns/`. `agent-eta turn --eta 20m --label "…"` records one for the calling session, and `agent-eta
turn --done` clears it. It ends on its own once the session goes idle or stops, and for Codex `UserPromptSubmit`, `Stop` and
`Interrupt` delete it as well.

**dsh** (`@deepseek-ai/dsh`, here as `dsh web` through `ollama launch dsh`) needs no hook and no config change, because
it logs every session itself. Each session is a folder
`${DSH_HOME:-~/.dsh}/sessions/--<cwd>--/session-<uuid>/` with the log `session.v3.jsonl.zstd`, a series of zstd frames
that `zstdcat` decodes into one JSON record per line. A process that has the session loaded holds `session.lock` in that
folder open, so agent-eta lists exactly the sessions whose lock a running dsh holds, found through `/proc/<pid>/fd`, and
the session disappears with its process. Archiving a session in the web UI does not unload it. dsh only adds its id
to `global.archivedSessionIds` in `${DSH_HOME:-~/.dsh}/storages/workspace.json`, so agent-eta leaves out every id
listed there, together with its bash calls, and an unarchived session comes back. The state comes from the records in
this order.

1. An `approval/asked` without its `approval/decided` waits, shown as `(permission)`.
2. An open `ask_user_question` call waits as `(question)`, an open `exit_plan_mode` call as `(plan approval)`.
3. A `turn/start` without its `turn/end` works. An `llm/retry` since the last tool call or model answer adds
   `(retry 2/5 (TIMEOUT))`, so a slow row says why.
4. A last `turn/end` of kind `error`, `max-tokens` or `blocked` waits as `(turn failed (TIMEOUT))`, `(hit max tokens)` or
   `(blocked)`, and the session counts as needing you. After two hours such a session goes dormant like an idle one.
5. Anything else, a completed, aborted or interrupted turn, is idle.

The name is the title dsh gave the session, else the `/goal` objective, else the first line of the first prompt. The
model comes from the last `request/context`. Every bash call that has been open for at least ten seconds is listed as a
task under its session, labelled with the call's `description` and without an ETA. A log is decoded again only when its
size or mtime changed, and the summary lives in `cache/dsh-cache.json` in the state directory meanwhile. Without
`zstdcat` dsh is left out of the list and nothing else changes.

### When a task counts as ended

No agent reports the end of a background task to anything outside itself, so every entry names a holder, and the reader
judges it on its own. Entries without a holder retain their normal expiry and explicit `done` behavior; their
continued presence alone does not prove that a session is working.

| Holder | The task runs while | Written by |
|---|---|---|
| `pid` | a process with this pid and this starttime exists, which also rules out a reused pid | the Claude Code hook, `run-local.sh`, `add --pid` |
| `lock` | the writer still holds an `flock` on the entry file | `agent-eta run` |
| `pair` | the matching Codex `PostToolUse` has not deleted it, the Codex app-server it was recorded under still runs, its turn has not ended, and it has not expired | the Codex hook |
| none | it has not expired | `agent-eta add` |

An entry expires once it is overdue by its own length, but never earlier than one hour after its due time. An entry
without an ETA expires two hours after it started.

The `lock` holder exists because of the Codex sandbox. Codex starts every command with `bwrap --unshare-pid`, so inside
the sandbox a command sees itself as pid 1, and a pid recorded there means nothing on the host. An `flock` belongs to the
file and not to a pid, and `/tmp` is the same file system on both sides. `agent-eta run` takes the lock on a temporary
file before it renames that file into place, so the reader never sees the entry unlocked.

### Where the ETA comes from

The hooks read the ETA from text the agent writes anyway. The first `ETA`, `ca.` or `ungefähr` that is followed by a
duration counts, in English or German, so `ETA 25m`, `ca. 10 minutes`, `ca. 1 Stunde 30 Minuten` and `ungefähr 45
Minuten` all work. A task without one is listed with `?` rather than left out.

### Usage windows

The usage table at the end of the list compares, for every usage window of Claude Code and Codex, how much of it is
used with how much of it has passed. Each agent has a row of its own, and its windows follow as `└` rows. ELAPSED is
one minus the time left until the reset divided by the window length, so a 5-hour window that resets in three hours
stands at 40 percent. PACE is USED minus ELAPSED in percentage points. It reads `ahead` while that is above zero, which
means the window runs out before it resets if the work goes on at the same rate, and `ok` otherwise. REMAINING and DUE
say when the window resets, and READ says how old the agent's reading is. A NOTE column appears as soon as an account is
not in order, with the same wording as the tray, such as `Different account logged in` or `Stale reading`. An account
with a note but no reading gets a row of its own in a third section.

An agent's row holds the worst of its windows per column. USED is the highest used share and PACE the worst pace, each
from whichever window holds it, so ELAPSED belongs to no single window and reads `-`. The table has two sections. The
first holds the agents with room left in every window, and the REMAINING and DUE of an agent's row are those of its
window that resets first. The second holds the agents with a reached limit, and there they are those of the reached
window that resets last, because that reset ends the block. The first section orders the agents by the reset of
their 7-day window and then by that of their 5-hour window, the soonest first, and an agent without a known window of
that length sorts after those with one. The second section puts the agent whose block ends soonest first. Each agent's windows follow with the soonest reset first. An empty section says so. `--json`
carries the windows as `usage`, with `used`, `elapsed` and `pace` in percent, `remaining` in seconds and `reached`.

Claude Code's windows come from `usage-state.json` in each account's config directory, where
[`scripts/claude-usage/statusline.py`](https://github.com/bestcodename/ai/blob/main/scripts/claude-usage/statusline.py) in bestcodename/ai records `five_hour` and `seven_day` each time it renders the status line. Codex's
windows come from the latest `token_count` event whose `rate_limits` carry windows, searched in the five most recently
written rollout transcripts that hold such a reading, at most 50 back. Codex writes batches of short threads whose
readings are all null, and on 2026-10-05 eight of them from the day before hid the last real reading, which showed the
weekly window at 100 percent. Each window comes with its length in `window_minutes`. A window whose reset lies in the past
has started over since its reading, so its row shows `?` until a newer reading arrives, and it counts as having room.

The CLI now saves readings in an account-scoped persistent cache. A missing local reading cannot remove an account
or erase a cached reading. A reproduction on 2026-10-14 showed that 50 newer rollouts without readings hid an older
valid Codex reading from the bounded reader. The cache regression covers that mechanism; its involvement in the
reported multi-day disappearance remains unconfirmed.

The first due listing schedules one background refresh. Refresh attempts are limited to one per five minutes,
and an inherited file lock keeps every widget instance on the same worker. Native probes share a 30-second overall
budget. Codex uses `account/read` and `account/rateLimits/read` through its private stdio app-server without starting
or resuming a thread. Claude authentication uses `claude-account run NAME auth status --json`; Claude usage still
comes from the status-line recorder. The native clients handle credentials; the helpers never open credential files.
API-key authentication remains authenticated even when subscription usage is unavailable.

Readings older than five minutes, readings past a recorded reset and readings retained after refresh failure are
marked stale. A past reset makes the effective usage unknown, never zero. Authentication failures become unknown,
not logged out. Confirmed logout clears usage but keeps the account row. An identity change clears prior readings.
Claude's logged-in identity differing from its registration is reported as a mismatch, and the account keeps its
readings. The status line records them per config directory, so they belong to the login stored there, while the
email that `auth status` compares is a cached profile copy in the global state file. On 2026-10-15 that copy in
`~/.claude.json` named the other registered account while the stored login was still the registered one. A window-ending notification
with no fresh reading says that a reading is pending rather than promising unused quota.

### Account actions and preferences

```sh
agent-eta account list --json
agent-eta account refresh --json
agent-eta account login claude:work
agent-eta account remove claude:work
agent-eta account launch claude:work
agent-eta account launch codex --directory '/home/me/a project'
agent-eta account default-directory codex '/home/me/PhpstormProjects'
agent-eta account remove codex
agent-eta account enable codex
```

Use the IDs returned by `account list`. Registered Claude accounts use `claude:NAME`; an unregistered primary uses
`claude:default` and cannot be removed through this tool. A single registered account keeps the legacy `claude` usage
label. `account refresh` performs a due refresh, or returns the current inventory while another worker holds the lock
or the five-minute interval has not passed. Its JSON also carries safe per-account failures.

Claude login opens `claude-account run NAME auth login` in Konsole. Removal delegates to `claude-account remove NAME`
and preserves the config directory. Codex login opens the native `codex login` command in Konsole. Removing Codex
disables local monitoring without logging out; `account enable codex` or the widget's **Restore Codex monitoring**
setting restores it. No action logs another account out.

Each account has a saved default session directory, falling back to the home directory. `default-directory ID`
prints it; supplying a path saves it. `launch --directory` chooses one folder without replacing that preference.
Claude launches through its account wrapper in a separate Konsole window. Codex opens the new-thread composer through
`codex://threads/new?path=...`, with the path encoded. Native commands receive argument arrays, not interpolated shell
text. A missing executable, invalid directory or immediately failing launcher produces a safe action error.

Preferences live at `${XDG_CONFIG_HOME:-~/.config}/agent-eta/config.json` and cached readings at
`${XDG_CACHE_HOME:-~/.cache}/agent-eta/accounts.json`. New files have mode 0600. Tests can override `AGENT_ETA_CONFIG`
and `AGENT_ETA_CACHE_DIR`; `AGENT_ETA_DIR` also isolates account state under that directory. `AGENT_ETA_NO_REFRESH=1`
disables automatic workers. `AGENT_ETA_CODEX_BIN`, `CLAUDE_BIN`, `AGENT_ETA_CLAUDE_ACCOUNT_BIN`,
`AGENT_ETA_TERMINAL_BIN`, `AGENT_ETA_OPENER_BIN` and `AGENT_ETA_QDBUS_BIN` override the native binaries. Codex resolution checks PATH and
then the desktop bundle at `/usr/lib/chatgpt/resources/codex`.

### The list contract

`agent_eta_model.py` decides everything the CLI and the widget share. The collectors in `agent-eta` read registries,
hooks, transcripts and processes, and `build_snapshot()` turns their output into one snapshot with one timestamp. It
does no I/O, reads no clock and changes none of its inputs. `agent-eta list` renders that snapshot as the text table,
and `list --json` publishes it as contract schema 1, which the widget validates and only formats.

| Key | Content |
|---|---|
| `schema_version` | `1`. A listing without it makes the widget report "agent-eta CLI too old, update it" |
| `labels` | the state and section labels and `dormant_after` in seconds |
| `sessions` | every session with `key`, `reported_state` as its agent reported it, `activity_state` as it effectively is, `activity_label`, `light` (`attention`, `caution`, `active`, `off`), `dormant`, `section`, its ETA fields, its task ids and `handoff` |
| `tasks`, `usage`, `accounts` | the tasks, usage windows and accounts, each with a `key` |
| `summary` | the counts per state, `light`, `badge_count`, `status` and `progress_session_key` for the tray icon |
| `sections`, `usage_groups` | the display order, as lists of keys |
| `notification_signals` | one signal per waiting, overdue or reset condition, with `key`, `kind`, `entity_key`, `active`, `edge`, `notify_on_new`, `dedupe_key` and `message_params` |

Keys are `claude:<pid>`, `codex:<thread>`, `task:<id>`, `window:<agent>:<minutes>`, `account:<id>` and
`usage:<agent>`. An idle session that owns verified background work is working, while a reminder without a holder
proves nothing. A Codex turn that runs on while an async question waits stays red and reads "working, question open".
The widget sends a notification only between two valid listings, for a rising signal with `notify_on_new` or for a
falling reset, and never on the first poll. `test_model.py` writes the fixtures in `test_fixtures/contract-v1/` when
`AGENT_ETA_WRITE_FIXTURES=1` is set and fails when they are stale, and the JavaScript and QML tests read them.

### Handoff between Claude Code and Codex

```sh
agent-eta handoff claude:<session> --to codex [--plan PATH] [--wait 1800] [--dry-run]
agent-eta handoff codex:<thread> --to claude [--account NAME]
agent-eta handoff claude:<session> --to claude --account NAME   # delegates to claude-account handoff --only
```

A move between providers starts a fresh session that continues the source's plan. Claude Code to Claude Code stays a
resume through `claude-account handoff --only`, which keeps the conversation. Each source is handled on its own, and
the command prints one JSON record per source.

1. **The plan** comes from `--plan`. Otherwise a Claude Code session's plan comes from its plan-progress record in
   `~/.local/state/claude-plan-progress/<session>.json`, which counts as approved only while the transcript holds the
   matching ExitPlanMode approval, and then from the transcript's `plan_mode` attachment while it still plans. A Codex
   thread's plan is the latest `Plan` item of its rollout, approved once a later turn starts outside plan mode.
   Without a plan, a forked one-shot of the source writes one, read-only and without saving a session. If that fails
   too, the handoff stops with "preparation needed".
2. **The snapshot** goes to `~/.local/state/agent-eta/handoff/<id>/` (`AGENT_ETA_HANDOFF_DIR`, mode 0700) as `plan.md`
   and `status.json`. `plan.md` is the plan with a "Handover" section of phase, progress, next step, directory,
   branch, HEAD, dirty paths and a pointer to the plan's verification. Once the source is paused at its boundary, the
   snapshot is written again with the plan's current progress, the git state and the command, since the source may
   have worked on while the handoff waited. A plan from `--plan` or from a fork keeps its text.
3. **The boundary**: the source must be idle or stopped, with no open question and no verified background writer.
   The command waits up to `--wait` seconds and then reports `waiting` without changing anything.
4. **The move**: the source process moves into the transient user scope `agent-eta-handoff-<id>.scope`, is frozen
   there with the cgroup freezer and is checked again. The destination opens in a new Konsole window
   (`AGENT_ETA_HANDOFF_TERMINAL`, default `konsole --tabs-from-file`) with the agent markers of the source removed, and
   once it registered within 300 seconds (`AGENT_ETA_HANDOFF_REGISTER_TIMEOUT`) the source gets SIGHUP and is thawed,
   so it ends without running in between. Claude Code registers through the session id the handoff gave it, and Codex
   through a rollout whose first user message carries the handoff id, searched in the first 4 MiB. A failure, a
   timeout, a cancel by Ctrl-C, SIGTERM or SIGHUP, and any other error thaw the source and keep `status.json`, whose
   `resume_source` holds `systemctl --user thaw` for a source that stayed frozen. Every pause and signal checks the
   process start time first, so a reused pid is never hit. The freezer replaces SIGSTOP because bash takes the
   terminal back from a stopped foreground job, which then stops again at its next read, measured on 2026-10-20.
   Polls run every 5 seconds (`AGENT_ETA_HANDOFF_POLL`).

Claude Code starts as `claude-account run ACCOUNT --session-id UUID PROMPT`, with `--permission-mode plan` while the
plan is unapproved. Codex starts as `codex -C DIR PROMPT`, read-only with `-a on-request` while the plan is unapproved,
because Codex has no flag that starts it in plan mode. `codex` is `AGENT_ETA_CODEX_BIN`, else the one on PATH, else the
desktop package's `/usr/lib/chatgpt/resources/codex`, and without one the handoff is refused before the pause. Neither gets model or effort flags, so each uses its own
configuration. Without `--account`, the Claude Code account is the first eligible one from `claude-account targets
--json`, and otherwise the only registered one. A lock per source and the records make a repeated request report the
earlier move.

Every chat of the Codex desktop app runs in one shared app-server, so pausing one would pause all of them. Such a
thread is refused with "desktop chats cannot be gated", and only a Codex thread with a process of its own can move.
The listing's `handoff` field says per session whether it can move, where to, why not and how its latest move went.

Two triggers start a handoff by themselves, each detached and once per tripped window and session.

- **Claude Code**: bestcodename/ai's usage guard hands each session that prompts to Codex when no other Claude account
  is free and its `codex_handoff` setting allows it.
- **Codex**: the Stop hook hands the thread to Claude Code at 90 % of its 5-hour window or 95 % of its weekly window.
  A reset never moves a session back. The settings live in `~/.config/agent-eta/config.json`:

  ```json
  {"codex_handoff": {"enabled": true, "five_hour_percent": 90, "weekly_percent": 95}}
  ```

## Install

```sh
./install.sh
```

The script links `~/.local/bin/agent-eta` to this repository, so a pull updates the tool the hooks call. A second run
changes nothing. `~/.local/bin` is on neither the Claude Code nor the Codex `PATH`, so the hooks and the agent rules use
the absolute path.

Where `kpackagetool6` exists, the script also copies the tray widget to
`~/.local/share/plasma/plasmoids/com.github.bestcodename.agenteta` and adds it to every system tray, as the section
[Tray widget](#tray-widget) describes. The widget is a copy, so a pull that changes it needs another run and a restart
of plasmashell, which the script names without running it.

```sh
systemctl --user restart plasma-plasmashell.service
```

The hooks are wired by hand, because Codex skips a new hook until it is trusted in its own settings.

- `~/.claude/settings.json` gets a `PostToolUse` group with the matcher `Bash` and the command
  `/home/stefanr/.local/bin/agent-eta hook`, as shown in [claude-code-config.md](https://github.com/bestcodename/ai/blob/main/docs/claude-code-config.md).
- `~/.codex/hooks.json` gets a `PreToolUse` and a `PostToolUse` group, each with the matcher `Bash` and the same command,
  and one more group without a matcher for each of `UserPromptSubmit`, `Stop`, `PermissionRequest`, `Interrupt`
  and `SessionEnd`. A group for an event that already has one goes after it, because Codex keys its trust by event, group index and hook
  index, so an appended group leaves the trusted ones untouched. Every new hook has to be trusted once under Settings >
  Hooks in the Codex app. That stores a `trusted_hash` under
  `[hooks.state]` in `~/.codex/config.toml`. Writing that hash by hand would skip the review the app asks for, so it is
  not done here.

After native review, send a fresh prompt in each local Codex chat. Verify that its registration appears in
`/tmp/agent-eta-<uid>/sessions/`, then check `agent-eta list --json --all` and the modal. Confirm working on a new
prompt, waiting at a native permission prompt and idle after Stop. `SessionEnd` removes the native registration;
independent manual reminders remain until their normal expiry or Mark done. Merely finding a thread in the Codex
database does not prove it is active. If a registration is missing, inspect the event and session id in `hook.log`
before changing discovery code. The command is `/home/stefanr/.local/bin/agent-eta hook` with `type: "command"` and
`timeout: 3` in each group. Append only missing handlers, preserving existing groups and native trust records.

## Use per agent

**Claude Code.** The description of a background Bash command ends with its ETA, for example `Run the test suite (ETA
ca. 10 minutes)`. The `PostToolUse` hook acts only when the result carries a `backgroundTaskId`. That covers
`run_in_background` and a command moved to the background after its timeout. Claude Code points fd 1 of the background
shell at `.../tasks/<task id>.output`, which is how the hook finds the shell's pid. The label is the description without
its ETA. A command that already goes through `agent-eta run` is skipped, so it is not listed twice.

**Codex.** A long command ends with a comment carrying its ETA, for example `composer test  # ETA ca. 10 minutes`,
because Codex has no description field. The `PreToolUse` hook records every Bash call under its `tool_use_id`, and the
`PostToolUse` hook deletes it again. A command that goes through `agent-eta run` is skipped here as well. A Codex entry shows only once it is ten seconds old, which is Codex's default
yield, so ordinary short commands never flicker into the list.

**Local runs.** `run-local.sh` registers the whole run right before it starts goose, with `--pid $$` and the timeout as
the ETA, since the timeout is the run's worst case. goose 1.36 has hooks of its own, but its `shell` tool always waits
for a command to finish, so the run itself is the only background task a local model has. Without the tool installed,
the script runs unchanged.

**dsh.** Nothing to do. dsh gets no ETA rule on purpose, because the local models already struggle with the rules
in Claude Code and Codex. A dsh session therefore shows its state and its running bash calls only. A command inside a
dsh session gets `DSH_SESSION_ID`, so `agent-eta add`, `run` and `turn` called from there attach to that session.

**Turn ETAs.** The rule in both agent configs asks for `agent-eta turn --eta 20m --label "…"` at the start of a turn
that will run longer than ca. 10 minutes. `~/.claude/settings.json` allows `agent-eta turn` without a prompt, and in
Codex it writes from inside the sandbox through the shared `/tmp`.

**By hand, or where no hook reaches.**

```sh
agent-eta run --eta 25m --label "full test suite" -- composer test
id=$(agent-eta add --eta 10m --label "CI pipeline 1234")
agent-eta done "$id"
```

`run` lists the command for exactly as long as it runs. It forwards INT, TERM and HUP to it and exits with its exit code.
`add` is for a wait that is not a local process, such as a CI pipeline or a subagent. With `--pid` the entry lives as
long as that process. A bare number after `--eta` is seconds, as for `timeout(1)`.

Every hook call adds one line to `hook.log` in the state directory, with the event, the agent, the session and tool ids
and what the hook did. The command text never goes there. The log rotates at 256 KB.

## Tray widget

`plasmoid` is a Plasma 6 widget for the system tray. It runs `agent-eta list --json --all` every
5 seconds, and every 2 seconds while its popup is open. That call took 52 ms on 2026-10-05.

- **The icon** carries an orb in traffic-light colours over the sessions that are not dormant. It is red with the number
  of waiting sessions as soon as one waits for you, yellow with the number of idle sessions and working ones past their
  ETA, and green without a number while every other session works or waits for a usage limit. Without such a session
  there is no orb, so dormant sessions alone leave the icon bare. Only a red orb marks the widget as needing attention,
  which makes the system tray pulse the icon, and any other orb marks it as active. A thin bar under the icon fills
  with the progress of the working session whose ETA ends first.
- **Hovering** shows the same headline and up to seven sessions with their state and ETA.
- **Clicking** opens the overview. The sessions come in the sections of the text list, each with its progress bar and
  its tasks below it. Stopped and dormant sessions each retain their heading and count and start folded. Their
  independent Show/Hide buttons keep their choice across polls and popup reopening until the widget restarts.
  A dot in the orb's colours marks each session's
  state, red waiting, yellow idle or overdue, green working and grey stopped or unknown. An idle session with a
  verified running background task counts as working for the dot and the orb. A holderless `agent-eta add` reminder
  does not establish activity by itself. The line below the title says how long the
  state has lasted and when it began, as in `idle for 1h 5m (17:25)`. The dot replaced play and pause icons in 0.71.0,
  because those read as buttons that start or stop the session. The usage windows follow, with one bar per window that
  fills with the used share. A tick marks the elapsed share of the window, so a fill past the tick runs out before the
  reset. Thinner and fainter ticks mark every hour of the 5-hour window and every day of the 7-day one, counted from
  the window's start, so the elapsed tick steps onto one of them at each full hour or day. The fill comes in traffic-light bands. With `d` as the share by which the usage runs past the tick and `k` as
  the half-width of the yellow band, it is green up to `k·d` below the tick, yellow from there to `k·d` above it and red
  over the rest up to the usage. `k` is a setting, 66% by default. At 80% usage with the tick at 50% and `k` at 1/3,
  the bar is green up to 40%, yellow up to 60% and red up to 80%. Usage at or below the tick stays green throughout. A
  reached limit is yellow up to the tick and red from there, and a window without a known reset keeps one colour, red
  when reached and green otherwise. The yellow band of a bar that is not reached fades into green and red by default,
  over a share of each half of the band that the settings set, so 100% leaves pure yellow only at the tick. The bands
  are painted on a `Canvas` as separate rectangles, because `QGradient` drops a second stop at the position of an
  earlier one and a hard edge needs two. Each band runs on to the end of the fill and the next one paints over it, so
  two antialiased edges never meet on the same pixel and leave the track showing through between them.
  Every reset carries its countdown, as in `56% · resets in 49m (18:30)`. The line under an account's name, beside the
  freshness of its reading, holds its highest used share and the reset that comes first among its windows, in the
  same form, and an account whose limit is reached reads `blocked · resets in 12h 13m (24:00)` with the reset that
  ends the block.
- **Account rows** remain visible without usage windows. They show authentication and reading freshness. Logged-out
  accounts offer Login and Remove controls. A left or right click anywhere on an account's row opens its menu, with
  **New session in the default directory**, **New session in…**, **Set default directory…**, **Log in** and, for a
  registered Claude account, **Move all sessions here** (see [claude-account.md](https://github.com/bestcodename/ai/blob/main/docs/claude-account.md#handing-sessions-to-another-account)).
  A Claude account also offers **Move all Codex sessions here** and the Codex row **Move all Claude sessions here**,
  which run `agent-eta account handoff ID --from codex|claude` and hand every session that can move over at once.
  The pointer turns into a hand wherever a click does something, on account rows and session rows alike. Cancelling a folder chooser starts no process.
  CLI action failures remain in the footer across ordinary polls.
- **A click on a row** jumps to the session's window. A right click offers that and four more actions.
  - *Jump to window* activates the window of the nearest ancestor in `pids` that owns one. Konsole runs all its windows
    in one process, so the tray first calls `agent-eta tab <pids>`. It finds the Konsole tab whose process is in `pids`
    over D-Bus (`qdbus6`, else `qdbus`, overridden by `AGENT_ETA_QDBUS_BIN`), makes it the current tab of its window and
    prints the caption titles before and after the switch, and the window with one of those captions wins. Without a
    Konsole tab the call exits 1 and the jump goes on as before. Every PhpStorm window belongs to the same process, so
    among several it takes the one whose title starts with `project_name`. For a Codex thread
    it is *Open thread in Codex*, which opens `codex://threads/<id>` in the ChatGPT app. For a dsh session it is *Open
    dsh web UI*, which opens the `web_url` of its process, for example `http://127.0.0.1:3080/`.
  - *Open in PhpStorm* runs `phpstorm <project_root>`, which is always the project root and never a subdirectory.
  - *Open folder* opens the working directory in the file manager.
  - *Copy resume command* puts `cd <cwd> && claude-account run <account> --resume <id>` on the clipboard, or
    `claude --resume <id>` for a session outside the accounts. A Codex thread copies its `codex://` link, since there is
    no Codex CLI on the `PATH`. A dsh session has no resume command, so the action is missing there.
  - *Hand off to Codex* or *Hand off to Claude Code* runs `agent-eta handoff` detached. It is disabled with the
    reason where the session cannot move, and the detail line shows a pending or failed handoff.
  - *Mark done* removes an entry from `agent-eta add` and shows only on such a task.
- **Notifications** go out when a session's or a task's ETA turns overdue and when a usage limit resets. One for a
  session that starts waiting exists as well, but it is off by default since 0.71.0, because the red pulsing orb already
  shows it. Each of the three is switched on and off in the widget's settings. A session whose ETA comes from its tasks
  gets no overdue notification of its own, because the overdue task already brings one. Each panel has a tray of its own
  and therefore its own instance of the widget. Both see every transition, so they share the event keys through
  `contents/code/shared.js` and the first one to claim a key sends it. The first poll after a start only records the
  state and notifies nothing.

The settings also hold the command, which defaults to `"$HOME/.local/bin/agent-eta"` because plasmashell's `PATH`
lacks `~/.local/bin`, the two poll intervals, whether the usage block shows, the half-width of a usage bar's yellow
band and whether the yellow band of a usage
bar fades, together with the width of that fade. The logic that needs no QML lives in
`contents/code/logic.mjs`, which the tests run under node.

```sh
plasmawindowed com.github.bestcodename.agenteta    # the overview in a window, without touching a panel
```

## Measured on 2026-10-05

- A Claude Code session in a PhpStorm terminal runs as `claude` under `bash` under `phpstorm` under the user's
  `systemd`. A `claude bg-spare` session of the daemon runs under `claude bg-pty-host` and has no window ancestor.
- All PhpStorm windows had the same `_NET_WM_PID` and titles of the form `ai – TODO.md`, so the pid alone could not pick
  a window and the project name before ` – ` does.
- The ChatGPT app at `/usr/lib/chatgpt/ChatGPT` is the handler for `x-scheme-handler/codex`, and its bundle routes
  `codex://threads/<id>`. The Claude desktop app routes only `claude://code/new`, `needs-input` and `continue`, so there
  is no link to a Claude Code session.
- `EnabledByDefault` in `metadata.json` did not add the widget to any tray after a restart of plasmashell. The tray
  only shows the ids listed in `extraItems` of its containment, which `install.sh` sets through
  `org.kde.PlasmaShell.evaluateScript`.
- A package directory that is a link to this repository was found by `kpackagetool6 --show` but left out of
  `kpackagetool6 --list`, and at its next start the tray removed the id from `extraItems` again. A real directory with
  links inside failed to load with `kf.package: Path traversal attempt detected`. Only a copy works.
- The system tray moves an applet's full representation into its popup only when the applet leaves
  `preferredRepresentation` unset (`PlasmoidPopupsContainer.qml`, line 38). With it set to the compact one, a click
  set `expanded` but no popup opened.
- Plasma 6.3.6 loads an ES module into QML with `import "../code/logic.mjs" as Logic`.
- A notification the widget sends from inside plasmashell never appears on the session bus, because plasmashell hosts
  the notification server itself. The journal shows the popup instead, as a warning from `DelegatePopup.qml` in the
  same second.

### dsh

- dsh 0.1.5-rc.1 ran as `node /usr/local/bin/dsh web --patch ~/.ollama/launch/dsh/ollama.cordis.yml --no-open`
  under `ollama launch dsh`. Its process held six `session.lock` files open, one per loaded session.
- The largest log was 474 KB, 1.5 MB decoded, with 943 records, decoded and parsed in 27 ms. `agent-eta list --json
  --all` took 116 ms with a cold cache and 55 ms with a warm one, against 52 ms without dsh.
- 194 of 194 bash calls carried a `description`. None used `run_in_background`, so a dsh background job has not been
  seen yet.
- The only page the web server serves is `/`, so there is no link to a single session. The browser keeps its login
  cookie for 30 days, so opening the root needs no token.
- The `/goal` session of sdwa5-inventur ended at 04:47 with five `llm/retry` records of code `TIMEOUT` and a `turn/end`
  of kind `error`. agent-eta showed it under needs you as `waiting (turn failed (TIMEOUT))`.

## Measured on 2026-10-03

- Claude Code 2.1.288 hands its Bash tool and its hooks `CLAUDE_PID`, and `procStart` in `~/.claude/sessions/<pid>.json`
  is field 22 of `/proc/<pid>/stat`. It runs commands in the host pid namespace with no sandbox. No hook fires when a
  background shell ends.
- Codex desktop (codex-cli 0.159.2) runs every command under `bwrap --unshare-pid --unshare-user --proc /proc --bind
  /tmp /tmp`. Inside, `~/.local/state` and `/run/user/1000` are read-only, and `/tmp` is the host's. Its hooks run
  unsandboxed on the host, and their `session_id` is the thread id.
- According to the codex-cli 0.159.2 source, `PostToolUse` does not fire when a command outlives its yield. It fires
  later with the same `tool_use_id`, once a `write_stdin` poll sees the exit. No hook payload carries a host pid.
- The live counter-test passed. A `sleep 120  # ETA ca. 2 minutes` in a Codex thread was recorded by `PreToolUse` at
  22:45:54 and listed ten seconds later as `sleep 120`, under its thread name and with the app-server's pid as holder.
  `PostToolUse` removed it at 22:47:54, the second the sleep ended. Codex therefore runs hooks for the shell calls
  nested in its code-mode `exec`, and in this case it polled the end of the command on its own.
- A cross-test from 22:54 to 23:00 ran three Claude Code tasks and five Codex tasks in two threads side by side. Claude
  Code had a background command with an ETA, one without and an `add`. Codex had three parallel sleeps, one of them
  with an ETA shorter than its run, plus an `add`, a `run` and a `done` from inside the sandbox. Every task was listed in
  the right order, the short ETA turned overdue on top, and the `run` was listed once. Codex `PostToolUse` removed each
  sleep within a second of its end, and the list was empty when the last one finished.
- Claude Code 2.1.288 writes `status` as `busy`, `shell`, `waiting` or `idle`, with `waitingFor` while it waits. The
  binary names `input needed`, `dialog open`, `worker request` and `sandbox request` as reasons, and a permission or
  question dialog brings its own. `shell` was measured on a session whose foreground Bash command was running.
- The Codex 0.159.2 binary names the hook events `PreToolUse`, `PermissionRequest`, `PostToolUse`, `PreCompact`,
  `PostCompact`, `SessionStart`, `SessionEnd`, `SubagentStart`, `SubagentStop` and `Interrupt`, besides
  `UserPromptSubmit` and `Stop`. `config.toml` keys hook trust as `<file>:<event>:<group>:<hook>`.
- On 2026-10-03 at 23:59:39 a Codex thread asked a question through `request_user_input`. No hook fired for it, and
  the list kept showing the thread as working until the reader learned to look for the unanswered call in the rollout
  transcript, where it is a `response_item` of type `function_call` whose `function_call_output` is still missing.
- Claude Code 2.1.288 marks how a registry name came about in `nameSource`, which is `derived`, `auto`, `user`,
  `collision`, `hook` or `peer`. A `derived` name such as `ai-0b` comes from the directory, while the session's title
  is in its transcript as an `ai-title` record, or as a `custom-title` record after a rename.
- The Codex desktop app keeps its threads in `~/.codex/state_5.sqlite`, table `threads`, with `name`, `title` (the first
  prompt) and `rollout_path`. A thread from 03:19 that day had no `name` and no line in `session_index.jsonl`.
- On 2026-10-04 at 01:40:55 a Codex thread in plan mode ended its turn with an `item_completed` event whose `item.type`
  is `Plan`, followed by `task_complete`, and the app asked "Implement this plan?". `Stop` had set the thread idle, and
  only the transcript showed that it waited for the approval.
- On 2026-10-04 at 02:17:51 a Codex thread hit its 5-hour usage limit. The prompt's `UserPromptSubmit` set the thread
  working and no `Stop` followed. The rollout transcript ended with a `task_complete` whose `error` carried
  `codex_error_info: "usage_limit_exceeded"`. The `token_count` event before it had `limit_id: "codex"` with `primary` at
  `used_percent: 100.0` and a `resets_at` of 02:24:10, which matched the app's usage panel. The `token_count` event after
  it had `limit_id: "premium"`, `primary: null` and `rate_limit_reached_type: "workspace_member_credits_depleted"`.
- On 2026-10-04 at 02:49:24 and 02:55:34 a Codex thread asked for a command permission. `PermissionRequest` fired
  each time, the second time twice within the same second, and the list showed the thread as `waiting (permission)`.
- From 2026-10-03 to 2026-10-04 one Codex thread raised 83 permission requests under `approval_policy: "on-request"`
  with `approvals_reviewer: "auto_review"` in its `turn_context`. The app's log database `~/.codex/logs_2.sqlite`
  holds no `op: ExecApproval` submission for any of them, while it logged the same thread's `turn_input` submissions.
  On 2026-10-01, with the reviewer set to `user`, it logged 14 such decisions within ten minutes, and one more at 04:03
  after the thread had switched to `auto_review`. An auto-review request can therefore still reach the user. The
  script holding a request wrote its output 3 to 7 seconds after it, for example at 02:55:41 for the request at
  02:55:34, while the next hook call came at 02:56:17. A long command yields into a `write_stdin` session instead, so
  its `PostToolUse` came only when the model polled it, two minutes later for the request at 02:49:24.
- On 2026-10-04 at 03:46 the Claude Code 5-hour window stood at 34 percent with 32 percent of it passed, and the
  7-day window at 87 percent with 23 percent passed. Codex stood at 39 percent of its 5-hour window with 25 percent
  passed, and at 90 percent of its 7-day window with 43 percent passed. The Codex readings carried `window_minutes` of
  300 and 10080.
- On 2026-10-04 two Claude Code sessions had been idle for two days and more. One was `kind: "interactive"` with a
  `parkedJobId`, running in a PhpStorm terminal tab, and one was `kind: "bg"`, a `claude bg-spare` process under a
  `claude bg-pty-host` of the daemon. The session in active use at the same time was `kind: "bg"` as well.
- goose 1.36.0 has plugin hooks under `~/.agents/plugins/<name>/hooks/hooks.json`.

## Limits

- A Codex command whose process ends without the model polling it again never gets its `PostToolUse`. It then stays
  listed until it expires or until the Codex app-server exits. Matching the process through `CODEX_THREAD_ID` in
  `/proc/*/environ` would close that gap, which TODO.md proposes in case it turns out to matter.
- A command Codex was not allowed to run may also leave an entry behind until it expires.
- When Claude Code starts `run-local.sh` in the background, the list shows two rows, one for the Claude Code task and
  one for the local run.
- Background agents and Monitor tasks of Claude Code are not recorded by the hook. `agent-eta add` covers them.
- A turn that ends with a question in plain text shows as idle, not waiting, because no hook and no registry field tells
  it from a finished turn.
- A Codex script that waits a long time for a command it was allowed to run, through a large `yield_time_ms`, keeps the
  thread at `waiting (permission)` until it returns, because its output is what ends the wait. A request whose script
  is no longer in the last 256 KiB of the transcript stays at waiting until the next hook call.
- Only `usage_limit_exceeded` has been seen as a Codex turn error. Any other `codex_error_info` shows as the stop
  reason with its underscores turned into spaces, and without a countdown.
- The Claude Code usage reading of an account is only as fresh as the last status line render in a session of that
  account. An account without a session since its window reset shows `?`.
- A Codex thread shows only once a hook fired for it, so a thread that has been quiet since the hooks were trusted is
  missing until its next prompt.
- The state of a Codex thread from before the four state hooks were trusted stays at working until its next `Stop`.
- The tray widget's jump focuses the PhpStorm window of the project, but it cannot select the PhpStorm terminal tab the
  session runs in. Konsole tabs are selected. A session of the Claude Code daemon has no window, so its jump is
  disabled.
- plasmashell loads a changed widget only after a restart.
- *Open dsh web UI* opens the root of the web UI in a new browser tab, not the session, because dsh has no link to a
  single session.
- A dsh row is only as fresh as dsh's log writes, which come in batches of about 200 ms.
- A dsh bash call that dsh moves to the background is not recognised as such, because no log here has shown one yet.
- The QML tests click a row and drive the jump against a stub task list, not against KWin, and they do not open the
  context menu or follow its entries into `act()`. Plasma's `i18n` is missing there, so task labels stay empty.

## Tests

```sh
python3 -m unittest discover -s . -v
node --test --test-isolation=none test_plasmoid.mjs
QT_QPA_PLATFORM=offscreen /usr/lib/qt6/bin/qmltestrunner -import test_qml/stubs -input test_qml
journalctl --user -u plasma-plasmashell -n 200 | grep -i agenteta    # QML errors of the widget
```

`test_install.py` runs `install.sh` into a temporary home and checks the link, the copy, a second run, a stale file, a
package link of the first version and the refusal to replace something foreign. It also runs the node tests of
`logic.mjs` and skips them where node is missing. Those cover the formatting and the reset countdown, the summary, the
traffic light of the orb and of each session, the sections, the usage bars with their traffic-light bands and fade, the window choice between PhpStorm windows
of one process, the resume commands and their quoting, and each notification transition.

`test_model.py` covers the model with no-mutation checks, effective activity, ETAs, usage groups, the summary, the
signals and the handoff field, and keeps the contract fixtures current. `test_handoff.py` covers plan resolution for
both providers, the forked one-shot, the destination commands per phase, the launcher's quoting, the snapshot with a
dirty tree, the refreshed snapshot, Codex resolution and registration, and `--dry-run`. Against real `sleep`
processes and a recording freezer it covers the gate, the thaw after a failed registration, a cancel, SIGHUP, any
other error, a refusing freezer, a source turning busy after the pause, a reused pid, duplicates, the lock and a
partial batch. `test_handoff_e2e.py` runs `agent-eta handoff` as a subprocess against a real interactive bash in a pty,
whose foreground job is the source, with the real collectors and the real freezer, and only a fake terminal and a fake
Codex. It covers a completed move, a registration timeout and a cancel, and checks that the job keeps the terminal. It
is skipped without a systemd user manager.

`test_accounts.py` uses isolated homes and stub native clients for authentication, logout, mismatches, cache
persistence, identity changes, expired readings, refresh failures, the 50-empty-rollout regression, throttling and
a real inherited-lock worker. Launch tests cover native argument arrays and URL encoding for spaces, Unicode,
quotes and shell metacharacters. JavaScript tests cover independent folding, reset transitions, missing account
readings, local folder decoding and notifications while fresh usage is unknown. CI installs Node explicitly.

On 2026-10-14 live Codex account and rate-limit reads succeeded without a turn. The implemented CLI refresh returned
current Codex readings, a stale Claude reading and a registered Claude identity mismatch. Source widget previews
loaded both offscreen and on desktop X11 without QML errors during the bounded checks. The OS handler accepted
the current existing thread's deep link. Those are basic checks, not full validation of interactive login, removal,
folder picking or navigation. On 2026-10-18 *Jump to window* raised the right Konsole window for two sessions in
one Konsole process on the notebook under Wayland, checked by hand.

`test_qml.py` runs the QML tests in `test_qml/` with Qt Quick Test, offscreen. `tst_windowjumper.qml` drives
`WindowJumper.qml` against a stub `org.kde.taskmanager` from `test_qml/stubs` and a launcher that records its
commands. It covers the `agent-eta tab` call and its titles picking the Konsole window, a failed call falling back,
a session without a window, the PhpStorm project choice, and Codex and dsh running nothing. `tst_sessionrow.qml`
clicks `SessionRow.qml` with the real Plasma components and covers the jump on a click, the hover, and the menu on a
right click for the session, for a task row and for a session without an id. The test is skipped without the Qt 6
`qmltestrunner` (Debian `qt6-declarative-dev-tools`, `qml6-module-qttest`). CI runs it in a `debian:trixie`
container, because Ubuntu runners have no Plasma 6 modules.

The suite covers duration parsing in both languages, the sort order, every holder alive and dead, `run` with exit codes
and a forwarded SIGTERM, `add` and `done`, the Claude Code hook against a real process whose fd 1 points at a fake
`tasks/<id>.output`, the Codex pairing, and garbage hook input. For sessions it covers the Claude Code registry with a
live and a dead pid, the order of waiting, working and idle, a task without a session, every Codex state hook including
an `Interrupt` without `turn_id`, the stale and expired Codex thread, and turn ETAs for both agents ending with the
turn. For usage it covers the Claude Code windows, the latest Codex reading among several rollouts, a window past its
reset, and both sections with their order. Two registered accounts get their sessions, titles and usage rows read
from both directories under `claude/<name>`. It runs in its own state directory and with fake Claude
Code, Codex and dsh homes, so it never touches a live session. `test_dsh.py` covers every dsh state on record lists,
the title order, the bash calls, the command line of a dsh process with its web address, and, with real zstd logs and a
fake dsh process that holds the locks, the listing of loaded sessions only, an archived session left out and back after unarchiving, the bash task after ten seconds, the cache,
`DSH_SESSION_ID`, a failed turn going dormant and a missing `zstdcat`. It skips the log cases where zstd is missing. The `run-local.sh` selftest checks the registration through a
stub.
