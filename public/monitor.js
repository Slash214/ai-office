// Workstation textures use public status and, on the owner's computer, actual Codex edits.
export const editStages={planning:'分析工程',reading:'读取源码',edited:'已写入候选版',testing:'运行测试',delivered:'已交付',error:'执行遇到问题'};

export async function readWorkstation(agents) {
  const status=agents.find(person=>person.id==='codex')?.status;
  if(!['coding','terminal','done','error'].includes(status))return null;
  try {
    const response=await fetch('/api/workstation',{cache:'no-store',signal:AbortSignal.timeout(3000)});
    if(response.ok)return (await response.json()).codex||null;
  } catch {}
  return null;
}
const displayNames={carbon:'CARBON',astra:'ASTRA',codex:'CODEX',dot:'DOT',argon:'ARGON',hydrogen:'HYDROGEN'};
const states={idle:'待命',assigned:'等待接力',queued:'已接单排队',coding:'编写代码',terminal:'操作终端',browsing:'查阅资料',thinking:'思考中',needs_input:'等待协助',error:'遇到问题',done:'已完成'};
const categories={general:'常规任务',code:'代码开发',research:'资料研究',review:'方案复核',writing:'撰写内容',planning:'任务规划',media:'媒体制作'};

export function workLabel(status,activity){
  const work={planning:'规划任务',review:'审核分工',writing:'撰写文稿'};
  return (status==='thinking'&&work[activity])||states[status]||states.idle;
}

export async function readDesktopSummary(){
  try{
    const r=await fetch('/api/desktop',{cache:'no-store',signal:AbortSignal.timeout(3000)});
    if(r.ok)return await r.json();
  }catch{}
  return null;
}

export function drawTaskBoard(c,w,h,data,history,hint){
  c.save();
  c.fillStyle=history?'#193c3d':'#142642';c.fillRect(0,0,w,h);
  c.fillStyle=history?'#8ae2c9':'#88d7fa';c.fillRect(0,0,8,h);
  c.font='bold 31px "Microsoft YaHei UI",sans-serif';
  c.fillText(history?'最近工单动态':'团队工单',24,49);
  c.fillStyle='#dfedf7';
  if(!data){c.fillText(hint,24,151);c.restore();return;}
  if(history){
    c.font='28px "Microsoft YaHei UI",sans-serif';
    (data.recent||[]).slice(0,3).forEach((row,i)=>{
      const when=new Date(row.at).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',hour12:false});
      c.fillText(when+'  '+row.text,24,107+60*i,w-46);
    });
    if(!data.recent?.length)c.fillText('暂无工单动态',24,151);
  }else{
    c.font='bold 44px "Microsoft YaHei UI",sans-serif';c.fillText(data.headline,24,140,w-45);
    c.font='27px "Microsoft YaHei UI",sans-serif';
    c.fillText('执行 '+data.running+'    排队 '+data.queued+'    待验收 '+data.reviews,24,239,w-45);
  }
  c.restore();
}

export function drawMonitor(c,w,h,{id,color,status='idle',activity='general',phase=0,edit=null}) {
  c.save();
  c.scale(w/600,h/300);
  c.fillStyle='#0c172b'; c.fillRect(0,0,600,300);
  c.fillStyle=color; c.fillRect(0,0,600,9);
  if(id==='codex'&&edit&&Object.hasOwn(editStages,edit.stage)){
    c.fillStyle='#a5f4ec'; c.font='700 29px "Microsoft YaHei UI",sans-serif';
    c.fillText('CODEX  /  '+editStages[edit.stage],20,47);
    c.fillStyle='#abc1e6'; c.font='23px Consolas,monospace';
    c.fillText(edit.path||'工作室工程',20,85,555);
    c.fillStyle='#283956'; c.fillRect(20,100,560,2);
    c.font='25px Consolas,"Microsoft YaHei UI",monospace';
    (edit.lines||[]).slice(0,5).forEach((line,i)=>{
      c.fillStyle=line.startsWith('−')?'#ffacbb':'#99ead2';
      c.fillText(line.slice(0,37),19,137+i*34);
    });
    c.restore();return;
  }
  c.font='700 34px "Segoe UI",sans-serif'; c.fillText(displayNames[id]||'STUDIO',25,66);
  c.fillStyle='#ecf4ff'; c.font='700 61px "Microsoft YaHei UI","PingFang SC",sans-serif';
  c.fillText(workLabel(status,activity),25,165,359);
  c.fillStyle='#344561'; c.fillRect(26,206,548,2);
  c.fillStyle='#bacce7'; c.font='29px "Microsoft YaHei UI","PingFang SC",sans-serif';
  c.fillText(status==='idle'?'工位待命':categories[activity]||categories.general,27,264);
  c.strokeStyle=color; c.fillStyle=color; c.lineWidth=8; c.lineCap='round'; c.lineJoin='round';
  function line(points) {c.beginPath();points.forEach(([x,y],i)=>i?c.lineTo(x,y):c.moveTo(x,y));c.stroke()}
  if(status==='done') {
    c.beginPath();c.arc(488,125,49,0,Math.PI*2);c.stroke();
    line([[463,125],[481,143],[515,105]]);
  } else if(status==='coding'||status==='terminal') {
    line([[463,97],[439,124],[463,151]]);line([[515,97],[539,124],[515,151]]);
    line([[497,94],[480,153]]);
  } else if(status==='needs_input'||status==='error') {
    line([[489,82],[543,168],[435,168],[489,82]]);line([[489,111],[489,132]]);
    c.beginPath();c.arc(489,148,4,0,7);c.fill();
  } else if(status==='thinking') {
    line([[431,144],[475,108],[534,135]]);
    [[431,144],[475,108],[534,135]].forEach(([x,y],i)=>{c.fillStyle='#0c172b';c.beginPath();c.arc(x,y,10+(i===Math.floor(phase)%3?3:0),0,7);c.fill();c.stroke()});
  } else if(['browsing','assigned','queued'].includes(status)) {
    c.strokeRect(439,83,90,81);line([[452,105],[506,105]]);line([[452,124],[493,124]]);line([[452,143],[502,143]]);
  } else {
    c.beginPath();c.arc(488,125,39,0,Math.PI*2);c.stroke();c.beginPath();c.arc(488,125,8,0,Math.PI*2);c.fill();
  }
  c.restore();
}

