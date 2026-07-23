import sqlite3
import re
import json
from typing import List, Dict, Any

# SIFMES StationID -> station name (kept in sync with collector.STATION_MAP)
STATION_MAP = {1: 'SIF-401', 2: 'SIF-402', 3: 'SIF-405', 4: 'SIF-407'}

STATION_ROLES = {
    'SIF-401': 'container & pallet loading',
    'SIF-402': 'hopper filling',
    'SIF-405': 'cap feeding & placement',
    'SIF-407': 'delivery',
}


class NLPService:
    def __init__(self, db_path: str = 'sif400.db'):
        self.db_path = db_path
        self.stations = list(STATION_MAP.values())
        self.thresholds = None  # Will be set by the main app

    def get_db_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def set_thresholds(self, thresholds: Dict):
        """Update the thresholds reference from the main application"""
        self.thresholds = thresholds

    def process_query(self, query: str) -> str:
        """Process natural language query and return appropriate response"""
        query_lower = query.lower().strip()

        current_data = self._get_current_status()
        alerts = self._get_active_alerts()

        intent = self._classify_intent(query_lower)

        if intent == 'status_overview':
            return self._generate_status_overview(current_data, alerts)
        elif intent == 'legacy_electrical':
            return self._generate_legacy_electrical_response(current_data)
        elif intent == 'power_query':
            return self._generate_power_response(query_lower, current_data)
        elif intent == 'energy_query':
            return self._generate_energy_response(query_lower, current_data)
        elif intent == 'air_query':
            return self._generate_air_response()
        elif intent == 'caps_query':
            return self._generate_caps_response()
        elif intent == 'inventory_query':
            return self._generate_inventory_response(query_lower)
        elif intent == 'oee_query':
            return self._generate_oee_response(query_lower)
        elif intent == 'alert_query':
            return self._generate_alert_response(alerts)
        elif intent == 'connection_query':
            return self._generate_connection_response()
        elif intent == 'trend_query':
            return self._generate_trend_response(query_lower, current_data)
        elif intent == 'station_specific':
            station = self._extract_station(query_lower)
            return self._generate_station_response(station, current_data)
        elif intent == 'comparison':
            return self._generate_comparison_response(current_data)
        else:
            return self._generate_help_response(current_data)

    def _classify_intent(self, query: str) -> str:
        """Classify the intent of the user query"""

        patterns = {
            # Voltage/current are not exposed by the SIFMES-400 API; explain instead of guessing
            'legacy_electrical': [r'voltage', r'\bvolt', r'\bamp', r'amperage', r'\bcurrent\b(?!.*status)'],
            'alert_query': [r'alert', r'warning', r'problem', r'issue', r'error', r'fault', r'anomal'],
            'connection_query': [r'connect', r'online', r'offline', r'reachab', r'api.*(up|down|status)', r'link'],
            'caps_query': [r'\bcaps?\b', r'\blids?\b', r'kanban', r'feeder'],
            'inventory_query': [r'inventor', r'stock', r'material', r'container', r'hopper', r'pallet', r'supply', r'supplies'],
            'oee_query': [r'\boee\b', r'availability', r'effectiveness', r'efficien', r'quality', r'cycle', r'stops?\b', r'units'],
            'air_query': [r'\bair\b', r'pneumatic', r'compress'],
            'energy_query': [r'energy', r'\bwh\b', r'kwh', r'consumption', r'consumed'],
            'power_query': [r'power', r'\bwatt', r'\bw\b'],
            'trend_query': [r'trend', r'history', r'over.*time', r'past.*hour', r'changing', r'increasing', r'decreasing'],
            'station_specific': [r'sif[-\s]?40[1257]', r'station.*40[1257]'],
            'comparison': [r'compar', r'differ', r'which.*(higher|lower|most|least)', r'best.*perform', r'worst.*perform'],
            'status_overview': [r'(how|what).*(status|doing|operating)', r'(overall|general|current).*(status|condition)',
                                r'(summary|overview)', r'how.*(station|everything|factory|line)'],
        }

        for intent, intent_patterns in patterns.items():
            if any(re.search(p, query) for p in intent_patterns):
                return intent
        return 'general'

    def _extract_station(self, query: str) -> str:
        """Extract station ID from query"""
        for station in self.stations:
            if station.lower().replace('-', '') in query.replace('-', '').replace(' ', ''):
                return station
        return None

    # ------------------------------------------------------------------ data access

    def _get_current_status(self) -> Dict[str, Any]:
        """Latest energy measurement per station"""
        with self.get_db_connection() as conn:
            status = {}
            for station_id in self.stations:
                measurement = conn.execute('''
                    SELECT power_w, energy_today_wh, energy_total_wh, timestamp
                    FROM energy_measurements
                    WHERE station_id = ?
                    ORDER BY timestamp DESC
                    LIMIT 1
                ''', (station_id,)).fetchone()
                if measurement:
                    status[station_id] = dict(measurement)
            return status

    def _get_active_alerts(self) -> List[Dict[str, Any]]:
        with self.get_db_connection() as conn:
            alerts = conn.execute('''
                SELECT station_id, alert_type, message, severity, timestamp
                FROM alerts
                WHERE resolved = FALSE
                ORDER BY timestamp DESC
                LIMIT 10
            ''').fetchall()
            return [dict(alert) for alert in alerts]

    def _get_snapshot(self, key: str):
        with self.get_db_connection() as conn:
            row = conn.execute('SELECT json, updated_at FROM snapshots WHERE key = ?', (key,)).fetchone()
            if not row:
                return None, None
            return json.loads(row['json']), row['updated_at']

    # ------------------------------------------------------------------ responses

    def _format_power(self, data: Dict) -> str:
        power = data.get('power_w')
        return f'{power:.0f}W' if power is not None else 'measuring...'

    def _generate_status_overview(self, current_data: Dict, alerts: List) -> str:
        connection, _ = self._get_snapshot('connection')
        connected = bool(connection and connection.get('connected'))

        response = "📊 SIF-400 System Status Overview:\n\n"
        response += "🟢 SIF-400 API link: connected\n" if connected else "🔴 SIF-400 API link: DISCONNECTED\n"

        if current_data:
            response += "\n📈 Station Readings (today):\n"
            for station_id, data in current_data.items():
                energy = data.get('energy_today_wh')
                energy_text = f'{energy:.0f}Wh' if energy is not None else 'n/a'
                response += f"• {station_id}: {self._format_power(data)}, {energy_text} consumed\n"

        ekanban, _ = self._get_snapshot('ekanban')
        caps = self._total_caps(ekanban)
        if caps is not None:
            response += f"\n🧢 Caps remaining in SIF-405: {caps}\n"

        if alerts:
            response += f"\n🚨 Active Alerts ({len(alerts)}):\n"
            for alert in alerts[:3]:
                response += f"• {alert['station_id']}: {alert['message']}\n"
        else:
            response += "\n✅ No active alerts"

        return response

    def _generate_legacy_electrical_response(self, current_data: Dict) -> str:
        response = ("ℹ️ The SIF-400 API doesn't expose voltage or current readings — "
                    "it reports energy consumption per station. Here's the closest real data:\n\n")
        for station_id, data in current_data.items():
            energy = data.get('energy_today_wh')
            energy_text = f'{energy:.0f}Wh today' if energy is not None else 'no data yet'
            response += f"⚡ {station_id}: {self._format_power(data)} (avg), {energy_text}\n"
        return response

    def _generate_power_response(self, query: str, current_data: Dict) -> str:
        station = self._extract_station(query)

        if station and station in current_data:
            data = current_data[station]
            return (f"⚡ {station} Power: {self._format_power(data)} "
                    f"(average over the last few minutes, derived from energy consumption)")

        response = "⚡ Current Power (derived from energy deltas):\n"
        total = 0.0
        known = 0
        for station_id, data in current_data.items():
            response += f"• {station_id}: {self._format_power(data)}\n"
            if data.get('power_w') is not None:
                total += data['power_w']
                known += 1
        if known:
            response += f"\n📊 Total line power: {total:.0f}W"
        return response

    def _generate_energy_response(self, query: str, current_data: Dict) -> str:
        station = self._extract_station(query)

        if station and station in current_data:
            data = current_data[station]
            today = data.get('energy_today_wh')
            total = data.get('energy_total_wh')
            response = f"🔋 {station} Energy:\n"
            response += f"• Today: {today:.0f}Wh\n" if today is not None else "• Today: n/a\n"
            response += f"• Lifetime total: {total / 1000:.1f}kWh" if total is not None else "• Lifetime total: n/a"
            return response

        response = "🔋 Energy Consumed Today:\n"
        for station_id, data in current_data.items():
            today = data.get('energy_today_wh')
            response += f"• {station_id}: {today:.0f}Wh\n" if today is not None else f"• {station_id}: n/a\n"

        air_energy, _ = self._get_snapshot('air_and_energy_today')
        if air_energy:
            computed = air_energy.get('_computed_today') or {}
            line_today = computed.get('energy_today', air_energy.get('EnergyConsumedPeriod'))
            if line_today is not None:
                response += f"\n📊 Whole line today: {line_today:.0f}Wh"
                if air_energy.get('EnergyConsumedTotal') is not None:
                    response += f" (lifetime {air_energy['EnergyConsumedTotal'] / 1000:.0f}kWh)"
        return response

    def _generate_air_response(self) -> str:
        air_energy, updated = self._get_snapshot('air_and_energy_today')
        if not air_energy:
            return "💨 No air consumption data received from the SIF-400 yet."
        response = "💨 Compressed Air Consumption (line-wide):\n"
        computed = air_energy.get('_computed_today') or {}
        air_today = computed.get('air_today', air_energy.get('AirConsumedPeriod'))
        if air_today is not None:
            response += f"• Today: {air_today}L\n"
        if air_energy.get('AirConsumedTotal') is not None:
            response += f"• Lifetime total: {air_energy['AirConsumedTotal']}L\n"
        if updated:
            response += f"(updated {updated})"
        return response

    def _total_caps(self, ekanban):
        if not ekanban:
            return None
        total = 0
        found = False
        for station in ekanban.get('stations') or []:
            for charger in (station.get('lids_left') or {}).values():
                if charger.get('left') is not None:
                    total += charger['left']
                    found = True
        return total if found else None

    def _generate_caps_response(self) -> str:
        ekanban, updated = self._get_snapshot('ekanban')
        if not ekanban:
            return "🧢 No e-kanban cap data received from the SIF-400 yet."

        response = "🧢 Caps Remaining (SIF-405 e-kanban):\n"
        for station in ekanban.get('stations') or []:
            for charger_name, charger in sorted((station.get('lids_left') or {}).items()):
                cap_type = str(charger.get('type', 'unknown')).title()
                left = charger.get('left')
                warn = ''
                if self.thresholds and left is not None and left < self.thresholds.get('caps_min', 0):
                    warn = ' ⚠️ below minimum!'
                response += f"• {charger_name.replace('_', ' ').title()} ({cap_type}): {left}{warn}\n"
        total = self._total_caps(ekanban)
        if total is not None:
            response += f"\n📊 Total caps left: {total}"
        if updated:
            response += f"\n(updated {updated})"
        return response

    def _generate_inventory_response(self, query: str) -> str:
        inventory, updated = self._get_snapshot('inventory')
        if not inventory:
            return "📦 No inventory data received from the SIF-400 yet."

        wanted = self._extract_station(query)
        response = "📦 SIF-400 Raw Material Inventory:\n"
        for station in inventory.get('Stations') or []:
            name = STATION_MAP.get(station.get('StationID'), f"Station {station.get('StationID')}")
            if wanted and name != wanted:
                continue
            response += f"\n{name} ({STATION_ROLES.get(name, 'station')}):\n"
            for loader in station.get('ContainerLoaders') or []:
                presence = '✅' if loader.get('Presence') else '❌ empty'
                response += (f"• Loader {loader.get('LoaderNumber')} "
                             f"({loader.get('ContainerType')}): {presence}\n")
            pallet = station.get('PalletLoader')
            if pallet:
                presence = '✅' if pallet.get('Presence') else '❌ empty'
                response += f"• Pallet loader (pos {pallet.get('Position')}): {presence}\n"
            for hopper in station.get('Hoppers') or []:
                presence = '✅' if hopper.get('Presence') else '❌ missing'
                response += f"• Hopper {hopper.get('HopperNumber')} ({hopper.get('Color')}): {presence}\n"
            for feeder in station.get('Feeders') or []:
                response += (f"• Feeder {feeder.get('FeederNumber')} "
                             f"({feeder.get('CapType')} caps): {feeder.get('CapCount')} left\n")
        if updated:
            response += f"\n(updated {updated})"
        return response

    def _generate_oee_response(self, query: str) -> str:
        oee, updated = self._get_snapshot('oee')
        if not oee or not oee.get('Stations'):
            return "📐 No OEE data received from the SIF-400 yet."

        wanted = self._extract_station(query)
        response = "📐 OEE (today):\n"
        for station in oee['Stations']:
            name = STATION_MAP.get(station.get('StationID'))
            if not name:
                continue  # StationID 0 = aggregate row without a physical station
            if wanted and name != wanted:
                continue
            response += (f"\n{name}: OEE {station.get('OEE', 0):.0%} — "
                         f"availability {station.get('Availability', 0):.0%}, "
                         f"performance {station.get('Performance', 0):.0%}, "
                         f"quality {station.get('Quality', 0):.0%}\n")
            if station.get('TotalUnits'):
                response += (f"• Units: {station.get('GoodUnits', 0):.0f} good / "
                             f"{station.get('RejectedUnits', 0):.0f} rejected "
                             f"of {station.get('TotalUnits', 0):.0f}\n")
            if station.get('RunningTimeFormatted') and station['RunningTimeFormatted'] != '00:00:00':
                response += f"• Running time: {station['RunningTimeFormatted']}\n"
        if updated:
            response += f"\n(updated {updated})"
        return response

    def _generate_alert_response(self, alerts: List) -> str:
        if not alerts:
            return "✅ No active alerts. All stations are operating normally."

        response = f"🚨 Active Alerts ({len(alerts)}):\n\n"
        for alert in alerts:
            severity_emoji = "🔴" if alert['severity'] == 'critical' else "⚠️"
            response += f"{severity_emoji} {alert['station_id']}: {alert['message']}\n"
        return response

    def _generate_connection_response(self) -> str:
        connection, updated = self._get_snapshot('connection')
        if not connection:
            return "🔌 The data collector hasn't reported yet — the backend may have just started."

        if connection.get('connected'):
            response = "🟢 Connected to the SIF-400 API"
            if connection.get('last_success'):
                response += f" (last check: {connection['last_success']})"
            failing = {name: feed for name, feed in (connection.get('feeds') or {}).items()
                       if not feed.get('ok')}
            for name, feed in failing.items():
                response += f"\n⚠️ {name} feed failing: {feed.get('last_error')}"
        else:
            response = "🔴 NOT connected to the SIF-400 API"
            if connection.get('last_error'):
                response += f"\nLast error: {connection['last_error']}"
            if connection.get('last_success'):
                response += f"\nLast successful contact: {connection['last_success']}"
        response += f"\nAPI address: {connection.get('api_base')}"
        return response

    def _generate_trend_response(self, query: str, current_data: Dict) -> str:
        station = self._extract_station(query)

        with self.get_db_connection() as conn:
            if station:
                trend_data = conn.execute('''
                    SELECT power_w, energy_today_wh, timestamp FROM energy_measurements
                    WHERE station_id = ? AND power_w IS NOT NULL
                    ORDER BY timestamp DESC
                    LIMIT 10
                ''', (station,)).fetchall()

                if len(trend_data) >= 2:
                    recent = trend_data[0]['power_w']
                    prev = trend_data[-1]['power_w']
                    change = recent - prev
                    direction = "📈 increasing" if change > 0 else "📉 decreasing" if change < 0 else "➡️ stable"
                    return (f"📊 {station} Trend Analysis:\nPower: {recent:.0f}W ({direction})\n"
                            f"Change: {change:+.0f}W over recent readings")
                return f"📊 {station}: not enough power readings yet for a trend — try again in a few minutes."

            response = "📊 System Trend (latest readings):\n"
            for station_id, data in current_data.items():
                energy = data.get('energy_today_wh')
                energy_text = f'{energy:.0f}Wh today' if energy is not None else 'n/a'
                response += f"• {station_id}: {self._format_power(data)}, {energy_text}\n"
            return response

    def _generate_station_response(self, station: str, current_data: Dict) -> str:
        if not station:
            return f"❌ Station not found. Available stations: {', '.join(self.stations)}"

        response = f"🏭 {station} ({STATION_ROLES.get(station, 'station')}):\n"
        data = current_data.get(station)
        if data:
            energy = data.get('energy_today_wh')
            total = data.get('energy_total_wh')
            response += f"⚡ Power: {self._format_power(data)}\n"
            if energy is not None:
                response += f"🔋 Energy today: {energy:.0f}Wh\n"
            if total is not None:
                response += f"🔋 Lifetime energy: {total / 1000:.1f}kWh\n"
        else:
            response += "⚡ No energy readings yet.\n"

        inventory, _ = self._get_snapshot('inventory')
        for inv_station in (inventory or {}).get('Stations') or []:
            if STATION_MAP.get(inv_station.get('StationID')) != station:
                continue
            loaders = inv_station.get('ContainerLoaders') or []
            if loaders:
                present = sum(1 for l in loaders if l.get('Presence'))
                response += f"📦 Container loaders with stock: {present}/{len(loaders)}\n"
            hoppers = inv_station.get('Hoppers') or []
            if hoppers:
                present = sum(1 for h in hoppers if h.get('Presence'))
                response += f"📦 Hoppers present: {present}/{len(hoppers)}\n"
            for feeder in inv_station.get('Feeders') or []:
                response += (f"🧢 Feeder {feeder.get('FeederNumber')} "
                             f"({feeder.get('CapType')}): {feeder.get('CapCount')} caps\n")
        return response

    def _generate_comparison_response(self, current_data: Dict) -> str:
        powered = {s: d['power_w'] for s, d in current_data.items() if d.get('power_w') is not None}
        energies = {s: d['energy_today_wh'] for s, d in current_data.items() if d.get('energy_today_wh') is not None}

        if not powered and not energies:
            return "📊 Not enough data to compare stations yet — the collector needs a few minutes of readings."

        response = "📊 Station Comparison (today):\n\n"
        if powered:
            highest = max(powered, key=powered.get)
            lowest = min(powered, key=powered.get)
            response += f"⚡ Highest power: {highest} ({powered[highest]:.0f}W)\n"
            response += f"⚡ Lowest power: {lowest} ({powered[lowest]:.0f}W)\n"
        if energies:
            highest = max(energies, key=energies.get)
            lowest = min(energies, key=energies.get)
            response += f"🔋 Most energy consumed: {highest} ({energies[highest]:.0f}Wh)\n"
            response += f"🔋 Least energy consumed: {lowest} ({energies[lowest]:.0f}Wh)\n"
        return response

    def _generate_help_response(self, current_data: Dict) -> str:
        response = "🤖 I'm your SIF-400 Digital Twin Assistant! I can help you with:\n\n"
        response += "• Station status, energy, and power readings\n"
        response += "• Compressed air consumption\n"
        response += "• Caps remaining (e-kanban) and raw-material inventory\n"
        response += "• OEE and production metrics\n"
        response += "• Alerts and SIF-400 connection status\n\n"
        response += "Try asking: 'What's the status?', 'How many caps are left?', "
        response += "'Show me the inventory', or 'Any alerts?'\n"

        if current_data:
            response += "\nCurrent readings:\n"
            for station_id, data in current_data.items():
                energy = data.get('energy_today_wh')
                energy_text = f'{energy:.0f}Wh today' if energy is not None else 'n/a'
                response += f"• {station_id}: {self._format_power(data)}, {energy_text}\n"
        return response
