"""
MQTT 구독: 192.168.1.101:1883 에서 VVB001(진동), TP3237(온도) 구독 후 on_message 콜백으로 전달.
VVB001(진동)과 TP3237(온도)는 vibration_decode.py / mqtt_service.py의 디코딩 로직을 참고해서
프론트엔드에는 디코딩된 값만 전달한다.
"""
import json
import threading
import time
import os
import sys

try:
    from vibration_decode import parse_hex_to_temperature, decode_vvb001, PDIN_PATHS
except ImportError:
    # backend/에서 실행될 때 프로젝트 루트에 있는 vibration_decode.py를 찾기 위한 보정
    ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
    if ROOT_DIR not in sys.path:
        sys.path.append(ROOT_DIR)
    from vibration_decode import parse_hex_to_temperature, decode_vvb001, PDIN_PATHS

# 기본 브로커 설정 (Consumer 설정의 Broker/Server 기준)
MQTT_BROKER = "192.168.1.3"
MQTT_PORT = 1883
TOPICS = ["VVB001", "TP3237"]  # 진동, 온도

_mqtt_thread = None
_stop_event = None
_on_message_callback = None


def _parse_payload(payload_bytes):
    """payload를 숫자 또는 문자열로 파싱."""
    if not payload_bytes:
        return None
    try:
        s = payload_bytes.decode("utf-8").strip()
    except Exception:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    try:
        return int(s)
    except ValueError:
        pass
    try:
        obj = json.loads(s)
        if isinstance(obj, (int, float)):
            return obj
        if isinstance(obj, dict):
            # IO-Link MQTT가 {"eventno":..,"srcurl":..,"payload":{...}} 형태로 오는 경우,
            # payload 안쪽에서 data/value/temperature/vibration를 우선 추출
            inner = obj.get("payload")
            if isinstance(inner, dict):
                for key in ("data", "value", "temperature", "vibration"):
                    if key in inner:
                        return inner[key]
            elif isinstance(inner, (int, float)):
                return inner
            elif isinstance(inner, str):
                try:
                    inner_obj = json.loads(inner)
                    if isinstance(inner_obj, dict):
                        for key in ("data", "value", "temperature", "vibration"):
                            if key in inner_obj:
                                return inner_obj[key]
                    if isinstance(inner_obj, (int, float)):
                        return inner_obj
                except Exception:
                    # 숫자 문자열일 수도 있으니 한 번 더 시도
                    try:
                        return float(inner)
                    except ValueError:
                        try:
                            return int(inner)
                        except ValueError:
                            pass

            # dict 자체에 센서 값이 들어있는 경우
            for key in ("data", "value", "temperature", "vibration"):
                if key in obj:
                    return obj[key]
        return s
    except Exception:
        return s


def _run_mqtt_loop(on_message):
    global _stop_event
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        if on_message:
            on_message("mqtt_error", {"message": "paho-mqtt 미설치. pip install paho-mqtt"})
        return

    stop = _stop_event
    client = mqtt.Client(client_id="plc_monitor_sensor")
    last_values = {}

    def on_connect(client, userdata, flags, reason_code, *args):
        if reason_code != 0:
            err = f"MQTT 연결 실패: reason_code={reason_code}"
            print(f"[MQTT] {err}", flush=True)
            if on_message:
                on_message("mqtt_error", {"message": err})
            return
        for topic in TOPICS:
            client.subscribe(topic, qos=0)
        if on_message:
            on_message("mqtt_connected", {"broker": f"{MQTT_BROKER}:{MQTT_PORT}"})

    def on_message_cb(client, userdata, msg):
        topic = msg.topic
        raw = msg.payload
        ts = time.time()

        decoded_value = None

        # 토픽별로 mqtt_service.py / vibration_decode.py 로직 참고해서 디코딩
        try:
            text = raw.decode("utf-8").strip() if raw else ""
            data = json.loads(text) if text else {}
        except Exception:
            data = {}

        if topic == "TP3237":
            # mqtt_service.py 의 TP3237 처리 로직 참고
            try:
                payload = data.get("data", {}).get("payload", {}) if isinstance(data, dict) else {}
                hex_data = None
                if isinstance(payload, dict):
                    hex_data = payload.get("/iolinkmaster/port[2]/iolinkdevice/pdin", {}).get("data")
                    if not hex_data:
                        hex_data = payload.get("/iolinkmaster/port[1]/iolinkdevice/pdin", {}).get("data")
                if hex_data:
                    decoded_value = parse_hex_to_temperature(hex_data)
            except Exception:
                decoded_value = None

        elif topic == "VVB001":
            # mqtt_service.py 의 진동 처리 로직 참고
            # vibration_decode.decode_vvb001를 그대로 사용해서 전체 디코딩 결과(dict)를 전달
            try:
                payload = data.get("data", {}).get("payload", {}) if isinstance(data, dict) else {}
                hex_data = None
                if isinstance(payload, dict):
                    for path in PDIN_PATHS:
                        hex_data = payload.get(path, {}).get("data")
                        if hex_data:
                            break
                if hex_data:
                    decoded = decode_vvb001(hex_data)
                    if decoded and isinstance(decoded, dict):
                        # v_rms, a_peak, a_rms, temperature, crest, device_status 등 전체 dict 전달
                        decoded_value = decoded
            except Exception:
                decoded_value = None

        # 위 디코딩에서 값이 안 나왔으면, 기존 generic 파서로 fallback
        if decoded_value is None:
            decoded_value = _parse_payload(raw)

        last_values[topic] = {
            "value": decoded_value,
            "raw": raw.hex() if raw else "",
            "topic": topic,
        }
        if on_message:
            on_message("sensor_data", {"topic": topic, "value": decoded_value, "ts": ts})

    client.on_connect = on_connect
    client.on_message = on_message_cb
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    except Exception as e:
        print(f"[MQTT] connect 예외: {e}", flush=True)
        if on_message:
            on_message("mqtt_error", {"message": str(e)})
        return
    client.loop_start()
    while not (stop and stop.is_set()):
        time.sleep(0.5)
    client.loop_stop()
    client.disconnect()
    if on_message:
        on_message("mqtt_disconnected", {})


def start(broadcast_fn):
    """브로드캐스트 함수를 받아 MQTT 구독 스레드 시작. broadcast_fn(event, data)."""
    global _mqtt_thread, _stop_event
    if _mqtt_thread and _mqtt_thread.is_alive():
        return
    _stop_event = threading.Event()

    def on_message(event, data):
        broadcast_fn(event, data)

    _mqtt_thread = threading.Thread(
        target=_run_mqtt_loop,
        args=(on_message,),
        daemon=True,
    )
    _mqtt_thread.start()


def stop():
    """MQTT 구독 스레드 종료."""
    global _stop_event
    if _stop_event:
        _stop_event.set()
