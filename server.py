#!/usr/bin/env python3
print("Starting server...")
print("Importing modules (this may take a while)...")
import time
t1 = time.perf_counter()
import os
import json
import time
import traceback
from threading import Thread, Lock
import tornado.web
import tornado.websocket
import tornado.httpserver
from tornado.options import define, options
from ev3dev2.motor import list_motors, Motor
from ev3dev2.sensor import list_sensors, Sensor
from ev3dev2 import Device
t2 = time.perf_counter()
print("Imported in", t2-t1)

define("port", default=8000, help="run on the given port", type=int)


class EV3InfoHandler(tornado.websocket.WebSocketHandler):
    websockets = set()
    websockets_lock = Lock()

    def open(self):
        with self.websockets_lock:
            self.websockets.add(self)
        self.write_message(get_info(set(), set())[0])
    
    def on_close(self):
        with self.websockets_lock:
            self.websockets.remove(self)

    def on_message(self, message):
        try:
            print("got message", message)
            data = json.loads(message)
            device_type = data["deviceType"]
            port = data["port"]
            attributes = data["attributes"]
            if device_type == "sensor":
                device = Sensor(port)
            elif device_type == "motor":
                device = Motor(port)
            else:
                raise ValueError("Unknown device type '" + device + "'")
            for name, value in attributes.items():
                setattr(device, name, value)
        except Exception:
            traceback.print_exc()
    
    @classmethod
    def send_to_all(cls, message):
        with cls.websockets_lock:
            for websocket in cls.websockets:
                try:
                    websocket.write_message(message)
                except Exception:
                    traceback.print_exc()


"""
Returns a string containing a JSON object which describes the current motor/sensor values in the following format:
    {
        "<address (e.g. "ev3-ports:in1")": {
            // for both sensors and motors:
            "driver_name": "<driver name>",
            "command": [<list of possible commands>],
            // for sensors:
            "values": "<current sensor values, separated by space (max. 8)>",
            "mode": {
                "selected": "<currently selected mode>],
                "values": [<list of possible modes>]
            },
            // for motors:
            "position": "<current motor position>",
            "duty_cycle_sp": "<duty cycle setpoint>",
            "polarity": "normal" or "inversed",
            "position_sp": "position setpoint",
            "speed_sp": "speed setpoint",
            "ramp_up_sp": "ramp up setpoint",
            "ramp_down_sp": "ramp down setpoint",
            "stop_action": {
                "selected": "<currently selected stop_action>",
                "values": [<list of possible stop_actions>]
            },
            "time_sp": "time setpoint",
        }
    }
Parameters 'old_sensor_addressse' and 'old_motor_addresses' are sets of previously available adresses. 
If an address was previously available, only "values" attribute (for sensors) or "position" attribute (for motors) is included.
This is because these are the only properties that change while the user views the page. 
When a WebSocket first connects with the server, get_info(set(), set()) is called so that initially the client receives all attributes (see EV3InfoHandler.open). 

get_info returns: (string containing JSON object, new sensor addresses (for use in the next call of get_info), new motor addresses (for use in the next call of get_info)).
"""
def get_info(old_sensor_addresses, old_motor_addresses):
    info = {"disconnected_devices": []}
    sensor_addresses = set()
    for sensor in list_sensors("*"):
        try:
            address = sensor.address
            if address.count(":") > 1:
                # addresses for i2c sensors end with ':i2c*', remove this
                address = address[:address.index(":", address.index(":")+1)]
            if address in old_sensor_addresses:
                old_sensor_addresses.remove(address)
                info[address] = {
                    "values": " ".join(str(sensor.value(i)) for i in range(sensor.num_values))
                }
            else:
                info[address] = {
                    "driver_name": sensor.driver_name,
                    "mode": {
                        "values": sensor.modes,
                        "selected": sensor.mode
                    },
                    "command": sensor.commands,
                    "values": " ".join(str(sensor.value(i)) for i in range(sensor.num_values)),
                    #"decimals": sensor.decimals,
                }
            sensor_addresses.add(address)
        except Exception:
            traceback.print_exc()
    info["disconnected_devices"].extend(old_sensor_addresses)
    motor_addresses = set()
    for motor in list_motors("*"):
        try:
            address = motor.address
            if address in old_motor_addresses:
                old_motor_addresses.remove(address)
                info[address] = {
                    "position": motor.position
                }
            else:
                info[address] = {
                    "driver_name": motor.driver_name,
                    "duty_cycle_sp": motor.duty_cycle_sp,
                    "polarity": motor.polarity,
                    "position": motor.position,
                    "position_sp": motor.position_sp,
                    "speed_sp": motor.speed_sp,
                    "ramp_up_sp": motor.ramp_up_sp,
                    "ramp_down_sp": motor.ramp_down_sp,
                    "stop_action": {
                        "values": motor.stop_actions,
                        "selected": motor.stop_action
                    },
                    "time_sp": motor.time_sp,
                    "command": motor.commands
                }
            motor_addresses.add(address)
        except Exception:
            traceback.print_exc()
    info["disconnected_devices"].extend(old_motor_addresses)
    content = json.dumps(info).encode("utf-8")
    return content, sensor_addresses, motor_addresses


def send_info():
    # always send all info on newly connected devices, but normally only send changing values (sensor.values and motor.position) to client
    old_sensor_addresses = set()
    old_motor_addresses = set()
    while True:
        if len(EV3InfoHandler.websockets) == 0:
            print("Waiting for clients to connect...")
            while len(EV3InfoHandler.websockets) == 0:
                time.sleep(0.5)
            print("Clients connected!")
        content, old_sensor_addresses, old_motor_addresses = get_info(old_sensor_addresses, old_motor_addresses)
        EV3InfoHandler.send_to_all(content)
        time.sleep(0.1)


if __name__ == "__main__":
    tornado.options.parse_command_line()
    static_files = os.path.join(os.path.dirname(__file__), "website")
    app = tornado.web.Application([
            (r"/ev3-info", EV3InfoHandler),
            (r"/(.*)", tornado.web.StaticFileHandler, {"path": static_files, "default_filename": "index.html"})
        ],
        static_path=os.path.join(os.path.dirname(__file__), "website")
    )
    app.listen(options.port)
    print("Serving on port", options.port)
    ioloop = tornado.ioloop.IOLoop.current()
    Thread(target=ioloop.start).start()
    Thread(target=send_info).start()
