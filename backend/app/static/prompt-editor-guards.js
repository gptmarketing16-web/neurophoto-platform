(() => {
  const promptLock = document.querySelector('#promptEditorPromptLock');
  const referenceLock = document.querySelector('#promptEditorReferenceLock');
  const promptText = document.querySelector('#promptEditorText');

  promptLock?.addEventListener('click', event => {
    const original = state.promptEditorOriginal?.config;
    const draft = state.promptEditorDraft?.config;
    if (!original || !draft) return;
    const tryingToRelock = !draft.prompt_locked;
    const changedWhileOriginallyLocked = Boolean(
      tryingToRelock && original.prompt_locked && promptText.value !== (original.prompt_text || '')
    );
    if (!changedWhileOriginallyLocked) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    toast('Сначала сохраните изменённый промпт, затем снова откройте блок и закройте его', 'error');
  }, true);

  referenceLock?.addEventListener('click', event => {
    const draft = state.promptEditorDraft?.config;
    const tryingToRelock = draft && !draft.reference_locked;
    if (!tryingToRelock || !state.promptEditorReferenceFile) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    toast('Сначала сохраните новый референс, затем снова откройте блок и закройте его', 'error');
  }, true);
})();
