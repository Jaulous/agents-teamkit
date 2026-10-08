from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from teamkit.fsutil import yaml  # noqa: E402  (installed PyYAML or the vendored copy)


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
        env = os.environ.copy()
        env["TEAMKIT_SKIP_RUNTIME_ENV"] = "1"
        result = subprocess.run(
            [sys.executable, str(CLI), *args],
            cwd=self.workdir,
            text=True,
            capture_output=True,
            check=False,
            env=env,
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

    def test_home_and_external_run_root_keep_all_run_files_together(self) -> None:
        team_file = self.workdir / "team.yaml"
        data = yaml.safe_load(team_file.read_text(encoding="utf-8"))
        data.pop("workspace", None)
        team_file.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        external = self.workdir / "external-runs"
        env = os.environ.copy()
        env["TEAMKIT_SKIP_RUNTIME_ENV"] = "1"
        env["TEAMKIT_RUNS_DIR"] = str(external)
        result = subprocess.run(
            [sys.executable, str(CLI), "--team", "team.yaml", "run", "init", "--run", "external-001"],
            cwd=self.workdir, text=True, capture_output=True, check=False, env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((external / "external-001" / "state.yaml").exists())
        self.assertTrue((external / "external-001" / "artifacts" / "artifacts.jsonl").exists())
        self.assertFalse((self.workdir / "runs" / "external-001" / "state.yaml").exists())
        home = self.run_cli("home", "--team", "team.yaml", "--run", "external-001", "--json")
        payload = json.loads(home.stdout)
        self.assertEqual(payload["runBaseSource"], "default")

    def test_parallel_fork_join_and_batch_ledger(self) -> None:
        team_file = self.workdir / "team.yaml"
        data = yaml.safe_load(team_file.read_text(encoding="utf-8"))
        nodes = data["process"]["graph"]["nodes"]
        nodes.extend([
            {"id": "parallel_a", "expert": "evidence", "task": "A"},
            {"id": "parallel_b", "expert": "policy", "task": "B"},
            {"id": "join_node", "expert": "decision", "task": "Join", "join": "all"},
        ])
        data["process"]["graph"]["edges"] = [
            {"from": "material_intake", "to": "parallel_a", "relation": "parallel"},
            {"from": "material_intake", "to": "parallel_b", "relation": "parallel"},
            {"from": "parallel_a", "to": "join_node", "relation": "parallel"},
            {"from": "parallel_b", "to": "join_node", "relation": "parallel"},
        ]
        team_file.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        self.run_cli("run", "init", "--team", "team.yaml", "--run", "parallel-001")
        fork = self.run_cli("graph", "advance", "--team", "team.yaml", "--run", "parallel-001", "--json")
        fork_payload = json.loads(fork.stdout)
        self.assertEqual({item["currentNode"] for item in fork_payload["activeNodes"]}, {"parallel_a", "parallel_b"})
        self.run_cli("graph", "advance", "--team", "team.yaml", "--run", "parallel-001", "--node", "parallel_a")
        blocked = json.loads(self.run_cli("graph", "next", "--team", "team.yaml", "--run", "parallel-001", "--json").stdout)
        self.assertTrue(any(item["currentNode"] == "parallel_b" for item in blocked["activeNodes"]))
        self.run_cli("graph", "advance", "--team", "team.yaml", "--run", "parallel-001", "--node", "parallel_b")
        topic = json.loads(self.run_cli("topic", "status", "--team", "team.yaml", "--run", "parallel-001", "--json").stdout)
        self.assertEqual(topic["active_nodes"][0]["node"], "join_node")

        cases_dir = self.workdir / "cases"
        cases_dir.mkdir()
        (cases_dir / "a.md").write_text("a", encoding="utf-8")
        (cases_dir / "b.md").write_text("b", encoding="utf-8")
        init = json.loads(self.run_cli("batch", "init", "--team", "team.yaml", "--batch", "smoke", "--cases-dir", "cases", "--json").stdout)
        next_payload = json.loads(self.run_cli("batch", "next", "--team", "team.yaml", "--batch", init["batchId"], "--max", "2").stdout)
        self.assertEqual(len(next_payload["cases"]), 2)
        self.assertEqual(next_payload["counts"]["running"], 2)

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
        self.assertEqual(plan["commandContract"]["run"], "teamkit run init/status/close/audit/bind")
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
        self.assertFalse((self.workdir / "runs" / "case-001" / "artifacts" / "final").exists())
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
        )
        premature_artifact_id = premature_final.stdout.strip()
        self.assertRegex(premature_artifact_id, r"^art_[0-9a-f]{24}$")
        premature_archive = self.workdir / "runs" / "case-001" / "artifacts" / "final" / f"{premature_artifact_id}.md"
        self.assertTrue(premature_archive.exists())
        waiting_status = json.loads(
            self.run_cli("run", "status", "--team", "team.yaml", "--run", "case-001", "--json").stdout
        )
        self.assertNotEqual(waiting_status["status"], "completed")
        self.assertEqual(waiting_status["topic"]["status"], "waiting")

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

        active_status_result = self.run_cli(
            "run", "status", "--team", "team.yaml", "--run", "case-001", "--json"
        )
        active_status = json.loads(active_status_result.stdout)
        self.assertNotEqual(active_status["status"], "completed")
        self.assertEqual(active_status["topic"]["status"], "active")

        self.run_cli(
            "run",
            "close",
            "--team",
            "team.yaml",
            "--run",
            "case-001",
            "--by",
            "decision",
        )

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
        self.assertTrue(status["final_result"]["path"].startswith("runs/case-001/artifacts/final/"))
        self.assertNotEqual(status["final_result"]["path"], "runs/case-001/final-report.md")

        done_graph_result = self.run_cli(
            "graph", "next", "--team", "team.yaml", "--run", "case-001", "--json"
        )
        done_graph = json.loads(done_graph_result.stdout)
        self.assertTrue(done_graph["blocked"])
        self.assertEqual(done_graph["reason"], "topic is resolved")

    def test_run_close_without_result_and_duplicate_close(self) -> None:
        self.run_cli("run", "init", "--team", "team.yaml", "--run", "close-demo")
        self.run_cli("run", "close", "--team", "team.yaml", "--run", "close-demo", "--by", "test")
        status = json.loads(
            self.run_cli("run", "status", "--team", "team.yaml", "--run", "close-demo", "--json").stdout
        )
        self.assertEqual(status["status"], "completed")
        self.assertIsNone(status["final_result"])
        self.assertEqual(status["topic"]["status"], "resolved")
        graph = json.loads(
            self.run_cli("graph", "next", "--team", "team.yaml", "--run", "close-demo", "--json").stdout
        )
        self.assertTrue(graph["blocked"])
        self.assertEqual(graph["reason"], "topic is resolved")

        duplicate = self.run_cli(
            "run", "close", "--team", "team.yaml", "--run", "close-demo", check=False
        )
        self.assertEqual(duplicate.returncode, 2)
        self.assertIn("run already closed", duplicate.stderr)

    def test_result_publish_archives_without_closing_or_business_gates(self) -> None:
        self.run_cli("run", "init", "--team", "team.yaml", "--run", "archive-demo")
        message = self.run_cli(
            "msg",
            "send",
            "--team",
            "team.yaml",
            "--run",
            "archive-demo",
            "--from",
            "intake",
            "--to",
            "evidence",
            "--subject",
            "Required handoff",
            "--body",
            "A reply remains open while the result is archived.",
            "--response",
            "required",
        )
        message_id = message.stdout.strip()
        result = self.run_cli(
            "result",
            "publish",
            "--team",
            "team.yaml",
            "--run",
            "archive-demo",
            "--from",
            "decision",
            "--file",
            "runs/archive-demo/experts/decision/result.md",
        )
        artifact_id = result.stdout.strip()
        self.assertRegex(artifact_id, r"^art_[0-9a-f]{24}$")
        archive = self.workdir / "runs" / "archive-demo" / "artifacts" / "final" / f"{artifact_id}.md"
        self.assertTrue(archive.exists())
        self.assertFalse((self.workdir / "runs" / "archive-demo" / "final-report.md").exists())
        status = json.loads(
            self.run_cli("run", "status", "--team", "team.yaml", "--run", "archive-demo", "--json").stdout
        )
        self.assertNotEqual(status["status"], "completed")
        self.assertEqual(status["open_messages"], [message_id])
        self.assertEqual(status["topic"]["status"], "active")

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
        launcher_path = package_dir / "skills" / "teamkit-runtime" / "scripts" / "teamkit"
        self.assertTrue(launcher_path.exists())
        self.assertTrue(os.access(launcher_path, os.X_OK))
        self.assertNotIn(".agents-teamkit-runtime", launcher_path.read_text(encoding="utf-8"))
        self.assertTrue((package_dir / "teamkit-workspace" / "team.yaml").exists())
        self.assertTrue((package_dir / "teamkit-workspace" / "roster.json").exists())
        self.assertTrue((package_dir / "vendor" / "teamkit" / "cli.py").exists())
        self.assertTrue((package_dir / "vendor" / "teamkit" / "_vendor" / "yaml" / "__init__.py").exists())

        plugin = json.loads((package_dir / ".codebuddy-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(plugin["expertType"], "team")
        self.assertEqual(plugin["teamInfo"]["leadAgent"], plugin["agentName"])
        self.assertNotIn(plugin["agentName"], plugin["teamInfo"]["memberAgents"])
        self.assertEqual(len(plugin["tags"]), 3)
        self.assertEqual(len(plugin["quickPrompts"]), 3)

        # Generated agents follow the native-first protocol: native tools carry
        # every message and TeamKit only needs run/graph/result commands.
        lead_md = package_dir / "agents" / f"{plugin['agentName']}.md"
        lead_text = lead_md.read_text(encoding="utf-8")
        self.assertIn("TeamCreate", lead_text)
        self.assertIn("name` 与 `subagent_type` 都必须填 **Agent ID**", lead_text)
        self.assertIn("[TeamKit run=<run-id> node=<节点ID>]", lead_text)
        self.assertIn("graph advance --run <run-id>", lead_text)
        self.assertIn("禁止重复创建同一成员", lead_text)
        self.assertIn("审核结论专家", lead_text)  # coordinator profile is embedded
        self.assertNotIn("TeamKit Rules", lead_text)
        self.assertNotIn("msg send", lead_text.split("账本说明")[0])
        for member in plugin["teamInfo"]["memberAgents"]:
            text = (package_dir / "agents" / f"{member}.md").read_text(encoding="utf-8")
            self.assertIn("recipient`=`team-lead`", text)
            self.assertIn(f"Agent ID `{member}`", text)
            self.assertNotIn("TeamKit Rules", text)

        skill_text = (package_dir / "skills" / "teamkit-runtime" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("run status --run <run-id>", skill_text)

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
            [str(installed_dir / "skills" / "teamkit-runtime" / "scripts" / "teamkit"), "team", "validate"],
            cwd=self.workdir,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(wrapper_result.returncode, 0, wrapper_result.stderr)
        self.assertIn("valid team definition", wrapper_result.stdout)

    def test_workbuddy_export_packages_declared_external_skill_and_avatars(self) -> None:
        skill_dir = self.workdir / "custom-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: custom-skill\ndescription: A test skill\n---\n\n# Custom Skill\n",
            encoding="utf-8",
        )
        (self.workdir / "workbuddy.yaml").write_text(
            "skills:\n  - name: custom-skill\n    path: custom-skill\n    agents:\n      - evidence\n",
            encoding="utf-8",
        )
        avatars = self.workdir / "avatars"
        avatars.mkdir()
        (avatars / "team.png").write_bytes(b"team-avatar")

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
        package_dir = Path(json.loads(result.stdout)["packageDir"])
        plugin = json.loads((package_dir / ".codebuddy-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertIn("./skills/custom-skill", plugin["skills"])
        self.assertTrue((package_dir / "skills" / "custom-skill" / "SKILL.md").exists())
        self.assertEqual(plugin["avatar"], "avatars/team.png")
        self.assertTrue((package_dir / "avatars" / "team.png").exists())
        evidence_md = (package_dir / "agents" / "risk-review-evidence.md").read_text(encoding="utf-8")
        self.assertIn("skills: [teamkit-runtime, custom-skill]", evidence_md)
        self.assertNotIn("custom-skill", (package_dir / "agents" / "risk-review-team-lead.md").read_text(encoding="utf-8"))

    def test_workbuddy_export_failure_preserves_previous_package(self) -> None:
        first = self.run_cli(
            "workbuddy",
            "export",
            "--team",
            "team.yaml",
            "--out",
            "build/workbuddy",
            "--force",
            "--json",
        )
        package_dir = Path(json.loads(first.stdout)["packageDir"])
        sentinel = package_dir / "sentinel.txt"
        sentinel.write_text("keep", encoding="utf-8")

        # A malformed adapter manifest fails before publication.  The already
        # published package must remain intact even when --force is requested.
        (self.workdir / "workbuddy.yaml").write_text("skills: not-a-list\n", encoding="utf-8")
        failed = self.run_cli(
            "workbuddy",
            "export",
            "--team",
            "team.yaml",
            "--out",
            "build/workbuddy",
            "--force",
            check=False,
        )
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_workbuddy_export_init_failure_preserves_previous_package(self) -> None:
        first = self.run_cli(
            "workbuddy",
            "export-init",
            "--out",
            "build/workbuddy",
            "--force",
            "--json",
        )
        package_dir = Path(json.loads(first.stdout)["packageDir"])
        sentinel = package_dir / "sentinel.txt"
        sentinel.write_text("keep", encoding="utf-8")

        # Exercise the staging failure path directly without changing source
        # files: the package builder must leave the previous package untouched.
        from teamkit.adapters.workbuddy import package as package_module
        from teamkit.errors import TeamKitError

        original = package_module.write_launcher
        package_module.write_launcher = lambda _skill_dir: (_ for _ in ()).throw(
            TeamKitError("injected export failure")
        )
        try:
            with self.assertRaises(TeamKitError):
                package_module.export_workbench_package(
                    self.workdir / "build" / "workbuddy",
                    "agents-teamkit-workbench",
                    True,
                )
        finally:
            package_module.write_launcher = original
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_workbuddy_install_renders_final_runtime_paths(self) -> None:
        from teamkit.adapters.workbuddy import installer

        staging = self.workdir / "staging"
        target = self.workdir / "installed" / "risk-review"
        launcher = staging / "skills" / "teamkit-runtime" / "scripts" / "teamkit"
        skill = staging / "skills" / "teamkit-runtime" / "SKILL.md"
        agent = staging / "agents" / "risk-review-team-lead.md"
        launcher.parent.mkdir(parents=True)
        agent.parent.mkdir(parents=True)
        launcher.write_text("#!/bin/sh\n", encoding="utf-8")
        skill.write_text("{{TEAMKIT_SCRIPT}} team validate\n", encoding="utf-8")
        agent.write_text("`{{TEAMKIT_SCRIPT}} run status`\n", encoding="utf-8")

        installer.render_launcher_paths(staging, target)

        expected = (target / "skills" / "teamkit-runtime" / "scripts" / "teamkit").as_posix()
        self.assertEqual(skill.read_text(encoding="utf-8"), expected + " team validate\n")
        self.assertIn(expected, agent.read_text(encoding="utf-8"))
        self.assertNotIn(str(staging), skill.read_text(encoding="utf-8"))

    def test_workbuddy_install_rejects_nested_source_and_preserves_target_on_validation_failure(self) -> None:
        export_result = self.run_cli(
            "workbuddy",
            "export",
            "--team",
            "team.yaml",
            "--out",
            "build/workbuddy",
            "--force",
            "--json",
        )
        package_dir = Path(json.loads(export_result.stdout)["packageDir"])
        config_dir = self.workdir / "fake-workbuddy"
        target = config_dir / "plugins" / "marketplaces" / "my-experts" / "plugins" / "risk-review"
        target.mkdir(parents=True)
        sentinel = target / "sentinel.txt"
        sentinel.write_text("keep", encoding="utf-8")

        nested_source = target / "source"
        shutil.copytree(package_dir, nested_source)
        nested_result = self.run_cli(
            "workbuddy",
            "install",
            "--package",
            str(nested_source),
            "--config-dir",
            str(config_dir),
            "--force",
            check=False,
        )
        self.assertNotEqual(nested_result.returncode, 0)
        self.assertTrue(nested_source.exists())
        self.assertTrue(sentinel.exists())

        broken_source = self.workdir / "broken-package"
        shutil.copytree(package_dir, broken_source)
        broken_plugin = broken_source / ".codebuddy-plugin" / "plugin.json"
        plugin = json.loads(broken_plugin.read_text(encoding="utf-8"))
        plugin["skills"].append("./skills/missing-skill")
        broken_plugin.write_text(json.dumps(plugin, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        broken_result = self.run_cli(
            "workbuddy",
            "install",
            "--package",
            str(broken_source),
            "--config-dir",
            str(config_dir),
            "--force",
            check=False,
        )
        self.assertNotEqual(broken_result.returncode, 0)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_profile_protocol_sections_are_replaced_by_adapter_protocol(self) -> None:
        from teamkit.adapters.workbuddy.prompts import strip_protocol_sections

        profile = "# Expert\n\n## Identity\nRole.\n\n## TeamKit Rules\n- use teamkit msg send\n\n## Evidence Rules\n- cite.\n"
        stripped = strip_protocol_sections(profile)
        self.assertNotIn("msg send", stripped)
        self.assertIn("## Evidence Rules", stripped)
        self.assertIn("## Identity", stripped)

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
        self.assertEqual(payload["packageName"], "agents-teamkit-workbench")
        self.assertTrue((package_dir / ".codebuddy-plugin" / "plugin.json").exists())
        self.assertTrue((package_dir / "settings.json").exists())
        self.assertTrue((package_dir / "skills" / "agent-team-builder" / "SKILL.md").exists())
        self.assertTrue((package_dir / "skills" / "agent-prompt-optimizer" / "SKILL.md").exists())
        self.assertTrue((package_dir / "skills" / "agent-team-optimizer" / "SKILL.md").exists())
        source_skill_names = sorted(
            path.name
            for path in (ROOT / "skills").iterdir()
            if path.is_dir() and (path / "SKILL.md").is_file()
        )
        exported_skill_names = sorted(
            path.name
            for path in (package_dir / "skills").iterdir()
            if path.is_dir()
            and path.name != "agents-teamkit-workbench-runtime"
            and (path / "SKILL.md").is_file()
        )
        self.assertEqual(exported_skill_names, source_skill_names)
        launcher_path = package_dir / "skills" / "agents-teamkit-workbench-runtime" / "scripts" / "teamkit"
        self.assertTrue(launcher_path.exists())
        self.assertTrue((package_dir / "docs" / "coordination-model.md").exists())
        self.assertTrue((package_dir / "schemas" / "team.schema.json").exists())
        self.assertTrue((package_dir / "vendor" / "teamkit" / "cli.py").exists())

        plugin = json.loads((package_dir / ".codebuddy-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(plugin["expertType"], "team")
        self.assertEqual(plugin["displayName"]["zh"], "Agents TeamKit 工作台")
        self.assertEqual(plugin["profession"], plugin["displayName"])
        self.assertEqual(plugin["teamInfo"]["leadAgent"], plugin["agentName"])
        self.assertEqual(plugin["teamInfo"]["memberAgents"], [])
        self.assertEqual(
            plugin["skills"],
            [
                "./skills/agent-prompt-optimizer",
                "./skills/agent-team-builder",
                "./skills/agent-team-optimizer",
                "./skills/agents-teamkit-workbench-runtime",
            ],
        )
        lead_frontmatter = (package_dir / "agents" / f"{plugin['agentName']}.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "skills: [agent-prompt-optimizer, agent-team-builder, agent-team-optimizer, agents-teamkit-workbench-runtime]",
            lead_frontmatter,
        )

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
        self.assertTrue(any(item["name"] == "agents-teamkit-workbench" for item in marketplace["plugins"]))
        installed_runtime_skill = (
            installed_dir / "skills" / "agents-teamkit-workbench-runtime" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn(
            (installed_dir / "skills" / "agents-teamkit-workbench-runtime" / "scripts" / "teamkit").as_posix(),
            installed_runtime_skill,
        )
        self.assertNotIn(".agents-teamkit-workbench.install-", installed_runtime_skill)

        wrapper_result = subprocess.run(
            [
                str(installed_dir / "skills" / "agents-teamkit-workbench-runtime" / "scripts" / "teamkit"),
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
            "agents-teamkit-workbench",
            "--config-dir",
            "fake-workbuddy",
            "--force",
            "--json",
        )
        uninstall_payload = json.loads(uninstall_result.stdout)
        self.assertTrue(uninstall_payload["directoryExisted"])
        self.assertTrue(uninstall_payload["registrationRemoved"])
        self.assertFalse(installed_dir.exists())
        self.assertTrue(Path(uninstall_payload["backup"]).exists())  # uninstall never destroys files


if __name__ == "__main__":
    unittest.main()
