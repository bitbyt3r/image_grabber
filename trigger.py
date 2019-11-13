#!/usr/bin/python
import threading
import requests
import argparse
import socket
import struct
import time
import json
import os

parser = argparse.ArgumentParser()
parser.add_argument("-p", "--port", help="Port to listen on", default=11000, type=int)
parser.add_argument("-i", "--interface", help="Interface to listen on", default="0.0.0.0")
parser.add_argument("-d", "--device", help="Device to send broadcast packets from", default="eth0")
parser.add_argument("-s", "--server", help="Path to image server's REST endpoint", default="http://localhost:5000")
parser.add_argument("-S", "--serial", help="Sets the reported id", default="1")
config = parser.parse_args()

controllers = {}

def udp_server():
    print("Starting udp server...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((config.interface, config.port))
    while True:
        data, addr = sock.recvfrom(1024)
        if addr[0] in socket.gethostbyname_ex(socket.gethostname())[2]:
            continue
        msg = data[:-1].decode('UTF-8')
        netid = data[-1]
        if msg == "macAddressAnnounce":
            if not netid in controllers:
                controllers[netid] = {"ip": addr[0], "status": "unknown"}
        elif msg == "captureComplete":
            if netid in controllers:
                controllers[netid]['status'] = "ready"
        elif msg == "receivedConfiguration":
            if netid in controllers:
                controllers[netid]['status'] = "ready"
            for netid in controllers:
                if controllers[netid]['status'] != "ready":
                    break
            else:
                requests.post(config.server + "/configuration_complete", json={"serial": config.serial})

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
sock.setsockopt(socket.SOL_SOCKET, 25, str(config.device + '\0').encode('utf-8'))

def udp_discover():
    print("Starting discovery...")
    while True:
        sock.sendto("discovering".encode('ASCII'), ('<broadcast>', config.port))
        time.sleep(10)

server = threading.Thread(target=udp_server)
server.daemon = True
server.start()

discover = threading.Thread(target=udp_discover)
discover.daemon = True
discover.start()

def heartbeat():
    now = time.time()
    request = requests.post(config.server + "/heartbeat", json={"controllers": controllers, "serial": config.serial, "type": "controller"})
    data = request.json()
    if 'configuration' in data:
        configuration = {
            "open_time": 100,
            "close_time": 200,
            "flash_power": 0.5,
            "flash_time": 150
        }
        configuration.update(data['configuration'])
        shutter_times = [[configuration['open_time']*10, configuration['close_time']*10] for x in range(24)]
        flash_power = int(configuration['flash_power']*2.55)
        flash_times = [configuration['flash_time'] * 10]*3
        for controller in controllers:
            controllers[controller]['status'] = "configuring"
            data = bytearray()
            data.extend("configuration".encode('ASCII'))
            data.append(controller)
            data.append(len(shutter_times))
            data.append(flash_power)
            for i in flash_times:
                data.extend(struct.pack('>H', i))
            for i in shutter_times:
                data.extend(struct.pack('>H', i[0]))
                data.extend(struct.pack('>H', i[1]))
            sock.sendto(data, (controllers[controller]['ip'], config.port))
    if 'fire' in data:
        for controller in controllers:
            controllers[controller]['status'] = "firing"
        sock.sendto("fire".encode('ASCII'), ('<broadcast>', config.port))
    return now + data['heartbeat_interval']

while True:
    next_heartbeat = heartbeat()
    time.sleep(max(next_heartbeat - time.time(), 0))
