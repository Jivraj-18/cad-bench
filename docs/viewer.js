import * as THREE from 'three';
import {OrbitControls} from './lib/OrbitControls.js';

const json = async url => {
  const response = await fetch(url);
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

async function horizontal(host,config) {
  const models=await Promise.all(config.models.map(async item=>({
    ...item, data:await json(item.url),
    transform:item.alignment ? inverseAlignment(await json(item.alignment)) : null,
  })));
  const scenes=models.map(item=>scene(item.data,item.transform));
  const box=new THREE.Box3(); scenes.forEach(s=>box.union(new THREE.Box3().setFromObject(s)));
  const center=box.getCenter(new THREE.Vector3()), size=box.getSize(new THREE.Vector3());
  const radius=Math.max(size.x,size.y,size.z)*.65;
  const panels=host.querySelector('.viewer-panels');
  for (const [i,item] of models.entries()) {
    const panel=document.createElement('div');panel.className='viewer-pane';
    const title=document.createElement('h4');title.textContent=item.label;panel.append(title);
    if(item.stats){
      const stats=document.createElement('p');stats.className='pane-stats';
      stats.textContent=`Score ${item.stats.score} · ${item.stats.elapsed} · ${item.stats.cost}`;panel.append(stats);
    }else{
      const stats=document.createElement('p');stats.className='pane-stats';stats.textContent='Ground-truth CAD from the dataset';panel.append(stats);
    }
    const toolbar=document.createElement('div');toolbar.className='pane-toolbar';
    const select=document.createElement('select');select.setAttribute('aria-label',item.shortLabel+' CAD revision');
    const options=[{name:item.reference?'Ground truth':'Final CAD',data:item.data},
      ...(item.revisions||[]).map((r,n)=>({name:`Saved revision ${n+1}`,url:r.url})),
      ...(item.data.stages||[]).filter(s=>s.vertices?.length&&s.triangles?.length)
        .map(s=>({name:'Feature: '+(s.label||s.name),data:s}))];
    options.forEach((o,n)=>{const node=document.createElement('option');node.value=n;node.textContent=o.name;select.append(node);});
    const reset=document.createElement('button');reset.type='button';reset.textContent='Reset';
    reset.setAttribute('aria-label','Reset '+item.shortLabel+' view');
    toolbar.append(select,reset);panel.append(toolbar);
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
    select.addEventListener('change',async()=>{
      try {
        const choice=options[Number(select.value)];if(!choice.data)choice.data=await json(choice.url);
        scenes[i]=scene(choice.data,item.transform);draw();
      }catch(error){host.querySelector('.viewer-status').textContent=error.message;host.querySelector('.viewer-status').hidden=false;}
    });
    controls.addEventListener('change',draw);new ResizeObserver(draw).observe(canvas);
    reset.addEventListener('click',()=>{controls.reset();draw();});draw();
  }
  host.querySelector('.viewer-status').hidden=true;
  host.querySelector('.viewer-caption').textContent='Each panel rotates and zooms independently. All start with the same orientation and scale.';
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
