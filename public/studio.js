import {mountTasks} from './tasks.js';
import {mountEffects} from './effects.js';
import {avatar} from './portraits.js';
import {daylight, updateMarket} from './office-environment.js';
import {mountConnections} from './connections.js';
import {editStages,readWorkstation,readDesktopSummary} from './monitor.js';

const roster = {
  carbon:{name:'Gemini 4 Carbon',short:'Carbon',role:'规划主管'},
  astra:{name:'GPT Astra',short:'Astra',role:'审核与分工'},
  codex:{name:'本机 Codex',short:'Codex',role:'代码开发与测试'},
  dot:{name:'Codex Dot',short:'Dot',role:'执行成员'},
  argon:{name:'Gemini 4 Argon',short:'Argon',role:'执行成员'},
  hydrogen:{name:'Gemini 4 Hydrogen',short:'Hydrogen',role:'执行成员'}
};
const states={idle:'空闲',assigned:'等待接力',queued:'已接单 · 排队',coding:'写代码',terminal:'操作终端',browsing:'查阅资料',thinking:'思考中',needs_input:'需要你',error:'遇到问题',done:'已完成'};
const activities={general:'常规任务',code:'代码开发',research:'资料研究',review:'方案复核',writing:'撰写内容',planning:'任务规划',media:'媒体制作'};
const paths={
  chat:'<path d="M20 11c0 4-3.5 7-8 7-1 0-2-.1-3-.4L5 20v-4a6.5 6.5 0 0 1-2-5c0-4 3.5-7 8.5-7S20 7 20 11Z"/><path d="M7 11h1m3 0h1m3 0h1"/>',
  prism:'<path d="m12 2 8.5 6-3 11-11 .5L3 9zM12 2l2 9 6.5-3M3 9l11 2-7.5 8.5m7.5-8.5 3.5 8"/>' ,
  clock:'<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3 2"/>',
  radio:'<circle cx="12" cy="12" r="1.5"/><path d="M8.5 8.5a5 5 0 0 0 0 7m7-7a5 5 0 0 1 0 7M5.5 5.5a9.2 9.2 0 0 0 0 13m13-13a9.2 9.2 0 0 1 0 13"/>',
  play:'<path d="m7 4 12 8-12 8z"/>', cube:'<path d="m12 2 9 5v10l-9 5-9-5V7zM3 7l9 5 9-5m-9 5v10"/>',
  mute:'<path d="M3 9h4l5-4v14l-5-4H3zM16 9l5 6m0-6-5 6"/>',
  volume:'<path d="M3 9h4l5-4v14l-5-4H3zM16 8a6 6 0 0 1 0 8m2-11a10 10 0 0 1 0 14"/>',
  expand:'<path d="M3 9V3h6m6 0h6v6m0 6v6h-6m-6 0H3v-6"/>',
  camera:'<path d="M3 7h4l2-3h6l2 3h4v13H3z"/><circle cx="12" cy="13" r="3"/>',
  users:'<circle cx="9" cy="9" r="3"/><path d="M3 20v-2a6 6 0 0 1 12 0v2m0-14a3 3 0 0 1 0 6m3 2c2 .5 3 2 3 5"/>',
  sun:'<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M19 5l-1.5 1.5m-11 11L5 19"/>',
  moon:'<path d="M20.3 14.6a8.7 8.7 0 0 1-10.9-11A9 9 0 1 0 20.3 14.6z"/>',
  plus:'<path d="M12 4v16M4 12h16"/>',minus:'<path d="M4 12h16"/>',briefcase:'<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V4h8v3M3 12c6 3 12 3 18 0m-9 0v3"/>',
  pulse:'<path d="M2 13h5l3-8 4 15 3-9 2 2h3"/>',arrow:'<path d="M4 12h15m-6-6 6 6-6 6"/>',
  close:'<path d="m5 5 14 14M19 5 5 19"/>',check:'<path d="m4 12 5 5L20 6"/>',copy:'<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V4H4v13h4"/>'
};
const icon=k=>'<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'+(paths[k]||'')+'</svg>';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const $=s=>document.querySelector(s);
document.querySelectorAll('[data-icon]').forEach(el=>el.replaceWith(document.createRange().createContextualFragment(icon(el.dataset.icon))));
document.querySelectorAll('dialog .close').forEach(el=>el.addEventListener('click',()=>el.closest('dialog').close()));
document.querySelectorAll('dialog').forEach(el=>el.addEventListener('click',e=>{
  if(e.target!==el)return;
  const r=el.getBoundingClientRect();
  if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)el.close();
}));
let timer;
function notify(text){const toast=$('#toast');toast.textContent=text;toast.hidden=false;clearTimeout(timer);timer=setTimeout(()=>toast.hidden=true,3500)}
const tasks=mountTasks({roster,notify,icon,esc,onTaskChange:()=>poll(true)});
if (window.chrome?.webview && new URLSearchParams(location.search).get('desktop')==='1') {
  window.officeMayReleaseView=()=>!tasks.hasDraft() && !document.querySelector('dialog[open],.crew.opened') && !$('#slot-name').value.trim();
  window.officeOpenTask=id=>tasks.openFromTray(id);
}
mountConnections({notify});
function setDrawer(open){
  $('#crew').classList.toggle('opened',open);$('#sheet-mask').hidden=!open;
  document.body.classList.toggle('drawer-open',open);
  document.querySelectorAll('.mast,.intro,#scene-panel,.lower-panels,.mobile-actions').forEach(el=>el.inert=open);
  if(open){$('#crew').setAttribute('role','dialog');$('#crew').setAttribute('aria-label','团队成员');$('#crew').setAttribute('aria-modal','true')}
  else{for(const key of ['role','aria-label','aria-modal'])$('#crew').removeAttribute(key)}
  $('#crew-open').setAttribute('aria-expanded',String(open));
  if(open)$('#crew-close').focus();else if(matchMedia('(max-width:899px)').matches)$('#crew-open').focus();
}
$('#crew-open').onclick=()=>setDrawer(true);
$('#crew-close').onclick=$('#sheet-mask').onclick=()=>setDrawer(false);
$('#mobile-dispatch').onclick=()=>$('#dispatch').click();
document.addEventListener('office-show-dispatch',()=>{if($('#crew').classList.contains('opened'))setDrawer(false)});
document.addEventListener('keydown',e=>{
  if(!$('#crew').classList.contains('opened')||document.querySelector('dialog[open]'))return;
  if(e.key==='Escape'){setDrawer(false);return}
  if(e.key!=='Tab')return;
  const buttons=$('#crew').querySelectorAll('button:not(:disabled)'),first=buttons[0],last=buttons[buttons.length-1];
  if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus()}
  if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}
});
matchMedia('(max-width:899px)').addEventListener('change',()=>{if($('#crew').classList.contains('opened'))setDrawer(false)});
const fresh=()=>Object.keys(roster).map(id=>({id,status:'idle',activity:'general',updatedAt:null,collaborator:null}));
let real=fresh(),shown=fresh(),caps={},liveEvents=[],demoEvents=[],scene,disconnected=true,demo=false,demoPhase=0,selection=null,capPending=false;
let guestSeats=[];
let codexEdit=null;
let desktopSummary=null;
const effects=mountEffects({onChange:mode=>scene?.setEffects?.(mode)});
let chatter=true;
try{chatter=localStorage.getItem('hehe-office-chatter')!=='off'}catch{}
function updateChatter(){
  const button=$('#chatter');button.setAttribute('aria-pressed',String(chatter));
  button.title=chatter?'收起预写的场景闲聊，保留头顶动作':'显示预写的办公室闲聊';
  scene?.setChatter?.(chatter);
}
$('#chatter').onclick=()=>{chatter=!chatter;try{localStorage.setItem('hehe-office-chatter',chatter?'on':'off')}catch{}updateChatter()};
updateChatter();
const timeLabel=iso=>new Date(iso).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',hour12:false});
const phaseActions=[
  [['carbon','thinking','planning']], [['carbon','thinking','planning','astra'],['astra','thinking','review','carbon']],
  [['carbon','done','planning'],['astra','done','review']], [['codex','coding','code'],['argon','browsing','research'],['hydrogen','thinking','writing']],
  [['codex','terminal','code'],['argon','done','research'],['hydrogen','done','writing']], [['codex','done','code']]
];
function demoStep(){
  const data=fresh(), now=new Date().toISOString();
  for(const [id,status,activity,collaborator] of phaseActions[demoPhase]){
    Object.assign(data.find(a=>a.id===id),{status,activity,collaborator,updatedAt:now});
    demoEvents.unshift({id,status,activity,at:now});
  }
  demoEvents=demoEvents.slice(0,12);demoPhase=(demoPhase+1)%phaseActions.length;
  render(data);
}
function badge(a){
  const labels={planning:'规划中',review:'审核中',writing:'撰写中'};
  const state=(a.status==='thinking'&&labels[a.activity])||states[a.status]||states.idle;
  const label=disconnected&&!demo?'未连接':a.updatedAt?state:'待报到';
  const kind=['needs_input','error'].includes(a.status)?'alert':['assigned','queued'].includes(a.status)?'waiting':
    a.status==='thinking'?'thinking':a.status!=='idle'?'working':'';
  return '<span class="state '+kind+'"><b class="signal"></b>'+esc(label)+'</span>';
}
function render(agents){
  shown=agents;
  scene?.setState(agents);
  scene?.setCodexEdit(demo||disconnected?null:codexEdit);
  scene?.setSummary(demo||disconnected?null:desktopSummary,demo?'演示模式':'数据暂不可用');
  scene?.setGuests(demo ? [] : guestSeats);
  $('#scene-mode').textContent=demo?'演示模式 · 模拟数据':disconnected?'连接中断':'实时视图';
  $('.viewport-label').classList.toggle('sim',demo||disconnected);
  const team=$('#team');
  if(!team.childElementCount){
    team.innerHTML=Object.keys(roster).map(id=>'<button class="member" data-id="'+id+'">'+avatar(id)+'<span class="member-info"><strong>'+roster[id].name+'</strong><small>'+roster[id].role+'</small></span><span class="slot"></span></button>').join('');
    team.querySelectorAll('button').forEach(el=>el.onclick=()=>openProfile(el.dataset.id));
  }
  agents.forEach(a=>{const slot=team.querySelector('[data-id="'+a.id+'"] .slot');if(slot){slot.parentElement.dataset.busy=String(!disconnected||demo ? ['thinking','coding','terminal','browsing'].includes(a.status) : false);slot.style.marginLeft='auto';slot.innerHTML=badge(a)}});
  const events=demo?demoEvents:liveEvents;
  $('#feed-label').textContent=demo?'演示记录':'本次访问';
  $('#events').innerHTML=events.length?events.slice(0,6).map(e=>'<div class="event" data-id="'+esc(e.id)+'"><i class="signal"></i><b>'+esc(roster[e.id].short)+'</b><span>'+esc(states[e.status])+' · '+esc(activities[e.activity])+'</span><time>'+timeLabel(e.at)+'</time></div>').join(''):'<div class="empty">'+(disconnected?'暂时无法读取实时状态，正在重连。':'等待第一条工作动态。成员报到后，状态变化会出现在这里。')+'</div>';
  if($('#profile').open&&selection)profileText();
}
function profileText(){
  const p=roster[selection],a=shown.find(v=>v.id===selection);if(!p||!a)return;
  const detail=caps[selection]?.detail||'正在核对本机接入状态…';
  $('#dot-profile').hidden=selection!=='dot';
  $('#profile-content').innerHTML='<div class="line-name">'+avatar(selection)+'<strong style="margin-left:10px">'+p.name+'</strong>'+badge(a)+'</div><p>'+p.role+' · '+esc(detail)+'</p><p>'+(demo?'演示模式 · 模拟类别':'当前任务类别')+'　'+esc(a.updatedAt?activities[a.activity]:'待报到')+'<br>'+(demo?'模拟时间':'最后上报')+'　'+esc(a.updatedAt?new Date(a.updatedAt).toLocaleString('zh-CN'):'尚未收到')+'</p>';
  if(selection==='codex'&&!demo&&!disconnected&&codexEdit){
    const heading=document.createElement('strong');
    heading.textContent=[editStages[codexEdit.stage],codexEdit.path].filter(Boolean).join(' · ');
    $('#profile-content').append(heading);
    if(codexEdit.lines?.length){
      const snippet=document.createElement('pre');snippet.textContent=codexEdit.lines.join('\n');
      $('#profile-content').append(snippet);
    }
  }
}
function openProfile(id){
  if(id.startsWith('slot-')){$('#open-slots').click();return;}
  if(id==='president'){$('#dispatch').click();return}
  if(!roster[id])return;
  selection=id;scene?.setSelected(id);profileText();$('#profile').showModal();
}
$('#profile').addEventListener('close',()=>{selection=null;scene?.setSelected(focusedDesk)});
let polling=false,initial=true,refreshRequested=false;
async function poll(force=false){
  if(polling){if(force)refreshRequested=true;return;}
  polling=true;
  try{
    const res=await fetch('/api/status',{signal:AbortSignal.timeout(7500)});if(!res.ok)throw Error();
    const board=await res.json(),agents=board.agents;guestSeats=board.guestSeats||[];
    [codexEdit,desktopSummary]=demo?[null,null]:await Promise.all([readWorkstation(agents),readDesktopSummary()]);
    for(const a of agents){
      if(!Object.hasOwn(roster,a.id))continue;
      const last=real.find(v=>v.id===a.id);
      if(a.updatedAt&&(initial||a.status!==last?.status||a.activity!==last?.activity||a.collaborator!==last?.collaborator))
        liveEvents.unshift({id:a.id,status:a.status,activity:a.activity,at:a.updatedAt});
    }
    liveEvents.sort((a,b)=>b.at.localeCompare(a.at));liveEvents=liveEvents.slice(0,20);initial=false;real=agents.filter(a=>Object.hasOwn(roster,a.id));disconnected=false;
  }catch{disconnected=true}finally{
    polling=false;
    if(!demo)render(real);
    if(refreshRequested){refreshRequested=false;if(!document.hidden)void poll();}
  }
}
function guideText(){
  $('#connections').innerHTML=Object.entries(roster).map(([id,r])=>'<div class="connection"><strong>'+r.name+'</strong> · '+(id==='dot'?'个人会话工单':caps[id]?(caps[id].ready?'CLI 已就绪':'人工交接'):'核对中')+'<small>'+esc(caps[id]?.detail||'正在读取本机 CLI 状态…')+'</small></div>').join('');
}
async function loadCaps(){
  if(capPending)return;capPending=true;
  try{const r=await fetch('/api/capabilities',{signal:AbortSignal.timeout(60000)});if(!r.ok)throw Error();caps=(await r.json()).agents;tasks.setCapabilities(caps);guideText();if($('#profile').open)profileText()}
  catch{$('#connections').textContent='暂时无法核对本机 CLI 状态。请稍后重新打开指南。'}finally{capPending=false}
}
$('#guide').onclick=()=>{guideText();$('#instructions').showModal();loadCaps()};
let demoTimer;
function changeMode(useDemo){
  if(demo===useDemo)return;demo=useDemo;clearInterval(demoTimer);
  $('#live').setAttribute('aria-pressed',String(!demo));$('#demo').setAttribute('aria-pressed',String(demo));
  tasks.setDemo(demo);
  if(demo){demoPhase=0;demoEvents=[];demoStep();demoTimer=setInterval(demoStep,6200)}else{render(real);poll()}
}
$('#live').onclick=()=>changeMode(false);$('#demo').onclick=()=>changeMode(true);
let lighting,manualLight=false;
function applyLight(mode){
  lighting=mode;scene?.setLighting(mode);$('.viewport').classList.toggle('night',mode==='night');
  $('#lighting-label').textContent=(mode==='day'?'日间':'夜间')+' · 人物日常演绎';
  $('#light').innerHTML=icon(mode==='day'?'sun':'moon');$('#light').title=mode==='day'?'切换至夜间':'切换至日间';$('#light').setAttribute('aria-label',$('#light').title);
}
function tick(){
  const now=new Date();$('#clock').textContent=timeLabel(now);
  if(!manualLight){const next=daylight(now);if(next!==lighting)applyLight(next)}
}
$('#light').onclick=()=>{manualLight=true;applyLight(lighting==='day'?'night':'day')};
let view='overview',zoom=1,focusedDesk=null;
function cameraView(next){
  focusedDesk=null;$('#desk-lens').hidden=true;view=next;
  document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.view===view)));
  scene?.setSelected(null);scene?.setView(view);
}
$('#desk-lens').onclick=()=>cameraView('overview');
$('#look-desk').onclick=()=>{
  const id=selection;if(!roster[id])return;
  $('#profile').close();
  if($('#crew').classList.contains('opened'))setDrawer(false);
  cameraView('workstations');focusedDesk=id;scene?.setSelected(id);scene?.focusDesk?.(id);
  $('#desk-lens span').textContent=roster[id].short+' 的工位';
  $('#desk-lens').setAttribute('aria-label',roster[id].short+' 的工位近景，返回全景');
  $('#desk-lens').hidden=false;$('#scene-panel').scrollIntoView({block:'nearest'});$('#desk-lens').focus({preventScroll:true});
};
function showZoom(next){zoom=next;$('#reset-view').textContent=Math.round(zoom*100)+'%';$('#zoom-in').disabled=zoom>=1.5;$('#zoom-out').disabled=zoom<=.8}
function adjustZoom(delta){showZoom(Math.min(1.5,Math.max(.8,Math.round((zoom+delta)*10)/10)));scene?.setZoom?.(zoom)}
document.querySelectorAll('[data-view]').forEach(el=>el.onclick=()=>cameraView(el.dataset.view));
$('#zoom-in').onclick=()=>adjustZoom(.1);$('#zoom-out').onclick=()=>adjustZoom(-.1);
$('#reset-view').onclick=()=>{cameraView('overview');showZoom(1);scene?.resetCamera?.();scene?.setZoom?.(1)};
$('#expand').onclick=async()=>{
  const panel=$('#scene-panel');
  try{if(document.fullscreenElement)await document.exitFullscreen();else if(panel.requestFullscreen)await panel.requestFullscreen();else panel.classList.toggle('expanded')}catch{panel.classList.toggle('expanded')}
};
document.addEventListener('keydown',e=>{if(e.key==='Escape')$('#scene-panel').classList.remove('expanded')});
let music=null,musicTimer=null;
async function toggleMusic(){
  if(music){clearInterval(musicTimer);const old=music;music=null;await old.close()}
  else{
    try{
      music=new AudioContext();await music.resume();const notes=[261.63,329.63,392,293.66,349.23,440,246.94,392];let i=0;
      const play=()=>{if(!music||document.hidden)return;const start=music.currentTime,osc=music.createOscillator(),amp=music.createGain();osc.type='sine';osc.frequency.value=notes[i++%notes.length];amp.gain.setValueAtTime(.0001,start);amp.gain.exponentialRampToValueAtTime(.025,start+.16);amp.gain.exponentialRampToValueAtTime(.0001,start+1.8);osc.connect(amp).connect(music.destination);osc.start();osc.stop(start+1.85);osc.onended=()=>{amp.disconnect();osc.disconnect()}};
      play();musicTimer=setInterval(play,1050);
    }catch{music=null;notify('当前浏览器无法播放环境音乐。')}
  }
  $('#sound').innerHTML=icon(music?'volume':'mute');$('#sound').setAttribute('aria-pressed',String(!!music));
}
$('#sound').onclick=toggleMusic;
$('#enter').onclick=()=>{if($('#welcome-sound').checked)toggleMusic();$('#welcome').close()};
$('#welcome').addEventListener('close',()=>{try{localStorage.setItem('hehe-office-visited','1')}catch{}});
function shouldWelcome(){try{return !localStorage.getItem('hehe-office-visited')}catch{return true}}
if(shouldWelcome())$('#welcome').showModal();
const market=()=>updateMarket(scene);
tick();setInterval(()=>{if(!document.hidden)tick();},30000);guideText();poll();loadCaps();setInterval(()=>{if(!document.hidden)poll();},3500);
document.addEventListener('visibilitychange',()=>{if(!document.hidden){tick();poll();}});
window.addEventListener('pagehide',e=>{if(!e.persisted){scene?.dispose();scene=null;}});
setInterval(()=>{if(!document.hidden)loadCaps()},65000);
import('./scene.js').then(({mountOffice})=>{
  scene=mountOffice($('#canvas'));scene.setEffects?.(effects.mode);updateChatter();scene.setLighting(lighting);scene.setState(shown);scene.setCodexEdit(demo||disconnected?null:codexEdit);scene.setGuests(demo?[]:guestSeats);scene.setView(view);if(focusedDesk)scene.focusDesk?.(focusedDesk);scene.setZoom?.(zoom);scene.onZoom?.(showZoom);scene.onSelect(openProfile);market();setInterval(()=>{if(!document.hidden)market()},60000);
}).catch(()=>{$('#canvas').textContent='空间视图加载失败，请刷新页面重试。'});
window.addEventListener('hashchange',()=>document.querySelectorAll('.mast nav a').forEach(a=>a.classList.toggle('current',a.hash===(location.hash||'#office'))));

