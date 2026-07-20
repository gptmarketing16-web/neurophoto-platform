# NeuroPhoto Platform v7 — Render + Supabase + Upstash

Deployment package for a low-cost online test environment:

- Render Web Service: web application and generation worker in one container
- Supabase: PostgreSQL and private S3-compatible storage
- Upstash: Redis-compatible generation queue

Open `ONLINE_START_RU.md` for the Russian step-by-step instructions.

## Important free-tier limitations

Render free web services sleep after inactivity and have an ephemeral filesystem.
Supabase free projects can pause after inactivity and have storage/database quotas.
This setup is suitable for testing and initial users, not guaranteed production uptime.
