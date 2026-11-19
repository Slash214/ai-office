// Local stage directions. The only bridge input is the public status snapshot.
const MEETING = {
  carbon:[3.33,-3.47,0], astra:[5.03,-3.47,0], dot:[3.33,-.59,Math.PI],
  argon:[5.03,-.59,Math.PI], hydrogen:[6.33,-2.03,-Math.PI/2], codex:[2.03,-2.03,Math.PI/2],
};
const WAITING = new Set(['assigned', 'queued']);
const BUSY = new Set(['assigned', 'queued', 'coding', 'terminal', 'browsing', 'thinking', 'needs_input', 'error']);
const AMBIENT = {
  home: ['idle', '在工位小憩', '回工位'], coffee: ['coffee', '喝咖啡', '去茶水间'],
  arcade: ['game', '摸鱼打街机', '去游戏角'], rest: ['lounge', '沙发摸鱼', '去休息室'],
  focus: ['read', '在看规划板', '去看规划板'], print: ['read', '整理打印稿', '去打印区'],
  chatA: ['chat', '聊两句', '去找同伴'], chatB: ['chat', '聊两句', '去找同伴'],
};
const WORK = {
  assigned: ['read','等待接力'], queued: ['read','已接单排队'],
  coding: ['type','编写代码'], terminal: ['type','操作终端'], browsing: ['read','查阅资料'],
  thinking: ['think','梳理思路'], needs_input: ['attention','等待协助'], error: ['error','遇到问题'],
};
const THINKING = {planning:['think','规划任务'],review:['read','审核分工'],writing:['type','撰写文稿']};
const BREAKS = ['coffee','home','print','rest','home','arcade','focus','home'];
const CHAT = [
  ['茶水间还有冰咖啡。','等我这局结束！'],
  ['窗外的灯亮起来了。','这个角度真好看。'],
  ['新豆子闻起来很香。','我去拿两个杯子。'],
  ['刚才那关你过了吗？','差一格，再试试。'],
];
const distance = (a, b) => Math.hypot(a.x - b.x, a.z - b.z);

const BODY_RADIUS = .49;
const SEPARATION = 1.02;
const GRID_STEP = .24;
const FLOOR = {left:-10.21,right:10.49,back:-6.16,front:6.51};

const position = (x,z) => ({x,z});
const yawTo = (a,b) => Math.atan2(b.x-a.x,b.z-a.z);
const offset = (p,x,z) => position(p.x+x,p.z+z);
const between = (a,b,t) => position(a.x+(b.x-a.x)*t,a.z+(b.z-a.z)*t);

// Footprints follow the furniture in scene.js and rooms.js. Keep the chair
// separate from the desk so only its own seat transition may enter it.
function furniture(homes) {
  const items = [];
  function add(x,z,width,depth,yaw=0,seat=null){
    items.push({x,z,hw:width/2,hd:depth/2,c:Math.cos(yaw),s:Math.sin(yaw),seat});
  }
  for(const [id,home] of Object.entries(homes)){
    const desk = home.desk ?? offset(home,.35,-1.30);
    add(desk.x,desk.z,3.03,1.36);
    add(home.x,home.z,.90,.96,home.yaw,'home-'+id);
  }
  add(4.18,-2.03,3.64,2.02,0,'meeting-table');
  for(const id of Object.keys(homes)){
    const [x,z,yaw]=MEETING[id];
    add(x,z,.90,.96,yaw,'meeting-'+id);
  }
  add(-5.73,-6.35,2.42,.93);
  add(3.46,-6.24,3.95,.90);
  add(-6.72,-6.38,.86,.86);
  add(6.10,-6.49,1.08,1.08);
  add(5.42,6.12,1.15,1.15);
  add(-3.15,6.04,3.75,.93);
  add(1.79,6.15,2.65,.79);
  add(8.84,-5.97,3.56,1.28);
  add(-10.25,-2.38,.79,3.52);
  add(-9.51,-5.79,2.32,.99);
  add(-10.05,1.94,1.61,1.12,Math.PI/2);
  add(-9.91,4.83,1.73,1.06,Math.PI/2,'rest');
  add(-10.41,3.39,.79,.79);
  add(8.88,2.35,2.48,.99,.16,'chatA');
  add(10.06,5.11,1.22,.99,-1.94,'chatB');
  add(9.30,3.41,.84,.84);
  add(10.45,1.83,1.03,1.03);
  add(9.47,-2.03,1.48,1.42,-.26);
  add(7.75,-2.43,1.14,1.59,-.10);
  return items;
}

// Test the swept segment instead of checking endpoints. Local-space slabs
// keep the clearance around rotated chairs, counters and cabinets.
function rectangleHit(a,b,item,padding){
  const ax=a.x-item.x, az=a.z-item.z, bx=b.x-item.x, bz=b.z-item.z;
  const x=ax*item.c-az*item.s, z=ax*item.s+az*item.c;
  const dx=(bx-ax)*item.c-(bz-az)*item.s, dz=(bx-ax)*item.s+(bz-az)*item.c;
  let start=0, end=1;
  for(const [p,v,edge] of [[x,dx,item.hw+padding],[z,dz,item.hd+padding]]){
    if(Math.abs(v)<1e-7){
      if(Math.abs(p)>edge)return false;
      continue;
    }
    const t0=(-edge-p)/v,t1=(edge-p)/v;
    start=Math.max(start,Math.min(t0,t1));
    end=Math.min(end,Math.max(t0,t1));
    if(start>end)return false;
  }
  return true;
}
function meetingTableHit(a,b,item,padding){
  // Work in the unit circle scaled by the tabletop's two radii.
  const x=(a.x-item.x)/item.hw,z=(a.z-item.z)/item.hd;
  const dx=(b.x-a.x)/item.hw,dz=(b.z-a.z)/item.hd;
  let start=0,end=1;
  for(let i=0;i<8;i++){
    const angle=i*Math.PI/4,c=Math.cos(angle),s=Math.sin(angle);
    const edge=Math.cos(Math.PI/8)+padding*Math.hypot(c/item.hw,s/item.hd);
    const p=x*c+z*s,v=dx*c+dz*s;
    if(Math.abs(v)<1e-7){
      if(p>edge)return false;
    } else if(v>0)end=Math.min(end,(edge-p)/v);
    else start=Math.max(start,(edge-p)/v);
    if(start>end)return false;
  }
  return true;
}
function blocked(items,a,b,pad=BODY_RADIUS,except=null){
  if([a,b].some(p=>p.x<FLOOR.left||p.x>FLOOR.right||p.z<FLOOR.back||p.z>FLOOR.front))return true;
  return items.some(item=>{
    if(except && item.seat===except)return false;
    if(item.seat==='meeting-table')return meetingTableHit(a,b,item,pad);
    if(Math.min(a.x,b.x)>item.x+item.hw+item.hd+pad||Math.max(a.x,b.x)<item.x-item.hw-item.hd-pad||
       Math.min(a.z,b.z)>item.z+item.hw+item.hd+pad||Math.max(a.z,b.z)<item.z-item.hw-item.hd-pad)return false;
    return rectangleHit(a,b,item,pad);
  });
}
function peersBlock(a,b,others){
  const dx=b.x-a.x,dz=b.z-a.z,len=dx*dx+dz*dz;
  return others.some(p=>{
    const before=distance(a,p);
    if(before<SEPARATION && (a.x-p.x)*dx+(a.z-p.z)*dz>=0)return false;
    const t=len?Math.max(0,Math.min(1,((p.x-a.x)*dx+(p.z-a.z)*dz)/len)):0;
    return distance(p,between(a,b,t))<SEPARATION-1e-6;
  });
}
function buildGrid(items){
  const cols=Math.floor((FLOOR.right-FLOOR.left)/GRID_STEP)+1;
  const rows=Math.floor((FLOOR.front-FLOOR.back)/GRID_STEP)+1;
  const nodes=Array.from({length:cols*rows},(_,i)=>position(FLOOR.left+i%cols*GRID_STEP,FLOOR.back+Math.floor(i/cols)*GRID_STEP));
  const free=nodes.map(p=>!blocked(items,p,p));
  const neighbors=nodes.map((node,i)=>{
    if(!free[i])return [];
    const col=i%cols,row=Math.floor(i/cols),links=[];
    for(let dz=-1;dz<=1;dz++)for(let dx=-1;dx<=1;dx++){
      if((dx===0&&dz===0)||col+dx<0||col+dx>=cols||row+dz<0||row+dz>=rows)continue;
      const n=i+dx+dz*cols;
      if(free[n]&&!blocked(items,node,nodes[n]))links.push(n);
    }
    return links;
  });
  function nearby(p){
    const cx=Math.round((p.x-FLOOR.left)/GRID_STEP),cz=Math.round((p.z-FLOOR.back)/GRID_STEP);
    const result=[];
    for(let row=Math.max(0,cz-3);row<Math.min(rows,cz+4);row++){
      for(let col=Math.max(0,cx-3);col<Math.min(cols,cx+4);col++){
        const i=row*cols+col;
        if(free[i]&&!blocked(items,p,nodes[i]))result.push(i);
      }
    }
    return result;
  }
  return {nodes,neighbors,nearby};
}
function push(heap,item){
  let i=heap.length;
  heap.push(item);
  while(i>0){
    const parent=(i-1)>>1;
    if(heap[parent].score<=item.score)break;
    heap[i]=heap[parent];i=parent;
  }
  heap[i]=item;
}
function pop(heap){
  const head=heap[0],tail=heap.pop();
  if(!heap.length)return head;
  let i=0;
  while(i*2+1<heap.length){
    let child=i*2+1;
    if(child+1<heap.length&&heap[child+1].score<heap[child].score)child++;
    if(heap[child].score>=tail.score)break;
    heap[i]=heap[child];i=child;
  }
  heap[i]=tail;
  return head;
}
function findPath(floor,start,goal,others){
  const valid=(a,b)=>!blocked(floor.items,a,b)&&!peersBlock(a,b,others);
  if(valid(start,goal))return [goal];
  const {nodes,neighbors,nearby}=floor.grid;
  const targets=new Set(nearby(goal).filter(i=>!peersBlock(nodes[i],goal,others)));
  if(!targets.size)return null;
  const costs=new Float64Array(nodes.length).fill(Infinity);
  const from=new Int32Array(nodes.length).fill(-1);
  const heap=[];
  for(const i of nearby(start)){
    if(peersBlock(start,nodes[i],others))continue;
    costs[i]=distance(start,nodes[i]);
    push(heap,{i,score:costs[i]+distance(nodes[i],goal),cost:costs[i]});
  }
  while(heap.length){
    const {i,cost}=pop(heap);
    if(cost!==costs[i])continue;
    const a=nodes[i];
    if(targets.has(i)){
      const path=[goal];
      for(let j=i;j>=0;j=from[j])path.push(nodes[j]);
      path.reverse();
      const smooth=[];
      let at=start;
      for(let j=0;j<path.length;){
        let k=path.length-1;
        while(k>j&&!valid(at,path[k]))k--;
        at=path[k];smooth.push(at);j=k+1;
      }
      return smooth;
    }
    for(const next of neighbors[i]){
      const b=nodes[next],total=cost+distance(a,b);
      if(total>=costs[next]||peersBlock(a,b,others))continue;
      costs[next]=total;from[next]=i;
      push(heap,{i:next,cost:total,score:total+distance(b,goal)});
    }
  }
  return null;
}
function buildFloor(homes,locations){
  const items=furniture(homes),stops=new Map();
  function stop(name,at){
    const yaw=at.yaw??0;
    if(!at.seated){
      if(!blocked(items,at,at))stops.set(name,{at,yaw,seated:false,entries:[at]});
      return;
    }
    const entries=[];
    // Approach the front or one of the open sides. The transition after
    // walking stops may cross the occupied chair footprint, never a neighbor's.
    const angles=at.frontEntry?[0,.19,-.19,.38,-.38]:[0,.6,-.6,1.03,-1.03,1.50,-1.50,1.9,-1.9];
    for(const radius of [1.03,1.19,1.35,1.51]){
      for(const angle of angles){
        const entry=offset(at,radius*Math.sin(yaw+angle),radius*Math.cos(yaw+angle));
        if(!blocked(items,entry,entry)&&!blocked(items,entry,at,.42,name))entries.push(entry);
      }
    }
    if(!entries.length)throw Error('No floor access for '+name);
    stops.set(name,{at,yaw,seated:true,entries});
  }
  for(const [id,home] of Object.entries(homes))stop('home-'+id,{...home,seated:true});
  for(const id of Object.keys(homes)){
    const [x,z,yaw]=MEETING[id];
    stop('meeting-'+id,{x,z,yaw,seated:true});
  }
  for(const [name,at] of Object.entries(locations))if(AMBIENT[name])stop(name,at);
  return {items,stops,grid:buildGrid(items)};
}
function ready(person){
  return person.arrived;
}
function choosePath(person,target,floor,others){
  const entries=[...target.entries].sort((a,b)=>distance(person,a)-distance(person,b));
  for(const entry of entries){
    const path=findPath(floor,person,entry,others);
    if(path)return {entry,path};
  }
  return null;
}
function turn(person,yaw,amount){
  person.angle+=Math.atan2(Math.sin(yaw-person.angle),Math.cos(yaw-person.angle))*amount;
}
function reservedPositions(others){
  return others.flatMap(p=>{
    if(!p.seat||p.arrived)return [p];
    const stop=p.seat.name===p.target?p.seat.at:p.seat.entry;
    return [p,between(p,stop,.5),stop];
  });
}
function seatSpace(at,entry,others){
  return !peersBlock(at,entry,reservedPositions(others));
}
function advance(person,target,floor,others,dt,speed,time){
  const {seat}=person;
  if(seat){
    const exiting=seat.name!==person.target;
    if(exiting&&seat.progress===1){
      const open=[seat.entry,...seat.entries].find(entry=>seatSpace(seat.at,entry,others));
      if(!open){
        if(person.blockedSince===null)person.blockedSince=time;
        return false;
      }
      seat.entry=open;
    }
    turn(person,seat.yaw,1-Math.exp(-dt*18));
    if(!exiting&&seat.progress===0&&Math.cos(person.angle-seat.yaw)<.91)return false;
    const progress=Math.max(0,Math.min(1,seat.progress+(exiting?-1:1)*dt*2.5));
    const next=between(seat.entry,seat.at,progress);
    if(peersBlock(person,next,others)){
      if(person.blockedSince===null)person.blockedSince=time;
      return false;
    }
    Object.assign(person,next);
    person.blockedSince=null;
    seat.progress=progress;
    if(exiting&&progress===0){person.seat=null;person.arrived=false;}
    else if(!exiting&&progress===1)person.arrived=true;
    return false;
  }
  if(person.arrived)return false;
  if(person.yieldUntil>time)return false;
  const reservations=reservedPositions(others);
  if(!person.path.length){
    if(person.retryAt>time)return false;
    const result=choosePath(person,target,floor,reservations);
    if(result)Object.assign(person,result);
    else{
      person.retryAt=time+.35;
      const peer=others.find(p=>p.id&&!p.arrived&&distance(person,p)<1.50&&
        p.blockedSince!==null&&time-p.blockedSince>.65&&(p.seat||person.id>p.id));
      if(person.blockedSince===null)person.blockedSince=time;
      if(!peer||time-person.blockedSince<.8)return false;
      // In a one-person passage, one of the walkers backs up into open
      // floor and waits briefly, giving the other a consistent right of way.
      const away=yawTo(peer,person);
      const parking=[];
      for(const radius of [1.55,2.10,2.65]){
        for(const angle of [0,.55,-.55,1.1,-1.1,1.60,-1.60]){
          const spot=offset(person,radius*Math.sin(away+angle),radius*Math.cos(away+angle));
          if(blocked(floor.items,spot,spot)||others.some(p=>distance(spot,p)<1.27))continue;
          const room=[0,Math.PI/2,Math.PI,-Math.PI/2].filter(yaw=>{
            const exit=offset(spot,.64*Math.sin(yaw),.64*Math.cos(yaw));
            return !blocked(floor.items,spot,exit);
          }).length;
          parking.push({spot,score:room*2-distance(person,spot)});
        }
      }
      parking.sort((a,b)=>b.score-a.score);
      for(const {spot} of parking){
        const path=findPath(floor,person,spot,reservations);
        if(path){person.yielding=true;person.path=path;person.entry=null;break;}
      }
      if(!person.path.length)return false;
    }
  }
  let budget=speed*dt, travelled=0;
  while(person.path.length&&budget>0){
    const next=person.path[0],length=distance(person,next),step=Math.min(budget,length);
    if(length<.00001){person.path.shift();continue;}
    const at=between(person,next,step/length);
    if(peersBlock(person,at,reservations)){
      // Replan around the moving obstacle on the next bounded retry.
      if(person.blockedSince===null)person.blockedSince=time;
      person.path=[];person.retryAt=time+.18;
      person.yielding=false;
      break;
    }
    person.angle=yawTo(person,at);Object.assign(person,at);
    budget-=step;travelled+=step;
    if(step===length)person.path.shift();
  }
  if(travelled>0)person.blockedSince=null;
  if(person.yielding&&!person.path.length){
    person.yielding=false;person.yieldUntil=time+1.4;
  }
  person.phase=(person.phase+travelled*4.1)%(2*Math.PI);
  if(person.path.length===0&&person.entry&&distance(person,person.entry)<.00001){
    if(!target.seated)person.arrived=true;
    else if(seatSpace(person.entry,target.at,others))
      person.seat={...target,entry:person.entry,progress:0,name:person.target};
    else person.retryAt=time+.18;
  }
  return travelled>.00001;
}
function snap(person,name,stop){
  Object.assign(person,stop.at);
  person.angle=stop.yaw;
  person.seat=stop.seated?{...stop,entry:stop.entries[0],progress:1,name}:null;
  person.path=[];person.arrived=true;person.target=name;
}

export function createOfficeLife({homes,locations,now=Date.now}) {
  const floor=buildFloor(homes,locations);
  const initial=['home-carbon','home-astra','arcade','chatA','chatB'];
  const people=Object.keys(homes).map((id,i)=>{
    const target=floor.stops.has(initial[i])?initial[i]:'home-'+id;
    const p={id,path:[],phase:i*.7,entry:null,retryAt:0,blockedSince:null,yielding:false,yieldUntil:0,
      status:'idle',activity:null,collaborator:null,stamp:null,celebrateUntil:0,
      dwellUntil:[1.3,6.4,10.2,6,6,12][i],turn:i*2,ambient:target,row:{id}};
    snap(p,target,floor.stops.get(target));
    return p;
  });
  const byId = new Map(people.map(p=>[p.id,p]));
  let time=0, nextChat=2.2, chat=null, pairStart=3, chatIndex=0, wasReduced=false;
  const rows=people.map(p=>p.row);

  function setState(agents=[]) {
    const at=now();
    for (const p of people) {
      const a=agents.find(entry=>entry.id===p.id), previous=p.status;
      const stamp=a?.updatedAt??null, age=stamp ? at-Date.parse(stamp) : 0;
      const status=a?.status??'idle';
      if(status==='done' && (previous!=='done'||stamp!==p.stamp) && age<12000)
        p.celebrateUntil=time+1.5;
      if(status!=='done')p.celebrateUntil=0;
      p.status=status;p.activity=a?.activity??null;p.stamp=stamp;p.collaborator=a?.collaborator??null;
      if(BUSY.has(previous) && !BUSY.has(status)){
        p.ambient='home-'+p.id;
        p.dwellUntil=time+1.9;
      }
    }
  }

  function meetings(){
    const pairs=new Map();
    for(const p of people){
      const other=byId.get(p.collaborator);
      if(!other||other===p||!BUSY.has(p.status)||WAITING.has(p.status)||WAITING.has(other.status)||['needs_input','error'].includes(p.status)||
         ['needs_input','error'].includes(other.status)||other.celebrateUntil>time||
         pairs.has(p.id)||pairs.has(other.id))continue;
      pairs.set(p.id,other.id);pairs.set(other.id,p.id);
    }
    return pairs;
  }
  function updateChat(pairs,soft){
    const free=p=>!BUSY.has(p.status)&&!pairs.has(p.id)&&p.celebrateUntil<=time;
    if(chat && (chat.people.some(p=>!free(p)) || (chat.started===null && time-chat.created>26) || (chat.started!==null && time-chat.started>10.8))){
      for(const p of chat.people){p.ambient='home-'+p.id;p.dwellUntil=null;}
      chat=null;nextChat=time+(soft?35:24);
    }
    if(!chat && time>=nextChat && floor.stops.has('chatA') && floor.stops.has('chatB')){
      const available=people.map((_,i)=>people[(pairStart+i)%people.length]).filter(free);
      if(available.length>=2){
        chat={people:available.slice(0,2),started:null,created:time,lines:CHAT[chatIndex++%CHAT.length]};
        pairStart=(pairStart+2)%people.length;
      } else nextChat=time+3;
    }
  }
  function nextBreak(p) {
    for(let i=0;i<BREAKS.length;i++){
      const slot=BREAKS[p.turn++%BREAKS.length];
      const name=slot==='home'?'home-'+p.id:slot;
      if(name!==p.target && floor.stops.has(name) &&
        !people.some(other=>other!==p && (other.ambient===name||other.target===name)))return name;
    }
    return 'home-'+p.id;
  }

  function tick(dt,{reducedMotion=false,soft=false,obstacles=[],standby=''}={}) {
    const delta=Number.isFinite(dt)?Math.max(0,Math.min(dt,.10)):0;
    time+=delta;
    const pairs=meetings();
    if(reducedMotion || standby){
      chat=null;nextChat=time+2.2;
    }else updateChat(pairs,soft);
    for(const p of people){
      const r=p.row, station='home-'+p.id, partner=pairs.get(p.id);
      const work=(p.status==='thinking'&&THINKING[p.activity])||WORK[p.status];
      const seat=chat?.people.indexOf(p)??-1;
      const celebrating=p.celebrateUntil>time;
      let target,pose,caption,travel;
      if(partner){
        target='meeting-'+p.id;pose='meeting';caption=p.activity==='review'?'审核分工':'协作讨论';travel='去会议区';
      }else if(work){
        target=station;[pose,caption]=work;travel=WAITING.has(p.status)?'接单回工位':'返回工位';
      }else if(standby && p.status==='idle'){
        target=station;pose='read';caption=standby;travel='返回工位';
      }else{
        if(reducedMotion || (p.target?.startsWith('meeting-') && p.ambient?.startsWith('chat')))
          p.ambient=station;
        if(seat>=0)p.ambient=seat===0?'chatA':'chatB';
        else if(!reducedMotion && !celebrating && ready(p) && p.dwellUntil!==null && time>=p.dwellUntil)p.ambient=nextBreak(p);
        target=p.ambient;
        [pose,caption,travel]=AMBIENT[target.startsWith('home-')?'home':target];
      }
      const stop=floor.stops.get(target);
      const changed=target!==p.target;
      if(changed){
        p.target=target;p.path=[];p.entry=null;p.arrived=false;p.dwellUntil=null;p.retryAt=0;p.blockedSince=null;p.yielding=false;p.yieldUntil=0;
      }
      if(reducedMotion&&(changed||!wasReduced||!p.arrived))snap(p,target,stop);
      const others=[...people.filter(q=>q!==p),...obstacles];
      const walking=!reducedMotion&&(!celebrating||!p.arrived)&&advance(p,stop,floor,others,delta,soft?1.82:2.15,time);
      const arrived=ready(p);
      if(arrived){
        turn(p,stop.yaw,reducedMotion?1:1-Math.exp(-delta*7));
        if(p.dwellUntil===null)p.dwellUntil=time+4.5+(p.turn%4)*1.8;
      }
      const seatBlend=p.seat?.progress??0;
      Object.assign(r,{x:p.x,z:p.z,angle:p.angle,walking,step:p.phase,seatBlend,
        pose:walking?'walk':arrived?(celebrating?'celebrate':pose):'idle',
        seated:seatBlend===1,
        caption:arrived?(celebrating?'任务完成':caption):travel,
        partner:partner??null, celebration:arrived&&celebrating&&!reducedMotion?Math.sin(Math.PI*(p.celebrateUntil-time)/1.5):0,
        speech:null,lookYaw:0});
    }
    if(chat){
      const [a,b]=chat.people;
      const together=a.target==='chatA'&&b.target==='chatB'&&ready(a)&&ready(b);
      if(together){
        if(chat.started===null)chat.started=time;
        const age=time-chat.started;
        a.row.partner=b.id;b.row.partner=a.id;
        for(const [speaker,listener] of [[a,b],[b,a]]){
          const offset=yawTo(speaker,listener)-speaker.angle;
          speaker.row.lookYaw=Math.atan2(Math.sin(offset),Math.cos(offset));
        }
        const speaker=age<4.3?0:age>=5.0&&age<9.4?1:-1;
        if(speaker>=0)chat.people[speaker].row.speech=chat.lines[speaker];
      }
    }
    wasReduced=reducedMotion;
    return rows;
  }
  return {setState,tick};
}
