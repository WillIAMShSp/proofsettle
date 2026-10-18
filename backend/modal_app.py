"""The backend on Modal. From backend/:

    uv run python modal_secret.py --frontend https://your-frontend.example   # once, and after .env changes
    uvx modal deploy modal_app.py

The FastAPI app in app/main.py is served as is. Its settings come from the Modal secret
`proofsettle-backend` (built from backend/.env by modal_secret.py); nothing is read from a
.env file on Modal. Data and photos live in Supabase, so the container keeps nothing on disk.

One container (max_containers=1), on purpose: Solana anchoring and AI inspections run in the
process, after the response, and anchoring's per-shipment lock only guards one process. Two
containers could send the same shipment's transactions twice.
"""

from pathlib import Path

import modal

APP_NAME = "proofsettle-backend"
SECRET_NAME = "proofsettle-backend"
HERE = Path(__file__).resolve().parent

image = (
    modal.Image.debian_slim(python_version="3.12")
    # Dependencies from pyproject.toml + uv.lock (frozen); the project itself isn't installed.
    .uv_sync(str(HERE))
    # The package, including its non-Python files (app/chain/proofsettle.json,
    # app/fixtures/mock_inspection.json). /root is on the container's PYTHONPATH.
    .add_local_dir(HERE / "app", "/root/app", ignore=["**/__pycache__", "**/*.pyc"])
)

app = modal.App(APP_NAME, image=image)


@app.function(
    secrets=[modal.Secret.from_name(SECRET_NAME)],
    max_containers=1,
    # Stay up between requests (Modal's maximum is 20 minutes), so a background inspection
    # or Solana anchoring that outlives its request isn't cut short, and fewer cold starts.
    scaledown_window=20 * 60,
    # Per request, including the background work after the response: an inspection can take
    # Gemini's full timeout (5 min) plus storing and anchoring.
    timeout=15 * 60,
    # Next to the Supabase database (us-east-2), so every query is a short hop. Optional:
    # pinning a region costs more on Modal; remove it to let Modal choose.
    region="us-east",
)
@modal.concurrent(max_inputs=50)
@modal.asgi_app()
def web():
    from app.main import app as fastapi_app

    return fastapi_app
