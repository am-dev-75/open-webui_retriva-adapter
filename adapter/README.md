# Open WebUI/Retriva Adapter

Thin adapter that mirrors Open WebUI file uploads into Retriva knowledge base.

## Quick start

On a fresh machine, you can install the dependencies and start the service by following these steps:

1. **Create and activate a virtual environment:**
   ```bash
   cd adapter
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. **Install the adapter and its dependencies:**
   ```bash
   pip install -e .
   ```

3. **Configure environment variables:**
   Go back to the root of the project, copy the example environment file and fill in your values (e.g., API keys, URLs):
   ```bash
   cd ..
   cp .env.example .env
   # Edit .env with your favorite editor
   ```

4. **Start the service:**
   Run the application module. By default, it will start a Uvicorn server on port `8500`.
   ```bash
   cd adapter
   python3 -m adapter
   ```