/* Members, activity feed, billing/plans, settings, reports, alerts + app boot.
   Edit here for: roles UX, plan display, MFA, schedules. */
const roleLabel=r=>({tenant_owner:'owner',tenant_admin:'admin'}[r]||r);
async function vMembers(){
  const canAdmin=['tenant_owner','tenant_admin'].includes(S.me.role);
  const members=await api('/members');
  let invites=[];
  if(canAdmin){try{invites=await api('/members/invitations')}catch{}}
  $('#view').innerHTML=`<div class="pagehead"><div><h2>Members</h2>
  <p class="muted">Roles govern what people can build, see and administer.</p></div>
  ${canAdmin?'<button class="btn" onclick="openInvite()">Invite teammate</button>':''}</div>
  <div class="card"><table><thead><tr><th>Name</th><th>Email</th><th>Role</th></tr></thead>
  <tbody>${members.map(m=>`<tr>
    <td><b>${esc(m.display_name)}</b>${m.user_id===S.me.user_id?' <span class="muted">(you)</span>':''}</td>
    <td class="muted">${esc(m.email)}</td>
    <td>${canAdmin&&m.user_id!==S.me.user_id?`<select onchange="setRole('${m.membership_id}',this.value)" style="width:auto;padding:.3rem .5rem">
      ${['tenant_owner','tenant_admin','analyst','viewer'].map(r=>`<option value="${r}" ${r===m.role?'selected':''}>${roleLabel(r)}</option>`).join('')}</select>`
      :`<span class="pill role">${roleLabel(m.role)}</span>`}</td>
  </tr>`).join('')}</tbody></table></div>
  ${invites.filter(i=>!i.accepted).length?`<div class="card" style="margin-top:1rem"><h3>Pending invitations</h3>
  <table style="margin-top:.5rem"><thead><tr><th>Email</th><th>Role</th><th>Expires</th></tr></thead>
  <tbody>${invites.filter(i=>!i.accepted).map(i=>`<tr><td>${esc(i.email)}</td>
    <td><span class="pill role">${roleLabel(i.role)}</span></td><td class="muted">${new Date(i.expires_at).toLocaleDateString()}</td></tr>`).join('')}
  </tbody></table></div>`:''}`}
function openInvite(){
  modal(`<h3>Invite teammate</h3>
  <label>Email</label><input id="in-email" type="email" placeholder="teammate@company.com">
  <label>Role</label><select id="in-role"><option value="analyst">analyst — builds datasets & dashboards</option><option value="viewer">viewer — read-only</option><option value="tenant_admin">admin — manages members & connections</option></select>
  <div class="row" style="justify-content:flex-end;margin-top:1.1rem">
    <button class="btn-ghost" onclick="closeModal()">Cancel</button>
    <button class="btn" onclick="sendInvite()">Send invite</button></div>`)}
async function sendInvite(){
  try{await withLoader(()=>api('/members/invitations',{method:'POST',
    json:{email:$('#in-email').value,role:$('#in-role').value}}));
    closeModal();toast('Invitation sent (dev: token in the outbox .eml)');go('members')}
  catch(e){toast(e.message,true)}}
async function setRole(membershipId,role){
  try{await api(`/members/${membershipId}`,{method:'PATCH',json:{role}});toast('Role updated')}
  catch(e){toast(e.message,true);go('members')}}
async function vActivity(){
  const evts=await api('/audit?limit=100');
  const ICON={'auth':'🔐','tenant':'🏢','dataset':'🗃️','dashboard':'📊','connection':'🔌',
    'workspace':'📁','billing':'💳','alert':'🔔','report':'📧','share':'🔗','member':'👥','invite':'✉️'};
  $('#view').innerHTML=`<div class="pagehead"><div><h2>Activity</h2>
  <p class="muted">The immutable audit trail — every consequential action, who and when.</p></div></div>
  <div class="card">${evts.length===0?'<p class="muted">Nothing yet.</p>':evts.map(e=>{
    const kind=e.action.split('.')[0];
    return `<div class="row" style="padding:.5rem 0;border-bottom:1px solid #EEF2F8;gap:.8rem">
      <span style="font-size:1.1rem">${ICON[kind]||'•'}</span>
      <div style="flex:1"><b class="mono" style="font-size:.8rem">${esc(e.action)}</b>
        <span class="muted" style="font-size:.78rem"> ${esc(e.resource_type||'')}${e.detail&&Object.keys(e.detail).length?' · '+esc(JSON.stringify(e.detail)).slice(0,110):''}</span></div>
      <span class="muted" style="font-size:.74rem;flex:none">${ago(e.at)}</span></div>`}).join('')}</div>`}
async function vBilling(){
  const b=await api('/billing/summary');
  const cur=b.plans.find(p=>p.code===b.plan_code)||b.plans[0];
  const bars=[['Datasets',b.usage.datasets,b.limits.max_datasets],
              ['Dashboards',b.usage.dashboards,b.limits.max_dashboards],
              ['Connections',b.usage.connections,b.limits.max_connections],
              ['Members',b.usage.members,b.limits.max_members]];
  $('#view').innerHTML=`<div class="pagehead"><div><h2>Billing & usage</h2>
  <p class="muted">Metered live. Limits enforced at the API — upgrades apply instantly.</p></div></div>
  <div class="grid two">
    <div class="card"><h3>Usage on <span style="color:var(--primary)">${esc(cur.name)}</span></h3>
      ${bars.map(([label,used,max])=>`<div style="margin-top:.8rem">
        <div class="row between"><span class="muted">${label}</span><span class="mono" style="font-size:.8rem">${used} / ${max??'∞'}</span></div>
        <div class="usage-bar"><i style="width:${max?Math.min(100,used/max*100):3}%${max&&used/max>=.9?';background:var(--red)':''}"></i></div></div>`).join('')}
      <div style="margin-top:.9rem" class="muted">Min sync interval: <b>${b.limits.min_sync_interval_minutes??b.limits.min_sync_minutes??'—'} min</b></div>
      ${b.billing_events.length?`<h3 style="margin-top:1rem">Billing events</h3>
      <table style="margin-top:.4rem"><tbody>${b.billing_events.map(e=>`<tr>
        <td class="mono" style="font-size:.76rem">${esc(e.kind)}</td><td class="num">×${e.count}</td></tr>`).join('')}</tbody></table>`:''}
    </div>
    <div class="card"><h3>Plans</h3>${b.plans.map(p=>`
      <div class="row between" style="padding:.55rem 0;border-bottom:1px solid var(--border)">
        <div><b>${esc(p.name)}</b> <span class="mono" style="color:var(--primary)">$${p.monthly_price_usd}/mo</span>
        <div class="muted" style="font-size:.75rem">${p.limits.max_datasets} datasets · ${p.limits.max_members} members · ${p.limits.max_connections} connections</div></div>
        ${p.code===b.plan_code?'<span class="pill published">current</span>'
          :`<button class="btn-ghost btn-sm" onclick="changePlan('${p.code}')">${p.monthly_price_usd>cur.monthly_price_usd?'Upgrade':'Downgrade'}</button>`}
      </div>`).join('')}
      <p class="muted" style="margin-top:.6rem;font-size:.75rem">Plan changes emit billing events (see Activity) — invoicing integration attaches there.</p>
    </div>
  </div>`}
async function changePlan(code){
  try{await withLoader(()=>api('/billing/plan',{method:'POST',json:{plan_code:code}}));
    S.tenant=await api('/tenants/current');
    $('#chip').innerHTML=`<b>${esc(S.tenant.slug)}</b> · ${esc(S.tenant.plan_code)} plan`;
    toast('Plan changed');go('billing')}
  catch(e){toast(e.message,true)}}
async function vSettings(){
  const me=S.me;
  $('#view').innerHTML=`<div class="pagehead"><div><h2>Settings</h2></div></div>
  <div class="grid two">
    <div class="card"><h3>Profile</h3>
      <label>Name</label><input value="${esc(me.display_name)}" disabled>
      <label>Email ${me.email_verified?'<span class="pill published" style="margin-left:.3rem">verified</span>':''}</label>
      <input value="${esc(me.email)}" disabled>
      <label>Role</label><input value="${roleLabel(me.role)}" disabled>
      <hr style="border:none;border-top:1px solid var(--border);margin:1rem 0">
      <h3>Multi-factor authentication</h3>
      <p class="muted" style="margin:.3rem 0 .6rem">Status: ${me.mfa_enabled?'<span class="pill published">enabled</span>':'<span class="pill draft">disabled</span>'}</p>
      ${me.mfa_enabled?`<p class="muted" style="font-size:.78rem">MFA protects this account on every login. If you lose your authenticator, sign in with a recovery code instead of the 6-digit code.</p>
        <button class="btn-ghost btn-sm" onclick="regenRecovery()">Regenerate recovery codes</button>`
        :`<button class="btn" onclick="enrollMfa()">Enable MFA</button>`}
    </div>
    <div class="card"><h3>Organization</h3>
      <label>Name</label><input value="${esc(S.tenant.name)}" disabled>
      <label>Slug</label><input value="${esc(S.tenant.slug)}" disabled>
      <label>Plan</label><input value="${esc(S.tenant.plan_code)}" disabled>
      <hr style="border:none;border-top:1px solid var(--border);margin:1rem 0">
      <h3>Scheduled reports & alerts</h3>
      <p class="muted" style="margin:.3rem 0 .6rem">Email digests of published dashboards, and formula-based threshold alerts on any dataset.</p>
      <div class="row"><button class="btn-ghost btn-sm" onclick="openReports()">Manage reports</button>
      <button class="btn-ghost btn-sm" onclick="openAlerts()">Manage alerts</button></div>
    </div>
  </div>`}
async function enrollMfa(){
  try{const d=await withLoader(()=>api('/auth/mfa/setup',{method:'POST'}));
    modal(`<h3>Enable MFA</h3>
    <p class="muted" style="margin:.3rem 0 .6rem">Add this secret to your authenticator app (or scan the otpauth URI), then confirm with a code.</p>
    <label>Secret</label><input class="mono" value="${d.secret}" readonly onclick="this.select()">
    <label>otpauth URI</label><input class="mono" value="${esc(d.otpauth_uri)}" readonly onclick="this.select()" style="font-size:.68rem">
    <label>Code from app</label><input id="mfa-code" inputmode="numeric">
    <div class="row" style="justify-content:flex-end;margin-top:1rem">
      <button class="btn-ghost" onclick="closeModal()">Cancel</button>
      <button class="btn" onclick="confirmMfa()">Confirm</button></div>`)}
  catch(e){toast(e.message,true)}}
async function confirmMfa(){
  try{const d=await api('/auth/mfa/enable',{method:'POST',json:{otp:$('#mfa-code').value}});
    S.me=await api('/auth/me');showRecoveryCodes(d.recovery_codes,'MFA enabled');go('settings')}
  catch(e){toast(e.message,true)}}
function showRecoveryCodes(codes,title){
  modal(`<h3>${title} — save your recovery codes</h3>
  <p class="muted" style="margin:.3rem 0 .6rem">Each code signs you in <b>once</b> if you lose your
  authenticator. They are shown <b>only now</b> — store them in your password manager.</p>
  <div class="mono" style="columns:2;padding:.6rem;border:1px solid var(--border);border-radius:8px;font-size:.85rem;line-height:1.7">
    ${codes.map(c=>`<div>${c}</div>`).join('')}</div>
  <div class="row" style="justify-content:flex-end;margin-top:1rem;gap:.5rem">
    <button class="btn-ghost" onclick="navigator.clipboard.writeText('${codes.join('\\n')}').then(()=>toast('Copied'))">Copy all</button>
    <button class="btn" onclick="closeModal()">I saved them</button></div>`)}
async function regenRecovery(){
  const pw=prompt('Confirm your account password to replace ALL recovery codes:');
  if(!pw)return;
  try{const d=await withLoader(()=>api('/auth/mfa/recovery-codes',{method:'POST',json:{password:pw}}));
    showRecoveryCodes(d.recovery_codes,'New recovery codes')}
  catch(e){toast(e.message,true)}}
/* ---- scheduled reports: per published dashboard ---- */
async function openReports(){
  const dbs=(await api('/dashboards')).filter(d=>d.published_version);
  if(!dbs.length){toast('Publish a dashboard first — reports send the published snapshot',true);return}
  modal(`<h3>📧 Scheduled reports</h3>
  <label>Dashboard (published only)</label>
  <select id="rp-db" onchange="loadReports()">${dbs.map(d=>`<option value="${d.id}">${esc(d.name)}</option>`).join('')}</select>
  <div id="rp-list" style="margin-top:.6rem"><p class="muted">Loading…</p></div>
  <hr style="border:none;border-top:1px solid var(--border);margin:1rem 0">
  <label>Cadence</label><select id="rp-int"><option value="1440">Daily</option><option value="10080">Weekly</option><option value="60">Hourly</option></select>
  <label>Recipients (comma-separated)</label><input id="rp-to" placeholder="ceo@company.com, coo@company.com">
  <div class="row" style="justify-content:flex-end;margin-top:1rem">
    <button class="btn-ghost" onclick="closeModal()">Close</button>
    <button class="btn" onclick="addReport()">Schedule</button></div>`);
  loadReports()}
async function loadReports(){
  const id=$('#rp-db').value;
  const scheds=await api(`/dashboards/${id}/report-schedules`);
  $('#rp-list').innerHTML=scheds.length?`<table><thead><tr><th>Every</th><th>Recipients</th><th>Last</th><th>Enabled</th></tr></thead>
  <tbody>${scheds.map(s=>`<tr><td>${s.interval_minutes>=1440?(s.interval_minutes/1440)+'d':(s.interval_minutes/60)+'h'}</td>
    <td class="muted" style="font-size:.78rem">${esc(s.recipients.join(', '))}</td>
    <td>${s.last_status?`<span class="pill ${s.last_status==='sent'?'published':'failing'}">${s.last_status}</span>`:'<span class="muted">—</span>'}</td>
    <td><button class="btn-ghost btn-sm" onclick="toggleReport('${s.id}',${!s.enabled})">${s.enabled?'On → pause':'Paused → resume'}</button></td></tr>`).join('')}</tbody></table>`
  :'<p class="muted">No schedules for this dashboard yet.</p>'}
async function addReport(){
  try{await withLoader(()=>api(`/dashboards/${$('#rp-db').value}/report-schedules`,{method:'POST',json:{
    interval_minutes:Number($('#rp-int').value),
    recipients:$('#rp-to').value.split(',').map(s=>s.trim()).filter(Boolean)}}));
    toast('Report scheduled — PDF lands by email each cycle');loadReports()}
  catch(e){toast(e.message,true)}}
async function toggleReport(id,enabled){
  try{await api(`/report-schedules/${id}`,{method:'PATCH',json:{enabled}});loadReports()}
  catch(e){toast(e.message,true)}}
/* ---- threshold alerts: per dataset, governed formulas ---- */
async function openAlerts(){
  const ds=await api('/datasets');
  if(!ds.length){toast('Land a dataset first',true);return}
  window._alDs=ds;
  modal(`<h3>🔔 Threshold alerts</h3>
  <label>Dataset</label>
  <select id="al-ds" onchange="loadAlerts()">${ds.map(d=>`<option value="${d.id}">${esc(d.name)}</option>`).join('')}</select>
  <div id="al-list" style="margin-top:.6rem"><p class="muted">Loading…</p></div>
  <hr style="border:none;border-top:1px solid var(--border);margin:1rem 0">
  <label>Name</label><input id="al-name" placeholder="e.g. Revenue floor">
  <label>Governed formula</label><input id="al-formula" class="mono" placeholder="e.g. sum(total)">
  <div class="row"><div style="flex:1"><label>Condition</label>
    <select id="al-op"><option value="lt">&lt; below</option><option value="lte">≤ at or below</option>
    <option value="gt">&gt; above</option><option value="gte">≥ at or above</option></select></div>
  <div style="flex:1"><label>Threshold</label><input id="al-thr" type="number" step="any"></div>
  <div style="flex:1"><label>Check every</label><select id="al-int"><option value="60">Hour</option><option value="1440">Day</option><option value="15">15 min</option></select></div></div>
  <label>Notify (comma-separated emails)</label><input id="al-to" placeholder="ops@company.com">
  <div class="row" style="justify-content:flex-end;margin-top:1rem">
    <button class="btn-ghost" onclick="closeModal()">Close</button>
    <button class="btn" onclick="addAlert()">Create alert</button></div>`);
  loadAlerts()}
async function loadAlerts(){
  const id=$('#al-ds').value;
  const rules=await api(`/datasets/${id}/alerts`);
  const ds=(window._alDs||[]).find(d=>d.id===id);
  const nums=(ds?.schema||[]).filter(c=>['number','integer'].includes(c.inferred_type)).map(c=>c.name);
  if(!$('#al-formula').value&&nums.length)$('#al-formula').value=`sum(${nums[0]})`;
  $('#al-list').innerHTML=rules.length?`<table><thead><tr><th>Name</th><th>Condition</th><th>State</th><th>Enabled</th></tr></thead>
  <tbody>${rules.map(r=>`<tr><td>${esc(r.name)}</td>
    <td class="mono" style="font-size:.75rem">${esc(r.formula)} ${({gt:'>',gte:'≥',lt:'<',lte:'≤'})[r.operator]} ${fmtN(r.threshold)}</td>
    <td><span class="pill ${r.last_state==='triggered'?'failing':'published'}">${r.last_state||'ok'}</span></td>
    <td><button class="btn-ghost btn-sm" onclick="toggleAlert('${id}','${r.id}',${!r.enabled})">${r.enabled?'On → pause':'Paused → resume'}</button></td></tr>`).join('')}</tbody></table>`
  :'<p class="muted">No alerts on this dataset yet.</p>'}
async function addAlert(){
  try{await withLoader(()=>api(`/datasets/${$('#al-ds').value}/alerts`,{method:'POST',json:{
    name:$('#al-name').value.trim()||'Alert',formula:$('#al-formula').value.trim(),
    operator:$('#al-op').value,threshold:Number($('#al-thr').value),
    interval_minutes:Number($('#al-int').value),
    recipients:$('#al-to').value.split(',').map(s=>s.trim()).filter(Boolean)}}));
    toast('Alert armed — evaluated on the scheduler cycle');loadAlerts()}
  catch(e){toast(e.message,true)}}
async function toggleAlert(dsId,id,enabled){
  try{await api(`/datasets/${dsId}/alerts/${id}`,{method:'PATCH',json:{enabled}});loadAlerts()}
  catch(e){toast(e.message,true)}}
/* ---- boot ---- */
(function(){
  const saved=sessionStorage.getItem('if_session');
  if(saved){try{const s=JSON.parse(saved);S.token=s.token;S.refresh=s.refresh;S.ws=s.ws||'all';enter()}catch{}}
})();
