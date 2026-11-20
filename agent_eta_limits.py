"""Usage limits: the cutoffs at which a usage window counts as blocked and the thresholds at which
sessions are handed over, per window and agent.

Both live in ~/.config/agent-eta/config.json, `usage_block` and `handoff`, in one shape:

    {"enabled": true, "five_hour_percent": 99, "weekly_percent": 99, "monthly_percent": 99,
     "agents": {"jetbrains": {"enabled": true, "monthly_percent": 97}}}

For each agent and window the agent's own value wins, then the section's, then BUILTIN. A value
must be a number from 1 to 100; anything else is ignored on read. An agent is enabled when both the
section and the agent are, each true by default. `agent-eta config get|set` reads and writes them,
the widget's Usage limits page runs the same commands, and bestcodename/ai's usage guard reads
`config get --json` for the Claude Code and JetBrains AI thresholds.
"""

import copy
import json
import math
import sys

import agent_eta_accounts as accounts_api

# The account PhpStorm's AI chats bill, the JetBrains AI quota.
JETBRAINS_ACCOUNT = "jetbrains-ai"
# A window's config key by its length in minutes.
WINDOW_KEYS = {300: "five_hour_percent", 10080: "weekly_percent", 43200: "monthly_percent"}
PERCENT_KEYS = tuple(WINDOW_KEYS.values())
# The windows each agent has.
AGENTS = {"claude": (300, 10080), "codex": (300, 10080), "jetbrains": (43200,)}
AGENT_NAMES = {"claude": "Claude Code", "codex": "Codex", "jetbrains": "JetBrains AI"}
# Below 100 a cutoff blocks an account that still has a sliver left, which no session can use anyway.
# The handoff values are those the usage guard used for Claude Code before 2.23.0.
BUILTIN = {
    "usage_block": {"enabled": True, "five_hour_percent": 99, "weekly_percent": 99, "monthly_percent": 99},
    "handoff": {"enabled": True, "five_hour_percent": 100, "weekly_percent": 98, "monthly_percent": 98},
}
SCHEMA = 1


class LimitError(Exception):
    pass


def valid_percent(value):
    """A number, not a bool, from 1 to 100."""
    return type(value) in (int, float) and math.isfinite(value) and 1 <= value <= 100


def agent_of(label):
    """The agent of a usage window's label: `codex` or `codex/*` is Codex, `*/jetbrains-ai` is
    JetBrains AI, and every other label is a Claude Code account."""
    label = label or ""
    if label == "codex" or label.startswith("codex/"):
        return "codex"
    if label.endswith("/" + JETBRAINS_ACCOUNT):
        return "jetbrains"
    return "claude"


def agent_keys(agent):
    return [WINDOW_KEYS[minutes] for minutes in AGENTS[agent]]


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _flag(value):
    return value if isinstance(value, bool) else True


def defaults(settings, section):
    """The section's own `enabled` and per-window values over BUILTIN."""
    raw = _mapping(settings.get(section))
    found = {"enabled": _flag(raw.get("enabled"))}
    for key in PERCENT_KEYS:
        found[key] = raw[key] if valid_percent(raw.get(key)) else BUILTIN[section][key]
    return found


def effective(settings, section):
    """Per agent, whether the section applies to it and its value for each of its windows."""
    section_values = defaults(settings, section)
    agents = _mapping(_mapping(settings.get(section)).get("agents"))
    found = {}
    for agent in AGENTS:
        own = _mapping(agents.get(agent))
        values = {"enabled": section_values["enabled"] and _flag(own.get("enabled"))}
        for key in agent_keys(agent):
            values[key] = own[key] if valid_percent(own.get(key)) else section_values[key]
        found[agent] = values
    return found


def block_at(settings):
    """A function from a usage window to its cutoff in percent, None when the agent's block is off or
    the window length is unknown, for agent_eta_model.usage_view()."""
    table = effective(settings, "usage_block")

    def cutoff(window):
        values = table[agent_of(window.get("agent"))]
        key = WINDOW_KEYS.get(window.get("minutes"))
        return values[key] if values["enabled"] and key in values else None

    return cutoff


def handoff_thresholds(settings, agent):
    """Whether handoffs apply to the agent and its threshold per window length in minutes."""
    values = effective(settings, "handoff")[agent]
    return values["enabled"], {minutes: values[WINDOW_KEYS[minutes]] for minutes in AGENTS[agent]}


def describe(settings):
    """What `config get --json` prints: the agents with their window keys, and per section the
    built-ins, the raw configured section, the section's own values and every agent's effective ones."""
    found = {"schema": SCHEMA, "agents": {agent: agent_keys(agent) for agent in AGENTS}, "names": dict(AGENT_NAMES)}
    for section in BUILTIN:
        found[section] = {"builtin": dict(BUILTIN[section]), "configured": _mapping(settings.get(section)),
                          "defaults": defaults(settings, section), "effective": effective(settings, section)}
    return found


def parse_value(pair, field, text):
    if field == "enabled":
        if text not in ("true", "false"):
            raise LimitError("%s: enabled takes true, false or default" % pair)
        return text == "true"
    try:
        number = float(text)
    except ValueError:
        number = math.nan
    if not valid_percent(number):
        raise LimitError("%s: a percent is a number from 1 to 100, or default" % pair)
    return int(number) if number.is_integer() else number


def apply(settings, pairs):
    """The settings with each `KEY=VALUE` pair applied in order, where KEY is `<section>[.<field>]` or
    `<section>.agents.<agent>[.<field>]`. VALUE `default` deletes the key, the agent or the section and
    prunes what became empty. Raises LimitError on the first bad pair, and the input stays unchanged."""
    result = copy.deepcopy(settings)
    for pair in pairs:
        key, sep, text = pair.partition("=")
        if not sep:
            raise LimitError("%s: expected KEY=VALUE" % pair)
        parts = key.split(".")
        section, rest = parts[0], parts[1:]
        if section not in BUILTIN:
            raise LimitError("%s: unknown section %r, use %s" % (pair, section, " or ".join(BUILTIN)))
        agent = None
        if rest[:1] == ["agents"]:
            if len(rest) < 2 or rest[1] not in AGENTS:
                raise LimitError("%s: name an agent, one of %s" % (pair, ", ".join(AGENTS)))
            agent, rest = rest[1], rest[2:]
        allowed = ("enabled",) + tuple(agent_keys(agent) if agent else PERCENT_KEYS)
        if len(rest) > 1 or (rest and rest[0] not in allowed):
            raise LimitError("%s: unknown field, %s takes %s" % (pair, agent or section, ", ".join(allowed)))
        field = rest[0] if rest else None
        if text == "default":
            reset(result, section, agent, field)
            continue
        if field is None:
            raise LimitError("%s: only default applies to a whole %s" % (pair, "agent" if agent else "section"))
        value = parse_value(pair, field, text)
        target = _child(result, section)
        if agent:
            target = _child(_child(target, "agents"), agent)
        target[field] = value
    return result


def _child(parent, key):
    if not isinstance(parent.get(key), dict):
        parent[key] = {}
    return parent[key]


def reset(settings, section, agent, field):
    """Delete a field, an agent or a section, and prune what became empty."""
    raw = settings.get(section)
    if not isinstance(raw, dict) or (agent is None and field is None):
        settings.pop(section, None)
        return
    if agent is None:
        raw.pop(field, None)
    else:
        agents = raw.get("agents")
        if isinstance(agents, dict):
            own = agents.get(agent)
            if field is None or not isinstance(own, dict):
                agents.pop(agent, None)
            else:
                own.pop(field, None)
                if not own:
                    agents.pop(agent)
            if not agents:
                raw.pop("agents")
    if not raw:
        settings.pop(section)


def _percent(value):
    return "-" if value is None else "%g%%" % value


def table(described):
    """The human `config get`: per section a default row and one row per agent."""
    rows = [("SETTING", "AGENT", "ON", "5H", "7D", "30D")]
    for section in BUILTIN:
        values = described[section]["defaults"]
        rows.append((section, "default", "on" if values["enabled"] else "off")
                    + tuple(_percent(values[key]) for key in PERCENT_KEYS))
        for agent, values in described[section]["effective"].items():
            rows.append((section, AGENT_NAMES[agent], "on" if values["enabled"] else "off")
                        + tuple(_percent(values.get(key)) for key in PERCENT_KEYS))
    widths = [max(len(row[column]) for row in rows) for column in range(len(rows[0]))]
    return "\n".join("  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip() for row in rows)


def config_action(args):
    store = accounts_api.AccountStore()
    if args.config_action == "get":
        described = describe(store.settings())
        print(json.dumps(described, indent=2, sort_keys=True) if args.json else table(described))
        return 0

    def change(data):
        updated = apply(data, args.pairs)
        data.clear()
        data.update(updated)

    try:
        store.configure(change)
    except LimitError as exc:
        print("agent-eta config: %s" % exc, file=sys.stderr)
        return 2
    return 0


def add_parser(sub):
    parser = sub.add_parser("config", help="usage block cutoffs and handoff thresholds per window and agent")
    actions = parser.add_subparsers(dest="config_action", required=True)
    get = actions.add_parser("get", help="show the effective values")
    get.add_argument("--json", action="store_true")
    put = actions.add_parser("set", help="change values, e.g. handoff.agents.codex.five_hour_percent=90; "
                                         "VALUE default removes a key, an agent or a section")
    put.add_argument("pairs", nargs="+", metavar="KEY=VALUE")
