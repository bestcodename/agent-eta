# agent-eta

`agent-eta` lists every running Claude Code, Codex, dsh and local-model session on a Linux machine with its state, its
ETA and its background tasks, and shows the usage windows of every account. Sessions waiting for an answer come first.
Completed Codex turns stay idle even when a rejected command misses its completion hook; unanswered native questions
show as waiting. An open asynchronous question stays green in Working while its turn continues, with the label
"working, question open". A permission request still needs attention. A Plasma 6 tray widget shows the same overview,
shows a session's existing terminal on click and offers account
actions such as starting a session, logging in and moving all Claude Code sessions to another account.
New sessions from the widget use the CLI by default. **Use CLI by default** in the widget settings selects the
Codex launch client; its account menu also offers the other client for a single launch.
`agent-eta handoff` moves a session between Claude Code and Codex with its plan, by hand or at a usage limit.

Hooks and the agents' own session registries fill the list, so an agent only has to write down the ETA it states anyway.
Run process-aware listing on the host. A sandbox with a different PID namespace is refused before it can delete
host session records; explicit `add` and `done` commands remain usable inside the sandbox.

## Install

```sh
git clone git@github.com:bestcodename/agent-eta.git ~/PhpstormProjects/agent-eta
~/PhpstormProjects/agent-eta/install.sh
systemctl --user restart plasma-plasmashell.service   # load a new or changed widget
```

The installer links `~/.local/bin/agent-eta` to the checkout, so a `git pull` updates the CLI. The widget is a copy in
`~/.local/share/plasma/plasmoids`, so it needs the installer and a plasmashell restart after each change.

Requirements are Python 3.11 or later with the standard library only (CI runs 3.13), and Plasma 6 for the widget. The Claude Code
account features use `claude-account` from [bestcodename/ai](https://github.com/bestcodename/ai) when it is on `PATH`
or in `~/.local/bin`, and the usage windows come from that repository's `scripts/claude-usage/statusline.py`.
Managed CLI sessions and cross-provider handoffs require tmux and a running systemd 254+ user manager.
Install tmux with your package manager before running the installer. A private tmux server hosts agent terminals
independently of viewers and handoff controllers. Konsole is the default viewer; `AGENT_ETA_TERMINAL_BIN` can select
another terminal supporting `-e`. Closing the viewer leaves agents running; explicitly ending an agent stops it.
A viewer closes once its agent ends, instead of showing another agent. Viewers run the running tmux server's own
binary, so a tmux upgrade does not break new viewers before the server restarts.
Each pane keeps a separate launcher so tmux's own scope tracking cannot move the agent out of its owned scope.
The launcher clears inherited `NO_COLOR` so automation tools cannot force an interactive agent into grayscale.
It preserves `TERM` and `COLORTERM`; explicitly supplied launcher settings still take precedence.

## Usage

```sh
agent-eta                          # sessions, their tasks and the usage windows
agent-eta add --eta 10m --label "Run the test suite"
agent-eta set <id> --eta 30m       # a revised ETA replaces the old one
agent-eta done <id>
agent-eta turn --eta 20m --label "Long refactor"
agent-eta list --json --all        # what the widget reads, contract schema 1
agent-eta account launch claude:NAME --directory /trusted/project
agent-eta account launch claude:NAME --cli --model opus --effort max --permission-mode plan --prompt 'Review this project'
agent-eta account launch codex --cli --directory /trusted/project
agent-eta attach claude:<session>   # show the existing managed terminal
ssh -t HOST agent-eta attach claude:<session>   # the same from another machine
agent-eta remote add HOST           # show HOST's sessions in the widget, opened over SSH
agent-eta account-tabs FILE         # start a claude-account handoff's tabs in managed tmux
agent-eta handoff claude:<session> --to codex   # continue a session's plan in Codex
```

A handoff refuses a folder the destination client does not trust yet, and its message names the command that opens
the client there once to accept the trust question.

Managed Codex resumes are listed idle before their first prompt. Local launch and attach succeed only after a
viewer attaches; remote attach requires its SSH viewer to stay running through a short settling period.
Managed CLI rows focus the window already showing their pane, or open a window of their own. Inside a viewer, a
click on a status-line tab switches agents. An agent shows in at most one local viewer; selecting one that another
viewer shows points at that viewer instead. An attach from another machine (`--host`) always opens a viewer of its
own. `"viewer_duplicates": true` in `~/.config/agent-eta/config.json` allows duplicates.
Remote navigation reuses matching SSH viewers opened manually with `agent-eta` on PATH or through a full path.
An idle session whose only open entries are reminders not due yet is listed with the working sessions;
`"reminder_sessions": "needs_you"` in the same file keeps it under Needs you.
Existing desktop threads open in the app. Unmanaged CLI sessions remain visible but must be closed and resumed with
`agent-eta account launch ACCOUNT --cli --resume SESSION_ID --directory DIR` before cross-provider handoff.
Resuming a session with a live writer is refused; a session that only an open ETA keeps listed has none.
Existing clients are never moved into tmux.

Claude launches accept `--model`, `--effort`, `--permission-mode` and `--prompt`, including with `--resume`.
These options apply to that launch and keep the chosen account and managed terminal. Omitted settings use native
defaults. Use this route for takeover sessions instead of hand-written Konsole commands. Codex rejects these
Claude-only options.

The hooks for Claude Code and Codex, every command and the widget are described in
[docs/agent-eta.md](docs/agent-eta.md).

## Tests

```sh
python3 -m unittest discover -s . -v
node --test --test-isolation=none test_plasmoid.mjs
```

The QML tests in `test_qml/` need Qt 6's `qmltestrunner` and the Plasma 6 QML modules, see
[docs/agent-eta.md](docs/agent-eta.md#tests).
CI reports Python test failures as GitHub annotations, including their tracebacks.
`.gitlab-ci.yml` provides Python, JavaScript and QML test jobs for GitLab runners as well.

## Changelog and roadmap

See [CHANGELOG.md](CHANGELOG.md) and [TODO.md](TODO.md). Before 1.0.0 agent-eta lived in bestcodename/ai under
`scripts/agent-eta`.

## License

MIT, see [LICENSE](LICENSE).
