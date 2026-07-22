import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
venv_python = root / "venv" / "Scripts" / "python.exe"

print("Starting Knowledge Hub...")

if not venv_python.exists():
    print(f"ERROR: venv python not found at {venv_python}")
    sys.exit(1)

# Start backend
backend = subprocess.Popen(
    [str(venv_python), "-m", "uvicorn", "api.server:app", "--reload", "--port", "8000"],
    cwd=str(root),
)

print()
print("  Backend:  http://localhost:8000")
print("  API docs: http://localhost:8000/docs")
print()
print("Press Ctrl+C to stop.")

try:
    backend.wait()
except KeyboardInterrupt:
    print("\nShutting down...")
    backend.terminate()
    backend.wait()
