#!/usr/bin/python
# -*- coding: UTF-8 -*-
import os
import sys
import time
import logging
import socket
import spidev as SPI
import psutil
sys.path.append("..")
from lib import LCD_1inch28
from PIL import Image, ImageDraw, ImageFont, ImageOps

# Raspberry Pi pin configuration:
RST = 27
DC = 25
BL = 18
bus = 0
device = 0
refresh = 2 #number of seconds before refresh
foreground_image_path = "image.png"
max_bandwidth_mbps = 1000
logging.basicConfig(level=logging.DEBUG)

def interpolate_color(start_color, end_color, factor):
    #Interpolate between two colors
    return tuple([
        int(start_color[i] + (end_color[i] - start_color[i]) * factor)
        for i in range(3)
    ])

def draw_usage_bar(draw, center, radius, width, start_angle, usage, clockwise=True):
    start_color = (0, 255, 0)  # Green
    end_color = (255, 0, 0)    # Red
    steps = 10  # Number of steps in the gradient
    angle_step = (usage * 0.80) / steps
    factor_usage = usage / 100
    acw_start_angle =  start_angle - (usage * 0.80)
    for i in range(steps):
        factor = i / steps
        if clockwise:
            color = interpolate_color(start_color, end_color, factor * factor_usage)
            draw.arc([center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius],
                     start_angle + i * angle_step, start_angle + (i + 1) * angle_step, fill=color, width=width)
        else:
            color = interpolate_color(end_color, start_color, 1- ((1 - factor) * factor_usage))
            draw.arc([center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius],
                     acw_start_angle + i * angle_step, acw_start_angle + (i + 1) * angle_step, fill=color, width=width)

def get_ip_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0)
    try:
        # Doesn't even have to be reachable
        s.connect(('10.254.254.254', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

def get_network_usage_percentage(max_bandwidth_mbps, interval=1):
    net_io_start = psutil.net_io_counters()
    time.sleep(interval)
    net_io_end = psutil.net_io_counters()
    
    bytes_sent = net_io_end.bytes_sent - net_io_start.bytes_sent
    bytes_recv = net_io_end.bytes_recv - net_io_start.bytes_recv
    
    # Convert bits to megabits
    mbps_sent = (bytes_sent * 8) / (1024 ** 2) / interval
    mbps_recv = (bytes_recv * 8) / (1024 ** 2) / interval
    
    # Calculate usage as a percentage of max_bandwidth_mbps
    usage_sent_percent = (mbps_sent / max_bandwidth_mbps) * 100
    usage_recv_percent = (mbps_recv / max_bandwidth_mbps) * 100
    
    return usage_sent_percent, usage_recv_percent

def get_process_using_most_cpu():
    processes = [(proc.info['pid'], proc.info['name'], proc.info['cpu_percent']) for proc in psutil.process_iter(['pid', 'name', 'cpu_percent'])]
    if processes:
        # Sort processes by CPU usage in descending order and get the one with the highest usage
        process_using_most_cpu = max(processes, key=lambda x: x[2])
        return process_using_most_cpu
    return None

try:
    disp = LCD_1inch28.LCD_1inch28()
    disp.Init()
    disp.clear()
    disp.bl_DutyCycle(50)
    hostname = socket.gethostname()
    ip_address = get_ip_address()

    # Load the foreground image with transparency
    foreground_image = Image.open(foreground_image_path)
    Font12 = ImageFont.truetype("Font02.ttf", 20)  # Preload font

    last_network_update = time.time()
    last_process_update = time.time()
    network_usage_sent_percent, network_usage_recv_percent = 0, 0
    appcpu = "GETTING TOP PROCESS.."
    network_usage = ""

    while True:
        current_time = time.time()
        
        # Create blank image for drawing.
        image1 = Image.new("RGB", (disp.width, disp.height), "BLACK")
        draw = ImageDraw.Draw(image1)

        # Get CPU and RAM usage
        cpu_usage = psutil.cpu_percent()
        ram_usage = psutil.virtual_memory().percent
        # Get disk usage
        disk_usage = psutil.disk_usage('/').percent

        # Update network usage every 5 seconds
        if current_time - last_network_update >= 5:
            network_usage_sent_percent, network_usage_recv_percent = get_network_usage_percentage(max_bandwidth_mbps)
            net_io = psutil.net_io_counters()
            network_usage = f"{net_io.bytes_recv / (1024 ** 2):.0f}MB {net_io.bytes_sent / (1024 ** 2):.0f}MB"
            last_network_update = current_time

        # Update process information every 10 seconds
        if current_time - last_process_update >= 10:
            process = get_process_using_most_cpu()
            if process:
                pid, name, cpu_percent = process
                appcpu = f"{name} @ {cpu_percent:.0f}%"
            last_process_update = current_time

        # Draw CPU usage bar on the left, starting from bottom and curving clockwise
        draw_usage_bar(draw, (120, 120), 110, 16, 188, cpu_usage, clockwise=True)
        # Draw RAM usage bar on the right, starting from bottom and curving anticlockwise
        draw_usage_bar(draw, (120, 120), 110, 16, -8, ram_usage, clockwise=False)

        # Draw upload and download
        draw_usage_bar(draw, (120, 120), 110, 16, 82, network_usage_sent_percent, clockwise=False)
        draw_usage_bar(draw, (120, 120), 110, 16, 98, network_usage_recv_percent, clockwise=True)

        # Draw hostname and IP address in the center of the screen
        text = f"{appcpu}\nDISK: {disk_usage}%\n{network_usage}"
        text_bbox = draw.textbbox((0, 0), text, font=Font12)
        text_width = text_bbox[2] - text_bbox[0]
        draw.text(((disp.width - text_width) / 2, 115), text, fill="WHITE", font=Font12, align="center")

        # Overlay the foreground image onto the drawing
        image1.paste(foreground_image, (0, 0), foreground_image)

        text = f"{hostname}\n{ip_address}"
        text_bbox = draw.textbbox((0, 0), text, font=Font12)
        text_width = text_bbox[2] - text_bbox[0]
        draw.text(((disp.width - text_width) / 2, 45), text, fill="WHITE", font=Font12, align="center")

        # Convert back to RGB before displaying
        #image1 = image1.convert("RGB")
        
        # Display image
        #im_r = image1.rotate(180)
        disp.ShowImage(image1)

        # Sleep for a second before updating
        time.sleep(refresh)

except IOError as e:
    logging.info(e)
except KeyboardInterrupt:
    disp.module_exit()
    logging.info("quit:")
    exit()
