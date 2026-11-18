import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createOfficeLife} from './public/life.js';
import {buildRooms} from './public/rooms.js';

const crew = [
  ['carbon', -4.9, 2.6], ['astra', -4.9, -1.3], ['dot', -.35, 2.6],
  ['argon', -.35, -1.3], ['hydrogen', 4.2, 2.6], ['codex', -1.6, -5.2],
];
const homes = Object.fromEntries(crew.map(([id,x,z])=>[id,{x:x-.35,z:z+1.30,yaw:Math.PI}]));
const meeting = [[3.33,-3.47], [5.03,-3.47], [3.33,-.59], [5.03,-.59], [6.33,-2.03], [2.03,-2.03]];
const transform = () => ({position:{set(){}},rotation:{set(){}},scale:{set(){}}});
const {anchors:locations} = buildRooms({
  parent:transform(),animated:transform(),group:transform,box:transform,
  cyl:transform,mesh:transform,luminous:()=>null,floorPad:transform,
  textureSurface:()=>({object:transform(),refresh(){}}),
});
const distance = (a,b) => Math.hypot(a.x-b.x,a.z-b.z);
const dt = 1/60;

function setup() {
  const life=createOfficeLife({homes,locations});
  const poses=new Set();
  let previous=null,minGap=Infinity;
  function frames(seconds, options={}) {
    let rows;
    for(let i=0;i<Math.max(1,Math.round(seconds/dt));i++){
      rows=life.tick(dt,options);
      for(const [index,row] of rows.entries()){
        poses.add(row.pose);
        if(previous&&!options.reducedMotion)assert.ok(distance(row,previous[index])<.064);
        for(const other of rows.slice(index+1))minGap=Math.min(minGap,distance(row,other));
        assert.ok(row.x>=-10.21&&row.x<=10.49&&row.z>=-6.16&&row.z<=6.51);
        if(!row.walking)continue;
        // Check desk and chair clearance against the actual world positions.
        for(const [id,x,z] of crew){
          assert.ok(Math.abs(row.x-x)>=1.515+.48||Math.abs(row.z-z)>=.68+.48);
          assert.ok(Math.abs(row.x-homes[id].x)>=.45+.48||Math.abs(row.z-homes[id].z)>=.48+.48);
        }
      }
      previous=rows.map(row=>({...row}));
    }
    assert.ok(minGap>=1.02-1e-5);
    return rows;
  }
  function setState(status,partners={}){
    life.setState(crew.map(([id])=>({id,status,collaborator:partners[id]})));
  }
  return {frames,setState,poses};
}
function allInSeat(rows,partners={}){
  for(const [i,row] of rows.entries()){
    const peer=partners[row.id]??Object.keys(partners).find(id=>partners[id]===row.id);
    const [x,z]=peer?meeting[i]:[homes[row.id].x,homes[row.id].z];
    assert.equal(row.pose,peer?'meeting':'type',row.id);
    assert.ok(row.seated&&!row.walking&&distance(row,{x,z})<1e-6,row.id);
    if(!peer)assert.ok(Math.cos(row.angle-Math.PI)>.99);
  }
}

test('six coworkers walk around furniture, settle at desks and meetings, and reroute mid-task',()=>{
  const {frames,setState,poses}=setup();
  frames(10);
  setState('coding');
  allInSeat(frames(18));
  const first={carbon:'astra',dot:'hydrogen',argon:'codex'};
  setState('coding',first);
  allInSeat(frames(17),first);
  const second={carbon:'argon',astra:'hydrogen'};
  setState('coding',second);
  frames(1.15);
  const interrupted={dot:'argon',hydrogen:'carbon'};
  setState('coding',interrupted);
  allInSeat(frames(20),interrupted);
  setState('idle');
  frames(120);
  for(const pose of ['walk','coffee','game','lounge','read','chat'])assert.ok(poses.has(pose),pose);
});

test('reduced motion keeps ambient activity still and still responds to real status',()=>{
  const {frames,setState}=setup();
  const opts={reducedMotion:true};
  const idle=frames(30,opts);
  assert.ok(idle.every(row=>row.seated&&!row.walking&&row.pose==='idle'&&distance(row,homes[row.id])<1e-6));
  setState('coding');
  allInSeat(frames(0,opts));
  const partners={carbon:'astra',dot:'hydrogen'};
  setState('coding',partners);
  allInSeat(frames(0,opts),partners);
  setState('idle');
  assert.ok(frames(0,opts).every(row=>row.seated&&row.pose==='idle'&&distance(row,homes[row.id])<1e-6));
});
