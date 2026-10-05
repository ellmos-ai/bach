import { test } from "node:test";
import assert from "node:assert/strict";
import {
  TASK_SUMMARY_URL, parseTaskSummary, loadTaskSummary, taskPresentation, escapeHtml,
} from "../src/lib/task-summary.js";

test("requests a filtered page and displays the total, not its length", async () => {
  const tasks = Array.from({ length: 5 }, (_, id) => ({ id, status: "pending" }));
  const result = await loadTaskSummary(async url => {
    assert.equal(url, TASK_SUMMARY_URL);
    assert.match(url, /status=pending,in_progress&limit=5/);
    return { ok: true, json: async () => ({ success: true, tasks, count: 5, total: 143 }) };
  });
  assert.equal(result.total, 143);
  assert.equal(result.tasks.length, 5);
});

test("terminal and blocked states cannot appear as open tasks", () => {
  const states = ["pending", "open", "in_progress", "progress", "completed", "done",
    "closed", "cancelled", "canceled", "duplicate", "blocked"];
  const result = parseTaskSummary({ tasks: states.map(status => ({ status })), total: 11 });
  assert.deepEqual(result.tasks.map(t => t.status), states.slice(0, 4));
  assert.equal(result.total, null);
});

test("an empty response and an unknown legacy total are distinct", () => {
  assert.deepEqual(parseTaskSummary({ tasks: [], total: 0 }), { tasks: [], total: 0 });
  assert.equal(parseTaskSummary({ tasks: [{ status: "pending" }], count: 1 }).total, null);
  for (const total of [-1, "100", NaN, 0.5]) {
    assert.equal(parseTaskSummary({ tasks: [], total }).total, null);
  }
});

test("HTTP, application, malformed and transport errors reject", async () => {
  await assert.rejects(loadTaskSummary(async () => ({ ok: false, status: 503 })));
  for (const payload of [{ success: false, error: "offline" }, {}, { tasks: {} }, null]) {
    await assert.rejects(loadTaskSummary(async () => ({ ok: true, json: async () => payload })));
  }
  await assert.rejects(loadTaskSummary(async () => { throw new Error("offline"); }));
});

test("canonical assignment wins and delegated/unassigned tasks have fallbacks", () => {
  assert.equal(taskPresentation({ assigned_to: "CODEX", delegated_to: "BACH" }).assignee, "CODEX");
  assert.equal(taskPresentation({ delegated_to: "BACH" }).assignee, "BACH");
  assert.equal(taskPresentation({}).assignee, "Unzugewiesen");
});

test("priority aliases and untrusted task titles render safely", () => {
  for (const priority of ["P1", "1", "high", "hoch", "kritisch"]) {
    assert.equal(taskPresentation({ priority }).highPriority, true);
  }
  assert.equal(taskPresentation({ priority: "P2" }).highPriority, false);
  assert.equal(escapeHtml('<img src="x" onerror="alert(1)">&'),
    "&lt;img src=&quot;x&quot; onerror=&quot;alert(1)&quot;&gt;&amp;");
});
