(() => {
  const original = {
    hasUnsavedChanges,
    saveAllChanges,
    openProject,
    reloadCurrentProject,
    uploadNodeImage,
    startGeneration,
    duplicateSelectedObjects,
    configurePromptNode,
  };

  Object.assign(state, {
    promptEditorNodeId: null,
    promptEditorDraft: null,
    promptEditorOriginal: null,
    promptEditorReferenceFile: null,
    promptEditorReferencePreviewUrl: null,
    promptEditorDirty: false,
    promptEditorSaving: false,
  });

  const promptTemplate = document.querySelector('#promptNodeTemplate');
  if (promptTemplate) {
    promptTemplate.innerHTML = `
      <article class="node prompt-node prompt-node-compact">
        <header class="node-head drag-handle">
          <div class="node-type-icon prompt-icon"><svg viewBox="0 0 24 24"><path d="M5 4h14v16H5z"/><path d="M8 8h8M8 12h8M8 16h5"/></svg></div>
          <div class="prompt-title-block"><input class="node-title" maxlength="180" readonly /><span class="reference-number"></span></div>
          <button class="node-menu delete-node" title="Удалить">×</button>
          <span class="edge-handle input-handle"></span>
        </header>
        <div class="node-body prompt-card-body">
          <div class="prompt-connected-status"><span class="prompt-connected-icon">✓</span><strong class="prompt-connected-label">Промпт подключён</strong><span class="prompt-empty-label">Промпт не заполнен</span></div>
          <div class="prompt-card-reference" role="button" tabindex="0" aria-label="Открыть настройки блока">
            <div class="prompt-card-reference-empty"><svg viewBox="0 0 24 24"><path d="M12 16V4M7 9l5-5 5 5"/><path d="M5 14v5h14v-5"/></svg><strong>Добавьте референс</strong><span>Откройте блок для загрузки</span></div>
            <img class="prompt-card-reference-image" alt="Референс" loading="lazy" decoding="async" draggable="false" />
            <span class="prompt-card-open-hint">Открыть блок</span>
          </div>
          <div class="connections-summary"><span class="links-icon">↗</span><strong class="connection-count">0 фото</strong><span>подключено автоматически</span></div>
          <div class="generation-settings provider-settings prompt-card-settings">
            <label><span>Модель</span><select class="provider-select"><option value="openai">ChatGPT</option><option value="gemini">Gemini</option></select></label>
            <label><span>Формат</span><select class="aspect-ratio"><option value="auto">Авто</option><option value="1:1">1:1</option><option value="2:3">2:3</option><option value="3:2">3:2</option><option value="3:4">3:4</option><option value="4:3">4:3</option><option value="4:5">4:5</option><option value="5:4">5:4</option><option value="9:16">9:16</option><option value="16:9">16:9</option></select><small class="detected-ratio"></small></label>
            <label><span>Результатов</span><input class="output-count" type="number" min="1" max="20" value="1" /></label>
            <label><span>Качество</span><select class="image-quality"><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select></label>
          </div>
          <div class="provider-node-status"></div>
          <button class="generate-btn" type="button"><span class="spark">✦</span><span class="generate-label">Генерировать</span><span class="generate-count"></span></button>
          <div class="generation-message"></div>
          <div class="results-section"><div class="results-head"><strong>Результат</strong><span class="result-meta"><span class="result-time"></span><span class="result-expiry"></span></span></div><div class="result-grid"></div></div>
        </div>
      </article>`;
  }

  document.body.insertAdjacentHTML('beforeend', `
    <aside class="prompt-editor-panel" id="promptEditorPanel" aria-hidden="true">
      <div class="prompt-editor-head">
        <div><span class="eyebrow">БЛОК-ПРОМПТ</span><h2>Настройки генерации</h2><p id="promptEditorReferenceNumber"></p></div>
        <button class="icon-btn prompt-editor-close" id="promptEditorClose" type="button" aria-label="Закрыть">×</button>
      </div>
      <div class="prompt-editor-scroll">
        <label class="prompt-editor-field"><span>Название блока</span><input id="promptEditorTitle" maxlength="180" /></label>

        <section class="prompt-editor-section">
          <div class="prompt-editor-section-head"><div><strong>Промпт</strong><small id="promptEditorPromptState"></small></div><button class="prompt-editor-lock" id="promptEditorPromptLock" type="button"></button></div>
          <textarea id="promptEditorText" rows="12" placeholder="Вставьте системный промпт для этой генерации…"></textarea>
        </section>

        <section class="prompt-editor-section">
          <div class="prompt-editor-section-head"><div><strong>Референс</strong><small id="promptEditorReferenceState"></small></div><button class="prompt-editor-lock" id="promptEditorReferenceLock" type="button"></button></div>
          <div class="prompt-editor-reference" id="promptEditorReferenceZone">
            <input id="promptEditorReferenceInput" type="file" accept="image/*" hidden />
            <div class="prompt-editor-reference-empty"><svg viewBox="0 0 24 24"><path d="M12 16V4M7 9l5-5 5 5"/><path d="M5 14v5h14v-5"/></svg><strong>Загрузить референс</strong><span>Нажмите, перетащите файл или вставьте из буфера</span></div>
            <img id="promptEditorReferenceImage" alt="Референс блока" loading="lazy" decoding="async" />
          </div>
          <div class="prompt-editor-reference-actions"><button class="secondary-btn" id="promptEditorChooseReference" type="button">Загрузить</button><button class="secondary-btn" id="promptEditorPasteReference" type="button">Вставить</button></div>
        </section>

        <div class="prompt-editor-connections"><span>↗</span><strong id="promptEditorPhotoCount">0 фото</strong><small>подключено автоматически</small></div>

        <section class="prompt-editor-section">
          <strong class="prompt-editor-section-title">Параметры</strong>
          <div class="prompt-editor-settings">
            <label><span>Модель</span><select id="promptEditorProvider"><option value="openai">ChatGPT · GPT Image 2</option><option value="gemini">Gemini</option></select></label>
            <label><span>Формат</span><select id="promptEditorAspect"><option value="auto">Авто · по референсу</option><option value="1:1">1:1</option><option value="2:3">2:3</option><option value="3:2">3:2</option><option value="3:4">3:4</option><option value="4:3">4:3</option><option value="4:5">4:5</option><option value="5:4">5:4</option><option value="9:16">9:16</option><option value="16:9">16:9</option></select></label>
            <label><span>Результатов</span><input id="promptEditorCount" type="number" min="1" max="20" /></label>
            <label><span>Качество</span><select id="promptEditorQuality"><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select></label>
          </div>
          <div class="prompt-editor-model-name" id="promptEditorModelName"></div>
        </section>
        <div class="prompt-editor-message" id="promptEditorMessage"></div>
      </div>
      <div class="prompt-editor-footer">
        <button class="secondary-btn" id="promptEditorGenerate" type="button"><span>✦</span> Генерировать</button>
        <button class="primary-btn" id="promptEditorSave" type="button">Сохранить</button>
      </div>
    </aside>`);

  const panel = document.querySelector('#promptEditorPanel');
  const panelEls = {
    title: document.querySelector('#promptEditorTitle'),
    text: document.querySelector('#promptEditorText'),
    promptLock: document.querySelector('#promptEditorPromptLock'),
    referenceLock: document.querySelector('#promptEditorReferenceLock'),
    referenceZone: document.querySelector('#promptEditorReferenceZone'),
    referenceInput: document.querySelector('#promptEditorReferenceInput'),
    referenceImage: document.querySelector('#promptEditorReferenceImage'),
    chooseReference: document.querySelector('#promptEditorChooseReference'),
    pasteReference: document.querySelector('#promptEditorPasteReference'),
    provider: document.querySelector('#promptEditorProvider'),
    aspect: document.querySelector('#promptEditorAspect'),
    count: document.querySelector('#promptEditorCount'),
    quality: document.querySelector('#promptEditorQuality'),
    save: document.querySelector('#promptEditorSave'),
    generate: document.querySelector('#promptEditorGenerate'),
    close: document.querySelector('#promptEditorClose'),
    message: document.querySelector('#promptEditorMessage'),
    promptState: document.querySelector('#promptEditorPromptState'),
    referenceState: document.querySelector('#promptEditorReferenceState'),
    photoCount: document.querySelector('#promptEditorPhotoCount'),
    referenceNumber: document.querySelector('#promptEditorReferenceNumber'),
    modelName: document.querySelector('#promptEditorModelName'),
  };

  const deepCopy = value => structuredClone(value ?? {});
  const currentPromptNode = () => state.project?.nodes?.find(node => node.id === state.promptEditorNodeId && node.node_type === 'prompt') || null;
  const nodeHasUnsavedChanges = nodeId => state.dirtyNodes.has(nodeId) || (state.promptEditorNodeId === nodeId && state.promptEditorDirty);

  function revokeReferencePreview() {
    if (state.promptEditorReferencePreviewUrl) URL.revokeObjectURL(state.promptEditorReferencePreviewUrl);
    state.promptEditorReferencePreviewUrl = null;
  }

  function normalizedPromptConfig(config = {}) {
    const normalized = deepCopy(config);
    normalized.provider ||= 'openai';
    normalized.model ||= defaultModel(normalized.provider);
    normalized.aspect_ratio ||= 'auto';
    normalized.detected_aspect_ratio ||= '1:1';
    normalized.output_count = Math.max(1, Math.min(20, Number(normalized.output_count) || 1));
    normalized.quality ||= 'high';
    normalized.prompt_text ||= '';
    normalized.prompt_locked = Boolean(normalized.prompt_locked);
    normalized.reference_locked = Boolean(normalized.reference_locked);
    return normalized;
  }

  function setEditorDirty(dirty = true) {
    state.promptEditorDirty = dirty;
    panel.classList.toggle('dirty', dirty);
    panelEls.save.disabled = state.promptEditorSaving || !dirty || state.projectReadOnly;
    updateDirtyUI();
  }

  function readEditorDraft() {
    if (!state.promptEditorDraft) return null;
    const draft = state.promptEditorDraft;
    draft.title = panelEls.title.value.trim() || 'Без названия';
    draft.config.prompt_text = panelEls.text.value;
    const nextProvider = panelEls.provider.value;
    if (draft.config.provider !== nextProvider) draft.config.model = defaultModel(nextProvider);
    draft.config.provider = nextProvider;
    draft.config.aspect_ratio = panelEls.aspect.value;
    draft.config.output_count = Math.max(1, Math.min(20, Number(panelEls.count.value) || 1));
    draft.config.quality = panelEls.quality.value;
    return draft;
  }

  function renderEditorLockState() {
    const draft = state.promptEditorDraft;
    if (!draft) return;
    const readonly = state.projectReadOnly;
    panelEls.text.readOnly = readonly || draft.config.prompt_locked;
    panelEls.promptLock.disabled = readonly;
    panelEls.promptLock.classList.toggle('locked', draft.config.prompt_locked);
    panelEls.promptLock.textContent = draft.config.prompt_locked ? '🔒 Открыть' : '🔓 Закрыть';
    panelEls.promptState.textContent = draft.config.prompt_locked ? 'Закрыт от изменений' : 'Доступен для редактирования';

    panelEls.referenceLock.disabled = readonly;
    panelEls.referenceLock.classList.toggle('locked', draft.config.reference_locked);
    panelEls.referenceLock.textContent = draft.config.reference_locked ? '🔒 Открыть' : '🔓 Закрыть';
    panelEls.referenceState.textContent = draft.config.reference_locked ? 'Закрыт от замены' : 'Доступен для замены';
    panelEls.chooseReference.disabled = readonly || draft.config.reference_locked;
    panelEls.pasteReference.disabled = readonly || draft.config.reference_locked;
    panelEls.referenceZone.classList.toggle('locked', readonly || draft.config.reference_locked);
  }

  function updateEditorReferencePreview() {
    const node = currentPromptNode();
    const saved = node && referenceAsset(node);
    const src = state.promptEditorReferencePreviewUrl || saved?.url || '';
    panelEls.referenceZone.classList.toggle('has-image', Boolean(src));
    panelEls.referenceImage.src = src;
  }

  function fillEditor(node) {
    const config = normalizedPromptConfig(node.config || {});
    state.promptEditorOriginal = {title: node.title, config: deepCopy(config)};
    state.promptEditorDraft = {title: node.title, config: deepCopy(config)};
    state.promptEditorReferenceFile = null;
    revokeReferencePreview();

    panelEls.title.value = node.title;
    panelEls.text.value = config.prompt_text;
    panelEls.provider.value = config.provider;
    panelEls.aspect.value = config.aspect_ratio;
    panelEls.count.value = config.output_count;
    panelEls.quality.value = config.quality;
    panelEls.referenceNumber.textContent = `Референс №${config.reference_number ?? '—'}`;
    panelEls.photoCount.textContent = pluralPhotos(uploadedPhotoCount());
    panelEls.modelName.textContent = `Используется модель: ${config.model || defaultModel(config.provider)}`;
    panelEls.message.textContent = state.projectReadOnly ? 'Проект доступен только для просмотра.' : '';
    panelEls.title.readOnly = state.projectReadOnly;
    [panelEls.provider, panelEls.aspect, panelEls.count, panelEls.quality].forEach(control => { control.disabled = state.projectReadOnly; });
    panelEls.generate.disabled = state.projectReadOnly;
    renderEditorLockState();
    updateEditorReferencePreview();
    setEditorDirty(false);
  }

  function openPromptEditor(nodeId) {
    const node = state.project?.nodes?.find(item => item.id === nodeId && item.node_type === 'prompt');
    if (!node) return;
    if (state.promptEditorNodeId && state.promptEditorNodeId !== nodeId && state.promptEditorDirty) {
      if (!confirm('Закрыть блок без сохранения изменений?')) return;
    }
    state.promptEditorNodeId = nodeId;
    fillEditor(node);
    panel.classList.add('open');
    panel.setAttribute('aria-hidden', 'false');
    document.body.classList.add('prompt-editor-open');
    selectNode(nodeId, false);
  }

  function closePromptEditor({force = false} = {}) {
    if (!force && state.promptEditorDirty && !confirm('Закрыть блок без сохранения изменений?')) return false;
    revokeReferencePreview();
    state.promptEditorNodeId = null;
    state.promptEditorDraft = null;
    state.promptEditorOriginal = null;
    state.promptEditorReferenceFile = null;
    state.promptEditorDirty = false;
    panel.classList.remove('open', 'dirty');
    panel.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('prompt-editor-open');
    updateDirtyUI();
    return true;
  }

  function stageReferenceFile(file) {
    if (!file?.type?.startsWith('image/')) return toast('Выберите изображение', 'error');
    if (!state.promptEditorDraft || state.promptEditorDraft.config.reference_locked) return toast('Сначала откройте референс', 'error');
    revokeReferencePreview();
    state.promptEditorReferenceFile = file;
    state.promptEditorReferencePreviewUrl = URL.createObjectURL(file);
    updateEditorReferencePreview();
    setEditorDirty(true);
  }

  async function fetchProjectPreservingLocalChanges(resetView = false) {
    if (!state.project) return;
    const projectId = state.project.id;
    const dirtyNodes = new Map([...state.dirtyNodes.entries()].map(([id, value]) => [id, deepCopy(value)]));
    const dirtyProject = deepCopy(state.dirtyProject);
    const currentView = {...state.view};
    const fresh = await api(`/api/projects/${projectId}`);

    for (const [nodeId, changes] of dirtyNodes.entries()) {
      const node = fresh.nodes.find(item => item.id === nodeId);
      if (!node) continue;
      if ('title' in changes) node.title = changes.title;
      if ('x' in changes) node.x = changes.x;
      if ('y' in changes) node.y = changes.y;
      if (changes.config) node.config = {...(node.config || {}), ...deepCopy(changes.config)};
    }
    if (dirtyProject.title) fresh.title = dirtyProject.title;
    state.project = fresh;
    state.dirtyNodes = dirtyNodes;
    state.dirtyProject = dirtyProject;
    if (!resetView) state.view = currentView;
    else state.view = {
      x: Number(fresh.viewport?.x ?? 80),
      y: Number(fresh.viewport?.y ?? 80),
      zoom: Number(fresh.viewport?.zoom ?? 1),
    };
    state.edgeStyle = dirtyProject.viewport?.edge_style || fresh.viewport?.edge_style || state.edgeStyle;
    renderCanvas();
    if (state.promptEditorNodeId) panelEls.photoCount.textContent = pluralPhotos(uploadedPhotoCount());
    updateDirtyUI();
    refreshProjectsQuietly();
  }

  async function savePromptEditor({close = true, silent = false} = {}) {
    const node = currentPromptNode();
    if (!node || !state.promptEditorDraft) return false;
    if (state.projectReadOnly) return false;
    const draft = readEditorDraft();
    state.promptEditorSaving = true;
    panel.classList.add('saving');
    panelEls.save.disabled = true;
    panelEls.generate.disabled = true;
    panelEls.message.textContent = 'Сохранение…';
    try {
      const pending = deepCopy(state.dirtyNodes.get(node.id) || {});
      const changes = {title: draft.title, config: draft.config};
      if ('x' in pending) changes.x = pending.x;
      if ('y' in pending) changes.y = pending.y;
      await api(`/api/projects/${state.project.id}/save`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({project: {}, nodes: [{id: node.id, changes}]}),
      });
      state.dirtyNodes.delete(node.id);
      if (state.promptEditorReferenceFile) {
        const form = new FormData();
        form.append('file', state.promptEditorReferenceFile, state.promptEditorReferenceFile.name || `reference-${Date.now()}.png`);
        await api(`/api/canvas/nodes/${node.id}/reference`, {method: 'POST', body: form});
      }
      state.promptEditorReferenceFile = null;
      revokeReferencePreview();
      state.promptEditorDirty = false;
      await fetchProjectPreservingLocalChanges(false);
      panelEls.message.textContent = 'Изменения сохранены.';
      if (!silent) toast('Блок сохранён', 'success');
      if (close) closePromptEditor({force: true});
      else {
        const freshNode = currentPromptNode();
        if (freshNode) fillEditor(freshNode);
      }
      return true;
    } catch (error) {
      panelEls.message.textContent = error.message;
      toast(error.message, 'error');
      return false;
    } finally {
      state.promptEditorSaving = false;
      panel.classList.remove('saving');
      panelEls.generate.disabled = state.projectReadOnly;
      panelEls.save.disabled = !state.promptEditorDirty || state.projectReadOnly;
      updateDirtyUI();
    }
  }

  function markEditorInput() {
    if (!state.promptEditorDraft || state.projectReadOnly) return;
    readEditorDraft();
    panelEls.modelName.textContent = `Используется модель: ${state.promptEditorDraft.config.model || defaultModel(panelEls.provider.value)}`;
    setEditorDirty(true);
  }

  [panelEls.title, panelEls.text, panelEls.provider, panelEls.aspect, panelEls.count, panelEls.quality].forEach(control => {
    control.addEventListener(control.tagName === 'SELECT' ? 'change' : 'input', markEditorInput);
  });

  panelEls.promptLock.addEventListener('click', () => {
    if (!state.promptEditorDraft || state.projectReadOnly) return;
    state.promptEditorDraft.config.prompt_locked = !state.promptEditorDraft.config.prompt_locked;
    renderEditorLockState();
    setEditorDirty(true);
  });
  panelEls.referenceLock.addEventListener('click', () => {
    if (!state.promptEditorDraft || state.projectReadOnly) return;
    state.promptEditorDraft.config.reference_locked = !state.promptEditorDraft.config.reference_locked;
    renderEditorLockState();
    setEditorDirty(true);
  });
  panelEls.chooseReference.addEventListener('click', () => panelEls.referenceInput.click());
  panelEls.referenceZone.addEventListener('click', () => {
    if (!state.promptEditorDraft?.config.reference_locked && !state.projectReadOnly) panelEls.referenceInput.click();
  });
  panelEls.referenceInput.addEventListener('change', () => {
    if (panelEls.referenceInput.files?.[0]) stageReferenceFile(panelEls.referenceInput.files[0]);
    panelEls.referenceInput.value = '';
  });
  panelEls.referenceZone.addEventListener('dragover', event => { event.preventDefault(); panelEls.referenceZone.classList.add('dragover'); });
  panelEls.referenceZone.addEventListener('dragleave', () => panelEls.referenceZone.classList.remove('dragover'));
  panelEls.referenceZone.addEventListener('drop', event => {
    event.preventDefault();
    panelEls.referenceZone.classList.remove('dragover');
    stageReferenceFile(event.dataTransfer.files?.[0]);
  });
  panelEls.pasteReference.addEventListener('click', async () => {
    const file = await readClipboardImage();
    if (!file) return toast('В буфере обмена нет изображения или браузер не дал доступ', 'error');
    stageReferenceFile(file);
  });
  panelEls.close.addEventListener('click', () => closePromptEditor());
  panelEls.save.addEventListener('click', () => savePromptEditor({close: true}));
  panelEls.generate.addEventListener('click', async () => {
    const saved = await savePromptEditor({close: false, silent: true});
    if (!saved) return;
    const node = currentPromptNode();
    const article = document.querySelector(`.prompt-node[data-node-id="${node?.id}"]`);
    if (!node || !article) return;
    panelEls.message.textContent = 'Запускаем генерацию…';
    await startGeneration(node, article);
    panelEls.message.textContent = 'Генерация запущена.';
  });

  hasUnsavedChanges = function hasUnsavedChangesWithEditor() {
    return original.hasUnsavedChanges() || state.promptEditorDirty;
  };

  configurePromptNode = function configureCompactPromptNode(article, node) {
    const config = normalizedPromptConfig(node.config || {});
    node.config = config;
    const ref = referenceAsset(node);
    const readyPhotoCount = uploadedPhotoCount();
    const totalPhotoCount = projectPhotoNodes().length;
    const hasPrompt = Boolean(config.prompt_text.trim());

    article.classList.toggle('has-reference', Boolean(ref));
    article.classList.toggle('has-prompt', hasPrompt);
    $('.reference-number', article).textContent = `Референс №${config.reference_number ?? '—'}`;
    $('.prompt-connected-label', article).style.display = hasPrompt ? '' : 'none';
    $('.prompt-connected-icon', article).style.display = hasPrompt ? '' : 'none';
    $('.prompt-empty-label', article).style.display = hasPrompt ? 'none' : '';
    const refImage = $('.prompt-card-reference-image', article);
    if (ref) refImage.src = ref.url;
    else refImage.removeAttribute('src');
    refImage.loading = 'lazy';
    refImage.decoding = 'async';

    $('.connection-count', article).textContent = pluralPhotos(readyPhotoCount);
    $('.connections-summary', article).title = `${readyPhotoCount} из ${totalPhotoCount} фото-блоков содержат загруженные изображения`;

    const providerSelect = $('.provider-select', article);
    const aspectSelect = $('.aspect-ratio', article);
    const countInput = $('.output-count', article);
    const qualitySelect = $('.image-quality', article);
    providerSelect.value = config.provider;
    aspectSelect.value = config.aspect_ratio;
    countInput.value = config.output_count;
    qualitySelect.value = config.quality;
    $('.detected-ratio', article).textContent = config.aspect_ratio === 'auto' ? `Референс: ${config.detected_aspect_ratio}` : '';
    [providerSelect, aspectSelect, countInput, qualitySelect].forEach(control => {
      control.disabled = state.projectReadOnly;
      control.addEventListener('pointerdown', event => event.stopPropagation());
    });

    providerSelect.addEventListener('change', () => {
      snapshotForUndo();
      config.provider = providerSelect.value;
      config.model = defaultModel(config.provider);
      scheduleNodeConfigSave(node);
      renderNodeProviderStatus(article, config.provider);
    });
    aspectSelect.addEventListener('change', () => {
      snapshotForUndo();
      config.aspect_ratio = aspectSelect.value;
      $('.detected-ratio', article).textContent = config.aspect_ratio === 'auto' ? `Референс: ${config.detected_aspect_ratio}` : '';
      scheduleNodeConfigSave(node);
    });
    countInput.addEventListener('change', () => {
      snapshotForUndo();
      config.output_count = Math.max(1, Math.min(20, Number(countInput.value) || 1));
      countInput.value = config.output_count;
      scheduleNodeConfigSave(node);
      updateGenerateAvailability(article, node);
    });
    qualitySelect.addEventListener('change', () => {
      snapshotForUndo();
      config.quality = qualitySelect.value;
      scheduleNodeConfigSave(node);
    });

    const title = $('.node-title', article);
    title.readOnly = true;
    title.addEventListener('click', event => { event.stopPropagation(); openPromptEditor(node.id); });
    $('.prompt-card-reference', article).addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openPromptEditor(node.id); }
    });

    let pointerStart = null;
    article.addEventListener('pointerdown', event => { pointerStart = {x: event.clientX, y: event.clientY}; }, true);
    article.addEventListener('click', event => {
      if (state.noteLinkSourceId) return;
      if (event.target.closest('button,select,input,a,.result-card,.edge-handle')) return;
      if (pointerStart && Math.hypot(event.clientX - pointerStart.x, event.clientY - pointerStart.y) > 7) return;
      event.stopPropagation();
      openPromptEditor(node.id);
    });

    $('.generate-btn', article).addEventListener('click', event => {
      event.stopPropagation();
      startGeneration(node, article).catch(error => toast(error.message, 'error'));
    });
    renderNodeProviderStatus(article, config.provider);
    renderGenerationState(article, node);
    updateGenerateAvailability(article, node);
  };

  startGeneration = async function startGenerationWithoutAutosave(node, article) {
    if (!canEditProject()) return toast('Проект AI-агента доступен только для просмотра', 'error');
    if (nodeHasUnsavedChanges(node.id)) {
      toast('Сначала сохраните изменения этого блока', 'error');
      return false;
    }
    const savedNode = state.project?.nodes?.find(item => item.id === node.id);
    if (!savedNode) return false;
    const hasPrompt = Boolean(String(savedNode.config?.prompt_text || '').trim());
    const hasRef = Boolean(referenceAsset(savedNode));
    if (!hasPrompt || !hasRef || uploadedPhotoCount() < 1) {
      toast('Для генерации нужны сохранённые промпт, референс и фото заказчика', 'error');
      return false;
    }
    const button = $('.generate-btn', article);
    button.disabled = true;
    button.classList.add('running');
    $('.generate-label', article).textContent = 'Запускаем…';
    const result = await api(`/api/canvas/nodes/${savedNode.id}/generate`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({output_count: Number(savedNode.config.output_count || 1)}),
    });
    savedNode.generations = [...(savedNode.generations || []), result];
    savedNode.latest_generation = result;
    renderGenerationState(article, savedNode);
    toast(`Запущена только генерация №${savedNode.config.reference_number}`, 'success');
    return true;
  };

  uploadNodeImage = async function uploadImageWithoutAutosave(node, endpointKind, file) {
    if (!canEditProject()) return toast('Проект AI-агента доступен только для просмотра', 'error');
    if (!file?.type?.startsWith('image/')) return toast('Выберите изображение', 'error');
    if (endpointKind === 'reference' && node.config?.reference_locked) return toast('Сначала откройте референс и сохраните блок', 'error');
    const form = new FormData();
    form.append('file', file, file.name || `clipboard-${Date.now()}.png`);
    setSaveStatus('saving', 'Загрузка…');
    try {
      await api(`/api/canvas/nodes/${node.id}/${endpointKind}`, {method: 'POST', body: form});
      await fetchProjectPreservingLocalChanges(false);
      updateDirtyUI();
      toast(endpointKind === 'photo' ? 'Фото заказчика загружено' : 'Референс загружен', 'success');
    } catch (error) {
      setSaveStatus('error');
      toast(error.message, 'error');
    }
  };

  reloadCurrentProject = async function reloadWithoutAutosave(resetView = false) {
    return fetchProjectPreservingLocalChanges(resetView);
  };

  openProject = async function openProjectWithoutAutosave(projectId, closeDrawer = true) {
    if (state.project?.id === projectId) {
      if (closeDrawer) { closeProjectsDrawer(); return state.project; }
      await fetchProjectPreservingLocalChanges(false);
      return state.project;
    }
    if (state.project && hasUnsavedChanges()) {
      if (!confirm('В проекте есть несохранённые изменения. Перейти и потерять их?')) return null;
      state.dirtyNodes.clear();
      state.dirtyProject = {};
      updateDirtyUI();
    }
    if (state.promptEditorNodeId) closePromptEditor({force: true});
    return original.openProject(projectId, closeDrawer);
  };

  duplicateSelectedObjects = async function duplicateOnlySavedObjects() {
    if (hasUnsavedChanges()) return toast('Сначала сохраните изменения проекта', 'error');
    return original.duplicateSelectedObjects();
  };

  saveAllChanges = async function saveAllExplicitly(options = {}) {
    if (state.promptEditorDirty) {
      const saved = await savePromptEditor({close: false, silent: true});
      if (!saved) return false;
    }
    return original.saveAllChanges(options);
  };

  document.addEventListener('click', event => {
    const deleteButton = event.target.closest('.prompt-node .delete-node');
    if (!deleteButton) return;
    const nodeId = deleteButton.closest('.prompt-node')?.dataset.nodeId;
    if (!nodeId || nodeId !== state.promptEditorNodeId) return;
    setTimeout(() => {
      if (!state.project?.nodes?.some(node => node.id === nodeId)) closePromptEditor({force: true});
    }, 0);
  }, true);

  document.addEventListener('click', event => {
    if (!event.target.closest('.project-duplicate') || !hasUnsavedChanges()) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    toast('Сначала сохраните изменения проекта', 'error');
  }, true);

  document.querySelector('#projectForm')?.addEventListener('submit', event => {
    const form = event.currentTarget;
    const baseId = form.project_type?.value === 'agent' ? form.base_project_id?.value : '';
    if (!baseId || baseId !== state.project?.id || !hasUnsavedChanges()) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    toast('Сначала сохраните изменения проекта-основы', 'error');
  }, true);

  window.addEventListener('keydown', event => {
    if (event.key === 'Escape' && panel.classList.contains('open')) {
      event.stopImmediatePropagation();
      closePromptEditor();
    }
  }, true);

  window.addEventListener('paste', event => {
    const file = imageFileFromPasteEvent(event);
    if (!file) return;
    const promptArticle = event.target?.closest?.('.prompt-node');
    if (!panel.classList.contains('open') && !promptArticle) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (!panel.classList.contains('open') && promptArticle) openPromptEditor(promptArticle.dataset.nodeId);
    stageReferenceFile(file);
  }, true);

  function optimizeImages(root = document) {
    root.querySelectorAll?.('img').forEach(image => {
      image.loading = 'lazy';
      image.decoding = 'async';
    });
  }
  optimizeImages();
  new MutationObserver(records => {
    for (const record of records) for (const node of record.addedNodes) {
      if (node.nodeType === Node.ELEMENT_NODE) optimizeImages(node);
    }
  }).observe(document.body, {childList: true, subtree: true});

  if (state.project) renderCanvas();
  updateDirtyUI();
})();
