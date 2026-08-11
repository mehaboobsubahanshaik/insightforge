/* Dashboards: list, builder, widgets/charts, cross-filter, drill-through,
   versions, comments, sharing. Edit here for: new widget types, chart styling.
   Widget schema (server-validated): {type: kpi|bar|line|area|pie|donut|table|pivot,
   title, dataset_id, formula, group_by?, group_by2?, limit?, width?} */
async function vDashboards(){
  const [rows,dsAll]=await Promise.all([api('/dashboards'),api('/datasets')]);
  const dbs=wsFilter(rows);
  window._dsCache=dsAll;
  $('#view').innerHTML=`<div class="pagehead"><div><h2>Dashboards</h2>
  <p class="muted">${S.ws==='all'?'All workspaces':'📁 '+esc(wsName(S.ws))} — governed, versioned, shareable.</p></div>
  <div class="row"><button class="btn-ghost" onclick="openFromTemplate()">From template</button>
  <button class="btn" onclick="openNewDash()">+ New dashboard</button></div></div>
  ${dbs.length===0?`<div class="card" style="text-align:center;padding:3rem">
    <div style="font-size:2.2rem">📊</div><h3 style="margin:.5rem 0">No dashboards ${S.ws==='all'?'yet':'in this workspace yet'}</h3>
    <p class="muted">Start from a template — it wires up KPI cards and charts for you.</p>
    <button class="btn" style="margin-top:1rem" onclick="openFromTemplate()">Browse templates</button></div>`
  :`<div class="grid cards stagger">${dbs.map(d=>`
    <div class="card" style="cursor:pointer" onclick="openDash('${d.id}')" tabindex="0" onkeydown="if(event.key==='Enter')this.click()">
      <div class="row between"><b>${esc(d.name)}</b><span class="pill ${d.status}">${d.status}</span></div>
      <div class="muted" style="margin:.2rem 0 .5rem;font-size:.74rem">📁 ${esc(wsName(d.workspace_id))}</div>
      <div class="muted">${d.published_version?`published v${d.published_version}`:'never published'} · ${d.widgets.length} widgets · created ${ago(d.created_at)}</div>
    </div>`).join('')}</div>`}`}
function openNewDash(){
  modal(`<h3>New dashboard</h3>
  <label>Name</label><input id="nd-name" placeholder="e.g. Revenue pulse">
  <label>Workspace (project folder)</label>
  <select id="nd-ws">${S.wsList.map(w=>`<option value="${w.id}" ${w.id===defaultWs()?'selected':''}>📁 ${esc(w.name)}</option>`).join('')}</select>
  <div class="row" style="justify-content:flex-end;margin-top:1.1rem">
    <button class="btn-ghost" onclick="closeModal()">Cancel</button>
    <button class="btn" onclick="createDash()">Create</button></div>`)}
async function createDash(){
  try{const d=await withLoader(()=>api('/dashboards',{method:'POST',json:{
    workspace_id:$('#nd-ws').value,name:$('#nd-name').value.trim()||'Untitled'}}));
    closeModal();openDash(d.id)}
  catch(e){toast(e.message,true)}}
async function openFromTemplate(){
  const ds=wsFilter(window._dsCache||await api('/datasets'));
  if(!ds.length){toast('Land a dataset first — templates need data',true);return}
  const tpls=await withLoader(()=>api('/dashboard-templates'));
  modal(`<h3>Dashboard templates</h3>
  <label>Dataset</label><select id="tp-ds">${ds.map(d=>`<option value="${d.id}">${esc(d.name)} (📁 ${esc(wsName(d.workspace_id))})</option>`).join('')}</select>
  <div style="margin-top:.8rem">${tpls.map(t=>`
    <div class="card" style="margin-bottom:.6rem;cursor:pointer" onclick="useTemplate('${t.key}')">
      <b>${esc(t.name)}</b><p class="muted" style="margin-top:.25rem">${esc(t.description)}</p>
      <p class="muted mono" style="font-size:.72rem;margin-top:.3rem">needs: ${Object.entries(t.requires).map(([k,v])=>`${k} (${v})`).join(', ')}</p></div>`).join('')}
  </div>
  <div class="row" style="justify-content:flex-end"><button class="btn-ghost" onclick="closeModal()">Cancel</button></div>`)}
async function useTemplate(key){
  const dsId=$('#tp-ds').value;const ds=(window._dsCache||[]).find(d=>d.id===dsId);
  const nums=ds.schema.filter(c=>['number','integer'].includes(c.inferred_type)).map(c=>c.name);
  const cats=ds.schema.filter(c=>!['number','integer'].includes(c.inferred_type)&&c.inferred_type!=='date').map(c=>c.name);
  const dates=ds.schema.filter(c=>c.inferred_type==='date').map(c=>c.name);
  if(!nums.length||!cats.length){toast('This template needs a numeric and a text column',true);return}
  modal(`<h3>Map your columns</h3>
  <label>Value column (numeric)</label><select id="tm-val">${nums.map(c=>`<option>${esc(c)}</option>`).join('')}</select>
  <label>Category column</label><select id="tm-cat">${cats.map(c=>`<option>${esc(c)}</option>`).join('')}</select>
  ${dates.length?`<label>Date column</label><select id="tm-date">${dates.map(c=>`<option>${esc(c)}</option>`).join('')}</select>`:''}
  <div class="row" style="justify-content:flex-end;margin-top:1.1rem">
    <button class="btn-ghost" onclick="closeModal()">Back</button>
    <button class="btn" onclick="applyTemplate('${key}','${dsId}')">Create dashboard</button></div>`)}
async function applyTemplate(key,dsId){
  try{const ds=(window._dsCache||[]).find(d=>d.id===dsId);
    const body={dataset_id:dsId,workspace_id:ds.workspace_id,
      value_column:$('#tm-val').value,category_column:$('#tm-cat').value};
    if($('#tm-date'))body.date_column=$('#tm-date').value;
    const d=await withLoader(()=>api(`/dashboard-templates/${key}/apply`,{method:'POST',json:body}));
    closeModal();toast('Dashboard created from template');openDash(d.id)}
  catch(e){toast(e.message,true)}}
let DB=null,XF=[],DRAG=null;
async function openDash(id){DB=await withLoader(()=>api('/dashboards/'+id));XF=[];renderDash()}
async function renderDash(){
  const canEdit=['tenant_owner','tenant_admin','analyst'].includes(S.me.role);
  $('#view').innerHTML=`
  <div class="pagehead"><div>
    <p class="muted"><a href="#" onclick="go('dashboards');return false">Dashboards</a> / 📁 ${esc(wsName(DB.workspace_id))}</p>
    <div class="row"><h2>${esc(DB.name)}</h2><span class="pill ${DB.status}">${DB.status}</span>
    ${DB.published_version?`<span class="muted">published v${DB.published_version}</span>`:''}</div>
    <div class="readout" style="margin-top:.3rem" id="dash-readout"></div></div>
  <div class="row">
    ${canEdit?`<button class="btn-ghost" onclick="openAddWidget()">+ Widget</button>
    <button class="btn-ghost" onclick="openVersions()">Versions</button>
    <button class="btn-ghost" onclick="publishDash()">${DB.published_version?'Republish':'Publish'}</button>`:''}
    <button class="btn-ghost" onclick="openViews()">👁 Views</button>
    <button class="btn-ghost" onclick="openComments()">💬 Comments</button>
    ${DB.published_version?`<button class="btn" onclick="openShare()">Share</button>`:''}
  </div></div>
  ${XF.length?`<div class="row" style="margin-bottom:.8rem">${XF.map((f,i)=>
    `<span class="filter-chip">${esc(f.column)} = ${esc(f.value)}<button onclick="XF.splice(${i},1);renderDash()">✕</button></span>`).join('')}
    <button class="btn-ghost btn-sm" onclick="XF=[];renderDash()">Clear filters</button></div>`:''}
  <div class="grid widgets" id="wgrid">${DB.widgets.map((w,i)=>`
    <div class="card widget-card ${w.width==='full'||w.type==='table'||w.type==='pivot'?'w-full':''}" draggable="${canEdit}" data-i="${i}"
      ondragstart="DRAG=${i};this.classList.add('dragging')" ondragend="this.classList.remove('dragging')"
      ondragover="event.preventDefault();this.classList.add('drop-hint')" ondragleave="this.classList.remove('drop-hint')"
      ondrop="this.classList.remove('drop-hint');dropWidget(${i})">
      <div class="row between"><b>${esc(w.title)}</b>
        ${canEdit?`<button class="btn-danger" onclick="removeWidget(${i})">✕</button>`:''}</div>
      <div id="w-${i}" class="${w.type==='kpi'?'':'chart'}" style="margin-top:.5rem"></div>
    </div>`).join('')}</div>`;
  const q=XF.length?`?filters=${encodeURIComponent(JSON.stringify(XF))}`:'';
  const data=await withLoader(()=>api(`/dashboards/${DB.id}/data${q}`));
  $('#dash-readout').innerHTML=`FRESHNESS <b>${ago(data.freshness)}</b> · QUALITY <b>${data.quality_score??'—'}/100</b> · GOVERNED <b>YES</b>`;
  data.widgets.forEach((wd,i)=>renderWidget(i,wd))}
function renderWidget(i,wd){
  const el=document.getElementById('w-'+i);if(!el)return;
  if(wd.error){el.innerHTML=`<p class="muted" style="color:var(--red)">${esc(wd.error)}</p>`;return}
  if(wd.type==='kpi'){
    el.innerHTML=`<div class="kpi-value" style="color:${PALETTE[i%PALETTE.length]}">${wd.value===null?'—':fmtN(wd.value)}</div>
    <div class="muted mono" style="font-size:.72rem">${esc(wd.formula)}</div>`;return}
  if(wd.type==='table'){
    el.classList.remove('chart');
    el.innerHTML=`<div style="overflow:auto;max-height:330px"><table><thead><tr>${wd.columns.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead>
    <tbody>${wd.rows.map(r=>`<tr>${wd.columns.map(c=>
      `<td>${esc(r[c])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;return}
  if(wd.type==='pivot'){
    el.classList.remove('chart');const p=wd.pivot;
    el.innerHTML=`<div style="overflow:auto;max-height:330px"><table><thead><tr><th>${esc(wd.group_by)} ↓ / ${esc(wd.group_by2)} →</th>
    ${p.cols.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead>
    <tbody>${p.rows.map((rk,ri)=>`<tr><td><b>${esc(rk)}</b></td>
      ${p.cells[ri].map(v=>`<td class="num">${v===null?'—':fmtN(v)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;return}
  // grouped charts: bar | line | area | pie | donut — data in wd.groups [{group,value}]
  const ch=echarts.init(el);
  const cats=(wd.groups||[]).map(r=>r.group),vals=(wd.groups||[]).map(r=>r.value);
  const base={grid:{left:52,right:16,top:22,bottom:34},tooltip:{trigger:'item'},
    xAxis:{type:'category',data:cats,axisLabel:{fontSize:10,rotate:cats.length>6?28:0}},
    yAxis:{type:'value',axisLabel:{fontSize:10}}};
  const click=p=>{onChartClick(wd,p.name)};
  if(wd.type==='bar'){ch.setOption({...base,series:[{type:'bar',data:vals.map((v,j)=>({value:v,
    itemStyle:{color:PALETTE[j%PALETTE.length],borderRadius:[6,6,0,0]}})),barMaxWidth:44}]});ch.on('click',click)}
  else if(wd.type==='line'||wd.type==='area'){ch.setOption({...base,series:[{type:'line',data:vals,smooth:true,symbolSize:7,
    lineStyle:{width:3,color:'#4F46E5'},itemStyle:{color:'#7C3AED'},
    areaStyle:wd.type==='area'?{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(79,70,229,.28)'},{offset:1,color:'rgba(79,70,229,0)'}]}}:undefined}]});ch.on('click',click)}
  else{ch.setOption({tooltip:{trigger:'item'},
    series:[{type:'pie',radius:wd.type==='donut'?['42%','70%']:'70%',
      itemStyle:{borderRadius:7,borderColor:'#fff',borderWidth:2},
      label:{fontSize:10},data:(wd.groups||[]).map((r,j)=>({name:r.group,value:r.value,
        itemStyle:{color:PALETTE[j%PALETTE.length]}}))}]});ch.on('click',click)}
  new ResizeObserver(()=>ch.resize()).observe(el)}
function onChartClick(wd,label){
  const col=wd.group_by;if(!col)return;
  modal(`<h3>${esc(label)}</h3>
  <p class="muted" style="margin:.3rem 0 .9rem">${esc(col)} = ${esc(label)}</p>
  <div class="row" style="justify-content:flex-end">
    <button class="btn-ghost" onclick="closeModal()">Cancel</button>
    <button class="btn-ghost" onclick="closeModal();drillRows('${esc(wd.dataset_id)}','${esc(col)}','${esc(label)}')">View underlying rows</button>
    <button class="btn" onclick="XF.push({column:'${esc(col)}',op:'eq',value:'${esc(label)}'});closeModal();renderDash()">Filter dashboard</button></div>`)}
async function drillRows(dsId,col,label){
  const filt=[{column:col,op:'eq',value:String(label)},...XF.filter(f=>f.column!==col)];
  const prev=await withLoader(()=>api(`/datasets/${dsId}/preview?limit=50&filters=${encodeURIComponent(JSON.stringify(filt))}`));
  modal(`<h3>Underlying rows — ${esc(col)} = ${esc(String(label))}</h3>
  <p class="muted" style="margin:.2rem 0 .6rem">${prev.rows.length} rows from the governed dataset (drill-through).</p>
  <div style="overflow:auto;max-height:420px"><table><thead><tr>${prev.columns.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead>
  <tbody>${prev.rows.map(r=>`<tr>${prev.columns.map(c=>`<td>${esc(r[c])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>
  <div class="row" style="justify-content:flex-end;margin-top:.9rem"><button class="btn-ghost" onclick="closeModal()">Close</button></div>`)}
async function saveWidgets(){
  DB=await api('/dashboards/'+DB.id,{method:'PATCH',json:{widgets:DB.widgets}});renderDash()}
async function dropWidget(target){
  if(DRAG===null||DRAG===target)return;
  const w=DB.widgets.splice(DRAG,1)[0];DB.widgets.splice(target,0,w);DRAG=null;
  try{await saveWidgets()}catch(e){toast(e.message,true)}}
async function removeWidget(i){DB.widgets.splice(i,1);
  try{await saveWidgets()}catch(e){toast(e.message,true)}}
function openAddWidget(){
  const ds=wsFilter(window._dsCache||[]);
  if(!ds.length){toast('No datasets in this workspace yet',true);return}
  modal(`<h3>Add widget</h3>
  <label>Type</label><select id="aw-type" onchange="awTypeChanged()">
    <option value="kpi">KPI card</option><option value="bar">Bar chart</option>
    <option value="line">Line chart</option><option value="area">Area chart</option>
    <option value="pie">Pie chart</option><option value="donut">Donut chart</option>
    <option value="table">Table (latest rows)</option><option value="pivot">Pivot (two-way)</option></select>
  <label>Title</label><input id="aw-title" placeholder="e.g. Revenue by region">
  <label>Dataset</label><select id="aw-ds" onchange="awDsChanged()">${ds.map(d=>`<option value="${d.id}">${esc(d.name)}</option>`).join('')}</select>
  <div id="aw-fields"></div>
  <div class="row" style="justify-content:flex-end;margin-top:1.1rem">
    <button class="btn-ghost" onclick="closeModal()">Cancel</button>
    <button class="btn" onclick="addWidget()">Add widget</button></div>`);
  awDsChanged()}
function awDsChanged(){window._awDs=(window._dsCache||[]).find(d=>d.id===$('#aw-ds').value);awTypeChanged()}
function awTypeChanged(){
  const t=$('#aw-type').value,ds=window._awDs;if(!ds)return;
  const nums=ds.schema.filter(c=>['number','integer'].includes(c.inferred_type)).map(c=>c.name);
  const cats=ds.schema.map(c=>c.name);
  let html='';
  if(t==='table'){html=`<label>Rows to show</label><input id="aw-limit" type="number" value="15" min="1" max="100">`}
  else{
    html=`<label>Governed formula <span style="text-transform:none">— e.g. sum(${esc(nums[0]||'col')}), count(), sum(x)/count()</span></label>
    <input id="aw-formula" class="mono" value="${nums.length?`sum(${esc(nums[0])})`:'count()'}">
    ${t!=='kpi'?`<label>Group by</label><select id="aw-cat">${cats.map(c=>`<option>${esc(c)}</option>`).join('')}</select>`:''}
    ${t==='pivot'?`<label>Then by (columns)</label><select id="aw-cat2">${cats.map(c=>`<option>${esc(c)}</option>`).join('')}</select>`:''}`}
  $('#aw-fields').innerHTML=html}
async function addWidget(){
  const t=$('#aw-type').value,ds=window._awDs;
  const w={type:t,title:$('#aw-title').value.trim()||'Untitled',dataset_id:ds.id};
  if(t==='table')w.limit=Number($('#aw-limit').value)||15;
  else{w.formula=$('#aw-formula').value.trim();
    if(!w.formula){toast('Write a formula, e.g. sum(total)',true);return}
    if(t!=='kpi')w.group_by=$('#aw-cat').value;
    if(t==='pivot')w.group_by2=$('#aw-cat2').value}
  if(['table','pivot'].includes(t))w.width='full';
  DB.widgets.push(w);
  try{await withLoader(saveWidgets);closeModal()}
  catch(e){DB.widgets.pop();toast(e.message,true)}}
async function publishDash(){
  try{const r=await withLoader(()=>api(`/dashboards/${DB.id}/publish`,{method:'POST'}));
    DB.status=r.status;DB.published_version=r.published_version;
    toast(`Published v${r.published_version} — a frozen snapshot your team can trust`);renderDash()}
  catch(e){toast(e.message,true)}}
async function openVersions(){
  const vs=await withLoader(()=>api(`/dashboards/${DB.id}/versions`));
  modal(`<h3>Version history</h3>
  ${vs.length?`<table style="margin-top:.7rem"><thead><tr><th>Version</th><th>By</th><th>When</th><th>Widgets</th><th></th></tr></thead>
  <tbody>${vs.map(v=>`<tr><td>v${v.version}</td><td>${esc(v.published_by)}</td>
    <td class="muted">${new Date(v.at).toLocaleString()}</td>
    <td class="num">${v.widget_count}</td>
    <td style="text-align:right"><button class="btn-ghost btn-sm" onclick="revertTo(${v.version})">Revert to this</button></td></tr>`).join('')}
  </tbody></table>`:'<p class="muted" style="margin-top:.6rem">Nothing published yet.</p>'}
  <div class="row" style="justify-content:flex-end;margin-top:1rem"><button class="btn-ghost" onclick="closeModal()">Close</button></div>`)}
async function revertTo(v){
  try{DB=await withLoader(()=>api(`/dashboards/${DB.id}/revert?version=${v}`,{method:'POST'}));
    closeModal();toast('Reverted — now a draft; publish to release it');renderDash()}
  catch(e){toast(e.message,true)}}
async function openComments(){
  const cs=await withLoader(()=>api(`/dashboards/${DB.id}/comments`));
  modal(`<h3>💬 Comments</h3>
  <div style="max-height:330px;overflow:auto;margin-top:.6rem">${cs.length?cs.map(c=>`
    <div class="comment ${c.parent_id?'reply':''}">
      <b>${esc(c.author)}</b> <span class="muted" style="font-size:.72rem">${ago(c.at)}</span>
      <p style="margin-top:.2rem">${esc(c.body).replace(/@(\w[\w.+-]*)/g,'<b style="color:var(--primary)">@$1</b>')}</p>
      <button class="btn-ghost btn-sm" onclick="$('#cm-parent').value='${c.id}';$('#cm-body').focus();toast('Replying — mention teammates with @name')">Reply</button>
    </div>`).join(''):'<p class="muted">No comments yet. Mention teammates with @name — they get an email.</p>'}</div>
  <input type="hidden" id="cm-parent">
  <label>Add comment</label><textarea id="cm-body" rows="2" placeholder="e.g. @priya can you check June's spike?"></textarea>
  <div class="row" style="justify-content:flex-end;margin-top:.8rem">
    <button class="btn-ghost" onclick="closeModal()">Close</button>
    <button class="btn" onclick="postComment()">Comment</button></div>`)}
async function postComment(){
  const body=$('#cm-body').value.trim();if(!body)return;
  const mentions=[...body.matchAll(/@(\w[\w.+-]*)/g)].map(m=>m[1]);
  try{await withLoader(()=>api(`/dashboards/${DB.id}/comments`,{method:'POST',
    json:{body,parent_id:$('#cm-parent').value||null,mentions}}));openComments()}
  catch(e){toast(e.message,true)}}
async function openShare(){
  const shares=await withLoader(()=>api(`/dashboards/${DB.id}/shares`));
  modal(`<h3>Share dashboard</h3>
  <p class="muted" style="margin:.3rem 0 .8rem">Links expose the <b>published snapshot</b> (v${DB.published_version}) only — never drafts.</p>
  ${shares.length?`<table style="margin-bottom:.8rem"><thead><tr><th>Expires</th><th>Status</th><th></th></tr></thead>
  <tbody>${shares.map(l=>`<tr><td class="muted">${new Date(l.expires_at).toLocaleString()}</td>
    <td><span class="pill ${l.revoked?'failing':l.expired?'draft':'published'}">${l.revoked?'revoked':l.expired?'expired':'live'}</span></td>
    <td style="text-align:right">${!l.revoked&&!l.expired?`<button class="btn-danger" onclick="revokeShare('${l.id}')">Revoke</button>`:''}</td></tr>`).join('')}</tbody></table>`:''}
  <label>New link expires in</label><select id="sh-h"><option value="168">7 days</option><option value="720">30 days</option><option value="24">1 day</option></select>
  <div class="row" style="justify-content:flex-end;margin-top:1rem">
    <button class="btn-ghost" onclick="closeModal()">Close</button>
    <button class="btn" onclick="makeShare()">Create link</button></div>`)}
async function makeShare(){
  try{const s=await withLoader(()=>api(`/dashboards/${DB.id}/share`,{method:'POST',
    json:{expires_in_hours:Number($('#sh-h').value)}}));
    modal(`<h3>Link created</h3>
    <p class="muted" style="margin:.3rem 0 .6rem">Expires ${new Date(s.expires_at).toLocaleString()}</p>
    <input class="mono" value="${s.url}" readonly onclick="this.select()">
    <div class="row" style="justify-content:flex-end;margin-top:1rem">
      <button class="btn" onclick="navigator.clipboard.writeText('${s.url}');toast('Copied')">Copy</button>
      <button class="btn-ghost" onclick="closeModal()">Done</button></div>`)}
  catch(e){toast(e.message,true)}}
async function revokeShare(id){
  try{await api(`/shares/${id}/revoke`,{method:'POST'});openShare()}
  catch(e){toast(e.message,true)}}

/* ---- Saved views: personal & shared filter sets on a dashboard ---- */
let VLIST=[];
async function openViews(){
  try{VLIST=await withLoader(()=>api(`/dashboards/${DB.id}/views`));renderViewsModal()}
  catch(e){toast(e.message,true)}}
function renderViewsModal(){
  const canAdmin=['tenant_owner','tenant_admin'].includes(S.me.role);
  modal(`<h3>👁 Saved views</h3>
  <p class="muted" style="margin:.3rem 0 .8rem">A view is a saved set of filters on this dashboard —
  keep it personal, or share it so the whole team sees the same slice.</p>
  ${VLIST.length?VLIST.map((v,i)=>`
    <div class="row between" style="padding:.45rem 0;border-bottom:1px solid var(--border)">
      <span><b>${esc(v.name)}</b>
        <span class="pill ${v.shared?'published':'draft'}">${v.shared?'team':'personal'}</span>
        <span class="muted" style="font-size:.78rem">${v.filters.length?v.filters.map(f=>esc(f.column)+' = '+esc(f.value)).join(' · '):'no filters (reset)'}</span></span>
      <span class="row">
        <button class="btn-ghost btn-sm" onclick="applyView(${i})">Apply</button>
        ${v.mine||canAdmin?`<button class="btn-ghost btn-sm" onclick="toggleViewShared(${i})">${v.shared?'Make personal':'Share with team'}</button>
        <button class="btn-ghost btn-sm" onclick="archiveView(${i})">Remove</button>`:''}
      </span></div>`).join('')
    :`<p class="muted">No saved views yet.</p>`}
  <label style="margin-top:1rem">Save current filters as a view
    <span class="muted" style="font-size:.78rem">(${XF.length?XF.length+' active filter'+(XF.length>1?'s':''):'none — saves a "show everything" reset view'})</span></label>
  <div class="row"><input id="view-name" placeholder="e.g. South region only" style="flex:1">
    <label class="row" style="gap:.3rem;font-size:.85rem"><input type="checkbox" id="view-shared"> team</label>
    <button class="btn" onclick="saveView()">Save</button></div>
  <div class="row" style="justify-content:flex-end;margin-top:1rem">
    <button class="btn-ghost" onclick="closeModal()">Close</button></div>`)}
async function saveView(){
  const name=$('#view-name').value.trim();if(!name){toast('Give the view a name',true);return}
  try{await api(`/dashboards/${DB.id}/views`,{method:'POST',
      json:{name,filters:XF,shared:$('#view-shared').checked}});
    toast(`View “${name}” saved`);openViews()}
  catch(e){toast(e.message,true)}}
function applyView(i){XF=(VLIST[i].filters||[]).map(f=>({...f}));closeModal();renderDash();
  toast(`View “${VLIST[i].name}” applied`)}
async function toggleViewShared(i){
  try{await api(`/dashboards/${DB.id}/views/${VLIST[i].id}`,{method:'PATCH',
      json:{shared:!VLIST[i].shared}});openViews()}
  catch(e){toast(e.message,true)}}
async function archiveView(i){
  if(!confirm(`Remove view “${VLIST[i].name}”?`))return;
  try{await api(`/dashboards/${DB.id}/views/${VLIST[i].id}`,{method:'PATCH',
      json:{archived:true}});openViews()}
  catch(e){toast(e.message,true)}}