#!/usr/bin/env bash
# One-time setup for Worky. Installs build tools, creates a virtual
# environment, and installs everything needed for the Chat, Coder, and
# Image (safetensors / Hugging Face folder) pages.
#
# GGUF image generation via stable-diffusion.cpp is a separate,
# optional step: see setup_image_gguf.sh.
set -e

cd "$(dirname "$0")"

echo "== 1. System build tools =="
sudo apt update
sudo apt install -y build-essential cmake git python3-pip python3-venv

echo "== 2. Python virtual environment =="
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip

echo "== 3. CPU-only PyTorch (skips the multi-GB CUDA build) =="
pip install torch --index-url https://download.pytorch.org/whl/cpu

echo "== 4. llama.cpp core, compiled with AVX2 for CPU inference =="
CMAKE_ARGS="-DGGML_AVX2=on -DGGML_CUDA=off -DGGML_METAL=off" \
  pip install --no-cache-dir --force-reinstall llama-cpp-python

echo "== 5. Remaining Python dependencies =="
pip install -r requirements.txt

echo ""
echo "Setup complete."
echo "Start the app with: ./start.sh"
echo "For GGUF-based image generation (optional, faster than the safetensors path):"
echo "  ./setup_image_gguf.sh"
