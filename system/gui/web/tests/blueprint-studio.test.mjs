import test from "node:test";
import assert from "node:assert/strict";
import {escapeHtml,blueprintState,executionSettings,normalizeTools,correlatedStart,instanceSettings,startLabel} from "../src/scripts/blueprint-studio.mjs";

test("catalogue escapes saved names and prompts",()=>{
  assert.equal(escapeHtml('<img src=x onerror="alert(1)">'),"&lt;img src=x onerror=&quot;alert(1)&quot;&gt;");
  assert.equal(escapeHtml("Müller & Söhne"),"Müller &amp; Söhne");
});
test("a stored flag cannot claim Living or Running",()=>{
  assert.equal(blueprintState({is_materialized:1}),"Vorlage");
  assert.equal(blueprintState({instance:{status:"running",running:true}}),"Konfiguriert · Status unbekannt");
});
test("only observed controller state supplies readiness",()=>{
  assert.equal(blueprintState({instance:{runtime_verified:true,running:true}}),"Running");
  assert.equal(blueprintState({instance:{runtime_verified:true,running:false,living:true}}),"Living · bereit");
  assert.equal(blueprintState({instance:{runtime_verified:true,running:false,enabled:false}}),"Aus");
});
test("execution uses saved configuration and observed instance without model fallback",()=>{
  assert.deepEqual(executionSettings({}),{});
  assert.equal(executionSettings({contractus:{execution:{model:"openrouter/free"}},instance:{model:"current-model"}},{model:"default"}).model,"current-model");
});
test("legacy grants map to native tools; unknown grants stay visible",()=>{
  assert.deepEqual(normalizeTools(["read_files","directory_list","mcp_cookbooks"]),["read_file","list_directory","mcp_cookbooks"]);
});
test("start confirmation binds worker, request, service and generation",()=>{
  const result={runtime_verified:true,execution:{schema:"bach.worker-execution.v1",worker_id:"system-blueprint-7",start_request_id:"a".repeat(32),service_instance:"b".repeat(32),generation:"c".repeat(32),terminal:false,worker_thread_started:true}};
  assert.equal(correlatedStart(result,"system-blueprint-7","a".repeat(32)),true);
  assert.equal(correlatedStart(result,"another-worker","a".repeat(32)),false);
  assert.equal(correlatedStart(result,"system-blueprint-7","d".repeat(32)),false);
  assert.equal(correlatedStart({...result,execution:{...result.execution,generation:""}},"system-blueprint-7","a".repeat(32)),false);
  assert.equal(correlatedStart({...result,execution:{...result.execution,worker_thread_started:"true"}},"system-blueprint-7","a".repeat(32)),false);
});

test("instance edits use values and CAS from the same fresh core image",()=>{
  const stale={id:7,contractus:{execution:{model:"saved-model",mode:"safe"}},instance:{model:"stale-model",backend:"ollama",mode:"safe"}};
  const core={configuration_version:"fresh",agents:[{id:"buddha_chat",model:"default-model"},{id:"system-blueprint-7",blueprint_id:7,model:"fresh-model",backend:"openrouter",mode:"full"}]};
  assert.equal(instanceSettings(stale,core).model,"fresh-model");
  assert.equal(instanceSettings(stale,core).mode,"full");
  assert.equal(instanceSettings(stale,core).backend,"openrouter");
});
test("cloud and API paths never advertise a local start",()=>{
  assert.equal(startLabel({backend:"hermes",model:"any"}),"Cloud/API starten");
  assert.equal(startLabel({backend:"ollama",model:"model:cloud",resolved_model:"resolved"}),"Cloud/API starten");
  assert.equal(startLabel({backend:"ollama",model:"model:local",resolved_model:"model:cloud"}),"Cloud/API starten");
  assert.equal(startLabel({backend:"ollama",model:"test-local"}),"Lokal starten");
});
test("a made-up run_generation field cannot confirm the controller contract",()=>{
  const execution={schema:"bach.worker-execution.v1",worker_id:"system-blueprint-7",start_request_id:"a".repeat(32),service_instance:"b".repeat(32),run_generation:"c".repeat(32),terminal:false,worker_thread_started:true};
  assert.equal(correlatedStart({runtime_verified:true,execution},"system-blueprint-7","a".repeat(32)),false);
});
