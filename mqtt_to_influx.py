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

# Inicializar cliente de InfluxDB
influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
write_api = influx_client.write_api(write_options=SYNCHRONOUS)

# --- CONFIGURACIÓN MQTT ---

MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_TOPIC = os.getenv("MQTT_TOPIC")

# Callback cuando nos conectamos a Mosquitto
def on_connect(client, userdata, flags, rc, properties=None):
    print(f"Conectado a Mosquitto local. Suscribiéndose a {MQTT_TOPIC}...")
    client.subscribe(MQTT_TOPIC)

# Callback cuando llega un mensaje MQTT de la Raspberry Pi
def on_message(client, userdata, msg):
    try:
        # Parsear el JSON recibido
        payload = json.loads(msg.payload.decode('utf-8'))
        print(f"Mensaje MQTT recibido: {payload}")

        # Estructurar el dato para la base de datos de series temporales
        point = Point("clima") \
            .tag("ubicacion", "salon") \
            .field("temperatura", float(payload["temperatura"])) \
            .field("humedad", float(payload["humedad"])) \
            .field("presion", float(payload["presion"])) \
            .time(payload["timestamp"], WritePrecision.NS)

        # Escribir en InfluxDB
        write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)
        print("¡Dato guardado con éxito en InfluxDB!")
    except Exception as e:
        print(f"Error procesando el mensaje: {e}")

# Configurar cliente MQTT local (versión compatible con Paho v2)
mqtt_client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

print("Arrancando script puente...")
mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)

# Mantener el script corriendo permanentemente
mqtt_client.loop_forever()
