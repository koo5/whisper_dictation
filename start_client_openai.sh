#!/bin/bash
# Start the whisper_cpp_client.py speech recognition client using OpenAI's Whisper API

# Navigate to the whisper_dictation directory
cd "$(dirname "$0")" || exit

# Check if OPENAI_API_KEY is set
if [ -z "$OPENAI_API_KEY" ]; then
    echo "Error: OPENAI_API_KEY environment variable is not set."
    echo "Please set your OpenAI API key with:"
    echo "export OPENAI_API_KEY=your_api_key_here"
    exit 1
fi

# Setup for status indicators
export SHOW_PROCESSING_STATUS=true  # Enable processing status indicators

# Define status indicator colors
export PROCESSING_COLOR="\033[1;33m"  # Yellow
export IDLE_COLOR="\033[1;32m"        # Green
export RESET_COLOR="\033[0m"          # Reset color

# Start the client with OpenAI Whisper API enabled
echo "Starting whisper speech recognition client with OpenAI Whisper API..."
echo -e "${IDLE_COLOR}[IDLE]${RESET_COLOR} Waiting for speech input..."
export USE_OPENAI_WHISPER=true
python3 whisper_cpp_client.py