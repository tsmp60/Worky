# Worky

**A local-first AI workspace for chatting, coding, and image generation.**

Worky is a web app that runs on your own computer and connects to AI models stored locally. It brings three workflows together in one browser-based interface: chat with a language model, work on coding projects with a file-based assistant, and generate images with a local image model.

The app runs at `http://127.0.0.1:5050`. Its local model workflows do not require an API key. Web search is optional; when enabled, search queries are sent to the selected search provider.

## Features

### Chat

- Chat with a locally loaded language model.
- Save conversations and reopen them from the sidebar.
- Optionally enable web search for answers that need current information.
- Display model reasoning separately when the model emits reasoning inside `<think>...</think>` tags.

### Coder

- Keep projects in separate workspaces with a nested file tree.
- Ask the assistant to inspect files, read project content, and search the web.
- Review its actions in an activity transcript.
- See diffs when the assistant creates or changes files.
- Open, edit, and save files in the built-in editor.
- Upload files to a project and export a project as a ZIP archive.

### Image generation

- Generate images from prompts with a locally loaded image model.
- Use a single-file `.safetensors` image checkpoint or a Hugging Face Diffusers model directory.
- The documented Diffusers workflow runs on the CPU; generation speed depends on the model and hardware.

### Local model management

- Load text models in GGUF or Hugging Face format.
- Load image models from a `.safetensors` checkpoint or Hugging Face Diffusers directory.
- Remember a model selection for each page.
- Unload the active page's model when switching to another page, rather than intentionally keeping every page's model in memory.
- Configure a RAM limit for supported Hugging Face model offloading. Disk offloading requires `accelerate` and can reduce speed.

## Requirements and performance

Worky's performance depends on the model and the computer running it.

- **Python:** Python 3.11 (64-bit) is the recommended starting point for the installation steps below. The project dependencies are not version-pinned, so compatibility can change as upstream packages change.
- **RAM and disk:** Model files can be several gigabytes. Larger models need more memory, and disk offloading can be slower than keeping a model in RAM.
- **CPU:** The setup instructions below install CPU versions of the required inference libraries. CPU inference can be slow, especially for image generation.
- **Internet:** An internet connection is needed to install dependencies and download models. The app's local inference workflows do not require an external AI API. Web search is optional.

A smaller or more heavily quantized model is often a better starting point on a computer with limited memory.

## Installation

Choose the instructions for your operating system. The Linux setup script is written for Ubuntu/Debian-style systems. Windows users should follow the Command Prompt instructions instead of running the `.sh` scripts directly.

### Windows (Command Prompt / CMD)

The following steps set up Worky's CPU-based Chat, Coder, and Diffusers image workflows on Windows.

#### 1. Install prerequisites

Install these tools before continuing:

- **Python 3.11, 64-bit:** install from [python.org](https://www.python.org/downloads/windows/) and enable the Python launcher (`py`).
- **Git for Windows:** needed if you plan to clone the repository. A ZIP download from GitHub is also fine.
- **Microsoft C++ Build Tools:** normally only needed if pip cannot find a compatible `llama-cpp-python` wheel and has to compile it. During installation, select **Desktop development with C++**, including the MSVC compiler, a Windows SDK, and CMake tools. See [Microsoft's C++ Build Tools documentation](https://learn.microsoft.com/en-us/cpp/build/building-on-the-command-line).

Open **Command Prompt**. Clone the repository, or change directory to the folder where you extracted it:

```cmd
git clone https://github.com/USERNAME/REPOSITORY.git
cd REPOSITORY
```

If you downloaded a ZIP instead, use `cd /d` with the path to the extracted project directory, for example:

```cmd
cd /d "C:\Users\YOUR_USERNAME\Downloads\worky"
```

#### 2. Create a virtual environment and install dependencies

Run these commands from the project directory:

```cmd
py -3.11 -m venv venv
venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
python -m pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
python -m pip install -r requirements.txt
```

The `llama-cpp-python` command uses the package's published CPU-wheel index. If pip cannot find a wheel compatible with your Python version and Windows architecture, it may try to build the package from source. In that case, install the Microsoft C++ Build Tools described above and use the **x64 Native Tools Command Prompt** or the **Developer Command Prompt** provided by Visual Studio.

#### 3. If `llama-cpp-python` must be built from source

Open the Visual Studio Developer Command Prompt, change to the Worky project directory, and activate the virtual environment again:

```cmd
cd /d "C:\path\to\worky"
venv\Scripts\activate.bat
```

For a CPU that supports AVX2, use the same AVX2 optimization as the Linux setup:

```cmd
set CMAKE_ARGS=-DGGML_AVX2=on -DGGML_CUDA=off
python -m pip install --no-cache-dir --force-reinstall llama-cpp-python
```

If your CPU does not support AVX2, do not enable that option. Use:

```cmd
set CMAKE_ARGS=-DGGML_CUDA=off
python -m pip install --no-cache-dir --force-reinstall llama-cpp-python
```

Then install the remaining requirements if needed:

```cmd
python -m pip install -r requirements.txt
```

The `CMAKE_ARGS` setting applies only to the current Command Prompt window.

#### 4. Start Worky

With the virtual environment activated, run:

```cmd
python -m server.app
```

The app should open in your browser. If it does not, visit:

```text
http://127.0.0.1:5050
```

To start Worky again later, open a new Command Prompt, change to the project directory, and run:

```cmd
venv\Scripts\activate.bat
python -m server.app
```

**Windows limitation:** the optional `setup_image_gguf.sh` script is a Bash/Linux script, not a CMD script. In addition, the current `server/image_gen.py` points to the Linux-style `sd.cpp/build/bin/sd` executable path and does not resolve the Windows `.exe` filename. Therefore, GGUF-based image generation is not supported by the current Windows setup instructions. Use a `.safetensors` checkpoint or a Hugging Face Diffusers directory for image generation on Windows.

### Linux (Ubuntu/Debian)

The included setup script uses `apt`, `sudo`, and Bash, so these instructions are for Ubuntu/Debian-style Linux distributions.

From the project directory, run:

```bash
chmod +x start setup.sh
./start
```

On first launch, `start` runs `setup.sh` if the virtual environment does not exist. The setup script installs system build tools, creates `venv`, installs CPU-only PyTorch and `llama-cpp-python`, and installs the packages in `requirements.txt`. It then starts the Flask app.

To start Worky on later runs:

```bash
./start
```

The optional GGUF image-generation engine can be built on the documented Linux setup with:

```bash
./setup_image_gguf.sh
```

This clones and builds `stable-diffusion.cpp`. It is not required for `.safetensors` checkpoints or Hugging Face Diffusers model directories.

## Loading models

On the page where you want to use a model, select **Browse...** beside the model path field and choose the model file or directory.

| Model format | What to select | Intended use |
| --- | --- | --- |
| GGUF file (`.gguf`) | Select the file itself | Chat and coding; GGUF image generation requires the optional `stable-diffusion.cpp` engine and is currently documented for Linux only |
| Single-file `.safetensors` checkpoint | Select the file itself | Image generation |
| Hugging Face model directory | Select the directory containing the model configuration and files | Text or image models, depending on the model |

A standalone `.safetensors` text-model weights file is not enough to load a text model. Select the complete model directory containing its configuration and related files. A single-file `.safetensors` image checkpoint is supported by the image workflow.

### Memory notes

- GGUF models are memory-mapped by the underlying runtime, which can help reduce memory pressure.
- Hugging Face models can use the RAM limit in the sidebar settings. Disk offloading for larger models requires `accelerate` and may reduce performance.
- The Diffusers image workflow enables attention and VAE memory-saving features where available.
- Model compatibility, memory use, and speed vary. Check the model publisher's instructions and license before downloading or using a model.

## Reasoning display

Some reasoning-tuned chat models place their reasoning in `<think>...</think>` tags. When a loaded model uses this format, Worky displays that content separately in the **Reasoning** panel. Models that do not emit these tags will not populate the panel.

## Web search

Web search is optional and off by default. It is available in Chat and Coder.

- **DuckDuckGo:** used when no search API key is configured; no API key is needed for this mode.
- **Brave Search:** can be used when a Brave Search API key is configured in the sidebar settings.

When web search is enabled, queries are sent to the selected search service. Review that provider's privacy policy before using the feature.

## Send a conversation to another page

The **Send to** control in Chat turns the current conversation into a starting prompt for Coder or Image and switches to that page. This can be useful when planning a task in Chat before carrying it out in another workspace.

## Project structure

```text
worky/
├── start                  # Linux startup script
├── start.sh               # Linux startup script (same purpose as start)
├── setup.sh               # Linux dependency and environment setup
├── setup_image_gguf.sh    # Optional Linux GGUF image-engine setup
├── requirements.txt
├── config.json            # Created locally to store settings and remembered model paths
├── LICENSE
├── THIRD_PARTY_NOTICES.md  # Notices for bundled third-party assets
├── .gitignore
├── server/                # Flask routes and model/chat/coder/search logic
├── static/                # Front-end assets and generated images
├── templates/             # HTML templates
├── workspace/             # Coder projects (local user data)
└── data/
    └── chat.db            # SQLite conversation history (local user data)
```

## Privacy and local data

Worky runs its web server on `127.0.0.1`, so the application is intended for use on the same computer. Local model inference runs on that machine. Installing dependencies and downloading models requires an internet connection. If web search is enabled, search queries are sent to the configured search provider.

The following paths can contain personal or machine-specific data and should not be committed to a public repository:

- `config.json` — remembered model paths and settings; may contain an API key if one is configured.
- `data/chat.db` — saved conversations and messages.
- `workspace/` — files created or uploaded through Coder.
- `models/` — downloaded model files, if stored in the project directory.
- `static/generated/` — generated images.
- `venv/`, `__pycache__/`, and compiled files — local environment/build artifacts.

A `.gitignore` file is included with the companion files for this README. If any of these files are already tracked by Git, adding them to `.gitignore` will not remove them from the Git index; remove them from tracking before publishing.

## Troubleshooting

- **`py -3.11` is not recognized:** install Python 3.11 and ensure the Python launcher is installed. Reopen Command Prompt after installation.
- **`llama-cpp-python` fails to install on Windows:** update pip, check that Python is 64-bit, and install the Microsoft C++ Build Tools if pip is compiling from source. Use a Visual Studio Developer Command Prompt for source builds.
- **A model will not load:** check that you selected the correct file or model directory and that the format is supported for that page.
- **The model is too slow or runs out of memory:** try a smaller or more heavily quantized model, reduce the configured RAM limit where appropriate, or use a computer with more available memory.
- **GGUF image generation is unavailable:** on Linux, run `./setup_image_gguf.sh` and review any build errors. The current Windows setup does not support this optional engine.
- **Web search does not work:** check your internet connection and, when using Brave Search, verify that the configured API key is valid.
- **The app does not open automatically:** open `http://127.0.0.1:5050` manually after starting the server.

When reporting a problem, include your operating system, Python version, the command you ran, and the relevant error output. Remove API keys, passwords, personal paths, and other private information before posting logs publicly.

## Contributing

Bug reports, suggestions, and pull requests are welcome.

1. Open an issue to describe a bug or propose a significant change.
2. For bug reports, include steps to reproduce the problem and relevant error messages.
3. Keep pull requests focused and explain user-visible changes.
4. Test the affected workflow where possible and update the documentation when behavior or setup instructions change.

Please do not include API keys, private chat histories, personal model paths, or private project files in issues or pull requests.

## License

Worky's project code is licensed under the [MIT License](LICENSE). The bundled CodeMirror editor's MIT notice is included in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Python dependencies, other third-party assets, and downloaded AI models may have separate licenses and terms; check those licenses before redistributing them.

## Useful installation references

- [PyTorch — Get Started](https://pytorch.org/get-started/locally/)
- [llama-cpp-python — Installation](https://github.com/abetlen/llama-cpp-python#installation)
- [Microsoft C++ Build Tools — command-line builds](https://learn.microsoft.com/en-us/cpp/build/building-on-the-command-line)
