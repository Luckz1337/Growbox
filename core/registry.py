from core.i2c_mux import TCA9548AChannel


def _log_error(component, error):
    print(f"[registry] {component}: {error}")


def build_sensors(specs, i2c, sensor_factories, mux_addr=0x70):
    """specs: settings.SENSORS. sensor_factories: {type_name: create(spec, bus) -> Sensor}.
    One failing sensor never stops the others - it just stays absent from the returned dict
    (never_connected status), same as today's per-sensor try/except in init_sensors()."""
    sensors = {}
    for spec in specs:
        try:
            bus = spec["bus"]
            if bus == "i2c_mux":
                device_bus = TCA9548AChannel(i2c, mux_addr, spec["mux_channel"])
            elif bus == "adc":
                device_bus = None  # ADC sensors build their own CalibratedADC from the spec directly
            else:
                raise ValueError(f"unknown bus type: {bus}")

            factory = sensor_factories[spec["type"]]
            sensor = factory(spec, device_bus)
            sensors[spec["id"]] = sensor
            print(f"[registry] sensor '{spec['id']}' initialized")
        except Exception as e:
            _log_error(f"sensor '{spec.get('id', '?')}' init", e)
    return sensors


def build_actuators(specs, actuator_factories):
    actuators = {}
    for spec in specs:
        try:
            factory = actuator_factories[spec["type"]]
            actuators[spec["id"]] = factory(spec)
            print(f"[registry] actuator '{spec['id']}' initialized")
        except Exception as e:
            _log_error(f"actuator '{spec.get('id', '?')}' init", e)
    return actuators
