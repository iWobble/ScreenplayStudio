"""A story as a filmstrip to review before it is rendered: one self-contained HTML page that plays the story's sound while it shows each
shot's still, moved the way the render will move it, with the line being spoken as a caption, and a strip of the shots to jump along.

The timing is the render's own plan (`manifest.plan`), so what is seen and heard here is what the film will be. The page holds
its pictures (small JPEGs) and its sound inside it, so it opens anywhere, with no sign-in; it cannot change anything in Marvin, so
approving is done there. `player()` is pure (the pieces in, text out); `make()` does the ffmpeg work."""

import base64
import html
import json
from pathlib import Path

from . import build, ffmpeg, manifest


def _clamp(x: float, zoom: float) -> float:
    half = 0.5 / max(zoom, 1.0)
    return min(max(x, half), 1 - half)


def player(title: str, shots: list[dict], audio_src: str) -> str:
    """The page. Each shot: {"id", "label", "start", "duration", "image" (a data: or http url), "from": {x, y, zoom}, "to": {...},
    "lines": [{"speaker", "text", "start", "end"}]}. `audio_src` is the story's sound."""
    data = json.dumps(shots).replace("</", "<\\/")
    heading = html.escape(title)
    return (
        f"<!DOCTYPE html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{heading}: filmstrip</title><style>{_STYLE}</style></head><body>"
        f"<h1>{heading}</h1><p class='hint'>Space plays or pauses; the arrows go to the next or previous shot. This page only plays: approve the beats in Marvin.</p>"
        "<div class='stage'><div class='frame'><img id='pic' alt=''></div><div id='caption' class='caption'></div></div>"
        "<div class='bar'><button id='prev' aria-label='Previous shot'>&#9664;&#9664;</button><button id='play' aria-label='Play or pause'>&#9654;</button>"
        "<button id='next' aria-label='Next shot'>&#9654;&#9654;</button></div><div id='where' class='where'></div>"
        "<input id='seek' type='range' min='0' max='1000' value='0' aria-label='Position'>"
        "<div id='strip' class='strip'></div>"
        f"<audio id='a' preload='auto' src='{html.escape(audio_src, quote=True)}'></audio>"
        f"<script>const SHOTS={data};{_SCRIPT}</script></body></html>\n"
    )


_STYLE = (
    "body{margin:0;padding:1rem;background:#16161a;color:#eee;font:15px/1.4 system-ui,sans-serif;text-align:center}h1{font-size:1.1rem;margin:.2rem 0}"
    ".hint{color:#9a9aa5;font-size:.8rem;margin:.2rem 0 .8rem}.stage{position:relative;width:min(100%,380px);margin:0 auto}"
    ".frame{position:relative;aspect-ratio:9/16;overflow:hidden;background:#000;border-radius:8px}"
    ".frame img{position:absolute;left:0;top:0;width:100%;height:100%;transform-origin:0 0;will-change:transform}"
    ".caption{position:absolute;left:8px;right:8px;bottom:14px;padding:.4rem .6rem;border-radius:6px;background:rgba(0,0,0,.62);font-size:1rem;min-height:1.2rem}"
    ".caption:empty{display:none}.caption b{color:#f0c36b;font-weight:600}"
    ".bar{display:flex;gap:.8rem;align-items:center;justify-content:center;margin:.8rem 0 .3rem}.bar button{display:inline-flex;align-items:center;justify-content:center;background:#2a2a31;color:#eee;border:1px solid #3d3d46;border-radius:999px;width:56px;height:44px;padding:0;font-size:1rem;line-height:1;cursor:pointer}"
    ".bar button#play{width:64px;height:52px;font-size:1.2rem}.bar button:hover{background:#34343c}.where{color:#bdbdc7;text-align:center;margin:.2rem 0 .5rem;font-variant-numeric:tabular-nums}input[type=range]{display:block;width:min(100%,380px);margin:0 auto}"
    ".strip{display:flex;gap:6px;overflow-x:auto;padding:.7rem 0;max-width:100%}.strip::before,.strip::after{content:'';margin:auto}.strip img{height:84px;aspect-ratio:9/16;object-fit:cover;border-radius:4px;border:2px solid transparent;cursor:pointer;flex:0 0 auto;opacity:.65}"
    ".strip img.on{border-color:#f0c36b;opacity:1}"
)

_SCRIPT = r"""
const a=document.getElementById('a'),pic=document.getElementById('pic'),cap=document.getElementById('caption'),where=document.getElementById('where'),seek=document.getElementById('seek'),strip=document.getElementById('strip'),play=document.getElementById('play');
const total=SHOTS.length?SHOTS[SHOTS.length-1].start+SHOTS[SHOTS.length-1].duration:0;let cur=-1;
const clamp=(x,z)=>{const h=.5/Math.max(z,1);return Math.min(Math.max(x,h),1-h)};
const tc=s=>Math.floor(s/60)+':'+(s%60).toFixed(1).padStart(4,'0');
SHOTS.forEach((s,i)=>{const t=document.createElement('img');t.src=s.image;t.alt=s.label;t.title=s.label;t.onclick=()=>go(i,true);strip.append(t)});
function idx(t){let i=0;for(let k=0;k<SHOTS.length;k++){if(t>=SHOTS[k].start)i=k}return i}
function go(i,start){i=Math.max(0,Math.min(SHOTS.length-1,i));a.currentTime=SHOTS[i].start+0.001;if(start)a.play()}
function frame(){const t=a.currentTime,i=idx(t),s=SHOTS[i];if(!s){requestAnimationFrame(frame);return}
 if(i!==cur){cur=i;pic.src=s.image;[...strip.children].forEach((c,k)=>c.classList.toggle('on',k===i));strip.children[i].scrollIntoView({block:'nearest',inline:'center'})}
 const p=Math.min(1,Math.max(0,(t-s.start)/Math.max(s.duration,.01))),f=s.from,o=s.to,z=f.zoom+(o.zoom-f.zoom)*p,x=clamp(f.x+(o.x-f.x)*p,z),y=clamp(f.y+(o.y-f.y)*p,z);
 pic.style.transform='translate('+(-(x*z-.5)*100)+'%,'+(-(y*z-.5)*100)+'%) scale('+z+')';
 const L=(s.lines||[]).find(l=>t>=l.start&&t<=l.end+.15);cap.replaceChildren();if(L){const b=document.createElement('b');b.textContent=(L.speaker||'')+(L.speaker?': ':'');cap.append(b,document.createTextNode(L.text||''))}
 where.textContent=s.label+' · '+(i+1)+'/'+SHOTS.length+' · '+tc(t)+' / '+tc(total);seek.value=total?Math.round(1000*t/total):0;play.innerHTML=a.paused?'&#9654;':'&#10074;&#10074;';requestAnimationFrame(frame)}
document.getElementById('next').onclick=()=>go(idx(a.currentTime)+1,!a.paused);document.getElementById('prev').onclick=()=>{const i=idx(a.currentTime);go(a.currentTime-SHOTS[i].start>1.2?i:i-1,!a.paused)};
play.onclick=()=>a.paused?a.play():a.pause();seek.oninput=()=>{a.currentTime=total*seek.value/1000};
document.addEventListener('keydown',e=>{if(e.key==='ArrowRight')go(idx(a.currentTime)+1,!a.paused);else if(e.key==='ArrowLeft')go(idx(a.currentTime)-1,!a.paused);else if(e.key===' '){e.preventDefault();a.paused?a.play():a.pause()}});
if(SHOTS.length){pic.src=SHOTS[0].image;requestAnimationFrame(frame)}
"""


def _data_uri(raw: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


def _small(still: Path, work: Path, n: int) -> str:
    """The still as a small JPEG (so the page stays a few MB), as a data: url."""
    out = work / f"still{n:03d}.jpg"
    ffmpeg.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(still), "-vf", "scale=540:-2", "-q:v", "5", str(out)])
    return _data_uri(out.read_bytes(), "image/jpeg")


def make(m: manifest.Manifest, work: Path, *, audio_url: str | None = None) -> dict:
    """Mix the sound, then write `filmstrip.html` into `work`. With `audio_url` the page points at the already-made cut; without it the sound
    is made here and held inside the page. Returns {"html": path, "seconds", "shots"}."""
    work.mkdir(parents=True, exist_ok=True)
    timeline = manifest.plan(m)
    cut = None
    if audio_url is None:
        cut = build.listen(m, work / "filmstrip.mp3")
        audio_src = _data_uri((work / "filmstrip.mp3").read_bytes(), "audio/mpeg")
    else:
        audio_src = audio_url
    shots = []
    for n, planned in enumerate(timeline.shots):
        s = planned.shot
        shots.append(
            {
                "id": s.id,
                "label": f"Beat {s.id[1:]}" if s.id.startswith("b") else s.id,
                "start": round(planned.start, 3),
                "duration": round(planned.duration, 3),
                "image": _small(s.still, work, n),
                "from": {"x": s.move_from.x, "y": s.move_from.y, "zoom": s.move_from.zoom},
                "to": {"x": s.move_to.x, "y": s.move_to.y, "zoom": s.move_to.zoom},
                "lines": [{"speaker": p.line.speaker, "text": p.line.text, "start": round(p.start, 3), "end": round(p.start + p.line.duration, 3)} for p in planned.lines],
            }
        )
    page = work / "filmstrip.html"
    page.write_text(player(m.title, shots, audio_src), encoding="utf-8")
    return {"html": page, "seconds": round(timeline.duration, 3), "shots": len(shots), "cut": cut}
