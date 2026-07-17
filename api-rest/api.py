#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=====================================================================
 API REST de comandos de vuelo  (Flask)
 Sistema SAR basado en dron - se ejecuta en el EC2
=====================================================================

Hace lo mismo que comandos.py (construir un JSON y publicarlo por MQTT),
pero en vez de lanzarse desde la terminal, se invoca por HTTP desde la
web. Es la "puerta web" delante del publicador MQTT.

    web --HTTP--> [ESTA API] --MQTT--> receptor (Pi) --MAVLink--> dron

Endpoint principal:
    POST /api/command
    Body JSON: {"command": "arm"}
               {"command": "takeoff", "altitude": 20}

Uso:
    python3 api.py          (queda escuchando en el puerto 5000)

AVISO: sin autenticacion. Solo para simulacion / red de confianza.
"""

import os
import json
import uuid
from datetime import datetime
from dotenv import load_dotenv
import paho.mqtt.client as mqtt
from flask import Flask, request, jsonify


# =====================================================================
#  CONFIGURACION (desde .env)
# =====================================================================
load_dotenv()

MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
DRONE_ID = os.getenv("DRONE_ID", "dron-01")

# Comandos permitidos (deben coincidir con los del receptor.py)
COMANDOS_VALIDOS = {"arm", "disarm", "takeoff", "land", "rtl", "hold",
                    "start_mission"}
ALTITUD_MAXIMA = 120        # limite legal (Reglamento UE): 120 m sobre el terreno


# =====================================================================
#  CLIENTE MQTT (se conecta una vez y se reutiliza)
# =====================================================================
mqtt_client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
mqtt_client.loop_start()


def publicar_comando(command, params):
    """Construye el JSON y lo publica en el topic de comandos."""
    mensaje = {
        "command": command,
        "params": params,
        "drone_id": DRONE_ID,
        "command_id": uuid.uuid4().hex[:6],
        "timestamp": datetime.now().astimezone().isoformat(),
    }
    topic = f"dronsar/{DRONE_ID}/comandos"
    info = mqtt_client.publish(topic, json.dumps(mensaje), qos=1, retain=False)
    info.wait_for_publish(timeout=5)
    return mensaje, info.is_published()


# =====================================================================
#  APLICACION FLASK
# =====================================================================
app = Flask(__name__)


# Permite que la web (en otro origen) llame a esta API sin que el
# navegador la bloquee por CORS.
@app.after_request
def add_cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "POST, GET, OPTIONS"
    return resp


@app.route("/api/health", methods=["GET"])
def health():
    """Comprobacion rapida de que la API esta viva."""
    return jsonify({"status": "ok", "drone_id": DRONE_ID})


@app.route("/api/command", methods=["POST", "OPTIONS"])
def command():
    """Recibe un comando por HTTP y lo publica por MQTT."""
    if request.method == "OPTIONS":       # peticion previa de CORS
        return ("", 204)

    datos = request.get_json(silent=True) or {}
    command = datos.get("command")

    # Validaciones
    if command not in COMANDOS_VALIDOS:
        return jsonify({"ok": False,
                        "error": f"Comando no valido: {command}"}), 400

    params = {}
    if command == "takeoff":
        altitude = datos.get("altitude")
        if altitude is None:
            return jsonify({"ok": False,
                            "error": "takeoff requiere 'altitude'"}), 400
        if altitude > ALTITUD_MAXIMA:
            return jsonify({"ok": False,
                            "error": f"altitud maxima {ALTITUD_MAXIMA} m"}), 400
        params["altitude"] = altitude

    # Publicar
    mensaje, publicado = publicar_comando(command, params)
    if publicado:
        return jsonify({"ok": True, "enviado": mensaje})
    return jsonify({"ok": False, "error": "No se pudo publicar"}), 500


# =====================================================================
#  ARRANQUE
# =====================================================================
if __name__ == "__main__":
    # host=0.0.0.0 -> accesible desde fuera del EC2 (no solo localhost)
    app.run(host="0.0.0.0", port=5000)
