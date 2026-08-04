from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "teamkit" / "cli.py"
BIN = ROOT / "bin" / "teamkit"
EXAMPLE = ROOT / "examples" / "risk-review-team"


class TeamKitCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.workdir = Path(self.tmp.name)
        shutil.copytree(EXAMPLE, self.workdir, dirs_exist_ok=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_cli(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(CLI), *args],
            cwd=self.workdir,
            text=True,
            capture_output=True,
            check=False,
        )
        if check and result.returncode != 0:
            self.fail(
                f"teamkit failed: {' '.join(args)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        return result

    def test_bin_entrypoint_is_usable_from_source(self) -> None:
        result = subprocess.run(
            [str(BIN), "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("teamkit", result.stdout)

    def test_end_to_end_run_workspace(self) -> None:
        self.run_cli("team", "validate", "--team", "team.yaml")

        compile_result = self.run_cli(
            "team", "compile", "--team", "team.yaml", "--out", "build/execution-plan.json"
        )
        plan_path = Path(compile_result.stdout.strip())
        self.assertTrue(plan_path.exists())
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        self.assertEqual(plan["schemaVersion"], "teamkit.execution_plan.v0.1")
        self.assertIsNone(plan["adapterBoundary"]["target"])
        self.assertEqual(plan["adapterBoundary"]["availableAdapters"], ["workbuddy"])
        self.assertEqual(plan["process"]["graph"]["entry"], "material_intake")
        self.assertNotIn("mainSteps", plan["process"])
        self.assertEqual(plan["commandContract"]["topic"], "teamkit topic status/update/link")
        self.assertEqual(plan["commandContract"]["context"], "teamkit context add/list")
        self.assertEqual(plan["commandContract"]["graph"], "teamkit graph next/advance")
        self.assertNotIn("data", plan["commandContract"])
        self.assertNotIn("steps", plan["commandContract"])
        self.assertEqual(
            [item["id"] for item in plan["contexts"]],
            [
                "review_sop",
                "risk_rules",
                "merchant_profile",
                "blacklist_hit",
                "recent_transaction_summary",
                "review_history",
            ],
        )

        self.run_cli("run", "init", "--team", "team.yaml", "--run", "case-001")
        self.assertTrue((self.workdir / "runs" / "case-001" / "state.yaml").exists())
        self.assertTrue((self.workdir / "runs" / "case-001" / "human-review.jsonl").exists())
        self.assertTrue((self.workdir / "runs" / "case-001" / "topic.yaml").exists())
        self.assertTrue((self.workdir / "runs" / "case-001" / "context-items.jsonl").exists())
        self.assertTrue((self.workdir / "runs" / "case-001" / "contexts" / "review_sop" / "manifest.json").exists())
        state_text = (self.workdir / "runs" / "case-001" / "state.yaml").read_text(encoding="utf-8")
        self.assertIn("active_node:", state_text)
        self.assertNotIn("active_step:", state_text)
        self.assertNotIn("steps:", state_text)

        topic_result = self.run_cli(
            "topic", "status", "--team", "team.yaml", "--run", "case-001", "--json"
        )
        topic = json.loads(topic_result.stdout)
        self.assertEqual(topic["current_node"], "material_intake")
        self.assertEqual([item["id"] for item in topic["context_refs"]], ["review_sop", "risk_rules"])

        context_list_result = self.run_cli(
            "context", "list", "--team", "team.yaml", "--run", "case-001", "--json"
        )
        contexts = json.loads(context_list_result.stdout)
        self.assertEqual(len(contexts), 2)
        self.assertEqual(contexts[1]["scope"], "agents")
        self.assertEqual(contexts[1]["visibleTo"], ["policy", "decision", "qa"])

        graph_result = self.run_cli(
            "graph", "next", "--team", "team.yaml", "--run", "case-001", "--json"
        )
        graph_next = json.loads(graph_result.stdout)
        self.assertFalse(graph_next["blocked"])
        self.assertEqual(graph_next["actions"][0]["to"], "evidence_check")

        send_result = self.run_cli(
            "msg",
            "send",
            "--team",
            "team.yaml",
            "--run",
            "case-001",
            "--from",
            "intake",
            "--to",
            "evidence",
            "--subject",
            "Need evidence check",
            "--body",
            "Please compare submitted materials with managed context.",
        )
        message_id = send_result.stdout.strip()
        self.assertRegex(message_id, r"^msg_[0-9a-f]{16}$")

        blocked_result = self.run_cli(
            "graph", "next", "--team", "team.yaml", "--run", "case-001", "--json"
        )
        blocked = json.loads(blocked_result.stdout)
        self.assertTrue(blocked["blocked"])
        self.assertEqual(blocked["openMessages"], [message_id])

        self.run_cli(
            "msg",
            "reply",
            "--team",
            "team.yaml",
            "--run",
            "case-001",
            "--from",
            "evidence",
            "--reply-to",
            message_id,
            "--body",
            "Business data matches the submitted materials.",
        )

        unblocked_result = self.run_cli(
            "graph", "next", "--team", "team.yaml", "--run", "case-001", "--json"
        )
        unblocked = json.loads(unblocked_result.stdout)
        self.assertFalse(unblocked["blocked"])
        self.assertEqual(unblocked["actions"][0]["to"], "evidence_check")

        advanced_topic_result = self.run_cli(
            "graph",
            "advance",
            "--team",
            "team.yaml",
            "--run",
            "case-001",
            "--to",
            "evidence_check",
            "--summary",
            "Evidence expert is checking managed context.",
            "--by",
            "decision",
            "--json",
        )
        advanced_topic = json.loads(advanced_topic_result.stdout)
        self.assertEqual(advanced_topic["current_node"], "evidence_check")
        self.assertEqual(advanced_topic["status"], "active")
        self.assertEqual(advanced_topic["visits"]["evidence_check"], 1)

        updated_topic_result = self.run_cli(
            "topic",
            "update",
            "--team",
            "team.yaml",
            "--run",
            "case-001",
            "--summary",
            "Evidence check has stable context snapshots.",
            "--json",
        )
        updated_topic = json.loads(updated_topic_result.stdout)
        self.assertEqual(updated_topic["current_node"], "evidence_check")
        self.assertEqual(updated_topic["status"], "active")

        added_context_result = self.run_cli(
            "context",
            "add",
            "--team",
            "team.yaml",
            "--run",
            "case-001",
            "--id",
            "runtime_note",
            "--name",
            "运行补充说明",
            "--file",
            "references/review-sop.md",
            "--scope",
            "agents",
            "--visible-to",
            "evidence",
            "--by",
            "decision",
            "--summary",
            "Only evidence expert should inspect this additional note.",
        )
        self.assertEqual(added_context_result.stdout.strip(), "runtime_note")
        evidence_contexts_result = self.run_cli(
            "context",
            "list",
            "--team",
            "team.yaml",
            "--run",
            "case-001",
            "--visible-to",
            "evidence",
            "--json",
        )
        evidence_contexts = json.loads(evidence_contexts_result.stdout)
        self.assertEqual([item["id"] for item in evidence_contexts], ["review_sop", "runtime_note"])

        query_context_result = self.run_cli(
            "context",
            "add",
            "--team",
            "team.yaml",
            "--run",
            "case-001",
            "--id",
            "blacklist_hit",
            "--text",
            '{"merchant":"merchant-123","blacklistHit":false}',
            "--summary",
            "No blacklist hit in the queried context.",
            "--by",
            "evidence",
        )
        self.assertEqual(query_context_result.stdout.strip(), "blacklist_hit")

        context_after_data_result = self.run_cli(
            "context",
            "list",
            "--team",
            "team.yaml",
            "--run",
            "case-001",
            "--visible-to",
            "policy",
            "--json",
        )
        policy_contexts = json.loads(context_after_data_result.stdout)
        self.assertIn("blacklist_hit", [item["id"] for item in policy_contexts])

        review_result = self.run_cli(
            "human",
            "request",
            "--team",
            "team.yaml",
            "--run",
            "case-001",
            "--from",
            "policy",
            "--reason",
            "policy conflict",
            "--question",
            "Which policy interpretation should be used?",
        )
        review_id = review_result.stdout.strip()
        self.assertRegex(review_id, r"^hr_[0-9a-f]{16}$")

        waiting_topic_result = self.run_cli(
            "topic", "status", "--team", "team.yaml", "--run", "case-001", "--json"
        )
        waiting_topic = json.loads(waiting_topic_result.stdout)
        self.assertEqual(waiting_topic["status"], "waiting")
        self.assertEqual(waiting_topic["waiting_on"]["type"], "human_review")
        self.assertEqual(waiting_topic["waiting_on"]["ref"], review_id)

        premature_final = self.run_cli(
            "result",
            "publish",
            "--team",
            "team.yaml",
            "--run",
            "case-001",
            "--from",
            "decision",
            "--file",
            "runs/case-001/experts/decision/result.md",
            check=False,
        )
        self.assertEqual(premature_final.returncode, 2)
        self.assertIn("human input requests are open", premature_final.stderr)

        self.run_cli(
            "human",
            "resolve",
            "--team",
            "team.yaml",
            "--run",
            "case-001",
            "--review",
            review_id,
            "--by",
            "reviewer",
            "--resolution",
            "approved",
            "--answer",
            "Use the current policy.",
        )

        active_topic_result = self.run_cli(
            "topic", "status", "--team", "team.yaml", "--run", "case-001", "--json"
        )
        active_topic = json.loads(active_topic_result.stdout)
        self.assertEqual(active_topic["status"], "active")
        self.assertIsNone(active_topic["waiting_on"])

        artifact_result = self.run_cli(
            "artifact",
            "publish",
            "--team",
            "team.yaml",
            "--run",
            "case-001",
            "--from",
            "evidence",
            "--file",
            "runs/case-001/experts/evidence/result.md",
            "--kind",
            "expert_result",
        )
        self.assertRegex(artifact_result.stdout.strip(), r"^art_[0-9a-f]{24}$")

        final_result = self.run_cli(
            "result",
            "publish",
            "--team",
            "team.yaml",
            "--run",
            "case-001",
            "--from",
            "decision",
            "--file",
            "runs/case-001/experts/decision/result.md",
        )
        self.assertRegex(final_result.stdout.strip(), r"^art_[0-9a-f]{24}$")

        status_result = self.run_cli(
            "run", "status", "--team", "team.yaml", "--run", "case-001", "--json"
        )
        status = json.loads(status_result.stdout)
        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["topic"]["status"], "resolved")
        self.assertEqual(status["context_item_count"], 4)
        self.assertEqual(status["open_messages"], [])
        self.assertEqual(status["open_human_reviews"], [])
        self.assertEqual(status["message_count"], 2)
        self.assertEqual(status["human_review_count"], 1)
        self.assertIsNotNone(status["final_result"])

        done_graph_result = self.run_cli(
            "graph", "next", "--team", "team.yaml", "--run", "case-001", "--json"
        )
        done_graph = json.loads(done_graph_result.stdout)
        self.assertTrue(done_graph["blocked"])
        self.assertEqual(done_graph["reason"], "topic is resolved")

    def test_communication_rules_reject_unlisted_route(self) -> None:
        self.run_cli("run", "init", "--team", "team.yaml", "--run", "case-002")
        result = self.run_cli(
            "msg",
            "send",
            "--team",
            "team.yaml",
            "--run",
            "case-002",
            "--from",
            "evidence",
            "--to",
            "intake",
            "--subject",
            "Unsupported route",
            "--body",
            "This should be rejected by configured communication rules.",
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("communication rule does not allow", result.stderr)

    def test_team_context_commands_manage_definition_visibility(self) -> None:
        uploaded = self.workdir.parent / "uploaded-website-sop.md"
        uploaded.write_text("# Website SOP\n\nCheck the public website.\n", encoding="utf-8")

        add_result = self.run_cli(
            "team",
            "context",
            "add",
            "--team",
            "team.yaml",
            "--id",
            "website_sop",
            "--name",
            "网站审核 SOP",
            "--file",
            str(uploaded),
            "--scope",
            "agents",
            "--visible-to",
            "evidence",
            "--summary",
            "Only evidence can inspect this SOP initially.",
            "--json",
        )
        added = json.loads(add_result.stdout)
        self.assertEqual(added["id"], "website_sop")
        self.assertEqual(added["path"], "references/website_sop.md")
        self.assertEqual(added["visibleTo"], ["evidence"])
        self.assertTrue((self.workdir / "references" / "website_sop.md").exists())

        self.run_cli(
            "team",
            "context",
            "assign",
            "--team",
            "team.yaml",
            "--context",
            "website_sop",
            "--visible-to",
            "policy",
        )
        policy_list_result = self.run_cli(
            "team",
            "context",
            "list",
            "--team",
            "team.yaml",
            "--expert",
            "policy",
            "--json",
        )
        policy_contexts = json.loads(policy_list_result.stdout)
        self.assertIn("website_sop", [item["id"] for item in policy_contexts])

        self.run_cli(
            "team",
            "context",
            "unassign",
            "--team",
            "team.yaml",
            "--context",
            "website_sop",
            "--visible-to",
            "evidence",
        )
        self.run_cli("team", "validate", "--team", "team.yaml")
        self.run_cli("run", "init", "--team", "team.yaml", "--run", "context-managed")
        contexts = json.loads(
            self.run_cli(
                "context",
                "list",
                "--team",
                "team.yaml",
                "--run",
                "context-managed",
                "--visible-to",
                "policy",
                "--json",
            ).stdout
        )
        self.assertIn("website_sop", [item["id"] for item in contexts])

    def test_concurrent_message_sends_keep_state_consistent(self) -> None:
        self.run_cli("run", "init", "--team", "team.yaml", "--run", "case-concurrent")

        def send(index: int) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "msg",
                    "send",
                    "--team",
                    "team.yaml",
                    "--run",
                    "case-concurrent",
                    "--from",
                    "intake",
                    "--to",
                    "evidence",
                    "--subject",
                    f"Concurrent request {index}",
                    "--body",
                    f"Body {index}",
                    "--response",
                    "required",
                ],
                cwd=self.workdir,
                text=True,
                capture_output=True,
                check=False,
            )

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(send, range(6)))

        for result in results:
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertRegex(result.stdout.strip(), r"^msg_[0-9a-f]{16}$")

        status_result = self.run_cli(
            "run", "status", "--team", "team.yaml", "--run", "case-concurrent", "--json"
        )
        status = json.loads(status_result.stdout)
        self.assertEqual(status["message_count"], 6)
        self.assertEqual(len(status["open_messages"]), 6)

    def test_main_steps_are_rejected(self) -> None:
        team_path = self.workdir / "team.yaml"
        text = team_path.read_text(encoding="utf-8")
        text = text.replace(
            "  graph:\n    entry: material_intake\n",
            "  main_steps:\n    - id: legacy_step\n      expert: intake\n      task: legacy step\n  graph:\n    entry: material_intake\n",
            1,
        )
        team_path.write_text(text, encoding="utf-8")
        result = self.run_cli("team", "validate", "--team", "team.yaml", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("process.main_steps is not part of TeamKit v0.1", result.stderr)

    def test_generated_protocol_drift_is_rejected(self) -> None:
        (self.workdir / "contexts").mkdir(exist_ok=True)
        team_path = self.workdir / "team.yaml"
        text = team_path.read_text(encoding="utf-8")
        text = text.replace("path: references/review-sop.md", "path: contexts/", 1)
        text = text.replace("required_when:", "conditions:", 1)
        text = text.replace(
            "output:\n  name:",
            "output:\n  final_report:\n    name: Nested report\n  name:",
            1,
        )
        team_path.write_text(text, encoding="utf-8")
        result = self.run_cli("team", "validate", "--team", "team.yaml", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("context path must be a file, not a directory", result.stderr)
        self.assertIn("human_review.conditions is not part of TeamKit v0.1", result.stderr)
        self.assertIn("output.final_report is not part of TeamKit v0.1", result.stderr)

    def test_workbuddy_export_creates_team_expert_package(self) -> None:
        result = self.run_cli(
            "workbuddy",
            "export",
            "--team",
            "team.yaml",
            "--out",
            "build/workbuddy",
            "--force",
            "--json",
        )
        payload = json.loads(result.stdout)
        package_dir = Path(payload["packageDir"])
        self.assertTrue((package_dir / ".codebuddy-plugin" / "plugin.json").exists())
        self.assertTrue((package_dir / "settings.json").exists())
        self.assertTrue((package_dir / "skills" / "teamkit-runtime" / "SKILL.md").exists())
        wrapper_path = package_dir / "skills" / "teamkit-runtime" / "scripts" / "teamkit.py"
        self.assertTrue(wrapper_path.exists())
        self.assertIn(".teamkit", wrapper_path.read_text(encoding="utf-8"))
        self.assertTrue((package_dir / "teamkit-workspace" / "team.yaml").exists())
        self.assertTrue((package_dir / "vendor" / "teamkit" / "teamkit" / "cli.py").exists())

        plugin = json.loads((package_dir / ".codebuddy-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(plugin["expertType"], "team")
        self.assertEqual(plugin["teamInfo"]["leadAgent"], plugin["agentName"])
        self.assertNotIn(plugin["agentName"], plugin["teamInfo"]["memberAgents"])
        self.assertEqual(len(plugin["tags"]), 3)
        self.assertEqual(len(plugin["quickPrompts"]), 3)

        install_result = self.run_cli(
            "workbuddy",
            "install",
            "--package",
            str(package_dir),
            "--config-dir",
            "fake-workbuddy",
            "--force",
            "--json",
        )
        install_payload = json.loads(install_result.stdout)
        installed_dir = Path(install_payload["installedDir"])
        marketplace_path = Path(install_payload["marketplacePath"])
        self.assertTrue((installed_dir / ".codebuddy-plugin" / "plugin.json").exists())
        marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
        self.assertTrue(any(item["name"] == "risk-review" for item in marketplace["plugins"]))

        wrapper_result = subprocess.run(
            [sys.executable, str(package_dir / "skills" / "teamkit-runtime" / "scripts" / "teamkit.py"), "team", "validate"],
            cwd=self.workdir,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(wrapper_result.returncode, 0, wrapper_result.stderr)
        self.assertIn("valid team definition", wrapper_result.stdout)

    def test_workbuddy_export_init_creates_teamkit_workbench_package(self) -> None:
        result = self.run_cli(
            "workbuddy",
            "export-init",
            "--out",
            "build/workbuddy",
            "--force",
            "--json",
        )
        payload = json.loads(result.stdout)
        package_dir = Path(payload["packageDir"])
        self.assertEqual(payload["packageName"], "teamkit-workbench")
        self.assertTrue((package_dir / ".codebuddy-plugin" / "plugin.json").exists())
        self.assertTrue((package_dir / "settings.json").exists())
        self.assertTrue((package_dir / "skills" / "agent-team-builder" / "SKILL.md").exists())
        self.assertTrue((package_dir / "skills" / "agent-prompt-optimizer" / "SKILL.md").exists())
        wrapper_path = package_dir / "skills" / "teamkit-workbench-runtime" / "scripts" / "teamkit.py"
        self.assertTrue(wrapper_path.exists())
        self.assertIn(".teamkit", wrapper_path.read_text(encoding="utf-8"))
        self.assertTrue((package_dir / "docs" / "coordination-model.md").exists())
        self.assertTrue((package_dir / "schemas" / "team.schema.json").exists())
        self.assertTrue((package_dir / "vendor" / "teamkit" / "teamkit" / "cli.py").exists())

        plugin = json.loads((package_dir / ".codebuddy-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(plugin["expertType"], "team")
        self.assertEqual(plugin["displayName"]["zh"], "TeamKit 工作台")
        self.assertEqual(plugin["profession"], plugin["displayName"])
        self.assertEqual(plugin["teamInfo"]["leadAgent"], plugin["agentName"])
        self.assertEqual(plugin["teamInfo"]["memberAgents"], [])
        self.assertEqual(len(plugin["skills"]), 3)

        install_result = self.run_cli(
            "workbuddy",
            "install",
            "--package",
            str(package_dir),
            "--config-dir",
            "fake-workbuddy",
            "--force",
            "--json",
        )
        install_payload = json.loads(install_result.stdout)
        installed_dir = Path(install_payload["installedDir"])
        marketplace = json.loads(Path(install_payload["marketplacePath"]).read_text(encoding="utf-8"))
        self.assertTrue(any(item["name"] == "teamkit-workbench" for item in marketplace["plugins"]))

        wrapper_result = subprocess.run(
            [
                sys.executable,
                str(package_dir / "skills" / "teamkit-workbench-runtime" / "scripts" / "teamkit.py"),
                "--team",
                "team.yaml",
                "team",
                "validate",
            ],
            cwd=self.workdir,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(wrapper_result.returncode, 0, wrapper_result.stderr)
        self.assertIn("valid team definition", wrapper_result.stdout)

        uninstall_result = self.run_cli(
            "workbuddy",
            "uninstall",
            "--package",
            "teamkit-workbench",
            "--config-dir",
            "fake-workbuddy",
            "--force",
            "--json",
        )
        uninstall_payload = json.loads(uninstall_result.stdout)
        self.assertTrue(uninstall_payload["directoryExisted"])
        self.assertTrue(uninstall_payload["registrationRemoved"])
        self.assertFalse(installed_dir.exists())


if __name__ == "__main__":
    unittest.main()
