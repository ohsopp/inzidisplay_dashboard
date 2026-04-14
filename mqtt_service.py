# backend/services/mqtt_service.py - MQTT 연결·콜백·InfluxDB 저장
import json
import queue
import traceback
import threading
import time
import paho.mqtt.client as mqtt
from influxdb_client import Point

from config import (
    MQTT_BROKER, MQTT_PORT, MQTT_TOPIC, VIBRATION_MQTT_TOPIC,
    MQTT_USERNAME, MQTT_PASSWORD,
    INFLUXDB_BUCKET, VIBRATION_SAMPLING_INTERVAL,
)
from core.state import state
from services.vibration_decode import (
    parse_hex_to_temperature,
    decode_vvb001,
    PDIN_PATHS,
)
from iolink_sensor_info import extract_sensor_info_from_mqtt
from parquet_dual_writer import append_point_to_parquet


def _safe_put(q, data):
    """Queue에 데이터 삽입. 꽉 차면 가장 오래된 항목을 버리고 삽입."""
    try:
        q.put_nowait(data)
    except queue.Full:
        try:
            q.get_nowait()  # 가장 오래된 항목 드롭
        except queue.Empty:
            pass
        try:
            q.put_nowait(data)
        except queue.Full:
            pass  # 극히 드문 경합 상황 — 데이터 포인트 1개 스킵


def _save_vibration_to_influxdb(decoded_data):
    """진동센서 데이터를 InfluxDB에 저장 (샘플링 레이트 적용)"""
    if not state.write_api:
        return
    current_time = time.time()
    if current_time - state.last_vibration_save_time < VIBRATION_SAMPLING_INTERVAL:
        return
    try:
        state.last_vibration_save_time = current_time
        point = Point("vibration") \
            .tag("sensor_type", "VVB001") \
            .field("v_rms", float(decoded_data.get('v_rms', 0)) if decoded_data.get('v_rms') is not None else 0) \
            .field("a_peak", float(decoded_data.get('a_peak', 0)) if decoded_data.get('a_peak') is not None else 0) \
            .field("a_rms", float(decoded_data.get('a_rms', 0)) if decoded_data.get('a_rms') is not None else 0) \
            .field("temperature", float(decoded_data.get('temperature', 0)) if decoded_data.get('temperature') is not None else 0) \
            .field("crest", float(decoded_data.get('crest', 0)) if decoded_data.get('crest') is not None else 0) \
            .time(time.time_ns())
        state.write_api.write(bucket=INFLUXDB_BUCKET, record=point)
        append_point_to_parquet(
            bucket=INFLUXDB_BUCKET,
            measurement="vibration",
            tags={"sensor_type": "VVB001"},
            fields={
                "v_rms": float(decoded_data.get("v_rms", 0)) if decoded_data.get("v_rms") is not None else 0,
                "a_peak": float(decoded_data.get("a_peak", 0)) if decoded_data.get("a_peak") is not None else 0,
                "a_rms": float(decoded_data.get("a_rms", 0)) if decoded_data.get("a_rms") is not None else 0,
                "temperature": float(decoded_data.get("temperature", 0)) if decoded_data.get("temperature") is not None else 0,
                "crest": float(decoded_data.get("crest", 0)) if decoded_data.get("crest") is not None else 0,
            },
            source="mqtt_vibration",
        )
        print(f"💾 Saved vibration data to InfluxDB (bucket: {INFLUXDB_BUCKET}): v_rms={decoded_data.get('v_rms')}, a_peak={decoded_data.get('a_peak')}, a_rms={decoded_data.get('a_rms')}")
    except Exception as e:
        print(f"❌ InfluxDB vibration write error: {e}")
        traceback.print_exc()


# paho-mqtt 연결 결과 코드 (원인 파악용)
_MQTT_RC = {
    0: "성공",
    1: "프로토콜 버전 불일치",
    2: "잘못된 Client ID",
    3: "브로커 사용 불가(다운/네트워크)",
    4: "잘못된 사용자명/비밀번호",
    5: "인증 거부(권한 없음)",
}


def _on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"✅ MQTT Connected to {MQTT_BROKER}:{MQTT_PORT}")
        client.subscribe(MQTT_TOPIC)
        client.subscribe(VIBRATION_MQTT_TOPIC)
        print(f"✅ Subscribed to topic: {MQTT_TOPIC}")
        print(f"✅ Subscribed to topic: {VIBRATION_MQTT_TOPIC}")
    else:
        reason = _MQTT_RC.get(rc, f"알 수 없음({rc})")
        print(f"❌ MQTT Connection failed: rc={rc} — {reason}")


def _on_message(client, userdata, msg):
    try:
        state.last_mqtt_message_time = time.time()
        message_str = msg.payload.decode('utf-8')
        print(f"📨 MQTT Message received on topic {msg.topic}: {message_str}")

        try:
            data = json.loads(message_str)

            if msg.topic == 'TP3237':
                payload = data.get('data', {}).get('payload', {})
                hex_data = payload.get('/iolinkmaster/port[2]/iolinkdevice/pdin', {}).get('data')
                if not hex_data:
                    hex_data = payload.get('/iolinkmaster/port[1]/iolinkdevice/pdin', {}).get('data')

                if hex_data:
                    temperature = parse_hex_to_temperature(hex_data)
                    if temperature is not None:
                        print(f"🌡️ Temperature extracted: {temperature}°C")
                        _safe_put(state.mqtt_queue, {'temperature': temperature, 'timestamp': time.time()})
                        if state.write_api:
                            try:
                                point = Point("temperature").field("value", float(temperature)).time(time.time_ns())
                                state.write_api.write(bucket=INFLUXDB_BUCKET, record=point)
                                append_point_to_parquet(
                                    bucket=INFLUXDB_BUCKET,
                                    measurement="temperature",
                                    tags={},
                                    fields={"value": float(temperature)},
                                    source="mqtt_tp3237",
                                )
                                print(f"💾 Saved to InfluxDB: {temperature}°C")
                            except Exception as e:
                                print(f"❌ InfluxDB write error: {e}")
                                traceback.print_exc()
                    else:
                        print("⚠️ Failed to parse hex data to temperature")
                else:
                    print("⚠️ Hex data not found in message structure")
                    print(f"📋 Message structure: {json.dumps(data, indent=2)}")

            elif msg.topic == VIBRATION_MQTT_TOPIC:
                payload = data.get('data', {}).get('payload', {})
                hex_data = None
                try:
                    extract_sensor_info_from_mqtt(data, payload, port='1')
                except Exception as e:
                    print(f"❌ 센서 정보 추출 중 오류: {e}")
                    traceback.print_exc()

                for path in PDIN_PATHS:
                    hex_data = payload.get(path, {}).get('data')
                    if hex_data:
                        break

                if hex_data:
                    decoded_data = decode_vvb001(hex_data)
                    if decoded_data:
                        print(f"📳 Vibration data decoded: v_rms={decoded_data.get('v_rms')}, a_peak={decoded_data.get('a_peak')}, a_rms={decoded_data.get('a_rms')}")
                        state.latest_vibration_data = {**decoded_data, 'timestamp': time.time()}
                        _safe_put(state.vibration_queue, {
                            'v_rms': decoded_data.get('v_rms'), 'a_peak': decoded_data.get('a_peak'),
                            'a_rms': decoded_data.get('a_rms'), 'temperature': decoded_data.get('temperature'),
                            'crest': decoded_data.get('crest'), 'timestamp': time.time()
                        })
                        _save_vibration_to_influxdb(decoded_data)
                    else:
                        print("⚠️ Failed to decode VVB001 data")
                else:
                    print("⚠️ Hex data not found in VVB001 message structure")
                    print(f"📋 Message structure: {json.dumps(data, indent=2)}")
            else:
                temp_value = data.get('temperature') or data.get('temp') or data.get('value')
                if temp_value is not None:
                    temperature = float(temp_value)
                    print(f"🌡️ Temperature extracted: {temperature}°C")
                    _safe_put(state.mqtt_queue, {'temperature': temperature, 'timestamp': time.time()})
                    if state.write_api:
                        try:
                            point = Point("temperature").field("value", float(temperature)).time(time.time_ns())
                            state.write_api.write(bucket=INFLUXDB_BUCKET, record=point)
                            append_point_to_parquet(
                                bucket=INFLUXDB_BUCKET,
                                measurement="temperature",
                                tags={},
                                fields={"value": float(temperature)},
                                source="mqtt_generic",
                            )
                            print(f"💾 Saved to InfluxDB: {temperature}°C")
                        except Exception as e:
                            print(f"❌ InfluxDB write error: {e}")
                            traceback.print_exc()
        except json.JSONDecodeError as e:
            print(f"❌ JSON decode error: {e}")
            print(f"📋 Raw message: {message_str}")
        except Exception as e:
            print(f"❌ Error processing message: {e}")
            traceback.print_exc()
    except Exception as e:
        print(f"❌ Error in on_message: {e}")
        traceback.print_exc()


def _on_disconnect(client, userdata, rc):
    print("🔌 MQTT Disconnected")


MQTT_WATCHDOG_INTERVAL = 30  # 연결 끊김 감지 주기 (초)


def _mqtt_watchdog():
    """워치독 스레드: 연결 끊김 자동 감지 → 재연결/재구독 (_on_connect에서 구독)."""
    while True:
        time.sleep(MQTT_WATCHDOG_INTERVAL)
        if state.mqtt_client is None:
            continue
        if not state.mqtt_client.is_connected():
            print("⚠️ MQTT 연결 끊김 감지, 재연결 시도 중...")
            try:
                state.mqtt_client.reconnect()
                print("✅ MQTT 워치독: 재연결 성공")
            except Exception as e:
                print(f"❌ MQTT 워치독 재연결 실패: {e}")


def start_mqtt():
    """MQTT 클라이언트 생성·연결·백그라운드 스레드 시작. state 초기화 후 호출."""
    try:
        client = mqtt.Client()
        if MQTT_USERNAME or MQTT_PASSWORD:
            client.username_pw_set(MQTT_USERNAME or "", MQTT_PASSWORD or "")
        client.on_connect = _on_connect
        client.on_message = _on_message
        client.on_disconnect = _on_disconnect
        client.reconnect_delay_set(min_delay=1, max_delay=120)
        state.mqtt_client = client
    except Exception as e:
        print(f"❌ Error initializing MQTT client: {e}")
        state.mqtt_client = None
        return

    def connect_mqtt():
        if state.mqtt_client is None:
            return
        try:
            print(f"🔄 Attempting to connect to MQTT broker: {MQTT_BROKER}:{MQTT_PORT}" + (" (with auth)" if (MQTT_USERNAME or MQTT_PASSWORD) else ""))
            state.mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            state.mqtt_client.loop_start()
            print("🔄 MQTT loop started")
        except Exception as e:
            print(f"❌ MQTT Connection error: {e}")
            print("💡 네트워크 연결을 확인하고 잠시 후 자동으로 재연결을 시도합니다.")
            traceback.print_exc()

            def retry_connect():
                time.sleep(5)
                if state.mqtt_client is not None:
                    try:
                        state.mqtt_client.reconnect()
                    except Exception:
                        pass
            threading.Thread(target=retry_connect, daemon=True).start()

    def run_mqtt():
        connect_mqtt()
        # 워치독 스레드 시작 (연결 끊김 자동 감지 + 재연결/재구독)
        threading.Thread(target=_mqtt_watchdog, daemon=True).start()

    threading.Thread(target=run_mqtt, daemon=True).start()
