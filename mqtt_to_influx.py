import json
import os
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from dotenv import load_dotenv

# Cargar variables del .env
load_dotenv()

# --- CONFIGURACIÓN INFLUXDB ---
INFLUX_URL = os.getenv("INFLUX_URL")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN")
INFLUX_ORG = os.getenv("INFLUX_ORG")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET")

influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
write_api = influx_client.write_api(write_options=SYNCHRONOUS)

# --- CONFIGURACIÓN MQTT ---
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
# Un único topic con comodín cubre TODOS los drones y TODOS los dominios.
#   dronsar/{dron_id}/{dominio}                  (ej: sistema, sensor, deteccion)
#   dronsar/{dron_id}/{dominio}/{subdominio}      (ej: deteccion/sesion, video/resumen)
# El unico caso que se descarta a proposito es el que termina en "config"
# (dronsar/{dron_id}/{dominio}/config): son comandos hacia la Pi, no telemetria.
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "dronsar/#")


def _aplanar(prefijo, valor, salida):
    """Aplana dicts anidados a campos planos con nombres 'a_b_c'.

    El dominio 'detección' envía sub-objetos (caja, resolucion, dron), que
    InfluxDB no admite como campo directamente. Se aplanan a 'caja_cx',
    'dron_lat', etc. Los valores None se descartan (no se escriben).
    """
    if valor is None:
        return
    if isinstance(valor, dict):
        for k, v in valor.items():
            nombre = f"{prefijo}_{k}" if prefijo else k
            _aplanar(nombre, v, salida)
    elif isinstance(valor, bool):
        salida[prefijo] = valor
    elif isinstance(valor, (int, float)):
        # Todos los números como float para evitar conflictos de tipo en Influx
        # (un campo no puede ser int en una escritura y float en otra).
        salida[prefijo] = float(valor)
    elif isinstance(valor, str):
        salida[prefijo] = valor
    # listas u otros tipos: se ignoran


def on_connect(client, userdata, flags, rc, properties=None):
    print(f"Conectado a Mosquitto. Suscribiéndose a '{MQTT_TOPIC}'...")
    client.subscribe(MQTT_TOPIC)


def on_message(client, userdata, msg):
    try:
        partes = msg.topic.split("/")
        # dronsar/{dron_id}/{dominio}[/{subdominio}] -> al menos 3 niveles.
        if len(partes) < 3 or partes[0] != "dronsar":
            return
        # Los comandos de configuracion de la Pi (.../config) no son telemetria.
        if partes[-1] == "config":
            return

        dron_id = partes[1]
        # Si hay subdominio (ej: deteccion/sesion), la measurement junta
        # ambos niveles: "deteccion_sesion". Si no, es solo "sistema", etc.
        dominio = "_".join(partes[2:])
        payload = json.loads(msg.payload.decode("utf-8"))

        # El timestamp se usa como tiempo del punto, no como campo.
        ts = payload.pop("timestamp", None)

        campos = {}
        _aplanar("", payload, campos)
        if not campos:
            print(f"[{msg.topic}] sin campos numéricos/válidos, se ignora.")
            return

        point = Point(dominio).tag("dron_id", dron_id)
        for nombre, valor in campos.items():
            point = point.field(nombre, valor)

        if ts:
            point = point.time(ts, WritePrecision.NS)
        else:
            point = point.time(datetime.now(timezone.utc), WritePrecision.NS)

        write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)
        print(f"OK [{dron_id}/{dominio}] -> {len(campos)} campos")
    except Exception as e:
        print(f"Error procesando '{msg.topic}': {e}")


mqtt_client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

print("Arrancando puente MQTT -> InfluxDB (multidominio)...")
mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
mqtt_client.loop_forever()
