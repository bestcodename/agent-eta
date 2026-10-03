#!/usr/bin/env bash
#
# Link agent-eta into ~/.local/bin. See docs/agent-eta.md.
#
# A link rather than a copy, so a pull of this repository updates the tool that the hooks
# call. The hooks themselves are wired by hand in ~/.claude/settings.json and
# ~/.codex/hooks.json, because Codex skips every new hook until it is trusted in its own
# settings, and that step cannot be scripted honestly. A second run changes nothing.
#
# The tests redirect it with BIN_DIR.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bin_dir="${BIN_DIR:-$HOME/.local/bin}"
target="$bin_dir/agent-eta"

if [ -e "$target" ] && [ ! -L "$target" ]; then
    echo "$target exists and is not a link. Refusing to replace it." >&2
    exit 1
fi
mkdir -p "$bin_dir"
ln -sfn "$here/agent-eta" "$target"
echo "$target -> $(readlink "$target")"
