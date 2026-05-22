import os
import signal
import shutil
import subprocess
import uuid
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
import uvicorn

AUTORESEARCH_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "autoresearch.py")

app = FastAPI()
active_runs: dict[str, subprocess.Popen] = {}


@app.post("/run")
async def run_evolution(
    task: str = Form(...),
    baseline: str = Form(...),
    iterations: int = Form(...),
    modelChoice: str = Form("local"),
    apiKey: str = Form(""),
    data: UploadFile = File(None),
):
    run_id = str(uuid.uuid4())
    workdir = f"/tmp/run_{run_id}"
    os.makedirs(workdir, exist_ok=True)

    with open(os.path.join(workdir, "program.md"), "w") as f:
        f.write(task)
    with open(os.path.join(workdir, "train.py"), "w") as f:
        f.write(baseline)
    if data:
        contents = await data.read()
        with open(os.path.join(workdir, data.filename), "wb") as f:
            f.write(contents)

    def stream_researcher():
        env = os.environ.copy()
        env["MAX_ITERATIONS"] = str(iterations)
        if modelChoice == "gemini":
            env["USE_GEMINI"] = "true"
            env["GEMINI_API_KEY"] = apiKey
        if data:
            env["DATASET_PATH"] = data.filename

        process = subprocess.Popen(
            ["python", "-u", AUTORESEARCH_PATH],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            cwd=workdir,
            preexec_fn=os.setsid,
        )
        active_runs[run_id] = process
        yield f"__RUN_ID__:{run_id}\n"

        try:
            while True:
                read_fn = getattr(process.stdout, "read1", process.stdout.read)
                chunk = read_fn(128)
                if not chunk:
                    break
                yield chunk.decode("utf-8", errors="replace")
        finally:
            process.stdout.close()
            process.wait()
            active_runs.pop(run_id, None)

            try:
                with open(os.path.join(workdir, "train.py"), "r") as f:
                    yield "\n[FINAL_CODE_START]\n"
                    for line in f:
                        yield line
                    yield "\n[FINAL_CODE_END]\n"
            except FileNotFoundError:
                pass

            shutil.rmtree(workdir, ignore_errors=True)

    return StreamingResponse(stream_researcher(), media_type="text/plain")


@app.post("/cancel/{run_id}")
async def cancel_run(run_id: str):
    process = active_runs.get(run_id)
    if process is None:
        return JSONResponse({"error": "run not found"}, status_code=404)
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except ProcessLookupError:
        pass
    return JSONResponse({"status": "cancelled", "run_id": run_id})


if __name__ == "__main__":
    # Listen on all interfaces so the Mac host can reach it
    uvicorn.run(app, host="0.0.0.0", port=8000)
