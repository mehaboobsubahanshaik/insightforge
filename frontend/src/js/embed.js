/* Embedded viewer (MVP4 E1): renders a published dashboard from a signed
   embed token. No login, no app chrome — iframe-ready. The token in the URL
   carries the customer filters inside its signature. */
(async function(){
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const token=new URLSearchParams(location.search).get('token');
  const grid=document.getElementById('e-grid');
  if(!token){grid.innerHTML='<div class="ecard">Missing embed token.</div>';return}
  try{
    const r=await fetch(`/api/v1/embed/${encodeURIComponent(token)}/data`);
    if(!r.ok){const e=await r.json().catch(()=>({detail:r.statusText}));
      grid.innerHTML=`<div class="ecard">⚠️ ${esc(e.detail||'Could not load')}</div>`;return}
    const d=await r.json();
    const th=d.theme||{};
    const L={en:{view:'View',powered:'Powered by InsightForge · governed data'},
      es:{view:'Vista',powered:'Con tecnología de InsightForge · datos gobernados'},
      fr:{view:'Vue',powered:'Propulsé par InsightForge · données gouvernées'},
      de:{view:'Ansicht',powered:'Bereitgestellt von InsightForge · kontrollierte Daten'},
      hi:{view:'दृश्य',powered:'InsightForge द्वारा संचालित · शासित डेटा'}};
    const lang=new URLSearchParams(location.search).get('lang')||th.locale||'en';
    const T=L[lang]||L.en;
    document.documentElement.lang=lang;
    if(th.accent)document.documentElement.style.setProperty('--accent',th.accent);
    if(th.background)document.body.style.background=th.background;
    if(th.foreground)document.body.style.color=th.foreground;
    const brand=th.brand_name?th.brand_name+' · ':'';
    document.title=(th.brand_name||'InsightForge')+' — '+d.name;
    const foot=document.querySelector('.efoot span:last-child');
    if(foot)foot.textContent=th.white_label?(th.brand_name||''):T.powered;
    document.getElementById('e-title').textContent=brand+d.name;
    document.getElementById('e-cust').textContent=T.view+': '+(d.customer||'');
    grid.innerHTML=d.widgets.map(w=>{
      if(w.error)return `<div class="ecard">⚠️ ${esc(w.error)}</div>`;
      if(w.type==='kpi')return `<div class="ecard"><div style="font-size:.8rem;color:#888">${esc(w.title||w.formula||'')}</div><div class="ekpi">${Number(w.value??0).toLocaleString()}</div></div>`;
      if(w.groups){const max=Math.max(...w.groups.map(g=>Math.abs(g.value||0)),1);
        return `<div class="ecard"><div style="font-size:.8rem;color:#888;margin-bottom:.4rem">${esc(w.title||w.formula||'')}</div>`+
          w.groups.map(g=>`<div class="ebar"><span style="width:90px;overflow:hidden;text-overflow:ellipsis">${esc(g.group)}</span><i style="width:${Math.round(Math.abs(g.value)/max*130)}px"></i><b>${Number(g.value??0).toLocaleString()}</b></div>`).join('')+`</div>`}
      if(w.rows)return `<div class="ecard" style="overflow:auto;max-height:300px"><table style="font-size:.78rem;border-collapse:collapse">`+
        `<tr>${(w.columns||[]).map(c=>`<th style="text-align:left;padding:.2rem .5rem;border-bottom:1px solid #eee">${esc(c)}</th>`).join('')}</tr>`+
        w.rows.map(row=>`<tr>${(w.columns||[]).map(c=>`<td style="padding:.2rem .5rem">${esc(row[c])}</td>`).join('')}</tr>`).join('')+`</table></div>`;
      return `<div class="ecard">${esc(w.type)}</div>`}).join('');
  }catch(e){grid.innerHTML=`<div class="ecard">⚠️ ${esc(e.message)}</div>`}
})();
