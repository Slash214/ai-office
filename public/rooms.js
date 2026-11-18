// Furnished wings of the cutaway. All anchor positions are in world space.
export function buildRooms({parent, animated, box, cyl, group, rod, mesh, globe, textureSurface, luminous, floorPad}) {
  const anchors = {
    coffee: {x:8.23,z:-4.63,yaw:Math.PI,seated:false,via:[]},
    arcade: {x:9.20,z:-.65,yaw:2.90,seated:false},
    chatA: {x:8.17,z:2.49,yaw:.16,seated:true,frontEntry:true},
    chatB: {x:10.03,z:5.10,yaw:-1.94,seated:true,frontEntry:true},
    focus: {x:-9.02,z:-2.38,yaw:-Math.PI/2,seated:false,via:[]},
    print: {x:-8.79,z:1.94,yaw:-Math.PI/2,seated:false,via:[]},
    rest: {x:-9.85,z:4.83,yaw:Math.PI/2,seated:true,frontEntry:true},
  };
  const ink='#23314d', metal='#657591', pale='#c3d2d8', oak='#b98967';
  const mint=luminous('#86f8d4'), amber=luminous('#ffcf83'), violet=luminous('#bd9bff');
  const wing=group(parent);

  function plant(g,x,z,s) {
    cyl(g,x,.22*s,z,.32*s,.23*s,.44*s,'#a8b5b5',7);
    cyl(g,x,.452*s,z,.28*s,.28*s,.035*s,'#454a52',7);
    for (const [dx,dy,dz,tilt,color] of [[-.18,.76,-.03,.68,'#629c80'],[.17,.83,-.06,-.46,'#6bbc9d'],[.02,.98,0,-.07,'#96d9ad'],[.08,.68,.15,-.54,'#70b08b']]) {
      const leaf=mesh(g,globe,color,x+dx*s,dy*s,z+dz*s,.17*s,.43*s,.14*s);
      leaf.rotation.z=tilt;
    }
  }
  function mug(g,x,y,z,color) {
    cyl(g,x,y+.10,z,.129,.099,.20,color,8);
    cyl(g,x,y+.204,z,.101,.101,.008,'#563735',8);
    box(g,x+.137,y+.114,z,.075,.083,.052,color);
  }
  function couch(g,x,z,yaw,width,fabric,back) {
    const seat=group(g,x,0,z,yaw);
    box(seat,0,.26,0,width-.14,.26,.90,ink);
    box(seat,0,.51,0,width,.30,.91,fabric);
    box(seat,0,.89,-.41,width,.69,.23,back);
    for(const dx of [-1,1]) box(seat,dx*(width/2-.09),.68,.015,.18,.43,.95,back);
    box(seat,0,1.16,-.31,width-.25,.035,.045,fabric);
  }

  // A warm counter, espresso group and backlit menu occupy the far corner.
  const cafe=group(wing,8.84,0,-5.97);
  floorPad(cafe,0,.37,3.66,2.05,'#695054',.042);
  box(cafe,0,.16,0,3.25,.23,.89,ink);
  box(cafe,0,.67,0,3.38,.90,.91,'#986a52');
  for(const dx of [-1.04,0,1.04]) {
    box(cafe,dx,.67,.474,.96,.74,.047,'#c28a65');
    box(cafe,dx,.88,.501,.39,.044,.025,'#795d51');
  }
  box(cafe,0,1.16,.015,3.52,.13,1.04,'#ddbf98');
  box(cafe,0,1.07,.48,3.40,.033,.028,amber);
  box(cafe,0,2.20,-.44,3.39,2.10,.17,'#563f49');
  box(cafe,-.01,3.10,-.33,3.55,.17,.31,'#b77d5e');
  textureSurface(cafe,0,2.73,-.337,2.98,.57,(c,w,h)=>{
    c.fillStyle='#413040';c.fillRect(0,0,w,h);
    c.strokeStyle='#ffd996';c.lineWidth=12;
    c.strokeRect(32,98,71,61);c.beginPath();c.arc(106,119,17,-Math.PI/2,Math.PI/2);c.stroke();
    c.fillStyle='#fff0b5';c.font='bold 82px sans-serif';c.fillText('COFFEE BAR',151,157,w-176);
    c.fillStyle='#d49f74';c.fillRect(28,215,542,6);
  });
  // Espresso machine has a boiler enclosure, brass group head, drip tray and cup.
  const espresso=group(cafe,-.61,1.23,-.025);
  box(espresso,0,.13,.04,1.22,.23,.59,'#38575b');
  box(espresso,0,.46,-.21,1.17,.60,.24,'#537b77');
  for(const dx of [-.51,.51]) box(espresso,dx,.43,.008,.16,.67,.50,'#548a82');
  box(espresso,0,.77,.035,1.24,.26,.62,'#82b7a2');
  box(espresso,0,.79,.354,.88,.10,.026,'#324b52');
  box(espresso,.24,.8,.373,.20,.037,.019,mint);
  cyl(espresso,-.12,.59,.218,.113,.085,.14,'#d3b080',8);
  box(espresso,.02,.603,.24,.28,.048,.054,'#433c45');
  box(espresso,-.09,.268,.22,.66,.034,.29,'#a2a9a2');
  mug(espresso,-.13,.283,.22,'#f8dcaa');
  cyl(cafe,.61,1.57,-.14,.19,.20,.65,'#73554f',8);
  cyl(cafe,.61,1.92,-.14,.215,.215,.065,'#b0b4aa',8);
  mug(cafe,1.14,1.229,.14,'#f2c4a0');
  plant(cafe,1.51,1.09,.79);
  const steamRoot=group(animated,8.10,1.93,-5.78);
  const steam=Array.from({length:2},(_,i)=>mesh(steamRoot,globe,'#d9d8be',0,.18+i*.18,0,.048,.105,.046));
  steam.forEach(p=>{p.castShadow=false;});

  // Research board has a legible diagram and movable sticky notes; the shelves
  // behind it hold physical samples so the lab also reads in the overview.
  const board=group(wing,-10.36,0,-2.38,Math.PI/2);
  floorPad(board,0,.70,3.95,2.08,'#365a63',.043);
  for(const dx of [-1.40,1.40]) {
    box(board,dx,.60,0,.11,1.10,.13,metal);
    box(board,dx,.13,0,.20,.105,.71,ink);
  }
  box(board,0,1.87,0,3.52,1.92,.18,'#5c8690');
  textureSurface(board,0,1.87,.096,3.37,1.75,(c,w,h)=>{
    c.fillStyle='#c2d7c8';c.fillRect(0,0,w,h);
    c.fillStyle='#466b6c';c.font='bold 22px sans-serif';c.fillText('RESEARCH BOARD',23,35);
    c.fillStyle='#648c83';c.fillRect(22,46,w-44,3);
    c.strokeStyle='#557e79';c.lineWidth=4;c.beginPath();
    c.moveTo(128,113);c.lineTo(194,113);c.lineTo(220,172);c.lineTo(290,172);c.lineTo(324,107);c.lineTo(396,107);c.stroke();
    [[57,76,76,68,'#f1bf74'],[209,141,78,63,'#e69f9f'],[343,71,70,67,'#a18db8']].forEach(([x,y,ww,hh,color])=>{
      c.fillStyle='#829e92';c.fillRect(x+4,y+4,ww,hh);c.fillStyle=color;c.fillRect(x,y,ww,hh);
      c.fillStyle='#506366';c.fillRect(x+10,y+15,ww*.62,4);c.fillRect(x+10,y+26,ww*.42,4);
    });
    c.strokeStyle='#75988e';c.lineWidth=2;c.strokeRect(453,79,104,137);
    for(let i=0;i<4;i++){c.fillStyle=['#557877','#609d8b','#79af91','#e5ad6d'][i];c.fillRect(468+i*22,184-i*18,11,21+i*18);}
    c.fillStyle='#5d857f';c.fillRect(37,246,373,3);c.fillRect(37,257,237,3);
  });
  box(board,0,.88,.13,3.53,.08,.32,'#91aaa4');
  box(board,.78,.952,.18,.39,.045,.064,'#7ed9bb');
  box(board,1.19,.952,.18,.23,.055,.10,ink);
  const samples=group(wing,-9.51,0,-5.79);
  box(samples,0,.54,0,2.20,.97,.90,'#455674');
  box(samples,0,1.06,0,2.32,.13,.99,pale);
  for(const [i,h,color] of [[0,.52,'#8abfa7'],[1,.73,'#a394c2'],[2,.42,'#dfa66d']]) {
    const x=(i-1)*.62;
    cyl(samples,x,1.18,0,.26,.28,.12,'#465674',8);
    const specimen=mesh(samples,globe,color,x,1.25+h*.43,0,.24,h*.66,.23);
    specimen.rotation.z=.29-i*.21;
  }

  // The copier has a document feeder, a tilted control screen and a paper tray.
  const copier=group(wing,-10.05,0,1.94,Math.PI/2);
  floorPad(copier,0,.20,2.37,1.75,'#405674',.042);
  box(copier,0,.22,0,1.25,.34,.93,'#36475c');
  box(copier,0,.68,0,1.49,.76,1.04,'#a2b9c5');
  for(const y of [.47,.72]) {
    box(copier,0,y,.529,1.32,.20,.042,'#819dac');
    box(copier,-.05,y+.045,.556,.43,.034,.020,ink);
  }
  box(copier,-.05,1.13,-.07,1.30,.30,.89,'#384d65');
  box(copier,-.10,1.09,.407,.87,.032,.29,'#e5e4d7');
  box(copier,0,1.37,0,1.58,.19,1.06,'#c2d3d6');
  box(copier,-.19,1.53,-.05,.96,.22,.72,'#7d98a8');
  const screen=box(copier,.52,1.49,.35,.35,.22,.08,mint);
  screen.rotation.x=-.40;
  const bench=group(wing,-9.91,0,4.83,Math.PI/2);
  floorPad(bench,0,.20,2.33,1.41,'#596571',.043);
  couch(bench,0,0,0,1.73,'#9e91ad','#746d91');
  plant(wing,-10.41,3.39,.88);

  // Couched seating faces across a low tea table. The west end is open to the
  // circulation spine, including both approaches to the chairs.
  const lounge=group(wing,9.02,0,3.55);
  floorPad(lounge,0,0,3.60,3.62,'#335064',.044);
  floorPad(lounge,0,0,3.41,3.43,'#4c6b78',.061);
  const rug=textureSurface(lounge,0,.081,0,3.40,3.42,(c,w,h)=>{
    c.fillStyle='#596278';c.fillRect(0,0,w,h);
    c.lineWidth=6;c.strokeStyle='#93a2a6';c.strokeRect(13,10,w-26,h-20);
    c.lineWidth=3;c.strokeStyle='#ac93a6';c.strokeRect(26,19,w-52,h-38);
    for(let i=-1;i<4;i++){
      c.strokeStyle=i%2?'#667b87':'#657082';c.lineWidth=10;c.beginPath();
      c.moveTo(w*.04,h*(.40+i*.24));c.lineTo(w*.47,h*(.06+i*.24));
      c.lineTo(w*.97,h*(.43+i*.24));c.stroke();
    }
  });
  rug.object.rotation.x=-Math.PI/2;
  couch(wing,8.89,2.38,.16,2.48,'#6db6ae','#438a8c');
  couch(wing,10.03,5.10,-1.94,1.22,'#9ba7c9','#797ca5');
  const cushion=box(wing,9.58,.89,2.20,.42,.38,.15,'#dbb083');
  cushion.rotation.set(-.19,.16,.19);
  const teaTable=group(lounge,.28,0,-.14);
  cyl(teaTable,0,.24,0,.21,.32,.43,'#496276',8);
  cyl(teaTable,0,.51,0,.42,.38,.12,'#cdac89',8);
  box(teaTable,-.08,.592,.05,.32,.038,.22,'#6f82a3').rotation.y=.31;
  mug(teaTable,.19,.574,-.04,'#d8e3d3');
  plant(wing,10.45,1.83,1.21);

  const arcade=group(wing,9.53,0,-2.24,-.26);
  floorPad(arcade,0,.20,1.85,2.02,'#574b76',.043);
  box(arcade,0,.12,0,1.34,.16,1.00,ink);
  box(arcade,0,.62,-.05,1.19,.98,.90,'#524575');
  box(arcade,0,.58,.416,.91,.66,.045,'#303b59');
  box(arcade,.24,.76,.446,.22,.17,.019,'#765b88');
  box(arcade,.24,.79,.459,.095,.027,.017,amber);
  for(const x of [-.65,.65]) {
    box(arcade,x,1.33,-.04,.15,2.32,1.00,'#806aab');
    box(arcade,x,1.99,-.055,.14,.94,.86,'#b097cc');
    box(arcade,x,1.96,.40,.065,.86,.042,violet);
  }
  box(arcade,0,1.22,.28,1.31,.16,.79,'#aa8cbb');
  box(arcade,0,1.25,.684,1.29,.058,.031,violet);
  cyl(arcade,-.33,1.40,.45,.040,.040,.21,ink,6);
  mesh(arcade,globe,'#ed99ae',-.33,1.53,.45,.115,.112,.111);
  for (const [x,z,color] of [[.15,.44,amber],[.36,.38,mint]]) cyl(arcade,x,1.326,z,.068,.081,.040,color,8);
  box(arcade,0,1.83,-.107,1.19,.90,.54,'#28304c');
  const gameDisplay=textureSurface(arcade,0,1.82,.171,1.04,.71,(c,w,h)=>drawCourt(c,w,h,false));
  const sidePanel=group(arcade,.734,1.39,-.055,Math.PI/2);
  textureSurface(sidePanel,0,0,0,.81,1.55,(c,w,h)=>{
    c.fillStyle='#51416d';c.fillRect(0,0,w,h);c.fillStyle='#81609b';
    c.beginPath();c.moveTo(0,h*.69);c.lineTo(w,h*.31);c.lineTo(w,h*.55);c.lineTo(0,h*.92);c.fill();
    c.fillStyle='#f2b578';c.beginPath();c.ellipse(w*.50,h*.43,w*.185,h*.112,0,0,Math.PI*2);c.fill();
    c.strokeStyle='#ffdac0';c.lineWidth=8;c.beginPath();c.ellipse(w*.50,h*.43,w*.30,h*.052,-.17,0,Math.PI*2);c.stroke();
    c.fillStyle='#beabd3';for(const [x,y] of [[.16,.12],[.80,.19],[.87,.69],[.24,.79]])c.fillRect(x*w,y*h,8,4);
  });
  box(arcade,0,2.43,-.07,1.48,.35,1.00,'#8773aa');
  textureSurface(arcade,0,2.43,.437,1.32,.255,(c,w,h)=>{
    c.fillStyle='#614671';c.fillRect(0,0,w,h);c.fillStyle='#ffdb9a';c.font='italic bold 146px sans-serif';
    c.textAlign='center';c.textBaseline='middle';c.fillText('ORBIT',w/2,h*.53);
  });
  // Low pinball machine next to the taller arcade cabinet.
  const pinball=group(wing,7.75,0,-2.43,-.10);
  for(const x of [-.43,.43]) for(const z of [-.53,.53]) box(pinball,x,.40,z,.095,.77,.095,metal);
  box(pinball,0,.90,0,1.10,.33,1.59,'#466478');
  const field=box(pinball,0,1.12,0,.95,.06,1.49,'#427978');
  field.rotation.x=.10;
  box(pinball,0,1.43,-.65,1.14,.66,.22,'#7f9ba3');
  box(pinball,0,1.46,-.525,.90,.40,.035,'#315563');
  for(const [x,z,color] of [[-.20,-.35,amber],[.17,-.17,mint],[-.16,.12,violet]]) {
    cyl(pinball,x,1.18-z*.10,z,.112,.13,.07,color,8);
  }
  for(const side of [-1,1]) box(pinball,.17*side,1.13,.43,.27,.057,.082,'#f7c485').rotation.y=.36*side;

  // Agents play a small paddle game. The raster scoreboard belongs to the
  // cabinet's single texture, and the same drawing is used by both renderers.
  let ball={x:.5,y:.52,vx:.44,vy:.30}, left=.50, right=.51, score=[0,0];
  let active=false,lastSim=null,lastPaint=-1,steamFrame=-1;
  function drawCourt(c,w,h,playing) {
    c.fillStyle='#16223b';c.fillRect(0,0,w,h);
    c.fillStyle='#26334a';for(let i=1;i<9;i++)c.fillRect(i*w/9,0,2,h);
    c.fillStyle='#3f526a';for(let i=0;i<9;i++)c.fillRect(w*.5,15+i*h/9,4,h/17);
    if(!playing) {
      c.fillStyle='#96e6d4';c.font='bold 62px monospace';c.textAlign='center';c.fillText('ORBIT PONG',w*.5,h*.48);
      c.fillStyle='#d8b0ef';c.font='bold 31px monospace';c.fillText('PRESS START',w*.5,h*.68);
      return;
    }
    c.fillStyle='#aaf7dc';c.fillRect(w*.10,(left-.10)*h,w*.035,h*.20);
    c.fillStyle='#edbcff';c.fillRect(w*.865,(right-.10)*h,w*.035,h*.20);
    c.fillStyle='#ffda8c';c.fillRect(ball.x*w-5,ball.y*h-5,11,11);
    c.font='bold 47px monospace';c.fillStyle='#d9dfed';c.textAlign='center';
    c.fillText(String(score[0]),w*.40,h*.17);c.fillText(String(score[1]),w*.60,h*.17);
  }
  function play(dt,t) {
    const steer=(value,target,speed)=>Math.max(.11,Math.min(.89,value+Math.max(-dt*speed,Math.min(dt*speed,target-value))));
    left=steer(left,ball.y+.075*Math.sin(t*2.3),.61);
    right=steer(right,ball.y+.12*Math.cos(t*1.9),.49);
    const oldX=ball.x;
    ball.x+=ball.vx*dt;ball.y+=ball.vy*dt;
    if(ball.y<.035 || ball.y>.965){ball.y=Math.max(.035,Math.min(.965,ball.y));ball.vy*=-1;}
    const leftHit=ball.vx<0 && oldX>=.14 && ball.x<.14 && Math.abs(ball.y-left)<.115;
    const rightHit=ball.vx>0 && oldX<=.86 && ball.x>.86 && Math.abs(ball.y-right)<.115;
    if(leftHit||rightHit){
      ball.x=leftHit?.141:.859;
      ball.vx=(leftHit?1:-1)*Math.min(.80,Math.abs(ball.vx)+.033);
      ball.vy=(ball.y-(leftHit?left:right))*3.5+.17*Math.sin(t*1.7);
    }
    if(ball.x<0 || ball.x>1) {
      const winner=ball.x<0?1:0;
      score[winner]++;ball={x:.5,y:.5,vx:winner?.44:-.44,vy:.32*Math.cos(t)};
    }
  }
  function update(sim,animatedFx,arcadeInUse=false) {
    const dt=lastSim===null?0:Math.max(0,Math.min(.10,sim-lastSim));
    lastSim=sim;
    if(arcadeInUse && animatedFx)play(dt,sim);
    const frame=arcadeInUse && animatedFx?Math.floor(sim*8):0;
    if(active!==arcadeInUse || frame!==lastPaint) {
      gameDisplay.refresh((c,w,h)=>drawCourt(c,w,h,arcadeInUse));
      lastPaint=frame;active=arcadeInUse;
    }
    const frameSteam=animatedFx?Math.floor(sim*6):-1;
    if(frameSteam!==steamFrame) {
      steamFrame=frameSteam;
      steam.forEach((p,i)=>{
        const u=animatedFx?(sim*.58+i*.49)%1:(.21+i*.36);
        p.position.set(.04*Math.sin(u*5+i),.09+u*.40,0);
        p.scale.set(.028+.023*Math.sin(u*Math.PI),.062+.035*Math.sin(u*Math.PI),.037);
      });
    }
  }
  return {anchors,update};
}
