#!/usr/bin/python
from signal import alarm, signal, SIGALRM, SIGKILL
import requests
import argparse
import pygame
import socket
import time
import json
import os

parser = argparse.ArgumentParser()
parser.add_argument("-s", "--server", help="Path to image server's REST endpoint", default="http://localhost:5000")
parser.add_argument("-i", "--images", help="Path to the images to project", default="./images")
parser.add_argument("-S", "--signal", help="Sets the serial reported to the server", default="2")
config = parser.parse_args()

drivers = ['fbcon', 'directfb', 'svgalib', 'x11']
for driver in drivers:
    print("Trying driver {0}".format(driver))
    if not os.getenv('SDL_VIDEODRIVER'):
        os.putenv('SDL_VIDEODRIVER', driver)
    try:
        class Alarm(Exception):
            pass
        def alarm_handler(signum, frame):
            raise Alarm
        signal(SIGALRM, alarm_handler)
        alarm(3)
        try:
            print("Starting pygame")
            pygame.display.init()
            print("Started pygame")
            alarm(0)
        except Alarm:
            raise KeyboardInterrupt
    except pygame.error:
        print('Driver: {0} failed.'.format(driver))
        continue
    break
else:
    print("Could not find suitable video driver!")
    raise Exception('No suitable video driver found!')

size = (pygame.display.Info().current_w, pygame.display.Info().current_h)
print("Screen size is {0}x{1}".format(*size))
screen = pygame.display.set_mode(size, pygame.FULLSCREEN)
screen.fill((0, 0, 0))        
pygame.font.init()
pygame.mouse.set_visible(False)
pygame.display.update()

def display(file_name):
    if not file_name:
        screen.fill((0,0,0))
        pygame.display.update()
        return
    if not(os.path.isfile(file_name)):
        print("Image {0} does not exist".format(file_name))
        return
    try:
        image = pygame.image.load(file_name).convert()
    except:
        print("Failed to load image {0}. Check the format?".format(file_name))
    print("Displaying image {0}".format(file_name))
    isize = image.get_size()
    dsize = (pygame.display.Info().current_w, pygame.display.Info().current_h)
    xp = (dsize[0] - isize[0]) / 2
    yp = (dsize[1] - isize[1]) / 2
    screen.blit(image, (xp, yp))
    pygame.display.update()

def heartbeat():
    now = time.time()
    request = requests.post(config.server + "/heartbeat", json={"serial": config.serial, "type": "projector"})
    data = request.json()
    if 'configuration' in data:
        if 'projector_image' in data['configuration']:
            image = os.path.join(config.images, data['configuration']['projector_image'])
            display(image)
    return now + data['heartbeat_interval']

while True:
    next_heartbeat = heartbeat()
    time.sleep(max(next_heartbeat - time.time(), 0))
