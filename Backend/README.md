# Migo English — backend del prototipo de validación

FastAPI + SQLite. Sin API key corre con un evaluador heurístico (solo para probar el flujo);
con `ANTHROPIC_API_KEY` el LLM genera diagnóstico/actividades y evalúa evidencia (`MIGO_MODEL` para cambiar el modelo).

    pip install -r requirements.txt
    python smoke_test.py                 # recorre: diagnóstico -> sesión 1 -> chat -> sesión 2
    uvicorn migo.main:app --reload       # docs interactivas en /docs

## Flujo (mapea con la sección 10 del documento)
1. `POST /users` objetivo + situación concreta
2. `GET/POST /users/{id}/diagnostic` 4 tareas de acción (+ `self_rating` para declarado vs demostrado)
3-4. respuesta del POST: perfil + cuello de botella + plan (3-5 pasos)
5. `POST /users/{id}/sessions` -> decisión explícita (regla, objetivo, dificultad, ayuda permitida, criterio, memoria a actualizar)
   `POST /sessions/{id}/help` (pista→pregunta→ejemplo→explicación; `blocked:true` cambia estrategia)
   `POST /sessions/{id}/attempt` · `POST /sessions/{id}/recovery` (cierra, actualiza memoria, evidencia antes/después)
7. `POST /users/{id}/chat` conversación libre; extrae frustración, cambio de objetivo, preferencias
8. `GET /users/{id}/memory` · `GET /users/{id}/next` (qué haría Migo ahora)
9. Sesión 2: mismo endpoint; el motor cambia por lo ocurrido antes
`GET /users/{id}/progress` progreso basado en evidencia sin ayuda.

## Dónde vive cada cosa
- `engine.decide()`: reglas §5 (bloqueo > error recurrente > reducir pistas > avanzar > cuello de botella).
- Memoria (§3): `competencies` (nivel vs autonomía), `errors`, `strengths`, `preferences`, `decisions`.
- Métricas §12: tablas `sessions`, `decisions`, `evidence` permiten calcular activación, retención y progreso.

## Límites conocidos
Auth básica + idioma de ayuda por nivel (migo/i18n.py) (migo/auth.py: cuentas + token), pero los demás endpoints aún no exigen el token; heurística de fallback muy básica; el pase de la sesión usa umbral fijo (0.7); sin tests de absentismo (>=3 días).

## Nivel (landing → app)
La landing (con migo-test.js, test adaptativo de 12 preguntas) envía nivel, rango y confianza a app.html?lvl=A2&conf=alta&lo=A2&hi=B1...; la app lo guarda en POST /users/{id}/placement. migo/levels.py calcula nivel estimado y tiempo a la siguiente etapa.

## Diagnóstico
Tareas por nivel (comprensión, expresión, respuesta rápida de 60 s) + mini-juego «palabras con imagen» (POST /users/{id}/vocab). Ya no hay lista de 5 palabras ni deletreo.

## Frontend
Abre `app.html` (mismo directorio que tu landing). Por defecto llama a http://localhost:8000; cambia con localStorage "migo-api".

## Base de datos (Supabase / Postgres)
Si existe la variable `DATABASE_URL` (también se acepta `DATABASEURL`) se usa PostgreSQL; si no, SQLite local.
Las tablas se crean solas al arrancar. En Render: Environment → `DATABASE_URL = postgresql://postgres.<ref>:<PASSWORD>@aws-0-us-east-2.pooler.supabase.com:6543/postgres`
(Transaction pooler; sin corchetes; si la contraseña tiene @ / # : ? % se escribe codificada: @=%40, /=%2F, #=%23, :=%3A, ?=%3F, %=%25).
Comprueba en `/health` que diga `"db": "postgres"`.
