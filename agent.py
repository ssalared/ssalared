#!/usr/bin/env python3
"""Agent: turns natural-language (text or voice) tasks into shell commands and runs them on this machine.

Core needs only Python 3.8+. Voice mode extras: pip install faster-whisper sounddevice pyttsx3
(or run: python agent.py --install-voice)
"""

import argparse
import json
import os
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request

MAX_OUTPUT_CHARS = 6000
MAX_HISTORY_MESSAGES = 60

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
    import numpy as np
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


def main():
    parser = argparse.ArgumentParser(
        prog="agent",
        description="Local agent that turns natural-language (text or voice) tasks into shell commands and runs them on this machine.",
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

    if args.voice:
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
