import paho.mqtt.client as mqtt


if __name__ == "__main__":
    def on_connect(client, userdata, flags, rc):
        print(f"Connected with result code {rc}")
        # client.subscribe("test/topic")

    def on_message(client, userdata, msg):
        print(f"Received message: {msg.topic} {msg.payload.decode()}")

    def on_subscribe(client, userdata, mid, granted_qos):
        print(f"Subscribed: {mid}, qos: {granted_qos}")

    id_ = 107
    # id_ = 0x0101
    # host = "192.168.12.1"
    host = "192.168.12.1"
    # host = "127.0.0.1"
    port =3333
    # port = 1883

    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id=str(id_))
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    mqtt_client.on_subscribe = on_subscribe

    mqtt_client.connect(host, port, 60)
    mqtt_client.subscribe("GameStatus")
    mqtt_client.loop_forever()
