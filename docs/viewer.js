import * as THREE from 'three';
import {OrbitControls} from './lib/OrbitControls.js';

// One fixed D3 scale across official scores; error cells declare their own scale.
for (const cell of document.querySelectorAll('[data-quality]')) {
  const q=Math.max(0,Math.min(1,Number(cell.dataset.quality)));
  cell.style.backgroundColor=d3.interpolateRdYlGn(.12+.76*q);
}

const json = async url => {
  const response = await fetch(url,{cache:'no-cache'});
  if (!response.ok) throw new Error(`Could not load CAD data (${response.status})`);
  return response.json();
};

function geometry(data, alignment) {
  let vertices = data.vertices;
  if (alignment) {
    const r = alignment.rotation, t = alignment.translation;
    vertices = vertices.map(v => [0, 1, 2].map(j =>
      v[0] * r[0][j] + v[1] * r[1][j] + v[2] * r[2][j] + t[j]));
  }
  const result = new THREE.BufferGeometry();
  result.setAttribute('position', new THREE.Float32BufferAttribute(vertices.flat(), 3));
  result.setIndex(data.triangles.flat());
  result.computeVertexNormals();
  result.computeBoundingBox();
  return result;
}

function scene(model, alignment) {
  const result = new THREE.Scene();
  result.background = new THREE.Color('#f8f8f5');
  result.add(new THREE.HemisphereLight(0xffffff, 0x667080, 2.5));
  const light = new THREE.DirectionalLight(0xffffff, 3);
  light.position.set(-1, -2, 3); result.add(light);
  const mesh = new THREE.Mesh(geometry(model, alignment), new THREE.MeshStandardMaterial({
    color: '#98a9b5', roughness: .72, metalness: .08,
    side: THREE.DoubleSide, flatShading: true,
  }));
  result.add(mesh);
  const edges = new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry, 28),
    new THREE.LineBasicMaterial({color: '#34434d', transparent: true, opacity: .4}));
  result.add(edges);
  return result;
}

function inverseAlignment(a) {
  const r=a.rotation, t=a.translation;
  return {rotation:[0,1,2].map(i=>[0,1,2].map(j=>r[j][i])),
    translation:[0,1,2].map(j=>-(t[0]*r[j][0]+t[1]*r[j][1]+t[2]*r[j][2]))};
}

function differences(data,reference){
  const result=scene(reference);
  for(const object of result.children){
    if(object.isMesh){object.material.transparent=true;object.material.opacity=.12;object.material.depthWrite=false;}
    if(object.isLineSegments)object.material.opacity=.12;
  }
  for(const [kind,color] of [['missing','#cf3838'],['extra','#e6a020']]){
    const region=data.overlap.regions[kind];if(!region.vertices.length)continue;
    result.add(new THREE.Mesh(geometry(region),new THREE.MeshStandardMaterial({
      color,side:THREE.DoubleSide,flatShading:true,roughness:.8,
    })));
  }
  return result;
}

function disposeScene(value){
  value.traverse(object=>{
    object.geometry?.dispose();
    if(Array.isArray(object.material))object.material.forEach(m=>m.dispose());
    else object.material?.dispose();
  });
}

async function horizontal(host,config) {
  const models=await Promise.all(config.models.map(async item=>{
    const diagnostic=item.comparison?await json(item.comparison):null;
    return {...item,data:await json(item.url),diagnostic,
      transform:diagnostic?diagnostic.overlap.candidate_to_reference:
        item.alignment?inverseAlignment(await json(item.alignment)):null};
  }));
  const groundTruth=models.find(m=>m.reference).data;
  const scenes=models.map(item=>scene(item.data,item.transform));
  const box=new THREE.Box3(); scenes.forEach(s=>box.union(new THREE.Box3().setFromObject(s)));
  const center=box.getCenter(new THREE.Vector3()), size=box.getSize(new THREE.Vector3());
  const radius=Math.max(size.x,size.y,size.z)*.65;
  const panels=host.querySelector('.viewer-panels');
  const sync=host.querySelector('.sync-views');
  const peers=[];let copying=false,lastActive=null;
  function synchronize(source){
    if(copying||!sync.checked)return;
    copying=true;
    for(const peer of peers){
      if(peer===source)continue;
      peer.camera.position.copy(source.camera.position);
      peer.camera.up.copy(source.camera.up);
      peer.camera.zoom=source.camera.zoom;
      peer.controls.target.copy(source.controls.target);
      peer.controls.update();peer.draw();
    }
    copying=false;
  }
  sync.addEventListener('change',()=>{
    if(sync.checked)synchronize(lastActive||peers[0]);
    host.querySelector('.viewer-caption').textContent=sync.checked?
      'Views linked: rotation, zoom and pan in any panel update all three. Construction playback stays independent.':
      'Views independent: rotate, zoom, pan and play construction separately in each panel.';
  });
  for (const [i,item] of models.entries()) {
    const panel=document.createElement('div');panel.className='viewer-pane';
    panel.dataset.model=item.reference?'reference':item.shortLabel.toLowerCase();
    if(new URLSearchParams(location.search).get('model')===panel.dataset.model){
      panel.classList.add('selected-model');
    }
    const title=document.createElement('h4');title.textContent=item.label;panel.append(title);
    if(item.stats){
      const stats=document.createElement('p');stats.className='pane-stats';
      stats.textContent=`Effort: ${item.stats.effort} · Score ${item.stats.score} · ${item.stats.elapsed} · ${item.stats.cost}`;panel.append(stats);
    }else{
      const stats=document.createElement('p');stats.className='pane-stats';stats.textContent='Ground-truth CAD from the dataset';panel.append(stats);
    }
    const toolbar=document.createElement('div');toolbar.className='pane-toolbar';
    const select=document.createElement('select');select.setAttribute('aria-label',item.shortLabel+' CAD revision');
    const options=[{name:item.reference?'Ground truth':'Final CAD',data:item.data},
      ...(item.diagnostic?[{name:'Missing / extra material',difference:true}]:[]),
      ...(item.revisions||[]).map((r,n)=>({name:`Saved revision ${n+1}`,url:r.url})),
      ...(item.data.stages||[]).filter(s=>s.vertices?.length&&s.triangles?.length)
        .map(s=>({name:'Feature: '+(s.label||s.name),data:s}))];
    options.forEach((o,n)=>{const node=document.createElement('option');node.value=n;node.textContent=o.name;select.append(node);});
    const reset=document.createElement('button');reset.type='button';reset.textContent='Reset';
    reset.setAttribute('aria-label','Reset '+item.shortLabel+' view');
    const play=document.createElement('button');play.type='button';play.textContent='▶ Play';
    play.setAttribute('aria-label','Play '+item.shortLabel+' construction');
    const steps=options.map((o,n)=>o.name.startsWith('Feature:')?n:-1).filter(n=>n>=0);
    play.disabled=!steps.length;
    const stepStatus=document.createElement('p');stepStatus.className='replay-status';
    stepStatus.textContent='Feature-tree replay · not a recording of the agent’s edits';
    toolbar.append(select,play,reset);panel.append(toolbar,stepStatus);
    const canvas=document.createElement('canvas');canvas.setAttribute('aria-label',item.label+' interactive CAD');
    panel.append(canvas);panels.append(panel);
    const renderer=new THREE.WebGLRenderer({canvas,antialias:true});
    renderer.setPixelRatio(Math.min(window.devicePixelRatio,2));
    const camera=new THREE.OrthographicCamera(-radius,radius,radius,-radius,.01,radius*30);
    camera.up.set(0,0,1);camera.position.copy(center).add(new THREE.Vector3(1.6,-2.4,1.6).multiplyScalar(radius));
    camera.lookAt(center);
    const controls=new OrbitControls(camera,canvas);controls.target.copy(center);
    controls.minZoom=.1;controls.maxZoom=20;controls.update();controls.saveState();
    function draw(){
      const width=canvas.clientWidth,height=canvas.clientHeight;
      renderer.setSize(width,height,false);
      camera.left=-radius*Math.max(1,width/height);camera.right=-camera.left;
      camera.top=radius*Math.max(1,height/width);camera.bottom=-camera.top;
      camera.updateProjectionMatrix();renderer.render(scenes[i],camera);
    }
    const peer={camera,controls,draw};peers.push(peer);
    let timer=null,playing=false,loadVersion=0,resumeAt=0;
    function stop(reset=true){
      if(reset)resumeAt=0;
      playing=false;clearTimeout(timer);play.textContent='▶ Play';
      play.setAttribute('aria-label','Play '+item.shortLabel+' construction');
    }
    async function showChoice(){
      const version=++loadVersion;
      try {
        const choice=options[Number(select.value)];
        let next;
        if(choice.difference)next=differences(item.diagnostic,groundTruth);
        else{if(!choice.data)choice.data=await json(choice.url);next=scene(choice.data,item.transform);}
        if(version!==loadVersion){disposeScene(next);return;}
        disposeScene(scenes[i]);scenes[i]=next;
        const index=steps.indexOf(Number(select.value));
        stepStatus.textContent=index>=0?`Step ${index+1} of ${steps.length} · ${choice.name.slice(9)}`:
          choice.difference?'Red: missing reference material · Gold: extra candidate material':
          choice.name.startsWith('Saved revision')?'Actual CAD revision saved during the run':
          'Feature-tree replay · not a recording of the agent’s edits';
        draw();
      }catch(error){stop();host.querySelector('.viewer-status').textContent=error.message;host.querySelector('.viewer-status').hidden=false;}
    }
    async function advance(n){
      if(!playing)return;
      if(n>=steps.length){stop();stepStatus.textContent+=' · Replay complete';return;}
      select.value=steps[n];await showChoice();
      resumeAt=n+1;
      if(playing)timer=setTimeout(()=>advance(n+1),1100);
    }
    play.addEventListener('click',()=>{
      if(playing){stop(false);play.textContent='▶ Resume';play.setAttribute('aria-label','Resume '+item.shortLabel+' construction');return;}
      playing=true;play.textContent='Ⅱ Pause';
      play.setAttribute('aria-label','Pause '+item.shortLabel+' construction');advance(resumeAt);
    });
    select.addEventListener('change',()=>{stop();showChoice();});
    controls.addEventListener('change',()=>{draw();if(!copying){lastActive=peer;synchronize(peer);}});
    new ResizeObserver(draw).observe(canvas);
    reset.addEventListener('click',()=>{controls.reset();draw();synchronize(peer);});draw();
  }
  host.querySelector('.viewer-status').hidden=true;
  host.querySelector('.viewer-caption').textContent='Views independent: rotate, zoom, pan and play construction separately in each panel.';
  host.dataset.ready='true';

}

async function mount(host) {
  const status = host.querySelector('.viewer-status');
  try {
    const config = await json(host.dataset.viewer);
    if(config.models){await horizontal(host,config);return;}
    const [reference, candidate, alignment] = await Promise.all([
      json(config.reference), json(config.candidate), json(config.alignment),
    ]);
    const choices = host.querySelector('select');
    const options = [
      {name: 'Compare reference and final CAD', mode: 'compare'},
      {name: 'Final candidate', model: candidate},
      {name: 'Dataset reference', model: reference, alignment},
      ...(config.revisions || []).map((r, i) => ({name: `Saved revision ${i + 1}`, url: r.url, observed: r.observed_at})),
      ...(candidate.stages || []).filter(s => s.vertices?.length && s.triangles?.length)
        .map(s => ({name: `Feature: ${s.label || s.name}`, model: s, feature: true})),
    ];
    for (const [i, option] of options.entries()) {
      const node = document.createElement('option'); node.value = i; node.textContent = option.name;
      choices.append(node);
    }
    const canvas = host.querySelector('canvas');
    const renderer = new THREE.WebGLRenderer({canvas, antialias: true, alpha: false});
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setScissorTest(true);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    const center = new THREE.Vector3(...alignment.shared_limits.map(([lo, hi]) => (lo + hi) / 2));
    const radius = (alignment.shared_limits[0][1] - alignment.shared_limits[0][0]) / 2;
    const camera = new THREE.OrthographicCamera(-radius, radius, radius, -radius, .01, radius * 30);
    camera.up.set(0, 0, 1);
    camera.position.copy(center).add(new THREE.Vector3(1.6, -2.4, 1.6).multiplyScalar(radius));
    camera.lookAt(center);
    const controls = new OrbitControls(camera, canvas);
    controls.target.copy(center); controls.minZoom = .1; controls.maxZoom = 20;
    controls.update(); controls.saveState();
    const referenceScene = scene(reference, alignment);
    const finalScene = scene(candidate);
    let active = finalScene, compare = true;
    const labels = host.querySelector('.viewer-labels');
    const description = host.querySelector('.viewer-caption');
    function draw() {
      const width = canvas.clientWidth, height = canvas.clientHeight;
      renderer.setSize(width, height, false);
      const pane = compare ? width / 2 : width;
      camera.left = -radius * pane / height; camera.right = radius * pane / height;
      camera.top = radius; camera.bottom = -radius; camera.updateProjectionMatrix();
      renderer.setViewport(0, 0, pane, height); renderer.setScissor(0, 0, pane, height);
      renderer.render(compare ? referenceScene : active, camera);
      if (compare) {
        renderer.setViewport(pane, 0, pane, height); renderer.setScissor(pane, 0, pane, height);
        renderer.render(finalScene, camera);
      }
    }
    choices.addEventListener('change', async () => {
      const option = options[Number(choices.value)];
      try {
        compare = option.mode === 'compare';
        if (!compare) {
          if (!option.model) option.model = await json(option.url);
          if (!option.scene) option.scene = scene(option.model, option.alignment);
          active = option.scene;
        }
        labels.hidden = !compare;
        description.textContent = option.observed ? `Intermediate CAD saved during the run · ${option.observed}` :
          option.feature ? 'Construction step from the final feature tree; not a saved intermediate revision.' :
          compare ? 'Reference and final candidate share one camera and scale. Rotate either view to inspect both.' : option.name;
        draw();
      } catch (error) { status.textContent = error.message; status.hidden = false; }
    });
    controls.addEventListener('change', draw);
    host.querySelector('.viewer-reset').addEventListener('click', () => {controls.reset(); draw();});
    new ResizeObserver(draw).observe(canvas);
    status.hidden = true; choices.disabled = false;
    description.textContent = 'Reference and final candidate share one camera and scale. Rotate either view to inspect both.';
    host.dataset.ready = 'true';
    draw();
  } catch (error) {
    status.textContent = `${error.message}. The CAD download remains available below.`;
    host.dataset.ready = 'error';
  }
}

for (const host of document.querySelectorAll('[data-viewer]')) mount(host);
