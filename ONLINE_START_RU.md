# NeuroPhoto v7: Render + Supabase + Upstash

## 1. Обновление закрытого GitHub

Удалите из локальной папки репозитория старые файлы v6, но не удаляйте скрытую папку `.git`.
Скопируйте в неё всё содержимое архива v7. В GitHub Desktop выполните:

- Summary: `Render deployment version`
- `Commit to main`
- `Push origin`

## 2. Supabase

Создайте новый проект. Запишите пароль базы.

### PostgreSQL

Нажмите `Connect` и выберите **Session pooler**, порт 5432. Render не подключается к бесплатному прямому IPv6 endpoint.

Для `DATABASE_URL`:

1. Скопируйте Session pooler URI.
2. Замените `[YOUR-PASSWORD]` на пароль базы.
3. Замените начало `postgresql://` на `postgresql+psycopg://`.
4. Добавьте в конец `?sslmode=require`.

### Storage

1. `Storage` → `New bucket`.
2. Название: `neurophoto`.
3. Bucket должен быть private.
4. `Storage` → `Settings/Configuration` → `S3`.
5. Включите S3 protocol.
6. Создайте Access Key и сразу сохраните Secret Key — он показывается один раз.
7. Скопируйте Endpoint и Region.

## 3. Upstash

1. Создайте Redis database на бесплатном тарифе.
2. Регион выберите ближе к региону Render/Supabase.
3. Откройте `Connect`.
4. Скопируйте **native Redis URL**, начинающийся с `rediss://`.
5. Не используйте REST URL в переменной `REDIS_URL`.

## 4. Render

1. `New` → `Blueprint`.
2. Подключите private GitHub repository `neurophoto-platform`.
3. Render обнаружит `render.yaml`.
4. Заполните запрашиваемые секретные переменные.

Обязательные значения находятся в `RENDER_ENV_TEMPLATE.txt`.

Для `APP_SECRET_KEY` создайте случайную строку в PowerShell:

```powershell
$bytes = New-Object byte[] 48
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($bytes)
[Convert]::ToBase64String($bytes)
```

После создания дождитесь статуса `Live`, затем откройте:

```text
https://ИМЯ-СЕРВИСА.onrender.com/login
```

Войдите с `OWNER_EMAIL` и `OWNER_PASSWORD` из Render.

## 5. Подключение AI

После входа откройте раздел `API`. Добавьте прямой ключ или параметры интегратора. Не помещайте ключи в GitHub.

## 6. Первый тест

- тестовый проект;
- одно тестовое фото;
- один промпт;
- один референс;
- одна генерация.

Фото заказчика удаляется через 30 минут, результат — через 60 минут. Промпты и референсы сохраняются.
