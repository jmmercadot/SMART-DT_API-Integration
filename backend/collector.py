import datetime
import json
import sys
import threading
import time
from collections import deque

from sif400_client import SIF400Client, SIF400ApiError, PA_AIR_AND_ENERGY, PA_OEE

# SIFMES StationID -> physical station name (confirmed via /api/Inventory StationTypeID)
STATION_MAP = {1: 'SIF-401', 2: 'SIF-402', 3: 'SIF-405', 4: 'SIF-407'}
STATION_IDS = list(STATION_MAP.values())

SYSTEM_STATION = 'SYSTEM'

# Poll intervals (seconds)
FAST_INTERVAL = 5        # checker, ekanban, inventory
ENERGY_INTERVAL = 30     # performanceAnalytics AirAndEnergy for today
OEE_INTERVAL = 60        # performanceAnalytics OEE for today
HISTORY_INTERVAL = 300   # 14-day AirAndEnergy day-bucket series

# Derived power is computed from energy-total deltas over a sliding window;
# totals are integer Wh so a longer window smooths quantization noise.
POWER_WINDOW_SECONDS = 600
POWER_MIN_DELTA_SECONDS = 60

# These bench stations draw at most a few hundred watts. The device occasionally
# returns a garbage EnergyConsumedTotal (typically a transient 0 during a DB
# refresh / exercise transition); when the counter "recovers" the raw delta
# implies an impossible power (millions of watts). Any single sample implying
# instantaneous power beyond this ceiling is treated as a glitch and discarded
# so it can't poison the sliding window. A change sustained for this many
# consecutive samples is accepted as a real counter reset instead.
POWER_SANITY_CEILING_W = 5000
POWER_RESET_CONFIRM_SAMPLES = 3


class SIF400Collector:
    """Polls the real SIFMES-400 API and persists snapshots + energy history to SQLite.

    Two polling threads: a fast one for cheap endpoints (checker/ekanban/inventory)
    and a slow one for performanceAnalytics, whose responses can take tens of
    seconds on the device and must not stall the fast feeds.
    """

    def __init__(self, get_db, client=None):
        self.get_db = get_db  # context manager yielding a sqlite3 connection
        self.client = client or SIF400Client()
        self.running = False
        self.threads = []
        self.lock = threading.Lock()

        self.connected = False
        self.last_success = None
        self.last_error = None
        # feed name -> {'ok', 'last_success', 'last_error'} for diagnosability
        self.feeds = {}

        # station name -> deque of (unix_time, energy_total_wh) for power derivation
        self._energy_window = {name: deque() for name in STATION_IDS}
        # station name -> consecutive implausible-sample count (glitch vs real reset)
        self._glitch_count = {name: 0 for name in STATION_IDS}
        # station name -> latest derived figures (also persisted to DB)
        self.station_state = {name: {'power_w': None, 'energy_today_wh': None,
                                     'energy_total_wh': None, 'timestamp': None}
                              for name in STATION_IDS}

        # Alert thresholds, adjustable via the API
        self.thresholds = {
            'caps_min': 3,        # alert when a SIF-405 feeder has fewer caps than this
            'power_max_w': 500.0  # alert when a station's derived power exceeds this
        }

        # Which two-day PA window worked last (index into _pa_query_today candidates)
        self._pa_range_idx = 0

    # ------------------------------------------------------------------ lifecycle

    def start(self):
        if not self.running:
            self.running = True
            self.threads = [
                threading.Thread(target=self._run_fast, daemon=True),
                threading.Thread(target=self._run_slow, daemon=True),
            ]
            for thread in self.threads:
                thread.start()

    def stop(self):
        self.running = False
        for thread in self.threads:
            thread.join(timeout=FAST_INTERVAL + 1)

    def _run_fast(self):
        while self.running:
            started = time.time()
            if self._poll_checker():
                self._safe('ekanban', self._poll_ekanban)
                self._safe('inventory', self._poll_inventory)
            self._save_connection_snapshot()
            time.sleep(max(0.5, FAST_INTERVAL - (time.time() - started)))

    def _run_slow(self):
        next_energy = next_oee = next_history = 0
        while self.running:
            now = time.time()
            if self.connected:
                if now >= next_energy:
                    self._safe('air_and_energy_today', self._poll_energy_today)
                    next_energy = time.time() + ENERGY_INTERVAL
                if now >= next_oee:
                    self._safe('oee', self._poll_oee)
                    next_oee = time.time() + OEE_INTERVAL
                if now >= next_history:
                    self._safe('air_and_energy_history', self._poll_energy_history)
                    next_history = time.time() + HISTORY_INTERVAL
            time.sleep(1)

    def _safe(self, feed, fn):
        try:
            fn()
            with self.lock:
                self.feeds[feed] = {'ok': True, 'last_success': _now_str(),
                                    'last_error': None}
            return True
        except Exception as exc:  # noqa: BLE001 - collector must never die
            message = f'{type(exc).__name__}: {exc}'
            with self.lock:
                previous = self.feeds.get(feed) or {}
                self.feeds[feed] = {'ok': False,
                                    'last_success': previous.get('last_success'),
                                    'last_error': message}
                self.last_error = f'{feed}: {message}'
            print(f'[collector] {feed} failed: {message}', file=sys.stderr)
            return False

    # ------------------------------------------------------------------ polls

    def _poll_checker(self):
        try:
            self.client.checker()
            with self.lock:
                if not self.connected:
                    self._resolve_connection_alerts()
                self.connected = True
                self.last_success = _now_str()
                self.feeds['checker'] = {'ok': True, 'last_success': self.last_success,
                                         'last_error': None}
            return True
        except Exception as exc:  # noqa: BLE001
            message = f'{type(exc).__name__}: {exc}'
            with self.lock:
                was_connected = self.connected
                self.connected = False
                self.last_error = f'checker: {message}'
                previous = self.feeds.get('checker') or {}
                self.feeds['checker'] = {'ok': False,
                                         'last_success': previous.get('last_success'),
                                         'last_error': message}
            if was_connected:
                print(f'[collector] lost connection to SIF-400 API: {message}', file=sys.stderr)
                with self.get_db() as conn:
                    self._create_alert(conn, SYSTEM_STATION, 'connection',
                                       f'Lost connection to SIF-400 API: {exc}', 'critical')
                    conn.commit()
            return False

    def _poll_ekanban(self):
        data = self.client.ekanban()
        self._save_snapshot('ekanban', data)

    def _poll_inventory(self):
        data = self.client.inventory()
        self._save_snapshot('inventory', data)
        self._check_inventory_alerts(data)

    def _pa_query_today(self, option):
        """Query performanceAnalytics for 'today'.

        The real device rejects same-day ranges (from == to answers
        Success=false), so use a two-day window: prefer (today, tomorrow),
        whose period only contains today's data, and fall back to
        (yesterday, today), from which today's slice is read out of the
        per-day buckets. Remembers which window the device accepts.
        Returns (Object, (date_from, date_to)).
        """
        today = datetime.date.today()
        one_day = datetime.timedelta(days=1)
        candidates = [(today, today + one_day), (today - one_day, today)]
        order = [self._pa_range_idx] + [i for i in range(len(candidates)) if i != self._pa_range_idx]
        last_error = None
        for idx in order:
            date_from, date_to = candidates[idx]
            try:
                data = self.client.performance_analytics(option, date_from, date_to)
                self._pa_range_idx = idx
                return data, (date_from, date_to)
            except SIF400ApiError as exc:  # window rejected; try the other one
                last_error = exc
        raise last_error

    @staticmethod
    def _today_bucket(points):
        """Today's value from a {Values, Labels} day-bucket series (labels are dd/MM/yyyy)."""
        if not points:
            return None
        labels = points.get('Labels') or []
        values = points.get('Values') or []
        key = datetime.date.today().strftime('%d/%m/%Y')
        if key in labels and len(values) > labels.index(key):
            return values[labels.index(key)]
        return values[-1] if values else None

    def _poll_energy_today(self):
        data, window = self._pa_query_today(PA_AIR_AND_ENERGY)
        info = (data or {}).get('PAEAInformation') or {}
        air_today = self._today_bucket(info.get('AirDayPoints'))
        energy_today_line = self._today_bucket(info.get('EnergyConsumedDayPoints'))
        info['_computed_today'] = {
            'air_today': air_today if air_today is not None else info.get('AirConsumedPeriod'),
            'energy_today': energy_today_line if energy_today_line is not None else info.get('EnergyConsumedPeriod'),
            'window': [str(window[0]), str(window[1])],
        }
        self._save_snapshot('air_and_energy_today', info)

        now = time.time()
        timestamp = _now_str()
        with self.get_db() as conn:
            for station in info.get('Stations') or []:
                name = STATION_MAP.get(station.get('StationID'))
                if not name:
                    continue
                energy_today = self._today_bucket(station.get('EnergyConsumedDayPoints'))
                if energy_today is None:
                    energy_today = station.get('EnergyConsumedPeriod')
                energy_total = station.get('EnergyConsumedTotal')
                power = self._derive_power(name, now, energy_total)

                with self.lock:
                    self.station_state[name] = {
                        'power_w': power,
                        'energy_today_wh': energy_today,
                        'energy_total_wh': energy_total,
                        'timestamp': timestamp,
                    }
                conn.execute('''
                    INSERT INTO energy_measurements (station_id, power_w, energy_today_wh, energy_total_wh, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                ''', (name, power, energy_today, energy_total, timestamp))

                if power is not None and power > self.thresholds['power_max_w']:
                    self._create_alert(conn, name, 'power',
                                       f'Power anomaly: {power:.0f}W exceeds limit of '
                                       f'{self.thresholds["power_max_w"]:.0f}W', 'warning')
            conn.commit()

    def _poll_oee(self):
        data, window = self._pa_query_today(PA_OEE)
        info = (data or {}).get('PAOEEInformation') or {}
        # OEE has no per-day buckets, so the metrics cover the whole queried
        # window; record it so the UI can label the numbers honestly.
        info['_window'] = [str(window[0]), str(window[1])]
        self._save_snapshot('oee', info)

    def _poll_energy_history(self):
        today = datetime.date.today()
        data = self.client.performance_analytics(PA_AIR_AND_ENERGY, today - datetime.timedelta(days=13), today)
        self._save_snapshot('air_and_energy_history', (data or {}).get('PAEAInformation') or {})

    # ------------------------------------------------------------------ derivations

    def _derive_power(self, station, now, energy_total):
        """Average power (W) from Wh-total delta over a sliding window.

        Guards against the device's occasional garbage EnergyConsumedTotal
        readings: a single sample implying impossible instantaneous power (a
        spike, or the recovery from a transient 0) is discarded so it can't
        poison the window; only a change sustained across several samples is
        accepted as a genuine counter reset.
        """
        if energy_total is None:
            return None
        energy_total = float(energy_total)
        window = self._energy_window[station]

        if window:
            last_time, last_total = window[-1]
            dt = now - last_time
            if dt <= 0:
                return None
            inst_power = (energy_total - last_total) / (dt / 3600.0)
            if inst_power < 0 or inst_power > POWER_SANITY_CEILING_W:
                # Implausible jump. Treat as a one-off glitch and drop it, unless
                # it persists (genuine reset, e.g. a new exercise) - then rebase.
                self._glitch_count[station] += 1
                if self._glitch_count[station] >= POWER_RESET_CONFIRM_SAMPLES:
                    window.clear()
                    window.append((now, energy_total))
                    self._glitch_count[station] = 0
                return None
            self._glitch_count[station] = 0

        window.append((now, energy_total))
        while window and now - window[0][0] > POWER_WINDOW_SECONDS:
            window.popleft()
        oldest_time, oldest_total = window[0]
        elapsed = now - oldest_time
        if elapsed < POWER_MIN_DELTA_SECONDS:
            return None
        delta_wh = energy_total - oldest_total
        if delta_wh < 0:  # shouldn't happen given the guard above, but stay safe
            window.clear()
            window.append((now, energy_total))
            return None
        power = round(delta_wh / (elapsed / 3600.0), 1)
        return power if power <= POWER_SANITY_CEILING_W else None

    def _check_inventory_alerts(self, data):
        caps_min = self.thresholds['caps_min']
        with self.get_db() as conn:
            for station in (data or {}).get('Stations') or []:
                name = STATION_MAP.get(station.get('StationID'))
                if not name:
                    continue
                for loader in station.get('ContainerLoaders') or []:
                    if loader.get('Presence') is False:
                        self._create_alert(conn, name, f'loader_{loader.get("LoaderNumber")}',
                                           f'Container loader {loader.get("LoaderNumber")} '
                                           f'({loader.get("ContainerType")}) has no containers', 'warning')
                pallet = station.get('PalletLoader')
                if pallet and pallet.get('Presence') is False:
                    self._create_alert(conn, name, 'pallet_loader',
                                       'Pallet loader has no pallets', 'warning')
                for hopper in station.get('Hoppers') or []:
                    if hopper.get('Presence') is False:
                        self._create_alert(conn, name, f'hopper_{hopper.get("HopperNumber")}',
                                           f'Hopper {hopper.get("HopperNumber")} '
                                           f'({hopper.get("Color")}) is not present', 'warning')
                for feeder in station.get('Feeders') or []:
                    count = feeder.get('CapCount')
                    if count is not None and count < caps_min:
                        self._create_alert(conn, name, f'feeder_{feeder.get("FeederNumber")}',
                                           f'Feeder {feeder.get("FeederNumber")} low on '
                                           f'{str(feeder.get("CapType", "")).lower()} caps: '
                                           f'{count} left (minimum {caps_min})', 'warning')
            conn.commit()

    def station_status(self, station, active_alert_stations):
        """normal | warning | offline for the dashboard cards."""
        if not self.connected:
            return 'offline'
        return 'warning' if station in active_alert_stations else 'normal'

    # ------------------------------------------------------------------ persistence

    def _save_snapshot(self, key, obj):
        with self.get_db() as conn:
            conn.execute('''
                INSERT INTO snapshots (key, json, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET json = excluded.json, updated_at = excluded.updated_at
            ''', (key, json.dumps(obj), _now_str()))
            conn.commit()

    def _save_connection_snapshot(self):
        with self.lock:
            snapshot = {
                'connected': self.connected,
                'last_success': self.last_success,
                'last_error': self.last_error,
                'api_base': self.client.base_url,
                'feeds': dict(self.feeds),
            }
        self._save_snapshot('connection', snapshot)

    def _create_alert(self, conn, station_id, alert_type, message, severity):
        # Suppress duplicates while an alert is open, and snooze re-raising for
        # 5 minutes after one is dismissed even if the condition persists.
        existing = conn.execute('''
            SELECT id FROM alerts
            WHERE station_id = ? AND alert_type = ?
            AND (resolved = FALSE OR timestamp > datetime('now', 'localtime', '-5 minutes'))
        ''', (station_id, alert_type)).fetchone()
        if not existing:
            conn.execute('''
                INSERT INTO alerts (station_id, alert_type, message, severity, timestamp)
                VALUES (?, ?, ?, ?, ?)
            ''', (station_id, alert_type, message, severity, _now_str()))

    def _resolve_connection_alerts(self):
        with self.get_db() as conn:
            conn.execute('''
                UPDATE alerts SET resolved = TRUE
                WHERE station_id = ? AND alert_type = 'connection' AND resolved = FALSE
            ''', (SYSTEM_STATION,))
            conn.commit()


def _now_str():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
