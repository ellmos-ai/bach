// SPDX-License-Identifier: MIT
// Ordered flow nodes/arrows and drag-to-add adapted from skills-board.js renderFlowNodes.
export const escapeHtml=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
export function flowNodes(steps){
  if(!steps.length)return '<span class="chain-note">Agenten oder Skills hierher ziehen oder einen Schritt hinzufügen.</span>';
  return steps.map((node,index)=>`<div class="flow-node" data-index="${index}"><span class="node-icon">${index+1}</span><span>${escapeHtml(node.label)}</span></div>${index<steps.length-1?'<span class="flow-arrow">→</span>':''}`).join('');
}
export function moveStep(steps,index,delta){
  const copy=steps.slice(); const next=index+delta;
  if(!Number.isInteger(index)||!Number.isInteger(delta)||index<0||index>=copy.length||next<0||next>=copy.length)return copy;
  [copy[index],copy[next]]=[copy[next],copy[index]];return copy;
}
export function phaseLabel(run){
  if(run.phase==='unconfirmed')return 'Lauf nicht bestätigt';
  const labels={ready:'Start vorbereitet',starting:'Schritt wird zugelassen',running:'Running',stopping:'Stop angefordert',complete:'Abgeschlossen',failed:'Schritt ohne bestätigtes Ergebnis',stopped:'Gestoppt'};
  return labels[run.phase]||'Status unbekannt';
}
export function selectedModels(chain,agents){
  return chain.steps.map(step=>agents.find(agent=>agent.id===(chain.mode==='skills'?chain.agent_slot:step.agent_slot))||{id:step.agent_slot,name:'Agent nicht verfügbar'});
}

if(typeof document!=='undefined')initialize();
function initialize(){
  const $=id=>document.getElementById(id),state={catalog:null,edit:null,steps:[],start:null,startRequest:null,busy:false};
  const notify=(id,text,error=false)=>{ $(id).textContent=text;$(id).dataset.error=String(error); };
  async function api(path,options={}){
    const response=await fetch(path,{...options,headers:{'Content-Type':'application/json',...options.headers}});
    let data;try{data=await response.json();}catch{throw new Error('Antwort nicht lesbar (HTTP '+response.status+')');}
    if(!response.ok||data.ok===false)throw new Error((data.detail||data.error||'Anfrage nicht bestätigt')+' (HTTP '+response.status+')');
    return data;
  }
  const button=(label,action)=>{const b=document.createElement('button');b.type='button';b.className='btn';b.textContent=label;b.addEventListener('click',action);return b;};
  const option=(value,label)=>{const o=document.createElement('option');o.value=value;o.textContent=label;return o;};
  const agentText=a=>`${a.name} · ${a.backend||'Anbieter unbekannt'} / ${a.model||'Modell unbekannt'}`;
  const selectedChain=id=>state.catalog.chains.find(c=>c.id===id);
  async function load(){
    try{state.catalog=await api('/api/marblerun/catalog');render();notify('chain-status',state.catalog.runtime_available?'Katalog und nativer Controller verbunden.':state.catalog.unavailable_reason||'Ausführung nicht verfügbar.',!state.catalog.runtime_available);}
    catch(error){notify('chain-status',error.message,true);}
  }
  function render(){
    $('chains-grid').replaceChildren();
    for(const chain of state.catalog.chains){
      const card=document.createElement('article');card.className='chain-card';card.dataset.chainId=chain.id;
      const title=document.createElement('h3');title.textContent=chain.title||chain.name;
      const note=document.createElement('p');note.className='chain-note';note.textContent=`${chain.steps.length} Schritte · ${chain.legacy?'Zuordnung erforderlich':chain.mode==='skills'?'Ein Agent · Skillfolge':'Agentenfolge'} · Version ${chain.version}`;
      const description=document.createElement('p');description.textContent=chain.description||'';
      const actions=document.createElement('div');actions.className='chain-actions';
      const start=button('Starten',()=>openStart(chain));start.disabled=chain.legacy||!state.catalog.runtime_available;
      actions.append(start,button(chain.legacy?'Zuordnen':'Bearbeiten',()=>openEditor(chain)),button('Löschen',async()=>{
        if(!confirm('Kette „'+(chain.title||chain.name)+'“ löschen?'))return;
        try{await api('/api/marblerun/chains/'+chain.id+'?version='+chain.version,{method:'DELETE'});await load();}catch(error){notify('chain-status',error.message,true);}
      }));card.append(title,note,description,actions);$('chains-grid').append(card);
    }
    if(!state.catalog.chains.length)$('chains-grid').textContent='Noch keine Kette gespeichert.';
    $('chain-runs').replaceChildren();
    for(const run of state.catalog.runs){
      const card=document.createElement('article');card.className='chain-card';card.dataset.runId=run.run_id;
      const h=document.createElement('h3');h.textContent=phaseLabel(run)+' · '+run.cursor+'/'+run.step_count;
      const note=document.createElement('p');note.className='chain-note';note.textContent='Lauf '+run.run_id+' · '+(selectedChain(run.chain_id)?.title||'Kette #'+run.chain_id);
      card.append(h,note);
      if(run.stop_requested){const p=document.createElement('p');p.textContent='Stop wurde dauerhaft angefordert.';card.append(p);}
      if(run.reason){const p=document.createElement('p');p.textContent=run.reason;card.append(p);}
      for(const step of run.steps){const p=document.createElement('p');p.className='chain-note';const link=document.createElement('a');link.href='/tasks?task_id='+step.task_id;link.textContent='Task #'+step.task_id;p.append('Schritt '+(step.cursor+1)+' · ',link);card.append(p);}
      if(run.completed.length){const details=document.createElement('details');const summary=document.createElement('summary');summary.textContent='Fachliche Ergebnisse';details.append(summary);for(const result of run.completed){const pre=document.createElement('pre');pre.textContent=result.output;details.append(pre);}card.append(details);}
      if(!['complete','failed','stopped'].includes(run.phase)){
        const stop=button(run.stop_requested?'Stopstatus prüfen':'Stop',async()=>{
          try{await api('/api/marblerun/runs/'+run.run_id+'/stop',{method:'POST',body:'{}'});await load();}catch(error){notify('chain-status',error.message,true);}
        });stop.disabled=run.runtime_verified!==true;card.append(stop);
      }
      $('chain-runs').append(card);
    }
    if(!state.catalog.runs.length)$('chain-runs').textContent='Noch kein nativer Kettenlauf gestartet.';
  }
  function openEditor(chain=null){
    if(!state.catalog)return;
    state.edit=chain;state.steps=(chain?.steps||[]).map(s=>typeof s==='object'?{label:s.label||s.name||s.id||'Schritt',agent_slot:s.agent_slot||'',skill_ids:s.skill_ids||[],instructions:s.instructions||''}:{label:String(s),agent_slot:'',skill_ids:[],instructions:''});
    $('chain-editor-title').textContent=chain?'Kette bearbeiten · Version '+chain.version:'Neue Kette';
    $('chain-name').value=chain?.name||'';$('chain-title').value=chain?.title||'';$('chain-description').value=chain?.description||'';
    $('chain-mode').value=chain?.mode==='skills'?'skills':'agents';
    $('chain-agent').replaceChildren(option('','Agent auswählen'),...state.catalog.agents.map(a=>option(a.id,agentText(a))));$('chain-agent').value=chain?.agent_slot||'';
    notify('chain-editor-status',chain?.legacy?'Ordne jedem bestehenden Schritt einen ausführenden Agenten oder Skill zu.':'');
    renderEditor();$('chain-editor').showModal();
  }
  function renderEditor(){
    const skillMode=$('chain-mode').value==='skills';$('chain-agent-field').hidden=!skillMode;
    $('chain-palette').replaceChildren();
    const search=$('chain-palette-search').value.toLocaleLowerCase('de');
    const palette=(skillMode?state.catalog.skills:state.catalog.agents).filter(item=>(item.name+' '+item.id).toLocaleLowerCase('de').includes(search)).slice(0,24);
    for(const item of palette){
      const b=button(item.name,()=>addFromPalette(item.id));b.classList.add('chain-button');b.draggable=true;
      b.addEventListener('dragstart',event=>event.dataTransfer.setData('application/bach-sequence-step',JSON.stringify({mode:$('chain-mode').value,id:item.id})));
      $('chain-palette').append(b);
    }
    $('pipeline-canvas').innerHTML=flowNodes(state.steps);$('chain-steps').replaceChildren();
    state.steps.forEach((step,index)=>{
      const card=document.createElement('div');card.className='chain-step';
      const head=document.createElement('div');head.className='chain-step-heading';const title=document.createElement('strong');title.textContent='Schritt '+(index+1);
      const controls=document.createElement('div');controls.className='chain-step-controls';
      const up=button('↑',()=>{state.steps=moveStep(state.steps,index,-1);renderEditor();});up.disabled=index===0;up.setAttribute('aria-label','Schritt nach oben verschieben');
      const down=button('↓',()=>{state.steps=moveStep(state.steps,index,1);renderEditor();});down.disabled=index===state.steps.length-1;down.setAttribute('aria-label','Schritt nach unten verschieben');
      controls.append(up,down,button('Entfernen',()=>{state.steps.splice(index,1);renderEditor();}));head.append(title,controls);card.append(head);
      function field(label,input){const l=document.createElement('label');l.textContent=label;l.append(input);card.append(l);}
      const label=document.createElement('input');label.required=true;label.maxLength=120;label.value=step.label;label.addEventListener('input',()=>{step.label=label.value;$('pipeline-canvas').innerHTML=flowNodes(state.steps);});field('Bezeichnung',label);
      const select=document.createElement('select');select.required=true;select.append(option('',skillMode?'Skill auswählen':'Agent auswählen'));
      for(const item of skillMode?state.catalog.skills:state.catalog.agents)select.append(option(item.id,skillMode?item.name:agentText(item)));
      select.value=skillMode?(step.skill_ids[0]||''):step.agent_slot;
      select.addEventListener('change',()=>{if(skillMode)step.skill_ids=select.value?[select.value]:[];else step.agent_slot=select.value;});field(skillMode?'Skill':'Ausführender Agent',select);
      const instructions=document.createElement('textarea');instructions.rows=2;instructions.maxLength=12000;instructions.value=step.instructions;instructions.addEventListener('input',()=>step.instructions=instructions.value);field('Schrittanweisung',instructions);
      $('chain-steps').append(card);
    });
  }
  function addFromPalette(id){
    if(state.steps.length>=32){notify('chain-editor-status','Höchstens 32 Schritte.',true);return;}
    const skillMode=$('chain-mode').value==='skills',item=(skillMode?state.catalog.skills:state.catalog.agents).find(x=>x.id===id);
    if(!item)return;
    state.steps.push({label:item.name,agent_slot:skillMode?'':item.id,skill_ids:skillMode?[item.id]:[],instructions:''});renderEditor();
  }
  function openStart(chain){
    state.start=chain;state.startRequest=null;$('chain-start-title').textContent='„'+(chain.title||chain.name)+'“ starten';
    const models=selectedModels(chain,state.catalog.agents);$('chain-start-summary').textContent=models.map((a,i)=>`${i+1}. ${agentText(a)}`).join(' → ');
    $('chain-start-preview').innerHTML=flowNodes(chain.steps);$('chain-input').value='';notify('chain-start-status','');$('chain-start-dialog').showModal();
  }
  $('chain-form').addEventListener('submit',async event=>{
    event.preventDefault();if(state.busy||!$('chain-form').reportValidity())return;
    const data={name:$('chain-name').value,title:$('chain-title').value,description:$('chain-description').value,mode:$('chain-mode').value,agent_slot:$('chain-agent').value,steps:state.steps};
    if(!data.steps.length||(data.mode==='skills'&&!data.agent_slot)){notify('chain-editor-status','Wähle einen Agenten und mindestens einen Schritt.',true);return;}
    state.busy=true;$('chain-save').disabled=true;
    try{await api('/api/marblerun/chains'+(state.edit?'/'+state.edit.id:''),{method:state.edit?'PUT':'POST',body:JSON.stringify(state.edit?{version:state.edit.version,definition:data}:data)});$('chain-editor').close();await load();}
    catch(error){notify('chain-editor-status',error.message,true);}finally{state.busy=false;$('chain-save').disabled=false;}
  });
  $('chain-start-form').addEventListener('submit',async event=>{
    event.preventDefault();if(state.busy||!$('chain-start-form').reportValidity())return;
    state.startRequest??={request_id:crypto.randomUUID().replaceAll('-',''),version:state.start.version,configuration_version:state.catalog.configuration_version,expected_service_instance:state.catalog.service_instance,input:$('chain-input').value};
    state.busy=true;$('chain-start-submit').disabled=true;
    try{const data=await api('/api/marblerun/chains/'+state.start.id+'/run',{method:'POST',body:JSON.stringify(state.startRequest)});if(data.accepted!==true||data.run?.run_id!==state.startRequest.request_id)throw new Error('Startkennung nicht bestätigt');$('chain-start-dialog').close();await load();}
    catch(error){notify('chain-start-status',error.message+' Bei fehlender Antwort wird dieselbe Startkennung erneut geprüft.',true);}finally{state.busy=false;$('chain-start-submit').disabled=false;}
  });
  $('chain-mode').addEventListener('change',renderEditor);$('chain-add-step').addEventListener('click',()=>{if(state.steps.length<32){state.steps.push({label:'Neuer Schritt',agent_slot:'',skill_ids:[],instructions:''});renderEditor();}});
  $('chain-palette-search').addEventListener('input',renderEditor);
  $('pipeline-canvas').addEventListener('dragover',event=>{event.preventDefault();$('pipeline-canvas').classList.add('drag-over');});
  $('pipeline-canvas').addEventListener('dragleave',()=>$('pipeline-canvas').classList.remove('drag-over'));
  $('pipeline-canvas').addEventListener('drop',event=>{event.preventDefault();$('pipeline-canvas').classList.remove('drag-over');try{const item=JSON.parse(event.dataTransfer.getData('application/bach-sequence-step'));if(item.mode===$('chain-mode').value)addFromPalette(item.id);}catch{notify('chain-editor-status','Schritt nicht erkannt.',true);}});
  document.querySelectorAll('[data-close]').forEach(b=>b.addEventListener('click',() => $(b.dataset.close).close()));
  $('chain-new').addEventListener('click',()=>openEditor());$('chain-refresh').addEventListener('click',load);load();
  setInterval(()=>{if(!document.hidden&&!state.busy&&!$('chain-editor').open&&!$('chain-start-dialog').open)load();},5000);
}
