from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Iterable

from faster_whisper import WhisperModel

_HOOK_PHRASES=("how","why","what if","the truth","most people","the problem","the biggest","one thing","here's","here is","you need to","you don't","you do not","never","mistake","secret","nobody","no one","the reason","instead","imagine","listen","surprising","changed my","will change","don't make","do not make","simple way")
_model:WhisperModel|None=None

def run(cmd:list[str])->subprocess.CompletedProcess:
    result=subprocess.run(cmd,capture_output=True,text=True)
    if result.returncode:
        raise RuntimeError(result.stderr[-3500:] or "Media command failed.")
    return result

def probe_duration(path:Path)->float:
    result=run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)])
    try:return float(result.stdout.strip())
    except ValueError as exc:raise RuntimeError("Could not read video duration.") from exc

def transcribe(path:Path)->tuple[list[dict],str]:
    global _model
    if _model is None:_model=WhisperModel("base",device="cpu",compute_type="int8")
    segments,info=_model.transcribe(str(path),vad_filter=True,word_timestamps=False)
    items=[]
    for segment in segments:
        text=segment.text.strip()
        if text:items.append({"start":float(segment.start),"end":float(segment.end),"text":text})
    return items,getattr(info,"language","unknown")

def _hook_score(text:str,duration:float)->tuple[int,str]:
    lower=text.lower();score=52
    hits=sum(1 for phrase in _HOOK_PHRASES if phrase in lower)
    score+=min(25,hits*7)
    if "?" in text:score+=8
    if re.search(r"\b(never|nobody|always|only|exactly|actually|secret|mistake)\b",lower):score+=6
    if 7<=len(text.split())<=38:score+=5
    if duration>=18:score+=3
    kind="Hook" if hits or "?" in text else "Insight"
    return max(50,min(99,score)),kind

def choose_windows(segments:list[dict],count:int,target_duration:int=45)->list[dict]:
    if not segments:raise RuntimeError("No speech was detected. Try a video with clearer spoken audio.")
    candidates=[]
    for i,segment in enumerate(segments):
        start=max(0.0,segment["start"]-1.5);end=segment["end"];text_parts=[segment["text"]];j=i+1
        while j<len(segments) and segments[j]["end"]-start<=target_duration:
            end=segments[j]["end"];text_parts.append(segments[j]["text"]);j+=1
        duration=end-start
        if duration<12:continue
        text=" ".join(text_parts).strip();score,kind=_hook_score(text,duration);score-=min(8,i//8)
        candidates.append({"start":start,"end":end,"text":text,"score":int(score),"type":kind})
    candidates.sort(key=lambda x:x["score"],reverse=True)
    selected=[];min_gap=max(10,target_duration*0.55)
    for candidate in candidates:
        if all(abs(candidate["start"]-old["start"])>=min_gap for old in selected):
            candidate["id"]=f"hook-{len(selected)+1}";candidate["title"]=candidate["text"][:78].strip()+("…" if len(candidate["text"])>78 else "");selected.append(candidate)
        if len(selected)>=max(count*2,count):break
    selected.sort(key=lambda x:x["start"])
    for i,item in enumerate(selected,1):item["id"]=f"hook-{i}"
    return selected

def extract_thumbnail(source:Path,output:Path,timestamp:float)->None:
    output.parent.mkdir(parents=True,exist_ok=True)
    run(["ffmpeg","-y","-ss",f"{max(0,timestamp):.3f}","-i",str(source),"-frames:v","1","-q:v","4",str(output)])

def make_srt(segments:list[dict],start:float,end:float,output:Path)->None:
    lines=[];number=1
    for segment in segments:
        if segment["end"]<=start or segment["start"]>=end:continue
        local_start=max(0.0,segment["start"]-start);local_end=min(end-start,segment["end"]-start)
        if local_end<=local_start:continue
        def stamp(value:float)->str:
            ms=int(round((value-int(value))*1000));total=int(value);h,rem=divmod(total,3600);m,s=divmod(rem,60)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
        lines += [str(number),f"{stamp(local_start)} --> {stamp(local_end)}",segment["text"],""];number+=1
    output.write_text("\n".join(lines),encoding="utf-8")

def _subtitle_filter(path:Path)->str:
    safe=path.as_posix().replace(":","\\:").replace("'","\\'")
    return f"subtitles='{safe}':force_style='FontName=Arial,FontSize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H00101010,BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV=90'"

def make_vertical_clip(source:Path,output:Path,start:float,end:float,*,fmt:str="9:16",srt:Path|None=None,broll:Path|None=None)->None:
    duration=max(1.0,end-start)
    if fmt=="1:1":video_filter="scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080"
    elif fmt=="16:9":video_filter="scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080"
    else:video_filter="scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
    if srt:video_filter+=","+_subtitle_filter(srt)
    cmd=["ffmpeg","-y","-ss",f"{start:.3f}","-i",str(source)]
    if broll:
        cmd += ["-stream_loop","-1","-i",str(broll)]
        bstart=min(8,duration/3);bend=min(13,max(1,duration-1))
        filter_complex=f"[0:v]{video_filter}[main];[1:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[b];[main][b]overlay=0:0:enable='between(t,{bstart:.2f},{bend:.2f})'[v]"
        cmd += ["-t",f"{duration:.3f}","-filter_complex",filter_complex,"-map","[v]","-map","0:a?","-c:v","libx264","-preset","veryfast","-crf","23","-c:a","aac","-b:a","128k"]
    else:
        cmd += ["-t",f"{duration:.3f}","-vf",video_filter,"-c:v","libx264","-preset","veryfast","-crf","23","-c:a","aac","-b:a","128k"]
    cmd += ["-movflags","+faststart",str(output)];run(cmd)

def create_job(source:Path,output_dir:Path,selected:Iterable[dict],*,segments:list[dict],subtitles:bool,fmt:str,broll:Path|None=None)->list[Path]:
    output_dir.mkdir(parents=True,exist_ok=True);results=[]
    for number,item in enumerate(selected,1):
        start,end=float(item["start"]),float(item["end"]);srt=None
        if subtitles:
            srt=output_dir/f"short_{number:02d}.srt";make_srt(segments,start,end,srt)
        output=output_dir/f"short_{number:02d}.mp4";make_vertical_clip(source,output,start,end,fmt=fmt,srt=srt,broll=broll);results.append(output)
    return results

def download_youtube(url:str,destination:Path)->tuple[Path,str]:
    try:import yt_dlp
    except ImportError as exc:raise RuntimeError("YouTube support needs yt-dlp. Run run.bat again to install it.") from exc

    destination.parent.mkdir(parents=True,exist_ok=True)
    template=str(destination.with_suffix(".%(ext)s"))

    # YouTube frequently challenges datacenter IPs. Try the Android player
    # client first, then fall back to yt-dlp's normal client selection.
    client_attempts = [["android"], None]
    last_error = None

    for player_clients in client_attempts:
        for existing in destination.parent.glob(destination.stem+".*"):
            try:
                existing.unlink()
            except OSError:
                pass

        options={
            "format":"bv*+ba/b",
            "merge_output_format":"mp4",
            "outtmpl":template,
            "noplaylist":True,
            "quiet":True,
            "no_warnings":True,
            "retries":3,
            "fragment_retries":3,
            "socket_timeout":30,
        }
        if player_clients:
            options["extractor_args"]={"youtube":{"player_client":player_clients}}

        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info=ydl.extract_info(url,download=True)
                title=info.get("title") or "YouTube video"

            files=sorted(destination.parent.glob(destination.stem+".*"))
            media=next((p for p in files if p.suffix.lower() in {".mp4",".mkv",".webm",".mov"}),None)
            if media:
                return media,title
        except Exception as exc:
            last_error = exc

    message = str(last_error) if last_error else "Unknown YouTube download error."
    if "Sign in to confirm" in message or "not a bot" in message:
        raise RuntimeError(
            "YouTube is currently blocking server-side downloads from this Render server. "
            "This is a YouTube anti-bot challenge, not a ShortForge UI error. "
            "Try another video later or use the Upload Video option."
        )
    raise RuntimeError(f"Could not download the YouTube video: {message}")

