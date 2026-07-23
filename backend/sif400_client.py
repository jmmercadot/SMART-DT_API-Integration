import os
import requests

# All SIFMES-400 responses share the envelope {"Success": bool, "Error": str|null, "Object": ...}
# (verified against the live API; see api_probe_results_round2/).

DEFAULT_BASE_URL = 'http://130.130.130.199/api'

# paOption values accepted by /api/performanceAnalytics (from /api/Help)
PA_AIR_AND_ENERGY = 'AirAndEnergy'
PA_OEE = 'OEE'
PA_PRODUCTION_AND_LOGISTICS = 'ProductionAndLogistics'
PA_QUALITY = 'Quality'


class SIF400ApiError(Exception):
    """The API answered but reported failure (Success=false or bad payload)."""


class SIF400Client:
    def __init__(self, base_url=None, timeout=5, pa_timeout=30):
        self.base_url = (base_url or os.environ.get('SIF400_API_BASE', DEFAULT_BASE_URL)).rstrip('/')
        self.timeout = timeout
        # performanceAnalytics aggregates dashboard data on the device and can
        # take well over 5s to answer (the discovery probes needed a 20s budget)
        self.pa_timeout = pa_timeout
        self.session = requests.Session()
        self.session.headers['Accept'] = 'application/json'

    def _get(self, path, timeout=None):
        response = self.session.get(f'{self.base_url}/{path}', timeout=timeout or self.timeout)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or 'Success' not in data:
            raise SIF400ApiError(f'{path}: unexpected response shape')
        if not data['Success']:
            raise SIF400ApiError(data.get('Error') or f'{path}: API reported Success=false')
        return data.get('Object')

    def checker(self):
        """Connectivity probe. Returns True if the API answered Success=true."""
        self._get('checker')
        return True

    def ekanban(self):
        """Remaining caps in SIF-405, e.g. {"stations": [{"stationId": 3, "lids_left": {...}}]}"""
        return self._get('ekanban')

    def inventory(self):
        """Raw-material inventory for every station: {"Stations": [{"StationID", "StationTypeID", ...}]}"""
        return self._get('Inventory')

    def performance_analytics(self, pa_option, date_from, date_to):
        """Performance Analytics dashboards. Dates are datetime.date; API wants MM/dd/YYYY.

        The query string is built by hand so the date slashes stay literal
        (requests' params= would encode them as %2F; the verified-working
        probe requests sent them unencoded)."""
        query = (f'performanceAnalytics?paOption={pa_option}'
                 f'&from={date_from.strftime("%m/%d/%Y")}'
                 f'&to={date_to.strftime("%m/%d/%Y")}')
        return self._get(query, timeout=self.pa_timeout)
