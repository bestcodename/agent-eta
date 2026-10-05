.pragma library
// State that every instance of the widget shares, since a .pragma library is loaded once per
// engine. Each panel has its own system tray and therefore its own instance, and both see the same
// transition, so the first one to claim an event's key notifies and the other stays quiet.

var claimed = {};

function claim(key, now) {
    if (claimed[key] !== undefined) {
        return false;
    }
    claimed[key] = now;
    for (var old in claimed) {
        if (now - claimed[old] > 86400) {
            delete claimed[old];
        }
    }
    return true;
}
