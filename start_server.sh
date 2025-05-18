#!/bin/bash
# Start the whisper.cpp server with the medium.en model for better English recognition

# Navigate to the whisper.cpp directory
cd "$(dirname "$0")/whisper.cpp" || exit

# Download the large-v3 model for better recognition
echo "Downloading the large-v3 model for best possible recognition..."
cd models && ./download-ggml-model.sh large-v3-q5_0
cd ..

# Check if the server executable exists
if [ ! -f "build/bin/whisper-server" ]; then
    echo "Server executable not found. Building whisper.cpp server..."
    make server
fi

# Start the server with the large-v3 model and optimizations
echo "Starting whisper.cpp server with large-v3 model and parallel processing..."
echo "Using $(nproc) CPU cores for processing"

# Check if CUDA is available (if you have NVIDIA GPU)
if command -v nvidia-smi &> /dev/null; then
    echo "NVIDIA GPU detected, enabling GPU acceleration"
    # The default for GPU usage is true, so we don't need to specify it explicitly
    GPU_OPTIONS=""
    # To disable GPU, would use --no-gpu
else
    echo "No NVIDIA GPU detected, using CPU only"
    GPU_OPTIONS="--no-gpu"
fi

./build/bin/whisper-server \
    -m models/ggml-large-v3-turbo-q5_0.bin \
    --host 127.0.0.1 \
    --port 7777 \
    --language en \
    --threads $(nproc) \
    --processors $(nproc) \
    --best-of 5 \
    --convert \
    --beam-size 5 \
    --no-fallback \
    ${GPU_OPTIONS}

#    --word-thold 0.001 \
