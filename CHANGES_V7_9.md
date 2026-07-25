# NeuroPhoto 0.7.9 — Render recovery build

- Подготовлена безопасная версия для старого Render-сервиса.
- Сохранены все изменения 0.7.8: выбор Nano Banana 2 / Lite / Pro / Legacy, формат кадра, число результатов и качество.
- Gemini output MIME остаётся `image/jpeg`, чтобы устранить HTTP 400 для `image/png`.
- Для Nano Banana 2 добавлено актуальное разрешение `0.5K` вместе с `1K`, `2K`, `4K`.
- `google-genai` обновлён до актуальной ветки 2.x с Interactions API.
- Удалён VPS deployment workflow: этот репозиторий предназначен только для Render.
- Секреты не входят в репозиторий; Render продолжает брать их из Environment Variables.
