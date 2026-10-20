import QtQuick

import org.kde.plasma.plasma5support as Plasma5Support

// Runs shell commands through the executable data engine, which hands each one to /bin/sh -c.
// Every run gets a source of its own through an `AGENT_ETA_REQUEST=<n>` prefix, because the engine
// keys runs by their command text and a late answer to an abandoned run would otherwise reach the
// callback of the next one. A command that is still running is not started again, so polls never
// overlap. One that has not answered within `timeout` milliseconds is given up with exit code 124,
// so a hung run cannot stop the polling, and its answer is dropped should it still come.
Plasma5Support.DataSource {
    id: source

    property int timeout: 30000
    property int requests: 0
    // The source of each pending run by its command, and the run by its source.
    property var running: ({})
    property var pending: ({})

    engine: "executable"
    connectedSources: []

    onNewData: (sourceName, data) => {
        const entry = pending[sourceName];
        disconnectSource(sourceName);
        if (!entry) {
            return;
        }
        finish(sourceName);
        if (entry.callback) {
            entry.callback(data["exit code"], data["stdout"] || "", data["stderr"] || "");
        }
    }

    function finish(sourceName) {
        const entry = pending[sourceName];
        delete pending[sourceName];
        if (entry && running[entry.command] === sourceName) {
            delete running[entry.command];
        }
    }

    function run(command, callback) {
        const current = running[command];
        const entry = current ? pending[current] : null;
        if (entry && Date.now() - entry.started < timeout) {
            return false;
        }
        if (entry) {
            disconnectSource(current);
            finish(current);
            if (entry.callback) {
                entry.callback(124, "", "agent-eta did not answer within " + Math.round(timeout / 1000) + " s");
            }
        }
        requests += 1;
        const sourceName = "AGENT_ETA_REQUEST=" + requests + " " + command;
        pending[sourceName] = {command: command, callback: callback || null, started: Date.now()};
        running[command] = sourceName;
        connectSource(sourceName);
        return true;
    }

    // Starts a command that may outlive the call, such as an IDE, in its own session.
    function detach(command) {
        return run("setsid -f " + command + " >/dev/null 2>&1");
    }
}
