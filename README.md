# drone-cloud-server
Backend en AWS EC2 del sistema UAV de Búsqueda y Rescate (SAR) del TFG.
Recibe las medidas del sensor BME680 embarcado en la Raspberry Pi vía MQTT y las guarda en InfluxDB.
Incluye además las páginas web del proyecto, el panel de control y la API REST de comandos.

## Estructura del repositorio
- `www/web/` — Contenido de **web.gorostiditfg.com** (índice, journal, todo, operador).
- `control/` — Contenido de **control.gorostiditfg.com** (panel de control con botones de comando).
- `api-rest/` — API REST que traduce las peticiones HTTP del panel de control a mensajes MQTT.
  - `api.py` — Servidor Flask: recibe la petición HTTP del botón y publica el comando en MQTT.
  - `comandos.py` — Cliente de terminal alternativo: publica los mismos comandos sin pasar por la web.
- `mqtt_to_influx.py` — Puente MQTT→InfluxDB de telemetría del sensor.
- `mqtt-to-influx.service` — Servicio systemd del puente MQTT.

## Flujo de comandos
El panel de control envía órdenes al dron (armar, desarmar, despegar…) a través de esta cadena:`api.py` y `comandos.py` son dos emisores en paralelo (web y terminal) que hacen lo mismo: publicar el comando en MQTT. `receptor.py`, suscrito al topic, lo traduce a MAVLink y lo envía al autopiloto. Mission Planner, conectado también al autopiloto, refleja lo que ocurre.

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
