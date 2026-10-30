'use strict';
const ALLERGENS = ['peanuts','tree nuts','dairy','gluten','soy','egg','shellfish','fish','sesame'];
const DIETS = ['vegetarian','vegan','keto','low carb','low sodium','diabetic'];
const RETAILERS = ['Walmart','Publix','Instacart'];
// Public search pages only. No logins, carts or orders: each link just opens that store's own search in a new tab.
const STORES = {
  Walmart:   q => 'https://www.walmart.com/search?q=' + encodeURIComponent(q),
  Publix:    q => 'https://www.publix.com/search?searchTerm=' + encodeURIComponent(q),
  Instacart: q => 'https://www.instacart.com/store/s?k=' + encodeURIComponent(q)
};
function storeOrder(){ return [S.retailer, ...RETAILERS].filter((r,i,a)=>r && STORES[r] && a.indexOf(r)===i); }
function storeLinks(name){ return storeOrder().map(r=>`<a class="find" href="${esc(STORES[r](name))}" target="_blank" rel="noopener noreferrer">${esc(r)}</a>`).join(''); }
function listText(shop){
  const secs=[['need_soon','Need soon'],['running_low','Running low'],['recommended','Recommended']];
  return secs.filter(([k])=>shop[k].length).map(([k,l])=>l+':\n'+shop[k].map(x=>'- '+x.name).join('\n')).join('\n\n');
}
const IS_IOS = /iPhone|iPad|iPod/i.test(navigator.userAgent) || (navigator.platform==='MacIntel' && navigator.maxTouchPoints>1);
function mailtoHref(t){ return 'mailto:?subject=' + encodeURIComponent('Shopping list') + '&body=' + encodeURIComponent(t); }
function smsHref(t){ return 'sms:' + (IS_IOS ? '&' : '?') + 'body=' + encodeURIComponent(t); }
async function copyText(t){
  try { await navigator.clipboard.writeText(t); return true; } catch(e){}
  try { const a=document.createElement('textarea'); a.value=t; a.style.position='fixed'; a.style.opacity='0'; document.body.appendChild(a); a.select(); const ok=document.execCommand('copy'); a.remove(); return ok; } catch(e){ return false; }
}
const VERIFY = 'Ingredient checks use general food knowledge, not product labels. Always verify labels and packaging yourself. Brands, "may contain" warnings and cross-contact are things I can\'t see.';
const KEY = 'kitchenos.v1';
const $ = (s, r=document) => r.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function todayStr(){ const d=new Date(); return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0'); }

let S = load();
let ui = { tab:'tonight', step:1, wizard:false, tonight:null, week:null, shop:null, chat:[], photos:{}, busy:false, results:null, budget:null, ms:null, showKitchen:false, kitchen:null, explain:null, receipt:null, cooked:null };

function load(){ try { const s = JSON.parse(localStorage.getItem(KEY)); if (s && s.v===1) return s; } catch(e){} return {v:1, setup_done:false, members:[], retailer:null, items:[], use_up:{}, shopping:[], history:[], week_locks:{}, rejected:{}, dismissed:{}, last_photo:null}; }
function save(){ try { localStorage.setItem(KEY, JSON.stringify(S)); } catch(e){ toast('Storage is full - older data may not save'); } }
function setState(s){ if (s) { S = s; save(); } }

async function api(path, body={}){
  const r = await fetch('/api/'+path, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({state:S, today:todayStr(), ...body})});
  if (!r.ok) { let m='Something went wrong'; try { m=(await r.json()).detail||m; } catch(e){} throw new Error(m); }
  return r.json();
}
function toast(m){ const t=$('#toast'); t.textContent=m; t.classList.add('on'); clearTimeout(toast.t); toast.t=setTimeout(()=>t.classList.remove('on'), 2800); }
function uid(){ return Math.random().toString(36).slice(2,9); }

// ------------------------------------------------------------ shell
function render(){
  const app = $('#app');
  if (!S.setup_done || ui.wizard) { app.innerHTML = wizardHTML(); bindWizard(); return; }
  const tabs = [['tonight','🍽️','Tonight'],['week','📅','This Week'],['shopping','🛒','Shopping'],['assistant','💬','Assistant']];
  app.innerHTML = `<header class="top"><img src="/icon-180.png" alt=""><h1>Kitchen OS</h1><button id="gear" aria-label="Settings">⚙︎</button></header>
    <main id="main"></main>
    <nav class="tabs">${tabs.map(t=>`<button data-tab="${t[0]}" class="${ui.tab===t[0]?'on':''}"><span class="i">${t[1]}</span>${t[2]}</button>`).join('')}</nav>`;
  app.querySelectorAll('nav.tabs button').forEach(b => b.onclick = () => go(b.dataset.tab));
  $('#gear').onclick = openMenu;
  ({tonight:viewTonight, week:viewWeek, shopping:viewShop, assistant:viewAssistant})[ui.tab]();
}
function go(tab){ ui.tab=tab; ui.explain=null; ui.cooked=null; render(); window.scrollTo(0,0); }

function openMenu(){
  sheet(`<h2 style="font-size:20px">Settings</h2>
    <button class="b" style="width:100%;margin:6px 0" id="m1">Edit household &amp; allergies</button>
    <button class="b" style="width:100%;margin:6px 0" id="m2">Update kitchen photos</button>
    <button class="b" style="width:100%;margin:6px 0" id="m3">Usual store (for shopping links)</button>
    <a class="b" href="/guide" style="display:block;text-align:center;text-decoration:none;width:100%;margin:6px 0">Guide &amp; save to home screen</a>
    <button class="b" style="width:100%;margin:6px 0;color:#a00" id="m4">Reset everything</button>
    <p class="tiny">Your kitchen picture is stored on this phone. Photos are analyzed and then discarded; nothing is kept on the server.</p>`);
  $('#m1').onclick=()=>{closeSheet(); ui.wizard=true; ui.step=1; render();};
  $('#m2').onclick=()=>{closeSheet(); ui.wizard=true; ui.step=3; render();};
  $('#m3').onclick=()=>{closeSheet(); ui.wizard=true; ui.step=4; render();};
  $('#m4').onclick=()=>{ if (confirm('Erase everything on this phone and start over?')) { localStorage.removeItem(KEY); S=load(); ui={...ui,tab:'tonight',step:1,wizard:false,tonight:null,week:null,shop:null,chat:[],photos:{},results:null}; closeSheet(); render(); } };
}
function sheet(html){ const s=$('#sheet'); s.innerHTML=`<div class="panel">${html}</div>`; s.classList.remove('hidden'); s.onclick=e=>{ if(e.target===s) closeSheet(); }; }
function closeSheet(){ $('#sheet').classList.add('hidden'); }

// ----------------------------------------------------------- wizard
function wizardHTML(){
  const st = ui.step;
  const head = `<header class="top"><img src="/icon-180.png" alt=""><h1>Kitchen OS</h1><a href="/guide" style="font-size:14px;color:var(--mute)">Guide</a></header><main>`;
  if (st===1) {
    if (!S.members.length) S.members.push({id:uid(), name:'', kid:false, allergies:[], diets:[]});
    return head + `<div class="step">STEP 1 OF 4</div><h2>Who are we preparing for?</h2><p class="sub">Just first names. This is how I check dinner against everyone.</p>
      ${S.members.map((m,i)=>`<div class="member"><input type="text" data-n="${i}" placeholder="Name" value="${esc(m.name)}" maxlength="24">
        <div class="chips" style="margin-top:10px"><button class="chip ${m.kid?'on':''}" data-kid="${i}">Child</button>${S.members.length>1?`<button class="chip" data-del="${i}">Remove</button>`:''}</div></div>`).join('')}
      <button class="link" id="addm">+ Add another person</button>
      <button class="b primary" style="width:100%;margin-top:10px" id="next1">Next</button></main>`;
  }
  if (st===2) return head + `<div class="step">STEP 2 OF 4</div><h2>Allergies &amp; diets</h2><p class="sub">Tap anything that applies. Skip it if nothing does.</p>
      ${S.members.map((m,i)=>`<div class="member"><b>${esc(m.name||'Person '+(i+1))}</b>
        <h3 style="margin:10px 0 6px">Allergies</h3><div class="chips">${ALLERGENS.map(a=>`<button class="chip ${m.allergies.includes(a)?'on':''}" data-a="${i}|${a}">${a}</button>`).join('')}</div>
        <h3 style="margin:12px 0 6px">Diets</h3><div class="chips">${DIETS.map(a=>`<button class="chip ${m.diets.includes(a)?'on':''}" data-d="${i}|${a}">${a}</button>`).join('')}</div></div>`).join('')}
      <div class="verify">I'll always check dinner against this list, but I can never promise something is safe. You'll always be reminded to verify labels.</div>
      <div class="btns"><button class="b" id="back">Back</button><button class="b primary" style="grid-column:auto;font-size:16px" id="next2">Next</button></div></main>`;
  if (st===3) {
    const kinds=[['fridge','🧊','Fridge'],['freezer','❄️','Freezer'],['pantry','🥫','Pantry']];
    const n = Object.keys(ui.photos).length;
    const res = ui.results;
    return head + `<div class="step">STEP 3 OF 4</div><h2>Three quick photos</h2><p class="sub">Fridge, freezer, pantry. Doors open, nothing staged. Missing a spot? No problem, I'll work with a rough picture.</p>
      ${kinds.map(([k,ic,l])=>`<div class="photo ${ui.photos[k]?'done':''}"><div class="th" style="${ui.photos[k]?`background-image:url(${ui.photos[k]})`:''}">${ui.photos[k]?'':ic}</div>
        <label>${l}<small>${ui.photos[k]?'Got it - tap to retake':'Take or choose a photo'}</small><input type="file" accept="image/*" data-k="${k}"></label></div>`).join('')}
      ${ui.busy ? `<button class="b primary" style="width:100%" disabled><span class="spin"></span>Reading your photos...</button><p class="tiny" style="text-align:center">This takes 10-20 seconds.</p>` :
        `<button class="b primary" style="width:100%" id="analyze" ${n?'':'disabled'}>Analyze ${n||''} photo${n===1?'':'s'}</button>`}
      ${res ? resultsHTML(res) : ''}
      <button class="link" id="sample">No photos handy? Try a sample kitchen</button>
      <div class="btns"><button class="b" id="back">Back</button><button class="b" id="next3">${(S.items.length)?'Next':'Skip for now'}</button></div></main>`;
  }
  if (st===4) return head + `<div class="step">STEP 4 OF 4 · OPTIONAL</div><h2>Your usual store</h2><p class="sub">Kitchen OS doesn't log in to stores, build carts or place orders. In the Shopping tab, each item gets a "Find it" link that opens a search for it on Walmart, Publix or Instacart, in a new tab. Pick your usual store and its link goes first.</p>
      <div class="chips">${RETAILERS.map(r=>`<button class="chip ${S.retailer===r?'on':''}" data-r="${esc(r)}">${esc(r)}</button>`).join('')}</div>
      <div class="btns"><button class="b" id="back">Back</button><button class="b primary" style="grid-column:auto;font-size:16px" id="finish">${S.retailer?'Finish':'Skip &amp; finish'}</button></div></main>`;
}
function resultsHTML(res){
  return `<div class="card"><b>What I found</b>${res.map(r=>`<div style="margin-top:8px"><span class="pill">${esc(r.kind)}</span> ${r.ok?`<span class="tiny">${r.items.length} items${r.unknown_count?`, ${r.unknown_count} I couldn't identify`:''}</span>
      <div class="chips" style="margin-top:6px">${r.items.map(i=>`<span class="chip sm">${esc(i.name)} · ${i.confidence}%</span>`).join('')}</div>${r.note?`<p class="tiny">${esc(r.note)}</p>`:''}`:`<span class="tiny" style="color:#a00">${esc(r.error)}</span>`}</div>`).join('')}
    <p class="sub" style="margin-top:12px"><b>What did we miss?</b> Just tell me, e.g. "we also have eggs, rice and chicken thighs".</p>
    <input type="text" id="miss" placeholder="We also have..."><button class="b" style="width:100%;margin-top:8px" id="missgo">Add</button></div>`;
}
function bindWizard(){
  const A = (sel, fn) => document.querySelectorAll(sel).forEach(fn);
  const st = ui.step;
  if ($('#back')) $('#back').onclick = () => { ui.step--; render(); };
  if (st===1) {
    A('[data-n]', i => i.oninput = () => { S.members[+i.dataset.n].name = i.value; save(); });
    A('[data-kid]', b => b.onclick = () => { const m=S.members[+b.dataset.kid]; m.kid=!m.kid; save(); render(); });
    A('[data-del]', b => b.onclick = () => { S.members.splice(+b.dataset.del,1); save(); render(); });
    $('#addm').onclick = () => { S.members.push({id:uid(), name:'', kid:false, allergies:[], diets:[]}); save(); render(); };
    $('#next1').onclick = () => { S.members.forEach((m,i)=>{ if(!m.name.trim()) m.name = i===0?'Me':'Person '+(i+1); }); save(); ui.step=2; render(); };
  }
  if (st===2) {
    const tog = (arr, v) => arr.includes(v) ? arr.splice(arr.indexOf(v),1) : arr.push(v);
    A('[data-a]', b => b.onclick = () => { const [i,a]=b.dataset.a.split('|'); tog(S.members[+i].allergies,a); save(); render(); });
    A('[data-d]', b => b.onclick = () => { const [i,a]=b.dataset.d.split('|'); const m=S.members[+i]; tog(m.diets,a); if(a==='vegan'&&m.diets.includes('vegan')&&!m.diets.includes('vegetarian')) m.diets.push('vegetarian'); save(); render(); });
    $('#next2').onclick = () => { ui.step=3; render(); };
  }
  if (st===3) {
    A('input[type=file]', inp => inp.onchange = async () => { const f=inp.files[0]; if(!f) return; try { ui.photos[inp.dataset.k] = await shrink(f); } catch(e){ toast("Couldn't open that photo"); } render(); });
    if ($('#analyze')) $('#analyze').onclick = analyze;
    $('#sample').onclick = async () => { try { const r=await api('demo'); setState(r.state); toast('Sample kitchen loaded (not your real one)'); S.setup_done=true; save(); ui.step=4; render(); } catch(e){ toast(e.message); } };
    if ($('#missgo')) $('#missgo').onclick = async () => { const v=$('#miss').value.trim(); if(!v) return; try { const r=await api('assistant',{message: /^(we|i)\b/i.test(v)?v:'we also have '+v}); setState(r.state); $('#miss').value=''; toast((r.changes||[]).join(', ')||r.reply); } catch(e){ toast(e.message); } };
    $('#next3').onclick = () => { ui.step=4; render(); };
  }
  if (st===4) {
    A('[data-r]', b => b.onclick = async () => { S.retailer = S.retailer===b.dataset.r ? null : b.dataset.r; save(); render(); });
    $('#finish').onclick = () => { S.setup_done=true; save(); ui.wizard=false; ui.tab='tonight'; ui.tonight=null; ui.week=null; ui.shop=null; render(); };
  }
}
function shrink(file, max=1280){
  return new Promise((res, rej) => {
    const url = URL.createObjectURL(file); const img = new Image();
    img.onload = () => { const sc=Math.min(1, max/Math.max(img.width,img.height)); const c=document.createElement('canvas'); c.width=Math.round(img.width*sc); c.height=Math.round(img.height*sc);
      c.getContext('2d').drawImage(img,0,0,c.width,c.height); URL.revokeObjectURL(url); res(c.toDataURL('image/jpeg',0.78)); };
    img.onerror = () => { URL.revokeObjectURL(url); rej(new Error('bad image')); };
    img.src = url;
  });
}
async function analyze(){
  ui.busy=true; render();
  try {
    const photos = Object.entries(ui.photos).map(([kind,image])=>({kind,image}));
    const r = await api('photos',{photos});
    setState(r.state); ui.results = r.results;
    if (!r.ai) toast('AI vision is off on the server - use "What did we miss?" instead');
    ui.photos = {};
    if (r.results.some(x=>x.ok)) { S.setup_done = S.setup_done; }
  } catch(e){ toast(e.message); ui.results=[{kind:'photos',ok:false,error:e.message+' - you can tell me what you have instead.'}]; }
  ui.busy=false; render();
}

// ----------------------------------------------------------- tonight
async function viewTonight(){
  const m = $('#main');
  const t0 = performance.now();
  if (!ui.tonight) { m.innerHTML = `<h2>Tonight</h2><div class="skel"></div>`; try { const r = await api('tonight'); ui.tonight = r.tonight; ui.ms = Math.round(performance.now()-t0); } catch(e){ m.innerHTML = `<div class="card">Couldn't load: ${esc(e.message)}</div>`; return; } if (ui.tab!=='tonight') return; }
  drawTonight();
}
function drawTonight(){
  const t = ui.tonight, m = $('#main'); if (!m) return;
  const day = t.weekday;
  let h = `<div class="tiny" style="font-weight:700;letter-spacing:.6px">${esc(day.toUpperCase())} · TONIGHT</div>`;
  if (ui.cooked) { h += `<div class="card hero"><div class="name">Nice - ${esc(ui.cooked.name)}</div><p>${esc(ui.cooked.message)}</p><h3>Quick steps</h3><p>${esc(ui.cooked.steps)}</p><button class="b primary" style="width:100%" id="nextidea">What about tomorrow?</button></div>`; m.innerHTML=h; $('#nextidea').onclick=()=>go('week'); return; }
  if (t.stale_days) h += `<div class="stale">My picture of your kitchen is ${t.stale_days} days old. A quick photo in the Assistant tab keeps things accurate.</div>`;
  if (!t.meal) { h += `<div class="card"><h2 style="font-size:22px">I need a little more to go on</h2><p>${esc(t.empty||'')}</p><button class="b primary" style="width:100%" id="toasst">Tell the Assistant</button></div>`; m.innerHTML=h; $('#toasst').onclick=()=>go('assistant'); return; }
  const x = t.meal;
  if (t.nudge) h += `<div class="nudge">❄️ ${esc(t.nudge.text)}</div>`;
  h += `<div class="card hero"><div class="name">${esc(x.name)}</div>
    <div class="meta"><span class="pill">${x.mins} min</span>${x.kid?'<span class="pill g">Kid-friendly</span>':''}<span class="pill">~${x.kitchen_match}% match with my picture</span></div>
    <div class="btns3"><button class="b primary" id="cook">Cook this</button><button class="b" id="alt">Alternate Meal</button><button class="b" id="exp">Explain Choice</button><button class="b" id="addm" ${x.need_to_buy.length?'':'disabled'}>Add Missing Items${x.need_to_buy.length?` (${x.need_to_buy.length})`:''}</button></div>
    ${ui.explain ? `<div class="explain">${ui.explain==='loading'?'<span class="spin d"></span>Thinking it through...':esc(ui.explain.text)}${ui.explain.text?`<p class="tiny">Picked by: waste score ${ui.explain.breakdown.waste}, ${ui.explain.breakdown.coverage} main ingredients on hand, ${ui.explain.breakdown.mins} min · ${ui.explain.source.startsWith('ai')?'explained by AI':'explained by rules (AI unavailable)'}</p>`:''}</div>`:''}
    <h3>Why it was selected</h3><ul class="why">${x.reasons.map(r=>`<li>${esc(r)}</li>`).join('')}</ul>
    <h3>Checked against</h3>${x.checked.map(c=>`<div class="row"><div class="who">✓ ${esc(c.name)}</div><div class="note">${esc(c.note)}</div></div>`).join('')}
    <h3>Need to buy</h3>${x.need_to_buy.length ? x.need_to_buy.map(b=>`<div class="buy"><span>${esc(b.name)}</span><span class="tiny">~$${b.price.toFixed(2)}</span></div>`).join('') : '<p class="sub" style="margin:0">Nothing - I think you have it all.</p>'}
    <div class="verify"><b>Verify labels.</b> ${esc(t.verify_note||VERIFY)}</div>
    </div>
    ${t.use_soon && t.use_soon.length ? `<h3>Probably use soon</h3><div class="chips">${t.use_soon.map(u=>`<span class="chip sm">${esc(u.name)} · ${u.conf}%</span>`).join('')}</div>`:''}
    <p class="tiny" style="margin-top:14px">Decided in ${(ui.ms||0)<100?'under a tenth of a second':((ui.ms||0)/1000).toFixed(1)+'s'} · ${t.alternates_left} other ideas ready</p>`;
  m.innerHTML = h;
  $('#cook').onclick = async () => { try { const r=await api('tonight/action',{action:'cook',meal_id:x.id}); setState(r.state); ui.cooked={name:x.name,message:r.message,steps:x.steps}; ui.tonight=null; ui.week=null; ui.shop=null; drawTonight(); } catch(e){ toast(e.message); } };
  $('#alt').onclick = async () => { const t0=performance.now(); try { const r=await api('tonight/action',{action:'alternate',meal_id:x.id}); setState(r.state); ui.tonight=r.tonight; ui.explain=null; ui.ms=Math.round(performance.now()-t0); ui.week=null; drawTonight(); window.scrollTo(0,0);} catch(e){ toast(e.message); } };
  $('#exp').onclick = async () => { ui.explain='loading'; drawTonight(); try { ui.explain = await api('explain',{meal_id:x.id}); } catch(e){ ui.explain={text:'Could not explain right now.',breakdown:x.breakdown,source:'rules'}; } drawTonight(); };
  $('#addm').onclick = async () => { try { const r=await api('tonight/action',{action:'add_missing',meal_id:x.id}); setState(r.state); ui.shop=null; toast(r.added.length?('Added to Shopping: '+r.added.join(', ')):'Already on your list'); } catch(e){ toast(e.message); } };
}

// -------------------------------------------------------------- week
async function viewWeek(){
  const m=$('#main');
  if (!ui.week) { m.innerHTML=`<h2>This Week</h2><div class="skel"></div>`; try { ui.week = await api('week',{budget:ui.budget}); } catch(e){ m.innerHTML=`<div class="card">${esc(e.message)}</div>`; return; } if (ui.tab!=='week') return; }
  const w=ui.week;
  m.innerHTML = `<h2>This Week</h2><p class="sub">A rolling plan that updates as your kitchen changes. Tap a day to swap.</p>
    ${w.plan.map((p,i)=>`<div class="day" data-i="${i}"><div class="d">${p.short}</div><div class="m"><b>${esc(p.name)}</b><small>${p.mins} min${p.uses_soon.length?' · uses '+esc(p.uses_soon.join(', ').toLowerCase())+' soon':''}${p.missing.length?' · need '+esc(p.missing.join(', ').toLowerCase()):''}${p.thaw.length?' · thaw '+esc(p.thaw.join(', '))+' the night before':''}</small></div>${p.locked?'<span>📌</span>':'<span style="color:var(--mute)">›</span>'}</div>`).join('')}
    <p class="tiny">${w.budget?`Budget $${w.budget}: groceries I'd still need ≈ $${w.est_shopping_cost.toFixed(0)} (${w.within_budget?'within':'over'}). `:`Groceries I'd still need ≈ $${w.est_shopping_cost.toFixed(0)}. `}Prices are rough guesses.</p>`;
  m.querySelectorAll('.day').forEach(d => d.onclick = async () => {
    const p=w.plan[+d.dataset.i];
    sheet(`<h2 style="font-size:20px">${esc(p.weekday)}</h2><p class="sub">Pick something else:</p><div id="alts"><span class="spin d"></span>Looking...</div>`);
    try { const r = await api('week/alternatives',{date:p.date}); $('#alts').innerHTML = r.alternatives.map(a=>`<div class="item" data-id="${a.meal_id}"><div class="t"><b>${esc(a.name)}</b><small>${a.mins} min${a.missing.length?' · need '+esc(a.missing.join(', ').toLowerCase()):''}</small></div><button>Use</button></div>`).join('') || '<p>No other good fits yet.</p>';
      document.querySelectorAll('#alts .item').forEach(it => it.onclick = async () => { const r2 = await api('week/lock',{date:p.date, meal_id:it.dataset.id}); setState(r2.state); ui.week=r2.week; ui.tonight=null; ui.shop=null; closeSheet(); viewWeek(); toast('Swapped'); });
    } catch(e){ $('#alts').textContent = e.message; }
  });
}

// ---------------------------------------------------------- shopping
async function viewShop(){
  const m=$('#main');
  if (!ui.shop) { m.innerHTML=`<h2>Shopping</h2><div class="skel"></div>`; try { ui.shop = (await api('shopping')).shopping; } catch(e){ m.innerHTML=`<div class="card">${esc(e.message)}</div>`; return; } if (ui.tab!=='shopping') return; }
  const sec=[['need_soon','Need soon'],['running_low','Running low'],['recommended','Recommended']];
  const total = ui.shop.need_soon.reduce((a,x)=>a+(x.price||0),0);
  m.innerHTML = `<h2>Shopping</h2><p class="sub">Built automatically from what dinner needs and what's probably running out. These are guesses, not a count.</p>
    ${sec.map(([k,l])=>`<h3>${l}</h3>${ui.shop[k].length?ui.shop[k].map((x,i)=>`<div class="item"><div class="t"><b>${esc(x.name)}</b><small>${esc(x.why)}${x.price?` · ~$${x.price.toFixed(2)}`:''}</small></div><button data-bought="${k}|${i}">Got it</button><button class="x" data-dis="${k}|${i}" aria-label="Not needed">✕</button><div class="finds"><span>Find it:</span>${storeLinks(x.name)}</div></div>`).join(''):'<p class="tiny">Nothing right now.</p>'}`).join('')}
    <div style="display:flex;gap:8px;margin-top:14px"><input type="text" id="newi" placeholder="Add something (e.g. paper towels)"><button class="b" id="addi" style="padding:0 16px">Add</button></div>
    <div class="sendrow"><button class="b primary" id="copy">Copy list</button><a class="b" id="mail" href="#">Email list</a><a class="b" id="sms" href="#">Text list</a>${navigator.share?'<button class="b" id="share">Share</button>':''}</div>
    <p class="tiny">Need-soon total ≈ $${total.toFixed(0)} (rough guess). "Find it" opens a search on the store's own site in a new tab. Nothing is ordered and no login is needed.</p>`;
  m.querySelectorAll('[data-bought]').forEach(b=>b.onclick=async()=>{ const [k,i]=b.dataset.bought.split('|'); const r=await api('shopping/bought',{name:ui.shop[k][+i].name}); setState(r.state); ui.shop=r.shopping; ui.tonight=null; ui.week=null; viewShop(); toast('Added to what I think you have'); });
  m.querySelectorAll('[data-dis]').forEach(b=>b.onclick=async()=>{ const [k,i]=b.dataset.dis.split('|'); const r=await api('shopping/dismiss',{name:ui.shop[k][+i].name}); setState(r.state); ui.shop=r.shopping; viewShop(); });
  const add = async () => { const v=$('#newi').value.trim(); if(!v) return; const r=await api('assistant',{message:'add '+v+' to the shopping list'}); setState(r.state); ui.shop=null; viewShop(); };
  $('#addi').onclick=add; $('#newi').onkeydown=e=>{ if(e.key==='Enter') add(); };
  const setLinks=()=>{ const t=listText(ui.shop); $('#mail').href=mailtoHref(t); $('#sms').href=smsHref(t); }; setLinks();
  if ($('#share')) $('#share').onclick=async()=>{ try { await navigator.share({title:'Shopping list', text:listText(ui.shop)}); } catch(e){} };
  $('#copy').onclick=async()=>{ const ok=await copyText(listText(ui.shop)); toast(ok?'Shopping list copied':'Couldn\'t copy - select and copy it manually'); };
}

// ---------------------------------------------------------- assistant
const SUGG = ["What's for dinner?","What expires first?","Make a shopping list","We used all the yogurt","Add milk","Use up spinach","Plan meals under $100 this week","Create kid-friendly meals"];
function viewAssistant(){
  const m=$('#main');
  if (!ui.chat.length) ui.chat.push({role:'bot', text:"Hi! Tell me things like \"we used all the yogurt\", \"add milk\" or \"use up spinach\", or ask what's for dinner. I'll keep my rough picture of your kitchen up to date."});
  m.innerHTML = `<h2>Assistant</h2><div class="chat" id="chat">${ui.chat.map(c=>`<div class="msg ${c.role==='me'?'me':'bot'}">${esc(c.text)}${(c.changes||[]).map(x=>`<span class="ch">✓ ${esc(x)}</span>`).join('')}</div>`).join('')}${ui.thinking?'<div class="msg bot"><span class="spin d"></span>...</div>':''}</div>
    ${ui.chat.length<3?`<div class="chips" style="margin:10px 0">${SUGG.map(s=>`<button class="chip sm" data-s="${esc(s)}">${esc(s)}</button>`).join('')}</div>`:''}
    <div class="chips" style="margin-top:10px"><label class="chip sm" style="cursor:pointer">📷 Photo update<input type="file" accept="image/*" id="pic" style="display:none"></label><button class="chip sm" id="rcpt">🧾 Receipt <span class="mock">DEMO</span></button><button class="chip sm" id="kit">${ui.showKitchen?'Hide':'What I think is in your kitchen'}</button></div>
    ${ui.receipt?receiptHTML():''}${ui.showKitchen?kitchenHTML():''}
    <div style="height:70px"></div>
    <div class="composer"><button id="mic" aria-label="Voice">🎤</button><input type="text" id="msg" placeholder="Say or type anything..." autocomplete="off" enterkeyhint="send"><button class="send" id="send">↑</button></div>`;
  $('#send').onclick=()=>sendMsg(); $('#msg').onkeydown=e=>{ if(e.key==='Enter') sendMsg(); };
  m.querySelectorAll('[data-s]').forEach(b=>b.onclick=()=>sendMsg(b.dataset.s));
  $('#pic').onchange=async e=>{ const f=e.target.files[0]; if(!f) return; ui.chat.push({role:'me',text:'📷 (photo)'}); ui.thinking=true; viewAssistant(); try { const img=await shrink(f); const r=await api('photos',{photos:[{kind:'grocery haul or shelf',image:img}]}); setState(r.state); const res=r.results[0]; ui.chat.push({role:'bot',text: res.ok?`I see ${res.items.length} things: ${res.items.map(i=>i.name+' ('+i.confidence+'%)').join(', ')}. I've updated my picture. Anything I missed?`:res.error}); ui.tonight=null; ui.week=null; ui.shop=null; } catch(err){ ui.chat.push({role:'bot',text:'I could not read that photo ('+err.message+'). Tell me what you bought instead.'}); } ui.thinking=false; viewAssistant(); };
  $('#kit').onclick=async()=>{ ui.showKitchen=!ui.showKitchen; if(ui.showKitchen) ui.kitchen=(await api('kitchen')).items; viewAssistant(); };
  $('#rcpt').onclick=async()=>{ ui.receipt=(await api('receipt')); ui.receipt.items.forEach(i=>i.on=i.confidence>=85); viewAssistant(); };
  if ($('#addrc')) { m.querySelectorAll('[data-rc]').forEach(c=>c.onchange=()=>{ ui.receipt.items[+c.dataset.rc].on=c.checked; }); $('#addrc').onclick=async()=>{ const names=ui.receipt.items.filter(i=>i.on).map(i=>i.name); const r=await api('add',{names,source:'receipt'}); setState(r.state); ui.receipt=null; ui.tonight=null; ui.week=null; ui.shop=null; toast('Added '+names.length+' items'); viewAssistant(); }; }
  const SR = window.SpeechRecognition||window.webkitSpeechRecognition;
  if (!SR) $('#mic').classList.add('hidden'); else $('#mic').onclick=()=>{ const r=new SR(); r.lang='en-US'; r.onresult=e=>{ $('#msg').value=e.results[0][0].transcript; sendMsg(); }; r.onerror=()=>toast('Voice not available - type instead'); try{ r.start(); toast('Listening...'); }catch(e){} };
  const c=$('#chat'); if (c) window.scrollTo(0, document.body.scrollHeight);
}
function receiptHTML(){ return `<div class="card"><b>Receipt (sample)</b> <span class="mock">DEMO</span><p class="tiny">Real receipt scanning isn't built yet. Confident lines are pre-checked, shaky ones need your OK.</p>${ui.receipt.items.map((i,k)=>`<label class="buy"><span><input type="checkbox" data-rc="${k}" ${i.on?'checked':''}> ${esc(i.name)}</span><span class="tiny">${i.confidence}%</span></label>`).join('')}<button class="b" style="width:100%;margin-top:8px" id="addrc">Add checked items</button></div>`; }
function kitchenHTML(){ const k=ui.kitchen||[]; return `<div class="card"><b>What I think is in your kitchen</b><p class="tiny">A rough guess, sorted by what to use first. Not an inventory, and there's nothing here to maintain.</p><div style="overflow-x:auto"><table class="k"><tr><th>Item</th><th>Sure</th><th>Spoil risk</th><th>Gone?</th><th>Amount</th></tr>${k.map(i=>`<tr><td>${esc(i.name)}<br><span class="tiny">${esc(i.location)} · seen ${esc(i.observed)}</span></td><td>${Math.round(i.conf_now*100)}%</td><td><span class="bar"><i style="width:${Math.round(i.spoilage_risk*100)}%"></i></span></td><td>${Math.round(i.consumption_probability*100)}%</td><td>${esc(i.qty_text||'~'+Math.round(i.level*100)+'%')}</td></tr>`).join('')}</table></div></div>`; }
async function sendMsg(text){
  const inp=$('#msg'); const msg=(text||inp.value).trim(); if(!msg) return;
  ui.chat.push({role:'me',text:msg}); ui.thinking=true; viewAssistant();
  try {
    const r = await api('assistant',{message:msg, history:ui.chat.slice(-8).map(c=>({role:c.role==='me'?'user':'assistant',text:c.text}))});
    setState(r.state); ui.chat.push({role:'bot',text:r.reply,changes:r.changes});
    ui.tonight=null; ui.week=null; ui.shop=null; if (r.budget) ui.budget=r.budget;
    if (r.navigate) { ui.thinking=false; ui.tab=r.navigate; render(); toast(r.reply.slice(0,90)); return; }
  } catch(e){ ui.chat.push({role:'bot',text:'Hmm, that didn\'t go through ('+e.message+'). Try again?'}); }
  ui.thinking=false; viewAssistant();
}

if ('serviceWorker' in navigator && location.protocol.startsWith('http')) navigator.serviceWorker.register('/sw.js').catch(()=>{});
render();
