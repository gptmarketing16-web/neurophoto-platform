(() => {
  'use strict';

  const ASSET_PATTERN = /^\/api\/canvas\/assets\/([^/?#]+)(?:[?#].*)?$/;

  function directAssetUrl(url) {
    const value = String(url || '');
    if (value.endsWith('/direct')) return value;
    const match = value.match(ASSET_PATTERN);
    return match ? `/api/canvas/assets/${match[1]}/direct` : value;
  }

  function tuneImage(image) {
    if (!(image instanceof HTMLImageElement)) return;
    if (!image.closest('.node, .prompt-editor-panel')) return;

    image.loading = 'eager';
    image.decoding = 'async';
    image.fetchPriority = 'auto';

    const current = image.getAttribute('src') || '';
    const direct = directAssetUrl(current);
    if (direct === current) return;

    image.dataset.proxyAssetSrc = current;
    image.addEventListener('error', () => {
      const fallback = image.dataset.proxyAssetSrc;
      if (!fallback || image.dataset.proxyAssetFallback === '1') return;
      image.dataset.proxyAssetFallback = '1';
      image.src = fallback;
    }, {once: true});
    image.src = direct;
  }

  function tuneImages(root = document) {
    if (root instanceof HTMLImageElement) tuneImage(root);
    root.querySelectorAll?.('img').forEach(tuneImage);
  }

  function generationSignature(generation) {
    if (!generation) return null;
    return {
      id: generation.id,
      status: generation.status,
      error_message: generation.error_message,
      started_at: generation.started_at,
      completed_at: generation.completed_at,
      outputs: (generation.outputs || []).map(output => [
        output.id,
        output.url,
        output.expires_at,
      ]),
    };
  }

  function nodeSignature(node) {
    return JSON.stringify([
      node.node_type,
      node.title,
      Number(node.x || 0),
      Number(node.y || 0),
      node.config || {},
      (node.assets || []).map(asset => [
        asset.id,
        asset.kind,
        asset.url,
        asset.expires_at,
      ]),
      generationSignature(node.latest_generation),
    ]);
  }

  function buildNodeElement(node, signature) {
    const article = nodeTemplate(node).content.firstElementChild.cloneNode(true);
    article.dataset.nodeId = node.id;
    article.dataset.renderSignature = signature;
    article.style.left = `${node.x}px`;
    article.style.top = `${node.y}px`;
    article.classList.toggle('selected', state.selectedNodeIds.has(node.id));
    $('.node-title', article).value = node.title;
    bindCommonNode(article, node);
    if (node.node_type === 'photo') configurePhotoNode(article, node);
    else if (node.node_type === 'note') configureNoteNode(article, node);
    else configurePromptNode(article, node);
    tuneImages(article);
    return article;
  }

  renderCanvas = function renderCanvasIncrementally() {
    applyView();
    const projectNodes = state.project?.nodes || [];
    const existing = new Map(
      [...nodesLayer.children]
        .filter(element => element.dataset?.nodeId)
        .map(element => [element.dataset.nodeId, element]),
    );
    const activeIds = new Set();

    for (const node of projectNodes) {
      activeIds.add(node.id);
      const signature = nodeSignature(node);
      const current = existing.get(node.id);
      if (!current) {
        nodesLayer.appendChild(buildNodeElement(node, signature));
      } else if (current.dataset.renderSignature !== signature) {
        current.replaceWith(buildNodeElement(node, signature));
      } else {
        current.classList.toggle('selected', state.selectedNodeIds.has(node.id));
      }
    }

    for (const [nodeId, element] of existing.entries()) {
      if (!activeIds.has(nodeId)) element.remove();
    }

    emptyCanvas.classList.toggle('hidden', Boolean(projectNodes.length));
    $('#projectTitle').value = state.project?.title || 'Выберите проект';
    requestAnimationFrame(() => {
      drawEdges();
      renderMinimap();
      updateExpiryLabels();
    });
  };

  function updateCurrentProjectSummary() {
    if (!state.project) return;
    const summary = state.projects.find(item => item.id === state.project.id);
    if (!summary) return;
    summary.title = state.project.title;
    summary.updated_at = state.project.updated_at;
    summary.photo_count = projectPhotoNodes().length;
    summary.prompt_count = projectPromptNodes().length;
  }

  addNode = async function addNodeInstantly(type, position = null, showToast = true) {
    if (!canEditProject() && state.project) return toast('Проект AI-агента доступен только для просмотра', 'error');
    if (!state.project) { openProjectModal(); return null; }

    const coordinates = position || nextNodePosition(type);
    setSaveStatus('saving', 'Добавление…');
    try {
      const node = await api(`/api/projects/${state.project.id}/nodes/instant-create`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({node_type: type, ...coordinates}),
      });
      state.project.nodes.push(node);
      state.project.updated_at = node.updated_at || new Date().toISOString();
      state.selectedNodeId = node.id;
      state.selectedNodeIds = new Set([node.id]);
      updateCurrentProjectSummary();
      renderCanvas();
      updateDirtyUI();
      if (showToast) {
        const message = type === 'photo'
          ? 'Добавлен блок фото заказчика'
          : type === 'note'
            ? 'Добавлена заметка'
            : `Добавлен промпт №${node.config.reference_number}`;
        toast(message, 'success');
      }
      return node;
    } catch (error) {
      setSaveStatus('error');
      toast(error.message, 'error');
      return null;
    }
  };

  tuneImages();
  new MutationObserver(records => {
    for (const record of records) {
      for (const added of record.addedNodes) {
        if (added.nodeType === Node.ELEMENT_NODE) tuneImages(added);
      }
    }
  }).observe(document.body, {childList: true, subtree: true});

  if (state.project) renderCanvas();
})();
