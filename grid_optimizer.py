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
MIN_RESERVE = 20            # keep this many units in battery incase of grid failure
RESERVE_WINDOW = 6          # look back at this many hours to decide reserve size (battery)
LAST_HOURS = 3              # start spending the battery more in last few hours

NO_SOLAR = {"lecture_hall"}

class Controller:
    def __init__(self):
        self.battery = 0.0        # estimate of stored energy
        self.hour = 0
        self.prices = []          # grid price each hour so far
        self.outage_needs = []    # what the battery would need to cover each hour if the grid died
        self.total_cost = 0.0