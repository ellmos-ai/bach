// SPDX-License-Identifier: MIT
// One editor for the former factory and the real blueprint/controller contracts.
import {createAvatar,mountAvatarPicker} from '../lib/agent-avatar.mjs';
import {createSymbol,mountSymbolPicker} from '../lib/ticket-symbol.mjs';
export const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, char =>
  ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[char]);
export function blueprintState(blueprint) {
  const slot = blueprint.instance;
  if (!slot) return "Vorlage";
  if (slot.runtime_verified !== true) return "Konfiguriert · Status unbekannt";
  if (slot.running === true) return "Running";
  if (slot.enabled === false) return "Aus";
  return slot.living === true ? "Living · bereit" : slot.status || "Konfiguriert";
}
export function executionSettings(blueprint, fallback = {}) {
  return {...fallback, ...(blueprint.contractus?.execution || {}), ...(blueprint.instance || {})};
}
export function instanceSettings(blueprint, core) {
  const fallback = core?.agents?.find(slot => slot.id === "buddha_chat") || {};
  const fresh = core?.agents?.find(slot => slot.blueprint_id === blueprint.id);
  return {...executionSettings({...blueprint, instance:null}, fallback), ...(fresh || {})};
}
export function startLabel(slot) {
  const remoteModel = /:cloud(?:\s|$)/i.test([slot.model,slot.resolved_model].filter(Boolean).join(" "));
  return ["ollama","lmstudio"].includes(slot.backend) && !remoteModel ? "Lokal starten" : "Cloud/API starten";
}
export function normalizeTools(names) {
  const aliases = {
    read_files:["read_file","list_directory"], search_content:["search_text"],
    directory_list:["list_directory"], write_files:["write_file","edit_file","create_directory"],
    run_tests:["safe_shell"],
    git_guarded_p001:["start_task_worktree","finish_task"], code_analyze:["read_file","search_text"],
  };
  return [...new Set(names.flatMap(name => aliases[name] || [name]))];
}
export function correlatedStart(result, workerId, requestId) {
  const receipt = result?.execution;
  return result?.runtime_verified === true &&
    receipt?.schema === "bach.worker-execution.v1" &&
    receipt.worker_id === workerId && receipt.start_request_id === requestId &&
    /^[a-f0-9]{32}$/.test(receipt.service_instance || "") &&
    /^[a-f0-9]{32}$/.test(receipt.generation || "") &&
    typeof receipt.terminal === "boolean" && typeof receipt.worker_thread_started === "boolean";
}

if (typeof document !== "undefined") initializeStudio();

function initializeStudio() {
  const $ = id => document.getElementById(id);
  const state = {blueprints:[], teams:[], skills:[], tools:[], contracts:[], governance:[], core:null,
    prompts:null, library:"custom", edit:null, instance:null, instanceVersion:null, instanceConfig:null, promptVersion:null,
    team:null, avatar:"", symbol:"", modelRequest:0};
  const labels = {agent:"Agent",role:"Rolle",skill:"Skill-Vorlage",workflow:"Workflow-Vorlage",service:"Service-Vorlage",contractus:"Arbeitsvertrag"};
  const icons = {agent:"🤖",role:"🎭",skill:"🧩",workflow:"⛓",service:"⚙",contractus:"📜"};
  const notify = (id,text,error=false) => { $(id).textContent=text; $(id).dataset.error=String(error); };
  const close = id => $(id).close();
  const byId = id => state.blueprints.find(bp => Number(bp.id) === Number(id));
  const currentLocal = () => state.core?.agents?.find(slot => slot.id === "buddha_chat") || {};
  const atlasUrl = $("studio-portrait-source").dataset.portraitAtlas;
  const symbolUrls=JSON.parse($("studio-portrait-source").dataset.ticketSymbols);
  async function api(path, options={}) {
    const response = await fetch(path, {...options,headers:{"Content-Type":"application/json",...options.headers}});
    let data; try { data = await response.json(); } catch { throw new Error("Antwort nicht lesbar (HTTP "+response.status+")"); }
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "HTTP "+response.status);
    return data;
  }
  const post = (path,payload) => api(path,{method:"POST",body:JSON.stringify(payload)});
  const checked = id => [...$(id).querySelectorAll('input[type="checkbox"]:checked')].map(box => box.value);
  function choose(select, value) {
    if (value && ![...select.options].some(option => option.value === String(value))) select.add(new Option(String(value)+" (gespeichert)",String(value)));
    select.value = String(value ?? "");
  }
  function selectOptions(select,items,value) {
    select.replaceChildren(...items.map(item => {const option=new Option(item.label,item.value);option.disabled=item.disabled===true;return option;}));
    choose(select,value ?? items[0]?.value ?? "");
  }
  function optionList(target, items, selected) {
    const selectedSet = new Set(selected);
    target.innerHTML=items.map(item => '<label class="studio-option"><input type="checkbox" value="'+escapeHtml(item.id)+'" '+(selectedSet.has(item.id)?"checked":"")+' /><span>'+escapeHtml(item.name)+'<small>'+escapeHtml(item.description || "")+'</small></span></label>').join("");
  }
  function render() {
    const custom=state.blueprints.filter(bp=>!bp.is_template), templates=state.blueprints.filter(bp=>bp.is_template);
    $("count-custom").textContent=custom.length; $("count-templates").textContent=templates.length; $("count-teams").textContent=state.teams.length;
    document.querySelectorAll("[data-library]").forEach(button=>button.setAttribute("aria-selected",String(button.dataset.library===state.library)));
    const showTeams=state.library==="teams"; $("studio-grid").hidden=showTeams; $("studio-teams").hidden=!showTeams;
    if(showTeams) { renderTeams(); return; }
    const query=$("studio-search").value.toLocaleLowerCase("de"),kind=$("studio-kind").value;
    const items=(state.library==="templates"?templates:custom).filter(bp=>(!kind||bp.kind===kind)&&
      [bp.title,bp.name,bp.description,bp.persona_role].join(" ").toLocaleLowerCase("de").includes(query));
    $("studio-grid").innerHTML=items.map(bp=>{
      const id=Number(bp.id), slot=bp.instance, canExecute=["agent","role"].includes(bp.kind);
      const image=canExecute?'<span data-portrait-blueprint="'+id+'"></span>':'<span data-symbol-blueprint="'+id+'"></span>';
      const model=slot?.model||bp.contractus?.execution?.model;
      return '<article class="studio-card"><div class="studio-card-top">'+image+'<span class="studio-state" data-running="'+String(slot?.running===true)+'">'+escapeHtml(blueprintState(bp))+'</span></div>'+
        '<div><h3>'+escapeHtml(bp.title||bp.name)+'</h3><p>'+escapeHtml(bp.description||bp.persona_role||labels[bp.kind])+'</p></div>'+
        '<div class="studio-card-details"><span>'+escapeHtml(labels[bp.kind]||bp.kind)+'</span><span>· Version '+escapeHtml(bp.version)+'</span>'+(model?'<span>· '+escapeHtml(model)+'</span>':"")+'</div>'+
        '<div class="studio-card-actions"><button class="btn" data-copy="'+id+'">'+(bp.is_template?"Kopie erstellen":"Duplizieren")+'</button>'+
        (!bp.is_template?'<button class="btn" data-edit="'+id+'">Bearbeiten</button>':"")+
        (canExecute?'<button class="btn" data-instance="'+id+'">'+(slot?"Steckplatz aktualisieren":"Als Steckplatz")+'</button>':"")+
        (slot?'<a class="btn" href="/tasks?assigned_slot='+encodeURIComponent(slot.id)+'">Aufgaben</a>':"")+
        (slot&&slot.runtime_verified===true&&slot.running===false&&slot.enabled!==false?'<button class="btn btn-primary" data-start="'+id+'">'+startLabel(slot)+'</button>':"")+
        (!bp.is_template&&!slot?'<button class="btn" data-delete="'+id+'">Entfernen</button>':"")+'</div></article>';
    }).join("") || '<div class="studio-empty">'+(query||kind?"Keine passenden Blueprints.":"Noch keine eigenen Blueprints. Lege einen an oder übernimm eine Vorlage.")+'</div>';
    for(const target of $("studio-grid").querySelectorAll('[data-portrait-blueprint]')) {
      const bp=byId(target.dataset.portraitBlueprint),slot=bp.instance;
      target.replaceChildren(createAvatar(document,slot?.avatar||bp.contractus?.execution?.avatar,slot||bp,atlasUrl,'studio-card-avatar'));
    }
    for(const target of $("studio-grid").querySelectorAll('[data-symbol-blueprint]')) {
      const bp=byId(target.dataset.symbolBlueprint);
      target.replaceChildren(createSymbol(document,bp.contractus?.execution?.symbol,symbolUrls,
        {skill:'wissen',workflow:'scripts',service:'server',contractus:'office'}[bp.kind]||'topics_ai'));
    }
  }
  async function loadData() {
    notify("studio-status","Bibliothek wird geladen…");
    const data=await api("/api/agent-studio/blueprints");
    state.blueprints=[...(data.templates||[]),...(data.blueprints||[])];
    const requests=[["teams","/api/agenten/teams","teams"],["skills","/api/capabilities/skills","skills"],
      ["tools","/api/agent-studio/tools","tools"],["contracts","/api/agent-studio/contractus-presets","presets"],
      ["governance","/api/agent-studio/governance-presets","presets"],["core","/api/system/core-agents",null],
      ["prompts","/api/system/core-prompts",null]];
    const results=await Promise.allSettled(requests.map(async([key,url,field])=>{const value=await api(url);state[key]=field?value[field]||[]:value;}));
    const unavailable=results.map((result,index)=>result.status==="rejected"?requests[index][0]:null).filter(Boolean);
    render(); notify("studio-status",unavailable.length?"Bibliothek geladen; nicht erreichbar: "+unavailable.join(", "):state.blueprints.length+" Blueprints · Änderungen werden mit ihrer aktuellen Version gespeichert.",!!unavailable.length);
  }
  function renderRoles(value) {
    const roles=Object.keys(state.prompts?.prompts||{}).filter(key=>key.startsWith("role_")).map(key=>({value:key.slice(5),label:key.slice(5).replaceAll("_"," ")}));
    selectOptions($("bp-role"),[{value:"task_worker",label:"Eigene Rolle"},...roles],value||"personal-assistant");
  }
  function drawAvatar() {
    const identity={persona_role:$("bp-role").value};
    $("bp-avatar-preview").replaceChildren(createAvatar(document,state.avatar,identity,atlasUrl,'agent-avatar-preview'));
    mountAvatarPicker($("bp-avatar-presets"),state.avatar,identity,atlasUrl,value=>{state.avatar=value;drawAvatar();});
    mountSymbolPicker($("bp-symbols"),state.symbol,symbolUrls,value=>{state.symbol=value;drawAvatar();});
  }
  function editorPayload() {
    const previous=state.edit||{};
    const execution={backend:$("bp-backend").value,model:$("bp-model").value.trim(),mode:$("bp-mode").value,
      think:$("bp-think").checked,include_system_prompt:$("bp-include-system").checked,
      custom_system_prompt:$("bp-system").value,avatar:state.avatar,symbol:state.symbol,
      pause_after:Number($("bp-pause-after").value),pause_minutes:Number($("bp-pause-minutes").value),pause_basis:$("bp-pause-basis").value};
    return {name:$("bp-name").value.trim().toLowerCase(),title:$("bp-title").value.trim(),kind:$("bp-kind").value,
      description:$("bp-description").value,persona_role:$("bp-role").value,persona_prompt:$("bp-persona").value,
      expected_version:state.edit?.version||0,is_template:0,skills:checked("bp-skills"),animus_type:["claude","codex"].includes(execution.backend)?"cli":"api",
      modus:$("bp-modus").value,contractus:{...(previous.contractus||{}),turns:Number($("bp-turns").value),execution},
      governance:{...(previous.governance||{}),profile:$("bp-governance").value,tool_whitelist:checked("bp-tools")}};
  }
  function openEditor(blueprint=null,copy=false) {
    state.edit=blueprint&&!copy?blueprint:null;
    const bp=blueprint||{}, config=executionSettings(bp,currentLocal());
    $("blueprint-form").reset();$("bp-name").readOnly=!!state.edit;
    $("bp-name").value=copy?(bp.name+"-kopie-"+crypto.randomUUID().slice(0,6)):bp.name||"";
    $("bp-title").value=copy?(bp.title||bp.name)+" · Kopie":bp.title||"";
    $("bp-description").value=bp.description||"";choose($("bp-kind"),bp.kind||"agent");
    renderRoles(bp.persona_role);
    $("bp-persona").value=bp.persona_prompt||state.prompts?.prompts?.["role_"+$("bp-role").value]?.effective||"";
    $("bp-include-system").checked=config.include_system_prompt!==false;
    $("bp-system").value=config.custom_system_prompt||"";$("bp-system").disabled=!$("bp-include-system").checked;
    $("bp-system-default").textContent=state.prompts?.prompts?.system_default?.effective||"Systemvorlage derzeit nicht erreichbar.";
    choose($("bp-backend"),config.backend||"ollama");$("bp-model").value=config.model||"";
    choose($("bp-mode"),config.mode||"safe");$("bp-think").checked=config.think!==false;
    $("bp-turns").value=bp.contractus?.turns||bp.contractus?.max_turns||20;
    $("bp-pause-after").value=config.pause_after??5;$("bp-pause-minutes").value=config.pause_minutes??1;
    choose($("bp-pause-basis"),config.pause_basis||"runs");choose($("bp-modus"),bp.modus||"casualis");
    state.avatar=config.avatar||"";state.symbol=config.symbol||"";drawAvatar();
    selectOptions($("bp-contractus-preset"),[{value:"",label:"Eigener Arbeitsvertrag"},...state.contracts.map(p=>({value:p.id,label:p.title,disabled:p.execution_supported===false}))],"");
    selectOptions($("bp-governance"),state.governance.map(p=>({value:p.id,label:p.name})),bp.governance?.profile||"fail_closed_standard");
    const skillItems=state.skills.map(skill=>({id:skill.id,name:skill.name||skill.id,description:skill.evidence_type==="filesystem_present"?"Dateisystem · "+(skill.category||""):"Katalogeintrag · Installation nicht bestätigt"}));
    for(const id of bp.skills||[]) if(!skillItems.some(item=>item.id===id))skillItems.push({id,name:id,description:"Gespeichert · Quelle nicht verfügbar"});
    optionList($("bp-skills"),skillItems,bp.skills||[]);
    const selected=normalizeTools(bp.governance?.tool_whitelist||["read_file","list_directory","search_text","task_manage"]);
    const toolItems=state.tools.map(tool=>({id:tool.name,name:tool.name,description:tool.description}));
    for(const name of selected)if(!toolItems.some(item=>item.id===name))toolItems.push({id:name,name,description:"Nicht im aktuellen Toolkatalog · Freigabe vor Instanziierung ändern"});
    optionList($("bp-tools"),toolItems,selected);
    $("bp-tools-source").textContent="Native Toolfreigaben werden bei Ankündigung und Ausführung geprüft. Hooker-Anbindung wird hier nicht als Laufnachweis ausgewiesen.";
    $("editor-title").textContent=state.edit?"Blueprint bearbeiten":"Blueprint anlegen";
    $("editor-revision").textContent=state.edit?"Version "+bp.version:copy?"Kopie einer Vorlage":"Neuer Blueprint";
    $("bp-preview-text").hidden=true;notify("editor-status","");$("blueprint-editor").showModal();
    loadModels("bp").catch(error=>notify("editor-status",error.message,true));
  }
  async function loadModels(prefix) {
    const backend=$(prefix+"-backend").value;
    const data=await api("/api/system/workers/models?backend="+encodeURIComponent(backend));
    const list=$(prefix+"-models");
    if($(prefix+"-backend").value!==backend)return;
    list.replaceChildren(...(data.models||[]).filter(name=>typeof name==="string").map(name=>new Option(name,name)));
  }
  async function openInstance(bp) {
    state.instance=bp;
    const core=await api("/api/system/core-agents");state.core=core;state.instanceVersion=core.configuration_version;
    const config=instanceSettings(bp,core);state.instanceConfig=config;
    $("instance-backend").replaceChildren(...[...$("bp-backend").options].map(option=>new Option(option.text,option.value)));
    choose($("instance-backend"),config.backend||"ollama");$("instance-model").value=config.model||"";
    choose($("instance-mode"),config.mode||"safe");$("instance-description").textContent=bp.title||bp.name;
    notify("instance-status","");$("instance-editor").showModal();loadModels("instance").catch(error=>notify("instance-status",error.message,true));
  }
  async function runBlueprint(bp,button) {
    const core=await api("/api/system/core-agents"),slot=core.agents?.find(item=>item.blueprint_id===bp.id);
    if(!slot||slot.runtime_verified!==true||slot.running!==false)throw new Error("Aktueller Workerzustand erlaubt keinen Start. Living & Running prüfen.");
    const requestId=crypto.randomUUID().replaceAll("-","");
    button.disabled=true;
    try {
      const result=await post("/api/agent-studio/blueprints/"+bp.id+"/start",{expected_version:bp.version,configuration_version:core.configuration_version,start_request_id:requestId});
      if(!correlatedStart(result,slot.id,requestId))throw new Error("Startbeleg nicht bestätigt. Status vor einem weiteren Start prüfen.");
      await loadData();
      notify("studio-status",result.execution.terminal?"Lauf beendet · "+(result.execution.error_code||result.execution.state):
        result.execution.worker_thread_started?"Worker gestartet · Aufgaben im Taskboard zuweisen.":"Start angenommen · Startvorgang läuft.");
    }finally{button.disabled=false;}
  }
  function showPrompt() {
    const prompt=state.prompts?.prompts?.[$("prompt-key").value];
    $("prompt-effective").value=prompt?.effective||"";$("prompt-default").textContent=prompt?.default||"";
    $("prompt-save").disabled=state.prompts?.mutation_supported!==true;
    $("prompt-reset").disabled=$("prompt-save").disabled;
  }
  function renderTeams() {
    $("studio-team-grid").innerHTML=state.teams.map(team=>'<article class="studio-card"><div class="studio-card-top"><span class="studio-card-icon">👥</span><span class="studio-state">Teamkonfiguration</span></div><h3>'+escapeHtml(team.name)+'</h3><p>'+escapeHtml(team.description||"")+'</p><p>Koordination: '+escapeHtml(team.leader_agent||"–")+'<br>Mitglieder: '+escapeHtml(team.member_agents||"–")+'</p><div class="studio-card-actions"><button class="btn" data-team="'+Number(team.id)+'">Bearbeiten</button><a class="btn" href="/agenten/marblerun">Ablauf erstellen</a></div></article>').join("")||'<p class="studio-empty">Noch keine Teams gespeichert.</p>';
  }
  function teamLeaders(value) {
    const members=checked("team-members");
    selectOptions($("team-leader"),members.map(name=>({value:name,label:state.blueprints.find(bp=>bp.name===name)?.title||name})),members.includes(value)?value:members[0]||"");
    const drafts=Object.fromEntries([...$("team-models").querySelectorAll("input")].map(input=>[input.dataset.member,input.value]));
    $("team-models").innerHTML=members.map(name=>'<label>'+escapeHtml(state.blueprints.find(bp=>bp.name===name)?.title||name)+'<input data-member="'+escapeHtml(name)+'" maxlength="120" value="'+escapeHtml(drafts[name]??state.team?.member_models?.[name]??"")+'" placeholder="Steckplatzmodell" /></label>').join("");
  }
  function openTeam(team=null) {
    state.team=team;$("team-form").reset();$("team-models").replaceChildren();$("team-name").value=team?.name||"";$("team-description").value=team?.description||"";
    choose($("team-strategy"),team?.strategy||"swarm_parallel");
    const members=(team?.member_agents||"").split(",").map(name=>name.trim()).filter(Boolean);
    optionList($("team-members"),state.blueprints.filter(bp=>["agent","role"].includes(bp.kind)).map(bp=>({id:bp.name,name:bp.title||bp.name})),members);
    teamLeaders(team?.leader_agent);$("team-title").textContent=team?"Team bearbeiten":"Team anlegen";notify("team-status","");$("team-editor").showModal();
  }
  const handle = (id,event,fn,status="studio-status") => $(id).addEventListener(event,async e=>{try{await fn(e);}catch(error){notify(status,error.message,true);}});
  document.querySelectorAll("[data-close]").forEach(button=>button.addEventListener("click",()=>close(button.dataset.close)));
  document.querySelectorAll("[data-library]").forEach(button=>button.addEventListener("click",()=>{state.library=button.dataset.library;render();}));
  handle("studio-refresh","click",loadData);handle("studio-new","click",()=>openEditor());
  handle("studio-search","input",render);handle("studio-kind","change",render);
  handle("studio-grid","click",async event=>{
    const button=event.target.closest("[data-edit],[data-copy],[data-instance],[data-start],[data-delete]");if(!button)return;
    const attr=Object.keys(button.dataset).find(key=>["edit","copy","instance","start","delete"].includes(key)),bp=byId(button.dataset[attr]);if(!bp)return;
    if(attr==="edit")openEditor(bp);else if(attr==="copy")openEditor(bp,true);else if(attr==="instance")await openInstance(bp);else if(attr==="start")await runBlueprint(bp,button);
    else if(confirm("Blueprint „"+(bp.title||bp.name)+"“ entfernen?")){await api("/api/agent-studio/blueprints/"+bp.id+"?expected_version="+encodeURIComponent(bp.version),{method:"DELETE"});await loadData();}
  });
  handle("bp-role","change",()=>{const prompt=state.prompts?.prompts?.["role_"+$("bp-role").value]?.effective;if(prompt)$("bp-persona").value=prompt;drawAvatar();},"editor-status");
  handle("bp-include-system","change",()=>{$("bp-system").disabled=!$("bp-include-system").checked;},"editor-status");
  handle("bp-backend","change",()=>loadModels("bp"),"editor-status");
  handle("bp-skill-search","input",()=>{const query=$("bp-skill-search").value.toLowerCase();$("bp-skills").querySelectorAll("label").forEach(label=>label.hidden=!label.textContent.toLowerCase().includes(query));},"editor-status");
  handle("bp-contractus-preset","change",()=>{const p=state.contracts.find(item=>item.id===$("bp-contractus-preset").value);if(p){$("bp-turns").value=p.turns;choose($("bp-modus"),p.modus);$("bp-pause-minutes").value=Math.ceil(p.cooldown_seconds/60);}},"editor-status");
  handle("bp-governance","change",()=>{const preset=state.governance.find(p=>p.id===$("bp-governance").value);if(preset){const selected=new Set(normalizeTools(preset.tool_whitelist||[]));$("bp-tools").querySelectorAll("input").forEach(box=>box.checked=selected.has(box.value));if(preset.id==="read_only_research")$("bp-mode").value="safe";}},"editor-status");
  handle("bp-avatar-clear","click",()=>{state.avatar="";drawAvatar();},"editor-status");
  handle("bp-avatar-upload","change",async()=>{
    const file=$("bp-avatar-upload").files?.[0];if(!file)return;if(file.size>180000||!["image/png","image/jpeg","image/webp"].includes(file.type))throw new Error("Bitte PNG, JPEG oder WebP bis 180 KB verwenden.");
    state.avatar=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(file);});drawAvatar();
  },"editor-status");
  handle("bp-preview","click",async()=>{const data=await post("/api/agent-studio/synthesize-prompt",{blueprint:editorPayload()});$("bp-preview-text").textContent=data.start_prompt;$("bp-preview-text").hidden=false;},"editor-status");
  handle("blueprint-form","submit",async event=>{
    event.preventDefault();const payload=editorPayload();$("bp-save").disabled=true;
    try{
      const saved=await post("/api/agent-studio/blueprints",payload);await loadData();
      const readback=byId(saved.id);if(!readback||Number(readback.version)!==payload.expected_version+1||readback.persona_prompt!==payload.persona_prompt)throw new Error("Gespeicherte Version nicht bestätigt. Entwurf bleibt geöffnet.");
      close("blueprint-editor");state.library="custom";render();notify("studio-status","Blueprint gespeichert · Version "+readback.version);
    }finally{$("bp-save").disabled=false;}
  },"editor-status");
  handle("instance-backend","change",()=>loadModels("instance"),"instance-status");
  handle("instance-form","submit",async event=>{
    event.preventDefault();const bp=state.instance;const execution={...state.instanceConfig,backend:$("instance-backend").value,model:$("instance-model").value.trim(),mode:$("instance-mode").value};
    $("instance-save").disabled=true;
    try{
      const result=await post("/api/agent-studio/blueprints/"+bp.id+"/materialize",{expected_version:bp.version,configuration_version:state.instanceVersion,execution});
      if(result.worker_started!==false||result.slot_id!=="system-blueprint-"+bp.id)throw new Error("Instanziierung nicht bestätigt.");
      close("instance-editor");await loadData();notify("studio-status","Steckplatz eingerichtet · "+(result.is_living===true?"Living bereit":"Runtime-Status wird unter Living & Running geprüft"));
    }finally{$("instance-save").disabled=false;}
  },"instance-status");
  handle("studio-prompts","click",async()=>{
    state.prompts=await api("/api/system/core-prompts");state.promptVersion=state.prompts.configuration_version;
    selectOptions($("prompt-key"),Object.keys(state.prompts.prompts||{}).map(key=>({value:key,label:key==="system_default"?"Systemprompt":key.slice(5).replaceAll("_"," ")})),"system_default");
    showPrompt();notify("prompt-status","");$("prompt-editor").showModal();
  });
  handle("prompt-key","change",showPrompt,"prompt-status");
  async function mutatePrompt(reset=false) {
    const key=$("prompt-key").value;
    const result=await api("/api/system/core-prompts/"+encodeURIComponent(key)+(reset?"/reset":""),{method:reset?"POST":"PUT",body:JSON.stringify({configuration_version:state.promptVersion,text:$("prompt-effective").value})});
    if(result.ack?.configuration_saved!==true||result.ack?.worker_started!==false)throw new Error("Promptanpassung nicht bestätigt.");
    state.prompts=result;state.promptVersion=result.configuration_version;showPrompt();notify("prompt-status",reset?"Werkstandard wiederhergestellt.":"Anpassung gespeichert.");
  }
  handle("prompt-save","click",()=>mutatePrompt(),"prompt-status");
  handle("prompt-reset","click",()=>mutatePrompt(true),"prompt-status");
  handle("studio-new-team","click",()=>openTeam());
  handle("studio-team-grid","click",event=>{const button=event.target.closest("[data-team]");if(button)openTeam(state.teams.find(team=>Number(team.id)===Number(button.dataset.team)));});
  handle("team-members","change",()=>teamLeaders($("team-leader").value),"team-status");
  handle("team-form","submit",async event=>{
    event.preventDefault();const payload={name:$("team-name").value.trim(),description:$("team-description").value,strategy:$("team-strategy").value,leader_agent:$("team-leader").value,member_agents:checked("team-members").join(", "),expected_version:state.team?.version||0};
    payload.member_models=Object.fromEntries([...$("team-models").querySelectorAll("input")].filter(input=>input.value.trim()).map(input=>[input.dataset.member,input.value.trim()]));
    if(!payload.leader_agent)throw new Error("Bitte mindestens ein Mitglied auswählen.");
    await post("/api/agenten/teams"+(state.team?"/"+state.team.id:""),payload);close("team-editor");await loadData();
  },"team-status");
  loadData().then(()=>{
    const params=new URLSearchParams(location.search),id=params.get("edit")||params.get("copy");
    const bp=id?byId(id):state.blueprints.find(item=>item.name===params.get("blueprint"));
    if(["custom","templates","teams"].includes(params.get("tab"))){state.library=params.get("tab");render();}
    if(bp)openEditor(bp,params.has("copy")||bp.is_template===1);else if(params.has("new"))openEditor();
  }).catch(error=>notify("studio-status",error.message,true));
}
