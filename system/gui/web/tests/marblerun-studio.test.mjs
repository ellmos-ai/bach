import test from 'node:test';
import assert from 'node:assert/strict';
import {flowNodes,moveStep,phaseLabel,selectedModels} from '../src/scripts/marblerun-studio.mjs';
test('flow nodes reuse arrows while escaping actual stored labels',()=>{
  const html=flowNodes([{label:'<img onerror="alert(1)">'},{label:'Müller & Söhne'}]);
  assert.ok(html.includes('&lt;img'));assert.ok(html.includes('Müller &amp; Söhne'));assert.equal((html.match(/flow-arrow/g)||[]).length,1);
});
test('a blank chain has no made-up example steps',()=>{assert.ok(flowNodes([]).includes('Schritt hinzufügen'));assert.ok(!flowNodes([]).includes('NemoFold'));});
test('reordering keeps steps and does not mutate the saved draft',()=>{
  const draft=[{label:'A'},{label:'B'},{label:'C'}];assert.deepEqual(moveStep(draft,1,-1).map(s=>s.label),['B','A','C']);assert.equal(draft[0].label,'A');
  assert.deepEqual(moveStep(draft,0,-1),draft);assert.deepEqual(moveStep(draft,8,-1),draft);
});
test('uncertain controller state is not displayed as Running or completed',()=>{assert.equal(phaseLabel({phase:'unconfirmed'}),'Lauf nicht bestätigt');assert.equal(phaseLabel({phase:'unknown'}),'Status unbekannt');});
test('skill sequence resolves the same selected agent for every step',()=>{
  const agents=[{id:'a',model:'openrouter/free'},{id:'b',model:'other'}];
  assert.deepEqual(selectedModels({mode:'skills',agent_slot:'a',steps:[{agent_slot:'b'},{}]},agents).map(a=>a.model),['openrouter/free','openrouter/free']);
});
test('agent sequence preserves individual selections without a default model fallback',()=>{
  const models=selectedModels({mode:'agents',steps:[{agent_slot:'a'},{agent_slot:'missing'}]},[{id:'a',model:'chosen'}]);
  assert.equal(models[0].model,'chosen');assert.equal(models[1].model,undefined);
});
