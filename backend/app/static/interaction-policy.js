(() => {
  'use strict';

  const VIEW_STORAGE_PREFIX = 'neurophoto_local_view:';
  const MAX_UPLOAD_DIMENSION = 3072;
  const MAX_UPLOAD_BYTES_WITHOUT_OPTIMIZATION = 5 * 1024 * 1024;
  const JPEG_QUALITY = 0.92;

  function localViewKey(projectId) {
    return `${VIEW_STORAGE_PREFIX}${projectId}`;
  }

  function persistLocalView() {
    if (!state.project) return;
    storageSet(localViewKey(state.project.id), JSON.stringify({
      x: Number(state.view.x || 0),
      y: Number(state.view.y || 0),
      zoom: Number(state.view.zoom || 1),
    }));
  }

  function restoreLocalView(projectId) {
    if (!projectId || state.project?.id !== projectId) return;
    const raw = storageGet(localViewKey(projectId));
    if (!raw) return;
    try {
      const saved = JSON.parse(raw);
      state.view = {
        x: Number.isFinite(Number(saved.x)) ? Number(saved.x) : state.view.x,
        y: Number.isFinite(Number(saved.y)) ? Number(saved.y) : state.view.y,
        zoom: Math.max(.15, Math.min(2.5, Number(saved.zoom) || state.view.zoom)),
      };
      applyView();
    } catch (_) {}
  }

  // Moving and zooming the workspace is a local viewing preference, not a project edit.
  scheduleViewportSave = function scheduleViewportLocally() {
    persistLocalView();
  };
  if (state.dirtyProject?.viewport) {
    delete state.dirtyProject.viewport;
    updateDirtyUI();
  }

  const currentOpenProject = openProject;
  openProject = async function openProjectWithLocalView(projectId, closeDrawer = true) {
    const result = await currentOpenProject(projectId, closeDrawer);
    if (result !== null && state.project?.id === projectId) restoreLocalView(projectId);
    return result;
  };

  // Arrow style is an actual project setting and remains an explicit unsaved change.
  document.querySelectorAll('[data-edge-style]').forEach(button => {
    button.addEventListener('click', () => {
      if (!canEditProject() || !state.project) return;
      mergeDirtyProject({
        viewport: {...state.view, edge_style: state.edgeStyle},
      });
    });
  });

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

  addNode = async function addNodeFast(type, position = null, showToast = true) {
    if (!canEditProject() && state.project) return toast('Проект AI-агента доступен только для просмотра', 'error');
    if (!state.project) { openProjectModal(); return null; }

    try {
      const node = await api(`/api/projects/${state.project.id}/nodes/fast-create`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({node_type: type, ...(position || nextNodePosition(type))}),
      });
      state.project.nodes.push(node);
      state.project.updated_at = node.updated_at || new Date().toISOString();
      state.selectedNodeId = node.id;
      state.selectedNodeIds = new Set([node.id]);
      renderCanvas();
      syncCurrentProjectSummary();
      updateDirtyUI();
      if (showToast) {
        const message = type === 'photo'
          ? 'Добавлен блок фото заказчика'
          : type === 'note'
            ? 'Добавлена заметка'
            : `Добавлен промпт №${node.config.reference_number}. Все фото связаны автоматически.`;
        toast(message, 'success');
      }
      return node;
    } catch (error) {
      toast(error.message, 'error');
      return null;
    }
  };

  function localFormatBytes(bytes) {
    if (!bytes) return '0 Б';
    const units = ['Б', 'КБ', 'МБ', 'ГБ'];
    const index = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
    return `${(bytes / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
  }

  async function decodeImage(file) {
    if (!file) return null;
    if (typeof createImageBitmap === 'function') {
      try {
        const bitmap = await createImageBitmap(file);
        return {
          source: bitmap,
          width: bitmap.width,
          height: bitmap.height,
          close: () => bitmap.close?.(),
        };
      } catch (_) {}
    }
    return new Promise(resolve => {
      const url = URL.createObjectURL(file);
      const image = new Image();
      image.onload = () => resolve({
        source: image,
        width: image.naturalWidth,
        height: image.naturalHeight,
        close: () => URL.revokeObjectURL(url),
      });
      image.onerror = () => {
        URL.revokeObjectURL(url);
        resolve(null);
      };
      image.src = url;
    });
  }

  function canvasToBlob(canvas, type, quality) {
    return new Promise(resolve => canvas.toBlob(resolve, type, quality));
  }

  async function prepareImageForUpload(file) {
    const fallback = {
      file,
      dimensions: null,
      optimized: false,
      originalBytes: Number(file?.size || 0),
      uploadBytes: Number(file?.size || 0),
    };
    const decoded = await decodeImage(file);
    if (!decoded) return fallback;

    const sourceWidth = Number(decoded.width || 0);
    const sourceHeight = Number(decoded.height || 0);
    const longestSide = Math.max(sourceWidth, sourceHeight);
    const mustResize = longestSide > MAX_UPLOAD_DIMENSION;
    const mustCompress = Number(file.size || 0) > MAX_UPLOAD_BYTES_WITHOUT_OPTIMIZATION;

    if (!mustResize && !mustCompress) {
      decoded.close();
      return {...fallback, dimensions: {width: sourceWidth, height: sourceHeight}};
    }

    try {
      const scale = mustResize ? MAX_UPLOAD_DIMENSION / longestSide : 1;
      const width = Math.max(1, Math.round(sourceWidth * scale));
      const height = Math.max(1, Math.round(sourceHeight * scale));
      const canvas = document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext('2d', {alpha: false});
      if (!context) return {...fallback, dimensions: {width: sourceWidth, height: sourceHeight}};
      context.imageSmoothingEnabled = true;
      context.imageSmoothingQuality = 'high';
      context.fillStyle = '#fff';
      context.fillRect(0, 0, width, height);
      context.drawImage(decoded.source, 0, 0, width, height);
      const blob = await canvasToBlob(canvas, 'image/jpeg', JPEG_QUALITY);
      if (!blob || (!mustResize && blob.size >= file.size)) {
        return {...fallback, dimensions: {width: sourceWidth, height: sourceHeight}};
      }
      const base = String(file.name || `upload-${Date.now()}`).replace(/\.[^.]+$/, '') || `upload-${Date.now()}`;
      const optimizedFile = new File([blob], `${base}.jpg`, {
        type: 'image/jpeg',
        lastModified: file.lastModified || Date.now(),
      });
      return {
        file: optimizedFile,
        dimensions: {width, height},
        optimized: true,
        originalBytes: Number(file.size || 0),
        uploadBytes: Number(optimizedFile.size || 0),
      };
    } catch (_) {
      return {...fallback, dimensions: {width: sourceWidth, height: sourceHeight}};
    } finally {
      decoded.close();
    }
  }

  function uploadMessage(prepared) {
    return prepared.optimized
      ? `Загрузка ${localFormatBytes(prepared.uploadBytes)}…`
      : 'Загрузка…';
  }

  function optimizationSuffix(prepared) {
    return prepared.optimized
      ? ` (${localFormatBytes(prepared.originalBytes)} → ${localFormatBytes(prepared.uploadBytes)})`
      : '';
  }

  uploadNodeImage = async function uploadNodeImageManualSave(node, endpointKind, file) {
    if (!canEditProject()) return toast('Проект AI-агента доступен только для просмотра', 'error');
    if (!file?.type?.startsWith('image/')) return toast('Выберите изображение', 'error');
    if (endpointKind === 'reference' && node.config?.reference_locked) return toast('Референс зафиксирован', 'error');

    setSaveStatus('saving', 'Подготовка фото…');
    const prepared = await prepareImageForUpload(file);
    const form = new FormData();
    form.append('file', prepared.file, prepared.file.name || `clipboard-${Date.now()}.jpg`);
    setSaveStatus('saving', uploadMessage(prepared));

    try {
      // Uploading an image never saves other edits or moved blocks.
      const asset = await api(`/api/canvas/nodes/${node.id}/${endpointKind}`, {
        method: 'POST',
        body: form,
      });
      const assetKind = endpointKind === 'photo' ? 'customer_photo' : 'reference';
      node.assets = (node.assets || []).filter(item => item.kind !== assetKind || item.generation_id);
      node.assets.push(asset);
      if (endpointKind === 'reference' && prepared.dimensions) {
        node.config = {...(node.config || {})};
        node.config.reference_width = prepared.dimensions.width;
        node.config.reference_height = prepared.dimensions.height;
      }
      const now = new Date().toISOString();
      node.updated_at = now;
      if (state.project) state.project.updated_at = now;
      renderCanvas();
      syncCurrentProjectSummary();
      updateDirtyUI();
      const label = endpointKind === 'photo' ? 'Фото заказчика загружено' : 'Референс загружен';
      toast(`${label}${optimizationSuffix(prepared)}`, 'success');
      return asset;
    } catch (error) {
      setSaveStatus('error');
      toast(error.message, 'error');
      return null;
    }
  };

  async function createPhotoFromPaste(file) {
    if (!state.project) return openProjectModal();
    const position = canvasPositionFromClient(
      state.lastCanvasPointer?.x,
      state.lastCanvasPointer?.y,
      'photo',
    );
    setSaveStatus('saving', 'Подготовка фото…');
    const prepared = await prepareImageForUpload(file);
    const form = new FormData();
    form.append('x', String(position.x));
    form.append('y', String(position.y));
    form.append('file', prepared.file, prepared.file.name || `clipboard-${Date.now()}.jpg`);
    setSaveStatus('saving', uploadMessage(prepared));

    try {
      const node = await api(`/api/projects/${state.project.id}/nodes/fast-photo`, {
        method: 'POST',
        body: form,
      });
      state.project.nodes.push(node);
      state.project.updated_at = node.updated_at || new Date().toISOString();
      state.selectedNodeId = node.id;
      state.selectedNodeIds = new Set([node.id]);
      state.canvasPasteArmed = false;
      renderCanvas();
      syncCurrentProjectSummary();
      updateDirtyUI();
      toast(`Фото заказчика загружено${optimizationSuffix(prepared)}`, 'success');
      return node;
    } catch (error) {
      setSaveStatus('error');
      toast(error.message, 'error');
      return null;
    }
  }

  handlePastedImage = async function handlePastedImageFast(file, eventTarget) {
    if (state.project && !canEditProject()) return toast('Проект AI-агента доступен только для просмотра', 'error');
    if (!state.project) return openProjectModal();

    if (state.canvasPasteArmed) return createPhotoFromPaste(file);

    if (state.pasteTarget) {
      const node = state.project.nodes.find(item => item.id === state.pasteTarget.nodeId);
      if (node) {
        if (state.pasteTarget.kind === 'reference' && node.config?.reference_locked) return toast('Референс зафиксирован', 'error');
        return uploadNodeImage(node, state.pasteTarget.kind, file);
      }
    }

    const promptArticle = eventTarget?.closest?.('.prompt-node');
    if (promptArticle) {
      const node = state.project.nodes.find(item => item.id === promptArticle.dataset.nodeId);
      if (node?.config?.reference_locked) return toast('Референс зафиксирован', 'error');
      if (node) return uploadNodeImage(node, 'reference', file);
    }

    return createPhotoFromPaste(file);
  };

  // Physical V/H remain unchanged; Russian layout М/Р now works as well.
  window.addEventListener('keydown', event => {
    if (event.ctrlKey || event.metaKey || event.altKey || isEditingTarget(event.target)) return;
    const key = event.key.toLowerCase();
    if (key === 'м') {
      event.preventDefault();
      setToolMode('select');
    } else if (key === 'р') {
      event.preventDefault();
      setToolMode('hand');
    }
  }, true);
})();
