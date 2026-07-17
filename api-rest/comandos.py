#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=====================================================================
 Publicador de comandos de vuelo por MQTT
 Sistema SAR basado en dron
=====================================================================

Publica una orden (armar / desarmar / despegar) en el topic de comandos
del dron. El receptor (en la Raspberry Pi, a bordo) se suscribe a ese
topic y traduce la orden a MAVLink. Este script SOLO publica.

Uso:
    python3 comandos.py arm
    python3 comandos.py disarm
    python3 comandos.py takeoff --altitude 30
    python3 comandos.py arm --drone-id dron-02
"""

import os
import json
import uuid
import argparse
from datetime import datetime
from dotenv import load_dotenv
import paho.mqtt.client as mqtt


# =====================================================================
#  CONFIGURACION (desde .env)
# =====================================================================
load_dotenv()

EC2_HOST = os.getenv("MQTT_BROKER", "localhost")   # broker en el propio EC2
PORT = int(os.getenv("MQTT_PORT", 1883))
DRONE_ID_DEFAULT = os.getenv("DRONE_ID", "dron-01")


# =====================================================================
#  ARGUMENTOS DE LINEA DE COMANDOS
# =====================================================================
parser = argparse.ArgumentParser(
    description="Publica un comando de vuelo por MQTT")
parser.add_argument("accion", choices=["arm", "disarm", "takeoff","land","rtl", "hold"],
                    help="Accion a ejecutar en el dron")
parser.add_argument("--altitude", type=float, default=None,
                    help="Altitud de despegue en metros (solo para takeoff)")
parser.add_argument("--drone-id", default=DRONE_ID_DEFAULT,
                    help=f"Dron destino (por defecto: {DRONE_ID_DEFAULT})")
args = parser.parse_args()

# takeoff necesita altitud: si no se indica, se avisa y se para.
if args.accion == "takeoff" and args.altitude is None:
    parser.error("takeoff requiere --altitude (ej: takeoff --altitude 30)")


# =====================================================================
#  CONSTRUCCION DEL MENSAJE JSON
# =====================================================================
# 'params' lleva los datos propios de cada accion:
#   arm / disarm -> vacio (no necesitan nada)
#   takeoff      -> {"altitude": <metros>}
params = {}
if args.accion == "takeoff":
    params["altitude"] = args.altitude

mensaje = {
    "command": args.accion,
    "params": params,
    "drone_id": args.drone_id,
    "command_id": uuid.uuid4().hex[:6],
    "timestamp": datetime.now().astimezone().isoformat(),
}

topic = f"dronsar/{args.drone_id}/comandos"


# =====================================================================
#  PUBLICACION MQTT
# =====================================================================
client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
client.connect(EC2_HOST, PORT, 60)
client.loop_start()

payload = json.dumps(mensaje)
info = client.publish(topic, payload, qos=1, retain=False)
info.wait_for_publish(timeout=5)

if info.is_published():
    print(f"Comando enviado a '{topic}':")
    print(f"  {payload}")
else:
    print("No se pudo publicar el comando.")

client.loop_stop()
client.disconnect()
