# Despliegue de costo mínimo: Railway Hobby + AuraDB Free

Arquitectura de producción:

- Un servicio Railway Hobby ejecuta FastAPI y sirve el build de React.
- AuraDB Free aloja el grafo y su índice vectorial.
- Un Railway Cron pequeño consulta la base una vez al día para evitar la pausa
  automática de Aura por inactividad.
- Claude Haiku 4.5 atiende el chat con cuotas persistentes.

Railway Free no alcanza para esta aplicación: permite 0,5 GB de RAM y el
proceso con el modelo cargado usa aproximadamente 0,76 GB. La imagen verificada
mide 1,21 GB. Hobby cuesta como mínimo USD 5/mes e incluye USD 5 de consumo;
con Serverless y tráfico esporádico, el objetivo es mantenerse cerca de ese
mínimo. AuraDB Free no requiere tarjeta.

## 1. Migrar Neo4j local a AuraDB

La base debe estar detenida antes del dump:

```powershell
docker compose stop
New-Item -ItemType Directory -Force .\backups
docker compose run --rm --no-deps `
  -v "${PWD}/backups:/backups" `
  neo4j neo4j-admin database dump neo4j `
  --to-path=/backups --overwrite-destination=true
```

Crear una instancia AuraDB Free y guardar su URI, usuario y contraseña. Después:

```powershell
docker run --rm -it `
  -v "${PWD}/backups:/backups" `
  neo4j:5.26 neo4j-admin database upload neo4j `
  --from-path=/backups `
  --to-uri=neo4j+s://INSTANCE_ID.databases.neo4j.io `
  --overwrite-destination=true
```

El comando solicita la contraseña de Aura interactivamente. No pasarla en la
línea de comandos ni guardarla en el repositorio.

El dump local ya fue generado y verificado en `backups/neo4j.dump`
(275.411.500 bytes). La carpeta está ignorada por Git: conservar además una
copia privada, porque AuraDB Free elimina instancias que permanecen pausadas.

Validar contra Aura:

```powershell
$env:NEO4J_URI='neo4j+s://INSTANCE_ID.databases.neo4j.io'
$env:NEO4J_USERNAME='neo4j'
$env:NEO4J_PASSWORD='...'
.\.venv\Scripts\python.exe validar.py
```

El resultado esperado es 53 pacientes, 32.783 eventos, 110 fármacos, 1.854
prescripciones y 127.546 relaciones. Crear un snapshot manual en Aura al final.

## 2. Preparar los secretos

Crear dos secretos independientes:

```powershell
Add-Type -AssemblyName System.Security
[Convert]::ToHexString(
  [Security.Cryptography.RandomNumberGenerator]::GetBytes(32)
).ToLower()
```

Repetir el comando para `CHAT_RATE_SALT` y `KEEPALIVE_TOKEN`.

En Anthropic:

1. Crear un workspace exclusivo para el portafolio.
2. Crear una API key nueva dentro de ese workspace.
3. Fijar un límite mensual de USD 2 y desactivar auto-reload.
4. Revocar inmediatamente cualquier clave que haya aparecido en chats, logs o
   terminales compartidas.

## 3. Crear el servicio web en Railway

1. Crear un proyecto vacío en Railway Hobby.
2. Añadir un servicio desde este repositorio de GitHub y seleccionar la rama
   que contiene estos cambios (`develop` actualmente; `master` después del merge).
3. Railway detectará `railway.json` y `Dockerfile`.
4. Configurar las variables de `.env.example` con valores reales.
5. Generar un dominio público y activar **Serverless**.
6. Configurar una réplica, máximo 1 vCPU y 1,5 GB de RAM.
7. Fijar alerta de consumo en USD 4 y límite duro en USD 6.
8. Activar autodeploy y **Wait for CI**.

Comprobar:

```powershell
Invoke-RestMethod https://APP_DOMAIN/api/health
Invoke-RestMethod https://APP_DOMAIN/api/ready
```

## 4. Crear el keepalive diario

Crear un segundo servicio desde el mismo repositorio:

1. Usar `/railway.keepalive.json` como ruta de Config as Code.
2. Definir `APP_URL=https://APP_DOMAIN`.
3. Definir el mismo `KEEPALIVE_TOKEN` usado por el servicio web.
4. Confirmar el cron `0 12 * * *` (12:00 UTC todos los días).

Cada ejecución debe imprimir `{"status":"ok"}` y terminar. Si falla durante
varios días, AuraDB Free puede pausarse; reanudarla manualmente desde Aura
Console y volver a comprobar `/api/ready`.

## 5. Verificación final

- Abrir la UI y cargar la lista de pacientes, el grafo y la línea temporal.
- Enviar una pregunta y confirmar eventos SSE, tool use y evidencia resaltada.
- Comprobar que el cuarto mensaje diario desde el mismo cliente devuelve 429.
- Dejar dormir Railway y confirmar que la UI vuelve a responder y que el primer
  chat carga el modelo sin descargar archivos de Hugging Face.
- Revisar que Railway no contenga volúmenes Neo4j y que Git no rastree dumps,
  `.env`, fuentes FHIR, logs, cachés o credenciales.
