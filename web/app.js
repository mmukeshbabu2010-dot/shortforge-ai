const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
const API_BASE=(document.querySelector('meta[name="shortforge-api"]')?.content||window.SHORTFORGE_API_URL||"").replace(/\/$/,"");
const apiUrl=value=>{if(!value)return value;if(/^https?:\/\//i.test(value))return value;return API_BASE+value};
const LOCAL_AGENT_URL="http://127.0.0.1:8765";
const state={source:"youtube",hooks:[],selected:[],current:null,results:[]};
const form=$("#form"),sourceType=$("#sourceType"),url=$("#url"),video=$("#video"),brollFile=$("#brollFile");
let youtubeCookies=null;
let localAgentAvailable=false;
const toast=message=>{const el=$("#toast");el.textContent=message;el.classList.add("show");clearTimeout(window.__toast);window.__toast=setTimeout(()=>el.classList.remove("show"),2600)};
const fmt=seconds=>{seconds=Math.max(0,Math.round(Number(seconds)||0));const h=Math.floor(seconds/3600),m=Math.floor(seconds%3600/60),s=seconds%60;return h?h+":"+String(m).padStart(2,"0")+":"+String(s).padStart(2,"0"):m+":"+String(s).padStart(2,"0")};
const setProgress=(step,text,width)=>{$("#progressPanel").hidden=false;$$(".step").forEach((el,i)=>el.classList.toggle("active",i===step));$("#progressBar").style.width=width+"%";$("#progressText").textContent=text};
function installLocalBridge(){
  const youtubeSource=$("#youtubeSource");
  if(!youtubeSource||$("#localBridge"))return;
  const style=document.createElement("style");
  style.textContent="#localBridge{margin-top:14px;padding:14px 16px;border:1px solid rgba(139,92,246,.28);border-radius:14px;background:rgba(99,91,255,.06)}#localBridge .bridge-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.bridge-copy b{display:block;font-size:13px}.bridge-copy small{display:block;margin-top:5px;color:var(--muted);font-size:11px;line-height:1.45}.bridge-status{white-space:nowrap;font-size:10px;font-weight:800;padding:5px 8px;border-radius:999px;background:rgba(148,163,184,.12);color:var(--muted)}.bridge-status.online{background:rgba(34,197,94,.12);color:#4ade80}.bridge-actions{display:flex;gap:8px;align-items:center;margin-top:10px;flex-wrap:wrap}.bridge-file{position:relative;display:inline-flex;align-items:center;gap:7px;padding:8px 11px;border:1px solid rgba(139,92,246,.38);border-radius:9px;color:var(--text);background:rgba(99,91,255,.08);cursor:pointer;font-size:11px;font-weight:700}.bridge-file input{position:absolute;inset:0;width:100%;height:100%;opacity:0;cursor:pointer}.bridge-help{font-size:11px;color:var(--muted);text-decoration:none}.bridge-help:hover{text-decoration:underline}";
  document.head.appendChild(style);
  const box=document.createElement("div");
  box.id="localBridge";
  box.innerHTML='<div class="bridge-head"><div class="bridge-copy"><b><i class="ph ph-desktop"></i> Local YouTube bridge</b><small id="bridgeMessage">Your PC downloads the YouTube video, then sends only the downloaded video to ShortForge. YouTube cookies stay on your PC.</small></div><span id="bridgeStatus" class="bridge-status">Checking…</span></div><div id="bridgeSetup" class="bridge-setup"><span><i class="ph ph-info"></i> One-time setup: download the bridge, open the <b>local</b> folder, and double-click <b>run.bat</b>.</span><a class="bridge-download" href="https://github.com/vruntime-labs/shortforge-ai/archive/refs/heads/main.zip" target="_blank" rel="noreferrer"><i class="ph ph-download-simple"></i> Download bridge</a></div><div class="bridge-actions"><label class="bridge-file" id="cookiePicker" hidden><i class="ph ph-key"></i><span id="cookieLabel">Optional cookies.txt</span><input id="youtubeCookies" type="file" accept=".txt,text/plain"></label><a class="bridge-help" href="https://github.com/vruntime-labs/shortforge-ai/tree/main/local" target="_blank" rel="noreferrer">Help</a></div>';
  const hint=youtubeSource.querySelector(".source-hint");
  (hint?.parentNode||youtubeSource).appendChild(box);
  youtubeCookies=$("#youtubeCookies");
  youtubeCookies.addEventListener("change",()=>{if(youtubeCookies.files[0]){$("#cookieLabel").textContent=youtubeCookies.files[0].name;toast("Cookies will stay local and be used only by the local bridge.")}});
}
async function checkLocalAgent(){
  const status=$("#bridgeStatus");
  try{
    const req=new Request(LOCAL_AGENT_URL+"/health",{method:"GET",mode:"cors",targetAddressSpace:"loopback"});
    const res=await fetch(req,{cache:"no-store",signal:AbortSignal.timeout(1800)});
    const data=await res.json();
    localAgentAvailable=Boolean(res.ok&&data.status==="ok");
  }catch(_){localAgentAvailable=false}
  if(status){
    status.textContent=localAgentAvailable?"Local bridge ready":"Setup needed";
    status.classList.toggle("online",localAgentAvailable);
    $("#bridgeSetup")?.toggleAttribute("hidden",localAgentAvailable);
    $("#cookiePicker")?.toggleAttribute("hidden",!localAgentAvailable);
    if($("#bridgeMessage"))$("#bridgeMessage").textContent=localAgentAvailable?"Ready. Your PC downloads the YouTube video, then sends only the downloaded video to ShortForge.":"Start the local bridge once on your PC so YouTube downloads happen from your own connection.";
  }
}
async function analyzeViaLocalAgent(videoUrl,count){
  const cookies=youtubeCookies?.files?.[0]?await youtubeCookies.files[0].text():"";
  const payload=JSON.stringify({url:videoUrl,count:Number(count)||5,cookies});
  const req=new Request(LOCAL_AGENT_URL+"/analyze",{method:"POST",mode:"cors",targetAddressSpace:"loopback",headers:{"Content-Type":"application/json"},body:payload});
  const res=await fetch(req);
  const data=await res.json().catch(()=>({error:"Local bridge returned an invalid response."}));
  if(!res.ok||data.error)throw new Error(data.error||"Local YouTube bridge failed.");
  return data;
}
installLocalBridge();
checkLocalAgent();
setInterval(checkLocalAgent,5000);
$$(".nav-item").forEach(btn=>btn.addEventListener("click",()=>{const view=btn.dataset.view;$$(".nav-item").forEach(x=>x.classList.toggle("active",x===btn));$$(".view").forEach(x=>x.classList.toggle("active",x.id==="view-"+view));$("#sidebar").classList.remove("open")}));
$("#mobileMenu").addEventListener("click",()=>$("#sidebar").classList.toggle("open"));
$$("[data-go-home]").forEach(x=>x.addEventListener("click",()=>$$(".nav-item")[0].click()));
$("#themeBtn").addEventListener("click",()=>toast("Dark mode is the default ShortForge workspace."));
$$(".source-tab").forEach(tab=>tab.addEventListener("click",()=>{state.source=tab.dataset.source;sourceType.value=state.source;$$(".source-tab").forEach(x=>x.classList.toggle("active",x===tab));$("#youtubeSource").classList.toggle("active",state.source==="youtube");$("#uploadSource").classList.toggle("active",state.source==="upload")}));
video.addEventListener("change",()=>{if(video.files[0]){$("#fileName").textContent=video.files[0].name;toast("Video selected. Click Analyze Video to continue.")}});
$("#dropZone").addEventListener("dragover",e=>{e.preventDefault();e.currentTarget.style.borderColor="#635bff"});
$("#dropZone").addEventListener("dragleave",e=>e.currentTarget.style.borderColor="");
$("#dropZone").addEventListener("drop",e=>{e.preventDefault();e.currentTarget.style.borderColor="";if(e.dataTransfer.files[0]){video.files=e.dataTransfer.files;$("#fileName").textContent=e.dataTransfer.files[0].name}});
brollFile.addEventListener("change",()=>{if(brollFile.files[0]){$("#brollName").textContent=brollFile.files[0].name;$("#broll").checked=true;$("#featureBroll").textContent="On"}});
$("#subtitles").addEventListener("change",e=>$("#featureSubs").textContent=e.target.checked?"On":"Off");
$("#broll").addEventListener("change",e=>$("#featureBroll").textContent=e.target.checked?"On":"Off");
$$(".format").forEach(btn=>btn.addEventListener("click",()=>{$$(".format").forEach(x=>x.classList.remove("active"));btn.classList.add("active")}));
$("#sortHooks").addEventListener("change",renderHooks);
$("#clearResults").addEventListener("click",()=>{state.results=[];renderResults();toast("Generated Shorts cleared.")});
form.addEventListener("submit",async e=>{e.preventDefault();if(state.source==="youtube"&&!url.value.trim())return toast("Paste a YouTube URL first.");if(state.source==="upload"&&!video.files.length)return toast("Choose a video first.");if(state.source==="youtube"&&!localAgentAvailable)return toast("Start the Local YouTube bridge first. Then click Analyze Video again.");$("#emptyState").hidden=true;$("#analysisSection").hidden=true;$("#generateBtn").disabled=true;setProgress(0,"Preparing your video…",12);await wait(350);setProgress(0,state.source==="youtube"&&localAgentAvailable?"Downloading on this PC…":"Analyzing audio and video…",32);await wait(450);setProgress(1,state.source==="youtube"&&localAgentAvailable?"Sending the downloaded video to ShortForge…":"Finding hook-worthy moments…",58);try{let data;if(state.source==="youtube"&&localAgentAvailable){data=await analyzeViaLocalAgent(url.value.trim(),$("#count").value)}else{const fd=new FormData();if(state.source==="youtube")fd.append("url",url.value.trim());else fd.append("video",video.files[0]);fd.append("count",$("#count").value);fd.append("duration","45");if(state.source==="youtube"&&youtubeCookies?.files?.[0])fd.append("cookie_file",youtubeCookies.files[0]);const res=await fetch(apiUrl("/api/analyze"),{method:"POST",body:fd});data=await res.json();if(!res.ok||data.error)throw new Error(data.error||"Analysis failed.");}state.hooks=data.hooks||[];state.selected=state.hooks.slice(0,Math.min(3,state.hooks.length)).map(x=>x.id);state.current=state.hooks[0]||null;$("#sourceTitle").textContent=data.title||"Your video";$("#sourceDuration").textContent=fmt(data.duration);$("#durationLabel").textContent=fmt(data.duration);$("#hookCount").textContent=state.hooks.length;$("#bestScore").textContent=state.hooks.length?data.hooks[0].score+"/100":"—";$("#language").textContent=data.language||"Detected";$("#hookDescription").textContent="AI found "+state.hooks.length+" hook-worthy moments. Select the ones you want to forge.";if(data.preview_url){$("#sourcePreview").src=apiUrl(data.preview_url);$("#sourcePreview").load()}$("#analysisSection").hidden=false;setProgress(2,"Analysis complete. Select your moments and generate.",100);renderHooks();selectHook(state.hooks[0]);$("#generateBtn").disabled=!state.selected.length;toast("Found "+state.hooks.length+" potential Shorts.")}catch(err){$("#progressPanel").hidden=true;$("#emptyState").hidden=false;toast(err.message)}});
function renderHooks(){const list=$("#hooks");let hooks=[...state.hooks];if($("#sortHooks").value==="score")hooks.sort((a,b)=>b.score-a.score);else hooks.sort((a,b)=>a.start-b.start);list.innerHTML=hooks.map(h=>'<div class="hook-item" data-id="'+h.id+'"><input class="hook-check" type="checkbox" '+(state.selected.includes(h.id)?"checked":"")+'><img class="hook-thumb" src="'+apiUrl(h.thumbnail_url||"")+'" alt=""><div><div class="hook-time">'+fmt(h.start)+" — "+fmt(h.end)+'</div><div class="hook-title">'+escapeHtml(h.title)+'</div><div class="hook-tags"><span class="tag">'+escapeHtml(h.type||"Hook")+'</span><span class="tag">'+(h.score>=90?"High engagement":"Strong moment")+'</span></div></div><span class="hook-score">'+h.score+'%</span><button class="hook-edit" title="Preview"><i class="ph ph-play"></i></button></div>').join("");$$(".hook-item").forEach(row=>{const id=row.dataset.id;row.addEventListener("click",e=>{if(e.target.closest(".hook-check"))return;selectHook(state.hooks.find(h=>h.id===id))});row.querySelector(".hook-check").addEventListener("change",e=>{if(e.target.checked)state.selected.push(id);else state.selected=state.selected.filter(x=>x!==id);state.selected=[...new Set(state.selected)];$("#generateBtn").disabled=!state.selected.length})})}
function selectHook(h){if(!h)return;state.current=h;$("#previewCount").textContent=(state.hooks.findIndex(x=>x.id===h.id)+1)+" / "+state.hooks.length;if(h.preview_url){$("#clipPreview").src=apiUrl(h.preview_url);$("#clipPreview").load();$("#previewPlaceholder").style.display="none"}else $("#previewPlaceholder").style.display="flex"}
$("#generateBtn").addEventListener("click",async()=>{if(!state.selected.length)return;const btn=$("#generateBtn");btn.disabled=true;btn.innerHTML='<i class="ph ph-spinner"></i> Generating…';setProgress(2,"Forging vertical clips…",76);try{const fd=new FormData();fd.append("selected",JSON.stringify(state.selected));fd.append("subtitles",$("#subtitles").checked?"true":"false");fd.append("subtitle_style",$("#subtitleStyle").value);fd.append("broll",$("#broll").checked?"true":"false");fd.append("fmt",document.querySelector(".format.active").dataset.format);if(brollFile.files[0])fd.append("broll_file",brollFile.files[0]);const res=await fetch(apiUrl("/api/generate"),{method:"POST",body:fd});const data=await res.json();if(!res.ok||data.error)throw new Error(data.error||"Generation failed.");state.results=(data.clips||[]).concat(state.results);renderResults();setProgress(2,"Shorts generated successfully.",100);if(data.clips&&data.clips[0]){$("#clipPreview").src=apiUrl(data.clips[0].url);$("#clipPreview").load();$("#previewPlaceholder").style.display="none"}toast("Generated "+((data.clips||[]).length)+" Short(s).")}catch(err){toast(err.message)}finally{btn.disabled=false;btn.innerHTML='<i class="ph ph-sparkle"></i> Generate Shorts'}});
function renderResults(){const el=$("#results");if(!state.results.length){el.innerHTML='<div class="results-empty"><i class="ph ph-film-strip"></i><p>Your generated Shorts will appear here.</p></div>';return}el.innerHTML=state.results.map(c=>'<div class="result-item"><video src="'+apiUrl(c.url)+'" muted></video><div><strong>'+escapeHtml(c.name)+'</strong><small>'+fmt(c.duration||0)+" · Ready"+'</small></div><a class="download-btn" href="'+apiUrl(c.url)+'" download title="Download"><i class="ph ph-download-simple"></i></a></div>').join("")}
$("#downloadPreviewBtn").addEventListener("click",()=>{if(!state.current)return toast("Generate a Short first.");const src=$("#clipPreview").src;if(src){const a=document.createElement("a");a.href=src;a.download="shortforge-short.mp4";a.click()}});
$("#editBtn").addEventListener("click",()=>toast("Clip editor is the next editing layer."));
function wait(ms){return new Promise(r=>setTimeout(r,ms))}function escapeHtml(v){return String(v==null?"":v).replace(/[&<>'"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]))}
