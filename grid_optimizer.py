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
   
    def charge_amount(self, msg): #how much the geneerator puts into the battery this hour
            if self.hours_left()==0: # this is the last hour of the day so dont restore
                return 0.0
            expensive_grid = msg.get("grid_price", 0.0) > GENERATOR_PRICE + PRICE_MARGIN #grid is more expensive than generator
            target = self.reserve() #fill the battery up to this amount
            next_clouds = msg["forecast"] == "cloudy" #will it be cloudy next hour?
            if (expensive_grid or next_clouds) and not self.in_last_hours(): #if the grid is expensive or the next hour is cloudy (no solar), and we are not in the last 3 hours of the day
                target = BATTERY_CAP #FILL THE BATTERY TO MAXIMUM CAPACITY, will need it 
            else:
                target = self.reserve() #otherwise, just fill it to the reserve amount (emergency)
                return max (0.0, target - self.battery) #how much to pump, dont pump negatives

    def decide(self, msg):
        events = parse_events(msg)
        price = float(msg.get("grid_price", GENERATOR_PRICE))
        loads = msg.get("loads", [])

        sun_ok = "cloudy_weather" not in events
        grid_ok = "grid_failure" not in events
        battery_ok = "battery_failure" not in events
        generator_ok = "generator_failure" not in events

        kinds = [str(b.get("type", "")).lower() for b in loads]     # building types
        need = [float(b.get("load", 0)) for b in loads]             # demand per building 
        plan = [{"solar": 0.0, "battery": 0.0, "grid": 0.0} for _ in loads]

        battery_at_start = self.battery if battery_ok else 0.0   # remember this for the overcharge rule

        def give(source, order, amount):
            """returns how much is handed out"""
            used = 0.0
            for i in order:
                share = min(need[i], amount - used)
                if share <= 0:
                    continue
                plan[i][source] += share
                need[i] -= share
                used += share
            return used

        # sees how much reserve needs
        lecture_load = sum(need[i] for i in range(len(loads)) if kinds[i] in NO_SOLAR)
        other_load = sum(need) - lecture_load
        self.outage_needs.append(lecture_load + max(0.0, other_load - SOLAR_CAP))

        # allocates solar
        has_panels = [i for i in range(len(loads)) if kinds[i] not in NO_SOLAR]
        if sun_ok:
            give("solar", has_panels, SOLAR_CAP)

        # allocates battery (lecture halls come first)
        lecture_first = sorted(range(len(loads)), key=lambda i: kinds[i] not in NO_SOLAR)
        if not grid_ok: # grid is down
            battery_used = give("battery", lecture_first, battery_at_start)
        elif price > GENERATOR_PRICE + PRICE_MARGIN or self.in_last_hours(): # battery cheaper than the grid or last few hours
            spare = max(0.0, battery_at_start - self.reserve())
            battery_used = give("battery", range(len(loads)), spare)
        else:
            battery_used = 0.0

        # grid covers the rest
        if grid_ok:
            give("grid", range(len(loads)), float("inf"))

        # generator charges battery
        charge = 0.0
        if generator_ok and battery_ok and self.hours_left() > 0:
            target = self.reserve()
            if price > GENERATOR_PRICE + PRICE_MARGIN and not self.in_last_hours():
                target = BATTERY_CAP                        # grid is expensive so charge battery
            wanted = target - (battery_at_start - battery_used)
            room = BATTERY_CAP - battery_at_start           # prevents overcharge
            charge = max(0.0, min(wanted, room))

        # update battery estimate and cost
        if battery_ok:
            self.battery = battery_at_start - battery_used + charge
        cost = price * sum(p["grid"] for p in plan) + GENERATOR_PRICE * charge
        self.total_cost += cost
        self.hour += 1
        print(f"[hour {self.hour}] price={price:.2f} battery={self.battery:.1f} "
              f"charge={charge:.1f} cost=${cost:.2f} events={sorted(events)}", file=sys.stderr)

        return {"buildings": [{k: round(v, 6) for k, v in p.items()} for p in plan],
                "generator": round(charge, 6)}

def main():
    controller = Controller()

    with socket.create_connection((HOST, PORT)) as sock:
        while True:
            msg = read_message(sock)

            if msg is None:  # the server hung up, so the day is over
                break

            reply = controller.decide(msg)
            sock.sendall((json.dumps(reply) + "\n").encode())

    print(f"Estimated total cost: ${controller.total_cost:.2f}", file=sys.stderr)


if __name__ == "__main__":
    main()