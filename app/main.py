from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI,File,Form,UploadFile
from fastapi.responses import FileResponse,HTMLResponse
from fastapi.staticfiles import StaticFiles

from .processor import choose_windows,create_job,download_youtube,extract_thumbnail,probe_duration,transcribe

ROOT=Path(__file__).resolve().parent.parent
DATA=ROOT/"data";UPLOADS=DATA/"uploads";OUTPUTS=DATA/"outputs";PREVIEWS=DATA/"previews";WEB=ROOT/"web"
for folder in (UPLOADS,OUTPUTS,PREVIEWS):folder.mkdir(parents=True,exist_ok=True)

app=FastAPI(title="ShortForge AI",version="0.2.0")
app.mount("/static",StaticFiles(directory=WEB),name="static")
app.mount("/media",StaticFiles(directory=DATA),name="media")

def save_upload(upload:UploadFile,destination:Path)->Path:
    suffix=Path(upload.filename or "video.mp4").suffix.lower() or ".mp4";target=destination.with_suffix(suffix)
    with target.open("wb") as buffer:shutil.copyfileobj(upload.file,buffer)
    return target

@app.get("/",response_class=HTMLResponse)
def home():return (WEB/"index.html").read_text(encoding="utf-8")

@app.post("/api/analyze")
async def analyze(url:str=Form(""),video:UploadFile|None=File(None),count:int=Form(5)):
    job_id=uuid.uuid4().hex[:10];job_dir=PREVIEWS/job_id;job_dir.mkdir(parents=True,exist_ok=True);source_path=None
    try:
        if url.strip():source_path,title=download_youtube(url.strip(),job_dir/"source.mp4")
        elif video and video.filename:source_path=save_upload(video,job_dir/"source");title=Path(video.filename).stem.replace("_"," ")
        else:return {"error":"Add a YouTube URL or choose a video file."}
        duration=probe_duration(source_path);segments,language=transcribe(source_path);hooks=choose_windows(segments,count=max(3,min(count*2,10)),target_duration=45)
        for hook in hooks:
            thumb=job_dir/(hook["id"]+".jpg");extract_thumbnail(source_path,thumb,hook["start"]);hook["thumbnail_url"]=f"/media/previews/{job_id}/{thumb.name}";hook["preview_url"]=f"/media/previews/{job_id}/{source_path.name}#t={hook['start']:.2f},{hook['end']:.2f}";hook.pop("text",None)
        (job_dir/"analysis.json").write_text(json.dumps({"title":title,"duration":duration,"language":language,"hooks":hooks},indent=2),encoding="utf-8")
        return {"job_id":job_id,"title":title,"duration":duration,"language":language,"preview_url":f"/media/previews/{job_id}/{source_path.name}","hooks":hooks}
    except Exception as exc:
        shutil.rmtree(job_dir,ignore_errors=True);return {"error":str(exc)}

@app.post("/api/generate")
async def generate(selected:str=Form("[]"),subtitles:str=Form("false"),subtitle_style:str=Form("Modern Highlight"),broll:str=Form("false"),fmt:str=Form("9:16"),broll_file:UploadFile|None=File(None)):
    try:
        selected_ids=json.loads(selected)
        if not selected_ids:return {"error":"Select at least one hook."}
        snapshots=sorted(PREVIEWS.glob("*/analysis.json"),key=lambda p:p.stat().st_mtime,reverse=True)
        if not snapshots:return {"error":"Analyze a video before generating Shorts."}
        snapshot_path=snapshots[0];job_dir=snapshot_path.parent;data=json.loads(snapshot_path.read_text(encoding="utf-8"));hooks={item["id"]:item for item in data["hooks"]};chosen=[hooks[item] for item in selected_ids if item in hooks]
        source=next((p for p in job_dir.iterdir() if p.name.startswith("source") and p.suffix.lower() in {".mp4",".mkv",".webm",".mov"}),None)
        if not source:return {"error":"The analyzed source video is no longer available."}
        broll_path=None
        if broll.lower()=="true" and broll_file and broll_file.filename:broll_path=save_upload(broll_file,job_dir/"broll")
        output_dir=OUTPUTS/job_dir.name
        segments,_=transcribe(source) if subtitles.lower()=="true" else ([{"start":item["start"],"end":item["end"],"text":item.get("title","")} for item in chosen], "unknown")
        clips=create_job(source,output_dir,chosen,segments=segments,subtitles=subtitles.lower()=="true",fmt=fmt if fmt in {"9:16","1:1","16:9"} else "9:16",broll=broll_path)
        return {"clips":[{"name":p.name,"url":f"/media/outputs/{job_dir.name}/{p.name}","duration":float(chosen[index]["end"])-float(chosen[index]["start"])} for index,p in enumerate(clips)],"subtitle_style":subtitle_style}
    except Exception as exc:return {"error":str(exc)}

@app.get("/api/download/{job_id}/{filename}")
def download(job_id:str,filename:str):
    path=OUTPUTS/job_id/filename
    if not path.is_file() or path.parent!=OUTPUTS/job_id:return {"error":"File not found."}
    return FileResponse(path,media_type="video/mp4",filename=path.name)