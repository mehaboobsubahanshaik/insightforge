/* Data sources: connector gallery, connection wizard, sync, upload.
   Edit here for: new connector tiles UX, wizard fields, sync history. */
/* ============ sources: gallery, wizard, connections, upload ============ */
let GALLERY=[],GCAT='All';
async function vSources(){
  const [types,connsAll]=await Promise.all([api('/connections/types'),api('/connections')]);
  GALLERY=types;const conns=wsFilter(connsAll);
  const cats=['All','Databases','SaaS apps','Files'];
  $('#view').innerHTML=`
  <div class="pagehead"><div><h2>Data sources</h2>
  <p class="muted">Land data ${S.ws==='all'?'in a workspace':'in “'+esc(wsName(S.ws))+'”'} — live database platforms, SaaS apps, or file uploads.</p></div></div>
  ${conns.length?`<div class="card" style="margin-bottom:1.1rem"><h3>Your connections</h3>
    <table style="margin-top:.5rem"><thead><tr><th></th><th>Name</th><th>Workspace</th><th>Health</th><th>Last sync</th><th></th></tr></thead>
    <tbody>${conns.map(c=>`<tr>
      <td style="width:2.2rem"><span class="glyph" style="width:26px;height:26px;font-size:.7rem;border-radius:8px;background:${c.color}">${esc(c.glyph)}</span></td>
      <td><b>${esc(c.name)}</b><div class="muted" style="font-size:.72rem">${esc(c.label)}</div></td>
      <td class="muted">📁 ${esc(wsName(c.workspace_id))}</td>
      <td><span class="pill ${c.health}">${c.health}</span></td>
      <td class="muted">${ago(c.last_sync_at)}</td>
      <td style="text-align:right"><button class="btn-ghost btn-sm" onclick="runSync('${c.id}')">Sync now</button>
      <button class="btn-ghost btn-sm" onclick="viewRuns('${c.id}')">History</button></td></tr>`).join('')}
    </tbody></table></div>`:''}
  <div class="gallery">
    <div class="catlist card" style="padding:.6rem">${cats.map(c=>
      `<button class="${c===GCAT?'active':''}" onclick="GCAT='${c}';renderTiles()">${c}</button>`).join('')}</div>
    <div class="tilegrid" id="tiles"></div>
  </div>`;
  renderTiles()}
function renderTiles(){
  document.querySelectorAll('.catlist button').forEach(b=>b.classList.toggle('active',b.textContent===GCAT));
  const fileTiles=[{type:'__upload',label:'CSV / Excel upload',category:'Files',color:'#0891B2',glyph:'⇪',
    blurb:'Drop a spreadsheet — typed, profiled & quality-scored on arrival'}];
  const tiles=[...fileTiles,...GALLERY].filter(t=>GCAT==='All'||t.category===GCAT);
  $('#tiles').innerHTML=tiles.map(t=>`
    <div class="tile" onclick="${t.type==='__upload'?'openUpload()':`openWizard('${t.type}')`}" tabindex="0"
      onkeydown="if(event.key==='Enter')this.click()">
      <span class="glyph" style="background:${t.color}">${esc(t.glyph)}</span>
      <b>${esc(t.label)}</b><span>${esc(t.blurb)}</span>
      ${t.supports_sandbox_demo?'<span class="pill cyanp">demo available</span>':''}
    </div>`).join('')}
let WIZ={};
function openWizard(type){
  const t=GALLERY.find(x=>x.type===type);WIZ={t,step:1,cfg:{},creds:{}};
  renderWizard()}
function wizFields(){
  const {t}=WIZ;const k=t.config_keys;
  if(t.engine==='postgresql'||t.engine==='mysql'){
    const isPg=t.engine==='postgresql';
    return `
    <div class="row"><div style="flex:2"><label>Host</label><input id="wz-host" placeholder="db.example.com"></div>
    <div style="flex:1"><label>Port</label><input id="wz-port" value="${isPg?5432:3306}"></div></div>
    <p class="muted" style="margin:.45rem 0 0;font-size:.76rem">💡 Running InsightForge in Docker? <b>127.0.0.1 points at the API container itself.</b>
    Use host <b>postgres</b> for the bundled demo database, or <b>host.docker.internal</b> for a database on your machine.</p>
    <label>Database</label><input id="wz-database">
    <label>Table</label><input id="wz-table">
    <label>Incremental cursor column (optional — e.g. id or updated_at)</label><input id="wz-cursor">
    ${isPg?`<label>SSL mode</label><select id="wz-sslmode"><option value="prefer">prefer (default)</option>
      <option value="require">require (cloud platforms)</option><option value="disable">disable (local dev)</option></select>`
    :`<label>SSL</label><select id="wz-ssl"><option value="">off (local dev)</option><option value="1">on (cloud platforms)</option></select>`}
    <label>User</label><input id="wz-user" autocomplete="off">
    <label>Password</label><input id="wz-pass" type="password" autocomplete="new-password">`}
  const rows=[];
  if(k.includes('realm_id'))rows.push(['realm_id','Realm ID']);
  if(k.includes('instance_url'))rows.push(['instance_url','Instance URL']);
  if(k.includes('shop_domain'))rows.push(['shop_domain','Shop domain']);
  if(k.includes('property_id'))rows.push(['property_id','Property ID']);
  return `${t.supports_sandbox_demo?`<div class="card" style="background:#F0FDFA;border-color:#99F6E4;padding:.7rem .9rem;margin-top:.6rem">
    <label style="margin:0;display:flex;gap:.5rem;align-items:center;text-transform:none;font-size:.85rem">
    <input type="checkbox" id="wz-demo" checked style="width:auto"> Use the built-in sandbox demo (no credentials needed)</label></div>`:''}
  <div id="wz-saas-fields">${rows.map(([id,label])=>`<label>${label}</label><input id="wz-${id}">`).join('')}
  <label>API token</label><input id="wz-token" type="password" autocomplete="new-password"></div>`}
function renderWizard(){
  const {t,step}=WIZ;
  modal(`<div class="row" style="gap:.7rem"><span class="glyph" style="background:${t.color}">${esc(t.glyph)}</span>
  <div><h3>${esc(t.label)}</h3><span class="muted">${esc(t.blurb)}</span></div></div>
  <div class="steps" style="margin-top:.9rem"><i class="on"></i><i class="${step===2?'on':''}"></i></div>
  ${step===1?`
    <label>Connection name</label><input id="wz-name" placeholder="e.g. Production orders" value="${esc(WIZ.name||'')}">
    <label>Workspace (project folder)</label>
    <select id="wz-ws">${S.wsList.map(w=>`<option value="${w.id}" ${w.id===defaultWs()?'selected':''}>📁 ${esc(w.name)}</option>`).join('')}</select>
    ${wizFields()}
    <div class="row" style="justify-content:flex-end;margin-top:1.1rem">
      <button class="btn-ghost" onclick="closeModal()">Cancel</button>
      <button class="btn" onclick="wizTest()">Create & test connection</button></div>`
  :`<div class="card" style="background:#F0FDF4;border-color:#BBF7D0"><b style="color:var(--green)">✓ Connected — credentials verified & encrypted</b>
    <p class="muted" style="margin-top:.3rem">Credentials encrypted with your tenant key. First sync will land a typed, quality-scored dataset in 📁 ${esc(wsName(WIZ.cfgWs))}.</p></div>
    <div class="row" style="justify-content:flex-end;margin-top:1.1rem">
      <button class="btn" onclick="wizCreate()">Run first sync</button></div>`}`);
  if(step===1&&$('#wz-demo')){const tog=()=>{$('#wz-saas-fields').style.display=$('#wz-demo').checked?'none':'block'};
    $('#wz-demo').onchange=tog;tog()}}
function wizCollect(){
  const {t}=WIZ;WIZ.name=$('#wz-name').value.trim();WIZ.cfgWs=$('#wz-ws').value;
  const cfg={},creds={};
  if(t.engine==='postgresql'||t.engine==='mysql'){
    cfg.host=$('#wz-host').value.trim();cfg.port=$('#wz-port').value.trim();
    cfg.database=$('#wz-database').value.trim();cfg.table=$('#wz-table').value.trim();
    if($('#wz-cursor').value.trim())cfg.cursor_column=$('#wz-cursor').value.trim();
    if(t.engine==='postgresql')cfg.sslmode=$('#wz-sslmode').value;
    else if($('#wz-ssl').value)cfg.ssl=true;
    creds.user=$('#wz-user').value;creds.password=$('#wz-pass').value;
  }else{
    if($('#wz-demo')?.checked)cfg.sandbox_demo=true;
    else{for(const key of ['realm_id','instance_url','shop_domain','property_id'])
      if($('#wz-'+key))cfg[key]=$('#wz-'+key).value.trim();
      creds.token=$('#wz-token').value}}
  WIZ.cfg=cfg;WIZ.creds=creds}
async function wizTest(){wizCollect();
  if(!WIZ.name){toast('Give the connection a name',true);return}
  try{WIZ.created=await withLoader(()=>api('/connections',{method:'POST',json:{
    workspace_id:WIZ.cfgWs,name:WIZ.name,connector_type:WIZ.t.type,
    config:WIZ.cfg,credentials:WIZ.creds}}));
    WIZ.step=2;renderWizard()}
  catch(e){toast(e.message,true)}}
async function wizCreate(){
  closeModal();toast('Running first sync…');
  await runSync(WIZ.created.id)}
async function runSync(cid){
  try{const run=await withLoader(()=>api(`/connections/${cid}/sync`,{method:'POST',json:{mode:'incremental'}}));
    if(run.status==='succeeded')toast(`Sync complete: ${run.rows_extracted} extracted → ${run.rows_loaded} rows live`);
    else if(run.status==='no_change')toast('Already up to date — no new rows');
    else toast('Sync '+run.status+': '+(run.error||''),run.status==='failed');
    go(S.view==='sources'?'sources':'datasets')}
  catch(e){toast(e.message,true)}}
async function viewRuns(cid){
  const runs=await withLoader(()=>api(`/connections/${cid}/runs`));
  modal(`<h3>Sync history</h3>
  <table style="margin-top:.7rem"><thead><tr><th>When</th><th>Mode</th><th>Status</th><th>Extracted</th><th>Loaded</th><th>Error</th></tr></thead>
  <tbody>${runs.map(r=>`<tr><td class="muted">${ago(r.started_at)}</td><td>${r.mode}</td>
    <td><span class="pill ${r.status==='succeeded'?'published':r.status==='failed'?'failing':'draft'}">${r.status}</span></td>
    <td class="num">${r.rows_extracted??'—'}</td><td class="num">${r.rows_loaded??'—'}</td>
    <td class="muted" style="max-width:190px;overflow:hidden;text-overflow:ellipsis">${esc(r.error||'')}</td></tr>`).join('')}
  </tbody></table>
  <div class="row" style="justify-content:flex-end;margin-top:1rem"><button class="btn-ghost" onclick="closeModal()">Close</button></div>`)}
function openUpload(){
  modal(`<h3>Upload CSV or Excel</h3>
  <p class="muted" style="margin-top:.3rem">The file becomes a governed dataset: schema inferred, rows profiled, quality scored, bad rows quarantined (never silently dropped).</p>
  <label>Dataset name</label><input id="up-name" placeholder="e.g. June sales">
  <label>Workspace (project folder)</label>
  <select id="up-ws">${S.wsList.map(w=>`<option value="${w.id}" ${w.id===defaultWs()?'selected':''}>📁 ${esc(w.name)}</option>`).join('')}</select>
  <label>File (.csv, .xlsx)</label><input id="up-file" type="file" accept=".csv,.xlsx,.xls">
  <div class="row" style="justify-content:flex-end;margin-top:1.1rem">
    <button class="btn-ghost" onclick="closeModal()">Cancel</button>
    <button class="btn" onclick="doUpload()">Upload & analyze</button></div>`)}
async function doUpload(){
  const f=$('#up-file').files[0];if(!f){toast('Choose a file',true);return}
  const name=$('#up-name').value.trim()||f.name.replace(/\.[^.]+$/,'');
  const fd=new FormData();fd.append('file',f);
  const qs=new URLSearchParams({name,workspace_id:$('#up-ws').value});
  try{const ds=await withLoader(()=>api('/datasets/upload?'+qs,{method:'POST',body:fd}));
    closeModal();toast(`“${name}” ready — quality ${ds.quality_score}/100`);
    S.view='datasets';go('datasets')}
  catch(e){toast(e.message,true)}}
