const $ = id => document.getElementById(id);
let token = '', lastJob = null, objectURL = null, presets = [];
async function request(path, options = {}) {
  const response = await fetch(path, {...options, headers: {Authorization: `Bearer ${token}`, ...options.headers}});
  if (!response.ok) throw new Error(`${response.status}: ${(await response.text()).slice(0,400)}`);
  return response;
}
function showError(error) { $('status').textContent = error.message; }
$('connect').onclick = async () => {
  token = $('key').value.trim();
  try {
    const info = await (await request('/v1/capabilities')).json();
    $('mode').textContent = info.backend === 'preview' ? 'PIPELINE TEST MODE: synthetic test video only. No AI model is loaded.' : 'Wan mode: queued video generation. GPU worker readiness is checked separately.';
    presets = await (await request('/v1/stages')).json();
    $('stage').replaceChildren(new Option('Custom scene',''), ...presets.map(s => new Option(`${s.game} / ${s.title}`,s.id)));
    $('generate').disabled = false;
    $('status').textContent = 'Connected. Choose a stage or write a scene.';
  } catch(error) { showError(error); }
};
$('stage').onchange = () => {
  const stage = presets.find(s => s.id === $('stage').value);
  $('objective').textContent = stage ? stage.objective : '';
  if (stage) $('prompt').value = stage.scene;
};
$('continue').onchange = () => { $('image').disabled = $('continue').checked; };
$('jobform').onsubmit = async event => {
  event.preventDefault(); $('generate').disabled = true;
  try {
    let imageID = null;
    const useParent = $('continue').checked && lastJob;
    if (!useParent && $('image').files.length) {
      const form = new FormData(); form.append('image', $('image').files[0]);
      imageID = (await (await request('/v1/assets', {method:'POST',body:form})).json()).image_id;
    }
    const body = {prompt:$('prompt').value, character:$('character').value, stage_id:$('stage').value || null,
      image_id:imageID, parent_job_id:useParent ? lastJob : null, action:$('action').value, camera:$('camera').value,
      frames:Number($('frames').value), seed:Number($('seed').value)};
    let job = await (await request('/v1/jobs', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();
    while (['queued','running'].includes(job.state)) {
      $('status').textContent = `${job.state === 'queued' ? 'Queued — waiting for a worker' : 'Rendering'} · ${job.id}`;
      await new Promise(resolve => setTimeout(resolve,2000));
      job = await (await request(`/v1/jobs/${job.id}`)).json();
    }
    if (job.state !== 'succeeded') throw new Error(`Generation failed: ${job.error}. Check the GPU worker log.`);
    const blob = await (await request(`/v1/jobs/${job.id}/video`)).blob();
    if (objectURL) URL.revokeObjectURL(objectURL);
    objectURL = URL.createObjectURL(blob); $('video').src = objectURL; $('video').hidden = false;
    $('download').href = objectURL; $('download').download = `${job.id}.mp4`; $('download').hidden = false;
    lastJob = job.id; $('continue').disabled = false;
    $('status').textContent = job.result.synthetic_preview ? 'Synthetic pipeline test completed — this is not AI-generated video.' : 'Clip ready.';
    $('details').textContent = JSON.stringify(job.result,null,2);
  } catch(error) { showError(error); }
  finally { $('generate').disabled = false; }
};
