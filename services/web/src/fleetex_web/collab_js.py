"""Browser live-collab client (served at /assets/collab.js).

Contains:
  * ``OT`` — the ShareJS text OT type in JS (a port of the Python ot_text, which
    is TP1-fuzz-verified; the browser and server share the exact algorithm).
  * a minimal Socket.IO v4 client over raw WebSocket (no external dependency).
  * ``CollabDoc`` — a ShareJS-style client with inflight/buffer op tracking.
Exposed as ``window.Fleetex``.
"""

COLLAB_JS = r"""
(function(){
  // ---------- OT text type (port of server ot_text) ----------
  function isIns(c){return typeof c.i==='string';}
  function isDel(c){return typeof c.d==='string';}
  function inject(s,p,x){return s.slice(0,p)+x+s.slice(p);}
  function apply(snap, op){
    for(var k=0;k<op.length;k++){var c=op[k];
      if(isIns(c)) snap=inject(snap,c.p,c.i);
      else if(isDel(c)){
        var del=snap.slice(c.p,c.p+c.d.length);
        if(del!==c.d) throw new Error("delete mismatch: '"+c.d+"' vs '"+del+"'");
        snap=snap.slice(0,c.p)+snap.slice(c.p+c.d.length);
      }
    }
    return snap;
  }
  function append(op,c){
    if(c.i===''||c.d==='') return;
    if(op.length===0){op.push(c);return;}
    var last=op[op.length-1];
    if(isIns(last)&&isIns(c)&&last.p<=c.p&&c.p<=last.p+last.i.length)
      op[op.length-1]={i:inject(last.i,c.p-last.p,c.i),p:last.p};
    else if(isDel(last)&&isDel(c)&&c.p<=last.p&&last.p<=c.p+c.d.length)
      op[op.length-1]={d:inject(c.d,last.p-c.p,last.d),p:c.p};
    else op.push(c);
  }
  function compose(a,b){var n=a.slice();for(var k=0;k<b.length;k++)append(n,b[k]);return n;}
  function tp(pos,c,after){
    if(isIns(c)){ if(c.p<pos||(c.p===pos&&after)) return pos+c.i.length; return pos; }
    if(isDel(c)){ if(pos<=c.p) return pos; if(pos<=c.p+c.d.length) return c.p; return pos-c.d.length; }
    return pos;
  }
  function tc(dest,c,o,side){
    if(isIns(c)){ append(dest,{i:c.i,p:tp(c.p,o,side==='right')}); }
    else if(isDel(c)){
      if(isIns(o)){
        var s=c.d;
        if(c.p<o.p){append(dest,{d:s.slice(0,o.p-c.p),p:c.p});s=s.slice(o.p-c.p);}
        if(s!=='')append(dest,{d:s,p:c.p+o.i.length});
      } else if(isDel(o)){
        if(c.p>=o.p+o.d.length) append(dest,{d:c.d,p:c.p-o.d.length});
        else if(c.p+c.d.length<=o.p) append(dest,c);
        else{
          var nc={d:'',p:c.p};
          if(c.p<o.p) nc.d=c.d.slice(0,o.p-c.p);
          if(c.p+c.d.length>o.p+o.d.length) nc.d+=c.d.slice(o.p+o.d.length-c.p);
          var is=Math.max(c.p,o.p), ie=Math.min(c.p+c.d.length,o.p+o.d.length);
          if(c.d.slice(is-c.p,ie-c.p)!==o.d.slice(is-o.p,ie-o.p)) throw new Error("delete conflict");
          if(nc.d!==''){ nc.p=tp(nc.p,o,false); append(dest,nc); }
        }
      }
    }
    return dest;
  }
  function tcx(l,r,dl,dr){tc(dl,l,r,'left');tc(dr,r,l,'right');}
  function transformX(L,R){
    var newR=[];
    for(var i=0;i<R.length;i++){
      var rc=R[i], newL=[], k=0;
      while(k<L.length){
        var lc=L[k]; k++; var nx=[];
        tcx(lc,rc,newL,nx);
        if(nx.length===1){ rc=nx[0]; }
        else if(nx.length===0){ for(var a=k;a<L.length;a++)append(newL,L[a]); rc=null; break; }
        else { var res=transformX(L.slice(k),nx); for(var b=0;b<res[0].length;b++)append(newL,res[0][b]); for(var d=0;d<res[1].length;d++)append(newR,res[1][d]); rc=null; break; }
      }
      if(rc!==null) append(newR,rc);
      L=newL;
    }
    return [L,newR];
  }
  function transform(op,other,side){
    if(other.length===0) return op;
    if(op.length===1&&other.length===1) return tc([],op[0],other[0],side);
    if(side==='left') return transformX(op,other)[0];
    return transformX(other,op)[1];
  }
  var OT={apply:apply,compose:compose,transform:transform,tp:tp};

  // ---------- prefix/suffix diff -> op ----------
  function makeOp(oldS,newS){
    var start=0, oe=oldS.length, ne=newS.length;
    while(start<oe&&start<ne&&oldS[start]===newS[start]) start++;
    while(oe>start&&ne>start&&oldS[oe-1]===newS[ne-1]){oe--;ne--;}
    var op=[]; var removed=oldS.slice(start,oe), inserted=newS.slice(start,ne);
    if(removed) op.push({d:removed,p:start});
    if(inserted) op.push({i:inserted,p:start});
    return op;
  }

  // ---------- minimal Socket.IO v4 client over WebSocket ----------
  function connect(wsUrl, query, auth, handlers){
    var base = (wsUrl && wsUrl.indexOf('http')===0) ? wsUrl : location.origin;
    var wsBase = base.replace(/^http/,'ws');
    var qs = Object.keys(query).map(function(k){return k+'='+encodeURIComponent(query[k]);}).join('&');
    var ws = new WebSocket(wsBase+'/socket.io/?EIO=4&transport=websocket&'+qs);
    var ackId=0, acks={};
    function emit(){
      var args=Array.prototype.slice.call(arguments);
      var cb = (typeof args[args.length-1]==='function') ? args.pop() : null;
      var id=''; if(cb){ id=String(ackId++); acks[id]=cb; }
      ws.send('42'+id+JSON.stringify(args));
    }
    ws.onopen=function(){};
    ws.onclose=function(){ handlers.onClose&&handlers.onClose(); };
    ws.onmessage=function(e){
      var data=e.data;
      if(data[0]==='0'){ ws.send('40'+(auth?JSON.stringify(auth):'')); return; }
      if(data[0]==='2'){ ws.send('3'); return; }
      if(data[0]!=='4') return;
      var t=data[1], rest=data.slice(2);
      if(t==='0'){ handlers.onConnect&&handlers.onConnect(); }
      else if(t==='2'){ var m=rest.match(/^(\d*)(\[[\s\S]*\])$/); if(!m) return; var arr=JSON.parse(m[2]); handlers.onEvent&&handlers.onEvent(arr[0], arr.slice(1)); }
      else if(t==='3'){ var m2=rest.match(/^(\d+)(\[[\s\S]*\])$/); if(!m2) return; var arr2=JSON.parse(m2[2]); var cb=acks[m2[1]]; if(cb){ delete acks[m2[1]]; cb.apply(null,arr2); } }
      else if(t==='4'){ handlers.onError&&handlers.onError(rest); }
    };
    return { emit:emit, close:function(){ws.close();} };
  }

  // ---------- ShareJS-style client doc ----------
  function CollabDoc(snapshot, version, send){
    this.snapshot=snapshot; this.version=version; this.inflight=null; this.buffer=null; this.send=send;
  }
  CollabDoc.prototype.submitLocal=function(op){
    this.snapshot=OT.apply(this.snapshot, op);
    this.buffer=this.buffer?OT.compose(this.buffer,op):op;
    this.flush();
  };
  CollabDoc.prototype.flush=function(){
    if(!this.inflight && this.buffer){
      this.inflight=this.buffer; this.buffer=null;
      this.send({op:this.inflight, v:this.version});
    }
  };
  CollabDoc.prototype.onAck=function(v){ this.version=v+1; this.inflight=null; this.flush(); };
  CollabDoc.prototype.onRemote=function(op, v){
    var incoming=op;
    if(this.inflight){ var i2=OT.transform(this.inflight,incoming,'left'); incoming=OT.transform(incoming,this.inflight,'right'); this.inflight=i2; }
    if(this.buffer){ var b2=OT.transform(this.buffer,incoming,'left'); incoming=OT.transform(incoming,this.buffer,'right'); this.buffer=b2; }
    this.version=v+1;
    this.snapshot=OT.apply(this.snapshot, incoming);
    return incoming;
  };

  window.Fleetex={ OT:OT, connect:connect, CollabDoc:CollabDoc, makeOp:makeOp };
})();
"""
