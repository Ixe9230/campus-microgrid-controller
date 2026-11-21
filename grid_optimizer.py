import json
import socket
import sys

HOST = "localhost"
PORT = 8800

SOLAR_CAP = 200.0       
BATTERY_CAP = 100.0     
GENERATOR_PRICE = 1.0   
DAY_HOURS = 24

PRICE_MARGIN = 0.02         # use battery if grid is this much more expensive
MIN_RESERVE = 20            # keep this many units incase of grid failure
RESERVE_WINDOW = 6          # look back at this many hours to decide reserve size
LAST_HOURS = 3              # start spending the battery more in last few hours

NO_SOLAR = {"lecture_hall"}