Create the password file before `docker compose up` (it is git-ignored):

    docker run --rm -v "$PWD/infra/mosquitto:/m" eclipse-mosquitto:2 \
      sh -c "mosquitto_passwd -b -c /m/passwd awaaz-backend '<AWAAZ_MQTT_PASSWORD>' && \
             mosquitto_passwd -b /m/passwd awz-demo-001 '<DEVICE_MQTT_PASSWORD>'"

The device MQTT password is separate from the device HMAC secret. Losing the MQTT password
lets an attacker subscribe to that device's topic, but messages are still HMAC-signed and
sequence-checked, so they cannot forge an announcement.
