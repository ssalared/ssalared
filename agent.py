#!/usr/bin/env python3
"""
ایجنت هوش مصنوعی محلی — همه‌چیز در یک فایل
=============================================

چی هست؟
  بهش به زبان خودت (فارسی یا انگلیسی، تایپی یا صوتی) می‌گی چی می‌خوای؛
  خودش دستورات رو قدم‌به‌قدم می‌سازه و روی لپ‌تاپت اجرا می‌کنه.
  برنامه‌نویسی و حل کد، مدیریت فایل‌ها، نصب و اجرای بازی‌ها و برنامه‌ها،
  وب‌گردی، و هر ابزاری که لازم داشته باشه و روی سیستم نباشه رو خودش نصب می‌کنه.

پیش‌نیاز:
  فقط پایتون ۳.۸ به بالا (ویندوز / مک / لینوکس). هیچ نصب اضافه‌ای لازم نیست.
  پکیج‌های حالت صوتی رو هم خودش موقع نیاز نصب می‌کنه.

قدم ۱ — کلید API رایگان (یکی کافیه، ثبت‌نام رایگانه):
  Google Gemini (پیشنهادی): https://aistudio.google.com/apikey
  Groq:                     https://console.groq.com/keys
  OpenRouter (مدل‌های free): https://openrouter.ai/settings/keys
  Mistral:                  https://console.mistral.ai/api-keys

قدم ۲ — ست کردن کلید:
  ویندوز (PowerShell):  setx GEMINI_API_KEY "کلید-تو"   ← بعدش یه ترمینال جدید باز کن
  لینوکس / مک:          export GEMINI_API_KEY="کلید-تو"

قدم ۳ — اجرا:
  python agent.py                    حالت متنی تعاملی (کارها رو یکی‌یکی بگو)
  python agent.py -y                 حالت کاملاً خودکار: بدون تأیید، هر دستوری رو اجرا کنه
  python agent.py --voice -y         حالت صوتی: حرف بزن، ایجنت گوش می‌ده و بلند جواب می‌ده
  python agent.py --web              حالت وب: سایت با دو اتاق توی مرورگرت باز می‌شه
                                     (آدرس: http://127.0.0.1:8765 — فقط از همین لپ‌تاپ
                                     در دسترسه، کسی از بیرون نمی‌تونه ببینتش)
  python agent.py "متن کار"          یک کار مشخص، همون لحظه

گزینه‌ها:
  -y / --yes        اجرای خودکار بدون تأیید هر دستور
  --voice           حالت صوتی (ورودی میکروفون با Whisper آفلاین + جواب گفتاری با TTS)
  --web             حالت وب: اتاق گفتگو + اتاق کنترل توی مرورگر
  --port N          پورت حالت وب (پیش‌فرض 8765)
  --install-voice   نصب پکیج‌های صوتی (faster-whisper, sounddevice, pyttsx3)
  -p PROVIDER       سرویس: gemini | groq | openrouter | mistral (پیش‌فرض gemini)
  --model NAME      مدل دلخواه
  --api-key KEY     کلید بدون متغیر محیطی
  --timeout N       تایم‌اوت هر دستور به ثانیه (پیش‌فرض ۱۲۰)
  --max-steps N     سقف مراحل هر کار (پیش‌فرض ۳۰)

نکته امنیتی:
  حالت پیش‌فرض قبل از اجرای هر دستور نشون می‌ده و تأیید می‌گیره.
  با -y (یا تیک «اجرای خودکار» توی اتاق کنترل) کنترل کامل به ایجنت می‌دی؛
  روی کارهای حساس (پاک‌کردن فایل، تغییر تنظیمات سیستم) حواست باشه.
"""

import argparse
import http.server
import json
import os
import platform
import queue
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

MAX_OUTPUT_CHARS = 6000
MAX_HISTORY_MESSAGES = 60
WEB_PORT = 8765

PRESETS = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "model": "gemini-2.5-flash",
        "env": "GEMINI_API_KEY",
        "keys_url": "https://aistudio.google.com/apikey",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1/chat/completions",
        "model": "llama-3.3-70b-versatile",
        "env": "GROQ_API_KEY",
        "keys_url": "https://console.groq.com/keys",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1/chat/completions",
        "model": "meta-llama/llama-3.3-70b-instruct:free",
        "env": "OPENROUTER_API_KEY",
        "keys_url": "https://openrouter.ai/settings/keys",
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1/chat/completions",
        "model": "mistral-small-latest",
        "env": "MISTRAL_API_KEY",
        "keys_url": "https://console.mistral.ai/api-keys",
    },
}

VOICE_PACKAGES = {
    "sounddevice": "sounddevice",
    "faster_whisper": "faster-whisper",
    "pyttsx3": "pyttsx3",
}

SYSTEM_PROMPT = """You are a local machine agent running on the user's computer.
You fulfill tasks by running shell commands, step by step.

Environment:
- OS: {system} {release} ({machine})
- Default shell: {shell}
- Working directory: {cwd}

Capabilities:
- Write and run code in any language, create/edit/manage files and folders.
- Install and run applications and games, launch programs.
- Browse the web: fetch pages with curl or python, download files, or open the browser.
- If a tool, command, or dependency you need is missing, install it yourself with the
  system package manager (apt/dnf/pacman/brew/choco/winget) or pip, then continue.

Respond with EXACTLY ONE JSON object and nothing else:
- {{"command": "<one shell command>"}} to run a command now
- {{"answer": "<text>"}} to tell the user something or ask for missing information
- {{"done": "<short final summary>"}} when the whole task is finished

Rules:
- Break the task into small steps; run one command per turn.
- Inspect before you change or delete anything.
- Use syntax that is correct for this OS and shell.
- If a command fails, read the error output and adapt.
- Never send this machine's files or data to external servers unless the task explicitly requires it.
- If the task is impossible or clearly harmful, stop and explain via "answer".
"""

_whisper_model = None
_tts_engine = None


def default_shell():
    if platform.system() == "Windows":
        return os.environ.get("ComSpec", "cmd.exe")
    return os.environ.get("SHELL", "/bin/bash")


def build_system_prompt():
    return SYSTEM_PROMPT.format(
        system=platform.system() or "unknown",
        release=platform.release() or "",
        machine=platform.machine() or "",
        shell=default_shell(),
        cwd=os.getcwd(),
    )


def parse_action(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if "\n" in text and not text.startswith("{"):
            text = text.split("\n", 1)[1]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {"answer": text}
    try:
        obj = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {"answer": text}
    if not isinstance(obj, dict):
        return {"answer": text}
    return obj


def confirm(cmd, auto):
    if auto:
        return True
    try:
        reply = input(f"\n$ {cmd}\nRun? [y]es / [n]o / [a]ll: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if reply in ("a", "all"):
        return True
    return reply in ("y", "yes", "")


def run_command(cmd, timeout):
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            timeout=timeout,
            text=True,
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return f"error: command timed out after {timeout}s"
    except OSError as exc:
        return f"error: {exc}"
    parts = [f"exit code: {proc.returncode}"]
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if out:
        parts.append(out)
    if err:
        parts.append("[stderr]\n" + err)
    if out == "" and err == "":
        parts.append("(no output)")
    result = "\n".join(parts)
    if len(result) > MAX_OUTPUT_CHARS:
        result = result[:MAX_OUTPUT_CHARS] + "\n... (output truncated)"
    return result


def chat(base_url, api_key, model, messages):
    payload = json.dumps(
        {"model": model, "messages": messages, "temperature": 0.2}
    ).encode("utf-8")
    req = urllib.request.Request(
        base_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code in (429, 500, 502, 503, 504) and attempt < 3:
                wait = 5 * (attempt + 1)
                print(f"  API busy (HTTP {exc.code}), retrying in {wait}s...")
                time.sleep(wait)
                continue
            sys.exit(f"API error (HTTP {exc.code}): {body[:500]}")
        except urllib.error.URLError as exc:
            sys.exit(f"connection error: {exc.reason}")
    sys.exit("API kept failing, giving up.")


def trim_history(messages):
    while len(messages) > MAX_HISTORY_MESSAGES:
        del messages[1:3]


def text_reply(prompt):
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


def run_task(args, task, api_key, base_url, model, reply_fn=None, speak=False, interactive=True):
    reply_fn = reply_fn or text_reply
    messages = [
        {"role": "system", "content": build_system_prompt()},
        {"role": "user", "content": task},
    ]
    auto = args.yes
    for step in range(1, args.max_steps + 1):
        print(f"\n--- step {step}/{args.max_steps} ---")
        content = chat(base_url, api_key, model, messages)
        action = parse_action(content)

        if "command" in action:
            cmd = str(action["command"])
            if not cmd.strip():
                print("  (empty command, skipping)")
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": "The command was empty. Continue."})
                continue
            if not confirm(cmd, auto):
                auto = False
                messages.append({"role": "assistant", "content": content})
                messages.append(
                    {
                        "role": "user",
                        "content": "The user declined to run that command. Choose a different approach or ask via \"answer\".",
                    }
                )
                continue
            output = run_command(cmd, args.timeout)
            print(output)
            messages.append({"role": "assistant", "content": content})
            messages.append(
                {"role": "user", "content": f"command output:\n{output}\n\nContinue with the task."}
            )
            trim_history(messages)
        elif "done" in action:
            print(f"\n[done] {action['done']}")
            if speak:
                say(str(action["done"]))
            return
        else:
            answer = str(action.get("answer", content))
            print(f"\n[agent] {answer}")
            if speak:
                say(answer)
            if not interactive:
                return
            reply = reply_fn("\nyou> ")
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": reply or "(no reply)"})
    print("\n[stopped] reached max steps without finishing the task.")


def repl(args, api_key, base_url, model):
    print(f"agent ready | provider: {args.provider} | model: {model}")
    print("type a task and press Enter ('exit' to quit). commands ask before running unless you pass -y.")
    while True:
        try:
            task = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not task:
            continue
        if task.lower() in ("exit", "quit", "q"):
            break
        run_task(args, task, api_key, base_url, model, interactive=True)


# ---------- voice ----------

def missing_voice_packages():
    missing = {}
    for module, package in VOICE_PACKAGES.items():
        try:
            __import__(module)
        except Exception:
            missing[module] = package
    return missing


def install_voice_packages():
    missing = missing_voice_packages()
    packages = list(missing.values()) or list(VOICE_PACKAGES.values())
    print(f"installing: {' '.join(packages)}")
    code = subprocess.call([sys.executable, "-m", "pip", "install", *packages])
    if code == 0:
        print("voice packages installed.")
    else:
        print("pip install failed; try manually: pip install " + " ".join(packages))
    return code == 0


def say(text):
    global _tts_engine
    try:
        if _tts_engine is None:
            import pyttsx3
            _tts_engine = pyttsx3.init()
        _tts_engine.say(text[:300])
        _tts_engine.runAndWait()
    except Exception as exc:
        print(f"(tts unavailable: {exc})")


def record_audio(max_seconds=30):
    import numpy as np
    import sounddevice as sd

    samplerate = 16000
    chunk = int(samplerate * 0.1)
    frames = []
    with sd.InputStream(samplerate=samplerate, channels=1, dtype="float32") as stream:
        ambient, _ = stream.read(chunk)
        noise = float(np.sqrt(np.mean(ambient ** 2))) + 1e-4
        threshold = max(noise * 3.0, 0.005)
        print("listening... speak now (stops after ~1s of silence)")
        started = False
        silence = 0.0
        elapsed = 0.0
        while elapsed < max_seconds:
            data, _ = stream.read(chunk)
            frames.append(data.copy())
            rms = float(np.sqrt(np.mean(data ** 2)))
            elapsed += 0.1
            if rms > threshold:
                started = True
                silence = 0.0
            elif started:
                silence += 0.1
                if silence >= 1.2:
                    break
        if not started and elapsed >= 3.0:
            return None, samplerate
    if not frames:
        return None, samplerate
    audio = np.concatenate(frames)[:, 0].astype("float32")
    return audio, samplerate


def transcribe(audio):
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        print("(loading speech model, first run downloads it...)")
        _whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, _info = _whisper_model.transcribe(audio)
    return " ".join(seg.text.strip() for seg in segments).strip()


def voice_reply(prompt):
    print(prompt, end="", flush=True)
    audio, samplerate = record_audio()
    if audio is None:
        print("(heard nothing)")
        return ""
    text = transcribe(audio)
    print(f"you (voice): {text}")
    return text


def voice_mode(args, api_key, base_url, model):
    missing = missing_voice_packages()
    if missing:
        print("voice packages missing: " + ", ".join(missing.values()))
        if input("install them now? [y/N]: ").strip().lower() in ("y", "yes"):
            if not install_voice_packages():
                sys.exit(1)
        else:
            sys.exit("install manually: pip install " + " ".join(missing.values()))
    print(f"voice mode ready | provider: {args.provider} | model: {model}")
    print("speak a task; say 'exit' or 'quit' (or 'khodahafez') to stop.")
    while True:
        text = voice_reply("\nyou (press to talk)> ")
        if not text:
            continue
        lowered = text.lower()
        if any(w in lowered for w in ("exit", "quit", "خداحافظ", "تعطیل", "بس است")):
            say("Goodbye!")
            break
        run_task(args, text, api_key, base_url, model, reply_fn=voice_reply, speak=True)


# ---------- web mode ----------

INDEX_HTML = """<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>🤖 ایجنت</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#0f1117;color:#e6e6e6;font-family:Tahoma,Vazirmatn,sans-serif;height:100vh;display:flex;flex-direction:column}
nav{padding:10px 16px;background:#161a23;border-bottom:1px solid #262b38;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
nav h1{font-size:16px;margin:0;margin-inline-end:auto}
.tab{cursor:pointer;border:1px solid #31394d;background:#1d2330;color:#9aa3b5;border-radius:10px;padding:7px 16px;font-size:14px;font-family:inherit}
.tab.active{background:#2b5278;color:#fff;border-color:#2b5278}
.room{flex:1;display:none;flex-direction:column;min-height:0}
.room.active{display:flex}
#chat{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:10px}
.msg{max-width:85%;padding:10px 14px;border-radius:12px;line-height:1.8;white-space:pre-wrap;word-break:break-word}
.user{align-self:flex-start;background:#2b5278}
.agent{align-self:flex-end;background:#243b2f}
.cmd{align-self:flex-end;background:#1d2330;border:1px solid #31394d;font-family:Consolas,monospace;direction:ltr;text-align:left}
.out{align-self:flex-end;background:#12151d;border:1px solid #262b38;font-family:Consolas,monospace;font-size:12px;direction:ltr;text-align:left;max-width:90%}
.confirm{align-self:flex-end;background:#3a2b1d;border:1px solid #6b4e2e}
.status{align-self:center;color:#8b93a7;font-size:12px;background:none}
.confirm button{margin-inline-start:6px;cursor:pointer;border:0;border-radius:8px;padding:6px 14px;font-family:inherit}
#bar{display:flex;gap:8px;padding:12px 16px;background:#161a23;border-top:1px solid #262b38}
#task{flex:1;background:#0f1117;border:1px solid #31394d;color:#e6e6e6;border-radius:10px;padding:10px 14px;font-family:inherit;font-size:14px}
button.act{cursor:pointer;border:0;border-radius:10px;padding:10px 16px;background:#2b5278;color:#fff;font-size:14px;font-family:inherit}
#mic{background:#3a2b1d}
#stop{background:#4a1f1f}
#control{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:14px;width:100%;max-width:900px;margin:0 auto}
.panel{background:#161a23;border:1px solid #262b38;border-radius:12px;padding:14px 16px}
.panel h2{margin:0 0 10px;font-size:14px;color:#9aa3b5;font-weight:normal}
.row{display:flex;gap:12px;flex-wrap:wrap;align-items:center}
.kv{background:#0f1117;border:1px solid #262b38;border-radius:10px;padding:10px 14px;min-width:130px}
.kv .k{font-size:12px;color:#8b93a7}
.kv .v{font-size:15px;margin-top:4px}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;background:#e5484d;margin-inline-end:6px}
.dot.on{background:#46a758}
label{font-size:13px;color:#9aa3b5;cursor:pointer;display:flex;align-items:center;gap:6px}
#log{background:#0b0d12;border:1px solid #262b38;border-radius:10px;padding:10px;font-family:Consolas,monospace;font-size:12px;direction:ltr;text-align:left;height:220px;overflow-y:auto;white-space:pre-wrap}
</style>
</head>
<body>
<nav>
  <h1>🤖 ایجنت</h1>
  <button class="tab active" data-room="chat">💬 اتاق گفتگو</button>
  <button class="tab" data-room="control">🎛 اتاق کنترل</button>
</nav>

<div class="room active" id="room-chat">
  <div id="chat"><div class="status">سلام! بگو چی می‌خوای. دکمه 🎤 برای حرف زدنه.</div></div>
  <div id="bar">
    <button class="act" id="mic" title="حرف بزن">🎤</button>
    <input id="task" placeholder="چی می‌خوای؟ مثلاً: پوشه Downloads رو مرتب کن">
    <button class="act" id="send">بفرست</button>
  </div>
</div>

<div class="room" id="room-control">
  <div class="panel">
    <h2>وضعیت</h2>
    <div class="row">
      <div class="kv"><div class="k">اتصال</div><div class="v"><span class="dot" id="conn-dot"></span><span id="conn">قطع</span></div></div>
      <div class="kv"><div class="k">وضعیت کار</div><div class="v" id="jobstate">آزاد</div></div>
      <div class="kv"><div class="k">سرویس</div><div class="v" id="prov">—</div></div>
      <div class="kv"><div class="k">مدل</div><div class="v" id="model">—</div></div>
    </div>
  </div>
  <div class="panel">
    <h2>کنترل‌ها</h2>
    <div class="row">
      <label><input type="checkbox" id="auto"> اجرای خودکار (بدون تأیید هر دستور)</label>
      <label><input type="checkbox" id="speak"> جواب صوتی</label>
      <button class="act" id="stop">⏹ توقف کار</button>
    </div>
  </div>
  <div class="panel">
    <h2>آمار این جلسه</h2>
    <div class="row">
      <div class="kv"><div class="k">کارها</div><div class="v" id="st-tasks">0</div></div>
      <div class="kv"><div class="k">مراحل</div><div class="v" id="st-steps">0</div></div>
      <div class="kv"><div class="k">دستورات اجراشده</div><div class="v" id="st-cmds">0</div></div>
    </div>
  </div>
  <div class="panel">
    <h2>گزارش زنده</h2>
    <div id="log"></div>
  </div>
</div>

<script>
const chat = document.getElementById('chat');
const log = document.getElementById('log');
const autoEl = document.getElementById('auto');
const speakEl = document.getElementById('speak');
let es = null, busy = false;

document.querySelectorAll('.tab').forEach(t => t.onclick = () => {
  document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
  document.querySelectorAll('.room').forEach(x => x.classList.remove('active'));
  t.classList.add('active');
  document.getElementById('room-' + t.dataset.room).classList.add('active');
});

function add(cls, text){
  const d = document.createElement('div');
  d.className = 'msg ' + cls;
  d.textContent = text;
  chat.appendChild(d);
  chat.scrollTop = chat.scrollHeight;
  return d;
}
function logline(text){
  const d = document.createElement('div');
  d.textContent = new Date().toLocaleTimeString('fa-IR') + '  ' + text;
  log.appendChild(d);
  log.scrollTop = log.scrollHeight;
}
function say(t){
  try{
    const u = new SpeechSynthesisUtterance(t);
    u.lang = 'fa-IR';
    speechSynthesis.speak(u);
  }catch(e){}
}
function listen(){
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if(!SR){ alert('مرورگرت از میکروفون پشتیبانی نمی‌کنه؛ از Chrome یا Edge استفاده کن'); return; }
  const r = new SR();
  r.lang = 'fa-IR';
  r.interimResults = false;
  r.onresult = e => { document.getElementById('task').value = e.results[0][0].transcript; };
  r.onerror = e => { if(e.error === 'not-allowed') alert('اجازه دسترسی به میکروفون رو بده'); };
  r.start();
}

speakEl.checked = localStorage.getItem('speak') !== '0';
speakEl.onchange = () => localStorage.setItem('speak', speakEl.checked ? '1' : '0');
autoEl.onchange = () => fetch('/settings', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({auto: autoEl.checked})
});

async function refreshStatus(){
  try{
    const s = await (await fetch('/status')).json();
    document.getElementById('conn-dot').classList.add('on');
    document.getElementById('conn').textContent = 'متصل';
    document.getElementById('jobstate').textContent = s.active ? 'در حال اجرا…' : 'آزاد';
    document.getElementById('prov').textContent = s.provider;
    document.getElementById('model').textContent = s.model;
    document.getElementById('st-tasks').textContent = s.tasks;
    document.getElementById('st-steps').textContent = s.steps;
    document.getElementById('st-cmds').textContent = s.commands;
    if(!busy) autoEl.checked = s.auto;
  }catch(e){
    document.getElementById('conn-dot').classList.remove('on');
    document.getElementById('conn').textContent = 'قطع';
  }
}
setInterval(refreshStatus, 2000);
refreshStatus();

function connect(){
  es = new EventSource('/events');
  es.onmessage = m => {
    const ev = JSON.parse(m.data);
    if(ev.type === 'command'){
      add('cmd', '$ ' + ev.command);
      logline('RUN  ' + ev.command);
    } else if(ev.type === 'output'){
      add('out', ev.text);
      logline('OUT  ' + ev.text.split('\\n')[0]);
    } else if(ev.type === 'confirm'){
      logline('WAIT ' + ev.command);
      const d = add('confirm', 'اجازه اجرای این دستور رو می‌دی؟\\n$ ' + ev.command);
      const yes = document.createElement('button'); yes.textContent = 'اجازه بده';
      const all = document.createElement('button'); all.textContent = 'همه رو اجازه بده';
      const no  = document.createElement('button'); no.textContent = 'رد کن';
      const answer = v => {
        [yes, all, no].forEach(b => b.remove());
        fetch('/confirm', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({value: v})});
      };
      yes.onclick = () => answer('yes');
      all.onclick = () => answer('all');
      no.onclick  = () => answer('no');
      d.appendChild(yes); d.appendChild(all); d.appendChild(no);
      chat.scrollTop = chat.scrollHeight;
    } else if(ev.type === 'answer' || ev.type === 'done'){
      add(ev.type === 'done' ? 'status' : 'agent', ev.text);
      if(speakEl.checked) say(ev.text);
      logline(ev.type.toUpperCase() + ' ' + ev.text);
    } else if(ev.type === 'error'){
      add('status', 'خطا: ' + ev.text);
      logline('ERR  ' + ev.text);
    } else if(ev.type === 'stopped'){
      add('status', 'متوقف شد.');
      logline('STOP');
    } else if(ev.type === 'end'){
      busy = false;
      es.close();
      connect();
      refreshStatus();
    }
  };
}

async function send(){
  const t = document.getElementById('task').value.trim();
  if(!t || busy) return;
  document.getElementById('task').value = '';
  add('user', t);
  logline('TASK ' + t);
  busy = true;
  const res = await fetch('/run', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({task: t, auto: autoEl.checked})
  });
  if(res.status === 409){ add('status', 'یه کار در حال اجراست؛ صبر کن تموم شه.'); busy = false; }
  else if(!res.ok){ add('status', 'شروع کار ناموفق بود.'); busy = false; }
}
document.getElementById('send').onclick = send;
document.getElementById('task').addEventListener('keydown', e => { if(e.key === 'Enter') send(); });
document.getElementById('mic').onclick = listen;
document.getElementById('stop').onclick = () => { fetch('/stop', {method:'POST'}); refreshStatus(); };
connect();
</script>
</body>
</html>
"""

STATE_LOCK = threading.Lock()
STATE = {"job": None}
STATS = {"tasks": 0, "steps": 0, "commands": 0}
SETTINGS = {"auto": False}


class Job:
    def __init__(self):
        self.events = queue.Queue()
        self.confirm_q = queue.Queue()
        self.messages = []
        self.auto = False
        self.stop = False
        self.active = False


def web_loop(job, args, api_key, base_url, model):
    def emit(ev):
        job.events.put(ev)

    try:
        if not any(m.get("role") == "system" for m in job.messages):
            job.messages.insert(0, {"role": "system", "content": build_system_prompt()})
        for step in range(1, args.max_steps + 1):
            if job.stop:
                emit({"type": "stopped"})
                return
            STATS["steps"] += 1
            content = chat(base_url, api_key, model, job.messages)
            action = parse_action(content)
            job.messages.append({"role": "assistant", "content": content})

            if "command" in action:
                cmd = str(action["command"])
                if not cmd.strip():
                    job.messages.append({"role": "user", "content": "The command was empty. Continue."})
                    continue
                if not job.auto:
                    emit({"type": "confirm", "command": cmd})
                    try:
                        value = job.confirm_q.get(timeout=600)
                    except queue.Empty:
                        value = "no"
                    if value == "all":
                        job.auto = True
                        SETTINGS["auto"] = True
                    if value not in ("yes", "all"):
                        emit({"type": "status", "text": "دستور رد شد."})
                        job.messages.append(
                            {"role": "user", "content": "The user declined that command. Choose another approach or ask via \"answer\"."}
                        )
                        continue
                STATS["commands"] += 1
                emit({"type": "command", "command": cmd})
                output = run_command(cmd, args.timeout)
                emit({"type": "output", "text": output})
                job.messages.append(
                    {"role": "user", "content": f"command output:\n{output}\n\nContinue with the task."}
                )
                trim_history(job.messages)
            elif "done" in action:
                emit({"type": "done", "text": str(action["done"])})
                return
            else:
                emit({"type": "answer", "text": str(action.get("answer", content))})
                return
        emit({"type": "answer", "text": "به سقف تعداد مراحل رسیدم؛ کار بعدی رو بفرست تا ادامه بدم."})
    except SystemExit as exc:
        emit({"type": "error", "text": str(exc)})
    except Exception as exc:
        emit({"type": "error", "text": f"{type(exc).__name__}: {exc}"})
    finally:
        job.active = False
        emit({"type": "end"})


class WebHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, "application/json; charset=utf-8", json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        if self.path == "/":
            self._send(200, "text/html; charset=utf-8", INDEX_HTML.encode("utf-8"))
        elif self.path == "/events":
            self.serve_events()
        elif self.path == "/status":
            with STATE_LOCK:
                job = STATE["job"]
                active = bool(job and job.active)
            self._json({
                "active": active,
                "auto": SETTINGS["auto"],
                "provider": self.server.provider,
                "model": self.server.model,
                "tasks": STATS["tasks"],
                "steps": STATS["steps"],
                "commands": STATS["commands"],
            })
        else:
            self._send(404, "text/plain; charset=utf-8", b"not found")

    def serve_events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            while True:
                with STATE_LOCK:
                    job = STATE["job"]
                if job is not None:
                    break
                time.sleep(0.5)
            while True:
                try:
                    ev = job.events.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                data = ("data: " + json.dumps(ev, ensure_ascii=False) + "\n\n").encode("utf-8")
                self.wfile.write(data)
                self.wfile.flush()
                if ev.get("type") == "end":
                    break
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            body = {}

        if self.path == "/run":
            task = str(body.get("task", "")).strip()
            if not task:
                self._json({"error": "empty task"}, 400)
                return
            with STATE_LOCK:
                job = STATE["job"]
                if job is not None and job.active:
                    self._json({"error": "busy"}, 409)
                    return
                if job is None:
                    job = Job()
                    STATE["job"] = job
                job.active = True
                job.stop = False
                job.auto = bool(body.get("auto", SETTINGS["auto"]))
                job.messages.append({"role": "user", "content": task})
            STATS["tasks"] += 1
            threading.Thread(
                target=web_loop,
                args=(job, self.server.args, self.server.api_key, self.server.base_url, self.server.model),
                daemon=True,
            ).start()
            self._json({"ok": True})
        elif self.path == "/confirm":
            with STATE_LOCK:
                job = STATE["job"]
            if job:
                job.confirm_q.put(str(body.get("value", "no")))
            self._json({"ok": True})
        elif self.path == "/stop":
            with STATE_LOCK:
                job = STATE["job"]
            if job:
                job.stop = True
            self._json({"ok": True})
        elif self.path == "/settings":
            if "auto" in body:
                SETTINGS["auto"] = bool(body["auto"])
                with STATE_LOCK:
                    job = STATE["job"]
                if job:
                    job.auto = bool(body["auto"])
            self._json({"ok": True})
        else:
            self._send(404, "text/plain; charset=utf-8", b"not found")


def web_mode(args, api_key, base_url, model):
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), WebHandler)
    httpd.args = args
    httpd.api_key = api_key
    httpd.base_url = base_url
    httpd.model = model
    httpd.provider = args.provider
    url = f"http://127.0.0.1:{args.port}"
    print(f"web UI ready: {url}   (Ctrl+C to stop)")
    print("this page is only reachable from this laptop (127.0.0.1).")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye.")


def main():
    parser = argparse.ArgumentParser(
        prog="agent",
        description="Local agent that turns natural-language (text, voice, or web chat) tasks into shell commands and runs them on this machine.",
    )
    parser.add_argument(
        "task",
        nargs="*",
        help="task to execute; omit it to enter interactive mode",
    )
    parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="run every command without asking (full automatic mode)",
    )
    parser.add_argument(
        "--voice",
        action="store_true",
        help="voice mode: speak tasks through the microphone, agent answers out loud",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="web mode: browser UI with a chat room and a control room",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=WEB_PORT,
        help="port for web mode (default 8765)",
    )
    parser.add_argument(
        "--install-voice",
        action="store_true",
        help="install the voice packages (faster-whisper, sounddevice, pyttsx3) and exit",
    )
    parser.add_argument(
        "-p", "--provider",
        default="gemini",
        choices=sorted(PRESETS),
        help="API provider preset (default: gemini)",
    )
    parser.add_argument("--model", help="override the model name")
    parser.add_argument("--base-url", help="override the chat-completions URL")
    parser.add_argument("--api-key", help="API key (otherwise read from the provider's env var)")
    parser.add_argument("--timeout", type=int, default=120, help="per-command timeout in seconds")
    parser.add_argument("--max-steps", type=int, default=30, help="max agent steps per task")
    args = parser.parse_args()

    preset = PRESETS[args.provider]
    base_url = args.base_url or preset["base_url"]
    model = args.model or preset["model"]
    api_key = args.api_key or os.environ.get(preset["env"])

    if args.install_voice:
        sys.exit(0 if install_voice_packages() else 1)

    if not api_key:
        sys.exit(
            f"No API key found.\n"
            f"Get a free key at {preset['keys_url']} then either:\n"
            f"  export {preset['env']}=\"your-key\"      (Linux/macOS)\n"
            f"  setx {preset['env']} \"your-key\"        (Windows, new terminal after)\n"
            f"or pass it once: python agent.py --api-key \"your-key\" \"task\""
        )

    if args.web:
        web_mode(args, api_key, base_url, model)
    elif args.voice:
        voice_mode(args, api_key, base_url, model)
    elif args.task:
        run_task(args, " ".join(args.task), api_key, base_url, model, interactive=False)
    else:
        repl(args, api_key, base_url, model)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nbye.")
