"""Hermetic neutral resource, branding and browser-client contracts."""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from gui.activity_dashboard import DEFAULT_BRANDING
from gui.activity_dashboard import render_activity_dashboard as bach_render
from ocean_gui_shell import render_activity_dashboard


def script_of(page):
    return re.search(r"<script>(.*?)</script>", page, re.DOTALL)[1]


def test_neutral_and_bach_use_same_resource():
    neutral = render_activity_dashboard()
    assert "OCEAN Aktivitäten" in neutral
    assert "Buddha Chat" not in neutral
    assert "BACH" not in neutral
    assert bach_render() == render_activity_dashboard(DEFAULT_BRANDING)
    assert '{{' not in neutral
    assert not re.search(r'<(?:script|link)[^>]*(?:src|href)=', neutral)


def test_import_has_no_bach_or_backend_dependencies():
    package_root = Path(__file__).resolve().parents[1]
    code = """
import sys
sys.path.insert(0, sys.argv[1])
import ocean_gui_shell
assert not any(x == 'gui' or x.startswith(('gui.', 'hub', 'bach', 'fastapi', 'unified_gui')) for x in sys.modules)
assert 'OCEAN' in ocean_gui_shell.render_activity_dashboard()
"""
    result = subprocess.run([sys.executable, "-c", code, str(package_root)],
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("field", ["brand_icon", "title", "brand_name", "subtitle", "slot_chat_title", "slot_always_on_title", "token_storage_key"])
def test_branding_cannot_break_html_or_script(field):
    payload = "</script><img src=x onerror=alert(1)>\"'\\\n{{ brand_name }}"
    page = render_activity_dashboard({field: payload})
    assert '<img src=x' not in page
    assert page.count('</script>') == 1
    result = subprocess.run(["node", "--check", "-"], input=script_of(page),
                            encoding="utf-8", capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,test", "//evil.test/api", "/\\evil/api", "https://u:p@example.org/api"])
def test_unsafe_api_and_navigation_urls_rejected(url):
    with pytest.raises(ValueError):
        render_activity_dashboard(api_base=url)
    with pytest.raises(ValueError):
        render_activity_dashboard({"nav_links": [{"href": url}]})


@pytest.mark.parametrize("colors", [{"accent": "red;</style><script>"}, {"bad}:x": "red"}, {"accent": "url(https://evil.test)"}])
def test_unsafe_theme_rejected(colors):
    with pytest.raises(ValueError):
        render_activity_dashboard({"theme_colors": colors})


def run_browser_contract(read_only=False):
    page = render_activity_dashboard({"read_only": read_only}, api_base="/control-backend/api")
    # Run actual shared client functions with a deterministic DOM and transport;
    # scheduled boot reads are separately checked by the mount tests.
    script = script_of(page).rsplit("setWriteAccess(false, 'Nur lesen · Schreibzugriff noch nicht geprüft');", 1)[0]
    harness = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {textContent:'', innerHTML:'', style:{}, getAttribute:()=>"runWorker('safe')"});
  return elements.get(id);
}
let auth = true, fail = false, calls = [];
let receipt = {service:'bach-chat-control',authenticated:true};
const box = {
  document: {getElementById:element, querySelectorAll:()=>[element('write-button')], addEventListener:()=>{}},
  location: {origin:'http://testclient'}, localStorage:{getItem:()=> 'test-token', setItem:()=>{}},
  window:{prompt:()=> 'test-token'}, setTimeout:()=>{}, setInterval:()=>{},
  fetch: async (url, opts) => {
    calls.push([url, opts]);
    if (fail) throw new Error('offline');
    if (url.endsWith('/auth/check')) return {ok:auth, status:auth?200:403, json:async()=>receipt};
    return {ok:true, status:200, json:async()=>({ok:true, slots:{}, history:[]})};
  }
};
vm.createContext(box);
vm.runInContext(INPUT_SCRIPT, box);
(async()=> {
  await box.api('POST','/workers/run',{id:'safe'});
  assert.equal(calls.length,0);
  await box.api('GET','/slots');
  assert.equal(calls[0][0], '/control-backend/api/slots');
  assert.equal(calls[0][1].redirect,'error');
  assert.equal(calls[0][1].headers.Authorization,undefined);
  calls=[];
  const authorized = await box.authorizeControl();
  if (READ_ONLY) {
    assert.equal(authorized,false);
    assert.equal(calls.length,0);
    await box.api('POST','/workers/run',{id:'safe'});
    assert.equal(calls.length,0);
  } else {
    assert.equal(authorized,true);
    calls=[];
    await box.api('POST','/workers/run',{id:'safe'});
    assert.deepEqual(calls.map(x=>x[0]), ['/control-backend/api/auth/check','/control-backend/api/workers/run']);
    assert.equal(calls[1][1].headers.Authorization,'Bearer test-token');
    assert.equal(calls[1][1].redirect,'error');
    for (const invalid of [null, {}, {service:'foreign',authenticated:true}, {service:'bach-chat-control',authenticated:'true'}]) {
      receipt=invalid; calls=[];
      assert.equal(await box.authorizeControl(),false);
      const checked=calls.length;
      await box.api('POST','/workers/run',{id:'safe'});
      assert.equal(calls.length,checked);
    }
    receipt={service:'bach-chat-control',authenticated:true};
    await box.authorizeControl();
    auth=false; calls=[];
    const denied = await box.api('POST','/workers/run',{id:'safe'});
    assert.ok(denied.error);
    assert.equal(calls.length,1);
    assert.equal(element('write-button').disabled,true);
    fail=true;
    assert.ok((await box.api('GET','/slots')).error);
    assert.match(element('control-access').textContent, /nicht erreichbar/);
    fail=false; auth=true;
    await box.authorizeControl();
    box.fetch=async()=>({ok:false,status:409,json:async()=>({error:'busy'})});
    assert.equal((await box.api('GET','/slots')).error,'busy');
  }
  box.renderWorkers([{id:"x');alert(1);//",name:'attack'}, {id:'safe',status:"x');alert(1);//",mode:'<img onerror=attack>',task_id:'<b>',max_tool_rounds:'<svg>',sub_mode:'boss_routing',max_experts:'<script>'}]);
  const html=element('workers-container').innerHTML;
  assert.ok(!html.includes('alert(1)'));
  assert.ok(!html.includes('<img'));
  assert.ok(!html.includes('<svg>'));
  assert.ok(!html.includes('<script>'));
  assert.ok(html.includes('&lt;img'));
  console.log('browser contract passed');
})().catch(err=>{console.error(err);process.exitCode=1;});
"""
    harness = harness.replace("INPUT_SCRIPT", json.dumps(script)).replace("READ_ONLY", str(read_only).lower())
    result = subprocess.run(["node", "-"], input=harness, encoding="utf-8", capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("read_only", [True, False])
def test_browser_auth_offline_xss_and_mutation_contract(read_only):
    run_browser_contract(read_only)
