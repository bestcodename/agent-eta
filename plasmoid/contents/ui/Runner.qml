import QtQuick

import org.kde.plasma.plasma5support as Plasma5Support

// Runs shell commands through the executable data engine, which hands each one to /bin/sh -c.
// A command that is still running is not started again, so polls never overlap. One that has not
// answered within `timeout` milliseconds is given up, so a hung run cannot stop the polling.
Plasma5Support.DataSource {
    id: source

    property int timeout: 30000
    property var pending: ({})

    engine: "executable"
    connectedSources: []

    onNewData: (sourceName, data) => {
        const entry = pending[sourceName];
        delete pending[sourceName];
        disconnectSource(sourceName);
        if (entry && entry.callback) {
            entry.callback(data["exit code"], data["stdout"] || "", data["stderr"] || "");
        }
    }

    function run(command, callback) {
        const entry = pending[command];
        if (entry && Date.now() - entry.started < timeout) {
            return false;
        }
        if (entry) {
            disconnectSource(command);
        }
        pending[command] = {callback: callback || null, started: Date.now()};
        connectSource(command);
        return true;
    }

    // Starts a command that may outlive the call, such as an IDE, in its own session.
    function detach(command) {
        return run("setsid -f " + command + " >/dev/null 2>&1");
    }
}
