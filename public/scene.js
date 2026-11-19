import * as THREE from './vendor/three.module.js';
import {buildRooms} from './rooms.js';
import {createOfficeLife} from './life.js';
import {drawMonitor,drawTaskBoard,workLabel,editStages} from './monitor.js';
import {crewDesign} from './crew-design.js';

const ROSTER = [
  {id:'carbon', name:'Carbon', color:'#ffc46b', x:-4.9, z:2.6},
  {id:'astra', name:'Astra', color:'#47dafa', x:-4.9, z:-1.3},
  {id:'dot', name:'Dot', color:'#c78bff', x:-0.35, z:2.6},
  {id:'argon', name:'Argon', color:'#ff87ac', x:-0.35, z:-1.3},
  {id:'hydrogen', name:'Hydrogen', color:'#52e5a9', x:4.2, z:2.6},
  {id:'codex', name:'Codex', color:'#96baff', x:-1.6, z:-5.2},
];
const PALETTE = {
  alloy:'#425471', surface:'#7089a8', edge:'#23334f', sage:'#546c92', cream:'#b7ccdf',
  wall:'#363e6c', green:'#33869d', dark:'#18243d', paper:'#d3e2f3', coral:'#a78ace', steel:'#384b68',
};
const TAU = Math.PI * 2;
const Y_AXIS = new THREE.Vector3(0,1,0);
const clamp = THREE.MathUtils.clamp;

export function mountOffice(container, {wallpaper = false} = {}) {
  const styles=getComputedStyle(container);
  const crew=ROSTER.map(person=>{
    const tint=styles.getPropertyValue('--role-'+person.id).trim();
    return {...person,color:/^#[0-9a-f]{6}$/i.test(tint)?tint:person.color};
  });
  let effects='full',adaptiveSoft=false,windowFrame=-1,rateStart=0,renderedFrames=0;
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  function animatedEffects(){return effects==='full'&&!reduced.matches&&!adaptiveSoft;}
  const canvas = document.createElement('canvas');
  canvas.setAttribute('aria-hidden','true');
  Object.assign(canvas.style,{display:'block',width:'100%',height:'100%',position:'absolute',inset:'0'});
  if (getComputedStyle(container).position === 'static') container.style.position = 'relative';
  container.style.overflow = 'hidden';
  container.append(canvas);
  let renderer = null;
  try {
    renderer = new THREE.WebGLRenderer({canvas,alpha:true,antialias:true,powerPreference:'low-power'});
  } catch { /* The CPU projection below uses the same scene graph. */ }
  if (renderer) {
    renderer.setClearColor(0x000000,0);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.autoUpdate = !wallpaper;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
  }
  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(-10,10,7,-7,0.1,120);
  const architecture = new THREE.Group();
  scene.add(architecture);
  const materials = new Map(), geometries = new Map(), textures = [];
  // Color is the only difference between members of each palette.
  const standardPalette=new THREE.MeshStandardMaterial({flatShading:true,roughness:.75,metalness:.20});
  const luminousPalette=new THREE.MeshBasicMaterial();
  const sculptPalette=new THREE.MeshStandardMaterial({roughness:.68,metalness:.035});
  const palettes=new WeakMap();
  const cube = new THREE.BoxGeometry(1,1,1);
  const plane = new THREE.PlaneGeometry(1,1);
  const globe = new THREE.IcosahedronGeometry(1,0);
  const dynamic = new THREE.Group();
  scene.add(dynamic);
  // Keep selectable rig meshes separate from their WebGL instances.
  const poseRig=renderer?new THREE.Group():dynamic;
  const poseInstances=renderer?new THREE.Group():null;
  if(poseInstances)scene.add(poseInstances);

  function paletteMaterial(key,color,template){
    if(!materials.has(key)){
      const tinted=template.clone();
      tinted.color.set(color);
      palettes.set(tinted,template);
      materials.set(key,tinted);
    }
    return materials.get(key);
  }
  function material(color) {
    return paletteMaterial(color,color,standardPalette);
  }
  function soft(color) {
    return paletteMaterial('sculpt:'+color,color,sculptPalette);
  }
  function mesh(parent,geo,mat,x,y,z,sx,sy,sz) {
    const obj = new THREE.Mesh(geo,typeof mat === 'string' ? material(mat) : mat);
    obj.position.set(x,y,z); obj.scale.set(sx,sy,sz);
    obj.castShadow = true; obj.receiveShadow = true;
    parent.add(obj);
    return obj;
  }
  function box(parent,x,y,z,w,h,d,mat) { return mesh(parent,cube,mat,x,y,z,w,h,d); }
  function cyl(parent,x,y,z,rt,rb,h,mat,n=12) {
    const key = [rt,rb,h,n].join('/');
    if(!geometries.has(key)) geometries.set(key,new THREE.CylinderGeometry(rt,rb,h,n));
    return mesh(parent,geometries.get(key),mat,x,y,z,1,1,1);
  }
  function group(parent,x=0,y=0,z=0,angle=0) {
    const g=new THREE.Group(); g.position.set(x,y,z); g.rotation.y=angle; parent.add(g); return g;
  }
  function rod(parent,a,b,r,color,n=6) {
    const start=new THREE.Vector3(...a), end=new THREE.Vector3(...b);
    const delta=end.clone().sub(start);
    const m=cyl(parent,...start.clone().add(end).multiplyScalar(.5).toArray(),r,r,delta.length(),color,n);
    m.quaternion.setFromUnitVectors(Y_AXIS,delta.normalize()); return m;
  }
  function textureSurface(parent,x,y,z,w,h,draw,options={}) {
    const logicalWidth=600,logicalHeight=300;
    const scale=options.scale??(wallpaper?.60:.80),art=document.createElement('canvas');
    art.width=Math.round(logicalWidth*scale);art.height=Math.round(logicalHeight*scale);
    const ctx=art.getContext('2d');
    ctx.scale(art.width/logicalWidth,art.height/logicalHeight);
    draw(ctx,logicalWidth,logicalHeight);
    const tex=new THREE.CanvasTexture(art);tex.colorSpace=THREE.SRGBColorSpace;
    if(options.mipmaps===false){tex.generateMipmaps=false;tex.minFilter=THREE.LinearFilter;}
    const mat=new THREE.MeshBasicMaterial({map:tex,transparent:!!options.transparent,depthWrite:!options.transparent});
    textures.push(tex,mat);
    const obj=mesh(parent,plane,mat,x,y,z,w,h,1); obj.castShadow=false;
    obj.userData.image=art;
    return {object:obj,refresh(fn){fn(ctx,logicalWidth,logicalHeight);tex.needsUpdate=true;}};
  }
  function floorPad(parent,x,z,w,d,color,y=.022) {
    return box(parent,x,y,z,w,.024,d,color);
  }

  function mixHex(a,b,ratio){
    return '#'+new THREE.Color(a).lerp(new THREE.Color(b),ratio).getHexString();
  }
  function litFloor(parent,x,z,w,d,y,draw,transparent=false){
    const layer=textureSurface(parent,x,y,z,w,d,draw,{transparent,scale:transparent?.45:wallpaper?.45:.60});
    layer.object.rotation.x=-Math.PI/2;
    return layer;
  }
  const hemi=new THREE.HemisphereLight('#d5e6ff','#627597',1.75);
  const sun=new THREE.DirectionalLight('#ccddff',2.05);
  sun.position.set(-5,16,11);sun.castShadow=true;
  Object.assign(sun.shadow.camera,{left:-15,right:15,top:15,bottom:-15,near:1,far:48});
  const shadowResolution=wallpaper?512:2048;
  sun.shadow.mapSize.set(shadowResolution,shadowResolution);
  sun.shadow.normalBias=.035;sun.shadow.bias=-.00022;
  const fill=new THREE.DirectionalLight('#bea5fb',.88);fill.position.set(12,7,-5);
  const cyanBounce=new THREE.PointLight('#32e4e0',13,11,2);
  cyanBounce.position.set(-4.5,2.65,.01);
  const roseBounce=new THREE.PointLight('#ff74ba',17,11,2);
  roseBounce.position.set(4.5,3.1,-1.8);
  scene.add(hemi,sun,fill,cyanBounce,roseBounce);
  function luminous(color) {
    return paletteMaterial('light:'+color,color,luminousPalette);
  }
  const ice=luminous('#77fff1'),iris=luminous('#dd95ff'),rose=luminous('#ff86ac'),dimIce=luminous('#68bfd1');
  function glowBar(parent,x,y,z,w,h,d,core,edge){
    box(parent,x,y,z,w,h,d,edge);
    box(parent,x,y+h*.22,z+d*.14,w*.985,h*.44,d*.85,core);
  }
  // A continuous 22 × 14 floor joins two wings to the five central desks.
  const base=group(architecture);base.userData.layer=-8;
  box(base,0,-.53,0,22.0,.16,14.15,'#182641');
  box(base,0,-.37,0,22.24,.23,14.34,'#405378');
  for(const [x,line] of [[-8.24,ice],[-2.75,iris],[2.75,luminous('#87b6ff')],[8.24,rose]]){
    box(base,x,-.26,7.185,5.08,.042,.051,line);
  }
  box(base,0,-.23,0,22.15,.057,14.27,'#638eae');
  box(base,0,-.11,0,22.05,.18,14.18,'#0e152b');
  for(const x of [-9,-6,-3,0,3,6,9])box(base,x,-.35,7.18,.67,.043,.026,dimIce);
  for(const z of [-5.6,-2.8,0,2.8,5.6])box(base,11.13,-.35,z,.026,.043,.54,dimIce);
  const deck=group(architecture);deck.userData.layer=-7;
  const plates=['#40516e','#425470','#3d4e69','#394965'];
  for(let row=0;row<10;row++)for(let col=0;col<12;col++){
    const x=-11+(col+.5)*22/12,z=-7+(row+.5)*1.4;
    box(deck,x,-.014,z,1.808,.051,1.374,plates[(row+col*3)%4]);
    if((row+col)%5===0){
      box(deck,x+.64,.015,z+.47,.18,.012,.04,'#8d9db4');
      box(deck,x+.64,.015,z+.54,.18,.012,.022,'#8d9db4');
    }
  }
  // Aisle edges leave the walking lane unobstructed and identify the routes between wings.
  for(const x of [-7.84,-6.91,6.03,6.90])floorPad(deck,x,0,.036,13.26,'#8392aa');
  for(const z of [.26,1.12,4.19,4.88])floorPad(deck,-.45,z,13.65,.028,'#758ba3');
  for(const x of [-6,-3.2,-.4,2.4,5.2])floorPad(deck,x,.70,.20,.055,'#a7b2c5');
  // Colored bounce is painted into the deck at the same positions as its desk fittings.
  // A single transparent texture keeps these pools cheap in WebGL and Canvas.
  const bounce=litFloor(deck,0,0,14.99,10.04,.032,(ctx,w,h)=>{
    for(const f of crew){
      const x=(f.x/14.99+.5)*w,y=(f.z/10.04+.5)*h;
      ctx.save();ctx.translate(x,y);ctx.scale(w*.207,h*.201);
      const glow=ctx.createRadialGradient(0,0,0,0,0,1);
      glow.addColorStop(0,f.color+'bb');glow.addColorStop(.53,f.color+'66');glow.addColorStop(1,f.color+'00');
      ctx.fillStyle=glow;ctx.fillRect(-1,-1,2,2);ctx.restore();
    }
  },true);
  bounce.object.renderOrder=1;
  const wall=group(architecture);wall.userData.layer=-6;
  box(wall,0,2,-7.04,22.1,4.12,.28,'#534877');
  box(wall,-10.99,2,0,.26,4.12,14.27,'#305c72');
  box(wall,0,4.09,-7.03,22.18,.16,.33,'#826dab');
  box(wall,-10.99,4.09,0,.33,.16,14.35,'#5da9b3');
  box(wall,0,.27,-6.85,21.97,.49,.15,'#283553');
  box(wall,-10.80,.27,0,.15,.49,14.06,'#293f59');
  const fixtures=group(architecture);fixtures.userData.layer=-5;
  const wallWash=textureSurface(fixtures,0,2.13,-6.892,21.90,3.95,(ctx,w,h)=>{
    const ink=ctx.createLinearGradient(0,h,w,0);
    ink.addColorStop(0,'#20416f');ink.addColorStop(.30,'#3e3d77');ink.addColorStop(.62,'#5a3979');ink.addColorStop(1,'#2c3558');
    ctx.fillStyle=ink;ctx.fillRect(0,0,w,h);
    const bloom=ctx.createRadialGradient(w*.76,h*.12,3,w*.76,h*.12,w*.52);
    bloom.addColorStop(0,'#d775d066');bloom.addColorStop(1,'#9149ab00');ctx.fillStyle=bloom;ctx.fillRect(0,0,w,h);
    for(let i=0;i<12;i++){ctx.fillStyle='#c4a1ed18';ctx.fillRect(i*w/12,0,1,h);}
  });
  wallWash.object.userData.layer=-5.5;
  box(fixtures,0,.51,-6.748,21.83,.034,.035,dimIce);
  box(fixtures,-10.71,.51,0,.035,.034,14.04,dimIce);
  // Three inset observation windows look onto a moonlit skyline.
  const windowWall=group(fixtures,-10.80,.27,-.55,Math.PI/2);windowWall.scale.x=1.48;
  box(windowWall,0,2.35,0,8.02,2.75,.19,'#1b314c');
  const windowArt=group(windowWall,0,2.35,.10);
  function drawWindow(ctx,w,h,night=false,phase=0,soft=false) {
    const sky=ctx.createLinearGradient(0,0,0,h);
    sky.addColorStop(0,night?'#172854':'#213565');
    sky.addColorStop(.42,night?'#3e377d':'#5e4089');sky.addColorStop(.78,night?'#98698c':'#bd659d');sky.addColorStop(1,'#ea9f9c');
    ctx.fillStyle=sky;ctx.fillRect(0,0,w,h);
    ctx.fillStyle='#d3e9fc';ctx.beginPath();ctx.arc(w*.21,h*.29,h*.095,0,TAU);ctx.fill();
    for(let i=0;i<34;i++)ctx.fillRect((i*67+17)%w,(i*23+7)%(h*.50),1.5+i%2,1.5+i%2);
    // Overlapping polar ribbons: a soft luminous body and a crisp lower edge.
    ctx.save();ctx.globalCompositeOperation='screen';
    const colors=['#33edc0','#5acff2','#a67aff','#ee73bc'];
    for(let k=0;k<4;k++){
      const path=new Path2D(),base=h*(.32+k*.077);
      for(let x=0;x<=w+5;x+=5){
        const u=x/w;
        const v=base+h*.10*Math.sin(u*5.8+k*.55+phase)+h*.045*Math.sin(u*11.4+k+.5*phase)-h*.26*u;
        if(x===0)path.moveTo(x,v);else path.lineTo(x,v);
      }
      const ribbon=new Path2D(path);ribbon.lineTo(w,-h*.2);ribbon.lineTo(0,-h*.2);ribbon.closePath();
      const gleam=ctx.createLinearGradient(0,base-h*.37,0,base+h*.03);
      gleam.addColorStop(0,colors[k]+'00');gleam.addColorStop(.74,colors[k]+(soft?'25':'50'));gleam.addColorStop(1,colors[k]+(soft?'66':'aa'));
      ctx.fillStyle=gleam;ctx.fill(ribbon);ctx.strokeStyle=colors[k]+(soft?'55':'9c');ctx.lineWidth=1.9;ctx.stroke(path);
    }
    const veil=ctx.createLinearGradient(0,0,w,0);
    veil.addColorStop(0,'#32efce');veil.addColorStop(.38,'#6ee6fb');veil.addColorStop(.66,'#ae82ff');veil.addColorStop(1,'#ff70bd');
    ctx.strokeStyle=veil;ctx.lineCap='round';
    const ridge=new Path2D();ridge.moveTo(-20,h*.62);
    ridge.bezierCurveTo(w*.20,h*(.13+phase*.08),w*.39,h*.54,w*.57,h*(.33+phase*.07));
    ridge.bezierCurveTo(w*.78,h*.06,w*.91,h*.30,w+18,h*.07);
    for(const [thick,opacity] of [[.17,.16],[.085,.24],[.028,.72]]){
      ctx.lineWidth=h*thick;ctx.globalAlpha=soft?opacity*.80:opacity;ctx.stroke(ridge);
    }
    ctx.restore();
    function skyline(count,base,height,hue,seed) {
      for(let i=0;i<count;i++){
        const bw=w/count,x=i*bw,top=h*(base-height*((i*23+seed)%17)/17);
        ctx.fillStyle=hue;ctx.fillRect(x,top,bw*.9,h-top);
        if(i%6===0)ctx.fillRect(x+bw*.4,top-12,bw*.10,14);
        ctx.fillStyle=i%4===0?'#a4a5d4':'#81bfcf';
        for(let wy=top+6;wy<h-4;wy+=10)for(let wx=x+3;wx<x+bw*.8;wx+=7)
          if((Math.floor(wy)+Math.floor(wx))%3!==0)ctx.fillRect(wx,wy,2.6,2.0);
      }
    }
    skyline(24,.83,.29,'#524e82',7);skyline(18,.91,.28,'#37496f',3);skyline(11,.96,.23,'#243555',5);
  }
  const windowTexture=textureSurface(windowArt,0,0,.02,7.72,2.45,drawWindow,{mipmaps:false});
  for(const x of [-3.84,-1.35,1.35,3.84]){
    box(windowWall,x,2.34,.18,.083,2.59,.16,'#415572');
    box(windowWall,x-.041,2.34,.248,.024,2.58,.04,dimIce);
  }
  glowBar(windowWall,-2.65,3.72,.16,2.67,.12,.25,ice,'#41767e');
  glowBar(windowWall,0,3.72,.16,2.62,.12,.25,luminous('#98b7ff'),'#596b9d');
  glowBar(windowWall,2.65,3.72,.16,2.67,.12,.25,iris,'#7f5d95');
  box(windowWall,0,.97,.23,8.22,.17,.59,PALETTE.alloy);
  for(const z of [-6.72,5.6]){
    box(wall,-10.81,2.0,z,.27,3.95,.31,'#536786');
    box(wall,-10.64,2.65,z,.036,1.33,.086,iris);
  }
  // One telemetry surface on the planning side and an articulated market display in the meeting bay.
  const planningWall=group(fixtures,-2.53,2.72,-6.81);
  box(planningWall,0,0,0,3.26,1.80,.17,PALETTE.dark);
  let summary=null,summaryKey='',boardHint='等待读取';
  const teamDisplay=textureSurface(planningWall,0,0,.091,3.07,1.62,
    (c,w,h)=>drawTaskBoard(c,w,h,null,false,boardHint));
  for(let i=0;i<22;i++){
    const tint=i<6?'#6465a3':i<14?'#8d649d':'#ab739b';
    box(fixtures,.52+i*.29,2.05,-6.81,.105,3.80,.11,i%4===0?tint:'#58476b');
  }
  glowBar(fixtures,2.02,3.98,-6.73,3.12,.073,.085,iris,'#8c61a9');
  glowBar(fixtures,5.28,3.98,-6.73,3.12,.073,.085,rose,'#996579');
  const screen=group(fixtures,3.58,2.70,-6.58);
  box(screen,0,0,0,4.00,1.87,.18,PALETTE.dark);
  box(screen,0,0,-.086,4.15,2.0,.07,'#68769d');
  function drawMarket(c,w,h,price,time) {
    c.fillStyle='#101c37';c.fillRect(0,0,w,h);
    c.fillStyle='#73dce7';c.fillRect(0,0,9,h);c.fillStyle='#a6cbdc';c.font='bold 32px monospace';c.fillText('BTC / USD',32,57);
    c.fillStyle='#f1f3ff';c.font='bold 71px monospace';
    c.fillText(Number.isFinite(price)?'$'+Math.round(price).toLocaleString('en-US'):'— —',32,163);
    c.fillStyle='#8f9fc6';c.font='24px monospace';c.fillText(time||'MARKET MONITOR',33,252);
    c.fillStyle=Number.isFinite(price)?'#82dfcc':'#b29bdf';c.beginPath();c.arc(w-49,45,9,0,TAU);c.fill();
  }
  const tv=textureSurface(screen,0,0,.101,3.86,1.72,(...args)=>drawMarket(...args,null,''));
  // Two banks of independently ventilated server blades with small link lights.
  const rack=group(architecture,-5.73,0,-6.5);
  box(rack,0,1.52,.02,2.38,3.00,.63,'#3c4a6c');
  for(const x of [-.55,.55]){
    box(rack,x,1.51,.375,1.02,2.76,.088,'#1a2743');
    for(let i=0;i<8;i++){
      const y=.39+i*.318;box(rack,x,y,.435,.87,.233,.085,'#374762');
      box(rack,x-.29,y,.483,.11,.048,.017,i%3===0?iris:ice);
      for(let j=0;j<3;j++)box(rack,x+.10+j*.085,y,.482,.034,.12,.024,'#1d2946');
    }
  }
  for(const part of rack.children)part.userData.layer=-4.65+part.position.z*.85;
  const cabinet=group(architecture,3.46,0,-6.26);
  box(cabinet,0,.40,0,3.85,.69,.78,'#3a496d');
  box(cabinet,0,.80,0,3.95,.09,.87,'#7183a0');
  for(const x of [-1.24,0,1.24]){
    box(cabinet,x,.44,.399,1.16,.47,.049,'#4e6382');
    box(cabinet,x,.53,.43,.36,.041,.04,'#7791a7');
  }

  function plant(parent,x,y,z,s,seed=0) {
    const p=group(parent,x,y,z);p.scale.setScalar(s);
    cyl(p,0,.26,0,.35,.26,.51,'#526485',10);
    cyl(p,0,.505,0,.37,.35,.12,'#7586a3',10);
    cyl(p,0,.57,0,.30,.30,.025,'#273650',10);
    const greens=['#468496','#6595a6','#3f7285','#839aa5','#51778b'];
    for(let i=0;i<8;i++) {
      const a=i*2.40+seed, r=.30+(i%3)*.075, h=1.13+((i*5)%4)*.22;
      const end=[Math.cos(a)*r,h,Math.sin(a)*r];
      rod(p,[0,.51,0],end,.027,'#4b6779');
      const leaf=mesh(p,globe,greens[i%5],...end,.17,.40,.115);
      leaf.rotation.z=-Math.cos(a)*.74;leaf.rotation.x=Math.sin(a)*.74;leaf.rotation.y=-a;
    }
  }
  plant(architecture,-6.72,0,-6.38,.84);plant(architecture,6.10,0,-6.49,1.06,2);
  plant(architecture,5.42,0,6.12,1.08,1.3);plant(cabinet,1.28,1.01,0,.43);
  
  function chair(parent,x,z,angle,color) {
    const c=group(parent,x,0,z,angle);
    for(const dx of [-.33,.33]) for(const dz of [-.30,.30]) box(c,dx,.34,dz,.085,.68,.085,PALETTE.alloy);
    box(c,0,.70,0,.90,.16,.85,color);
    box(c,0,1.03,-.40,.85,.60,.13,color);
    return c;
  }
  // An accessible low reception counter and reading bench occupy the sunken front apron.
  const reception=group(architecture,-3.15,0,6.04);
  floorPad(reception,0,.03,4.46,1.64,'#363d58');
  box(reception,0,.38,0,3.53,.69,.72,'#3e4d6e');
  box(reception,0,.79,0,3.75,.13,.93,'#8591aa');
  box(reception,0,.61,.371,3.49,.043,.026,dimIce);
  const visitorScreen=group(reception,-.74,1.14,-.04,.09);
  box(visitorScreen,0,0,0,.88,.52,.089,PALETTE.dark);
  textureSurface(visitorScreen,0,0,.049,.79,.43,(c,w,h)=>{
    c.fillStyle='#18273f';c.fillRect(0,0,w,h);c.fillStyle='#c8f1fa';
    c.font='bold 103px "Microsoft YaHei",sans-serif';c.textAlign='center';c.fillText('接待',w/2,h*.66);
  });
  box(reception,.63,.9,.04,.60,.038,.38,'#c7cfe0');
  box(reception,.72,.938,.06,.45,.031,.30,'#83a3b9');
  plant(reception,1.43,.87,-.02,.44,.7);
  const bench=group(architecture,1.79,0,6.15);
  for(const x of [-1.02,1.02])box(bench,x,.26,0,.26,.50,.58,'#384964');
  box(bench,0,.56,0,2.65,.17,.79,'#55647f');
  for(const x of [-.85,0,.85])box(bench,x,.69,0,.80,.12,.70,'#7785a2');
  const meeting=group(architecture,4.18,0,-2.03);
  floorPad(meeting,0,0,4.78,3.66,'#293957');
  floorPad(meeting,0,0,4.55,3.44,'#485278',.038);
  for(const x of [-.85,.85]) {
    chair(meeting,x,-1.44,0,'#80769f');
    chair(meeting,x,1.44,Math.PI,'#8b7ea8');
  }
  chair(meeting,2.15,0,-Math.PI/2,'#80769f');
  chair(meeting,-2.15,0,Math.PI/2,'#80769f');
  const pillar=cyl(meeting,0,.50,0,.42,.62,.99,'#394b69',8);pillar.rotation.y=Math.PI/8;
  const tabletop=group(meeting);
  tabletop.scale.set(1.82,1,1.01);
  cyl(tabletop,0,1.07,0,1,1,.19,'#7785a6',8).rotation.y=Math.PI/8;
  const tableInset=group(meeting);
  tableInset.scale.set(1.50,1,.79);
  cyl(tableInset,0,1.178,0,1,1,.032,'#45536f',8).rotation.y=Math.PI/8;
  // A small model of orbital paths sits within the central planning console.
  cyl(meeting,.20,1.214,0,.36,.39,.055,'#19283e',16);
  function orbitArc(parent,radius,tilt,angle,mat) {
    const g=group(parent,.2,1.70,0,angle);g.rotation.z=tilt;
    let last=[radius,0,0];
    for(let i=1;i<=20;i++){const a=i*TAU/20,next=[Math.cos(a)*radius,0,Math.sin(a)*radius];
      rod(g,last,next,.014,mat,4);last=next;}
  }
  orbitArc(meeting,.40,.62,.2,dimIce);orbitArc(meeting,.45,-.85,.3,iris);
  mesh(meeting,globe,'#738ac0',.20,1.70,0,.18,.18,.18);
  const stationScreens=new Map();
  let codexEdit=null,editSignature='';
  function computer(d,person) {
    box(d,-.36,1.26,-.02,.54,.065,.40,PALETTE.steel);
    box(d,-.36,1.49,-.12,.10,.50,.10,PALETTE.steel);
    const monitor=group(d,-.36,1.84,-.15);
    box(monitor,0,0,-.04,1.45,.91,.16,mixHex(person.color,'#394365',.61));
    box(monitor,0,0,.016,1.35,.84,.14,PALETTE.dark);
    box(monitor,-.682,0,.061,.040,.76,.034,luminous(person.color));
    box(monitor,.682,-.19,.061,.040,.36,.034,luminous(person.color));
    const display=textureSurface(monitor,0,0,.092,1.20,.70,
      (...args)=>drawMonitor(...args,{id:person.id,color:person.color,status:'idle',activity:'',phase:0}),
      {scale:wallpaper?.50:512/600});
    const rgb=new THREE.Color(person.color);
    const lampMat=new THREE.MeshBasicMaterial({color:rgb});textures.push(lampMat);
    const right=person.x+1.32,back=person.z-.45;
    box(d,1.32,1.65,-.45,.099,.85,.11,PALETTE.dark);
    const lamp=box(dynamic,right,1.64,back+.055,.07,.58,.047,lampMat);lamp.castShadow=false;
    stationScreens.set(person.id,{display,status:'idle',activity:'',phase:-1,lamp,lampMat,rgb,
      gaze:new THREE.Vector3(person.x+monitor.position.x,monitor.position.y,person.z+monitor.position.z+.092),
      keyboard:new THREE.Vector3(person.x-.35,1.318,person.z+.38)});
    box(d,-.35,1.233,.38,.90,.055,.30,'#9ba8c1');
    for(let i=0;i<3;i++)box(d,-.35,1.267,.29+i*.08,.76,.014,.027,'#56647f');
    box(d,.28,1.25,.37,.15,.08,.22,PALETTE.sage);
  }
  function workstation(person) {
    const desk=group(architecture,person.x,0,person.z);
    const accent=person.color;
    const base=mixHex(accent,'#1a2948',.82),inner=mixHex(accent,'#24334c',.91);
    floorPad(desk,0,.02,3.60,2.50,base).userData.layer=-2;
    const inset=litFloor(desk,0,.02,3.55,2.44,.048,(c,w,h)=>{
      const metal=c.createLinearGradient(0,0,w,h);metal.addColorStop(0,base);metal.addColorStop(.70,inner);metal.addColorStop(1,base);
      c.fillStyle=metal;c.fillRect(0,0,w,h);
      const pool=c.createRadialGradient(w*.46,h*.50,0,w*.46,h*.50,w*.65);
      pool.addColorStop(0,accent+'95');pool.addColorStop(.46,accent+'48');pool.addColorStop(1,accent+'00');
      c.fillStyle=pool;c.fillRect(0,0,w,h);
      // Machined bevels and illuminated cut corners retain color at mobile scale.
      c.beginPath();c.moveTo(3,42);c.lineTo(44,5);c.lineTo(w-50,5);c.lineTo(w-4,44);
      c.lineTo(w-4,h-43);c.lineTo(w-46,h-5);c.lineTo(46,h-5);c.lineTo(4,h-45);c.closePath();
      c.strokeStyle=accent+'aa';c.lineWidth=6;c.stroke();
      c.fillStyle=accent;c.fillRect(w*.13,h-10,w*.24,7);c.fillRect(w*.84,8,w*.07,6);
    });
    inset.object.userData.layer=-1;
    for(const x of [-1.33,1.33]){
      box(desk,x,.62,-.35,.24,1.13,.48,base);
      box(desk,x,.62,-.09,.21,.58,.032,mixHex(accent,'#354260',.37));
    }
    for (const x of [-1.25,1.25]) for (const z of [-.45,.45])
      box(desk,x,.57,z,.14,1.12,.14,PALETTE.steel);
    box(desk,0,.99,-.47,2.65,.21,.13,PALETTE.sage);
    box(desk,0,1.09,0,3.03,.15,1.32,PALETTE.edge);
    const top=mixHex(person.color,'#72809d',.79);
    box(desk,0,1.175,0,2.98,.087,1.27,top);
    box(desk,-.22,1.096,.667,2.39,.054,.022,luminous(person.color));
    box(desk,1.24,1.101,.669,.29,.043,.018,person.color);
    box(desk,-1.02,.55,0,.63,.92,.75,'#52667e');
    for(const y of [.47,.77]) box(desk,-1.02,y,.38,.32,.035,.04,PALETTE.steel);
    computer(desk,person);
    cyl(desk,-1.12,1.33,.05,.13,.105,.23,person.color,10);
    cyl(desk,-1.12,1.451,.05,.093,.093,.011,'#2c3343',10);
    const seat=chair(desk,-.35,1.30,Math.PI,mixHex(person.color,'#505875',.44));
    box(seat,0,1.27,-.479,.82,.083,.048,luminous(person.color));
  }
  crew.forEach(workstation);

  const shell=new THREE.SphereGeometry(1,12,8);
  const smallShell=new THREE.SphereGeometry(1,8,5);
  const limb=new THREE.CylinderGeometry(.5,.5,1,8);
  const eyeSurface=luminous('#f6fbff');
  const spectacleFrame=new THREE.RingGeometry(.80,1,16);
  function buildGlyph(){
    const star=new THREE.Shape();
    star.moveTo(0,1);
    star.quadraticCurveTo(.18,.18,1,0);
    star.quadraticCurveTo(.18,-.18,0,-1);
    star.quadraticCurveTo(-.18,-.18,-1,0);
    star.quadraticCurveTo(-.18,.18,0,1);
    const starGeometry=new THREE.ShapeGeometry(star,6);

    const knotGeometry=new THREE.BufferGeometry(),vertices=[];
    const path=new THREE.SplineCurve([
      [-.19,.14],[-.19,.40],[-.19,.59],[-.14,.76],[0,.87],
      [.17,.90],[.33,.85],[.47,.72],[.51,.57],[.43,.44],
    ].map(([x,y])=>new THREE.Vector2(x,y)));
    const points=path.getPoints(42);
    const ribbonHalfWidth=.078;
    for(let spoke=0;spoke<6;spoke++){
      const rotation=spoke*Math.PI/3,cos=Math.cos(rotation),sin=Math.sin(rotation);
      const edge=(i,side)=>{
        const p=points[i],a=points[Math.max(0,i-1)],b=points[Math.min(points.length-1,i+1)];
        const dx=b.x-a.x,dy=b.y-a.y,length=Math.hypot(dx,dy);
        const x=p.x-side*dy*ribbonHalfWidth/length,y=p.y+side*dx*ribbonHalfWidth/length;
        return [x*cos-y*sin,x*sin+y*cos,0];
      };
      for(let i=0;i<points.length-1;i++){
        // One gap per ribbon lets the neighboring ribbon cross visibly above it.
        const section=(i+.5)/(points.length-1);
        if(section>.203&&section<.302)continue;
        vertices.push(...edge(i,1),...edge(i,-1),...edge(i+1,1),
          ...edge(i,-1),...edge(i+1,-1),...edge(i+1,1));
      }
    }
    knotGeometry.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));
    knotGeometry.computeVertexNormals();
    return {star:starGeometry,knot:knotGeometry};
  }
  const glyph=buildGlyph();
  const roleStyles={
    carbon:{panel:'#473047',gear:'#ad6249',detail:'#ffe7a4',symbol:'star'},
    astra:{panel:'#153849',gear:'#307889',detail:'#d3fff3',symbol:'knot'},
    dot:{panel:'#332354',gear:'#6852a2',detail:'#dcff94',symbol:'dot'},
    codex:{panel:'#22284e',gear:'#485a94',detail:'#dceaff',symbol:'terminal'},
    argon:{panel:'#4a2546',gear:'#944b78',detail:'#fff0be',symbol:'star'},
    hydrogen:{panel:'#1c3945',gear:'#337d74',detail:'#caffde',symbol:'star'},
  };
  const sculptShell=new THREE.SphereGeometry(1,20,12);
  const humanDefaults={
    carbon:{hairStyle:'quiff',jacketStyle:'varsity',headgear:'clip',skin:'#ebb489',blush:'#de8a75',
      hair:'#624032',hairHighlight:'#b27955',iris:'#a35e34',jacket:'#c37342',sleeves:'#ebe4db',trim:'#ffbd68',
      shirt:'#372c47',pants:'#353447',shoes:'#754031',hardware:'#382c3a'},
    astra:{hairStyle:'waves',jacketStyle:'hoodie',headgear:'headphones',skin:'#e6af91',blush:'#d68877',
      hair:'#242c39',hairHighlight:'#467b73',iris:'#367a64',jacket:'#22615b',sleeves:'#ccd8da',trim:'#81ead6',
      shirt:'#242e3d',pants:'#252f44',shoes:'#c4ddd6',hardware:'#22394a'},
    dot:{hairStyle:'crop',jacketStyle:'street',headgear:'cap',skin:'#eac0ab',blush:'#df899d',
      hair:'#605179',hairHighlight:'#9d83c9',iris:'#765da6',jacket:'#6c54a2',sleeves:'#aa94d8',trim:'#d9eb89',
      shirt:'#362944',pants:'#3b3256',shoes:'#a787cb',hardware:'#4c3a77'},
    argon:{hairStyle:'bob',jacketStyle:'analyst',headgear:'glasses',skin:'#efb9a7',blush:'#df8790',
      hair:'#66394e',hairHighlight:'#ac637e',iris:'#a45f86',jacket:'#884264',sleeves:'#edc6d4',trim:'#f4cb9c',
      shirt:'#43273f',pants:'#442e4d',shoes:'#8e4a6e',hardware:'#533250'},
    hydrogen:{hairStyle:'ponytail',jacketStyle:'utility',headgear:'microphone',skin:'#be8667',blush:'#c4796c',
      hair:'#29493f',hairHighlight:'#559c85',iris:'#557d54',jacket:'#427e6b',sleeves:'#b4dad1',trim:'#a0edc5',
      shirt:'#253941',pants:'#294750',shoes:'#559381',hardware:'#284951'},
    codex:{hairStyle:'spikes',jacketStyle:'developer',headgear:'visor',skin:'#e5b5a2',blush:'#ce8694',
      hair:'#242944',hairHighlight:'#5364a2',iris:'#557dc3',jacket:'#3c5088',sleeves:'#b8c7e4',trim:'#91c5ff',
      shirt:'#292f4c',pants:'#2b3455',shoes:'#b5d0f0',hardware:'#2e416e'},
  };
  const directorDesign={
    hairStyle:'sidepart',jacketStyle:'executive',headgear:'none',
    skin:'#e3a788',blush:'#c48177',hair:'#252939',hairHighlight:'#424858',iris:'#514445',
    jacket:'#263750',sleeves:'#30425b',trim:'#bbab92',shirt:'#21293a',
    pants:'#242e44',shoes:'#243149',hardware:'#394961',
  };
  const humanExpressions={
    president:{eye:.145,brow:.075,height:.108,lips:.046,smile:.145,tilt:.08},
    carbon:{eye:.173,brow:.035,height:.125,lips:.071,smile:.163},
    astra:{eye:.147,brow:.105,height:.109,lips:.038,smile:.129},
    dot:{eye:.182,brow:-.028,height:.123,lips:.060,smile:.143,asymmetry:.033,tilt:.16},
    argon:{eye:.176,brow:.052,height:.124,lips:.056,smile:.139},
    hydrogen:{eye:.189,brow:.055,height:.119,lips:.079,smile:.164},
    codex:{eye:.158,brow:.104,height:.111,lips:.041,smile:.138,tilt:.08},
  };
  const jacketCuts={
    varsity:{width:.70,sleeve:.216,hood:false,front:'snaps'},
    hoodie:{width:.73,sleeve:.219,hood:true,front:'drawstrings'},
    street:{width:.76,sleeve:.224,hood:true,front:'pouch'},
    analyst:{width:.681,sleeve:.196,hood:false,front:'lapels'},
    utility:{width:.716,sleeve:.208,hood:false,front:'pockets'},
    developer:{width:.708,sleeve:.207,hood:true,front:'straps'},
    executive:{width:.73,sleeve:.205,hood:false,front:'pin'},
  };
  function makeHairLock(curl) {
    const rings=8,sides=8,vertices=[],indices=[];
    for(let i=0;i<=rings;i++){
      const t=i/rings,angle=Math.atan2(2*curl*t,1);
      const width=.49*Math.pow(1-t,.73)+.008;
      const depth=.45*Math.pow(1-t,.65)+.007;
      for(let j=0;j<sides;j++){
        const theta=j/sides*TAU,edge=Math.cos(theta)*width;
        vertices.push(curl*t*t+Math.cos(angle)*edge,-t+Math.sin(angle)*edge,
          Math.sin(theta)*depth+.27*Math.sin(t*Math.PI));
      }
    }
    for(let i=0;i<rings;i++)for(let j=0;j<sides;j++){
      const a=i*sides+j,b=i*sides+(j+1)%sides,c=a+sides,d=b+sides;
      indices.push(a,b,c,b,d,c);
    }
    const root=vertices.length/3,tip=root+1;
    vertices.push(0,0,0,curl,-1,0);
    for(let i=0;i<sides;i++){
      const next=(i+1)%sides,lastRing=rings*sides;
      indices.push(root,next,i,tip,lastRing+i,lastRing+next);
    }
    const geometry=new THREE.BufferGeometry();
    geometry.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));
    geometry.setIndex(indices);geometry.computeVertexNormals();
    return geometry;
  }
  const hairLockRight=makeHairLock(.55),hairLockLeft=makeHairLock(-.55);
  function character(person) {
    const root=group(poseRig),body=group(root),head=group(body,0,1.65,.015);
    const accent=person.color,ink='#20283f',joint='#354259';
    const manager=person.id==='president';
    const defaults=manager?directorDesign:humanDefaults[person.id];
    const design=defaults?{...defaults,...crewDesign[person.id]}:null;
    const jacketCut=design?jacketCuts[design.jacketStyle]??jacketCuts[defaults.jacketStyle]:null;
    const skin=design?.skin;
    const coat=design?.jacket??mixHex(accent,'#4c5773',.45);
    const shade=design?.pants??mixHex(accent,ink,.78);
    const style=roleStyles[person.id]??{w:.95,h:.735,shell:mixHex(accent,'#d3deeb',.53),panel:'#273249',
      gear:mixHex(accent,ink,.55),detail:'#e7f4ff',blush:accent,symbol:'dot'};
    const {w,h,shell:helmet,panel,gear,detail,blush,symbol}=style;
    const light=luminous(design?mixHex(detail,design.trim,.27):detail);
    const pillow=(p,x,y,z,sx,sy,sz,c,geo=smallShell)=>mesh(p,geo,c,x,y,z,sx/2,sy/2,sz/2);
    const pillBar=(p,x,y,z,sx,sy,sz,c)=>pillow(p,x,y,z,sx,sy,sz,soft(c));
    function horizontalDisk(p,x,y,z,r,depth,c) {
      const disk=cyl(p,x,y,z,r,r,depth,c,16);
      disk.rotation.x=Math.PI/2;
      return disk;
    }
    function badge(p,x,y,z,r,yaw=0,pitch=0,markType=symbol) {
      const mount=group(p,x,y,z,yaw);
      mount.rotation.order='YXZ';mount.rotation.x=pitch;
      const knot=markType==='knot',markLight=knot?luminous('#f1fff8'):light;
      horizontalDisk(mount,0,0,0,r,.028,knot?luminous('#59dcb5'):panel);
      horizontalDisk(mount,0,0,.018,r*(knot?.884:.81),.012,knot?'#193e38':gear);
      if(markType==='dot') {
        horizontalDisk(mount,0,0,.032,r*.44,.013,light);
        pillow(mount,-r*.14,r*.12,.043,r*.19,r*.19,.013,eyeSurface);
      }else if(markType==='terminal'){
        const a=box(mount,-r*.20,r*.15,.032,r*.48,r*.12,.014,light);
        const b=box(mount,-r*.20,-r*.12,.032,r*.48,r*.12,.014,light);
        a.rotation.z=-.64;b.rotation.z=.64;
        box(mount,r*.34,-r*.20,.033,r*.40,r*.12,.014,light);
      }else{
        const mark=mesh(mount,glyph[markType],markLight,0,0,.032,r*.82,r*.82,1);
        mark.castShadow=false;mark.receiveShadow=false;
      }
    }
    function cuff(p,x,y,z,r,depth,c){
      const disc=cyl(p,x,y,z,r,r,depth,c,12);
      disc.rotation.z=Math.PI/2;
      return disc;
    }

    pillow(body,0,.675,0,.61,.32,.43,design?soft(shade):ink);
    const coatShell=pillow(body,0,1.000,.013,jacketCut?.width??.69,.575,.49,design?soft(coat):coat,shell);
    const shadowCasters=new Set([coatShell]);
    pillow(body,0,1.075,-.14,.49,.38,.27,design?soft(coat):shade);
    if(design){
      const {jacket,shirt,trim,hardware}=design;
      const garment=(x,y,z,w,h,d,color)=>pillow(body,x,y,z,w,h,d,soft(color),shell);
      garment(0,1.055,.208,.303,.413,.105,shirt);
      garment(0,.764,.019,.649,.106,.496,hardware);
      for(const side of [-1,1]){
        garment(side*.233,1.050,.168,.270,.415,.186,jacket);
        const seam=box(body,side*.075,1.032,.269,.024,.289,.021,soft(manager?hardware:trim));seam.rotation.z=side*.13;
        pillBar(body,side*.247,.923,.254,.160,.040,.051,hardware);
        pillBar(body,side*.252,.941,.273,.107,.014,.018,trim);
      }
      if(jacketCut.hood){
        garment(0,1.242,-.135,.576,.272,.393,design.sleeves);
        garment(0,1.251,-.227,.35,.129,.226,hardware);
      }else{
        for(const side of [-1,1]){
          const collar=garment(side*.109,1.214,.144,.150,.139,.175,manager?coat:trim);
          collar.rotation.z=side*.38;
        }
      }
      if(jacketCut.front==='snaps'){
        for(const y of [.885,.985,1.085])pillow(body,-.028,y,.277,.035,.035,.017,soft(trim));
      }else if(jacketCut.front==='drawstrings'){
        for(const side of [-1,1])pillBar(body,side*.105,1.088,.289,.018,.167,.022,design.sleeves).rotation.z=side*.13;
      }else if(jacketCut.front==='pouch'){
        garment(0,.951,.244,.300,.139,.089,hardware);
        pillBar(body,0,.954,.287,.193,.018,.044,trim);
      }else if(jacketCut.front==='lapels'){
        for(const side of [-1,1])pillBar(body,side*.144,1.145,.278,.112,.173,.047,trim).rotation.z=side*.54;
      }else if(jacketCut.front==='pin'){
        for(const side of [-1,1]){
          const lapel=box(body,side*.151,1.149,.274,.096,.171,.034,soft(hardware));
          lapel.rotation.z=side*.52;
        }
        const pin=box(body,-.170,1.143,.298,.045,.055,.019,soft(trim));
        pin.rotation.z=-.55;
        pillBar(body,.201,1.057,.273,.093,.025,.028,'#c7d8e3');
        pillBar(body,0,.924,.281,.026,.031,.019,trim);
      }else if(jacketCut.front==='pockets'){
        garment(.196,1.100,.251,.166,.141,.085,hardware);
        pillBar(body,.198,1.129,.293,.125,.022,.041,trim);
      }else{
        for(const side of [-1,1])pillBar(body,side*.221,1.149,.272,.057,.154,.035,hardware).rotation.z=side*.24;
      }
      if(!manager){
        badge(body,-.164,1.142,.295,.085,-.12,-.13);
        if(symbol==='knot'){
          badge(body,0,1.058,-.312,.173,Math.PI,-.38);
        }else{
          badge(body,0,1.115,-.277,.135,Math.PI,-.38);
        }
        if(symbol==='terminal'||symbol==='dot')badge(body,.219,1.197,-.196,.063,Math.PI-.22,-.35,'knot');
      }
    }else{
      pillow(body,0,1.025,.212,.55,.32,.15,gear);
      pillow(body,0,1.030,.268,.43,.23,.058,shade);
      badge(body,0,1.036,.302,.094);
      pillow(body,0,1.045,-.255,.36,.29,.14,gear);
      box(body,0,1.046,-.323,.155,.039,.017,light);
    }
    cyl(body,0,1.294,.014,.133,.157,.146,design?soft(skin):joint,8);

    const arms=[],legs=[];
    for(const side of [-1,1]){
      const sleeve=design?soft(design.sleeves):coat,wristWidth=jacketCut?.sleeve??.187;
      const shoulder=pillow(body,side*.344,1.224,0,.248,.242,.244,sleeve);
      const upper=mesh(body,limb,sleeve,0,0,0,jacketCut?.sleeve??.194,1,.204);
      const elbow=pillow(body,0,0,0,.183,.178,.183,design?sleeve:joint);
      const lower=mesh(body,limb,design?sleeve:gear,0,0,0,wristWidth,1,wristWidth);
      const hand=group(body),handSkin=design?soft(skin):helmet;
      const glove=pillow(hand,0,0,.034,.172,.118,.220,handSkin);
      pillow(hand,side*-.062,-.007,.087,.067,.075,.099,design?handSkin:accent);
      if(design){
        pillBar(hand,0,.002,-.049,.197,.148,.102,design.hardware);
        pillBar(hand,0,.066,-.038,.144,.030,.049,design.trim);
      }else{
        pillow(hand,0,.057,.070,.104,.035,.083,gear);
      }
      arms.push({shoulder,upper,elbow,lower,hand});

      const trousers=design?soft(design.pants):shade;
      const thigh=mesh(body,limb,trousers,0,0,0,.229,1,.225);
      const knee=pillow(body,0,0,0,.221,.201,.211,design?trousers:joint);
      const shin=mesh(body,limb,design?trousers:gear,0,0,0,.201,1,.214);
      const shoe=group(body);
      pillow(shoe,0,-.079,.081,.284,.115,.386,design?soft(manager?design.hardware:design.trim):accent);
      const footwear=pillow(shoe,0,-.026,.083,.277,.205,.373,design?soft(design.shoes):ink,shell);
      pillow(shoe,0,.017,.154,.191,.085,.175,design?soft(design.hardware):gear);
      if(design){
        for(const z of [.097,.137])pillBar(shoe,0,.081,z,.123,.022,.022,manager?design.shoes:design.trim);
      }
      legs.push({thigh,knee,shin,shoe});
      for(const caster of [upper,lower,glove,thigh,shin,footwear])shadowCasters.add(caster);
    }

    const eyes=[];
    let mouth;
    function eye(x,y,z,r,h,tilt=0){
      const lens=group(head,x,y,z);
      lens.rotation.y=tilt;
      pillow(lens,0,0,0,r,h,.035,eyeSurface);
      const pupil=mixHex(panel,'#10182e',.24);
      pillow(lens,r*.075,-h*.012,.020,r*.73,h*.83,.039,pupil);
      pillow(lens,-r*.10,h*.23,.039,r*.25,h*.23,.012,eyeSurface);
      pillow(lens,r*.22,-h*.17,.039,r*.11,h*.105,.012,eyeSurface);
      lens.userData.neutralHeight=1;eyes.push(lens);
      return lens;
    }
    function smile(y,z,color,width=.112){
      const lips=pillow(head,0,y,z,width,.059,.029,color);
      lips.userData.neutralHeight=lips.scale.y;
      pillow(head,0,y+.017,z+.009,width*.67,.015,.015,light);
      return lips;
    }

    function buildHumanFace() {
      const {skin,hair,hairHighlight,blush,iris,hardware,trim,hairStyle,headgear}=design;
      const shadows=mixHex(skin,blush,.32),lips=mixHex(skin,'#8c455a',.66);
      const brow=mixHex(hair,'#251c32',.30),darkEye='#211d37';
      const facePose=humanExpressions[person.id];
      function sculpt(p,x,y,z,a,b,c,color,geo=shell){
        return pillow(p,x,y,z,a,b,c,soft(color),geo);
      }
      function lock(x,y,z,width,length,depth,angle,turn=0,highlight=false,left=false) {
        const strand=mesh(head,left?hairLockLeft:hairLockRight,soft(highlight?hairHighlight:hair),
          x,y,z,width,length,depth);
        strand.rotation.order='YXZ';strand.rotation.set(0,turn,angle);
        return strand;
      }
      function detailLine(p,a,b,thickness,color) {
        const dx=b[0]-a[0],dy=b[1]-a[1],dz=b[2]-a[2];
        const line=box(p,(a[0]+b[0])/2,(a[1]+b[1])/2,(a[2]+b[2])/2,
          thickness,Math.hypot(dx,dy,dz),thickness,color);
        line.quaternion.setFromUnitVectors(Y_AXIS,new THREE.Vector3(dx,dy,dz).normalize());
        return line;
      }
      const face=sculpt(head,0,-.027,.046,.868,.767,.713,skin,sculptShell);
      shadowCasters.add(face);
      sculpt(head,0,-.082,.178,.727,.551,.505,skin,sculptShell);
      const capHeight=hairStyle==='crop'?.496:.607;
      shadowCasters.add(sculpt(head,0,.105,-.078,.929,capHeight,.732,hair,sculptShell));
      for(const side of [-1,1]){
        sculpt(head,side*.399,-.069,-.005,.159,.19,.148,skin);
        sculpt(head,side*.424,-.071,.055,.073,.096,.055,shadows,smallShell);
        const cheek=sculpt(head,side*.254,-.128,.357,.131,.054,.040,blush,smallShell);
        cheek.rotation.y=side*.30;
        const eye=group(head,side*.171,.002,.374,side*.24);
        eye.rotation.z=side*(hairStyle==='bob'?.135:.057);
        eye.userData.neutralHeight=1;eyes.push(eye);
        const eyeHeight=facePose.eye-(side>0?(facePose.asymmetry??0):0);
        pillow(eye,0,0,0,.235,eyeHeight+.015,.046,soft(darkEye),shell);
        pillow(eye,0,-.012,.019,.211,eyeHeight-.020,.039,eyeSurface,shell);
        pillow(eye,-side*.016,-.008,.041,.135,eyeHeight*.89,.049,soft(iris),shell);
        pillow(eye,-side*.016,-.006,.064,.082,eyeHeight*.65,.022,soft(darkEye));
        pillow(eye,-side*.038,.031,.076,.040,.042,.012,eyeSurface);
        pillow(eye,side*.008,-.041,.076,.018,.019,.009,eyeSurface);
        const eyebrowHeight=facePose.height+(side>0?(facePose.asymmetry??0)*.56:0);
        const browShape=sculpt(head,side*.166,eyebrowHeight,.375,.186,.038,.040,brow,smallShell);
        browShape.rotation.y=side*.28;browShape.rotation.z=side*facePose.brow;
        if(hairStyle==='bob'||hairStyle==='ponytail'){
          detailLine(eye,[side*.098,.040,.025],[side*.131,.058,.011],.014,soft(darkEye));
        }
      }
      sculpt(head,0,-.074,.411,.092,.087,.105,shadows);
      sculpt(head,0,-.060,.447,.045,.033,.032,skin,smallShell);
      const expression=group(head,0,-.161,.408);
      expression.rotation.z=facePose.tilt??0;
      const {lips:smileHeight,smile:smileWidth}=facePose;
      pillow(expression,0,0,0,smileWidth,smileHeight,.036,soft(lips),shell);
      if(smileHeight>.055){
        pillow(expression,0,smileHeight*.25,.014,smileWidth*.67,.016,.017,soft('#f9ddd2'));
        pillow(expression,0,-smileHeight*.29,.013,smileWidth*.48,.017,.014,soft(mixHex(blush,'#fbabb7',.28)));
      }
      for(const side of [-1,1]){
        const corner=sculpt(expression,side*smileWidth*.40,smileHeight*.14,.008,.034,.019,.020,lips,smallShell);
        corner.rotation.z=side*.43;
      }
      expression.userData.neutralHeight=1;

      if(hairStyle==='quiff'){
        // The longer front sweep and lifted forelock distinguish Carbon from every other profile.
        lock(-.28,.291,.167,.268,.463,.312,1.57,.03);
        lock(-.188,.363,.153,.264,.418,.310,1.77,-.06,true);
        lock(.10,.366,.192,.244,.319,.264,2.38,.15,true,true);
        lock(-.292,.202,.172,.176,.271,.205,-.54,.35,false,true);
        lock(.238,.267,.122,.174,.316,.255,.17,.42);
        lock(-.335,.216,-.030,.151,.285,.217,-.26,-.80,false,true);
        lock(-.311,.273,-.121,.161,.265,.226,-.58,-1.45,true,true);
        lock(-.143,.263,-.208,.204,.335,.250,-.50,2.92,true,true);
        lock(.122,.304,-.192,.253,.394,.233,.63,3.15);
      }else if(hairStyle==='waves'){
        lock(-.122,.363,.166,.284,.348,.340,-1.12,-.09,false,true);
        lock(-.026,.390,.137,.256,.377,.317,1.22,.05);
        lock(.130,.364,.178,.232,.312,.265,.54,.24,true,true);
        lock(.226,.293,.206,.201,.287,.215,.09,.39);
        lock(-.231,.294,.180,.174,.293,.203,-.69,-.52,true,true);
        lock(-.329,.238,-.032,.162,.282,.211,-.39,-1.12,false,true);
        lock(.331,.265,-.103,.171,.281,.215,.34,1.15,true);
        lock(-.127,.347,-.198,.275,.357,.280,-.65,2.82,false,true);
        lock(.139,.343,-.174,.292,.368,.226,.65,3.20,true);
      }else if(hairStyle==='crop'){
        lock(-.211,.265,.224,.180,.215,.188,-.44,.06,false,true);
        lock(-.022,.274,.230,.200,.235,.184,.67,.12,true);
        lock(.212,.237,.222,.181,.246,.191,.22,.28,false,true);
        lock(-.224,.160,-.242,.192,.204,.171,-.34,3.10,true,true);
        lock(.10,.198,-.266,.232,.213,.148,.25,3.00);
      }else if(hairStyle==='bob'){
        sculpt(head,0,-.022,-.188,.819,.630,.492,hair,sculptShell);
        lock(-.086,.340,.181,.291,.337,.284,-.98,-.16,false,true);
        lock(.101,.334,.175,.253,.305,.305,.69,.09,true);
        lock(-.312,.214,.095,.220,.477,.300,-.15,-.42,false,true);
        lock(.306,.221,.065,.248,.494,.320,.10,.50);
        lock(-.255,.127,-.244,.220,.398,.198,.22,3.02,true);
        lock(.224,.129,-.235,.229,.404,.204,-.26,3.10,false,true);
      }else if(hairStyle==='sidepart'){
        lock(-.226,.310,.113,.295,.458,.286,1.61,.10);
        lock(-.155,.369,.122,.251,.391,.276,1.74,.04,true);
        lock(.072,.343,.191,.222,.326,.253,1.27,.04);
        lock(-.230,.292,.191,.213,.287,.235,-.61,-.21,false,true);
        lock(.271,.258,.073,.173,.312,.190,.28,.61);
        lock(-.330,.209,-.036,.152,.241,.180,-.24,-1.09,false,true);
        lock(-.147,.302,-.201,.289,.323,.218,-.81,2.83);
        lock(.128,.290,-.210,.265,.277,.198,.73,3.09);
      }else if(hairStyle==='ponytail'){
        sculpt(head,0,.297,-.336,.272,.251,.307,hardware);
        sculpt(head,.024,.337,-.423,.214,.168,.218,trim);
        lock(-.028,.340,-.476,.332,.49,.265,.28,3.00);
        lock(.073,.336,-.397,.244,.418,.231,-.46,3.07,true,true);
        lock(-.060,.328,.182,.273,.305,.258,-.90,-.18,false,true);
        lock(.102,.312,.185,.248,.317,.236,.97,.08,true);
        lock(.275,.218,.079,.173,.283,.180,.35,.43);
      }else{
        lock(-.169,.358,.145,.213,.343,.228,-1.545,-.08,false,true);
        lock(-.108,.332,.192,.237,.308,.255,-.45,-.06);
        lock(.052,.362,.174,.229,.312,.271,1.17,.15,true);
        lock(.231,.256,.184,.196,.234,.217,.29,.22);
        lock(.339,.253,-.088,.153,.251,.181,.40,1.33);
        lock(-.321,.267,-.097,.173,.252,.195,-.55,-1.27,false,true);
        lock(.028,.332,-.035,.241,.282,.252,-2.048,2.40,false,true);
        lock(.183,.323,-.229,.258,.345,.233,1.62,3.10);
        lock(-.160,.312,-.214,.244,.355,.252,-1.17,3.00,true,true);
      }

      // The gripped headphone rail and product badges read in profile and from the work camera.
      if(headgear!=='cap'&&headgear!=='none'){
        for(const side of [-1,1]){
          const rail=sculpt(head,side*.352,.227,-.088,.096,.343,.136,hardware);
          rail.rotation.z=side*.33;
          sculpt(head,side*.385,.310,-.131,.095,.093,.131,trim);
        }
      }
      if(headgear!=='none'){
        for(const side of [-1,1]){
          const x=side*(headgear==='glasses'?.391:.407);
          const radius=symbol==='knot'?.169:headgear==='visor'?.146:headgear==='glasses'?.105:.122;
          cuff(head,x,-.039,-.136,radius,.102,hardware);
          badge(head,x+side*.063,-.031,-.145,radius*(symbol==='knot'?.97:.80),side*(Math.PI/2+.19),-.13);
        }
      }
      if(headgear==='clip'){
        const clip=group(head,-.296,.245,.316,-.38);
        clip.rotation.z=-.37;
        pillBar(clip,0,0,0,.147,.044,.027,darkEye);
        mesh(clip,glyph.star,light,0,.005,.018,.070,.070,1).castShadow=false;
        pillBar(clip,0,-.05,0,.110,.022,.029,trim);
      }else if(headgear==='cap'){
        sculpt(head,0,.302,-.042,.922,.320,.690,design.jacket,sculptShell).rotation.z=-.092;
        sculpt(head,.025,.250,.240,.880,.086,.497,mixHex(hairHighlight,design.jacket,.55)).rotation.z=-.10;
        sculpt(head,.039,.261,.246,.854,.084,.489,design.jacket).rotation.z=-.10;
        badge(head,.011,.330,.279,.094,0,-.27);
        sculpt(head,0,.474,-.030,.090,.057,.085,trim,smallShell);
      }else if(headgear==='glasses'){
        for(const side of [-1,1]){
          const frame=mesh(head,spectacleFrame,soft(trim),side*.171,.001,.471,.143,.106,1);
          frame.rotation.y=side*.19;frame.rotation.z=side*.10;
          detailLine(head,[side*.307,.022,.442],[side*.423,.028,.081],.021,soft(hardware));
        }
        pillBar(head,0,.020,.469,.103,.025,.026,trim);
      }else if(headgear==='microphone'){
        detailLine(head,[.488,-.041,-.138],[.382,-.142,.274],.032,soft(hardware));
        sculpt(head,.345,-.158,.312,.129,.075,.101,hardware);
        sculpt(head,.311,-.157,.346,.043,.029,.035,trim);
      }else if(headgear==='visor'){
        const glass=soft(trim),shade=soft(hardware);
        for(const side of [-1,1]){
          const corners=[[side*.031,.054,.469],[side*.097,.084,.470],[side*.303,.114,.427],
            [side*.327,-.032,.423],[side*.269,-.081,.451],[side*.077,-.085,.466],[side*.032,.005,.471]];
          for(let i=0;i<corners.length-1;i++)detailLine(head,corners[i],corners[i+1],i===1?.029:.021,glass);
          detailLine(head,[side*.303,.114,.427],[side*.455,.076,-.048],.029,shade);
        }
        pillBar(head,0,.055,.473,.096,.024,.026,trim);
      }
      return expression;
    }

    if(design){
      head.scale.set(1.145,1.10,1.016);
      mouth=buildHumanFace();
    }else{
      shadowCasters.add(pillow(head,0,0,0,w,h,.714,helmet,shell));
      pillow(head,0,.092,-.154,w*.94,h*.823,.498,gear,shell);
      pillow(head,0,-.044,.236,w*.906,h*.743,.386,shade,shell);
      pillow(head,0,-.038,.304,w*.799,h*.645,.271,panel,shell);
      for(const side of [-1,1]){
        const eyeWidth=symbol==='terminal'?.134:person.id==='argon'?.159:.151;
        const eyeHeight=person.id==='argon'?.125:person.id==='astra'?.177:.152;
        const lens=eye(side*.165,-.023,.438,eyeWidth,eyeHeight,side*.15);
        if(person.id==='argon')lens.rotation.z=side*.085;
        pillow(head,side*.258,-.129,.403,.117,.052,.030,luminous(blush));
        cuff(head,side*(w*.47),-.005,-.021,.129,.121,gear);
        cuff(head,side*(w*.47+.060),-.005,-.021,.102,.037,helmet);
        cuff(head,side*(w*.47+.081),-.005,-.021,.048,.016,light);
      }
      mouth=smile(-.143,.432,light);

      badge(head,0,.251,.274,.117,0,-.47);
      // A proud rear crest is visible while the figure faces its monitor.
      const crest=group(head,-.113,.183,-.392,Math.PI+.39);
      crest.rotation.order='YXZ';crest.rotation.x=-.57;
      pillow(crest,0,0,-.022,.436,.429,.126,accent);
      badge(crest,0,0,.051,.183);
    }
    const mug=group(arms[1].hand,.02,.012,.092),tablet=group(body,0,1.0,.36);
    cyl(mug,0,.08,0,.101,.085,.19,manager?'#c6b8eb':accent,10);
    cyl(mug,0,.18,0,.074,.074,.013,'#503c44',10);
    box(mug,.104,.08,0,.065,.095,.055,manager?'#c6b8eb':accent);
    box(tablet,0,0,0,.46,.35,.043,PALETTE.dark);
    box(tablet,0,.005,.027,.38,.26,.02,'#83b6cc');
    for(const y of [-.045,.002,.045])box(tablet,-.039,y,.04,.225,.016,.017,luminous('#d8eeff'));
    mug.visible=tablet.visible=false;
    // Tiny face, fabric and emblem details still receive the body's shadow.
    if(renderer){
      const joints=new Set([root,body,head,mug,tablet,mouth,...eyes]);
      for(const segment of [...arms,...legs])for(const joint of Object.values(segment))joints.add(joint);
      root.traverse(node=>{
        if(node.isMesh)node.castShadow=shadowCasters.has(node);
        // Hair, clothing and insignia inherit their joint's world transform.
        if(!joints.has(node)){node.updateMatrix();node.matrixAutoUpdate=false;}
      });
    }
    return {root,body,head,arms,legs,mug,tablet,eyes,mouth,human:!!design};
  }
  const figures=crew.map((person,i)=>{
    const f=character(person);const home=new THREE.Vector3(person.x-.35,0,person.z+1.30);
    f.root.position.copy(home);f.root.rotation.y=Math.PI;
    return {...f,...person,home,slot:i,status:'idle',activity:'',collaborator:null,doneAt:-100,tag:null};
  });
  const rooms=buildRooms({parent:architecture,animated:dynamic,box,cyl,mesh,rod,group,globe,textureSurface,luminous,floorPad,litFloor,mixHex,THREE});
  const homes=Object.fromEntries(figures.map(f=>[f.id,{x:f.home.x,z:f.home.z,yaw:Math.PI}]));
  const life=createOfficeLife({locations:rooms.anchors,homes});
  let transfer=null,transferKey='',transferStart=0;
  const president=Object.assign(character({id:'president',color:'#5a6e9a'}),{id:'president',name:'呵呵大王'});
  president.root.scale.setScalar(.98);
  const people=[...figures,president];
  const locatorGeo=new THREE.RingGeometry(.53,.56,28);
  const locator=mesh(dynamic,locatorGeo,dimIce,0,.067,0,1,1,1);locator.rotation.x=-Math.PI/2;
  locator.castShadow=false;
  const stationRing=new THREE.RingGeometry(.93,.959,32);
  const trails=figures.map(f=>{
    const m=luminous(f.color);
    const band=mesh(dynamic,stationRing,m,f.home.x-.38,.086,f.home.z-.14,1,1,1);
    band.rotation.x=-Math.PI/2;band.castShadow=false;band.receiveShadow=false;
    const packets=[0,1,2].map(()=>{const bit=mesh(dynamic,globe,m,0,0,0,.085,.045,.085);bit.castShadow=false;return bit});
    return {band,packets};
  });
  const markerGeo=new THREE.RingGeometry(.39,.47,28);
  const markerMat=new THREE.MeshBasicMaterial({color:'#b0c8e9',depthWrite:false,side:THREE.DoubleSide});
  const marker=mesh(dynamic,markerGeo,markerMat,0,.065,0,1,1,1);marker.rotation.x=-Math.PI/2;marker.visible=false;
  const confettiColors=['#ffbf6f','#6ce9e6','#dd91ff','#ff8daf','#6ae3a5','#a8bbff'];
  const confetti=figures.map(()=>confettiColors.map((c,i)=>{
    const obj=box(dynamic,0,0,0,.13,.06,.06,luminous(c));obj.castShadow=false;obj.visible=false;return obj;
  }));
  const shadowCanvas=document.createElement('canvas');shadowCanvas.width=shadowCanvas.height=128;
  const shadowCtx=shadowCanvas.getContext('2d'),fade=shadowCtx.createRadialGradient(64,64,30,64,64,64);
  fade.addColorStop(0,'rgba(4,9,25,.35)');fade.addColorStop(.66,'rgba(4,9,25,.20)');fade.addColorStop(1,'rgba(4,9,25,0)');
  shadowCtx.fillStyle=fade;shadowCtx.fillRect(0,0,128,128);
  const shadowTex=new THREE.CanvasTexture(shadowCanvas);shadowTex.colorSpace=THREE.SRGBColorSpace;textures.push(shadowTex);
  const catcher=new THREE.Mesh(plane,new THREE.MeshBasicMaterial({map:shadowTex,transparent:true,depthWrite:false}));
  catcher.rotation.x=-Math.PI/2;catcher.scale.set(30,21,1);catcher.position.set(.3,-.55,.05);scene.add(catcher);
  // Instancing keeps the five detailed workstations inexpensive on integrated GPUs.
  if(renderer) {
    architecture.updateMatrixWorld(true);
    const batches=new Map(), originals=[];
    architecture.traverse(obj=>{
      if(!obj.isMesh || obj.material.map) return;
      const palette=palettes.get(obj.material);
      const material=palette??obj.material;
      const key=[obj.geometry.id,material.id].join('/');
      if(!batches.has(key)) batches.set(key,{geometry:obj.geometry,material,palette,sources:[]});
      batches.get(key).sources.push(obj);originals.push(obj);
    });
    originals.forEach(obj=>obj.removeFromParent());
    for(const {geometry,material,palette,sources} of batches.values()) {
      const batch=new THREE.InstancedMesh(geometry,material,sources.length);
      sources.forEach((source,index)=>{
        batch.setMatrixAt(index,source.matrixWorld);
        if(palette)batch.setColorAt(index,source.material.color);
      });
      batch.castShadow=true;batch.receiveShadow=true;architecture.add(batch);
    }
    architecture.updateMatrixWorld(true);
    architecture.traverse(node=>{node.matrixAutoUpdate=false;node.matrixWorldAutoUpdate=false;});
  }

  let poseBatches=[],batchPopulation=0;
  function updatePoseInstances(){
    if(batchPopulation!==poseRig.children.length){
      poseBatches.forEach(({batch})=>{batch.removeFromParent();batch.dispose();});
      const sourceGroups=new Map();
      poseRig.traverse(source=>{
        if(!source.isMesh)return;
        const material=palettes.get(source.material)??source.material;
        const key=[source.geometry.id,material.id,source.castShadow,source.receiveShadow].join('/');
        if(!sourceGroups.has(key))sourceGroups.set(key,[]);
        sourceGroups.get(key).push(source);
      });
      poseBatches=Array.from(sourceGroups.values(),sources=>{
        const {geometry,material,castShadow,receiveShadow}=sources[0];
        const palette=palettes.get(material);
        const batch=new THREE.InstancedMesh(geometry,palette??material,sources.length);
        batch.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
        if(palette){
          batch.setColorAt(0,material.color);
          batch.instanceColor.setUsage(THREE.DynamicDrawUsage);
        }
        batch.castShadow=castShadow;batch.receiveShadow=receiveShadow;
        // The rig moves between desks, so a bounding sphere from its initial position expires.
        batch.frustumCulled=false;
        poseInstances.add(batch);
        return {sources,batch,lastSources:[]};
      });
      batchPopulation=poseRig.children.length;
    }
    poseRig.updateMatrixWorld(true);
    for(const {sources,batch,lastSources} of poseBatches){
      let index=0,colorsChanged=false;
      source: for(const mesh of sources){
        for(let node=mesh;node!==poseRig;node=node.parent)if(!node.visible)continue source;
        batch.setMatrixAt(index,mesh.matrixWorld);
        if(batch.instanceColor && lastSources[index]!==mesh){
          batch.setColorAt(index,mesh.material.color);lastSources[index]=mesh;colorsChanged=true;
        }
        index++;
      }
      batch.count=index;
      batch.visible=index>0;
      if(index)batch.instanceMatrix.needsUpdate=true;
      if(colorsChanged)batch.instanceColor.needsUpdate=true;
    }
  }

  // A small depth-sorted Canvas fallback retains camera controls and live characters
  // in remote desktops and browsers that do not expose a WebGL2 context.
  let drawingCanvas=canvas, context=null;
  if(!renderer){
    adaptiveSoft=true;
    drawingCanvas=canvas.cloneNode();canvas.replaceWith(drawingCanvas);
    context=drawingCanvas.getContext('2d');
  }
  let width=1,height=1,pixelRatio=1,lighting='day',selected=null,view='overview',callback=null,chatter=true;
  let sim=0,lastFrame=0,raf=0,disposed=false,visible=true,instantCamera=true,lastMarket='';
  let nextFrame=0,lastShadow=-Infinity,lastTags=-Infinity;
  const activeStatuses=new Set(['thinking','coding','browsing','terminal']);
  function isWorking(person){return activeStatuses.has(person.status);}
  function activeWork(){return summary?.running>0 || figures.some(isWorking) || guests.some(f=>f.online && f.root.visible && isWorking(f));}
  const aim=new THREE.Vector3(),camOffset=new THREE.Vector3(13,12.8,16.2).normalize().multiplyScalar(40);
  const initialYaw=Math.atan2(13,16.2),initialPitch=Math.asin(camOffset.y/40);
  let yaw=initialYaw,pitch=initialPitch,zoom=1,zoomCallback=null,orientationDirty=true;
  const cameraPresets={
    overview:{at:[0,1.68,0],span:1},
    workstations:{at:[-.48,.87,1.52],span:.62},
    meeting:{at:[3.88,1.19,-3.6],span:.50},
    lounge:{at:[8.4,1.02,-.08],span:.57}
  };
  let span=1,focusedDesk=null;
  const vector=new THREE.Vector3(),raycaster=new THREE.Raycaster();
  function attachTag(f){
    const btn=document.createElement(wallpaper?'span':'button');
    if(!wallpaper)btn.type='button';
    const name=document.createElement('strong'),activity=document.createElement('small');
    name.textContent=f.name;
    name.style.cssText='font-weight:700;display:block;line-height:1.18';
    activity.style.cssText='display:block;font-weight:500;color:#cdd8ee;line-height:1.2;margin-top:1px';
    btn.append(name,activity);f.activityTag=activity;
    btn.setAttribute('aria-label',f===president?'呵呵大王，总裁，分配任务':'选择 '+f.name);
    Object.assign(btn.style,{
      position:'absolute',left:'0',top:'0',zIndex:'1',display:'block',whiteSpace:'nowrap',lineHeight:'1.1',
      padding:'3px 6px',border:'1px solid #7b91b490',borderRadius:'5px',backgroundColor:'#1c2942ed',
      color:'#e5f1ff',font:'600 10px/1.05 system-ui, sans-serif',boxShadow:'0 2px 3px #080d1988',
      cursor:'pointer',touchAction:'manipulation'
    });
    const lead=document.createElement('span'),bubble=document.createElement('div');
    lead.setAttribute('aria-hidden','true');lead.style.cssText='position:absolute;height:1px;pointer-events:none;transform-origin:0 50%;background:#b6c9e8ab;z-index:1';
    bubble.setAttribute('aria-hidden','true');bubble.className='office-speech';bubble.style.cssText='position:absolute;z-index:3;pointer-events:none;white-space:nowrap;border:1px solid #b8b0df;border-radius:7px 7px 7px 2px;background:#eee9fc;color:#2d2645;padding:4px 7px;box-shadow:0 2px 7px #070a2490;font:600 11px/1.25 system-ui,sans-serif';
    const origin=document.createElement('small'),line=document.createElement('span');
    origin.textContent='场景闲聊';origin.style.cssText='display:block;font-size:.8em;font-weight:600;color:#645178;margin-bottom:1px';
    bubble.append(origin,line);bubble.hidden=true;
    if(!wallpaper)btn.addEventListener('click',()=>callback?.(f.id));container.append(lead,btn,bubble);
    Object.assign(f,{tag:btn,leader:lead,bubble,speechText:line});
  
  }
  people.forEach(attachTag);
  const guests=[];
  const guestColors=['#84dbe2','#fac48b','#c6a4ff','#a2d98a'];
  function guestSeat(i){
    const color=guestColors[i%guestColors.length],room=group(poseRig);
    box(room,0,-.22,.36,3.72,.42,3.08,'#29344d');
    box(room,0,.005,.36,3.65,.06,3.02,'#4c5974');
    box(room,0,-.13,1.91,3.36,.045,.025,luminous(color));
    box(room,0,1.17,0,2.68,.12,1.18,'#8598b0');
    for(const x of [-1.09,1.09])box(room,x,.57,0,.16,1.14,.83,'#394761');
    box(room,0,1.47,-.19,.13,.53,.13,'#40506d');
    box(room,0,1.86,-.19,1.28,.81,.12,'#25344d');
    box(room,0,1.86,-.12,1.12,.64,.03,'#203958');
    for(let k=0;k<3;k++)box(room,-.15+k*.04,2-k*.12,-.096,.52-k*.08,.025,.018,luminous(color));
    box(room,0,1.255,.33,.83,.055,.29,'#566885');
    chair(room,0,1.30,Math.PI,color);
    const f=Object.assign(character({id:'guest',color}),{color,name:'协作 '+String(i+1).padStart(2,'0'),room,
      station:{keyboard:new THREE.Vector3(),gaze:new THREE.Vector3()}});
    f.root.rotation.y=Math.PI;attachTag(f);people.push(f);return f;
  }
  let guestRows=0;
  function setGuests(rows){
    const count=Math.min(rows.length,12);guestRows=Math.ceil(count/4);
    for(let i=0;i<Math.max(guests.length,count);i++){
      const f=guests[i]??(guests[i]=guestSeat(i));
      f.root.visible=f.room.visible=i<count;
      if(i>=count)continue;
      const columns=Math.min(4,count-Math.floor(i/4)*4);
      const x=(i%4-(columns-1)/2)*3.76,z=8.5+Math.floor(i/4)*3.12;
      f.id=rows[i].id;f.room.position.set(x,0,z);f.root.position.set(x,0,z+1.30);
      f.station.keyboard.set(x,1.31,z+.33);f.station.gaze.set(x,1.86,z-.09);
      f.online=rows[i].online;f.status=rows[i].status;
    }
    cameraPresets.overview.at[2]=guestRows?(1.55+(guestRows-1)*1.56):0;
  }
  const staticFaces=[];
  function gatherFaces(root,faces,timeLayer=0){
    root.updateWorldMatrix(true,true);
    root.traverseVisible(obj=>{
      if(!obj.isMesh || obj===marker || !obj.geometry.attributes.position) return;
      const geom=obj.geometry,mat=obj.material,points=geom.attributes.position,idx=geom.index;
      const n=idx?idx.count:points.count, normalMatrix=new THREE.Matrix3().getNormalMatrix(obj.matrixWorld);
      const world=(index)=>new THREE.Vector3().fromBufferAttribute(points,idx?idx.getX(index):index).applyMatrix4(obj.matrixWorld);
      let layer=timeLayer;for(let p=obj;p;p=p.parent) if(p.userData.layer!==undefined) {layer=p.userData.layer;break;}
      const add=(positions,index)=>{
        const normal=new THREE.Vector3().fromBufferAttribute(geom.attributes.normal,idx?idx.getX(index):index).applyMatrix3(normalMatrix).normalize();
        if(normal.dot(camOffset)<=0) return;
        const center=new THREE.Vector3();positions.forEach(v=>center.add(v));center.divideScalar(positions.length);
        const unlit=mat.isMeshBasicMaterial;
        const dayDot=Math.max(0,normal.dot(keyLight)),nightDot=Math.max(0,normal.dot(nightKey));
        const color=mat.color||new THREE.Color('white');
        faces.push({positions,layer,depth:center.dot(camOffset),image:obj.userData.image,
          day:unlit?color.getStyle():color.clone().multiplyScalar(.64+.21*(normal.y+1)/2+.45*dayDot).getStyle(),
          night:unlit?color.getStyle():color.clone().multiply(new THREE.Color(.71,.84,1)).multiplyScalar(.50+.34*nightDot+.12*normal.y).getStyle()});
      };
      if(geom===cube) {
        for(let i=0;i<n;i+=6) add([world(i),world(i+1),world(i+4),world(i+2)],i);
      } else if(geom===plane) {
        add([world(0),world(2),world(4),world(1)],0);
      } else {
        for(let i=0;i<n;i+=3) add([world(i),world(i+1),world(i+2)],i);
      }
    });
  }
  const keyLight=new THREE.Vector3(-.28,.8,.57).normalize(),nightKey=new THREE.Vector3(-.50,.80,.25).normalize();

  function project(v){
    vector.copy(v).project(camera);
    return [(vector.x+1)*width/2,(1-vector.y)*height/2];
  }
  function renderSoftware(){
    context.setTransform(pixelRatio,0,0,pixelRatio,0,0);
    context.clearRect(0,0,width,height);
    const ground=project(new THREE.Vector3(.15,-.62,.1));
    context.save();context.translate(...ground);context.scale(width*.45,height*.23);
    const shadow=context.createRadialGradient(0,0,.16,0,0,1);shadow.addColorStop(0,'#05091a69');shadow.addColorStop(.73,'#05091a3d');shadow.addColorStop(1,'#05091a00');
    context.fillStyle=shadow;context.fillRect(-1,-1,2,2);context.restore();
    const faces=staticFaces.slice();
    gatherFaces(dynamic,faces);faces.sort((a,b)=>a.layer-b.layer || a.depth-b.depth);
    context.lineJoin='round';context.lineWidth=.4;
    for(const f of faces){
      const pts=f.positions.map(project);
      if(f.image) {
        const [o,r,,b]=pts;
        context.save();context.transform((r[0]-o[0])/f.image.width,(r[1]-o[1])/f.image.width,(b[0]-o[0])/f.image.height,(b[1]-o[1])/f.image.height,o[0],o[1]);
        context.drawImage(f.image,0,0);context.restore();continue;
      }
      context.beginPath();context.moveTo(...pts[0]);for(let i=1;i<pts.length;i++)context.lineTo(...pts[i]);
      context.closePath();context.fillStyle=context.strokeStyle=lighting==='night'?f.night:f.day;context.fill();context.stroke();
    }
  }
  function setCamera(dt){
    const target=focusedDesk??cameraPresets[view],t=instantCamera || reduced.matches?1:1-Math.exp(-dt*5);
    aim.lerp(vector.set(...target.at),t);span+=(target.span-span)*t;
    if(orientationDirty){
      camOffset.set(Math.sin(yaw)*Math.cos(pitch),Math.sin(pitch),Math.cos(yaw)*Math.cos(pitch)).multiplyScalar(40);
      if(context){staticFaces.length=0;gatherFaces(architecture,staticFaces);}
      orientationDirty=false;
    }
    camera.position.copy(aim).add(camOffset);camera.lookAt(aim);camera.updateMatrixWorld(true);
    const aspect=width/height;
    // Fit all four floor corners and the tall back wall at every aspect ratio.
    const extra=view==='overview'&&guestRows?1.55+(guestRows-1)*1.56:0;
    const horizontal=(11.16*Math.cos(yaw)+(7.21+extra)*Math.sin(yaw))*1.035;
    const vertical=((11.15*Math.sin(yaw)+(7.19+extra)*Math.cos(yaw))*Math.sin(pitch)+2.41*Math.cos(pitch))*1.045;
    const halfW=(focusedDesk?Math.max(1.86,1.52*aspect):Math.max(horizontal,vertical*aspect)*span)/zoom;
    camera.left=-halfW;camera.right=halfW;camera.top=halfW/aspect;camera.bottom=-halfW/aspect;
    camera.updateProjectionMatrix();instantCamera=false;
  }
  const limbDirection=new THREE.Vector3();
  const handOnDesk=new THREE.Vector3(),lookAtScreen=new THREE.Vector3();
  const armHome=[new THREE.Vector3(),new THREE.Vector3()];
  function aimSegment(segment,start,end){
    limbDirection.subVectors(end,start);
    segment.position.copy(start).lerp(end,.5);
    segment.scale.y=limbDirection.length();
    segment.quaternion.setFromUnitVectors(Y_AXIS,limbDirection.normalize());
  }

  const shoulderPoint=new THREE.Vector3(),elbowPoint=new THREE.Vector3(),wrist=new THREE.Vector3();
  const hip=new THREE.Vector3(),kneePoint=new THREE.Vector3(),ankle=new THREE.Vector3();
  function poseCharacter(f,{seating,walking,step,pose,t,movement,station,deskSeat,lookYaw=0}){
    const motion=walking?movement:0;
    const swing=Math.sin(step),rock=Math.sin(t*2.7)*movement;
    const s=seating;
    const isDesk=deskSeat&&s>.02;
    const standingDrop=f.human?.067*(1-s):0;
    f.body.position.set(0,.187*s+Math.abs(swing)*.045*motion-standingDrop,0);
    const lean=pose==='lounge'?-.057:pose==='meeting'?.065:isDesk?.12:0;
    f.body.rotation.x=pose==='game'?.16:lean*s;
    f.body.rotation.z=swing*.027*motion;
    f.body.updateWorldMatrix(true,false);
    if(isDesk) f.body.worldToLocal(handOnDesk.copy(station.keyboard));
    f.arms.forEach((arm,i)=>{
      const side=i?1:-1;
      const stride=swing*side*motion;
      shoulderPoint.set(side*.345,1.224,-.005);
      elbowPoint.set(side*.390,.981,stride*.137+.12*s);
      wrist.set(side*.391,.738,stride*.28+.29*s);
      let tilt=-.30+stride*.49;
      if(isDesk){
        const keyTap=pose==='type'?Math.sin(t*(i?15.4:13.1)+i*1.12)*movement:0;
        armHome[i].copy(handOnDesk);
        // The wrist stays just behind the key surface. Finger tips land on the keys.
        armHome[i].x+=side*(pose==='read'&&i?.57:.218)+keyTap*.018;
        armHome[i].z-=.111+keyTap*.025;
        armHome[i].y+=.012+Math.max(0,keyTap)*.025;
        const weight=clamp((s-.12)/.80,0,1)*clamp((handOnDesk.z-.45)/.27,0,1);
        wrist.lerp(armHome[i],weight);
        elbowPoint.set(side*.363,Math.min(1.19,wrist.y-.002),.30+.085*s);
        tilt=-.16;
        if(pose==='think'&&!i){wrist.set(-.159,1.465,.467);elbowPoint.set(-.365,1.09,.442);tilt=-.84;}
      }else if(pose==='meeting'){
        elbowPoint.set(side*.398,1.00,.19);
        wrist.set(side*.318,1.061+(i?.08:0)+rock*.068,.43+rock*.038);
        tilt=-.30;
      }else if(pose==='game'){
        const play=movement*Math.sin(t*(i?13.4:8.8)+i*1.32);
        elbowPoint.set(side*.342,1.110,.463);
        wrist.set(side*.269+play*.037,1.45+play*.019,.865+play*.040);
        tilt=-.29;
      }else if(pose==='coffee'&&i){
        const sip=(.5-.5*Math.cos(t*1.30))*movement;
        elbowPoint.set(.397,.930+.24*sip,.213+.06*sip);
        wrist.set(.218-.075*sip,1.053+.278*sip,.388+.10*sip);
        tilt=0;
      }else if(pose==='read'||pose==='briefing'){
        elbowPoint.set(side*.391,.980,.14);
        wrist.set(side*.224,1.09,.425);
        tilt=-.70;
      }else if(pose==='chat'&&!i){
        elbowPoint.set(-.387,.96,.21);
        wrist.set(-.325+rock*.04,1.115+rock*.065,.38+rock*.044);
        tilt=-.65;
      }else if(pose==='lounge'||pose==='chat'){
        elbowPoint.set(side*.372,.945,.16);
        wrist.set(side*.275,.88,.44);
        tilt=-.02;
      }
      if(((pose==='attention'||pose==='error')&&i)||pose==='celebrate'){
        elbowPoint.set(side*.475,1.43,.17);
        wrist.set(side*.510,1.665+rock*.082,.31+rock*.036);
        tilt=-1.08;
      }
      arm.shoulder.position.copy(shoulderPoint);
      arm.elbow.position.copy(elbowPoint);
      arm.hand.position.copy(wrist);
      arm.hand.rotation.set(tilt,0,0);
      aimSegment(arm.upper,shoulderPoint,elbowPoint);
      aimSegment(arm.lower,elbowPoint,wrist);
    });
    f.legs.forEach((leg,i)=>{
      const side=i?1:-1;
      const stride=swing*side*motion;
      hip.set(side*.151,.665,-.01);
      kneePoint.set(side*.174,.389+.222*s,.021+.408*s+stride*.14);
      ankle.set(side*.174,.139-f.body.position.y+Math.max(0,stride)*.106,.012+.451*s+stride*.248);
      leg.knee.position.copy(kneePoint);
      leg.shoe.position.copy(ankle);
      leg.shoe.rotation.x=-f.body.rotation.x+stride*.25;
      aimSegment(leg.thigh,hip,kneePoint);
      aimSegment(leg.shin,kneePoint,ankle);
    });
    f.head.rotation.order='YXZ';
    f.head.rotation.y=walking?rock*.042:pose==='chat'?lookYaw+rock*.04:0;
    f.head.rotation.z=pose==='think'?-.112:pose==='chat'?-.065+rock*.042:0;
    f.head.rotation.x=pose==='read'||pose==='briefing'?.24:pose==='coffee'?-.07*rock:0;
    if(isDesk){
      f.body.worldToLocal(lookAtScreen.copy(station.gaze)).sub(f.head.position);
      const glance=pose==='read'?.060*rock:pose==='think'?.025:0;
      f.head.rotation.y=clamp(Math.atan2(lookAtScreen.x,lookAtScreen.z),-.36,.36)+glance;
      f.head.rotation.x=clamp(-Math.atan2(lookAtScreen.y,Math.hypot(lookAtScreen.x,lookAtScreen.z)),-.23,.28);
    }
    f.mug.visible=pose==='coffee'&&!walking;
    f.tablet.visible=(pose==='read'&&!isDesk)||pose==='briefing';
    f.tablet.position.set(0,1.09,.443);
    f.tablet.rotation.x=-.46;
    const blink=movement&&t%5.6<.13;
    for(const eye of f.eyes){
      if(eye.userData.neutralHeight){
        eye.scale.y=eye.userData.neutralHeight*(blink?.16:pose==='think'?.72:1);
      }else eye.visible=!blink;
    }
    if(f.mouth.userData.neutralHeight){
      const talking=(pose==='chat'&&f.speech)||pose==='meeting';
      f.mouth.scale.y=f.mouth.userData.neutralHeight*(talking?1+Math.max(0,Math.sin(t*13))*1.4*movement:1);
    }
  }

  const patrolStops=[[-2.25,1.38],[6.48,1.38],[6.48,4.98],[-3.13,4.98],
    [-3.13,5.04],[-3.13,4.98],[-7.35,4.98],[-7.35,1.38]];
  president.root.position.set(patrolStops[0][0],.015,patrolStops[0][1]);
  let patrolIndex=1,patrolPause=0,patrolStep=0,patrolWait=0;
  function animatePresident(dt,movement,blend){
    const target=patrolStops[patrolIndex],pos=president.root.position;
    const dx=target[0]-pos.x,dz=target[1]-pos.z,dist=Math.hypot(dx,dz);
    const atReception=patrolIndex===5&&patrolPause>0;
    const command=summary?.command;
    const onDuty=command && command.phase!=='review' && sim%12<3.5;
    let walking=false;
    if(onDuty){
      // Brief the team from the current safe position, then resume the patrol.
      patrolWait=0;
    }else if(patrolPause>0){
      patrolPause=Math.max(0,patrolPause-dt);
    }else if(movement){
      if(dist<.025){
        patrolPause=patrolIndex===4?7:patrolIndex===0?2:0;
        patrolIndex=(patrolIndex+1)%patrolStops.length;patrolWait=0;
      }else{
        const stride=Math.min(dt*.94,dist),frac=stride/dist;
        const nx=pos.x+dx*frac,nz=pos.z+dz*frac;
        const clear=figures.every(f=>{
          const before=Math.hypot(f.root.position.x-pos.x,f.root.position.z-pos.z);
          const after=Math.hypot(f.root.position.x-nx,f.root.position.z-nz);
          return after>=1.02||after>before;
        });
        if(clear){
          pos.x=nx;pos.z=nz;patrolStep=(patrolStep+stride*4.4)%TAU;walking=true;patrolWait=0;
        }else if((patrolWait+=dt)>1.5){
          patrolIndex=(patrolIndex+patrolStops.length-1)%patrolStops.length;patrolWait=0;
        }
      }
    }
    const direction=onDuty ? .65 : atReception?0:walking?Math.atan2(dx,dz):president.root.rotation.y;
    president.root.rotation.y+=Math.atan2(Math.sin(direction-president.root.rotation.y),Math.cos(direction-president.root.rotation.y))*blend;
    poseCharacter(president,{seating:0,walking,step:patrolStep,pose:onDuty?(command.phase==='blocked'?'attention':'briefing'):atReception?'briefing':'idle',t:sim,movement});
    president.caption=command?.text || (summary?.reviews?'有 '+summary.reviews+' 项待验收':atReception?'看简报 ing':'巡视 ing');
    locator.position.set(pos.x,.067,pos.z);
  }
  function animateFigures(dt){
    const fx=animatedEffects();
    const movement=reduced.matches?0:1;
    const blend=reduced.matches?1:1-Math.exp(-dt*3.2);
    const standby=summary?.command?.standby || '';
    const frames=life.tick(dt,{reducedMotion:reduced.matches,soft:effects==='soft',night:lighting==='night',obstacles:[president.root.position],standby});
    rooms.update?.(sim,fx,frames.some(p=>p.pose==='game'&&!p.walking));
    figures.forEach((f,i)=>{
      const frame=frames.find(p=>p.id===f.id);
      if(!frame)return;
      const {walking,seated,pose}=frame,meetingSeat=pose==='meeting';
      const t=sim+i*1.73,active=pose==='type',pathPhase=frame.step;
      const caption=frame.caption||'待命';
      f.caption=['assigned','queued'].includes(f.status)||caption==='任务完成' ?
        caption : caption.replace(/(?:\s*ing|中)$/i,'')+' ing';
      if(wallpaper)f.caption=!f.reported?'待报到':f.id==='codex'&&codexEdit?editStages[codexEdit.stage]:workLabel(f.status,f.activity);
      if(standby && f.status==='idle')f.caption=standby;
      f.speech=wallpaper?'':frame.speech||'';
      f.root.position.set(frame.x,0,frame.z);
      const look=frame.angle;
      f.root.rotation.y+=Math.atan2(Math.sin(look-f.root.rotation.y),Math.cos(look-f.root.rotation.y))*blend;
      f.pose=pose;f.tag.dataset.pose=pose;
      const edit=f.id==='codex'?codexEdit:null;
      const station=stationScreens.get(f.id),phase=!edit&&f.status==='thinking'&&active&&fx?Math.floor(sim*1.7)%3:-1;
      if(station.status!==f.status||station.activity!==f.activity||phase!==station.phase||station.edit!==edit){
        station.edit=edit;
        station.status=f.status;station.activity=f.activity;station.phase=phase;
        station.display.refresh((...args)=>drawMonitor(...args,{id:f.id,color:f.color,status:f.status,
          activity:f.activity,phase:Math.max(0,phase),edit}));
      }
      const engaged=!['idle','done','error'].includes(f.status);
      const wave=fx?.5-.5*Math.cos(t*(engaged?2.2:.82)):.5;
      station.lampMat.color.copy(station.rgb).multiplyScalar(engaged?.78+.22*wave:.48+.12*wave);
      const lampHeight=engaged?.70+.23*wave:.47;
      station.lamp.scale.y=lampHeight;station.lamp.position.y=1.239+lampHeight*.5;
      const trail=trails[i];trail.band.visible=engaged;
      const pulse=fx?(t*.48)%1:.36;
      trail.band.scale.setScalar(.66+pulse*.43);
      trail.packets.forEach((packet,j)=>{
        if(transfer&&f.id===transfer.sender){
          const end=homes[transfer.receiver],u=(sim-transferStart)*.48-j*.14;
          packet.visible=!!end&&fx&&u>=0&&u<=1;
          if(packet.visible)packet.position.set(THREE.MathUtils.lerp(f.home.x,end.x,u),.35+Math.sin(u*Math.PI)*1.7,THREE.MathUtils.lerp(f.home.z,end.z,u));
          return;
        }
        packet.visible=meetingSeat&&fx;
        if(!packet.visible)return;
        const u=(sim*.24+j/3)%1;
        packet.position.set(THREE.MathUtils.lerp(f.home.x,4.25,u),.135+.08*Math.sin(u*Math.PI),
          THREE.MathUtils.lerp(f.home.z,-1.95,u)+.37*Math.sin(u*Math.PI));
      });
      const deskSeat=Math.hypot(frame.x-f.home.x,frame.z-f.home.z)<.20;
      const targetSeat=frame.seatBlend??Number(seated);
      f.seating=THREE.MathUtils.lerp(f.seating??targetSeat,targetSeat,clamp(dt*10,0,1));
      const jumpTime=sim-f.doneAt;
      poseCharacter(f,{seating:f.seating,walking,step:pathPhase,pose,t,movement,station,deskSeat,lookYaw:frame.lookYaw});
      f.body.position.y+=(frame.celebration||0)*.50*movement;
      confetti[i].forEach((piece,j)=>{
        piece.visible=jumpTime>=0 && jumpTime<1.25 && fx;
        if(!piece.visible)return;
        const a=j*2+.4;piece.position.set(f.root.position.x+Math.cos(a)*jumpTime,2.2+2.6*jumpTime-2.8*jumpTime*jumpTime,f.root.position.z+Math.sin(a)*jumpTime);
        piece.rotation.set(jumpTime*4+a,jumpTime*2,a);
      });
    });
    animatePresident(dt,movement,blend);
    guests.forEach((f,i)=>{
      if(!f.root.visible)return;
      const active=f.status==='thinking',done=f.status==='done',error=f.status==='error';
      const queued=f.status==='queued',assigned=f.status==='assigned';
      const pose=active?'type':error?'attention':queued||assigned?'read':f.online?'think':'idle';
      f.caption=active?'处理分工 ing':done?'已交付':error?'需要协助':
        queued?'等待领取':assigned?'等待接力':f.online?'在线待命':'等待连接';
      poseCharacter(f,{seating:1,walking:false,step:0,pose,t:sim+i,movement,station:f.station,deskSeat:true});
    });
    const focus=figures.find(f=>f.id===selected);
    marker.visible=!!focus && focus.root.visible;
    if(marker.visible)marker.position.set(focus.root.position.x,.076,focus.root.position.z);
  }
  const overlayElements=Array.from(container.parentElement.querySelectorAll('.viewport-label,#desk-lens,#chatter,#lighting-label'));
  function placeTags(){
    const canvasRect=container.getBoundingClientRect();
    const overlays=overlayElements.flatMap(element=>{
      const bounds=element.getBoundingClientRect();
      if(!bounds.width||!bounds.height)return [];
      return [{x:(bounds.left+bounds.right)/2-canvasRect.left,y:(bounds.top+bounds.bottom)/2-canvasRect.top,
        w:bounds.width,h:bounds.height}];
    });
    const small=width<480,occupied=[...overlays],shown=[];
    const labelScale=wallpaper?clamp(Math.min(width/1536,height/900),1,1.55):1;
    const size=small?8:Math.round(10*labelScale), textWidth=text=>Array.from(text).reduce((w,ch)=>w+(/[^ -~]/.test(ch)?size:size*.57),0);
    const clips=(cx,cy,w,h)=>occupied.some(r=>Math.abs(cx-r.x)<(w+r.w)/2+3&&Math.abs(cy-r.y)<(h+r.h)/2+2);
    const tagAt=people.map(f=>{
      const p=f.root.position.clone();p.y+=2.40+f.body.position.y;
      return {f,point:project(p)};
    }).sort((a,b)=>Number(b.f.id===selected)-Number(a.f.id===selected)||a.point[1]-b.point[1]);
    for(const {f,point:[px,py]} of tagAt){
      f.bubble.hidden=true;f.leader.style.display='none';
      const inView=f.root.visible&&px>=0&&px<=width&&py>=-4&&py<height-5;
      f.tag.hidden=!inView;f.tag.style.display=inView?'block':'none';if(!inView)continue;
      if(f.activityTag.textContent!==f.caption)f.activityTag.textContent=f.caption||'待命 ing';
      f.tag.style.fontSize=size+'px';f.activityTag.style.fontSize=(small?7.6:Math.round(9*labelScale))+'px';
      f.tag.style.padding=small?'2px 4px':'3px 6px';
      const tw=Math.max(textWidth(f.name),textWidth(f.caption||''))+(small?11:15),th=small?24:Math.ceil(24*labelScale+7);
      const bx=clamp(px,tw/2+3,width-tw/2-3),by=clamp(py-th/2-1,th/2+3,height-th/2-3);
      const candidates=[[0,0],[0,-th-3],[-tw*.70,-4],[tw*.70,-4],[0,th+4],[-tw*.65,-th],[tw*.65,-th],[0,-th*2]];
      if(clips(bx,by,tw,th)){
        for(const r of overlays){
          const padX=(r.w+tw)/2+5,padY=(r.h+th)/2+5;
          candidates.push([r.x-padX-bx,0],[r.x+padX-bx,0],[0,r.y+padY-by],[0,r.y-padY-by]);
        }
      }
      let tx,ty;
      for(const [dx,dy] of candidates){
        const cx=clamp(bx+dx,tw/2+3,width-tw/2-3),cy=clamp(by+dy,th/2+3,height-th/2-3);
        if(!clips(cx,cy,tw,th)){tx=cx;ty=cy;break;}
      }
      if(tx===undefined){f.tag.hidden=true;f.tag.style.display='none';continue;}
      occupied.push({x:tx,y:ty,w:tw,h:th});shown.push({f,tx,ty,th});
      f.tag.style.transform='translate('+tx.toFixed(1)+'px,'+ty.toFixed(1)+'px) translate(-50%,-50%)';
      f.tag.style.backgroundColor=f===president?'#383451f5':selected===f.id?'#304e69':'#17233cf2';
      f.tag.style.color=f===president?'#e6dcff':'#e7f2ff';
      f.tag.style.borderColor=f===president?'#b29ee0':selected===f.id?f.color:mixHex(f.color,'#334567',.57);
      f.tag.style.boxShadow=f===president?'0 2px 3px #080d1988':'inset 2px 0 0 '+f.color+',0 2px 3px #080d1988';
      const dy=ty+th/2-py,dx=tx-px,len=Math.hypot(dx,dy);
      if(len>8&&!overlays.some(r=>Math.abs(px-r.x)<r.w/2&&Math.abs(py-r.y)<r.h/2)){
        Object.assign(f.leader.style,{display:'block',left:px+'px',top:py+'px',width:len+'px',transform:'rotate('+Math.atan2(dy,dx)+'rad)'});
      }
    }
    for(const {f,tx,ty,th} of shown){
      if(!chatter||!f.speech)continue;
      const bw=Math.max(53,textWidth(f.speech)*1.16+13),bh=small?30:Math.ceil(26*labelScale+8),step=th/2+bh/2+4;
      const side=bw*.64;
      const places=[[tx,ty-step],[tx,ty+step],[tx+side,ty-step],[tx-side,ty-step],
        [tx+side,ty+step],[tx-side,ty+step],[tx+bw/2+25,ty],[tx-bw/2-25,ty],
        [tx,ty-step-bh],[tx,ty+step+bh]];
      let spot=null;
      for(const [x,y] of places){
        const cx=clamp(x,bw/2+3,width-bw/2-3),cy=clamp(y,bh/2+3,height-bh/2-3);
        if(!clips(cx,cy,bw,bh)){spot={x:cx,y:cy,w:bw,h:bh};break;}
      }
      if(!spot)continue;
      f.speechText.textContent=f.speech;f.bubble.style.fontSize=(small?9:Math.round(11*labelScale))+'px';
      f.bubble.style.left=spot.x+'px';f.bubble.style.top=spot.y+'px';f.bubble.style.transform='translate(-50%,-50%)';
      f.bubble.hidden=false;occupied.push(spot);
    }
  }
  function syncAnimation(){
    if(!disposed&&!document.hidden&&visible&&width>1&&height>1){
      if(!raf)raf=requestAnimationFrame(draw);
    }else{
      if(raf)cancelAnimationFrame(raf);
      nextFrame=raf=lastFrame=rateStart=renderedFrames=0;
    }
  }
  function draw(frame){
    raf=0;
    if(disposed || document.hidden || !visible || width<=1 || height<=1)return;
    const rate=wallpaper?24:context?12:30;
    const period=1000/rate;
    // Keep the fractional remainder on 60 Hz and 144 Hz displays.
    if(frame+.5<nextFrame){syncAnimation();return;}
    nextFrame=nextFrame && frame-nextFrame<period?nextFrame+period:frame+period;
    const interval=lastFrame?frame-lastFrame:0;
    if(renderer&&!adaptiveSoft){
      if(!rateStart){rateStart=frame;renderedFrames=0;}
      else {
        renderedFrames++;
        if(frame-rateStart>=3000){
          adaptiveSoft=renderedFrames*1000/(frame-rateStart)<rate*.8;
          rateStart=frame;renderedFrames=0;
        }
      }
    }
    const dt=lastFrame?Math.min(.15,interval/1000):.08;
    lastFrame=frame;sim+=dt;
    const motion=animatedEffects();
    const skyFrame=motion?Math.floor(sim*(wallpaper?.5:1.8)):-1;
    if(windowFrame!==skyFrame){
      windowFrame=skyFrame;
      windowTexture.refresh((...args)=>drawWindow(...args,lighting==='night',motion?Math.sin(sim*.075)*.26:0,!motion));
    }
    setCamera(dt);animateFigures(dt);
    if(!wallpaper || frame-lastTags>=95){placeTags();lastTags=frame;}
    if(renderer){
      updatePoseInstances();
      if(wallpaper && frame-lastShadow>=(activeWork()?125:500)){
        renderer.shadowMap.needsUpdate=true;lastShadow=frame;
      }
      renderer.render(scene,camera);
    }else if(context)renderSoftware();
    syncAnimation();
  }
  function resize() {
    const rect=container.getBoundingClientRect();
    width=Math.max(1,rect.width);height=Math.max(1,rect.height);
    pixelRatio=wallpaper?(devicePixelRatio||1):Math.min(devicePixelRatio||1,width<900||context?1.5:1.7);
    if(renderer){renderer.setPixelRatio(pixelRatio);renderer.setSize(width,height,false);}
    else {drawingCanvas.width=Math.round(width*pixelRatio);drawingCanvas.height=Math.round(height*pixelRatio);}
    lastFrame=0;
    syncAnimation();
  }
  let pointer=null,nextClickBlocked=false;
  drawingCanvas.style.cursor='grab';drawingCanvas.style.touchAction='pan-y';
  function setZoom(value) {
    if(!Number.isFinite(value))return zoom;
    const next=Math.round(clamp(value,.8,1.5)*100)/100;
    if(next!==zoom){zoom=next;zoomCallback?.(zoom);}
    return zoom;
  }
  function resetCamera(){
    yaw=initialYaw;pitch=initialPitch;orientationDirty=true;view='overview';focusedDesk=null;setZoom(1);
  }
  function down(e){
    if(!e.isPrimary||e.button!==0)return;
    nextClickBlocked=false;
    pointer={id:e.pointerId,x:e.clientX,y:e.clientY,yaw,pitch,dragged:false};
    drawingCanvas.setPointerCapture(e.pointerId);
  }
  function move(e){
    if(!pointer||pointer.id!==e.pointerId)return;
    const dx=e.clientX-pointer.x,dy=e.clientY-pointer.y;
    if(!pointer.dragged&&Math.abs(dx)+Math.abs(dy)<5)return;
    pointer.dragged=true;drawingCanvas.style.cursor='grabbing';
    yaw=clamp(pointer.yaw-dx*.006,.30,focusedDesk?1.45:1.13);
    pitch=clamp(pointer.pitch+dy*.004,.34,.78);orientationDirty=true;
  }
  function up(e){
    if(!pointer||e.pointerId!==pointer.id)return;
    nextClickBlocked=pointer.dragged;pointer=null;drawingCanvas.style.cursor='grab';
    if(drawingCanvas.hasPointerCapture(e.pointerId))drawingCanvas.releasePointerCapture(e.pointerId);
  }
  function wheel(e){
    if(!e.ctrlKey)return;e.preventDefault();
    const px=e.deltaY*(e.deltaMode===1?16:e.deltaMode===2?height:1);
    setZoom(zoom*Math.exp(-px*.0018));
  }
  const handlers={pointerdown:down,pointermove:move,pointerup:up,pointercancel:up,lostpointercapture:up,wheel};
  for(const [event,fn] of Object.entries(handlers))drawingCanvas.addEventListener(event,fn,event==='wheel'?{passive:false}:false);
  function clickScene(event) {
    if(nextClickBlocked){nextClickBlocked=false;return;}
    if(!callback)return;
    const box=drawingCanvas.getBoundingClientRect();
    raycaster.setFromCamera(new THREE.Vector2(2*(event.clientX-box.left)/width-1,1-2*(event.clientY-box.top)/height),camera);
    const screens=[...stationScreens.values()].map(station=>station.display.object);
    const hits=raycaster.intersectObjects([...people.filter(f=>f.root.visible).map(f=>f.root),...screens],true);
    if(!hits.length)return;
    for(const [id,station] of stationScreens){
      if(hits[0].object===station.display.object){callback(id);return;}
    }
    for(let obj=hits[0].object;obj;obj=obj.parent){
      const f=people.find(entry=>entry.root===obj);if(f){callback(f.id);break;}
    }
  }
  drawingCanvas.addEventListener('click',clickScene);
  const resizeObserver=new ResizeObserver(resize);resizeObserver.observe(container);
  const intersection=new IntersectionObserver(([entry])=>{visible=entry.isIntersecting;syncAnimation();});
  intersection.observe(container);
  document.addEventListener('visibilitychange',syncAnimation);
  resize();
  return {
    setGuests,
    setSummary(value,hint='数据暂不可用'){
      const key=JSON.stringify([value,hint]);
      if(key===summaryKey)return;
      summary=value;summaryKey=key;boardHint=hint;
      transfer=value?.handoff||null;
      const event=transfer?JSON.stringify(transfer):'';
      if(event!==transferKey){transferKey=event;transferStart=sim;}
      teamDisplay.refresh((c,w,h)=>drawTaskBoard(c,w,h,value,false,hint));
      rooms.updateBoard(value,hint);
    },
    setCodexEdit(edit){
      const signature=JSON.stringify(edit);
      if(signature!==editSignature){editSignature=signature;codexEdit=edit;}
    },
    setState(agents=[]) {
      life.setState(agents);
      figures.forEach(f=>{
        const agent=agents.find(a=>a.id===f.id),status=agent?.status||'idle';
        if(status==='done' && f.status!=='done')f.doneAt=sim;
        f.reported=!!agent?.updatedAt;f.status=status;f.activity=agent?.activity||'';f.collaborator=agent?.collaborator||null;
      });
    },
    setView(mode){
      if(!Object.hasOwn(cameraPresets,mode))return;
      if(focusedDesk){yaw=initialYaw;pitch=initialPitch;orientationDirty=true;focusedDesk=null;}
      view=mode;
    },
    focusDesk(id){
      const station=stationScreens.get(id);
      if(!station)return false;
      const {x,y,z}=station.gaze;
      focusedDesk={at:[x+.12,y-.57,z+.62],span:.18};
      yaw=1.21;pitch=.47;orientationDirty=true;instantCamera=true;
      return true;
    },
    setChatter(enabled){chatter=!!enabled;placeTags();},
    setEffects(mode){effects=mode==='soft'?'soft':'full';windowFrame=-2;},
    setZoom,getZoom:()=>zoom,onZoom(fn){zoomCallback=fn;},resetCamera,reset:resetCamera,
    setSelected(id){selected=id;},
    onSelect(fn){callback=fn;},
    setLighting(mode){
      lighting=mode==='night'?'night':'day';
      const night=lighting==='night';
      windowFrame=-2;
      hemi.color.set(night?'#a9c2ef':'#d5e6ff');hemi.intensity=night?1.35:1.75;
      sun.color.set(night?'#becaf7':'#ccddff');sun.intensity=night?1.65:2.05;
      fill.color.set(night?'#ba9bed':'#bea5fb');fill.intensity=night?.82:.88;
    },
    setMarket(data={}) {
      let time='';
      if(Number.isFinite(data.price)&&data.updatedAt){
        const stamp=new Date(data.updatedAt);if(Number.isFinite(stamp.getTime()))time=stamp.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'});
      }
      const quote=String(data.price)+'/'+time;
      if(quote!==lastMarket){tv.refresh((...args)=>drawMarket(...args,data.price,time));lastMarket=quote;}
    },
    dispose(){
      disposed=true;syncAnimation();resizeObserver.disconnect();intersection.disconnect();
      document.removeEventListener('visibilitychange',syncAnimation);
      for(const [event,fn] of Object.entries(handlers))drawingCanvas.removeEventListener(event,fn);
      drawingCanvas.removeEventListener('click',clickScene);people.forEach(f=>{f.tag.remove();f.leader.remove();f.bubble.remove()});drawingCanvas.remove();
      const unique=new Set([standardPalette,luminousPalette,sculptPalette,...materials.values(),...geometries.values(),...textures,
        sculptShell,hairLockLeft,hairLockRight]);
      for(const root of [scene,poseRig])root.traverse(obj=>{
        if(!obj.isMesh)return;
        unique.add(obj.geometry);unique.add(obj.material);
        if(obj.isInstancedMesh)unique.add(obj);
      });
      unique.forEach(obj=>obj.dispose());
      sun.shadow.dispose();renderer?.dispose();renderer?.forceContextLoss();
    }
  };
}
