// Tests for the logic of the agent-eta tray widget.
//
// Run with:  node --test scripts/agent-eta/test_plasmoid.mjs
// test_plasmoid.py runs this file as well, so the Python suite covers it.

process.env.TZ = "Europe/Berlin";

import assert from "node:assert/strict";
import test from "node:test";

import * as logic from "./plasmoid/contents/code/logic.mjs";

const NOW = 1791162767;

function session(fields) {
    return Object.assign({
        agent: "claude", account: null, id: "s-1", pid: 100, name: "shop", state: "idle", waiting_for: null,
        since: NOW - 120, cwd: "/work/shop", due: null, remaining: null, overdue: false, eta_source: null,
        turn_label: null, dormant: false, section: 0, tasks: [], progress: null, eta_started: null, pids: [],
        project_root: "/work/shop", project_name: "shop",
    }, fields);
}

function listing(sessions, tasks = [], usage = []) {
    return {now: NOW, sessions, tasks, usage};
}

test("spans read like the REMAINING column", () => {
    for (const [seconds, text] of [[null, "?"], [30, "<1m"], [240, "4m"], [3900, "1h05"], [-720, "-12m"],
                                   [-30, "-0m"], [97200, "1d3h"]]) {
        assert.equal(logic.formatSpan(seconds), text);
    }
});

test("due times carry the date only when a day or more away", () => {
    const due = Date.UTC(2026, 9, 5, 19, 40) / 1000;
    assert.equal(logic.formatClock(due, due - 600), "21:40");
    assert.equal(logic.formatClock(due, due - 2 * 86400), "05.10. 21:40");
    assert.equal(logic.formatClock(null, NOW), "-");
    assert.equal(logic.formatWindow(300), "5h");
    assert.equal(logic.formatWindow(10080), "7d");
});

test("usage bars get a faint tick at every hour or day of the window", () => {
    assert.deepEqual(logic.windowTicks(300), [0.2, 0.4, 0.6, 0.8]);
    assert.deepEqual(logic.windowTicks(10080), [1, 2, 3, 4, 5, 6].map(day => day / 7));
    assert.equal(logic.windowTicks(1440).length, 23);
    assert.deepEqual(logic.windowTicks(60), []);
    for (const minutes of [90, 0, -300, null, undefined, 2.5]) {
        assert.deepEqual(logic.windowTicks(minutes), [], String(minutes));
    }
});

test("keys follow agent-eta's session_key", () => {
    assert.equal(logic.sessionKey(session({})), "claude:100");
    assert.equal(logic.sessionKey(session({agent: "codex", pid: null, id: "t-1"})), "codex:t-1");
    assert.equal(logic.sessionKey(session({agent: "local", pid: null, id: null, tasks: ["run-1"]})), "task:run-1");
});

test("rows say what is left, what ran over and where the session stands", () => {
    assert.equal(logic.etaText({due: NOW + 600, remaining: 600}), "10m left");
    assert.equal(logic.etaText({due: NOW - 180, remaining: -180}), "3m over");
    assert.equal(logic.etaText({state: "working", due: null}), "no ETA");
    assert.equal(logic.etaText({state: "idle", due: null}), "");
    const waiting = session({state: "waiting", waiting_for: "permission", account: "ndcnet"});
    assert.equal(logic.detailLine(waiting, NOW), "claude/ndcnet · shop · waiting (permission) for 2m (03:10)");
    const failed = session({agent: "dsh", account: null, model: "qwen3-coder", state: "waiting",
                            waiting_for: "turn failed (TIMEOUT)"});
    assert.equal(logic.detailLine(failed, NOW), "dsh · qwen3-coder · shop · waiting (turn failed (TIMEOUT)) for 2m (03:10)");
    assert.equal(logic.title(session({turn_label: "tests"})), "shop · tests");
});

test("each state gets a traffic-light colour and an overdue working session turns yellow", () => {
    for (const [state, light] of [["waiting", "red"], ["idle", "yellow"], ["working", "green"], ["stopped", "grey"],
                                  ["-", "grey"]]) {
        assert.equal(logic.stateLight(session({state})), light);
    }
    assert.equal(logic.stateLight(session({state: "working", overdue: true})), "yellow");
    assert.equal(logic.stateLight(session({state: "idle", tasks: ["wait"]})), "green");
    assert.equal(logic.stateLight(session({state: "idle", tasks: ["wait"], overdue: true})), "yellow");
});

test("countdowns read like `12h 13m` and follow the clock time of a reset", () => {
    for (const [seconds, text] of [[null, ""], [-5, ""], [0, "<1m"], [59, "<1m"], [2940, "49m"], [3600, "1h 0m"],
                                   [44_000, "12h 13m"], [183_600, "2d 3h"]]) {
        assert.equal(logic.formatIn(seconds), text);
    }
    const reset = Date.UTC(2026, 9, 5, 22, 0) / 1000;
    assert.equal(logic.resetText(reset, reset - 44_000), "in 12h 13m (00:00)");
    assert.equal(logic.resetText(reset, reset - 3 * 86400), "in 3d 0h (06.10. 00:00)");
    assert.equal(logic.resetText(reset, reset + 60), "00:00");
    assert.equal(logic.resetText(null, NOW), "-");
    assert.equal(logic.sinceText(NOW - 3900, NOW), "1h 5m (02:07)");
});

test("the tray orb is a traffic light over the sessions that are not dormant", () => {
    const orb = sessions => {
        const summary = logic.summary(listing(sessions));
        return [summary.light, summary.orbCount, summary.status];
    };
    assert.deepEqual(orb([]), ["none", 0, "passive"]);
    assert.deepEqual(orb([session({state: "idle", dormant: true, section: 3})]), ["none", 0, "passive"]);
    assert.deepEqual(orb([session({state: "working"})]), ["green", 0, "active"]);
    assert.deepEqual(orb([session({state: "stopped"})]), ["green", 0, "active"]);
    assert.deepEqual(orb([session({state: "idle", tasks: ["wait"]})]), ["green", 0, "active"]);
    assert.deepEqual(orb([session({state: "working", pid: 1}), session({state: "idle", pid: 2})]),
                     ["yellow", 1, "active"]);
    assert.deepEqual(orb([session({state: "working", overdue: true, pid: 1}), session({state: "idle", pid: 2})]),
                     ["yellow", 2, "active"]);
    assert.deepEqual(orb([session({state: "waiting", pid: 1}), session({state: "idle", pid: 2}),
                          session({state: "waiting", pid: 3})]), ["red", 2, "attention"]);
});

test("the summary counts what needs you and picks the soonest working ETA", () => {
    const data = listing([
        session({state: "waiting", pid: 1}),
        session({state: "working", pid: 2, due: NOW + 600, remaining: 600, progress: 0.5}),
        session({state: "working", pid: 3, due: NOW + 60, remaining: 60, progress: 0.9}),
        session({state: "working", pid: 4, tasks: ["late"]}),
        session({state: "idle", pid: 5, dormant: true, section: 3}),
    ], [{id: "late", overdue: true}]);
    const summary = logic.summary(data);
    assert.deepEqual([summary.waiting, summary.working, summary.overdue, summary.dormant, summary.attention],
                     [1, 3, 1, 1, 2]);
    assert.equal(summary.status, "attention");
    assert.equal(summary.next.pid, 3);
    assert.equal(summary.headline, "1 waiting · 1 overdue · 3 working");
    assert.equal(summary.light, "red");
    assert.equal(logic.summary(listing([session({state: "idle"})])).status, "active");
    assert.equal(logic.summary(null).status, "passive");
    assert.equal(logic.summary(null).headline, "No active agent sessions");
});

test("sessions group by their section and dormant ones only count unless shown", () => {
    const data = listing([
        session({state: "waiting", pid: 1, section: 0}),
        session({state: "working", pid: 2, section: 1, tasks: ["t"]}),
        session({state: "idle", pid: 3, section: 3, dormant: true}),
    ], [{id: "t", label: "tests"}]);
    const groups = logic.groupSessions(data, false);
    assert.deepEqual(groups.map(g => [g.title, g.count, g.sessions.length]),
                     [["Needs you", 1, 1], ["Working", 1, 1], ["Dormant", 1, 0]]);
    assert.equal(groups[1].sessions[0].taskItems[0].label, "tests");
    assert.equal(logic.groupSessions(data, true)[2].sessions.length, 1);
});

test("stopped and dormant sections retain counts and open independently", () => {
    const data = listing([
        session({pid: 1, section: 0, state: "waiting"}),
        session({pid: 2, section: 1, state: "working"}),
        session({pid: 3, section: 2, state: "stopped", tasks: ["blocked-task"]}),
        session({pid: 4, section: 3, dormant: true}),
    ], [{id: "blocked-task", label: "tests"}]);
    for (const [dormant, stopped, lengths] of [[false, false, [1, 1, 0, 0]], [true, false, [1, 1, 0, 1]],
                                             [false, true, [1, 1, 1, 0]], [true, true, [1, 1, 1, 1]]]) {
        const groups = logic.groupSessions(data, dormant, stopped);
        assert.deepEqual(groups.map(g => g.count), [1, 1, 1, 1]);
        assert.deepEqual(groups.map(g => g.sessions.length), lengths);
    }
    assert.equal(logic.groupSessions(data, false, true)[2].sessions[0].taskItems[0].label, "tests");
    data.sessions[2].section = 0;
    data.sessions[2].state = "idle";
    assert.deepEqual(logic.groupSessions(data, false).map(g => [g.section, g.sessions.length]), [[0, 2], [1, 1], [3, 0]]);
});

test("accounts without readings remain visible and authentication has its own status", () => {
    const accounts = [{id: "codex", agent: "codex", auth_state: "logged_out", usage_status: "unavailable"},
                      {id: "claude:work", agent: "claude/work", auth_state: "unknown", usage_status: "unavailable"}];
    const groups = logic.usageGroups([], accounts);
    assert.deepEqual(groups.map(g => [g.account.id, g.windows.length]), [["codex", 0], ["claude:work", 0]]);
    assert.equal(logic.usageHeadline(groups[0], NOW), "?");
    assert.equal(logic.accountStatus(accounts[0], NOW), "Not logged in");
    assert.equal(logic.accountStatus(accounts[1], NOW), "Authentication unknown · Usage unavailable");
    assert.match(logic.accountStatus({auth_state: "authenticated", usage_status: "stale", seen_at: NOW - 600}, NOW), /Stale reading · read 10m ago/);
});

test("the folder picker decodes local paths and rejects other URL types", () => {
    assert.equal(logic.folderPath("file:///home/me/a%20folder%20%24%28echo%20no%29"), "/home/me/a folder $(echo no)");
    assert.equal(logic.folderPath("file:///home/me/quote%27"), "/home/me/quote'");
    for (const url of ["https://example.org", "file://remote/home/me", "file:///bad%", ""]) {
        assert.equal(logic.folderPath(url), null);
    }
});

test("a recorded window ending with no new reading never promises unused quota", () => {
    const before = listing([], [], [{agent: "codex", minutes: 300, used: 100, reached: true, resets_at: NOW}]);
    const after = listing([], [], [{agent: "codex", minutes: 300, used: null, reached: false, resets_at: NOW}]);
    assert.equal(logic.transitions(before, after)[0].text,
                 "The recorded 5h window ended. A fresh usage reading is pending.");
});

test("usage groups put reached limits last and order windows by reset", () => {
    const groups = logic.usageGroups([
        {agent: "codex", minutes: 300, used: null, remaining: null, reached: false},
        {agent: "codex", minutes: 10080, used: 100, remaining: 259783, reached: true, ahead: true},
        {agent: "claude", minutes: 10080, used: 39, remaining: 380832, reached: false},
        {agent: "claude", minutes: 300, used: 39, remaining: 14232, reached: false, ahead: true},
    ]);
    assert.deepEqual(groups.map(g => [g.agent, g.reached, g.used]), [["claude", false, 39], ["codex", true, 100]]);
    assert.deepEqual(groups[0].windows.map(w => w.minutes), [300, 10080]);
    assert.equal(groups[0].resetBy.minutes, 300);
    assert.equal(groups[1].resetBy.minutes, 10080);
    assert.equal(groups[0].ahead, true);
});

test("usage groups sort open agents by the 7-day reset and blocked ones by the end of the block", () => {
    const groups = logic.usageGroups([
        {agent: "week-late", minutes: 300, used: 10, remaining: 100, reached: false},
        {agent: "week-late", minutes: 10080, used: 10, remaining: 9000, reached: false},
        {agent: "tie-late", minutes: 300, used: 10, remaining: 800, reached: false},
        {agent: "tie-late", minutes: 10080, used: 10, remaining: 5000, reached: false},
        {agent: "tie-soon", minutes: 300, used: 10, remaining: 700, reached: false},
        {agent: "tie-soon", minutes: 10080, used: 10, remaining: 5000, reached: false},
        {agent: "no-week", minutes: 300, used: 10, remaining: 50, reached: false},
        {agent: "week-blocked", minutes: 300, used: 100, remaining: 100, reached: true},
        {agent: "week-blocked", minutes: 10080, used: 100, remaining: 9000, reached: true},
        {agent: "unblocks-late", minutes: 300, used: 100, remaining: 3000, reached: true},
        {agent: "unblocks-late", minutes: 10080, used: 50, remaining: 4000, reached: false},
        {agent: "unblocks-soon", minutes: 300, used: 100, remaining: 100, reached: true},
        {agent: "unblocks-soon", minutes: 10080, used: 50, remaining: 8000, reached: false},
    ]);
    assert.deepEqual(groups.map(g => g.agent),
        ["tie-soon", "tie-late", "week-late", "no-week", "unblocks-soon", "unblocks-late", "week-blocked"]);
});

test("an agent's usage line names its highest share and its soonest reset", () => {
    const reset = NOW + 2940;
    const [open, blocked] = logic.usageGroups([
        {agent: "claude", minutes: 10080, used: 56, remaining: 380832, resets_at: NOW + 380832, reached: false},
        {agent: "claude", minutes: 300, used: 20, remaining: 2940, resets_at: reset, reached: false},
        {agent: "codex", minutes: 300, used: 100, remaining: 44_000, resets_at: NOW + 44_000, reached: true},
    ]);
    assert.equal(logic.usageHeadline(open, NOW), `56% · resets ${logic.resetText(reset, NOW)}`);
    assert.match(logic.usageHeadline(open, NOW), /^56% · resets in 49m \(/);
    assert.match(logic.usageHeadline(blocked, NOW), /^blocked · resets in 12h 13m \(/);
    const [stale] = logic.usageGroups([{agent: "codex", minutes: 300, used: null, remaining: null, reached: false}]);
    assert.equal(logic.usageHeadline(stale, NOW), "?");
});

function bands(window, fade, yellow = 1 / 3) {
    return logic.usageBands(Object.assign({reached: false}, window), fade, yellow)
        .map(each => [Math.round(each.from * 100) / 100, Math.round(each.to * 100) / 100, each.light]);
}

test("a usage bar is green up to the tick, yellow around it and red over the last two thirds past it", () => {
    assert.deepEqual(bands({used: 30, elapsed: 50}), [[0, 30, "green"]]);
    assert.deepEqual(bands({used: 50, elapsed: 50}), [[0, 50, "green"]]);
    assert.deepEqual(bands({used: 80, elapsed: 50}), [[0, 40, "green"], [40, 60, "yellow"], [60, 80, "red"]]);
    assert.deepEqual(bands({used: 80, elapsed: 10}), [[0, 33.33, "yellow"], [33.33, 80, "red"]]);
    assert.deepEqual(bands({used: 40, elapsed: 0}), [[0, 13.33, "yellow"], [13.33, 40, "red"]]);
});

test("a reached usage bar is yellow up to the tick and red from there", () => {
    assert.deepEqual(bands({used: 100, elapsed: 40, reached: true}), [[0, 40, "yellow"], [40, 100, "red"]]);
    assert.deepEqual(bands({used: 100, elapsed: 90, reached: true}), [[0, 90, "yellow"], [90, 100, "red"]]);
    assert.deepEqual(bands({used: 104, elapsed: 0, reached: true}), [[0, 100, "red"]]);
    assert.equal(logic.usageBands({used: 100, elapsed: 40, reached: true}, 1, 1 / 3).some(each => each.stops), false);
});

test("a usage bar without a known reset keeps one colour, and an empty one has no bands", () => {
    assert.deepEqual(bands({used: 70, elapsed: null}), [[0, 70, "green"]]);
    assert.deepEqual(bands({used: 100, elapsed: undefined, reached: true}), [[0, 100, "red"]]);
    assert.deepEqual(bands({used: 0, elapsed: 50}), []);
    assert.deepEqual(bands({used: null, elapsed: null}), []);
});

test("the yellow band's half-width is a share of the usage past the tick", () => {
    assert.deepEqual(logic.usageBands({used: 80, elapsed: 50, reached: false}),
                     logic.usageBands({used: 80, elapsed: 50, reached: false}, 0, 0.66));
    assert.deepEqual(bands({used: 80, elapsed: 50}, 0, 0.66), [[0, 30.2, "green"], [30.2, 69.8, "yellow"], [69.8, 80, "red"]]);
    assert.deepEqual(bands({used: 80, elapsed: 50}, 0), bands({used: 80, elapsed: 50}, 0, 1 / 3));
    assert.deepEqual(logic.usageBands({used: 80, elapsed: 50, reached: false}, 0, 0.5)
        .map(each => [each.from, each.to, each.light]), [[0, 35, "green"], [35, 65, "yellow"], [65, 80, "red"]]);
    assert.deepEqual(logic.usageBands({used: 80, elapsed: 50, reached: false}, 1, 0)
        .map(each => [each.from, each.to, each.light, Boolean(each.stops)]), [[0, 50, "green", false], [50, 80, "red", false]]);
    assert.deepEqual(logic.usageBands({used: 80, elapsed: 50, reached: false}, 0, 1)
        .map(each => [each.from, each.to, each.light]), [[0, 20, "green"], [20, 80, "yellow"]]);
    assert.deepEqual(logic.usageBands({used: 100, elapsed: 40, reached: true}, 0, 0.9)
        .map(each => [each.from, each.to, each.light]), [[0, 40, "yellow"], [40, 100, "red"]]);
});

test("the fade blends only the yellow band, over the share of each half it is given", () => {
    const hard = logic.usageBands({used: 80, elapsed: 50, reached: false}, 0, 1 / 3);
    assert.equal(hard.some(each => each.stops), false);
    const full = logic.usageBands({used: 80, elapsed: 50, reached: false}, 1, 1 / 3);
    assert.deepEqual(full.map(each => Boolean(each.stops)), [false, true, false]);
    assert.deepEqual(full[1].stops, [[40, "green"], [50, "yellow"], [50, "yellow"], [60, "red"]]);
    const half = logic.usageBands({used: 80, elapsed: 50, reached: false}, 0.5, 1 / 3);
    assert.deepEqual(half[1].stops, [[40, "green"], [45, "yellow"], [55, "yellow"], [60, "red"]]);
    const cut = logic.usageBands({used: 80, elapsed: 10, reached: false}, 1, 1 / 3);
    assert.equal(cut[0].from, 0);
    assert.equal(Math.round(cut[0].stops[0][0] * 100) / 100, -13.33);
});

test("the nearest window owner wins, and the project name picks among PhpStorm windows", () => {
    const windows = [
        {index: 0, pid: 55593, title: "sdwa5 – checkout.php"},
        {index: 1, pid: 55593, title: "ai – TODO.md"},
        {index: 2, pid: 900, title: "Konsole"},
    ];
    assert.equal(logic.pickWindow(windows, [791258, 2553840, 55593], "ai"), 1);
    assert.equal(logic.pickWindow(windows, [791258, 2553840, 55593], "sdwa5"), 0);
    assert.equal(logic.pickWindow(windows, [791258, 2553840, 55593], "other"), 0);
    assert.equal(logic.pickWindow(windows, [12, 900, 55593], "ai"), 2);
    assert.equal(logic.pickWindow(windows, [2491308, 2491283], "sdwa5"), -1);
    assert.equal(logic.pickWindow(windows, [], "ai"), -1);
});

test("quoting survives a quote in a path", () => {
    assert.equal(logic.shellQuote("it's here"), "'it'\\''s here'");
    assert.equal(logic.shellQuote("plain"), "'plain'");
});

test("copy gives a resume command for Claude Code and a thread link for Codex", () => {
    assert.equal(logic.resumeCommand(session({id: "abc", account: "ndcnet"})),
                 "cd '/work/shop' && claude-account run 'ndcnet' --resume 'abc'");
    assert.equal(logic.resumeCommand(session({id: "abc", cwd: null})), "claude --resume 'abc'");
    assert.equal(logic.resumeCommand(session({agent: "codex", id: "t-1"})), "codex://threads/t-1");
    assert.equal(logic.resumeCommand(session({agent: "local", id: null})), "");
    assert.equal(logic.resumeCommand(session({agent: "dsh", id: "session-1"})), "");
});

test("the tooltip escapes names and cuts off after the limit", () => {
    const data = listing([
        session({name: "<b>x</b>", state: "waiting", waiting_for: "permission"}),
        session({pid: 2, name: "two", state: "working", due: NOW + 600, remaining: 600}),
        session({pid: 3, name: "three"}),
        session({pid: 4, name: "old", dormant: true}),
    ]);
    assert.deepEqual(logic.tooltipLines(data, 2), [
        "<b>&lt;b&gt;x&lt;/b&gt;</b> · waiting (permission)",
        "<b>two</b> · working, 10m left",
        "… 1 more",
    ]);
});

test("transitions notify a new wait, an ETA that runs over and a reset limit, once each", () => {
    const before = listing(
        [session({state: "working", pid: 1}),
         session({state: "working", pid: 2, eta_source: "turn", due: NOW + 5, remaining: 5}),
         session({state: "working", pid: 3, eta_source: "tasks", due: NOW + 5, remaining: 5, tasks: ["t"]})],
        [{id: "t", label: "tests", overdue: false, due: NOW + 5}],
        [{agent: "codex", minutes: 10080, reached: true, resets_at: NOW}]);
    const after = listing(
        [session({state: "waiting", pid: 1, waiting_for: "permission"}),
         session({state: "working", pid: 2, eta_source: "turn", due: NOW + 5, remaining: -1, overdue: true}),
         session({state: "working", pid: 3, eta_source: "tasks", due: NOW + 5, remaining: -1, overdue: true,
                  tasks: ["t"]})],
        [{id: "t", label: "tests", overdue: true, due: NOW + 5, session_name: "shop"}],
        [{agent: "codex", minutes: 10080, reached: false, resets_at: NOW}]);
    const events = logic.transitions(before, after);
    assert.deepEqual(events.map(e => e.kind), ["waiting", "overdue", "overdue", "reset"]);
    assert.deepEqual(events.map(e => e.key), [
        `waiting:claude:1:${NOW - 120}`, `overdue:claude:2:${NOW + 5}`, `overdue:task:t:${NOW + 5}`,
        `reset:codex:10080:${NOW}`,
    ]);
    assert.equal(events[0].text, "claude needs you: permission");
    assert.deepEqual(logic.transitions(after, after), []);
    assert.deepEqual(logic.transitions(null, after), []);
});
