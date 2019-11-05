#!/usr/bin/python
import gphoto2 as gp
import requests
import argparse
import time
import json
import uuid
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
parser.add_argument("-c", "--config", help="Path to config file", default="/etc/imagegrabber.conf")
parser.add_argument("-b", "--bus", help="USB Bus of the camera", type=int)
parser.add_argument("-d", "--device", help="Device number of the camera", type=int)
parser.add_argument("-s", "--server", help="Path to server's REST endpoint")
parser.add_argument("-f", "--folder", help="Path to the image storage")
args = parser.parse_args()

config = {}
if os.path.isfile(args.config):
    with open(args.config, "r") as CONFIG_FILE:
        config = json.loads(CONFIG_FILE.read())

for i in vars(args).keys():
    if getattr(args, i):
        config[i] = getattr(args, i)

camera = gp.Camera()
context = gp.Context()
portlist = gp.PortInfoList()
portlist.load()
port_index = portlist.lookup_path("{},{}".format(config['bus'], config['device']))
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
        for setting in section:
            setting_obj = settings_obj.get_child_by_name(setting)
            setting_val = settings[section][setting]
            if setting_obj.get_value() != setting_val:
                setting_obj.set_value(setting_val)
    camera.set_config(settings_obj, context)

serial_number = camera.get_config(context).get_child_by_name('eosserialnumber').get_value()

last_heartbeat = time.time()
next_heartbeat = 0
def heartbeat():
    request = requests.post(config.server + "/camera/heartbeat", data={"serial": serial_number})
    data = request.json()
    last_heartbeat = time.time()
    next_heartbeat = last_heartbeat + data['heartbeat_interval']
    if 'configuration' in data.keys():
        set_settings(data['configuration'])
    if 'update_options' in data.keys():
        requests.post(config.server + "/camera/options", data={"serial": serial_number, "options": get_settings()})

while True:
    event, data = camera.wait_for_event(1000, context)
    if type(data) is gp.camera.CameraFilePath:
        image_uuid = str(uuid.uuid4())
        dest_path = os.path.join(config['folder'], image_uuid)
        os.makedirs(dest_path)
        dest_file = os.path.join(dest_path, data.name)
        image_file = camera.file_get(data.folder, data.name, gp.GP_FILE_TYPE_NORMAL, context)
        gp.gp_file_save(image_file, dest_file)
        requests.post(config.server + "/image/uploaded", data={"uuid": image_uuid, "serial": serial_number, "path": dest_file})
    if time.time() > next_heartbeat:
        heartbeat()
