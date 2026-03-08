"""
Modal deployment for the RAG prepare pipeline.
Run: modal deploy modal_rag.py

Requires a Modal secret named 'rag-secrets' with:
  GOOGLE_API_KEY, BROWSERBASE_API_KEY, TAVILY_API_KEY, GOOGLE_MAPS_API_KEY (optional)
"""

import os
import subprocess
import sys

import modal

app = modal.App("rag-prepare")

MARKER = "--- Assistant Response ---"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "fastapi[standard]",
        "langchain",
        "langchain-core",
        "langchain-community",
        "langchain-google-genai",
        "langgraph",
        "browserbase",
        "playwright",
        "requests",
    )
    .run_commands("playwright install chromium")
    .add_local_file("main-rag.py", remote_path="/main-rag.py")
)


def extract_assistant_output(stdout: str) -> str:
    idx = stdout.rfind(MARKER)
    if idx == -1:
        return stdout.strip()
    return stdout[idx + len(MARKER) :].strip()


@app.function(
    image=image,
    timeout=180,
    secrets=[modal.Secret.from_name("rag-secrets")],
)
@modal.web_endpoint(method="POST")
def prepare(payload: dict) -> dict:
    """HTTP POST endpoint. Expects JSON body with 'prompt'."""
    prompt = (payload or {}).get("prompt", "")
    if isinstance(prompt, str):
        prompt = prompt.strip()
    else:
        prompt = ""

    if not prompt:
        return {"success": False, "error": "prompt is required"}

    try:
        result = subprocess.run(
            [sys.executable, "/main-rag.py"],
            env={**os.environ, "RAG_INPUT": prompt},
            capture_output=True,
            text=True,
            timeout=170,
        )
    except subprocess.TimeoutExpired as e:
        return {"success": False, "error": f"RAG pipeline timed out: {e}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

    if result.returncode != 0:
        err = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        return {"success": False, "error": err}

    output = extract_assistant_output(result.stdout)
    return {"success": True, "ragOutput": output}
