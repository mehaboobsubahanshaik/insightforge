/* Navigation rail, Home view, guided product tour.
   Edit here for: nav items, home KPIs/checklist, tour steps. */
/* ============ nav + home + tour ============ */
const NAV=[
 ['home','Home','<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/></svg>'],
 ['sources','Sources','<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><ellipse cx="12" cy="5.5" rx="7.5" ry="3"/><path d="M4.5 5.5v13c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3v-13"/><path d="M4.5 12c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3"/></svg>'],
 ['datasets','Datasets','<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3.5" y="4" width="17" height="16" rx="2"/><path d="M3.5 9.5h17M9 4v16"/></svg>'],
 ['dashboards','Dashboards','<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3.5" y="3.5" width="7" height="10" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="6" rx="1.5"/><rect x="13.5" y="12.5" width="7" height="8" rx="1.5"/><rect x="3.5" y="16.5" width="7" height="4" rx="1.5"/></svg>'],
 ['members','Members','<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.8-3.6 3.4-5.5 6.5-5.5s5.7 1.9 6.5 5.5"/><circle cx="17.5" cy="9.5" r="2.5"/><path d="M16 14.7c2.6.3 4.6 1.9 5.4 4.8"/></svg>'],
 ['activity','Activity','<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 12h4l2.5-7 4 14 2.5-7h5"/></svg>'],
 ['billing','Billing','<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="5.5" width="18" height="13" rx="2"/><path d="M3 10h18"/><path d="M7 15h4"/></svg>'],
 ['settings','Settings','<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3"/><path d="M12 2.8v3M12 18.2v3M21.2 12h-3M5.8 12h-3M18.5 5.5l-2.1 2.1M7.6 16.4l-2.1 2.1M18.5 18.5l-2.1-2.1M7.6 7.6 5.5 5.5"/></svg>'],
];
function renderNav(){$('#nav').innerHTML=NAV.map(([id,label,icon])=>
  `<button id="nav-${id}" onclick="go('${id}')" aria-label="${label}">${icon}<span>${label}</span></button>`).join('')}
async function go(view){S.view=view;
  NAV.forEach(([id])=>$('#nav-'+id)?.classList.toggle('active',id===view));
  const fn={home:vHome,sources:vSources,datasets:vDatasets,dashboards:vDashboards,
            members:vMembers,activity:vActivity,billing:vBilling,settings:vSettings}[view];
  try{await withLoader(fn)}catch(e){toast(e.message,true)}}
async function vHome(){
  const [dsAll,dbAll,connAll,bill]=await Promise.all([
    api('/datasets'),api('/dashboards'),api('/connections'),api('/billing/summary')]);
  const ds=wsFilter(dsAll),db=wsFilter(dbAll),conn=wsFilter(connAll);
  const wsLabel=S.ws==='all'?'across all workspaces':'in “'+esc(wsName(S.ws))+'”';
  const avgQ=ds.length?Math.round(ds.reduce((a,d)=>a+(d.quality_score??100),0)/ds.length):null;
  const done={source:conn.length>0||ds.length>0,dataset:ds.length>0,dash:db.length>0,
              publish:db.some(x=>x.status==='published'),team:bill.usage.members>1};
  $('#view').innerHTML=`
  <div class="pagehead"><div><h2>Welcome back, ${esc(S.me.display_name.split(' ')[0])} 👋</h2>
  <p class="muted">Here's the pulse of <b>${esc(S.tenant.name)}</b> ${wsLabel}.</p></div>
  <button class="btn" onclick="go('sources')">+ Connect data</button></div>
  <div class="grid cards stagger">
    <div class="card"><div class="muted">Datasets</div><div class="kpi-value" style="color:var(--primary)">${ds.length}</div></div>
    <div class="card"><div class="muted">Dashboards</div><div class="kpi-value" style="color:var(--cyan)">${db.length}</div></div>
    <div class="card"><div class="muted">Live connections</div><div class="kpi-value" style="color:var(--pink)">${conn.length}</div></div>
    <div class="card"><div class="muted">Avg data quality</div><div class="kpi-value" style="color:${avgQ===null?'var(--muted)':avgQ>=90?'var(--green)':avgQ>=70?'var(--amber)':'var(--red)'}">${avgQ===null?'—':avgQ}</div></div>
  </div>
  <div class="grid two" style="margin-top:1rem">
    <div class="card"><h3>Get to first insight</h3><div class="checklist" style="margin-top:.5rem">
      ${[['source','Connect a source or upload a file'],['dataset','Land your first dataset'],
         ['dash','Build a dashboard (try a template)'],['publish','Publish it for your team'],
         ['team','Invite a teammate']].map(([k,txt])=>
        `<div class="${done[k]?'done':''}">${done[k]?'✓':'○'} ${txt}</div>`).join('')}
    </div></div>
    <div class="card"><h3>Workspaces</h3>
      <p class="muted" style="margin:.4rem 0 .6rem">Each workspace holds one project's sources, datasets and dashboards together.</p>
      ${S.wsList.map(w=>`<div class="row between" style="padding:.3rem 0">
        <span>📁 ${esc(w.name)}</span>
        <button class="btn-ghost btn-sm" onclick="setWorkspace('${w.id}')">Open</button></div>`).join('')}
      <button class="btn-ghost btn-sm" style="margin-top:.5rem" onclick="openWorkspaces()">+ New workspace</button>
    </div>
  </div>`}
/* ---- guided tour ---- */
const TOUR=[
 ['#nav-sources','Connect your data','Pick from 19 platform tiles — live databases like PostgreSQL, MySQL, Supabase or Neon, or SaaS demos like Stripe. CSV/Excel upload lives here too.'],
 ['#nav-datasets','Trust every number','Each import is typed, quality-scored and quarantined. Open a dataset to clean it with recipes and watch quality climb.'],
 ['#nav-dashboards','Build without SQL','Drag widgets, use templates, add governed formulas, filter by clicking charts, and drill to underlying rows.'],
 ['#ws-switch','Organise by project','Workspaces keep one project\'s documents together. Switch here, or create one per client, team or initiative.'],
 ['#nav-billing','Grow when ready','Plans meter datasets, members and sync frequency. Upgrade takes effect instantly.'],
];
let TSTEP=0;
function startTour(manual){TSTEP=0;sessionStorage.setItem('if_toured','1');
  $('#tour').classList.add('on');tourStep()}
function tourStep(){
  const [sel,title,body]=TOUR[TSTEP];
  const el=$(sel);if(!el){endTour();return}
  const r=el.getBoundingClientRect(),pad=6;
  const spot=$('#tour-spot');
  spot.style.cssText=`left:${r.left-pad}px;top:${r.top-pad}px;width:${r.width+pad*2}px;height:${r.height+pad*2}px`;
  const b=$('#tour-bubble');
  b.innerHTML=`<h4>${title}</h4><p>${body}</p>
    <div class="row between"><span class="muted">${TSTEP+1} / ${TOUR.length}</span>
    <span class="row">${TSTEP>0?'<button class="btn-ghost btn-sm" onclick="TSTEP--;tourStep()">Back</button>':''}
    <button class="btn btn-sm" onclick="${TSTEP===TOUR.length-1?'endTour()':'TSTEP++;tourStep()'}">${TSTEP===TOUR.length-1?'Done':'Next'}</button></span></div>`;
  const bx=Math.min(Math.max(r.left,12),window.innerWidth-320);
  const by=r.bottom+14>window.innerHeight-180?r.top-170:r.bottom+14;
  b.style.cssText=`left:${bx}px;top:${by}px`}
function endTour(){$('#tour').classList.remove('on')}
