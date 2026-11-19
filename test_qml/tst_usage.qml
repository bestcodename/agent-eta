import QtQuick
import QtTest

import "../plasmoid/contents/ui" as UI
import "../plasmoid/contents/code/logic.mjs" as Logic

Item {
    id: root
    width: 800
    height: 400

    function i18n(text, a, b) { return text.replace("%1", a).replace("%2", b); }
    function i18nc(context, text) { return text; }

    Component { id: rowComponent; UI.UsageRow {} }
    Component { id: axisComponent; UI.UsageTimeAxis {} }
    Component { id: foldComponent; UI.FoldHeader {} }
    Component { id: signalSpy; SignalSpy {} }

    function named(item, name) {
        let found = item.objectName === name ? [item] : [];
        for (const child of item.children) found = found.concat(named(child, name));
        return found;
    }

    TestCase {
        name: "Usage"
        when: windowShown

        readonly property real end: new Date("2026-11-13T08:24:00+01:00").getTime() / 1000

        function test_a_fold_header_toggles_on_click_and_return() {
            const header = createTemporaryObject(foldComponent, root, {width: 400, text: "Usage (3)"});
            verify(header);
            const toggled = createTemporaryObject(signalSpy, root, {target: header, signalName: "foldRequested"});
            waitForRendering(header);
            mouseClick(header);
            compare(toggled.count, 1);
            header.forceActiveFocus();
            keyClick(Qt.Key_Return);
            compare(toggled.count, 2);
            const arrow = root.named(header, "foldArrow")[0];
            verify(arrow);
            compare(String(arrow.source), "go-down");
            header.collapsed = true;
            compare(String(arrow.source), "go-next");
        }

        function test_time_label_setting_loads_and_saves() {
            const component = Qt.createComponent("../plasmoid/contents/ui/configAppearance.qml");
            compare(component.status, Component.Ready, component.errorString());
            const settings = createTemporaryObject(component, root, {width: 500, height: 400,
                cfg_showUsage: true, cfg_showUsageTimeLabels: true});
            verify(settings);
            compare(settings.cfg_showUsageTimeLabels, true);
            settings.cfg_showUsageTimeLabels = false;
            compare(settings.cfg_showUsageTimeLabels, false);
            const checkbox = root.named(settings, "showUsageTimeLabels")[0];
            verify(checkbox);
            compare(checkbox.checked, false);
            checkbox.toggle();
            compare(settings.cfg_showUsageTimeLabels, true);
            settings.cfg_showUsage = false;
            compare(checkbox.enabled, false);
        }

        function test_each_settings_page_loads_and_saves_data() {
            return [
                {tag: "general", file: "configGeneral.qml", key: "cfg_pollOpen", first: 7, second: 9},
                {tag: "sessions", file: "configSessions.qml", key: "cfg_launchInCli", first: false, second: true},
                {tag: "appearance", file: "configAppearance.qml", key: "cfg_blendWidth", first: 30, second: 50},
                {tag: "notifications", file: "configNotifications.qml", key: "cfg_notifyReset", first: false, second: true}
            ];
        }
        function test_each_settings_page_loads_and_saves(data) {
            const component = Qt.createComponent("../plasmoid/contents/ui/" + data.file);
            compare(component.status, Component.Ready, component.errorString());
            const properties = {width: 500, height: 400, cfg_command: "agent-eta"};
            properties[data.key] = data.first;
            const settings = createTemporaryObject(component, root, properties);
            verify(settings);
            compare(settings[data.key], data.first);
            settings[data.key] = data.second;
            compare(settings[data.key], data.second);
        }

        function test_axis_labels_fit_actual_font_widths_data() {
            return [
                {tag: "narrow hours", minutes: 300, width: 180},
                {tag: "minimum popup days", minutes: 10080, width: 380},
                {tag: "wide days", minutes: 10080, width: 800}
            ];
        }
        function test_axis_labels_fit_actual_font_widths(data) {
            const axis = createTemporaryObject(axisComponent, root, {
                width: data.width, marks: Logic.windowTimeMarks({minutes: data.minutes, resets_at: end})});
            verify(axis);
            waitForRendering(axis);
            const labels = root.named(axis, "usageTimeLabel");
            verify(labels.length >= 2);
            for (let index = 0; index < labels.length; index++) {
                verify(labels[index].x >= 0);
                verify(labels[index].x + labels[index].width <= axis.width);
                if (index) verify(labels[index].x >= labels[index - 1].x + labels[index - 1].width);
            }
            verify(axis.implicitHeight > 0);
        }

        function test_row_setting_hides_axes_and_missing_deadlines_have_none() {
            const row = createTemporaryObject(rowComponent, root, {width: 380, now: end - 3600, group: {
                agent: "codex", account: null, reached: false, used: 40, resetBy: null,
                windows: [{minutes: 300, resets_at: end, used: 40, elapsed: 80, remaining: 3600},
                          {minutes: 10080, resets_at: null, used: null, elapsed: null, remaining: null}]}});
            verify(row);
            waitForRendering(row);
            const axes = root.named(row, "usageTimeAxis");
            compare(axes.length, 2);
            verify(axes[0].visible);
            verify(!axes[1].visible);
            row.timeLabels = false;
            tryVerify(() => !axes[0].visible);
            row.timeLabels = true;
            tryVerify(() => axes[0].visible);
            grabImage(row).save("/tmp/agent-eta-usage-labels.png");
        }

        function test_usage_rows_at_popup_widths_data() {
            return [{tag: "minimum", width: 380}, {tag: "normal", width: 500}, {tag: "wide", width: 900}];
        }
        function test_usage_rows_at_popup_widths(data) {
            const row = createTemporaryObject(rowComponent, root, {width: data.width, now: end - 14400, group: {
                agent: "codex", account: null, reached: false, used: 80, resetBy: null,
                windows: [{minutes: 300, resets_at: end, used: 80, elapsed: 20, remaining: 14400,
                           exhaustion: {state: "before_reset", at: end - 13500}},
                          {minutes: 10080, resets_at: end + 86400, used: 40, elapsed: 83.33, remaining: 100800,
                           exhaustion: {state: "until_reset", at: null}}]}});
            verify(row);
            waitForRendering(row);
            const axes = root.named(row, "usageTimeAxis");
            compare(axes.length, 2);
            for (const axis of axes) {
                verify(axis.visible);
                verify(axis.width <= row.width);
                verify(root.named(axis, "usageTimeLabel").length >= 2);
            }
            grabImage(row).save("/tmp/agent-eta-usage-labels-" + data.tag + ".png");
        }

        function test_estimates_stay_separate_from_resets_data() {
            return ["before_reset", "until_reset", "stale", "no_usage", "insufficient", "exhausted", "unavailable"]
                .map(state => ({tag: state, state: state}));
        }
        function test_estimates_stay_separate_from_resets(data) {
            const window = {minutes: 300, resets_at: end, used: 80, elapsed: 20, remaining: 14400,
                            exhaustion: {state: data.state, at: end - 13500}};
            const row = createTemporaryObject(rowComponent, root, {width: 380, now: end - 14400, group: {
                agent: "codex", account: null, reached: false, used: 80, resetBy: null, windows: [window]}});
            verify(row);
            waitForRendering(row);
            const estimate = root.named(row, "usageExhaustion")[0];
            const reset = root.named(row, "usageReset")[0];
            verify(estimate);
            verify(reset);
            compare(estimate.text, Logic.exhaustionShort(window, end - 14400));
            compare(estimate.Accessible.description, Logic.exhaustionText(window, end - 14400));
            verify(reset.text.indexOf("resets") >= 0);
            verify(estimate.text !== reset.text);
            // Both share the line above the bar, the estimate left of the reset and never over it.
            compare(estimate.mapToItem(row, 0, 0).y, reset.mapToItem(row, 0, 0).y);
            verify(estimate.mapToItem(row, 0, 0).x + estimate.width <= reset.mapToItem(row, 0, 0).x + 1);
            verify(reset.mapToItem(row, 0, 0).x + reset.width <= row.width + 1);
            verify(estimate.implicitHeight > 0);
        }
    }
}
