let currentJob = null;
let slugTimer = null;

async function jsonOrThrow(response) {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || JSON.stringify(body));
  return body;
}

function workspacePublicUrl(slug) {
  return `${location.origin}/${slug}`;
}

async function loadWorkspace() {
  const workspace = await jsonOrThrow(await fetch('/api/workspace'));
  if (!workspace) return;
  const form = document.getElementById('workspaceForm');
  form.display_name.value = workspace.display_name;
  form.tagline.value = workspace.tagline;
  form.slug.value = workspace.slug;
  form.is_public.checked = workspace.is_public;
  renderWorkspace(workspace);
}

function renderWorkspace(workspace) {
  const url = workspacePublicUrl(workspace.slug);
  document.getElementById('workspaceStatus').textContent = `Сохранено: ${workspace.display_name}\nАдрес: /${workspace.slug}`;
  document.getElementById('workspaceUrl').value = url;
  document.getElementById('workspaceLinkRow').hidden = false;
  const availability = document.getElementById('slugAvailability');
  availability.textContent = '✓ Адрес доступен и сохранён';
  availability.className = 'availability ok';
}

async function checkSlug(value) {
  const availability = document.getElementById('slugAvailability');
  if (!value.trim()) {
    availability.textContent = 'Латинские буквы, цифры и символ _';
    availability.className = 'availability';
    return;
  }
  try {
    const result = await jsonOrThrow(await fetch(`/api/workspace/slug-availability?slug=${encodeURIComponent(value)}`));
    if (result.normalized && result.normalized !== value) document.getElementById('slugInput').value = result.normalized;
    availability.textContent = result.available ? `✓ /${result.normalized} свободен` : `× ${result.reason}`;
    availability.className = `availability ${result.available ? 'ok' : 'bad'}`;
  } catch (error) {
    availability.textContent = `× ${error.message}`;
    availability.className = 'availability bad';
  }
}

document.getElementById('slugInput').addEventListener('input', (event) => {
  clearTimeout(slugTimer);
  slugTimer = setTimeout(() => checkSlug(event.target.value), 350);
});

document.getElementById('workspaceForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const status = document.getElementById('workspaceStatus');
  status.textContent = 'Сохранение…';
  const form = event.target;
  try {
    const result = await jsonOrThrow(await fetch('/api/workspace', {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        display_name: form.display_name.value,
        tagline: form.tagline.value,
        slug: form.slug.value,
        is_public: form.is_public.checked,
      }),
    }));
    renderWorkspace(result);
  } catch (error) { status.textContent = `Ошибка: ${error.message}`; }
});

document.getElementById('copyWorkspace').addEventListener('click', async () => {
  const input = document.getElementById('workspaceUrl');
  await navigator.clipboard.writeText(input.value);
  const button = document.getElementById('copyWorkspace');
  const old = button.textContent;
  button.textContent = 'Скопировано';
  setTimeout(() => button.textContent = old, 1400);
});

async function loadTemplates() {
  const templates = await jsonOrThrow(await fetch('/api/templates'));
  const list = document.getElementById('templateList');
  const select = document.getElementById('templateSelect');
  list.innerHTML = '';
  select.innerHTML = '';
  templates.forEach(t => {
    const card = document.createElement('div');
    card.className = 'template-card';
    card.innerHTML = `<div><strong>${escapeHtml(t.title)}</strong><small>${escapeHtml(t.id)} · ${t.assets.length} ref · default ${t.default_output_count}</small></div><span class="template-pill">ACTIVE</span>`;
    list.appendChild(card);
    const option = document.createElement('option');
    option.value = t.id;
    option.textContent = `${t.title} (${t.id})`;
    select.appendChild(option);
  });
  if (!templates.length) {
    list.innerHTML = '<div class="status-box">Пока нет шаблонов.</div>';
    select.innerHTML = '<option value="">Сначала создайте шаблон</option>';
  }
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
}

document.getElementById('templateForm').addEventListener('submit', async event => {
  event.preventDefault();
  const status = document.getElementById('templateStatus');
  status.textContent = 'Сохранение…';
  try {
    const result = await jsonOrThrow(await fetch('/api/templates', { method:'POST', body:new FormData(event.target) }));
    status.textContent = `Создан шаблон ${result.id}`;
    event.target.reset();
    event.target.default_output_count.value = 3;
    event.target.max_output_count.value = 10;
    event.target.size.value = '1024x1536';
    await loadTemplates();
  } catch (error) { status.textContent = `Ошибка: ${error.message}`; }
});

document.getElementById('jobForm').addEventListener('submit', async event => {
  event.preventDefault();
  const status = document.getElementById('jobStatus');
  const outputs = document.getElementById('outputs');
  outputs.innerHTML = '';
  status.textContent = 'Создание задания…';
  try {
    const result = await jsonOrThrow(await fetch('/api/jobs', { method:'POST', body:new FormData(event.target) }));
    currentJob = result.id;
    status.textContent = `${result.id}: ${result.status}`;
    pollJob(result.id);
  } catch (error) { status.textContent = `Ошибка: ${error.message}`; }
});

async function pollJob(jobId) {
  const status = document.getElementById('jobStatus');
  const outputs = document.getElementById('outputs');
  try {
    const job = await jsonOrThrow(await fetch(`/api/jobs/${jobId}`));
    status.textContent = `${job.id}\nСтатус: ${job.status}\nРезультатов: ${job.assets.filter(a => a.kind === 'output').length}/${job.output_count}${job.error_message ? '\nОшибка: '+job.error_message : ''}`;
    outputs.innerHTML = '';
    job.assets.filter(a => a.kind === 'output' && a.url).forEach(asset => {
      const link = document.createElement('a'); link.href = asset.url; link.target = '_blank'; link.rel = 'noreferrer';
      const img = document.createElement('img'); img.src = asset.url; img.alt = asset.original_filename;
      link.appendChild(img); outputs.appendChild(link);
    });
    if (['queued','running'].includes(job.status)) setTimeout(() => pollJob(jobId), 2000);
    else document.getElementById('deleteAssets').style.display = 'inline-flex';
  } catch (error) { status.textContent = `Ошибка опроса: ${error.message}`; }
}

document.getElementById('deleteAssets').addEventListener('click', async (event) => {
  if (!currentJob) return;
  const response = await fetch(`/api/jobs/${currentJob}/assets`, {method:'DELETE'});
  document.getElementById('jobStatus').textContent = response.ok ? `${currentJob}: временные файлы удалены` : 'Ошибка удаления';
  document.getElementById('outputs').innerHTML = '';
  event.target.style.display = 'none';
});

Promise.all([loadWorkspace(), loadTemplates()]).catch(console.error);
