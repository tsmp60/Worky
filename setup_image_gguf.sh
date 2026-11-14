#!/usr/bin/env bash
# Optional: builds stable-diffusion.cpp so the Image page can also run
# quantized .gguf Stable Diffusion models (faster and lighter on RAM
# than the safetensors/diffusers CPU path). Not required if you only
# plan to use .safetensors files or Hugging Face model folders.
set -e

cd "$(dirname "$0")"

if [ ! -d "sd.cpp" ]; then
  git clone --recursive https://github.com/leejet/stable-diffusion.cpp sd.cpp
fi

cd sd.cpp
mkdir -p build && cd build
cmake .. -DGGML_AVX2=on -DGGML_CUDA=off
cmake --build . --config Release -j"$(nproc)"

echo ""
echo "Built. The binary is at sd.cpp/build/bin/sd"
echo "You can now load a quantized GGUF Stable Diffusion model on the Image page."
