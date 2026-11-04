# Migo English — backend

FastAPI + PostgreSQL (Supabase) + OpenAI. Las tablas se crean solas al arrancar.

## Variables de entorno
- `DATABASE_URL` (obligatoria): `postgresql://usuario:contraseña@host:puerto/base`. Con el Transaction pooler de Supabase (puerto 6543) funciona; contraseñas con @ / # : ? % van codificadas (%40 %2F %23 %3A %3F %25).
- `OPENAI_API_KEY`: sin ella la app funciona con un evaluador de respaldo muy básico (el perfil sale marcado «sin evaluador LLM»).
- `MIGO_MODEL`: modelo de OpenAI (por defecto `gpt-4.1-mini`).
- `MIGO_SELF_URL`: URL pública del backend (ej. `https://tu-app.onrender.com`). Si existe (o `RENDER_EXTERNAL_URL`, que Render pone solo), el servidor se llama a `/health` cada `MIGO_KEEPALIVE_MIN` minutos (14 por defecto; 0 lo apaga) para que el plan gratis no se duerma.
- `MIGO_LESSON_DAILY`: lecciones propias («How to…» pedidas por el usuario) por día y usuario (por defecto 5). Las lecciones del catálogo se generan una vez por nivel e idioma y se guardan en `lesson_cache`.
- `MIGO_VOICE_DAILY`: límite de llamadas de voz por usuario y día UTC (por defecto 120; un rol completo gasta ~14). `MIGO_VOICE`, `MIGO_TTS_MODEL`, `MIGO_STT_MODEL`: voz y modelos de voz.
- `DB_POOL`: conexiones del pool (por defecto 5).

## Correr
    pip install -r requirements.txt
    uvicorn migo.main:app --host 0.0.0.0 --port $PORT      # docs en /docs

`/health` muestra el estado de la base, si hay clave de OpenAI y el tipo del último error del LLM (el detalle va a los logs).

## Pruebas
    TEST_DATABASE_URL=postgresql://... python smoke_test.py     # usa una base de PRUEBA

## Módulos
`main.py` endpoints · `engine.py` diagnóstico, decisión, sesión, memoria, progreso · `levels.py` nivel y tiempo a la siguiente etapa ·
`i18n.py` idioma de ayuda y textos de respaldo · `auth.py` cuentas y token · `llm.py` OpenAI · `db.py` Postgres.
Auth: los demás endpoints aún no exigen el token (pendiente antes de abrirlo al público).
