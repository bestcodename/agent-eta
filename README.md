# agent-eta

`agent-eta` lists every running Claude Code, Codex, dsh and local-model session on a Linux machine with its state, its
ETA and its background tasks, and shows the usage windows of every account. Sessions waiting for an answer come first.
Completed Codex turns stay idle even when a rejected command misses its completion hook; unanswered native questions
show as waiting. A Plasma 6 tray widget shows the same overview, shows a session's existing terminal on click and offers account
actions such as starting a session, logging in and moving all Claude Code sessions to another account.
`agent-eta handoff` moves a session between Claude Code and Codex with its plan, by hand or at a usage limit.

Hooks and the agents' own session registries fill the list, so an agent only has to write down the ETA it states anyway.

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

## Usage

```sh
agent-eta                          # sessions, their tasks and the usage windows
agent-eta add --eta 10m --label "Run the test suite"
agent-eta done <id>
agent-eta turn --eta 20m --label "Long refactor"
agent-eta list --json --all        # what the widget reads, contract schema 1
agent-eta account launch claude:NAME --directory /trusted/project
agent-eta account launch codex --cli --directory /trusted/project
agent-eta attach claude:<session>   # show the existing managed terminal
agent-eta handoff claude:<session> --to codex   # continue a session's plan in Codex
```

A handoff refuses a folder the destination client does not trust yet, and its message names the command that opens
the client there once to accept the trust question.

Managed CLI rows select their tmux pane and focus an attachment, opening the configured viewer when detached.
Desktop threads open in the app. Unmanaged CLI sessions remain visible but must be closed and resumed with
`agent-eta account launch ACCOUNT --cli --resume SESSION_ID --directory DIR` before cross-provider handoff.
Resuming a session with a live writer is refused. Existing clients are never moved into tmux.

The hooks for Claude Code and Codex, every command and the widget are described in
[docs/agent-eta.md](docs/agent-eta.md).

## Tests

```sh
python3 -m unittest discover -s . -v
node --test --test-isolation=none test_plasmoid.mjs
```

The QML tests in `test_qml/` need Qt 6's `qmltestrunner` and the Plasma 6 QML modules, see
[docs/agent-eta.md](docs/agent-eta.md#tests).

## Changelog and roadmap

See [CHANGELOG.md](CHANGELOG.md) and [TODO.md](TODO.md). Before 1.0.0 agent-eta lived in bestcodename/ai under
`scripts/agent-eta`.

## License

MIT, see [LICENSE](LICENSE).
