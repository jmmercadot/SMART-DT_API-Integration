from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import sqlite3
import json
import os
import io
import csv
import datetime
from contextlib import contextmanager

from collector import SIF400Collector, STATION_IDS
from nlp_service import NLPService
from sif400_client import PA_OEE

app = Flask(__name__)
CORS(app)

# Database setup. SIF400_DB overrides the file so mock/dev runs can keep their
# data out of the real research database (the mock workflow sets sif400_mock.db).
DATABASE = os.environ.get('SIF400_DB', 'sif400.db')

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

@contextmanager
def get_db():
    conn = get_db_connection()
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with get_db() as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS stations (
                id INTEGER PRIMARY KEY,
                station_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS energy_measurements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                station_id TEXT NOT NULL,
                power_w REAL,
                energy_today_wh REAL,
                energy_total_wh REAL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (station_id) REFERENCES stations (station_id)
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                station_id TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                message TEXT NOT NULL,
                severity TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                resolved BOOLEAN DEFAULT FALSE
            );

            -- Latest raw payloads from the SIFMES-400 API, keyed by feed name
            CREATE TABLE IF NOT EXISTS snapshots (
                key TEXT PRIMARY KEY,
                json TEXT NOT NULL,
                updated_at TIMESTAMP
            );
        ''')

        for station in STATION_IDS:
            conn.execute(
                'INSERT OR IGNORE INTO stations (station_id, name) VALUES (?, ?)',
                (station, f'Station {station}')
            )
        conn.commit()

def read_snapshot(conn, key):
    row = conn.execute('SELECT json, updated_at FROM snapshots WHERE key = ?', (key,)).fetchone()
    if not row:
        return None, None
    return json.loads(row['json']), row['updated_at']

def active_alert_stations(conn):
    rows = conn.execute('''
        SELECT DISTINCT station_id FROM alerts
        WHERE resolved = FALSE AND timestamp > datetime('now', 'localtime', '-5 minutes')
    ''').fetchall()
    return {row['station_id'] for row in rows}

# Initialize collector and NLP service
collector = SIF400Collector(get_db)
nlp_service = NLPService(db_path=DATABASE)
nlp_service.set_thresholds(collector.thresholds)

@app.route('/api/stations', methods=['GET'])
def get_stations():
    with get_db() as conn:
        stations = conn.execute('SELECT * FROM stations').fetchall()
        return jsonify([dict(row) for row in stations])

@app.route('/api/current-status', methods=['GET'])
def get_current_status():
    with get_db() as conn:
        connection, connection_updated = read_snapshot(conn, 'connection')
        air_energy, air_updated = read_snapshot(conn, 'air_and_energy_today')
        alerting = active_alert_stations(conn)

        stations = {}
        for station_id in STATION_IDS:
            state = dict(collector.station_state.get(station_id) or {})
            trend = conn.execute('''
                SELECT power_w, energy_today_wh, timestamp FROM energy_measurements
                WHERE station_id = ?
                ORDER BY timestamp DESC
                LIMIT 20
            ''', (station_id,)).fetchall()
            state['trend'] = [dict(row) for row in reversed(trend)]
            state['status'] = collector.station_status(station_id, alerting)
            stations[station_id] = state

        air = None
        if air_energy:
            computed = air_energy.get('_computed_today') or {}
            air = {
                'air_today_l': computed.get('air_today', air_energy.get('AirConsumedPeriod')),
                'air_total_l': air_energy.get('AirConsumedTotal'),
                'energy_today_wh': computed.get('energy_today', air_energy.get('EnergyConsumedPeriod')),
                'energy_total_wh': air_energy.get('EnergyConsumedTotal'),
                'updated_at': air_updated,
            }

        return jsonify({
            'connection': connection or {'connected': False, 'last_success': None,
                                         'last_error': 'Collector has not run yet',
                                         'api_base': collector.client.base_url},
            'connection_updated': connection_updated,
            'stations': stations,
            'air': air,
        })

@app.route('/api/alerts', methods=['GET'])
def get_alerts():
    with get_db() as conn:
        alerts = conn.execute('''
            SELECT * FROM alerts
            WHERE resolved = FALSE
            ORDER BY timestamp DESC
            LIMIT 10
        ''').fetchall()
        return jsonify([dict(row) for row in alerts])

@app.route('/api/alerts/<int:alert_id>/resolve', methods=['POST'])
def resolve_alert(alert_id):
    with get_db() as conn:
        conn.execute('UPDATE alerts SET resolved = TRUE WHERE id = ?', (alert_id,))
        conn.commit()
    return jsonify({'message': 'Alert resolved'})

@app.route('/api/ekanban', methods=['GET'])
def get_ekanban():
    with get_db() as conn:
        data, updated_at = read_snapshot(conn, 'ekanban')
        return jsonify({'data': data, 'updated_at': updated_at})

@app.route('/api/inventory', methods=['GET'])
def get_inventory():
    with get_db() as conn:
        data, updated_at = read_snapshot(conn, 'inventory')
        return jsonify({'data': data, 'updated_at': updated_at})

@app.route('/api/performance', methods=['GET'])
def get_performance():
    with get_db() as conn:
        today, today_updated = read_snapshot(conn, 'air_and_energy_today')
        history, history_updated = read_snapshot(conn, 'air_and_energy_history')
        oee, oee_updated = read_snapshot(conn, 'oee')
        return jsonify({
            'air_and_energy_today': {'data': today, 'updated_at': today_updated},
            'air_and_energy_history': {'data': history, 'updated_at': history_updated},
            'oee': {'data': oee, 'updated_at': oee_updated},
        })

# Selectable ranges for the measurement-history endpoints (seconds; None = everything)
HISTORY_RANGES = {'1h': 3600, '6h': 21600, '24h': 86400, '7d': 604800, 'all': None}
HISTORY_TARGET_POINTS = 240  # downsample so a range charts to roughly this many buckets
OEE_CACHE_SECONDS = 300

def _history_filter(range_key):
    """(where_sql, params) limiting energy_measurements to the requested range."""
    span = HISTORY_RANGES[range_key]
    if span is None:
        return '', {}
    return "WHERE timestamp >= datetime('now', 'localtime', :since)", {'since': f'-{span} seconds'}

@app.route('/api/history', methods=['GET'])
def get_history():
    range_key = request.args.get('range', '6h')
    if range_key not in HISTORY_RANGES:
        return jsonify({'error': f'range must be one of {sorted(HISTORY_RANGES)}'}), 400

    where, params = _history_filter(range_key)
    with get_db() as conn:
        span = HISTORY_RANGES[range_key]
        if span is None:
            bounds = conn.execute('SELECT MIN(timestamp) AS mn, MAX(timestamp) AS mx FROM energy_measurements').fetchone()
            if not bounds or not bounds['mn']:
                return jsonify({'range': range_key, 'bucket_seconds': 30, 'stations': {}})
            fmt = '%Y-%m-%d %H:%M:%S'
            span = max((datetime.datetime.strptime(bounds['mx'], fmt)
                        - datetime.datetime.strptime(bounds['mn'], fmt)).total_seconds(), 3600)

        bucket = max(30, int(span / HISTORY_TARGET_POINTS))
        rows = conn.execute(f'''
            SELECT station_id,
                   CAST(strftime('%s', timestamp) / :bucket AS INTEGER) * :bucket AS bucket_ts,
                   AVG(power_w) AS power_w,
                   MAX(energy_today_wh) AS energy_today_wh
            FROM energy_measurements
            {where}
            GROUP BY station_id, bucket_ts
            ORDER BY bucket_ts
        ''', {**params, 'bucket': bucket}).fetchall()

    stations = {}
    for row in rows:
        # strftime('%s') read the local timestamp as if UTC; format it back the same way
        ts = datetime.datetime.fromtimestamp(row['bucket_ts'], datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        stations.setdefault(row['station_id'], []).append({
            'timestamp': ts,
            'power_w': round(row['power_w'], 1) if row['power_w'] is not None else None,
            'energy_today_wh': row['energy_today_wh'],
        })
    return jsonify({'range': range_key, 'bucket_seconds': bucket, 'stations': stations})

@app.route('/api/history/export', methods=['GET'])
def export_history():
    range_key = request.args.get('range', 'all')
    if range_key not in HISTORY_RANGES:
        return jsonify({'error': f'range must be one of {sorted(HISTORY_RANGES)}'}), 400

    where, params = _history_filter(range_key)
    with get_db() as conn:
        rows = conn.execute(f'''
            SELECT station_id, timestamp, power_w, energy_today_wh, energy_total_wh
            FROM energy_measurements
            {where}
            ORDER BY station_id, timestamp
        ''', params).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['station_id', 'timestamp', 'power_w', 'energy_today_wh', 'energy_total_wh'])
    for row in rows:
        writer.writerow([row['station_id'], row['timestamp'], row['power_w'],
                         row['energy_today_wh'], row['energy_total_wh']])

    filename = f'sif400_history_{range_key}_{datetime.date.today().isoformat()}.csv'
    return Response(output.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename={filename}'})

@app.route('/api/oee', methods=['GET'])
def get_oee_range():
    """OEE for today (collector cache) or a wider window (queried on demand, cached 5 min)."""
    days = request.args.get('days', 0, type=int)
    if days <= 1:
        with get_db() as conn:
            data, updated = read_snapshot(conn, 'oee')
        return jsonify({'data': data, 'updated_at': updated})

    key = f'oee_{days}d'
    with get_db() as conn:
        cached, updated = read_snapshot(conn, key)
    if cached and updated:
        age = (datetime.datetime.now()
               - datetime.datetime.strptime(updated, '%Y-%m-%d %H:%M:%S')).total_seconds()
        if age < OEE_CACHE_SECONDS:
            return jsonify({'data': cached, 'updated_at': updated})

    today = datetime.date.today()
    date_from = today - datetime.timedelta(days=days)
    try:
        result = collector.client.performance_analytics(PA_OEE, date_from, today)
    except Exception as exc:  # noqa: BLE001 - surface device/network errors to the UI
        if cached:
            return jsonify({'data': cached, 'updated_at': updated, 'stale': True,
                            'error': f'{type(exc).__name__}: {exc}'})
        return jsonify({'data': None, 'error': f'{type(exc).__name__}: {exc}'}), 502

    info = (result or {}).get('PAOEEInformation') or {}
    info['_window'] = [str(date_from), str(today)]
    collector._save_snapshot(key, info)
    return jsonify({'data': info, 'updated_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.get_json()
    message = data.get('message', '')

    if not message:
        return jsonify({'error': 'Message is required'}), 400

    response = nlp_service.process_query(message)
    return jsonify({'response': response})

@app.route('/api/thresholds', methods=['GET'])
def get_thresholds():
    return jsonify(collector.thresholds)

@app.route('/api/thresholds', methods=['PUT'])
def update_thresholds():
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Threshold data is required'}), 400

    required_fields = ['caps_min', 'power_max_w']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400
        if not isinstance(data[field], (int, float)) or data[field] < 0:
            return jsonify({'error': f'Invalid value for {field}: must be a positive number'}), 400

    collector.thresholds.update({
        'caps_min': int(data['caps_min']),
        'power_max_w': float(data['power_max_w']),
    })
    nlp_service.set_thresholds(collector.thresholds)

    return jsonify({
        'message': 'Thresholds updated successfully',
        'thresholds': collector.thresholds
    })


if __name__ == '__main__':
    init_db()
    collector.start()
    try:
        # use_reloader=False: the reloader would spawn a second collector thread
        app.run(debug=True, use_reloader=False, host='0.0.0.0', port=5001)
    finally:
        collector.stop()
