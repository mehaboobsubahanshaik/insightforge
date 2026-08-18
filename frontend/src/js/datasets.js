/* Datasets: list, detail, preview+drill, lineage, cleaning recipes, AI insights.
   Edit here for: dataset views, recipe ops UX, quality trend, forecasts/anomalies. */
/* ============ datasets: list, detail, recipe, drill ============ */
let DSQ='';
async function vDatasets(){
  const all=wsFilter(await api('/datasets'));
  const q=DSQ.trim().toLowerCase();
  const rows=q?all.filter(d=>d.name.toLowerCase().includes(q)
    ||d.source_type.toLowerCase().includes(q)
    ||wsName(d.workspace_id).toLowerCase().includes(q)):all;
  $('#view').innerHTML=`<div class="pagehead"><div><h2>Datasets</h2>
  <p class="muted">${S.ws==='all'?'All workspaces':'📁 '+esc(wsName(S.ws))} — every dataset carries its trust evidence.</p></div>
  <span class="row" style="gap:.5rem">
  <input id="ds-search" placeholder="🔍 Search name, source, workspace…" value="${esc(DSQ)}"
    oninput="DSQ=this.value;clearTimeout(window._dsq);window._dsq=setTimeout(()=>{const p=this.selectionStart;vDatasets().then(()=>{const el=$('#ds-search');el.focus();el.setSelectionRange(p,p)})},250)"
    style="min-width:230px">
  <button class="btn" onclick="openUpload()">Upload CSV / Excel</button></span></div>
  ${rows.length===0?(q?`<div class="card" style="text-align:center;padding:3rem">
    <div style="font-size:2.2rem">🔍</div><h3 style="margin:.5rem 0">No datasets match “${esc(DSQ)}”</h3>
    <p class="muted">Try a different term, or clear the search.</p>
    <button class="btn-ghost" style="margin-top:1rem" onclick="DSQ='';vDatasets()">Clear search</button></div>`
  :`<div class="card" style="text-align:center;padding:3rem">
    <div style="font-size:2.2rem">🗃️</div><h3 style="margin:.5rem 0">No datasets ${S.ws==='all'?'yet':'in this workspace yet'}</h3>
    <p class="muted">Connect a source or upload a spreadsheet to land your first one.</p>
    <button class="btn" style="margin-top:1rem" onclick="go('sources')">Open data sources</button></div>`)
  :`<div class="grid cards stagger">${rows.map(d=>{
    const q=d.quality_score??100;
    const qc=q>=90?'var(--green)':q>=70?'var(--amber)':'var(--red)';
    return `<div class="card" style="cursor:pointer" onclick="openDataset('${d.id}')" tabindex="0"
      onkeydown="if(event.key==='Enter')this.click()">
      <div class="row between"><b>${esc(d.name)}</b><span class="pill draft">${d.source_type}</span></div>
      <div class="muted" style="margin:.2rem 0 .6rem;font-size:.74rem">📁 ${esc(wsName(d.workspace_id))}</div>
      <div class="row" style="gap:1.4rem">
        <div><div class="muted" style="font-size:.7rem">ROWS</div><b class="mono">${fmtN(d.row_count)}</b></div>
        <div><div class="muted" style="font-size:.7rem">QUALITY</div><b class="mono" style="color:${qc}">${q}</b></div>
        <div><div class="muted" style="font-size:.7rem">QUARANTINED</div><b class="mono">${d.quarantined_count}</b></div>
      </div>
      <div class="usage-bar" style="margin-top:.7rem"><i style="width:${q}%;background:${qc}"></i></div>
      <div class="readout" style="margin-top:.5rem">FRESH <b>${ago(d.ingested_at)}</b></div>
    </div>`}).join('')}</div>`}`}
let DS=null,DRILL=[];
async function openDataset(id){
  DS=await withLoader(()=>api('/datasets/'+id));DRILL=[];
  renderDataset()}
async function renderDataset(){
  const filters=DRILL.length?'&filters='+encodeURIComponent(JSON.stringify(DRILL)):'';
  const [prev,hist]=await withLoader(()=>Promise.all([
    api(`/datasets/${DS.id}/preview?limit=60${filters}`),
    api(`/datasets/${DS.id}/dq-history`)]));
  const q=DS.quality_score??100,dq=DS.dq_results||[],lin=DS.lineage||{};
  $('#view').innerHTML=`
  <div class="pagehead"><div>
    <p class="muted"><a href="#" onclick="go('datasets');return false">Datasets</a> / 📁 ${esc(wsName(DS.workspace_id))}</p>
    <h2>${esc(DS.name)}</h2>
    <div class="readout" style="margin-top:.3rem">FRESHNESS <b>${ago(DS.ingested_at)}</b> · QUALITY <b>${q}/100</b> · ROWS <b>${fmtN(DS.row_count)}</b> · QUARANTINED <b>${DS.quarantined_count}</b> · SOURCE <b>${esc(lin.source||DS.source_type)}</b></div>
  </div>
  <div class="row">
    <button class="btn-ghost" onclick="openRecipe()">🧼 Clean data</button>
    <button class="btn-ghost" onclick="openSuggestions()">✨ Suggest fixes</button>
    <button class="btn-ghost" onclick="openLineage()">Lineage</button>
    <button class="btn-ghost" onclick="openInsights()">✨ AI insights</button>
    <button class="btn" onclick="exportDs('${DS.id}')">Export CSV</button>
  </div></div>
  ${DRILL.length?`<div class="row" style="margin-bottom:.8rem">${DRILL.map((f,i)=>
    `<span class="filter-chip">${esc(f.column)} ${f.op} ${esc(f.value)}<button onclick="DRILL.splice(${i},1);renderDataset()">✕</button></span>`).join('')}
    <button class="btn-ghost btn-sm" onclick="DRILL=[];renderDataset()">Clear drill</button></div>`:''}
  <div class="card" style="margin-bottom:1rem">
    <div class="row between"><h3>💬 Ask this dataset</h3>
      <span class="muted" style="font-size:.75rem">grounded in your columns & certified measures — never a guess</span></div>
    <div class="row" style="margin-top:.5rem">
      <input id="ask-q" placeholder='e.g. "total by region", "average quantity last month", "top 3 products by total"'
        style="flex:1" onkeydown="if(event.key==='Enter')runAsk()">
      <button class="btn-ghost" onclick="voiceAsk()" title="Ask by voice">🎤</button>
    <button class="btn" onclick="runAsk()">Ask</button></div>
    <div id="ask-out"></div>
  </div>
  <div class="grid two" style="margin-bottom:1rem">
    <div class="card"><h3>Data quality checks</h3>
      ${dq.length===0?'<p class="muted" style="margin-top:.5rem">All checks green on the current import.</p>'
      :`<table style="margin-top:.5rem"><thead><tr><th>Rule</th><th>Severity</th><th>Affected</th><th>Detail</th></tr></thead>
      <tbody>${dq.map(r=>`<tr><td>${esc(r.rule)}</td>
        <td><span class="pill ${r.severity==='error'?'failing':'degraded'}">${r.severity}</span></td>
        <td class="num">${r.affected}</td><td class="muted">${esc(r.detail)}</td></tr>`).join('')}</tbody></table>`}
    </div>
    <div class="card"><h3>Quality trend</h3><div id="dq-chart" class="chart"></div></div>
  </div>
  <div class="card"><div class="row between"><h3>Preview <span class="muted" style="font-weight:400">(click a cell to drill)</span></h3>
    <span class="muted">${prev.rows.length} of ${fmtN(DS.row_count)} clean rows</span></div>
    <div style="overflow:auto;max-height:400px;margin-top:.6rem">
    <table><thead><tr>${DS.schema.map(c=>
      `<th><span class="type-ic">${{number:'#',integer:'#',date:'📅',text:'A'}[c.inferred_type]||'A'}</span>${esc(c.name)}</th>`).join('')}</tr></thead>
    <tbody>${prev.rows.map(r=>`<tr>
      ${DS.schema.map(c=>{const v=r[c.name];
        return `<td class="${['number','integer'].includes(c.inferred_type)?'num':''}" style="cursor:pointer"
        onclick="drillCell('${esc(c.name)}','${esc(String(v??''))}')">${['number','integer'].includes(c.inferred_type)?fmtN(v):esc(v)}</td>`}).join('')}
    </tr>`).join('')}</tbody></table></div></div>
  ${DS.quarantined_count?`<div class="card" style="margin-top:1rem"><div class="row between">
    <h3 style="color:var(--red)">Quarantined rows (${DS.quarantined_count})</h3>
    <span class="muted">Never silently dropped — fix with a 🧼 recipe to rescue them.</span></div>
    <div id="qwrap" style="overflow:auto;max-height:260px;margin-top:.6rem"><p class="muted">Loading…</p></div></div>`:''}`;
  if(DS.quarantined_count)loadQuarantine();
  const el=document.getElementById('dq-chart');
  if(el&&hist.length){const ch=echarts.init(el);
    ch.setOption({grid:{left:40,right:16,top:20,bottom:26},
      xAxis:{type:'category',data:hist.map(h=>new Date(h.at).toLocaleDateString()),axisLabel:{fontSize:10}},
      yAxis:{type:'value',min:0,max:100},
      series:[{type:'line',data:hist.map(h=>h.score),smooth:true,symbolSize:8,
        lineStyle:{width:3,color:'#4F46E5'},itemStyle:{color:'#7C3AED'},
        areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,
          colorStops:[{offset:0,color:'rgba(79,70,229,.25)'},{offset:1,color:'rgba(79,70,229,0)'}]}}}]});
    new ResizeObserver(()=>ch.resize()).observe(el)}}
async function loadQuarantine(){
  const d=await api(`/datasets/${DS.id}/preview?limit=40&include_quarantined=true`);
  const rows=d.quarantine||[];
  $('#qwrap').innerHTML=rows.length?`<table><thead><tr><th>Reason</th>${DS.schema.map(c=>`<th>${esc(c.name)}</th>`).join('')}</tr></thead>
  <tbody>${rows.map(r=>`<tr class="quarantined"><td>${esc(r.reason)}</td>
    ${DS.schema.map(c=>`<td>${esc(r[c.name])}</td>`).join('')}</tr>`).join('')}</tbody></table>`
  :'<p class="muted">None in the current import 🎉</p>'}
function drillCell(column,value){
  if(DRILL.some(f=>f.column===column&&f.value===value))return;
  DRILL.push({column,op:'eq',value});renderDataset()}
async function exportDs(id){
  loader(true);try{
    const r=await fetch(`/api/v1/datasets/${id}/export.csv`,{headers:{Authorization:'Bearer '+S.token}});
    const blob=await r.blob();const a=document.createElement('a');
    a.href=URL.createObjectURL(blob);a.download=(DS?.name||'dataset')+'.csv';a.click()}
  finally{loader(false)}}
async function openLineage(){
  const l=DS.lineage||{};
  const hops=[
    ['Source',l.source==='upload'?'CSV/Excel upload by a member':'Live connector sync'+(l.connection_id?' (connection '+l.connection_id.slice(0,8)+'…)':'')],
    ['Trust pipeline','Types inferred → rows validated → bad rows quarantined → columns profiled'],
    ['Quality gate',`Scored ${DS.quality_score}/100 · ${DS.quarantined_count} rows quarantined (recoverable)`],
    ['Current generation',`Import ${l.import_id?l.import_id.slice(0,8)+'…':'—'} · ${fmtN(DS.row_count)} clean rows · ${l.ingested_at?new Date(l.ingested_at).toLocaleString():''}`],
  ];
  modal(`<h3>Lineage — where these numbers come from</h3>
  <div style="margin-top:.8rem">${hops.map((h,i)=>`
    <div class="row" style="gap:.7rem;padding:.45rem 0">
      <span class="glyph" style="width:30px;height:30px;font-size:.72rem;border-radius:9px;background:${PALETTE[i%PALETTE.length]}">${i+1}</span>
      <div><b>${esc(h[0])}</b><div class="muted" style="font-size:.78rem">${esc(h[1])}</div></div></div>`).join('')}
  </div>
  <p class="muted" style="font-size:.75rem">Every recipe application or re-sync writes a NEW generation — numbers are snapshot-consistent and auditable.</p>
  <div class="row" style="justify-content:flex-end;margin-top:1rem"><button class="btn-ghost" onclick="closeModal()">Close</button></div>`)}
/* ---- cleaning recipe editor ---- */
let RSTEPS=[];
async function openRecipe(){
  const r=await withLoader(()=>api(`/datasets/${DS.id}/recipe`));
  RSTEPS=structuredClone(r.steps||[]);
  renderRecipe(r.ops)}
function renderRecipe(ops){
  const cols=DS.schema.map(c=>c.name);
  const OPMETA={trim:'Trim spaces',uppercase:'UPPERCASE',lowercase:'lowercase',
    replace:'Find & replace',fill_missing:'Fill missing',strip_non_numeric:'Extract number'};
  modal(`<h3>🧼 Cleaning recipe</h3>
  <p class="muted" style="margin:.3rem 0 .8rem">Steps run in order over <b>every row</b> (including quarantined ones — cleaning is how you rescue them), then types, quality and lineage are recomputed.</p>
  <div id="rsteps">${RSTEPS.map((s,i)=>`
    <div class="row" style="padding:.35rem 0;border-bottom:1px solid var(--border)">
      <span class="mono muted">${i+1}.</span><b>${OPMETA[s.op]}</b>
      <span class="pill draft">${esc(s.column)}</span>
      ${s.op==='replace'?`<span class="muted mono" style="font-size:.75rem">"${esc(s.find)}"→"${esc(s.replace)}"</span>`:''}
      ${s.op==='fill_missing'?`<span class="muted mono" style="font-size:.75rem">→"${esc(s.value)}"</span>`:''}
      <span style="flex:1"></span>
      <button class="btn-danger" onclick="RSTEPS.splice(${arguments.length?i:i},1);renderRecipe(${JSON.stringify(ops).replace(/"/g,'&quot;')})">remove</button>
    </div>`).join('')||'<p class="muted">No steps yet — add one below.</p>'}</div>
  <div class="card" style="margin-top:.9rem;background:#F8FAFD">
    <div class="row">
      <select id="r-op" style="flex:1">${ops.map(o=>`<option value="${o}">${OPMETA[o]||o}</option>`).join('')}</select>
      <select id="r-col" style="flex:1">${cols.map(c=>`<option>${esc(c)}</option>`).join('')}</select>
    </div>
    <div class="row" style="margin-top:.5rem">
      <input id="r-find" placeholder="find (for replace)" style="flex:1">
      <input id="r-val" placeholder="replace with / fill value" style="flex:1">
    </div>
    <button class="btn-ghost btn-sm" style="margin-top:.6rem" onclick="addStep()">+ Add step</button>
  </div>
  <div class="row" style="justify-content:flex-end;margin-top:1.1rem">
    <button class="btn-ghost" onclick="closeModal()">Cancel</button>
    <button class="btn" onclick="applyRecipe()">Apply recipe (${RSTEPS.length} steps)</button></div>`)}
function addStep(){
  const op=$('#r-op').value,column=$('#r-col').value;
  const step={op,column};
  if(op==='replace'){step.find=$('#r-find').value;step.replace=$('#r-val').value;
    if(!step.find){toast('Replace needs a find value',true);return}}
  if(op==='fill_missing')step.value=$('#r-val').value;
  RSTEPS.push(step);
  api(`/datasets/${DS.id}/recipe`).then(r=>renderRecipe(r.ops))}
async function applyRecipe(){
  try{const d=await withLoader(()=>api(`/datasets/${DS.id}/recipe/apply`,{method:'POST',json:{steps:RSTEPS}}));
    DS=d;closeModal();toast(`Recipe applied — quality now ${d.quality_score}/100`);renderDataset()}
  catch(e){toast(e.message,true)}}

/* ---- AI insights: forecast + anomaly detection (ml/ package) ---- */
async function openInsights(){
  const nums=DS.schema.filter(c=>['number','integer'].includes(c.inferred_type)).map(c=>c.name);
  const dates=DS.schema.filter(c=>c.inferred_type==='date').map(c=>c.name);
  const cats=DS.schema.filter(c=>!['number','integer'].includes(c.inferred_type)).map(c=>c.name);
  if(!nums.length){toast('Insights need at least one numeric column',true);return}
  modal(`<h3>✨ AI insights</h3>
  <p class="muted" style="margin:.3rem 0 .6rem">Forecast the trend and hunt anomalies in a governed series —
  facts, forecasts and anomalies are always labelled apart.</p>
  <div class="row"><div style="flex:1"><label>Value (sum of)</label>
    <select id="ins-val">${nums.map(c=>`<option>${esc(c)}</option>`).join('')}</select></div>
  <div style="flex:1"><label>Over (date/category)</label>
    <select id="ins-date">${[...dates,...cats].map(c=>`<option>${esc(c)}</option>`).join('')}</select></div>
  <div style="width:110px"><label>Horizon</label><select id="ins-h"><option>6</option><option>3</option><option>12</option></select></div></div>
  <div class="row" style="justify-content:flex-end;margin-top:.9rem">
    <button class="btn-ghost" onclick="closeModal()">Close</button>
    <button class="btn" onclick="runInsights()">Analyze</button></div>
  <div id="ins-out"></div>`)}
async function runInsights(){
  try{const d=await withLoader(()=>api(`/datasets/${DS.id}/insights?value_column=${encodeURIComponent($('#ins-val').value)}`+
      `&date_column=${encodeURIComponent($('#ins-date').value)}&horizon=${$('#ins-h').value}`));
    const anoms=d.anomalies.anomalies||[];
    $('#ins-out').innerHTML=`
    <div class="readout" style="margin:1rem 0 .4rem">FRESHNESS <b>${ago(d.freshness)}</b> · QUALITY <b>${d.quality_score}/100</b> · METHOD <b>${d.forecast.method||'—'}</b></div>
    <div id="ins-chart" class="chart" style="height:270px"></div>
    <h3 style="margin-top:.9rem">Anomalies ${anoms.length?`<span class="pill failing">${anoms.length}</span>`:'<span class="pill published">none</span>'}</h3>
    ${anoms.length?`<table style="margin-top:.4rem"><thead><tr><th>Where</th><th>Value</th><th>Expected</th><th>Score</th><th>Direction</th></tr></thead>
    <tbody>${anoms.slice(0,8).map(a=>`<tr><td class="mono" style="font-size:.78rem">${esc(a.label)}</td>
      <td class="num">${fmtN(a.value)}</td><td class="num">${fmtN(a.expected)}</td>
      <td class="num">${a.score}</td><td><span class="pill ${a.direction==='spike'?'degraded':'failing'}">${a.direction}</span></td></tr>`).join('')}</tbody></table>`
    :'<p class="muted" style="margin-top:.3rem">No point deviates ≥3.5 robust z-scores from its neighbours.</p>'}
    ${d.forecast.error?`<p class="muted" style="color:var(--red)">Forecast: ${esc(d.forecast.error)}</p>`
    :`<p class="muted" style="margin-top:.6rem">Next ${d.forecast.points.length} steps trend <b style="color:${d.forecast.trend_per_step>=0?'var(--green)':'var(--red)'}">${d.forecast.trend_per_step>=0?'+':''}${fmtN(d.forecast.trend_per_step)}</b> per step (95% band shown).</p>`}`;
    if(!d.forecast.error){
      const hist=d.series,fc=d.forecast.points;
      const labels=[...hist.map(x=>x.label),...fc.map(p=>'+'+p.step)];
      const histData=[...hist.map(x=>x.value),...fc.map(()=>null)];
      const fcData=[...hist.map(()=>null),...fc.map(p=>p.forecast)];
      if(hist.length)fcData[hist.length-1]=hist[hist.length-1].value;
      const lo=[...hist.map(()=>null),...fc.map(p=>p.lo)];
      const band=[...hist.map(()=>null),...fc.map(p=>p.hi-p.lo)];
      const anomIdx=new Set(anoms.map(a=>a.index));
      const ch=echarts.init(document.getElementById('ins-chart'));
      ch.setOption({grid:{left:56,right:16,top:24,bottom:34},tooltip:{trigger:'axis'},
        xAxis:{type:'category',data:labels,axisLabel:{fontSize:9,rotate:labels.length>10?35:0}},
        yAxis:{type:'value',axisLabel:{fontSize:10},scale:true},
        series:[
          {name:'actual',type:'line',data:histData.map((v,i)=>anomIdx.has(i)?{value:v,symbolSize:11,
            itemStyle:{color:'#EF4444',borderColor:'#fff',borderWidth:2}}:v),smooth:true,symbolSize:6,
            lineStyle:{width:3,color:'#4F46E5'},itemStyle:{color:'#7C3AED'}},
          {name:'band-lo',type:'line',data:lo,stack:'b',lineStyle:{opacity:0},symbol:'none'},
          {name:'95% band',type:'line',data:band,stack:'b',lineStyle:{opacity:0},symbol:'none',
            areaStyle:{color:'rgba(8,145,178,.16)'}},
          {name:'forecast',type:'line',data:fcData,symbolSize:6,
            lineStyle:{width:3,type:'dashed',color:'#0891B2'},itemStyle:{color:'#0891B2'}}]});
      new ResizeObserver(()=>ch.resize()).observe(document.getElementById('ins-chart'))}}
  catch(e){toast(e.message,true)}}


/* ---- MVP3: governed natural-language questions ---- */
async function runAsk(){
  const q=$('#ask-q').value.trim();if(!q)return;
  try{const a=await withLoader(()=>api(`/datasets/${DS.id}/ask`,{method:'POST',json:{question:q}}));
    const out=$('#ask-out');
    if(a.explanation){
      out.innerHTML=`<div style="margin-top:.8rem"><p style="font-size:.92rem;line-height:1.55">${esc(a.explanation.text)}</p>
        ${a.explanation.certified_measure?`<span class="pill published">certified: ${esc(a.explanation.certified_measure)}</span>`:''}
        <div class="readout" style="margin-top:.6rem">QUALITY <b>${a.quality_score}</b> · FRESH <b>${ago(a.freshness)}</b></div></div>`;
      return}
    if(!a.answered){
      out.innerHTML=`<div style="margin-top:.8rem"><p class="muted">${esc(a.reason)}</p>
        <p class="muted" style="font-size:.78rem">Try things like: ${a.answerable.examples.map(e=>`<code>${esc(e)}</code>`).join(' · ')}</p></div>`;
      return}
    let body='';
    if(a.answer.groups){
      const max=Math.max(...a.answer.groups.map(g=>g.value),1);
      body=a.answer.groups.map(g=>`<div class="row" style="gap:.6rem;align-items:center;margin:.2rem 0">
        <span style="min-width:110px;font-size:.8rem">${esc(g.group)}</span>
        <div style="flex:1;background:var(--surface2);border-radius:6px"><div style="width:${Math.max(2,g.value/max*100)}%;background:var(--primary);height:14px;border-radius:6px"></div></div>
        <b class="mono" style="min-width:80px;text-align:right">${fmtN(g.value)}</b></div>`).join('')}
    else body=`<div class="kpi-value" style="color:var(--primary)">${fmtN(a.answer.value)}</div>`;
    out.innerHTML=`<div style="margin-top:.8rem">${body}
      <div class="readout" style="margin-top:.6rem">${esc(a.description)} · CONFIDENCE <b>${a.confidence.toUpperCase()}</b> · QUALITY <b>${a.quality_score}</b> · FRESH <b>${ago(a.freshness)}</b></div>
      <div class="row between" style="margin-top:.5rem">
      <button class="btn-ghost btn-sm" onclick='addAskWidget(${JSON.stringify(JSON.stringify(a.suggested_widget))})'>➕ Add as ${esc(a.suggested_widget.type)} widget to a dashboard…</button>
      <span>${fbButtons('question',q)}</span></div>
    </div>`}
  catch(e){toast(e.message,true)}}
async function addAskWidget(wjson){
  const w=JSON.parse(wjson);
  try{const dbs=wsFilter(await api('/dashboards')).filter(d=>!d.archived);
    if(!dbs.length){toast('Create a dashboard first (Dashboards page)',true);return}
    modal(`<h3>Add "${esc(w.title)}" to…</h3>
      ${dbs.map(d=>`<div class="row between" style="padding:.4rem 0;border-bottom:1px solid var(--border)">
        <span>${esc(d.name)}</span>
        <button class="btn-ghost btn-sm" onclick='confirmAddAsk("${d.id}",${JSON.stringify(wjson)})'>Add</button></div>`).join('')}
      <div class="row" style="justify-content:flex-end;margin-top:1rem"><button class="btn-ghost" onclick="closeModal()">Cancel</button></div>`)}
  catch(e){toast(e.message,true)}}
async function confirmAddAsk(did,wjson){
  const w=JSON.parse(wjson);
  try{const d=await api('/dashboards/'+did);
    await api('/dashboards/'+did,{method:'PATCH',json:{widgets:[...d.widgets,w]}});
    closeModal();toast(`Widget added to "${d.name}" (draft) — publish when ready`)}
  catch(e){toast(e.message,true)}}


/* ---- MVP3: AI-assisted prep suggestions + feedback ---- */
async function openSuggestions(){
  try{const r=await withLoader(()=>api(`/datasets/${DS.id}/prep-suggestions`));
    const sugs=r.suggestions;
    modal(`<h3>✨ Suggested fixes</h3>
    <p class="muted" style="margin:.3rem 0 .8rem">${esc(r.note)}</p>
    ${sugs.length?sugs.map((sg,i)=>`
      <div style="padding:.5rem 0;border-bottom:1px solid var(--border)">
        <div class="row between"><b>${esc(sg.op)} · ${esc(sg.column)}</b>
          <button class="btn-ghost btn-sm" onclick="applySuggestion(${i})">Apply</button></div>
        <p class="muted" style="margin:.2rem 0 0;font-size:.8rem">Why: ${esc(sg.reason)}<br>Effect: ${esc(sg.effect)}</p></div>`).join('')
      +`<div class="row" style="justify-content:space-between;margin-top:1rem">
        <span>${fbButtons('prep_suggestion','suggestions for '+DS.name)}</span>
        <span class="row" style="gap:.5rem">
          <button class="btn" onclick="applyAllSuggestions()">Apply all ${sugs.length}</button>
          <button class="btn-ghost" onclick="closeModal()">Close</button></span></div>`
      :`<div class="row" style="justify-content:flex-end;margin-top:1rem"><button class="btn" onclick="closeModal()">Close</button></div>`}`);
    window.SUGS=sugs}
  catch(e){toast(e.message,true)}}
function _sugSteps(list){return list.map(s=>({op:s.op,column:s.column,...(s.value!==undefined?{value:s.value}:{})}))}
async function applySuggestion(i){
  try{await withLoader(()=>api(`/datasets/${DS.id}/recipe/apply`,{method:'POST',json:{steps:_sugSteps([SUGS[i]])}}));
    toast('Applied — dataset re-scored');closeModal();openDataset(DS.id)}
  catch(e){toast(e.message,true)}}
async function applyAllSuggestions(){
  try{await withLoader(()=>api(`/datasets/${DS.id}/recipe/apply`,{method:'POST',json:{steps:_sugSteps(SUGS)}}));
    toast(`Applied ${SUGS.length} fixes — dataset re-scored`);closeModal();openDataset(DS.id)}
  catch(e){toast(e.message,true)}}
function fbButtons(kind,subject){
  const s=JSON.stringify(subject).replace(/"/g,'&quot;');
  return `<span class="muted" style="font-size:.78rem">Was this helpful?</span>
  <button class="btn-ghost btn-sm" onclick='sendFeedback("${kind}",${s},true)'>👍</button>
  <button class="btn-ghost btn-sm" onclick='sendFeedback("${kind}",${s},false)'>👎</button>`}
async function sendFeedback(kind,subject,helpful){
  try{await api('/ai/feedback',{method:'POST',json:{kind,subject,helpful}});
    toast(helpful?'Thanks!':'Thanks — noted for the eval suite')}
  catch(e){toast(e.message,true)}}


/* ---- MVP6 A3: voice-based analytics (Web Speech API -> governed NLQ) ---- */
function voiceAsk(){
  const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!SR){toast('Voice input needs Chrome/Edge (Web Speech API)',true);return}
  const r=new SR();r.lang=document.documentElement.lang==='hi'?'hi-IN':'en-US';
  toast('Listening… ask your question');
  r.onresult=e=>{const q=e.results[0][0].transcript;
    document.getElementById('ask-q').value=q;runAsk()};
  r.onerror=e=>toast('Voice: '+e.error,true);
  r.start()}
