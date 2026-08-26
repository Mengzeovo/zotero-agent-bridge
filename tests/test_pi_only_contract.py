from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from zotero_agent_bridge.config import Settings
from zotero_agent_bridge.models import (
    ASSISTANT_IMAGE_MIME_TYPES,
    ASSISTANT_MAX_IMAGES,
    ASSISTANT_MAX_IMAGE_BYTES,
    ASSISTANT_MAX_TOTAL_IMAGE_BYTES,
    PI_THINKING_LEVELS,
    AssistantSaveNoteRequest,
)
from zotero_agent_bridge.service import BridgeService, create_app
from zotero_agent_bridge.version import BRIDGE_VERSION, PRODUCT_NAME, PRODUCT_SCOPE
from zotero_agent_bridge.zotero_local import ZoteroLocalClient


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "pi-only-transition.json"
BASELINE_PATH = ROOT / "docs" / "PI_PLUGIN_CAPABILITY_BASELINE.md"
BOOTSTRAP_PATH = ROOT / "zotero_companion_addon" / "bootstrap.js"
PANEL_PATH = ROOT / "zotero_companion_addon" / "chrome" / "content" / "scripts" / "pi_chat_panel.js"

BRIDGE_CALL_PATTERN = re.compile(
    r'(?:this\.controller\.)?(?:rawBridgeRequest|bridgeRequest)\(\s*'
    r'["\'](?P<method>GET|POST|PUT|PATCH|DELETE)["\']\s*,\s*'
    r'(?P<quote>["\'`])(?P<path>.*?)(?P=quote)',
    re.DOTALL,
)


RoutePair = tuple[str, str]


def load_policy() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def policy_routes(policy: dict[str, Any], key: str) -> set[RoutePair]:
    return {(str(route["method"]), str(route["path"])) for route in policy[key]}


def application_routes() -> dict[RoutePair, APIRoute]:
    settings = SimpleNamespace(api_token="pi-contract-token")
    service = SimpleNamespace(settings=settings)
    lifecycle = SimpleNamespace()
    app = create_app(settings=settings, service=service, lifecycle=lifecycle)
    routes: dict[RoutePair, APIRoute] = {}
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods:
            routes[(method, route.path)] = route
    return routes


def addon_route_calls(path: Path) -> set[RoutePair]:
    source = path.read_text(encoding="utf-8-sig")
    calls: set[RoutePair] = set()
    for match in BRIDGE_CALL_PATTERN.finditer(source):
        route_path = match.group("path").split("?", 1)[0]
        if route_path.startswith("/assistant/experience-note/jobs/${"):
            route_path = "/assistant/experience-note/jobs/{job_id}"
        calls.add((match.group("method"), route_path))
    return calls


class PiOnlyContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = load_policy()
        cls.retained = policy_routes(cls.policy, "retained_http_routes")
        cls.retired = policy_routes(cls.policy, "retired_http_routes")
        cls.routes = application_routes()

    def test_product_metadata_is_zotero_pi_assistant_042(self) -> None:
        manifest = json.loads((ROOT / "zotero_companion_addon" / "manifest.json").read_text(encoding="utf-8-sig"))
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        bootstrap = BOOTSTRAP_PATH.read_text(encoding="utf-8-sig")
        self.assertEqual(PRODUCT_NAME, "Zotero Pi Assistant")
        self.assertEqual(PRODUCT_SCOPE, "zotero-pi-only")
        self.assertEqual(BRIDGE_VERSION, "0.4.2")
        self.assertEqual(manifest["name"], PRODUCT_NAME)
        self.assertEqual(manifest["version"], BRIDGE_VERSION)
        self.assertEqual(manifest["applications"]["zotero"]["id"], "zotero-agent-bridge@local")
        self.assertTrue(readme.startswith("# Zotero Pi Assistant"))
        self.assertIn("**当前版本：0.4.2**", readme)
        self.assertNotIn("syncSelectedNoteToObsidian", bootstrap)
        self.assertNotIn("Sync to Obsidian", bootstrap)

    def test_transition_policy_is_complete_disjoint_and_versioned(self) -> None:
        self.assertEqual(self.policy["schema_version"], 1)
        self.assertEqual(self.policy["product_name"], "Zotero Pi Assistant")
        self.assertEqual(self.policy["product_scope"], "zotero-pi-only")
        self.assertEqual(self.policy["baseline_version"], "0.3.5")
        self.assertEqual(self.policy["transition_release"], "0.4.0-beta")
        self.assertEqual(self.policy["final_removal_release"], "0.4.1-beta")
        self.assertEqual(self.policy["stage_2"]["release"], "0.4.1-beta")
        self.assertEqual(
            self.policy["stage_2"]["http_behavior"],
            "Retired routes remain authenticated compatibility stubs, perform no side effects, and return the transition_error payload.",
        )
        self.assertEqual(len(self.retained), 19)
        self.assertEqual(len(self.retired), 17)
        self.assertFalse(self.retained & self.retired)
        self.assertEqual(len(self.retained), len(self.policy["retained_http_routes"]))
        self.assertEqual(len(self.retired), len(self.policy["retired_http_routes"]))

    def test_current_application_surface_is_retained_plus_authenticated_retirement_stubs(self) -> None:
        self.assertEqual(set(self.routes), self.retained | self.retired)

    def test_every_retained_route_requires_bridge_authentication(self) -> None:
        for route_pair in sorted(self.retained):
            with self.subTest(route=route_pair):
                route = self.routes[route_pair]
                self.assertGreaterEqual(len(route.dependencies), 1)
                self.assertGreaterEqual(len(route.dependant.dependencies), 1)

    def test_every_retired_route_requires_authentication_and_returns_410(self) -> None:
        settings = SimpleNamespace(api_token="pi-contract-token")
        service = SimpleNamespace(settings=settings)
        app = create_app(settings=settings, service=service, lifecycle=SimpleNamespace())
        client = TestClient(app)
        expected_error = self.policy["transition_error"]
        for method, route_path in sorted(self.retired):
            concrete_path = re.sub(r"\{[^}]+\}", "RETIREDKEY", route_path)
            with self.subTest(method=method, path=route_path, authenticated=False):
                unauthenticated = client.request(method, concrete_path, json={})
                self.assertEqual(unauthenticated.status_code, 401, unauthenticated.text)
            with self.subTest(method=method, path=route_path, authenticated=True):
                response = client.request(
                    method,
                    concrete_path,
                    headers={"X-Bridge-Token": settings.api_token},
                    json={},
                )
                self.assertEqual(response.status_code, expected_error["http_status"], response.text)
                error = response.json()["error"]
                self.assertEqual(error["code"], expected_error["code"])
                self.assertEqual(error["message"], expected_error["message"])

    def test_pi_panel_calls_exact_retained_assistant_surface(self) -> None:
        expected = {route for route in self.retained if route[1].startswith("/assistant/")}
        actual = {route for route in addon_route_calls(PANEL_PATH) if route[1].startswith("/assistant/")}
        self.assertEqual(actual, expected)
        self.assertFalse(actual & self.retired)

    def test_bootstrap_calls_retained_lifecycle_and_health_surface(self) -> None:
        expected = {
            ("GET", "/health"),
            ("GET", "/lifecycle"),
            ("POST", "/lifecycle/shutdown"),
        }
        actual = addon_route_calls(BOOTSTRAP_PATH)
        self.assertTrue(expected <= actual)
        self.assertEqual({route for route in actual if route in self.retained}, expected)

    def test_typed_assistant_response_contracts_remain_stable(self) -> None:
        expected_models = {
            ("POST", "/assistant/session/open"): "AssistantSessionOpenResponse",
            ("GET", "/assistant/session/events"): "AssistantEventsResponse",
            ("POST", "/assistant/session/resume"): "AssistantSessionOpenResponse",
            ("POST", "/assistant/session/save-note"): "AssistantSaveNoteResponse",
            ("POST", "/assistant/experience-note/update"): "AssistantExperienceNoteJobAccepted",
            ("GET", "/assistant/experience-note/jobs/{job_id}"): "AssistantExperienceNoteJobStatus",
            ("POST", "/assistant/session/reset"): "AssistantSessionOpenResponse",
        }
        for route_pair, model_name in expected_models.items():
            with self.subTest(route=route_pair):
                model = self.routes[route_pair].response_model
                self.assertIsNotNone(model)
                self.assertEqual(model.__name__, model_name)

    def test_retired_cli_modules_entry_points_and_scripts_are_physically_absent(self) -> None:
        for relative_path in self.policy["retired_scripts"]:
            with self.subTest(path=relative_path):
                self.assertFalse((ROOT / relative_path).exists())
        package_root = ROOT / "zotero_agent_bridge"
        self.assertFalse((package_root / "mcp_server.py").exists())
        self.assertFalse((package_root / "retirement.py").exists())
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertNotIn("zotero-agent-bridge-mcp", pyproject)
        self.assertNotIn("mcp_server", pyproject)

    def test_retired_addon_frontend_resources_are_absent(self) -> None:
        for relative_path in self.policy["retired_addon_resources"]:
            with self.subTest(path=relative_path):
                self.assertFalse((ROOT / relative_path).exists())

    def test_retired_python_implementation_modules_are_absent(self) -> None:
        retired_implementations = {
            "collection_tree.py",
            "doi.py",
            "mirror.py",
            "obsidian.py",
            "paper_classifier.py",
            "pdf_tools.py",
            "mcp_server.py",
            "retirement.py",
        }
        package_root = ROOT / "zotero_agent_bridge"
        self.assertTrue(all(not (package_root / name).exists() for name in retired_implementations))

    def test_runtime_settings_exclude_mirror_and_obsidian_but_preserve_identity_paths(self) -> None:
        self.assertEqual(
            set(Settings.__dataclass_fields__),
            {
                "host",
                "port",
                "api_token",
                "zotero_local_api_base",
                "bridge_home",
                "addon_timeout_seconds",
                "addon_status_ttl_seconds",
                "user_agent",
                "base_attachment_path",
                "pi",
                "lifecycle_owner_id",
                "lifecycle_owner_token",
                "lifecycle_addon_exit_grace_seconds",
                "lifecycle_watchdog_interval_seconds",
            },
        )

    def test_zotero_local_client_exposes_only_pi_bundle_operations(self) -> None:
        public_methods = {
            name
            for name, value in ZoteroLocalClient.__dict__.items()
            if callable(value) and not name.startswith("_")
        }
        self.assertEqual(public_methods, {"is_available", "build_bundle"})

    def test_python_service_public_surface_is_pi_only(self) -> None:
        public_methods = {
            name
            for name, value in BridgeService.__dict__.items()
            if callable(value) and not name.startswith("_")
        }
        self.assertEqual(
            public_methods,
            {
                "health",
                "open_assistant_session",
                "send_assistant_message",
                "assistant_events",
                "assistant_messages",
                "assistant_session_history",
                "resume_assistant_session",
                "assistant_models",
                "select_assistant_model",
                "assistant_thinking_levels",
                "select_assistant_thinking_level",
                "assistant_status",
                "save_assistant_note",
                "update_experience_note",
                "experience_note_job_status",
                "abort_assistant_session",
                "reset_assistant_session",
                "shutdown",
            },
        )

    def test_note_save_scope_request_fields_are_frozen(self) -> None:
        self.assertEqual(
            set(AssistantSaveNoteRequest.model_fields),
            {
                "item_key",
                "attachment_key",
                "context_fingerprint",
                "document_id",
                "answer",
                "question",
                "title",
            },
        )

    def test_image_and_thinking_contract_limits_are_frozen(self) -> None:
        self.assertEqual(
            ASSISTANT_IMAGE_MIME_TYPES,
            frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"}),
        )
        self.assertEqual(ASSISTANT_MAX_IMAGES, 4)
        self.assertEqual(ASSISTANT_MAX_IMAGE_BYTES, 10 * 1024 * 1024)
        self.assertEqual(ASSISTANT_MAX_TOTAL_IMAGE_BYTES, 20 * 1024 * 1024)
        self.assertEqual(
            PI_THINKING_LEVELS,
            frozenset({"off", "minimal", "low", "medium", "high", "xhigh", "max"}),
        )

    def test_baseline_document_names_every_retained_route(self) -> None:
        baseline = BASELINE_PATH.read_text(encoding="utf-8")
        for method, route_path in sorted(self.retained):
            with self.subTest(method=method, path=route_path):
                self.assertIn(f"`{method} {route_path}`", baseline)

    def test_identifiers_and_session_paths_are_explicitly_preserved(self) -> None:
        preserved = set(self.policy["preserved_identifiers_and_paths"])
        self.assertIn("zotero-agent-bridge@local", preserved)
        self.assertIn("%USERPROFILE%/Zotero/zotero-agent-bridge", preserved)
        self.assertIn(
            "%USERPROFILE%/Zotero/zotero-agent-bridge/pi-chat/session-index.json",
            preserved,
        )
        self.assertIn(
            "%USERPROFILE%/Zotero/zotero-agent-bridge/pi-chat/experience-note-index.json",
            preserved,
        )
        self.assertIn("%USERPROFILE%/Zotero/zotero-agent-bridge/pi-sessions", preserved)


if __name__ == "__main__":
    unittest.main()
