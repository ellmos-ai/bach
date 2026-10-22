// Tests for src/lib/task-hindrances.js: five fail-closed hindrance groups
// built from native backend data (lease, worker policy, task detail).
import test from "node:test";
import assert from "node:assert/strict";
import {
  HINDRANCE_GROUPS,
  buildTaskHindrances,
  escapeHtml,
  renderTaskHindrances
} from "../src/lib/task-hindrances.js";

function groupById(model, id) {
  const group = model.groups.find((candidate) => candidate.id === id);
  assert.ok(group, `Gruppe ${id} fehlt`);
  return group;
}

function joinedTexts(group) {
  return group.entries.map((entry) => entry.text).join(" | ");
}

test("fremde Lease wird als Hindernis mit Holder-Rohdaten dargestellt", () => {
  const model = buildTaskHindrances({
    lease: {
      leased: true,
      own: false,
      legacy: false,
      fence: "fence-1",
      task_version: 7,
      holder: { worker_id: "w-4711", host: "worker-host", intent: "work", expires_at: "2030-01-01T00:00:00Z" }
    }
  });
  const leaseGroup = groupById(model, "lease");
  assert.equal(leaseGroup.state, "hindrance");
  const joined = joinedTexts(leaseGroup);
  assert.match(joined, /w-4711/);
  assert.match(joined, /worker-host/);
  assert.equal(model.hasHindrances, true);
});

test("eigene Lease erzeugt kein Hindernis", () => {
  const model = buildTaskHindrances({
    lease: { leased: true, own: true, legacy: false, task_version: 3, fence: "fence-3" }
  });
  const leaseGroup = groupById(model, "lease");
  assert.notEqual(leaseGroup.state, "hindrance");
  assert.match(joinedTexts(leaseGroup), /Lease dieses Geräts/);
});

test("fehlende Lease-Daten werden fail-closed als nicht abrufbar markiert", () => {
  const model = buildTaskHindrances({ lease: null });
  const leaseGroup = groupById(model, "lease");
  assert.equal(leaseGroup.state, "unavailable");
  assert.match(joinedTexts(leaseGroup), /nicht abrufbar/);
});

test("Abhängigkeitsblockade erscheint als Hindernis in der Statusgruppe", () => {
  const model = buildTaskHindrances({
    task: { status: "pending", is_blocked_by_dep: true, depends_on: [42, 43] }
  });
  const statusGroup = groupById(model, "status");
  assert.equal(statusGroup.state, "hindrance");
  const joined = joinedTexts(statusGroup);
  assert.match(joined, /is_blocked_by_dep: true/);
  assert.match(joined, /status: pending/);
  assert.match(joined, /depends_on: \[42,43\]/);
});

test("Policy-Antwort zeigt fünf effektive Felder als Rohdaten", () => {
  const model = buildTaskHindrances({
    policy: {
      effective: {
        user_review_required: true,
        github_external_review: false,
        allow_review_task_pickup: true,
        effective_mode: "default",
        policy_source: "system_default"
      }
    }
  });
  const policyGroup = groupById(model, "policy");
  assert.equal(policyGroup.state, "info");
  const joined = joinedTexts(policyGroup);
  assert.match(joined, /effective\.user_review_required: true/);
  assert.match(joined, /effective\.github_external_review: false/);
  assert.match(joined, /effective\.allow_review_task_pickup: true/);
  assert.match(joined, /effective\.effective_mode: default/);
  assert.match(joined, /effective\.policy_source: system_default/);
});

test("Policy-Fehler wird fail-closed ohne Zulassungsaussage dargestellt", () => {
  const model = buildTaskHindrances({ policyError: { status: 503 } });
  const policyGroup = groupById(model, "policy");
  assert.equal(policyGroup.state, "unavailable");
  const joined = joinedTexts(policyGroup);
  assert.match(joined, /nicht abrufbar/);
  assert.match(joined, /503/);
  assert.doesNotMatch(joined, /erlaubt|zulässig|darf übernehmen/);
});

test("Modell- und Zuständigkeitsfelder werden unverändert gezeigt", () => {
  const model = buildTaskHindrances({
    task: { required_model: "claude-sonnet-4-5", assigned_slot: null, assigned_to: "dev-agent" }
  });
  const bindingGroup = groupById(model, "binding");
  assert.equal(bindingGroup.state, "info");
  const joined = joinedTexts(bindingGroup);
  assert.match(joined, /required_model: claude-sonnet-4-5/);
  assert.match(joined, /assigned_slot: null/);
  assert.match(joined, /assigned_to: dev-agent/);
});

test("Versionen und Fence werden aus beiden Endpunkten gegenübergestellt", () => {
  const model = buildTaskHindrances({
    task: { task_version: 11 },
    lease: { task_version: 12, fence: "fence-9" }
  });
  const versionsGroup = groupById(model, "versions");
  const joined = joinedTexts(versionsGroup);
  assert.match(joined, /task_version \(Detail-GET\): 11/);
  assert.match(joined, /task_version \(Lease-GET\): 12/);
  assert.match(joined, /fence \(Lease-GET\): fence-9/);
});

test("escapeHtml maskiert HTML-Metazeichen", () => {
  assert.equal(escapeHtml('<img src=x onerror="alert(1)">'), "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;");
  assert.equal(escapeHtml('a & b < c > d " e'), "a &amp; b &lt; c &gt; d &quot; e");
});

test("Render-Ausgabe maskiert Holder-Daten", () => {
  const model = buildTaskHindrances({
    lease: { leased: true, own: false, legacy: false, holder: { worker_id: '<script>alert("x")</script>' } }
  });
  const html = renderTaskHindrances(model);
  assert.ok(html.includes("&lt;script&gt;"));
  assert.ok(!html.includes("<script>alert"));
});

test("fünf Gruppen mit fester Reihenfolge und Labels", () => {
  assert.deepEqual(
    HINDRANCE_GROUPS.map((group) => group.label),
    [
      "Fremde Lease",
      "Status / Abhängigkeit",
      "Ausführungsrechte",
      "Harte Modell-/Zuständigkeitsregeln",
      "Unveränderte Rückgabe"
    ]
  );
  const model = buildTaskHindrances({});
  assert.deepEqual(model.groups.map((group) => group.id), ["lease", "status", "policy", "binding", "versions"]);
  const html = renderTaskHindrances(model);
  for (const group of model.groups) {
    assert.ok(html.includes(group.label));
  }
});

test("Render-Ausgabe enthält keine Zulassungsaussage", () => {
  const scenarios = [
    {},
    { lease: { leased: false } },
    { policy: { effective: { user_review_required: false } } }
  ];
  for (const input of scenarios) {
    const html = renderTaskHindrances(input);
    assert.doesNotMatch(html, /erlaubt|zulässig|darf übernehmen/);
  }
});

test("historisches claimed_by wird ohne Aussage über die aktuelle Lease gezeigt", () => {
  const model = buildTaskHindrances({ task: { claimed_by: "agent-7" }, lease: { leased: false } });
  const joined = joinedTexts(groupById(model, "lease"));
  assert.match(joined, /claimed_by: agent-7/);
  assert.match(joined, /historisch, keine Aussage über die aktuelle Lease/);
});