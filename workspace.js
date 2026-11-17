// One bounded kdotool invocation. Python supplies request as JSON before this file.
function identity(window) {
    return [String(window.desktopFileName || ""), String(window.resourceClass || ""),
        String(window.resourceName || ""), String(window.windowRole || ""), String(window.caption || "")];
}

function rectangle(value) {
    return [value.x, value.y, value.width, value.height];
}

function capture() {
    return {
        x11: workspace.supportInformation().indexOf("Operation Mode: X11") >= 0,
        desktops: workspace.desktops.map(desktop => ({id: desktop.id, name: desktop.name})),
        current: workspace.currentDesktop.id,
        active_output: workspace.activeScreen.name,
        outputs: workspace.screens.map(output => ({name: output.name,
            area: rectangle(workspace.clientArea(KWin.MaximizeArea, output, workspace.currentDesktop))})),
        windows: workspace.windowList().filter(window => window.normalWindow && !window.specialWindow)
            .map(window => ({id: String(window.internalId), identity: identity(window), pid: window.pid,
                desktops: window.desktops.map(desktop => desktop.name),
                all_desktops: window.onAllDesktops, output: window.output.name,
                geometry: rectangle(window.frameGeometry), tiled: !!window.tile || !!window.quickTileMode,
                movable: window.moveable, resizable: window.resizeable,
                state: {minimized: window.minimized, fullscreen: window.fullScreen,
                    maximize: Number(window.maximizeMode)}})),
    };
}

function apply() {
    const result = {created: [], applied: [], skipped: []};
    const actual = workspace.desktops.map(desktop => ({id: desktop.id, name: desktop.name}));
    if (JSON.stringify(actual) !== JSON.stringify(request.expected_desktops)) {
        throw new Error("Desktop topology changed. Preview again.");
    }
    for (const item of request.creates) {
        workspace.createDesktop(item.position, item.name);
        const created = workspace.desktops.filter(desktop => desktop.name === item.name);
        if (created.length !== 1) throw new Error("KWin refused desktop creation.");
        result.created.push(item.name);
    }
    for (const item of request.windows) {
        const windows = workspace.windowList().filter(window => String(window.internalId) === item.id);
        const window = windows.length === 1 ? windows[0] : null;
        if (!window || window.pid !== item.pid || JSON.stringify(identity(window)) !== JSON.stringify(item.identity)) {
            result.skipped.push({id: item.id, reason: "Window identity changed."});
            continue;
        }
        if (window.tile || window.quickTileMode || !window.moveable || !window.resizeable) {
            result.skipped.push({id: item.id, reason: "Window has tiling or geometry constraints."});
            continue;
        }
        const desktops = item.desktops.map(name => workspace.desktops.find(desktop => desktop.name === name));
        if (desktops.some(desktop => !desktop)) throw new Error("Target desktop disappeared.");
        try {
            // Clear geometry-owning states before restoring the normal rectangle.
            if (window.fullScreen) window.fullScreen = false;
            if (window.maximizeMode) window.setMaximize(false, false);
            window.frameGeometry = {x: item.geometry[0], y: item.geometry[1],
                width: item.geometry[2], height: item.geometry[3]};
            if (request.phase !== "geometry") {
                if (item.all_desktops) window.onAllDesktops = true;
                else window.desktops = desktops;
                if (item.state.maximize) window.setMaximize(!!(item.state.maximize & 1), !!(item.state.maximize & 2));
                if (window.fullScreen !== item.state.fullscreen) window.fullScreen = item.state.fullscreen;
                if (window.minimized !== item.state.minimized) window.minimized = item.state.minimized;
            }
            result.applied.push(item.id);
        } catch (error) {
            result.skipped.push({id: item.id, reason: String(error)});
        }
    }
    return result;
}

output_result(JSON.stringify(request.operation === "snapshot" ? capture() : apply()));
