# Migo English — backend

FastAPI + PostgreSQL (Supabase) + OpenAI. Las tablas se crean solas al arrancar.

## Variables de entorno
- `DATABASE_URL` (obligatoria): `postgresql://usuario:contraseña@host:puerto/base`. Con el Transaction pooler de Supabase (puerto 6543) funciona; contraseñas con @ / # : ? % van codificadas (%40 %2F %23 %3A %3F %25).
- `OPENAI_API_KEY`: sin ella la app funciona con un evaluador de respaldo muy básico (el perfil sale marcado «sin evaluador LLM»).
- `MIGO_MODEL`: modelo de OpenAI (por defecto `gpt-4.1-mini`).
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
