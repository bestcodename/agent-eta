"""Tests for agent_eta_limits: resolving the usage block cutoffs and handoff thresholds, changing
them with `config set`, and `config get`."""

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

import agent_eta_limits as limits

_SRC = pathlib.Path(__file__).with_name("agent-eta")
_spec = importlib.util.spec_from_loader("agent_eta_cli", importlib.machinery.SourceFileLoader("agent_eta_cli", str(_SRC)))
eta = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eta)


class Resolve(unittest.TestCase):
    def test_a_missing_config_gives_the_builtins(self):
        block = limits.effective({}, "usage_block")
        handoff = limits.effective({}, "handoff")
        self.assertEqual(block["claude"], {"enabled": True, "five_hour_percent": 99, "weekly_percent": 99})
        self.assertEqual(block["jetbrains"], {"enabled": True, "monthly_percent": 99})
        self.assertEqual(handoff["codex"], {"enabled": True, "five_hour_percent": 100, "weekly_percent": 98})
        self.assertEqual(handoff["jetbrains"], {"enabled": True, "monthly_percent": 98})

    def test_invalid_values_are_ignored_per_key(self):
        for bad in (True, "90", 0, 101, float("nan"), None, [90]):
            settings = {"usage_block": {"five_hour_percent": bad, "weekly_percent": 95, "enabled": "no"}}
            claude = limits.effective(settings, "usage_block")["claude"]
            self.assertEqual(claude, {"enabled": True, "five_hour_percent": 99, "weekly_percent": 95}, bad)

    def test_the_agent_beats_the_section_and_the_section_the_builtin(self):
        settings = {"handoff": {"five_hour_percent": 95, "agents": {"codex": {"five_hour_percent": 90}}}}
        handoff = limits.effective(settings, "handoff")
        self.assertEqual(handoff["codex"]["five_hour_percent"], 90)
        self.assertEqual(handoff["claude"]["five_hour_percent"], 95)
        self.assertEqual(handoff["claude"]["weekly_percent"], 98)

    def test_an_agent_switch_disables_only_that_agent_and_the_master_all(self):
        settings = {"handoff": {"agents": {"codex": {"enabled": False}}}}
        self.assertEqual({a: v["enabled"] for a, v in limits.effective(settings, "handoff").items()},
                         {"claude": True, "codex": False, "jetbrains": True})
        settings = {"handoff": {"enabled": False, "agents": {"codex": {"enabled": True}}}}
        self.assertEqual({a: v["enabled"] for a, v in limits.effective(settings, "handoff").items()},
                         {"claude": False, "codex": False, "jetbrains": False})

    def test_a_leftover_codex_handoff_key_changes_nothing(self):
        settings = {"codex_handoff": {"enabled": False, "five_hour_percent": 50}}
        self.assertEqual(limits.handoff_thresholds(settings, "codex"), (True, {300: 100, 10080: 98}))

    def test_agent_of_a_window_label(self):
        self.assertEqual([limits.agent_of(label) for label in
                          ("claude", "claude/sri@ndcom.de", "claude/jetbrains-ai", "codex", "codex/x", None)],
                         ["claude", "claude", "jetbrains", "codex", "codex", "claude"])

    def test_block_at_maps_a_window_to_its_agents_cutoff(self):
        settings = {"usage_block": {"agents": {"jetbrains": {"monthly_percent": 97}, "codex": {"enabled": False}}}}
        cutoff = limits.block_at(settings)
        self.assertEqual(cutoff({"agent": "claude/jetbrains-ai", "minutes": 43200}), 97)
        self.assertEqual(cutoff({"agent": "claude", "minutes": 10080}), 99)
        self.assertIsNone(cutoff({"agent": "codex", "minutes": 300}))
        self.assertIsNone(cutoff({"agent": "claude", "minutes": 60}))
        self.assertIsNone(cutoff({"agent": "claude", "minutes": 43200}))

    def test_handoff_thresholds_by_window_length(self):
        settings = {"handoff": {"agents": {"jetbrains": {"monthly_percent": 95}}}}
        self.assertEqual(limits.handoff_thresholds(settings, "jetbrains"), (True, {43200: 95}))
        self.assertEqual(limits.handoff_thresholds(settings, "claude"), (True, {300: 100, 10080: 98}))


class Apply(unittest.TestCase):
    def test_set_stores_ints_floats_and_flags(self):
        result = limits.apply({}, ["usage_block.weekly_percent=97", "handoff.agents.codex.five_hour_percent=90.5",
                                   "handoff.agents.codex.enabled=false"])
        self.assertEqual(result, {"usage_block": {"weekly_percent": 97},
                                  "handoff": {"agents": {"codex": {"five_hour_percent": 90.5, "enabled": False}}}})
        self.assertIs(type(result["usage_block"]["weekly_percent"]), int)

    def test_default_deletes_and_prunes(self):
        settings = {"handoff": {"enabled": False, "agents": {"codex": {"five_hour_percent": 90}}}, "remote_hosts": []}
        self.assertEqual(limits.apply(settings, ["handoff.agents.codex.five_hour_percent=default"]),
                         {"handoff": {"enabled": False}, "remote_hosts": []})
        self.assertEqual(limits.apply(settings, ["handoff.agents.codex=default", "handoff.enabled=default"]),
                         {"remote_hosts": []})
        self.assertEqual(limits.apply(settings, ["handoff=default"]), {"remote_hosts": []})
        self.assertEqual(limits.apply({}, ["usage_block.agents.claude=default"]), {})

    def test_pairs_apply_in_order_so_an_agent_is_replaced_whole(self):
        settings = {"usage_block": {"agents": {"claude": {"enabled": False, "weekly_percent": 90}}}}
        result = limits.apply(settings, ["usage_block.agents.claude=default", "usage_block.agents.claude.five_hour_percent=95"])
        self.assertEqual(result, {"usage_block": {"agents": {"claude": {"five_hour_percent": 95}}}})

    def test_a_bad_pair_changes_nothing(self):
        settings = {"handoff": {"weekly_percent": 97}}
        with self.assertRaises(limits.LimitError):
            limits.apply(settings, ["handoff.weekly_percent=90", "handoff.weekly_percent=0"])
        self.assertEqual(settings, {"handoff": {"weekly_percent": 97}})

    def test_each_error_names_the_pair(self):
        for pair in ("handoff", "nope.enabled=true", "handoff.agents=default", "handoff.agents.junie.enabled=true",
                     "handoff.colour=1", "handoff.agents.jetbrains.five_hour_percent=90",
                     "handoff.agents.codex.monthly_percent=90", "handoff.enabled=yes", "handoff.weekly_percent=101",
                     "handoff.weekly_percent=nan", "handoff.weekly_percent=true", "handoff.enabled.x=true",
                     "handoff.agents.codex=false"):
            with self.subTest(pair=pair), self.assertRaises(limits.LimitError) as caught:
                limits.apply({}, [pair])
            self.assertIn(pair, str(caught.exception))


class Cli(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "config.json")
        with open(self.path, "w") as handle:
            json.dump({"remote_hosts": ["desktop"]}, handle)
        patch = mock.patch.dict(os.environ, {"AGENT_ETA_CONFIG": self.path})
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.dir.cleanup)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = eta.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_set_writes_and_get_json_reads_back(self):
        self.assertEqual(self.run_cli("config", "set", "handoff.agents.codex.five_hour_percent=90")[0], 0)
        with open(self.path) as handle:
            self.assertEqual(json.load(handle), {"remote_hosts": ["desktop"],
                                                 "handoff": {"agents": {"codex": {"five_hour_percent": 90}}}})
        code, out, _ = self.run_cli("config", "get", "--json")
        described = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(described["schema"], 1)
        self.assertEqual(described["agents"]["jetbrains"], ["monthly_percent"])
        self.assertEqual(described["handoff"]["effective"]["codex"]["five_hour_percent"], 90)
        self.assertEqual(described["handoff"]["configured"], {"agents": {"codex": {"five_hour_percent": 90}}})
        self.assertEqual(described["usage_block"]["defaults"],
                         {"enabled": True, "five_hour_percent": 99, "weekly_percent": 99, "monthly_percent": 99})

    def test_a_bad_set_exits_2_and_leaves_the_file(self):
        code, _, err = self.run_cli("config", "set", "usage_block.weekly_percent=90", "usage_block.weekly_percent=0")
        self.assertEqual(code, 2)
        self.assertIn("agent-eta config: usage_block.weekly_percent=0", err)
        with open(self.path) as handle:
            self.assertEqual(json.load(handle), {"remote_hosts": ["desktop"]})

    def test_get_prints_a_table(self):
        self.run_cli("config", "set", "usage_block.agents.codex.enabled=false")
        code, out, _ = self.run_cli("config", "get")
        lines = out.splitlines()
        self.assertEqual(code, 0)
        self.assertEqual(lines[0].split(), ["SETTING", "AGENT", "ON", "5H", "7D", "30D"])
        self.assertEqual(lines[1].split(), ["usage_block", "default", "on", "99%", "99%", "99%"])
        self.assertEqual(lines[3].split(), ["usage_block", "Codex", "off", "99%", "99%", "-"])
        self.assertEqual(lines[8].split(), ["handoff", "JetBrains", "AI", "on", "-", "-", "98%"])


if __name__ == "__main__":
    unittest.main()
