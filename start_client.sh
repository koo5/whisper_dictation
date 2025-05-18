#!/bin/bash
# Start the whisper_cpp_client.py speech recognition client

# Navigate to the whisper_dictation directory
cd "$(dirname "$0")" || exit

# Check if server is running
if ! curl -s http://127.0.0.1:7777/inference > /dev/null; then
    echo "Warning: The whisper server doesn't appear to be running."
    echo "Please start the server first with ./start_server.sh"
    echo "Continue anyway? (y/n)"
    read -r response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Setup for status indicators
export SHOW_PROCESSING_STATUS=true  # Enable processing status indicators

# Define status indicator colors
export PROCESSING_COLOR="\033[1;33m"  # Yellow
export IDLE_COLOR="\033[1;32m"        # Green
export RESET_COLOR="\033[0m"          # Reset color

# Start the client
echo "Starting whisper speech recognition client..."
echo -e "${IDLE_COLOR}[IDLE]${RESET_COLOR} Waiting for speech input..."
python3 whisper_cpp_client.py