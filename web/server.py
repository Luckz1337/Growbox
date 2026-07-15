import time
import json
import gc
import asyncio

from web.httputil import parse_query, send_json, send_plain, send_unauthorized, send_file_chunked
from core.auth import check_basic_auth
from core.timeutil import format_datetime, localtime_with_offset


async def _read_request(reader):
    request_line = await reader.readline()
    if not request_line:
        return None, None, {}
    parts = request_line.decode().split()
    if len(parts) < 2:
        return None, None, {}
    method, path = parts[0], parts[1]

    headers = {}
    while True:
        line = await reader.readline()
        if not line or line == b"\r\n":
            break
        if b":" in line:
            key, _, value = line.decode().partition(":")
            headers[key.strip().lower()] = value.strip()
    return method, path, headers


class WebServer:
    def __init__(self, sensors, controller, schedule_store, csv_logger, wifi, config,
                 web_user, web_password, ota_updater=None):
        self.sensors = sensors
        self.controller = controller
        self.schedule_store = schedule_store
        self.csv_logger = csv_logger
        self.wifi = wifi
        self.config = config
        self.web_user = web_user
        self.web_password = web_password
        self.ota_updater = ota_updater
        self.request_count = 0

    async def start(self):
        await asyncio.start_server(self._handle_client, "0.0.0.0", 80)
        print("Webserver gestartet auf Port 80")

    async def _handle_client(self, reader, writer):
        try:
            method, path, headers = await _read_request(reader)
            if method is None:
                return
            self.request_count += 1

            if not check_basic_auth(headers, self.web_user, self.web_password):
                await send_unauthorized(writer)
                return
            if method != "GET":
                await send_plain(writer, 405, "Method Not Allowed")
                return

            if self.request_count % 50 == 0:
                print(f"Request #{self.request_count}: {path}")

            await self._route(writer, path)
        except Exception as e:
            print(f"[web] handle_client error: {e}")
        finally:
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _route(self, writer, path):
        route, params = parse_query(path)

        if route in ("/", "/index.html"):
            await send_file_chunked(writer, "index.html", "text/html")
        elif route == "/api/sensordata":
            await self._handle_sensordata(writer)
        elif route == "/api/status":
            await self._handle_status(writer)
        elif route == "/api/actuators":
            await send_json(writer, self._actuators_payload())
        elif route == "/api/actuators/set":
            await self._handle_actuators_set(writer, params)
        elif route == "/api/schedule":
            await self._handle_schedule_get(writer)
        elif route == "/api/schedule/add":
            await self._handle_schedule_add(writer, params)
        elif route == "/api/schedule/delete":
            await self._handle_schedule_delete(writer, params)
        elif route == "/api/schedule/toggle":
            await self._handle_schedule_toggle(writer, params)
        elif route == "/api/schedule/clear":
            await self._handle_schedule_clear(writer)
        elif route == "/api/csv/download":
            await send_file_chunked(writer, self.csv_logger.filename, "text/csv")
        elif route == "/api/ota/status":
            await self._handle_ota_status(writer)
        elif route == "/api/ota/apply":
            await self._handle_ota_apply(writer)
        elif route == "/reset":
            await send_plain(writer, 200, "OK", "Reset...")
            await asyncio.sleep(1)
            import machine
            machine.reset()
        else:
            await send_plain(writer, 404, "Not Found", "404")

    def _actuators_payload(self):
        result = []
        for actuator in self.controller.actuators.values():
            d = actuator.to_status_dict()
            d["value"] = actuator.value
            d["min_value"] = actuator.min_value
            d["max_value"] = actuator.max_value
            result.append(d)
        return result

    async def _handle_sensordata(self, writer):
        payload = {"timestamp": format_datetime(localtime_with_offset()), "sensors": {}}
        for sensor_id, sensor in self.sensors.items():
            values = dict(sensor.last_values)
            values["status"] = sensor.status
            values["last_ok_ms_ago"] = sensor.age_ms()
            payload["sensors"][sensor_id] = values
        await send_json(writer, payload)

    async def _handle_status(self, writer):
        gc.collect()
        free_mem = gc.mem_free()
        alloc_mem = gc.mem_alloc()
        total_mem = free_mem + alloc_mem
        mem_usage = (alloc_mem / total_mem) * 100 if total_mem else 0

        rssi = self.wifi.wlan.status('rssi')
        ip_config = self.wifi.wlan.ifconfig()
        mac = ':'.join('{:02x}'.format(b) for b in self.wifi.wlan.config('mac'))

        import machine
        freq = machine.freq()
        uptime_sec = time.ticks_ms() // 1000
        csv_stat = self.csv_logger.stat()

        status = {
            "memory": {
                "total": total_mem, "free": free_mem, "allocated": alloc_mem,
                "usage_percent": round(mem_usage, 1),
            },
            "wifi": {
                "rssi": rssi,
                "signal_quality": (
                    "Exzellent" if rssi > -50 else
                    "Sehr gut" if rssi > -60 else
                    "Gut" if rssi > -70 else "Schwach"
                ),
                "ip_address": ip_config[0], "subnet": ip_config[1],
                "gateway": ip_config[2], "dns": ip_config[3], "mac_address": mac,
            },
            "system": {
                "chip": "ESP32-S3", "cpu_freq": freq, "uptime_seconds": uptime_sec,
                "uptime_formatted": f"{uptime_sec // 3600}h {(uptime_sec % 3600) // 60}m {uptime_sec % 60}s",
            },
            "data": {
                "csv_size_bytes": csv_stat["size_bytes"], "csv_lines": csv_stat["lines"],
                "sensor_poll_interval": self.config["SENSOR_POLL_INTERVAL"],
                "csv_log_interval": self.config["CSV_LOG_INTERVAL"],
            },
            "timestamp": format_datetime(localtime_with_offset()),
        }
        await send_json(writer, status)

    async def _handle_actuators_set(self, writer, params):
        try:
            results = {}
            for actuator_id, value_str in params.items():
                results[actuator_id] = self.controller.apply(actuator_id, float(value_str), source="manual")
            await send_json(writer, {"status": "success", "values": results})
        except Exception as e:
            await send_json(writer, {"status": "error", "message": str(e)}, status=400, status_text="Bad Request")

    async def _handle_schedule_get(self, writer):
        await send_json(writer, {
            "schedule": self.schedule_store.rules,
            "current_values": self.controller.get_values(),
            "current_time": format_datetime(localtime_with_offset()),
        })

    async def _handle_schedule_add(self, writer, params):
        try:
            required = ['name', 'start_hour', 'start_minute', 'end_hour', 'end_minute', 'actions']
            if not all(k in params for k in required):
                await send_json(writer, {"status": "error", "message": "Fehlende Parameter"})
                return
            actions = json.loads(params['actions'])
            weekdays = ([int(d) for d in params['weekdays'].split(',')]
                        if params.get('weekdays') else list(range(7)))
            rule = {
                "name": params['name'],
                "start_hour": int(params['start_hour']), "start_minute": int(params['start_minute']),
                "end_hour": int(params['end_hour']), "end_minute": int(params['end_minute']),
                "weekdays": weekdays,
                "enabled": params.get('enabled', 'true').lower() == 'true',
                "actions": actions,
                "created": format_datetime(localtime_with_offset()),
            }
            await self.schedule_store.add(rule)
            await send_json(writer, {"status": "success", "schedule": self.schedule_store.rules})
        except Exception as e:
            await send_json(writer, {"status": "error", "message": str(e)})

    async def _handle_schedule_delete(self, writer, params):
        try:
            index = int(params.get("id", -1))
            rule = await self.schedule_store.delete(index)
            if rule:
                await send_json(writer, {
                    "status": "success",
                    "message": f"Regel '{rule.get('name', 'Unbenannt')}' geloescht",
                    "schedule": self.schedule_store.rules,
                })
            else:
                await send_json(writer, {"status": "error", "message": "Ungueltige Regel-ID"})
        except Exception as e:
            await send_json(writer, {"status": "error", "message": str(e)})

    async def _handle_schedule_toggle(self, writer, params):
        try:
            index = int(params.get("id", -1))
            rule = await self.schedule_store.toggle(index)
            if rule:
                status = "aktiviert" if rule["enabled"] else "deaktiviert"
                await send_json(writer, {
                    "status": "success",
                    "message": f"Regel '{rule.get('name', 'Unbenannt')}' {status}",
                    "schedule": self.schedule_store.rules,
                })
            else:
                await send_json(writer, {"status": "error", "message": "Ungueltige Regel-ID"})
        except Exception as e:
            await send_json(writer, {"status": "error", "message": str(e)})

    async def _handle_schedule_clear(self, writer):
        await self.schedule_store.clear()
        await send_json(writer, {"status": "success", "schedule": self.schedule_store.rules})

    async def _handle_ota_status(self, writer):
        if self.ota_updater is None:
            await send_json(writer, {"status": "error", "message": "OTA nicht konfiguriert"})
            return
        try:
            result = self.ota_updater.check_for_update()
            result["status"] = "success"
            await send_json(writer, result)
        except Exception as e:
            await send_json(writer, {"status": "error", "message": str(e)})

    async def _handle_ota_apply(self, writer):
        if self.ota_updater is None:
            await send_json(writer, {"status": "error", "message": "OTA nicht konfiguriert"})
            return
        try:
            files = self.ota_updater.apply_update()
            await send_json(writer, {"status": "success", "files": files, "message": "Neustart..."})
            await asyncio.sleep(1)
            import machine
            machine.reset()
        except Exception as e:
            await send_json(writer, {"status": "error", "message": str(e)})
