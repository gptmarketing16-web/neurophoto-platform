# Развёртывание NeuroPhoto 0.7.9 на Render

Этот исходный код предназначен для существующего Render Web Service `neurophoto-platform`.

Важно:
- не добавляйте `.env`, ключи API, пароли, базу данных и пользовательские фотографии в GitHub;
- оставьте существующие Environment Variables в Render без изменений;
- для постоянного хранения на Render должен использоваться `STORAGE_BACKEND=s3` и действующие S3-параметры;
- Health Check Path: `/health`;
- Runtime: Docker.

После коммита Render должен запустить Auto Deploy. Проверка версии: `/openapi.json` содержит `0.7.9`, а `/health` возвращает статус `ok`.
