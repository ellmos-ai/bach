#!/usr/bin/env python3
import re,sys
WT="/Users/lukas/services/bach-worktrees/task-2619"
CB=re.compile(r"```[^\n]*\n.*?```",re.S);HP=re.compile(r"^(#{1,6}) ",re.M)
DN=re.compile(r"[A-ZÄÖÜ][A-ZÄÖÜ0-9_-]{3,}\.md");H12=re.compile(r"^#{1,2} ",re.M)
def L(n):return open(WT+"/"+n,encoding="utf-8").read()
def S(n,t):open(WT+"/"+n,"w",encoding="utf-8").write(t)
m=sys.argv[1]
de=L("SKILL.md");cbd=CB.findall(de);hd=HP.findall(de);ok=True
for name in ("SKILL_EN.md","SKILL_ES.md"):
 t=L(name);cbt=CB.findall(t);ht=HP.findall(t)
 ex=sorted(set(DN.findall(t))-set(DN.findall(de)))
 print(name,"CB",len(cbt),"DE",len(cbd),"HP",len(ht),"DE",len(hd),"H12",len(H12.findall(t)),"DOCextra",ex)
 if m=="check":
  print(name,"fences",t.count("```"),"DEfences",de.count("```"))
  print("HPdiff",[(i,hd[i] if i<len(hd) else None,ht[i] if i<len(ht) else None) for i in range(max(len(hd),len(ht))) if (hd[i] if i<len(hd) else None)!=(ht[i] if i<len(ht) else None)])
 if m=="sync":
  if len(cbt)!=len(cbd):print("ABORT",name,len(cbt),"!=",len(cbd));ok=False;continue
  o=[];p=0
  for i,mm in enumerate(CB.finditer(t)):
   o.append(t[p:mm.start()]);o.append(cbd[i]);p=mm.end()
  o.append(t[p:]);new="".join(o)
  if CB.findall(new)!=cbd:print("FAILOUT",name);ok=False;continue
  if new!=t:S(name,new);print("SYNC",name,len(cbt),"Bloecke->DE")
  else:print("SKIP",name,"Blocks gleich")
 if m=="verify":
  c1=cbt==cbd;c2=ht==hd;c3=(ex==[])
  print("PASSCHECK",name,c1,c2,c3)
  ok=ok and c1 and c2 and c3
sys.exit(0 if ok else 1)