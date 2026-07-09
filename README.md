# drone-cloud-server

Backend en AWS EC2 del sistema UAV de Búsqueda y Rescate (SAR) del TFG.

Recibe las medidas del sensor BME680 embarcado en la Raspberry Pi vía MQTT y las guarda en InfluxDB.

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
