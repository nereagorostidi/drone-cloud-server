#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=====================================================================
 Puente MQTT -> InfluxDB
 Sistema SAR basado en dron — servidor EC2
=====================================================================

Recibe los mensajes que publican los nodos edge por MQTT y los escribe
en InfluxDB. Es GENÉRICO respecto al dominio: no conoce de antemano los
campos de cada tipo de dato, sino que los deduce del topic y del JSON.

Convención de topics:   dronsar/{dron_id}/{dominio}
    - el {dominio} determina la MEASUREMENT (ambiental, sistema, vuelo,
      deteccion...)
    - el {dron_id} se guarda como TAG (indexado), para poder filtrar y
      agrupar por dron de forma eficiente.

Al ser genérico, añadir un dominio nuevo NO obliga a tocar este puente:
basta con que el nodo edge publique en dronsar/{dron_id}/{nuevo_dominio}.
"""

import json
import os
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

# --- CONFIGURACIÓN MQTT ---
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
# Comodín que capta TODOS los drones y TODOS los dominios de una vez.
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "dronsar/#")

# Clave del JSON que representa el instante de captura. No es un campo:
# se usa como marca temporal del punto en InfluxDB.
CAMPO_TIEMPO = "timestamp"


# =====================================================================
#  CONSTRUCCIÓN GENÉRICA DEL PUNTO
# =====================================================================
def _tipar(valor):
    """Devuelve el valor con un tipo válido para InfluxDB, o None si no
    se puede escribir como campo.

    Los números se fuerzan a float a propósito: en InfluxDB, un campo fija
    su tipo en la primera escritura y no puede ser unas veces entero y
    otras decimal dentro de la misma measurement. Forzar float evita ese
    conflicto (p. ej. bateria_pct llegando como 78 y luego como 78.0).
    """
    # bool es subclase de int en Python: hay que comprobarlo ANTES que int,
    # o un True/False acabaría convertido en 1.0/0.0.
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)):
        return float(valor)
    if isinstance(valor, str):
        return valor
    return None


def _anadir_campos(point, payload, prefijo=""):
    """Añade al punto todos los campos del JSON, salvo la marca de tiempo.

    Aplana un nivel de objetos anidados generando nombres 'padre_hijo'.
    Así la detección (caja, resolucion, dron) se guarda como caja_cx,
    caja_cy, dron_lat, etc., sin lógica específica por dominio.
    """
    for clave, valor in payload.items():
        if clave == CAMPO_TIEMPO:
            continue
        nombre = f"{prefijo}{clave}"
        if isinstance(valor, dict):
            _anadir_campos(point, valor, prefijo=f"{nombre}_")
        else:
            tipado = _tipar(valor)
            if tipado is not None:
                point.field(nombre, tipado)


def construir_punto(topic, payload):
    """Traduce un mensaje (topic + JSON) a un Point de InfluxDB.

    Devuelve None si el topic no sigue la convención dronsar/{dron_id}/{dominio}.
    """
    partes = topic.split("/")
    if len(partes) != 3 or partes[0] != "dronsar":
        return None
    _, dron_id, dominio = partes

    # La measurement es el dominio; el dron_id va como tag (indexado).
    point = Point(dominio).tag("dron_id", dron_id)
    _anadir_campos(point, payload)

    # Marca temporal: el instante de captura que viene en el propio mensaje.
    if CAMPO_TIEMPO in payload:
        point = point.time(payload[CAMPO_TIEMPO], WritePrecision.NS)
    return point


# =====================================================================
#  CALLBACKS MQTT
# =====================================================================
def on_connect(client, userdata, flags, rc, properties=None):
    print(f"Conectado a Mosquitto. Suscribiéndose a '{MQTT_TOPIC}'...")
    client.subscribe(MQTT_TOPIC)


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))

        point = construir_punto(msg.topic, payload)
        if point is None:
            print(f"Topic ignorado (formato inesperado): {msg.topic}")
            return

        write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)

        # partes[2] es el dominio; se muestra para seguimiento en los logs.
        dominio = msg.topic.split("/")[2]
        print(f"Guardado en '{dominio}': {payload}")
    except Exception as e:
        print(f"Error procesando el mensaje: {e}")


# =====================================================================
#  ARRANQUE
# =====================================================================
if __name__ == "__main__":
    # Inicializar cliente de InfluxDB
    influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    write_api = influx_client.write_api(write_options=SYNCHRONOUS)

    # Configurar cliente MQTT local (compatible con Paho v2)
    mqtt_client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message

    print("Arrancando script puente (dronsar/# -> InfluxDB)...")
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)

    # Mantener el script corriendo permanentemente
    mqtt_client.loop_forever()