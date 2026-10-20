// Tests for the logic of the agent-eta tray widget.
//
// Run with:  node --test --test-isolation=none test_plasmoid.mjs
// test_install.py runs this file as well, so the Python suite covers it.

process.env.TZ = "Europe/Berlin";

import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
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

// A contract listing agent-eta's model wrote, see test_model.py.
function fixture(name) {
    return JSON.parse(readFileSync(new URL(`./test_fixtures/contract-v1/${name}.json`, import.meta.url), "utf8"));
}

function find(data, key) {
    return data.sessions.find(session => session.key === key);
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

test("the folder picker decodes local paths and rejects other URL types", () => {
    assert.equal(logic.folderPath("file:///home/me/a%20folder%20%24%28echo%20no%29"), "/home/me/a folder $(echo no)");
    assert.equal(logic.folderPath("file:///home/me/quote%27"), "/home/me/quote'");
    for (const url of ["https://example.org", "file://remote/home/me", "file:///bad%", ""]) {
        assert.equal(logic.folderPath(url), null);
    }
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

test("the caption titles agent-eta tab reports pick among the windows of one Konsole process", () => {
    const windows = [
        {index: 0, pid: 58086, title: "sec"},
        {index: 1, pid: 58086, title: "Handoff 3d"},
        {index: 2, pid: 58086, title: "Handoff 3d (2)"},
    ];
    const pids = [58107, 58086];
    assert.equal(logic.pickWindow(windows, pids, "stefanr", ["Handoff 3d", "Handoff 3d"]), 1);
    assert.equal(logic.pickWindow(windows, pids, "stefanr", ["sec", "sec"]), 0);
    assert.equal(logic.pickWindow(windows, pids, "stefanr", ["gone", "Handoff 3d (2)"]), 2);
    assert.equal(logic.pickWindow([{index: 0, pid: 58086, title: "sec"},
        {index: 1, pid: 58086, title: "Handoff 3d — Konsole"}], pids, "", ["Handoff 3d"]), 1);
    assert.equal(logic.pickWindow(windows, pids, "stefanr", ["Handoff"]), 0);
    assert.equal(logic.pickWindow(windows, pids, "stefanr", []), 0);
    assert.equal(logic.pickWindow(windows, pids, "stefanr"), 0);
    assert.equal(logic.pickWindow(windows, pids, "sec", ["", null]), 0);
});

test("the tab call takes only real pids and its output only on success", () => {
    assert.equal(logic.tabCommand("agent-eta", [58107, 58086]), "agent-eta tab 58107 58086");
    assert.equal(logic.tabCommand("agent-eta", [0, -1, "1; rm", 1.5, 42]), "agent-eta tab 42");
    assert.equal(logic.tabCommand("agent-eta", []), "");
    assert.equal(logic.tabCommand("agent-eta", undefined), "");
    assert.deepEqual(logic.tabTitles(0, '{"window": "/Windows/3", "titles": ["sec", "Handoff 3d"]}\n'),
        ["sec", "Handoff 3d"]);
    assert.deepEqual(logic.tabTitles(1, '{"titles": ["sec"]}'), []);
    assert.deepEqual(logic.tabTitles(0, "garbage"), []);
    assert.deepEqual(logic.tabTitles(0, '{"titles": "sec"}'), []);
    assert.deepEqual(logic.tabTitles(0, '{"titles": ["", 3, "sec"]}'), ["sec"]);
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

test("only a listing of contract 1 passes, and an older CLI is told to update", () => {
    const mixed = fixture("mixed");
    assert.equal(logic.validateListing(JSON.stringify(mixed)).listing.now, mixed.now);
    assert.equal(logic.validateListing(mixed).error, "");
    const {schema_version: _, ...old} = mixed;
    assert.equal(logic.validateListing(JSON.stringify(old)).error, "agent-eta CLI too old, update it");
    assert.match(logic.validateListing(Object.assign({}, mixed, {schema_version: 2})).error, /reads 1\. Update the widget/);
    assert.equal(logic.validateListing("{oops").error, "agent-eta printed no valid JSON");
    assert.equal(logic.validateListing("[]").error, "agent-eta printed no listing");
    assert.equal(logic.validateListing(Object.assign({}, mixed, {sections: null})).error, "agent-eta listing lacks sections");
    assert.match(logic.validateListing(Object.assign({}, mixed, {summary: []})).error, /lacks now, summary or labels/);
});

test("rows show agent-eta's activity labels and lights", () => {
    const mixed = fixture("mixed");
    const question = find(mixed, "codex:s-t-1");
    assert.equal(logic.stateLabel(question), "working, question open");
    assert.equal(logic.stateLight(question), "red");
    assert.match(logic.detailLine(question, mixed.now), /working, question open \(question\)/);
    const owner = find(mixed, "claude:1");
    assert.deepEqual([owner.state, logic.stateLabel(owner), logic.stateLight(owner)], ["idle", "working", "green"]);
    assert.equal(logic.etaText(owner), "8m left");
    assert.equal(logic.stateLight(find(mixed, "claude:2")), "yellow");
    assert.equal(logic.stateLight(find(mixed, "task:reminder")), "grey");
    assert.equal(logic.stateLight({}), "grey");
});

test("the tray summary is agent-eta's, with the orb colour and the progress session", () => {
    const summary = logic.summary(fixture("mixed"));
    assert.deepEqual([summary.waiting, summary.working, summary.overdue, summary.dormant, summary.attention],
                     [2, 2, 1, 1, 3]);
    assert.deepEqual([summary.light, summary.orbCount, summary.status], ["red", 2, "attention"]);
    assert.equal(summary.next.key, "claude:2");
    assert.equal(summary.headline, "2 waiting · 1 overdue · 2 working · 1 idle · 1 stopped");
    const empty = logic.summary(fixture("empty"));
    assert.deepEqual([empty.light, empty.orbCount, empty.status, empty.next], ["none", 0, "passive", null]);
    assert.equal(logic.summary(null).headline, "No active agent sessions");
});

test("sections come in agent-eta's order, and stopped and dormant ones open independently", () => {
    const mixed = fixture("mixed");
    for (const [dormant, stopped, lengths] of [[false, false, [4, 2, 0, 0]], [true, false, [4, 2, 0, 1]],
                                             [false, true, [4, 2, 1, 0]], [true, true, [4, 2, 1, 1]]]) {
        const groups = logic.groupSessions(mixed, dormant, stopped);
        assert.deepEqual(groups.map(g => [g.title, g.count]),
                         [["Needs you", 4], ["Working", 2], ["Stopped until a limit resets", 1], ["Dormant", 1]]);
        assert.deepEqual(groups.map(g => g.sessions.length), lengths);
    }
    const [needs, working] = logic.groupSessions(mixed, false);
    assert.deepEqual(needs.sessions.map(s => s.key), ["codex:s-t-1", "claude:3", "task:reminder", "claude:4"]);
    assert.equal(working.sessions[1].taskItems[0].id, "build");
    assert.deepEqual(logic.groupSessions(fixture("empty"), true, true), []);
});

test("usage groups resolve agent-eta's window and account keys", () => {
    const mixed = fixture("mixed");
    const groups = logic.usageGroups(mixed);
    assert.deepEqual(groups.map(g => [g.agent, g.reached, g.windows.map(w => w.minutes), g.resetBy.minutes]),
                     [["claude", false, [300, 10080], 300], ["claude/work", false, [300], 300],
                      ["codex", true, [300, 10080], 300]]);
    assert.equal(groups[1].account.id, "claude:work");
    assert.equal(logic.accountStatus(groups[1].account, mixed.now), "Authentication unknown · Stale reading · read 2h 0m ago");
    assert.match(logic.usageHeadline(groups[0], mixed.now), /^55% · resets in 50m \(/);
    assert.match(logic.usageHeadline(groups[2], mixed.now), /^blocked · resets in 20m \(/);
    assert.equal(logic.usageHeadline({reached: false, used: null, resetBy: null, windows: []}, mixed.now), "?");
    assert.equal(logic.accountStatus({auth_state: "logged_out"}, NOW), "Not logged in");
});

test("signals notify a new wait, an ETA that ran over and a reset limit, once each", () => {
    const before = fixture("signals-before");
    const after = fixture("signals-after");
    const events = logic.signalEvents(before, after);
    assert.deepEqual(events.map(e => [e.kind, e.key]), [
        ["waiting", "waiting:claude:3:1760000115"], ["waiting", "waiting:claude:6:1760000117"],
        ["overdue", "overdue:claude:2:1760000030"], ["overdue", "overdue:task:ci:1760000100"],
        ["reset", "reset:window:codex:300:1760000060"],
    ]);
    assert.equal(events[0].title, "asks soon is waiting");
    assert.equal(events[0].text, "claude needs you: question");
    assert.match(events[2].text, /^It was due /);
    assert.match(events[3].text, /^ci expected it at /);
    assert.equal(events[4].text, "The recorded 5h window ended. A fresh usage reading is pending.");
    assert.deepEqual(logic.signalEvents(after, after), []);
    assert.deepEqual(logic.signalEvents(null, after), []);
});

test("the tooltip escapes names, uses the activity label and cuts off after the limit", () => {
    const mixed = fixture("mixed");
    mixed.sessions[0].name = "<b>x</b>";
    const lines = logic.tooltipLines(mixed, 2);
    assert.deepEqual(lines, [
        "<b>&lt;b&gt;x&lt;/b&gt;</b> · working, question open (question)",
        "<b>permission</b> · waiting (permission)",
        "… 5 more",
    ]);
});

test("the dormant threshold reads in whole hours", () => {
    assert.equal(logic.formatDuration(fixture("mixed").labels.dormant_after), "2 hours");
    assert.equal(logic.formatDuration(3600), "1 hour");
    assert.equal(logic.formatDuration(5400), "1h 30m");
});

test("handoff entries name the other provider and why a session cannot move", () => {
    const claude = {agent: "claude", id: "s'1", handoff: {available: true, reason: null, targets: ["codex", "claude"], status: null}};
    assert.deepEqual(logic.handoffAction(claude, "agent-eta"),
        {text: "Hand off to Codex", enabled: true, command: "agent-eta handoff 'claude:s'\\''1' --to codex"});
    const desktop = {agent: "codex", id: "t1", handoff: {available: false, reason: "desktop chats cannot be gated", targets: ["claude"], status: null}};
    assert.deepEqual(logic.handoffAction(desktop, "agent-eta").text, "Hand off to Claude Code (desktop chats cannot be gated)");
    assert.equal(logic.handoffAction(desktop, "agent-eta").enabled, false);
    assert.equal(logic.handoffAction({agent: "dsh", handoff: {available: false, targets: []}}, "agent-eta"), null);
});

test("rows show a pending or failed handoff and forget a completed one", () => {
    const at = (state, error) => ({agent: "claude", state: "idle", handoff: {status: {state, target: "codex", error}}});
    assert.equal(logic.handoffText(at("launched")), "handoff to Codex pending");
    assert.equal(logic.handoffText(at("failed", "did not register")), "handoff to Codex failed: did not register");
    assert.equal(logic.handoffText(at("completed")), "");
    assert.match(logic.detailLine(at("waiting"), 0), /handoff to Codex pending$/);
});
