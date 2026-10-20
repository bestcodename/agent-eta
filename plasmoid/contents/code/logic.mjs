// What the agent-eta tray widget shows, from `agent-eta list --json --all`, contract schema 1.
//
// agent-eta decides activity, order, sections, counts, usage grouping and what may notify, and
// this file only checks and formats its listing. Pure functions without QML, so `node --test`
// covers them (test_plasmoid.mjs). See docs/agent-eta.md, section "Tray widget".

// The contract version this widget reads.
export const SCHEMA_VERSION = 1;
export const DORMANT_SECTION = 3;
export const STOPPED_SECTION = 2;

// The traffic-light colour of a semantic light. A coloured dot rather than a media icon, because a
// play or pause symbol reads as a button that starts or stops the session. Lights.qml maps the
// colour names to theme colours.
const LIGHT_COLOURS = {
    attention: "red",
    caution: "yellow",
    active: "green",
    off: "grey",
};

const LISTS = ["sessions", "tasks", "usage", "accounts", "sections", "usage_groups", "notification_signals"];

// The listing in `text`, or why it cannot be shown. A CLI older than the contract prints no
// `schema_version`, and a newer contract needs a newer widget.
export function validateListing(text) {
    let data = null;
    try {
        data = typeof text === "string" ? JSON.parse(text) : text;
    } catch (error) {
        return {listing: null, error: "agent-eta printed no valid JSON"};
    }
    if (!data || typeof data !== "object" || Array.isArray(data)) {
        return {listing: null, error: "agent-eta printed no listing"};
    }
    if (data.schema_version === undefined) {
        return {listing: null, error: "agent-eta CLI too old, update it"};
    }
    if (data.schema_version !== SCHEMA_VERSION) {
        return {listing: null,
                error: `agent-eta reports contract ${data.schema_version}, this widget reads ${SCHEMA_VERSION}. Update the widget`};
    }
    const missing = LISTS.filter(key => !Array.isArray(data[key]));
    if (typeof data.now !== "number" || !isObject(data.summary) || !isObject(data.labels)) {
        missing.unshift("now, summary or labels");
    }
    return missing.length ? {listing: null, error: `agent-eta listing lacks ${missing.join(", ")}`}
        : {listing: data, error: ""};
}

function isObject(value) {
    return !!value && typeof value === "object" && !Array.isArray(value);
}

export function lightColour(light) {
    return LIGHT_COLOURS[light] || "grey";
}

function pad(number) {
    return String(number).padStart(2, "0");
}

// A span as agent-eta's REMAINING column prints it: `<1m`, `4m`, `1h05`, `2d3h`, `-12m` or `?`.
export function formatSpan(seconds) {
    if (seconds === null || seconds === undefined) {
        return "?";
    }
    const sign = seconds < 0 ? "-" : "";
    const left = Math.abs(Math.trunc(seconds));
    if (!sign && left < 60) {
        return "<1m";
    }
    const totalMinutes = Math.floor(left / 60);
    const hours = Math.floor(totalMinutes / 60);
    const minutes = totalMinutes % 60;
    if (hours >= 24) {
        return `${sign}${Math.floor(hours / 24)}d${hours % 24}h`;
    }
    if (hours) {
        return `${sign}${hours}h${pad(minutes)}`;
    }
    return `${sign}${minutes}m`;
}

// A due time as agent-eta's DUE column prints it, in local time, with the date when it is a day
// or more away.
export function formatClock(epoch, now) {
    if (!epoch) {
        return "-";
    }
    const moment = new Date(epoch * 1000);
    const time = `${pad(moment.getHours())}:${pad(moment.getMinutes())}`;
    if (Math.abs(epoch - now) >= 86400) {
        return `${pad(moment.getDate())}.${pad(moment.getMonth() + 1)}. ${time}`;
    }
    return time;
}

// A span ahead as `<1m`, `49m`, `12h 13m` or `2d 3h`, for the countdown behind a clock time. A span
// that is unknown or already over gives "".
export function formatIn(seconds) {
    if (seconds === null || seconds === undefined || seconds < 0) {
        return "";
    }
    const totalMinutes = Math.floor(seconds / 60);
    if (totalMinutes < 1) {
        return "<1m";
    }
    const hours = Math.floor(totalMinutes / 60);
    if (hours >= 24) {
        return `${Math.floor(hours / 24)}d ${hours % 24}h`;
    }
    return hours ? `${hours}h ${totalMinutes % 60}m` : `${totalMinutes}m`;
}

// A reset as `in 12h 13m (24:00)`, or the clock time alone once it has passed.
export function resetText(epoch, now) {
    const left = epoch ? formatIn(epoch - now) : "";
    return left ? `in ${left} (${formatClock(epoch, now)})` : formatClock(epoch, now);
}

// How long a state has lasted, as `1h 5m (17:25)` with the clock time it began.
export function sinceText(epoch, now) {
    return `${formatIn(now - epoch)} (${formatClock(epoch, now)})`;
}

// A usage window length as `5h` or `7d`.
export function formatWindow(minutes) {
    if (minutes % 1440 === 0) {
        return `${minutes / 1440}d`;
    }
    if (minutes % 60 === 0) {
        return `${minutes / 60}h`;
    }
    return `${minutes}m`;
}

// The faint ticks of a usage bar as shares from 0 to 1, one at every full day of a window of several
// days and one at every full hour of a shorter one, counted from the window's start like the elapsed
// tick, so that tick lands on one of them each hour or day. A window of no whole hours gets none.
export function windowTicks(minutes) {
    if (!Number.isInteger(minutes) || minutes <= 0) {
        return [];
    }
    const unit = minutes > 1440 && minutes % 1440 === 0 ? 1440 : minutes % 60 === 0 ? 60 : 0;
    if (!unit) {
        return [];
    }
    const count = minutes / unit;
    return Array.from({length: count - 1}, (_, index) => (index + 1) / count);
}

export function percent(value) {
    return value === null || value === undefined ? "?" : `${Math.round(value)}%`;
}

export function agentLabel(session) {
    return session.account ? `${session.agent}/${session.account}` : session.agent || "-";
}

// The words for what a session does, from agent-eta's label table.
export function stateLabel(session) {
    return session.activity_label || session.activity_state || session.state || "-";
}

export function stateLight(session) {
    return lightColour(session.light);
}

export function title(session) {
    return session.turn_label ? `${session.name} · ${session.turn_label}` : session.name || "-";
}

// The right-hand text of a row: how long is left, how far it ran over, or nothing.
export function etaText(item) {
    if (item.due) {
        return item.remaining < 0 ? `${formatSpan(-item.remaining)} over` : `${formatSpan(item.remaining)} left`;
    }
    return (item.activity_state || item.state) === "working" ? "no ETA" : "";
}

// The second line of a session row.
export function detailLine(session, now) {
    const parts = [agentLabel(session)];
    if (session.model) {
        parts.push(session.model);
    }
    if (session.project_name) {
        parts.push(session.project_name);
    }
    let state = stateLabel(session);
    if (session.waiting_for) {
        state += ` (${session.waiting_for})`;
    }
    if (session.since && session.state !== "-") {
        state += ` for ${sinceText(session.since, now)}`;
    }
    parts.push(state);
    if (session.due) {
        parts.push(`due ${formatClock(session.due, now)}`);
    }
    const moving = handoffText(session);
    if (moving) {
        parts.push(moving);
    }
    return parts.join(" · ");
}

const PROVIDERS = {claude: "Claude Code", codex: "Codex"};
const HANDOFF_PENDING = ["prepared", "launched", "waiting"];

// The latest handoff of a session while it is pending or after it failed. A completed one ends the source.
export function handoffText(session) {
    const status = session.handoff && session.handoff.status;
    if (!status) {
        return "";
    }
    const target = PROVIDERS[status.target] || status.target;
    if (HANDOFF_PENDING.includes(status.state)) {
        return `handoff to ${target} pending`;
    }
    if (status.state === "failed" || status.state === "cancelled") {
        return `handoff to ${target} ${status.state}` + (status.error ? `: ${status.error}` : "");
    }
    return "";
}

// The session menu's handoff entry: the other provider, the command and, when it cannot move, why.
export function handoffAction(session, command) {
    const view = session && session.handoff;
    if (!view || !view.targets || view.targets.length === 0) {
        return null;
    }
    const target = view.targets.find(name => name !== session.agent) || view.targets[0];
    const text = `Hand off to ${PROVIDERS[target] || target}` + (view.available ? "" : ` (${view.reason})`);
    return {text: text, enabled: !!view.available,
            command: `${command} handoff ${shellQuote(session.agent + ":" + session.id)} --to ${target}`};
}

function sessionsOf(listing) {
    return (listing && listing.sessions) || [];
}

function byKey(items) {
    const found = {};
    for (const item of items || []) {
        found[item.key] = item;
    }
    return found;
}

function tasksById(listing) {
    const found = {};
    for (const task of (listing && listing.tasks) || []) {
        found[task.id] = task;
    }
    return found;
}

// A span of whole hours as `2 hours`, any other as formatIn() does.
export function formatDuration(seconds) {
    if (seconds > 0 && seconds % 3600 === 0) {
        return seconds === 3600 ? "1 hour" : `${seconds / 3600} hours`;
    }
    return formatIn(seconds);
}

// The tray state from agent-eta's summary, with the colour of the orb and the session whose
// progress the tray icon shows. Only red marks the widget as needing attention, which makes the
// tray pulse. Without any session that is not dormant the orb is "none".
export function summary(listing) {
    const found = (listing && listing.summary) || {};
    const count = name => found[name] || 0;
    const result = {
        waiting: count("waiting"),
        working: count("working"),
        idle: count("idle"),
        stopped: count("stopped"),
        overdue: count("overdue"),
        dormant: count("dormant"),
        attention: count("attention"),
        next: (found.progress_session_key && byKey(sessionsOf(listing))[found.progress_session_key]) || null,
        light: !found.light || found.light === "off" ? "none" : lightColour(found.light),
        orbCount: count("badge_count"),
        status: found.status || "passive",
    };
    const parts = [];
    for (const name of ["waiting", "overdue", "working", "idle", "stopped"]) {
        if (result[name]) {
            parts.push(`${result[name]} ${name}`);
        }
    }
    result.headline = parts.length ? parts.join(" · ") : "No active agent sessions";
    return result;
}

// The sections agent-eta ordered, each with its sessions and their task objects as `taskItems`.
// Stopped and dormant sections retain their counts, and list their sessions only when independently
// opened. Empty sections are left out.
export function groupSessions(listing, showDormant, showStopped = false) {
    const sessions = byKey(sessionsOf(listing));
    const tasks = tasksById(listing);
    const groups = ((listing && listing.sections) || []).map(section => {
        const keys = section.session_keys || [];
        const shown = (section.index !== DORMANT_SECTION || showDormant)
            && (section.index !== STOPPED_SECTION || showStopped);
        return {
            section: section.index, title: section.title, count: keys.length,
            sessions: shown ? keys.map(key => sessions[key]).filter(Boolean).map(session => Object.assign({}, session, {
                taskItems: (session.tasks || []).map(id => tasks[id]).filter(Boolean),
            })) : [],
        };
    });
    return groups.filter(group => group.count > 0);
}

// The usage groups agent-eta ordered, with their window and account objects. `resetBy` is the window
// that resets first for an agent with room left and the one that ends the block for a blocked one.
export function usageGroups(listing) {
    const windows = byKey(listing && listing.usage);
    const accounts = byKey(listing && listing.accounts);
    return ((listing && listing.usage_groups) || []).map(group => ({
        agent: group.agent,
        account: accounts[group.account_key] || null,
        windows: (group.window_keys || []).map(key => windows[key]).filter(Boolean),
        reached: !!group.reached,
        ahead: !!group.ahead,
        used: group.used === undefined ? null : group.used,
        resetBy: windows[group.reset_window_key] || null,
    }));
}

function known(window) {
    return !!window && window.remaining !== null && window.remaining !== undefined;
}

// Authentication and missing readings describe accounts, not inferred session states.
export function accountStatus(account, now) {
    if (!account) return "";
    if (account.auth_state === "logged_out") return "Not logged in";
    if (account.auth_state === "mismatch") return "Different account logged in";
    const parts = [];
    if (account.auth_state === "unknown") parts.push("Authentication unknown");
    if (account.usage_status !== "current") parts.push(account.usage_status === "stale" ? "Stale reading" : "Usage unavailable");
    if (account.seen_at) parts.push(`read ${formatIn(Math.max(0, now - account.seen_at))} ago`);
    if (account.error) parts.push(account.error);
    return parts.join(" · ");
}

export function folderPath(url) {
    const text = String(url);
    if (!text.startsWith("file:///")) return null;
    try { return decodeURIComponent(text.slice(7)); } catch (_) { return null; }
}

function band(from, to, light) {
    return {from: Math.max(0, from), to, light};
}

// The traffic-light bands of a usage bar's filled part, as `{from, to, light}` in percent of the
// whole bar. With `u` the used share, `t` the tick of the elapsed share, `d = u - t` and `k` the
// half-width of the yellow band as a share of `d`, 0.66 by default:
//
// - Usage at or below the tick is green throughout.
// - Usage past the tick is green up to `t - k·d`, yellow from there to `t + k·d`, so the yellow
//   band is centred on the tick, and red from there up to the usage. With `k` at 1/3, red covers
//   the last two thirds of `d`.
// - A reached limit is yellow up to the tick and red from there.
// - A window without a known reset keeps one colour, red when reached and green otherwise.
//
// `fade`, from 0 to 1, blends the yellow band of a bar that is not reached into its neighbours.
// It is the share of each half of the band that fades, so 1 leaves pure yellow only at the tick
// and 0 keeps hard edges. The band then carries `stops` as `[percent, light]` pairs over the band
// before it was cut off at 0, so a cut band keeps its fade where it was.
export function usageBands(window, fade = 0, yellow = 0.66) {
    const used = Math.min(100, window.used || 0);
    if (used <= 0) {
        return [];
    }
    const tick = window.elapsed;
    if (tick === null || tick === undefined) {
        return [band(0, used, window.reached ? "red" : "green")];
    }
    if (window.reached) {
        return [band(0, tick, "yellow"), band(tick, used, "red")].filter(each => each.to > each.from);
    }
    if (used <= tick) {
        return [band(0, used, "green")];
    }
    const half = (used - tick) * Math.max(0, Math.min(1, yellow));
    const start = tick - half;
    const end = tick + half;
    const middle = band(start, end, "yellow");
    const share = Math.max(0, Math.min(1, fade));
    if (share > 0 && half > 0) {
        middle.stops = [[start, "green"], [start + share * half, "yellow"],
                        [end - share * half, "yellow"], [end, "red"]];
    }
    return [band(0, start, "green"), middle, band(end, used, "red")].filter(each => each.to > each.from);
}

// The line beside an agent's name in the usage block. An agent with room left shows its highest
// used share and the reset that comes first, as in `56% · resets in 49m (18:30)`, and a blocked one
// the reset that ends the block. Without a known reset the share stands alone.
export function usageHeadline(group, now) {
    if (group.reached && group.resetBy) {
        return `blocked · resets ${resetText(group.resetBy.resets_at, now)}`;
    }
    const next = group.resetBy;
    return known(next)
        ? `${percent(group.used)} · resets ${resetText(next.resets_at, now)}`
        : percent(group.used);
}

function titleProject(title) {
    return String(title || "").split(" – ")[0].trim();
}

// The window to raise for a session, as an index into `windows` ({index, pid, title}), or -1. The
// nearest process in the session's lineage that owns a window wins. One process may own several
// windows. Konsole runs all its windows in one process, so the caption titles `agent-eta tab` reports
// pick among them first. One PhpStorm process owns every project window, so the window whose title
// starts with the project name comes next.
export function pickWindow(windows, pids, projectName, titles) {
    for (const pid of pids || []) {
        const owned = (windows || []).filter(window => window.pid === pid);
        if (!owned.length) {
            continue;
        }
        const captioned = owned.find(window => (titles || []).some(title => title
            && (window.title === title || String(window.title || "").startsWith(title + " — "))));
        const named = projectName
            ? owned.find(window => titleProject(window.title) === projectName)
                || owned.find(window => String(window.title || "").includes(projectName))
            : null;
        return (captioned || named || owned[0]).index;
    }
    return -1;
}

// The `agent-eta tab` call that makes a session's Konsole tab current, or "" for a session without pids.
export function tabCommand(command, pids) {
    const numbers = (pids || []).filter(pid => Number.isInteger(pid) && pid > 0);
    return numbers.length ? command + " tab " + numbers.join(" ") : "";
}

// The caption titles `agent-eta tab` printed, or [] when it found no Konsole tab or printed garbage.
export function tabTitles(code, stdout) {
    if (code !== 0) {
        return [];
    }
    try {
        const titles = JSON.parse(stdout).titles;
        return Array.isArray(titles) ? titles.filter(title => typeof title === "string" && title) : [];
    } catch (error) {
        return [];
    }
}

export function shellQuote(text) {
    return `'${String(text).replace(/'/g, "'\\''")}'`;
}

// What "Copy" puts on the clipboard. A Claude Code session gets the command that resumes it in its
// directory and account, a Codex thread its link in the Codex app, which has no CLI on the PATH.
export function resumeCommand(session) {
    if (session.agent === "codex" && session.id) {
        return `codex://threads/${session.id}`;
    }
    if (session.agent !== "claude" || !session.id) {
        return "";
    }
    const claude = session.account ? `claude-account run ${shellQuote(session.account)}` : "claude";
    const resume = `${claude} --resume ${shellQuote(session.id)}`;
    return session.cwd ? `cd ${shellQuote(session.cwd)} && ${resume}` : resume;
}

export function escapeHtml(text) {
    return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// The tooltip's lines, one per session that is not dormant, as StyledText.
export function tooltipLines(listing, max) {
    const live = sessionsOf(listing).filter(session => !session.dormant);
    const lines = live.slice(0, max).map(session => {
        const detail = [stateLabel(session) + (session.waiting_for ? ` (${session.waiting_for})` : "")];
        const eta = etaText(session);
        if (eta && eta !== "no ETA") {
            detail.push(eta);
        }
        return `<b>${escapeHtml(session.name || "-")}</b> · ${escapeHtml(detail.join(", "))}`;
    });
    if (live.length > max) {
        lines.push(`… ${live.length - max} more`);
    }
    return lines;
}

// The notification texts of a signal, from the parameters agent-eta gives it.
function message(signal, now) {
    const params = signal.message_params || {};
    if (signal.kind === "waiting") {
        return {title: `${params.name} is waiting`, text: `${params.agent} needs you: ${params.waiting_for}`};
    }
    if (signal.kind === "overdue" && String(signal.entity_key).startsWith("task:")) {
        return {title: `${params.label || "A task"} is overdue`,
                text: `${params.session_name} expected it at ${formatClock(params.due, now)}`};
    }
    if (signal.kind === "overdue") {
        return {title: `${params.name} is overdue`,
                text: params.turn_label ? `${params.turn_label} was due ${formatClock(params.due, now)}`
                    : `It was due ${formatClock(params.due, now)}`};
    }
    return {title: `${params.agent} usage limit reset`,
            text: params.reading_pending
                ? `The recorded ${formatWindow(params.minutes)} window ended. A fresh usage reading is pending.`
                : `The ${formatWindow(params.minutes)} window has room again`};
}

// The events worth a notification between two valid listings, by agent-eta's signals. A rising
// signal notifies when it turns active, or when it shows up active with `notify_on_new`. A falling
// one notifies when it turns inactive, under the dedupe key it had while active. The key is the same
// for every widget instance, so two trays notify once. The first poll has nothing to compare with.
export function signalEvents(previous, next) {
    if (!previous || !next) {
        return [];
    }
    const before = new Map((previous.notification_signals || []).map(signal => [signal.key, signal]));
    const events = [];
    for (const signal of next.notification_signals || []) {
        const old = before.get(signal.key);
        let key = null;
        if (signal.edge === "rising" && signal.active && (old ? !old.active : signal.notify_on_new)) {
            key = signal.dedupe_key;
        } else if (signal.edge === "falling" && old && old.active && !signal.active) {
            key = old.dedupe_key;
        }
        if (key) {
            events.push(Object.assign({kind: signal.kind, key}, message(signal, next.now)));
        }
    }
    return events;
}
