"""Mock of the real SIFMES-400 API for development away from the lab network.

Replicates the endpoints, envelope, and payload shapes captured from the live
device (see api_probe_results_round2/). Run it, then point the backend at it:

    python mock_sifmes_api.py                     # serves on http://localhost:8199/api
    SIF400_API_BASE=http://localhost:8199/api python app.py   # (or set the env var on Windows)

The mock "produces": station energy totals accumulate at realistic rates, caps
count down and refill, and loaders occasionally run empty so alerts can be seen.
"""
import datetime
import random
import time

from flask import Flask, request, jsonify

app = Flask(__name__)

START_TIME = time.time()

# Baseline lifetime totals taken from the real capture
BASE_ENERGY_TOTALS = {1: 858665.0, 2: 962628.0, 3: 1118144.0, 4: 756066.0}
BASE_AIR_TOTAL = 34085.0

# Nominal draw per station in W while "producing" (mock line always produces)
STATION_POWER_W = {1: 79.0, 2: 80.0, 3: 107.0, 4: 69.0}
AIR_L_PER_HOUR = 14.0


def _elapsed_hours():
    return (time.time() - START_TIME) / 3600.0


def _energy_total(station_id):
    wobble = 1.0 + 0.25 * random.uniform(-1, 1)
    return BASE_ENERGY_TOTALS[station_id] + STATION_POWER_W[station_id] * _elapsed_hours() * wobble


def _envelope(obj):
    return jsonify({'Success': True, 'Error': None, 'Object': obj})


@app.route('/api/checker')
def checker():
    return jsonify({'Success': True, 'Error': None, 'Object': None})


@app.route('/api/ekanban')
def ekanban():
    # Caps count down over time and refill, mimicking consumption on SIF-405
    cycle = int(time.time() / 45)
    return _envelope({'stations': [{
        'stationId': 3,
        'lids_left': {
            'charger_1': {'type': 'round', 'left': 8 - (cycle % 9)},
            'charger_2': {'type': 'square', 'left': 9 - ((cycle + 3) % 10)},
        },
    }]})


@app.route('/api/Inventory')
def inventory():
    cycle = int(time.time() / 45)
    # Loader 4 and the pallet loader flip presence periodically (on different
    # phases) so their inventory alerts - and alert tips - can be exercised
    loader4_present = (int(time.time() / 120) % 2) == 0
    pallet_present = (int(time.time() / 60) % 2) == 1
    return _envelope({'Stations': [
        {
            'StationID': 1, 'StationTypeID': 401,
            'ContainerLoaders': [
                {'LoaderNumber': 1, 'ContainerType': 'Square', 'Presence': True, 'Minimum': True},
                {'LoaderNumber': 2, 'ContainerType': 'Square', 'Presence': True, 'Minimum': True},
                {'LoaderNumber': 3, 'ContainerType': 'Square', 'Presence': True, 'Minimum': True},
                {'LoaderNumber': 4, 'ContainerType': 'Round', 'Presence': loader4_present, 'Minimum': True},
                {'LoaderNumber': 5, 'ContainerType': 'Round', 'Presence': True, 'Minimum': True},
            ],
            'PalletLoader': {'Position': 'c0', 'Presence': pallet_present, 'Minimum': True},
        },
        {
            'StationID': 2, 'StationTypeID': 402,
            'Hoppers': [
                {'HopperNumber': 1, 'Color': 'Blue', 'Presence': True, 'Minimum': True},
                {'HopperNumber': 2, 'Color': 'Yellow', 'Presence': True, 'Minimum': True},
                {'HopperNumber': 3, 'Color': 'Red', 'Presence': True, 'Minimum': True},
            ],
        },
        {
            'StationID': 3, 'StationTypeID': 405,
            'Feeders': [
                {'FeederNumber': 1, 'CapType': 'Round', 'CapCount': 8 - (cycle % 9)},
                {'FeederNumber': 2, 'CapType': 'Square', 'CapCount': 9 - ((cycle + 3) % 10)},
            ],
        },
    ]})


def _day_series(date_from, date_to, daily_value):
    days = (date_to - date_from).days + 1
    labels = [(date_from + datetime.timedelta(days=i)).strftime('%d/%m/%Y') for i in range(days)]
    values = [round(daily_value * random.uniform(0, 1.4)) for _ in range(days)]
    if days:
        values[-1] = round(daily_value * random.uniform(0.2, 0.6))  # today still in progress
    mean = round(sum(values) / days) if days else 0
    return {'Values': values, 'Labels': labels, 'Means': [mean] * days}


@app.route('/api/performanceAnalytics')
def performance_analytics():
    option = request.args.get('paOption', '')
    try:
        date_from = datetime.datetime.strptime(request.args.get('from', ''), '%m/%d/%Y').date()
        date_to = datetime.datetime.strptime(request.args.get('to', ''), '%m/%d/%Y').date()
    except ValueError:
        return jsonify({'Success': False, 'Error': 'Invalid date', 'Object': None})

    # The real device answers Success=false for same-day ranges (from == to);
    # be strict about future 'to' as well so clients exercise their fallback.
    if date_from >= date_to or date_to > datetime.date.today():
        return jsonify({'Success': False, 'Error': None, 'Object': None})

    if option == 'AirAndEnergy':
        stations = []
        line_period = 0.0
        line_total = 0.0
        for sid in (1, 2, 3, 4):
            total = _energy_total(sid)
            period = STATION_POWER_W[sid] * min(_elapsed_hours(), 8.0) * random.uniform(0.8, 1.2)
            line_period += period
            line_total += total
            stations.append({
                'StationID': sid,
                'EnergyConsumedPeriod': round(period),
                'EnergyConsumedTotal': round(total),
                'EnergyConsumedMinutePoints': None,
                'EnergyConsumedHourPoints': None,
                'EnergyConsumedDayPoints': _day_series(date_from, date_to, STATION_POWER_W[sid] * 4),
                'EnergyConsumedMonthPoints': None,
            })
        return _envelope({'PAEAInformation': {
            'AirConsumedPeriod': round(AIR_L_PER_HOUR * min(_elapsed_hours(), 8.0)),
            'AirConsumedTotal': round(BASE_AIR_TOTAL + AIR_L_PER_HOUR * _elapsed_hours()),
            'AirMinutePoints': None,
            'AirHourPoints': None,
            'AirDayPoints': _day_series(date_from, date_to, AIR_L_PER_HOUR * 4),
            'AirMonthPoints': None,
            'EnergyConsumedPeriod': round(line_period),
            'EnergyConsumedTotal': round(line_total),
            'EnergyConsumedMinutePoints': None,
            'EnergyConsumedHourPoints': None,
            'EnergyConsumedDayPoints': _day_series(date_from, date_to, sum(STATION_POWER_W.values()) * 4),
            'EnergyConsumedMonthPoints': None,
            'Stations': stations,
        }})

    if option == 'OEE':
        # Mirror the real line: OEE is only nonzero for windows containing an
        # MES-managed production run. Short windows (today-ish) come back zero.
        if (date_to - date_from).days <= 2:
            zero = {'OEE': 0.0, 'Availability': 0.0, 'Performance': 0.0, 'Quality': 0.0,
                    'MeanProductionCapacity': 0.0,
                    'TotalPlannedStops': 0.0, 'TotalPlannedStopTime': 0.0,
                    'TotalPlannedStopTimeFormatted': '00:00:00',
                    'TotalUnplannedStops': 0.0, 'TotalUnplannedStopTime': 0.0,
                    'TotalUnplannedStopTimeFormatted': '00:00:00',
                    'TotalCycles': 0.0, 'TotalCycleTime': 0.0,
                    'TotalCycleTimeFormatted': '00:00:00',
                    'RunningTime': 0.0, 'RunningTimeFormatted': '00:00:00',
                    'AvailableTime': 0.0, 'AvailableTimeFormatted': '00:00:00',
                    'ExpectedUnits': 0.0, 'TotalUnits': 0.0, 'GoodUnits': 0.0,
                    'RejectedUnits': 0.0, 'StatusBar': None}
            return _envelope({'PAOEEInformation': {
                'Stations': [dict(zero, StationID=sid) for sid in (1, 2, 3, 4, 0)]}})
        stations = []
        for sid in (1, 2, 3, 4, 0):  # StationID 0 mirrors the real API's aggregate row
            availability = random.uniform(0.7, 0.98)
            performance = random.uniform(0.6, 0.95)
            quality = random.uniform(0.9, 1.0)
            total_units = random.randint(20, 60)
            good = round(total_units * quality)
            stations.append({
                'StationID': sid,
                'OEE': round(availability * performance * quality, 3),
                'Availability': round(availability, 3),
                'Performance': round(performance, 3),
                'Quality': round(quality, 3),
                'MeanProductionCapacity': round(random.uniform(30, 60), 1),
                'TotalPlannedStops': float(random.randint(0, 3)),
                'TotalPlannedStopTime': 0.0, 'TotalPlannedStopTimeFormatted': '00:05:00',
                'TotalUnplannedStops': float(random.randint(0, 2)),
                'TotalUnplannedStopTime': 0.0, 'TotalUnplannedStopTimeFormatted': '00:02:30',
                'TotalCycles': float(total_units),
                'TotalCycleTime': 0.0, 'TotalCycleTimeFormatted': '01:10:00',
                'RunningTime': 0.0, 'RunningTimeFormatted': '03:45:00',
                'AvailableTime': 0.0, 'AvailableTimeFormatted': '04:00:00',
                'ExpectedUnits': float(total_units + random.randint(0, 10)),
                'TotalUnits': float(total_units),
                'GoodUnits': float(good),
                'RejectedUnits': float(total_units - good),
                'StatusBar': None,
            })
        return _envelope({'PAOEEInformation': {'Stations': stations}})

    # Real API answers Success=false for unknown options
    return jsonify({'Success': False, 'Error': None, 'Object': None})


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8199)
