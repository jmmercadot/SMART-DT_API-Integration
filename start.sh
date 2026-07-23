#!/bin/bash

# SIF-400 Digital Twin startup script
#   ./start.sh          run against the real SIF-400 (requires the lab network)
#   MOCK=1 ./start.sh   run against the bundled mock SIFMES API (no lab network)

echo "🚀 Starting SIF-400 Digital Twin System..."

if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo "❌ Python 3 is required but not installed."
    exit 1
fi
PYTHON=$(command -v python3 || command -v python)

if ! command -v node &> /dev/null; then
    echo "❌ Node.js is required but not installed."
    exit 1
fi

MOCK_PID=""

start_backend() {
    echo "🔧 Starting Python backend..."
    cd backend

    if [ ! -d "venv" ]; then
        echo "📦 Creating virtual environment..."
        "$PYTHON" -m venv venv
    fi

    # Windows (Git Bash) puts activate under Scripts/, Unix under bin/
    if [ -f "venv/Scripts/activate" ]; then
        source venv/Scripts/activate
    else
        source venv/bin/activate
    fi

    echo "📦 Syncing Python dependencies..."
    pip install -q -r requirements.txt

    if [ -n "$MOCK" ]; then
        echo "🎭 Starting mock SIFMES API on port 8199..."
        python mock_sifmes_api.py &
        MOCK_PID=$!
        sleep 2
        export SIF400_API_BASE=http://localhost:8199/api
        # Mock data goes to a separate DB so it never pollutes the real research data.
        export SIF400_DB=sif400_mock.db
    fi

    echo "🌐 Starting Flask server on port 5001..."
    python app.py &
    BACKEND_PID=$!
    cd ..

    echo "✅ Backend started (PID: $BACKEND_PID)"
}

start_frontend() {
    echo "🎨 Starting React frontend..."
    cd frontend

    if [ ! -d "node_modules" ]; then
        echo "📦 Installing Node.js dependencies..."
        npm install
    fi

    echo "🌐 Starting React development server on port 3000..."
    npm start &
    FRONTEND_PID=$!
    cd ..

    echo "✅ Frontend started (PID: $FRONTEND_PID)"
}

cleanup() {
    echo "🛑 Shutting down services..."
    [ -n "$BACKEND_PID" ] && kill $BACKEND_PID 2>/dev/null
    [ -n "$FRONTEND_PID" ] && kill $FRONTEND_PID 2>/dev/null
    [ -n "$MOCK_PID" ] && kill $MOCK_PID 2>/dev/null

    pkill -f "python app.py" 2>/dev/null
    pkill -f "python mock_sifmes_api.py" 2>/dev/null
    pkill -f "react-scripts start" 2>/dev/null

    echo "✅ Services stopped"
    exit 0
}

trap cleanup SIGINT SIGTERM

start_backend
sleep 3
start_frontend

echo ""
echo "🎉 SIF-400 Digital Twin is starting up!"
echo "📊 Backend API: http://localhost:5001"
echo "🖥️  Frontend UI: http://localhost:3000"
[ -n "$MOCK" ] && echo "🎭 Mock SIFMES API: http://localhost:8199/api"
echo ""
echo "Press Ctrl+C to stop all services"
echo ""

sleep 5

if curl -s http://localhost:5001/api/current-status > /dev/null 2>&1; then
    echo "✅ Backend is running and responding"
else
    echo "⚠️  Backend may not be fully started yet"
fi

wait
