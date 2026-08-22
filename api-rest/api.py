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
DRONE_ID = os.getenv("DRONE_ID", "dron-02")

# Drones que existen de verdad (deben coincidir con el desplegable de la web).
# No es autenticacion: es solo para que un drone_id mal escrito o con
# caracteres de MQTT (/, +, #) no acabe formando un topic distinto al
# esperado o publicando fuera del namespace "dronsar/...".
DRONES_VALIDOS = {"dron-01", "dron-02"}

# Comandos permitidos (deben coincidir con los del receptor.py)
COMANDOS_VALIDOS = {"arm", "disarm", "takeoff", "land", "rtl", "hold",
                    "start_mission"}
ALTITUD_MAXIMA = 120        # limite legal (Reglamento UE): 120 m sobre el terreno

# Comandos de configuracion de la Raspberry Pi (grupo "Sistema" del panel).
# A diferencia de COMANDOS_VALIDOS (que van al topic de comandos de vuelo),
# estos van cada uno a su propio dominio MQTT: dronsar/{drone_id}/{dominio}/config
COMANDOS_CONFIG = {
    "shutdown": "sistema",
    "set_sensor_interval": "sensor",
    "set_video_throttle": "deteccion",
    "start_recording": "deteccion",
    "stop_recording": "deteccion",
}


# =====================================================================
#  CLIENTE MQTT (se conecta una vez y se reutiliza)
# =====================================================================
mqtt_client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
mqtt_client.loop_start()


def _publicar(topic, command, params, drone_id):
    """Construye el JSON y lo publica en el topic indicado."""
    mensaje = {
        "command": command,
        "params": params,
        "drone_id": drone_id,
        "command_id": uuid.uuid4().hex[:6],
        "timestamp": datetime.now().astimezone().isoformat(),
    }
    info = mqtt_client.publish(topic, json.dumps(mensaje), qos=1, retain=False)
    info.wait_for_publish(timeout=5)
    return mensaje, info.is_published()


def publicar_comando(command, params, drone_id):
    """Publica un comando de vuelo en su topic de siempre."""
    topic = f"dronsar/{drone_id}/comandos"
    return _publicar(topic, command, params, drone_id)


def publicar_config(command, params, drone_id):
    """Publica un comando de configuracion de la Pi en el topic de su dominio."""
    dominio = COMANDOS_CONFIG[command]
    topic = f"dronsar/{drone_id}/{dominio}/config"
    return _publicar(topic, command, params, drone_id)


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
    drone_id = datos.get("drone_id") or DRONE_ID

    if drone_id not in DRONES_VALIDOS:
        return jsonify({"ok": False, "error": f"drone_id no valido: {drone_id}"}), 400

    # Comandos de vuelo: van al topic de comandos de siempre.
    if command in COMANDOS_VALIDOS:
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

        mensaje, publicado = publicar_comando(command, params, drone_id)
        if publicado:
            return jsonify({"ok": True, "enviado": mensaje})
        return jsonify({"ok": False, "error": "No se pudo publicar"}), 500

    # Comandos de configuracion de la Pi: cada uno a su topic de dominio.
    if command in COMANDOS_CONFIG:
        params = {}
        if command == "set_sensor_interval":
            interval = datos.get("interval_seconds")
            if interval is None or interval <= 0:
                return jsonify({"ok": False,
                                "error": "set_sensor_interval requiere 'interval_seconds' > 0"}), 400
            params["interval_seconds"] = interval
        elif command == "set_video_throttle":
            throttle = datos.get("throttle_ms")
            if throttle is None or throttle < 0:
                return jsonify({"ok": False,
                                "error": "set_video_throttle requiere 'throttle_ms' >= 0"}), 400
            params["throttle_ms"] = throttle

        mensaje, publicado = publicar_config(command, params, drone_id)
        if publicado:
            return jsonify({"ok": True, "enviado": mensaje})
        return jsonify({"ok": False, "error": "No se pudo publicar"}), 500

    return jsonify({"ok": False,
                    "error": f"Comando no valido: {command}"}), 400


# =====================================================================
#  ARRANQUE
# =====================================================================
if __name__ == "__main__":
    # host=0.0.0.0 -> accesible desde fuera del EC2 (no solo localhost)
    app.run(host="0.0.0.0", port=5000)
