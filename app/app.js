'use strict';
const $ = id => document.getElementById(id);
const labels = {queued:'En attente',preparing:'Chargement',running:'Calcul en cours',cancelling:'Annulation…',succeeded:'Terminé',failed:'Échec',cancelled:'Annulé',interrupted:'Interrompu'};
const busyStates = new Set(['queued','preparing','running','cancelling']);
let token = '', mode = 'edit', uploadId = null, uploadUrl = null, selectedId = null;
let state = null, selectedJob = null, polling = false, uploading = false, submitting = false, uploadRevision = 0;
let historySignature = '';
let photoDimensions = null;
let outputGeometry = QwenResolution.dimensions(1,1,1024), resolutionError = '';
const MAX_INPUT_SIDE = 4096;
const inputHint = 'Photos 1K, 2K, 4K et plus · préparation locale jusqu’à 4 096 px sur le côté long · 32 Mo max.';

function showError(message) { $('form-error').textContent = message; $('form-error').hidden = !message; }
function formatDuration(seconds) { const n=Math.max(0,Math.round(seconds||0)); return n<60 ? `${n} s` : `${Math.floor(n/60)} min ${String(n%60).padStart(2,'0')} s`; }
function formatDate(value) { return new Date(value).toLocaleString('fr-FR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}); }
function humanBytes(value) { return value>=1e9 ? `${(value/1e9).toFixed(2)} Go` : `${(value/1e6).toFixed(1)} Mo`; }

async function api(path, options={}) {
  const response = await fetch(path,{cache:'no-store',...options,headers:{...(options.method ? {'X-Qwen-Token':token} : {}),...options.headers}});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Erreur HTTP ${response.status}`);
  return data;
}
function post(path, data) { return api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}); }

function updateLaunch() {
  const blocked = !state?.engine.ready || !!state?.active_job || uploading || submitting || !!resolutionError;
  $('launch').disabled = blocked;
  $('launch').firstElementChild.textContent = uploading ? 'Préparation de la photo…' : submitting ? 'Démarrage…' : state?.active_job ? 'Un essai est en cours' : mode==='edit' ? 'Lancer la retouche' : 'Créer l’image';
}
function setMode(value) {
  mode = value;
  for (const option of ['edit','generate']) {
    $(`mode-${option}`).classList.toggle('active',mode===option);
    $(`mode-${option}`).setAttribute('aria-pressed',String(mode===option));
  }
  $('photo-area').hidden = mode!=='edit';
  $('generation-format').hidden = mode!=='generate';
  $('prompt').placeholder = mode==='edit' ? 'Remplace le fond par un jardin lumineux. Garde le sujet et ses détails inchangés.' : 'Une tasse en céramique verte sur une table en bois clair, lumière douce du matin, photographie réaliste.';
  showError(''); updateResolution();
}
$('mode-edit').addEventListener('click',()=>setMode('edit'));
$('mode-generate').addEventListener('click',()=>setMode('generate'));
$('example').addEventListener('click',()=>{
  $('prompt').value = mode==='edit' ? 'Change la couleur de l’objet principal en bleu profond. Conserve sa forme, sa texture, la lumière et le fond de la photo.' : 'Photographie réaliste d’une tasse en céramique rouge sur une table en bois clair, près d’une fenêtre. Lumière naturelle douce, fond beige uni, composition simple.';
  $('prompt').focus();
});
$('random-seed').addEventListener('click',()=>{$('seed').value='-1';});

function updateResolution() {
  const shortSide=Number($('resolution').value);
  const [rw,rh]=$('generation-ratio').value.split(':').map(Number);
  const source=mode==='edit' ? photoDimensions || {width:1,height:1} : {width:rw,height:rh};
  try {
    outputGeometry=QwenResolution.dimensions(source.width,source.height,shortSide);
    resolutionError='';
    $('output-size').textContent=`${outputGeometry.width.toLocaleString('fr-FR')} × ${outputGeometry.height.toLocaleString('fr-FR')} px`;
    $('ratio-info').textContent=mode==='edit' && !photoDimensions ? 'Les proportions suivront automatiquement votre photo.' : `${mode==='edit'?'Proportions de la photo conservées':'Format choisi conservé'} · côté court ${shortSide.toLocaleString('fr-FR')} px · ${(outputGeometry.width*outputGeometry.height/1e6).toLocaleString('fr-FR',{maximumFractionDigits:2})} Mpx. Arrondi au pixel le plus proche.`;
  } catch(error) { resolutionError=error.message; outputGeometry=null; $('output-size').textContent='Dimensions trop grandes'; }
  $('resolution-error').textContent=resolutionError; $('resolution-error').hidden=!resolutionError;
  const factor=(shortSide/1024)**2;
  $('resolution-cost').textContent=shortSide===1024 ? '1K : 1 024 px sur le côté le plus court. Comptez plusieurs minutes par essai ; la durée dépend aussi du format de la photo.' : `${shortSide/1024}K produit ${factor} fois plus de pixels que 1K au même format. Ces grandes résolutions demandent davantage de mémoire et de temps ; leur fonctionnement sur ce GPU n’a pas encore été validé.`;
  updateLaunch();
}
$('resolution').addEventListener('change',updateResolution);
$('generation-ratio').addEventListener('change',updateResolution);

async function preparePhoto(file) {
  if (!file) return;
  const revision = ++uploadRevision;
  photoDimensions = null;
  uploadId = null; uploading = true; showError(''); updateLaunch();
  updateResolution();
  try {
    if (!['image/png','image/jpeg','image/webp'].includes(file.type)) throw new Error('Choisissez une photo PNG, JPEG ou WebP.');
    if (file.size>32*1024*1024) throw new Error('La photo dépasse 32 Mo. Réduisez sa taille avant de l’ajouter.');
    const bitmap = await createImageBitmap(file,{imageOrientation:'from-image'});
    const originalWidth = bitmap.width, originalHeight = bitmap.height;
    const ratio = Math.min(1,MAX_INPUT_SIDE/Math.max(bitmap.width,bitmap.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1,Math.round(bitmap.width*ratio)); canvas.height = Math.max(1,Math.round(bitmap.height*ratio));
    canvas.getContext('2d').drawImage(bitmap,0,0,canvas.width,canvas.height); bitmap.close();
    const blob = await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));
    if (!blob) throw new Error('Impossible de convertir cette photo.');
    if (blob.size>32*1024*1024) throw new Error('La photo convertie dépasse 32 Mo. Utilisez une image plus petite.');
    if (revision!==uploadRevision) return;
    const result = await api('/api/uploads',{method:'POST',headers:{'Content-Type':'image/png'},body:blob});
    if (revision!==uploadRevision) return;
    uploadId = result.upload_id;
    photoDimensions = {width:originalWidth,height:originalHeight}; updateResolution();
    if (uploadUrl) URL.revokeObjectURL(uploadUrl);
    uploadUrl = URL.createObjectURL(blob);
    $('upload-preview').src = uploadUrl; $('upload-preview').hidden=false;
    $('upload-placeholder').hidden=true; $('replace-photo').hidden=false;
    $('upload-info').textContent=`${file.name} · original ${originalWidth} × ${originalHeight} → entrée ${result.width} × ${result.height} · PNG local · ${humanBytes(result.bytes)}`;
  } catch (error) {
    if (revision===uploadRevision) {
      $('upload-preview').hidden=true; $('upload-placeholder').hidden=false; $('replace-photo').hidden=true;
      $('upload-info').textContent=inputHint;
      showError(error.message || 'Impossible de lire cette photo.');
    }
  } finally { if (revision===uploadRevision) {uploading=false; updateLaunch();} }
}
$('photo').addEventListener('change',event=>preparePhoto(event.target.files[0]));
for (const eventName of ['dragenter','dragover']) $('dropzone').addEventListener(eventName,event=>{event.preventDefault();$('dropzone').classList.add('dragging');});
for (const eventName of ['dragleave','drop']) $('dropzone').addEventListener(eventName,event=>{event.preventDefault();$('dropzone').classList.remove('dragging');});
$('dropzone').addEventListener('drop',event=>preparePhoto(event.dataTransfer.files[0]));

$('job-form').addEventListener('submit',async event=>{
  event.preventDefault(); showError('');
  if (submitting || uploading) return;
  if (mode==='edit' && !uploadId) {showError('Ajoutez une photo de départ.');return;}
  updateResolution();
  if (!outputGeometry) {showError(resolutionError);return;}
  const data={mode,upload_id:uploadId,prompt:$('prompt').value,width:outputGeometry.engineWidth,height:outputGeometry.engineHeight,output_width:outputGeometry.width,output_height:outputGeometry.height,steps:Number($('steps').value),cfg:Number($('cfg').value),seed:Number($('seed').value)};
  submitting=true;updateLaunch();
  try {
    const job = await post('/api/jobs',data);
    selectedId=job.id;selectedJob=job;state.active_job=job.id;
    renderJob(job);$('logs-details').open=true;
    $('result-title').scrollIntoView({behavior:'smooth',block:'start'});
    await poll();
  } catch(error) {showError(error.message);}
  finally {submitting=false;updateLaunch();}
});
$('cancel').addEventListener('click',async()=>{
  if (!selectedId) return;
  $('cancel').disabled=true;
  try {renderJob(await post(`/api/jobs/${selectedId}/cancel`,{}));await poll();}
  catch(error){showError(error.message);}
  finally{$('cancel').disabled=false;}
});
$('reuse-settings').addEventListener('click',()=>{
  if (!selectedJob) return;
  setMode(selectedJob.mode);$('prompt').value=selectedJob.prompt;
  for (const name of ['steps','cfg','seed']) $(name).value=selectedJob[name];
  const ow=selectedJob.output_width || selectedJob.width, oh=selectedJob.output_height || selectedJob.height;
  const oldShort=Math.min(ow,oh);
  $('resolution').value=[1024,2048,3072,4096].includes(oldShort)?String(oldShort):'1024';
  if(selectedJob.mode==='generate') {
    let option=$('generation-ratio').querySelector('option[data-reused]');
    if(!option){option=document.createElement('option');option.dataset.reused='true';$('generation-ratio').append(option);}
    option.value=`${ow}:${oh}`;option.textContent='Format de cet essai';$('generation-ratio').value=option.value;
  }
  updateResolution();
  if (selectedJob.mode==='edit' && selectedJob.input_url) {
    fetch(selectedJob.input_url,{cache:'no-store'}).then(response=>{if(!response.ok)throw new Error('Photo de départ introuvable.');return response.blob();}).then(blob=>preparePhoto(new File([blob],'photo-depart.png',{type:blob.type}))).catch(error=>showError(error.message));
  }
  $('new-title').scrollIntoView({behavior:'smooth',block:'start'});
});

function renderState(data) {
  state=data;token=data.csrf_token;
  $('root-path').textContent=data.root;
  $('engine-badge').textContent=data.engine.ready ? 'Moteur prêt' : 'Installation à vérifier';
  $('engine-badge').className='badge'+(data.engine.ready?'':' error');
  const missing=data.engine.files.filter(file=>!file.present || !file.bytes).map(file=>file.name);
  $('installation-error').textContent=data.engine.error || (missing.length ? `Fichiers manquants ou vides : ${missing.join(', ')}. Vérifiez config.json et les téléchargements.` : '');
  $('installation-error').hidden=data.engine.ready;
  const files=$('model-files');files.replaceChildren();
  for(const file of data.engine.files){const item=document.createElement('li');item.textContent=`${file.present && file.bytes ? '✓' : '×'} ${file.filename}${file.present?` · ${humanBytes(file.bytes)}`:''}`;files.append(item);}
  if (!selectedId) selectedId=data.active_job || data.jobs[0]?.id || null;
  renderHistory(data.jobs);updateLaunch();
}

function renderHistory(jobs) {
  const signature=JSON.stringify(jobs.map(job=>[job.id,job.status,job.image_url]))+'|'+selectedId;
  if(signature===historySignature)return;
  historySignature=signature;
  const container=$('history');container.replaceChildren();
  if(!jobs.length){const empty=document.createElement('p');empty.className='hint';empty.textContent='Aucun essai pour le moment.';container.append(empty);return;}
  for(const job of jobs){
    const button=document.createElement('button');button.type='button';button.className='history-item'+(job.id===selectedId?' selected':'');
    button.setAttribute('aria-label',`${labels[job.status]||job.status} : ${job.prompt}`);
    let thumb;if(job.image_url){thumb=document.createElement('img');thumb.src=job.image_url;thumb.alt='';thumb.loading='lazy';}else{thumb=document.createElement('span');thumb.textContent=busyStates.has(job.status)?'◌':'✳';}thumb.className='history-thumb';
    const text=document.createElement('span');text.className='history-text';
    const prompt=document.createElement('span');prompt.className='history-prompt';prompt.textContent=job.prompt;
    const meta=document.createElement('span');meta.className='history-meta';meta.textContent=`${formatDate(job.created_at)} · ${labels[job.status]||job.status} · ${job.mode==='edit'?'Retouche':'Création'}`;
    text.append(prompt,meta);button.append(thumb,text);
    button.addEventListener('click',async()=>{selectedId=job.id;renderHistory(state.jobs);try{renderJob(await api(`/api/jobs/${job.id}`));}catch(error){showError(error.message);}});
    container.append(button);
  }
}

function setImage(imgId, linkId, url) {
  if(!url)return;
  if($(imgId).getAttribute('src')!==url) $(imgId).src=url;
  $(linkId).href=url;
}
function renderJob(job) {
  if(job.id!==selectedId)return;
  selectedJob=job;
  $('empty-result').hidden=true;$('job-result').hidden=false;
  $('job-status').textContent=labels[job.status]||job.status;
  $('job-status').className='badge'+(job.status==='failed'?' error':busyStates.has(job.status)?' pending':'');
  const busy=busyStates.has(job.status);
  $('elapsed').textContent=job.started_at ? `${formatDuration(busy ? (Date.now()-new Date(job.started_at))/1000 : job.elapsed_seconds)}${busy?' écoulées':''}` : '';
  $('running-info').hidden=!busy;
  $('cancel').hidden=job.status==='cancelling';
  $('running-label').textContent=job.status==='cancelling'?'Arrêt du moteur en cours…':job.status==='queued'||job.status==='preparing'?'Préparation et diagnostic NVIDIA…':'Chargement des modèles et calcul sur ce PC. Le journal ci-dessous indique l’étape en cours.';
  $('job-error').textContent=job.error || (job.status==='cancelled'?'Essai annulé. Le journal reste disponible.':'');
  $('job-error').hidden=!$('job-error').textContent;
  if(job.status==='failed')$('logs-details').open=true;
  $('source-figure').hidden=!job.input_url;$('output-figure').hidden=!job.image_url;
  $('image-comparison').hidden=!job.input_url&&!job.image_url;
  setImage('source-image','source-link',job.input_url);setImage('output-image','output-link',job.image_url);
  $('download-row').hidden=!job.image_url;
  if(job.image_url){$('download').href=job.image_url;$('download').download=`qwen-${job.id}.png`;}
  $('job-prompt').textContent=job.prompt;
  $('job-settings').textContent=`${job.output_width || job.width} × ${job.output_height || job.height} · ${job.steps} étapes · CFG ${job.cfg} · Graine ${job.seed}${job.exit_code!==null?` · Code de sortie ${job.exit_code}`:''}`;
  $('full-log').href=job.log_url;$('metadata-link').href=job.metadata_url;$('command-link').href=job.command_url;$('diagnostics-link').href=job.diagnostics_url;
  $('log-state').textContent=busy?'En direct':'Conservé';
  if(job.log_tail!==undefined){
    const log=$('log-tail');const bottom=log.scrollHeight-log.clientHeight-log.scrollTop<40;
    const clean=job.log_tail.replace(/\u001b\[[0-9;]*[A-Za-z]/g,'').replace(/\r\n?/g,'\n');
    if(log.textContent!==clean){log.textContent=clean || 'En attente du moteur…';if(bottom)log.scrollTop=log.scrollHeight;}
  }
  $('run-folder').textContent=`Dossier de l’essai : ${state?.root||''}\\data\\results\\${job.id}`;
}

async function poll(){
  if(polling)return;
  polling=true;
  try{
    renderState(await api('/api/state'));
    $('connection-error').hidden=true;
    if(selectedId)renderJob(await api(`/api/jobs/${selectedId}`));
  }catch(error){
    $('connection-error').textContent=`Connexion à l’interface interrompue. Relancez Lancer.ps1 si nécessaire. ${error.message}`;
    $('connection-error').hidden=false;$('engine-badge').textContent='Hors connexion';$('engine-badge').className='badge error';$('launch').disabled=true;
  }finally{polling=false;}
}
updateResolution();poll();setInterval(poll,1800);
