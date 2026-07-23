#!/bin/bash

# SIF-400 Digital Twin stop script

echo "🛑 Stopping SIF-400 Digital Twin System..."

echo "🔧 Stopping Python backend (and mock API if running)..."
pkill -f "python app.py" 2>/dev/null
pkill -f "python mock_sifmes_api.py" 2>/dev/null

echo "🎨 Stopping React frontend..."
pkill -f "react-scripts start" 2>/dev/null
pkill -f "node.*react-scripts" 2>/dev/null

sleep 2

# Force kill if processes are still running
pkill -9 -f "python app.py" 2>/dev/null
pkill -9 -f "python mock_sifmes_api.py" 2>/dev/null
pkill -9 -f "react-scripts start" 2>/dev/null

echo "✅ All services stopped"
echo "📊 Backend (port 5001) - stopped"
echo "🖥️  Frontend (port 3000) - stopped"
