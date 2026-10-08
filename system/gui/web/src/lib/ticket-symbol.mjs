export const TICKET_SYMBOLS = [
  ['topics_ai','KI & Agenten'], ['scripts','Tools & Abläufe'], ['wissen','Wissen'],
  ['topics_research','Recherche'], ['topics_software','Software'], ['server','Server'],
  ['githubbot','GitHub'], ['sync','Sync'], ['office','Büro'], ['usr','Persönlich'],
  ['topics_hardware','Hardware'], ['topics_roblox','Games'], ['topics_umbruch','Um:bruch'],
  ['topics_uni','Studium'], ['topics_gesim','Gesim'], ['topics','Themen'],
].map(([id,name])=>({id,name}));

export function createSymbol(document,value,urls,fallback='topics_ai') {
  const known=TICKET_SYMBOLS.find(item=>item.id===value)||TICKET_SYMBOLS.find(item=>item.id===fallback);
  if(!known)throw new Error('Symbol nicht verfügbar.');
  const url=urls[known.id];
  if(typeof url!=='string'||!/^\/_astro\/[A-Za-z0-9_-][A-Za-z0-9._-]*\.svg$/.test(url))throw new Error('Symbolquelle nicht verfügbar.');
  const image=document.createElement('img');image.src=url;image.alt='';image.className='ticket-symbol';
  image.setAttribute('aria-hidden','true');image.dataset.symbol=known.id;return image;
}

export function mountSymbolPicker(container,value,urls,onSelect,fallback='topics_ai') {
  container.replaceChildren();
  for(const item of TICKET_SYMBOLS){
    const button=container.ownerDocument.createElement('button');button.type='button';button.className='symbol-choice';
    button.title=item.name;button.setAttribute('aria-label',item.name);
    button.setAttribute('aria-pressed',String(item.id===(value||fallback)));
    button.append(createSymbol(container.ownerDocument,item.id,urls));
    button.addEventListener('click',()=>onSelect(item.id));container.append(button);
  }
}

// An explicit frontmatter field keeps the selected symbol versioned with SKILL.md.
export function withSkillSymbol(content,symbol) {
  if(!TICKET_SYMBOLS.some(item=>item.id===symbol))throw new Error('Unbekanntes Symbol.');
  const newline=content.includes('\r\n')?'\r\n':'\n';
  const header=/^(---\r?\n)([\s\S]*?)(\r?\n---(?=\r?\n|$))/.exec(content);
  if(!header)return '---'+newline+'symbol: '+symbol+newline+'---'+newline+content;
  const first=header[2].split(/\r?\n/).find(line=>line.trim()&&!/^\s*#/.test(line));
  if((first&&!/^[A-Za-z_][A-Za-z0-9_-]*\s*:/.test(first))||/^["'?%]|^\.\.\./m.test(header[2]))
    throw new Error('Der YAML-Kopf verwendet eine komplexe Form. Bitte das Symbol direkt in der Anleitung bearbeiten.');
  if(/^symbol\s*:[^\r\n]*[|>\[\{&*]/m.test(header[2])||/^symbol\s*:[ \t]*\r?\n[ \t]+\S/m.test(header[2]))
    throw new Error('Das vorhandene Symbolfeld ist mehrzeilig. Bitte in der Anleitung bearbeiten.');
  const lines=header[2].split(/\r?\n/).filter(line=>!/^symbol\s*:/.test(line));
  return header[1]+['symbol: '+symbol,...lines].join(newline)+header[3]+content.slice(header[0].length);
}

if(typeof window!=='undefined')window.BachSymbols={createSymbol,mountSymbolPicker};
