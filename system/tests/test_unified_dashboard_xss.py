# SPDX-License-Identifier: MIT
"""Offline XSS regressions: execute the real dashboard JS with Node, parse its HTML.

No GUI server, network, production database, browser, or npm install is needed.
The capture DOM exercises rendering and listeners; HTMLParser checks the emitted
markup. This is deliberately not a claim of browser/live acceptance.
Run directly: python -B system/tests/test_unified_dashboard_xss.py
"""

from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest
from urllib.parse import parse_qs, urlsplit


DASHBOARD = Path(__file__).resolve().parents[1] / "gui" / "unified_dashboard.html"
PAYLOAD = '\'\"><img src=x onerror="globalThis.pwned=1"><svg onload="globalThis.pwned=2">&quot;&lt;'

NODE_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const nodes = {};
const calls = [];
const alerts = [];
const downloads = [];
const revoked = [];
let failure = false;
function element() {
    return {innerHTML: '', textContent: '', value: input.payload,
        dataset: {}, style: {}, listeners: {}, actionElements: [],
        addEventListener(type, callback) { this.listeners[type] = callback; },
        querySelectorAll() { return this.actionElements; },
        click() { downloads.push({href: this.href, name: this.download}); },
        remove() {}, classList: {add() {}, remove() {}}};
}
const document = {
    getElementById(id) { return nodes[id] ||= element(); },
    querySelectorAll() { return []; },
    createElement() { return element(); }, body: {appendChild() {}}
};
const sandbox = {document, console: {error() {}},
    window: {location: {hash: ''}, addEventListener() {}},
    history: {replaceState() {}}, alert(message) { alerts.push(message); },
    URL: {createObjectURL() { return 'blob:offline-test'; }, revokeObjectURL(url) { revoked.push(url); }},
    setTimeout(callback) { callback(); },
    async fetch(url, options) {
        calls.push({url, method: options?.method || 'GET'});
        if (failure) throw new Error(input.payload);
        return {ok: input.ok !== false, status: input.ok === false ? 403 : 200,
            async json() { return input.responses[url] || {}; }, async blob() { return {}; }};
    }
};
vm.createContext(sandbox);
// Omit only automatic initial loading: every selected function runs unchanged.
vm.runInContext(input.script.replace('        loadTasks();\n    }\n', '\n    }\n'), sandbox);
(async () => {
    // Let automatic initial fetch settle, then keep only explicitly tested calls.
    await new Promise(resolve => setImmediate(resolve));
    calls.length = 0;
    for (const spec of input.actions || []) {
        const target = document.getElementById(spec.container);
        target.actionElements = spec.datasets.map(dataset => Object.assign(element(), {dataset}));
    }
    failure = Boolean(input.failure);
    for (const name of input.functions || []) await sandbox[name]();
    for (const spec of input.actions || []) {
        for (const item of nodes[spec.container].actionElements) await item.listeners.click?.();
    }
    for (const args of input.materializeIds || []) await sandbox.materializeAgent(args);
    for (const args of input.chainIds || []) await sandbox.runChain(args);
    if (input.preview) await sandbox.previewArtifact(...input.preview);
    if (input.download) await sandbox.downloadArtifact(...input.download);
    await new Promise(resolve => setImmediate(resolve));
    const output = {};
    for (const [id, node] of Object.entries(nodes)) {
        output[id] = {html: node.innerHTML, text: node.textContent, dataset: node.dataset, style: node.style};
    }
    process.stdout.write(JSON.stringify({nodes: output, calls, alerts, downloads, revoked, pwned: sandbox.pwned || null}));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


class Markup(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.text = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


@unittest.skipUnless(shutil.which("node"), "Node.js is required for offline JS regression tests")
class TestUnifiedDashboardXss(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = DASHBOARD.read_text(encoding="utf-8")
        cls.script = re.search(r"<script>(.*?)</script>", cls.source, re.S | re.I).group(1)

    def execute(self, **options):
        result = subprocess.run(
            [shutil.which("node"), "-e", NODE_HARNESS],
            input=json.dumps({"script": self.script, "payload": PAYLOAD, "responses": {}, **options}),
            text=True, encoding="utf-8", capture_output=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def assert_safe_markup(self, markup):
        parsed = Markup(markup)
        allowed = {"table", "thead", "tbody", "tr", "th", "td", "strong", "span", "code", "div", "p", "button", "ul", "li", "h4"}
        for tag, attrs in parsed.tags:
            self.assertIn(tag, allowed, f"Injected HTML tag: {tag}")
            for attr in attrs:
                self.assertFalse(attr.startswith("on"), f"Injected event handler: {attr}")
            for attr in ("class", "style"):
                self.assertNotIn("pwned", attrs.get(attr, ""))
        return parsed

    def test_every_dashboard_view_treats_api_fields_as_text(self):
        p = PAYLOAD
        cases = [
            ("loadTasks", "/api/tasks?limit=50", {"tasks": [dict.fromkeys(["id", "title", "priority", "category", "status", "assigned_to"], p)]}, ["tasks-table-container"]),
            ("loadBlueprints", "/api/agent-studio/blueprints", {"templates": [dict.fromkeys(["id", "title", "animus_type", "description", "modus"], p)], "blueprints": [{"id": 4, "name": p, "persona_role": p, "animus_type": p, "modus": p}]}, ["blueprints-container"]),
            ("loadLiving", "/api/agent-studio/living", {"living_agents": [dict.fromkeys(["title", "status", "animus", "current_task"], p), {"name": p}]}, ["living-container"]),
            ("loadCapabilities", "/api/capabilities", {"stats": dict.fromkeys(["total_skills", "total_tools", "total_mcps"], p), "skills_by_category": {p: [{"name": p}]}}, ["capabilities-stats", "capabilities-container"]),
            ("loadChains", "/api/marblerun/chains", {"chains": [{"id": p, "title": p, "description": p, "steps": [{"name": p}]}, {"id": 5, "name": p}]}, ["chains-container"]),
            ("loadAgentsMap", "/api/marblerun/agents-map", {"stats": {"total_nodes": p, "total_links": p}, "nodes": [{"label": p, "animus": p}]}, ["agents-map-container"]),
            ("searchGardener", "/api/gardener/search?q=" + self.execute_query(p), {"results": [{"name": p, "type": p}]}, ["gardener-results"]),
            ("loadMemoryDigest", "/api/memory/knowledge-digest", {"knowledge_folders": [dict.fromkeys(["label", "path", "file_count"], p)]}, ["knowledge-folders"]),
            ("runCompareRace", "/api/chat/compare-race", {"winner": p, "candidates": [dict.fromkeys(["model", "latency_ms", "score", "response"], p)]}, ["compare-results"]),
            ("loadArtifacts", "/api/artifacts?limit=30", {"artifacts": [{"path": p, "name": p, "type": p, "modified": p, "size_bytes": p}]}, ["artifacts-list"]),
        ]
        for function, endpoint, response, ids in cases:
            with self.subTest(function=function):
                out = self.execute(functions=[function], responses={endpoint: response})
                self.assertIsNone(out["pwned"])
                for node_id in ids:
                    markup = out["nodes"][node_id]["html"]
                    parsed = self.assert_safe_markup(markup)
                    self.assertIn("pwned", "".join(parsed.text).lower())
                if function == "loadArtifacts":
                    li = next(attrs for tag, attrs in parsed.tags if tag == "li")
                    self.assertEqual(li["data-artifact-path"], p)
                    self.assertEqual(li["data-artifact-name"], p)
                if function in {"loadBlueprints", "loadChains"}:
                    buttons = [attrs for tag, attrs in parsed.tags if tag == "button"]
                    self.assertEqual(buttons[0]["data-id"], "")
                    self.assertIn("disabled", buttons[0])
                    self.assertNotIn("disabled", buttons[1])

    @staticmethod
    def execute_query(value):
        from urllib.parse import quote
        return quote(value, safe="~!*'()")  # encodeURIComponent's safe characters

    def test_governance_fields_are_text(self):
        p = PAYLOAD
        out = self.execute(functions=["loadGovernance"], responses={
            "/api/governance/locks": {"locks": [dict.fromkeys(["name", "type", "status"], p)]},
            "/api/governance/policies": {"policies": [dict.fromkeys(["id", "name", "enforcement", "desc"], p)]},
            "/api/governance/decisions": {"decisions": [{"title": p, "id": p}]},
        })
        for node_id in ["locks-container", "policies-container", "decisions-container"]:
            parsed = self.assert_safe_markup(out["nodes"][node_id]["html"])
            self.assertIn(p, "".join(parsed.text))

    def test_error_messages_are_text(self):
        functions = ["loadTasks", "loadBlueprints", "loadLiving", "loadCapabilities", "loadChains", "loadAgentsMap", "searchGardener", "runCompareRace", "loadArtifacts"]
        out = self.execute(functions=functions, failure=True)
        for node in out["nodes"].values():
            if "Fehler" in node["html"]:
                self.assertIn(PAYLOAD, "".join(self.assert_safe_markup(node["html"]).text))
            elif "Fehler" in node["text"]:
                self.assertIn(PAYLOAD, node["text"])
        self.assertIsNone(out["pwned"])

    def test_numeric_action_ids_reject_code_and_path_segments(self):
        invalid = [PAYLOAD, "1);globalThis.pwned=1;//", "../1", "1?x=y", "1e2", "01", 0, -1, 1.5, True, None, [], {}, 9007199254740992]
        out = self.execute(materializeIds=invalid, chainIds=invalid)
        self.assertEqual(out["calls"], [])
        valid = self.execute(materializeIds=["12"], chainIds=[13])
        self.assertIn({"url": "/api/agent-studio/blueprints/12/materialize", "method": "POST"}, valid["calls"])
        self.assertIn({"url": "/api/marblerun/chains/13/run", "method": "POST"}, valid["calls"])
        for function, container, response, dataset, expected in [
            ("loadBlueprints", "blueprints-container", {"templates": [{"id": 12}]}, {"id": "12"}, "/api/agent-studio/blueprints/12/materialize"),
            ("loadChains", "chains-container", {"chains": [{"id": 13}]}, {"id": "13"}, "/api/marblerun/chains/13/run"),
        ]:
            endpoint = "/api/agent-studio/blueprints" if function == "loadBlueprints" else "/api/marblerun/chains"
            clicked = self.execute(functions=[function], responses={endpoint: response}, actions=[{"container": container, "datasets": [dataset, {"id": PAYLOAD}]}])
            posts = [call["url"] for call in clicked["calls"] if call["method"] == "POST"]
            self.assertEqual(posts, [expected])

    def test_artifact_paths_and_names_do_not_become_code_or_urls(self):
        path = "folder/a'b\"<&?#=Ä.txt"
        out = self.execute(functions=["loadArtifacts"], responses={
            "/api/artifacts?limit=30": {"artifacts": [{"path": path, "name": PAYLOAD}]},
        }, actions=[{"container": "artifacts-list", "datasets": [{"artifactPath": path, "artifactName": PAYLOAD}]}])
        preview_call = next(call for call in out["calls"] if "/content?" in call["url"])
        self.assertEqual(parse_qs(urlsplit(preview_call["url"]).query), {"path": [path]})
        self.assertEqual(out["nodes"]["artifact-preview-title"]["text"], "Vorschau: " + PAYLOAD)
        downloaded = self.execute(download=[path, PAYLOAD])
        self.assertEqual(parse_qs(urlsplit(downloaded["calls"][0]["url"]).query), {"path": [path]})
        self.assertEqual(downloaded["downloads"], [{"href": "blob:offline-test", "name": PAYLOAD}])
        self.assertEqual(downloaded["revoked"], ["blob:offline-test"])
        preview = self.execute(preview=[path, PAYLOAD], responses={preview_call["url"]: {"content": PAYLOAD}})
        self.assertEqual(preview["nodes"]["artifact-preview-body"]["text"], PAYLOAD)
        self.assertEqual(preview["nodes"]["artifact-preview-body"]["html"], "")

    def test_failed_mutations_and_downloads_do_not_report_success(self):
        out = self.execute(ok=False, materializeIds=[12], chainIds=[13], preview=["test.txt", "test"], download=["test.txt", "test"])
        self.assertEqual(out["alerts"], ["Fehler: HTTP 403", "Fehler: HTTP 403"])
        self.assertEqual(out["downloads"], [])
        self.assertEqual(out["nodes"]["artifact-download-btn"]["style"]["display"], "none")
        self.assertEqual(out["nodes"]["artifact-preview-body"]["text"], "Fehler beim Download: HTTP 403")

    def test_auth_wrapper_precedes_script_and_no_dynamic_inline_handlers(self):
        self.assertLess(self.source.index('<script src="/static/js/device-fetch.js"></script>'), self.source.index("<script>"))
        self.assertIsNone(re.search(r"\bon[a-z]+=\"[^\"]*\$\{", self.script))
        self.assertNotIn("innerHTML = 'Fehler: ' +", self.script)


if __name__ == "__main__":
    unittest.main()
