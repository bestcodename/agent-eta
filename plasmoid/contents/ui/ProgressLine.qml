import QtQuick

import org.kde.kirigami as Kirigami

// A thin bar. `value` fills it from 0 to 1, and `marker`, when 0 or more, draws a tick there, which
// the usage rows use for the share of the window that has passed. `bands`, from usageBands() in
// logic.mjs, colours the fill in traffic-light bands instead of the one `color`. They are painted as
// separate rectangles inside the rounded fill rather than as one gradient with a pair of stops at
// each edge, because QGradient replaces a stop that lands on the position of another one.
Item {
    id: line

    property real value: 0
    property real marker: -1
    property color color: Kirigami.Theme.highlightColor
    property var bands: []

    implicitHeight: Math.max(3, Math.round(Kirigami.Units.smallSpacing * 1.5))

    onValueChanged: banded.requestPaint()
    onBandsChanged: banded.requestPaint()

    Lights {
        id: lights
    }
    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: Kirigami.Theme.textColor
        opacity: 0.15
    }
    Rectangle {
        visible: line.bands.length === 0
        width: parent.width * Math.max(0, Math.min(1, line.value))
        height: parent.height
        radius: height / 2
        color: line.color
    }
    Canvas {
        id: banded

        anchors.fill: parent
        visible: line.bands.length > 0

        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onVisibleChanged: requestPaint()
        onPaint: {
            const ctx = getContext("2d");
            ctx.reset();
            const fill = width * Math.max(0, Math.min(1, line.value));
            if (!visible || fill <= 0) {
                return;
            }
            const x = percent => width * percent / 100;
            ctx.beginPath();
            ctx.roundedRect(0, 0, fill, height, height / 2, height / 2);
            ctx.clip();
            for (const band of line.bands) {
                if (band.stops) {
                    const first = band.stops[0][0];
                    const span = band.stops[band.stops.length - 1][0] - first;
                    const gradient = ctx.createLinearGradient(x(first), 0, x(first + span), 0);
                    for (const [at, light] of band.stops) {
                        gradient.addColorStop(span > 0 ? (at - first) / span : 0, lights.colorOf(light));
                    }
                    ctx.fillStyle = gradient;
                } else {
                    ctx.fillStyle = lights.colorOf(band.light);
                }
                // On to the end of the fill, under the next band. Two edges on the same fractional pixel
                // would each cover it only partly and let the track show through as a thin gap.
                ctx.fillRect(x(band.from), 0, fill - x(band.from), height);
            }
        }
    }
    Rectangle {
        visible: line.marker >= 0
        x: Math.round(parent.width * Math.min(1, line.marker)) - 1
        y: -2
        width: 2
        height: parent.height + 4
        color: Kirigami.Theme.textColor
    }
}
