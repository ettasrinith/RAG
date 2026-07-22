/* ════════════════════════════════════════════════════════════
   Knowledge Hub — app.js
   Targets the live FastAPI monolith (api/server.py).
   ════════════════════════════════════════════════════════════ */
'use strict';

/* ── State ─────────────────────────────────────────────────── */
const S = {
  source: 'folder',          // active index source: folder | github | zip
  zipPath: null,             // extracted path after a ZIP upload
  selectedPapers: new Map(), // paper_id -> paper
  discovered: [],            // last discover results
  streaming: false,          // chat busy flag
  theme: localStorage.getItem('kh-theme') || 'light',
};

/* ── DOM helpers ───────────────────────────────────────────── */
const $  = id => document.getElementById(id);
const qs = s  => document.querySelector(s);
const qsa = s => document.querySelectorAll(s);

function esc(s){ const d=document.createElement('div'); d.textContent = s==null?'':String(s); return d.innerHTML; }
function escAttr(s){ return String(s==null?'':s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

/* escape text then wrap query-term matches in <mark> */
function hl(text, q){
  const s = String(text||'');
  const terms = String(q||'').toLowerCase().split(/\s+/).filter(t=>t.length>1);
  if(!terms.length) return esc(s);
  const safe = terms.map(t=>t.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'));
  const re = new RegExp('('+safe.join('|')+')','ig');
  let out='', last=0, m;
  while((m=re.exec(s))){
    out += esc(s.slice(last,m.index)) + '<mark>' + esc(m[0]) + '</mark>';
    last = m.index + m[0].length;
    if(m[0].length===0) re.lastIndex++;
  }
  return out + esc(s.slice(last));
}

function toast(title, text='', type=''){
  const el=document.createElement('div');
  el.className='toast '+type;
  el.innerHTML='<strong>'+esc(title)+'</strong>'+(text?'<p>'+esc(text)+'</p>':'');
  $('toasts').appendChild(el);
  setTimeout(()=>{ el.style.opacity='0'; el.style.transition='opacity .3s'; setTimeout(()=>el.remove(),320); }, 3200);
}

function countUp(el, target, suffix=''){
  const dur=550, start=performance.now();
  (function tick(t){
    const p=Math.min(1,(t-start)/dur), eased=1-Math.pow(1-p,3);
    el.textContent=Math.round(target*eased)+suffix;
    if(p<1) requestAnimationFrame(tick);
  })(start);
}

/* ── API ───────────────────────────────────────────────────── */
async function api(path, opts={}){
  const token=(localStorage.getItem('kh_token')||'').trim();
  const headers={'Content-Type':'application/json', ...(token?{'X-API-Key':token}:{}), ...(opts.headers||{})};
  if(opts.body instanceof FormData){ delete headers['Content-Type']; }
  const res=await fetch(path,{...opts,headers});
  const ct=res.headers.get('content-type')||'';
  if(!res.ok){
    let msg='Request failed';
    try{ const j=await res.json(); msg=j.detail||j.error||msg; }catch(_){ try{ msg=await res.text()||msg; }catch(_e){} }
    throw new Error(msg);
  }
  if(ct.includes('text/event-stream')) return res;
  if(ct.includes('application/json')) return res.json();
  return res.text();
}

/* stream SSE from a POST endpoint, calling onEvent per `data:` frame */
async function apiStream(path, body, onEvent){
  const token=(localStorage.getItem('kh_token')||'').trim();
  const res=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json',...(token?{'X-API-Key':token}:{})},body:JSON.stringify(body)});
  const ct=res.headers.get('content-type')||'';
  if(!ct.includes('text/event-stream')){
    let j={}; try{ j=await res.json(); }catch(_){}
    throw new Error(j.error||j.detail||'Could not start stream');
  }
  const rd=res.body.getReader(), dec=new TextDecoder(); let buf='';
  while(true){
    const {done,value}=await rd.read(); if(done) break;
    buf+=dec.decode(value,{stream:true});
    const lines=buf.split('\n'); buf=lines.pop()||'';
    for(const l of lines){
      if(!l.startsWith('data: ')) continue;
      try{ onEvent(JSON.parse(l.slice(6))); }catch(_){}
    }
  }
}

/* ── Theme ─────────────────────────────────────────────────── */
function applyTheme(){
  document.documentElement.classList.toggle('dark', S.theme==='dark');
  $('theme-btn').textContent = S.theme==='dark' ? '☀️' : '🌙';
}
applyTheme();
$('theme-btn').addEventListener('click',()=>{
  S.theme = S.theme==='dark' ? 'light' : 'dark';
  localStorage.setItem('kh-theme', S.theme);
  applyTheme();
});

/* ── Topbar scroll + keyboard ──────────────────────────────── */
window.addEventListener('scroll',()=>{ $('nav').classList.toggle('scrolled', window.scrollY>10); },{passive:true});
document.addEventListener('keydown',e=>{
  if(e.key==='/' && !['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName)){
    e.preventDefault(); navigate('search'); $('search-query').focus();
  }
  if(e.key==='Escape' && document.activeElement) document.activeElement.blur();
});

/* ── Navigation ────────────────────────────────────────────── */
function navigate(page){
  qsa('.nav-item').forEach(b=>b.classList.toggle('active', b.dataset.section===page));
  qsa('.section').forEach(s=>s.classList.remove('active'));
  const t=$('section-'+page); if(t) t.classList.add('active');
  if(page==='search'){ loadRepos(); $('search-query').focus(); }
  if(page==='chat') $('chat-input').focus();
  if(page==='index') pollStatus();
  if(page==='research'){ loadCollectionPicker(); loadLibrary(); }
}
qsa('.nav-item').forEach(b=>b.addEventListener('click',()=>navigate(b.dataset.section)));

/* ── Status polling ────────────────────────────────────────── */
async function pollStatus(){
  try{
    const s=await api('/sync/status');
    const dot=$('status-dot'), txt=$('status-text');
    if(s.indexing){ dot.classList.add('indexing'); txt.textContent='Indexing…'; $('start-btn').disabled=true; $('stop-btn').disabled=false; }
    else{ dot.classList.remove('indexing'); txt.textContent='Ready'; $('start-btn').disabled=false; $('stop-btn').disabled=true; }
  }catch(_){}
}
setInterval(pollStatus, 3000);

/* ── Search ────────────────────────────────────────────────── */
const SOURCE_LABELS=[
  ['github_files','Files'],['github_commits','Commits'],['website','Website'],
  ['arxiv','arXiv'],['youtube','YouTube'],['documents','Documents'],
];
(function initSourceSelect(){
  const sel=$('search-source');
  SOURCE_LABELS.forEach(([v,l])=>{ const o=document.createElement('option'); o.value=v; o.textContent=l; sel.appendChild(o); });
})();

async function loadRepos(){
  try{
    const {repos, counts}=await api('/repos');
    const sel=$('search-repo');
    sel.innerHTML='<option value="">All repos</option>';
    (repos||[]).forEach(r=>{
      const o=document.createElement('option'); o.value=r;
      o.textContent = r + (counts&&counts[r]!=null ? ' ('+counts[r]+')' : '');
      sel.appendChild(o);
    });
  }catch(_){}
}

function showSkeleton(host){
  host.innerHTML=Array(4).fill('<div class="skeleton-card"><div class="skeleton-line"></div><div class="skeleton-line"></div><div class="skeleton-line"></div><div class="skeleton-line"></div></div>').join('');
}

function activeFilterChips(){
  const src=$('search-source').value, repo=$('search-repo').value;
  const strip=$('filter-strip');
  let h='';
  if(src) h+='<span class="filter-chip">Source: '+esc((SOURCE_LABELS.find(x=>x[0]===src)||[])[1]||src)+'<span class="rm" data-clear="source">×</span></span>';
  if(repo) h+='<span class="filter-chip">Repo: '+esc(repo)+'<span class="rm" data-clear="repo">×</span></span>';
  strip.innerHTML=h;
}
$('filter-strip').addEventListener('click',e=>{
  const rm=e.target.closest('.rm'); if(!rm) return;
  if(rm.dataset.clear==='source') $('search-source').value='';
  if(rm.dataset.clear==='repo') $('search-repo').value='';
  doSearch();
});

async function doSearch(){
  const q=$('search-query').value.trim();
  const host=$('search-results');
  activeFilterChips();
  if(!q){
    host.innerHTML='<div class="empty-state"><span class="eicon">🔍</span><strong>Start with a query</strong><p>Your indexed knowledge is one search away. Press <b>/</b> to focus.</p></div>';
    $('facets').innerHTML='';
    return;
  }
  showSkeleton(host);
  try{
    const d=await api('/search',{method:'POST',body:JSON.stringify({
      q, k:12,
      hybrid:$('search-hybrid').checked,
      source:$('search-source').value||null,
      repo:$('search-repo').value||null,
    })});
    renderSearch(q, d.results||[]);
  }catch(e){
    host.innerHTML='<div class="empty-state"><span class="eicon">⚠️</span><strong>Search failed</strong><p>'+esc(e.message)+'</p></div>';
  }
}

function renderSearch(q, hits){
  const host=$('search-results');
  if(!hits.length){
    host.innerHTML='<div class="empty-state"><span class="eicon">🔎</span><strong>No results</strong><p>Try a different query, or clear the source / repo filters.</p></div>';
    return;
  }
  const meta=document.createElement('div');
  meta.className='results-meta';
  meta.innerHTML='≈ <span class="n" id="result-count">0</span>&nbsp;results for "'+esc(q)+'"';
  const cards=hits.map((h,i)=>{
    const url=h.url||(h.title?'/file?path='+encodeURIComponent(h.title):'');
    const src=(h.source||'').replace('github_files','file').replace('github_commits','commit');
    const score=h.score!=null && isFinite(h.score) ? '<span class="score">'+Number(h.score).toFixed(3)+'</span>' : '';
    return '<article class="result-card" style="animation-delay:'+(i*55)+'ms"'+(url?' data-url="'+escAttr(url)+'"':'')+'>'+
      '<div class="top"><div><div class="title">'+(url?'<a href="'+escAttr(url)+'" target="_blank" rel="noopener">'+esc(h.title||'Untitled')+'</a>':esc(h.title||'Untitled'))+'</div>'+
      '<div class="meta-row">'+(src?'<span class="badge src">'+esc(src)+'</span>':'')+(h.repo?'<span class="badge">'+esc(h.repo)+'</span>':'')+(h.author?'<span class="badge author">'+esc(h.author)+'</span>':'')+'</div></div>'+score+'</div>'+
      '<div class="snippet">'+hl(h.snippet,q)+'</div>'+
      (h.summary?'<div class="tldr"><strong>Summary: </strong>'+esc(h.summary)+'</div>':'')+
      '</article>';
  }).join('');
  host.innerHTML=''; host.appendChild(meta); host.insertAdjacentHTML('beforeend', cards);
  countUp($('result-count'), hits.length);
}

/* clicking a card (not its link) opens it */
$('search-results').addEventListener('click',e=>{
  if(e.target.closest('a')) return;
  const card=e.target.closest('.result-card'); if(card&&card.dataset.url) window.open(card.dataset.url,'_blank');
});

let searchTimer=null;
$('search-query').addEventListener('input',()=>{ clearTimeout(searchTimer); searchTimer=setTimeout(doSearch,280); });
$('search-form').addEventListener('submit',e=>{ e.preventDefault(); doSearch(); });
$('search-source').addEventListener('change',doSearch);
$('search-repo').addEventListener('change',doSearch);
$('search-hybrid').addEventListener('change',doSearch);

/* ── Chat ──────────────────────────────────────────────────── */
function addMsg(role, html){
  const div=document.createElement('div');
  div.className='msg '+role;
  div.innerHTML=html;
  $('chat-messages').appendChild(div);
  scrollChat();
  return div;
}
function scrollChat(){ const el=$('chat-messages'); el.scrollTop=el.scrollHeight; }

async function sendChat(){
  const inp=$('chat-input'), q=inp.value.trim();
  if(!q||S.streaming) return;
  inp.value=''; S.streaming=true; $('chat-btn').disabled=true;
  const emp=$('chat-messages').querySelector('.empty-state'); if(emp) emp.remove();
  addMsg('user', esc(q));
  const a=addMsg('assist','<span class="typing"><span></span><span></span><span></span></span>');
  let content='', sources=[], started=false;
  try{
    await apiStream('/chat',{q,k:8,scope:$('chat-scope').value},ev=>{
      if(ev.type==='sources') sources=ev.sources||[];
      else if(ev.type==='token'){
        if(!started){ a.innerHTML=''; started=true; }
        content+=ev.text;
        a.innerHTML='<div>'+esc(content)+'</div>';
        scrollChat();
      }
      else if(ev.type==='done'){
        if(sources.length){
          a.insertAdjacentHTML('beforeend','<div class="sources"><strong>Sources</strong>'+
            sources.map((s,i)=>'<a href="'+escAttr(s.url||('/file?path='+encodeURIComponent(s.title||'')))+'" target="_blank" rel="noopener">['+(i+1)+'] '+esc(s.title||s.repo||'Source')+'</a>').join('')+'</div>');
        }
        S.streaming=false;
      }
      else if(ev.type==='error'){ a.innerHTML='<div>Error: '+esc(ev.error||'unknown')+'</div>'; S.streaming=false; }
    });
  }catch(e){ a.innerHTML='<div>Error: '+esc(e.message)+'</div>'; }
  finally{ S.streaming=false; $('chat-btn').disabled=false; inp.focus(); scrollChat(); }
}
$('chat-btn').addEventListener('click',sendChat);
$('chat-input').addEventListener('keydown',e=>{ if(e.key==='Enter'&&!e.shiftKey){ e.preventDefault(); sendChat(); } });

/* ── Index: source cards + panels ──────────────────────────── */
qsa('.source-card').forEach(c=>{
  const activate=()=>{
    qsa('.source-card').forEach(x=>x.classList.remove('selected'));
    c.classList.add('selected');
    S.source=c.dataset.source;
    qsa('.cfg-panel').forEach(p=>p.classList.remove('open'));
    const p=$('panel-'+S.source); if(p) p.classList.add('open');
  };
  c.addEventListener('click',activate);
  c.addEventListener('keydown',e=>{ if(e.key==='Enter'||e.key===' '){ e.preventDefault(); activate(); } });
});
/* open folder panel by default */
var _fc=qs('.source-card[data-source="folder"]'); if(_fc) _fc.click();

/* folder browser */
$('folder-browse').addEventListener('click',async()=>{
  const list=$('folder-list');
  if(list.classList.contains('open')){ list.classList.remove('open'); return; }
  list.classList.add('open');
  list.innerHTML='<div class="folder-item"><strong>Scanning…</strong></div>';
  try{
    const {folders}=await api('/folders');
    if(!folders||!folders.length){ list.innerHTML='<div class="folder-item"><strong>No git folders found</strong></div>'; return; }
    list.innerHTML=folders.map(f=>'<div class="folder-item" data-path="'+escAttr(f.path)+'"><strong>'+esc(f.name)+'</strong><span>'+esc(f.path)+'</span></div>').join('');
  }catch(e){ list.innerHTML='<div class="folder-item"><strong>'+esc(e.message)+'</strong></div>'; }
});
$('folder-list').addEventListener('click',e=>{
  const item=e.target.closest('.folder-item'); if(!item||!item.dataset.path) return;
  $('folder-path').value=item.dataset.path;
  $('folder-list').classList.remove('open');
});

/* zip upload */
const uz=$('upload-zone'), zf=$('zip-file');
uz.addEventListener('click',()=>zf.click());
uz.addEventListener('dragover',e=>{ e.preventDefault(); uz.classList.add('dragover'); });
uz.addEventListener('dragleave',()=>uz.classList.remove('dragover'));
uz.addEventListener('drop',e=>{ e.preventDefault(); uz.classList.remove('dragover'); if(e.dataTransfer.files.length) uploadZip(e.dataTransfer.files[0]); });
zf.addEventListener('change',()=>{ if(zf.files.length) uploadZip(zf.files[0]); });

async function uploadZip(file){
  if(!/\.zip$/i.test(file.name)){ toast('Not a ZIP','Please choose a .zip file.','err'); return; }
  $('file-list').innerHTML='<div class="file-item"><span class="name">⏳ Uploading '+esc(file.name)+'…</span></div>';
  try{
    const fd=new FormData();
    fd.append('file',file);
    fd.append('label',file.name.replace(/\.zip$/i,''));
    const token=(localStorage.getItem('kh_token')||'').trim();
    const res=await fetch('/uploads/zip',{method:'POST',headers:token?{'X-API-Key':token}:{},body:fd});
    const j=await res.json();
    if(!res.ok) throw new Error(j.detail||'Upload failed');
    S.zipPath=j.path;
    $('file-list').innerHTML='<div class="file-item"><span class="name">📦 '+esc(file.name)+'</span><span class="size">'+j.files+' files extracted</span><span class="rm" id="zip-clear">×</span></div>';
    toast('Uploaded','Extracted '+j.files+' files — ready to index.','info');
  }catch(e){
    S.zipPath=null;
    $('file-list').innerHTML='';
    toast('Upload failed',e.message,'err');
  }
}
$('file-list').addEventListener('click',e=>{
  if(e.target.id==='zip-clear'){ S.zipPath=null; $('file-list').innerHTML=''; zf.value=''; }
});

/* config save + indexing */
async function saveGithubConfig(){
  await api('/config',{method:'POST',body:JSON.stringify({
    github_mode:'github',
    github_repo:$('github-repo').value.trim()||null,
    github_pat:$('github-pat').value.trim()||null,
    github_branch:$('github-branch').value.trim()||null,
    github_files_enabled:true,
  })});
}

function setProgress(pct,label){
  $('progress-fill').style.width=Math.min(100,Math.max(0,pct))+'%';
  $('progress-percent').textContent=Math.round(pct)+'%';
  if(label) $('progress-label').textContent=label;
}
function addLog(text,type=''){
  const log=$('progress-log');
  const el=document.createElement('div');
  el.className='log-entry '+type;
  el.textContent=text;
  log.appendChild(el);
  log.scrollTop=log.scrollHeight;
}

async function startIndexing(){
  let repoPath='';
  if(S.source==='folder'){
    repoPath=$('folder-path').value.trim();
    if(!repoPath){ toast('Path required','Enter or browse to a folder first.','err'); return; }
  }else if(S.source==='github'){
    if(!$('github-repo').value.trim()){ toast('Repo required','Enter owner/repo first.','err'); return; }
    try{ await saveGithubConfig(); }catch(e){ toast('Config save failed',e.message,'err'); return; }
  }else if(S.source==='zip'){
    if(!S.zipPath){ toast('Upload first','Drop a ZIP to extract it, then index.','err'); return; }
    repoPath=S.zipPath;
  }

  $('progress-card').classList.remove('hide');
  $('progress-log').innerHTML='';
  setProgress(4,'Starting…');
  addLog('Indexing started');
  $('start-btn').disabled=true; $('stop-btn').disabled=false;

  try{
    await apiStream('/sync/start',{repo_path:repoPath,force_full:$('force-full').checked},ev=>{
      if(ev.type==='doc_indexed'){
        setProgress(Math.min(90,20+(ev.total_docs||0)*2),(ev.total_docs||0)+' docs · '+(ev.total_chunks||0)+' chunks');
      }
      else if(ev.type==='connector_done') addLog('Done: '+ev.key+' ('+(ev.docs||0)+' docs)','success');
      else if(ev.type==='error'){ addLog('Error: '+ev.error,'error'); toast('Indexing failed',ev.error,'err'); }
      else if(ev.type==='done'||ev.type==='cancelled'){
        setProgress(100, ev.cancelled?'Cancelled':'Completed');
        addLog(ev.cancelled?'Cancelled':'Completed','success');
        toast(ev.cancelled?'Indexing cancelled':'Indexing complete','','info');
        pollStatus();
      }
    });
  }catch(e){
    addLog('Failed: '+e.message,'error');
    toast('Indexing failed',e.message,'err');
  }finally{
    pollStatus();
  }
}
$('start-btn').addEventListener('click',startIndexing);
$('stop-btn').addEventListener('click',async()=>{
  try{ await api('/sync/stop',{method:'POST'}); addLog('Stop requested…'); }
  catch(e){ toast('Stop failed',e.message,'err'); }
});

/* ── Research: discover ────────────────────────────────────── */
function authorsStr(p){
  if(Array.isArray(p.authors)) return p.authors.slice(0,3).join(', ')+(p.authors.length>3?' et al.':'');
  return p.authors||p.author||'';
}

$('discover-form').addEventListener('submit',e=>{ e.preventDefault(); doDiscover(); });

async function doDiscover(){
  const q=$('discover-query').value.trim();
  if(!q) return;
  const sources=[];
  if($('src-arxiv').checked) sources.push('arxiv');
  if($('src-s2').checked) sources.push('semantic_scholar');
  if($('src-oa').checked) sources.push('openalex');
  if(!sources.length){ toast('No sources','Select at least one source.','err'); return; }

  const host=$('discover-results'), status=$('discover-status');
  $('discover-btn').disabled=true;
  status.style.display='flex'; status.innerHTML='<span class="spin" style="width:14px;height:14px"></span> Searching '+sources.join(', ')+'…';
  host.innerHTML=''; $('select-bar').classList.add('hide');
  S.selectedPapers.clear(); updateSelectedCount();

  try{
    const d=await api('/research/discover',{method:'POST',body:JSON.stringify({q,sources,limit_per_source:parseInt($('discover-limit').value,10)||10})});
    S.discovered=d.papers||[];
    status.innerHTML='Found <span class="n">'+(d.total_found||S.discovered.length)+'</span> papers'+(d.already_indexed?' ('+d.already_indexed+' already indexed)':'');
    if(!S.discovered.length){
      host.innerHTML='<div class="empty-state"><span class="eicon">🔬</span><strong>No papers found</strong><p>Try a different query or enable more sources.</p></div>';
      return;
    }
    renderPapers(sortPapers(S.discovered), host, false, q);
    $('select-bar').classList.remove('hide');
    loadCollectionPicker();
  }catch(e){
    status.style.display='none';
    host.innerHTML='<div class="empty-state"><span class="eicon">⚠️</span><strong>Discover failed</strong><p>'+esc(e.message)+'</p></div>';
  }finally{
    $('discover-btn').disabled=false;
  }
}

function sortPapers(list){
  const mode=$('discover-sort').value;
  const a=[...list];
  if(mode==='year_desc') a.sort((x,y)=>(y.year||0)-(x.year||0));
  else if(mode==='year_asc') a.sort((x,y)=>(x.year||9999)-(y.year||9999));
  else if(mode==='citations_desc') a.sort((x,y)=>(y.citation_count||0)-(x.citation_count||0));
  return a;
}
$('discover-sort').addEventListener('change',()=>{
  if(S.discovered.length) renderPapers(sortPapers(S.discovered), $('discover-results'), false, $('discover-query').value.trim());
});

function renderPapers(papers, host, isLibrary, q){
  host.innerHTML=papers.map((p,i)=>{
    const id=p.paper_id||p.id||'';
    const link=p.abs_url||p.pdf_url||p.url||'';
    const au=authorsStr(p);
    const sel=!isLibrary && !p.already_indexed
      ? '<label class="paper-select"><input type="checkbox" data-id="'+escAttr(id)+'" '+(S.selectedPapers.has(id)?'checked':'')+' /><span class="box">✓</span></label>'
      : '';
    const del=isLibrary ? '<button class="btn btn-danger btn-sm" data-del="'+escAttr(id)+'">Remove</button>' : '';
    const indexBtn=(!isLibrary && !p.already_indexed) ? '<button class="btn btn-pri btn-sm" data-indexone="'+escAttr(id)+'" data-title="'+escAttr(p.title||'')+'">Index this paper</button>' : '';
    const pdfBtn=p.pdf_url ? '<a class="btn btn-sec btn-sm" href="'+escAttr(p.pdf_url)+'" target="_blank" rel="noopener">PDF</a>' : '';
    const idxBadge=p.already_indexed ? '<span class="badge indexed">Indexed</span>' : '';
    return '<article class="paper-card'+(S.selectedPapers.has(id)?' selected':'')+'" style="animation-delay:'+(i*50)+'ms">'+sel+
      '<div class="paper-title">'+(link?'<a href="'+escAttr(link)+'" target="_blank" rel="noopener">'+esc(p.title||'Untitled')+'</a>':esc(p.title||'Untitled'))+'</div>'+
      (au?'<div class="paper-authors">'+esc(au)+'</div>':'')+
      '<div class="paper-meta">'+
        (p.source?'<span class="badge src">'+esc(p.source)+'</span>':'')+
        (p.year?'<span class="badge">'+esc(String(p.year))+'</span>':'')+
        (p.citation_count!=null?'<span class="badge">'+esc(String(p.citation_count))+' cites</span>':'')+
        (p.venue?'<span class="badge">'+esc(String(p.venue).slice(0,40))+'</span>':'')+idxBadge+
      '</div>'+
      '<div class="paper-abstract">'+hl(p.abstract||p.snippet||'', q||'')+'</div>'+
      '<div class="paper-actions">'+indexBtn+pdfBtn+del+'</div>'+
      '</article>';
  }).join('');
}

/* selection + delegated actions on discover results */
$('discover-results').addEventListener('change',e=>{
  const cb=e.target.closest('input[type=checkbox][data-id]'); if(!cb) return;
  const id=cb.dataset.id;
  const paper=S.discovered.find(p=>(p.paper_id||p.id)===id);
  if(cb.checked){ if(paper) S.selectedPapers.set(id,paper); }
  else S.selectedPapers.delete(id);
  const card=cb.closest('.paper-card'); if(card) card.classList.toggle('selected',cb.checked);
  updateSelectedCount();
});
$('discover-results').addEventListener('click',e=>{
  const one=e.target.closest('[data-indexone]');
  if(one){ indexSingle(one.dataset.indexone, one.dataset.title); }
});

function updateSelectedCount(){
  $('selected-count').textContent=S.selectedPapers.size+' selected';
}

async function loadCollectionPicker(){
  try{
    const d=await api('/research/collections');
    const sel=$('collection-picker');
    sel.innerHTML='<option value="default">default</option>';
    (d.collections||[]).forEach(c=>{ if(c==='default') return; const o=document.createElement('option'); o.value=c; o.textContent=c; sel.appendChild(o); });
    const lib=$('library-collection');
    if(lib){
      lib.innerHTML='<option value="">All collections</option>';
      (d.collections||[]).forEach(c=>{ const o=document.createElement('option'); o.value=c; o.textContent=c; lib.appendChild(o); });
    }
  }catch(_){}
}

/* research progress helpers */
function setRProgress(pct,label){
  $('research-progress-fill').style.width=Math.min(100,Math.max(0,pct))+'%';
  $('research-progress-percent').textContent=Math.round(pct)+'%';
  if(label) $('research-progress-label').textContent=label;
}
function addRLog(text,type=''){
  const log=$('research-progress-log');
  const el=document.createElement('div'); el.className='log-entry '+type; el.textContent=text;
  log.appendChild(el); log.scrollTop=log.scrollHeight;
}

async function streamIndex(papers, collection){
  $('research-progress-card').classList.remove('hide');
  $('research-progress-log').innerHTML='';
  setRProgress(4,'Starting…'); addRLog('Indexing '+papers.length+' paper(s)…');
  await apiStream('/research/index',{paper_ids:papers.map(p=>p.paper_id||p.id),papers,collection},ev=>{
    if(ev.type==='paper_indexed') setRProgress(Math.min(90,20+(ev.total_papers||0)*8),(ev.total_papers||0)+' papers · '+(ev.total_chunks||0)+' chunks');
    else if(ev.type==='paper_error') addRLog('Error: '+ev.error,'error');
    else if(ev.type==='error'){ addRLog('Error: '+ev.error,'error'); toast('Indexing failed',ev.error,'err'); }
    else if(ev.type==='done'||ev.type==='cancelled'){
      setRProgress(100, ev.cancelled?'Cancelled':'Completed');
      addRLog(ev.cancelled?'Cancelled':'Completed','success');
      toast(ev.cancelled?'Cancelled':'Papers indexed','','info');
      S.selectedPapers.clear(); updateSelectedCount();
      loadLibrary();
    }
  });
}

$('index-selected-btn').addEventListener('click',async()=>{
  if(!S.selectedPapers.size){ toast('No papers','Select papers to index first.','err'); return; }
  const collection=$('collection-picker').value||'default';
  try{ await streamIndex([...S.selectedPapers.values()], collection); }
  catch(e){ addRLog('Failed: '+e.message,'error'); toast('Indexing failed',e.message,'err'); }
});

async function indexSingle(id,title){
  const paper=S.discovered.find(p=>(p.paper_id||p.id)===id);
  const papers=paper?[paper]:[{paper_id:id,title}];
  const collection=$('collection-picker').value||'default';
  try{ await streamIndex(papers, collection); }
  catch(e){ toast('Indexing failed',e.message,'err'); }
}

/* ── Research: library ─────────────────────────────────────── */
async function loadLibrary(){
  const collection=$('library-collection').value||'';
  const host=$('library-results');
  host.innerHTML='<div class="loading"><span class="spin"></span> Loading library…</div>';
  try{
    let url='/research/catalog'; if(collection) url+='?collection='+encodeURIComponent(collection);
    const cat=await api(url);
    const ids=cat.papers||[];
    if(!ids.length){
      host.innerHTML='<div class="empty-state"><span class="eicon">📚</span><strong>No papers indexed yet</strong><p>Use Discover to find and index papers.</p></div>';
      return;
    }
    const sr=await api('/research/search',{method:'POST',body:JSON.stringify({q:'*',k:Math.max(ids.length,1),collection:collection||null})});
    const papers=(sr.results||[]).map(r=>({
      paper_id:r.paper_id||'', title:r.title||'', source:r.source||'', year:r.year||null,
      authors:r.author?[r.author]:[], abstract:r.snippet||'', abs_url:r.url||'', already_indexed:true,
    }));
    renderPapers(papers, host, true, '');
  }catch(e){
    host.innerHTML='<div class="empty-state"><span class="eicon">⚠️</span><strong>Failed to load library</strong><p>'+esc(e.message)+'</p></div>';
  }
}
$('library-collection').addEventListener('change',loadLibrary);
$('library-results').addEventListener('click',async e=>{
  const btn=e.target.closest('[data-del]'); if(!btn) return;
  if(!confirm('Remove this paper from the research library?')) return;
  try{
    await api('/research/delete',{method:'POST',body:JSON.stringify({paper_ids:[btn.dataset.del]})});
    toast('Removed','Paper deleted from library.','info');
    loadLibrary();
  }catch(e){ toast('Delete failed',e.message,'err'); }
});

/* ── Scroll reveal for below-fold headers ──────────────────── */
qsa('.section-title,.section-divider').forEach(el=>el.classList.add('reveal'));
const io=new IntersectionObserver(es=>es.forEach(en=>{ if(en.isIntersecting){ en.target.classList.add('in'); io.unobserve(en.target); } }),{threshold:.15});
qsa('.reveal').forEach(el=>io.observe(el));

/* ── Init ──────────────────────────────────────────────────── */
loadRepos();
pollStatus();
navigate('search');