// What the agent-eta tray widget shows, computed from `agent-eta list --json --all`.
//
// Pure functions without QML, so `node --test` covers them (scripts/agent-eta/test_plasmoid.mjs).
// The order of the sessions and their section come from agent-eta itself, so nothing here sorts
// sessions. See docs/agent-eta.md, section "Tray widget".

export const SECTION_TITLES = ["Needs you", "Working", "Stopped until a limit resets", "Dormant"];
export const DORMANT_SECTION = 3;

// The traffic-light colour of a session state. A coloured dot rather than a media icon, because a
// play or pause symbol reads as a button that starts or stops the session. StateDot.qml maps the
// names to theme colours.
const STATE_LIGHTS = {
    waiting: "red",
    idle: "yellow",
    working: "green",
    stopped: "grey",
};

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

export function percent(value) {
    return value === null || value === undefined ? "?" : `${Math.round(value)}%`;
}

// A key that stays the same across polls. Claude Code sessions keep their pid through a /clear,
// as in agent-eta's session_key(), Codex threads their id, and a lone task its id.
export function sessionKey(session) {
    if (session.agent === "claude" && session.pid) {
        return `claude:${session.pid}`;
    }
    if (session.id) {
        return `${session.agent}:${session.id}`;
    }
    return `task:${(session.tasks || [])[0]}`;
}

export function agentLabel(session) {
    return session.account ? `${session.agent}/${session.account}` : session.agent || "-";
}

// A working session past its ETA turns yellow, like the tray orb counts it.
export function stateLight(session) {
    if (session.overdue && session.state === "working") {
        return "yellow";
    }
    return STATE_LIGHTS[session.state] || "grey";
}

export function title(session) {
    return session.turn_label ? `${session.name} · ${session.turn_label}` : session.name || "-";
}

// The right-hand text of a row: how long is left, how far it ran over, or nothing.
export function etaText(item) {
    if (item.due) {
        return item.remaining < 0 ? `${formatSpan(-item.remaining)} over` : `${formatSpan(item.remaining)} left`;
    }
    return item.state === "working" ? "no ETA" : "";
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
    let state = session.state;
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
    return parts.join(" · ");
}

function sessionsOf(listing) {
    return (listing && listing.sessions) || [];
}

function late(session, tasksById) {
    return session.overdue || (session.tasks || []).some(id => tasksById[id] && tasksById[id].overdue);
}

function tasksById(listing) {
    const found = {};
    for (const task of (listing && listing.tasks) || []) {
        found[task.id] = task;
    }
    return found;
}

// Counts, the tray state and the session whose progress the tray icon shows. `attention` counts the
// sessions that need you now, which are the waiting ones and the working ones that ran over.
//
// `light` is the tray orb, a traffic light over the sessions that are not dormant. Red with the
// number of waiting sessions as soon as one waits, yellow with the number of idle and overdue ones,
// green without a number while everything else works or waits for a limit, and "none" without any
// such session. Only red marks the widget as needing attention, which makes the tray pulse.
export function summary(listing) {
    const byId = tasksById(listing);
    const live = sessionsOf(listing).filter(session => !session.dormant);
    const count = state => live.filter(session => session.state === state).length;
    const overdue = live.filter(session => session.state === "working" && late(session, byId)).length;
    const waiting = count("waiting");
    const timed = live.filter(session => session.state === "working" && session.progress !== null
                              && session.progress !== undefined);
    timed.sort((a, b) => a.remaining - b.remaining);
    const result = {
        waiting,
        working: count("working"),
        idle: count("idle"),
        stopped: count("stopped"),
        overdue,
        dormant: sessionsOf(listing).length - live.length,
        attention: waiting + overdue,
        next: timed.length ? timed[0] : null,
    };
    if (waiting) {
        result.light = "red";
        result.orbCount = waiting;
    } else if (result.idle || overdue) {
        result.light = "yellow";
        result.orbCount = result.idle + overdue;
    } else {
        result.light = live.length ? "green" : "none";
        result.orbCount = 0;
    }
    result.status = result.light === "red" ? "attention" : live.length ? "active" : "passive";
    const parts = [];
    for (const name of ["waiting", "overdue", "working", "idle", "stopped"]) {
        if (result[name]) {
            parts.push(`${result[name]} ${name}`);
        }
    }
    result.headline = parts.length ? parts.join(" · ") : "No active agent sessions";
    return result;
}

// The sessions by section, each with its task objects as `taskItems`. A dormant section only
// lists its sessions when asked to, and otherwise only counts them.
export function groupSessions(listing, showDormant) {
    const byId = tasksById(listing);
    const groups = SECTION_TITLES.map((name, section) => ({section, title: name, count: 0, sessions: []}));
    for (const session of sessionsOf(listing)) {
        const group = groups[session.section] || groups[session.dormant ? DORMANT_SECTION : 0];
        group.count += 1;
        if (group.section !== DORMANT_SECTION || showDormant) {
            group.sessions.push(Object.assign({}, session, {
                taskItems: (session.tasks || []).map(id => byId[id]).filter(Boolean),
            }));
        }
    }
    return groups.filter(group => group.count > 0);
}

// The window lengths in minutes that order the agents, the 7-day window deciding before the 5-hour one.
const USAGE_SORT_WINDOWS = [10080, 300];

function untilReset(window) {
    return !window || window.remaining === null || window.remaining === undefined ? Infinity : window.remaining;
}

function compareAgents(a, b) {
    for (const minutes of USAGE_SORT_WINDOWS) {
        const left = untilReset(a.windows.find(window => window.minutes === minutes));
        const right = untilReset(b.windows.find(window => window.minutes === minutes));
        if (left !== right) {
            return left < right ? -1 : 1;
        }
    }
    return 0;
}

// The usage windows per agent, as agent-eta's usage table orders them. Agents with room left come
// first, by the reset of the 7-day window and then by that of the 5-hour window, and those with a
// reached limit last, by the reset that ends their block, the soonest first in both.
export function usageGroups(usage) {
    const byAgent = new Map();
    for (const window of usage || []) {
        if (!byAgent.has(window.agent)) {
            byAgent.set(window.agent, []);
        }
        byAgent.get(window.agent).push(window);
    }
    const groups = [];
    for (const [agent, windows] of byAgent) {
        windows.sort((a, b) => untilReset(a) - untilReset(b));
        const reached = windows.filter(window => window.reached);
        const known = windows.filter(window => window.used !== null && window.used !== undefined);
        const resetBy = reached.length
            ? reached.reduce((last, window) => (untilReset(window) > untilReset(last) ? window : last))
            : windows[0];
        groups.push({
            agent,
            windows,
            reached: reached.length > 0,
            ahead: windows.some(window => window.ahead),
            used: known.length ? Math.max(...known.map(window => window.used)) : null,
            resetBy,
        });
    }
    groups.sort((a, b) => (a.reached - b.reached)
        || (a.reached ? untilReset(a.resetBy) - untilReset(b.resetBy) : 0)
        || compareAgents(a, b));
    return groups;
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
    if (group.reached) {
        return `blocked · resets ${resetText(group.resetBy.resets_at, now)}`;
    }
    const next = group.resetBy;
    return next && untilReset(next) !== Infinity
        ? `${percent(group.used)} · resets ${resetText(next.resets_at, now)}`
        : percent(group.used);
}

function titleProject(title) {
    return String(title || "").split(" – ")[0].trim();
}

// The window to raise for a session, as an index into `windows` ({index, pid, title}), or -1. The
// nearest process in the session's lineage that owns a window wins. One PhpStorm process owns every
// project window, so among its windows the one whose title starts with the project name wins.
export function pickWindow(windows, pids, projectName) {
    for (const pid of pids || []) {
        const owned = (windows || []).filter(window => window.pid === pid);
        if (!owned.length) {
            continue;
        }
        const named = projectName
            ? owned.find(window => titleProject(window.title) === projectName)
                || owned.find(window => String(window.title || "").includes(projectName))
            : null;
        return (named || owned[0]).index;
    }
    return -1;
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
        const detail = [session.state + (session.waiting_for ? ` (${session.waiting_for})` : "")];
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

// The events worth a notification between two polls, each with a key that is the same for every
// widget instance, so two trays notify once. The first poll has nothing to compare with.
export function transitions(previous, next) {
    if (!previous || !next) {
        return [];
    }
    const events = [];
    const before = new Map(sessionsOf(previous).map(session => [sessionKey(session), session]));
    for (const session of sessionsOf(next)) {
        if (session.dormant) {
            continue;
        }
        const key = sessionKey(session);
        const old = before.get(key);
        if (session.state === "waiting" && (!old || old.state !== "waiting")) {
            events.push({
                kind: "waiting", key: `waiting:${key}:${session.since}`,
                title: `${session.name} is waiting`,
                text: `${agentLabel(session)} needs you: ${session.waiting_for || "input"}`,
            });
        }
        // A session whose ETA comes from its tasks runs over with them, and the task says which.
        if (session.overdue && old && !old.overdue && session.eta_source !== "tasks"
                && session.state === "working") {
            events.push({
                kind: "overdue", key: `overdue:${key}:${session.due}`,
                title: `${session.name} is overdue`,
                text: session.turn_label ? `${session.turn_label} was due ${formatClock(session.due, next.now)}`
                    : `It was due ${formatClock(session.due, next.now)}`,
            });
        }
    }
    const oldTasks = tasksById(previous);
    for (const task of (next.tasks || [])) {
        const old = oldTasks[task.id];
        if (task.overdue && old && !old.overdue) {
            events.push({
                kind: "overdue", key: `overdue:task:${task.id}:${task.due}`,
                title: `${task.label || "A task"} is overdue`,
                text: `${task.session_name || task.agent} expected it at ${formatClock(task.due, next.now)}`,
            });
        }
    }
    const oldWindows = new Map((previous.usage || []).map(window => [`${window.agent}:${window.minutes}`, window]));
    for (const window of (next.usage || [])) {
        const old = oldWindows.get(`${window.agent}:${window.minutes}`);
        if (old && old.reached && !window.reached) {
            events.push({
                kind: "reset", key: `reset:${window.agent}:${window.minutes}:${old.resets_at}`,
                title: `${window.agent} usage limit reset`,
                text: `The ${formatWindow(window.minutes)} window has room again`,
            });
        }
    }
    return events;
}
