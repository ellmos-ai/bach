"""Independent, offline XSS and delegation probe; no server or live data access."""
from html.parser import HTMLParser
from pathlib import Path
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
JS = r'''
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const payload = '<img src=x onerror="globalThis.__xss=1">';
const specialId = `id"'&<>[]`;
const markup = {};
const checks = [];
function environment(file) {
  const elements = new Map();
  function element() {
    return { dataset: {}, style: {}, listeners: {}, _text: '', _html: '',
      classList: { add() {}, remove() {}, contains() { return false; }, toggle() {} },
      set textContent(s) { this._text = String(s); this._html = String(s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); },
      get textContent() { return this._text; },
      set innerHTML(s) { this._html = s; }, get innerHTML() { return this._html; },
      addEventListener(kind, fn) { (this.listeners[kind] ??= []).push(fn); },
      querySelectorAll() { return []; }, querySelector() { return null; },
      remove() {}, focus() {}, scrollIntoView() {}, setSelectionRange() {}
    };
  }
  const document = {
    addEventListener() {}, createElement: element,
    getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); },
    querySelectorAll() { return []; },
    body: { appendChild(el) { elements.set(el.id, el); } }
  };
  const storage = new Map();
  const c = vm.createContext({ document, window: {}, console: { log() {}, warn() {}, error() {} },
    localStorage: { getItem(k) { return storage.get(k) ?? null; }, setItem(k, v) { storage.set(k, v); } },
    setTimeout() {}, payload, specialId });
  vm.runInContext(fs.readFileSync(file, 'utf8'), c, { filename: file });
  vm.runInContext(`
    hierarchyData = {
      items: { agents: [{id: specialId, name: payload, description: payload}],
        experts: [{id: 'expert', name: payload, description: payload}],
        skills: [{id: specialId, name: payload}], services: [], workflows: [] },
      assignments: { [specialId]: { experts: ['expert'], skills: [specialId] } },
      expertSkills: { expert: [specialId] }
    };
    teamFlow = [{id: specialId, type: 'skill', name: payload}];
  `, c);
  return { c, document, elements };
}
const current = environment('system/gui/static/js/agents-board.js');
const {c, document, elements} = current;
function evaluate(code) { return vm.runInContext(code, c); }
markup.tree = evaluate(`renderTreeItem(hierarchyData.items.agents[0], 'agent')`);
markup.fallback = evaluate(`renderTreeItem({id: payload, name: ' '}, 'skill')`);
markup.nested = evaluate(`renderNestedAssignments(hierarchyData.assignments[specialId])`);
evaluate(`renderDetailView(hierarchyData.items.agents[0], 'agent')`);
markup.detail = document.getElementById('detail-panel').innerHTML;
markup.assignments = evaluate(`renderAgentAssignments(specialId, hierarchyData.assignments[specialId])`);
markup.usage = evaluate(`renderItemUsage(specialId, 'skill')`);
markup.task = evaluate(`renderTaskForm(specialId)`);
markup.selector = evaluate(`renderExpertSkillsSelector('expert')`);
markup.flow = evaluate(`renderFlowNodes()`);
evaluate(`editItem('expert', 'expert')`);
markup.modal = elements.get('edit-modal').innerHTML;
evaluate(`renderDetailView({id: 'ati', name: payload, description: payload}, 'agent')`);
markup.dashboard = document.getElementById('detail-panel').innerHTML;
assert.equal(evaluate(`escapeAttr(null)`), '');
assert.equal(evaluate(`escapeAttr(undefined)`), '');
assert.equal(evaluate(`escapeAttr(0)`), '0');
assert.equal(evaluate(`escapeAttr(false)`), 'false');
assert.equal(evaluate(`escapeAttr(specialId)`), 'id&quot;&#x27;&amp;&lt;&gt;[]');
checks.push('escapeHtml/escapeAttr: null, undefined, zero, false, quotes, ampersand, angle brackets');
evaluate(`setupTreeDelegation(); setupTreeDelegation(); setupDetailDelegation(); setupDetailDelegation();`);
const tree = document.getElementById('tree-content');
const detail = document.getElementById('detail-panel');
assert.equal(tree.listeners.click.length, 1);
assert.equal(detail.listeners.click.length, 1);
checks.push('one listener per stable tree/detail container after repeated setup and render');
const calls = [];
const names = ['selectItem', 'toggleAgentChildren', 'removeFromFlow', 'removeAssignment',
  'editItem', 'createTaskForAgent', 'usePromptTemplate', 'submitAgentTask', 'saveTeamFlow',
  'saveItemEdit', 'toggleExpertSkill', 'closeEditModal', 'loadItemSource'];
for (const name of names) c[name] = (...args) => calls.push([name, ...args]);
function dispatch(el, kind, selector, data, expected, extra = {}) {
  const target = { dataset: data, ...extra };
  // Model a click on a child of the actionable element, exercising closest().
  const child = {closest(s) { return s === selector ? target : null; }};
  for (const fn of el.listeners[kind]) fn({target: kind === 'change' ? target : child, stopPropagation() {}});
  assert.deepEqual(calls.splice(0), [expected]);
  checks.push(expected[0] + ': exact arguments');
}
dispatch(tree, 'click', '.tree-item', {id: specialId, type: 'agent'}, ['selectItem', specialId, 'agent']);
dispatch(tree, 'click', '.expand-btn', {agentId: specialId}, ['toggleAgentChildren', specialId]);
const routes = [
 ['remove-flow-node', {index: '0'}, ['removeFromFlow', 0]],
 ['remove-assignment', {agentId: specialId, sectionKey: 'skills', itemId: specialId}, ['removeAssignment', specialId, 'skills', specialId]],
 ['edit-item', {id: specialId, type: 'agent'}, ['editItem', specialId, 'agent']],
 ['create-task', {id: specialId}, ['createTaskForAgent', specialId]],
 ['select-item', {id: specialId, type: 'agent'}, ['selectItem', specialId, 'agent']],
 ['submit-agent-task', {agentId: specialId}, ['submitAgentTask', specialId]],
 ['save-team-flow', {agentId: specialId}, ['saveTeamFlow', specialId]]
];
for (const key of ['task', 'question', 'analysis', 'report'])
  routes.push(['use-template', {template: key, agentName: payload}, ['usePromptTemplate', key, payload]]);
for (const [action, data, expected] of routes)
  dispatch(detail, 'click', `[data-action="${action}"]`, data, expected);
const modal = elements.get('edit-modal');
dispatch(modal, 'click', '[data-action="save-item-edit"]', {id: specialId, type: 'expert'}, ['saveItemEdit', specialId, 'expert']);
dispatch(modal, 'click', '[data-action="close-modal"]', {}, ['closeEditModal']);
for (const checked of [true, false]) dispatch(modal, 'change', '',
  {action: 'toggle-expert-skill', expertId: 'expert', skillId: specialId},
  ['toggleExpertSkill', 'expert', specialId, checked], {checked});
// Exercise the real switchTab implementation and both pane branches.
const buttons = ['info', 'source'].map(id => ({
  active: false, getAttribute() { return `switchTab('${id}')`; },
  classList: {add() { buttons.find(b => b === this.owner).active = true; }, remove() {this.owner.active = false;} }
}));
buttons.forEach(b => {b.classList.owner = b;});
document.querySelectorAll = selector => selector === '.tab-btn' ? buttons :
  selector === '.tab-pane' ? [document.getElementById('info-pane'), document.getElementById('source-pane')] : [];
evaluate(`selectedItem = {id: specialId, type: 'agent'}; switchTab('source')`);
assert.equal(buttons[1].active, true);
assert.equal(document.getElementById('source-pane').style.display, 'flex');
assert.deepEqual(calls.splice(0), [['loadItemSource']]);
evaluate(`switchTab('info')`);
assert.equal(buttons[0].active, true);
assert.equal(document.getElementById('info-pane').style.display, 'block');
checks.push('switchTab: source/info activation and lazy source load');
const legacy = environment('system/gui/static/js/skills-board.js');
// A normal skill avoids the legacy agent expand-state bug; only its name is hostile.
markup.loaded_script_control = vm.runInContext(`renderTreeItem({id:'probe', name:payload}, 'skill')`, legacy.c);
process.stdout.write(JSON.stringify({payload, specialId, markup, checks}));
'''


class Markup(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


run = subprocess.run(['node', '-'], input=JS, text=True, encoding='utf-8',
                     cwd=ROOT, capture_output=True)
if run.returncode:
    raise SystemExit(f'Node failed ({run.returncode}):\n{run.stderr}')
result = json.loads(run.stdout)
safe = 0
for name, html in result['markup'].items():
    parsed = Markup(html)
    dangerous = [(tag, attrs) for tag, attrs in parsed.tags if 'onerror' in attrs]
    if name == 'loaded_script_control':
        assert any(tag == 'img' for tag, _ in dangerous), dangerous
        print(f'CONFIRMED loaded skills-board.js: {len(dangerous)} executable onerror attribute(s)')
    else:
        assert not dangerous, (name, dangerous)
        assert not any(tag == 'img' for tag, _ in parsed.tags), name
        safe += 1
        print(f'PASS {name}: no img element / executable onerror attribute')
tree = Markup(result['markup']['tree'])
assert any(attrs.get('data-name') == result['payload'] and
           attrs.get('data-id') == result['specialId'] for _, attrs in tree.tags)
task = Markup(result['markup']['task'])
assert sum(attrs.get('data-agent-name') == result['payload'] for _, attrs in task.tags) == 4
print('PASS HTML attribute decoding: exact name, ID and four prompt-template names')
print(f"PASS {len(result['checks'])} helper/delegation checks")
print(f'RESULT: {safe} safe current render cases; active legacy script remains vulnerable')
