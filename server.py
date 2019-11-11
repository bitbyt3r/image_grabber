#!/usr/bin/python
from flask import send_from_directory, request, jsonify, Flask
import requests
import argparse
import shutil
import redis
import time
import json
import os

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", help="Path to config file", default="/etc/imagegrabber.conf")
    parser.add_argument("-s", "--server", help="Path to reconstruction server's REST endpoint")
    parser.add_argument("-f", "--image-folder", help="Path to the image storage")
    parser.add_argument("-F", "--scan-folder", help="Path to the root folder for scan storage")
    parser.add_argument("-r", "--redis-host", help="Redis host", default="localhost")
    parser.add_argument("-p", "--redis-port", help="Redis port", default=6379, type=int)
    parser.add_argument("-d", "--redis-db", help="Redis db", default=0, type=int)
    parser.add_argument("-H", "--heartbeat", help="Sets the heartbeat interval for clients", default=1, type=float)
    args = parser.parse_args()

    config = {}
    if os.path.isfile(args.config):
        with open(args.config, "r") as CONFIG_FILE:
            config = json.loads(CONFIG_FILE.read())

    for i in vars(args).keys():
        if getattr(args, i):
            config[i] = getattr(args, i)
else:
    config = {
        'config': "",
        'server': "localhost:8080",
        'image-folder': "./images",
        'scan-folder': "./scans",
        'redis-host': "localhost",
        'redis-port': 6379,
        'redis-db': 0,
        'heartbeat': 0.5
    }

r = redis.Redis(host=config['redis-host'], port=config['redis-port'], db=config['redis-db'])

app = Flask(__name__)

def update_heartbeat(id):
    heartbeats = {}
    if r.exists('heartbeats'):
        heartbeats = json.loads(r.get('heartbeats'))
    heartbeats[id] = time.time()
    r.set('heartbeats', json.dumps(heartbeats))

@app.route("/camera/heartbeat", methods=["POST", "GET"])
def heartbeat():
    if request.method == "GET":
        heartbeats = {}
        if r.exists('heartbeats'):
            heartbeats = json.loads(r.get('heartbeats'))
        now = time.time()
        cameras = []
        for camera in heartbeats:
            if heartbeats[camera] > (now - config['heartbeat'] * 1.5):
                cameras.append(camera)
        return jsonify(cameras=cameras)
    elif request.method == "POST":
        id = request.json['serial']
        r.transaction(lambda x : update_heartbeat(id), 'heartbeats')
        camera_options = {}
        if r.exists('options_received'):
            camera_options = json.loads(r.get('options_received'))
        if not id in camera_options:
            return jsonify(heartbeat_interval=config['heartbeat'], update_options=True)
        if r.exists('configuration'):
            configuration = json.loads(r.get('configuration'))
            configured = json.loads(r.get('configured'))
            if id in configuration and not configured[id]:
                return jsonify(heartbeat_interval=config['heartbeat'], configuration=configuration[id])
        return jsonify(heartbeat_interval=config['heartbeat'])

def update_configured(id):
    configured = {}
    if r.exists('configured'):
        configured = json.loads(r.get('configured'))
    configured[id] = True
    r.set('configured', json.dumps(configured))

@app.route("/camera/configuration_complete", methods=["POST"])
def configuration_complete():
    id = request.json['serial']
    r.transaction(lambda x : update_configured(id), 'configured')
    return jsonify(success=True)

def update_options(id, options):
    if r.exists('options'):
        current_options = json.loads(r.get('options'))
    else:
        r.set('options', json.dumps(options))
        return
    for section in options:
        for option in options[section]:
            to_del = []
            if 'choices' in current_options[section][option]:
                for choice in current_options[section][option]['choices']:
                    if not choice in options[section][option]['choices']:
                        to_del.append(choice)
                for deleting in to_del:
                    current_options[section][option]['choices'].remove(deleting)
    r.set('options', json.dumps(current_options))
    options_received = {}
    if r.exists('options_received'):
        options_received = json.loads(r.get('options_received'))
    options_received[id] = True
    r.set('options_received', json.dumps(options_received))

@app.route("/camera/options", methods=["POST"])
def camera_options():
    serial = request.json['serial']
    options = request.json['options']
    r.transaction(lambda x : update_options(serial, options), 'options')
    return jsonify(success=True)

def update_capture_configure(camera_config):
    heartbeats = {}
    if r.exists('heartbeats'):
        heartbeats = json.loads(r.get('heartbeats'))
    now = time.time()
    configuration = {}
    configured = {}
    for camera in heartbeats:
        if heartbeats[camera] > (now - config['heartbeat'] * 1.5):
            configuration[camera] = camera_config
            configured[camera] = False
    r.set('configuration', json.dumps(configuration))
    r.set('configured', json.dumps(configured))

@app.route("/capture/configure", methods=["POST", "GET"])
def capture_configure():
    if request.method == "GET":
        if r.exists('configuration'):
            return jsonify(configuration=json.loads(r.get('configuration')), configured=json.loads(r.get('configured')))
        return jsonify(success=False)
    configuration = request.json
    r.transaction(lambda x : update_capture_configure(configuration), 'configuration')
    return jsonify(success=True)

@app.route("/options")
def get_options():
    if r.exists('options'):
        return jsonify(json.loads(r.get('options')))
    return jsonify({})

@app.route("/image/<path:path>")
def get_image(path):
    return send_from_directory(config['image-folder'], path)

@app.route("/images")
def get_images():
    cameras = os.listdir(config['image-folder'])
    images = {}
    for camera in cameras:
        images[camera] = os.listdir(os.path.join(config['image-folder'], camera))
    return jsonify(images)

@app.route("/delete", methods=["POST"])
def delete_images():
    for camera in request.json:
        for image in request.json[camera]:
            image_path = os.path.join(config['image-folder'], camera, image)
            if os.path.isfile(image_path):
                os.remove(image_path)
    return jsonify(success=True)

@app.route("/group", methods=["POST"])
def group_images():
    scan_dir = os.path.join(config['scan-folder'], request.json['name'])
    if not os.path.isdir(scan_dir):
        os.makedirs(scan_dir)
    to_move = []
    for camera in request.json['cameras']:
        image_path = os.path.join(config['image-folder'], camera, request.json['cameras'][camera])
        dest_path = os.path.join(scan_dir, camera + "." + image_path.split(".")[-1])
        if os.path.isfile(image_path):
            to_move.append((image_path, dest_path))
        else:
            return jsonify(success=False)
    for move in to_move:
        shutil.move(*move)
    return jsonify(success=True)