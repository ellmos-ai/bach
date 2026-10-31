import test from 'node:test';
import assert from 'node:assert/strict';
import {getPolicyRegistry, getEffectivePolicy, describePolicyRegistryModule} from '../src/lib/governance-client.mjs';

const providerObj = {id:'policy-registry', version:'0.2.4', source_commit:'2c4896b70cb3',
  repository:'ellmos-ai/policy-registry', verified:true};
const view = {entries:[{kind:'policy', name:'device-auth', version:'1'}], count:1,
  provider:providerObj, registry_version:'a1b2c3d4', extra_note:'unbekanntes Zusatzfeld'};
const response = (data, status=200) => ({ok:status<400, status, json:async()=>data});
const rejectingFetcher = async()=>{throw new Error('Es wurde ein Request ausgelöst.');};

test('successful reads return entries, count, provider and registry_version with extra fields', async()=>{
  assert.deepEqual(await getPolicyRegistry({}, async()=>response(view)), view);
  const effective = {...view, entries:[{kind:'decision', name:'allow-gui', version:'1'}], scope:'device:gui'};
  const result = await getEffectivePolicy('device:gui', {}, async()=>response(effective));
  assert.deepEqual(result.entries, effective.entries);
  assert.equal(result.count, 1);
  assert.deepEqual(result.provider, providerObj);
  assert.equal(result.registry_version, 'a1b2c3d4');
  assert.equal(result.scope, 'device:gui');
  assert.equal(result.extra_note, 'unbekanntes Zusatzfeld');
});

test('policy provider unavailability stays visible without silent fallback data', async()=>{
  let calls=0;
  const fetcher=async()=>{calls++;return response({detail:'Richtlinien-Anbieter antwortet nicht'},503);};
  const error=await getPolicyRegistry({},fetcher).then(()=>{throw new Error('Fehler wurde verschluckt');},e=>e);
  assert.equal(error.name,'PolicyProviderUnavailable');
  assert.equal(error.status,503);
  assert.match(error.message,/PolicyProviderUnavailable/);
  assert.match(error.message,/Richtlinien-Anbieter antwortet nicht/);
  assert.equal(calls,1);
  await assert.rejects(getEffectivePolicy('device:gui',{},fetcher),/PolicyProviderUnavailable/);
});

test('policy snapshot change reports the reload requirement', async()=>{
  const error=await getPolicyRegistry({},async()=>response({detail:'Richtlinien-Snapshot wurde inzwischen geändert'},409))
    .then(()=>{throw new Error('Konflikt wurde verschluckt');},e=>e);
  assert.equal(error.name,'PolicySnapshotChanged');
  assert.equal(error.status,409);
  assert.match(error.message,/PolicySnapshotChanged/);
  assert.match(error.message,/neu laden|Neuladen/);
  assert.match(error.message,/Richtlinien-Snapshot wurde inzwischen geändert/);
});

test('optional query parameters are only sent when set and remain encoded', async()=>{
  const calls=[];
  const fetcher=async(url)=>{calls.push(url);return response(view);};
  await getPolicyRegistry({scope:'', consumer:undefined, query:'grüße & Regeln', kind:''}, fetcher);
  assert.equal(calls[0],'/api/governance/policy-registry?query='+encodeURIComponent('grüße & Regeln'));
  assert.ok(!calls[0].includes('kind='));
  assert.ok(!calls[0].includes('scope='));
  await getPolicyRegistry({scope:'device:gui', kind:'decision-candidate'}, fetcher);
  assert.equal(calls[1],'/api/governance/policy-registry?scope=device%3Agui&kind=decision-candidate');
  await getEffectivePolicy('team:ops',{query:'', consumer:'gui'}, fetcher);
  assert.equal(calls[2],'/api/governance/effective-policy?scope=team%3Aops&consumer=gui');
});

test('invalid kind values abort before any request', async()=>{
  await assert.rejects(getPolicyRegistry({kind:'policy;drop view'},rejectingFetcher),/Eintragstyp/);
  await assert.rejects(getPolicyRegistry({kind:'Policies'},rejectingFetcher),/Eintragstyp/);
  await assert.rejects(getPolicyRegistry({kind:42},rejectingFetcher),/Eintragstyp/);
});

test('effective policy without a scope aborts before any request', async()=>{
  await assert.rejects(getEffectivePolicy(undefined,{},rejectingFetcher),/Geltungsbereich/);
  await assert.rejects(getEffectivePolicy('',{},rejectingFetcher),/Geltungsbereich/);
  await assert.rejects(getEffectivePolicy('   ',{},rejectingFetcher),/Geltungsbereich/);
});

test('policy-registry module status keeps unknown reason codes and every field', ()=>{
  const module={adapter_registered:true, runtime_verified:false, available:false,
    reason_code:'future_provider_reconfigured', observed_at:'2026-10-22T04:00:00Z',
    probe:{url:'https://example.test/registry'}};
  const described=describePolicyRegistryModule(module);
  assert.equal(described.reason_code,'future_provider_reconfigured');
  assert.match(described.text,/future_provider_reconfigured/);
  assert.equal(described.adapter_registered,true);
  assert.equal(described.available,false);
  assert.equal(described.observed_at,'2026-10-22T04:00:00Z');
  assert.deepEqual(described.probe,{url:'https://example.test/registry'});
  assert.equal(described.ok,false);
  const available=describePolicyRegistryModule({adapter_registered:true, available:true, reason_code:'verified'});
  assert.equal(available.ok,true);
  const missing=describePolicyRegistryModule(null);
  assert.equal(missing.ok,false);
  assert.match(missing.text,/nicht gelesen werden/);
});