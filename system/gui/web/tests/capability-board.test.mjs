import test from 'node:test';
import assert from 'node:assert/strict';
import {loadSkill, saveSkill, requestJson} from '../src/lib/capability-board-client.mjs';

const revision = 'a'.repeat(64), nextRevision = 'b'.repeat(64);
const current = {id:'example',content:'# Aktuelle Grüße',source_version:revision};
const response = (data, status=200) => ({ok:status<400,status,json:async()=>data});

test('opening a skill returns actual source content and rejects declarations', async()=>{
  assert.deepEqual(await loadSkill('example',async()=>response(current)),current);
  await assert.rejects(loadSkill('example',async()=>response({id:'example',role:'only metadata'})),/bestätigt/);
  await assert.rejects(loadSkill('../escape',async()=>assert.fail('Invalid path fetched')),/Kennung/);
});

test('saving uses current source CAS and reads the written source again',async()=>{
  const calls=[],content='# Neue Grüße';
  const saved={id:'example',content,source_version:nextRevision,receipt:{source_saved:true}};
  const fetcher=async(url,options={})=>{calls.push({url,options});return response(saved);};
  assert.equal((await saveSkill(current,content,fetcher)).content,content);
  assert.equal(calls.length,2);
  assert.deepEqual(JSON.parse(calls[0].options.body),{content,source_version:revision});
  assert.equal(calls[0].options.method,'PUT');
  assert.equal(calls[1].options.method,undefined);
});

test('source conflict does not retry or overwrite',async()=>{
  let count=0;
  await assert.rejects(saveSkill(current,'changed',async()=>{count++;return response({detail:'conflict'},409);}),/inzwischen geändert/);
  assert.equal(count,1);
});

test('an unconfirmed save and a changed readback cannot claim success',async()=>{
  await assert.rejects(saveSkill(current,'changed',async()=>response({id:'example',content:'changed',source_version:nextRevision})),/Speicherbeleg/);
  let count=0;
  await assert.rejects(saveSkill(current,'changed',async()=>response(++count===1?{id:'example',content:'changed',source_version:nextRevision,receipt:{source_saved:true}}:current)),/erneut geändert/);
});

test('new skills use absence CAS and malformed input does not issue requests',async()=>{
  let sent;
  const saved={id:'new',content:'new content',source_version:nextRevision,receipt:{source_saved:true}};
  await saveSkill({id:'new',source_version:'0'},'new content',async(url,options={})=>{if(options.body)sent=JSON.parse(options.body);return response(saved);});
  assert.equal(sent.source_version,'0');
  await assert.rejects(saveSkill({id:'new'},'new content',async()=>assert.fail('Unversioned write')),/Quellenversion/);
});

test('invalid JSON and API failures remain visible',async()=>{
  await assert.rejects(requestJson('/api/test',{},async()=>({ok:true,json:async()=>{throw new Error('invalid');}})),/lesbare Antwort/);
  await assert.rejects(requestJson('/api/test',{},async()=>response({detail:'Quelle nicht lesbar'},503)),/Quelle nicht lesbar/);
});
