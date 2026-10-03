"""Authenticated setup/review endpoints. Generation stays in the existing action API."""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
import tempfile
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from .assets import Catalog, SUFFIX
from .config import readiness
from .gates import release_check
from .models import Episode, validate_episode
from .template import starter


class ValidateRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    spec: dict


class EditorialRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    video_sha256: str=Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["approve","reject"]
    checklist: dict[str,StrictBool]
    notes: str=Field(min_length=10,max_length=2000)


def router(components,approver,finished_dir):
    routes=APIRouter()

    @routes.get("/bolt-kids")
    async def page():
        return FileResponse(Path(__file__).resolve().parents[2]/"static"/"bolt-kids.html")

    @routes.get("/api/kids/schema")
    async def schema(): return Episode.model_json_schema()

    @routes.get("/api/kids/template")
    async def template(): return starter()

    @routes.post("/api/kids/validate")
    async def validate(body:ValidateRequest): return validate_episode(body.spec)

    @routes.get("/api/kids/capabilities")
    async def capabilities():
        return {"flow":"bolt_kids_v1","schema":"bolt_kids_episode_v1","target_sec":120,
                "template":"backyard_hide_and_seek_v1","live_pilot_verified":False,
                "readiness":readiness(),"required_setup":["approved character/set assets","OpenAI speech and review access",
                "Eleven Music access or saved songs","fal motion access or saved clips"],
                "final_editorial_review_required":True,"automatic_youtube_publishing":False}

    @routes.get("/api/kids/actions/{action_id}/spec")
    async def saved_spec(action_id:str):
        import agent_actions
        action=await asyncio.to_thread(agent_actions.repository().get,action_id)
        if not action or action.get("operation")!="bolt_kids_episode":
            raise HTTPException(404,"Kids action not found")
        return {"action_id":action_id,"spec_sha256":action["spec_sha256"],
                "payload":action["payload"],"status":action["status"]}

    @routes.get("/api/kids/assets")
    async def assets():
        try: return {"assets":await asyncio.to_thread(Catalog().list),"limit":200}
        except Exception: raise HTTPException(503,"Kids asset storage is unavailable") from None

    @routes.post("/api/kids/assets")
    async def upload(request:Request, file:UploadFile=File(...),name:str=Form(...),
                     license_info:str=Form(...),origin:str=Form(...),approved:bool=Form(False)):
        if not approved: raise HTTPException(422,"Review the source appearance and usage rights before uploading")
        if file.content_type not in SUFFIX: raise HTTPException(422,"Unsupported media type")
        if any(not value.strip() or len(value)>1000 for value in (name,license_info,origin)):
            raise HTTPException(422,"Asset metadata must be nonempty and at most 1000 characters")
        with tempfile.TemporaryDirectory(prefix="kids_upload_") as work:
            path=Path(work)/("source"+SUFFIX[file.content_type]); size=0
            try:
                with path.open("wb") as output:
                    while chunk:=await file.read(65536):
                        size+=len(chunk)
                        if size>32*1024*1024: raise HTTPException(413,"Asset exceeds 32 MiB")
                        output.write(chunk)
                _,blob=components()
                return await asyncio.to_thread(Catalog().add,path,mime_type=file.content_type,
                    license_info=license_info.strip(),origin=origin.strip(),name=name.strip(),
                    reviewer=approver(request),blob=blob)
            except ValueError as exc: raise HTTPException(422,str(exc)) from exc
            finally: await file.close()

    def finished_quality(job_id):
        import finished_api
        record=finished_api._get(job_id,finished_dir) or {}
        if record.get("format")!="bolt_kids" and (record.get("metadata") or {}).get("format")!="bolt_kids":
            raise ValueError("This is not a completed Bolt Kids job")
        artifacts=record.get("artifacts") or {}
        video=artifacts.get("video") or {}; grade=artifacts.get("grade") or {}
        if not video.get("sha256") or not grade.get("sha256"): raise ValueError("Finished Kids artifacts unavailable")
        _,blob=components()
        with tempfile.TemporaryDirectory(prefix="kids_review_") as work:
            target=Path(work)/"quality.json"; blob.download(grade,str(target))
            return video["sha256"],json.loads(target.read_text())

    @routes.get("/api/kids/jobs/{job_id}/review")
    async def get_review(job_id:str):
        try:
            digest,automatic=await asyncio.to_thread(finished_quality,job_id)
            record=await asyncio.to_thread(Catalog().latest_review,job_id,digest)
            return {"job_id":job_id,"video_sha256":digest,"automatic":automatic,
                    "editorial":record,"publishable":bool(record and record.get("publishable"))}
        except ValueError as exc: raise HTTPException(409,str(exc)) from exc

    @routes.post("/api/kids/jobs/{job_id}/review")
    async def review(job_id:str,body:EditorialRequest,request:Request):
        try: digest,automatic=await asyncio.to_thread(finished_quality,job_id)
        except ValueError as exc: raise HTTPException(409,str(exc)) from exc
        if body.video_sha256!=digest: raise HTTPException(409,"Review is stale: the finished video hash changed")
        publishable=release_check(automatic,digest,body.decision,body.checklist)
        if body.decision=="approve" and not publishable:
            raise HTTPException(409,"Approval cannot override missing or failed automatic/editorial checks")
        payload={"job_id":job_id,"video_sha256":digest,"reviewer":approver(request),
                 "decision":body.decision,"checklist":body.checklist,"notes":body.notes,
                 "publishable":publishable,"automatic_report_unchanged":True,
                 "youtube_published":False}
        return await asyncio.to_thread(Catalog().review,job_id,digest,payload)

    return routes
