"""Conservative cross-host workspace reconciliation and optional adapter boundaries."""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import agent_eta_workspace as workspace


def snapshot(names=("Work",), windows=True, host="source", output="screen", area=None):
    value = {"version": 1, "host": host, "x11": False,
             "desktops": [{"id": str(index), "name": name} for index, name in enumerate(names)],
             "outputs": [{"name": output, "area": area or [0, 0, 1920, 1040]}], "active_output": output,
             "windows": []}
    if windows:
        value["windows"].append({"id": host + "-window", "identity": ["app", "class", "name", "role", "digest"],
                                 "pid": 123, "desktops": [names[0]], "all_desktops": False, "output": output,
                                 "rect": [0.1, 0.2, 0.5, 0.6], "movable": True, "resizable": True, "tiled": False,
                                 "state": {"minimized": False, "fullscreen": False, "maximize": 0}})
    return value


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.source = snapshot()
        self.target = snapshot(host="target")

    def test_exact_unique_identity_matches_without_pid_equality(self):
        self.target["windows"][0]["pid"] = 999
        plan = workspace.reconcile(self.source, self.target)
        self.assertEqual(len(plan["windows"]), 1)
        self.assertEqual(plan["windows"][0]["id"], "target-window")
        self.assertEqual(plan["windows"][0]["geometry"], [192, 208, 960, 624])

    def test_desktop_ids_and_destination_only_names_are_preserved(self):
        source = snapshot(("A", "B", "C"), windows=False)
        target = snapshot(("A", "C", "Local"), windows=False)
        before = deepcopy(target)
        creates, warnings = workspace.desktop_plan(source, target)
        self.assertEqual(creates, [{"name": "B", "position": 1}])
        self.assertFalse(warnings)
        self.assertEqual(target, before)

    def test_order_conflicts_are_reported_without_renaming(self):
        source = snapshot(("A", "B", "C"), windows=False)
        target = snapshot(("C", "A", "Local"), windows=False)
        creates, warnings = workspace.desktop_plan(source, target)
        self.assertEqual(creates, [{"name": "B", "position": 3}])
        self.assertTrue(warnings)

    def test_repeated_topology_application_has_no_creates(self):
        self.assertEqual(workspace.desktop_plan(self.source, self.target), ([], []))

    def test_duplicate_names_between_matched_desktops_report_no_order_conflict(self):
        layout = snapshot(("Work", "New Desktop", "New Desktop", "Mail"), windows=False)
        self.assertEqual(workspace.desktop_plan(layout, deepcopy(layout)),
                         ([], ["Desktops with duplicate names stay unmatched: New Desktop."]))

    def test_capacity_is_checked_before_any_writes(self):
        source = snapshot(tuple("Source%d" % number for number in range(15)), windows=False)
        target = snapshot(tuple("Target%d" % number for number in range(15)), windows=False)
        with self.assertRaisesRegex(workspace.WorkspaceError, "capacity"):
            workspace.reconcile(source, target)

    def test_unknown_versions_are_rejected(self):
        with self.assertRaises(workspace.WorkspaceError):
            workspace.reconcile(dict(self.source, version=2), self.target)

    def test_duplicate_desktop_names_stay_unmatched_with_a_warning(self):
        def with_new_desktop(value, names):
            value["desktops"] = [{"id": str(index), "name": name} for index, name in enumerate(names)]
            extra = deepcopy(value["windows"][0])
            extra.update(id=value["host"] + "-other", identity=["app", "class", "other", "role", "digest"],
                         desktops=["New Desktop"])
            value["windows"].append(extra)
            return value

        for duplicated in ("source", "target"):
            with self.subTest(duplicated=duplicated):
                names = {"source": ("Work", "New Desktop"), "target": ("Work", "New Desktop")}
                names[duplicated] = ("Work", "New Desktop", "New Desktop")
                source = with_new_desktop(snapshot(), names["source"])
                target = with_new_desktop(snapshot(host="target"), names["target"])
                plan = workspace.reconcile(source, target)
                self.assertEqual([window["id"] for window in plan["windows"]], ["target-window"])
                self.assertEqual(plan["skipped"], [{"id": "source-other", "reason": "Desktop name is not unique."}])
                self.assertEqual(plan["creates"], [])
                self.assertIn("Desktops with duplicate names stay unmatched: New Desktop.", plan["warnings"])

    def test_invalid_records_are_rejected_before_application(self):
        for key, replacement in (("rect", [0, 0, float("nan"), 1]), ("rect", [0, 0, 0, 1]),
                                 ("desktops", ["Unknown"]), ("output", "missing"), ("identity", []),
                                 ("state", {"minimized": "false", "fullscreen": False, "maximize": 0})):
            value = deepcopy(self.source)
            value["windows"][0][key] = replacement
            with self.subTest(key=key, replacement=replacement), self.assertRaises(workspace.WorkspaceError):
                workspace.validate(value)

    def test_duplicate_or_different_captions_never_pick_an_arbitrary_window(self):
        for side in ("source", "target"):
            source, target = deepcopy(self.source), deepcopy(self.target)
            value = source if side == "source" else target
            value["windows"].append(dict(value["windows"][0], id="other"))
            self.assertFalse(workspace.reconcile(source, target)["windows"])
        self.target["windows"][0]["identity"][-1] = "different-caption"
        self.assertFalse(workspace.reconcile(self.source, self.target)["windows"])

    def test_managed_identity_survives_changed_captions(self):
        self.source["windows"][0]["session"] = "claude:same"
        self.target["windows"][0].update(session="claude:same", identity=["other"] * 5)
        self.assertEqual(len(workspace.reconcile(self.source, self.target)["windows"]), 1)

    def test_unmatched_managed_session_cannot_fall_back_to_caption(self):
        self.source["windows"][0]["session"] = "claude:missing"
        self.assertFalse(workspace.reconcile(self.source, self.target)["windows"])

    def test_shared_and_tiled_or_constrained_windows_are_skipped(self):
        for key, value in (("shared", True), ("tiled", True), ("movable", False), ("resizable", False)):
            target = deepcopy(self.target)
            target["windows"][0][key] = value
            self.assertFalse(workspace.reconcile(self.source, target)["windows"])
        self.source["windows"][0]["shared"] = True
        self.assertFalse(workspace.reconcile(self.source, self.target)["windows"])

    def test_multiple_memberships_are_supported_on_wayland_and_reported_on_x11(self):
        source = snapshot(("A", "B"))
        source["windows"][0]["desktops"] = ["A", "B"]
        self.assertTrue(workspace.reconcile(source, self.target)["windows"])
        self.target["x11"] = True
        self.assertFalse(workspace.reconcile(source, self.target)["windows"])

    def test_all_desktop_membership_survives(self):
        self.source["windows"][0].update(desktops=[], all_desktops=True)
        self.assertTrue(workspace.reconcile(self.source, self.target)["windows"][0]["all_desktops"])

    def test_geometry_maps_different_sizes_and_negative_coordinates(self):
        self.target["outputs"][0]["area"] = [-1600, -900, 1600, 860]
        self.assertEqual(workspace.reconcile(self.source, self.target)["windows"][0]["geometry"],
                         [-1440, -728, 800, 516])
        self.assertEqual(workspace.geometry([-0.5, 2, 3, 4], [-1600, 0, 1600, 860]), [-1600, 0, 1600, 860])

    def test_output_fallbacks_are_explicit(self):
        self.source["outputs"].append({"name": "second", "area": [1920, 0, 1920, 1040]})
        self.source["windows"][0]["output"] = "second"
        self.target["outputs"][0]["name"] = "laptop"
        self.target["windows"][0]["output"] = "laptop"
        self.target["active_output"] = "laptop"
        item = workspace.reconcile(self.source, self.target)["windows"][0]
        self.assertEqual(item["mapping"], {"from": "second", "to": "laptop", "method": "active output"})


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="eta-workspace-")
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.dict(os.environ, AGENT_ETA_DIR=self.tmp.name)
        patch.start()
        self.addCleanup(patch.stop)

    def test_preview_never_applies_or_writes_a_backup(self):
        backend = mock.Mock()
        backend.snapshot.return_value = snapshot(host="target")
        result = workspace.apply_snapshot(snapshot(), backend=backend)
        self.assertFalse(result["applied"])
        backend.apply.assert_not_called()
        self.assertFalse(list(Path(self.tmp.name).rglob("before-*.json")))

    def test_apply_saves_private_backup_and_reports_readback(self):
        backend = mock.Mock()
        backend.snapshot.return_value = snapshot(host="target")
        backend.apply.return_value = {"applied": ["target-window"], "skipped": []}
        result = workspace.apply_snapshot(snapshot(), apply=True, backend=backend)
        self.assertTrue(result["applied"])
        self.assertEqual(result["verification"], [])
        self.assertEqual(Path(result["backup"]).stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(Path(result["backup"]).read_text())["host"], "target")

    def test_apply_failure_names_backup_and_possible_partial_changes(self):
        backend = mock.Mock()
        backend.snapshot.return_value = snapshot(host="target")
        backend.apply.side_effect = workspace.WorkspaceError("Desktop topology changed.")
        with self.assertRaisesRegex(workspace.WorkspaceError, "Partial application.*backup"):
            workspace.apply_snapshot(snapshot(), apply=True, backend=backend)

    def test_unsupported_version_does_not_even_contact_kwin(self):
        backend = mock.Mock()
        with self.assertRaises(workspace.WorkspaceError):
            workspace.apply_snapshot({"version": 99}, apply=True, backend=backend)
        backend.snapshot.assert_not_called()

    def test_live_identity_changes_are_rejected(self):
        backend = workspace.Backend()
        with self.assertRaisesRegex(workspace.WorkspaceError, "identity changed"):
            backend.apply({"windows": [{"id": "gone", "expected_identity": []}]})

    def test_native_stderr_and_titles_do_not_leak_into_errors(self):
        backend = workspace.Backend()
        with mock.patch.dict(os.environ, AGENT_ETA_KDOTOOL_BIN="/fake/kdotool"), \
                mock.patch.object(workspace.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "private-title")):
            with self.assertRaises(workspace.WorkspaceError) as error:
                backend.run({"operation": "snapshot"})
        self.assertNotIn("private-title", str(error.exception))

    def test_ssh_shell_without_session_environment_still_reaches_kdotool(self):
        environment = {key: value for key, value in os.environ.items() if key != "KDE_SESSION_VERSION"}
        environment["AGENT_ETA_KDOTOOL_BIN"] = "/fake/kdotool"
        with mock.patch.dict(os.environ, environment, clear=True), \
                mock.patch.object(workspace.subprocess, "run",
                                  return_value=subprocess.CompletedProcess([], 0, "{}", "")) as run:
            workspace.Backend().run({"operation": "snapshot"})
        self.assertEqual(run.call_args.kwargs["env"]["KDE_SESSION_VERSION"], "6")

    def test_timeout_removes_temporary_script(self):
        folder = []
        def timed_out(argv, **kwargs):
            folder.append(Path(argv[-1]).parent)
            raise subprocess.TimeoutExpired(argv, 10)
        with mock.patch.dict(os.environ, AGENT_ETA_KDOTOOL_BIN="/fake/kdotool"), \
                mock.patch.object(workspace.subprocess, "run", side_effect=timed_out):
            with self.assertRaises(workspace.WorkspaceError):
                workspace.Backend().run({"operation": "snapshot"})
        self.assertFalse(folder[0].exists())

    def test_private_keyless_and_ambiguous_branches_have_no_assignment(self):
        for branch, expected in (("feature/private-work", None), ("feature/ABC-123-task", "ABC-123"),
                                 ("feature/ABC-123-DEF-456", None), ("feature/ABC-123-ABC-123", "ABC-123")):
            with self.subTest(branch=branch), mock.patch.object(workspace.subprocess, "run",
                    return_value=subprocess.CompletedProcess([], 0, branch, "")):
                self.assertEqual(workspace.assignment("/project"), expected)
        with mock.patch.object(workspace.subprocess, "run") as run:
            self.assertEqual(workspace.assignment("/project", "OTHER-7"), "OTHER-7")
            run.assert_not_called()
        with self.assertRaises(workspace.WorkspaceError):
            workspace.assignment("/project", "not a key")

    def test_clear_assignment_is_persisted_without_creating_a_desktop(self):
        runtime, record = mock.Mock(), {"id": "record", "workspace": {"jira_key": "ABC-123"}}
        workspace.configure(runtime, record)
        self.assertEqual(record["workspace"], {"jira_key": None})
        runtime.write.assert_called_once_with(record)
        with mock.patch.object(workspace, "Backend") as backend:
            self.assertTrue(workspace.place_viewer(runtime, record))
            backend.assert_not_called()

    def test_workspace_failure_leaves_running_session_untouched(self):
        runtime = mock.Mock()
        backend = mock.Mock()
        backend.snapshot.side_effect = workspace.WorkspaceError("Unavailable")
        record = {"workspace": {"jira_key": "ABC-123"}}
        with mock.patch("sys.stderr"):
            self.assertFalse(workspace.place_viewer(runtime, record, backend=backend))
        runtime.stop.assert_not_called()

    def test_resize_acknowledgement_precedes_membership_changes(self):
        backend = workspace.Backend()
        raw = {"id": "target-window", "identity": ["app", "class", "name", "role", "caption"],
               "pid": 999, "geometry": [192, 208, 960, 624]}
        target = snapshot(host="target")
        target["windows"][0]["identity"] = workspace.identity(raw["identity"])
        source = deepcopy(target)
        plan = workspace.reconcile(source, target)
        backend.raw_windows = {raw["id"]: raw}
        with mock.patch.object(backend, "run", side_effect=[
                {"created": [], "applied": [raw["id"]], "skipped": []},
                {"created": [], "applied": [raw["id"]], "skipped": []}]) as run, \
                mock.patch.object(backend, "snapshot", return_value=target) as capture:
            backend.apply(plan)
        self.assertEqual(run.call_args_list[0].args[0]["phase"], "geometry")
        self.assertNotIn("phase", run.call_args_list[1].args[0])
        capture.assert_called_once()

    def test_handoff_adapter_keeps_assignment_and_geometry_without_changing_legacy_fields(self):
        import agent_eta_tmux as tmux
        import base64
        placement = dict(snapshot(), assignment="ABC-123")
        encoded = base64.b64encode(json.dumps(placement).encode()).decode()
        tabs = Path(self.tmp.name) / "tabs"
        tabs.write_text("title: Handoff;; workdir: /project;; command: /bin/sleep 60;; workspace: " + encoded + "\n")
        record = {"id": "a" * 32}
        with mock.patch.object(tmux, "Runtime") as runtime:
            runtime.return_value.start.return_value = record
            tmux.account_tabs(tabs)
        self.assertEqual(record["workspace"], {"jira_key": "ABC-123", "placement": placement})
        runtime.return_value.attach.assert_called_once_with(record)

    def test_explicit_launch_key_reaches_managed_metadata_before_attachment(self):
        import agent_eta_providers as providers
        account = {"provider": "codex", "directory": "/account"}
        record = {"id": "a" * 32}
        with mock.patch.object(providers, "executable", return_value="/fake/codex"), \
                mock.patch("agent_eta_tmux.Runtime") as runtime:
            runtime.return_value.start.return_value = record
            providers.launch(account, self.tmp.name, cli=True, jira_key="ABC-123")
        self.assertEqual(record["workspace"], {"jira_key": "ABC-123"})
        runtime.return_value.attach.assert_called_once_with(record)
        with mock.patch("agent_eta_tmux.Runtime") as runtime, self.assertRaises(providers.AccountError):
            providers.launch(account, self.tmp.name, cli=True, jira_key="not a key")
        runtime.assert_not_called()

    def test_existing_jump_viewer_is_placed_without_opening_a_duplicate(self):
        import agent_eta_tmux as tmux
        runtime = tmux.Runtime(self.tmp.name)
        record = {"workspace": {"jira_key": "ABC-123"}}
        with mock.patch.object(runtime, "pane", return_value={"window": "@1"}), \
                mock.patch.object(runtime, "local_client", return_value={"pid": 555}), \
                mock.patch.object(tmux, "lineage", return_value=[555, 444]), \
                mock.patch.object(workspace, "place_viewer") as place, \
                mock.patch.object(tmux, "open_terminal") as open_terminal:
            result = runtime.attach(record)
        place.assert_called_once_with(runtime, record, [555, 444])
        open_terminal.assert_not_called()
        self.assertFalse(result["opened"])

    def test_shared_konsole_is_never_selected(self):
        import agent_eta_konsole as konsole
        with mock.patch.object(konsole, "qdbus", return_value="qdbus"), \
                mock.patch.object(konsole, "find_tab", return_value=("org.kde.konsole-123", "/Windows/1", "1")), \
                mock.patch.object(konsole, "call", return_value="1\n2\n"), \
                mock.patch.object(konsole, "select") as select:
            self.assertIsNone(workspace.viewer_window(mock.Mock(), {}, snapshot(), [123]))
        select.assert_not_called()


if __name__ == "__main__":
    unittest.main()
