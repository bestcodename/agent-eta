#!/usr/bin/env bash
#
# Link agent-eta into ~/.local/bin and install its tray widget into Plasma. See docs/agent-eta.md.
#
# The tool is linked, so a pull of this repository updates what the hooks call. The widget has to
# be copied (see below), so a pull that changes it needs another run of this script. The hooks themselves are wired by hand in ~/.claude/settings.json and
# ~/.codex/hooks.json, because Codex skips every new hook until it is trusted in its own settings,
# and that step cannot be scripted honestly. A second run changes nothing.
#
# Where Plasma 6 runs, the widget is copied into ~/.local/share/plasma/plasmoids and added to every
# system tray through plasmashell's scripting interface. plasmashell only loads a new or changed
# widget after a restart, so the script names that command rather than restarting it.
#
# The tests redirect it with BIN_DIR and PLASMOID_DIR, and AGENT_ETA_TRAY=0 leaves the trays alone.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bin_dir="${BIN_DIR:-$HOME/.local/bin}"
target="$bin_dir/agent-eta"
plasmoid_id="com.github.bestcodename.agenteta"

link() {
    if [ -e "$2" ] && [ ! -L "$2" ]; then
        echo "$2 exists and is not a link. Refusing to replace it." >&2
        exit 1
    fi
    mkdir -p "$(dirname "$2")"
    ln -sfn "$1" "$2"
    echo "$2 -> $(readlink "$2")"
}

link "$here/agent-eta" "$target"

if [ -z "${PLASMOID_DIR:-}" ] && ! command -v kpackagetool6 >/dev/null 2>&1; then
    exit 0
fi
# The widget is copied, not linked. Plasma's package listing skips a package directory that is a
# link, the system tray drops every item that listing lacks, and KPackage refuses links inside a
# package that point out of it. The copy is replaced as a whole, so a deleted file goes as well.
package="${PLASMOID_DIR:-$HOME/.local/share/plasma/plasmoids}/$plasmoid_id"
if [ -L "$package" ]; then
    rm "$package"
elif [ -e "$package" ] && ! grep -qs "\"Id\": \"$plasmoid_id\"" "$package/metadata.json"; then
    echo "$package exists and is not this widget. Refusing to replace it." >&2
    exit 1
fi
mkdir -p "$(dirname "$package")"
staging="$(mktemp -d "$package.XXXXXX")"
chmod 755 "$staging"
cp -R "$here/plasmoid/." "$staging/"
rm -rf "$package"
mv "$staging" "$package"
echo "$package <- $here/plasmoid"

if [ "${AGENT_ETA_TRAY:-1}" = 0 ] \
        || ! gdbus introspect --session --dest org.kde.plasmashell --object-path /PlasmaShell >/dev/null 2>&1; then
    exit 0
fi
# Each panel's system tray keeps its items in a containment of its own, which the tray applet names
# in SystrayContainmentId. Plasma's own update scripts reach it the same way.
read -r -d '' script <<EOF || true
var id = "$plasmoid_id", trays = 0, added = 0;
panels().forEach(function (panel) {
    panel.widgets("org.kde.plasma.systemtray").forEach(function (widget) {
        var tray = desktopById(widget.readConfig("SystrayContainmentId"));
        if (!tray) {
            return;
        }
        trays++;
        tray.currentConfigGroup = ["General"];
        var items = String(tray.readConfig("extraItems") || "").split(",").filter(function (item) { return item; });
        if (items.indexOf(id) < 0) {
            items.push(id);
            tray.writeConfig("extraItems", items);
            tray.reloadConfig();
            added++;
        }
    });
});
print(trays + " system trays, widget added to " + added);
EOF
gdbus call --session --dest org.kde.plasmashell --object-path /PlasmaShell \
    --method org.kde.PlasmaShell.evaluateScript "$script" | sed "s/^('//; s/\\\\n',)\$//; s/',)\$//"
echo "Restart plasmashell to load a new or changed widget: systemctl --user restart plasma-plasmashell.service"
