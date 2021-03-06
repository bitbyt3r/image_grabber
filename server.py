#!/usr/bin/python
from flask import send_from_directory, request, jsonify, Flask
from types import SimpleNamespace
import requests
import argparse
import shutil
import redis
import rados
import time
import json
import os

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--server", help="Path to reconstruction server's REST endpoint")
    parser.add_argument("-F", "--scan_folder", help="Path to the root folder for scan storage")
    parser.add_argument("-r", "--redis_host", help="Redis host", default="localhost")
    parser.add_argument("-p", "--redis_port", help="Redis port", default=6379, type=int)
    parser.add_argument("-d", "--redis_db", help="Redis db", default=0, type=int)
    parser.add_argument("-H", "--heartbeat", help="Sets the heartbeat interval for clients", default=1, type=float)
    parser.add_argument("-l", "--host", help="Hostname to listen on", default="localhost")
    parser.add_argument("-P", "--port", help="Port to listen on", default=5000, type=int)
    parser.add_argument("-m", "--cephmonitors", help="The ip address(es) of the ceph monitors", default="130.85.96.90 130.85.96.91")
    parser.add_argument("-k", "--cephkey", help="The cephx auth key of the ceph cluster", default="")
    parser.add_argument("-o", "--pool", help="The ceph pool to save images to", default="photorig")
    config = parser.parse_args()
else:
    config = SimpleNamespace(
        server="http://localhost:5000",
        image_folder="/srv/ceph/images",
        scan_folder="/srv/ceph/scans",
        redis_host="localhost",
        redis_port=6379,
        redis_db=0,
        heartbeat=1,
        host="localhost",
        port=5000,
        cephmonitors="130.85.96.90 130.85.96.91",
        cephkey="",
        pool="photorig"
    )

cluster = rados.Rados()
cluster.conf_set("mon_host", config.cephmonitors)
cluster.conf_set("key", config.cephkey)
cluster.connect()

r = redis.Redis(host=config.redis_host, port=config.redis_port, db=config.redis_db)

app = Flask(__name__)

def update_heartbeat(id):
    heartbeats = {}
    if r.exists('heartbeats'):
        heartbeats = json.loads(r.get('heartbeats'))
    heartbeats[id] = time.time()
    r.set('heartbeats', json.dumps(heartbeats))

@app.route("/heartbeat", methods=["POST", "GET"])
def heartbeat():
    if request.method == "GET":
        heartbeats = {}
        if r.exists('heartbeats'):
            heartbeats = json.loads(r.get('heartbeats'))
        now = time.time()
        devices = []
        for device in heartbeats:
            if heartbeats[device] > (now - config.heartbeat * 3.0):
                devices.append(device)
        return jsonify(devices=devices)
    if request.method == "POST":
        id = request.json['serial']
        r.transaction(lambda x : update_heartbeat(id), 'heartbeats')
        if request.json['type'] == "camera":
            camera_options = {}
            if r.exists('options_received'):
                camera_options = json.loads(r.get('options_received'))
            if not id in camera_options:
                return jsonify(heartbeat_interval=config.heartbeat, update_options=True)
        if r.exists('configuration'):
            configuration = json.loads(r.get('configuration'))
            configured = json.loads(r.get('configured'))
            if id in configuration and not configured[id]:
                return jsonify(heartbeat_interval=config.heartbeat, configuration=configuration[id])
        if request.json['type'] == "controller":
            if r.exists('fire'):
                if json.loads(r.get('fire')):
                    r.set('fire', json.dumps(False))
                    return jsonify(heartbeat_interval=config.heartbeat/10, fire=True)
            return jsonify(heartbeat_interval=config.heartbeat/10)
        return jsonify(heartbeat_interval=config.heartbeat)

@app.route("/fire", methods=["POST"])
def fire():
    r.set('fire', json.dumps(True))
    return jsonify(success=True)

def update_configured(id):
    configured = {}
    if r.exists('configured'):
        configured = json.loads(r.get('configured'))
    configured[id] = True
    r.set('configured', json.dumps(configured))

@app.route("/configuration_complete", methods=["POST"])
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

def update_capture_configure(capture_config, same=True):
    configuration = {}
    configured = {}
    if same:
        heartbeats = {}
        if r.exists('heartbeats'):
            heartbeats = json.loads(r.get('heartbeats'))
        now = time.time()
        for entity in heartbeats:
            if heartbeats[entity] > (now - config.heartbeat * 3.0):
                configuration[entity] = capture_config
                configured[entity] = False
    else:
        for entity in capture_config:
            configuration[entity] = capture_config[entity]
            configured[entity] = False
    r.set('configuration', json.dumps(configuration))
    r.set('configured', json.dumps(configured))


@app.route("/capture/configure", methods=["POST", "GET"])
def capture_configure():
    if request.method == "GET":
        if r.exists('configuration'):
            return jsonify(configuration=json.loads(r.get('configuration')), configured=json.loads(r.get('configured')))
        return jsonify(success=False)
    if request.method == "POST":
        configuration = request.json
        r.transaction(lambda x : update_capture_configure(configuration, True), 'configuration')
        number_configured = len(json.loads(r.get('configured')))
        return jsonify(success=True, number_configured=number_configured)

@app.route("/capture/configure_all", methods=["POST", "GET"])
def capture_configure_all():
    if request.method == "GET":
        if r.exists('configuration'):
            return jsonify(configuration=json.loads(r.get('configuration')), configured=json.loads(r.get('configured')))
        return jsonify(success=False)
    if request.method == "POST":
        configuration = request.json
        r.transaction(lambda x : update_capture_configure(configuration, False), 'configuration')
        return jsonify(success=True)

@app.route("/options")
def get_options():
    if r.exists('options'):
        return jsonify(json.loads(r.get('options')))
    return jsonify({})

@app.route("/image/<path:path>")
def get_image(path):
    with cluster.open_ioctx(config.pool) as CEPH:
        return CEPH.read(path)

@app.route("/images")
def get_images():
    images = {}
    with cluster.open_ioctx(config.pool) as CEPH:
        for obj in CEPH.list_objects():
            camera, image = obj.split("-")
            images[camera] = image
    return jsonify(images)

@app.route("/delete", methods=["POST"])
def delete_images():
    with cluster.open_ioctx(config.pool) as CEPH:
        for camera in request.json:
            for image in request.json[camera]:
                image_path = "{}-{}".format(camera, image)
                CEPH.remove(image_path)
    return jsonify(success=True)

@app.route("/group", methods=["POST"])
def group_images():
    scan_dir = os.path.join(config.scan_folder, request.json['name'])
    if not os.path.isdir(scan_dir):
        os.makedirs(scan_dir)
    to_move = []
    for camera in request.json['cameras']:
        image_path = "{}-{}".format(camera, request.json['cameras'][camera])
        dest_path = os.path.join(scan_dir, camera + "." + image_path.split(".")[-1])
    with cluster.open_ioctx(config.pool) as CEPH:
        for move in to_move:
            with open(move[1], "wb") as OUT:
                OUT.write(CEPH.read(move[0]))
                CEPH.remove(move[0])
    return jsonify(success=True)

if __name__ == "__main__":
    app.run(host=config.host, port=config.port)
