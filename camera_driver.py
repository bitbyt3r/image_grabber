#!/usr/bin/python
import gphoto2 as gp
import requests
import argparse
import time
import json
import os

WIDGET_TYPES = {
    gp.GP_WIDGET_TEXT: "text",
    gp.GP_WIDGET_RANGE: "range",
    gp.GP_WIDGET_TOGGLE: "toggle",
    gp.GP_WIDGET_RADIO: "select",
    gp.GP_WIDGET_MENU: "select",
    gp.GP_WIDGET_DATE: "date",
    }

parser = argparse.ArgumentParser()
parser.add_argument("-b", "--bus", help="USB Bus of the camera", type=int)
parser.add_argument("-d", "--device", help="Device number of the camera", type=int)
parser.add_argument("-s", "--server", help="Path to image server's REST endpoint", default="http://localhost:5000")
parser.add_argument("-f", "--folder", help="Path to the image storage", default="./images")
config = parser.parse_args()

camera = gp.Camera()
context = gp.Context()
portlist = gp.PortInfoList()
portlist.load()
port_index = portlist.lookup_path("usb:{:03d},{:03d}".format(config.bus, config.device))
camera.set_port_info(portlist[port_index])
camera.init(context)

def get_settings():
    settings = {}
    settings_obj = camera.get_config(context)
    for n in range(settings_obj.count_children()):
        section = settings_obj.get_child(n)
        settings[section.get_name()] = {}
        for j in range(section.count_children()):
            child = section.get_child(j)
            data = {
                "name": child.get_name(),
                "type": WIDGET_TYPES[child.get_type()],
                "readonly": child.get_readonly(),
                "value": child.get_value(),
                }
            if data['type'] == 'range':
                data['range_low'], data['range_high'], data['range_inc'] = child.get_range()
            if data['type'] == 'select':
                data['choices'] = [child.get_choice(x) for x in range(child.count_choices())]
            settings[section.get_name()][child.get_name()] = data
    return settings

def set_settings(settings):
    settings_obj = camera.get_config(context)
    for section in settings:
        for setting in settings[section]:
            setting_obj = settings_obj.get_child_by_name(setting)
            setting_val = settings[section][setting]
            if setting_obj.get_value() != setting_val:
                setting_obj.set_value(setting_val)
    camera.set_config(settings_obj, context)

serial_number = camera.get_config(context).get_child_by_name('serialnumber').get_value()
if not os.path.isdir(os.path.join(config.folder, serial_number)):
    os.makedirs(os.path.join(config.folder, serial_number))

def heartbeat():
    now = time.time()
    request = requests.post(config.server + "/heartbeat", json={"serial": serial_number, "type": "camera"})
    data = request.json()
    if 'configuration' in data:
        set_settings(data['configuration'])
        requests.post(config.server + "/configuration_complete", json={"serial": serial_number})
    if 'update_options' in data:
        requests.post(config.server + "/camera/options", json={"serial": serial_number, "options": get_settings()})
    return now + data['heartbeat_interval']

next_heartbeat = 0
while True:
    event, data = camera.wait_for_event(min(1000, int(next_heartbeat - time.time())), context)
    if type(data) is gp.camera.CameraFilePath:
        image_file = camera.file_get(data.folder, data.name, gp.GP_FILE_TYPE_NORMAL, context)
        gp.gp_file_save(image_file, os.path.join(config.folder, serial_number, data.name))
    if time.time() > next_heartbeat:
        next_heartbeat = heartbeat()
