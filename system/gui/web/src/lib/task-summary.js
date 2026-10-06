// Dashboard contract shared with tests, independent of the page and its DOM.
export const TASK_SUMMARY_URL = "/api/tasks?status=pending,in_progress&limit=5";
const OPEN_STATUSES = new Set(["pending", "open", "in_progress", "progress"]);
const HIGH_PRIORITIES = new Set(["P1", "1", "HIGH", "HOCH", "KRITISCH"]);

export function parseTaskSummary(payload) {
  if (!payload || payload.success === false || !Array.isArray(payload.tasks)) {
    throw new Error("Invalid task summary response");
  }
  const tasks = payload.tasks.filter(task => task && OPEN_STATUSES.has(
    String(task.status).toLowerCase(),
  ));
  // Older APIs lack total. Never present the length of a partial page as the
  // overall backlog, or trust a total from an unfiltered legacy response.
  const total = tasks.length === payload.tasks.length &&
    Number.isSafeInteger(payload.total) && payload.total >= tasks.length
      ? payload.total : null;
  return { tasks: tasks.slice(0, 5), total };
}

export async function loadTaskSummary(fetchImpl = fetch) {
  const response = await fetchImpl(TASK_SUMMARY_URL);
  if (!response.ok) throw new Error(`Tasks HTTP ${response.status}`);
  return parseTaskSummary(await response.json());
}

export function taskPresentation(task) {
  return {
    assignee: task.assigned_to || task.delegated_to || "Unzugewiesen",
    highPriority: HIGH_PRIORITIES.has(String(task.priority).trim().toUpperCase()),
  };
}

export function escapeHtml(text) {
  if (text == null) return "";
  return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
