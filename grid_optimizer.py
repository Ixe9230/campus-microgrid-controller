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

def parse_events(msg):
    """random_event may be 'none', 'a', 'a,b' or a list. Return a set of names."""
    event = msg.get("random_event", "none")

    if isinstance(event, list):
        names = event
    else:
        names = str(event).split(",")

    events = set()
    for name in names:
        events.add(str(name).strip().lower())
    return events

def format_number(x):
    """Round to 6 decimals, and return whole numbers as ints."""
    x = round(float(x), 6)

    if x == int(x):
        return int(x)

    return x

def read_message(sock):
    """Read from the server until we have one complete message."""
    text = ""

    while True:
        data = sock.recv(1024)
        if not data:
            return None  # the server closed the connection

        text += data.decode()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass  # not all of it has arrived yet, keep reading

class Controller:
    def __init__(self):
        self.battery = 0.0        # estimate of stored energy
        self.hour = 0
        self.outage_needs = []    # what the battery would need to cover each hour if the grid died
        self.total_cost = 0.0

    def hours_left(self): 
        """hours remaining after current one"""      
        return DAY_HOURS - self.hour - 1

    def in_last_hours(self):      # True during last 3 hours
        return self.hours_left() < LAST_HOURS

    def reserve(self):  # how much battery to keep in case the grid fails
            if self.hours_left() == 0:  # last hour of the day: nothing left to protect
                return 0.0
            window = 2 if self.in_last_hours() else RESERVE_WINDOW  # last 3 hours: look back 2 hours, otherwise 6
            worst_recent_hour = max(self.outage_needs[-window:], default=0.0)  # the hour that would have needed the most battery
            return min(BATTERY_CAP, max(MIN_RESERVE, worst_recent_hour))  # keep at least 20, at most 100
   
    def charge_amount(self, msg): #how much to refill the battery ($1 per unit, how full should the batteru be??)
        if self.hours_left()==0: # this is the last hour of the day so dont restore
            return 0.0
        expensive_grid = msg.get("grid_price", 0.0)
        target = self.reserve() #fill the battery up to the emergency amount
        next_clouds = str(msg.get("forecast", "")). strip().lower() == "cloudy"
            