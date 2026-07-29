(() => {
  'use strict';

  const ASPECT_RATIOS = [
    ['1:8', 1 / 8], ['1:4', 1 / 4], ['2:3', 2 / 3], ['3:4', 3 / 4],
    ['4:5', 4 / 5], ['1:1', 1], ['5:4', 5 / 4], ['4:3', 4 / 3],
    ['3:2', 3 / 2], ['16:9', 16 / 9], ['21:9', 21 / 9], ['4:1', 4], ['8:1', 8],
  ];
  const MAX_UPLOAD_DIMENSION = 3072;
  const MAX_UPLOAD_BYTES_WITHOUT_OPTIMIZATION = 5 * 1024 * 1024;
  const JPEG_QUALITY = 0.92;

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

  function optimizedFilename(filename) {
    const base = String(filename || `upload-${Date.now()}`).replace(/\.[^.]+$/, '') || `upload-${Date.now()}`;
    return `${base}.jpg`;
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
      if (!blob) return {...fallback, dimensions: {width: sourceWidth, height: sourceHeight}};
      if (!mustResize && blob.size >= file.size) {
        return {...fallback, dimensions: {width: sourceWidth, height: sourceHeight}};
      }
      const optimizedFile = new File([blob], optimizedFilename(file.name), {
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

    setSaveStatus('saving', 'Подготовка фото…');
    const prepared = await prepareImageForUpload(file);
    const uploadFile = prepared.file;
    const form = new FormData();
    form.append('file', uploadFile, uploadFile.name || `clipboard-${Date.now()}.jpg`);
    setSaveStatus(
      'saving',
      prepared.optimized
        ? `Загрузка ${localFormatBytes(prepared.uploadBytes)}…`
        : 'Загрузка…',
    );

    try {
      if (hasUnsavedChanges()) await saveAllChanges({silent: true});
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
        node.config.detected_aspect_ratio = closestAspectRatio(
          prepared.dimensions.width,
          prepared.dimensions.height,
        );
      }

      const now = new Date().toISOString();
      node.updated_at = now;
      if (state.project) state.project.updated_at = now;
      syncCurrentProjectSummary();
      renderCanvas();
      setSaveStatus();
      const label = endpointKind === 'photo' ? 'Фото заказчика загружено' : 'Референс загружен';
      const optimization = prepared.optimized
        ? ` (${localFormatBytes(prepared.originalBytes)} → ${localFormatBytes(prepared.uploadBytes)})`
        : '';
      toast(`${label}${optimization}`, 'success');
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
