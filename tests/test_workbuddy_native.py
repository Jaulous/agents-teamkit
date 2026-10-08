"""WorkBuddy adapter behavior: native sync, generated prompts, launcher, install, audit."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from teamkit.fsutil import yaml  # noqa: E402  (installed PyYAML or the vendored copy)

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "teamkit" / "cli.py"
EXAMPLE = ROOT / "examples" / "risk-review-team"
SESSION = "sess-lead-0001"


def now_ms() -> int:
    return int(time.time() * 1000)


class WorkBuddyFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.workdir = Path(self.tmp.name)
        shutil.copytree(EXAMPLE, self.workdir / "team")
        for leftover in ("runs", "build"):
            shutil.rmtree(self.workdir / "team" / leftover, ignore_errors=True)
        self.config = self.workdir / "wb-config"
        self.config.mkdir()
        self.env = os.environ.copy()
        self.env.update({
            "TEAMKIT_HOST": "workbuddy",
            "TEAMKIT_HOST_PACKAGE": "risk-review",
            "CODEBUDDY_SESSION_ID": SESSION,
            "WORKBUDDY_CONFIG_DIR": str(self.config),
            "TEAMKIT_RUNS_DIR": str(self.workdir / "runs"),
        })

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def tk(self, *args: str, check: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(CLI), "--team", str(self.workdir / "team" / "team.yaml"), *args],
            cwd=self.workdir, text=True, capture_output=True, check=False, env=env or self.env,
        )
        if check and result.returncode != 0:
            self.fail(f"teamkit {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")
        return result

    def tk_json(self, *args: str) -> dict:
        return json.loads(self.tk(*args, "--json").stdout)

    # ------------------------------------------------------------------ native fixtures

    def native_team(self, name: str, members: list[dict], session: str = SESSION) -> Path:
        team_dir = self.config / "teams" / name
        (team_dir / "inboxes").mkdir(parents=True)
        lead = {"agentId": f"team-lead@{name}", "name": "team-lead", "agentType": "risk-review-team-lead",
                "joinedAt": now_ms(), "cwd": str(self.workdir), "subscriptions": []}
        config = {"name": name, "createdAt": now_ms(), "leadAgentId": f"team-lead@{name}",
                  "leadSessionId": session, "members": [lead, *members]}
        (team_dir / "config.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        return team_dir

    def member(self, agent_type: str, prompt: str, name: str | None = None) -> dict:
        return {"agentId": f"{name or agent_type}@x", "name": name or agent_type, "agentType": agent_type,
                "prompt": prompt, "joinedAt": now_ms(), "backendType": "in-process", "cwd": str(self.workdir)}

    def inbox(self, team_dir: Path, owner: str, entries: list[dict]) -> None:
        path = team_dir / "inboxes" / f"{owner}.json"
        existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        path.write_text(json.dumps(existing + entries, ensure_ascii=False), encoding="utf-8")

    def transcript(self, rows: list[dict], session: str = SESSION) -> Path:
        path = self.config / "projects" / "Users-test-task" / f"{session}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return path

    @staticmethod
    def teammate_row(sender: str, text: str, summary: str = "") -> dict:
        body = f'<teammate-message teammate_id="{sender}" summary="{summary}">\n{text}\n</teammate-message>'
        return {"type": "message", "role": "user", "timestamp": now_ms(), "content": [{"type": "input_text", "text": body}]}

    def iso_now(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


class NativeSyncTest(WorkBuddyFixture):
    def test_session_bound_run_syncs_native_dispatch_and_reply_and_unblocks_graph(self) -> None:
        init = self.tk_json("run", "init", "--run", "case-1")
        self.assertIn("material_intake", init["nextStep"])
        state = yaml.safe_load((self.workdir / "runs" / "case-1" / "state.yaml").read_text(encoding="utf-8"))
        self.assertEqual(state["host"]["sessionId"], SESSION)
        self.assertEqual(state["host"]["platform"], "workbuddy")

        team_dir = self.native_team("risk-review-ab12", [
            self.member("risk-review-intake", "[TeamKit run=case-1 node=material_intake]\n请整理材料并列出缺失项"),
        ])
        blocked = self.tk_json("graph", "next", "--run", "case-1")
        self.assertTrue(blocked["blocked"])
        self.assertEqual(len(blocked["openMessages"]), 1)

        # The member's report reaches the lead; WorkBuddy keeps it in the lead transcript.
        self.transcript([self.teammate_row("risk-review-intake", "[TeamKit run=case-1 node=material_intake]\n材料齐全，无缺失项", "材料齐全")])
        status = self.tk_json("run", "status", "--run", "case-1")
        self.assertEqual(status["host"]["nativeTeam"], "risk-review-ab12")
        self.assertEqual(status["host"]["matchedBy"], "leadSessionId")
        self.assertEqual(status["open_messages"], [])
        self.assertEqual(status["sync"]["newMessages"], 1)
        messages = self.tk_json("msg", "list", "--run", "case-1", "--no-sync")
        result = next(m for m in messages if m["from"] == "intake")
        dispatch = next(m for m in messages if m["to"] == "intake")
        self.assertEqual(result["replyTo"], dispatch["id"])
        self.assertEqual(dispatch["status"], "replied")
        self.assertEqual(result["native"]["via"], "transcript")

        again = self.tk_json("run", "status", "--run", "case-1")
        self.assertEqual(again["sync"]["newMessages"], 0)
        self.assertEqual(again["sync"]["newEvents"], 0)

        advanced = self.tk_json("graph", "advance", "--run", "case-1", "--summary", "材料初审完成")
        self.assertEqual(advanced["current_node"], "evidence_check")

        # A member-to-member message outside the allowed routes is recorded and flagged.
        self.inbox(team_dir, "risk-review-intake", [{
            "from": "risk-review-evidence", "text": "[TeamKit run=case-1 node=evidence_check]\n直接问你一下", "summary": "越权直连",
            "timestamp": self.iso_now(), "read": True,
        }])
        audit = self.tk_json("run", "audit", "--run", "case-1")
        self.assertEqual(audit["verdict"], "FAIL")
        checks = {c["check"]: c for c in audit["checks"]}
        self.assertEqual(checks["violation:unauthorized_route"]["status"], "FAIL")
        self.assertEqual(checks["host_binding"]["status"], "PASS")

    def test_member_names_and_duplicates_are_checked(self) -> None:
        self.tk("run", "init", "--run", "case-2")
        self.native_team("risk-review-cd34", [
            self.member("risk-review-evidence", "[TeamKit run=case-2 node=evidence_check]\n核验", name="evidence"),
            self.member("risk-review-evidence", "[TeamKit run=case-2 node=evidence_check]\n再核验", name="evidence-2"),
            self.member("general-purpose", "[TeamKit run=case-2]\n随便查查", name="helper"),
        ])
        self.tk("run", "status", "--run", "case-2")
        events = [json.loads(line) for line in (self.workdir / "runs" / "case-2" / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        kinds = sorted(e["kind"] for e in events if e["type"] == "protocol.violation")
        self.assertIn("duplicate_member", kinds)
        self.assertIn("noncanonical_member_name", kinds)
        self.assertIn("unknown_member", kinds)

    def test_respawn_after_failure_is_not_a_violation(self) -> None:
        self.tk("run", "init", "--run", "case-3")
        team_dir = self.native_team("risk-review-ef56", [
            self.member("risk-review-evidence", "[TeamKit run=case-3 node=evidence_check]\n核验"),
            self.member("risk-review-evidence", "[TeamKit run=case-3 node=evidence_check]\n重新核验", name="risk-review-evidence-2"),
        ])
        self.transcript([self.teammate_row(
            "system", '[Framework Auto-Notification]\nTeammate "risk-review-evidence" failed.\nError: 429', "failed")])
        self.tk("run", "status", "--run", "case-3")
        events = [json.loads(line) for line in (self.workdir / "runs" / "case-3" / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertFalse([e for e in events if e.get("kind") == "duplicate_member"])
        self.assertTrue([e for e in events if e["type"] == "member.failed"])
        self.assertTrue(team_dir.exists())

    def test_subagent_dispatch_is_recorded_and_flagged(self) -> None:
        self.tk("run", "init", "--run", "case-4")
        self.native_team("risk-review-gh78", [])
        self.transcript([
            {"type": "function_call", "name": "Agent", "callId": "call-1", "timestamp": now_ms(),
             "arguments": json.dumps({"subagent_type": "risk-review-policy", "description": "规则判断",
                                      "prompt": "[TeamKit run=case-4 node=policy_review]\n判断规则"})},
            {"type": "function_call_result", "name": "Agent", "callId": "call-1", "timestamp": now_ms(),
             "status": "completed", "output": {"type": "text", "text": "规则判断：适用规则 R1"}},
        ])
        audit = self.tk_json("run", "audit", "--run", "case-4")
        checks = {c["check"]: c for c in audit["checks"]}
        self.assertEqual(checks["violation:subagent_dispatch"]["status"], "FAIL")
        messages = self.tk_json("msg", "list", "--run", "case-4", "--no-sync")
        self.assertEqual({(m["from"], m["to"]) for m in messages}, {("decision", "policy"), ("policy", "decision")})

    def test_unheaded_messages_are_ambiguous_when_runs_share_a_native_team(self) -> None:
        self.tk("run", "init", "--run", "order-a")
        self.tk("run", "init", "--run", "order-b")
        team_dir = self.native_team("risk-review-ij90", [])
        self.tk("run", "bind", "--run", "order-a", "--native-team", "risk-review-ij90")
        self.tk("run", "bind", "--run", "order-b", "--native-team", "risk-review-ij90")
        self.inbox(team_dir, "risk-review-evidence", [
            {"from": "team-lead", "text": "没有标识头的派发", "summary": "无头", "timestamp": self.iso_now()},
            {"from": "team-lead", "text": "[TeamKit run=order-b node=evidence_check]\n带标识头的派发", "summary": "有头",
             "timestamp": self.iso_now()},
        ])
        report_a = self.tk_json("workbuddy", "sync", "--run", "order-a")
        report_b = self.tk_json("workbuddy", "sync", "--run", "order-b")
        self.assertEqual(report_a["newMessages"], 0)
        self.assertEqual(report_a["unattributed"], 1)
        self.assertEqual(report_b["newMessages"], 1)

    def test_unbound_run_audit_is_unverified(self) -> None:
        env = {k: v for k, v in self.env.items() if k not in {"TEAMKIT_HOST", "CODEBUDDY_SESSION_ID"}}
        self.tk("run", "init", "--run", "plain", env=env)
        audit = json.loads(self.tk("run", "audit", "--run", "plain", "--json", env=env).stdout)
        self.assertEqual(audit["verdict"], "UNVERIFIED")


class RuntimeSemanticsTest(WorkBuddyFixture):
    def test_force_advance_requires_reason_and_is_audited(self) -> None:
        env = {k: v for k, v in self.env.items() if k not in {"TEAMKIT_HOST", "CODEBUDDY_SESSION_ID"}}
        self.tk("run", "init", "--run", "force-1", env=env)
        self.tk("msg", "send", "--run", "force-1", "--from", "intake", "--to", "evidence", "--subject", "s",
                "--body", "b", "--response", "required", env=env)
        blocked = self.tk("graph", "advance", "--run", "force-1", check=False, env=env)
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("--force", blocked.stderr)
        no_reason = self.tk("graph", "advance", "--run", "force-1", "--force", check=False, env=env)
        self.assertIn("--reason", no_reason.stderr)
        self.tk("graph", "advance", "--run", "force-1", "--force", "--reason", "reply arrived by phone", env=env)
        audit = json.loads(self.tk("run", "audit", "--run", "force-1", "--json", env=env).stdout)
        self.assertIn("forced_advances", {c["check"] for c in audit["checks"]})

    def test_reply_by_send_is_correlated_but_questions_are_not(self) -> None:
        env = {k: v for k, v in self.env.items() if k not in {"TEAMKIT_HOST", "CODEBUDDY_SESSION_ID"}}
        self.tk("run", "init", "--run", "corr", env=env)
        request = self.tk("msg", "send", "--run", "corr", "--from", "decision", "--to", "evidence", "--subject", "补证据",
                          "--body", "请补充", "--response", "required", env=env).stdout.strip()
        self.tk("msg", "send", "--run", "corr", "--from", "evidence", "--to", "decision", "--type", "escalation",
                "--subject", "确认范围", "--body", "只核验近 30 天吗？", env=env)
        status = json.loads(self.tk("run", "status", "--run", "corr", "--json", env=env).stdout)
        self.assertIn(request, status["open_messages"])  # an escalation never answers a request
        self.tk("msg", "send", "--run", "corr", "--from", "evidence", "--to", "decision", "--subject", "证据已补",
                "--body", "见附件", env=env)
        status = json.loads(self.tk("run", "status", "--run", "corr", "--json", env=env).stdout)
        self.assertNotIn(request, status["open_messages"])

    def test_close_status_and_non_blocking_human_input(self) -> None:
        env = {k: v for k, v in self.env.items() if k not in {"TEAMKIT_HOST", "CODEBUDDY_SESSION_ID"}}
        self.tk("run", "init", "--run", "h-1", env=env)
        self.tk("human", "request", "--run", "h-1", "--from", "decision", "--reason", "提醒", "--question", "后续补件",
                "--non-blocking", env=env)
        status = json.loads(self.tk("run", "status", "--run", "h-1", "--json", env=env).stdout)
        self.assertEqual(status["status"], "prepared")
        self.assertFalse(status["graph"]["blocked"])
        self.tk("msg", "send", "--run", "h-1", "--from", "intake", "--to", "evidence", "--subject", "s", "--body", "b",
                "--response", "required", env=env)
        closed = json.loads(self.tk("run", "close", "--run", "h-1", "--status", "cancelled", "--json", env=env).stdout)
        self.assertEqual(closed["status"], "cancelled")
        self.assertEqual(len(closed["closedMessages"]), 1)
        topic = json.loads(self.tk("topic", "status", "--run", "h-1", "--json", env=env).stdout)
        self.assertEqual(topic["status"], "resolved")
        self.assertTrue(all(item["status"] == "done" for item in topic["active_nodes"]))

    def test_damaged_ledger_line_does_not_stall_the_run(self) -> None:
        env = {k: v for k, v in self.env.items() if k not in {"TEAMKIT_HOST", "CODEBUDDY_SESSION_ID"}}
        self.tk("run", "init", "--run", "dmg", env=env)
        messages = self.workdir / "runs" / "dmg" / "messages.jsonl"
        messages.write_text('{"id": "msg_truncated", "from": "in', encoding="utf-8")
        self.tk("msg", "send", "--run", "dmg", "--from", "intake", "--to", "evidence", "--subject", "s", "--body", "b", env=env)
        status = json.loads(self.tk("run", "status", "--run", "dmg", "--json", env=env).stdout)
        self.assertEqual(status["message_count"], 1)
        self.assertTrue(status["ledgerWarnings"])
        audit = json.loads(self.tk("run", "audit", "--run", "dmg", "--json", env=env).stdout)
        self.assertEqual({c["check"]: c["status"] for c in audit["checks"]}["ledger_integrity"], "FAIL")

    def test_force_init_archives_instead_of_deleting(self) -> None:
        env = {k: v for k, v in self.env.items() if k not in {"TEAMKIT_HOST", "CODEBUDDY_SESSION_ID"}}
        self.tk("run", "init", "--run", "again", env=env)
        self.tk("msg", "send", "--run", "again", "--from", "intake", "--to", "evidence", "--subject", "s", "--body", "b", env=env)
        result = json.loads(self.tk("run", "init", "--run", "again", "--force", "--json", env=env).stdout)
        self.assertTrue(Path(result["archivedPrevious"]).exists())
        status = json.loads(self.tk("run", "status", "--run", "again", "--json", env=env).stdout)
        self.assertEqual(status["message_count"], 0)

    def test_graph_shape_warnings(self) -> None:
        team_file = self.workdir / "team" / "team.yaml"
        data = yaml.safe_load(team_file.read_text(encoding="utf-8"))
        graph = data["process"]["graph"]
        graph["nodes"].append({"id": "orphan", "expert": "qa", "task": "never reached"})
        graph["edges"].append({"from": "decision_draft", "to": "policy_review", "relation": "parallel"})
        team_file.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        result = self.tk("team", "validate")
        self.assertIn("orphan is unreachable", result.stderr)
        self.assertIn("mixes parallel and choice edges", result.stderr)


class PackageTest(WorkBuddyFixture):
    def export(self) -> Path:
        out = self.workdir / "build"
        payload = self.tk_json("workbuddy", "export", "--out", str(out), "--force")
        return Path(payload["packageDir"])

    def test_generated_prompts_compile_graph_and_roster(self) -> None:
        package = self.export()
        roster = json.loads((package / "teamkit-workspace" / "roster.json").read_text(encoding="utf-8"))
        self.assertEqual(roster["coordinator"], "decision")
        self.assertEqual(roster["experts"]["decision"]["nativeName"], "team-lead")
        self.assertEqual(roster["experts"]["evidence"]["agentId"], "risk-review-evidence")
        lead = (package / "agents" / "risk-review-team-lead.md").read_text(encoding="utf-8")
        frontmatter = yaml.safe_load(lead.split("---")[1])
        self.assertEqual(frontmatter["name"], "risk-review-team-lead")
        self.assertEqual(frontmatter["skills"], ["teamkit-runtime"])
        self.assertNotIn("tools:", lead.split("---")[1])
        for node in ("material_intake", "evidence_check", "policy_review", "decision_draft", "qa_review"):
            self.assertIn(f"`{node}`", lead)
        self.assertIn("--to policy_review", lead)
        self.assertIn("--to decision_draft", lead)
        self.assertIn("最多进入 2 次", lead)
        self.assertIn("`risk-review-evidence`", lead)
        member = (package / "agents" / "risk-review-evidence.md").read_text(encoding="utf-8")
        self.assertIn("`risk-review-policy`", member)  # evidence -> policy is an explicit rule
        self.assertIn("风控规则说明", (package / "agents" / "risk-review-policy.md").read_text(encoding="utf-8"))
        self.assertNotIn("风控规则说明", (package / "agents" / "risk-review-intake.md").read_text(encoding="utf-8"))

        validator = Path("/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/resources/builtin-skills/expert-manager/scripts/validate_expert.py")
        if validator.is_file():
            experts_dir = self.config / "plugins" / "marketplaces" / "my-experts" / "plugins"
            experts_dir.mkdir(parents=True)
            shutil.copytree(package, experts_dir / "risk-review")
            check = subprocess.run([sys.executable, str(validator), str(experts_dir / "risk-review")], text=True,
                                   capture_output=True, env={**self.env, "WORKBUDDY_CONFIG_DIR": str(self.config)})
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
            self.assertNotIn("warning", check.stdout.lower())

    def test_installed_launcher_runs_vendored_runtime_without_site_packages(self) -> None:
        package = self.export()
        env = {k: v for k, v in self.env.items() if k not in {"TEAMKIT_HOST", "TEAMKIT_HOST_PACKAGE", "TEAMKIT_RUNS_DIR"}}
        env["WORKBUDDY_APP_PATH"] = str(self.workdir / "no-app")
        install = json.loads(subprocess.run(
            [sys.executable, str(CLI), "workbuddy", "install", "--package", str(package), "--config-dir", str(self.config),
             "--force", "--json"], text=True, capture_output=True, env=env, check=True).stdout)
        self.assertEqual(install["officialValidation"], "skipped")
        self.assertTrue(install["warnings"])
        installed = Path(install["installedDir"])
        launcher = installed / "skills" / "teamkit-runtime" / "scripts" / "teamkit"
        self.assertIn(launcher.as_posix(), (installed / "agents" / "risk-review-team-lead.md").read_text(encoding="utf-8"))

        env["TEAMKIT_PYTHON"] = sys.executable
        run = subprocess.run([str(launcher), "run", "init", "--run", "wb-1", "--json"], text=True,
                             capture_output=True, env=env, cwd=self.workdir)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue((self.config / "teamkit-runs" / "risk-review" / "wb-1" / "state.yaml").exists())
        state = yaml.safe_load((self.config / "teamkit-runs" / "risk-review" / "wb-1" / "state.yaml").read_text(encoding="utf-8"))
        self.assertEqual(state["host"]["package"], "risk-review")

        # The vendored YAML keeps the runtime working with no site-packages at all.
        bare = subprocess.run([sys.executable, "-S", str(installed / "vendor" / "teamkit_entry.py"), "run", "status",
                               "--run", "wb-1", "--json", "--no-sync"], text=True, capture_output=True, env=env)
        self.assertEqual(bare.returncode, 0, bare.stderr)

        strict = subprocess.run(
            [sys.executable, str(CLI), "workbuddy", "install", "--package", str(package), "--config-dir", str(self.config),
             "--force", "--strict"], text=True, capture_output=True, env=env)
        self.assertNotEqual(strict.returncode, 0)

        doctor = json.loads(subprocess.run([sys.executable, str(CLI), "workbuddy", "doctor", "--config-dir", str(self.config), "--json"],
                                           text=True, capture_output=True, env=env).stdout)
        self.assertIn("package:risk-review", {c["check"] for c in doctor["checks"]})

    def test_expert_id_colliding_with_lead_agent_is_rejected(self) -> None:
        team_file = self.workdir / "team" / "team.yaml"
        data = yaml.safe_load(team_file.read_text(encoding="utf-8"))
        data["experts"].append({"id": "team-lead", "name": "冒名", "profile": "experts/qa.md"})
        team_file.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        result = self.tk("workbuddy", "export", "--out", str(self.workdir / "build"), "--force", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("lead Agent ID", result.stderr)


if __name__ == "__main__":
    unittest.main()
