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

    function named(item, name) {
        let found = item.objectName === name ? [item] : [];
        for (const child of item.children) found = found.concat(named(child, name));
        return found;
    }

    TestCase {
        name: "Usage"
        when: windowShown

        readonly property real end: new Date("2026-11-13T08:24:00+01:00").getTime() / 1000

        function test_time_label_setting_loads_and_saves() {
            const component = Qt.createComponent("../plasmoid/contents/ui/configGeneral.qml");
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
            compare(estimate.text, Logic.exhaustionText(window, end - 14400));
            verify(reset.text.indexOf("resets") >= 0);
            verify(estimate.text !== reset.text);
            verify(estimate.paintedWidth <= estimate.width + 1);
            verify(estimate.implicitHeight > 0);
        }
    }
}
