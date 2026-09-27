const $ = (id) => document.getElementById(id);
const appBootstrap = window.SolvAIBootstrap || {};
const currentUser = appBootstrap.user || {display_name:"User",email:"",role:"viewer"};
const currentUserName = String(currentUser.display_name || currentUser.email || "User");
const currentUserInitial = currentUserName.trim().charAt(0).toUpperCase() || "U";
const appState = window.SolvAI = window.SolvAI || {
  version: String(appBootstrap.appVersion || "37.0.0"),
  initialized: false,
  view: "overview",
  requests: new Map(),
  controllers: new Map(),
  responseCache: new Map(),
  companyDirectory: [],
  recentCompanies: [],
  pinnedCompanies: [],
  clientHealth: new Map(),
  eventWorkspaceTab: "history",
  unreadAlerts: 0,
  recentAlerts: []
};
const featureControllers = window.SolvAIControllers = window.SolvAIControllers || Object.create(null);
function runFeatureController(name, fallback, ...args){
  const controller=featureControllers[name];
  return controller&&typeof controller.load==='function'?controller.load(...args):fallback(...args);
}

const workspaceStoragePrefix=`solvai.${String(currentUser.workspace_id||'default')}.${String(currentUser.id||'anonymous')}`;
function workspaceStorageKey(key){return `${workspaceStoragePrefix}.${key}`;}
function readWorkspaceList(key){try{const value=JSON.parse(localStorage.getItem(workspaceStorageKey(key))||'[]');return Array.isArray(value)?value:[];}catch{return [];}}
function saveWorkspaceList(key,value){try{localStorage.setItem(workspaceStorageKey(key),JSON.stringify(value));}catch{}}
appState.recentCompanies=readWorkspaceList('recentCompanies');
appState.pinnedCompanies=readWorkspaceList('pinnedCompanies');
let currentRatioBasis = "latest";
// Declare macro state before any navigation handler is registered. Using `var` here
// also avoids the temporal-dead-zone error seen in older cached bundles.
var macroRefreshInFlight = false;
var epCatalog = null;
var epInitialized = false;

function setPageMeta(view){
  const meta={
    overview:["PERSONAL FINANCIAL INTELLIGENCE",`Welcome back, ${currentUserName}.`,"Your research workspace for verified financial evidence, market context, and decision support."],
    compare:["OVERVIEW","Compare companies","Compare verified financial evidence across the companies in your library."],
    stock:["ANALYTICS","Stock analytics","Review market direction, technical context, and historical trading evidence."],
    indicatorsVsa:["ANALYTICS","Indicators & VSA","Read price, volume, market structure, trap risk, and conditional trade levels together."],
    risk:["ANALYTICS","Investment research","Screen accounting quality, then test long-term value with traceable assumptions."],
    tradePlanner:["ANALYTICS","Trade planner","Define the stop, reward target, and position size without mixing them into company valuation."],
    macro:["ANALYTICS","Macro regime monitor","Track global macro conditions and the Vietnam market in one view."],
    eventProbability:["ANALYTICS","Event scenarios","Rank plausible outcomes by evidence share; probability language appears only after calibration."],
    news:["DATA","Company news","Use current news as market context alongside verified financial evidence."],
    learn:["DATA","Data sources & reports","Manage your research library and keep scanned evidence indexed."],
    portfolio:["DATA","Portfolio risk","Measure concentration, volatility, drawdown, correlation, and portfolio risk contribution."],
    watchlist:["DATA","Watchlist & alerts","Monitor saved valuation thresholds, evidence changes, and account-private history."],
    guardian:["ACCOUNT","Model guardian","Check coverage, consistency, and data-health conditions across your library."],
    systemHealth:["ACCOUNT","Data health","Monitor provider freshness, fallbacks, latency, and research calibration."]
  }[view]||null;
  if(meta){$("pageEyebrow").textContent=meta[0];$("workspaceGreeting").textContent=meta[1];$("workspaceSubtitle").textContent=meta[2];}
}
function setViewStyles(viewName){
  const featureStyles=$("featureStylesheet"),dashboardStyles=$("dashboardStylesheet");
  if(featureStyles)featureStyles.disabled=viewName==="overview";
  // The modern shell belongs to every page. SolvAI11's feature stylesheet is
  // layered underneath it only outside the Dashboard.
  if(dashboardStyles)dashboardStyles.disabled=false;
}
function closeHeaderMenu(){
  const menu=$("headerActionMenu");
  if(menu)menu.hidden=true;
  document.querySelectorAll(".workspace-header-actions [aria-expanded]").forEach(button=>button.setAttribute("aria-expanded","false"));
}
function notificationMenuMarkup(){
  const count=Number(appState.unreadAlerts||0),latest=appState.recentAlerts?.[0];
  return `<div class="header-menu-kicker">SMART ALERTS</div><strong>${count?`${count} unread ${count===1?'alert':'alerts'}`:'You’re up to date'}</strong><p>${latest?`${esc(latest.company)} · ${esc(latest.title)}`:'Watched-company price, valuation, and evidence changes will appear here.'}</p><button type="button" data-action="view" data-view="watchlist">Open watchlist &amp; alerts <span>→</span></button><button type="button" data-action="view" data-view="systemHealth">Open Data Health <span>→</span></button>`;
}
function toggleHeaderMenu(type,trigger){
  const menu=$("headerActionMenu");if(!menu)return;
  if(!menu.hidden&&menu.dataset.menu===type){closeHeaderMenu();return;}
  const content={
    settings:`<div class="header-menu-kicker">WORKSPACE SETTINGS</div><strong>Research workspace</strong><p>Manage reports, evidence quality and provider health from one workspace.</p><button type="button" data-action="view" data-view="learn">Data sources &amp; reports <span>→</span></button><button type="button" data-action="view" data-view="guardian">Model Guardian <span>→</span></button><button type="button" data-action="view" data-view="systemHealth">Data Health <span>→</span></button>`,
    notifications:notificationMenuMarkup(),
    account:`<div class="header-account-row"><span>${esc(currentUserInitial)}</span><div><strong>${esc(currentUserName)}</strong><small>${esc(currentUser.email||'Local research account')}</small></div></div><p>Your reports, scans, and workspace settings stay connected to this protected profile.</p><button type="button" data-action="navigate" data-href="/account/security">Account security <span>→</span></button>${currentUser.role==='admin'?`<button type="button" data-action="navigate" data-href="/admin/users">Access center <span>→</span></button>`:''}<button type="button" data-action="view" data-view="guardian">Review workspace health <span>→</span></button><button type="button" data-action="logout">Sign out <span>→</span></button>`
  }[type];
  if(!content)return;
  document.querySelectorAll(".workspace-header-actions [aria-expanded]").forEach(button=>button.setAttribute("aria-expanded","false"));
  menu.dataset.menu=type;
  menu.innerHTML=content;
  menu.hidden=false;
  trigger?.setAttribute("aria-expanded","true");
}

function keepSidebarSelectionVisible(button,{instant=false}={}){
  const scroller=$("sidebarScrollRegion");
  if(!scroller||!button||window.innerWidth<=620)return;
  const scrollerRect=scroller.getBoundingClientRect(),buttonRect=button.getBoundingClientRect(),padding=12;
  let nextTop=scroller.scrollTop;
  if(buttonRect.top<scrollerRect.top+padding)nextTop-=scrollerRect.top+padding-buttonRect.top;
  else if(buttonRect.bottom>scrollerRect.bottom-padding)nextTop+=buttonRect.bottom-(scrollerRect.bottom-padding);
  nextTop=Math.max(0,nextTop);
  if(Math.abs(nextTop-scroller.scrollTop)>1)scroller.scrollTo({top:nextTop,behavior:instant?'auto':'smooth'});
}

function toggleSidebar(){
  document.body.classList.toggle('sidebar-collapsed');
  window.requestAnimationFrame(()=>keepSidebarSelectionVisible(document.querySelector('.sidebar-scroll-region nav button.active[data-view]'),{instant:true}));
}

function showView(viewName){
  closeHeaderMenu();
  setViewStyles(viewName);
  document.querySelectorAll(".view").forEach(v=>v.classList.remove("active"));
  const view=$(viewName); if(view)view.classList.add("active");
  appState.view=viewName;
  document.body.dataset.activeView=viewName;
  document.querySelectorAll("nav button").forEach(b=>b.classList.toggle("active",b.dataset.view===viewName));
  window.requestAnimationFrame(()=>keepSidebarSelectionVisible(document.querySelector(`.sidebar-scroll-region nav button[data-view="${viewName}"]`)));
  setPageMeta(viewName);
  if(viewName === "overview") {
    loadDashboard();
    window.SolvAIDashboardMacro?.load?.(false);
  }
  if(viewName === "guardian") loadGuardian();
  if(viewName === "macro") loadMacro(false);
  if(viewName === "eventProbability") initEventProbability();
  if(viewName === "indicatorsVsa") initVsaWorkspace();
  if(viewName === "risk") $("risk")?.dispatchEvent(new CustomEvent("risk:opened"));
  if(viewName === "tradePlanner") $("tradePlanner")?.dispatchEvent(new CustomEvent("trade:opened"));
  if(viewName === "systemHealth") loadSystemHealth();
  if(viewName === "watchlist") loadWatchlistWorkspace();
}

function esc(value){return String(value ?? "").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[m]));}
function safeHttpUrl(value){try{const candidate=String(value||'').trim();if(!candidate)return '#';const url=new URL(candidate,window.location.origin);return ['http:','https:'].includes(url.protocol)?url.href:'#';}catch{return '#';}}
function num(value,d=1){if(value===null||value===undefined||Number.isNaN(Number(value)))return "Unavailable";return Number(value).toLocaleString(undefined,{maximumFractionDigits:d});}
function pct(value){return value===null||value===undefined?"Unavailable":`${Number(value).toFixed(1)}%`;}
function money(value){if(value===null||value===undefined)return "Unavailable";const n=Math.abs(Number(value)),s=n>=1e12?`${(Number(value)/1e12).toFixed(2)}T`:n>=1e9?`${(Number(value)/1e9).toFixed(2)}B`:n>=1e6?`${(Number(value)/1e6).toFixed(1)}M`:num(value,0);return s+" VND";}
function metricValue(item){if(item===null||item===undefined)return null;return typeof item === "object" ? item.value : item;}
async function secureFetch(url,options={}){
  const method=String(options.method||'GET').toUpperCase();
  const headers=new Headers(options.headers||{});
  if(!['GET','HEAD','OPTIONS'].includes(method)&&appBootstrap.csrfToken)headers.set('X-CSRF-Token',appBootstrap.csrfToken);
  const response=await window.fetch(url,{...options,headers});
  if(response.status===401&&url!=='/api/auth/login'){
    window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname+window.location.search)}`);
  }
  return response;
}
async function logoutWorkspace(){
  closeHeaderMenu();
  try{await secureFetch('/api/auth/logout',{method:'POST'});}finally{window.location.assign('/login');}
}
async function getJSON(url,options={}){
  const method=String(options.method||'GET').toUpperCase();
  const dedupe=options.dedupe!==false;
  const cacheMs=Math.max(0,Number(options.cacheMs||0));
  const cancelKey=options.cancelKey||null;
  const requestKey=`${method}:${url}:${method==='GET'?'':String(options.body||'')}`;
  const cached=appState.responseCache.get(requestKey);
  if(method==='GET'&&cacheMs&&cached&&Date.now()-cached.at<cacheMs)return cached.data;
  if(dedupe&&appState.requests.has(requestKey))return appState.requests.get(requestKey);
  if(cancelKey&&appState.controllers.has(cancelKey))appState.controllers.get(cancelKey).abort();
  const controller=new AbortController();
  if(cancelKey)appState.controllers.set(cancelKey,controller);
  const fetchOptions={...options,signal:options.signal||controller.signal};
  delete fetchOptions.dedupe;delete fetchOptions.cacheMs;delete fetchOptions.cancelKey;
  const started=performance.now();
  const task=(async()=>{
    try{
      const r=await secureFetch(url,fetchOptions);let data;
      try{data=await r.json();}catch{throw new Error("The server returned an unexpected response. Try restarting the local app.");}
      if(!r.ok||data.success===false&&data.error)throw new Error(data.error||"Request failed.");
      if(method==='GET'&&cacheMs)appState.responseCache.set(requestKey,{at:Date.now(),data});
      appState.clientHealth.set(url.split('?')[0],{status:'healthy',latency_ms:Math.round(performance.now()-started),checked_at:new Date().toISOString()});
      return data;
    }catch(error){
      if(error?.name!=='AbortError')appState.clientHealth.set(url.split('?')[0],{status:'unavailable',latency_ms:Math.round(performance.now()-started),checked_at:new Date().toISOString()});
      throw error;
    }finally{
      appState.requests.delete(requestKey);
      if(cancelKey&&appState.controllers.get(cancelKey)===controller)appState.controllers.delete(cancelKey);
    }
  })();
  if(dedupe)appState.requests.set(requestKey,task);
  return task;
}
function metricCard(label,value,sub=""){const subHtml=sub?(String(sub).includes("<button")?sub:`<div class="data-note">${esc(sub)}</div>`):"";return `<div class="metric"><label>${esc(label)}</label><strong>${esc(value)}</strong>${subHtml}</div>`;}
function renderCompanyList(companies){
  appState.companyDirectory=Array.isArray(companies)?companies:[];
  $("companyList").innerHTML=companies.length?companies.map(c=>`<button type="button" class="company" data-action="open-company" data-company="${esc(c.company)}"><b>${esc(c.company)}</b><small>${esc(c.industry)}</small><span class="data-note">${c.reports} report${c.reports===1?"":"s"}</span></button>`).join(""):"<div class='empty-state'>No reports discovered yet.</div>";
  setupCompanySearch(companies);
}
function companyKey(value){return String(value||'').trim().toUpperCase();}
function recordRecentCompany(company){const key=companyKey(company);if(!key)return;appState.recentCompanies=[key,...appState.recentCompanies.filter(x=>x!==key)].slice(0,6);saveWorkspaceList('recentCompanies',appState.recentCompanies);}
function togglePinnedCompany(company){const key=companyKey(company);appState.pinnedCompanies=appState.pinnedCompanies.includes(key)?appState.pinnedCompanies.filter(x=>x!==key):[key,...appState.pinnedCompanies].slice(0,8);saveWorkspaceList('pinnedCompanies',appState.pinnedCompanies);renderCompanySuggestions($("overviewCompany")?.value||'');}
function companyMatchScore(item,query){
  const q=companyKey(query),name=companyKey(item.company),ticker=companyKey(item.market_ticker).replace('.VN','');
  if(!q)return 0;if(q===name||q===ticker)return 100;if(name.startsWith(q)||ticker.startsWith(q))return 82;if(name.includes(q)||ticker.includes(q))return 64;
  let at=0;for(const ch of q){at=name.indexOf(ch,at);if(at<0)return 0;at+=1;}return 38;
}
function companySuggestionRows(query){
  const q=companyKey(query),byKey=new Map(appState.companyDirectory.map(row=>[companyKey(row.company),row]));
  if(!q){
    const keys=[...appState.pinnedCompanies,...appState.recentCompanies].filter((value,index,rows)=>rows.indexOf(value)===index);
    const selected=keys.map(key=>byKey.get(key)).filter(Boolean);
    return selected.length?selected:appState.companyDirectory.slice(0,6);
  }
  return appState.companyDirectory.map(row=>({...row,_score:companyMatchScore(row,q)})).filter(row=>row._score>0).sort((a,b)=>b._score-a._score||Number(b.reports||0)-Number(a.reports||0)).slice(0,7);
}
let companySuggestionIndex=-1;
function renderCompanySuggestions(query){
  const menu=$("companySearchMenu"),input=$("overviewCompany");if(!menu||!input)return;
  const rows=companySuggestionRows(query);companySuggestionIndex=Math.min(companySuggestionIndex,rows.length-1);
  if(!rows.length){menu.innerHTML=`<button type="button" class="company-search-empty" data-company="${esc(companyKey(query))}"><span>Search for <b>${esc(companyKey(query))}</b></span><small>Use this ticker or company name</small></button>`;menu.hidden=false;input.setAttribute('aria-expanded','true');return;}
  const hasQuery=Boolean(companyKey(query));
  menu.innerHTML=`<div class="company-search-menu-head"><span>${hasQuery?'Best matches':'Pinned and recent'}</span><small>↑↓ navigate · Enter open</small></div>${rows.map((row,index)=>{const key=companyKey(row.company),pinned=appState.pinnedCompanies.includes(key);return `<div class="company-suggestion ${index===companySuggestionIndex?'active':''}" role="option" aria-selected="${index===companySuggestionIndex}" data-company="${esc(key)}"><span class="company-suggestion-mark">${esc(key.slice(0,3))}</span><span class="company-suggestion-copy"><b>${esc(row.company)}</b><small>${esc(row.market_ticker||key)} · ${esc(row.industry||row.exchange||'Local research')}</small></span><button type="button" class="company-pin ${pinned?'active':''}" data-pin="${esc(key)}" aria-label="${pinned?'Unpin':'Pin'} ${esc(key)}" title="${pinned?'Unpin company':'Pin company'}">${pinned?'★':'☆'}</button></div>`;}).join('')}`;
  menu.hidden=false;input.setAttribute('aria-expanded','true');
}
function selectCompanySuggestion(company){const input=$("overviewCompany"),menu=$("companySearchMenu");if(input)input.value=companyKey(company);if(menu)menu.hidden=true;input?.setAttribute('aria-expanded','false');recordRecentCompany(company);loadOverview();}
function setupCompanySearch(companies){
  appState.companyDirectory=Array.isArray(companies)?companies:appState.companyDirectory;
  const input=$("overviewCompany"),menu=$("companySearchMenu");if(!input||!menu||input.dataset.searchReady)return;input.dataset.searchReady='1';input.setAttribute('role','combobox');input.setAttribute('aria-autocomplete','list');input.setAttribute('aria-controls','companySearchMenu');input.setAttribute('aria-expanded','false');
  input.addEventListener('focus',()=>{companySuggestionIndex=-1;renderCompanySuggestions(input.value);});
  input.addEventListener('input',()=>{companySuggestionIndex=-1;renderCompanySuggestions(input.value);});
  input.addEventListener('keydown',event=>{const rows=[...menu.querySelectorAll('[data-company]')];if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();companySuggestionIndex=(companySuggestionIndex+(event.key==='ArrowDown'?1:-1)+rows.length)%Math.max(1,rows.length);renderCompanySuggestions(input.value);}else if(event.key==='Enter'&&!menu.hidden&&companySuggestionIndex>=0&&rows[companySuggestionIndex]){event.preventDefault();selectCompanySuggestion(rows[companySuggestionIndex].dataset.company);}else if(event.key==='Escape'){menu.hidden=true;input.setAttribute('aria-expanded','false');}});
  menu.addEventListener('mousedown',event=>event.preventDefault());
  menu.addEventListener('click',event=>{const pin=event.target.closest('[data-pin]');if(pin){togglePinnedCompany(pin.dataset.pin);return;}const row=event.target.closest('[data-company]');if(row)selectCompanySuggestion(row.dataset.company);});
  input.addEventListener('blur',()=>setTimeout(()=>{menu.hidden=true;input.setAttribute('aria-expanded','false');},120));
}
function openCompany(company){
  $("overviewCompany").value=String(company||"").trim().toUpperCase();
  recordRecentCompany(company);
  document.querySelectorAll(".view").forEach(v=>v.classList.remove("active"));
  $("overview")?.classList.add("active");
  document.querySelectorAll("nav button").forEach(b=>b.classList.toggle("active",b.dataset.view==="overview"));
  setPageMeta("overview");
  loadOverview();
}
function directionUI(direction){return direction==="UP"?{arrow:"↑",cls:"up",text:"Positive evidence"}:direction==="DOWN"?{arrow:"↓",cls:"down",text:"Negative evidence"}:{arrow:"→",cls:"flat",text:direction==="INSUFFICIENT"?"Insufficient evidence":"Mixed evidence"};}
function chartPeriod(x){if(!x)return "";const d=new Date(x);if(Number.isNaN(d.getTime()))return String(x);return `Q${Math.floor(d.getMonth()/3)+1} ${d.getFullYear()}`;}
function lineChart(history,metric,label){const vals=(history[metric]||[]).filter(x=>x.value!==null&&x.value!==undefined);if(vals.length<2)return `<div class="chart-empty">Not enough historical ${esc(label.toLowerCase())} data yet.</div>`;const W=760,H=240,P=38,nums=vals.map(x=>Number(x.value)),min=Math.min(...nums),max=Math.max(...nums),span=max-min||1,pts=vals.map((v,i)=>`${(P+i/(vals.length-1)*(W-2*P)).toFixed(1)},${(H-P-(v.value-min)/span*(H-2*P)).toFixed(1)}`).join(" "),trend=nums.at(-1)>nums[0]?"up":nums.at(-1)<nums[0]?"down":"flat";return `<div class="chart-card"><div class="chart-heading"><b>${esc(label)}</b><span class="${trend}">${trend==="up"?"↑ improving":trend==="down"?"↓ declining":"→ stable"}</span></div><svg class="line-chart" viewBox="0 0 ${W} ${H}"><line x1="${P}" y1="${H-P}" x2="${W-P}" y2="${H-P}" class="axis"/><polyline points="${pts}" class="trend-line"/>${vals.map((v,i)=>{const x=P+i/(vals.length-1)*(W-2*P),y=H-P-(v.value-min)/span*(H-2*P);return `<circle cx="${x}" cy="${y}" r="4" class="trend-point"/>`;}).join("")}</svg><div class="chart-labels"><span>${esc(chartPeriod(vals[0].period_end)||vals[0].year)}</span><span>${esc(chartPeriod(vals.at(-1).period_end)||vals.at(-1).year)}</span></div></div>`;}
function evidencePie(components){const e=Object.entries(components||{}).filter(([,v])=>v!==null&&v!==undefined);if(!e.length)return `<div class="chart-empty">No score components are available yet.</div>`;const total=e.reduce((s,[,v])=>s+Math.max(0,Number(v)),0)||1;let cursor=0;const colors=["#2f6ea8","#3d9b72","#e1a13d","#8d5fbf"];const stops=e.map(([n,v],i)=>{const start=cursor;cursor+=Math.max(0,Number(v))/total*360;return `${colors[i%colors.length]} ${start}deg ${cursor}deg`;}).join(",");return `<div class="pie-wrap"><div class="pie" style="background:conic-gradient(${stops})"></div><div class="legend">${e.map(([n,v],i)=>`<div><span class="dot" style="background:${colors[i%colors.length]}"></span><b>${esc(n)}</b><span>${Math.round(Number(v))}/100</span></div>`).join("")}</div></div>`;}
function metricBars(items){return `<div class="metric-bars">${items.map(([label,value])=>{const n=value===null||value===undefined?null:Number(value);if(n===null||Number.isNaN(n))return `<div class="metric-bar-row"><div class="metric-bar-head"><span>${esc(label)}</span><b>Unavailable</b></div><div class="metric-bar-track"><div class="metric-bar-fill unavailable" style="width:8%"></div></div></div>`;const clipped=Math.max(0,Math.min(100,50+n*2));return `<div class="metric-bar-row"><div class="metric-bar-head"><span>${esc(label)}</span><b>${pct(n)}</b></div><div class="metric-bar-track"><div class="metric-bar-fill" style="width:${clipped}%"></div></div></div>`;}).join("")}</div>`;}
function confidenceGauge(coverage,quality){return `<div class="gauge-wrap"><div class="gauge" style="--value:${Math.max(0,Math.min(100,Math.round((coverage+quality)/2)))}"><div class="gauge-inner"><strong>${Math.round((coverage+quality)/2)}%</strong><span>confidence</span></div></div></div>`;}
function evidenceButton(company,metric,label="Evidence"){return `<button class="evidence-btn" data-action="evidence" data-company="${esc(company)}" data-metric="${esc(metric)}">${esc(label)}</button>`;}
function setRatioBasis(basis){currentRatioBasis=basis;document.querySelectorAll('.basis-btn').forEach(b=>b.classList.toggle('active',b.dataset.basis===basis));loadOverview();}
function selectedRatio(d,metric){
  if(currentRatioBasis==='latest') return metric==='revenue_growth'?d.metrics.revenue_growth:metricValue(d.metrics[metric]);
  if(metric==='revenue_growth') return currentRatioBasis==='ttm'?d.ratio_views?.market?.revenue_growth??null:null;
  const key=metric + (currentRatioBasis==='ttm'?'_ttm':'_annual');
  const item=d.market_ratios?.[key];
  return metricValue(item);
}
async function showEvidence(company,metric){
  try{
    const d=await getJSON(`/api/evidence/${encodeURIComponent(company)}?metric=${encodeURIComponent(metric)}&basis=${encodeURIComponent(currentRatioBasis)}`);
    const ov=document.createElement('div'); ov.className='modal-backdrop'; ov.innerHTML=`<div class="modal-card"><button class="modal-close" data-action="remove-closest" data-closest=".modal-backdrop">×</button><div class="assistant-kicker">EVIDENCE TRACE</div><h2>${esc(company)} · ${esc(metric.replaceAll('_',' '))}</h2><div class="dashboard"><div class="metric"><label>Value</label><strong>${metric.includes('margin')||metric.includes('roe')||metric.includes('roa')||metric.includes('growth')?pct(d.value):money(d.value)}</strong></div><div class="metric"><label>Period</label><strong>${esc(d.period_end||'Unavailable')}</strong></div><div class="metric"><label>Confidence</label><strong>${d.confidence==null?'Unavailable':pct(Number(d.confidence)*100)}</strong></div><div class="metric"><label>Scope</label><strong>${esc(d.document_scope||'Unavailable')}</strong></div></div><div class="notice"><b>Formula / basis</b><br>${esc(d.formula||'Verified library observation.')}</div><div class="data-note"><b>Source file:</b> ${esc(d.source_path||'Unavailable')}<br><b>Source type:</b> ${esc(d.source_type||'Unavailable')}<br><b>Document quality:</b> ${d.document_quality==null?'Unavailable':Math.round(Number(d.document_quality))+'/100'}</div></div>`;document.body.appendChild(ov);
  }catch(e){alert(e.message);}
}
function anomalyCards(items){if(!items?.length)return `<div class="chart-empty">No material anomalies detected in the available periods.</div>`;return `<div class="anomaly-list">${items.slice(0,8).map(x=>`<div class="anomaly ${x.type==='drop'?'negative':''}"><div><b>${esc(x.metric)}</b><div class="muted">${esc(x.from_period||'prior')} → ${esc(x.to_period||'latest')}</div></div><strong>${x.change_pct>0?'+':''}${num(x.change_pct,1)}%</strong>${x.detail?`<div class="data-note">${esc(x.detail)}</div>`:''}</div>`).join('')}</div>`;}
let overviewMode=1;
let overviewCache=null;
let overviewMarketCache=null;
let overviewMode3Previous=1;
let overviewRequestId=0;

function _fmtCap(v){ if(v==null) return "Unavailable"; const n=Number(v); if(!Number.isFinite(n)) return "Unavailable"; return Math.abs(n)>=1e12?(n/1e12).toFixed(2)+"T VND":Math.abs(n)>=1e9?(n/1e9).toFixed(1)+"B VND":n.toLocaleString()+" VND"; }
function _fmtPrice(v,currency='VND'){ if(v==null||!Number.isFinite(Number(v))) return "Unavailable"; const digits=String(currency||'').toUpperCase()==='VND'?0:2; return Number(v).toLocaleString(undefined,{minimumFractionDigits:digits,maximumFractionDigits:digits})+(currency?` ${currency}`:''); }
function _safeMetric(v,suffix=''){return v==null||Number.isNaN(Number(v))?'Unavailable':Number(v).toLocaleString(undefined,{maximumFractionDigits:2})+suffix;}
function _compactMetric(label,value,sub){return `<div class="compact-metric" title="${esc(label)}: ${esc(value)}"><span>${esc(label)}</span><b>${esc(value)}</b>${sub?`<small>${esc(sub)}</small>`:''}</div>`;}

function renderOverviewMode1(){
  const d=overviewCache, m=d?.metrics||{}, snap=overviewMarketCache||{};
  const growth=selectedRatio(d||{},'revenue_growth'), roe=selectedRatio(d||{},'roe'), pe=snap.pe, cap=snap.market_cap, price=snap.price;
  const status=d?.health?.direction||'INSUFFICIENT';
  const statusText=status==='UP'?'Positive evidence':status==='DOWN'?'Negative evidence':'Insufficient evidence';
  const statusCls=status==='UP'?'up':status==='DOWN'?'down':'flat';
  const company=d?.company||$('overviewCompany')?.value||'—';
  const mark=String(company).replace(/[^A-Za-z0-9]/g,'').slice(0,3)||'—';
  $('overviewCompactContent').innerHTML=`<div class="company-compact-head"><div class="company-symbol">${esc(mark)}</div><div class="company-identity-copy"><strong>${esc(company||'Company unavailable')}</strong><small>${esc(d?.industry||'Research workspace')}</small></div><span class="company-status ${statusCls}"><i></i>${esc(statusText)}</span></div><div class="compact-metrics">${_compactMetric('Price',_fmtPrice(price,snap.currency||'VND'))}${_compactMetric('Market cap',_fmtCap(cap))}${_compactMetric('P/E · TTM',_safeMetric(pe))}${_compactMetric('ROE',pct(roe))}${_compactMetric('Debt / EBITDA',metricValue(m.debt_to_ebitda)==null?'Unavailable':_safeMetric(metricValue(m.debt_to_ebitda),'×'))}</div><div class="compact-foot"><span><b>Report</b>${d?.latest_report?.period_end?esc(d.latest_report.period_end):'Unavailable'}</span><span class="${statusCls}"><b>Research score</b>${d?.health?.score==null?'—':esc(d.health.score)} / 100</span></div>`;
}

function renderOverviewMode2(){
  const d=overviewCache; if(!d)return;
  const m=d.metrics||{}, c=d.coverage||{}, h=d.health||{};
  const growth=selectedRatio(d,'revenue_growth'), net=selectedRatio(d,'net_margin'), ebitda=selectedRatio(d,'ebitda_margin'), roe=selectedRatio(d,'roe'), roa=selectedRatio(d,'roa');
  const fill=c.total_metrics?Math.round(c.available_metrics/c.total_metrics*100):0;
  $('overviewExpandedContent').innerHTML=`<div class="expanded-company-top"><div><div class="assistant-kicker">${esc(d.company||'COMPANY')} · ${esc(d.industry||'')}</div><h3>${esc(h.label||'Research overview')}</h3><p>${esc((h.signals||[]).slice(0,2).join(' • ')||'Use the evidence below to review the company.')}</p></div><div class="expanded-score"><strong>${h.score==null?'—':esc(h.score)}</strong><span>/100</span><small>research score</small></div></div><div class="expanded-stat-grid"><div><span>Revenue</span><b>${money(metricValue(m.revenue))}</b></div><div><span>Revenue growth</span><b>${pct(growth)}</b></div><div><span>Net margin</span><b>${pct(net)}</b></div><div><span>EBITDA margin</span><b>${pct(ebitda)}</b></div><div><span>ROE</span><b>${pct(roe)}</b></div><div><span>ROA</span><b>${pct(roa)}</b></div><div><span>Debt / EBITDA</span><b>${metricValue(m.debt_to_ebitda)==null?'Unavailable':_safeMetric(metricValue(m.debt_to_ebitda),'×')}</b></div><div><span>Data coverage</span><b>${fill}%</b></div></div><div class="expanded-bottom"><div><div class="data-note">Coverage</div><div class="coverage-bar"><div class="coverage-fill" style="width:${fill}%"></div></div></div><button class="secondary compact-open-btn" type="button" data-action="overview-mode" data-mode="3">Open full research ↗</button></div>`;
}

function syncOverviewModeDOM(){
  const compact=$("overviewCompactContent"), expanded=$("overviewExpandedContent");
  if(compact)compact.hidden=overviewMode!==1;
  if(expanded)expanded.hidden=overviewMode!==2;
  const panel=$("overviewCompanyPanel"); if(panel)panel.dataset.mode=String(overviewMode);
  document.querySelectorAll('.company-mode-btn').forEach(b=>{const active=Number(b.dataset.mode)===overviewMode;b.classList.toggle('active',active);b.setAttribute('aria-selected',String(active));});
}
function setOverviewMode(mode){
  const next=Math.max(1,Math.min(3,Number(mode)||1));
  if(next===3){overviewMode3Previous=overviewMode===3?1:overviewMode;overviewMode=3;document.body.dataset.overviewMode='3';openOverviewMode3();return;}
  overviewMode=next;document.body.dataset.overviewMode=String(next);
  if(next===1)renderOverviewMode1(); else renderOverviewMode2();
  syncOverviewModeDOM();
}
function openOverviewMode3(){
  const overlay=$("companyModeOverlay"),content=$("companyOverlayContent"); if(!overlay||!content)return;
  const title=$("companyOverlayTitle");
  const requested=$("overviewCompany")?.value.trim().toUpperCase()||'';
  const cached=String(overviewCache?.company||'').trim().toUpperCase();
  overlay.hidden=false;
  document.body.classList.add('research-overlay-open');
  document.querySelectorAll('.company-mode-btn').forEach(b=>{const active=Number(b.dataset.mode)===3;b.classList.toggle('active',active);b.setAttribute('aria-selected',String(active));});
  if(title)title.textContent=requested?`${requested} research overview`:'Full research overview';
  if(!requested){
    content.innerHTML=`<div class="overlay-empty-state"><div class="overlay-empty-mark">⌕</div><b>Choose a company first</b><p>Enter a company or ticker in the search box, then open Mode 3 for the complete research overview.</p></div>`;
    return;
  }
  if(!overviewCache||requested!==cached){
    content.innerHTML=`<div class="overlay-loading"><span></span><b>Building the ${esc(requested)} overview</b><small>Loading verified financial evidence and market context…</small></div>`;
    loadOverview();
    return;
  }
  const full=$("overviewOut")?.innerHTML||'';
  content.innerHTML=full||`<div class="overlay-loading">Loading full company research…</div>`;
  if(!full && overviewCache) setTimeout(()=>{content.innerHTML=$("overviewOut")?.innerHTML||content.innerHTML;},0);
}
function closeOverviewMode3(){
  const overlay=$("companyModeOverlay"); if(overlay)overlay.hidden=true;
  document.body.classList.remove('research-overlay-open');
  const back=overviewMode3Previous||1;
  overviewMode=back;document.body.dataset.overviewMode=String(back);
  if(back===1)renderOverviewMode1(); else renderOverviewMode2();
  syncOverviewModeDOM();
}

async function loadOverview(){
  const input=$("overviewCompany"),panel=$("overviewCompanyPanel"),submit=panel?.querySelector('.company-search-submit');
  const company=input.value.trim().toUpperCase();
  if(!company){input.focus();panel?.classList.add('needs-company');setTimeout(()=>panel?.classList.remove('needs-company'),420);return;}
  const requestId=++overviewRequestId;
  input.value=company;
  recordRecentCompany(company);
  overviewMarketCache=null;
  panel?.classList.add('is-loading');
  panel?.setAttribute('aria-busy','true');
  if(submit)submit.disabled=true;
  const loading=`<div class="company-loading-state"><span></span><div><b>Researching ${esc(company)}</b><small>Checking company evidence and market context…</small></div></div>`;
  if(overviewMode===1)$("overviewCompactContent").innerHTML=loading;
  if(overviewMode===2)$("overviewExpandedContent").innerHTML=loading;
  try{
    const d=await getJSON(`/api/overview/${encodeURIComponent(company)}`,{cancelKey:'company-overview'});
    if(requestId!==overviewRequestId)return;
    if(d.error){
      const errorHtml=`<div class="overlay-empty-state"><div class="overlay-empty-mark">!</div><b>Overview unavailable</b><p>${esc(d.error)}</p></div>`;
      $("overviewOut").innerHTML=`<div class="card notice">${esc(d.error)}</div>`;
      if(overviewMode===1)$("overviewCompactContent").innerHTML=errorHtml;
      if(overviewMode===2)$("overviewExpandedContent").innerHTML=errorHtml;
      if(overviewMode===3&&$("companyOverlayContent"))$("companyOverlayContent").innerHTML=errorHtml;
      return;
    }
    overviewCache=d;
    let h=d.health,u=directionUI(h.direction),m=d.metrics,c=d.coverage,quality=Number(d.latest_report?.quality_score??0),fill=c.total_metrics?Math.round(c.available_metrics/c.total_metrics*100):0,qualityLabel=quality>=80?"Verified":quality>=50?"Review":"Failed";
    const growth=selectedRatio(d,'revenue_growth'),netMargin=selectedRatio(d,'net_margin'),ebitdaMargin=selectedRatio(d,'ebitda_margin'),roe=selectedRatio(d,'roe'),roa=selectedRatio(d,'roa');
    let anomaliesData={anomalies:[]};try{anomaliesData=await getJSON(`/api/anomalies/${encodeURIComponent(company)}`,{cancelKey:'company-anomalies'});}catch(_){}
    if(requestId!==overviewRequestId)return;
    $("overviewOut").innerHTML=`<div class="card overview-result"><div class="signal executive-signal"><div class="arrow ${u.cls}">${u.arrow}</div><div><div class="assistant-kicker">EXECUTIVE SUMMARY</div><h2>${esc(d.company)} — ${esc(d.industry)}</h2><b>${esc(h.label)}</b><div class="muted">${esc(h.signals.join(" • ")||u.text)}</div></div><div class="executive-score">${h.score===null?"—":h.score}<span>/100</span><small>research score</small></div></div><div class="coverage"><b>Data coverage</b><div class="coverage-bar"><div class="coverage-fill" style="width:${fill}%"></div></div><b>${c.available_metrics}/${c.total_metrics}</b></div><div class="dashboard">${metricCard("Revenue",money(metricValue(m.revenue)),evidenceButton(d.company,'revenue'))}${metricCard("Revenue growth",pct(growth),evidenceButton(d.company,'revenue_growth'))}${metricCard("Net margin",pct(netMargin),evidenceButton(d.company,'net_margin'))}${metricCard("EBITDA margin",pct(ebitdaMargin),evidenceButton(d.company,'ebitda_margin'))}${metricCard("ROE",pct(roe),evidenceButton(d.company,'roe'))}${metricCard("ROA",pct(roa),evidenceButton(d.company,'roa'))}${metricCard("Debt / EBITDA",metricValue(m.debt_to_ebitda)==null?"Unavailable":`${num(metricValue(m.debt_to_ebitda),2)}×`,evidenceButton(d.company,'debt_to_ebitda'))}${metricCard("Data quality",`${Math.round(quality)}/100`,qualityLabel)}${metricCard("Reports",d.reports,`Latest: ${d.latest_report.period_end||"date not detected"}`)}</div>${c.transparency_alerts&&c.transparency_alerts.length?`<div class="notice bad"><b>Unavailable</b>: ${c.transparency_alerts.map(esc).join(", ")}</div>`:""}<div class="summary-visuals"><div class="chart-card summary-chart-card"><div class="chart-heading"><div><b>Performance profile</b><div class="data-note">${esc(currentRatioBasis.toUpperCase())} basis</div></div><span class="muted">Research view</span></div>${metricBars([["Growth",growth],["Net margin",netMargin],["EBITDA margin",ebitdaMargin],["ROE",roe],["ROA",roa]])}</div><div class="chart-card summary-chart-card"><div class="chart-heading"><div><b>Research confidence</b><div class="data-note">Evidence quality and coverage</div></div><span class="${quality>=80?'up':quality>=50?'flat':'down'}">${esc(qualityLabel)}</span></div>${confidenceGauge(fill,quality)}<div class="confidence-legend"><span><i class="dot dot-blue"></i>Coverage ${fill}%</span><span><i class="dot dot-green"></i>Quality ${Math.round(quality)}%</span></div></div></div><div class="visual-grid"><div><h3>Financial history</h3>${lineChart(d.history,"revenue","Revenue")}${lineChart(d.history,"net_income","Net income")}</div><div><h3>What changed?</h3>${anomalyCards(anomaliesData.anomalies)}</div></div><h3>Research timeline</h3><div class="timeline-strip">${(d.history.revenue||[]).slice(-8).map((x,i)=>`<div class="timeline-node"><span>${esc(chartPeriod(x.period_end)||x.year)}</span><b>${money(x.value)}</b><small>${i===d.history.revenue.length-1?'Latest verified period':'Historical observation'}</small></div>`).join('')||'<div class="chart-empty">No historical timeline available.</div>'}</div><h3>Position inside ${esc(d.industry)}</h3><table class="table"><thead><tr><th>Company</th><th>Growth</th><th>Profitability</th><th>Capital efficiency</th><th>Leverage</th></tr></thead><tbody>${d.peers.map(p=>`<tr><td><b>${esc(p.company)}</b></td><td>${pct(p.revenue_growth)}</td><td>${pct(p.net_margin)}</td><td>${pct(p.roe)}</td><td>${p.debt_to_ebitda==null?"Unavailable":num(p.debt_to_ebitda,2)+"×"}</td></tr>`).join("")}</tbody></table><div class="visual-grid"><div><h3>Evidence balance</h3>${evidencePie(h.components)}<p class="data-note">Only verified consolidated evidence feeds the main financial metrics.</p></div><div><h3>Report health</h3><div class="dashboard">${metricCard('Scope',d.latest_report.scope||'Unknown')}${metricCard('Status',d.latest_report.status||'Review')}${metricCard('Quality',Math.round(quality)+'/100')}${metricCard('Coverage',fill+'%')}</div><div class="notice">${c.transparency_alerts?.length?esc(c.transparency_alerts.slice(0,4).join(' • ')):'No material data-health warning on the latest report.'}</div></div></div><div class="notice">Latest report: <b>${esc(d.latest_report.period_end||"date not detected")}</b> · ${esc(d.latest_report.scope||"unknown")} · ${esc(d.latest_report.status||"review")}.</div></div>`;
    $("overviewOut").querySelector('.overview-result')?.insertAdjacentHTML('beforeend',`<section class="core-value-overview-card"><div class="core-value-overview-intro"><div><div class="assistant-kicker">CORE VALUE RESEARCH</div><h3>DCF, earnings, dividends and assets</h3><p>Calculate a transparent per-share range using visible assumptions. Missing methods remain unavailable and are excluded from the blend.</p></div><button type="button" class="primary" data-action="overview-valuation">Calculate core value <span aria-hidden="true">→</span></button></div><div class="overview-core-value-mount"><div class="valuation-empty"><b>Not calculated yet</b><span>Run only when you need the deeper valuation so the dashboard stays fast.</span></div></div></section>`);
    renderOverviewMode1();
    if(overviewMode===2)renderOverviewMode2();
    if(overviewMode===3)openOverviewMode3();
    loadMarketSnapshot(company);
  }catch(e){
    if(e?.name==='AbortError'||requestId!==overviewRequestId)return;
    $("overviewOut").innerHTML=`<div class="card notice">${esc(e.message)}</div>`;
    const errorHtml=`<div class="company-no-selection"><b>Company unavailable</b><span>${esc(e.message)}</span></div>`;
    if(overviewMode===1)$("overviewCompactContent").innerHTML=errorHtml;
    if(overviewMode===2)$("overviewExpandedContent").innerHTML=errorHtml;
    if(overviewMode===3&&$("companyOverlayContent"))$("companyOverlayContent").innerHTML=`<div class="overlay-empty-state"><div class="overlay-empty-mark">!</div><b>Overview unavailable</b><p>${esc(e.message)}</p></div>`;
  }finally{
    if(requestId!==overviewRequestId)return;
    panel?.classList.remove('is-loading');
    panel?.removeAttribute('aria-busy');
    if(submit)submit.disabled=false;
  }
}

async function loadResearchBrief(){const company=$("overviewCompany").value.trim().toUpperCase();if(!company)return;try{const d=await getJSON(`/api/research/brief/${encodeURIComponent(company)}`);$("overviewOut").insertAdjacentHTML('afterbegin',`<div class="card research-brief"><div class="chart-heading"><div><div class="assistant-kicker">RESEARCH BRIEF</div><h2>${esc(d.company)} — Research Snapshot</h2><div class="data-note">Generated from local financial evidence and historical market data.</div></div><button class="secondary" data-action="remove-closest" data-closest=".research-brief">Close</button></div><div class="dashboard">${metricCard('Revenue',money(metricValue(d.metrics.revenue)))}${metricCard('Net margin',pct(metricValue(d.metrics.net_margin)))}${metricCard('EBITDA margin',pct(metricValue(d.metrics.ebitda_margin)))}${metricCard('ROE',pct(metricValue(d.metrics.roe)))}${metricCard('ROA',pct(metricValue(d.metrics.roa)))}</div><div class="visual-grid"><div><h3>Risk summary</h3><div class="notice ${d.risk.flags?.length?'bad':'good'}">${esc(d.risk.flags?.length?d.risk.flags.join(' • '):'No major rule-based warning.')}</div></div><div><h3>Market view</h3><div class="notice">${esc(d.market.status==='ok'?(d.market.direction+' · up tendency '+pct(d.market.up_probability*100)):(d.market.status||'Unavailable'))}</div></div></div>${anomalyCards(d.anomalies)}</div>`);}catch(e){alert(e.message);}}

function addPortfolioRow(){const wrap=$("portfolioRows");const row=document.createElement('div');row.className='grid3 portfolio-row';row.innerHTML=`<label>Company<input class="portfolio-company" placeholder="FPT"></label><label>Weight %<input class="portfolio-weight" type="number" value="10" min="0" max="100" step="0.1"></label><button type="button" class="secondary remove-portfolio" data-action="remove-portfolio">Remove</button>`;wrap.appendChild(row);}
async function loadPortfolioRisk(){const rows=[...document.querySelectorAll('.portfolio-row')];const holdings=rows.map(r=>({company:r.querySelector('.portfolio-company')?.value.trim().toUpperCase(),weight:Number(r.querySelector('.portfolio-weight')?.value||0)})).filter(x=>x.company&&x.weight>0);$("portfolioOut").innerHTML=`<div class="card"><div class="muted">Calculating historical portfolio risk…</div></div>`;try{const d=await getJSON('/api/portfolio/risk',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({holdings})});if(d.status!=='ok')throw new Error(d.status||d.error||'Portfolio analysis unavailable.');const rowsHtml=(d.holdings||[]).map(x=>`<tr><td><b>${esc(x.company)}</b></td><td>${pct(x.weight)}</td><td>${pct(x.volatility)}</td><td>${pct(x.risk_contribution)}</td></tr>`).join('');$("portfolioOut").innerHTML=`<div class="card"><div class="dashboard">${metricCard('Annualized volatility',pct(d.portfolio_volatility_pct))}${metricCard('Max drawdown',pct(d.max_drawdown_pct))}${metricCard('Concentration',pct(d.concentration_hhi_pct))}${metricCard('History',num(d.data_points,0)+' days')}</div><h3>Risk contribution</h3><table class="table"><thead><tr><th>Company</th><th>Weight</th><th>Volatility</th><th>Risk contribution</th></tr></thead><tbody>${rowsHtml}</tbody></table><h3>Correlation</h3><div class="correlation-grid">${Object.entries(d.correlation||{}).map(([c,row])=>Object.entries(row).map(([k,v])=>`<div class="corr-cell"><span>${esc(c)} / ${esc(k)}</span><b>${num(v,2)}</b></div>`).join('')).join('')}</div><div class="notice">${esc(d.warning||'Historical risk estimates only.')}</div></div>`;}catch(e){$("portfolioOut").innerHTML=`<div class="card notice">${esc(e.message)}</div>`;}}

async function loadCompare(){const a=$("compareA").value.trim().toUpperCase(),b=$("compareB").value.trim().toUpperCase();if(!a||!b)return;try{const d=await getJSON(`/api/compare?companies=${encodeURIComponent(a+","+b)}`);if(d.error){$("compareOut").innerHTML=`<div class="card notice">${esc(d.error)}</div>`;return;}$("compareOut").innerHTML=`<div class="card"><h2>${esc(a)} vs ${esc(b)}</h2><div class="compare-grid">${d.companies.map(c=>{const u=directionUI(c.health.direction);return `<div class="compare-company"><div class="compare-title"><b>${esc(c.company)}</b><span class="${u.cls}">${u.arrow}</span></div><div class="score">${c.health.score===null?"—":c.health.score}</div><div class="muted">${esc(c.health.label)}</div><div class="mini-grid"><div class="mini">Growth<b>${pct(c.metrics.revenue_growth)}</b></div><div class="mini">Net margin<b>${pct(metricValue(c.metrics.net_margin))}</b></div><div class="mini">ROE<b>${pct(metricValue(c.metrics.roe))}</b></div></div></div>`;}).join("")}</div><h3>Side-by-side view</h3><table class="table"><thead><tr><th>What we compare</th>${d.companies.map(c=>`<th>${esc(c.company)}</th>`).join("")}</tr></thead><tbody>${[["Revenue growth",c=>pct(c.metrics.revenue_growth)],["Net margin",c=>pct(metricValue(c.metrics.net_margin))],["ROE",c=>pct(metricValue(c.metrics.roe))],["Debt load",c=>metricValue(c.metrics.debt_to_ebitda)==null?"Unavailable":num(metricValue(c.metrics.debt_to_ebitda),2)+"×"]].map(([label,fn])=>`<tr><td><b>${label}</b></td>${d.companies.map(fn).map(v=>`<td>${v}</td>`).join("")}</tr>`).join("")}</tbody></table><div class="notice">There is no universal “better” company. The system compares growth, profitability, capital efficiency, leverage and evidence coverage together.</div></div>`;}catch(e){$("compareOut").innerHTML=`<div class="card notice">${esc(e.message)}</div>`;}}

async function loadStock(){const company=$("stockCompany").value.trim().toUpperCase();if(!company)return;try{$("stockOut").innerHTML=`<div class="card"><div class="muted">Loading historical market data…</div></div>`;const d=await getJSON(`/api/stock/${encodeURIComponent(company)}`);$("stockOut").innerHTML=renderStock(d);}catch(e){$("stockOut").innerHTML=`<div class="card notice">${esc(e.message)}</div>`;}}
function renderStockHorizon(row){
  if(row.status!=="ok")return `<article class="quant-horizon unavailable"><div><span>${esc(row.label||row.key)}</span><small>${num(row.trading_days,0)} trading days</small></div><b>Unavailable</b><p>${esc(row.reason||"Insufficient validated history.")}</p></article>`;
  const validation=row.validation||{},direction=row.direction||"UNCERTAIN";
  const tone=direction==="UPWARD"?"up":direction==="DOWNWARD"?"down":"flat";
  return `<article class="quant-horizon ${tone} ${row.signal_suppressed?"suppressed":""}"><div><span>${esc(row.label)}</span><small>${num(row.trading_days,0)} trading days</small></div><b>${esc(direction)}</b><strong>${pct(Number(row.up_probability||0)*100)} up</strong><div class="quant-probability"><i style="width:${Math.max(0,Math.min(100,Number(row.up_probability||0)*100))}%"></i></div><dl><div><dt>Brier skill</dt><dd>${pct(validation.brier_skill_pct)}</dd></div><div><dt>Validation</dt><dd>${num(validation.samples,0)} outcomes</dd></div><div><dt>Stability</dt><dd>${esc(validation.stability||"Unavailable")}</dd></div><div><dt>Quality</dt><dd>${esc(row.quality||"Unavailable")}</dd></div></dl><p>${esc(row.quality_reason||"")}</p></article>`;
}
function renderStock(d){
  if(d.status!=="ok")return `<div class="card notice">${esc(d.status||"Market analysis unavailable.")}</div>`;
  const u=directionUI(d.direction==="UPWARD"?"UP":d.direction==="DOWNWARD"?"DOWN":"FLAT"),z=d.zones||{},validation=d.validation||{};
  const horizons=(d.horizons||[]).map(renderStockHorizon).join("");
  const importance=(d.feature_importance||[]).map(row=>`<div class="quant-driver"><span>${esc(row.label)}</span><i><em style="width:${Math.max(0,Math.min(100,Number(row.importance_pct||0)))}%"></em></i><b>${pct(row.importance_pct)}</b></div>`).join("");
  return `<div class="card quant-research-card"><div class="signal"><div class="arrow ${u.cls}">${u.arrow}</div><div><div class="assistant-kicker">CALIBRATED MARKET SIGNAL · ${esc(d.primary_horizon_label||"1 month")}</div><h2>${esc(d.direction)}</h2><div class="muted">${esc(d.quality_reason||"Model signal based on historical market behavior.")}</div></div><span class="pill">${esc(d.quality||"Unavailable")} validation</span></div><div class="dashboard">${metricCard("Current price",num(d.price,2))}${metricCard("Up probability",pct(d.up_probability*100),esc(d.primary_horizon_label||""))}${metricCard("Down probability",pct(d.down_probability*100),esc(d.primary_horizon_label||""))}${metricCard("Brier skill",pct(validation.brier_skill_pct),"vs historical base rate")}</div><section class="quant-section"><div class="section-head"><div><div class="assistant-kicker">MULTI-HORIZON OUTLOOK</div><h3>What the model can validate</h3></div><p>Every horizon is trained and tested separately.</p></div><div class="quant-horizon-grid">${horizons}</div></section><div class="quant-two-column"><section class="quant-section"><div class="assistant-kicker">WALK-FORWARD VALIDATION</div><h3>Probability quality</h3><div class="quant-validation-grid"><div><span>Model accuracy</span><b>${pct(Number(validation.accuracy||0)*100)}</b></div><div><span>Base-rate accuracy</span><b>${pct(Number(validation.baseline_accuracy||0)*100)}</b></div><div><span>Brier score</span><b>${num(validation.brier_score,4)}</b></div><div><span>Baseline Brier</span><b>${num(validation.baseline_brier_score,4)}</b></div><div><span>Log loss</span><b>${num(validation.log_loss,4)}</b></div><div><span>Validation folds</span><b>${num(validation.folds,0)}</b></div></div><p class="data-note">${esc(validation.method||"")}</p></section><section class="quant-section"><div class="assistant-kicker">MODEL DRIVERS</div><h3>Relative feature importance</h3><div class="quant-driver-list">${importance||'<div class="chart-empty">Feature importance unavailable.</div>'}</div><p class="data-note">Importance is historical and non-causal; it does not explain every individual prediction.</p></section></div><section class="quant-section"><div class="assistant-kicker">REFERENCE ZONES</div><h3>Historical price structure</h3><div class="dashboard">${metricCard("20-day support",num(z.support20,2))}${metricCard("20-day resistance",num(z.resistance20,2))}${metricCard("60-day support",num(z.support60,2))}${metricCard("60-day resistance",num(z.resistance60,2))}</div></section><div class="notice ${d.signal_suppressed?"bad":""}">${esc(d.warning)}</div></div>`;
}

function vsaOptionalNumber(id){
  const raw=$(id)?.value?.trim();
  if(raw===''||raw==null)return null;
  const value=Number(raw);
  return Number.isFinite(value)?value:null;
}
function vsaPayload(){
  return {
    company:($('vsaCompany')?.value||'').trim().toUpperCase(),
    market_symbol:($('vsaSymbol')?.value||'').trim().toUpperCase(),
    profile:$('vsaProfile')?.value||'balanced',
    position_status:$('vsaPositionStatus')?.value||'watching',
    account_value:vsaOptionalNumber('vsaAccountValue'),
    entry_price:vsaOptionalNumber('vsaEntryPrice'),
    risk_pct:vsaOptionalNumber('vsaRiskPct')??1,
    sector_exposure_pct:vsaOptionalNumber('vsaSectorExposure')??0,
  };
}
function initVsaWorkspace(){
  const company=$('vsaCompany');
  if(company&&!company.value&&appState.companyDirectory.length)company.value=String(appState.companyDirectory[0].company||'').toUpperCase();
}
function vsaPrice(value,ticker=''){
  if(value==null||!Number.isFinite(Number(value)))return 'Unavailable';
  const vietnam=String(ticker||'').toUpperCase().endsWith('.VN');
  return Number(value).toLocaleString(undefined,{maximumFractionDigits:vietnam?0:2})+(vietnam?' VND':'');
}
function vsaActionLabel(action){
  return ({
    CONSIDER_ON_CONFIRMATION:'Candidate on confirmation',WAIT_FOR_CONFIRMATION:'Wait for confirmation',
    WAIT_FOR_PULLBACK:'Wait for pullback',WAIT_TRAP_RESOLUTION:'Wait—trap risk',AVOID_NEW_ENTRY:'Avoid new entry',
    HOLD_WITH_RULES:'Hold with rules',TIGHTEN_RISK:'Tighten risk',REVIEW_EXIT:'Review exit now'
  })[action]||String(action||'Unresolved').replaceAll('_',' ');
}
function vsaTone(action){
  if(['CONSIDER_ON_CONFIRMATION','HOLD_WITH_RULES'].includes(action))return 'positive';
  if(['AVOID_NEW_ENTRY','REVIEW_EXIT','TIGHTEN_RISK','WAIT_TRAP_RESOLUTION'].includes(action))return 'negative';
  return 'caution';
}
function vsaEventCard(event,trap=false){
  const tone=event.bias==='bullish'?'bullish':event.bias==='bearish'?'bearish':'neutral';
  return `<article class="vsa-event ${tone}"><div><span>${esc(event.date||'Recent')}</span><em>${esc(event.strength||'observed')}</em></div><h4>${esc(event.name||'Volume event')}</h4><p>${esc(event.explanation||'')}</p><small><b>Confirm:</b> ${esc(event.confirmation||'Wait for subsequent price action.')}</small>${trap&&event.level!=null?`<strong>Reference ${vsaPrice(event.level)}</strong>`:''}</article>`;
}
function vsaIndicatorCard(indicator){
  const label=indicator.label||'Indicator';
  let value=indicator.value;
  if(label==='Relative volume'&&value!=null)value=`${num(value,2)}×`;
  else if(label==='ATR (14)'&&value!=null)value=num(value,2);
  else if(label==='Chaikin Money Flow'&&value!=null)value=num(value,3);
  else if(label==='MACD'&&value!=null)value=num(value,3);
  else if(value!=null)value=num(value,1);
  else if(indicator.sma20!=null)value=`20: ${num(indicator.sma20,1)}`;
  else if(indicator.middle!=null)value=`Mid: ${num(indicator.middle,1)}`;
  else value='Unavailable';
  return `<article class="vsa-indicator"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(indicator.state||'')}</small></article>`;
}
function vsaRiskMeter(label,value,tone){
  const bounded=Math.max(0,Math.min(100,Number(value||0)));
  return `<div class="vsa-risk-meter ${tone}"><div><span>${esc(label)}</span><b>${pct(bounded)}</b></div><i><em style="width:${bounded}%"></em></i></div>`;
}
function renderVsaAnalysis(data){
  if(!data||data.status!=='ok')return `<section class="card notice bad"><b>Analysis unavailable</b><br>${esc(data?.reason||'No usable OHLCV history was returned.')}</section>`;
  const plan=data.plan||{},entry=plan.conditional_entry_zone||{},wait=plan.wait_window||{},hold=plan.holding_window||{};
  const tone=vsaTone(plan.action),statements=data.financial_statements||{},position=plan.position_sizing||{};
  const indicators=Object.values(data.indicators||{}).map(vsaIndicatorCard).join('');
  const events=(data.vsa?.recent_events||[]).map(event=>vsaEventCard(event)).join('')||'<div class="vsa-no-event">No high-conviction VSA event appeared in the latest eight sessions. Treat absence as neutral—not bullish.</div>';
  const traps=(data.traps?.recent_events||[]).map(event=>vsaEventCard(event,true)).join('')||'<div class="vsa-no-event">No recent failed-breakout or failed-breakdown pattern crossed the rule threshold.</div>';
  const scoreRows=(data.score_components||[]).map(row=>`<div class="vsa-score-row"><div><span>${esc(row.label)}</span><b>${num(row.score,1)} / ${num(row.maximum,0)}</b></div><i><em style="width:${Math.max(0,Math.min(100,Number(row.score||0)/Math.max(1,Number(row.maximum||1))*100))}%"></em></i>${row.available===false?'<small>Neutral placeholder: no indexed statement evidence</small>':''}</div>`).join('');
  const statementHtml=statements.available?`<div class="vsa-statement-grid"><div><span>Latest statement</span><b>${esc(statements.latest_period||'Date unavailable')}</b></div><div><span>Evidence coverage</span><b>${pct(statements.coverage_pct)}</b></div><div><span>Research health</span><b>${statements.health_score==null?'Unavailable':num(statements.health_score,0)+'/100'}</b></div><div><span>Risk flags</span><b>${num(statements.risk_flag_count||0,0)}</b></div></div>${statements.risk_flags?.length?`<div class="notice bad">${statements.risk_flags.map(esc).join(' • ')}</div>`:'<div class="notice good">No current rule-based statement warning feeds this score.</div>'}`:`<div class="notice">${esc(statements.note||'No indexed statement evidence is connected to this symbol.')}</div>`;
  const sizingHtml=position.maximum_units!=null?`<div class="vsa-sizing-grid"><div><span>Risk budget</span><b>${vsaPrice(position.risk_budget,data.ticker)}</b></div><div><span>Maximum units</span><b>${num(position.maximum_units,0)}</b></div><div><span>Maximum position</span><b>${vsaPrice(position.maximum_position_value,data.ticker)}</b></div><div><span>Units per stage</span><b>${num(position.per_stage_units,0)} × 3</b></div></div>`:`<div class="vsa-no-event">Add account value to calculate a risk-based maximum size. The ${esc(plan.profile_label||'selected')} profile still caps risk at ${pct(position.profile_cap_pct)} per trade, position size at ${pct(position.max_position_pct)}, and same-industry exposure at ${pct(position.max_sector_pct)}.</div>`;
  return `<div class="vsa-result-stack">
    <section class="card vsa-decision-hero ${tone}"><div class="vsa-decision-copy"><div class="assistant-kicker">${esc(data.company)} · ${esc(data.ticker)} · ${esc(data.as_of)}</div><span class="vsa-action-chip">${esc(vsaActionLabel(plan.action))}</span><h2>${esc(plan.headline||'Conditional plan')}</h2><p>${esc(plan.disclaimer||'Research only.')}</p></div><div class="vsa-score-dial"><strong>${num(data.research_score,0)}</strong><span>/100</span><small>${pct(data.confidence_pct)} evidence confidence</small></div></section>
    <section class="card vsa-plan-card"><div class="vsa-section-heading"><div><span class="vsa-step">03</span><div><h3>Conditional price plan</h3><p>Levels come from current volatility and recent structure; confirmation is required before a new entry.</p></div></div><span class="pill">${esc(plan.profile_label||'Balanced')}</span></div><div class="vsa-level-grid"><article><span>Current</span><b>${vsaPrice(plan.current_price,data.ticker)}</b><small>Last available daily close</small></article><article class="entry"><span>Conditional entry zone</span><b>${vsaPrice(entry.low,data.ticker)} – ${vsaPrice(entry.high,data.ticker)}</b><small>Use only with checklist confirmation</small></article><article><span>Breakout trigger</span><b>${vsaPrice(plan.breakout_confirmation,data.ticker)}</b><small>Close and participation required</small></article><article class="risk"><span>Invalidation</span><b>${vsaPrice(plan.invalidation,data.ticker)}</b><small>Review/exit after decisive close below</small></article><article><span>Target 1</span><b>${vsaPrice(plan.target_1,data.ticker)}</b><small>Protect part of the gain</small></article><article><span>Target 2</span><b>${vsaPrice(plan.target_2,data.ticker)}</b><small>Conditional, never guaranteed</small></article></div><div class="vsa-time-grid"><div><span>How long to wait</span><b>${num(wait.min_sessions,0)}–${num(wait.max_sessions,0)} sessions</b><p>${esc(wait.condition||'')}</p></div><div><span>Model holding window</span><b>${num(hold.min_sessions,0)}–${num(hold.max_sessions,0)} sessions</b><p>${esc(hold.condition||'')}</p></div></div></section>
    <div class="vsa-two-column"><section class="card"><div class="assistant-kicker">VOLUME SPREAD ANALYSIS</div><h3>Recent price–volume evidence</h3><div class="vsa-mini-kpis"><div><span>Volume</span><b>${num(data.vsa?.latest_volume_ratio,2)}× normal</b></div><div><span>Spread</span><b>${num(data.vsa?.latest_spread_ratio,2)}× normal</b></div><div><span>Close location</span><b>${pct(data.vsa?.latest_close_location_pct)}</b></div></div><div class="vsa-event-list">${events}</div><p class="data-note">${esc(data.vsa?.method||'')}</p></section><section class="card"><div class="assistant-kicker">TRAP RADAR</div><h3>Failed-break risk</h3>${vsaRiskMeter('Bull-trap risk',data.traps?.bull_trap_risk,'bearish')}${vsaRiskMeter('Bear-trap risk',data.traps?.bear_trap_risk,'bullish')}<div class="vsa-event-list compact">${traps}</div><p class="data-note">${esc(data.traps?.method||'')}</p></section></div>
    <div class="vsa-two-column"><section class="card"><div class="assistant-kicker">WYCKOFF CONTEXT</div><div class="vsa-phase-head"><div><h3>${esc(data.wyckoff?.label||'Unresolved')}</h3><p>${esc(data.wyckoff?.description||'')}</p></div><strong>${pct(data.wyckoff?.confidence)}<small>heuristic confidence</small></strong></div><div class="vsa-range-position"><span>Position inside 60-session range</span><i><em style="left:${Math.max(0,Math.min(100,Number(data.wyckoff?.range_position_pct||50)))}%"></em></i><b>${pct(data.wyckoff?.range_position_pct)}</b></div><div class="notice">${esc(data.wyckoff?.warning||'')}</div></section><section class="card"><div class="assistant-kicker">INDICATOR BOARD</div><h3>Trend, momentum, money flow, and volatility</h3><div class="vsa-indicator-grid">${indicators}</div></section></div>
    <div class="vsa-two-column"><section class="card"><div class="assistant-kicker">STATEMENT EVIDENCE</div><h3>Automatically refreshed after re-indexing</h3>${statementHtml}<div class="vsa-score-list">${scoreRows}</div></section><section class="card"><div class="assistant-kicker">POSITION BALANCE</div><h3>Cap exposure before estimating reward</h3>${sizingHtml}<p class="data-note">${esc(position.method||'')}</p></section></div>
    <div class="vsa-two-column"><section class="card"><div class="assistant-kicker">ENTRY CONFIRMATION</div><h3>All three checks should pass</h3><ol class="vsa-rule-list">${(plan.confirmation_checklist||[]).map(rule=>`<li>${esc(rule)}</li>`).join('')}</ol></section><section class="card"><div class="assistant-kicker">SELL / RISK RULES</div><h3>Know the exit conditions first</h3><ol class="vsa-rule-list">${(plan.sell_rules||[]).map(rule=>`<li>${esc(rule)}</li>`).join('')}</ol></section></div>
    <section class="card vsa-limitations"><details><summary>Model limitations and correct use</summary><ul>${(data.limitations||[]).map(item=>`<li>${esc(item)}</li>`).join('')}</ul></details></section>
  </div>`;
}
async function loadVsaAnalysis(){
  const payload=vsaPayload(),out=$('vsaOut'),button=document.querySelector('[data-action="vsa-analyze"]');
  if(!payload.company){out.innerHTML='<section class="card notice bad">Enter a company or ticker first.</section>';return;}
  if(button)button.disabled=true;
  out.innerHTML='<section class="card vsa-loading"><i></i><div><b>Reading daily price and volume…</b><span>Calculating indicators, VSA events, trap risk, and conditional levels.</span></div></section>';
  try{const data=await getJSON('/api/indicators-vsa/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),dedupe:false});out.innerHTML=renderVsaAnalysis(data);}
  catch(error){out.innerHTML=`<section class="card notice bad">${esc(error.message)}</section>`;}
  finally{if(button)button.disabled=false;}
}
function renderVsaScreen(data){
  if(!data||!data.candidates?.length){const missing=(data?.unavailable||[]).slice(0,5).map(item=>`${item.company||item.ticker}: ${item.reason||item.status}`).join(' • ');return `<div class="notice">No candidate had sufficient data.${missing?` ${esc(missing)}`:''}</div>`;}
  const cards=data.candidates.map((item,index)=>{const plan=item.plan||{},tone=vsaTone(plan.action);return `<article class="vsa-candidate ${tone}"><div class="vsa-candidate-rank">${String(index+1).padStart(2,'0')}</div><div class="vsa-candidate-main"><span>${esc(item.company)} · ${esc(item.ticker)}</span><h4>${esc(vsaActionLabel(plan.action))}</h4><p>${esc(plan.headline||'')}</p></div><div class="vsa-candidate-score"><strong>${num(item.research_score,0)}</strong><span>/100</span></div><div class="vsa-candidate-level"><span>Conditional zone</span><b>${vsaPrice(plan.conditional_entry_zone?.low,item.ticker)} – ${vsaPrice(plan.conditional_entry_zone?.high,item.ticker)}</b></div><button type="button" class="secondary" data-action="vsa-open-candidate" data-company="${esc(item.company)}">Open analysis</button></article>`;}).join('');
  const unavailable=data.unavailable?.length?`<details class="vsa-screen-unavailable"><summary>${data.unavailable.length} unavailable symbol${data.unavailable.length===1?'':'s'}</summary><ul>${data.unavailable.map(item=>`<li><b>${esc(item.company||item.ticker||'Unknown')}</b> — ${esc(item.reason||item.status||'No data')}</li>`).join('')}</ul></details>`:'';
  return `<div class="vsa-screen-summary"><b>${data.analyzed} of ${data.requested} companies analyzed</b><span>${esc(data.ranking_note||'')}</span></div><div class="vsa-candidate-list">${cards}</div>${unavailable}<p class="data-note">${esc(data.update_note||'')}</p>`;
}
async function loadVsaScreen(){
  const base=vsaPayload(),raw=($('vsaUniverse')?.value||'').trim();
  const payload={...base,companies:raw?raw.split(',').map(value=>value.trim().toUpperCase()).filter(Boolean):[]};
  const out=$('vsaScreenOut'),button=document.querySelector('[data-action="vsa-screen"]');if(button)button.disabled=true;
  out.innerHTML='<div class="vsa-loading compact"><i></i><div><b>Ranking the research universe…</b><span>This can take longer because each market history is checked independently.</span></div></div>';
  try{const data=await getJSON('/api/indicators-vsa/screen',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),dedupe:false});out.innerHTML=renderVsaScreen(data);}
  catch(error){out.innerHTML=`<div class="notice bad">${esc(error.message)}</div>`;}
  finally{if(button)button.disabled=false;}
}
function openVsaCandidate(company){
  showView('indicatorsVsa');
  if($('vsaCompany'))$('vsaCompany').value=String(company||'').toUpperCase();
  window.scrollTo({top:0,behavior:'smooth'});
  loadVsaAnalysis();
}

function riskInfoTip(text,{right=false,side=false,label='More information'}={}){
  return `<span class="risk-info-tip${right?' risk-info-tip-right':''}${side?' risk-info-tip-side':''}" tabindex="0" role="button" aria-expanded="false" aria-label="${esc(label)}. ${esc(text)}" data-tooltip="${esc(text)}">i</span>`;
}
function riskMetricLabel(label,tip,right=false){
  return `<span class="risk-metric-label">${esc(label)}${tip?riskInfoTip(tip,{right,label:`About ${label}`}):''}</span>`;
}
function riskChangeTone(metric,value){
  const number=Number(value);
  if(!Number.isFinite(number)||number===0)return 'neutral';
  const adverse=String(metric).toLowerCase()==='debt'?number>0:number<0;
  return adverse?'adverse':'favorable';
}
async function loadRisk(){
  const company=$("riskCompany")?.value.trim().toUpperCase();if(!company)return;
  if($("valuationCompany"))$("valuationCompany").value=company;
  if($("tradeCompany"))$("tradeCompany").value=company;
  const out=$("riskOut");
  if(out)out.innerHTML='<section class="risk-empty-state compact"><span>READING VERIFIED EVIDENCE</span><h3>Building the accounting-quality screen…</h3><p>Checking rule-based warnings, paired filing periods, and the Beneish component model.</p></section>';
  valuationCache=null;
  if($('valuationOut'))$('valuationOut').innerHTML='<div class="valuation-empty"><b>Ready when you are</b><span>Review the assumptions, then calculate the long-holding outlook.</span></div>';
  try{
    const d=await getJSON(`/api/risk/${encodeURIComponent(company)}`),b=d.beneish||{};
    const flags=Array.isArray(d.flags)?d.flags:[],changes=Array.isArray(d.report_consistency)?d.report_consistency:[];
    const available=b.status==='ok',flagged=available&&Boolean(b.screening_flag),caution=flags.length>0||flagged;
    const tone=caution?'caution':available?'positive':'neutral';
    const badge=caution?'Review signals':available?'No screen flag':'Limited evidence';
    const signalValue=b.relative_screen_signal_pct??b.risk_proxy_pct;
    const proxy=signalValue==null?'Unavailable':`${Number(signalValue).toFixed(1)}%`;
    const score=b.score==null?'Unavailable':Number(b.score).toFixed(3);
    const periods=Array.isArray(b.periods)?b.periods.filter(Boolean).map(String):[];
    const componentMeta={
      DSRI:['Receivables / sales','Compares receivables relative to sales with the prior period.'],
      GMI:['Gross margin','Compares prior gross margin with current gross margin.'],
      AQI:['Asset quality','Tracks the share of assets outside current assets and property, plant, and equipment.'],
      SGI:['Sales growth','Compares current sales with the prior matched period.'],
      DEPI:['Depreciation rate','Compares the prior depreciation rate with the current rate.'],
      SGAI:['SG&A intensity','Compares selling and administrative expense relative to sales.'],
      LVGI:['Leverage','Compares debt relative to total assets across periods.'],
      TATA:['Accrual intensity','Compares accounting earnings with operating cash flow relative to assets.']
    };
    const componentEntries=b.components&&typeof b.components==='object'?Object.entries(b.components):[];
    const componentRows=componentEntries.length?componentEntries.map(([key,value])=>{
      const meta=componentMeta[key]||['Model component','One input to the composite screening score.'];
      return `<tr><td><span class="risk-component-name"><b>${esc(key)}</b>${riskInfoTip(meta[1],{side:true,label:`About ${key}`})}</span></td><td><b>${num(value,key==='TATA'?4:3)}</b></td><td>${esc(meta[0])}</td></tr>`;
    }).join(''):'';
    const componentWeights={DSRI:.92,GMI:.528,AQI:.404,SGI:.892,DEPI:.115,SGAI:-.172,LVGI:-.327,TATA:4.679};
    const componentDrivers=componentEntries.map(([key,value])=>{
      const number=Number(value),neutral=key==='TATA'?0:1,impact=(componentWeights[key]||0)*(number-neutral);
      const meta=componentMeta[key]||['Model component','One input to the composite screening score.'];
      return {key,value:number,impact,meta};
    }).filter(item=>Number.isFinite(item.value)).sort((a,z)=>Math.abs(z.impact)-Math.abs(a.impact));
    const flagDrivers=flags.map(flag=>({type:'rule',title:String(flag),copy:'A high-level company rule also needs review.',tone:'caution'}));
    const modelDrivers=componentDrivers.map(item=>({
      type:'model',
      title:`${item.key} · ${item.meta[0]}`,
      copy:`${item.impact>.03?'Raises':item.impact<-.03?'Offsets':'Has limited effect on'} the composite screen. ${item.meta[1]}`,
      tone:item.impact>.03?'caution':item.impact<-.03?'supportive':'neutral',
      value:num(item.value,item.key==='TATA'?4:3)
    }));
    const priorityDrivers=[...flagDrivers,...modelDrivers].slice(0,3);
    const driverRows=priorityDrivers.length?priorityDrivers.map(driver=>`<article class="risk-priority-item ${driver.tone}"><div><span>${driver.type==='rule'?'RULE SIGNAL':'MODEL DRIVER'}</span><b>${esc(driver.title)}</b><p>${esc(driver.copy)}</p></div>${driver.value?`<strong>${esc(driver.value)}</strong>`:''}</article>`).join(''):'<article class="risk-priority-item neutral"><div><span>EVIDENCE STATUS</span><b>No ranked drivers available</b><p>More verified paired inputs are needed before the model can explain the result.</p></div></article>';
    const changeRows=changes.length?changes.map(change=>{
      const periodList=Array.isArray(change.periods)?change.periods:[];
      const label=String(change.metric||'metric').replaceAll('_',' ');
      return `<article class="risk-change-item ${riskChangeTone(change.metric,change.change_pct)}"><div><b>${esc(label)}</b><small>${esc(String(periodList[0]||'Prior period'))} → ${esc(String(periodList[1]||'Current period'))}</small></div><strong>${pct(change.change_pct)}</strong></article>`;
    }).join(''):'<div class="risk-warning-panel caution"><b>Comparable change data unavailable</b>Not enough verified paired periods are available for revenue, income, debt, or cash flow.</div>';
    const signalCopy=flags.length
      ? `<b>${flags.length} rule-based ${flags.length===1?'signal needs':'signals need'} review</b>${flags.map(esc).join(' • ')}`
      : flagged
        ? `<b>M-score review threshold crossed</b>The composite score of ${score} is above the −1.78 review threshold. No additional leverage, revenue-growth, or net-margin rule was triggered.`
        : '<b>No screening warning triggered</b>The M-score and the available leverage, revenue-growth, and net-margin rules did not trigger a warning.';
    const missing=Array.isArray(b.missing_inputs)?b.missing_inputs:[];
    const decisionTitle=!available?'Evidence incomplete':caution?'Review recommended':'No screening flag';
    const decisionSummary=!available
      ? 'The report library does not yet contain enough paired inputs for a complete screen.'
      : flags.length
        ? `${flags.length} additional company ${flags.length===1?'rule needs':'rules need'} review${flagged?', and the M-score is above its review threshold.':'.'}`
        : flagged
          ? 'The M-score is above its review threshold. No additional leverage, revenue-growth, or net-margin rule was triggered.'
          : 'The M-score and the available high-level company rules did not trigger a review warning.';
    const coverage=`${componentEntries.length}/8 inputs ${available?'ready':'available'}`;
    const currentPeriod=periods.length?periods.at(-1):'Unavailable';
    if(out)out.innerHTML=`<section class="risk-financial-result ${tone}">
      <div class="risk-decision-hero">
        <div class="risk-decision-copy"><span class="feature-kicker">${esc(company)} · ACCOUNTING QUALITY</span><div class="risk-decision-title"><h3>${esc(decisionTitle)}</h3><span class="risk-result-badge">${esc(badge)}</span></div><p>${esc(decisionSummary)}</p><small>Investigative screen only—not an accusation, audit opinion, probability, or buy/sell signal.</small><div class="risk-next-actions"><button type="button" class="feature-secondary" data-risk-target="riskEvidenceDetails">Review detailed evidence</button><button type="button" class="feature-primary" data-risk-step-go="2">Continue to core value →</button></div></div>
        <div class="risk-score-card"><span>${riskMetricLabel('M-score','A weighted combination of eight accounting indices. Higher values warrant more investigation; the score is not an audit conclusion.',true)}</span><strong>${score}</strong><small>${available?'review threshold −1.78':'not calculated'}</small></div>
      </div>
      <div class="risk-summary-meta"><span><small>Evidence quality</small><b>${esc(coverage)}</b></span><span><small>Evidence period</small><b>${esc(currentPeriod)}</b></span><span><small>Additional rule checks</small><b>${flags.length?`${flags.length} need review`:'No additional flags'}</b></span></div>
      ${missing.length?`<div class="risk-warning-panel caution"><b>Screen incomplete</b>Missing paired inputs: ${missing.map(esc).join(', ')}.</div>`:''}
      <section class="risk-priority-panel"><div class="risk-panel-heading"><div><h4>What matters most</h4><p>The three largest visible drivers, ranked before the full accounting detail.</p></div><span class="risk-result-badge">Top 3</span></div><div class="risk-priority-grid">${driverRows}</div></section>
      <details id="riskEvidenceDetails" class="risk-evidence-disclosure">
        <summary><span><b>Detailed evidence</b><small>All eight model inputs, same-period movement, and limitations</small></span><em>View details</em></summary>
        <div class="risk-evidence-body">
          <div class="risk-advanced-meta"><article>${riskMetricLabel('Relative screen signal','A monotonic transform of the M-score for comparing screening strength. It is not a calibrated fraud probability.')}<b>${proxy}</b><small>comparison aid only</small></article><article>${riskMetricLabel('Period basis','The reporting periods and basis used for the component calculation.')}<b>${esc(currentPeriod)}</b><small>${esc(b.period_basis||'basis unavailable')} · ${periods.length>1?`${esc(periods[0])} → current`:'comparator unavailable'}</small></article></div>
          <div class="risk-warning-panel${caution?' caution':''}">${signalCopy}</div>
          <div class="risk-evidence-grid">
            <section class="risk-evidence-panel"><div class="risk-panel-heading"><div><h4>Eight-component evidence</h4><p>Open each ⓘ to understand what the input measures.</p></div><span class="risk-result-badge">${componentRows?'8-index model':'Unavailable'}</span></div>${componentRows?`<div class="risk-component-scroll"><table class="table risk-component-table"><thead><tr><th>Index</th><th>Value</th><th>Measures</th></tr></thead><tbody>${componentRows}</tbody></table></div>`:'<div class="risk-warning-panel caution">The verified reports do not yet contain every paired input needed for this table.</div>'}</section>
            <section class="risk-evidence-panel"><div class="risk-panel-heading"><div><h4>Same-period movement</h4><p>Direction versus the report’s matched comparator.</p></div></div><div class="risk-change-list">${changeRows}</div></section>
          </div>
          <details class="risk-model-note"><summary>Method, limitations &amp; correct interpretation</summary><p>${esc(b.note||b.status||'Beneish-style screening is unavailable.')}</p><p>${esc(d.disclaimer||'Fraud screening is an investigative aid, not a legal or audit conclusion.')}</p></details>
        </div>
      </details>
    </section>`;
    $('risk')?.dispatchEvent(new CustomEvent('risk:review-ready'));
  }catch(e){if(out)out.innerHTML=`<section class="risk-financial-result caution"><div class="risk-warning-panel caution"><b>Risk review unavailable</b>${esc(e.message)}</div></section>`;}
}

let valuationCache=null;
function valuationMoney(value,currency='VND'){
  if(value===null||value===undefined||!Number.isFinite(Number(value)))return 'Unavailable';
  const digits=String(currency).toUpperCase()==='VND'?0:2;
  return `${Number(value).toLocaleString(undefined,{minimumFractionDigits:digits,maximumFractionDigits:digits})} ${currency}`;
}
function valuationInputRow(input){
  const shown=input.value===null||input.value===undefined?'Unavailable':`${num(input.value,2)}${input.unit?` ${esc(input.unit)}`:''}`;
  const timing=input.as_of?`as of ${String(input.as_of).slice(0,10)}`:String(input.source||'').toLowerCase().includes('assumption')?'current run':'date unavailable';
  const evidence=[input.source,timing].filter(Boolean).join(' · ');
  return `<li><span>${esc(input.label)}</span><b>${shown}</b><small>${esc(evidence)}</small></li>`;
}
function valuationMethodCard(method,currency){
  const ready=method.status==='available';
  return `<article class="valuation-method ${ready?'available':'unavailable'}"><div class="valuation-method-head"><div><span>${ready?'Calculated':'Unavailable'}</span><h4>${esc(method.name)}</h4></div><strong>${ready?valuationMoney(method.value_per_share,currency):'—'}</strong></div>${ready?`<div class="valuation-method-range"><span>Sensitivity range</span><b>${valuationMoney(method.low,currency)} – ${valuationMoney(method.high,currency)}</b></div>`:''}<p>${esc(method.interpretation||'')}</p><details><summary>Formula, inputs & limitations <span>${ready?num(method.applied_weight_pct,0)+'% blend':'not blended'}</span></summary><div class="valuation-method-detail">${method.formula?`<div class="valuation-formula"><b>Formula</b><span>${esc(method.formula)}</span></div>`:''}<ul>${(method.inputs||[]).map(valuationInputRow).join('')}</ul><div class="valuation-limitations">${(method.limitations||[]).map(x=>`<span>• ${esc(x)}</span>`).join('')}</div></div></details></article>`;
}
function renderDividendOutlook(outlook,currency){
  const schedule=outlook?.schedule||{},window= schedule.next_estimated_window;
  return `<section class="valuation-dividend"><div><div class="assistant-kicker">DIVIDEND OUTLOOK</div><h3>${esc(schedule.cadence||'Schedule unavailable')}</h3><p>${esc(schedule.note||'No usable payment history was returned.')}</p></div><div class="valuation-dividend-kpis"><span><small>Annual dividend / share</small><b>${valuationMoney(outlook?.annual_dividend_per_share,currency)}</b></span><span><small>Trailing yield</small><b>${pct(outlook?.trailing_yield_pct)}</b></span><span><small>Payout ratio</small><b>${pct(outlook?.payout_ratio_pct)}</b></span><span><small>Estimated next window</small><b>${window?`${esc(window.from)} – ${esc(window.to)}`:'Unavailable'}</b></span></div><div class="valuation-warning">${esc(outlook?.warning||'Future dividends are not guaranteed.')}</div></section>`;
}
function renderValuationScenarios(data){
  const currency=data.currency||'VND';
  return `<section class="valuation-decision-section"><div class="valuation-section-head"><div><div class="assistant-kicker">BEAR · BASE · BULL</div><h3>How value changes when assumptions change</h3></div><p>Every scenario recalculates the available valuation methods. Percentages are transparent research weights—not statistically calibrated outcome probabilities.</p></div><div class="valuation-scenario-grid">${(data.scenarios||[]).map(scenario=>`<article class="valuation-scenario ${esc(scenario.key||'base')}"><div class="valuation-scenario-head"><div><span>${esc(scenario.label)}</span><small>${Number(scenario.method_coverage||0)} methods</small></div><div class="valuation-scenario-value"><strong>${valuationMoney(scenario.fair_value,currency)}</strong><em>${pct(scenario.research_weight_pct??scenario.probability_pct)} weight</em></div></div><p>${esc(scenario.description||'')}</p><div class="valuation-scenario-entry"><span>Research entry ≤</span><b>${valuationMoney(scenario.research_entry_price,currency)}</b></div><div class="valuation-scenario-assumptions"><span>Return <b>${pct(scenario.assumptions?.required_return_pct)}</b></span><span>Growth <b>${pct(scenario.assumptions?.near_growth_pct)}</b></span><span>Stable <b>${pct(scenario.assumptions?.terminal_growth_pct)}</b></span><span>P/E <b>${num(scenario.assumptions?.normalized_pe,1)}×</b></span></div><details><summary>Values by method</summary><div>${(scenario.method_values||[]).map(method=>`<span><small>${esc(method.name)}</small><b>${valuationMoney(method.value_per_share,currency)}</b></span>`).join('')||'<span>Unavailable</span>'}</div></details></article>`).join('')}</div></section>`;
}
function renderScenarioAnalysis(data){
  const analysis=data.scenario_analysis||{},currency=data.currency||'VND',p=analysis.research_weights||analysis.probabilities||{};
  if(analysis.status!=='available')return '';
  return `<section class="valuation-risk-reward"><div class="valuation-section-head"><div><div class="assistant-kicker">SCENARIO-WEIGHTED RISK / REWARD</div><h3>${esc(analysis.headline||'Scenario analysis')}</h3></div><span class="pill">${esc(analysis.evidence_label||'Low')} evidence</span></div><div class="valuation-risk-kpis"><div><span>Weighted fair value</span><b>${valuationMoney(analysis.weighted_fair_value,currency)}</b></div><div><span>Weighted entry ≤</span><b>${valuationMoney(analysis.weighted_entry_price,currency)}</b></div><div><span>Expected value gap</span><b class="${Number(analysis.expected_gap_pct)>=0?'up':'down'}">${pct(analysis.expected_gap_pct)}</b></div><div><span>Upside / downside</span><b>${analysis.upside_downside_ratio===null||analysis.upside_downside_ratio===undefined?'Unavailable':num(analysis.upside_downside_ratio,2)+'×'}</b></div></div><div class="valuation-probability-bar" aria-label="Scenario research weights"><i class="bear" style="width:${Number(p.bear)||0}%"></i><i class="base" style="width:${Number(p.base)||0}%"></i><i class="bull" style="width:${Number(p.bull)||0}%"></i></div><div class="valuation-probability-labels"><span><i class="bear"></i>Bear <b>${pct(p.bear)}</b><small>${pct(analysis.bear_return_pct)} vs market</small></span><span><i class="base"></i>Base <b>${pct(p.base)}</b><small>central case</small></span><span><i class="bull"></i>Bull <b>${pct(p.bull)}</b><small>${pct(analysis.bull_return_pct)} vs market</small></span></div><details class="valuation-probability-method"><summary>How were these weights calculated?</summary><p>${esc(analysis.method||'')}</p><p>${esc(analysis.warning||'')}</p></details></section>`;
}
function renderForwardDriverModel(data){
  const model=data.forward_driver_model||{},currency=data.currency||'VND';
  const drivers=(model.drivers||[]).map(driver=>`<article class="valuation-driver ${esc(driver.tone||'unavailable')}"><div><span>${esc(driver.label)}</span><b>${driver.status==='available'?`${num(driver.value,2)} ${esc(driver.unit||'')}`:'Unavailable'}</b></div>${driver.status==='available'?`<div class="valuation-driver-scale"><i></i><em style="left:${Math.max(0,Math.min(100,(Number(driver.score||0)+1)*50))}%"></em></div>`:''}<p>${esc(driver.interpretation||'')}</p><small>${esc(driver.source||'Source unavailable')}${driver.as_of?` · ${esc(String(driver.as_of).slice(0,10))}`:''}</small></article>`).join('');
  const projections=(model.projections||[]).map(row=>`<div><span>${esc(row.label)}</span><b>${row.key==='forward_eps'?valuationMoney(row.value,currency):`${num(row.value,2)} ${esc(row.unit||'')}`}</b><small>${esc(row.basis||'')}</small></div>`).join('');
  return `<section class="valuation-forward-model"><div class="valuation-section-head"><div><div class="assistant-kicker">FORWARD BUSINESS DRIVERS</div><h3>${Number(model.available_drivers||0)} of ${Number(model.total_drivers||0)} drivers available</h3></div><p>${esc(model.method||'')}</p></div><div class="valuation-driver-grid">${drivers}</div>${projections?`<div class="valuation-forward-projections">${projections}</div>`:''}<div class="valuation-forward-warning">${esc(model.warning||'Forward inputs are assumption-sensitive.')}</div></section>`;
}
function renderValuationConfidence(data){
  const quality=data.data_quality||{},components=quality.components||{};
  const componentLabels={method_coverage_pct:'Method coverage',method_agreement_pct:'Model agreement',market_freshness_pct:'Market freshness',input_traceability_pct:'Input traceability'};
  return `<section class="valuation-quality"><div class="valuation-quality-score"><div class="valuation-score-ring" style="--quality:${Math.max(0,Math.min(100,Number(quality.score)||0))}"><div><strong>${Number(quality.score||0)}</strong><span>/100</span></div></div><div><div class="assistant-kicker">DATA CONFIDENCE</div><h3>${esc(quality.label||'Low')} evidence confidence</h3><p>${esc(quality.explanation||'Confidence is unavailable.')}</p></div></div><div class="valuation-quality-components">${Object.entries(components).map(([key,value])=>`<div><span>${esc(componentLabels[key]||key.replaceAll('_',' '))}<b>${num(value,0)}%</b></span><i><em style="width:${Math.max(0,Math.min(100,Number(value)||0))}%"></em></i></div>`).join('')}</div>${quality.warnings?.length?`<div class="valuation-quality-warnings">${quality.warnings.map(warning=>`<span>• ${esc(warning)}</span>`).join('')}</div>`:''}<details class="valuation-source-details"><summary>View source and reporting date for every core input <span>${(data.source_evidence||[]).filter(row=>row.value!==null&&row.value!==undefined).length} available</span></summary><div class="valuation-source-grid">${(data.source_evidence||[]).map(row=>`<article><span>${esc(row.field)}</span><b>${row.value===null||row.value===undefined?'Unavailable':`${num(row.value,2)} ${esc(row.unit||'')}`}</b><small>${esc(row.source||'Source unavailable')}</small><small>${row.as_of?`As of ${esc(String(row.as_of).slice(0,10))}`:'Reporting date unavailable'}</small></article>`).join('')}</div></details></section>`;
}
function renderValuationSensitivity(data){
  const sensitivity=data.sensitivity||{},currency=data.currency||'VND';
  if(sensitivity.status!=='available')return `<section class="valuation-sensitivity unavailable"><div class="valuation-section-head"><div><div class="assistant-kicker">SENSITIVITY</div><h3>DCF sensitivity unavailable</h3></div></div><p>${esc(sensitivity.reason||'Required inputs are missing.')}</p></section>`;
  return `<section class="valuation-sensitivity"><div class="valuation-section-head"><div><div class="assistant-kicker">DCF SENSITIVITY</div><h3>Growth versus required return</h3></div><p>${esc(sensitivity.note||'')}</p></div><div class="valuation-sensitivity-scroll"><table><thead><tr><th>Near growth ↓ / Return →</th>${(sensitivity.columns||[]).map(value=>`<th>${pct(value)}</th>`).join('')}</tr></thead><tbody>${(sensitivity.rows||[]).map(row=>`<tr><th>${pct(row.near_growth_pct)}</th>${(row.values||[]).map(value=>`<td>${valuationMoney(value,currency)}</td>`).join('')}</tr>`).join('')}</tbody></table></div></section>`;
}
function renderInvestmentPlan(data){
  const plan=data.investment_plan||{},currency=data.currency||'VND';
  const values=[plan.deep_value_threshold,plan.preferred_entry_threshold,plan.fair_range_low,plan.fair_value,plan.fair_range_high,plan.overvaluation_threshold,plan.current_price].map(Number).filter(Number.isFinite);
  const scaleMin=values.length?Math.min(...values)*.92:0,scaleMax=values.length?Math.max(...values)*1.08:1;
  const position=value=>Number.isFinite(Number(value))&&scaleMax>scaleMin?Math.max(0,Math.min(100,(Number(value)-scaleMin)/(scaleMax-scaleMin)*100)):null;
  const currentPos=position(plan.current_price),fairPos=position(plan.fair_value);
  const thresholds=[['Deep-value threshold',plan.deep_value_threshold,'deep'],['Preferred entry ≤',plan.preferred_entry_threshold,'entry'],['Fair range low',plan.fair_range_low,'fair-low'],['Base fair value',plan.fair_value,'fair'],['Fair range high',plan.fair_range_high,'fair-high'],['Above-range threshold',plan.overvaluation_threshold,'above']];
  return `<section class="valuation-plan"><div class="valuation-section-head"><div><div class="assistant-kicker">INVESTMENT PLANNING</div><h3>Research price ladder</h3></div><p>Thresholds organize the valuation result; they are not personalized trade instructions.</p></div><div class="valuation-price-track" aria-label="Current price and fair value position"><i class="deep"></i><i class="entry"></i><i class="fair"></i><i class="above"></i>${currentPos===null?'':`<span class="current" style="left:${currentPos}%"><b>Current</b></span>`}${fairPos===null?'':`<span class="modeled" style="left:${fairPos}%"><b>Fair</b></span>`}</div><div class="valuation-price-axis"><span>${valuationMoney(scaleMin,currency)}</span><span>${valuationMoney(scaleMax,currency)}</span></div><div class="valuation-threshold-grid">${thresholds.map(([label,value,tone])=>`<div class="${tone}"><span>${esc(label)}</span><b>${valuationMoney(value,currency)}</b></div>`).join('')}</div><div class="valuation-return-box"><div><span>Illustrative 3-year total return</span><b>${pct(plan.three_year_total_return_pct)}</b></div><div><span>Illustrative annualized return</span><b>${pct(plan.three_year_annualized_return_pct)}</b></div><p>${esc(plan.return_basis||'Return illustration unavailable.')}</p></div><div class="valuation-outlook-grid">${(plan.outlooks||[]).map(outlook=>`<article><span>${esc(outlook.period)}</span><h4>${esc(outlook.title)}</h4><p>${esc(outlook.comment)}</p></article>`).join('')}</div><details class="valuation-review-triggers"><summary>When should this valuation be recalculated?</summary><div>${(plan.review_triggers||[]).map(trigger=>`<span>• ${esc(trigger)}</span>`).join('')}</div></details></section>`;
}
function renderValuation(data){
  const s=data.summary||{},currency=data.currency||'VND',available=s.status==='available';
  const zone=String(s.zone||'insufficient_data').replaceAll('_','-');
  const persistence=data.persistence||{};
  const historyNote=persistence.saved?'This evidence-backed calculation was added to your private valuation history.':persistence.duplicate?'This calculation already exists in your private history.':esc(persistence.reason||'Track the company to monitor future changes.');
  return `<div class="valuation-results"><section class="valuation-summary ${zone}"><div class="valuation-summary-copy"><div class="assistant-kicker">${esc(data.company)} · ${esc(data.ticker)} · CORE VALUE</div><h2>${esc(s.headline||'Valuation unavailable')}</h2><p>${esc(s.research_action||'')}</p></div><div class="valuation-fair"><span>Modeled fair value</span><strong>${valuationMoney(s.fair_value,currency)}</strong><small>${available?`${valuationMoney(s.fair_range_low,currency)} – ${valuationMoney(s.fair_range_high,currency)}`:'Add missing evidence'}</small></div></section><div class="valuation-kpis"><div><span>Market price</span><b>${valuationMoney(data.market?.price,currency)}</b><small>${esc(data.market?.updated_at||'Timestamp unavailable')}</small></div><div><span>Research entry ≤</span><b>${valuationMoney(s.research_entry_price,currency)}</b><small>${num(s.margin_of_safety_pct,0)}% margin of safety</small></div><div><span>Fair-value gap</span><b class="${Number(s.upside_downside_to_fair_pct)>=0?'up':'down'}">${pct(s.upside_downside_to_fair_pct)}</b><small>fair value vs current price</small></div><div><span>Data confidence</span><b>${Number(data.data_quality?.score||0)} / 100</b><small>${esc(data.data_quality?.label||'Low')} evidence confidence</small></div></div><div class="valuation-watch-actions"><div><b>Private monitoring</b><span>${historyNote}</span></div><button type="button" data-action="watchlist-add" data-company="${esc(data.company)}">☆ Track company</button><button type="button" class="secondary" data-action="watchlist-history" data-company="${esc(data.company)}">View history</button></div>${renderScenarioAnalysis(data)}${renderValuationScenarios(data)}${renderForwardDriverModel(data)}${renderInvestmentPlan(data)}${renderValuationConfidence(data)}${renderValuationSensitivity(data)}<section class="valuation-horizon"><div><span>Review / holding horizon</span><b>${esc(s.holding_review_horizon||'Unavailable')}</b></div><div><span>Model range, not a promise</span><p>Recalculate after material earnings, cash-flow, capital, share-count, or dividend changes.</p></div></section><div class="valuation-method-grid">${(data.methods||[]).map(method=>valuationMethodCard(method,currency)).join('')}</div><section class="valuation-comments"><div><div class="assistant-kicker">GENERAL COMMENTS</div><h3>How to read the result</h3></div><ul>${(s.comments||[]).map(comment=>`<li>${esc(comment)}</li>`).join('')||'<li>Not enough evidence is available for a valuation comment.</li>'}</ul></section>${renderDividendOutlook(data.dividend_outlook,currency)}<section class="valuation-assumptions"><div><div class="assistant-kicker">VISIBLE ASSUMPTIONS</div><h3>What drives this estimate</h3></div><div><span>Required return <b>${pct(data.assumptions?.required_return_pct)}</b></span><span>Near growth <b>${pct(data.assumptions?.near_growth_pct)}</b></span><span>Stable growth <b>${pct(data.assumptions?.terminal_growth_pct)}</b></span><span>Forecast <b>${num(data.assumptions?.forecast_years,0)} years</b></span><span>Normalized P/E <b>${num(data.assumptions?.normalized_pe,1)}×</b></span></div><p>${esc(data.assumptions?.growth_source||'')}.</p></section><div class="valuation-disclaimer">${(data.limitations||[]).map(x=>`<span>• ${esc(x)}</span>`).join('')}</div><section class="risk-step-complete"><div><span>STAGE 2 COMPLETE</span><b>Core value is ready. Trade sizing is a separate decision.</b></div><button type="button" class="feature-primary" data-action="view" data-view="tradePlanner">Open Trade Planner →</button></section></div>`;
}
function valuationAssumptions(){
  const optional=$('valuationNearGrowth')?.value;
  return {required_return_pct:$('valuationRequiredReturn')?.value,near_growth_pct:optional===''?null:optional,terminal_growth_pct:$('valuationTerminalGrowth')?.value,forecast_years:$('valuationYears')?.value,normalized_pe:$('valuationPE')?.value,margin_of_safety_pct:$('valuationMargin')?.value};
}
function valuationInputs(){
  const values={price:$('valuationPrice')?.value,shares_outstanding:$('valuationShares')?.value,free_cash_flow:$('valuationFCF')?.value,eps:$('valuationEPS')?.value,dividend_rate:$('valuationDividend')?.value,book_value_per_share:$('valuationBook')?.value,currency:$('valuationCurrency')?.value};
  return Object.fromEntries(Object.entries(values).filter(([,value])=>value!==undefined&&value!==null&&String(value).trim()!==''));
}
function valuationDrivers(){
  const values={revenue_growth_pct:$('valuationRevenueGrowth')?.value,eps_growth_pct:$('valuationEPSGrowth')?.value,margin_change_pct_points:$('valuationMarginChange')?.value,net_debt_to_ebitda:$('valuationNetDebt')?.value,return_on_equity_pct:$('valuationROE')?.value};
  return Object.fromEntries(Object.entries(values).filter(([,value])=>value!==undefined&&value!==null&&String(value).trim()!==''));
}
async function loadValuation(companyOverride=null){
  const company=String(companyOverride||$('valuationCompany')?.value||'').trim().toUpperCase();if(!company)return;
  if($('valuationCompany'))$('valuationCompany').value=company;
  const out=$('valuationOut');if(out)out.innerHTML='<div class="valuation-loading"><span></span><div><b>Estimating core value</b><small>Loading cash flow, earnings, dividends, shares and verified book value…</small></div></div>';
  try{
    const data=await getJSON(`/api/valuation/${encodeURIComponent(company)}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({assumptions:valuationAssumptions(),inputs:valuationInputs(),drivers:valuationDrivers()}),cancelKey:'company-valuation',dedupe:false});
    valuationCache=data;if(out)out.innerHTML=renderValuation(data);
    document.querySelectorAll('.overview-core-value-mount').forEach(mount=>mount.innerHTML=renderOverviewValuation(data));
    loadAlertSummary();
  }catch(error){if(error?.name!=='AbortError'&&out)out.innerHTML=`<div class="notice bad">${esc(error.message)}</div>`;}
}
function renderOverviewValuation(data){
  const s=data.summary||{},weighted=data.scenario_analysis||{},currency=data.currency||'VND';
  const scenarios=Object.fromEntries((data.scenarios||[]).map(row=>[row.key,row]));
  return `<div class="overview-valuation-summary"><div><div class="assistant-kicker">DECISION CENTER · ${esc(data.ticker||data.company)}</div><h3>${esc(s.headline||'Valuation unavailable')}</h3><p>${esc(s.research_action||'')}</p></div><div class="overview-valuation-numbers"><span><small>Bear · ${pct(scenarios.bear?.research_weight_pct??scenarios.bear?.probability_pct)}</small><b>${valuationMoney(scenarios.bear?.fair_value,currency)}</b></span><span><small>Base · ${pct(scenarios.base?.research_weight_pct??scenarios.base?.probability_pct)}</small><b>${valuationMoney(scenarios.base?.fair_value,currency)}</b></span><span><small>Bull · ${pct(scenarios.bull?.research_weight_pct??scenarios.bull?.probability_pct)}</small><b>${valuationMoney(scenarios.bull?.fair_value,currency)}</b></span><span><small>Weighted value</small><b>${valuationMoney(weighted.weighted_fair_value,currency)}</b></span><span><small>Current price</small><b>${valuationMoney(data.market?.price,currency)}</b></span><span><small>Evidence</small><b>${esc(weighted.evidence_label||'Low')}</b></span><div class="overview-valuation-actions"><button type="button" data-action="watchlist-add" data-company="${esc(data.company)}">☆ Track</button><button type="button" data-action="valuation-open-risk">Open full valuation →</button></div></div></div>`;
}
async function loadOverviewValuation(){
  const company=$('overviewCompany')?.value.trim().toUpperCase();if(!company)return;
  if(overviewMode!==3)setOverviewMode(3);
  document.querySelectorAll('.overview-core-value-mount').forEach(mount=>mount.innerHTML='<div class="valuation-loading"><span></span><div><b>Calculating core value</b><small>Loading valuation inputs…</small></div></div>');
  try{
    const data=await getJSON(`/api/valuation/${encodeURIComponent(company)}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({assumptions:{}}),cancelKey:'overview-valuation',dedupe:false});
    valuationCache=data;document.querySelectorAll('.overview-core-value-mount').forEach(mount=>mount.innerHTML=renderOverviewValuation(data));
    loadAlertSummary();
  }catch(error){if(error?.name!=='AbortError')document.querySelectorAll('.overview-core-value-mount').forEach(mount=>mount.innerHTML=`<div class="notice bad">${esc(error.message)}</div>`);}
}
function openValuationRisk(){
  const company=valuationCache?.company||$('overviewCompany')?.value.trim().toUpperCase();
  showView('risk');if($('riskCompany'))$('riskCompany').value=company;if($('valuationCompany'))$('valuationCompany').value=company;
  if(valuationCache&&$('valuationOut'))$('valuationOut').innerHTML=(featureControllers.valuation?.render||renderValuation)(valuationCache);else runFeatureController('valuation',loadValuation,company);
  $('risk')?.dispatchEvent(new CustomEvent('risk:open-step',{detail:{step:2,unlock:true}}));
  $('valuationLabTitle')?.scrollIntoView({behavior:'smooth',block:'start'});
}


function money0(v){if(v==null||!Number.isFinite(Number(v)))return "Unavailable";const n=Number(v),a=Math.abs(n);if(a>=1e12)return `${(n/1e12).toFixed(3)}T VND`;if(a>=1e9)return `${(n/1e9).toFixed(3)}B VND`;if(a>=1e6)return `${(n/1e6).toFixed(1)}M VND`;return `${n.toLocaleString()} VND`;}
function renderTradingRisk(d){
  if(d.status!=="ok")return `<section class="risk-trade-result"><div class="risk-plan-warning"><h4>Trading-risk plan unavailable</h4><p>${esc(d.status||"Trading risk analysis unavailable.")}${d.error?` ${esc(d.error)}`:""}</p></div></section>`;
  const sp=d.stop_plan||{}, rb=d.risk_budget||{}, ex=d.expectancy||{}, dd=d.peak_to_trough||{}, mae=d.forward_mae||{}, rz=d.reference_zones||{};
  const hold=d.holdout||{};
  const holdoutWin=hold.win_probability==null?null:Number(hold.win_probability)*100;
  const holdoutLoss=hold.loss_probability==null?null:Number(hold.loss_probability)*100;
  const holdoutResolved=hold.resolved_rate==null?null:Number(hold.resolved_rate)*100;
  return `<section class="risk-trade-result">
    <div class="risk-trade-hero">
      <div class="risk-trade-hero-main"><span class="feature-kicker">${esc(d.ticker||'')} · ${esc((d.side||'long').toUpperCase())} · HISTORICAL PLAN</span><h3>${esc(sp.method||'Historical risk model')}</h3><p>The engine compares volatility, drawdown, adverse excursion, and market structure, then ranks eligible stop distances by in-sample expectancy.</p></div>
      <div class="risk-trade-hero-stat"><span>ENTRY</span><b>${money0(d.entry_price)}</b><small>${d.entry_price===d.current_price?'latest available price':'your planning input'}</small></div>
      <div class="risk-trade-hero-stat"><span>PLANNED STOP</span><b>${money0(sp.stop_price)}</b><small>${pct(sp.stop_distance_pct)} from entry</small></div>
      <div class="risk-trade-hero-stat"><span>${num(sp.target_r_multiple,1)}R TARGET</span><b>${money0(sp.target_price)}</b><small>${pct(sp.target_distance_pct)} from entry</small></div>
    </div>
    <div class="risk-trade-section-head"><h4>Historical outcome evidence</h4><p>${num(d.horizon_days,0)}-day path · ${num(d.data_points,0)} market observations</p></div>
    <div class="risk-trade-metrics">
      <article class="risk-trade-metric">${riskMetricLabel('Expected loss','Historical stop-hit probability multiplied by the planned stop distance. It is an average path estimate, not the maximum possible loss.')}<b>${pct(ex.expected_loss_pct)}</b><small>${money0(ex.expected_loss_amount)} with current size</small></article>
      <article class="risk-trade-metric">${riskMetricLabel('Expected gain','Historical target-hit probability multiplied by the planned target distance.')}<b>${pct(ex.expected_gain_pct)}</b><small>${money0(ex.expected_gain_amount)} with current size</small></article>
      <article class="risk-trade-metric">${riskMetricLabel('Expectancy','Average modeled return per tested path: probability-weighted gain minus probability-weighted loss.')}<b>${pct(ex.expectancy_pct)}</b><small>per historical setup</small></article>
      <article class="risk-trade-metric">${riskMetricLabel('Win / loss','Among historical paths that reached either the target or stop, the share that hit each level first.')}<b>${pct(ex.win_probability_pct)} / ${pct(ex.loss_probability_pct)}</b><small>${pct(ex.resolved_rate_pct)} paths resolved</small></article>
      <article class="risk-trade-metric">${riskMetricLabel('Drawdown P75','The 75th percentile depth of completed peak-to-trough drawdown episodes.')}<b>${pct(dd.p75)}</b><small>${num(dd.episodes,0)} drawdown episodes</small></article>
      <article class="risk-trade-metric">${riskMetricLabel('Forward MAE P80','The 80th percentile maximum adverse excursion over the chosen holding horizon.')}<b>${pct(mae.p80)}</b><small>adverse move after entry</small></article>
      <article class="risk-trade-metric">${riskMetricLabel('ATR14','Fourteen-session Average True Range, a measure of recent price movement and gaps.')}<b>${money0(d.atr14)}</b><small>${pct(d.atr14_pct)} of current price</small></article>
      <article class="risk-trade-metric">${riskMetricLabel('Training sample','Historical forward paths evaluated when ranking the stop candidates.')}<b>${num(ex.sample_size,0)} paths</b><small>unresolved paths are disclosed</small></article>
    </div>
    <div class="risk-trade-section-head"><h4>Fixed Fractional position size</h4><p>Position size appears only when account equity is supplied.</p></div>
    <div class="risk-sizing-kpis">
      <article>${riskMetricLabel('Risk budget','Account equity multiplied by the selected risk-per-trade percentage.')}<b>${money0(rb.risk_amount)}</b><small>${pct(rb.risk_pct)} of ${money0(rb.account_equity)}</small></article>
      <article>${riskMetricLabel('Position units','Risk budget divided by the planned loss per unit. Fractional units are rounded for display only.')}<b>${rb.position_units==null?'Unavailable':`${num(rb.position_units,0)} units`}</b><small>based on the planned stop</small></article>
      <article>${riskMetricLabel('Position value','Estimated units multiplied by the planning entry price.')}<b>${money0(rb.position_value)}</b><small>before fees and slippage</small></article>
      <article>${riskMetricLabel('Risk per unit','Absolute currency distance between the entry and planned stop.')}<b>${money0(rb.per_unit_risk)}</b><small>entry-to-stop distance</small></article>
    </div>
    <div class="risk-trade-lower">
      <section class="risk-reference-card"><h4>Market-structure references</h4><table class="table"><thead><tr><th>Reference</th><th>Price / evidence</th></tr></thead><tbody><tr><td>20-day support</td><td>${money0(rz.support20)}</td></tr><tr><td>60-day support</td><td>${money0(rz.support60)}</td></tr><tr><td>20-day resistance</td><td>${money0(rz.resistance20)}</td></tr><tr><td>60-day resistance</td><td>${money0(rz.resistance60)}</td></tr><tr><td>Holdout win / loss</td><td>${pct(holdoutWin)} / ${pct(holdoutLoss)}</td></tr><tr><td>Holdout resolved</td><td>${pct(holdoutResolved)} · ${num(hold.sample_size,0)} paths</td></tr></tbody></table></section>
      <aside class="risk-plan-warning"><h4>Use the plan as a boundary, not a promise</h4><p>${esc(d.warning||'Historical outcomes do not guarantee future results. Gaps, liquidity, and slippage can exceed the planned stop.')}</p></aside>
    </div>
  </section>`;
}
async function loadTradingRisk(){
  const company=$("tradeCompany")?.value.trim().toUpperCase() || $("riskCompany")?.value.trim().toUpperCase();
  if(!company)return;
  const qs=new URLSearchParams();
  const entry=$("tradeEntry")?.value; const equity=$("tradeEquity")?.value;
  if(entry)qs.set("entry",entry); if(equity)qs.set("equity",equity);
  qs.set("risk_pct",$("tradeRiskPct")?.value||"1");
  qs.set("target_r",$("tradeTargetR")?.value||"2");
  qs.set("horizon",$("tradeHorizon")?.value||"20");
  qs.set("side",$("tradeSide")?.value||"long");
  $("tradingRiskOut").innerHTML='<section class="risk-empty-state compact"><span>CALCULATING HISTORICAL RISK</span><h3>Testing stop and target paths…</h3><p>Comparing drawdown, adverse excursion, volatility, market structure, and expectancy.</p></section>';
  try{const d=await getJSON(`/api/risk/trading/${encodeURIComponent(company)}?${qs.toString()}`);$("tradingRiskOut").innerHTML=renderTradingRisk(d);}catch(e){$("tradingRiskOut").innerHTML=`<section class="risk-trade-result"><div class="risk-plan-warning"><h4>Trading-risk plan unavailable</h4><p>${esc(e.message)}</p></div></section>`;}
}
async function loadNews(){const company=$("newsCompany").value.trim().toUpperCase();if(!company)return;try{const d=await getJSON(`/api/news?company=${encodeURIComponent(company)}`);$("newsOut").innerHTML=`<div class="card">${d.items?.length?d.items.map(x=>`<div class="news"><a href="${esc(safeHttpUrl(x.link))}" target="_blank" rel="noopener noreferrer">${esc(x.title)}</a><small>${esc(x.source)} · ${esc(x.published)}</small></div>`).join(""):`<div class="notice">${esc(d.error||"No news found.")}</div>`}</div>`;}catch(e){$("newsOut").innerHTML=`<div class="card notice">${esc(e.message)}</div>`;}}

async function waitForJob(job,onProgress){for(let attempt=0;attempt<240;attempt++){const data=await getJSON(`/api/jobs/${encodeURIComponent(job.id)}`);const current=data.job||{};if(onProgress)onProgress(current);if(current.status==='complete')return current.result||{};if(current.status==='failed')throw new Error(current.error||'Background task failed.');await new Promise(resolve=>setTimeout(resolve,1000));}throw new Error('The task is still running. Check again shortly.');}
function applyScanResult(d){const again=d.rescanned?.length||0;const restored=d.snapshot_restored?.length||0;const archived=d.snapshots_archived?.length||0;const pieces=[`Indexed ${d.documents||0} reports and ${d.observations||0} extracted observations`];if(restored)pieces.push(`reused ${restored} saved scan${restored===1?"":"s"}`);if(again)pieces.push(`reprocessed ${again}`);if(archived)pieces.push(`preserved ${archived} previous version${archived===1?"":"s"}`);if(Array.isArray(d.companies)){renderCompanyList(d.companies);renderGuardian({companies:d.companies,industries:[...new Set(d.companies.map(x=>x.industry))],failed:d.failed});}return pieces.join(" · ")+".";}
async function scan(){$("scanStatus").textContent="Scanning reports in the background…";try{const queued=await getJSON("/api/scan",{method:"POST"});const d=await waitForJob(queued.job,job=>{$("scanStatus").textContent=job.status==='queued'?"Scan queued…":"Scanning reports in the background…";});$("scanStatus").textContent=applyScanResult(d);}catch(e){$("scanStatus").textContent=e.message;}}
async function uploadReport(){const file=$("reportFile").files[0];if(!file){$("learnOut").innerHTML=`<div class="card notice">Choose a report first.</div>`;return;}const f=new FormData();f.append("file",file);f.append("industry",$("upIndustry").value);f.append("company",$("upCompany").value);try{const response=await secureFetch("/api/upload",{method:"POST",body:f});const data=await response.json();if(!response.ok)throw new Error(data.error);$("learnOut").innerHTML=`<div class="card notice good">Saved <b>${esc(data.saved_to)}</b>. Secure validation passed; indexing is continuing in the background.</div>`;const result=await waitForJob(data.job);$("learnOut").innerHTML=`<div class="card notice good">Saved <b>${esc(data.saved_to)}</b>. ${esc(applyScanResult(result))}</div>`;}catch(e){$("learnOut").innerHTML=`<div class="card notice">${esc(e.message)}</div>`;}}
async function uploadChart(){const file=$("chartFile").files[0],company=$("stockCompany").value.trim().toUpperCase();if(!file||!company){$("stockOut").innerHTML=`<div class="card notice">Choose a chart image and enter the company ticker.</div>`;return;}const f=new FormData();f.append("file",file);f.append("company",company);try{const r=await secureFetch("/api/chart",{method:"POST",body:f});const d=await r.json();if(!r.ok)throw new Error(d.error);$("stockOut").innerHTML=renderStock(d.result)+`<div class="card"><p>The chart was stored as supplementary evidence. The statistical model still uses historical market data rather than inventing values from the image.</p></div>`;}catch(e){$("stockOut").innerHTML=`<div class="card notice">${esc(e.message)}</div>`;}}
function renderGuardian(data){const companies=data.companies||[],enough=companies.filter(x=>x.reports>=2).length,failed=(data.failed||[]).length;$("guardianOut").innerHTML=`<div class="dashboard">${metricCard("Companies discovered",companies.length)}${metricCard("With 2+ reports",enough)}${metricCard("Industries",(data.industries||[]).length)}${metricCard("Scan errors",failed)}</div><div class="notice">The guardian blocks false confidence: missing financial fields become “Unavailable”, and statistical models should become more useful only as your historical dataset grows.</div>${failed?`<h3>Files that need attention</h3>${data.failed.slice(0,8).map(x=>`<div class="notice">${esc(x.file)}<br><span class="data-note">${esc(x.reason)}</span></div>`).join("")}`:""} `;}
function assistantMessageHtml(role,text){
  const safe=esc(text).replace(/\n/g,"<br>");
  const meta=role==='user'?'You':'Financial AI';
  return `<div class="assistant-message ${role}"><div class="message-meta">${meta}</div><div>${safe}</div></div>`;
}
function clearAssistant(){const box=$("assistantMessages");if(!box)return;box.innerHTML=assistantMessageHtml('assistant',"Hello. I’m Financial AI. Tell me a company, metric, or research task and I’ll guide you from the evidence in your library.");}
async function sendAssistant(){
  const input=$("assistantInput"),box=$("assistantMessages"); if(!input||!box)return;
  const question=input.value.trim(); if(!question)return;
  box.insertAdjacentHTML("beforeend",assistantMessageHtml('user',question));
  input.value="";
  box.insertAdjacentHTML("beforeend",assistantMessageHtml('assistant',"Researching your local financial evidence…"));
  const thinking=[...box.querySelectorAll('.assistant-message.assistant')].at(-1);
  if(thinking)thinking.classList.add('thinking');
  box.scrollTop=box.scrollHeight;
  try{
    const r=await secureFetch("/api/ask",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({question})});
    const d=await r.json();
    if(!r.ok||d.success===false)throw new Error(d.error||"Assistant request failed.");
    thinking?.remove();
    box.insertAdjacentHTML("beforeend",assistantMessageHtml('assistant',d.answer||"No answer returned."));
  }catch(e){
    thinking?.remove();
    box.insertAdjacentHTML("beforeend",assistantMessageHtml('assistant',`I couldn't complete that request. ${e.message}`));
  }
  box.scrollTop=box.scrollHeight;
}
function usePrompt(text){
  const input=$("assistantInput");
  if(!input)return;
  input.value=text;
  input.focus();
  sendAssistant();
}

async function loadGuardian(){try{const d=await getJSON("/api/guardian");$("guardianOut").innerHTML=`<div class="dashboard">${metricCard("Guardian status",d.status)}${metricCard("Companies",d.companies.length)}${metricCard("Library reports",d.companies.reduce((s,x)=>s+x.reports,0))}${metricCard("Checks passed",d.checks.filter(x=>x.ok).length+"/"+d.checks.length)}</div><div class="notice">${esc(d.recommendation)}</div>${d.checks.map(x=>`<div class="signal"><div class="arrow ${x.ok?"up":"down"}">${x.ok?"✓":"!"}</div><div><b>${esc(x.name)}</b><div class="muted">${esc(x.message)}</div></div></div>`).join("")}`;}catch(e){$("guardianOut").innerHTML=`<div class="card notice">${esc(e.message)}</div>`;}}

function dashboardChart(history){
  const vals=(history||[]).filter(x=>x&&x.value!=null&&Number.isFinite(Number(x.value))).slice(-8);
  if(vals.length<2)return `<div class="chart-empty">Not enough historical data yet.</div>`;
  const W=620,H=180,P=20,nums=vals.map(x=>Number(x.value)),min=Math.min(...nums),max=Math.max(...nums),span=max-min||1;
  const pts=vals.map((v,i)=>`${(P+i/(vals.length-1)*(W-2*P)).toFixed(1)},${(H-P-(Number(v.value)-min)/span*(H-2*P)).toFixed(1)}`).join(' ');
  return `<svg viewBox="0 0 ${W} ${H}" aria-label="Historical revenue trend"><line x1="${P}" y1="${H-P}" x2="${W-P}" y2="${H-P}" class="axis"/><polyline points="${pts}" class="trend-line"/>${vals.map((v,i)=>{const x=P+i/(vals.length-1)*(W-2*P),y=H-P-(Number(v.value)-min)/span*(H-2*P);return `<circle cx="${x}" cy="${y}" r="4" class="trend-point"/>`;}).join('')}</svg><div class="chart-labels"><span>${esc(chartPeriod(vals[0].period_end)||vals[0].year)}</span><span>${esc(chartPeriod(vals.at(-1).period_end)||vals.at(-1).year)}</span></div>`;
}

let worldMarketItems=[];
let worldMarketOffset=0;
let worldMarketTimer=null;
let worldMarketDailyInFlight=false;
let worldMarketRealtimeInFlight=false;
let dashboardLoadPromise=null;
let dashboardInitialized=false;

function _worldMarketCard(item){
  const latest=item.latest?.value;
  const ch=item.change_pct;
  const cls=ch==null?'flat':Number(ch)>0?'up':Number(ch)<0?'down':'flat';
  const sign=ch==null?'':Number(ch)>0?'↑':Number(ch)<0?'↓':'→';
  const points=item.points||[];
  const chart=_miniMarketChart(points, cls);
  return `<article class="world-market-card ${item.success===false?'is-unavailable':''}">
    <div class="world-market-head"><div><span class="world-market-region">${esc(item.region||'Market')}</span><h3>${esc(item.label||item.symbol||'Index')}</h3></div><span class="world-market-status"><i></i>${item.success===false?'unavailable':'live'}</span></div>
    <div class="world-market-value-row"><strong>${latest==null?'Unavailable':Number(latest).toLocaleString(undefined,{maximumFractionDigits:2})}</strong><span class="${cls}">${latest==null?'':`${sign} ${Number(ch).toFixed(2)}%`}</span></div>
    ${chart}
    <div class="world-market-foot"><span>${esc(item.intraday?'live · 15m':'graph · daily')}</span><span>${item.success===false?'Data unavailable':esc(_relativeMarketTime(item.latest?.date))}</span></div>
  </article>`;
}
function _relativeMarketTime(value){
  if(!value)return '—';
  const d=new Date(value); if(Number.isNaN(d.getTime()))return String(value);
  return d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
}
function _miniMarketChart(points, cls){
  const vals=(points||[]).filter(x=>x&&x.value!=null&&Number.isFinite(Number(x.value))).slice(-42);
  if(vals.length<2)return `<div class="world-market-empty">Waiting for market history…</div>`;
  const W=320,H=82,P=5,nums=vals.map(x=>Number(x.value)),min=Math.min(...nums),max=Math.max(...nums),span=max-min||1;
  const y=v=>H-P-(Number(v)-min)/span*(H-2*P);
  const pts=vals.map((v,i)=>`${(P+i/(vals.length-1)*(W-2*P)).toFixed(1)},${y(v.value).toFixed(1)}`).join(' ');
  const area=`${P},${H-P} ${pts} ${W-P},${H-P}`;
  const last=vals.at(-1); const first=vals[0]; const delta=Number(last.value)-Number(first.value);
  return `<svg class="world-market-chart ${cls}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-label="Market trend chart">
    <path d="M ${area}" class="world-market-area"/>
    <polyline points="${pts}" class="world-market-line"/>
    <line x1="${P}" y1="${H-P}" x2="${W-P}" y2="${H-P}" class="world-market-axis"/>
    <circle cx="${W-P}" cy="${y(last.value).toFixed(1)}" r="4" class="world-market-point"/>
  </svg>`;
}
function renderMarketPerformance(){
  const box=$('marketPerformanceMount'); if(!box)return;
  const item=worldMarketItems.find(x=>x.symbol==='^VNINDEX')||worldMarketItems[0];
  if(!item){box.innerHTML='<div class="market-strip-loading">Market performance unavailable.</div>';return;}
  const pts=(item.points||[]).filter(x=>x&&x.value!=null&&Number.isFinite(Number(x.value))).slice(-72);
  const latest=item.latest?.value, ch=item.change_pct;
  const W=860,H=250,P=34, nums=pts.map(x=>Number(x.value)), min=Math.min(...nums,latest||0), max=Math.max(...nums,latest||0), span=max-min||1;
  const y=v=>H-P-(Number(v)-min)/span*(H-2*P);
  const svg=pts.length>1?`<svg class="main-market-chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><line x1="${P}" y1="${H-P}" x2="${W-P}" y2="${H-P}" class="chart-axis"/><polyline points="${pts.map((v,i)=>`${(P+i/(pts.length-1)*(W-2*P)).toFixed(1)},${y(v.value).toFixed(1)}`).join(' ')}" class="chart-line"/><circle cx="${W-P}" cy="${y(pts.at(-1).value).toFixed(1)}" r="5" class="chart-point"/></svg>`:'<div class="chart-empty">Not enough historical observations yet.</div>';
  box.innerHTML=`<div class="section-head-row market-performance-head"><div><div class="assistant-kicker">MARKET PERFORMANCE</div><h3>${esc(item.label||'Market')}</h3><p>Daily historical graph with the latest quote shown immediately after the chart loads.</p></div><div class="period-tabs"><button class="active">1D</button><button>5D</button><button>1M</button><button>3M</button><button>6M</button><button>YTD</button><button>1Y</button><button>5Y</button></div></div><div class="market-value-row"><strong>${latest==null?'Unavailable':Number(latest).toLocaleString(undefined,{maximumFractionDigits:2})}</strong><span class="${ch>0?'up':ch<0?'down':'flat'}">${ch==null?'':(ch>0?'↑ ':'↓ ')+Number(ch).toFixed(2)+'%'}</span></div>${svg}<div class="market-summary-row"><span><small>Open</small><b>${item.open==null?'Unavailable':num(item.open,2)}</b></span><span><small>High</small><b class="up">${item.high==null?'Unavailable':num(item.high,2)}</b></span><span><small>Low</small><b class="down">${item.low==null?'Unavailable':num(item.low,2)}</b></span><span><small>Prev Close</small><b>${item.prev_close==null?'Unavailable':num(item.prev_close,2)}</b></span><span><small>Volume</small><b>${item.volume==null?'Unavailable':num(item.volume,0)}</b></span></div>`;
}
function renderWorldMarketStrip(data){
  worldMarketItems=data.markets||[];
  setTimeout(renderMarketPerformance,0);
  if(!worldMarketItems.length)return `<div class="card market-strip-card"><div class="notice">Global market feeds are currently unavailable.</div></div>`;
  const visible=[];
  for(let i=0;i<4;i++) visible.push(worldMarketItems[(worldMarketOffset+i)%worldMarketItems.length]);
  const updated=data.updated_at?new Date(data.updated_at*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'}):'—';
  return `<section class="market-strip-card">
    <div class="market-strip-head"><div><div class="assistant-kicker">WORLD MARKETS · LIVE CONTEXT</div><h2>Market pulse</h2><p>Daily market graphs render first; live quote changes refresh immediately afterward while the Dashboard is open.</p></div><div class="market-strip-meta"><span><i></i> Live feed</span><span>Updated ${esc(updated)}</span></div></div>
    <div class="market-carousel"><button class="market-arrow left" type="button" aria-label="Previous markets" data-action="shift-markets" data-direction="-1">‹</button><div class="world-market-grid">${visible.map(_worldMarketCard).join('')}</div><button class="market-arrow right" type="button" aria-label="Next markets" data-action="shift-markets" data-direction="1">›</button></div>
    <div class="market-carousel-footer"><span>${Math.min(4,worldMarketItems.length)} of ${worldMarketItems.length} markets</span><span>Use the arrows to browse global exchanges</span></div>
  </section>`;
}
function shiftWorldMarkets(direction){
  if(!worldMarketItems.length)return;
  worldMarketOffset=(worldMarketOffset+direction+worldMarketItems.length)%worldMarketItems.length;
  const mount=$('worldMarketMount'); if(mount)mount.innerHTML=renderWorldMarketStrip({markets:worldMarketItems,updated_at:worldMarketItems[0]?.updated_at||null});
}
function scheduleWorldMarkets(seconds=60){
  if(worldMarketTimer)clearTimeout(worldMarketTimer);
  worldMarketTimer=setTimeout(()=>{if($('overview')?.classList.contains('active'))loadWorldMarkets(false,'intraday');},Math.max(30,Number(seconds||60))*1000);
}
async function loadWorldMarkets(force=false, mode="intraday"){
  if(mode==="intraday" && worldMarketRealtimeInFlight)return;
  if(mode==="daily" && worldMarketDailyInFlight)return;
  if(mode==="daily")worldMarketDailyInFlight=true; else worldMarketRealtimeInFlight=true;
  try{
    const qs=`?mode=${encodeURIComponent(mode)}${force?'&force=1':''}`;
    const d=await getJSON(`/api/world-markets${qs}`);
    const incoming=d.markets||[];
    if(mode==="daily"||!worldMarketItems.length){
      worldMarketItems=incoming;
      const mount=$('worldMarketMount');if(mount)mount.innerHTML=renderWorldMarketStrip(d);
    }else{
      const bySym=new Map(incoming.map(x=>[x.symbol,x]));
      worldMarketItems=worldMarketItems.map(old=>{const fresh=bySym.get(old.symbol);return fresh?{...old,...fresh,points:(fresh.points&&fresh.points.length?fresh.points:old.points)}:old;});
      const mount=$('worldMarketMount');if(mount)mount.innerHTML=renderWorldMarketStrip({...d,markets:worldMarketItems});
    }
    if(worldMarketOffset>=worldMarketItems.length)worldMarketOffset=0;
    scheduleWorldMarkets(d.refresh_seconds||60);
  }catch(e){if(mode==="daily"){const mount=$('worldMarketMount');if(mount)mount.innerHTML=`<section class="market-strip-card"><div class="market-strip-loading">${esc(e.message)}</div></section>`;}scheduleWorldMarkets(60);}
  finally{if(mode==="daily")worldMarketDailyInFlight=false; else worldMarketRealtimeInFlight=false;}
}

/* Macro market intelligence: isolated state, cache-safe initialization, and impact-first rendering. */
window.SolvAIMacroNews = window.SolvAIMacroNews || {
  items: [],
  filter: "All",
  timer: null
};

function _macroImpactStars(score){
  const n = Math.max(1, Math.min(5, Math.round(Number(score) || 1)));
  return "★".repeat(n) + "☆".repeat(5-n);
}

function _macroImpactLabel(item){
  const score = Number(item?.impact_score);
  if (Number.isFinite(score)) {
    if (score >= 4.5) return "Very high";
    if (score >= 3.6) return "High";
    if (score >= 2.7) return "Medium";
    if (score >= 1.8) return "Low";
  }
  return item?.impact || "Low";
}

function renderMacroNewsItems(){
  const box=$("macroNewsItems"); if(!box)return;
  const state = window.SolvAIMacroNews;
  const filtered=(state.items||[])
    .filter(x=>state.filter==="All"||x.category===state.filter)
    .slice(0,6);

  box.innerHTML = filtered.length
    ? filtered.map(x=>{
        const label=_macroImpactLabel(x);
        const score=Math.max(1,Math.min(5,Math.round(Number(x.impact_score)||1)));
        const effects=Array.isArray(x.potential_effect)?x.potential_effect.slice(0,3):[];
        return `<article class="macro-news-item">
          <div class="macro-news-top">
            <span class="macro-news-impact ${label.toLowerCase().replace(/\s+/g,'-')}" title="Research impact score">
              ${esc(label)} <span aria-hidden="true">${_macroImpactStars(score)}</span>
            </span>
            <span class="macro-news-category">${esc(x.category||'Macro')}</span>
          </div>
          <a href="${esc(safeHttpUrl(x.link))}" target="_blank" rel="noopener noreferrer">${esc(x.title||'Untitled macro story')}</a>
          <small>${esc(x.source||'Source')} · ${esc(x.published||'')}</small>
          ${effects.length?`<div class="macro-effect"><b>Why it matters</b>${effects.map(y=>`<span>→ ${esc(y)}</span>`).join('')}</div>`:''}
        </article>`;
      }).join('')
    : `<div class="overview-news-empty">No high-relevance macro stories returned for this filter yet.</div>`;
}

async function loadMacroNews(){
  const state = window.SolvAIMacroNews;
  const box=$("macroNewsItems");
  try{
    const d=await getJSON('/api/market-news');
    if(!d || d.success===false) throw new Error(d?.error||"Macro news service unavailable.");
    state.items=Array.isArray(d.items)?d.items:[];
    renderMacroNewsItems();
  }catch(e){
    if(box)box.innerHTML=`<div class="overview-news-empty">Macro intelligence temporarily unavailable. Market and company research remain available.</div>`;
  }
  if(state.timer) clearTimeout(state.timer);
  state.timer=setTimeout(()=>{
    if($('overview')?.classList.contains('active')) loadMacroNews();
  },600000);
}

function setupMacroNewsFilters(){
  document.querySelectorAll('.macro-news-filter').forEach(btn=>{
    btn.addEventListener('click',()=>{
      window.SolvAIMacroNews.filter=btn.dataset.filter||'All';
      document.querySelectorAll('.macro-news-filter')
        .forEach(b=>b.classList.toggle('active',b===btn));
      renderMacroNewsItems();
    });
  });
}

function loadDashboard(){
  if(dashboardLoadPromise)return dashboardLoadPromise;
  const out=$('dashboardOut'); if(!out)return Promise.resolve();
  const isFirstLoad=!dashboardInitialized;
  if(isFirstLoad)out.innerHTML=`<div id="worldMarketMount"><section class="market-strip-card"><div class="market-strip-loading">Loading market graph…</div></section></div>`;
  setupMacroNewsFilters();
  renderQuickAccess();
  dashboardLoadPromise=(async()=>{
    const marketPromise=(async()=>{
      await loadWorldMarkets(!isFirstLoad,'daily');
      await loadWorldMarkets(!isFirstLoad,'intraday');
    })();
    const newsPromise=loadMacroNews();
    try{
      const d=await getJSON('/api/companies');
      const companies=d.companies||[];
      renderCompanyList(companies);
      renderResearchActivity(companies);
      const current=$('overviewCompany')?.value.trim();
      const sorted=[...companies].sort((a,b)=>(Number(b.reports)||0)-(Number(a.reports)||0));
      const selected=current || sorted[0]?.company;
      if(selected){ $('overviewCompany').value=selected; await loadOverview(); }
      else {
        $('overviewCompany').value='';
        $('overviewCompactContent').innerHTML=`<div class="company-no-selection"><b>No company selected</b><span>Add a report in Data Sources & Reports, then choose a company here.</span></div>`;
        $('overviewExpandedContent').innerHTML='';
        $('overviewOut').innerHTML=`<div class="card overview-empty-card"><div class="assistant-kicker">COMPANY OVERVIEW</div><h2>No company selected</h2><p>Add a report in Data Sources & Reports, then choose a company here.</p></div>`;
      }
    }catch(e){
      const companyPanel=$('overviewCompactContent');
      if(companyPanel)companyPanel.innerHTML=`<div class="company-no-selection"><b>Company data unavailable</b><span>${esc(e.message)}</span></div>`;
      const activity=$('researchActivityMount');
      if(activity)activity.innerHTML=`<div class="overview-news-empty">Research activity is temporarily unavailable.</div>`;
    }
    await Promise.allSettled([marketPromise,newsPromise]);
    dashboardInitialized=true;
  })().finally(()=>{dashboardLoadPromise=null;});
  return dashboardLoadPromise;
}
function renderResearchActivity(companies){
  const box=$('researchActivityMount'); if(!box)return;
  const items=(companies||[]).slice(0,4);
  box.innerHTML=`<div class="section-head-row"><div><div class="assistant-kicker">RESEARCH ACTIVITY</div><h3>Latest work</h3></div><button class="link-button" type="button" data-action="view" data-view="learn">View all →</button></div>${items.length?items.map((c,i)=>`<div class="activity-row"><span class="activity-icon">${i===0?'↗':i===1?'◌':i===2?'▣':'○'}</span><div><b>${esc(c.company)}</b><small>${i===0?'Company Analysis':i===1?'Financial Health Check':i===2?'Sector Analysis':'Macro Report'} · ${Math.max(1,Number(c.reports)||1)} report${Number(c.reports)===1?'':'s'}</small></div><span class="activity-more">⋮</span></div>`).join(''):`<div class="overview-news-empty">No research activity yet.</div>`}`;
}
function renderQuickAccess(){
  const box=$('quickAccessMount'); if(!box)return;
  const items=[['indicatorsVsa','Indicators & VSA','Volume, levels & traps','⌁'],['risk','Investment Research','Quality & long-term value','△'],['tradePlanner','Trade Planner','Stops & position size','◇'],['eventProbability','Event Scenarios','Compare evidence-led outcomes','◎'],['learn','Data Sources','Reports & data','▣'],['portfolio','Portfolio Risk','Track portfolio','♡']];
  box.innerHTML=`<div class="assistant-kicker">QUICK ACCESS</div><div class="quick-access-row">${items.map(x=>`<button type="button" data-action="view" data-view="${esc(x[0])}"><span class="quick-icon">${x[3]}</span><span><b>${esc(x[1])}</b><small>${esc(x[2])}</small></span></button>`).join('')}</div>`;
}

/* Financial AI feature layer: market snapshot, macro regime monitor, and evidence-led event scenarios. */


function _fmtShares(v){ if(v==null) return "Unavailable"; const n=Number(v); if(!Number.isFinite(n)) return "Unavailable"; return Math.abs(n)>=1e9?(n/1e9).toFixed(2)+"B":Math.abs(n)>=1e6?(n/1e6).toFixed(1)+"M":n.toLocaleString(undefined,{maximumFractionDigits:0}); }
function _fmtVol(v){ if(v==null) return "Unavailable"; const n=Number(v); if(!Number.isFinite(n)) return "Unavailable"; return Math.abs(n)>=1e9?(n/1e9).toFixed(2)+"B":Math.abs(n)>=1e6?(n/1e6).toFixed(2)+"M":n.toLocaleString(undefined,{maximumFractionDigits:0}); }

function renderMarketSnapshot(d){
  if(!d||d.success===false) return `<div class="card notice">Market snapshot unavailable${d?.error?": "+esc(d.error):"."}</div>`;
  const card=(l,v,s)=>`<div class="market-mini-card"><span>${esc(l)}</span><strong>${esc(v)}</strong><small>${esc(s||"")}</small></div>`;
  const updated=d.updated_at?new Date(d.updated_at).toLocaleString():"provider timestamp unavailable";
  return `<div class="market-snapshot-card card"><div class="chart-heading"><div><div class="assistant-kicker">MARKET SNAPSHOT</div><h3>${esc(d.ticker||"")} <span class="data-note">market data</span></h3></div><div class="market-meta"><span>${esc(d.market_state||"Market")}</span><span>Updated ${esc(updated)}</span></div></div><div class="market-grid">${card("Price",d.price==null?"Unavailable":num(d.price,2)+" VND","current price")}${card("P/E",d.pe==null?"Unavailable":num(d.pe,2)+"×","trailing")}${card("P/B",d.pb==null?"Unavailable":num(d.pb,2)+"×","price / book")}${card("EPS",d.eps==null?"Unavailable":num(d.eps,0)+" VND","trailing EPS")}${card("Market cap",_fmtCap(d.market_cap),"equity value")}${card("Shares outstanding",_fmtShares(d.shares_outstanding),"shares")}${card("Avg volume",_fmtVol(d.avg_volume_10d),"10 sessions")}</div><div class="data-note market-source">Source: ${esc(d.source||"Yahoo Finance / yfinance")}. ${esc(d.warning||"")}</div></div>`;
}
async function loadMarketSnapshot(company){ const el=$("marketSnapshotOut"); try{ const d=await getJSON(`/api/market-snapshot/${encodeURIComponent(company)}`,{cancelKey:'company-market-snapshot'}); if(companyKey(company)!==companyKey($("overviewCompany")?.value))return; overviewMarketCache=d; if(el)el.innerHTML=renderMarketSnapshot(d); renderOverviewMode1(); }catch(e){ if(e?.name==='AbortError')return; overviewMarketCache=null; if(el)el.innerHTML=`<div class="card notice">${esc(e.message)}</div>`; renderOverviewMode1(); } }

function _svgLine(points, opts={}){
  const vals=(points||[]).filter(x=>x&&x.value!=null&&Number.isFinite(Number(x.value)));
  if(vals.length<2)return `<div class="chart-empty">Not enough observations yet.</div>`;
  const W=760,H=270,P=48,nums=vals.map(x=>Number(x.value));
  let min=opts.min??Math.min(...nums), max=opts.max??Math.max(...nums);
  if(min===max){min-=1;max+=1;}
  const span=max-min||1;
  const x=i=>P+(i/Math.max(1,vals.length-1))*(W-2*P);
  const y=v=>H-P-(Number(v)-min)/span*(H-2*P);
  const pts=vals.map((v,i)=>`${x(i).toFixed(1)},${y(v.value).toFixed(1)}`).join(' ');
  const area=`${x(0).toFixed(1)},${H-P} ${pts} ${x(vals.length-1).toFixed(1)},${H-P}`;
  const last=vals.at(-1), first=vals[0];
  const delta=Number(last.value)-Number(first.value);
  const threshold=opts.threshold==null?'':`<line x1="${P}" y1="${y(opts.threshold).toFixed(1)}" x2="${W-P}" y2="${y(opts.threshold).toFixed(1)}" class="macro-threshold"/>`;
  const grid=[0.2,0.4,0.6,0.8].map(r=>`<line x1="${P}" y1="${(P+r*(H-2*P)).toFixed(1)}" x2="${W-P}" y2="${(P+r*(H-2*P)).toFixed(1)}" class="chart-grid"/>`).join('');
  const cls=Math.abs(delta)<Math.max(Math.abs(Number(last.value))*0.002,1e-9)?'flat':delta>0?'up':'down';
  const lastX=x(vals.length-1),lastY=y(last.value);
  return `<div class="macro-line-wrap"><svg class="line-chart macro-line ${cls}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(opts.label||'Trend chart')}"><defs><linearGradient id="trendAreaGradient" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="#dcebf8"/><stop offset="100%" stop-color="#f6f9fc"/></linearGradient></defs>${grid}<path d="M ${area}" class="trend-area"/>${threshold}<polyline points="${pts}" class="trend-line"/><circle cx="${lastX.toFixed(1)}" cy="${lastY.toFixed(1)}" r="6" class="trend-point"/><circle cx="${lastX.toFixed(1)}" cy="${lastY.toFixed(1)}" r="11" class="trend-glow"/></svg><div class="chart-labels"><span>${esc(first.date||'')}</span><span class="chart-delta ${cls}">${delta>=0?'▲':'▼'} ${Math.abs(delta).toLocaleString(undefined,{maximumFractionDigits:2})}</span><strong class="chart-last ${cls}">${Number(last.value).toLocaleString(undefined,{maximumFractionDigits:2})}</strong><span>${esc(last.date||'')}</span></div></div>`;
}
function _marketChart(key,title,unit){const obj=window.__macroData?.[key]||{}; const pts=obj.points||[]; const latest=obj.latest?.value; return `<div class="macro-data-card"><div class="chart-heading"><div><b>${esc(title)}</b><div class="data-note">${esc(obj.source||'Live market feed')} · ${esc(unit||'')}</div></div><div class="macro-latest">${latest==null?'Unavailable':Number(latest).toLocaleString(undefined,{maximumFractionDigits:2})}<small>${esc(obj.latest?.date||'')}</small></div></div>${_svgLine(pts)}<div class="data-note source-row"><a target="_blank" rel="noopener noreferrer" href="${esc(safeHttpUrl(obj.url))}">Source ↗</a> · updates automatically</div></div>`;}
function _macroChart(key,title,unit,threshold){const obj=window.__macroData?.[key]||{}; const latest=obj.latest?.value; return `<div class="macro-data-card"><div class="chart-heading"><div><b>${esc(title)}</b><div class="data-note">${esc(obj.source||'Latest published macro observation')} · ${esc(unit||'')}</div></div><div class="macro-latest">${latest==null?'Unavailable':Number(latest).toLocaleString(undefined,{maximumFractionDigits:2})}<small>${esc(obj.latest?.date||'')}</small></div></div>${_svgLine(obj.points||[],threshold==null?{}:{threshold})}<div class="data-note source-row"><a target="_blank" rel="noopener noreferrer" href="${esc(safeHttpUrl(obj.url))}">Source ↗</a> · release frequency varies</div></div>`;}
function _statusBadge(text){const cls=/weak|signal|inverted|contraction|risk/i.test(String(text||''))?'down':/improv|positive|expansion|stable|no signal/i.test(String(text||''))?'up':'flat';return `<span class="macro-badge ${cls}">${esc(text||'Unavailable')}</span>`;}
function renderMacro(d){
  if(!d||d.success===false)return `<div class="card notice bad">Macro monitor unavailable${d?.error?": "+esc(d.error):"."}</div>`;
  window.__macroData=d;
  const sahm=d.us_sahm||{}, vn=d.vietnam_unemployment||{}, u=d.us_curve||{}, summary=d.summary||{};
  const fed=d.fed_rate?.latest?.value, pmi=d.pmi?.latest?.value, rec=d.recession_probability?.latest?.value, gold=d['GC=F']?.latest?.value, vnidx=d['^VNINDEX']?.latest?.value, usdvnd=d['USDVND=X']?.latest?.value;
  const recessionState=rec==null?'Unavailable':(Number(rec)>=20?'Elevated':Number(rec)>=10?'Watch':'Low');
  return `<div class="macro-page">
    <div class="macro-hero card"><div><div class="assistant-kicker">MACRO REGIME MONITOR</div><h2>Global Macro → Vietnam Market</h2><p>Global macro indicators are combined with live market feeds. Market series refresh automatically; macro series update when the underlying source publishes a new observation.</p></div><div class="macro-toolbar"><button class="primary macro-refresh-btn" data-action="macro-refresh"><span class="btn-icon">↻</span>Refresh data</button><div class="macro-live-pill"><i></i> AUTO · ${Number(d.refresh_seconds||60)}s</div><div class="data-note">Last fetch ${esc(new Date(d.updated_at).toLocaleString())}</div></div></div>
    <div class="dashboard macro-kpis macro-kpis-7">${metricCard('Gold',gold==null?'Unavailable':num(gold,0)+' USD/oz','Yahoo Finance')}${metricCard('Fed funds',fed==null?'Unavailable':num(fed,2)+'%','FRED')}${metricCard('PMI',pmi==null?'Unavailable':num(pmi,1),'50 = neutral')}${metricCard('Recession probability',rec==null?'Unavailable':num(rec,2)+'%',recessionState)}${metricCard('Sahm Rule',sahm.latest_indicator_pp==null?'Unavailable':num(sahm.latest_indicator_pp,2)+' pp',sahm.status||'')}${metricCard('VN-Index',vnidx==null?'Unavailable':num(vnidx,0),'market feed')}${metricCard('USD/VND',usdvnd==null?'Unavailable':num(usdvnd,0),'market feed')}</div>
    <div class="macro-section-head"><div><div class="assistant-kicker">01 · GLOBAL</div><h3>International macro regime</h3><p class="data-note">Policy, labor, recession risk, manufacturing and FX.</p></div></div>
    <div class="macro-grid macro-global-grid">${_marketChart('GC=F','Gold price','USD/oz')}${_macroChart('unemployment','U.S. unemployment rate','%')}${_macroChart('fed_rate','Federal funds rate','%')}${_macroChart('recession_probability','U.S. recession probability','%',null)}${_macroChart('pmi','ISM manufacturing PMI','index',50)}<div class="macro-data-card"><div class="chart-heading"><div><b>Claudia Sahm Rule</b><div class="data-note">3-month unemployment average gap</div></div>${_statusBadge(sahm.status)}</div>${_macroChart('sahm_series','Sahm indicator','pp',0.5).replace(/<div class="macro-data-card">|<\/div>$/g,'')}</div><div class="macro-data-card macro-fx-card"><div class="chart-heading"><div><b>Major currencies</b><div class="data-note">Latest market feed</div></div></div><div class="dashboard macro-small">${['EURUSD=X','USDJPY=X','USDCNY=X'].map(k=>{const x=d.global_markets?.[k]||{};return metricCard(x.label||k,x.latest?.value==null?'Unavailable':num(x.latest.value,4),x.latest?.date||'')}).join('')}</div></div></div>
    <div class="macro-section-head"><div><div class="assistant-kicker">02 · VIETNAM MARKET</div><h3>Vietnam market regime</h3><p class="data-note">Index direction, local FX and the sovereign curve.</p></div></div>
    <div class="macro-grid macro-vn-grid">${_marketChart('^VNINDEX','VN-Index','points')}${_marketChart('^VN30','VN30','points')}${_marketChart('^HNX','HNX-Index','points')}<div class="macro-data-card"><div class="chart-heading"><div><b>USD/VND</b><div class="data-note">FX pressure / liquidity signal</div></div></div>${_svgLine((d['USDVND=X']||{}).points||[])}<div class="data-note source-row"><a target="_blank" rel="noopener noreferrer" href="${esc(safeHttpUrl(d['USDVND=X']?.url))}">Source ↗</a></div></div><div class="macro-data-card"><div class="chart-heading"><div><b>Vietnam government yield curve</b><div class="data-note">HNX official curve when reachable</div></div>${_statusBadge(d.hnx_curve?.status)}</div>${d.hnx_curve?.points?.length?_hnxCurveSvg(d.hnx_curve.points):'<div class="chart-empty">Unavailable</div>'}<div class="data-note source-row"><a target="_blank" rel="noopener noreferrer" href="${esc(safeHttpUrl(d.hnx_curve?.url))}">HNX source ↗</a></div></div><div class="macro-data-card"><div class="chart-heading"><div><b>Vietnam unemployment</b><div class="data-note">Official quarterly release</div></div></div><div class="dashboard macro-small">${metricCard('Latest',vn.value_pct==null?'Unavailable':num(vn.value_pct,2)+'%',vn.period||'')}${metricCard('Interpretation',vn.value_pct!=null&&vn.value_pct<3?'Stable':'Watch','not a Sahm-equivalent')}</div><div class="data-note source-row"><a target="_blank" rel="noopener noreferrer" href="${esc(safeHttpUrl(vn.url))}">NSO source ↗</a></div></div></div>
    <div class="macro-section-head"><div><div class="assistant-kicker">03 · SCENARIO READING</div><h3>What the current values imply</h3></div></div>
    <div class="macro-summary-grid"><div class="card macro-summary-card"><div class="assistant-kicker">CURRENT REGIME</div><h3>${esc(summary.headline||'Latest macro conditions are mixed.')}</h3><div class="macro-summary-list">${(summary.implications||[]).map(x=>`<div><span>→</span><p>${esc(x)}</p></div>`).join('')}</div></div><div class="card macro-summary-card"><div class="assistant-kicker">SCENARIO IF CONDITIONS HOLD</div><div class="scenario-row"><b>Rates ↑</b><span>Usually tighter liquidity; valuation-sensitive equities face more pressure.</span></div><div class="scenario-row"><b>Rates ↓</b><span>Usually more liquidity support, especially for rate-sensitive growth and property assets.</span></div><div class="scenario-row"><b>PMI ↑</b><span>Signals improving manufacturing momentum; cyclical demand may strengthen.</span></div><div class="scenario-row"><b>PMI ↓</b><span>Signals softer activity; earnings revisions can become more defensive.</span></div><div class="scenario-row"><b>USD/VND ↑</b><span>Can increase imported-cost and FX pressure for some Vietnamese businesses.</span></div></div></div>
    <div class="macro-footnote card"><b>Data policy:</b> “Live” means the provider returned the latest available market observation; macro releases such as unemployment, PMI and recession probability are not intrinsically tick-by-tick. The dashboard never invents a value when a source is unavailable.</div>
  </div>`;
}
function _hnxCurveSvg(points){const vals=(points||[]).filter(x=>x&&x.annual_spot_pct!=null);if(vals.length<2)return `<div class="chart-empty">HNX curve unavailable.</div>`;const W=760,H=250,P=42,nums=vals.map(x=>Number(x.annual_spot_pct)),min=Math.min(...nums),max=Math.max(...nums),span=max-min||1,pts=vals.map((v,i)=>`${(P+i/(vals.length-1)*(W-2*P)).toFixed(1)},${(H-P-(Number(v.annual_spot_pct)-min)/span*(H-2*P)).toFixed(1)}`).join(' ');return `<svg class="line-chart macro-line" viewBox="0 0 ${W} ${H}"><line x1="${P}" y1="${H-P}" x2="${W-P}" y2="${H-P}" class="axis"/><polyline points="${pts}" class="trend-line"/>${vals.map((v,i)=>{const x=P+i/(vals.length-1)*(W-2*P),y=H-P-(Number(v.annual_spot_pct)-min)/span*(H-2*P);return `<circle cx="${x}" cy="${y}" r="4" class="trend-point"/><text x="${x}" y="${H-8}" class="macro-x-label" text-anchor="middle">${esc(v.tenor)}</text>`}).join('')}</svg>`;}
function _scheduleMacroRefresh(seconds=60){if(window.__solvaiMacroTimer)clearTimeout(window.__solvaiMacroTimer);window.__solvaiMacroTimer=setTimeout(()=>{if($('macro')?.classList.contains('active'))loadMacro(false);},Math.max(30,Number(seconds||60))*1000);}
async function loadMacro(force=false){const el=$('macroOut');if(!el||macroRefreshInFlight)return;macroRefreshInFlight=true;el.innerHTML=`<div class="card notice">${force?'Refreshing live market and macro data…':'Loading macro monitor…'}</div>`;try{const d=await getJSON(`/api/macro${force?'?force=1':''}`);el.innerHTML=renderMacro(d);_scheduleMacroRefresh(d.refresh_seconds||60);}catch(e){el.innerHTML=`<div class="card notice bad">${esc(e.message)}</div>`;_scheduleMacroRefresh(60);}finally{macroRefreshInFlight=false;}}

function epProbability(v){ return v==null ? "Unavailable" : `${Number(v).toFixed(1)}%`; }
function epBar(v){ const n=Math.max(0,Math.min(100,Number(v)||0)); return `<div class="ep-probbar"><i style="width:${n}%"></i></div>`; }
function epCleanSourceText(value){
  let text=String(value||'');
  for(let i=0;i<2;i++)text=text.replace(/&amp;/gi,'&').replace(/&nbsp;|&#160;|&#x0*a0;/gi,' ').replace(/&quot;/gi,'"').replace(/&#(?:39|x0*27);/gi,"'").replace(/&lt;/gi,'<').replace(/&gt;/gi,'>');
  return text.replace(/<[^>]+>/g,' ').replace(/\u00a0/g,' ').replace(/\s+/g,' ').trim();
}
function epFormatDate(value){if(!value)return 'Date unavailable';const date=new Date(value);if(Number.isNaN(date.getTime()))return 'Date unavailable';return date.toLocaleDateString(undefined,{year:'numeric',month:'short',day:'numeric'});}
function epSourceCard(x){const cached=Boolean(x.meta?.stale_fallback);return `<article class="ep-source-card"><div class="ep-source-head"><span>${esc(epCleanSourceText(x.source||"Source"))}${cached?'<i class="ep-cached-source">cached fallback</i>':''}</span><span>${x.value_score==null?"":Number(x.value_score).toFixed(0)+" value"}</span></div><a href="${esc(safeHttpUrl(x.url))}" target="_blank" rel="noopener noreferrer">${esc(epCleanSourceText(x.title||"Untitled source"))}</a><p>${esc(epCleanSourceText(x.snippet||"").slice(0,260))}</p><div class="data-note">${esc(epFormatDate(x.published_at))}</div></article>`; }
function epSourceHealth(issues,evidenceCount){
  if(!issues?.length)return '';
  const fallback=issues.some(issue=>issue.fallback_used||issue.code==='cached_fallback');
  const retry=Math.max(0,...issues.map(issue=>Number(issue.retry_after_seconds||0)));
  const messages=[...new Set(issues.map(issue=>epCleanSourceText(issue.message||`${issue.source||'One research source'} is temporarily unavailable. Analysis continued with other available sources.`)))];
  return `<div class="ep-source-health ${fallback?'using-fallback':''}" role="status"><span class="ep-source-health-icon" aria-hidden="true">${fallback?'↻':'i'}</span><div><b>${fallback?'Cached source fallback active':'Some live sources are temporarily limited'}</b><p>${messages.map(esc).join(' ')}</p><small>${evidenceCount||0} evidence items remain available${retry?` · automatic live retry after the cooldown`:''}.</small></div></div>`;
}
function epToneMeta(tone){return tone==='positive'?{label:'Improving / supportive',icon:'↑'}:tone==='negative'?{label:'Weakening / risk',icon:'↓'}:{label:'Mixed / unchanged',icon:'→'};}
function epDriverRow(x){return `<li><span class="ep-driver-dot ${esc(x.bucket||'mixed')}"></span><div><a href="${esc(safeHttpUrl(x.url))}" target="_blank" rel="noopener noreferrer">${esc(epCleanSourceText(x.title||'Untitled evidence'))}</a><small>${esc(epCleanSourceText(x.source||'Source'))} · ${esc(x.reason||'Relevant to this scenario.')}</small></div></li>`;}
function epOutcomeCard(outcome){
  const analysis=outcome.analysis||{},counts=analysis.counts||{},weighted=analysis.weighted_evidence_pct||{},tone=epToneMeta(outcome.tone),drivers=analysis.drivers||[],counters=analysis.counter_signals||[];
  const range=outcome.sensitivity_range||{};
  return `<article class="ep-outcome-card tone-${esc(outcome.tone||'neutral')}">
    <div class="ep-outcome-head"><span class="ep-outcome-direction" aria-hidden="true">${tone.icon}</span><div><small>${esc(tone.label)}</small><h4>${esc(outcome.candidate||'Scenario')}</h4></div><strong>${epProbability(outcome.evidence_share_pct??outcome.normalized_probability)}</strong></div>
    ${epBar(outcome.evidence_share_pct??outcome.normalized_probability)}
    ${range.low!=null&&range.high!=null?`<div class="ep-sensitivity-range"><span>Reasonable model range</span><b>${epProbability(range.low)}–${epProbability(range.high)}</b></div>`:''}
    <p class="ep-outcome-why"><b>Why this evidence share:</b> ${esc(outcome.why||'The share reflects the balance and quality of the available evidence.')}</p>
    <div class="ep-evidence-balance" aria-label="Weighted evidence balance"><span><b>${Number(weighted.support||0).toFixed(0)}%</b>supports<small>${counts.support||0} items</small></span><span><b>${Number(weighted.mixed||0).toFixed(0)}%</b>mixed<small>${counts.mixed||0} items</small></span><span><b>${Number(weighted.counter||0).toFixed(0)}%</b>opposes<small>${counts.counter||0} items</small></span></div>
    <details class="ep-outcome-detail"><summary>Inspect evidence drivers <span>${drivers.length+counters.length}</span></summary><div class="ep-outcome-detail-body">${drivers.length?`<b>Signals supporting or preserving this scenario</b><ul>${drivers.map(epDriverRow).join('')}</ul>`:'<p>No sufficiently aligned driver was found; the result stays close to the baseline.</p>'}${counters.length?`<b>Signals reducing this scenario</b><ul>${counters.map(epDriverRow).join('')}</ul>`:''}</div></details>
  </article>`;
}
function epQualitySummary(quality={}){const mix=quality.source_mix||{};return `<div class="ep-quality-card"><div class="ep-quality-score"><strong>${Number(quality.score||0)}</strong><span>/100</span><small>${esc(quality.grade||'Limited')} evidence quality</small></div><div class="ep-quality-details"><span><b>${quality.live_items||0}</b> live</span><span><b>${quality.cached_items||0}</b> cached</span><span><b>${quality.independent_domains||0}</b> domains</span><span><b>${quality.duplicates_removed||0}</b> duplicates grouped</span></div><div class="ep-source-mix"><span>Primary ${mix.primary||0}</span><span>Academic ${mix.academic||0}</span><span>Publishers ${mix.publisher||0}</span><span>Aggregators ${mix.aggregator||0}</span></div></div>`;}
function epComparisonPanel(comparison={}){if(!comparison.available)return `<div class="ep-comparison-empty">${esc(comparison.message||'No comparable earlier forecast yet.')}</div>`;return `<div class="ep-change-list">${(comparison.changes||[]).map(row=>`<div><span>${esc(row.candidate)}</span><b class="${row.change>0?'up':row.change<0?'down':'flat'}">${row.change>0?'+':''}${Number(row.change).toFixed(1)} pts</b><small>${epProbability(row.previous)} → ${epProbability(row.current)}</small></div>`).join('')}</div>`;}
function epMonitorPanel(signals=[]){return `<div class="ep-monitor-list">${signals.map(signal=>`<article class="${esc(signal.direction||'mixed')}"><span>${signal.direction==='raise'?'↑':signal.direction==='lower'?'↓':signal.direction==='confidence'?'◎':'→'}</span><div><b>${esc(signal.title)}</b><p>${esc(signal.effect)}</p><small>${esc(signal.why)}</small></div></article>`).join('')}</div>`;}
let currentEventForecast=null;
function renderEventProbability(d){
  if(!d||d.success===false) return `<div class="event-prob-dashboard"><div class="card notice bad">Event research unavailable${d?.error?": "+esc(d.error):"."}</div></div>`;
  const ranked=d.ranked||[],top=ranked[0],topSources=(d.research?.top_items||[]).slice(0,6),sourceErrors=d.research?.errors||[],model=d.probability_model||{},quality=d.research?.quality||{};
  const probability=Math.max(0,Math.min(100,Number(top?.evidence_share_pct??top?.normalized_probability??0)));
  const topDrivers=top?.analysis?.drivers||[],topCounters=top?.analysis?.counter_signals||[];
  return `<div class="event-prob-dashboard event-prob-results">
    <section class="card ep-result-summary">
      <div class="ep-result-copy"><div class="assistant-kicker">TOP OUTCOME · ${esc(d.category_label||d.category)} / ${esc(d.factor_label||d.factor)}</div><h2>${esc(top?.candidate||"No dominant outcome")}</h2><p><b>Question:</b> ${esc(d.event||'Scenario direction unavailable')} · ${esc(d.focus||"Broad context")} · ${esc(d.horizon||"")}</p></div>
      <div class="ep-result-score"><strong>${epProbability(top?.evidence_share_pct??top?.normalized_probability)}</strong><span>evidence share</span><small>Top-ranked outcome · not calibrated probability</small>${d.forecast_id?`<button type="button" class="ep-save-current ${d.review?.saved?'active':''}" data-action="forecast-save" data-forecast="${Number(d.forecast_id)}" data-saved="${!d.review?.saved}">${d.review?.saved?'★ Saved':'☆ Save research'}</button>`:''}</div>
      <div class="ep-result-confidence" aria-label="Top outcome evidence share"><i style="width:${probability}%"></i></div>
    </section>
    <div class="ep-kpi-strip">${metricCard("Evidence",d.research?.items||0,"ranked items")}${metricCard("Sources",d.research?.unique_sources||0,"independent groups")}${metricCard("Evidence quality",`${quality.score??0}/100`,quality.grade||'limited')}${metricCard("Model confidence",epProbability(model.global_confidence_pct),"confidence-adjusted")}${metricCard("Distribution",epProbability(model.total_pct??ranked.reduce((sum,x)=>sum+Number(x.normalized_probability||0),0)),"three outcomes = 100%")}</div>
    <section class="card ep-scenario-section"><div class="section-head"><div><div class="assistant-kicker">01 · EXPLAINED OUTLOOK</div><h3>Why each scenario receives its evidence share</h3><p class="data-note">Every share is relative to the other two outcomes and includes supporting, opposing and mixed evidence. ${esc(model.uncertainty_note||'')}</p></div><span class="pill">${esc(d.cache_hit?'cached evidence':'fresh evidence')}</span></div><div class="ep-outcome-grid">${ranked.length?ranked.map(epOutcomeCard).join(''):"<div class='chart-empty'>No ranked outcome was returned.</div>"}</div></section>
    <div class="ep-analysis-grid">
      <section class="card ep-method-card"><div class="section-head"><div><div class="assistant-kicker">02 · EVIDENCE-SHARE LOGIC</div><h3>How the model normalized the shares to 100%</h3></div><span class="ep-baseline-chip">Baseline ${epProbability(model.baseline_pct)}</span></div><p class="interpretation">${esc(model.explanation||d.method||"The estimate responds to the quality, recency, relevance, and diversity of available evidence.")}</p><ol class="ep-method-steps"><li><b>Start equal</b><span>Each mutually exclusive outcome begins at the same baseline.</span></li><li><b>Weight evidence</b><span>Reliable, recent and factor-relevant sources carry more influence.</span></li><li><b>Read direction</b><span>Language is separated into improving, weakening and mixed signals.</span></li><li><b>Temper uncertainty</b><span>Lower confidence pulls estimates toward the baseline before normalization.</span></li></ol><div class="ep-method-note">${esc(d.method||'Evidence shares are research comparisons, not calibrated probabilities.')}</div></section>
      <aside class="card ep-driver-card"><div class="section-head"><div><div class="assistant-kicker">03 · TOP-OUTCOME DRIVERS</div><h3>${esc(top?.candidate||'Leading scenario')}</h3></div><span class="pill">${epProbability(top?.confidence)} confidence</span></div><div class="ep-driver-columns"><div><b>Raises or preserves this share</b><ul>${topDrivers.length?topDrivers.map(epDriverRow).join(''):'<li class="ep-driver-empty">No aligned driver returned.</li>'}</ul></div><div><b>Pulls this share lower</b><ul>${topCounters.length?topCounters.map(epDriverRow).join(''):'<li class="ep-driver-empty">No material counter-signal returned.</li>'}</ul></div></div></aside>
    </div>
    <div class="ep-lab-grid">
      <section class="card ep-change-card"><div class="section-head"><div><div class="assistant-kicker">04 · CHANGE SINCE LAST RUN</div><h3>How the forecast moved</h3></div></div>${epComparisonPanel(d.comparison||{})}</section>
      <section class="card ep-monitor-card"><div class="section-head"><div><div class="assistant-kicker">05 · WHAT WOULD CHANGE THIS?</div><h3>Signals worth monitoring</h3></div></div>${epMonitorPanel(d.monitor_signals||[])}</section>
    </div>
    <section class="card ep-quality-section"><div class="section-head"><div><div class="assistant-kicker">06 · RESEARCH INTEGRITY</div><h3>Evidence quality and source diversity</h3><p class="data-note">Repeated coverage is grouped, cached items are discounted, and original sources receive stronger quality credit.</p></div></div>${epQualitySummary(quality)}</section>
    <section class="card ep-sources-card"><div class="section-head"><div><div class="assistant-kicker">07 · SOURCE EVIDENCE</div><h3>What matters most right now</h3><p class="data-note">The highest-value evidence is shown first; scroll within this panel for the rest.</p></div><span class="pill">${topSources.length} surfaced</span></div><div class="ep-source-grid">${topSources.length?topSources.map(epSourceCard).join(""):"<div class='chart-empty'>No online evidence returned.</div>"}</div>${epSourceHealth(sourceErrors,(d.research?.items||[]).length||topSources.length)}</section>
  </div>`;
}
function epForecastDate(value){if(!value)return 'Date unavailable';const date=new Date(value);return Number.isNaN(date.getTime())?'Date unavailable':date.toLocaleString(undefined,{year:'numeric',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});}
function renderCalibration(calibration={}){
  if(!calibration.resolved_forecasts)return `<div class="ep-calibration-empty"><span>◎</span><div><b>Calibration begins when outcomes are recorded</b><p>After a forecast horizon passes, select the observed scenario. SolvAI will calculate accuracy and a multiclass Brier score without rewriting the original forecast.</p></div></div>`;
  const buckets=calibration.calibration_buckets||[];
  return `<div class="ep-calibration"><div class="ep-calibration-kpis"><div><span>Resolved forecasts</span><b>${calibration.resolved_forecasts}</b></div><div><span>Brier score · lower is better</span><b>${Number(calibration.brier_score).toFixed(3)}</b></div><div><span>Top-outcome accuracy</span><b>${epProbability(calibration.top_outcome_accuracy_pct)}</b></div><div><span>Calibration state</span><b>${esc(calibration.status==='measured'?'Measured':'Learning')}</b></div></div>${buckets.length?`<div class="ep-calibration-chart"><div class="ep-calibration-legend"><span><i class="predicted"></i>Predicted</span><span><i class="observed"></i>Observed</span></div>${buckets.map(row=>`<div class="ep-calibration-row"><span>${esc(row.label)} · ${row.forecasts}</span><div><i class="predicted" style="width:${Math.max(2,Number(row.average_predicted_pct||0))}%"></i><i class="observed" style="width:${Math.max(2,Number(row.observed_frequency_pct||0))}%"></i></div><small>${epProbability(row.average_predicted_pct)} / ${epProbability(row.observed_frequency_pct)}</small></div>`).join('')}</div>`:''}</div>`;
}
function forecastHistoryRow(forecast){
  const result=forecast.result||{},ranked=result.ranked||[],top=ranked[0]||{},review=forecast.review||{},id=Number(forecast.id);
  return `<article class="forecast-history-row" data-forecast="${id}"><div class="forecast-history-main"><button type="button" class="forecast-open" data-action="forecast-open" data-forecast="${id}"><span>${esc(result.category_label||forecast.category||'Research')} · ${esc(result.factor_label||'Event probability')}</span><b>${esc(top.candidate||forecast.query||'Forecast')}</b><small>${epForecastDate(forecast.created_at)} · ${esc(forecast.horizon||'')}</small></button><strong>${epProbability(top.normalized_probability??top.probability)}</strong><button type="button" class="forecast-star ${review.saved?'active':''}" data-action="forecast-save" data-forecast="${id}" data-saved="${!review.saved}" aria-label="${review.saved?'Remove from saved':'Save forecast'}">${review.saved?'★':'☆'}</button></div><div class="forecast-review"><label>Observed outcome<select id="epResolution-${id}"><option value="">Not resolved yet</option>${ranked.map(row=>`<option value="${esc(row.candidate)}" ${review.resolved_outcome===row.candidate?'selected':''}>${esc(row.candidate)}</option>`).join('')}</select></label><label>Research note<input id="epNote-${id}" value="${esc(review.note||'')}" placeholder="Add a decision note or follow-up"></label><button type="button" data-action="forecast-update" data-forecast="${id}">Update</button></div></article>`;
}
function renderForecastWorkspace(data){
  const box=$("epForecastWorkspace");if(!box)return;
  const forecasts=data.forecasts||[];
  box.innerHTML=`<section class="ep-calibration-section"><div class="ep-workspace-subhead"><div><b>Probability calibration</b><span>Recorded outcomes stay separate from the original forecast.</span></div></div>${renderCalibration(data.calibration||{})}</section><section class="ep-history-section"><div class="ep-workspace-subhead"><div><b>${appState.eventWorkspaceTab==='saved'?'Saved research':'Forecast history'}</b><span>${forecasts.length} ${forecasts.length===1?'study':'studies'}</span></div></div><div class="forecast-history-list">${forecasts.length?forecasts.map(forecastHistoryRow).join(''):`<div class="forecast-workspace-empty">${appState.eventWorkspaceTab==='saved'?'No saved forecasts yet. Use “Save research” on a result to keep it here.':'No forecasts have been run yet.'}</div>`}</div></section>`;
}
async function loadForecastWorkspace(){
  const box=$("epForecastWorkspace");if(!box)return;
  box.innerHTML='<div class="forecast-workspace-empty">Loading forecast history…</div>';
  try{const saved=appState.eventWorkspaceTab==='saved'?'&saved=1':'';const data=await getJSON(`/api/event-probability/history?limit=30${saved}`,{cancelKey:'forecast-workspace'});renderForecastWorkspace(data);}catch(error){if(error?.name!=='AbortError')box.innerHTML=`<div class="forecast-workspace-empty">${esc(error.message)}</div>`;}
}
function setForecastWorkspaceTab(tab){appState.eventWorkspaceTab=tab==='saved'?'saved':'history';document.querySelectorAll('[data-ep-tab]').forEach(button=>button.classList.toggle('active',button.dataset.epTab===appState.eventWorkspaceTab));loadForecastWorkspace();}
async function toggleForecastSave(id,saved){
  try{const data=await getJSON(`/api/event-probability/review/${Number(id)}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({saved:Boolean(saved)}),dedupe:false});if(currentEventForecast&&Number(currentEventForecast.forecast_id)===Number(id)){currentEventForecast.review=data.review;$("epOut").innerHTML=renderEventProbability(currentEventForecast);}await loadForecastWorkspace();}catch(error){alert(error.message);}
}
async function saveForecastReview(id){
  const note=$(`epNote-${Number(id)}`)?.value||'',resolved=$(`epResolution-${Number(id)}`)?.value||'';
  try{await getJSON(`/api/event-probability/review/${Number(id)}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({note,resolved_outcome:resolved}),dedupe:false});await loadForecastWorkspace();}catch(error){alert(error.message);}
}
async function openHistoricalForecast(id){
  try{const data=await getJSON(`/api/event-probability/forecast/${Number(id)}`,{cancelKey:'historical-forecast'});const forecast=data.forecast;if(!forecast)return;currentEventForecast={...(forecast.result||{}),forecast_id:forecast.id,review:forecast.review};$("epOut").innerHTML=renderEventProbability(currentEventForecast);$("epOut")?.scrollIntoView({behavior:'smooth',block:'start'});}catch(error){if(error?.name!=='AbortError')alert(error.message);}
}
async function initEventProbability(){
  if(epInitialized)return; epInitialized=true;
  const fallback={
    economy:{label:'Economy',factors:{interest_rates:{label:'Interest rates'},inflation:{label:'Inflation'},employment:{label:'Employment'},growth:{label:'Economic growth'},investing:{label:'Risk appetite'},funds:{label:'Funds & capital flows'},fx:{label:'Currencies / FX'}}},
    technology:{label:'Technology',factors:{ai:{label:'AI & data centers'},semiconductors:{label:'Semiconductors'},software:{label:'Software demand'},cybersecurity:{label:'Cybersecurity'}}},
    banking:{label:'Banking & Financial Services',factors:{credit:{label:'Credit growth'},asset_quality:{label:'Asset quality'},net_interest_margin:{label:'Net interest margin'},capital:{label:'Capital & liquidity'}}},
    consumer:{label:'Consumer',factors:{retail:{label:'Retail demand'},travel:{label:'Travel & tourism'},autos:{label:'Autos'},income:{label:'Household income'}}},
    real_estate:{label:'Real Estate',factors:{housing:{label:'Housing'},commercial:{label:'Commercial property'},construction:{label:'Construction'},mortgage:{label:'Mortgage conditions'}}},
    energy:{label:'Energy',factors:{oil:{label:'Oil'},gas:{label:'Gas / LNG'},renewables:{label:'Renewables'}}},
    industrials:{label:'Industrials',factors:{manufacturing:{label:'Manufacturing activity'},infrastructure:{label:'Infrastructure'},logistics:{label:'Logistics & freight'}}},
    materials:{label:'Materials',factors:{metals:{label:'Metals'},commodities:{label:'Commodities'},chemicals:{label:'Chemicals'}}},
    healthcare:{label:'Healthcare',factors:{demand:{label:'Healthcare demand'},regulation:{label:'Regulation & reimbursement'},pharma:{label:'Pharma / biotech'}}},
    vietnam_market:{label:'Vietnam Market',factors:{foreign_flows:{label:'Foreign flows'},liquidity:{label:'Market liquidity'},earnings:{label:'Earnings cycle'},regulation:{label:'Market regulation'}}},
    global_markets:{label:'Global Markets',factors:{rates:{label:'Global rates'},usd:{label:'U.S. dollar'},gold:{label:'Gold'},recession:{label:'Recession risk'}}}
  };
  try{const d=await getJSON('/api/event-probability/options');epCatalog=d.categories||fallback;}catch(e){epCatalog=fallback;}
  const cat=$('epCategory');if(!cat)return;
  cat.innerHTML='<option value="">Select a category</option>'+Object.entries(epCatalog).map(([k,v])=>`<option value="${esc(k)}">${esc(v.label)}</option>`).join('');
  cat.addEventListener('change',()=>{const f=$('epFactor');const data=epCatalog[cat.value]?.factors||{};f.disabled=!cat.value;f.innerHTML='<option value="">Select a factor</option>'+Object.entries(data).map(([k,v])=>`<option value="${esc(k)}">${esc(v.label)}</option>`).join('');if($('epOut'))$('epOut').innerHTML='';});
  $('epFocus')?.addEventListener('keydown',e=>{if(e.key==='Enter'&&$('epCategory').value&&$('epFactor').value)runEventProbability(true);});
  loadForecastWorkspace();
}
async function runEventProbability(force=true){
  const category=$('epCategory')?.value,factor=$('epFactor')?.value;if(!category||!factor){if($('epOut'))$('epOut').innerHTML='<div class="card notice">Choose a category and a factor first.</div>';return;}
  const out=$('epOut'),button=document.querySelector('.event-prob-meta-row .primary');out.innerHTML='<div class="card notice">Researching online sources, grouping repeated coverage and ranking the strongest evidence…</div>';if(button)button.disabled=true;
  try{const d=await getJSON('/api/event-probability/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({category,factor,focus:$('epFocus')?.value||'',horizon:$('epHorizon')?.value||'30 days'})});currentEventForecast=d;out.innerHTML=renderEventProbability(d);await loadForecastWorkspace();}
  catch(e){out.innerHTML=`<div class="card notice bad">${esc(e.message)}</div>`;}finally{if(button)button.disabled=false;}
}

function syncAlertBadge(count,alerts=[]){
  appState.unreadAlerts=Math.max(0,Number(count)||0);
  appState.recentAlerts=Array.isArray(alerts)?alerts:[];
  const button=document.querySelector('.notification-button');
  if(button){
    button.classList.toggle('has-unread',appState.unreadAlerts>0);
    button.setAttribute('aria-label',appState.unreadAlerts?`Notifications, ${appState.unreadAlerts} unread`:'Notifications, none unread');
    button.title=appState.unreadAlerts?`${appState.unreadAlerts} unread valuation alert${appState.unreadAlerts===1?'':'s'}`:'Notifications';
  }
  const menu=$('headerActionMenu');
  if(menu&&!menu.hidden&&menu.dataset.menu==='notifications')menu.innerHTML=notificationMenuMarkup();
}
async function loadAlertSummary(){
  try{
    const data=await getJSON('/api/alerts?limit=3&unread=1',{cacheMs:5000,dedupe:false});
    syncAlertBadge(data.unread_alerts,data.alerts);
  }catch(_){syncAlertBadge(0,[]);}
}
function watchlistDate(value){
  if(!value)return 'Date unavailable';
  const date=new Date(value);
  return Number.isNaN(date.getTime())?'Date unavailable':date.toLocaleString(undefined,{year:'numeric',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
}
function renderWatchlistItem(item){
  const currency=item.currency||'VND',unread=Number(item.unread_alerts||0);
  return `<article class="watchlist-item" data-watch-company="${esc(item.company)}">
    <div class="watchlist-item-head"><div><span>${esc(item.ticker||item.company)}</span><h4>${esc(item.company)}</h4><small>Updated ${esc(watchlistDate(item.updated_at))}</small></div>${unread?`<b class="watchlist-unread">${unread} new</b>`:'<b class="watchlist-current">Current</b>'}</div>
    <div class="watchlist-value-row"><span><small>Last price</small><b>${valuationMoney(item.last_price,currency)}</b></span><span><small>Last fair value</small><b>${valuationMoney(item.last_fair_value,currency)}</b></span></div>
    <div class="watchlist-thresholds"><label>Entry alert at or below<input class="watch-entry" type="number" min="0" step="any" value="${item.preferred_entry_threshold??''}"></label><label>Above-range alert at<input class="watch-above" type="number" min="0" step="any" value="${item.above_range_threshold??''}"></label><label>Valuation change %<input class="watch-change" type="number" min="1" max="100" step="1" value="${item.valuation_change_pct??10}"></label></div>
    <details class="watchlist-rules"><summary>Alert rules</summary><div><label><input class="watch-price-below" type="checkbox" ${item.alert_price_below?'checked':''}> Price enters research range</label><label><input class="watch-price-above" type="checkbox" ${item.alert_price_above?'checked':''}> Price moves above range</label><label><input class="watch-valuation-change" type="checkbox" ${item.alert_valuation_change?'checked':''}> Material fair-value change</label><label><input class="watch-new-evidence" type="checkbox" ${item.alert_new_evidence?'checked':''}> New reporting evidence</label></div></details>
    <div class="watchlist-item-actions"><button type="button" data-action="watchlist-refresh-company" data-company="${esc(item.company)}">Refresh valuation</button><button type="button" class="secondary" data-action="watchlist-update" data-company="${esc(item.company)}">Save rules</button><button type="button" class="text-action" data-action="watchlist-history" data-company="${esc(item.company)}">History</button><button type="button" class="text-action danger" data-action="watchlist-remove" data-company="${esc(item.company)}">Remove</button></div>
  </article>`;
}
function renderWatchlistItems(data){
  const items=data.items||[],box=$('watchlistItems'),count=$('watchlistCount');
  if(count)count.textContent=`${items.length} ${items.length===1?'company':'companies'}`;
  if(box)box.innerHTML=items.length?items.map(renderWatchlistItem).join(''):`<div class="watchlist-empty"><b>No watched companies yet</b><span>Calculate a company’s core value, then choose “Track company”.</span><button type="button" data-action="view" data-view="risk">Open Investment Research</button></div>`;
}
function renderWatchlistAlerts(data){
  const alerts=data.alerts||[],box=$('watchlistAlerts');
  syncAlertBadge(data.unread_alerts,alerts.filter(row=>!row.read_at).slice(0,3));
  if(!box)return;
  box.innerHTML=alerts.length?alerts.map(row=>`<article class="watchlist-alert ${esc(row.severity||'info')} ${row.read_at?'is-read':'is-unread'}"><span class="watchlist-alert-mark">${row.kind==='price_entry'?'↓':row.kind==='price_above'?'↑':row.kind==='valuation_change'?'±':'◎'}</span><div><div><b>${esc(row.title)}</b><small>${esc(watchlistDate(row.created_at))}</small></div><p>${esc(row.message)}</p><span>${esc(row.company)} · ${esc(String(row.kind||'update').replaceAll('_',' '))}</span></div>${row.read_at?'':`<button type="button" data-action="alert-read" data-alert-id="${Number(row.id)}" aria-label="Mark alert read">✓</button>`}</article>`).join(''):'<div class="watchlist-empty"><b>No alerts yet</b><span>Alerts appear after a watched company crosses a saved threshold or receives new valuation evidence.</span></div>';
}
function watchlistHistoryChart(history,currency){
  const rows=[...(history||[])].reverse().filter(row=>Number.isFinite(Number(row.market_price))||Number.isFinite(Number(row.fair_value)));
  if(rows.length<2)return `<div class="watchlist-chart-empty">One snapshot saved. Refresh this company later to begin its valuation trend.</div>`;
  const values=rows.flatMap(row=>[row.market_price,row.fair_value]).map(Number).filter(Number.isFinite),W=760,H=210,P=30,min=Math.min(...values),max=Math.max(...values),span=max-min||1;
  const x=index=>P+index/Math.max(1,rows.length-1)*(W-2*P),y=value=>H-P-(Number(value)-min)/span*(H-2*P);
  const line=field=>rows.map((row,index)=>Number.isFinite(Number(row[field]))?`${x(index).toFixed(1)},${y(row[field]).toFixed(1)}`:'').filter(Boolean).join(' ');
  return `<div class="watchlist-history-chart"><div class="watchlist-chart-legend"><span><i class="market"></i>Market price</span><span><i class="fair"></i>Modeled fair value</span></div><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-label="Saved market price and modeled fair value history"><line x1="${P}" y1="${H-P}" x2="${W-P}" y2="${H-P}" class="axis"/><polyline points="${line('market_price')}" class="market-line"/><polyline points="${line('fair_value')}" class="fair-line"/></svg><div class="watchlist-chart-axis"><span>${esc(watchlistDate(rows[0].created_at))}</span><b>${valuationMoney(min,currency)} – ${valuationMoney(max,currency)}</b><span>${esc(watchlistDate(rows.at(-1).created_at))}</span></div></div>`;
}
function renderValuationHistory(company,history){
  const title=$('valuationHistoryTitle'),box=$('valuationHistoryOut'),currency=history[0]?.currency||'VND';
  if(title)title.textContent=`${company} saved valuations`;
  if(!box)return;
  if(!history.length){box.innerHTML='<div class="watchlist-empty">No evidence-backed valuation snapshots are available for this company.</div>';return;}
  box.innerHTML=`${watchlistHistoryChart(history,currency)}<div class="watchlist-history-table"><table><thead><tr><th>Saved</th><th>Market</th><th>Bear</th><th>Base</th><th>Bull</th><th>Confidence</th></tr></thead><tbody>${history.map(row=>`<tr><td>${esc(watchlistDate(row.created_at))}</td><td>${valuationMoney(row.market_price,currency)}</td><td>${valuationMoney(row.bear_value,currency)}</td><td><b>${valuationMoney(row.base_value??row.fair_value,currency)}</b></td><td>${valuationMoney(row.bull_value,currency)}</td><td>${num(row.confidence_score,0)}/100 · ${esc(row.confidence_label||'Low')}</td></tr>`).join('')}</tbody></table></div><p class="watchlist-history-note">Only provider/evidence-backed runs are saved. Manual-input valuations remain calculation-only and are excluded from this history.</p>`;
}
async function loadValuationHistory(company){
  const normalized=String(company||'').trim().toUpperCase(),box=$('valuationHistoryOut');if(!normalized||!box)return;
  box.innerHTML='<div class="watchlist-empty">Loading private valuation history…</div>';
  try{const data=await getJSON(`/api/valuation/history/${encodeURIComponent(normalized)}?limit=30`,{dedupe:false,cancelKey:'valuation-history'});renderValuationHistory(normalized,data.history||[]);}catch(error){if(error?.name!=='AbortError')box.innerHTML=`<div class="watchlist-empty error">${esc(error.message)}</div>`;}
}
async function loadWatchlistWorkspace(){
  const items=$('watchlistItems'),alerts=$('watchlistAlerts');
  if(items)items.innerHTML='<div class="watchlist-empty">Loading your private watchlist…</div>';
  if(alerts)alerts.innerHTML='<div class="watchlist-empty">Loading smart alerts…</div>';
  try{
    const [watchData,alertData]=await Promise.all([getJSON('/api/watchlist',{dedupe:false}),getJSON('/api/alerts?limit=50',{dedupe:false})]);
    renderWatchlistItems(watchData);renderWatchlistAlerts(alertData);
  }catch(error){if(items)items.innerHTML=`<div class="watchlist-empty error">${esc(error.message)}</div>`;if(alerts)alerts.innerHTML=`<div class="watchlist-empty error">${esc(error.message)}</div>`;}
}
async function saveWatchlist(company,settings={}){
  const normalized=String(company||'').trim().toUpperCase();if(!normalized)return;
  try{
    await getJSON(`/api/watchlist/${encodeURIComponent(normalized)}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(settings),dedupe:false});
    showView('watchlist');await loadValuationHistory(normalized);
  }catch(error){window.alert(error.message);}
}
async function updateWatchlist(element){
  const card=element.closest('.watchlist-item'),company=String(element.dataset.company||'').trim().toUpperCase();if(!card||!company)return;
  const settings={
    preferred_entry_threshold:card.querySelector('.watch-entry')?.value,
    above_range_threshold:card.querySelector('.watch-above')?.value,
    valuation_change_pct:card.querySelector('.watch-change')?.value,
    alert_price_below:Boolean(card.querySelector('.watch-price-below')?.checked),
    alert_price_above:Boolean(card.querySelector('.watch-price-above')?.checked),
    alert_valuation_change:Boolean(card.querySelector('.watch-valuation-change')?.checked),
    alert_new_evidence:Boolean(card.querySelector('.watch-new-evidence')?.checked)
  };
  element.disabled=true;
  try{await getJSON(`/api/watchlist/${encodeURIComponent(company)}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(settings),dedupe:false});await loadWatchlistWorkspace();}catch(error){window.alert(error.message);}finally{element.disabled=false;}
}
async function removeWatchlist(company){
  const normalized=String(company||'').trim().toUpperCase();if(!normalized||!window.confirm(`Remove ${normalized} from your watchlist? Saved valuation history will remain available.`))return;
  try{await getJSON(`/api/watchlist/${encodeURIComponent(normalized)}`,{method:'DELETE',dedupe:false});await loadWatchlistWorkspace();}catch(error){window.alert(error.message);}
}
async function markAlertRead(id){try{await getJSON(`/api/alerts/${Number(id)}/read`,{method:'POST',dedupe:false});await loadWatchlistWorkspace();}catch(error){window.alert(error.message);}}
async function markAllAlertsRead(){try{await getJSON('/api/alerts/read-all',{method:'POST',dedupe:false});await loadWatchlistWorkspace();}catch(error){window.alert(error.message);}}
async function refreshWatchedCompany(company){
  const normalized=String(company||'').trim().toUpperCase();if(!normalized)return;
  const button=[...document.querySelectorAll('[data-action="watchlist-refresh-company"]')].find(candidate=>candidate.dataset.company===normalized);if(button)button.disabled=true;
  try{await getJSON(`/api/valuation/${encodeURIComponent(normalized)}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({assumptions:{}}),dedupe:false});await loadWatchlistWorkspace();await loadValuationHistory(normalized);}catch(error){window.alert(error.message);}finally{if(button)button.disabled=false;}
}

function healthAge(seconds){if(seconds==null)return 'Not checked';const n=Number(seconds);if(n<60)return `${Math.max(0,Math.round(n))}s ago`;if(n<3600)return `${Math.round(n/60)}m ago`;if(n<86400)return `${Math.round(n/3600)}h ago`;return `${Math.round(n/86400)}d ago`;}
function renderSystemHealth(data){
  const providers=data.providers||[],calibration=data.application?.event_calibration||{};
  return `<div class="system-health-page"><section class="card system-health-hero"><div><div class="assistant-kicker">SOLVAI SYSTEM HEALTH</div><h2>${esc(data.label||'Workspace status')}</h2><p>Provider failures are isolated, recent successful evidence can remain available during short outages, and no raw service errors are shown to research users.</p></div><div class="system-health-score"><strong>${Number(data.score||0)}</strong><span>/100</span><small>${data.checked_providers||0} providers checked</small></div><button type="button" class="primary" data-action="system-health-refresh">Refresh status</button></section><div class="health-summary-grid">${metricCard('Checked providers',data.checked_providers||0,'this workspace session')}${metricCard('Resolved forecasts',calibration.resolved_forecasts||0,'calibration sample')}${metricCard('Brier score',calibration.brier_score==null?'Learning':Number(calibration.brier_score).toFixed(3),'lower is better')}${metricCard('Top-outcome accuracy',calibration.top_outcome_accuracy_pct==null?'Learning':epProbability(calibration.top_outcome_accuracy_pct),'resolved forecasts')}</div><section class="card provider-health-section"><div class="section-head"><div><div class="assistant-kicker">PROVIDER STATUS</div><h3>Freshness, latency and fallbacks</h3><p class="data-note">“Not checked” means that feature has not requested the provider during this session.</p></div></div><div class="provider-health-grid">${providers.map(row=>`<article class="provider-health-card ${esc(row.status)}"><div><span class="provider-status-dot"></span><b>${esc(row.name)}</b><em>${esc(row.status.replace('_',' '))}</em></div><p>${esc(row.message)}</p><dl><div><dt>Checked</dt><dd>${esc(healthAge(row.age_seconds))}</dd></div><div><dt>Latency</dt><dd>${row.latency_ms==null?'—':`${Number(row.latency_ms)} ms`}</dd></div><div><dt>Evidence</dt><dd>${row.evidence_count==null?'—':Number(row.evidence_count)}</dd></div><div><dt>Mode</dt><dd>${row.cached?'Cached fallback':'Live / local'}</dd></div></dl></article>`).join('')}</div></section><section class="card client-health-section"><div class="section-head"><div><div class="assistant-kicker">REQUEST COORDINATION</div><h3>Current page activity</h3><p class="data-note">Duplicate requests are combined and outdated company requests are cancelled automatically.</p></div><span class="pill">${appState.requests.size} active</span></div><div class="client-health-list">${[...appState.clientHealth.entries()].slice(-10).reverse().map(([endpoint,row])=>`<div><span class="provider-status-dot ${esc(row.status)}"></span><b>${esc(endpoint.replace('/api/',''))}</b><span>${row.latency_ms} ms</span><small>${esc(epForecastDate(row.checked_at))}</small></div>`).join('')||'<div class="forecast-workspace-empty">No client requests recorded yet.</div>'}</div></section></div>`;
}
async function loadSystemHealth(force=false){const out=$("systemHealthOut");if(!out)return;out.innerHTML='<div class="card notice">Checking provider and workspace health…</div>';try{const data=await getJSON(`/api/system-health${force?'?refresh=1':''}`,{dedupe:!force,cancelKey:'system-health'});out.innerHTML=renderSystemHealth(data);}catch(error){if(error?.name!=='AbortError')out.innerHTML=`<div class="card notice bad">${esc(error.message)}</div>`;}}

function runAction(element,event){
  const action=element.dataset.action;
  if(!action)return;
  event.preventDefault();
  const actions={
    'toggle-sidebar':()=>toggleSidebar(),
    navigate:()=>{const target=String(element.dataset.href||'');if(target.startsWith('/')&&!target.startsWith('//'))window.location.assign(target);},
    'header-menu':()=>toggleHeaderMenu(element.dataset.menu,element),
    view:()=>showView(element.dataset.view),
    logout:()=>logoutWorkspace(),
    'use-prompt':()=>usePrompt(element.dataset.prompt||''),
    'send-assistant':()=>sendAssistant(),
    'overview-mode':()=>setOverviewMode(Number(element.dataset.mode||1)),
    'research-brief':()=>loadResearchBrief(),
    'close-overview':()=>closeOverviewMode3(),
    compare:()=>loadCompare(),
    stock:()=>loadStock(),
    'vsa-analyze':()=>loadVsaAnalysis(),
    'vsa-screen':()=>loadVsaScreen(),
    'vsa-open-candidate':()=>openVsaCandidate(element.dataset.company||''),
    'upload-chart':()=>uploadChart(),
    risk:()=>loadRisk(),
    valuation:()=>runFeatureController('valuation',loadValuation),
    'overview-valuation':()=>loadOverviewValuation(),
    'valuation-open-risk':()=>openValuationRisk(),
    'trading-risk':()=>runFeatureController('tradePlanner',loadTradingRisk),
    'event-probability':()=>runEventProbability(true),
    'forecast-tab':()=>setForecastWorkspaceTab(element.dataset.epTab),
    news:()=>loadNews(),
    scan:()=>scan(),
    'upload-report':()=>uploadReport(),
    'remove-portfolio':()=>element.closest('.portfolio-row')?.remove(),
    'add-portfolio':()=>addPortfolioRow(),
    'portfolio-risk':()=>loadPortfolioRisk(),
    'open-company':()=>openCompany(element.dataset.company||''),
    evidence:()=>showEvidence(element.dataset.company||'',element.dataset.metric||''),
    'remove-closest':()=>{const selector=element.dataset.closest;if(selector&&['.modal-backdrop','.research-brief'].includes(selector))element.closest(selector)?.remove();},
    'shift-markets':()=>shiftWorldMarkets(Number(element.dataset.direction||0)),
    'macro-refresh':()=>loadMacro(true),
    'forecast-save':()=>toggleForecastSave(Number(element.dataset.forecast),element.dataset.saved==='true'),
    'forecast-open':()=>openHistoricalForecast(Number(element.dataset.forecast)),
    'forecast-update':()=>saveForecastReview(Number(element.dataset.forecast)),
    'system-health-refresh':()=>loadSystemHealth(true),
    'watchlist-refresh':()=>loadWatchlistWorkspace(),
    'watchlist-add':()=>saveWatchlist(element.dataset.company||valuationCache?.company||''),
    'watchlist-update':()=>updateWatchlist(element),
    'watchlist-remove':()=>removeWatchlist(element.dataset.company||''),
    'watchlist-history':()=>{showView('watchlist');loadValuationHistory(element.dataset.company||'');},
    'watchlist-refresh-company':()=>refreshWatchedCompany(element.dataset.company||''),
    'alert-read':()=>markAlertRead(Number(element.dataset.alertId)),
    'alerts-read-all':()=>markAllAlertsRead(),
  };
  actions[action]?.();
}

function initializeApp(){
  if(appState.initialized)return;
  appState.initialized=true;
  setViewStyles("overview");
  overviewMode=1;
  document.body.dataset.overviewMode="1";
  syncOverviewModeDOM();
  setPageMeta("overview");
  const sidebarScroller=$("sidebarScrollRegion");
  if(sidebarScroller)sidebarScroller.scrollTop=0;
  $("assistantInput")?.addEventListener("keydown",e=>{if(e.key==="Enter")sendAssistant();});
  $("overviewSearchForm")?.addEventListener("submit",event=>{event.preventDefault();loadOverview();});
  $("vsaAnalyzeForm")?.addEventListener("submit",event=>{event.preventDefault();loadVsaAnalysis();});
  document.addEventListener("click",event=>{
    const actionTarget=event.target.closest?.('[data-action]');
    const viewTarget=event.target.closest?.('nav button[data-view]');
    if(actionTarget)runAction(actionTarget,event);else if(viewTarget){event.preventDefault();showView(viewTarget.dataset.view);}
    if(!event.target.closest?.(".workspace-header-actions"))closeHeaderMenu();
    if(!event.target.closest?.('.company-search-row')&&!event.target.closest?.('#companySearchMenu')){const menu=$("companySearchMenu");if(menu)menu.hidden=true;}
  });
  document.addEventListener("keydown",e=>{if(e.key==="Escape"){closeHeaderMenu();if(!$("companyModeOverlay")?.hidden)closeOverviewMode3();}});
  Promise.allSettled([getJSON('/api/health',{cacheMs:30000}),loadDashboard(),loadAlertSummary()]);
}

initializeApp();
