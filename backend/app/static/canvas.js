const state = {
  projects: [],
  project: null,
  view: {x: 80, y: 80, zoom: 1},
  selectedNodeId: null,
  pan: null,
  drag: null,
  saveTimers: new Map(),
  pollTimers: new Map(),
  provider: 'mock',
  providerStatuses: {},
  pasteTarget: null,
  noteLinkSourceId: null,
  edgeStyle: 'curved',
  lastCanvasPointer: null,
  currentUser: null,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const viewport = $('#canvasViewport');
const world = $('#world');
const nodesLayer = $('#nodesLayer');
const edgesSvg = $('#edges');
const emptyCanvas = $('#emptyCanvas');
const saveState = $('#saveState');

function storageGet(key) { try { return localStorage.getItem(key); } catch (_) { return null; } }
function storageSet(key, value) { try { localStorage.setItem(key, value); } catch (_) {} }

async function api(url, options = {}) {
  const response = await fetch(url, options);
  if (response.status === 401) { location.href = '/login'; throw new Error('Требуется вход'); }
  if (response.status === 204) return null;
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || body.message || `Ошибка ${response.status}`);
  return body;
}

async function loadMe() {
  state.currentUser = await api('/api/auth/me');
  const initial = (state.currentUser.display_name || state.currentUser.email || '?').trim().charAt(0).toUpperCase();
  $('#profileButton').textContent = initial || '?';
  $('#profileButton').title = `${state.currentUser.display_name || state.currentUser.email} · ${state.currentUser.role}`;
  const owner = state.currentUser.role === 'owner';
  $('#usersButton').style.display = owner ? '' : 'none';
  $('#connectionsButton').style.display = owner ? '' : 'none';
  if (state.currentUser.role === 'viewer') {
    ['#addPhotoButton','#addPromptButton','#addNoteButton','#emptyAddPhoto','#emptyAddPrompt','#diagnosticsButton'].forEach(id => { const el=$(id); if(el) el.style.display='none'; });
  }
}

function toast(message, type = '') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = message;
  $('#toastStack').appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

function setSaveStatus(mode = 'saved', text = '') {
  saveState.className = `save-state ${mode === 'saved' ? '' : mode}`;
  saveState.innerHTML = `<span></span> ${text || (mode === 'saving' ? 'Сохранение…' : mode === 'error' ? 'Ошибка' : 'Сохранено')}`;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
}

function pluralPhotos(number) {
  const n = Math.abs(number) % 100;
  const n1 = n % 10;
  if (n > 10 && n < 20) return `${number} фото`;
  if (n1 === 1) return `${number} фото`;
  return `${number} фото`;
}

function formatBytes(bytes) {
  if (!bytes) return '0 Б';
  const units = ['Б', 'КБ', 'МБ', 'ГБ'];
  const index = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${(bytes / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}

function projectPhotoNodes() { return (state.project?.nodes || []).filter(node => node.node_type === 'photo'); }
function projectPromptNodes() { return (state.project?.nodes || []).filter(node => node.node_type === 'prompt'); }
function projectNoteNodes() { return (state.project?.nodes || []).filter(node => node.node_type === 'note'); }
function hasPhotoAsset(node) { return node.assets?.some(asset => asset.kind === 'customer_photo'); }
function referenceAsset(node) { return node.assets?.find(asset => asset.kind === 'reference'); }
function uploadedPhotoCount() { return projectPhotoNodes().filter(hasPhotoAsset).length; }
function providerLabel(provider) { return provider === 'gemini' ? 'Gemini' : provider === 'openai' ? 'ChatGPT' : 'MOCK'; }
function defaultModel(provider) { return provider === 'gemini' ? 'gemini-3.1-flash-image' : 'gpt-image-2'; }

async function loadProviderStatuses() {
  try {
    const health = await api('/health');
    state.provider = health.provider || 'mock';
    if (state.currentUser?.role === 'owner' || state.currentUser?.role === 'operator') {
      const providers = await api('/api/admin/providers');
      state.providerStatuses = Object.fromEntries(providers.map(item => [item.provider, item]));
    }
    renderProviderPill();
  } catch (_) { renderProviderPill(); }
}

function renderProviderPill() {
  const pill = $('#providerPill');
  const connected = Object.values(state.providerStatuses).filter(item => item.is_connected);
  pill.classList.toggle('openai', connected.length > 0);
  pill.innerHTML = connected.length
    ? `<span></span>${connected.length} API`
    : `<span></span>MOCK`;
}

async function loadProjects() {
  state.projects = await api('/api/projects');
  renderProjectList();
  const queryId = new URLSearchParams(location.search).get('project');
  const storedId = storageGet('neurophoto_current_project');
  const initialId = [queryId, storedId].find(id => state.projects.some(project => project.id === id));
  if (initialId) await openProject(initialId, false);
  else if (state.projects.length) await openProject(state.projects[0].id, false);
  else openProjectModal();
}

async function openProject(projectId, closeDrawer = true) {
  clearAllPolls();
  state.noteLinkSourceId = null;
  state.project = await api(`/api/projects/${projectId}`);
  state.view = {
    x: Number(state.project.viewport?.x ?? 80),
    y: Number(state.project.viewport?.y ?? 80),
    zoom: Number(state.project.viewport?.zoom ?? 1),
  };
  state.edgeStyle = state.project.viewport?.edge_style === 'orthogonal' ? 'orthogonal' : 'curved';
  updateEdgeStyleUI();
  storageSet('neurophoto_current_project', projectId);
  const url = new URL(location.href);
  url.searchParams.set('project', projectId);
  history.replaceState({}, '', url);
  $('#projectTitle').value = state.project.title;
  $('#projectTitle').readOnly = false;
  renderCanvas();
  renderProjectList();
  closeSearchResults();
  if (closeDrawer) closeProjectsDrawer();
}

function renderProjectList() {
  const list = $('#projectsList');
  if (!state.projects.length) {
    list.innerHTML = '<div class="project-card"><div><h3>Пока нет проектов</h3><p>Создайте первое рабочее пространство.</p></div></div>';
    return;
  }
  list.innerHTML = '';
  state.projects.forEach(project => {
    const card = document.createElement('article');
    card.className = `project-card ${state.project?.id === project.id ? 'active' : ''}`;
    card.dataset.projectId = project.id;
    card.innerHTML = `
      <div><h3>${escapeHtml(project.title)}</h3><p>${escapeHtml(project.description || project.theme || 'Без описания')}</p></div>
      <button class="project-delete" type="button" title="Удалить проект">×</button>
      <div class="project-card-meta"><span>${project.photo_count} фото-блоков</span><span>${project.prompt_count} промптов</span><span>${new Date(project.updated_at).toLocaleDateString('ru-RU')}</span></div>`;
    card.addEventListener('click', event => {
      if (event.target.closest('.project-delete')) return;
      openProject(project.id).catch(error => toast(error.message, 'error'));
    });
    $('.project-delete', card).addEventListener('click', async event => {
      event.stopPropagation();
      if (!confirm(`Удалить проект «${project.title}» вместе со всеми файлами?`)) return;
      try {
        await api(`/api/projects/${project.id}`, {method: 'DELETE'});
        if (state.project?.id === project.id) state.project = null;
        await loadProjectsFresh();
        toast('Проект удалён', 'success');
      } catch (error) { toast(error.message, 'error'); }
    });
    list.appendChild(card);
  });
}

async function loadProjectsFresh() {
  state.projects = await api('/api/projects');
  renderProjectList();
  if (!state.project && state.projects.length) await openProject(state.projects[0].id, false);
  if (!state.projects.length) {
    nodesLayer.innerHTML = '';
    edgesSvg.innerHTML = '';
    emptyCanvas.classList.remove('hidden');
    $('#projectTitle').value = 'Создайте проект';
    openProjectModal();
  }
}

function renderCanvas() {
  applyView();
  renderNodes();
  emptyCanvas.classList.toggle('hidden', Boolean(state.project?.nodes?.length));
  $('#projectTitle').value = state.project?.title || 'Выберите проект';
  requestAnimationFrame(() => {
    drawEdges();
    renderMinimap();
    updateExpiryLabels();
  });
}

function nodeTemplate(node) {
  if (node.node_type === 'photo') return $('#photoNodeTemplate');
  if (node.node_type === 'note') return $('#noteNodeTemplate');
  return $('#promptNodeTemplate');
}

function renderNodes() {
  nodesLayer.innerHTML = '';
  if (!state.project) return;
  for (const node of state.project.nodes) {
    const article = nodeTemplate(node).content.firstElementChild.cloneNode(true);
    article.dataset.nodeId = node.id;
    article.style.left = `${node.x}px`;
    article.style.top = `${node.y}px`;
    article.classList.toggle('selected', state.selectedNodeId === node.id);
    $('.node-title', article).value = node.title;
    bindCommonNode(article, node);
    if (node.node_type === 'photo') configurePhotoNode(article, node);
    else if (node.node_type === 'note') configureNoteNode(article, node);
    else configurePromptNode(article, node);
    nodesLayer.appendChild(article);
  }
}

function bindCommonNode(article, node) {
  article.addEventListener('pointerdown', event => {
    state.selectedNodeId = node.id;
    $$('.node').forEach(el => el.classList.toggle('selected', el.dataset.nodeId === node.id));
    event.stopPropagation();
  });

  article.addEventListener('click', event => {
    if (!state.noteLinkSourceId || node.id === state.noteLinkSourceId) return;
    if (event.target.closest('input,textarea,select,button,a,.upload-zone')) return;
    event.stopPropagation();
    toggleNoteTarget(state.noteLinkSourceId, node.id).catch(error => toast(error.message, 'error'));
  });

  const titleInput = $('.node-title', article);
  titleInput.addEventListener('pointerdown', event => event.stopPropagation());
  titleInput.addEventListener('change', async () => {
    node.title = titleInput.value.trim() || node.title;
    titleInput.value = node.title;
    await patchNode(node.id, {title: node.title});
  });

  $('.delete-node', article).addEventListener('click', async event => {
    event.stopPropagation();
    const label = node.node_type === 'photo' ? 'фото-блок' : node.node_type === 'note' ? 'заметку' : 'промпт-блок и его результаты';
    if (!confirm(`Удалить ${label}?`)) return;
    try {
      await api(`/api/canvas/nodes/${node.id}`, {method: 'DELETE'});
      state.project.nodes = state.project.nodes.filter(item => item.id !== node.id);
      for (const note of projectNoteNodes()) {
        note.config.target_node_ids = (note.config.target_node_ids || []).filter(id => id !== node.id);
      }
      renderCanvas();
      refreshProjectsQuietly();
      toast('Блок удалён', 'success');
    } catch (error) { toast(error.message, 'error'); }
  });

  bindNodeDrag(article, node);
}

function configurePhotoNode(article, node) {
  const asset = node.assets?.find(item => item.kind === 'customer_photo');
  article.classList.toggle('has-image', Boolean(asset));
  $('.photo-status', article).textContent = asset ? 'Фото подключено' : 'Ожидает фото';
  if (asset?.expires_at) article.dataset.expiresAt = asset.expires_at;
  setupUploadZone($('.photo-dropzone', article), node, 'photo', asset, () => false);
}

function configurePromptNode(article, node) {
  const config = node.config || {};
  node.config = config;
  config.provider ||= 'openai';
  config.model ||= defaultModel(config.provider);
  config.aspect_ratio ||= 'auto';
  config.detected_aspect_ratio ||= '1:1';
  config.output_count ||= 1;
  config.quality ||= 'high';
  config.prompt_locked = Boolean(config.prompt_locked);
  config.reference_locked = Boolean(config.reference_locked);

  const ref = referenceAsset(node);
  const photoCount = projectPhotoNodes().length;
  const readyPhotoCount = uploadedPhotoCount();
  $('.reference-number', article).textContent = `Референс №${config.reference_number ?? '—'}`;

  const textarea = $('.prompt-text', article);
  const promptLock = $('.prompt-lock', article);
  textarea.value = config.prompt_text || '';
  textarea.addEventListener('pointerdown', event => event.stopPropagation());
  textarea.addEventListener('input', () => {
    if (config.prompt_locked) return;
    config.prompt_text = textarea.value;
    scheduleNodeConfigSave(node);
    updateGenerateAvailability(article, node);
  });
  ['copy', 'cut'].forEach(type => textarea.addEventListener(type, event => {
    if (config.prompt_locked) { event.preventDefault(); toast('Системный промпт закрыт', 'error'); }
  }));
  promptLock.addEventListener('click', event => {
    event.stopPropagation();
    config.prompt_locked = !config.prompt_locked;
    applyPromptLockUI(article, config);
    scheduleNodeConfigSave(node, 0);
  });
  applyPromptLockUI(article, config);

  const referenceLock = $('.reference-lock', article);
  const refZone = $('.reference-dropzone', article);
  referenceLock.addEventListener('click', event => {
    event.stopPropagation();
    config.reference_locked = !config.reference_locked;
    applyReferenceLockUI(article, config);
    scheduleNodeConfigSave(node, 0);
  });
  applyReferenceLockUI(article, config);
  setupUploadZone(refZone, node, 'reference', ref, () => config.reference_locked);

  $('.paste-reference', article).addEventListener('click', async event => {
    event.stopPropagation();
    if (config.reference_locked) return toast('Сначала откройте референс', 'error');
    const file = await readClipboardImage();
    if (!file) return toast('В буфере обмена нет изображения или браузер не дал доступ', 'error');
    await uploadNodeImage(node, 'reference', file);
  });

  $('.connection-count', article).textContent = pluralPhotos(photoCount);
  $('.connections-summary', article).title = `${readyPhotoCount} из ${photoCount} блоков содержат загруженные изображения`;

  const providerSelect = $('.provider-select', article);
  const aspectSelect = $('.aspect-ratio', article);
  const countInput = $('.output-count', article);
  const qualitySelect = $('.image-quality', article);
  providerSelect.value = config.provider;
  aspectSelect.value = config.aspect_ratio;
  countInput.value = config.output_count;
  qualitySelect.value = config.quality;
  $('.detected-ratio', article).textContent = config.aspect_ratio === 'auto' ? `Референс: ${config.detected_aspect_ratio}` : '';
  [providerSelect, aspectSelect, countInput, qualitySelect].forEach(control => control.addEventListener('pointerdown', event => event.stopPropagation()));

  providerSelect.addEventListener('change', () => {
    config.provider = providerSelect.value;
    config.model = defaultModel(config.provider);
    scheduleNodeConfigSave(node, 0);
    renderNodeProviderStatus(article, config.provider);
  });
  aspectSelect.addEventListener('change', () => {
    config.aspect_ratio = aspectSelect.value;
    $('.detected-ratio', article).textContent = config.aspect_ratio === 'auto' ? `Референс: ${config.detected_aspect_ratio}` : '';
    scheduleNodeConfigSave(node, 0);
  });
  countInput.addEventListener('change', () => {
    config.output_count = Math.max(1, Math.min(20, Number(countInput.value) || 1));
    countInput.value = config.output_count;
    scheduleNodeConfigSave(node, 0);
    updateGenerateAvailability(article, node);
  });
  qualitySelect.addEventListener('change', () => {
    config.quality = qualitySelect.value;
    scheduleNodeConfigSave(node, 0);
  });

  $('.generate-btn', article).addEventListener('click', event => {
    event.stopPropagation();
    startGeneration(node, article).catch(error => toast(error.message, 'error'));
  });

  renderNodeProviderStatus(article, config.provider);
  renderGenerationState(article, node);
  updateGenerateAvailability(article, node);
}

function applyPromptLockUI(article, config) {
  const textarea = $('.prompt-text', article);
  const button = $('.prompt-lock', article);
  textarea.readOnly = config.prompt_locked;
  textarea.classList.toggle('locked', config.prompt_locked);
  button.classList.toggle('locked', config.prompt_locked);
  button.textContent = config.prompt_locked ? '🔒' : '🔓';
  button.title = config.prompt_locked ? 'Открыть системный промпт' : 'Закрыть системный промпт';
  button.setAttribute('aria-label', button.title);
}

function applyReferenceLockUI(article, config) {
  const zone = $('.reference-dropzone', article);
  const button = $('.reference-lock', article);
  const pasteButton = $('.paste-reference', article);
  zone.classList.toggle('locked', config.reference_locked);
  button.classList.toggle('locked', config.reference_locked);
  button.textContent = config.reference_locked ? '🔒' : '🔓';
  button.title = config.reference_locked ? 'Открыть референс' : 'Зафиксировать референс';
  button.setAttribute('aria-label', button.title);
  pasteButton.disabled = config.reference_locked;
}

function renderNodeProviderStatus(article, provider) {
  const status = state.providerStatuses[provider];
  const el = $('.provider-node-status', article);
  const connected = Boolean(status?.is_connected);
  el.className = `provider-node-status ${connected ? 'connected' : 'disconnected'}`;
  el.textContent = connected
    ? `✓ ${providerLabel(provider)} подключён`
    : `△ ${providerLabel(provider)} не подключён — локально будет использован MOCK`;
}

function configureNoteNode(article, node) {
  const config = node.config || {};
  config.note_text ||= '';
  config.target_node_ids ||= [];
  node.config = config;
  const textarea = $('.note-text', article);
  textarea.value = config.note_text;
  textarea.addEventListener('pointerdown', event => event.stopPropagation());
  textarea.addEventListener('input', () => {
    config.note_text = textarea.value;
    scheduleNodeConfigSave(node);
  });
  $('.link-note', article).addEventListener('click', event => {
    event.stopPropagation();
    beginNoteLink(node.id);
  });
  $('.clear-note-links', article).addEventListener('click', event => {
    event.stopPropagation();
    config.target_node_ids = [];
    scheduleNodeConfigSave(node, 0);
    state.noteLinkSourceId = null;
    renderCanvas();
  });
  article.classList.toggle('linking', state.noteLinkSourceId === node.id);
}

function beginNoteLink(noteId) {
  state.noteLinkSourceId = state.noteLinkSourceId === noteId ? null : noteId;
  $$('.note-node').forEach(el => el.classList.toggle('linking', el.dataset.nodeId === state.noteLinkSourceId));
  $$('.node').forEach(el => el.classList.toggle('edge-target-highlight', Boolean(state.noteLinkSourceId) && el.dataset.nodeId !== state.noteLinkSourceId));
  if (state.noteLinkSourceId) toast('Кликните по блоку, к которому нужно провести стрелку');
}

async function toggleNoteTarget(noteId, targetId) {
  const note = state.project?.nodes.find(item => item.id === noteId && item.node_type === 'note');
  if (!note) return;
  const ids = new Set(note.config.target_node_ids || []);
  if (ids.has(targetId)) ids.delete(targetId); else ids.add(targetId);
  note.config.target_node_ids = [...ids];
  await patchNode(note.id, {config: note.config});
  state.noteLinkSourceId = null;
  renderCanvas();
  toast(ids.has(targetId) ? 'Стрелка добавлена' : 'Стрелка удалена', 'success');
}

function updateGenerateAvailability(article, node) {
  const config = node.config || {};
  const button = $('.generate-btn', article);
  const hasPrompt = Boolean(String(config.prompt_text || '').trim());
  const hasRef = Boolean(referenceAsset(node));
  const photos = uploadedPhotoCount();
  const latest = node.latest_generation;
  const running = latest && ['queued', 'running'].includes(latest.status);
  button.disabled = running || !hasPrompt || !hasRef || photos < 1;
  $('.generate-count', article).textContent = `× ${config.output_count || 1}`;
  if (!running) {
    const missing = [];
    if (!photos) missing.push('фото заказчика');
    if (!hasPrompt) missing.push('промпт');
    if (!hasRef) missing.push('референс');
    button.title = missing.length ? `Не хватает: ${missing.join(', ')}` : 'Запустить только эту генерацию';
  }
}

function renderGenerationState(article, node) {
  const generation = node.latest_generation;
  const button = $('.generate-btn', article);
  const message = $('.generation-message', article);
  const resultsSection = $('.results-section', article);
  const grid = $('.result-grid', article);
  const time = $('.result-time', article);
  const ratio = node.config.aspect_ratio === 'auto' ? node.config.detected_aspect_ratio : node.config.aspect_ratio;
  grid.style.setProperty('--result-aspect', (ratio || '2:3').replace(':', '/'));

  message.className = 'generation-message';
  resultsSection.classList.remove('visible');
  grid.innerHTML = '';
  button.classList.remove('running');
  $('.generate-label', article).textContent = 'Генерировать';

  if (!generation) return;
  if (['queued', 'running'].includes(generation.status)) {
    button.classList.add('running');
    button.disabled = true;
    $('.generate-label', article).textContent = generation.status === 'queued' ? 'В очереди…' : 'Генерация…';
    message.classList.add('visible');
    message.textContent = `${providerLabel(node.config.provider)} обрабатывает связанные фотографии и референс этого блока.`;
    ensureGenerationPolling(generation.id, node.id);
    markConnectedEdgesActive(node.id, true);
    return;
  }

  markConnectedEdgesActive(node.id, false);
  if (generation.status === 'failed') {
    message.classList.add('visible', 'error');
    message.textContent = generation.error_message || 'Генерация завершилась с ошибкой';
    return;
  }

  if (generation.status === 'completed') {
    resultsSection.classList.add('visible');
    time.textContent = generation.completed_at ? new Date(generation.completed_at).toLocaleString('ru-RU', {hour:'2-digit', minute:'2-digit'}) : '';
    if (!generation.outputs?.length) {
      grid.innerHTML = '<div class="results-expired">Временные результаты автоматически удалены.</div>';
      return;
    }
    generation.outputs.forEach((output, index) => {
      const card = document.createElement('div');
      card.className = 'result-card';
      card.dataset.expiresAt = output.expires_at || '';
      card.innerHTML = `<img src="${output.url}" alt="Результат ${index + 1}" draggable="false"><span class="result-expiry-badge"></span><a href="${output.url}" target="_blank" title="Открыть оригинал">↗</a>`;
      grid.appendChild(card);
    });
    requestAnimationFrame(() => { drawEdges(); renderMinimap(); });
  }
}

function setupUploadZone(zone, node, endpointKind, asset, isLocked = () => false) {
  const input = $('input[type="file"]', zone);
  const image = $('.node-image', zone);
  if (asset) {
    zone.classList.add('has-image');
    image.src = asset.url;
  }
  const choose = () => {
    if (isLocked()) return toast(endpointKind === 'reference' ? 'Референс зафиксирован' : 'Поле заблокировано', 'error');
    input.click();
  };
  zone.addEventListener('click', event => {
    if (event.target.closest('button')) event.preventDefault();
    choose();
  });
  zone.addEventListener('pointerdown', event => {
    event.stopPropagation();
    if (!isLocked()) setPasteTarget(node, endpointKind, zone);
  });
  input.addEventListener('click', event => event.stopPropagation());
  input.addEventListener('change', () => {
    if (input.files?.[0]) uploadNodeImage(node, endpointKind, input.files[0]);
    input.value = '';
  });
  zone.addEventListener('dragover', event => {
    event.preventDefault();
    if (!isLocked()) zone.classList.add('dragover');
  });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
  zone.addEventListener('drop', event => {
    event.preventDefault();
    zone.classList.remove('dragover');
    if (isLocked()) return toast('Поле зафиксировано', 'error');
    const file = event.dataTransfer.files?.[0];
    if (file) uploadNodeImage(node, endpointKind, file);
  });
}

function setPasteTarget(node, kind, zone = null) {
  $$('.upload-zone').forEach(el => el.classList.remove('paste-focus'));
  state.pasteTarget = {nodeId: node.id, kind};
  zone?.classList.add('paste-focus');
  const hint = $('#pasteTargetHint');
  hint.textContent = kind === 'reference' ? 'Ctrl+V вставит изображение в этот референс' : 'Ctrl+V заменит фото в этом блоке';
  hint.classList.add('visible');
  clearTimeout(setPasteTarget.timer);
  setPasteTarget.timer = setTimeout(() => {
    hint.classList.remove('visible');
    $$('.upload-zone').forEach(el => el.classList.remove('paste-focus'));
  }, 2600);
}

async function uploadNodeImage(node, endpointKind, file) {
  if (!file?.type?.startsWith('image/')) return toast('Выберите изображение', 'error');
  const form = new FormData();
  form.append('file', file, file.name || `clipboard-${Date.now()}.png`);
  setSaveStatus('saving', 'Загрузка…');
  try {
    await api(`/api/canvas/nodes/${node.id}/${endpointKind}`, {method: 'POST', body: form});
    await reloadCurrentProject();
    setSaveStatus();
    toast(endpointKind === 'photo' ? 'Фото заказчика загружено' : 'Референс загружен', 'success');
  } catch (error) {
    setSaveStatus('error');
    toast(error.message, 'error');
  }
}

function imageFileFromPasteEvent(event) {
  for (const item of event.clipboardData?.items || []) {
    if (item.type.startsWith('image/')) {
      const blob = item.getAsFile();
      if (blob) return new File([blob], `clipboard-${Date.now()}.${item.type.includes('png') ? 'png' : 'jpg'}`, {type: item.type});
    }
  }
  return null;
}

async function readClipboardImage() {
  if (!navigator.clipboard?.read) return null;
  try {
    const items = await navigator.clipboard.read();
    for (const item of items) {
      const type = item.types.find(value => value.startsWith('image/'));
      if (!type) continue;
      const blob = await item.getType(type);
      return new File([blob], `clipboard-${Date.now()}.${type.includes('png') ? 'png' : 'jpg'}`, {type});
    }
  } catch (_) {}
  return null;
}

async function handlePastedImage(file, eventTarget) {
  if (!state.project) return openProjectModal();
  const promptArticle = eventTarget?.closest?.('.prompt-node');
  if (promptArticle) {
    const node = state.project.nodes.find(item => item.id === promptArticle.dataset.nodeId);
    if (node?.config?.reference_locked) return toast('Референс зафиксирован', 'error');
    return uploadNodeImage(node, 'reference', file);
  }
  if (state.pasteTarget) {
    const node = state.project.nodes.find(item => item.id === state.pasteTarget.nodeId);
    if (node) {
      if (state.pasteTarget.kind === 'reference' && node.config?.reference_locked) return toast('Референс зафиксирован', 'error');
      return uploadNodeImage(node, state.pasteTarget.kind, file);
    }
  }
  const position = canvasPositionFromClient(state.lastCanvasPointer?.x, state.lastCanvasPointer?.y, 'photo');
  const node = await addNode('photo', position, false);
  if (node) await uploadNodeImage(node, 'photo', file);
}

async function patchNode(nodeId, payload) {
  setSaveStatus('saving');
  try {
    const result = await api(`/api/canvas/nodes/${nodeId}`, {
      method: 'PATCH', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload),
    });
    setSaveStatus();
    return result;
  } catch (error) {
    setSaveStatus('error');
    toast(error.message, 'error');
    throw error;
  }
}

function scheduleNodeConfigSave(node, delay = 650) {
  clearTimeout(state.saveTimers.get(node.id));
  setSaveStatus('saving');
  state.saveTimers.set(node.id, setTimeout(async () => {
    try { await patchNode(node.id, {config: node.config}); }
    finally { state.saveTimers.delete(node.id); }
  }, delay));
}

async function flushNodeSave(node) {
  const timer = state.saveTimers.get(node.id);
  if (timer) {
    clearTimeout(timer);
    state.saveTimers.delete(node.id);
  }
  await patchNode(node.id, {config: node.config});
}

async function startGeneration(node, article) {
  await flushNodeSave(node);
  const button = $('.generate-btn', article);
  button.disabled = true;
  button.classList.add('running');
  $('.generate-label', article).textContent = 'Запускаем…';
  const result = await api(`/api/canvas/nodes/${node.id}/generate`, {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({output_count: Number(node.config.output_count || 1)}),
  });
  node.generations = [...(node.generations || []), result];
  node.latest_generation = result;
  renderGenerationState(article, node);
  toast(`Запущена только генерация №${node.config.reference_number}`, 'success');
}

function ensureGenerationPolling(generationId, nodeId) {
  if (state.pollTimers.has(generationId)) return;
  const poll = async () => {
    try {
      const generation = await api(`/api/canvas/generations/${generationId}`);
      const node = state.project?.nodes.find(item => item.id === nodeId);
      if (!node) return clearGenerationPoll(generationId);
      node.latest_generation = generation;
      const article = document.querySelector(`.node[data-node-id="${nodeId}"]`);
      if (article) {
        renderGenerationState(article, node);
        updateGenerateAvailability(article, node);
      }
      if (['queued','running'].includes(generation.status)) {
        state.pollTimers.set(generationId, setTimeout(poll, 1800));
      } else {
        clearGenerationPoll(generationId);
        await reloadCurrentProject(false);
        toast(generation.status === 'completed' ? 'Изображение готово' : 'Генерация завершилась с ошибкой', generation.status === 'completed' ? 'success' : 'error');
      }
    } catch (error) {
      clearGenerationPoll(generationId);
      toast(`Не удалось получить статус: ${error.message}`, 'error');
    }
  };
  state.pollTimers.set(generationId, setTimeout(poll, 1200));
}

function clearGenerationPoll(id) { clearTimeout(state.pollTimers.get(id)); state.pollTimers.delete(id); }
function clearAllPolls() { for (const timer of state.pollTimers.values()) clearTimeout(timer); state.pollTimers.clear(); }

async function reloadCurrentProject(resetView = false) {
  if (!state.project) return;
  const currentView = {...state.view};
  state.project = await api(`/api/projects/${state.project.id}`);
  if (!resetView) state.view = currentView;
  renderCanvas();
  refreshProjectsQuietly();
}

async function refreshProjectsQuietly() {
  try { state.projects = await api('/api/projects'); renderProjectList(); } catch (_) {}
}

function bindNodeDrag(article, node) {
  const handle = $('.drag-handle', article);
  handle.addEventListener('pointerdown', event => {
    if (event.button !== 0 || event.target.closest('input,button,textarea,select')) return;
    event.preventDefault();
    event.stopPropagation();
    state.drag = {node, article, startX:event.clientX, startY:event.clientY, nodeX:node.x, nodeY:node.y, pointerId:event.pointerId};
    handle.setPointerCapture?.(event.pointerId);
  });
  handle.addEventListener('pointermove', event => {
    if (!state.drag || state.drag.node.id !== node.id) return;
    node.x = Math.round(state.drag.nodeX + (event.clientX - state.drag.startX) / state.view.zoom);
    node.y = Math.round(state.drag.nodeY + (event.clientY - state.drag.startY) / state.view.zoom);
    article.style.left = `${node.x}px`;
    article.style.top = `${node.y}px`;
    drawEdges();
    renderMinimap();
  });
  const finish = async event => {
    if (!state.drag || state.drag.node.id !== node.id) return;
    handle.releasePointerCapture?.(event.pointerId);
    state.drag = null;
    await patchNode(node.id, {x: node.x, y: node.y});
  };
  handle.addEventListener('pointerup', finish);
  handle.addEventListener('pointercancel', finish);
}

function addSvgDefs() {
  const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
  defs.innerHTML = `
    <marker id="arrow-main" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L8,4 L0,8 z" fill="currentColor"></path></marker>
    <marker id="arrow-note" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L8,4 L0,8 z" fill="#b99100"></path></marker>`;
  edgesSvg.appendChild(defs);
}

function appendEdge(d, className, dataset = {}) {
  const glow = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  glow.setAttribute('d', d);
  glow.setAttribute('class', `${className} glow`);
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', d);
  path.setAttribute('class', className);
  path.setAttribute('marker-end', className.includes('note-edge') ? 'url(#arrow-note)' : 'url(#arrow-main)');
  Object.entries(dataset).forEach(([key, value]) => { glow.dataset[key] = value; path.dataset[key] = value; });
  edgesSvg.append(glow, path);
  return path;
}

function buildEdgePath(sx, sy, tx, ty, strength = .42) {
  if (state.edgeStyle === 'orthogonal') {
    const midX = sx + (tx - sx) * .52;
    return `M ${sx} ${sy} H ${midX} V ${ty} H ${tx}`;
  }
  const distance = Math.max(85, Math.abs(tx - sx) * strength);
  return `M ${sx} ${sy} C ${sx + distance} ${sy}, ${tx - distance} ${ty}, ${tx} ${ty}`;
}

function updateEdgeStyleUI() {
  $$('[data-edge-style]').forEach(button => button.classList.toggle('active', button.dataset.edgeStyle === state.edgeStyle));
}

function drawEdges() {
  edgesSvg.innerHTML = '';
  if (!state.project) return;
  addSvgDefs();
  const photos = projectPhotoNodes();
  const prompts = projectPromptNodes();
  for (const photo of photos) {
    const photoEl = document.querySelector(`.node[data-node-id="${photo.id}"]`);
    if (!photoEl) continue;
    const sx = photo.x + photoEl.offsetWidth + 2;
    const sy = photo.y + photoEl.offsetHeight - 19;
    for (const prompt of prompts) {
      const promptEl = document.querySelector(`.node[data-node-id="${prompt.id}"]`);
      if (!promptEl) continue;
      const tx = prompt.x - 2;
      const ty = prompt.y + 26;
      const d = buildEdgePath(sx, sy, tx, ty, .42);
      const path = appendEdge(d, 'edge-path', {promptId: prompt.id});
      const running = prompt.latest_generation && ['queued','running'].includes(prompt.latest_generation.status);
      if (running) path.classList.add('active');
    }
  }
  for (const note of projectNoteNodes()) {
    const noteEl = document.querySelector(`.node[data-node-id="${note.id}"]`);
    if (!noteEl) continue;
    const sx = note.x + noteEl.offsetWidth + 2;
    const sy = note.y + noteEl.offsetHeight - 20;
    for (const targetId of note.config?.target_node_ids || []) {
      const target = state.project.nodes.find(item => item.id === targetId);
      const targetEl = document.querySelector(`.node[data-node-id="${targetId}"]`);
      if (!target || !targetEl) continue;
      const tx = target.x - 2;
      const ty = target.y + Math.min(38, targetEl.offsetHeight / 2);
      appendEdge(buildEdgePath(sx, sy, tx, ty, .38), 'edge-path note-edge', {noteId: note.id});
    }
  }
}

function markConnectedEdgesActive(promptId, active) {
  $$(`.edge-path[data-prompt-id="${promptId}"]`).forEach(path => path.classList.toggle('active', active && !path.classList.contains('glow')));
}

function applyView() {
  state.view.zoom = Math.max(.15, Math.min(2.5, state.view.zoom));
  world.style.transform = `translate(${state.view.x}px, ${state.view.y}px) scale(${state.view.zoom})`;
  viewport.style.backgroundPosition = `${state.view.x}px ${state.view.y}px`;
  viewport.style.backgroundSize = `${24 * state.view.zoom}px ${24 * state.view.zoom}px`;
  $('#zoomLabel').textContent = `${Math.round(state.view.zoom * 100)}%`;
  renderMinimap();
}

function setZoom(newZoom, clientX = null, clientY = null) {
  const rect = viewport.getBoundingClientRect();
  const cx = clientX ?? rect.left + rect.width / 2;
  const cy = clientY ?? rect.top + rect.height / 2;
  const old = state.view.zoom;
  const worldX = (cx - rect.left - state.view.x) / old;
  const worldY = (cy - rect.top - state.view.y) / old;
  state.view.zoom = Math.max(.15, Math.min(2.5, newZoom));
  state.view.x = cx - rect.left - worldX * state.view.zoom;
  state.view.y = cy - rect.top - worldY * state.view.zoom;
  applyView();
  scheduleViewportSave();
}

viewport.addEventListener('wheel', event => {
  event.preventDefault();
  setZoom(state.view.zoom * Math.exp(-event.deltaY * .0012), event.clientX, event.clientY);
}, {passive: false});

viewport.addEventListener('pointermove', event => {
  state.lastCanvasPointer = {x:event.clientX, y:event.clientY};
  if (!state.pan) return;
  state.view.x = state.pan.x + event.clientX - state.pan.startX;
  state.view.y = state.pan.y + event.clientY - state.pan.startY;
  applyView();
});

viewport.addEventListener('pointerdown', event => {
  if (event.button !== 0 && event.button !== 1) return;
  if (event.target.closest('.node, button, input, textarea, select, .minimap, .project-workspace-toolbar')) return;
  state.pasteTarget = null;
  $$('.upload-zone').forEach(el => el.classList.remove('paste-focus'));
  if (state.noteLinkSourceId) beginNoteLink(state.noteLinkSourceId);
  state.pan = {startX:event.clientX, startY:event.clientY, x:state.view.x, y:state.view.y, pointerId:event.pointerId};
  viewport.classList.add('panning');
  viewport.setPointerCapture?.(event.pointerId);
});

const finishPan = event => {
  if (!state.pan) return;
  viewport.releasePointerCapture?.(event.pointerId);
  state.pan = null;
  viewport.classList.remove('panning');
  scheduleViewportSave();
};
viewport.addEventListener('pointerup', finishPan);
viewport.addEventListener('pointercancel', finishPan);

let viewportSaveTimer = null;
function scheduleViewportSave() {
  if (!state.project) return;
  clearTimeout(viewportSaveTimer);
  viewportSaveTimer = setTimeout(() => api(`/api/projects/${state.project.id}`, {
    method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({viewport:{...state.view, edge_style:state.edgeStyle}}),
  }).catch(() => {}), 700);
}

function nodeWidth(node) { return node.node_type === 'photo' ? 272 : node.node_type === 'note' ? 320 : 410; }
function renderMinimap() {
  const miniWorld = $('#minimapWorld');
  const miniView = $('#minimapView');
  miniWorld.innerHTML = '';
  if (!state.project?.nodes?.length) { $('#minimap').style.display = 'none'; return; }
  $('#minimap').style.display = '';
  const nodes = state.project.nodes;
  const minX = Math.min(...nodes.map(n => n.x)) - 100;
  const minY = Math.min(...nodes.map(n => n.y)) - 100;
  const maxX = Math.max(...nodes.map(n => n.x + nodeWidth(n))) + 100;
  const maxY = Math.max(...nodes.map(n => n.y + 420)) + 100;
  const width = Math.max(800, maxX - minX);
  const height = Math.max(500, maxY - minY);
  const scale = Math.min(150 / width, 92 / height);
  nodes.forEach(node => {
    const el = document.createElement('div');
    el.className = `minimap-node ${node.node_type}`;
    el.style.left = `${(node.x - minX) * scale}px`;
    el.style.top = `${(node.y - minY) * scale}px`;
    el.style.width = `${nodeWidth(node) * scale}px`;
    el.style.height = `${Math.max(5, (node.node_type === 'photo' ? 290 : node.node_type === 'note' ? 230 : 410) * scale)}px`;
    miniWorld.appendChild(el);
  });
  const rect = viewport.getBoundingClientRect();
  const viewLeft = -state.view.x / state.view.zoom;
  const viewTop = -state.view.y / state.view.zoom;
  miniView.style.left = `${(viewLeft - minX) * scale}px`;
  miniView.style.top = `${(viewTop - minY) * scale}px`;
  miniView.style.width = `${rect.width / state.view.zoom * scale}px`;
  miniView.style.height = `${rect.height / state.view.zoom * scale}px`;
}

function fitContent() {
  if (!state.project?.nodes?.length) return resetView();
  const rect = viewport.getBoundingClientRect();
  const nodes = state.project.nodes;
  const minX = Math.min(...nodes.map(n => n.x));
  const minY = Math.min(...nodes.map(n => n.y));
  const maxX = Math.max(...nodes.map(n => n.x + nodeWidth(n)));
  const maxY = Math.max(...nodes.map(n => n.y + (document.querySelector(`.node[data-node-id="${n.id}"]`)?.offsetHeight || 360)));
  const contentW = maxX - minX + 100;
  const contentH = maxY - minY + 100;
  state.view.zoom = Math.max(.18, Math.min(1.15, rect.width / contentW, rect.height / contentH));
  state.view.x = (rect.width - (maxX - minX) * state.view.zoom) / 2 - minX * state.view.zoom;
  state.view.y = (rect.height - (maxY - minY) * state.view.zoom) / 2 - minY * state.view.zoom;
  applyView();
  scheduleViewportSave();
}

function resetView() { state.view = {x:90, y:80, zoom:1}; applyView(); scheduleViewportSave(); }

function canvasPositionFromClient(clientX, clientY, type = 'prompt') {
  const rect = viewport.getBoundingClientRect();
  const cx = clientX ?? rect.left + rect.width / 2;
  const cy = clientY ?? rect.top + rect.height / 2;
  return {
    x: Math.round((cx - rect.left - state.view.x) / state.view.zoom - nodeWidth({node_type:type}) / 2),
    y: Math.round((cy - rect.top - state.view.y) / state.view.zoom - 130),
  };
}

function nextNodePosition(type) {
  const position = canvasPositionFromClient(null, null, type);
  const count = state.project?.nodes?.length || 0;
  const jitter = (count % 5) * 24;
  return {x:position.x + jitter, y:position.y + jitter};
}

async function addNode(type, position = null, showToast = true) {
  if (!state.project) { openProjectModal(); return null; }
  setSaveStatus('saving');
  try {
    const node = await api(`/api/projects/${state.project.id}/nodes`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({node_type:type, ...(position || nextNodePosition(type))}),
    });
    state.project.nodes.push(node);
    state.selectedNodeId = node.id;
    renderCanvas();
    setSaveStatus();
    refreshProjectsQuietly();
    if (showToast) {
      const message = type === 'photo' ? 'Добавлен блок фото заказчика' : type === 'note' ? 'Добавлена заметка' : `Добавлен промпт №${node.config.reference_number}. Все фото связаны автоматически.`;
      toast(message, 'success');
    }
    return node;
  } catch (error) {
    setSaveStatus('error');
    toast(error.message, 'error');
    return null;
  }
}

function centerOnNode(nodeId) {
  const node = state.project?.nodes.find(item => item.id === nodeId);
  const el = document.querySelector(`.node[data-node-id="${nodeId}"]`);
  if (!node || !el) return;
  const rect = viewport.getBoundingClientRect();
  state.view.x = rect.width / 2 - (node.x + el.offsetWidth / 2) * state.view.zoom;
  state.view.y = rect.height / 2 - (node.y + Math.min(el.offsetHeight, 360) / 2) * state.view.zoom;
  state.selectedNodeId = nodeId;
  applyView();
  $$('.node').forEach(item => item.classList.toggle('selected', item.dataset.nodeId === nodeId));
  el.animate([{filter:'brightness(1)'},{filter:'brightness(1.25)'},{filter:'brightness(1)'}], {duration:650});
  scheduleViewportSave();
}

function searchNodes(query) {
  const q = query.trim().toLowerCase();
  if (!q || !state.project) return [];
  return state.project.nodes.filter(node => {
    const config = node.config || {};
    const haystack = [node.title, config.prompt_text, config.note_text, config.reference_number && `референс ${config.reference_number}`, config.reference_number && String(config.reference_number)].filter(Boolean).join(' ').toLowerCase();
    return haystack.includes(q);
  }).slice(0, 20);
}

function renderSearchResults(query) {
  const box = $('#searchResults');
  const results = searchNodes(query);
  if (!query.trim()) return closeSearchResults();
  box.innerHTML = results.length ? '' : '<div class="search-result"><div class="search-result-copy"><strong>Ничего не найдено</strong><small>Попробуйте номер референса или часть текста</small></div></div>';
  results.forEach(node => {
    const button = document.createElement('button');
    button.className = 'search-result';
    const type = node.node_type === 'photo' ? 'Фото' : node.node_type === 'note' ? 'Заметка' : `№${node.config?.reference_number ?? '—'}`;
    const detail = node.node_type === 'prompt' ? (node.config?.prompt_text || 'Без промпта') : node.node_type === 'note' ? (node.config?.note_text || 'Пустая заметка') : 'Фото заказчика';
    button.innerHTML = `<span class="search-result-icon">${escapeHtml(type)}</span><span class="search-result-copy"><strong>${escapeHtml(node.title)}</strong><small>${escapeHtml(detail.slice(0, 90))}</small></span>`;
    button.addEventListener('click', () => { centerOnNode(node.id); closeSearchResults(); });
    box.appendChild(button);
  });
  box.classList.add('open');
}

function closeSearchResults() { $('#searchResults').classList.remove('open'); }

function openProjectsDrawer() { $('#projectsDrawer').classList.add('open'); $('#drawerBackdrop').classList.add('open'); refreshProjectsQuietly(); }
function closeProjectsDrawer() { $('#projectsDrawer').classList.remove('open'); $('#drawerBackdrop').classList.remove('open'); }
function openProjectModal() { $('#projectModal').classList.add('open'); setTimeout(() => $('#projectForm input[name="title"]')?.focus(), 100); }
function closeProjectModal() { $('#projectModal').classList.remove('open'); }
function openModal(id) { $(id).classList.add('open'); }
function closeModal(id) { $(id).classList.remove('open'); }

async function loadConnectionsModal() {
  await loadProviderStatuses();
  for (const [provider, status] of Object.entries(state.providerStatuses)) {
    const card = $(`.provider-card[data-provider="${provider}"]`);
    if (!card) continue;
    const input = $('.provider-key', card);
    const lock = $('.credential-lock', card);
    input.value = '';
    input.readOnly = Boolean(status.is_locked);
    lock.classList.toggle('locked', Boolean(status.is_locked));
    lock.textContent = status.is_locked ? '🔒' : '🔓';
    lock.title = status.is_locked ? 'Открыть поле API-ключа' : 'Закрыть поле API-ключа';
    $('.masked-key', card).textContent = status.masked_key ? `Сохранён: ${status.masked_key}` : 'Ключ ещё не сохранён';
    $('.provider-mode', card).value = status.connection_mode || 'direct';
    $('.provider-url', card).value = status.api_base_url || '';
    $('.provider-model', card).value = status.default_model || '';
    $('.provider-auth-header', card).value = status.auth_header || 'Authorization';
    $('.provider-auth-prefix', card).value = status.auth_prefix ?? 'Bearer';
    card.classList.toggle('integrator-mode', $('.provider-mode', card).value === 'integrator');
    const statusEl = $('.connection-status', card);
    statusEl.className = `connection-status ${status.is_connected ? 'connected' : 'disconnected'}`;
    $('b', statusEl).textContent = status.is_connected ? 'Подключено' : 'Не подключено';
    $('.provider-error', card).textContent = status.last_error || '';
  }
}

async function saveProviderCard(card, testAfter = false) {
  const provider = card.dataset.provider;
  const input = $('.provider-key', card);
  const lock = $('.credential-lock', card);
  const payload = {
    is_locked: lock.classList.contains('locked'),
    connection_mode: $('.provider-mode', card).value,
    api_base_url: $('.provider-url', card).value.trim(),
    model_name: $('.provider-model', card).value.trim(),
    auth_header: $('.provider-auth-header', card).value.trim(),
    auth_prefix: $('.provider-auth-prefix', card).value.trim(),
  };
  if (input.value.trim()) payload.api_key = input.value.trim();
  const button = testAfter ? $('.test-provider', card) : $('.save-provider', card);
  button.disabled = true;
  try {
    await api(`/api/admin/providers/${provider}`, {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
    if (testAfter) await api(`/api/admin/providers/${provider}/test`, {method:'POST'});
    input.value = '';
    await loadConnectionsModal();
    renderCanvas();
    toast(testAfter ? `${providerLabel(provider)} подключён` : 'Ключ сохранён', 'success');
  } catch (error) {
    $('.provider-error', card).textContent = error.message;
    toast(error.message, 'error');
  } finally { button.disabled = false; }
}

async function openDiagnostics() {
  openModal('#diagnosticsModal');
  const grid = $('#diagnosticGrid');
  grid.innerHTML = '<div class="diagnostic-loading">Загрузка…</div>';
  try {
    const data = await api('/api/admin/diagnostics');
    const cards = [
      [data.today.images, 'Изображений сегодня'],
      [data.today.runs, 'Запусков сегодня'],
      [data.today.tokens.toLocaleString('ru-RU'), 'Токенов сегодня'],
      [data.today.failed, 'Ошибок сегодня'],
      [data.all_time_images, 'Изображений всего'],
      [data.temporary.customer_photos, 'Временных фото'],
      [data.temporary.outputs, 'Временных результатов'],
      [formatBytes(data.temporary.storage_bytes), 'Размер хранилища'],
    ];
    grid.innerHTML = cards.map(([value, label]) => `<div class="diagnostic-card"><strong>${value}</strong><span>${label}</span></div>`).join('');
    const providers = $('#diagnosticProviders');
    providers.innerHTML = data.providers.length
      ? data.providers.map(item => `<div class="diagnostic-provider-row"><strong>${providerLabel(item.provider)}</strong><span>${item.images} изображений · ${item.tokens.toLocaleString('ru-RU')} токенов</span></div>`).join('')
      : '<div class="diagnostic-provider-row"><span>Реальные генерации ещё не запускались. MOCK не расходует токены.</span></div>';
    providers.insertAdjacentHTML('beforeend', `<div class="diagnostic-provider-row"><span>Фото заказчиков удаляются через ${data.temporary.customer_ttl_minutes} минут, результаты — через ${data.temporary.output_ttl_minutes} минут после появления. Референсы и промпты сохраняются.</span></div>`);
  } catch (error) { grid.innerHTML = `<div class="generation-message visible error">${escapeHtml(error.message)}</div>`; }
}

function updateExpiryLabels() {
  const now = Date.now();
  $$('.photo-node[data-expires-at]').forEach(article => {
    const expires = new Date(article.dataset.expiresAt).getTime();
    const minutes = Math.max(0, Math.ceil((expires - now) / 60000));
    $('.photo-expiry', article).textContent = minutes ? `${minutes} мин` : 'очистка…';
  });

  $$('.result-card[data-expires-at]').forEach(card => {
    const expires = new Date(card.dataset.expiresAt).getTime();
    const remaining = Math.max(0, expires - now);
    const totalSeconds = Math.ceil(remaining / 1000);
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    const badge = $('.result-expiry-badge', card);
    if (badge) badge.textContent = remaining > 0 ? `Удаление через ${minutes}:${String(seconds).padStart(2, '0')}` : 'Удаляется…';
    card.classList.toggle('expiring', remaining > 0 && remaining <= 15 * 60 * 1000);
    card.classList.toggle('critical', remaining <= 5 * 60 * 1000);
    const section = card.closest('.results-section');
    if (section) {
      const label = $('.result-expiry', section);
      if (label) label.textContent = remaining > 0 ? `Автоудаление: ${minutes}:${String(seconds).padStart(2, '0')}` : 'Автоудаление…';
      section.classList.toggle('expiring', remaining > 0 && remaining <= 15 * 60 * 1000);
    }
    if (remaining <= 0 && !card.dataset.refreshScheduled) {
      card.dataset.refreshScheduled = '1';
      setTimeout(async () => {
        if (!state.project) return;
        try { await openProject(state.project.id, false); } catch (_) {}
      }, 3500);
    }
  });
}
setInterval(updateExpiryLabels, 10000);

$('#projectForm').addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.target;
  const button = $('button[type="submit"]', form);
  button.disabled = true;
  button.textContent = 'Создание…';
  try {
    const project = await api('/api/projects', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({title:form.title.value, description:form.description.value, theme:form.theme.value, tags:form.tags.value.split(',').map(tag => tag.trim()).filter(Boolean)}),
    });
    form.reset();
    closeProjectModal();
    state.projects = await api('/api/projects');
    await openProject(project.id);
    toast('Проект создан', 'success');
  } catch (error) { toast(error.message, 'error'); }
  finally { button.disabled = false; button.textContent = 'Создать проект'; }
});

$('#projectTitle').addEventListener('change', async event => {
  if (!state.project) return;
  const title = event.target.value.trim();
  if (!title) { event.target.value = state.project.title; return; }
  try {
    await api(`/api/projects/${state.project.id}`, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({title})});
    state.project.title = title;
    refreshProjectsQuietly();
    setSaveStatus();
  } catch (error) { toast(error.message, 'error'); event.target.value = state.project.title; }
});


function roleLabel(role) { return role === 'owner' ? 'Владелец' : role === 'viewer' ? 'Наблюдатель' : 'Оператор'; }

function projectOptions(selected = []) {
  const set = new Set(selected || []);
  return state.projects.map(project => `<option value="${escapeHtml(project.id)}" ${set.has(project.id) ? 'selected' : ''}>${escapeHtml(project.title)}</option>`).join('');
}

async function openUsersModal() {
  if (state.currentUser?.role !== 'owner') return;
  openModal('#usersModal');
  const projectSelect = $('#createUserForm select[name="allowed_project_ids"]');
  projectSelect.innerHTML = projectOptions([]);
  await loadUsers();
}

async function loadUsers() {
  const users = await api('/api/admin/users');
  const list = $('#usersList');
  list.innerHTML = '';
  users.forEach(user => {
    const row = document.createElement('div');
    row.className = 'user-row';
    row.innerHTML = `
      <div><strong>${escapeHtml(user.display_name || user.email)}</strong><small>${escapeHtml(user.email)}</small></div>
      <select class="user-projects" multiple size="3">${projectOptions(user.allowed_project_ids)}</select>
      <select class="user-role"><option value="operator">Оператор</option><option value="viewer">Наблюдатель</option><option value="owner">Владелец</option></select>
      <input class="user-password" type="password" minlength="10" placeholder="Новый пароль" />
      <button class="user-status-toggle ${user.is_active ? 'active' : 'inactive'}" type="button">${user.is_active ? 'Активен' : 'Отключён'}</button>
      <button class="secondary-btn save-user" type="button">Сохранить</button>`;
    $('.user-role', row).value = user.role;
    $('.user-status-toggle', row).addEventListener('click', event => {
      const button = event.currentTarget;
      button.classList.toggle('active'); button.classList.toggle('inactive');
      button.textContent = button.classList.contains('active') ? 'Активен' : 'Отключён';
    });
    $('.save-user', row).addEventListener('click', async () => {
      const selected = [...$('.user-projects', row).selectedOptions].map(option => option.value);
      try {
        const payload = {
          role: $('.user-role', row).value,
          allowed_project_ids: selected,
          is_active: $('.user-status-toggle', row).classList.contains('active'),
        };
        const newPassword = $('.user-password', row).value.trim();
        if (newPassword) payload.password = newPassword;
        await api(`/api/admin/users/${user.id}`, {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
        toast('Права пользователя сохранены','success');
      } catch(error) { toast(error.message,'error'); }
    });
    list.appendChild(row);
  });
}

async function logout() {
  await fetch('/api/auth/logout', {method:'POST'});
  location.href='/login';
}

function toggleProfilePopover() {
  let popover = $('#profilePopover');
  if (!popover) {
    popover = document.createElement('div'); popover.id='profilePopover'; popover.className='profile-popover';
    popover.innerHTML = `<strong>${escapeHtml(state.currentUser?.display_name || '')}</strong><span>${escapeHtml(state.currentUser?.email || '')} · ${escapeHtml(roleLabel(state.currentUser?.role))}</span><button class="secondary-btn" type="button">Выйти</button>`;
    $('button', popover).addEventListener('click', logout); document.body.appendChild(popover);
  }
  popover.classList.toggle('open');
}

$('#projectsButton').addEventListener('click', openProjectsDrawer);
$('#closeProjects').addEventListener('click', closeProjectsDrawer);
$('#drawerBackdrop').addEventListener('click', closeProjectsDrawer);
$('#newProjectButton').addEventListener('click', openProjectModal);
$$('[data-close-modal]').forEach(button => button.addEventListener('click', closeProjectModal));
$('#projectModal').addEventListener('click', event => { if (event.target === $('#projectModal')) closeProjectModal(); });

$('#helpButton').addEventListener('click', () => openModal('#helpModal'));
$$('[data-close-help]').forEach(button => button.addEventListener('click', () => closeModal('#helpModal')));
$('#helpModal').addEventListener('click', event => { if (event.target === $('#helpModal')) closeModal('#helpModal'); });

$('#connectionsButton').addEventListener('click', async () => { openModal('#connectionsModal'); await loadConnectionsModal(); });
$('#usersButton').addEventListener('click', openUsersModal);
$$('[data-close-users]').forEach(button => button.addEventListener('click', () => closeModal('#usersModal')));
$('#usersModal').addEventListener('click', event => { if (event.target === $('#usersModal')) closeModal('#usersModal'); });
$('#profileButton').addEventListener('click', toggleProfilePopover);
$$('[data-close-connections]').forEach(button => button.addEventListener('click', () => closeModal('#connectionsModal')));
$('#connectionsModal').addEventListener('click', event => { if (event.target === $('#connectionsModal')) closeModal('#connectionsModal'); });
$$('.provider-card').forEach(card => {
  $('.credential-lock', card).addEventListener('click', () => {
    const lock = $('.credential-lock', card);
    const input = $('.provider-key', card);
    const locked = !lock.classList.contains('locked');
    lock.classList.toggle('locked', locked);
    lock.textContent = locked ? '🔒' : '🔓';
    lock.title = locked ? 'Открыть поле API-ключа' : 'Закрыть поле API-ключа';
    input.readOnly = locked;
    if (!locked) input.focus();
  });
  $('.provider-mode', card).addEventListener('change', event => card.classList.toggle('integrator-mode', event.target.value === 'integrator'));
  $('.save-provider', card).addEventListener('click', () => saveProviderCard(card, false));
  $('.test-provider', card).addEventListener('click', () => saveProviderCard(card, true));
});


$('#createUserForm').addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form));
  data.allowed_project_ids = [...form.elements.allowed_project_ids.selectedOptions].map(option => option.value);
  try {
    await api('/api/admin/users',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    form.reset(); form.elements.allowed_project_ids.innerHTML = projectOptions([]);
    await loadUsers(); toast('Аккаунт создан','success');
  } catch(error) { toast(error.message,'error'); }
});

$('#diagnosticsButton').addEventListener('click', openDiagnostics);
$('#refreshDiagnostics').addEventListener('click', openDiagnostics);
$$('[data-close-diagnostics]').forEach(button => button.addEventListener('click', () => closeModal('#diagnosticsModal')));
$('#diagnosticsModal').addEventListener('click', event => { if (event.target === $('#diagnosticsModal')) closeModal('#diagnosticsModal'); });

$('#addPhotoButton').addEventListener('click', () => addNode('photo'));
$('#addPromptButton').addEventListener('click', () => addNode('prompt'));
$('#addNoteButton').addEventListener('click', () => addNode('note'));
$('#emptyAddPhoto').addEventListener('click', () => addNode('photo'));
$('#emptyAddPrompt').addEventListener('click', () => addNode('prompt'));
$$('[data-edge-style]').forEach(button => button.addEventListener('click', () => {
  state.edgeStyle = button.dataset.edgeStyle === 'orthogonal' ? 'orthogonal' : 'curved';
  updateEdgeStyleUI();
  drawEdges();
  scheduleViewportSave();
  toast(state.edgeStyle === 'orthogonal' ? 'Включены угловые стрелки' : 'Включены плавные стрелки', 'success');
}));

$('#workspaceSearch').addEventListener('input', event => renderSearchResults(event.target.value));
$('#workspaceSearch').addEventListener('focus', event => { if (event.target.value) renderSearchResults(event.target.value); });
document.addEventListener('click', event => { if (!event.target.closest('.workspace-search-wrap')) closeSearchResults(); });

$('#zoomIn').addEventListener('click', () => setZoom(state.view.zoom * 1.18));
$('#zoomOut').addEventListener('click', () => setZoom(state.view.zoom / 1.18));
$('#resetView').addEventListener('click', resetView);
$('#fitButton').addEventListener('click', fitContent);

function applyTheme(theme) { document.documentElement.dataset.theme = theme; storageSet('neurophoto_theme', theme); }
applyTheme(storageGet('neurophoto_theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));
$('#themeButton').addEventListener('click', () => applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));

window.addEventListener('paste', event => {
  const file = imageFileFromPasteEvent(event);
  if (!file) return;
  event.preventDefault();
  handlePastedImage(file, event.target).catch(error => toast(error.message, 'error'));
});

window.addEventListener('resize', () => { applyView(); drawEdges(); });
window.addEventListener('keydown', event => {
  if (event.key === 'Escape') {
    closeProjectsDrawer(); closeProjectModal(); closeModal('#helpModal'); closeModal('#connectionsModal'); closeModal('#diagnosticsModal'); closeModal('#usersModal'); closeSearchResults(); $('#profilePopover')?.classList.remove('open');
    if (state.noteLinkSourceId) beginNoteLink(state.noteLinkSourceId);
  }
  if ((event.ctrlKey || event.metaKey) && event.key === '0') { event.preventDefault(); fitContent(); }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); $('#workspaceSearch').focus(); }
});

loadMe().then(() => Promise.all([loadProviderStatuses(), loadProjects()])).catch(error => {
  toast(`Не удалось запустить студию: ${error.message}`, 'error');
  console.error(error);
});
