/**
 * J.A.R.V.I.S. Right-Side Circular HUD, Visualizer (RING / CUBE / FACE),
 * Brain Switcher (Opus 5.5 <-> Fable 5.2), British Butler TTS, and Web Speech STT.
 */

import { tts } from "./api.js";

export class JarvisHUD {
  constructor(callbacks = {}) {
    this.callbacks = callbacks;
    this.canvas = document.getElementById("jarvis-hud-canvas");
    this.ctx = this.canvas.getContext("2d");

    this.brain = "opus-5.5"; // starts on Opus 5.5 just like 01:00 in the video!
    this.status = "online"; // online | listening | thinking | working | speaking | driving
    this.visMode = "ring"; // ring | cube | face
    this.voiceEnabled = true;
    this.voiceLevel = 0;
    this.phase = 0;

    this.selectedVoice = null;
    this.recognition = null;
    this.isListening = false;
    this.subtitleTimer = null;

    this._initVoices();
    this._initSpeechRecognition();
    this._bindUI();
  }

  _initVoices() {
    if (!("speechSynthesis" in window)) return;
    const pickVoice = () => {
      const voices = window.speechSynthesis.getVoices();
      if (!voices.length) return;
      // Prefer macOS British Butler "Daniel" or UK Male voice
      this.selectedVoice =
        voices.find((v) => /Daniel/i.test(v.name) && /en[-_]GB/i.test(v.lang)) ||
        voices.find((v) => /Daniel/i.test(v.name)) ||
        voices.find((v) => /Arthur|Oliver|Google UK English Male/i.test(v.name)) ||
        voices.find((v) => /en[-_]GB/i.test(v.lang)) ||
        voices.find((v) => /en/i.test(v.lang)) ||
        voices[0];
    };
    pickVoice();
    window.speechSynthesis.onvoiceschanged = pickVoice;
  }

  _initSpeechRecognition() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) return;
    const rec = new SR();
    rec.lang = "en-US";
    rec.interimResults = true;
    rec.continuous = false;

    const hearingEl = document.getElementById("jarvis-live-hearing");
    const micBtn = document.getElementById("dock-mic-btn");

    rec.onstart = () => {
      this.isListening = true;
      this.setStatus("listening");
      micBtn.classList.add("mic-listening");
      hearingEl.textContent = "● listening...";
      hearingEl.classList.remove("hidden");
    };

    rec.onresult = (event) => {
      let transcript = "";
      let isFinal = false;
      for (let i = event.resultIndex; i < event.results.length; i++) {
        transcript += event.results[i][0].transcript;
        if (event.results[i].isFinal) isFinal = true;
      }
      this.voiceLevel = 0.65;
      hearingEl.textContent = `● "${transcript.trim()}"`;
      if (isFinal && transcript.trim()) {
        if (this.callbacks.onCommand) {
          this.callbacks.onCommand(transcript.trim());
        }
      }
    };

    rec.onerror = () => {
      this.isListening = false;
      micBtn.classList.remove("mic-listening");
      hearingEl.classList.add("hidden");
      if (this.status === "listening") this.setStatus("online");
    };

    rec.onend = () => {
      this.isListening = false;
      micBtn.classList.remove("mic-listening");
      setTimeout(() => hearingEl.classList.add("hidden"), 900);
      if (this.status === "listening") this.setStatus("online");
    };

    this.recognition = rec;
  }

  toggleListening() {
    if (!this.recognition) {
      this.showSubtitle("Browser speech recognition requires Chrome/Safari — type any command below, sir.");
      document.getElementById("jarvis-prompt-input")?.focus();
      return;
    }
    if (this.isListening) {
      this.recognition.stop();
    } else {
      if ("speechSynthesis" in window) window.speechSynthesis.cancel();
      try {
        this.recognition.start();
      } catch (_) {}
    }
  }

  setBrain(brainId, announce = false) {
    this.brain = brainId;
    document.body.dataset.brain = brainId;
    const label = brainId === "fable-5.2" ? "FABLE 5.2" : "OPUS 5.5";
    document.getElementById("brain-label-text").textContent = label;
    const wsModel = document.getElementById("workshop-model-name");
    if (wsModel) {
      wsModel.textContent = brainId === "fable-5.2" ? "Claude Fable 5.2" : "Claude Opus 5.5";
    }

    document.querySelectorAll(".brain-option").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.brain === brainId);
    });

    if (announce) {
      if (brainId === "fable-5.2") {
        this.speak("Claude Fable 5.2 online, sir. A step above Opus, they say. I feel taller.");
      } else {
        this.speak("Switched back to Claude Opus 5.5, sir. Fast operations standing by.");
      }
    }
  }

  setStatus(status) {
    this.status = status;
    const pill = document.getElementById("jarvis-status-pill");
    const text = document.getElementById("jarvis-status-text");
    pill.className = `hud-pill status-${status}`;
    text.textContent = status.toUpperCase();
  }

  logReflex(entry) {
    const list = document.getElementById("reflex-log-list");
    if (!list) return;
    const div = document.createElement("div");
    div.className = "reflex-item";
    const stamp = new Date().toLocaleTimeString([], { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
    div.textContent = `[${stamp}] ${entry}`;
    list.prepend(div);
    while (list.children.length > 24) list.lastChild.remove();
  }

  showSubtitle(text, durationMs = 6500) {
    const toast = document.getElementById("jarvis-subtitle-toast");
    if (!toast) return;
    toast.textContent = text;
    toast.classList.remove("hidden");
    clearTimeout(this.subtitleTimer);
    this.subtitleTimer = setTimeout(() => {
      toast.classList.add("hidden");
    }, durationMs);
  }

  async speak(text) {
    if (!text) return;
    this.showSubtitle(text, Math.max(5500, text.length * 68));
    this.logReflex(`JARVIS: "${text}"`);

    if (!this.voiceEnabled) {
      this.setStatus("online");
      return;
    }

    this.setStatus("speaking");

    // 1. Try optional ElevenLabs server endpoint first
    try {
      const res = await tts(text);
      if (res) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        const pulseTimer = setInterval(() => {
          this.voiceLevel = 0.35 + Math.random() * 0.55;
        }, 75);
        audio.onended = () => {
          clearInterval(pulseTimer);
          this.voiceLevel = 0;
          URL.revokeObjectURL(url);
          if (this.status === "speaking") this.setStatus("online");
        };
        await audio.play();
        return;
      }
    } catch (_) {
      // Fallback to Web Speech API
    }

    // 2. Built-in Browser SpeechSynthesis (macOS "Daniel" UK Butler Voice)
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
      const utter = new SpeechSynthesisUtterance(text);
      if (this.selectedVoice) utter.voice = this.selectedVoice;
      utter.rate = 1.02;
      utter.pitch = 0.96;

      const pulseTimer = setInterval(() => {
        this.voiceLevel = 0.3 + Math.random() * 0.6;
      }, 80);

      utter.onboundary = () => {
        this.voiceLevel = 0.55 + Math.random() * 0.45;
      };
      utter.onend = () => {
        clearInterval(pulseTimer);
        this.voiceLevel = 0;
        if (this.status === "speaking") this.setStatus("online");
      };
      utter.onerror = () => {
        clearInterval(pulseTimer);
        this.voiceLevel = 0;
        if (this.status === "speaking") this.setStatus("online");
      };

      window.speechSynthesis.speak(utter);
    } else {
      setTimeout(() => {
        if (this.status === "speaking") this.setStatus("online");
      }, 2200);
    }
  }

  _bindUI() {
    document.getElementById("jarvis-ring-container").addEventListener("click", () => {
      this.toggleListening();
    });

    const switcherBtn = document.getElementById("brain-switcher-btn");
    const menu = document.getElementById("brain-dropdown-menu");

    switcherBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      menu.classList.toggle("hidden");
    });

    document.addEventListener("click", () => menu.classList.add("hidden"));

    document.querySelectorAll(".brain-option").forEach((btn) => {
      btn.addEventListener("click", () => {
        this.setBrain(btn.dataset.brain, true);
        menu.classList.add("hidden");
      });
    });

    document.querySelectorAll(".vis-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        this.visMode = btn.dataset.vis;
        document.querySelectorAll(".vis-btn").forEach((b) => b.classList.toggle("active", b === btn));
      });
    });

    // Subsystem toggles
    const eyesBtn = document.getElementById("sys-eyes-btn");
    const eyesBox = document.getElementById("eyes-preview-box");
    const eyesVideo = document.getElementById("eyes-webcam-video");
    let webcamStream = null;

    eyesBtn.addEventListener("click", async () => {
      const turningOn = !eyesBtn.classList.contains("on");
      if (turningOn) {
        try {
          webcamStream = await navigator.mediaDevices.getUserMedia({ video: { width: 320, height: 200 } });
          eyesVideo.srcObject = webcamStream;
          eyesBox.classList.remove("hidden");
          eyesBtn.classList.add("on");
          eyesBtn.querySelector(".sys-val").textContent = "on";
          this.speak("Optical sensor online, sir.");
        } catch (_) {
          eyesBtn.classList.add("on");
          eyesBtn.querySelector(".sys-val").textContent = "sim";
          this.showSubtitle("Optical sensor set to simulated viewport awareness.");
        }
      } else {
        if (webcamStream) webcamStream.getTracks().forEach((t) => t.stop());
        webcamStream = null;
        eyesBox.classList.add("hidden");
        eyesBtn.classList.remove("on");
        eyesBtn.querySelector(".sys-val").textContent = "off";
      }
    });

    const holoBtn = document.getElementById("sys-holo-btn");
    holoBtn.addEventListener("click", () => {
      const on = holoBtn.classList.toggle("on");
      holoBtn.querySelector(".sys-val").textContent = on ? "on" : "off";
      this.visMode = on ? "cube" : "ring";
      document.querySelectorAll(".vis-btn").forEach((b) => b.classList.toggle("active", b.dataset.vis === this.visMode));
    });

    const focusBtn = document.getElementById("sys-focus-btn");
    focusBtn.addEventListener("click", () => {
      const on = focusBtn.classList.toggle("on");
      focusBtn.querySelector(".sys-val").textContent = on ? "on" : "off";
      if (this.callbacks.onToggleFocus) this.callbacks.onToggleFocus(on);
    });

    const reflexBtn = document.getElementById("sys-reflex-btn");
    const reflexDrawer = document.getElementById("reflex-drawer");
    reflexBtn.addEventListener("click", () => {
      const on = reflexBtn.classList.toggle("on");
      reflexBtn.querySelector(".sys-val").textContent = on ? "active" : "hidden";
      reflexDrawer.classList.toggle("hidden", !on);
    });
  }

  tick(dt) {
    this.phase += dt;
    this.voiceLevel = Math.max(0, this.voiceLevel - dt * 1.8);
    if (this.status === "working" || this.status === "thinking" || this.status === "driving") {
      this.voiceLevel = Math.max(this.voiceLevel, 0.25 + 0.2 * Math.sin(this.phase * 7));
    }

    const ctx = this.ctx;
    const W = this.canvas.width;
    const H = this.canvas.height;
    const cx = W / 2;
    const cy = H / 2;
    ctx.clearRect(0, 0, W, H);

    const isFable = this.brain === "fable-5.2";
    const mainColor = this.status === "driving" ? "#eab308" : isFable ? "#a855f7" : "#14b8a6";
    const secColor = this.status === "driving" ? "#22d3ee" : isFable ? "#ec4899" : "#f59e0b";

    // Outer ambient glow
    const grad = ctx.createRadialGradient(cx, cy, 40, cx, cy, 205);
    grad.addColorStop(0, isFable ? "rgba(168, 85, 247, 0.16)" : "rgba(20, 184, 166, 0.15)");
    grad.addColorStop(1, "rgba(0, 0, 0, 0)");
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(cx, cy, 205, 0, Math.PI * 2);
    ctx.fill();

    // Outer mechanical tick ring
    const ticks = 72;
    for (let i = 0; i < ticks; i++) {
      const ang = (i / ticks) * Math.PI * 2 + this.phase * 0.14;
      const wave = Math.sin(ang * 6 + this.phase * 6) * 0.5 + 0.5;
      const len = (i % 6 === 0 ? 15 : 8) + this.voiceLevel * wave * 20;
      const r1 = 166;
      const r2 = r1 + len;

      ctx.strokeStyle = i % 6 === 0 ? secColor : mainColor;
      ctx.globalAlpha = 0.35 + wave * 0.55;
      ctx.lineWidth = i % 6 === 0 ? 2.6 : 1.6;
      ctx.beginPath();
      ctx.moveTo(cx + Math.cos(ang) * r1, cy + Math.sin(ang) * r1);
      ctx.lineTo(cx + Math.cos(ang) * r2, cy + Math.sin(ang) * r2);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;

    // Segmented counter-rotating arcs
    ctx.strokeStyle = mainColor;
    ctx.lineWidth = 3.5;
    for (let s = 0; s < 3; s++) {
      const start = -this.phase * 0.65 + (s * Math.PI * 2) / 3;
      ctx.beginPath();
      ctx.arc(cx, cy, 148, start, start + 1.15);
      ctx.stroke();
    }

    ctx.strokeStyle = secColor;
    ctx.lineWidth = 2.2;
    for (let s = 0; s < 4; s++) {
      const start = this.phase * 0.9 + (s * Math.PI * 2) / 4;
      ctx.beginPath();
      ctx.arc(cx, cy, 132, start, start + 0.65);
      ctx.stroke();
    }

    // Center Visualizer Mode: RING vs CUBE vs FACE
    if (this.visMode === "ring") {
      ctx.strokeStyle = mainColor;
      ctx.lineWidth = 2;
      ctx.beginPath();
      for (let i = 0; i <= 90; i++) {
        const a = (i / 90) * Math.PI * 2;
        const r = 104 + Math.sin(a * 8 + this.phase * 9) * (3 + this.voiceLevel * 18);
        const px = cx + Math.cos(a) * r;
        const py = cy + Math.sin(a) * r;
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.closePath();
      ctx.stroke();
    } else if (this.visMode === "cube") {
      // 3D rotating wireframe holographic cube
      const size = 56 + this.voiceLevel * 16;
      const rx = this.phase * 0.9;
      const ry = this.phase * 1.25;
      const verts = [
        [-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],
        [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1],
      ].map(([x, y, z]) => {
        const y1 = y * Math.cos(rx) - z * Math.sin(rx);
        const z1 = y * Math.sin(rx) + z * Math.cos(rx);
        const x2 = x * Math.cos(ry) + z1 * Math.sin(ry);
        const z2 = -x * Math.sin(ry) + z1 * Math.cos(ry);
        const scale = 220 / (220 + z2 * 40);
        return [cx + x2 * size * scale, cy + y1 * size * scale];
      });
      const cubeEdges = [
        [0,1],[1,2],[2,3],[3,0],[4,5],[5,6],[6,7],[7,4],[0,4],[1,5],[2,6],[3,7]
      ];
      ctx.strokeStyle = mainColor;
      ctx.lineWidth = 2;
      for (const [a, b] of cubeEdges) {
        ctx.beginPath();
        ctx.moveTo(verts[a][0], verts[a][1]);
        ctx.lineTo(verts[b][0], verts[b][1]);
        ctx.stroke();
      }
    } else if (this.visMode === "face") {
      // Stylized holographic vector AI mask
      ctx.strokeStyle = mainColor;
      ctx.lineWidth = 2.2;
      // Cranium contour
      ctx.beginPath();
      ctx.ellipse(cx, cy - 4, 64, 82, 0, 0, Math.PI * 2);
      ctx.stroke();
      // Glowing eyes
      ctx.fillStyle = secColor;
      ctx.fillRect(cx - 34, cy - 26, 20, 6);
      ctx.fillRect(cx + 14, cy - 26, 20, 6);
      // Speaking mouth bars
      const jaw = 4 + this.voiceLevel * 22;
      ctx.strokeRect(cx - 22, cy + 34 - jaw / 2, 44, jaw);
    }
  }
}
