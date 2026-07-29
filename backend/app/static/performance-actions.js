(() => {
  'use strict';

  const originalApi = api;

  function rewritePerformanceUrl(url) {
    if (/^\/api\/projects\/[^/]+\/save$/.test(url)) {
      return url.replace(/\/save$/, '/fast-save');
    }
    if (/^\/api\/canvas\/nodes\/[^/]+\/photo$/.test(url)) {
      return url.replace(/\/photo$/, '/fast-photo');
    }
    if (/^\/api\/canvas\/nodes\/[^/]+\/reference$/.test(url)) {
      return url.replace(/\/reference$/, '/fast-reference');
    }
    return url;
  }

  api = function performanceApi(url, options = {}) {
    return originalApi(rewritePerformanceUrl(url), options);
  };

  function deepCopy(value) {
    return structuredClone(value ?? {});
  }

  function syncCurrentProjectSummary() {
    if (!state.project) return;
    const summary = state.projects.find(item => item.id === state.project.id);
    if (!summary) return;
    summary.title = state.project.title;
    summary.updated_at = state.project.updated_at;
    summary.photo_count = projectPhotoNodes().length;
    summary.prompt_count = projectPromptNodes().length;
    renderProjectList();
  }

  deleteSelectedObjects = async function deleteSelectedObjectsFast() {
    if (!canEditProject()) return toast('Проект AI-агента доступен только для просмотра', 'error');
    const ids = selectedNodeIds();
    if (!ids.length || !state.project) return;
    if (!confirm(`Удалить выделенные объекты: ${ids.length}?`)) return;

    setSaveStatus('saving', 'Удаление…');
    try {
      const result = await api(`/api/projects/${state.project.id}/nodes/bulk-delete`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({node_ids: ids}),
      });
      const deleted = new Set(result?.deleted || ids);
      for (const id of deleted) state.dirtyNodes.delete(id);
      state.project.nodes = state.project.nodes.filter(node => !deleted.has(node.id));

      for (const note of projectNoteNodes()) {
        const previous = note.config?.target_node_ids || [];
        const next = previous.filter(id => !deleted.has(id));
        if (next.length !== previous.length) {
          note.config = {...(note.config || {}), target_node_ids: next};
          scheduleNodeConfigSave(note);
        }
      }

      if (result?.updated_at) state.project.updated_at = result.updated_at;
      clearSelection();
      renderCanvas();
      syncCurrentProjectSummary();
      updateDirtyUI();
      setSaveStatus();
      toast(deleted.size > 1 ? `Удалено объектов: ${deleted.size}` : 'Объект удалён', 'success');
    } catch (error) {
      setSaveStatus('error');
      toast(error.message, 'error');
    }
  };

  const panel = document.querySelector('#promptEditorPanel');
  const oldSaveButton = document.querySelector('#promptEditorSave');
  const oldGenerateButton = document.querySelector('#promptEditorGenerate');
  if (!panel || !oldSaveButton || !oldGenerateButton) return;

  const saveButton = oldSaveButton.cloneNode(true);
  const generateButton = oldGenerateButton.cloneNode(true);
  oldSaveButton.replaceWith(saveButton);
  oldGenerateButton.replaceWith(generateButton);

  const editor = {
    title: document.querySelector('#promptEditorTitle'),
    text: document.querySelector('#promptEditorText'),
    provider: document.querySelector('#promptEditorProvider'),
    model: document.querySelector('#promptEditorModel'),
    aspect: document.querySelector('#promptEditorAspect'),
    count: document.querySelector('#promptEditorCount'),
    quality: document.querySelector('#promptEditorQuality'),
    message: document.querySelector('#promptEditorMessage'),
    close: document.querySelector('#promptEditorClose'),
  };

  function currentPromptNode() {
    return state.project?.nodes?.find(
      node => node.id === state.promptEditorNodeId && node.node_type === 'prompt',
    ) || null;
  }

  function readPromptDraft() {
    const draft = state.promptEditorDraft;
    if (!draft) return null;
    draft.title = editor.title.value.trim() || 'Без названия';
    draft.config = {...(draft.config || {})};
    draft.config.prompt_text = editor.text.value;
    draft.config.provider = editor.provider.value === 'gemini' ? 'gemini' : 'openai';
    draft.config.model = editor.model.value || (draft.config.provider === 'gemini' ? 'gemini-3.1-flash-image' : 'gpt-image-2');
    draft.config.aspect_ratio = editor.aspect.value || 'auto';
    draft.config.output_count = Math.max(1, Math.min(20, Number(editor.count.value) || 1));
    draft.config.quality = editor.quality.value || (draft.config.provider === 'gemini' ? '2K' : 'high');
    draft.config.output_format = draft.config.provider === 'gemini' ? 'jpeg' : 'png';
    return draft;
  }

  function updateButtons() {
    const busy = Boolean(state.promptEditorSaving);
    saveButton.disabled = busy || !state.promptEditorDirty || state.projectReadOnly;
    generateButton.disabled = busy || state.projectReadOnly;
  }

  function clearReferencePreview() {
    if (state.promptEditorReferencePreviewUrl) {
      URL.revokeObjectURL(state.promptEditorReferencePreviewUrl);
    }
    state.promptEditorReferencePreviewUrl = null;
  }

  async function fastSavePromptEditor({close = true, silent = false} = {}) {
    const node = currentPromptNode();
    const draft = readPromptDraft();
    if (!node || !draft || state.projectReadOnly) return false;

    state.promptEditorSaving = true;
    panel.classList.add('saving');
    editor.message.textContent = 'Сохранение…';
    updateButtons();

    const referenceFile = state.promptEditorReferenceFile;
    const pending = deepCopy(state.dirtyNodes.get(node.id) || {});
    const changes = {title: draft.title, config: deepCopy(draft.config)};
    if ('x' in pending) changes.x = pending.x;
    if ('y' in pending) changes.y = pending.y;

    try {
      const result = await api(`/api/projects/${state.project.id}/save`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({project: {}, nodes: [{id: node.id, changes}]}),
      });

      node.title = draft.title;
      node.config = deepCopy(draft.config);
      state.dirtyNodes.delete(node.id);
      if (result?.updated_at) state.project.updated_at = result.updated_at;

      state.promptEditorDirty = false;
      panel.classList.remove('dirty');
      if (referenceFile) {
        const asset = await uploadNodeImage(node, 'reference', referenceFile);
        if (!asset) {
          state.promptEditorDirty = true;
          panel.classList.add('dirty');
          throw new Error('Не удалось сохранить новый референс');
        }
      } else {
        renderCanvas();
      }

      state.promptEditorReferenceFile = null;
      clearReferencePreview();
      state.promptEditorOriginal = {title: node.title, config: deepCopy(node.config)};
      state.promptEditorDraft = {title: node.title, config: deepCopy(node.config)};
      state.promptEditorDirty = false;
      panel.classList.remove('dirty');
      syncCurrentProjectSummary();
      updateDirtyUI();
      editor.message.textContent = 'Изменения сохранены.';
      if (!silent) toast('Блок сохранён', 'success');

      if (close) editor.close.click();
      return true;
    } catch (error) {
      editor.message.textContent = error.message;
      toast(error.message, 'error');
      return false;
    } finally {
      state.promptEditorSaving = false;
      panel.classList.remove('saving');
      updateButtons();
    }
  }

  saveButton.addEventListener('click', () => {
    fastSavePromptEditor({close: true}).catch(error => toast(error.message, 'error'));
  });

  generateButton.addEventListener('click', async () => {
    const saved = await fastSavePromptEditor({close: false, silent: true});
    if (!saved) return;
    const node = currentPromptNode();
    const article = document.querySelector(`.prompt-node[data-node-id="${node?.id}"]`);
    if (!node || !article) return;
    editor.message.textContent = 'Запускаем генерацию…';
    const started = await startGeneration(node, article);
    editor.message.textContent = started === false ? 'Генерация не запущена.' : 'Генерация запущена.';
  });

  const buttonObserver = new MutationObserver(updateButtons);
  buttonObserver.observe(panel, {attributes: true, attributeFilter: ['class', 'aria-hidden']});
  panel.addEventListener('input', () => requestAnimationFrame(updateButtons), true);
  panel.addEventListener('change', () => requestAnimationFrame(updateButtons), true);
  panel.addEventListener('click', () => requestAnimationFrame(updateButtons), true);
  updateButtons();
})();
