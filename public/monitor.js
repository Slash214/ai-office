// Local workstation display. Only categorical public status enters this texture.
const displayNames={carbon:'CARBON',astra:'ASTRA',codex:'CODEX',dot:'DOT',argon:'ARGON',hydrogen:'HYDROGEN'};
const states={idle:'待命',coding:'编写代码',terminal:'操作终端',browsing:'查阅资料',thinking:'思考中',needs_input:'等待协助',error:'遇到问题',done:'已完成'};
const categories={general:'常规任务',code:'代码开发',research:'资料研究',review:'方案复核',writing:'撰写内容',planning:'任务规划',media:'媒体制作'};

export function drawMonitor(c,w,h,{id,color,status='idle',activity='general',phase=0}) {
  c.save();
  c.scale(w/600,h/300);
  c.fillStyle='#0c172b'; c.fillRect(0,0,600,300);
  c.fillStyle=color; c.fillRect(0,0,600,9);
  c.font='700 34px "Segoe UI",sans-serif'; c.fillText(displayNames[id]||'STUDIO',25,66);
  c.fillStyle='#ecf4ff'; c.font='700 61px "Microsoft YaHei UI","PingFang SC",sans-serif';
  c.fillText(states[status]||states.idle,25,165,359);
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
  } else if(status==='browsing') {
    c.strokeRect(439,83,90,81);line([[452,105],[506,105]]);line([[452,124],[493,124]]);line([[452,143],[502,143]]);
  } else {
    c.beginPath();c.arc(488,125,39,0,Math.PI*2);c.stroke();c.beginPath();c.arc(488,125,8,0,Math.PI*2);c.fill();
  }
  c.restore();
}

