# KDE workspace synchronization

Workspace capture and restoration use KWin 6 and [kdotool 0.3.0](https://github.com/jinliu/kdotool/releases/tag/v0.3.0).
Python still uses only its standard library. Normal monitoring and navigation work without kdotool.

## Commands

| Command | Behavior |
|---|---|
| `agent-eta workspace snapshot` | Emit version 1 JSON without moving windows. |
| `agent-eta workspace snapshot --session SOURCE` | Capture topology and that managed session's dedicated viewer. |
| `agent-eta workspace apply < FILE` | Preview desktop creates, window moves, skips and output mappings. |
| `agent-eta workspace apply --apply --json < FILE` | Apply and return a structured receipt. |
| `agent-eta workspace assign SOURCE PROJECT-123` | Save the assignment and place its dedicated viewer. |
| `agent-eta workspace assign SOURCE --clear` | Clear the assignment without deleting a desktop. |

SOURCE is `claude:<session>`, `codex:<thread>` or `terminal:<managed-id>`.
Commands use the local compositor. SSH can invoke them through the user's existing session bus.
The private bestcodename/ai host-sync tool transports snapshots over its existing SSH connection.

## Desktop identity and matching

Unique desktop names identify workspaces across hosts. Existing local IDs and relative order remain unchanged.
Missing names are inserted before the next source desktop when existing order permits, otherwise appended.
Ordering differences are reported. Destination-only desktops remain. The union must fit KWin's 20-desktop capacity.
Desktops are never renamed, removed or automatically pruned.

Managed windows match through their native session identity. Konsole lookup reads D-Bus tab metadata without
selecting tabs. A viewer match requires one tab and exactly one normal window belonging to that Konsole process.
Other applications require unique, exact desktop-file, class, instance, role and caption identities on both sides.
Transferred captions are SHA-256 digests. PIDs and local window IDs never identify applications across hosts.
Unmanaged Konsole, shared terminals, ambiguous matches and tiled or constrained windows are skipped with reasons.
Applications are never reopened. Dialogs, panels and other special windows are excluded.

Geometry is relative to each output's usable area in logical coordinates. Mapping prefers names, then spatial order,
then the destination active output. Previews show mappings. Rectangles are clamped to usable areas. Application
size constraints can produce a partial result. Minimized, fullscreen, maximized and all-desktop states are retained.
Wayland permits multiple-desktop membership; X11 limitations are reported. Pre-maximization geometry and tiling
layouts are not saved. Background application does not activate windows or switch the current desktop.

## Ticket assignments and handoffs

`account launch --jira-key PROJECT-123` overrides inference. Otherwise a managed launch infers exactly one distinct
key from its Git branch. Private and ambiguous branches stay unassigned. The result is saved once; branch changes
do not silently reassign a running session. Use `workspace assign` to change it. No Jira API or credentials are used.

Launch, attach and the widget's existing Jump path reuse a ticket desktop and place the dedicated local viewer there.
Shared Codex desktop windows cannot receive per-thread placement; explicit keys require managed CLI mode.
Cross-provider handoffs retain assignment metadata in the destination managed record.

The optional `workspace` field in claude-account's existing `;;` tabs descriptor contains base64-encoded version 1
snapshot JSON. It carries an `assignment` and at most one window. New consumers restore placement after successful
attachment. Older consumers ignore the field; the sender reports missing destination support.
The Jira key determines desktop membership; captured geometry supplies position. Successful restoration consumes
captured geometry, so later Jump actions respect manual moves. Failure leaves the agent running and never repeats
a successful launch. Host topology is applied once before a batch resumes.

## Recovery and tests

Writes use a per-host lock. General application saves a mode-0600 destination backup under
`${AGENT_ETA_DIR:-/tmp/agent-eta-$UID}/workspace/before-*.json`. Preview and reapply a chosen backup to restore matched
windows. Newly created desktops remain. Snapshots contain no credentials, process environments or clipboard data.
Local window identities are rechecked inside KWin immediately before writes. Read-back waits up to two seconds for
asynchronous client acknowledgement before changing desktop membership. JSON receipts distinguish plans, skips,
applications and verification differences.
Failure after writing names the backup and reports possible partial application. Unconfirmed application returns
nonzero. Restoration does not promise atomic rollback.

```sh
python3 -m unittest -v test_workspace
AGENT_ETA_KWIN_TESTS=1 python3 -m unittest -v test_workspace_kwin
```

The opt-in suite needs kwin-x11, kwin-wayland, konsole, xvfb, xauth, dbus and kdotool. It uses private displays,
buses, homes and configuration. It never targets the user's compositor. Wayland uses the QPainter virtual backend.
Continuous synchronization, a widget assignment editor and application reopening remain deferred.
