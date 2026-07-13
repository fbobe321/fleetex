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
.pane textarea{flex:1;border:0;background:#0e1016;color:#e6e8ee;padding:14px;resize:none;font:13px/1.6 ui-monospace,monospace}
.pdf{display:flex;flex-direction:column;border-left:1px solid #2a2e3a;min-width:0}
.pdf .bar{display:flex;gap:8px;align-items:center;padding:8px;border-bottom:1px solid #2a2e3a}
.pdf iframe{flex:1;border:0;background:#fff}
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
  <span class=muted id=conn>connecting…</span>
  <span class=muted id=status></span>
  <button id=compileBtn onclick=compile()>Compile ▶</button>
  <button class=ghost onclick=newDoc()>New doc</button></div>
<div class=editor>
  <div class=tree id=tree></div>
  <div class=pane>
    <div class=bar><span class=muted id=cur>No document open</span><span class=grow></span>
      <button id=save onclick=save() disabled>Save</button>
      <button class=ghost id=delbtn onclick=delDoc() disabled>Delete</button></div>
    <textarea id=ed placeholder='Open a document from the file tree…'></textarea>
  </div>
  <div class=pdf>
    <div class=bar><span class=muted id=pdfstatus>Press Compile ▶ to build the PDF</span></div>
    <iframe id=pdfframe></iframe>
  </div>
</div>
<script src="/assets/collab.js"></script>
<script>
const pid=location.pathname.split('/')[2];
let boot=null, sock=null, doc=null, curId=null, lastValue='', applyingRemote=false;
function esc(s){return (s||'').replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]))}
function setConn(t){conn.textContent=t}
function fileLabel(id){const f=document.querySelector(`.file[data-id='${id}']`);return f?f.textContent.trim():'document'}
async function init(){
  const b=await fetch(`/project/${pid}?format=json`);
  if(b.status===401){location.href='/login';return}
  if(b.status===403){document.body.innerHTML='<div class=card><h1>No access</h1></div>';return}
  boot=await b.json();pname.textContent=boot.projectName||'Project';
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
  else if(['reciveNewDoc','reciveNewFolder','reciveNewFile','removeEntity','reciveEntityRename','reciveEntityMove'].indexOf(event)>=0){ loadTree() }
}
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
  });
}
async function httpOpen(id){ // fallback when socket unavailable
  const r=await fetch(`/project/${pid}/doc/${id}?plain=true`); if(!r.ok){cur.textContent='could not load';return}
  ed.value=await r.text();lastValue=ed.value;doc=null;curId=id;ed.disabled=false;save.disabled=false;delbtn.disabled=false;cur.textContent=fileLabel(id)+' · offline';
}
ed.addEventListener('input',function(){
  if(applyingRemote) return;
  if(doc){ const op=Fleetex.makeOp(lastValue,ed.value); lastValue=ed.value; if(op.length) doc.submitLocal(op); }
  else lastValue=ed.value;
});
function applyRemote(p){
  applyingRemote=true;
  const s=ed.selectionStart,e=ed.selectionEnd;
  const incoming=doc.onRemote(p.op,p.v);
  ed.value=doc.snapshot;lastValue=doc.snapshot;
  let ns=s,ne=e; for(const c of incoming){ns=Fleetex.OT.tp(ns,c,false);ne=Fleetex.OT.tp(ne,c,false)}
  ed.setSelectionRange(ns,ne);
  applyingRemote=false;
}
async function save(){
  if(!curId)return;status.textContent='Saving…';
  const r=await fetch(`/project/${pid}/doc/${curId}`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({content:ed.value})});
  status.textContent=r.ok?'Saved ✓':'Save failed';setTimeout(()=>status.textContent='',1500);
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
    if(c.status==='success'&&pdf){ pdfframe.src=pdf.url+'?t='+Date.now(); pdfstatus.textContent='✓ compiled' }
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
