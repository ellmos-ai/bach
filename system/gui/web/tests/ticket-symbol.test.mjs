import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {TICKET_SYMBOLS,createSymbol,withSkillSymbol} from '../src/lib/ticket-symbol.mjs';

test('sixteen existing Ticket-Master symbols are bundled with no active SVG content',()=>{
  assert.equal(TICKET_SYMBOLS.length,16);
  for(const item of TICKET_SYMBOLS){
    const svg=readFileSync(new URL('../src/assets/ticket-symbols/'+item.id+'.svg',import.meta.url),'utf8');
    assert.match(svg,/<svg\s/);
    assert.doesNotMatch(svg,/<(?:script|foreignObject)|\bon\w+\s*=|(?:href|src)\s*=["'](?:https?:|javascript:|data:)/i);
  }
});

test('symbol images resolve only known bundled assets',()=>{
  const doc={createElement:tag=>({tag,dataset:{},setAttribute(){}})};
  const urls={wissen:'/_astro/wissen.abc.svg'};
  assert.equal(createSymbol(doc,'https://foreign.example/bad.svg',urls,'wissen').src,urls.wissen);
  assert.throws(()=>createSymbol(doc,'wissen',{wissen:'https://foreign.example/bad.svg'}),/Symbolquelle/);
});

test('the skill symbol lives in frontmatter and preserves the remaining source and newlines',()=>{
  const text='---\r\nname: Grüße\r\nsymbol: wissen\r\ndescription: |\r\n  Österreich\r\n---\r\n# Inhalt\r\n';
  const changed=withSkillSymbol(text,'scripts');
  assert.match(changed,/symbol: scripts\r\n/);assert.doesNotMatch(changed,/symbol: wissen/);
  assert.ok(changed.endsWith('description: |\r\n  Österreich\r\n---\r\n# Inhalt\r\n'));
  assert.equal(withSkillSymbol('# Neu\n','wissen'),'---\nsymbol: wissen\n---\n# Neu\n');
  assert.throws(()=>withSkillSymbol('---\nsymbol: |\n  alt\n---\n# X','scripts'),/mehrzeilig/);
});

test('quoted, escaped and indented YAML root keys are rejected without changing source',()=>{
  for(const header of ['"symbol": wissen\nname: X','name: X\n\'symbol\': wissen',
    'name: X\n"sy\\u006dbol": wissen','  name: X\n  symbol: wissen','? symbol\n: wissen','- symbol: wissen']) {
    const source='---\n'+header+'\n---\n# Inhalt';
    assert.throws(()=>withSkillSymbol(source,'scripts'),/komplexe Form/);
    assert.equal(source,'---\n'+header+'\n---\n# Inhalt');
  }
});
