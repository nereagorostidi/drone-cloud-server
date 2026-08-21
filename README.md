# drone-cloud-server
Backend en AWS EC2 del sistema UAV de Búsqueda y Rescate (SAR) del TFG.
Recibe las medidas del sensor BME680 embarcado en la Raspberry Pi vía MQTT y las guarda en InfluxDB.
Incluye además las páginas web del proyecto, el panel de control y la API REST de comandos.

## Estructura del repositorio
- `www/web/` — Contenido de **web.gorostiditfg.com** (índice, journal, todo, operador).
- `www/control/` — Contenido de **control.gorostiditfg.com** (panel de control con botones de comando). Es una **PWA** (instalable, con modo offline del propio panel): `manifest.json` + `sw.js` + `icons/`. Detalles en la sección [Panel de control (PWA)](#panel-de-control-pwa) más abajo.
- `api-rest/` — API REST que traduce las peticiones HTTP del panel de control a mensajes MQTT.
  - `api.py` — Servidor Flask: recibe la petición HTTP del botón y publica el comando en MQTT.
  - `comandos.py` — Cliente de terminal alternativo: publica los mismos comandos sin pasar por la web.
- `mqtt_to_influx.py` — Puente MQTT→InfluxDB de telemetría del sensor.
- `mqtt-to-influx.service` — Servicio systemd del puente MQTT.

## Flujo de comandos
El panel de control envía órdenes al dron (armar, desarmar, despegar…) a través de esta cadena:`api.py` y `comandos.py` son dos emisores en paralelo (web y terminal) que hacen lo mismo: publicar el comando en MQTT. `receptor.py`, suscrito al topic, lo traduce a MAVLink y lo envía al autopiloto. Mission Planner, conectado también al autopiloto, refleja lo que ocurre.

## Panel de control (PWA)
`control.gorostiditfg.com` (`www/control/`) se puede instalar como app (Chrome/Android/iOS): icono propio y ventana sin barra del navegador. Piezas:
- `manifest.json` — nombre, iconos y `display: standalone`.
- `sw.js` — Service Worker: cachea el app shell (HTML/CSS/iconos) para carga instantánea/offline; las peticiones a `api.gorostiditfg.com` (comandos al dron) nunca se cachean, siempre van a red.
- `icons/` — iconos en varios tamaños (192, 512 maskable, apple-touch-icon, favicon).

Requiere HTTPS para que el Service Worker se registre (no funciona por HTTP salvo en `localhost`).

El grupo **Cámara** del panel incluye además la transmisión en directo de la cámara del dron: un `<iframe>` (WebRTC) apuntando a `stream.gorostiditfg.com/dron_live/`, un subdominio/servicio de streaming aparte que no vive en este repo.

## Convención de topics MQTT
Todo lo que viaja por MQTT sigue el prefijo `dronsar/{dron_id}/...`:

- **Telemetría** (la ingiere `mqtt_to_influx.py`): `dronsar/{dron_id}/{dominio}` o `dronsar/{dron_id}/{dominio}/{subdominio}` — ej. `dronsar/dron01/sistema`, `dronsar/dron01/video/resumen`. El `dron_id` se guarda como tag y el resto del path (`dominio` + `subdominio` unidos por `_`) es la measurement en InfluxDB. Añadir un dominio nuevo no requiere tocar el puente: basta con que el nodo edge publique ahí.
- **Comandos hacia la Pi**: `dronsar/{dron_id}/{dominio}/config` — el sufijo `config` es especial y `mqtt_to_influx.py` lo excluye siempre (no es telemetría, es una orden).
- Cada mensaje de telemetría, si incluye una clave `timestamp` (ISO 8601), se usa como hora del punto en InfluxDB; si no la trae, se usa la hora de llegada del mensaje.

## Requisitos
- Python 3.10+
- Mosquitto y InfluxDB corriendo en el EC2
- Entorno virtual en `/home/ubuntu/env`

## Instalación
```bash
git clone git@github.com:<tu-usuario>/drone-cloud-server.git
cd drone-cloud-server
pip install -r requirements.txt
cp .env.example .env   # edita con tus credenciales
```

## Ejecución manual
```bash
source /home/ubuntu/env/bin/activate
python mqtt_to_influx.py
```

## Ejecución como servicio
```bash
sudo cp mqtt-to-influx.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mqtt-to-influx.service
```
Ver logs en tiempo real:
```bash
journalctl -u mqtt-to-influx.service -f
```

## Autora
Nerea Gorostidi García — TFG UC3M
