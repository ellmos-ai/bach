import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import {Script} from "node:vm";

const page=readFileSync(new URL("../src/pages/agenten/fabrika.astro",import.meta.url),"utf8");
const source=page.match(/<script is:inline>([\s\S]*?)<\/script>/)[1];
function redirect(search) {
  let destination;
  new Script(source).runInNewContext({URL,URLSearchParams,location:{origin:"http://127.0.0.1:8000",search,replace(value){destination=value;}}});
  return destination;
}
test("the former factory opens the consolidated editor",()=>{
  assert.equal(redirect(""),"/agenten/blueprints?new=1");
});
test("legacy blueprint and team links keep their destination",()=>{
  assert.equal(redirect("?load=entwickler"),"/agenten/blueprints?blueprint=entwickler");
  assert.equal(redirect("?tab=teambuilding"),"/agenten/blueprints?tab=teams");
});
test("legacy links cannot redirect to external sites",()=>{
  assert.equal(redirect("?load=https://external.example"),"/agenten/blueprints?blueprint=https%3A%2F%2Fexternal.example");
});
