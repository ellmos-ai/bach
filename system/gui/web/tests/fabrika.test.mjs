import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { Script } from 'node:vm';

const page = readFileSync(new URL('../src/pages/agenten/fabrika.astro', import.meta.url), 'utf8');
const source = page.match(/<script is:inline>([\s\S]*?)<\/script>/)[1];

test('Fabrika inline code parses and exposes its startup functions', () => {
  const script = new Script(source);
  const context = { window: { addEventListener() {} } };
  script.runInNewContext(context);
  for (const name of ['resetForm', 'loadDynamicSkills', 'loadContractusPresets', 'applyGovProfile']) {
    assert.equal(typeof context[name], 'function', name);
  }
});

test('read-only governance disables write, command and git tools', () => {
  const fields = new Map(['read', 'write', 'cmd', 'git', 'mcp', 'web'].map(name => [
    `tool-${name}`, { checked: true },
  ]));
  const context = {
    window: { addEventListener() {} },
    document: { getElementById(id) { return fields.get(id); } },
  };
  new Script(source).runInNewContext(context);
  context.applyGovProfile('read_only_research');
  for (const name of ['write', 'cmd', 'git']) assert.equal(fields.get(`tool-${name}`).checked, false);
  for (const name of ['read', 'mcp', 'web']) assert.equal(fields.get(`tool-${name}`).checked, true);
});
