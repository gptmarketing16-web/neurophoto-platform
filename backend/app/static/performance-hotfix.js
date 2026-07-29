(() => {
  'use strict';

  const ASPECT_RATIOS = [
    ['1:8', 1 / 8], ['1:4', 1 / 4], ['2:3', 2 / 3], ['3:4', 3 / 4],
    ['4:5', 4 / 5], ['1:1', 1], ['5:4', 5 / 4], ['4:3', 4 / 3],
    ['3:2', 3 / 2], ['16:9', 16 / 9], ['21:9', 21 / 9], ['4:1', 4], ['8:1', 8],
  ];

  function closestAspectRatio(width, height) {
    if (!width || !height) return '1:1';
    const actual = width / height;
    let best = ASPECT_RATIOS[0];
    let bestDistance = Number.POSITIVE_INFINITY;
    for (const candidate of ASPECT_RATIOS) {
      const distance = Math.abs(Math.log(actual / candidate[1]));
      if (distance < bestDistance) {
        best = candidate;
        bestDistance = distance;
      }
    }
    return best[0];
  }

  async function readImageDimensions(file) {
    if (!file) return null;
    if (typeof createImageBitmap === 'function') {
      try {
        const bitmap = await createImageBitmap(file);
        const result = {width: bitmap.width, height: bitmap.height};
        bitmap.close?.();
        return result;
      } catch (_) {}
    }

    return new Promise(resolve => {
      const url = URL.createObjectURL(file);
      const image = new Image();
      image.onload = () => {
        const result = {width: image.naturalWidth, height: image.naturalHeight};
        URL.revokeObjectURL(url);
        resolve(result);
      };
      image.onerror = () => {
        URL.revokeObjectURL(url);
        resolve(null);
      };
      image.src = url;
    });
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

  saveAllChanges = async function saveAllChangesOptimized({silent = false} = {}) {
    if (state.projectReadOnly) return true;
    if (!state.project || !hasUnsavedChanges()) return true;

    const nodeEntries = [...state.dirtyNodes.entries()].map(([id, changes]) => ({
      id,
      changes: structuredClone(changes),
    }));
    const projectPayload = structuredClone(state.dirtyProject);
    setSaveStatus('saving', 'Сохранение…');
    const button = $('#saveChangesButton');
    if (button) button.disabled = true;

    try {
      const result = await api(`/api/projects/${state.project.id}/save`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({project: projectPayload, nodes: nodeEntries}),
      });

      for (const [id, changes] of nodeEntries.map(item => [item.id, item.changes])) {
        const current = state.dirtyNodes.get(id);
        if (current && JSON.stringify(current) === JSON.stringify(changes)) {
          state.dirtyNodes.delete(id);
        }
      }
      if (JSON.stringify(state.dirtyProject) === JSON.stringify(projectPayload)) {
        state.dirtyProject = {};
      }

      if (result?.updated_at) state.project.updated_at = result.updated_at;
      syncCurrentProjectSummary();
      updateDirtyUI();
      if (!silent) toast('Изменения сохранены', 'success');
      return true;
    } catch (error) {
      setSaveStatus('error');
      if (!silent) toast(error.message, 'error');
      throw error;
    } finally {
      if (button) button.disabled = !hasUnsavedChanges();
    }
  };

  uploadNodeImage = async function uploadNodeImageOptimized(node, endpointKind, file) {
    if (!canEditProject()) return toast('Проект AI-агента доступен только для просмотра', 'error');
    if (!file?.type?.startsWith('image/')) return toast('Выберите изображение', 'error');

    const form = new FormData();
    form.append('file', file, file.name || `clipboard-${Date.now()}.png`);
    const dimensionsPromise = endpointKind === 'reference' ? readImageDimensions(file) : Promise.resolve(null);
    setSaveStatus('saving', 'Загрузка…');

    try {
      if (hasUnsavedChanges()) await saveAllChanges({silent: true});
      const asset = await api(`/api/canvas/nodes/${node.id}/${endpointKind}`, {
        method: 'POST',
        body: form,
      });
      const assetKind = endpointKind === 'photo' ? 'customer_photo' : 'reference';
      node.assets = (node.assets || []).filter(item => item.kind !== assetKind || item.generation_id);
      node.assets.push(asset);

      const dimensions = await dimensionsPromise;
      if (endpointKind === 'reference' && dimensions) {
        node.config = {...(node.config || {})};
        node.config.reference_width = dimensions.width;
        node.config.reference_height = dimensions.height;
        node.config.detected_aspect_ratio = closestAspectRatio(dimensions.width, dimensions.height);
      }

      const now = new Date().toISOString();
      node.updated_at = now;
      if (state.project) state.project.updated_at = now;
      syncCurrentProjectSummary();
      renderCanvas();
      setSaveStatus();
      toast(endpointKind === 'photo' ? 'Фото заказчика загружено' : 'Референс загружен', 'success');
      return asset;
    } catch (error) {
      setSaveStatus('error');
      toast(error.message, 'error');
      return null;
    }
  };

  function optimizeImageElement(image) {
    if (!(image instanceof HTMLImageElement)) return;
    if (!image.matches('.node img, .result-card img, .prompt-editor-panel img')) return;
    image.loading = 'lazy';
    image.decoding = 'async';
  }

  document.querySelectorAll('.node img, .result-card img, .prompt-editor-panel img').forEach(optimizeImageElement);
  const imageObserver = new MutationObserver(mutations => {
    for (const mutation of mutations) {
      for (const added of mutation.addedNodes) {
        if (!(added instanceof Element)) continue;
        if (added.matches?.('img')) optimizeImageElement(added);
        added.querySelectorAll?.('img').forEach(optimizeImageElement);
      }
    }
  });
  imageObserver.observe(document.documentElement, {childList: true, subtree: true});
})();
