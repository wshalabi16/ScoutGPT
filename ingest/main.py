"""
ScoutGPT ingest service.

Endpoints:
  GET  /health        – liveness check
  POST /ingest        – load a competition/season into Postgres

Run locally:
  uvicorn main:app --reload
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from pipeline import run_ingest

app = FastAPI(title="ScoutGPT Ingest")


class IngestRequest(BaseModel):
    competition_id: int
    season_id: int
    embed: bool = True   # generate embeddings after loading stats


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ingest")
def ingest(req: IngestRequest):
    try:
        result = run_ingest(req.competition_id, req.season_id, embed=req.embed)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
