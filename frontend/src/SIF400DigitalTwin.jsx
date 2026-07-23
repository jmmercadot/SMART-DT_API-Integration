import React, { useState, useEffect, useRef } from 'react';
import {
  Activity, AlertTriangle, CheckCircle, Send, Zap, TrendingUp, Bot, Settings,
  ChevronDown, ChevronUp, Package, Layers, Gauge, Wind, WifiOff, CircleSlash, X,
  Moon, Sun, Download, LineChart
} from 'lucide-react';

const STATION_ROLES = {
  'SIF-401': 'Container & pallet loading',
  'SIF-402': 'Hopper filling',
  'SIF-405': 'Cap feeding & placement',
  'SIF-407': 'Delivery',
};

const STATION_ID_TO_NAME = { 1: 'SIF-401', 2: 'SIF-402', 3: 'SIF-405', 4: 'SIF-407' };

const STATION_COLORS = {
  'SIF-401': '#3b82f6', 'SIF-402': '#a855f7', 'SIF-405': '#f59e0b', 'SIF-407': '#22c55e',
};

const HOPPER_COLORS = {
  Blue: 'bg-blue-500', Yellow: 'bg-yellow-400', Red: 'bg-red-500', Green: 'bg-green-500',
};

// Troubleshooting tips attached to alerts, matched by station + alert type
const ALERT_TIPS = [
  {
    match: (alert) => alert.station_id === 'SIF-401' && /^loader_[45]$/.test(alert.alert_type),
    tip: 'If this loader is stocked, try pressing the bottommost canister against the wall of the loader.',
  },
  {
    match: (alert) => alert.alert_type === 'pallet_loader',
    tip: 'If this was caused by a material changeover, disregard this warning.',
  },
];
const getAlertTip = (alert) => ALERT_TIPS.find(t => t.match(alert))?.tip || null;

// Friendly label for which SIFMES API the backend is polling, from its base URL
const apiSourceLabel = (apiBase) => {
  if (!apiBase) return null;
  if (apiBase.includes('130.130.130.199')) return { text: 'Lab API', mock: false };
  if (/localhost|127\.0\.0\.1|8199/.test(apiBase)) return { text: 'Mock API', mock: true };
  return { text: apiBase, mock: false };
};

const HISTORY_RANGES = ['1h', '6h', '24h', '7d', 'all'];
const OEE_RANGES = [
  { label: 'Today', days: 0 },
  { label: '7 days', days: 7 },
  { label: '30 days', days: 30 },
];

// Default panel order per column; users rearrange via the hover arrows
// (persisted in localStorage under LAYOUT_KEY)
const DEFAULT_LAYOUT = {
  left: ['stations', 'alerts', 'history', 'inventory', 'ekanban', 'oee'],
  right: ['chat', 'line'],
};
const LAYOUT_KEY = 'sif400_panel_layout';
const THEME_KEY = 'sif400_theme';

const loadLayout = () => {
  try {
    const saved = JSON.parse(localStorage.getItem(LAYOUT_KEY));
    const sameKeys = (a, b) => [...a].sort().join() === [...b].sort().join();
    if (saved && sameKeys(saved.left || [], DEFAULT_LAYOUT.left)
              && sameKeys(saved.right || [], DEFAULT_LAYOUT.right)) {
      return saved;
    }
  } catch (e) { /* fall through to default */ }
  return DEFAULT_LAYOUT;
};

const SIF400DigitalTwin = () => {
  // State management
  const [stationData, setStationData] = useState({});
  const [sifConnection, setSifConnection] = useState(null);
  const [airData, setAirData] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [inventory, setInventory] = useState(null);
  const [ekanban, setEkanban] = useState(null);
  const [performance, setPerformance] = useState(null);
  const [historyRange, setHistoryRange] = useState('6h');
  const [historyData, setHistoryData] = useState(null);
  const [oeeDays, setOeeDays] = useState(0);
  const [oeeRange, setOeeRange] = useState({});
  const [layout, setLayout] = useState(loadLayout);
  const [darkMode, setDarkMode] = useState(() => localStorage.getItem(THEME_KEY) === 'dark');
  const [chatMessages, setChatMessages] = useState([
    { role: 'assistant', content: 'Hello! I\'m your SIF-400 Digital Twin Assistant. Ask me about energy, power, caps, inventory, OEE, or alerts.' }
  ]);
  const [inputMessage, setInputMessage] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState('disconnected');
  const [showThresholdConfig, setShowThresholdConfig] = useState(false);
  const [thresholds, setThresholds] = useState({ caps_min: 3, power_max_w: 500 });
  const [tempThresholds, setTempThresholds] = useState({ caps_min: 3, power_max_w: 500 });
  const chatEndRef = useRef(null);
  const historyRangeRef = useRef(historyRange);

  // API base URL (this app's backend, which relays data from the SIF-400)
  const API_BASE = 'http://localhost:5001/api';

  // Apply dark mode to the document root and persist the choice
  useEffect(() => {
    document.documentElement.classList.toggle('dark', darkMode);
    localStorage.setItem(THEME_KEY, darkMode ? 'dark' : 'light');
  }, [darkMode]);

  const movePanel = (column, key, dir) => {
    setLayout(prev => {
      const order = [...prev[column]];
      const i = order.indexOf(key);
      const j = i + dir;
      if (i < 0 || j < 0 || j >= order.length) return prev;
      [order[i], order[j]] = [order[j], order[i]];
      const next = { ...prev, [column]: order };
      localStorage.setItem(LAYOUT_KEY, JSON.stringify(next));
      return next;
    });
  };

  // Fetch current station status (energy/power + SIF-400 link state + air)
  const fetchStationStatus = async () => {
    try {
      const response = await fetch(`${API_BASE}/current-status`);
      if (response.ok) {
        const data = await response.json();
        setStationData(data.stations || {});
        setSifConnection(data.connection || null);
        setAirData(data.air || null);
        setConnectionStatus('connected');
      } else {
        setConnectionStatus('error');
      }
    } catch (error) {
      console.error('Error fetching station status:', error);
      setConnectionStatus('error');
    }
  };

  const fetchAlerts = async () => {
    try {
      const response = await fetch(`${API_BASE}/alerts`);
      if (response.ok) setAlerts(await response.json());
    } catch (error) {
      console.error('Error fetching alerts:', error);
    }
  };

  const dismissAlert = async (alertId) => {
    try {
      await fetch(`${API_BASE}/alerts/${alertId}/resolve`, { method: 'POST' });
      setAlerts(prev => prev.filter(alert => alert.id !== alertId));
    } catch (error) {
      console.error('Error dismissing alert:', error);
    }
  };

  const fetchInventoryAndEkanban = async () => {
    try {
      const [invResponse, ekResponse] = await Promise.all([
        fetch(`${API_BASE}/inventory`),
        fetch(`${API_BASE}/ekanban`),
      ]);
      if (invResponse.ok) setInventory((await invResponse.json()).data);
      if (ekResponse.ok) setEkanban((await ekResponse.json()).data);
    } catch (error) {
      console.error('Error fetching inventory/ekanban:', error);
    }
  };

  const fetchPerformance = async () => {
    try {
      const response = await fetch(`${API_BASE}/performance`);
      if (response.ok) setPerformance(await response.json());
    } catch (error) {
      console.error('Error fetching performance:', error);
    }
  };

  const fetchHistory = async (range) => {
    try {
      const response = await fetch(`${API_BASE}/history?range=${range || historyRangeRef.current}`);
      if (response.ok) setHistoryData(await response.json());
    } catch (error) {
      console.error('Error fetching history:', error);
    }
  };

  const fetchOeeRange = async (days) => {
    setOeeRange({ loading: true, days });
    try {
      const response = await fetch(`${API_BASE}/oee?days=${days}`);
      const data = await response.json();
      setOeeRange({ ...data, days, loading: false });
    } catch (error) {
      console.error('Error fetching OEE range:', error);
      setOeeRange({ days, loading: false, error: String(error) });
    }
  };

  const selectOeeRange = (days) => {
    setOeeDays(days);
    if (days > 0) fetchOeeRange(days);
  };

  const fetchThresholds = async () => {
    try {
      const response = await fetch(`${API_BASE}/thresholds`);
      if (response.ok) {
        const data = await response.json();
        setThresholds(data);
        setTempThresholds(data);
      }
    } catch (error) {
      console.error('Error fetching thresholds:', error);
    }
  };

  const updateThresholds = async () => {
    try {
      const response = await fetch(`${API_BASE}/thresholds`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(tempThresholds),
      });

      if (response.ok) {
        const data = await response.json();
        setThresholds(data.thresholds);
        setShowThresholdConfig(false);
        setChatMessages(prev => [...prev, {
          role: 'assistant',
          content: `✅ Threshold configuration updated!\n\n• Power maximum: ${data.thresholds.power_max_w}W\n• Caps minimum: ${data.thresholds.caps_min}`
        }]);
      } else {
        const error = await response.json();
        setChatMessages(prev => [...prev, {
          role: 'assistant',
          content: `❌ Error updating thresholds: ${error.error}`
        }]);
      }
    } catch (error) {
      console.error('Error updating thresholds:', error);
      setChatMessages(prev => [...prev, {
        role: 'assistant',
        content: '❌ Failed to update thresholds. Please check your connection.'
      }]);
    }
  };

  const resetThresholds = () => setTempThresholds({ ...thresholds });

  // Real-time data updates
  useEffect(() => {
    fetchStationStatus();
    fetchAlerts();
    fetchInventoryAndEkanban();
    fetchPerformance();
    fetchHistory();
    fetchThresholds();

    const fastInterval = setInterval(() => {
      fetchStationStatus();
      fetchAlerts();
    }, 3000);
    const mediumInterval = setInterval(fetchInventoryAndEkanban, 5000);
    const slowInterval = setInterval(fetchPerformance, 30000);
    const historyInterval = setInterval(() => fetchHistory(), 60000);

    return () => {
      clearInterval(fastInterval);
      clearInterval(mediumInterval);
      clearInterval(slowInterval);
      clearInterval(historyInterval);
    };
  }, []);

  // Refetch history when the selected range changes
  useEffect(() => {
    historyRangeRef.current = historyRange;
    fetchHistory(historyRange);
  }, [historyRange]);

  // Auto-scroll chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages]);

  // Handle chat submission
  const handleChatSubmit = async (e) => {
    e.preventDefault();
    if (!inputMessage.trim() || isLoading) return;

    const userMessage = inputMessage;
    setInputMessage('');
    setChatMessages(prev => [...prev, { role: 'user', content: userMessage }]);
    setIsLoading(true);

    try {
      const response = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userMessage }),
      });

      if (response.ok) {
        const data = await response.json();
        setChatMessages(prev => [...prev, { role: 'assistant', content: data.response }]);
      } else {
        setChatMessages(prev => [...prev, {
          role: 'assistant',
          content: 'I apologize, but I encountered an error processing your request. Please try again.'
        }]);
      }
    } catch (error) {
      console.error('Error in chat:', error);
      setChatMessages(prev => [...prev, {
        role: 'assistant',
        content: 'I\'m having trouble connecting to the server. Please check your connection and try again.'
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  // Small hint shown inside a panel when its backend feed is failing
  const FeedHint = ({ feedName }) => {
    const feed = sifConnection?.feeds?.[feedName];
    if (!feed || feed.ok) return null;
    return (
      <div className="mt-2 text-xs text-orange-600 dark:text-orange-300 bg-orange-50 dark:bg-orange-900/30 rounded p-2 break-words">
        ⚠️ {feedName} feed failing: {feed.last_error}
      </div>
    );
  };

  // Multi-station power line chart drawn as plain SVG
  const PowerChart = ({ stations }) => {
    const series = Object.entries(stations || {})
      .map(([name, pts]) => [name, (pts || []).filter(p => p.power_w !== null && p.power_w !== undefined)])
      .filter(([, pts]) => pts.length > 0);
    const allPoints = series.flatMap(([, pts]) => pts);

    if (allPoints.length === 0) {
      return (
        <div className="flex items-center justify-center h-40 text-xs text-gray-400">
          no power measurements in this range yet
        </div>
      );
    }

    const parseTs = (s) => new Date(s.replace(' ', 'T')).getTime();
    const t0 = Math.min(...allPoints.map(p => parseTs(p.timestamp)));
    const t1 = Math.max(...allPoints.map(p => parseTs(p.timestamp)));
    const maxP = Math.max(10, Math.max(...allPoints.map(p => p.power_w)) * 1.1);
    const W = 600, H = 210, mL = 40, mR = 8, mT = 8, mB = 20;
    const x = (t) => mL + ((t - t0) / Math.max(t1 - t0, 1)) * (W - mL - mR);
    const y = (p) => mT + (1 - p / maxP) * (H - mT - mB);

    const spanHours = (t1 - t0) / 3600000;
    const fmtTime = (t) => spanHours > 26
      ? new Date(t).toLocaleDateString([], { month: 'numeric', day: 'numeric' })
      : new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    const yTicks = [0, maxP / 2, maxP];
    const xTicks = [t0, (t0 + t1) / 2, t1];

    return (
      <div>
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
          {yTicks.map((p, i) => (
            <g key={i}>
              <line x1={mL} x2={W - mR} y1={y(p)} y2={y(p)}
                    className="stroke-gray-200 dark:stroke-gray-700" strokeWidth="1" />
              <text x={mL - 4} y={y(p) + 3} textAnchor="end" fontSize="9"
                    className="fill-gray-500 dark:fill-gray-400">{Math.round(p)}W</text>
            </g>
          ))}
          {xTicks.map((t, i) => (
            <text key={i} x={x(t)} y={H - 6} fontSize="9"
                  textAnchor={i === 0 ? 'start' : i === xTicks.length - 1 ? 'end' : 'middle'}
                  className="fill-gray-500 dark:fill-gray-400">{fmtTime(t)}</text>
          ))}
          {series.map(([name, pts]) => (
            <polyline
              key={name}
              fill="none"
              stroke={STATION_COLORS[name] || '#888'}
              strokeWidth="1.5"
              points={pts.map(p => `${x(parseTs(p.timestamp)).toFixed(1)},${y(p.power_w).toFixed(1)}`).join(' ')}
            />
          ))}
        </svg>
        <div className="flex flex-wrap gap-3 mt-1">
          {series.map(([name]) => (
            <span key={name} className="flex items-center gap-1 text-xs text-gray-600 dark:text-gray-300">
              <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: STATION_COLORS[name] }} />
              {name}
            </span>
          ))}
        </div>
      </div>
    );
  };

  // Station Card Component
  const StationCard = ({ stationId, data }) => {
    if (!data) return null;

    const isWarning = data.status === 'warning';
    const isOffline = data.status === 'offline';
    const powerTrend = (data.trend || []).filter(p => p.power_w !== null && p.power_w !== undefined);
    const maxPower = Math.max(...powerTrend.map(p => p.power_w), thresholds.power_max_w * 0.3);

    return (
      <div className={`bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6 transition-all duration-300 ${
        isWarning ? 'ring-2 ring-orange-400' : isOffline ? 'ring-2 ring-gray-300 dark:ring-gray-600 opacity-75' : ''
      }`}>
        <div className="flex justify-between items-start mb-4">
          <div>
            <h3 className="text-lg font-semibold text-gray-800 dark:text-gray-100">{stationId}</h3>
            <p className="text-xs text-gray-500 dark:text-gray-400">{STATION_ROLES[stationId]}</p>
          </div>
          <div className={`p-2 rounded-full ${
            isWarning ? 'bg-orange-100 dark:bg-orange-900' : isOffline ? 'bg-gray-100 dark:bg-gray-700' : 'bg-green-100 dark:bg-green-900'
          }`}>
            {isWarning ? (
              <AlertTriangle className="w-5 h-5 text-orange-600 dark:text-orange-300" />
            ) : isOffline ? (
              <WifiOff className="w-5 h-5 text-gray-500 dark:text-gray-300" />
            ) : (
              <CheckCircle className="w-5 h-5 text-green-600 dark:text-green-300" />
            )}
          </div>
        </div>

        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Zap className="w-4 h-4 text-blue-600 dark:text-blue-400" />
              <span className="text-sm text-gray-600 dark:text-gray-300">Power (avg)</span>
            </div>
            <span className="text-xl font-bold text-gray-800 dark:text-gray-100">
              {data.power_w !== null && data.power_w !== undefined ? `${data.power_w.toFixed(0)} W` : '—'}
            </span>
          </div>

          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Activity className="w-4 h-4 text-purple-600 dark:text-purple-400" />
              <span className="text-sm text-gray-600 dark:text-gray-300">Energy today</span>
            </div>
            <span className="text-xl font-bold text-gray-800 dark:text-gray-100">
              {data.energy_today_wh !== null && data.energy_today_wh !== undefined
                ? `${data.energy_today_wh.toFixed(0)} Wh` : '—'}
            </span>
          </div>

          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-green-600 dark:text-green-400" />
              <span className="text-sm text-gray-600 dark:text-gray-300">Lifetime</span>
            </div>
            <span className="text-xl font-bold text-gray-800 dark:text-gray-100">
              {data.energy_total_wh !== null && data.energy_total_wh !== undefined
                ? `${(data.energy_total_wh / 1000).toFixed(1)} kWh` : '—'}
            </span>
          </div>

          <div className="mt-4 h-16">
            {powerTrend.length > 0 ? (
              <div className="flex items-end h-full gap-1">
                {powerTrend.slice(-15).map((point, idx) => (
                  <div
                    key={idx}
                    className="flex-1 bg-blue-400 dark:bg-blue-500 rounded-t opacity-70 transition-all duration-300"
                    style={{ height: `${Math.max((point.power_w / maxPower) * 100, 5)}%` }}
                    title={`${point.power_w.toFixed(0)} W @ ${point.timestamp}`}
                  />
                ))}
              </div>
            ) : (
              <div className="flex items-center justify-center h-full text-xs text-gray-400">
                collecting power readings...
              </div>
            )}
            <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">Power Trend</div>
          </div>
        </div>
      </div>
    );
  };

  // Pill-style range selector shared by History and OEE panels
  const RangePills = ({ options, isActive, onSelect }) => (
    <div className="flex gap-1">
      {options.map(opt => (
        <button
          key={opt.key}
          onClick={() => onSelect(opt)}
          className={`px-2 py-1 text-xs rounded transition-colors ${
            isActive(opt)
              ? 'bg-indigo-600 text-white'
              : 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600'
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );

  // ------------------------------------------------------------ panel renderers

  const renderStations = () => (
    connectionStatus === 'connected' ? (
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {Object.entries(stationData).map(([stationId, data]) => (
          <StationCard key={stationId} stationId={stationId} data={data} />
        ))}
      </div>
    ) : (
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6 text-center">
        <div className="text-gray-500 dark:text-gray-400">
          {connectionStatus === 'error' ? (
            <div>
              <AlertTriangle className="w-12 h-12 mx-auto mb-4 text-red-500" />
              <p>Unable to connect to the backend server.</p>
              <p className="text-sm mt-2">Please ensure the Python backend is running on port 5001.</p>
            </div>
          ) : (
            <div>
              <Activity className="w-12 h-12 mx-auto mb-4 animate-spin text-blue-500" />
              <p>Connecting to station data...</p>
            </div>
          )}
        </div>
      </div>
    )
  );

  const renderAlerts = () => {
    if (alerts.length === 0) return null;
    return (
      <div className="bg-orange-50 dark:bg-orange-950/50 rounded-xl p-4">
        <h3 className="font-semibold text-orange-800 dark:text-orange-300 mb-3 flex items-center gap-2">
          <AlertTriangle className="w-5 h-5" />
          Active Alerts
        </h3>
        <div className="space-y-2">
          {alerts.slice(0, 5).map(alert => {
            const tip = getAlertTip(alert);
            return (
              <div key={alert.id} className="bg-white dark:bg-gray-800 rounded-lg p-3 flex justify-between items-start gap-2">
                <div className="min-w-0">
                  <span className="font-medium text-gray-800 dark:text-gray-100">{alert.station_id}</span>
                  <span className="text-gray-600 dark:text-gray-300 ml-2">{alert.message}</span>
                  {tip && (
                    <div className="text-xs text-indigo-600 dark:text-indigo-300 mt-1">
                      💡 Tip: {tip}
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className="text-xs text-gray-500 dark:text-gray-400">{new Date(alert.timestamp).toLocaleTimeString()}</span>
                  <button
                    onClick={() => dismissAlert(alert.id)}
                    className="p-1 text-gray-400 hover:text-gray-700 hover:bg-gray-100 dark:hover:text-gray-200 dark:hover:bg-gray-700 rounded transition-colors"
                    title="Dismiss alert (re-raises after 5 min if the condition persists)"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  const renderHistory = () => (
    <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6">
      <div className="flex items-center justify-between flex-wrap gap-2 mb-4">
        <h3 className="font-semibold text-gray-800 dark:text-gray-100 flex items-center gap-2">
          <LineChart className="w-5 h-5 text-indigo-600 dark:text-indigo-300" />
          Measurement History
        </h3>
        <div className="flex items-center gap-2">
          <RangePills
            options={HISTORY_RANGES.map(r => ({ key: r, label: r }))}
            isActive={(opt) => opt.key === historyRange}
            onSelect={(opt) => setHistoryRange(opt.key)}
          />
          <a
            href={`${API_BASE}/history/export?range=${historyRange}`}
            className="flex items-center gap-1 px-2 py-1 text-xs rounded bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600 transition-colors"
            title="Download the raw measurement rows for this range as CSV"
          >
            <Download className="w-3 h-3" /> CSV
          </a>
        </div>
      </div>
      <PowerChart stations={historyData?.stations} />
      <div className="text-xs text-gray-500 dark:text-gray-400 mt-2">
        Average power per station, sampled every ~30s
        {historyData?.bucket_seconds ? ` (chart buckets: ${historyData.bucket_seconds}s)` : ''}
      </div>
    </div>
  );

  const renderInventory = () => {
    const stations = inventory?.Stations || [];
    return (
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6">
        <h3 className="font-semibold text-gray-800 dark:text-gray-100 mb-4 flex items-center gap-2">
          <Package className="w-5 h-5 text-indigo-600 dark:text-indigo-300" />
          Raw Material Inventory
        </h3>
        {stations.length === 0 ? (
          <div>
            <div className="text-sm text-gray-400">Waiting for inventory data...</div>
            <FeedHint feedName="inventory" />
          </div>
        ) : (
          <div className="space-y-4">
            {stations.map(station => {
              const name = STATION_ID_TO_NAME[station.StationID] || `Station ${station.StationTypeID}`;
              return (
                <div key={station.StationID} className="border-b border-gray-100 dark:border-gray-700 pb-3 last:border-b-0 last:pb-0">
                  <div className="text-sm font-medium text-gray-700 dark:text-gray-200 mb-2">{name}</div>

                  {station.ContainerLoaders && (
                    <div className="flex flex-wrap gap-2">
                      {station.ContainerLoaders.map(loader => (
                        <div
                          key={loader.LoaderNumber}
                          className={`px-2 py-1 rounded text-xs flex items-center gap-1 ${
                            loader.Presence
                              ? 'bg-green-50 text-green-700 dark:bg-green-900/40 dark:text-green-300'
                              : 'bg-red-50 text-red-700 dark:bg-red-900/40 dark:text-red-300'
                          }`}
                          title={`Loader ${loader.LoaderNumber}`}
                        >
                          {loader.Presence
                            ? <CheckCircle className="w-3 h-3" />
                            : <CircleSlash className="w-3 h-3" />}
                          L{loader.LoaderNumber} {loader.ContainerType}
                        </div>
                      ))}
                      {station.PalletLoader && (
                        <div className={`px-2 py-1 rounded text-xs flex items-center gap-1 ${
                          station.PalletLoader.Presence
                            ? 'bg-green-50 text-green-700 dark:bg-green-900/40 dark:text-green-300'
                            : 'bg-red-50 text-red-700 dark:bg-red-900/40 dark:text-red-300'
                        }`}>
                          {station.PalletLoader.Presence
                            ? <CheckCircle className="w-3 h-3" />
                            : <CircleSlash className="w-3 h-3" />}
                          Pallets ({station.PalletLoader.Position})
                        </div>
                      )}
                    </div>
                  )}

                  {station.Hoppers && (
                    <div className="flex flex-wrap gap-2">
                      {station.Hoppers.map(hopper => (
                        <div
                          key={hopper.HopperNumber}
                          className={`px-2 py-1 rounded text-xs flex items-center gap-1 ${
                            hopper.Presence
                              ? 'bg-green-50 text-green-700 dark:bg-green-900/40 dark:text-green-300'
                              : 'bg-red-50 text-red-700 dark:bg-red-900/40 dark:text-red-300'
                          }`}
                        >
                          <span className={`w-3 h-3 rounded-full ${HOPPER_COLORS[hopper.Color] || 'bg-gray-400'}`} />
                          Hopper {hopper.HopperNumber} {hopper.Color}
                        </div>
                      ))}
                    </div>
                  )}

                  {station.Feeders && (
                    <div className="flex flex-wrap gap-2">
                      {station.Feeders.map(feeder => (
                        <div
                          key={feeder.FeederNumber}
                          className={`px-2 py-1 rounded text-xs ${
                            feeder.CapCount < thresholds.caps_min
                              ? 'bg-orange-50 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300'
                              : 'bg-green-50 text-green-700 dark:bg-green-900/40 dark:text-green-300'
                          }`}
                        >
                          Feeder {feeder.FeederNumber} ({feeder.CapType}): {feeder.CapCount} caps
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    );
  };

  const renderEkanban = () => {
    const chargers = [];
    (ekanban?.stations || []).forEach(station => {
      Object.entries(station.lids_left || {}).forEach(([name, charger]) => {
        chargers.push({ name, ...charger });
      });
    });

    return (
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6">
        <h3 className="font-semibold text-gray-800 dark:text-gray-100 mb-4 flex items-center gap-2">
          <Layers className="w-5 h-5 text-indigo-600 dark:text-indigo-300" />
          Caps E-Kanban <span className="text-xs font-normal text-gray-500 dark:text-gray-400">(SIF-405)</span>
        </h3>
        {chargers.length === 0 ? (
          <div>
            <div className="text-sm text-gray-400">Waiting for e-kanban data...</div>
            <FeedHint feedName="ekanban" />
          </div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {chargers.map(charger => {
              const low = charger.left !== null && charger.left < thresholds.caps_min;
              return (
                <div key={charger.name} className={`rounded-lg p-4 text-center ${
                  low
                    ? 'bg-orange-50 ring-1 ring-orange-300 dark:bg-orange-900/30 dark:ring-orange-700'
                    : 'bg-gray-50 dark:bg-gray-700'
                }`}>
                  <div className={`text-3xl font-bold ${
                    low ? 'text-orange-600 dark:text-orange-300' : 'text-gray-800 dark:text-gray-100'
                  }`}>
                    {charger.left ?? '—'}
                  </div>
                  <div className="text-sm text-gray-600 dark:text-gray-300 capitalize">{charger.type} caps</div>
                  <div className="text-xs text-gray-400">{charger.name.replace('_', ' ')}</div>
                  {low && <div className="text-xs text-orange-600 dark:text-orange-300 mt-1 font-medium">below minimum ({thresholds.caps_min})</div>}
                </div>
              );
            })}
          </div>
        )}
      </div>
    );
  };

  const renderOEE = () => {
    const source = oeeDays === 0
      ? { data: performance?.oee?.data, loading: false }
      : oeeRange;
    const oeeStations = (source?.data?.Stations || []).filter(s => STATION_ID_TO_NAME[s.StationID]);
    const oeeWindow = source?.data?._window;
    const noProduction = oeeStations.length > 0
      && oeeStations.every(s => !s.TotalCycles && !s.OEE);

    const pct = (v) => `${((v || 0) * 100).toFixed(0)}%`;

    return (
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6">
        <div className="flex items-center justify-between flex-wrap gap-2 mb-4">
          <h3 className="font-semibold text-gray-800 dark:text-gray-100 flex items-center gap-2">
            <Gauge className="w-5 h-5 text-indigo-600 dark:text-indigo-300" />
            OEE
            {oeeWindow && (
              <span className="text-xs font-normal text-gray-500 dark:text-gray-400">
                ({oeeWindow[0]} → {oeeWindow[1]})
              </span>
            )}
          </h3>
          <RangePills
            options={OEE_RANGES.map(r => ({ key: r.days, label: r.label }))}
            isActive={(opt) => opt.key === oeeDays}
            onSelect={(opt) => selectOeeRange(opt.key)}
          />
        </div>

        {source?.loading ? (
          <div className="flex items-center gap-2 text-sm text-gray-400 py-6">
            <Activity className="w-4 h-4 animate-spin" />
            Querying the SIF-400 (Performance Analytics can take up to 30s)...
          </div>
        ) : source?.error && !source?.data ? (
          <div className="text-xs text-orange-600 dark:text-orange-300 bg-orange-50 dark:bg-orange-900/30 rounded p-2 break-words">
            ⚠️ Could not fetch OEE for this range: {source.error}
          </div>
        ) : oeeStations.length === 0 ? (
          <div>
            <div className="text-sm text-gray-400">Waiting for OEE data...</div>
            <FeedHint feedName="oee" />
          </div>
        ) : noProduction ? (
          <div className="text-sm text-gray-500 dark:text-gray-400 py-4 text-center">
            No production cycles recorded in this window.
            <div className="text-xs mt-1">
              OEE is computed only during MES-managed production runs — try a wider range,
              or check back after the next exercise.
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto">
            {source?.stale && (
              <div className="text-xs text-gray-400 mb-2">showing cached data — {source.error}</div>
            )}
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-gray-500 dark:text-gray-400 border-b dark:border-gray-700">
                  <th className="py-2 pr-2">Station</th>
                  <th className="py-2 pr-2">OEE</th>
                  <th className="py-2 pr-2">Avail.</th>
                  <th className="py-2 pr-2">Perf.</th>
                  <th className="py-2 pr-2">Quality</th>
                  <th className="py-2 pr-2">Units (good/total)</th>
                  <th className="py-2">Running</th>
                </tr>
              </thead>
              <tbody>
                {oeeStations.map(s => (
                  <tr key={s.StationID} className="border-b border-gray-50 dark:border-gray-700/50 last:border-b-0">
                    <td className="py-2 pr-2 font-medium text-gray-700 dark:text-gray-200">{STATION_ID_TO_NAME[s.StationID]}</td>
                    <td className="py-2 pr-2 font-bold text-gray-800 dark:text-gray-100">{pct(s.OEE)}</td>
                    <td className="py-2 pr-2 text-gray-600 dark:text-gray-300">{pct(s.Availability)}</td>
                    <td className="py-2 pr-2 text-gray-600 dark:text-gray-300">{pct(s.Performance)}</td>
                    <td className="py-2 pr-2 text-gray-600 dark:text-gray-300">{pct(s.Quality)}</td>
                    <td className="py-2 pr-2 text-gray-600 dark:text-gray-300">
                      {(s.GoodUnits || 0).toFixed(0)}/{(s.TotalUnits || 0).toFixed(0)}
                    </td>
                    <td className="py-2 text-gray-600 dark:text-gray-300">{s.RunningTimeFormatted || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    );
  };

  const renderLine = () => {
    const history = performance?.air_and_energy_history?.data;
    const energyDays = history?.EnergyConsumedDayPoints;
    const airDays = history?.AirDayPoints;

    const DayBars = ({ series, color, unit }) => {
      if (!series?.Values?.length) return <div className="text-xs text-gray-400">no history yet</div>;
      const max = Math.max(...series.Values, 1);
      return (
        <div className="flex items-end h-20 gap-1">
          {series.Values.map((v, idx) => (
            <div key={idx} className="flex-1 flex flex-col justify-end h-full" title={`${series.Labels?.[idx]}: ${v} ${unit}`}>
              <div
                className={`${color} rounded-t opacity-80 transition-all duration-300`}
                style={{ height: `${Math.max((v / max) * 100, 2)}%` }}
              />
            </div>
          ))}
        </div>
      );
    };

    return (
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6">
        <h3 className="font-semibold text-gray-800 dark:text-gray-100 mb-4 flex items-center gap-2">
          <Gauge className="w-5 h-5 text-indigo-600 dark:text-indigo-300" />
          Line Consumption
        </h3>

        <div className="grid grid-cols-2 gap-4 mb-4">
          <div className="bg-blue-50 dark:bg-blue-900/30 rounded-lg p-3">
            <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300 mb-1">
              <Zap className="w-4 h-4 text-blue-600 dark:text-blue-400" /> Energy today
            </div>
            <div className="text-2xl font-bold text-gray-800 dark:text-gray-100">
              {airData?.energy_today_wh !== null && airData?.energy_today_wh !== undefined
                ? `${airData.energy_today_wh.toFixed(0)} Wh` : '—'}
            </div>
            <div className="text-xs text-gray-500 dark:text-gray-400">
              lifetime {airData?.energy_total_wh ? `${(airData.energy_total_wh / 1000).toFixed(0)} kWh` : '—'}
            </div>
          </div>
          <div className="bg-cyan-50 dark:bg-cyan-900/30 rounded-lg p-3">
            <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300 mb-1">
              <Wind className="w-4 h-4 text-cyan-600 dark:text-cyan-400" /> Air today
            </div>
            <div className="text-2xl font-bold text-gray-800 dark:text-gray-100">
              {airData?.air_today_l !== null && airData?.air_today_l !== undefined
                ? `${airData.air_today_l} L` : '—'}
            </div>
            <div className="text-xs text-gray-500 dark:text-gray-400">
              lifetime {airData?.air_total_l ? `${airData.air_total_l} L` : '—'}
            </div>
          </div>
        </div>

        {!airData && <FeedHint feedName="air_and_energy_today" />}

        <div className="space-y-3">
          <div>
            <div className="text-xs text-gray-500 dark:text-gray-400 mb-1">Energy, last 14 days (Wh)</div>
            <DayBars series={energyDays} color="bg-blue-400" unit="Wh" />
          </div>
          <div>
            <div className="text-xs text-gray-500 dark:text-gray-400 mb-1">Air, last 14 days (L)</div>
            <DayBars series={airDays} color="bg-cyan-400" unit="L" />
          </div>
          {!history && <FeedHint feedName="air_and_energy_history" />}
        </div>
      </div>
    );
  };

  const renderChat = () => (
    <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6 flex flex-col h-[600px]">
      <div className="flex items-center gap-3 mb-4 pb-4 border-b dark:border-gray-700">
        <div className="p-2 bg-indigo-100 dark:bg-indigo-900 rounded-lg">
          <Bot className="w-6 h-6 text-indigo-600 dark:text-indigo-300" />
        </div>
        <div>
          <h3 className="font-semibold text-gray-800 dark:text-gray-100">AI Assistant</h3>
          <p className="text-sm text-gray-600 dark:text-gray-300">Ask about the factory line</p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto mb-4 space-y-3">
        {chatMessages.map((msg, idx) => (
          <div
            key={idx}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[80%] rounded-lg p-3 whitespace-pre-wrap break-words ${
                msg.role === 'user'
                  ? 'bg-indigo-600 text-white'
                  : 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-100'
              }`}
            >
              {msg.content}
            </div>
          </div>
        ))}
        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-gray-100 dark:bg-gray-700 rounded-lg p-3">
              <div className="flex gap-1">
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></div>
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce delay-100"></div>
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce delay-200"></div>
              </div>
            </div>
          </div>
        )}
        <div ref={chatEndRef} />
      </div>

      <form onSubmit={handleChatSubmit} className="flex gap-2">
        <input
          type="text"
          value={inputMessage}
          onChange={(e) => setInputMessage(e.target.value)}
          placeholder="Ask about energy, caps, inventory, OEE, alerts..."
          className="flex-1 px-4 py-2 border dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 dark:placeholder-gray-400 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
          disabled={isLoading || connectionStatus !== 'connected'}
        />
        <button
          type="submit"
          disabled={isLoading || !inputMessage.trim() || connectionStatus !== 'connected'}
          className="p-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <Send className="w-5 h-5" />
        </button>
      </form>
    </div>
  );

  const PANEL_RENDERERS = {
    stations: renderStations,
    alerts: renderAlerts,
    history: renderHistory,
    inventory: renderInventory,
    ekanban: renderEkanban,
    oee: renderOEE,
    chat: renderChat,
    line: renderLine,
  };

  // Wraps a panel with hover arrows that move it up/down within its column
  const renderColumn = (column) => (
    layout[column].map((key, idx) => {
      const content = PANEL_RENDERERS[key]();
      if (!content) return null;
      const order = layout[column];
      return (
        <div key={key} className="relative group">
          <div className="absolute -top-2 -right-2 z-10 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
            <button
              onClick={() => movePanel(column, key, -1)}
              disabled={idx === 0}
              className="p-1 bg-white dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-full shadow text-gray-500 dark:text-gray-300 hover:text-indigo-600 dark:hover:text-indigo-300 disabled:opacity-30 disabled:cursor-not-allowed"
              title="Move panel up"
            >
              <ChevronUp className="w-3 h-3" />
            </button>
            <button
              onClick={() => movePanel(column, key, 1)}
              disabled={idx === order.length - 1}
              className="p-1 bg-white dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-full shadow text-gray-500 dark:text-gray-300 hover:text-indigo-600 dark:hover:text-indigo-300 disabled:opacity-30 disabled:cursor-not-allowed"
              title="Move panel down"
            >
              <ChevronDown className="w-3 h-3" />
            </button>
          </div>
          {content}
        </div>
      );
    })
  );

  // Threshold Configuration Component
  const ThresholdConfig = () => {
    const handleSliderChange = (field, value) => {
      setTempThresholds(prev => ({ ...prev, [field]: parseFloat(value) }));
    };

    return (
      <div className="mt-4 bg-gray-50 dark:bg-gray-900 rounded-xl p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-800 dark:text-gray-100 flex items-center gap-2">
            <Settings className="w-5 h-5" />
            Alert Threshold Configuration
          </h3>
          <button
            onClick={() => setShowThresholdConfig(!showThresholdConfig)}
            className="p-2 hover:bg-gray-200 dark:hover:bg-gray-700 rounded-lg transition-colors text-gray-700 dark:text-gray-200"
          >
            {showThresholdConfig ? <ChevronUp className="w-5 h-5" /> : <ChevronDown className="w-5 h-5" />}
          </button>
        </div>

        {showThresholdConfig && (
          <div className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-200 mb-2">
                  Power Maximum: {tempThresholds.power_max_w}W
                </label>
                <input
                  type="range"
                  min="50"
                  max="1000"
                  step="10"
                  value={tempThresholds.power_max_w}
                  onChange={(e) => handleSliderChange('power_max_w', e.target.value)}
                  className="w-full h-2 bg-gray-200 dark:bg-gray-600 rounded-lg appearance-none cursor-pointer slider"
                />
                <div className="flex justify-between text-xs text-gray-500 dark:text-gray-400 mt-1">
                  <span>50W</span>
                  <span>1000W</span>
                </div>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Alert when a station's average power exceeds this.</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-200 mb-2">
                  Caps Minimum: {tempThresholds.caps_min} caps
                </label>
                <input
                  type="range"
                  min="0"
                  max="10"
                  step="1"
                  value={tempThresholds.caps_min}
                  onChange={(e) => handleSliderChange('caps_min', e.target.value)}
                  className="w-full h-2 bg-gray-200 dark:bg-gray-600 rounded-lg appearance-none cursor-pointer slider"
                />
                <div className="flex justify-between text-xs text-gray-500 dark:text-gray-400 mt-1">
                  <span>0</span>
                  <span>10</span>
                </div>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Alert when a SIF-405 feeder drops below this many caps.</p>
              </div>
            </div>

            <div className="flex gap-3 pt-4">
              <button
                onClick={updateThresholds}
                disabled={connectionStatus !== 'connected'}
                className="flex-1 bg-indigo-600 text-white py-2 px-4 rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                Apply Thresholds
              </button>
              <button
                onClick={resetThresholds}
                className="px-4 py-2 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
              >
                Reset
              </button>
            </div>

            <div className="bg-white dark:bg-gray-800 rounded-lg p-4 mt-4">
              <h4 className="text-sm font-medium text-gray-700 dark:text-gray-200 mb-2">Current Threshold Settings:</h4>
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-gray-600 dark:text-gray-300">Power maximum:</span>
                  <span className="font-medium ml-2 text-gray-800 dark:text-gray-100">{thresholds.power_max_w}W</span>
                </div>
                <div>
                  <span className="text-gray-600 dark:text-gray-300">Caps minimum:</span>
                  <span className="font-medium ml-2 text-gray-800 dark:text-gray-100">{thresholds.caps_min} caps</span>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    );
  };

  // Connection status indicator: browser -> backend, and backend -> SIF-400 API
  const ConnectionIndicator = () => {
    const backendOk = connectionStatus === 'connected';
    const sifOk = Boolean(sifConnection?.connected);
    const source = apiSourceLabel(sifConnection?.api_base);

    const Dot = ({ ok, pending }) => (
      <div className={`w-3 h-3 rounded-full ${
        pending ? 'bg-yellow-500' : ok ? 'bg-green-500 animate-pulse' : 'bg-red-500'
      }`}></div>
    );

    return (
      <div className="flex flex-col items-end gap-1">
        <div className="flex items-center gap-2">
          <Dot ok={backendOk} pending={connectionStatus === 'disconnected'} />
          <span className="text-sm text-gray-600 dark:text-gray-300">
            Backend: {backendOk ? 'Connected' : connectionStatus === 'error' ? 'Error' : 'Connecting...'}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Dot ok={sifOk} pending={backendOk && !sifConnection} />
          <span className="text-sm text-gray-600 dark:text-gray-300">
            SIF-400 API: {!backendOk ? 'Unknown' : sifOk ? 'Connected' : 'Disconnected'}
          </span>
          {backendOk && source && (
            <span
              className={`text-xs px-1.5 py-0.5 rounded font-medium ${
                source.mock
                  ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-300'
                  : 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/50 dark:text-indigo-300'
              }`}
              title={`Data source: ${sifConnection?.api_base}`}
            >
              {source.text}
            </span>
          )}
        </div>
        {backendOk && sifConnection?.last_success && !sifOk && (
          <span className="text-xs text-gray-400">last contact {sifConnection.last_success}</span>
        )}
      </div>
    );
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 dark:from-gray-950 dark:to-gray-900 p-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-lg p-6 mb-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="p-3 bg-indigo-100 dark:bg-indigo-900 rounded-xl">
                <Activity className="w-8 h-8 text-indigo-600 dark:text-indigo-300" />
              </div>
              <div>
                <h1 className="text-3xl font-bold text-gray-800 dark:text-gray-100">SIF-400 Digital Twin</h1>
                <p className="text-gray-600 dark:text-gray-300">Live Energy, Inventory & Performance Monitoring</p>
              </div>
            </div>
            <div className="flex items-start gap-4">
              <button
                onClick={() => setDarkMode(!darkMode)}
                className="p-2 rounded-lg bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-700 dark:text-yellow-300 dark:hover:bg-gray-600 transition-colors"
                title={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
              >
                {darkMode ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />}
              </button>
              <ConnectionIndicator />
            </div>
          </div>

          {/* Threshold Configuration Section */}
          <ThresholdConfig />
        </div>

        {/* Main Grid — hover a panel to reveal arrows that rearrange it */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-6">
            {renderColumn('left')}
          </div>
          <div className="space-y-6">
            {renderColumn('right')}
          </div>
        </div>
      </div>
    </div>
  );
};

export default SIF400DigitalTwin;
