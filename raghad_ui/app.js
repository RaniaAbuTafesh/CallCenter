// Raghad Organics voice client.
// Uses Pipecat's official browser client + SmallWebRTC transport (the same
// stack as the stock /client/ page), so the bot behaves exactly the same.
import { PipecatClient } from "https://esm.sh/@pipecat-ai/client-js@1.16.0";
import { SmallWebRTCTransport } from "https://esm.sh/@pipecat-ai/small-webrtc-transport@1.11.2?deps=@pipecat-ai/client-js@1.16.0";

const OFFER_ENDPOINT = "/api/offer";

const $ = (id) => document.getElementById(id);
const els = {
  status: $("status"),
  statusText: $("status-text"),
  call: $("call"),
  callLabel: $("call-label"),
  mic: $("mic"),
  micLabel: $("mic-label"),
  error: $("error"),
  transcript: $("transcript"),
  empty: $("empty"),
  clear: $("clear"),
  audio: $("bot-audio"),
  dropWrap: $("drop-wrap"),
  canvas: $("drop"),
  voiceState: $("voice-state"),
  timer: $("timer"),
  heroCall: $("hero-call"),
  heroCallLabel: $("hero-call-label"),
  topics: document.querySelectorAll("[data-topic]"),
};

// Short label for the header pill.
const STATUS_TEXT = {
  idle: "غير متصل",
  connecting: "جاري الاتصال",
  ready: "متصل",
  listening: "متصل",
  speaking: "متصل",
  error: "انقطع الاتصال",
};

// Larger line under the drop.
const VOICE_TEXT = {
  idle: 'اضغطي "ابدأ المكالمة" وابدئي الحكي',
  connecting: "لحظة، عم نوصلك بالمساعدة…",
  ready: "تفضّلي، عم بسمعك",
  listening: "عم بسمعك…",
  speaking: "المساعدة بتحكي",
  error: "ما زبط الاتصال، جرّبي كمان مرة",
};

let client = null;
let inCall = false;
let busy = false;
let state = "idle";

// Audio levels feed the drop animation.
const level = { bot: 0, user: 0 };

// ---------------------------------------------------------------- UI state
function setState(next) {
  state = next;
  els.status.dataset.state = next;
  els.statusText.textContent = STATUS_TEXT[next] ?? next;
  els.voiceState.textContent = VOICE_TEXT[next] ?? "";
}

// ---------------------------------------------------------------- Call timer
let timerId = null;
function startTimer() {
  stopTimer();
  const started = Date.now();
  els.timer.hidden = false;
  const tick = () => {
    const s = Math.floor((Date.now() - started) / 1000);
    els.timer.textContent = `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  };
  tick();
  timerId = setInterval(tick, 1000);
}
function stopTimer() {
  clearInterval(timerId);
  timerId = null;
}

function setInCall(on) {
  inCall = on;
  document.body.classList.toggle("in-call", on);
  els.call.setAttribute("aria-pressed", String(on));
  els.callLabel.textContent = on ? "إنهاء المكالمة" : "ابدأ المكالمة";
  els.heroCallLabel.textContent = on ? "إنهاء المكالمة" : "احكي مع المساعدة الآن";
  els.heroCall.classList.toggle("is-live", on);
  els.mic.disabled = !on;
  if (!on) setMicUI(true);
}

function setMicUI(on) {
  els.mic.setAttribute("aria-checked", String(on));
  els.micLabel.textContent = on ? "المايك شغّال" : "المايك مسكّر";
}

function showError(text) {
  els.error.textContent = text;
  els.error.hidden = !text;
}

// ---------------------------------------------------------------- Transcript
let userEl = null; // current user bubble
let botEl = null; // current bot bubble
let interimEl = null; // live (not yet final) user text
const seenSegments = new Set();
let gotUserInput = false;
let gotBotOutput = false;

function addMessage(role, text, extraClass = "") {
  els.empty?.remove();
  const li = document.createElement("li");
  li.className = `msg ${role} ${extraClass}`.trim();
  if (role !== "system") {
    const who = document.createElement("span");
    who.className = "who";
    who.textContent = role === "user" ? "أنتِ" : "مساعدة رغد";
    li.appendChild(who);
  }
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  li.appendChild(bubble);
  els.transcript.appendChild(li);
  scrollDown();
  return li;
}

function appendTo(li, text) {
  const b = li.querySelector(".bubble");
  b.textContent = (b.textContent + " " + text).trim();
  scrollDown();
}

function scrollDown() {
  els.transcript.scrollTop = els.transcript.scrollHeight;
}

function onUserText(text, final) {
  if (!text?.trim()) return;
  botEl = null; // a new bot reply starts after the user speaks
  if (!final) {
    if (!interimEl) interimEl = addMessage("user", text, "interim");
    else interimEl.querySelector(".bubble").textContent = text;
    return;
  }
  interimEl?.remove();
  interimEl = null;
  const last = els.transcript.lastElementChild;
  if (userEl && last === userEl) appendTo(userEl, text);
  else userEl = addMessage("user", text);
}

function onBotText(text) {
  if (!text?.trim()) return;
  userEl = null;
  if (botEl && els.transcript.lastElementChild === botEl) appendTo(botEl, text);
  else botEl = addMessage("bot", text);
}

function resetTranscriptState() {
  userEl = botEl = interimEl = null;
  seenSegments.clear();
}

els.clear.addEventListener("click", () => {
  els.transcript.innerHTML = "";
  resetTranscriptState();
});

// ---------------------------------------------------------------- Microphones
els.mic.addEventListener("click", () => {
  if (!client) return;
  const enable = !client.isMicEnabled;
  client.enableMic(enable);
  setMicUI(enable);
});

// ---------------------------------------------------------------- Call flow
// TURN/STUN servers come from the bot (/raghad-config). On a cloud host like
// Railway there is no UDP, so the call is relayed through a TURN server.
// Locally the list is empty and the browser connects directly, as before.
async function loadIceServers() {
  try {
    const res = await fetch("/raghad-config", { cache: "no-store" });
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data.iceServers) ? data.iceServers : [];
  } catch {
    return [];
  }
}

function buildClient(iceServers) {
  return new PipecatClient({
    transport: new SmallWebRTCTransport(iceServers.length ? { iceServers } : undefined),
    enableMic: true,
    enableCam: false,
    callbacks: {
      onTransportStateChanged: (s) => {
        if (["initializing", "initialized", "connecting", "connected", "authenticating"].includes(s)) {
          if (state === "idle" || state === "error") setState("connecting");
        }
        if (s === "ready") setState("ready");
      },
      onBotReady: () => {
        setState("ready");
        startTimer();
        addMessage("system", "تم الاتصال");
      },
      onDisconnected: () => endCallUI(),
      onTrackStarted: (track, participant) => {
        if (participant?.local || track.kind !== "audio") return;
        els.audio.srcObject = new MediaStream([track]);
        els.audio.play().catch(() => {});
      },

      onUserStartedSpeaking: () => { if (inCall) setState("listening"); },
      onUserStoppedSpeaking: () => { if (inCall && state === "listening") setState("ready"); },
      onBotStartedSpeaking: () => { if (inCall) setState("speaking"); },
      onBotStoppedSpeaking: () => { if (inCall) setState("ready"); },

      onLocalAudioLevel: (l) => { level.user = Math.max(level.user, l); },
      onRemoteAudioLevel: (l) => { level.bot = Math.max(level.bot, l); },

      // What the user said (new API, with a fallback for older servers).
      onUserInput: (d) => {
        gotUserInput = true;
        if (d.input_type === "backchannel") return;
        onUserText(d.text, d.final);
      },
      onUserTranscript: (d) => {
        if (!gotUserInput) onUserText(d.text, d.final);
      },

      // What the bot said: one message per sentence segment.
      onBotOutput: (d) => {
        gotBotOutput = true;
        const kind = d.output_type ?? d.aggregated_by;
        if (kind === "word") return;
        if (d.segment_id != null) {
          if (seenSegments.has(d.segment_id)) return;
          seenSegments.add(d.segment_id);
        }
        onBotText(d.text);
      },
      onBotTranscript: (d) => {
        if (!gotBotOutput) onBotText(d.text);
      },

      onError: (msg) => {
        const text = msg?.data?.message || msg?.data?.error || "";
        showError(text ? `خطأ من البوت: ${text}` : "صار خطأ من البوت. شوفي نافذة PowerShell للتفاصيل.");
      },
    },
  });
}

async function startCall() {
  busy = true;
  showError("");
  resetTranscriptState();
  gotUserInput = gotBotOutput = false;
  setState("connecting");
  els.call.disabled = true;
  els.call.classList.add("is-connecting");
  setInCall(true);

  try {
    client = buildClient(await loadIceServers());
    await client.connect({ webrtcRequestParams: { endpoint: OFFER_ENDPOINT } });
  } catch (err) {
    console.error(err);
    const name = err?.name || "";
    let text = "ما قدرنا نتصل بالبوت. تأكدي إن نافذة PowerShell شغّالة وجرّبي كمان مرة.";
    if (name === "NotAllowedError" || /permission/i.test(String(err))) {
      text = "المتصفح منع الميكروفون. اسمحي للموقع يستخدم الميكروفون من أيقونة القفل جنب العنوان، وبعدين جرّبي كمان مرة.";
    } else if (name === "NotFoundError") {
      text = "ما في ميكروفون موصول بالجهاز. وصّلي ميكروفون وجرّبي كمان مرة.";
    }
    showError(text);
    await safeDisconnect();
    endCallUI("error");
  } finally {
    els.call.disabled = false;
    els.call.classList.remove("is-connecting");
    busy = false;
  }
}

async function safeDisconnect() {
  try { await client?.disconnect(); } catch { /* already closed */ }
  client = null;
}

function endCallUI(nextState = "idle") {
  if (inCall) addMessage("system", "انتهت المكالمة");
  setInCall(false);
  stopTimer();
  setState(nextState);
  els.audio.srcObject = null;
  level.bot = level.user = 0;
}

async function toggleCall() {
  if (busy) return;
  if (inCall) {
    busy = true;
    await safeDisconnect();
    endCallUI();
    busy = false;
  } else {
    await startCall();
  }
}

els.call.addEventListener("click", toggleCall);
els.dropWrap.addEventListener("click", () => { if (!inCall) toggleCall(); });

// Hero button and topic cards: bring the assistant into view, then call.
function goToAssistant() {
  document.getElementById("assistant").scrollIntoView({ block: "start" });
}
els.heroCall.addEventListener("click", () => {
  if (!inCall) goToAssistant();
  toggleCall();
});
els.topics.forEach((card) =>
  card.addEventListener("click", () => {
    goToAssistant();
    if (!inCall) toggleCall();
  })
);
window.addEventListener("beforeunload", () => { client?.disconnect(); });

// ---------------------------------------------------------------- The logo badge
// The Raghad logo on its own. It breathes when idle, ripples with the
// assistant's voice, and gets a leaf-green halo while it is listening to you.
const logoImg = new Image();
logoImg.src = "logo.png";
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const ctx = els.canvas.getContext("2d");
let W = 0, H = 0, DPR = 1;
const smooth = { bot: 0, user: 0, halo: 0, spin: 0 };
const ripples = [];
let lastRipple = 0;

function resize() {
  DPR = Math.min(window.devicePixelRatio || 1, 2);
  const r = els.canvas.getBoundingClientRect();
  W = r.width; H = r.height;
  els.canvas.width = Math.round(W * DPR);
  els.canvas.height = Math.round(H * DPR);
  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
}
new ResizeObserver(resize).observe(els.canvas);
resize();

function frame(now) {
  const t = reduceMotion ? 0 : now / 1000;

  // Ease levels toward their targets, then let the targets decay.
  smooth.bot += (level.bot - smooth.bot) * 0.18;
  smooth.user += (level.user - smooth.user) * 0.18;
  level.bot *= 0.86;
  level.user *= 0.86;
  const listening = state === "listening" || (inCall && smooth.user > 0.08 && state !== "speaking");
  smooth.halo += ((listening ? 1 : 0) - smooth.halo) * 0.08;
  smooth.spin += ((state === "connecting" ? 1 : 0) - smooth.spin) * 0.06;

  ctx.clearRect(0, 0, W, H);
  const cx = W / 2, cy = H / 2 - H * 0.03;
  const base = Math.min(W, H) * 0.3;
  const breathe = reduceMotion ? 0 : Math.sin(t * 1.2) * 0.012;
  const voice = Math.min(smooth.bot * 1.6, 1);
  const r = base * (1 + breathe + voice * 0.04);

  // Voice ripples.
  if (!reduceMotion && state === "speaking" && voice > 0.15 && now - lastRipple > 380) {
    ripples.push({ born: now, strength: voice });
    lastRipple = now;
  }
  for (let i = ripples.length - 1; i >= 0; i--) {
    const p = (now - ripples[i].born) / 1600;
    if (p >= 1) { ripples.splice(i, 1); continue; }
    ctx.beginPath();
    ctx.arc(cx, cy, r * (1.05 + p * 0.55), 0, Math.PI * 2);
    ctx.strokeStyle = `rgba(158,125,102,${(1 - p) * 0.35 * ripples[i].strength})`;
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }

  // Soft glow behind the logo: leaf green while listening,
  // warm caramel while the assistant talks. No shape, just light.
  const glow = (rgb, alpha) => {
    const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, r * 1.5);
    g.addColorStop(0, `rgba(${rgb},${alpha})`);
    g.addColorStop(1, `rgba(${rgb},0)`);
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(cx, cy, r * 1.5, 0, Math.PI * 2);
    ctx.fill();
  };
  if (smooth.halo > 0.01) glow("44,117,66", 0.22 * smooth.halo);
  if (voice > 0.01) glow("214,170,120", 0.3 * voice);

  // The Raghad logo on its own, pulsing gently with the assistant's voice.
  if (logoImg.complete && logoImg.naturalWidth) {
    const lw = r * 2.3 * (1 + voice * 0.06);
    const lh = lw * (logoImg.naturalHeight / logoImg.naturalWidth);
    ctx.drawImage(logoImg, cx - lw / 2, cy - lh / 2 + r * 0.02, lw, lh);
  }

  // Connecting: a caramel arc orbiting the logo.
  if (smooth.spin > 0.02) {
    const a = t * 3;
    ctx.beginPath();
    ctx.arc(cx, cy, r * 1.18, a, a + Math.PI * 0.6);
    ctx.strokeStyle = `rgba(158,125,102,${0.8 * smooth.spin})`;
    ctx.lineWidth = 3;
    ctx.lineCap = "round";
    ctx.stroke();
  }

  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

setState("idle");
