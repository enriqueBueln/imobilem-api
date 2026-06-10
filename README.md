# Imobilem API

Backend intermediario entre la **app móvil de autorizaciones** (Expo/React Native) y el **ERP SAP S/4HANA** del cliente.

La app nunca habla con SAP directamente. Este backend es el único que tiene las credenciales de SAP, resuelve la autenticación, y le expone a la app una API REST limpia (JSON normal, sin las rarezas de OData). También maneja **nuestra** autenticación (usuarios, login, JWT) contra una base de datos propia.

> **Si vienes de Django:** FastAPI es como Django + DRF, pero sin baterías incluidas — tú armas las piezas. La buena noticia es que casi todo tiene un equivalente directo, y este README te lo mapea.

---

## 1. Qué hace y qué NO hace (todavía)

**Hace hoy:**
- **Auth propio** (no depende de SAP): `POST /auth/login` → JWT, `GET /auth/me`, `POST /auth/logout`.
- **Usuarios en Postgres** con rol (`admin`/`staff`/`proveedor`) y `sapUserId`.
- **Health checks**: `/health` (vivo), `/health/db` (Postgres), `/health/sap` (conectividad a SAP).
- **Cliente de SAP sembrado** (`SapClient`): resuelve el patrón OData V2 + Basic Auth + baile CSRF, listo para reutilizar.
- **Smoke test** de conectividad a SAP.

**NO hace todavía (a propósito):**
- Los servicios de **lectura** de SAP (estimaciones, preestimaciones, etc.). No existen porque Federico aún no entrega el `$metadata` ni los nombres de servicio. Construirlos ahora sería adivinar.
- **Autorizar/rechazar** contra SAP (falta el contrato de la operación de escritura).
- **Revocación de logout** server-side (ver §8, decisiones de diseño).

El backend está diseñado para que agregar esos módulos después sea **clonar un patrón**, no reescribir.

---

## 2. Requisitos

- **Python 3.11+**
- **[uv](https://docs.astral.sh/uv/)** (gestor de paquetes/entorno). Si `uv` no se reconoce en tu terminal, está en `…\Python311\Scripts\uv.exe`; agrega esa carpeta al PATH.
- **Postgres** corriendo en local (puerto 5432 por defecto).

---

## 3. Puesta en marcha (paso a paso)

```bash
# 1. Instalar dependencias (crea el entorno .venv y el uv.lock)
uv sync

# 2. Crear tu archivo de configuración
copy .env.example .env        # Windows  (o: cp .env.example .env)
#   Edita .env:
#   - DATABASE_URL: pon tu contraseña de Postgres
#   - JWT_SECRET:  genera uno con  python -c "import secrets; print(secrets.token_urlsafe(32))"
#   - SAP_PASSWORD: la contraseña del .docx de Federico (solo cuando vayas a probar SAP)

# 3. Crear la base de datos en tu Postgres local
psql -U postgres -c "CREATE DATABASE imobilem_dev;"   # te pedirá tu contraseña de Postgres

# 4. Aplicar las migraciones (crea la tabla users)
uv run alembic upgrade head

# 5. Crear tu primer usuario para poder hacer login
uv run python scripts/create_user.py --email staff@imobilem.com --name "Staff Demo" --password "javier14" --role staff --sap-user-id CMENDOZA

# 6. Levantar el servidor
uv run uvicorn app.main:app --reload
```

Listo: abre **http://127.0.0.1:8000/docs** (Swagger) para ver y probar la API.

**Probar el login rápido:**
```bash
curl.exe -s -X POST http://127.0.0.1:8000/auth/login -H "Content-Type: application/json" -d "{\"email\":\"staff@imobilem.com\",\"password\":\"una-contrasena-segura\"}"
# copia el access_token y úsalo:
curl.exe -s http://127.0.0.1:8000/auth/me -H "Authorization: Bearer <token>"
```
En Swagger: haz login en `/auth/login`, copia el `access_token`, botón **Authorize**, pega el token, y ya puedes llamar `/auth/me`.

---

## 4. Estructura de carpetas (capa → dominio, igual que la app)

Cada carpeta de nivel superior es una **capa**; dentro se organiza por **dominio** (`auth`, `health`, …). Hoy solo existen los dominios que de verdad necesitamos.

```
imobilem-api/
├─ app/
│  ├─ main.py              # crea la app, CORS, registra routers   (≈ asgi + urls raíz)
│  ├─ core/                # INFRAESTRUCTURA (no es dominio)        (≈ tu lib/ + settings)
│  │  ├─ config.py         # settings tipadas por entorno          (≈ settings.py + django-environ)
│  │  ├─ database.py       # engine + sesión SQLAlchemy            (≈ config del ORM)
│  │  ├─ security.py       # hash de password + JWT                (≈ lo que Django auth te da gratis)
│  │  └─ sap/client.py     # SapClient sembrado (OData V2 + CSRF)
│  ├─ api/                 # routers por dominio                   (≈ urls.py + views)
│  │  ├─ deps.py           # get_db, get_current_user              (≈ middleware + permissions)
│  │  ├─ health.py
│  │  └─ auth.py
│  ├─ models/user.py       # tablas SQLAlchemy                     (≈ models.py)
│  ├─ schemas/auth.py      # validación in/out (Pydantic)          (≈ serializers de DRF)
│  └─ services/auth.py     # lógica de negocio del dominio
├─ alembic/                # migraciones                           (≈ migrations/)
│  └─ versions/0001_create_users.py
├─ scripts/
│  ├─ smoke_sap.py         # test de conexión a SAP (read-only)
│  └─ create_user.py       # crea usuarios
├─ tests/                  # pytest (corren sin Postgres, ver §8)
├─ .env.example            # plantilla de configuración
└─ pyproject.toml          # dependencias + ruff + pytest
```

**Para agregar un dominio nuevo** (ej. `estimates` cuando Federico mande su contrato): creas `models/estimate.py`, `schemas/estimate.py`, `services/estimate.py`, `api/estimates.py`, lo registras en `main.py`, y reutilizas el `SapClient`. Mismo patrón, sin tocar lo demás.

---

## 5. Qué hace cada pieza (y por qué)

| Pieza | Qué hace | Por qué así |
|---|---|---|
| **`core/config.py`** | Lee la configuración del `.env` con tipos. Si falta una variable obligatoria, **truena al arrancar**, no en runtime. | Errores de config tempranos y claros. Una sola fuente de verdad. |
| **`core/database.py`** | Crea el motor de base de datos (async) y la sesión. La conexión es **perezosa**: no se conecta hasta la primera consulta. | Importar el módulo nunca toca Postgres → arranque y tests más simples. |
| **`core/security.py`** | Hashea contraseñas (Argon2) y crea/valida los JWT. | Es lo que Django te da gratis; aquí lo controlas tú. Argon2 es el estándar actual de hashing. |
| **`models/user.py`** | La tabla `users` en **nuestra** BD. El `sap_user_id` es un **parámetro** para filtrar datos de SAP, **no** una credencial. | Modelo de identidad tipo Retool: SAP se accede con un usuario técnico único; cada persona se identifica contra nuestra BD. |
| **`schemas/auth.py`** | Define qué entra (request) y qué sale (response). FastAPI valida y documenta solo con esto. | Equivale a los serializers de DRF. El contrato con la app vive aquí. |
| **`services/auth.py`** | La lógica (buscar usuario, verificar password). Los routers quedan delgados. | Lógica testeable y reutilizable, separada del HTTP. |
| **`api/deps.py`** | `DbSession` inyecta una sesión; `CurrentUser` valida el Bearer JWT y carga al usuario. | Las **dependencias** (`Depends`) son el corazón de FastAPI: como middleware/permissions de Django pero por endpoint y testeables. |
| **`api/auth.py`** | Los endpoints de login/me/logout. | — |
| **`api/health.py`** | Liveness + readiness (db, sap). | Para monitoreo y para verificar SAP de forma automatizada. |
| **`core/sap/client.py`** | El `SapClient`: Basic Auth para todo, y el **baile CSRF solo en escrituras** (las lecturas no lo necesitan). | Resuelve el patrón de SAP **una sola vez**; todos los servicios futuros lo reutilizan. |

---

## 6. Comandos del día a día

```bash
uv run uvicorn app.main:app --reload     # servidor de desarrollo (hot reload)
uv run pytest                             # tests
uv run ruff check .                       # linter
uv run ruff format .                      # formateador
uv run alembic revision --autogenerate -m "mensaje"   # nueva migración tras cambiar un modelo
uv run alembic upgrade head               # aplicar migraciones
uv run python scripts/smoke_sap.py        # probar conexión a SAP (read-only)
```

---

## 7. El smoke test de SAP

Cuando infraestructura abra el firewall hacia `TLALOC:1080`, verifica la conexión:

```bash
uv run python scripts/smoke_sap.py
```

Para diagnóstico fino (distinguir firewall vs credenciales), el `curl` de una línea:

```bash
curl.exe -i --connect-timeout 15 -u "COM_ENK_IMO:<password-del-docx>" -H "X-CSRF-Token: Fetch" -H "Accept: application/json" "http://TLALOC.idei.com.mx:1080/sap/opu/odata/sap/ZBP_INB_TEST_SRV/"
```

- **`200` + header `x-csrf-token`** → red + credenciales + servicio OK.
- **timeout** → firewall/red (tu IP no autorizada).
- **`401`** → red OK, credenciales/usuario mal.

> La contraseña de SAP termina en `l` minúscula (es "ENKONTRO**L**"), no en `I` mayúscula.

---

## 8. Decisiones de diseño (por qué, para que no parezca deuda escondida)

- **Async.** El trabajo principal del backend es esperar respuestas de red (SAP), así que async (FastAPI + httpx + SQLAlchemy async) rinde mejor. Es la diferencia más grande con el Django síncrono.
- **`SapClient` sembrado.** `read()` y `create()` ya están escritos pero no se usan aún: están listos para cuando llegue el contrato de SAP. No es código muerto, es plomería preparada.
- **Logout stateless.** El JWT no se puede "invalidar" sin estado extra. El logout real (lista de revocación o refresh tokens) es el **siguiente paso documentado**; meter una versión a medias ahora sería deuda.
- **Tests con SQLite.** Los tests usan SQLite en memoria (vía override de la dependencia `get_session`), así corren sin Postgres ni secretos. Producción siempre es Postgres.
- **Solo los dominios que existen.** No hay carpetas vacías "por si acaso". Se agregan cuando hay algo real que poner.

---

## 9. Seguridad

- **Las credenciales viven solo en `.env`** (que está en `.gitignore`). Nunca en el repo ni en la app.
- **Genera un `JWT_SECRET` real** (`secrets.token_urlsafe(32)`), no uses el de ejemplo.
- **Rota la contraseña de SAP** al pasar a QA/PROD (la de DEV es débil y viaja sin cifrar sobre HTTP).
- El backend es el **único** punto donde vive la credencial de SAP: protégelo (sin logs de credenciales, sin exponer OData crudo a la app).

---

## 10. Lo que sigue

1. **Cuando Federico entregue** el `$metadata` y los servicios de lectura → agregar el primer dominio real (estimaciones) reutilizando el `SapClient`.
2. **En la app** → conectar el login real contra `POST /auth/login` y consumir `GET /auth/me`; agregar manejo de `401`.
3. **Después** → autorizar/rechazar (cuando exista el contrato de escritura), y luego logout con revocación, push, etc.
