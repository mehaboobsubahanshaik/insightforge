/* Core: state, API client, loader, toasts, modals, WORKSPACES, auth.
   Edit here for: session handling, workspace switcher/management, login/register. */
/* ============ core: state, api, loader, toast, modal, workspace ============ */
const $=s=>document.querySelector(s);
const S={token:null,refresh:null,me:null,tenant:null,view:'home',ws:'all',wsList:[]};
const PALETTE=['#4F46E5','#06B6D4','#16A34A','#F59E0B','#EF4444','#8B5CF6','#EC4899','#84CC16'];
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmtN=x=>{const n=Number(x);return Number.isFinite(n)?n.toLocaleString(undefined,{maximumFractionDigits:2}):esc(x)};
const ago=iso=>{if(!iso)return'never';const s=(Date.now()-new Date(iso))/1e3;
  if(s<60)return'just now';if(s<3600)return Math.floor(s/60)+'m ago';
  if(s<86400)return Math.floor(s/3600)+'h ago';return Math.floor(s/86400)+'d ago'};
let LDEPTH=0,LTIMER=null;
const LOADER_MSGS=['Analyzing your data…','Scoring data quality…','Checking freshness…','Forging insights…'];
function loader(on){
  if(on){LDEPTH++;if(LDEPTH===1){let i=0;$('#loader-msg').textContent=LOADER_MSGS[0];
    $('#loader').classList.add('on');
    LTIMER=setInterval(()=>{i=(i+1)%LOADER_MSGS.length;$('#loader-msg').textContent=LOADER_MSGS[i]},1400);}}
  else{LDEPTH=Math.max(0,LDEPTH-1);if(LDEPTH===0){$('#loader').classList.remove('on');clearInterval(LTIMER)}}}
async function withLoader(fn){loader(true);try{return await fn()}finally{loader(false)}}
function toast(msg,err=false){const t=document.createElement('div');t.className='toast'+(err?' err':'');
  t.textContent=msg;document.body.appendChild(t);setTimeout(()=>t.remove(),4200)}
async function api(path,opts={}){
  const headers=opts.headers||{};
  if(S.token)headers['Authorization']='Bearer '+S.token;
  if(opts.json){headers['Content-Type']='application/json';opts.body=JSON.stringify(opts.json)}
  let r=await fetch('/api/v1'+path,{...opts,headers});
  if(r.status===401&&S.refresh&&!opts._retried){
    const rr=await fetch('/api/v1/auth/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({refresh_token:S.refresh})});
    if(rr.ok){const d=await rr.json();S.token=d.access_token;S.refresh=d.refresh_token;saveSession();
      return api(path,{...opts,_retried:true})}
    logout();throw new Error('Session expired')}
  if(!r.ok){let d;try{d=await r.json()}catch{d={}}
    const err=new Error(d.detail?.detail||d.detail||d.title||('HTTP '+r.status));
    err.status=r.status;throw err}
  if(r.status===204)return null;
  return r.json()}
function saveSession(){sessionStorage.setItem('if_session',JSON.stringify({token:S.token,refresh:S.refresh,ws:S.ws}))}
function modal(html){$('#modal-root').innerHTML=`<div class="modal-bg" onclick="if(event.target===this)closeModal()"><div class="modal">${html}</div></div>`}
function closeModal(){$('#modal-root').innerHTML=''}
/* ---- workspaces: the project folders of InsightForge ---- */
async function loadWorkspaces(){S.wsList=await api('/workspaces');
  const saved=S.ws; const sel=$('#ws-switch');
  sel.innerHTML=`<option value="all">🗂 All workspaces</option>`+
    S.wsList.map(w=>`<option value="${w.id}" ${w.id===saved?'selected':''}>📁 ${esc(w.name)}</option>`).join('')+
    `<option value="__manage">⚙ Manage workspaces…</option>`;
  if(saved!=='all'&&!S.wsList.find(w=>w.id===saved))S.ws='all';
  sel.value=S.ws}
function setWorkspace(v){
  if(v==='__manage'){$('#ws-switch').value=S.ws;openWorkspaces();return}
  S.ws=v;saveSession();go(S.view)}
function wsFilter(rows){return S.ws==='all'?rows:rows.filter(r=>r.workspace_id===S.ws)}
function wsName(id){const w=S.wsList.find(w=>w.id===id);return w?w.name:'—'}
function defaultWs(){return S.ws!=='all'?S.ws:(S.wsList[0]||{}).id}
function openWorkspaces(){
  modal(`<h3>📁 Workspaces</h3>
  <p class="muted" style="margin:.4rem 0 .8rem">A workspace keeps everything about one project in one place —
  its connections, datasets and dashboards live together, so each project stays organised.</p>
  <div id="ws-rows">${S.wsList.map(w=>`
    <div class="row between" style="padding:.45rem 0;border-bottom:1px solid var(--border)">
      <span><b>📁 ${esc(w.name)}</b></span>
      <span class="row">
        <button class="btn-ghost btn-sm" onclick="renameWorkspace('${w.id}','${esc(w.name)}')">Rename</button>
        <button class="btn-ghost btn-sm" onclick="setWorkspace('${w.id}');closeModal()">Open</button>
      </span></div>`).join('')}</div>
  <label>New workspace (one per project)</label>
  <div class="row"><input id="ws-new" placeholder="e.g. Retail analytics" style="flex:1">
  <button class="btn" onclick="createWorkspace()">Create</button></div>
  <div class="row" style="justify-content:flex-end;margin-top:1rem"><button class="btn-ghost" onclick="closeModal()">Close</button></div>`)}
async function createWorkspace(){const name=$('#ws-new').value.trim();if(!name)return;
  try{const w=await withLoader(()=>api('/workspaces',{method:'POST',json:{name}}));
    await loadWorkspaces();S.ws=w.id;saveSession();$('#ws-switch').value=w.id;closeModal();
    toast(`Workspace “${name}” created — new sources and dashboards will live here`);go(S.view)}
  catch(e){toast(e.message,true)}}
async function renameWorkspace(id,current){const name=prompt('Workspace name',current);if(!name||name===current)return;
  try{await api('/workspaces/'+id,{method:'PATCH',json:{name}});await loadWorkspaces();openWorkspaces();go(S.view)}
  catch(e){toast(e.message,true)}}
/* ============ auth ============ */
function authTab(which){['login','register','invite'].forEach(t=>{
  $('#f-'+t).style.display=t===which?'block':'none';
  $('#tab-'+t).classList.toggle('active',t===which)})}
async function doLogin(ev){ev.preventDefault();
  try{const body={email:$('#li-email').value,password:$('#li-pass').value};
    if($('#li-otp').value)body.otp=$('#li-otp').value;
    if($('#li-slug').value)body.tenant_slug=$('#li-slug').value;
    const d=await withLoader(()=>api('/auth/login',{method:'POST',json:body}));
    S.token=d.access_token;S.refresh=d.refresh_token;saveSession();enter()}
  catch(e){
    if(e.status===428){$('#li-otp-wrap').style.display='block';toast('Enter your MFA code');return false}
    toast(e.message,true)}return false}
async function doRegister(ev){ev.preventDefault();
  try{const d=await withLoader(()=>api('/auth/register',{method:'POST',json:{
    tenant_name:$('#rg-org').value,tenant_slug:$('#rg-slug').value,
    display_name:$('#rg-name').value,email:$('#rg-email').value,password:$('#rg-pass').value}}));
    S.token=d.access_token;S.refresh=d.refresh_token;saveSession();
    sessionStorage.removeItem('if_toured');enter()}
  catch(e){toast(e.message,true)}return false}
async function doAcceptInvite(ev){ev.preventDefault();
  try{const body={token:$('#iv-token').value};
    if($('#iv-name').value)body.display_name=$('#iv-name').value;
    if($('#iv-pass').value)body.password=$('#iv-pass').value;
    const d=await withLoader(()=>api('/auth/accept-invite',{method:'POST',json:body}));
    S.token=d.access_token;S.refresh=d.refresh_token;saveSession();enter()}
  catch(e){toast(e.message,true)}return false}
async function resetFlow(){const email=prompt('Account email for password reset:');if(!email)return false;
  try{await api('/auth/password-reset/request',{method:'POST',json:{email}});
    const token=prompt('Reset requested. Paste the token from the reset email (dev: outbox/*.eml):');
    if(!token)return false;
    const pw=prompt('New password (10+ characters):');if(!pw)return false;
    await api('/auth/password-reset/confirm',{method:'POST',json:{token,new_password:pw}});
    toast('Password reset — log in with your new password')}
  catch(e){toast(e.message,true)}return false}
function logout(){sessionStorage.removeItem('if_session');location.reload()}
async function enter(){
  try{
    S.me=await api('/auth/me');S.tenant=await api('/tenants/current');
    await loadWorkspaces();
    $('#auth').style.display='none';$('#shell').style.display='block';
    $('#who').textContent=S.me.display_name;
    $('#avatar').textContent=(S.me.display_name||'?').slice(0,1).toUpperCase();
    $('#chip').innerHTML=`<b>${esc(S.tenant.slug)}</b> · ${esc(S.tenant.plan_code)} plan`;
    renderNav();go('home');
    if(!sessionStorage.getItem('if_toured'))setTimeout(()=>startTour(false),600);
  }catch(e){toast(e.message,true);logout()}}
