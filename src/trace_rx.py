"""
host application to catch my trace shit and dump it for some plotting with kst2
I miss having SWO to trace out data variables :(

run this with python -u !!!!
"""

import socket
import struct


sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("", 4242))

print("timestamp,position,goal,output")
while True:
    data, addr = sock.recvfrom(1024)
    # print(f"received {len(data)} bytes from addr: {addr}")
    #             b = struct.pack("<iiif", now, pos, goal, out)
    now, pos, goal, out = struct.unpack("<iiif", data)
    # now is a ticks in ms, lets get a real time in seconds
    now /= 1000
    print(f"{now},{pos},{goal},{out}")
