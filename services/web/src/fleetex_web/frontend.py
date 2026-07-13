"""Minimal Fleetex web frontend (Phase 7e).

Self-contained vanilla-JS pages (no build step, no external CDN) that consume the
JSON APIs built in Phases 7a-7d: login/register, a project dashboard, and a basic
editor (file tree + load/edit/save a doc, add/delete entities). This makes Fleetex
openable end-to-end in a browser for single-user editing over HTTP.

Live multi-user OT editing needs document-updater (Phase 8) + the real-time socket;
this frontend edits via the docstore-backed HTTP save endpoint.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from .collab_js import COLLAB_JS
from .sessions import generate_session_id, serialize_user
from .users import UserManager

_CSS = """
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;font:14px/1.5 system-ui,sans-serif;background:#12141a;color:#e6e8ee}
a{color:#6ea8fe;text-decoration:none}
.card{max-width:380px;margin:8vh auto;background:#1b1e27;padding:28px;border-radius:12px;box-shadow:0 8px 30px #0006}
.card h1{margin:0 0 4px;font-size:22px}.muted{color:#8a90a2;font-size:13px}
input,button,textarea{font:inherit}
input{width:100%;padding:10px;margin:8px 0;background:#12141a;border:1px solid #2a2e3a;border-radius:8px;color:#e6e8ee}
button{cursor:pointer;background:#2f6fed;border:0;color:#fff;padding:10px 14px;border-radius:8px;font-weight:600}
button.ghost{background:#2a2e3a}
button:hover{filter:brightness(1.1)}
.err{color:#ff6b6b;min-height:18px;font-size:13px}
.top{display:flex;align-items:center;gap:12px;padding:10px 16px;background:#1b1e27;border-bottom:1px solid #2a2e3a}
.top .grow{flex:1}
.brand{font-weight:700;letter-spacing:.3px}
.list{max-width:760px;margin:24px auto;padding:0 16px}
.proj{display:flex;align-items:center;gap:12px;padding:12px 14px;background:#1b1e27;border:1px solid #2a2e3a;border-radius:10px;margin-bottom:8px}
.proj .grow{flex:1}.proj .name{font-weight:600}
.editor{display:grid;grid-template-columns:240px 1fr 1fr;height:calc(100vh - 49px)}
.tree{border-right:1px solid #2a2e3a;overflow:auto;padding:8px}
.tree .file{padding:6px 8px;border-radius:6px;cursor:pointer;display:flex;gap:8px}
.tree .file:hover{background:#2a2e3a}.tree .file.active{background:#2f6fed33}
.pane{display:flex;flex-direction:column;min-width:0}
.pane .bar{display:flex;gap:8px;align-items:center;padding:8px;border-bottom:1px solid #2a2e3a}
.edwrap{flex:1;display:flex;min-height:0;background:#0e1016;overflow:hidden}
.gutter{padding:14px 8px 14px 12px;text-align:right;color:#454b5c;background:#0e1016;font:13px/1.6 ui-monospace,monospace;white-space:pre;overflow:hidden;user-select:none;border-right:1px solid #1b1e27}
.edarea{position:relative;flex:1;min-width:0}
.hl{position:absolute;inset:0;margin:0;padding:14px;font:13px/1.6 ui-monospace,monospace;white-space:pre-wrap;word-break:break-word;overflow:auto;pointer-events:none;color:#e6e8ee}
.edarea textarea{position:absolute;inset:0;padding:14px;border:0;background:transparent;color:transparent;caret-color:#e6e8ee;white-space:pre-wrap;word-break:break-word;resize:none;font:13px/1.6 ui-monospace,monospace}
.tok-cmd{color:#6ea8fe}.tok-com{color:#5b6270;font-style:italic}.tok-mth{color:#e0a458}.tok-brc{color:#c678dd}
.cursors{position:absolute;inset:0;pointer-events:none;overflow:hidden}
.rcursor{position:absolute;width:2px}
.rlabel{position:absolute;font-size:10px;padding:0 4px;border-radius:3px;color:#fff;white-space:nowrap;transform:translateY(-100%);font-family:system-ui}
.presence{display:flex;gap:4px;margin-right:8px}
.avatar{width:24px;height:24px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#fff;border:1px solid #12141a}
.pdf{display:flex;flex-direction:column;border-left:1px solid #2a2e3a;min-width:0}
.pdf .bar{display:flex;gap:8px;align-items:center;padding:8px;border-bottom:1px solid #2a2e3a}
.pdf iframe{flex:1;border:0;background:#fff}
.histpanel{position:fixed;top:0;right:0;width:380px;max-width:90vw;height:100vh;background:#1b1e27;border-left:1px solid #2a2e3a;box-shadow:-8px 0 30px #0007;display:none;flex-direction:column;z-index:50}
.histpanel.open{display:flex}
.histpanel .bar{display:flex;gap:8px;align-items:center;padding:12px 14px;border-bottom:1px solid #2a2e3a}
.histpanel .bar b{font-size:15px}
.histlist{overflow:auto;max-height:40%;border-bottom:1px solid #2a2e3a}
.hitem{padding:10px 14px;border-bottom:1px solid #23262f;cursor:pointer}
.hitem:hover{background:#2a2e3a}.hitem.active{background:#2f6fed33}
.hitem .hv{font-weight:600}.hitem .hmeta{color:#8a90a2;font-size:12px}
.histdiff{flex:1;overflow:auto;padding:14px;font:12px/1.6 ui-monospace,monospace;white-space:pre-wrap;word-break:break-word}
.seg-i{background:#1f6f3f66;color:#8ff0b0;text-decoration:none}
.seg-d{background:#7a2b2b66;color:#ff9d9d;text-decoration:line-through}
.histempty{padding:20px 14px;color:#8a90a2}
.histpanel .foot{padding:12px 14px;border-top:1px solid #2a2e3a;display:flex;gap:8px;align-items:center}
"""


def _page(title: str, body: str) -> str:
    return f"<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>{title}</title><style>{_CSS}</style></head><body>{body}</body></html>"


LOGIN_PAGE = _page("Fleetex — Sign in", """
<div class=card>
  <h1>Fleetex</h1><div class=muted>Self-hosted LaTeX editor. Sign in.</div>
  <input id=email type=email placeholder=Email autofocus>
  <input id=password type=password placeholder=Password>
  <div class=err id=err></div>
  <button onclick=login()>Sign in</button>
  <p class=muted>No account? <a href=/register>Create one</a></p>
</div>
<script>
async function login(){
  err.textContent='';
  const r=await fetch('/login',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({email:email.value,password:password.value})});
  if(r.ok){location.href='/projects'}else{const d=await r.json().catch(()=>({}));err.textContent=(d.message&&(d.message.text||d.message.key))||'Sign in failed'}
}
password.addEventListener('keydown',e=>{if(e.key==='Enter')login()});
</script>""")

REGISTER_PAGE = _page("Fleetex — Register", """
<div class=card>
  <h1>Create account</h1><div class=muted>Fleetex (self-hosted).</div>
  <input id=email type=email placeholder=Email autofocus>
  <input id=password type=password placeholder='Password (min 6 chars)'>
  <div class=err id=err></div>
  <button onclick=register()>Create account</button>
  <p class=muted>Have an account? <a href=/login>Sign in</a></p>
</div>
<script>
async function register(){
  err.textContent='';
  const r=await fetch('/register',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({email:email.value,password:password.value})});
  if(r.ok){location.href='/projects'}else{const d=await r.json().catch(()=>({}));err.textContent=(d.message&&d.message.text)||'Registration failed'}
}
</script>""")

DASHBOARD_PAGE = _page("Fleetex — Projects", """
<div class=top><span class=brand>Fleetex</span><span class=grow></span>
  <button onclick=newProject()>New project</button>
  <button class=ghost onclick=logout()>Sign out</button></div>
<div class=list id=list><div class=muted>Loading…</div></div>
<script>
async function load(){
  const r=await fetch('/api/project',{method:'POST',headers:{'content-type':'application/json'},body:'{}'});
  if(r.status===401){location.href='/login';return}
  const d=await r.json();
  if(!d.projects.length){list.innerHTML='<div class=muted>No projects yet. Create one!</div>';return}
  list.innerHTML=d.projects.map(p=>`<div class=proj><div class=grow><div class=name><a href='/project/${p.id}'>${esc(p.name)}</a></div><div class=muted>${p.accessLevel} · ${p.lastUpdated?new Date(p.lastUpdated).toLocaleString():''}</div></div><button class=ghost onclick="del('${p.id}')">Delete</button></div>`).join('');
}
function esc(s){return (s||'').replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]))}
async function newProject(){const n=prompt('Project name:');if(!n)return;const r=await fetch('/project/new',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({projectName:n})});if(r.ok){const d=await r.json();location.href='/project/'+d.project_id}else alert('Could not create project')}
async function del(id){if(!confirm('Delete this project?'))return;await fetch('/project/'+id,{method:'DELETE'});load()}
async function logout(){await fetch('/logout',{method:'POST'});location.href='/login'}
load();
</script>""")

EDITOR_PAGE = _page("Fleetex — Editor", """
<div class=top><a href=/projects>← Projects</a><span class=brand id=pname>…</span><span class=grow></span>
  <span class=presence id=presence></span>
  <span class=muted id=conn>connecting…</span>
  <span class=muted id=status></span>
  <button id=compileBtn onclick=compile()>Compile ▶</button>
  <button class=ghost onclick=share()>Share</button>
  <button class=ghost onclick=toggleHistory()>🕘 History</button>
  <button class=ghost onclick=newDoc()>New doc</button>
  <button class=ghost onclick=fileinput.click()>Upload</button>
  <input type=file id=fileinput style=display:none onchange=doUpload()></div>
<div class=editor>
  <div class=tree id=tree></div>
  <div class=pane>
    <div class=bar><span class=muted id=cur>No document open</span><span class=grow></span>
      <button id=save onclick=save() disabled>Save</button>
      <button class=ghost id=delbtn onclick=delDoc() disabled>Delete</button></div>
    <div class=edwrap>
      <div class=gutter id=gutter>1</div>
      <div class=edarea>
        <pre class=hl id=hl></pre>
        <textarea id=ed placeholder='Open a document from the file tree…' spellcheck=false></textarea>
        <div class=cursors id=cursors></div>
      </div>
    </div>
  </div>
  <div class=pdf>
    <div class=bar><span class=muted id=pdfstatus>Press Compile ▶ to build the PDF</span><span class=grow></span>
      <a id=pdfdl class=muted style='display:none' download='output.pdf'>⬇ PDF</a></div>
    <iframe id=pdfframe></iframe>
  </div>
</div>
<div class=histpanel id=histpanel>
  <div class=bar><b>History</b><span class=muted id=histdoc></span><span class=grow></span>
    <button class=ghost onclick=toggleHistory()>✕</button></div>
  <div class=histlist id=histlist></div>
  <div class=histdiff id=histdiff><div class=histempty>Select a version to see what changed.</div></div>
  <div class=foot><span class=muted id=histsel>No version selected</span><span class=grow></span>
    <button id=restoreBtn onclick=restoreSelected() disabled>Restore this version</button></div>
</div>
<script src="/assets/collab.js"></script>
<script>
const pid=location.pathname.split('/')[2];
let boot=null, sock=null, doc=null, curId=null, lastValue='', applyingRemote=false;
let myPublicId=null, myName='anon', peers={}, cursorTimer=null;
function esc(s){return (s||'').replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]))}
function setConn(t){conn.textContent=t}
function fileLabel(id){const f=document.querySelector(`.file[data-id='${id}']`);return f?f.textContent.trim():'document'}
async function init(){
  const b=await fetch(`/project/${pid}?format=json`);
  if(b.status===401){location.href='/login';return}
  if(b.status===403){document.body.innerHTML='<div class=card><h1>No access</h1></div>';return}
  boot=await b.json();pname.textContent=boot.projectName||'Project';
  myName=(boot.user&&(((boot.user.first_name||'')+' '+(boot.user.last_name||'')).trim()||boot.user.email))||'anon';
  await loadTree();
  connect();
  if(boot.rootDocId)openDoc(boot.rootDocId,'doc');
}
function connect(){
  sock=Fleetex.connect(boot.wsUrl,{projectId:pid},{user_id:boot.user&&boot.user.id},{
    onConnect(){setConn('🟢 live')},
    onClose(){setConn('🔴 offline')},
    onError(e){setConn('🔴 '+e)},
    onEvent(event,args){handleEvent(event,args)}
  });
}
function handleEvent(event,args){
  if(event==='otUpdateApplied'){
    const p=args[0]; if(!doc||p.doc!==curId) return;
    if(p.op!==undefined) applyRemote(p); else doc.onAck(p.v);
  } else if(event==='otUpdateError'){ setConn('🔴 sync error') }
  else if(event==='joinProjectResponse'){ myPublicId=args[0].publicId }
  else if(event==='clientTracking.clientUpdated'){
    const p=args[0]; if(p.id&&p.id!==myPublicId){ peers[p.id]={name:p.name||p.user_id,color:Fleetex.colorFor(p.id),doc_id:p.doc_id,row:p.row,column:p.column,t:Date.now()}; renderPeers(); }
  }
  else if(event==='clientTracking.clientDisconnected'){ delete peers[args[0]]; renderPeers(); }
  else if(['reciveNewDoc','reciveNewFolder','reciveNewFile','removeEntity','reciveEntityRename','reciveEntityMove'].indexOf(event)>=0){ loadTree() }
}
function renderPeers(){
  let bar='';
  for(const id in peers){ const p=peers[id]; const ini=(p.name||'?').trim().split(/\\s+/).map(s=>s[0]).join('').slice(0,2).toUpperCase()||'?'; bar+=`<span class=avatar title='${esc(p.name)}' style='background:${p.color}'>${esc(ini)}</span>`; }
  presence.innerHTML=bar;
  renderCursors();
}
function renderCursors(){
  let html='';
  for(const id in peers){
    const p=peers[id]; if(p.doc_id!==curId||p.row==null) continue;
    const pos=Fleetex.rowColToPos(ed.value,p.row,p.column);
    const c=Fleetex.caretCoords(ed,pos);
    const x=c.left-ed.scrollLeft, y=c.top-ed.scrollTop;
    if(y<-20||y>ed.clientHeight+20) continue;
    html+=`<div class=rcursor style='left:${x}px;top:${y}px;height:${c.height}px;background:${p.color}'></div>`;
    html+=`<div class=rlabel style='left:${x}px;top:${y}px;background:${p.color}'>${esc(p.name)}</div>`;
  }
  cursors.innerHTML=html;
}
function requestPresence(){
  if(!sock) return;
  sock.emit('clientTracking.getConnectedUsers',function(err,users){
    (users||[]).forEach(u=>{ if(u.client_id&&u.client_id!==myPublicId){ const cd=u.cursorData||{}; peers[u.client_id]={name:((u.first_name||'')+' '+(u.last_name||'')).trim()||u.user_id,color:Fleetex.colorFor(u.client_id),doc_id:cd.doc_id,row:cd.row,column:cd.column,t:Date.now()}; }});
    renderPeers();
  });
}
function sendCursor(){ if(!sock||!curId) return; const rc=Fleetex.posToRowCol(ed.value,ed.selectionStart); sock.emit('clientTracking.updatePosition',{doc_id:curId,row:rc.row,column:rc.column,name:myName}); }
function sendCursorSoon(){ if(cursorTimer) return; cursorTimer=setTimeout(()=>{cursorTimer=null;sendCursor();},120); }
setInterval(()=>{ const now=Date.now(); let ch=false; for(const id in peers){ if(now-peers[id].t>20000){ delete peers[id]; ch=true; } } if(ch) renderPeers(); },5000);
['keyup','click'].forEach(evt=>ed.addEventListener(evt,sendCursorSoon));
function highlightLatex(src){
  var e=src.replace(/[&<>]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c];});
  e=e.replace(/%[^\\n]*/g,function(m){return '<span class=tok-com>'+m+'</span>';});
  e=e.replace(/\\\\[a-zA-Z@]+\\*?|\\\\[^a-zA-Z]/g,function(m){return '<span class=tok-cmd>'+m+'</span>';});
  e=e.replace(/[{}]/g,function(m){return '<span class=tok-brc>'+m+'</span>';});
  return e+'\\n';
}
function updateView(){
  hl.innerHTML=highlightLatex(ed.value);
  var n=ed.value.split('\\n').length, g=''; for(var i=1;i<=n;i++) g+=i+'\\n'; gutter.textContent=g;
  gutter.scrollTop=ed.scrollTop;
}
ed.addEventListener('scroll',function(){ hl.scrollTop=ed.scrollTop; hl.scrollLeft=ed.scrollLeft; gutter.scrollTop=ed.scrollTop; renderCursors(); });
ed.addEventListener('keydown',function(e){
  if(e.key==='Tab'){ e.preventDefault(); const s=ed.selectionStart,en=ed.selectionEnd; ed.value=ed.value.slice(0,s)+'  '+ed.value.slice(en); ed.selectionStart=ed.selectionEnd=s+2; ed.dispatchEvent(new Event('input')); }
});
async function loadTree(){
  const d=await (await fetch(`/project/${pid}/tree`)).json();
  tree.innerHTML=d.entities.map(e=>`<div class=file data-id='${e.id}' data-type='${e.type}' onclick="openDoc('${e.id}','${e.type}')">${e.type==='doc'?'📄':'📎'} ${esc(e.path.slice(1))}</div>`).join('')||'<div class=muted>Empty</div>';
  document.querySelectorAll('.file').forEach(f=>f.classList.toggle('active',f.dataset.id===curId));
}
function openDoc(id,type){
  if(id===curId) return;
  if(curId&&sock) sock.emit('leaveDoc',curId,function(){});
  document.querySelectorAll('.file').forEach(f=>f.classList.toggle('active',f.dataset.id===id));
  if(type==='file'){ed.value='(binary file)';ed.disabled=true;save.disabled=true;delbtn.disabled=false;curId=id;doc=null;cur.textContent='binary file';return}
  if(!sock){return httpOpen(id)}
  sock.emit('joinDoc',id,-1,{},function(err,lines,version){
    if(err){setConn('🔴 join failed');return httpOpen(id)}
    curId=id;
    const snap=(lines||['']).join('\\n');
    doc=new Fleetex.CollabDoc(snap,version||0,function(u){sock.emit('applyOtUpdate',id,{op:u.op,v:u.v,meta:{}})});
    ed.value=snap;lastValue=snap;ed.disabled=false;save.disabled=false;delbtn.disabled=false;cur.textContent=fileLabel(id)+' · live';
    updateView(); requestPresence(); sendCursor(); renderCursors(); refreshHistoryIfOpen();
  });
}
async function httpOpen(id){ // fallback when socket unavailable
  const r=await fetch(`/project/${pid}/doc/${id}?plain=true`); if(!r.ok){cur.textContent='could not load';return}
  ed.value=await r.text();lastValue=ed.value;doc=null;curId=id;ed.disabled=false;save.disabled=false;delbtn.disabled=false;cur.textContent=fileLabel(id)+' · offline';updateView();refreshHistoryIfOpen();
}
ed.addEventListener('input',function(){
  if(applyingRemote) return;
  if(doc){ const op=Fleetex.makeOp(lastValue,ed.value); lastValue=ed.value; if(op.length) doc.submitLocal(op); }
  else lastValue=ed.value;
  updateView(); sendCursorSoon(); renderCursors();
});
function applyRemote(p){
  applyingRemote=true;
  const s=ed.selectionStart,e=ed.selectionEnd;
  const incoming=doc.onRemote(p.op,p.v);
  ed.value=doc.snapshot;lastValue=doc.snapshot;updateView();
  let ns=s,ne=e; for(const c of incoming){ns=Fleetex.OT.tp(ns,c,false);ne=Fleetex.OT.tp(ne,c,false)}
  ed.setSelectionRange(ns,ne);
  applyingRemote=false;
}
async function save(){
  if(!curId)return;status.textContent='Saving…';
  const r=await fetch(`/project/${pid}/doc/${curId}`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({content:ed.value})});
  status.textContent=r.ok?'Saved ✓':'Save failed';setTimeout(()=>status.textContent='',1500);
  if(r.ok) recordVersion('save');
}
// ---- version history ---------------------------------------------------- #
let histSelected=null;
function recordVersion(source){
  if(!curId||typeof curId!=='string') return;
  fetch(`/project/${pid}/doc/${curId}/history/version`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({content:ed.value,source:source||'save'})}).then(refreshHistoryIfOpen).catch(()=>{});
}
function toggleHistory(){ if(histpanel.classList.toggle('open')) loadHistory(); }
function refreshHistoryIfOpen(){ if(histpanel.classList.contains('open')) loadHistory(); }
async function loadHistory(){
  histdoc.textContent=curId?fileLabel(curId):'';
  histSelected=null;restoreBtn.disabled=true;histsel.textContent='No version selected';
  histdiff.innerHTML='<div class=histempty>Select a version to see what changed.</div>';
  if(!curId){histlist.innerHTML='<div class=histempty>Open a document to see its history.</div>';return}
  const r=await fetch(`/project/${pid}/doc/${curId}/history`);
  if(!r.ok){histlist.innerHTML='<div class=histempty>Could not load history.</div>';return}
  renderHistList(((await r.json()).versions)||[]);
}
function renderHistList(versions){
  if(!versions.length){histlist.innerHTML='<div class=histempty>No saved versions yet. Press Save (⌘/Ctrl+S) to create one.</div>';return}
  histlist.innerHTML=versions.map(v=>`<div class=hitem data-v='${v.version}' onclick='selectVersion(${v.version})'><div class=hv>v${v.version} · ${esc(v.source||'save')}</div><div class=hmeta>${v.ts?new Date(v.ts).toLocaleString():''}</div></div>`).join('');
}
async function selectVersion(v){
  histSelected=v;
  document.querySelectorAll('.hitem').forEach(e=>e.classList.toggle('active',e.dataset.v===String(v)));
  histsel.textContent='Version '+v;restoreBtn.disabled=false;
  histdiff.innerHTML='<div class=histempty>Loading…</div>';
  const r=await fetch(`/project/${pid}/doc/${curId}/history/diff?to=${v}`);
  if(!r.ok){histdiff.innerHTML='<div class=histempty>Could not load diff.</div>';return}
  renderDiff((await r.json()).diff||[]);
}
function renderDiff(segs){
  if(!segs.length){histdiff.innerHTML='<div class=histempty>No changes in this version.</div>';return}
  let h='';
  for(const s of segs){
    if('u' in s) h+=esc(s.u);
    else if('i' in s) h+='<span class=seg-i>'+esc(s.i)+'</span>';
    else if('d' in s) h+='<span class=seg-d>'+esc(s.d)+'</span>';
  }
  histdiff.innerHTML=h||'<div class=histempty>No changes in this version.</div>';
}
async function restoreSelected(){
  if(histSelected==null||!curId) return;
  if(!confirm('Restore version '+histSelected+'? This replaces the current document content.')) return;
  const r=await fetch(`/project/${pid}/history/version/${histSelected}`);
  if(!r.ok){alert('Could not load that version');return}
  const content=(await r.json()).content||'';
  if(doc){ // live: replay as a normal OT edit so every connected client converges
    const op=Fleetex.makeOp(lastValue,content); ed.value=content; lastValue=content; if(op.length) doc.submitLocal(op); updateView();
  } else { ed.value=content;lastValue=content;updateView();await save(); }
  status.textContent='Restored v'+histSelected;setTimeout(()=>status.textContent='',2500);
  recordVersion('restore');
}
async function share(){
  const m=await (await fetch(`/project/${pid}/members`)).json();
  const list=(m.members||[]).map(x=>`  • ${x.email||x.user_id} (${x.privilegeLevel})`).join('\\n')||'  (just you)';
  const email=prompt('Project members:\\n'+list+'\\n\\nInvite a collaborator by email (they get edit access):');
  if(!email) return;
  const r=await fetch(`/project/${pid}/members`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({email:email.trim(),privilegeLevel:'readAndWrite'})});
  if(r.ok){ const d=await r.json(); alert('✓ Added '+d.member.email+' as an editor'); }
  else { const d=await r.json().catch(()=>({})); alert('Could not add: '+((d.message&&d.message.text)||'error')); }
}
async function doUpload(){
  const f=fileinput.files[0]; if(!f) return;
  const fd=new FormData(); fd.append('qqfile',f); fd.append('name',f.name);
  status.textContent='Uploading '+f.name+'…';
  const r=await fetch(`/project/${pid}/upload`,{method:'POST',body:fd}); fileinput.value='';
  status.textContent=r.ok?('✓ uploaded '+f.name):'upload failed'; setTimeout(()=>status.textContent='',2000);
  if(r.ok) loadTree();
}
async function newDoc(){const n=prompt('New document name (e.g. chapter.tex):');if(!n)return;const r=await fetch(`/project/${pid}/doc`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({name:n})});if(r.ok){await loadTree();const d=await r.json();openDoc(d._id,'doc')}else alert('Could not create document')}
async function delDoc(){if(!curId||!confirm('Delete this entity?'))return;const f=document.querySelector(`.file[data-id='${curId}']`);const type=f?f.dataset.type:'doc';await fetch(`/project/${pid}/${type}/${curId}`,{method:'DELETE'});curId=null;doc=null;ed.value='';save.disabled=true;delbtn.disabled=true;cur.textContent='No document open';loadTree()}
async function compile(){
  if(doc) await save().catch(()=>{});  // flush current doc so the compile sees it
  compileBtn.disabled=true;pdfstatus.textContent='Compiling…';
  try{
    const r=await fetch(`/project/${pid}/compile`,{method:'POST'});
    if(!r.ok){pdfstatus.textContent='compile request failed';return}
    const c=(await r.json()).compile||{};
    const pdf=(c.outputFiles||[]).find(f=>f.path==='output.pdf');
    if(c.status==='success'&&pdf){ pdfframe.src=pdf.url+'?t='+Date.now(); pdfstatus.textContent='✓ compiled'; pdfdl.href=pdf.url; pdfdl.style.display=''; }
    else{
      pdfstatus.textContent='✗ '+(c.status||'failed')+(c.error?' — '+c.error:'');
      const log=(c.outputFiles||[]).find(f=>f.path==='output.log');
      if(log) pdfframe.src=log.url+'?t='+Date.now();
    }
  }finally{ compileBtn.disabled=false }
}
document.addEventListener('keydown',e=>{
  if((e.ctrlKey||e.metaKey)&&e.key==='s'){e.preventDefault();save()}
  if((e.ctrlKey||e.metaKey)&&e.key==='Enter'){e.preventDefault();compile()}
});
init();
</script>""")


def _cookie(config, signed_value: str) -> str:
    parts = [f"{config.cookie_name}={signed_value}", "Path=/", "HttpOnly", f"Max-Age={config.cookie_max_age_s}", f"SameSite={config.same_site.capitalize()}"]
    if config.secure_cookie:
        parts.append("Secure")
    return "; ".join(parts)


def register_frontend_routes(app: FastAPI, *, config, store, users: UserManager) -> None:
    @app.get("/")
    async def index():
        return RedirectResponse("/projects")

    @app.get("/login")
    async def login_page():
        return HTMLResponse(LOGIN_PAGE)

    @app.get("/register")
    async def register_page():
        if not config.open_registration:
            return RedirectResponse("/login")
        return HTMLResponse(REGISTER_PAGE)

    @app.get("/projects")
    async def dashboard_page():
        return HTMLResponse(DASHBOARD_PAGE)

    @app.get("/assets/collab.js")
    async def collab_js():
        return Response(COLLAB_JS, media_type="application/javascript")

    @app.post("/register")
    async def register(request: Request):
        if not config.open_registration:
            return JSONResponse({"message": {"type": "error", "text": "registration is disabled"}}, status_code=403)
        body = await request.json()
        email, password = body.get("email"), body.get("password")
        if not email or not isinstance(email, str) or "@" not in email:
            return JSONResponse({"message": {"type": "error", "text": "a valid email is required"}}, status_code=400)
        if not password or len(password) < 6:
            return JSONResponse({"message": {"type": "error", "text": "password must be at least 6 characters"}}, status_code=400)
        if await users.find_by_email(email):
            return JSONResponse({"message": {"type": "error", "text": "an account with that email already exists"}}, status_code=400)
        user = await users.create_user(email, password, first_name=body.get("first_name", ""))
        sid = generate_session_id()
        await store.save(sid, {"passport": {"user": serialize_user(user)}, "justLoggedIn": True})
        resp = JSONResponse({"redir": "/projects"})
        resp.headers.append("set-cookie", _cookie(config, store.sign_cookie(sid)))
        return resp
