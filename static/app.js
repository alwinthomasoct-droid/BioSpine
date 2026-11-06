/**
 * BioSpine Master Client Engine (v5)
 * Fully wired: Database Sync, jsPDF Export, Picture-in-Picture, BLE/Serial/WiFi, 3D Spine, AI Copilot
 */

const SERVICE_UUID = "4fafc201-1fb5-459e-8fcc-c5c9c331914b";
const CHAR_UUID    = "beb5483e-36e1-4688-b7f5-ea07361b26a8";
const CMD_UUID     = "7b9e1001-4b8a-4c18-9f21-0c2e8a8c1001";
const DEVICE_NAME  = "BioSpine-Wearable";

const $ = id => document.getElementById(id);
// Small hook table: extras.js (rewards, reviews, breaks, Posture Lab, Excel export) plugs into these moments.
const bsHooks = {};
const hook = (name, ...args) => { try { if (bsHooks[name]) return bsHooks[name](...args); } catch (e) { console.error("[BioSpine] hook " + name + " failed:", e); } };
const cssv = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim() || "#8899b2";   // theme-aware colour for canvas drawing

// Chart palette (Posture trend + Today donut)
const COLORS = {
  primary: "#4f7cff", cyan: "#00d9ff", purple: "#a855f7",
  greenBright: "#34d399", green: "#22c55e",
  red: "#ff3b6b", pink: "#fb7185",
  grid: "rgba(148, 163, 184, 0.16)", gridStrong: "rgba(148, 163, 184, 0.28)"
};
const TREND_WINDOW = 200;   // samples shown on the Posture trend graph

// User & State Management
let currentUser = localStorage.getItem("biospine_active_user") || "";
let userSettings = {
  angle: 18,
  safeZone: 3,
  lateralLimit: 12,
  mode: "focus",
  buzzer: false,
  notify: true,
  sound: true,            // the sound alarm is ON by default
  alarmVolume: 0.8, alarmRepeat: 15, swapAxes: false, syncDemo: false
};
let sessions = [];
let events = [];
let chatHistory = [];                       // AI Physio Q&A log, loaded from the server for the Chats & Doubts tab
let userStreak = { current: 0, longest: 0 };

// Device & Telemetry State
let bleDevice = null, telemetryChar = null, cmdChar = null, serialPort = null, ws = null;
let connected = false, transport = "—";
let historyPitchSigned = [], historyRollSigned = [];
let graphBuffer = Array(100).fill(0);
let sessionStart = null, samples = 0;
let totalCorrect = 0, totalIncorrect = 0, currentGood = 0, longestGood = 0, alertCount = 0;
let isSlouchActive = false, lastTick = Date.now();
let strainDistribution = { forward: 0, backward: 0, left: 0, right: 0 };

// Floating Picture-in-Picture Window Reference
let pipWindow = null;

// ==========================================================
// 1. INITIALIZATION & AUTHENTICATION (real email + password accounts)
// ==========================================================
let authMode = "login"; // "login" | "register"
let sessionToken = localStorage.getItem("biospine_session_token") || "";
let isGuest = false, emailVerified = true, deferredInstall = null;
let serverLoaded = 0, serverTotal = 0;      // how many older sessions the server has / we have fetched

// One place for every call to our own API: adds the sign-in token, parses JSON, handles expiry.
async function api(url, { method = "GET", body, auth = true, quiet401 = false } = {}) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (auth && sessionToken) headers["Authorization"] = "Bearer " + sessionToken;
  const res = await fetch(url, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
  let data = {};
  try { data = await res.json(); } catch (_) { /* non-JSON error page */ }
  if (res.status === 401 && auth && !quiet401 && !isGuest && sessionToken) forceSignedOut();
  return { res, data };
}

function forceSignedOut() {
  currentUser = ""; sessionToken = "";
  localStorage.removeItem("biospine_active_user");
  localStorage.removeItem("biospine_session_token");
  $('appShell').style.display = "none";
  $('landingPage').style.display = "block";
  openAuthModal("login");
  if ($('authError')) $('authError').textContent = "Your session expired. Please sign in again.";
}

function init() {
  $('openAuthModalBtn').onclick = () => openAuthModal("login");
  $('heroGetStartedBtn').onclick = () => openAuthModal("register");
  if ($('heroDemoBtn')) $('heroDemoBtn').onclick = startGuest;
  $('closeAuthModalBtn').onclick = () => $('authModal').style.display = "none";
  $('submitAuthBtn').onclick = handleAuthSubmit;
  $('signOutBtn').onclick = handleSignOut;
  if ($('forgotBtn')) $('forgotBtn').onclick = handleForgot;
  if ($('authModeToggle')) $('authModeToggle').onclick = () => setAuthMode(authMode === "login" ? "register" : "login");
  if ($('authPasswordInput')) $('authPasswordInput').addEventListener("keydown", e => { if (e.key === "Enter") handleAuthSubmit(); });
  if ($('yr')) $('yr').textContent = new Date().getFullYear();
  bindAccountUI();
  registerServiceWorker();
  setupInstallPrompt();

  if (currentUser && sessionToken) {
    restoreSession(currentUser, sessionToken);
  } else {
    currentUser = "";
    localStorage.removeItem("biospine_active_user");
    $('landingPage').style.display = "block";
    $('appShell').style.display = "none";
    try { if (sessionStorage.getItem("bs_open_register")) { sessionStorage.removeItem("bs_open_register"); openAuthModal("register"); } } catch (_) {}
  }
}

function openAuthModal(mode) {
  setAuthMode(mode);
  $('authModal').style.display = "flex";
  if ($('authInfo')) $('authInfo').textContent = "";
}

function setAuthMode(mode) {
  authMode = mode;
  if ($('authModalTitle')) $('authModalTitle').textContent = mode === "register" ? "Create your BioSpine account" : "Sign In to BioSpine";
  if ($('authModalSub')) $('authModalSub').textContent = mode === "register"
    ? "Choose an email and password to save your good-posture setting, your streak, XP and history to your account."
    : "Sign in with your email and password to load your settings, streak, rewards and history.";
  if ($('submitAuthBtn')) $('submitAuthBtn').textContent = mode === "register" ? "Create account" : "Sign In";
  if ($('authModeToggle')) $('authModeToggle').textContent = mode === "register" ? "Already have an account? Sign in" : "New here? Create an account";
  if ($('forgotBtn')) $('forgotBtn').style.display = mode === "register" ? "none" : "block";
  if ($('authPasswordInput')) $('authPasswordInput').autocomplete = mode === "register" ? "new-password" : "current-password";
  if ($('authError')) $('authError').textContent = "";
  if ($('bodyFields')) $('bodyFields').hidden = mode !== "register";
}

async function handleAuthSubmit() {
  const email = ($('authEmailInput').value || "").trim().toLowerCase();
  const password = $('authPasswordInput') ? $('authPasswordInput').value : "";
  const errBox = $('authError');
  if (errBox) errBox.textContent = "";
  if ($('authInfo')) $('authInfo').textContent = "";

  if (!email || !email.includes("@")) { if (errBox) errBox.textContent = "Please enter a valid email address."; return; }
  if (!password || password.length < 8) { if (errBox) errBox.textContent = "Password must be at least 8 characters."; return; }

  const payload = { email, password };
  if (authMode === "register") {
    const h = parseFloat(($('authHeight') || {}).value), w = parseFloat(($('authWeight') || {}).value);
    if (!(h >= 50 && h <= 250)) { if (errBox) errBox.textContent = "Please enter your height in cm (for example 170)."; return; }
    if (!(w >= 15 && w <= 350)) { if (errBox) errBox.textContent = "Please enter your weight in kg (for example 65)."; return; }
    payload.heightCm = h; payload.weightKg = w;
  }

  $('submitAuthBtn').disabled = true;
  try {
    const endpoint = authMode === "register" ? "/api/auth/register" : "/api/auth/login";
    const { res, data } = await api(endpoint, { method: "POST", body: payload, auth: false });
    if (!res.ok || !data.success) {
      if (data.code === "exists") setAuthMode("login");
      if (errBox) errBox.textContent = data.error || "Something went wrong. Please try again.";
      return;
    }
    const justRegistered = authMode === "register";
    applyAuthenticatedUser(email, data.user);
    $('authModal').style.display = "none";
    if (justRegistered && data.user && data.user.body && data.user.body.info) toast(`Your BMI is ${data.user.body.info.bmi} (${data.user.body.info.category})`);
    if (justRegistered) setTimeout(() => toast(data.emailSent ? "Welcome! We sent a confirmation link to your email." : "Welcome! Your account is ready. (The confirmation email could not be sent right now - you can press \"Resend email\" later.)"), 2600);
  } catch (e) {
    if (errBox) errBox.textContent = "Could not reach the server. Check your connection and try again.";
  } finally {
    $('submitAuthBtn').disabled = false;
  }
}

async function handleForgot() {
  const email = ($('authEmailInput').value || "").trim().toLowerCase();
  if (!email || !email.includes("@")) { $('authError').textContent = "Type your email address above first, then press 'Forgot password?'."; return; }
  $('authError').textContent = "";
  try {
    const { data } = await api("/api/auth/forgot", { method: "POST", body: { email }, auth: false });
    if (data.success) $('authInfo').textContent = data.message;
    else $('authError').textContent = data.error || "Could not send the reset email.";
  } catch (_) { $('authError').textContent = "Could not reach the server."; }
}

// Silently restores a signed-in session on page reload using the saved token.
async function restoreSession(email, token) {
  try {
    const { res, data } = await api("/api/auth/session", { method: "POST", body: {}, quiet401: true });
    if (res.ok && data.success) { applyAuthenticatedUser(email, data.user, /*keepToken*/ true); return; }
    if (res.status !== 401) {                               // server hiccup: keep the person working with their saved data
      applyAuthenticatedUser(email, null, true); toast("Server busy - showing the data saved on this device."); return;
    }
  } catch (e) {                                              // offline (e.g. installed app on a train): still usable
    applyAuthenticatedUser(email, null, true); toast("You're offline - showing the data saved on this device."); return;
  }
  currentUser = ""; sessionToken = "";
  localStorage.removeItem("biospine_active_user");
  localStorage.removeItem("biospine_session_token");
  $('landingPage').style.display = "block";
  $('appShell').style.display = "none";
  openAuthModal("login");
}

function applyAuthenticatedUser(email, userData, keepToken) {
  isGuest = false;
  currentUser = email;
  localStorage.setItem("biospine_active_user", email);
  if (!keepToken && userData && userData.token) {
    sessionToken = userData.token;
    localStorage.setItem("biospine_session_token", sessionToken);
  }
  loadUserFromBackend(email, userData);
}

function clearGuestData() {
  try {
    const prefix = `biospine:${STORE_VER}:demo-guest:`;
    Object.keys(localStorage).filter(k => k.startsWith(prefix)).forEach(k => localStorage.removeItem(k));
  } catch (_) {}
}

// Public demo: explore everything with simulated data, nothing is saved or sent to the server.
function startGuest() {
  isGuest = true; currentUser = "demo-guest"; sessionToken = "";
  clearGuestData();
  $('authModal').style.display = "none";
  loadUserFromBackend("demo-guest", null);
  setTimeout(() => { if (!demoTimer) toggleDemo(); }, 700);
}

async function handleSignOut() {
  if (demoTimer) { clearInterval(demoTimer); demoTimer = null; }
  finishSession();
  if (isGuest) clearGuestData();
  else if (sessionToken) { try { await api("/api/auth/logout", { method: "POST", body: {}, quiet401: true }); } catch (_) {} }
  currentUser = ""; sessionToken = "";
  localStorage.removeItem("biospine_active_user");
  localStorage.removeItem("biospine_session_token");
  location.reload();
}

// ==========================================================
// 2. VIEW SWITCHING & UI BINDINGS
// ==========================================================
function showView(viewId) {
  document.querySelectorAll('.view').forEach(v => {
    v.classList.remove('active');
    v.style.display = 'none';
  });
  const target = document.getElementById(viewId);
  if (target) {
    target.classList.add('active');
    target.style.display = 'block';
  }
  document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.view === viewId);
  });
  const title = $('pageTitle');
  if (title) {
    const titles = {
      dashboard: "Dashboard",
      biomechanics: "Posture Lab",
      analytics: "My Progress",
      history: "Session History",
      rewards: "Rewards & Quests",
      breaktime: "Back Break",
      device: "My Device",
      settings: "Settings",
      chats: "Chats with AI Physio"
    };
    title.textContent = titles[viewId] || viewId.toUpperCase();
  }
  activeView = viewId;
  if (viewId === "dashboard") { updateCharts(); }
  if (viewId === "analytics") { renderAnalytics(); }
  if (viewId === "history") { renderHistory(); }
  if (viewId === "chats") { loadChatHistory(); }
  if (viewId === "settings") { updateAccountUI(); }
  hook("viewShown", viewId);
  if (window.matchMedia && window.matchMedia("(max-width: 900px)").matches) {
    const ab = document.querySelector(".nav-btn.active");
    if (ab && ab.scrollIntoView) ab.scrollIntoView({ block: "nearest", inline: "center", behavior: "smooth" });
    window.scrollTo({ top: 0, behavior: "auto" });
  }
}

function setupUI() {
  // 1. Navigation tabs
  document.querySelectorAll('.nav-btn').forEach(b => {
    b.onclick = () => showView(b.dataset.view);
  });

  // 2. Sliders & outputs
  const aRange = $('angleRange'), aOut = $('angleOut');
  if (aRange && aOut) {
    aRange.value = userSettings.angle;
    aOut.textContent = userSettings.angle + "°";
    aRange.oninput = e => { userSettings.angle = +e.target.value; aOut.textContent = e.target.value + "°"; syncSettings(); };
  }

  const sRange = $('safeZoneRange'), sOut = $('safeZoneOut');
  if (sRange && sOut) {
    sRange.value = userSettings.safeZone;
    sOut.textContent = "±" + userSettings.safeZone + "°";
    sRange.oninput = e => { userSettings.safeZone = +e.target.value; sOut.textContent = "±" + e.target.value + "°"; syncSettings(); };
  }

  const lRange = $('lateralRange'), lOut = $('lateralOut');
  if (lRange && lOut) {
    lRange.value = userSettings.lateralLimit;
    lOut.textContent = userSettings.lateralLimit + "°";
    lRange.oninput = e => { userSettings.lateralLimit = +e.target.value; lOut.textContent = e.target.value + "°"; syncSettings(); };
  }

  // 3. Workday presets
  document.querySelectorAll('input[name="ergoMode"]').forEach(radio => {
    radio.checked = (radio.value === userSettings.mode);
    radio.onchange = e => {
      userSettings.mode = e.target.value;
      if (e.target.value === "focus") { userSettings.angle = 18; userSettings.safeZone = 3; }
      else if (e.target.value === "meeting") { /* silent: no alarm sound, only quiet on-screen reminders */ }
      else if (e.target.value === "rehab") { userSettings.angle = 15; userSettings.safeZone = 2; }

      if (aRange && aOut) { aRange.value = userSettings.angle; aOut.textContent = userSettings.angle + "°"; }
      if (sRange && sOut) { sRange.value = userSettings.safeZone; sOut.textContent = "±" + userSettings.safeZone + "°"; }
      if ($('buzzerToggle')) $('buzzerToggle').checked = userSettings.buzzer;
      syncSettings();
    };
  });

  // 4. Feedback switches (desktop notification / chime / vibration / pop-up), pop-up buttons, history + demo
  bindFeedbackSwitches();
  bindPopupButtons();
  bindHistoryUI();

  // 5. Connections & Hardware Controls
  $('connectBtn').onclick = connectBLE;
  if ($('deviceConnectBle')) $('deviceConnectBle').onclick = connectBLE;
  $('serialBtn').onclick = connectSerial;
  if ($('deviceConnectUsb')) $('deviceConnectUsb').onclick = connectSerial;
  $('wsConnect').onclick = connectWiFi;

  // 6. Floating Picture-in-Picture HUD
  if ($('pipBtn')) $('pipBtn').onclick = togglePictureInPicture;

  // 7. Calibration & Haptics Test
  $('calibrateBtn').onclick = calibrate;
  if ($('calibrateDevice')) $('calibrateDevice').onclick = calibrate;
  if ($('testAlarmBtn')) $('testAlarmBtn').onclick = () => { if (!playAlarm(true)) toast("Could not play the sound"); };

  // 8. Exports & Event Logs
  if ($('exportPdfBtn')) $('exportPdfBtn').onclick = () => exportClinicalPdfReport();
  if ($('clearEvents')) $('clearEvents').onclick = () => { events = []; renderEvents(); };

  // 9. AI Diagnostics & Chat
  $('generateAiReportBtn').onclick = requestAiDiagnosis;
  $('aiSendChatBtn').onclick = sendAiChatMessage;
  $('aiChatInput').onkeydown = e => { if (e.key === "Enter") sendAiChatMessage(); };
}

// ==========================================================
// 3. SETTINGS & DATABASE SYNC
// ==========================================================
// ==========================================================
// 4. FLOATING HUD (DOCUMENT PICTURE-IN-PICTURE API)
// ==========================================================
async function togglePictureInPicture() {
  if (!("documentPictureInPicture" in window)) {
    alert("Floating HUD requires Google Chrome or Microsoft Edge on desktop.");
    return;
  }
  if (pipWindow) {
    pipWindow.close();
    pipWindow = null;
    return;
  }
  try {
    pipWindow = await window.documentPictureInPicture.requestWindow({ width: 320, height: 220 });
    pipWindow.document.body.innerHTML = `
      <style>
        body { margin:0; background:#070d18; color:#f3f6fc; font-family:system-ui; display:flex; flex-direction:column; justify-content:center; align-items:center; height:100vh; text-align:center; padding:16px; box-sizing:border-box; }
        .pip-tag { font-size:10px; font-weight:800; letter-spacing:0.1em; color:#4f8bf9; margin-bottom:4px; }
        .pip-status { font-size:18px; font-weight:800; margin-bottom:4px; }
        .pip-status.good { color:#2ecc71; }
        .pip-status.bad { color:#f43f5e; }
        .pip-dev { font-size:36px; font-weight:900; margin:6px 0; }
        .pip-strain { font-size:12px; color:#8899b2; }
      </style>
      <div class="pip-tag">BIOSPINE FLOATING HUD</div>
      <div id="pipStatus" class="pip-status good">POSTURE OPTIMAL</div>
      <div id="pipDev" class="pip-dev">0.0°</div>
      <div id="pipStrain" class="pip-strain">Symmetrical Alignment</div>
    `;
    pipWindow.addEventListener("pagehide", () => { pipWindow = null; });
    toast("Floating HUD Opened (Stays on top of all apps)");
  } catch (err) {
    alert("Could not open floating window: " + err.message);
  }
}

function updateFloatingPip(slouch, dev, strainLabel) {
  if (!pipWindow) return;
  const statusEl = pipWindow.document.getElementById("pipStatus");
  const devEl = pipWindow.document.getElementById("pipDev");
  const strainEl = pipWindow.document.getElementById("pipStrain");
  if (statusEl) {
    statusEl.className = "pip-status " + (slouch ? "bad" : "good");
    statusEl.textContent = slouch ? "SLOUCH ALERT" : "POSTURE OPTIMAL";
  }
  if (devEl) devEl.textContent = `${dev.toFixed(1)}°`;
  if (strainEl) strainEl.textContent = strainLabel;
}

// ==========================================================
// 5. CONNECTIVITY (BLE, USB SERIAL, WI-FI)
// ==========================================================
async function sendCommand(obj) {
  const msg = JSON.stringify(obj);
  if (cmdChar) {
    try { await cmdChar.writeValue(new TextEncoder().encode(msg)); return; } catch (_) {}
  }
  if (serialPort && serialPort.writable) {
    const writer = serialPort.writable.getWriter();
    await writer.write(new TextEncoder().encode(msg + "\n"));
    writer.releaseLock();
    return;
  }
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(msg);
  }
}

async function calibrate() {
  if (!connected) { alert("Please connect your device first (or start the demo on the My Device page)."); return; }
  if ($('calStatus')) $('calStatus').textContent = "Sit in your best posture and hold still for 3 seconds...";
  $('calibrateBtn').disabled = true;

  sendCommand({ cmd: "calibrate" });
  for (let i = 3; i > 0; i--) {
    if ($('calStatus')) $('calStatus').textContent = `Saving your good posture... ${i}s`;
    await new Promise(r => setTimeout(r, 1000));
  }
  if ($('baseline')) $('baseline').textContent = "Good posture: saved ✓";
  if ($('calStatus')) $('calStatus').textContent = "Saved on your device - it remembers this even when switched off";
  $('calibrateBtn').disabled = false;
  toast("Done! Your good posture is saved.");
}

// ==========================================================
// 6. TELEMETRY, WAVEFORM & MULTI-AXIS EVALUATION
// ==========================================================
// ----------------------------------------------------------
// CHARTS: "Posture trend" line graph + "Today" donut
// Canvases are drawn at their real CSS size x devicePixelRatio so they stay
// sharp at any width; a hidden tab (size 0) is skipped and redrawn on show.
// ----------------------------------------------------------
function drawGrid(ctx, width, height) {
  ctx.strokeStyle = COLORS.grid;
  ctx.lineWidth = 1;
  const rows = 5, columns = 6;
  for (let i = 1; i < rows; i++) {
    const y = (i / rows) * height;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke();
  }
  for (let i = 1; i < columns; i++) {
    const x = (i / columns) * width;
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke();
  }
}

function drawThresholdLine(ctx, y, width, color) {
  ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y);
  ctx.strokeStyle = color; ctx.lineWidth = 1; ctx.globalAlpha = 0.35;
  ctx.setLineDash([6, 6]); ctx.stroke();
  ctx.setLineDash([]); ctx.globalAlpha = 1;
}

function drawTimeChart() {
  const canvas = $('timeChart');
  if (!canvas) return;
  const size = Math.round(canvas.clientWidth);
  if (size < 10) return;                                // tab hidden
  const dpr = window.devicePixelRatio || 1;
  const px = Math.round(size * dpr);
  if (canvas.width !== px || canvas.height !== px) { canvas.width = px; canvas.height = px; }
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, size, size);

  const total = totalCorrect + totalIncorrect;
  const correctRatio = total > 0 ? totalCorrect / total : 1;   // no data yet -> full ring
  const badRatio = 1 - correctRatio;

  // Ring geometry as fractions of the canvas: stroke 10%, radius 40%
  const cx = size / 2, cy = size / 2;
  const lineW = size * 0.10, radius = size * 0.40, glow = size * 0.05 * dpr;
  const start = -Math.PI / 2, split = start + Math.PI * 2 * correctRatio;

  ctx.lineWidth = lineW; ctx.lineCap = "butt";
  if (correctRatio > 0) {
    ctx.beginPath(); ctx.arc(cx, cy, radius, start, split);
    ctx.strokeStyle = COLORS.greenBright; ctx.shadowColor = COLORS.green; ctx.shadowBlur = glow;
    ctx.stroke();
  }
  if (badRatio > 0.0005) {
    ctx.beginPath(); ctx.arc(cx, cy, radius, split, start + Math.PI * 2);
    ctx.strokeStyle = COLORS.pink; ctx.shadowColor = COLORS.red; ctx.shadowBlur = glow;
    ctx.stroke();
  }
  ctx.shadowBlur = 0;
}

function updateCharts() { drawAngleChart(); drawTimeChart(); if (activeView === "analytics") drawWeek(); }

function initCharts() {
  updateCharts();
  if (typeof ResizeObserver !== "undefined") {
    const ro = new ResizeObserver(updateCharts);
    ["angleChart", "timeChart"].forEach(id => {
      const el = $(id);
      if (el && el.parentElement) ro.observe(el.parentElement);
    });
  }
}

// ==========================================================
// 7. 1-CLICK CLINICAL PHYSIO PDF EXPORT (jsPDF)
// ==========================================================
// ==========================================================
// 8. SECURE GEMINI AI DIAGNOSIS & INTERACTIVE CHAT
// ==========================================================
async function sendAiChatMessage() {
  const input = $('aiChatInput');
  const q = input.value.trim();
  if (!q) return;
  const box = $('aiChatBox');
  const bubble = (cls, text) => { const d = document.createElement("div"); d.className = "chat-msg " + cls; d.textContent = text; box.appendChild(d); box.scrollTop = box.scrollHeight; return d; };
  bubble("user", q);
  input.value = "";
  if (isGuest || !sessionToken) { bubble("ai", "Create a free account or sign in to chat with the AI Physio."); return; }

  const pending = bubble("ai typing", "Thinking…");
  $('aiSendChatBtn').disabled = true;
  try {
    const { res, data } = await api("/api/ai/chat", {
      method: "POST",
      body: {
        query: q,
        liveDev: parseFloat($('ringValue').textContent) || 0,
        livePostureType: $('strainType').textContent,
        compliance: $('score').textContent
      }
    });
    if (res.ok && data.success) {
      pending.className = "chat-msg ai"; pending.textContent = data.reply;
      loadChatHistory();            // saved server-side: shows up in "Chats & Doubts"
    } else if (res.status !== 401) {
      // Be honest when the AI is down instead of showing a canned answer that looks real.
      pending.className = "chat-msg ai error";
      pending.textContent = "⚠ " + (data.error || "The AI is unavailable right now.") + (data.tip ? "\n\nQuick offline tip: " + data.tip : "");
    }
  } catch (e) {
    pending.className = "chat-msg ai error";
    pending.textContent = "⚠ Could not connect. Check your internet connection and try again.";
  } finally {
    $('aiSendChatBtn').disabled = false;
    box.scrollTop = box.scrollHeight;
  }
}

// ==========================================================
// 8b. GAMIFIED DAY STREAK
// ==========================================================
function renderStreak() {
  const cur = userStreak.current || 0;
  const best = userStreak.longest || 0;
  if ($("dayStreak")) $("dayStreak").textContent = `${cur} day${cur === 1 ? "" : "s"}`;
  if ($("dayStreakNote")) $("dayStreakNote").textContent = best > cur ? `Best: ${best} days` : (cur > 0 ? "Personal best!" : "Hit 60%+ compliance today to start one");
  if ($("sidebarStreak")) $("sidebarStreak").textContent = cur > 0 ? `🔥 ${cur}` : "🔥 0";
}

// ==========================================================
// 8c. CHATS & DOUBTS — dedicated AI conversation history
// ==========================================================
async function loadChatHistory() {
  if (!currentUser || isGuest || !sessionToken) return;
  try {
    const { data } = await api("/api/chat/history");
    if (data.success) { chatHistory = data.history || []; renderChatHistory(); }
  } catch (e) { console.warn("[BioSpine] could not load chat history", e); }
}

function renderChatHistory() {
  const list = $("chatHistoryList");
  if (!list) return;
  if (!chatHistory.length) {
    list.innerHTML = "<div class='empty'>No AI conversations yet. Ask your AI Physio a question from the Dashboard and it will show up here.</div>";
    if ($("chatHistoryNote")) $("chatHistoryNote").textContent = "0 questions asked so far.";
    return;
  }
  list.innerHTML = chatHistory.map(c => `
    <div class="chat-history-item" data-id="${c.id}">
      <div class="chat-history-q"><b>Q:</b> ${esc(c.question)}</div>
      <div class="chat-history-a"><b>A:</b> ${esc(c.answer)}</div>
      <div class="chat-history-meta">
        <span>${esc(fmtDate(c.date))} · ${esc(fmtTime(c.date))}</span>
        <button type="button" class="text-btn chat-delete-btn" data-id="${c.id}" style="color:#f43f5e;">Delete</button>
      </div>
    </div>`).join("");
  if ($("chatHistoryNote")) $("chatHistoryNote").textContent = `${chatHistory.length} question${chatHistory.length === 1 ? "" : "s"} asked so far.`;
  list.querySelectorAll(".chat-delete-btn").forEach(btn => {
    btn.onclick = () => deleteChatMessage(btn.dataset.id);
  });
}

async function deleteChatMessage(id) {
  if (!currentUser || isGuest) return;
  try {
    await api(`/api/chat/${encodeURIComponent(id)}/delete`, { method: "POST", body: {} });
    chatHistory = chatHistory.filter(c => String(c.id) !== String(id));
    renderChatHistory();
  } catch (e) { toast("Could not delete that entry."); }
}

// ==========================================================
// 9. SESSION LOGGER, TICKS & ANALYTICS RENDERING
// ==========================================================
window.addEventListener("beforeunload", () => { finishSession(); });
window.addEventListener("pagehide", () => { finishSession(); });

function renderEvents() {
  const box = $('events');
  if (!box) return;
  box.innerHTML = events.length
    ? events.map(e => `
      <div class="event" style="display:flex; gap:10px; padding:8px 0; border-bottom:1px solid #1c2b42;">
        <span style="color:${e.type === 'good' ? '#2ecc71' : '#f43f5e'}; font-weight:bold;">${e.type === 'good' ? '✓' : '!'}</span>
        <div><b>${e.title}</b><small style="display:block; color:var(--muted); font-size:11px;">${e.detail} • ${e.time}</small></div>
      </div>`).join("")
    : "No events logged yet.";
}
window.addEventListener('resize', updateCharts);
function toast(msg) {
  const t = $('toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2800);
}

// ==========================================================
// 10. STATE ADDED IN v3.4  (session recorder, feedback, storage)
// ==========================================================
let rec = null;                                   // live session recorder (null while idle)
let lastPacketAt = 0, pktOk = 0, pktBad = 0, rxBuf = "";
let truncWarned = false, silentWarned = false, lastAutosave = 0, lastAnalyticsAt = 0, lastHistoryAt = 0, lastStatsAt = 0;
let episode = null;                               // current out-of-posture episode
let popupSnoozeUntil = 0, popupHideTimer = null;
let audioCtx = null, notifBlockedWarned = false;
let demoTimer = null, demoT0 = 0, demoSlouch = false, demoBadSince = 0;
let activeView = "dashboard";

const STORE_VER = "v1", MAX_SAVED_SESSIONS = 200, HIST_BINS = 901, MAX_TREND_POINTS = 720;
const DEFAULT_SETTINGS = { angle: 18, safeZone: 3, lateralLimit: 12, mode: "focus", buzzer: false, notify: true, sound: true, popup: true, breakReminder: false, dailyGoal: 120, weeklyEmail: true, alarmVolume: 0.8, alarmRepeat: 15, swapAxes: false, syncDemo: false };

const STRAIN_INFO = {
  forward: {
    name: "Forward Slouch", detail: "Extra strain on your neck", short: "forward tilt",
    hint: "Your head and shoulders are drifting forward.",
    tips: ["Lift your chest and roll your shoulders back", "Tuck your chin so your ears sit over your shoulders", "Raise your screen to eye level"]
  },
  backward: {
    name: "Leaning Too Far Back", detail: "Arching your lower back", short: "backward lean",
    hint: "You are leaning back or over-arching.",
    tips: ["Bring your hips back into the chair and sit tall", "Relax your lower back - avoid arching", "Keep your head stacked over your shoulders"]
  },
  right: {
    name: "Leaning to the Right", detail: "Leaning on right armrest", short: "right lean",
    hint: "You are leaning to the right.",
    tips: ["Sit evenly on both hips", "Stop propping on your right elbow or armrest", "Re-centre your head over your shoulders"]
  },
  left: {
    name: "Leaning to the Left", detail: "Leaning on left armrest", short: "left lean",
    hint: "You are leaning to the left.",
    tips: ["Sit evenly on both hips", "Stop propping on your left elbow or armrest", "Re-centre your head over your shoulders"]
  }
};

// ---------- small helpers ----------
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtDate = ms => new Date(ms).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" });
const fmtTime = ms => new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const fmtStamp = ms => new Date(ms).toLocaleString();
const scoreColor = s => (s >= 80 ? "#34d399" : s >= 60 ? "#f59e0b" : "#fb7185");
const r1 = v => Math.round(v * 10) / 10;
const cervicalLoadLbs = absPitch => Math.min(60, 11 + (absPitch / 15) * 14.5);

function formatSec(x) {
  x = Math.max(0, Math.round(x));
  const h = Math.floor(x / 3600), m = Math.floor((x % 3600) / 60), s = x % 60;
  return h ? `${h}h ${m}m` : m ? `${m}m ${s}s` : `${s}s`;
}

function safe(label, fn) {
  try { return fn(); } catch (e) { console.error("[BioSpine] " + label + " failed:", e); }
}

// ---------- persistent storage (per user, in this browser) ----------
const skey = name => `biospine:${STORE_VER}:${(currentUser || "guest").toLowerCase()}:${name}`;
function storeGet(name, fallback) {
  try { const raw = localStorage.getItem(skey(name)); return raw ? JSON.parse(raw) : fallback; } catch (_) { return fallback; }
}
function storeSet(name, value) {
  try { localStorage.setItem(skey(name), JSON.stringify(value)); return true; } catch (e) { console.warn("[BioSpine] storage error", e); return false; }
}
function storeRemove(name) { try { localStorage.removeItem(skey(name)); } catch (_) {} }

function sanitizeSettings() {
  ["angle", "safeZone", "lateralLimit"].forEach(k => {
    const v = Number(userSettings[k]);
    userSettings[k] = Number.isFinite(v) && v > 0 ? v : DEFAULT_SETTINGS[k];
  });
  ["buzzer", "notify", "sound", "popup"].forEach(k => { userSettings[k] = userSettings[k] === undefined ? DEFAULT_SETTINGS[k] : !!userSettings[k]; });
  userSettings.buzzer = false;       // the vibration buzzer was removed from the website: alerts are the sound alarm and the on-screen reminder
  if (!["focus", "meeting", "rehab"].includes(userSettings.mode)) userSettings.mode = "focus";
  userSettings.dailyGoal = Math.min(960, Math.max(10, Number(userSettings.dailyGoal) || DEFAULT_SETTINGS.dailyGoal));
  userSettings.breakReminder = !!userSettings.breakReminder;
  // v5.5: the new sound alarm is switched on once for everybody (they can still turn it off in Settings)
  if (userSettings.alarmV !== 2) { userSettings.sound = true; userSettings.alarmV = 2; }
  userSettings.alarmVolume = Math.min(1, Math.max(0.05, Number(userSettings.alarmVolume) || 0.8));
  userSettings.alarmRepeat = [0, 8, 15, 30].includes(Number(userSettings.alarmRepeat)) ? Number(userSettings.alarmRepeat) : 15;
  userSettings.swapAxes = !!userSettings.swapAxes; userSettings.syncDemo = !!userSettings.syncDemo;
  userSettings.weeklyEmail = userSettings.weeklyEmail === undefined ? true : !!userSettings.weeklyEmail;
}
function persistSettings() { storeSet("settings", userSettings); }

function saveSessions() {
  let list = sessions.filter(s => !s.summaryOnly).slice(0, MAX_SAVED_SESSIONS);
  for (let attempt = 0; attempt < 7; attempt++) {
    if (storeSet("sessions", list)) return true;
    if (attempt < 3) { const keep = Math.ceil(list.length / 2); list = list.map((s, i) => (i >= keep ? { ...s, trend: null } : s)); }
    else list = list.slice(0, Math.max(1, Math.floor(list.length * 0.7)));
  }
  return false;
}

function mergeServerSessions(local, server) {
  const out = local.slice();
  (server || []).forEach(s => {
    const end = Date.parse(s.date), dur = Number(s.duration) || 0;
    if (!Number.isFinite(end)) return;
    const dup = local.some(l => Math.abs(l.end - end) < 20000 && Math.abs(l.duration - dur) <= 3);
    if (dup) return;
    out.push({ v: 1, id: "srv" + end, start: end - dur * 1000, end, source: "server", summaryOnly: true, duration: dur,
      score: Number(s.score) || 0, alerts: Number(s.alerts) || 0, avg: Number(s.avg) || 0 });
  });
  return out.sort((a, b) => b.start - a.start);
}

const TAB_ID = Math.random().toString(36).slice(2, 8);
const liveKey = () => "live-" + TAB_ID;
let recoverRetry = null;

// Every open tab backs up its running session under its own key. On start-up, any backup whose owner has
// stopped refreshing it (tab crashed / browser killed / battery died) is turned into a normal saved session.
function recoverUnfinishedSession() {
  let prefix, keys = [];
  try {
    prefix = skey("live-");
    for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); if (k && k.startsWith(prefix) && k !== skey(liveKey())) keys.push(k); }
  } catch (_) { return; }
  let changed = false, pending = false;
  keys.forEach(k => {
    let live = null;
    try { live = JSON.parse(localStorage.getItem(k)); } catch (_) {}
    if (!live || !live.id) { try { localStorage.removeItem(k); } catch (_) {} return; }
    if (Date.now() - (live.heartbeat || 0) < 12000) { pending = true; return; }     // its tab is probably still alive (heartbeat every 5 s)
    try { localStorage.removeItem(k); } catch (_) {}
    if ((live.duration || 0) < 5 || sessions.some(x => x.id === live.id)) return;
    delete live.heartbeat;
    live.recovered = true;
    live.end = live.end || Date.now();
    sessions.unshift(live);
    changed = true;
  });
  if (changed) { sessions.sort((a, b) => b.start - a.start); saveSessions(); if (typeof renderHistory === "function" && $("historyList")) { renderHistory(); renderAnalytics(); } }
  if (pending && !recoverRetry) recoverRetry = setTimeout(() => { recoverRetry = null; recoverUnfinishedSession(); }, 13000);
}

// ==========================================================
// 11. SESSION RECORDER  (accurate whole-session statistics)
// ==========================================================
function newRecorder(source) {
  const now = Date.now();
  return {
    id: "s" + now.toString(36) + Math.random().toString(36).slice(2, 6),
    start: now, source, transport,
    mode: userSettings.mode, angle: userSettings.angle, safeZone: userSettings.safeZone, lateral: userSettings.lateralLimit,
    n: 0, sumAbs: 0, maxAbs: 0, sumAbsRoll: 0, maxAbsRoll: 0, peakLoad: 0,
    hist: new Uint32Array(HIST_BINS),
    strain: { forward: 0, backward: 0, left: 0, right: 0 },
    step: 1, tp: [], tr: [], tb: [],
    acc: { t0: now, n: 0, p: 0, r: 0, b: 0 },
    events: []
  };
}

function compactTrend(r) {
  const merge = a => { const o = []; for (let i = 0; i + 1 < a.length; i += 2) o.push((a[i] + a[i + 1]) / 2); if (a.length % 2) o.push(a[a.length - 1]); return o; };
  r.tp = merge(r.tp); r.tr = merge(r.tr); r.tb = merge(r.tb); r.step *= 2;
}

function recordSample(r, pitch, roll, bad, strainType, dt, now) {
  const ap = Math.abs(pitch), ar = Math.abs(roll);
  r.n++; r.sumAbs += ap; r.sumAbsRoll += ar;
  if (ap > r.maxAbs) r.maxAbs = ap;
  if (ar > r.maxAbsRoll) r.maxAbsRoll = ar;
  r.hist[Math.min(HIST_BINS - 1, Math.round(ap * 10))]++;
  const load = cervicalLoadLbs(ap);
  if (load > r.peakLoad) r.peakLoad = load;
  if (bad && strainType) r.strain[strainType] += dt;
  const a = r.acc;
  a.n++; a.p += pitch; a.r += roll; a.b += bad ? 1 : 0;
  if (now - a.t0 >= r.step * 1000) {
    r.tp.push(a.p / a.n); r.tr.push(a.r / a.n); r.tb.push(a.b / a.n);
    r.acc = { t0: now, n: 0, p: 0, r: 0, b: 0 };
    if (r.tp.length > MAX_TREND_POINTS) compactTrend(r);
  }
}

function histMedian(hist, n) {
  if (!n) return 0;
  let acc = 0;
  for (let i = 0; i < hist.length; i++) { acc += hist[i]; if (acc >= n / 2) return i / 10; }
  return 0;
}

function snapshotRecord(r) {
  const total = totalCorrect + totalIncorrect;
  const tp = r.tp.slice(), tr = r.tr.slice(), tb = r.tb.slice();
  if (r.acc.n) { tp.push(r.acc.p / r.acc.n); tr.push(r.acc.r / r.acc.n); tb.push(r.acc.b / r.acc.n); }
  return {
    v: 1, id: r.id, start: r.start, end: Date.now(), source: r.source, transport: r.transport,
    mode: r.mode, angle: r.angle, safeZone: r.safeZone, lateral: r.lateral,
    duration: Math.round(total), correctSec: r1(totalCorrect), incorrectSec: r1(totalIncorrect),
    score: total > 0 ? Math.round((totalCorrect / total) * 100) : 0,
    alerts: alertCount, longestStreak: Math.round(longestGood), samples: r.n,
    avg: r.n ? r1(r.sumAbs / r.n) : 0, median: histMedian(r.hist, r.n), max: r1(r.maxAbs),
    avgRoll: r.n ? r1(r.sumAbsRoll / r.n) : 0, maxRoll: r1(r.maxAbsRoll), peakLoad: Math.round(r.peakLoad),
    strain: { forward: r1(r.strain.forward), backward: r1(r.strain.backward), left: r1(r.strain.left), right: r1(r.strain.right) },
    trend: { step: r.step, pitch: tp.map(r1), roll: tr.map(r1), bad: tb.map(v => Math.round(v * 100) / 100) },
    events: r.events.slice(-200)
  };
}

function startSession(source) {
  if (rec) finishSession();
  historyPitchSigned = []; historyRollSigned = []; events = []; samples = 0;
  totalCorrect = 0; totalIncorrect = 0; currentGood = 0; longestGood = 0; alertCount = 0;
  isSlouchActive = false; sessionStart = Date.now(); lastTick = Date.now(); lastPacketAt = 0;
  pktOk = 0; pktBad = 0; rxBuf = ""; truncWarned = false; silentWarned = false; episode = null; lastAutosave = 0;
  rec = newRecorder(source || "device");
  strainDistribution = rec.strain;
  hidePosturePopup();
  renderEvents(); updateStats(); updatePacketStats();
  if (activeView === "history") renderHistory();
}

// ---- sending sessions to the account: full details, safe to repeat, retried until it works ----
function canSync(record) { return !!(currentUser && !isGuest && sessionToken && record && (record.source !== "demo" || userSettings.syncDemo)); }
function syncPayload(r) {
  return { session: { id: r.id, start: r.start, end: r.end, duration: r.duration, score: r.score, alerts: r.alerts, avg: r.avg, median: r.median, max: r.max,
                      avgRoll: r.avgRoll, maxRoll: r.maxRoll, peakLoad: r.peakLoad, mode: r.mode, angle: r.angle, source: r.source, strain: r.strain, trend: r.trend,
                      events: (r.events || []).slice(-40).map(e => ({ t: e.t, type: e.type, title: e.title, detail: e.detail })) },
           tzOffset: -new Date().getTimezoneOffset() };
}
function pendingIds() { return storeGet("pendingSync", []); }
function queuePending(id) { const l = pendingIds(); if (!l.includes(id)) { l.push(id); storeSet("pendingSync", l); } }
function dropPending(id) { storeSet("pendingSync", pendingIds().filter(x => x !== id)); }
let flushingSync = false;
async function flushPending() {
  if (flushingSync || !currentUser || isGuest || !sessionToken) return;
  if (!pendingIds().length) return;
  flushingSync = true;
  try {
    for (const id of pendingIds()) {
      const r = sessions.find(s => s.id === id && !s.summaryOnly);
      if (!r || !canSync(r)) { dropPending(id); continue; }
      let out;
      try { out = await api("/api/user/sync", { method: "POST", body: syncPayload(r) }); } catch (_) { break; }          // offline: try again later
      const d = out && out.data;
      if (out && out.res && out.res.status >= 400 && out.res.status < 500 && out.res.status !== 429 && out.res.status !== 401) { dropPending(id); continue; }   // the server refused it for good
      if (!out || !out.res || !out.res.ok || !d || !d.success) break;
      r.synced = true; dropPending(id); saveSessions();
      if (d.streak) { userStreak = d.streak; safe("streak", renderStreak); safe("goal", renderGoalAndBadges); if (d.streak.current > 0 && !d.duplicate) toast(`🔥 ${d.streak.current}-day streak!`); }
      hook("rewardsChanged"); hook("afterSync", d);
    }
  } finally { flushingSync = false; }
  renderSyncStatus();
}
function renderSyncStatus() {
  const el = $("syncStatus"); if (!el) return;
  if (isGuest || !currentUser) { el.textContent = ""; return; }
  const waiting = pendingIds().length, saved = sessions.filter(s => s.synced).length;
  el.textContent = waiting ? `☁ ${waiting} session${waiting === 1 ? "" : "s"} waiting to be backed up (will retry automatically)` : (saved ? `☁ ${saved} session${saved === 1 ? "" : "s"} backed up to your account` : "☁ Real-device sessions are backed up to your account automatically");
}
window.addEventListener("online", () => flushPending());
setInterval(() => flushPending(), 120000);

function finishSession() {
  if (!rec) return null;
  const record = snapshotRecord(rec);
  rec = null; sessionStart = null; episode = null;
  storeRemove(liveKey());
  hidePosturePopup();
  if (record.duration < 5) return null;
  sessions.unshift(record);
  sessions = sessions.filter(s => !s.summaryOnly).slice(0, MAX_SAVED_SESSIONS).concat(sessions.filter(s => s.summaryOnly));
  saveSessions();
  if (canSync(record)) { queuePending(record.id); flushPending(); }
  safe("goal render", renderGoalAndBadges); safe("progress render", renderProgress);
  safe("history render", renderHistory);
  safe("analytics render", renderAnalytics);
  toast("Session saved to Session History");
  hook("sessionSaved", record);
  return record;
}

function allRecords() {
  const list = sessions.slice();
  if (rec) list.unshift(snapshotRecord(rec));
  return list;
}

// ==========================================================
// 12. TELEMETRY INGEST  (all transports -> handlePayload)
// ==========================================================
function updatePacketStats() {
  if ($("pktStats")) $("pktStats").textContent = `${pktOk} good / ${pktBad} lost`;
}

function noteBadPacket() {
  pktBad++; updatePacketStats();
  if (!truncWarned && pktOk === 0 && pktBad >= 5 && /BLE/i.test(transport)) {
    truncWarned = true;
    toast("Some Bluetooth data is arriving cut off. Try USB or Wi-Fi, or update the device software.");
    if ($("deviceState")) $("deviceState").textContent = "Connected, but some data is cut off (Bluetooth limit)";
  }
}

// Reassembles {...} JSON objects from any chunking (BLE notifications, serial lines, WebSocket frames)
function feedTelemetry(chunk) {
  rxBuf += String(chunk);
  for (let guard = 0; guard < 200; guard++) {
    const start = rxBuf.indexOf("{");
    if (start < 0) { rxBuf = ""; return; }
    let depth = 0, end = -1, inStr = false, esc_ = false;
    for (let i = start; i < rxBuf.length; i++) {
      const c = rxBuf[i];
      if (inStr) { if (esc_) esc_ = false; else if (c === "\\") esc_ = true; else if (c === '"') inStr = false; }
      else if (c === '"') inStr = true;
      else if (c === "{") depth++;
      else if (c === "}") { depth--; if (depth === 0) { end = i; break; } }
    }
    const next = rxBuf.indexOf('{"dev"', start + 1);      // a new packet began before this one finished -> it was cut off
    if (next >= 0 && (end < 0 || next < end)) { noteBadPacket(); rxBuf = rxBuf.slice(next); continue; }
    if (end < 0) {
      if (rxBuf.length - start > 4000) { noteBadPacket(); rxBuf = ""; } else rxBuf = rxBuf.slice(start);
      return;
    }
    const one = rxBuf.slice(start, end + 1);
    rxBuf = rxBuf.slice(end + 1);
    handlePayload(one);
  }
}

function classifyStrain(pitch, roll, angle, lateral) {
  const pRatio = Math.abs(pitch) / Math.max(1, angle), rRatio = Math.abs(roll) / Math.max(1, lateral);
  if (pRatio >= rRatio) return pitch >= 0 ? "forward" : "backward";
  return roll >= 0 ? "right" : "left";
}

function handlePayload(raw) {
  let d;
  try { d = JSON.parse(raw); } catch (_) { noteBadPacket(); return; }
  if (!d || typeof d !== "object") { noteBadPacket(); return; }
  let pitch = Number(d.signedDev ?? d.dev);
  if (!Number.isFinite(pitch)) { noteBadPacket(); return; }
  const rollRaw = Number(d.signedRoll ?? d.rollDev ?? 0);
  let roll = Number.isFinite(rollRaw) ? rollRaw : 0;
  // "Fix directions" (Settings): older sensor software reported forward as left, left as forward, back as right, right as back.
  if (userSettings.swapAxes) { const p0 = pitch; pitch = -roll; roll = -p0; }
  const absPitch = Math.abs(pitch), absRoll = Math.abs(roll);
  if (!rec) startSession("device");
  pktOk++;

  const now = Date.now();
  const dt = lastPacketAt ? Math.min(1, Math.max(0, (now - lastPacketAt) / 1000)) : 0;
  lastPacketAt = now;

  // Verdict: trust the firmware's own hysteresis-filtered flag; otherwise apply the same band client-side
  const fromDevice = typeof d.slouch === "boolean" && !userSettings.swapAxes;   // with the fix on, judge with the corrected axes
  const angle = userSettings.angle, lat = userSettings.lateralLimit, band = userSettings.safeZone;
  let isBad;
  if (fromDevice) isBad = d.slouch;
  else {
    const pT = Math.max(1, isSlouchActive ? angle - band : angle + band);
    const rT = Math.max(1, isSlouchActive ? lat - band : lat + band);
    isBad = absPitch > pT || absRoll > rT;
  }
  const strainType = isBad ? classifyStrain(pitch, roll, angle, lat) : null;
  const info = strainType ? STRAIN_INFO[strainType] : null;

  if (isBad) { totalIncorrect += dt; currentGood = 0; }
  else { totalCorrect += dt; currentGood += dt; if (currentGood > longestGood) longestGood = currentGood; }
  samples++;
  historyPitchSigned.push(pitch); if (historyPitchSigned.length > 600) historyPitchSigned.shift();
  historyRollSigned.push(roll);   if (historyRollSigned.length > 600) historyRollSigned.shift();
  graphBuffer.push(pitch);        if (graphBuffer.length > 100) graphBuffer.shift();
  recordSample(rec, pitch, roll, isBad, strainType, dt, now);

  // Each stage is isolated so one failure can never blank the 3D model / graph / donut
  const activeDev = Math.max(absPitch, absRoll);
  safe("dashboard", () => updateHero(isBad, info, activeDev, pitch, roll, absPitch, d));
  safe("3d", () => { if (window.updateSpine) window.updateSpine(pitch, roll, isBad); });
  safe("pip", () => updateFloatingPip(isBad, activeDev, info ? info.name : "Sitting evenly"));
  safe("episode", () => trackEpisode(isBad, strainType, pitch, roll, now, fromDevice ? 0 : 1500));
  isSlouchActive = isBad;
  safe("charts", drawAngleChart);
  if (now - lastStatsAt > 200) { lastStatsAt = now; safe("stats", updateStats); }   // donut + score react immediately, not once a second
}

function rulaFor(absPitch) {
  if (absPitch < 10) return { level: 1, note: "Negligible Risk", color: "var(--green)" };
  if (absPitch < 20) return { level: 2, note: "Low Risk - monitor", color: "var(--blue)" };
  if (absPitch < 30) return { level: 3, note: "Medium Risk - change soon", color: "var(--amber)" };
  return { level: 4, note: "High Risk - act now", color: "var(--red)" };
}

function updateHero(isBad, info, activeDev, pitch, roll, absPitch, d) {
  $("strainType").textContent = isBad ? info.name : "None";
  $("strainType").style.color = isBad ? "var(--red)" : "var(--green)";
  $("strainDetail").textContent = isBad ? info.detail : "Sitting evenly";
  $("ringValue").textContent = activeDev.toFixed(1) + "°";
  if ($("ring")) $("ring").style.setProperty("--p", Math.min(100, (activeDev / 30) * 100).toFixed(0) + "%");
  $("statusCard").className = "hero-status " + (isBad ? "bad" : "good");
  $("statusText").textContent = isBad ? "SLOUCH ALERT" : "POSTURE OPTIMAL";
  $("statusHint").textContent = isBad ? `${info.hint} ${info.tips[0]}.` : "Your neck and back are lined up nicely. Keep it up!";
  const load = cervicalLoadLbs(absPitch), huge = absPitch > 60;      // the research chart stops at 60 degrees / 60 lbs
  $("cervicalLoad").textContent = huge ? "60+ lbs" : Math.round(load) + " lbs";
  if ($("cervicalNote")) $("cervicalNote").textContent = huge ? "⚠ Very huge load! Sit up now" : `${(load * 0.4536).toFixed(1)} kg (${load < 15 ? "Normal" : load < 30 ? "Elevated" : "High"})`;
  const rula = rulaFor(absPitch);
  $("rulaScore").textContent = "Level " + rula.level;
  $("rulaScore").style.color = rula.color;
  if ($("rulaNote")) $("rulaNote").textContent = rula.note;
  if ($("pitchReadout")) $("pitchReadout").textContent = `Forward lean: ${pitch.toFixed(1)}°`;
  if ($("rollReadout")) $("rollReadout").textContent = `Sideways lean: ${roll.toFixed(1)}°`;
  if ($("motorStatus")) $("motorStatus").textContent = d.vib === true ? "Vibrating" : (userSettings.buzzer ? "Ready (buzzes when you slouch)" : "Disabled");
  if ($("telemetry")) $("telemetry").textContent = "Live ✓";
  updatePacketStats();
}

// ==========================================================
// 13. FEEDBACK: desktop notification / audio chime / vibration
// ==========================================================
function getAudio() {
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    if (!audioCtx) audioCtx = new AC();
    if (audioCtx.state === "suspended" && audioCtx.resume) audioCtx.resume();
    return audioCtx;
  } catch (_) { return null; }
}

function playChime(kind) {
  const ac = getAudio();
  if (!ac) return false;
  const seq = kind === "alert" ? [[880, 0], [659.25, 0.18], [880, 0.36]] : kind === "ok" ? [[523.25, 0], [783.99, 0.14]] : [[659.25, 0], [880, 0.16]];
  const t0 = ac.currentTime + 0.02;
  seq.forEach(([freq, off]) => {
    const o = ac.createOscillator(), g = ac.createGain();
    o.type = "sine"; o.frequency.value = freq;
    g.gain.setValueAtTime(0.0001, t0 + off);
    g.gain.exponentialRampToValueAtTime(0.28, t0 + off + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + off + 0.30);
    o.connect(g); g.connect(ac.destination);
    o.start(t0 + off); o.stop(t0 + off + 0.32);
  });
  return true;
}

async function ensureNotificationPermission() {
  if (!("Notification" in window)) return "unsupported";
  if (Notification.permission === "granted" || Notification.permission === "denied") return Notification.permission;
  try { return await Notification.requestPermission(); } catch (_) { return "denied"; }
}

function showDesktopNotification(title, body) {
  if (!("Notification" in window) || Notification.permission !== "granted") return false;
  try {
    const n = new Notification(title, { body, tag: "biospine-posture" });
    setTimeout(() => { try { n.close(); } catch (_) {} }, 8000);
    return true;
  } catch (e) { console.warn("[BioSpine] notification failed", e); return false; }
}

function pulseVibration(strong) {
  let phone = false;
  if (navigator.vibrate) { try { phone = navigator.vibrate(strong ? [250, 120, 250] : [150]); } catch (_) {} }
  return phone;
}

// ---- sound alarm (static/audio/alarm.mp3) ----
let lastAlarmAt = 0;
function alarmEl() { return $("alarmAudio"); }
function playAlarm(force) {
  if (!force && (!userSettings.sound || userSettings.mode === "meeting")) return false;      // Meeting Mode is always silent
  const a = alarmEl();
  lastAlarmAt = Date.now();
  if (!a) return playChime("alert");
  try {
    a.volume = Math.min(1, Math.max(0.05, Number(userSettings.alarmVolume) || 0.8));
    a.currentTime = 0;
    const p = a.play();
    if (p && p.catch) p.catch(() => { playChime("alert"); });       // blocked by the browser? fall back to a beep
  } catch (_) { playChime("alert"); }
  return true;
}
function stopAlarm() { const a = alarmEl(); if (a) { try { a.pause(); a.currentTime = 0; } catch (_) {} } }
function unlockAlarm() {                                            // browsers only allow sound after one click or key press
  const a = alarmEl(); if (!a) return;
  try { a.muted = true; const p = a.play(); if (p && p.then) p.then(() => { a.pause(); a.currentTime = 0; a.muted = false; }).catch(() => { a.muted = false; }); } catch (_) { a.muted = false; }
}

function fireStrainFeedback(info, dev) {
  const body = `${info.name} - ${dev.toFixed(1)}° off neutral. Please realign.`;
  playAlarm();
  if (userSettings.notify && !showDesktopNotification("BioSpine: correct your posture", body) && !notifBlockedWarned) {
    notifBlockedWarned = true;
    toast("Desktop notifications are blocked or unsupported in this browser.");
  }
  if (userSettings.buzzer) pulseVibration(true);      // the wearable's motor is driven by the firmware (buzzerEnabled is synced)
}

function initFeedbackHooks() {
  const once = () => {
    document.removeEventListener("pointerdown", once, true);
    document.removeEventListener("keydown", once, true);
    getAudio();                                       // browsers only allow audio after a user gesture
    unlockAlarm();
    if (userSettings.notify && "Notification" in window && Notification.permission === "default") {
      Notification.requestPermission().then(p => {
        if (p !== "granted") { userSettings.notify = false; if ($("notifyToggle")) $("notifyToggle").checked = false; persistSettings(); }
      }).catch(() => {});
    }
  };
  document.addEventListener("pointerdown", once, true);
  document.addEventListener("keydown", once, true);
}

function bindFeedbackSwitches() {
  const buzz = null, notify = $("notifyToggle"), sound = $("soundToggle"), pop = $("popupToggle");
  if (buzz) {
    buzz.checked = userSettings.buzzer;
    buzz.onchange = e => {
      userSettings.buzzer = e.target.checked; syncSettings();
      if (!userSettings.buzzer) { toast("Vibration is off"); return; }
      const phone = pulseVibration(false);
      let device = false;
      if (connected && !demoTimer) { sendCommand({ cmd: "buzz" }); device = true; }
      toast(device ? "Vibration on - test buzz sent to your BioSpine" : phone ? "Vibration on - test buzz played" : "Vibration on - the wearable will buzz when you slouch");
    };
  }
  if (notify) {
    notify.checked = userSettings.notify;
    notify.onchange = async e => {
      if (!e.target.checked) { userSettings.notify = false; persistSettings(); toast("Desktop notifications off"); return; }
      const res = await ensureNotificationPermission();
      if (res === "granted") {
        userSettings.notify = true;
        showDesktopNotification("BioSpine notifications on", "You'll get a desktop alert whenever your posture needs correcting.");
        toast("Desktop notifications enabled");
      } else {
        userSettings.notify = false; e.target.checked = false;
        toast(res === "denied" ? "Notifications are blocked - allow them in your browser's site settings" : "This browser doesn't support desktop notifications");
      }
      persistSettings();
    };
  }
  if (sound) {
    sound.checked = userSettings.sound;
    sound.onchange = e => {
      userSettings.sound = e.target.checked; persistSettings();
      if (!userSettings.sound) { stopAlarm(); toast("Sound alarm off"); return; }
      playAlarm(true); toast("Sound alarm on");
    };
  }
  if ($("alarmVolume")) { $("alarmVolume").value = Math.round(userSettings.alarmVolume * 100); $("alarmVolume").oninput = e => { userSettings.alarmVolume = e.target.value / 100; persistSettings(); }; }
  if ($("alarmRepeat")) { $("alarmRepeat").value = String(userSettings.alarmRepeat); $("alarmRepeat").onchange = e => { userSettings.alarmRepeat = Number(e.target.value); persistSettings(); }; }
  if ($("alarmTest")) $("alarmTest").onclick = () => { if (!playAlarm(true)) toast("Could not play the sound"); };
  if ($("swapAxes")) { $("swapAxes").checked = !!userSettings.swapAxes; $("swapAxes").onchange = e => { userSettings.swapAxes = e.target.checked; persistSettings(); toast(e.target.checked ? "Directions fixed: forward / back and left / right are swapped" : "Directions back to normal"); }; }
  if (pop) {
    pop.checked = userSettings.popup;
    pop.onchange = e => {
      userSettings.popup = e.target.checked; persistSettings();
      if (!userSettings.popup) hidePosturePopup();
      toast(userSettings.popup ? "Posture pop-up enabled" : "Posture pop-up off");
    };
  }
}

// ==========================================================
// 14. OUT-OF-POSTURE EPISODES + CENTRE-SCREEN POP-UP
// ==========================================================
function trackEpisode(isBad, strainType, pitch, roll, now, delayMs) {
  const dev = Math.max(Math.abs(pitch), Math.abs(roll));
  if (isBad) {
    if (!episode) episode = { start: now, fired: false, dismissed: false, type: strainType };
    episode.type = strainType;
    if (!episode.fired && now - episode.start >= delayMs) {
      episode.fired = true;
      const info = STRAIN_INFO[strainType];
      alertCount++;
      addEvent("warning", info.name, `${dev.toFixed(1)}° ${info.short}`);
      fireStrainFeedback(info, dev);
    }
    if (episode.fired) {
      refreshPosturePopup(strainType, dev);
      if (userSettings.sound && userSettings.alarmRepeat > 0 && now - lastAlarmAt >= userSettings.alarmRepeat * 1000) playAlarm();   // keep reminding until you sit up
    }
  } else if (episode) {
    const wasFired = episode.fired;
    episode = null;
    if (wasFired) {
      addEvent("good", "Neutral Alignment Restored", "Spine returned to safe physiological zone");
      stopAlarm();
      if (userSettings.sound && userSettings.mode !== "meeting") playChime("ok");
      showPopupSuccess();
    }
  }
}

function popupAllowed() { return userSettings.popup !== false && Date.now() >= popupSnoozeUntil; }

function refreshPosturePopup(type, dev) {
  const layer = $("postureAlert");
  if (!layer) return;
  if (!episode || episode.dismissed || !popupAllowed()) { hidePosturePopup(); return; }
  const info = STRAIN_INFO[type];
  if (popupHideTimer) { clearTimeout(popupHideTimer); popupHideTimer = null; }
  const card = layer.querySelector(".posture-popup");
  card.classList.remove("ok");
  if (layer.dataset.type !== type) {
    layer.dataset.type = type;
    $("ppTitle").textContent = "Correct your posture";
    $("ppText").textContent = info.hint;
    $("ppTips").innerHTML = info.tips.map(t => `<li>${esc(t)}</li>`).join("");
  }
  $("ppIcon").textContent = "!";
  $("ppDev").textContent = dev.toFixed(1) + "°";
  $("ppLabel").textContent = info.short;
  $("ppTips").style.display = "";
  $("ppActions").style.display = "";
  layer.hidden = false;
}

function showPopupSuccess() {
  const layer = $("postureAlert");
  if (!layer || layer.hidden) return;
  layer.querySelector(".posture-popup").classList.add("ok");
  $("ppIcon").textContent = "✓";
  $("ppTitle").textContent = "Posture corrected - nice work!";
  $("ppText").textContent = "Keep your spine stacked and shoulders relaxed.";
  $("ppDev").textContent = "0.0°";
  $("ppLabel").textContent = "back in the safe zone";
  $("ppTips").style.display = "none";
  $("ppActions").style.display = "none";
  layer.dataset.type = "";
  if (popupHideTimer) clearTimeout(popupHideTimer);
  popupHideTimer = setTimeout(hidePosturePopup, 1800);
}

function hidePosturePopup() {
  const layer = $("postureAlert");
  if (popupHideTimer) { clearTimeout(popupHideTimer); popupHideTimer = null; }
  if (layer) { layer.hidden = true; layer.dataset.type = ""; }
}

function bindPopupButtons() {
  if ($("ppDismiss")) $("ppDismiss").onclick = () => { if (episode) episode.dismissed = true; hidePosturePopup(); };
  if ($("ppSnooze")) $("ppSnooze").onclick = () => { popupSnoozeUntil = Date.now() + 5 * 60000; hidePosturePopup(); toast("Pop-up snoozed for 5 minutes"); };
  document.addEventListener("keydown", e => { if (e.key === "Escape" && $("postureAlert") && !$("postureAlert").hidden) { if (episode) episode.dismissed = true; hidePosturePopup(); } });
}

// ==========================================================
// 15. TREND PAINTER (shared by dashboard, history detail, PDF)
// ==========================================================
function fitCanvas(canvas, w, h, dprOverride) {
  const width = w ?? canvas.clientWidth, height = h ?? canvas.clientHeight;
  if (width < 10 || height < 10) return null;
  const dpr = dprOverride ?? (window.devicePixelRatio || 1);
  const bw = Math.round(width * dpr), bh = Math.round(height * dpr);
  if (canvas.width !== bw || canvas.height !== bh) { canvas.width = bw; canvas.height = bh; }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  return { ctx, width, height, dpr };
}

function paintTrend(ctx, width, height, dpr, values, opts) {
  drawGrid(ctx, width, height);
  if (values.length < 2) return;
  const limit = opts.limit;
  let maxValue = Math.max(25, limit + 10);
  for (const v of values) maxValue = Math.max(maxValue, Math.abs(v));
  const minValue = -maxValue, range = maxValue - minValue;
  const padY = 8, plotW = width - 8, plotH = height - padY * 2;
  const yOf = v => height - padY - ((v - minValue) / range) * plotH;
  const xOf = i => (i / (values.length - 1)) * plotW;

  if (opts.bad) {                                     // shade the stretches that were out of posture
    ctx.fillStyle = "rgba(255, 59, 107, 0.10)";
    const half = plotW / (values.length - 1) / 2;
    opts.bad.forEach((b, i) => { if (b >= 0.5) ctx.fillRect(Math.max(0, xOf(i) - half), 0, half * 2, height); });
  }
  drawThresholdLine(ctx, yOf(limit), width, COLORS.red);
  drawThresholdLine(ctx, yOf(-limit), width, COLORS.red);
  drawThresholdLine(ctx, yOf(0), width, COLORS.gridStrong);

  const gradient = ctx.createLinearGradient(0, 0, plotW, 0);
  gradient.addColorStop(0, COLORS.primary); gradient.addColorStop(0.5, COLORS.cyan); gradient.addColorStop(1, COLORS.purple);
  ctx.beginPath();
  values.forEach((v, i) => { const x = xOf(i), y = yOf(v); i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y); });
  ctx.strokeStyle = gradient; ctx.lineWidth = 3; ctx.lineJoin = "round"; ctx.lineCap = "round";
  ctx.shadowColor = COLORS.cyan; ctx.shadowBlur = 10 * dpr;
  ctx.stroke(); ctx.shadowBlur = 0;

  const dot = opts.dotColor || COLORS.cyan;
  ctx.beginPath(); ctx.arc(plotW, yOf(values[values.length - 1]), 5, 0, Math.PI * 2);
  ctx.fillStyle = dot; ctx.shadowColor = dot; ctx.shadowBlur = 14 * dpr; ctx.fill(); ctx.shadowBlur = 0;
}

function drawAngleChart() {
  const canvas = $("angleChart");
  if (!canvas) return;
  const f = fitCanvas(canvas);
  if (!f) return;
  paintTrend(f.ctx, f.width, f.height, f.dpr, historyPitchSigned.slice(-TREND_WINDOW),
    { limit: userSettings.angle, dotColor: isSlouchActive ? COLORS.red : COLORS.cyan });
}

function drawSessionChart(canvas, r, w, h, dpr) {
  const f = fitCanvas(canvas, w, h, dpr);
  if (!f || !r.trend) return false;
  paintTrend(f.ctx, f.width, f.height, f.dpr, r.trend.pitch, { limit: r.angle, bad: r.trend.bad, dotColor: COLORS.cyan });
  return true;
}

// ==========================================================
// 16. 3D SPINE  (chain that visibly bends with pitch and roll)
// ==========================================================
function init3D() {
  const container = $("spine3dContainer");
  if (!container) return;
  if (typeof THREE === "undefined") {
    container.innerHTML = '<div class="empty" style="align-self:center">3D model unavailable - three.js could not be loaded (check your internet connection and reload).</div>';
    return;
  }
  const W = () => Math.max(200, container.clientWidth), H = () => Math.max(160, container.clientHeight);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(40, W() / H(), 0.1, 100);
  camera.position.set(9, 2.5, 9);
  camera.lookAt(0, 0.3, 0);
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  if (renderer.setPixelRatio) renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(W(), H());
  container.innerHTML = ""; container.appendChild(renderer.domElement);

  const N = 12, L = 0.55, BASE_Y = -3.2, up = new THREE.Vector3(0, 1, 0);
  const verts = [], group = new THREE.Group();
  for (let i = 0; i < N; i++) {
    const mesh = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.6, 0.35, 16),
      new THREE.MeshStandardMaterial({ color: i > 6 ? 0x38bdf8 : 0x2ecc71 }));
    group.add(mesh); verts.push(mesh);
  }
  scene.add(group);
  const ref = new THREE.Line(                          // upright reference line: makes any deviation obvious
    new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, BASE_Y, 0), new THREE.Vector3(0, BASE_Y + N * L + 0.2, 0)]),
    new THREE.LineBasicMaterial({ color: 0x475569 }));
  scene.add(ref);
  const key = new THREE.DirectionalLight(0xffffff, 1.3); key.position.set(3, 6, 5); scene.add(key);
  scene.add(new THREE.AmbientLight(0x404856));

  // Total tilt is spread along the chain (more bend towards the neck), so the column curves like a real spine
  const weights = verts.map((_, i) => i + 1), wSum = weights.reduce((a, b) => a + b, 0);
  const GAIN = 1.5;                                    // mild visual exaggeration so 20-30 degrees reads clearly (exact angles are in the readouts)
  function pose(pitchDeg, rollDeg) {
    pitchDeg = Math.max(-75, Math.min(75, pitchDeg * GAIN)); rollDeg = Math.max(-75, Math.min(75, rollDeg * GAIN));
    let cp = 0, cr = 0, x = 0, y = BASE_Y, z = 0;
    verts.forEach((m, i) => {
      cp += (pitchDeg * Math.PI / 180) * (weights[i] / wSum);
      cr += (rollDeg * Math.PI / 180) * (weights[i] / wSum);
      const dir = new THREE.Vector3(Math.sin(cr), Math.cos(cp) * Math.cos(cr), Math.sin(cp)).normalize();
      m.position.set(x + dir.x * L / 2, y + dir.y * L / 2, z + dir.z * L / 2);
      m.quaternion.setFromUnitVectors(up, dir);
      x += dir.x * L; y += dir.y * L; z += dir.z * L;
    });
  }
  pose(0, 0);
  renderer.render(scene, camera);

  window.updateSpine = (p, r, slouch) => {
    pose(p, r);
    verts.forEach((v, idx) => v.material.color.setHex(slouch ? 0xf43f5e : (idx > 6 ? 0x38bdf8 : 0x2ecc71)));
    renderer.render(scene, camera);
  };
  window.__spineVerts = verts;
  const resize = () => { renderer.setSize(W(), H()); camera.aspect = W() / H(); camera.updateProjectionMatrix(); renderer.render(scene, camera); };
  if (typeof ResizeObserver !== "undefined") new ResizeObserver(resize).observe(container);
  else window.addEventListener("resize", resize);
}

// ==========================================================
// 17. CONNECTIVITY (BLE / USB serial / Wi-Fi) + DEMO
// ==========================================================
async function connectBLE() {
  if (!navigator.bluetooth) {
    alert("This browser can't use Bluetooth. Use Chrome or Edge on Android or desktop (iPhone browsers don't support Web Bluetooth). You can still explore with the demo data on the Device tab.");
    return;
  }
  try {
    bleDevice = await navigator.bluetooth.requestDevice({
      filters: [{ name: DEVICE_NAME }, { services: [SERVICE_UUID] }],
      optionalServices: [SERVICE_UUID]
    });
    bleDevice.addEventListener("gattserverdisconnected", onDisconnected);
    const server = await bleDevice.gatt.connect();
    const service = await server.getPrimaryService(SERVICE_UUID);
    telemetryChar = await service.getCharacteristic(CHAR_UUID);
    try { cmdChar = await service.getCharacteristic(CMD_UUID); } catch (_) { cmdChar = null; }

    const decoder = new TextDecoder();
    await telemetryChar.startNotifications();
    telemetryChar.addEventListener("characteristicvaluechanged", e => feedTelemetry(decoder.decode(e.target.value, { stream: true })));

    transport = "BLE 5.0";
    setConnection(true);
    startSession("device");
    syncSettings();
    toast("Connected via Bluetooth Low Energy");
  } catch (e) {
    if (e && e.name === "NotFoundError") return;           // user closed the chooser: not an error
    alert("BLE connection failed: " + (e && e.message ? e.message : e));
  }
}

async function connectSerial() {
  if (!("serial" in navigator)) {
    alert("Web Serial is supported in Chrome, Edge, and Opera.");
    return;
  }
  try {
    serialPort = await navigator.serial.requestPort();
    await serialPort.open({ baudRate: 115200 });

    transport = "USB Serial";
    setConnection(true);
    startSession("device");
    syncSettings();
    toast("Connected via High-Speed USB Serial");

    const decoder = new TextDecoderStream();
    serialPort.readable.pipeTo(decoder.writable);
    const reader = decoder.readable.getReader();
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      feedTelemetry(value);
    }
    onDisconnected();
  } catch (e) {
    alert("USB Serial error: " + e.message);
    if (connected) onDisconnected();
  }
}

function connectWiFi() {
  const url = $("wsUrl").value.trim() || "ws://192.168.4.1:81";
  if (location.protocol === "https:" && url.startsWith("ws://")) {
    alert("Browsers block insecure Wi-Fi (ws://) connections from secure https pages. Use Bluetooth or USB instead, or open this app over http:// on your local network.");
    return;
  }
  try {
    ws = new WebSocket(url);
    ws.onopen = () => {
      transport = "Wi-Fi";
      setConnection(true);
      startSession("device");
      syncSettings();
      toast("Connected via Wi-Fi WebSocket");
    };
    ws.onmessage = e => feedTelemetry(e.data);
    ws.onclose = onDisconnected;
    ws.onerror = () => alert("Could not reach the ESP32 WebSocket. Join the BioSpine Wi-Fi network and make sure this page is opened over http:// (not https://).");
  } catch (_) {
    alert("Invalid WebSocket URL");
  }
}

function onDisconnected() {
  if (demoTimer) { clearInterval(demoTimer); demoTimer = null; }
  connected = false;
  setConnection(false);
  finishSession();
  renderHistory();
  drawWeek();
  toast("Device disconnected");
}

function setConnection(on) {
  connected = on;
  $("connectBtn").textContent = on ? "Connected" : "Connect Bluetooth (BLE)";
  $("connectBtn").classList.toggle("connected", on);
  $("connectionLine").textContent = on ? `Monitoring active via ${transport}` : "Device disconnected";
  if ($("deviceState")) $("deviceState").textContent = on ? "Connected and sending live readings" : "Not connected";
  if ($("transport")) $("transport").textContent = on ? transport : "—";
  if ($("telemetry")) $("telemetry").textContent = on ? "Waiting for the first reading..." : "Standby";
  if ($("motorStatus")) $("motorStatus").textContent = on ? (userSettings.buzzer ? "Ready (buzzes when you slouch)" : "Disabled") : "Off (Standby)";
  if ($("demoBtn")) $("demoBtn").textContent = demoTimer ? "■ Stop demo data" : "▶ Start demo data (no device needed)";
  if (!on) hidePosturePopup();
}

function toggleDemo() {
  if (demoTimer) { onDisconnected(); return; }
  if (connected) { toast("Disconnect your device before starting demo data"); return; }
  transport = "Demo (simulated)";
  demoT0 = Date.now(); demoSlouch = false; demoBadSince = 0;
  demoTimer = setInterval(demoStep, 100);
  setConnection(true);
  startSession("demo");
  toast("Demo data started - this is simulated, not from your device");
}

function demoStep() {
  const now = Date.now(), t = (now - demoT0) / 1000, c = t % 60;
  let pitch = 3 * Math.sin(t * 1.3) + 1.5 * Math.sin(t * 3.1), roll = 2 * Math.sin(t * 0.9);
  if (c >= 15 && c < 27) pitch = 22 + 6 * Math.min(1, (c - 15) / 3) + 1.5 * Math.sin(t * 2);
  else if (c >= 38 && c < 46) roll = -16 + 1.5 * Math.sin(t * 2);
  else if (c >= 50 && c < 55) pitch = -21 + Math.sin(t * 2);
  const angle = userSettings.angle, lat = userSettings.lateralLimit, band = userSettings.safeZone;
  const exceeds = Math.abs(pitch) > Math.max(1, demoSlouch ? angle - band : angle + band) || Math.abs(roll) > Math.max(1, demoSlouch ? lat - band : lat + band);
  if (exceeds) { if (!demoBadSince) demoBadSince = now; if (now - demoBadSince >= 1500) demoSlouch = true; }
  else { demoBadSince = 0; demoSlouch = false; }
  const f = v => Math.round(v * 10) / 10;
  handlePayload(JSON.stringify({ dev: f(Math.abs(pitch)), signedDev: f(pitch), pitch: f(pitch), rollDev: f(Math.abs(roll)), signedRoll: f(roll), slouch: demoSlouch, vib: demoSlouch && userSettings.buzzer }));
}

// ==========================================================
// 18. SETTINGS SYNC, LOGIN, TICK, STATS
// ==========================================================
function syncSettings() {
  persistSettings();
  sendCommand({
    cmd: "settings",
    angle: userSettings.angle,
    safeZone: userSettings.safeZone,
    lateralLimit: userSettings.lateralLimit,
    buzzerEnabled: userSettings.buzzer
  });
  if (currentUser && !isGuest && sessionToken) {
    api("/api/user/sync", { method: "POST", body: { settings: userSettings } }).catch(() => {});
  }
}

// userData is the payload already returned by /api/auth/register, /login or
// /session (handleAuthSubmit / restoreSession fetch it) - this function no
// longer authenticates on its own, it just applies whatever account data it's given.
async function loadUserFromBackend(email, userData) {
  currentUser = email;
  if (!isGuest) localStorage.setItem("biospine_active_user", email);
  let serverSessions = [];
  if (userData) {
    userSettings = { ...userSettings, ...userData.settings };
    serverSessions = userData.sessions || [];
    userStreak = userData.streak || userStreak;
    emailVerified = userData.emailVerified !== false;
    serverLoaded = serverSessions.length;
    serverTotal = userData.totalSessions || serverLoaded;
  }
  const local = storeGet("settings", null);
  if (local) userSettings = { ...userSettings, ...local };
  userSettings = { ...DEFAULT_SETTINGS, ...userSettings };
  sanitizeSettings();
  sessions = mergeServerSessions(storeGet("sessions", []), serverSessions);
  recoverUnfinishedSession();

  $("landingPage").style.display = "none";
  $("appShell").style.display = "flex";
  $("userBadge").textContent = isGuest ? "Demo mode" : currentUser;

  setupUI();
  init3D();
  renderHistory();
  renderAnalytics();
  renderStreak();
  renderGoalAndBadges();
  renderProgress();
  updateAccountUI();
  applyCompat();
  updateLoadMore();
  loadChatHistory();
  setInterval(tick, 1000);
  initCharts();
  initFeedbackHooks();
  hook("afterLogin", userData);
  setTimeout(() => { flushPending(); renderSyncStatus(); }, 2500);
}

function tick() {
  const now = Date.now();
  if (now - lastGoalAt > 5000) { lastGoalAt = now; safe("goal render", renderGoalAndBadges); }
  if (connected && rec) {
    if (lastPacketAt && now - lastPacketAt > 3000 && $("telemetry")) $("telemetry").textContent = "No data coming in";
    if (!lastPacketAt && !silentWarned && now - rec.start > 8000 && !demoTimer) {
      silentWarned = true;
      toast("Connected, but no readings have arrived yet. Please check the device is switched on and has the latest software.");
    }
    updateStats();
    if (now - lastAutosave >= 5000) {                 // crash-safe autosave of the running session
      lastAutosave = now;
      storeSet(liveKey(), { ...snapshotRecord(rec), heartbeat: now });
    }
  }
  if (activeView === "analytics" && now - lastAnalyticsAt > 2000) renderAnalytics();
  if (activeView === "history" && rec && now - lastHistoryAt > 5000) renderHistory();
}

function updateStats() {
  const total = totalCorrect + totalIncorrect;
  const has = total > 0;                                // no data yet -> dashes instead of a misleading 0% / 100%
  const score = has ? Math.round((totalCorrect / total) * 100) : 0;
  $("correctPct").textContent = has ? score + "%" : "—";
  $("badPct").textContent = has ? (100 - score) + "%" : "—";
  $("score").textContent = has ? score + "%" : "—";
  $("todayScore").textContent = has ? score + "%" : "—";
  $("streak").textContent = formatSec(currentGood);
  if ($("streakNote")) $("streakNote").textContent = `Best this session: ${formatSec(longestGood)}`;
  $("alerts").textContent = alertCount;
  drawTimeChart();
}

function addEvent(type, title, detail) {
  const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  events.unshift({ type, title, detail, time });
  events = events.slice(0, 15);
  if (rec && rec.events.length < 400) rec.events.push({ t: Date.now(), type, title, detail });
  renderEvents();
}

// ==========================================================
// 19. ANALYTICS & TRENDS
// ==========================================================
const dayKey = d => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;

function recTimes(s) {
  if (s.correctSec !== undefined) return { c: s.correctSec, t: s.correctSec + s.incorrectSec };
  return { c: (s.duration * s.score) / 100, t: s.duration };
}

function weeklyData() {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const days = [];
  for (let i = 6; i >= 0; i--) { const d = new Date(today); d.setDate(today.getDate() - i); days.push({ date: d, key: dayKey(d), c: 0, t: 0, isToday: i === 0 }); }
  const map = Object.fromEntries(days.map(d => [d.key, d]));
  allRecords().forEach(s => { const day = map[dayKey(new Date(s.start))]; if (!day) return; const x = recTimes(s); day.c += x.c; day.t += x.t; });
  days.forEach(d => { d.score = d.t > 0 ? Math.round((d.c / d.t) * 100) : null; });
  return days;
}

function drawWeek() {
  const canvas = $("weekChart");
  if (!canvas) return;
  const f = fitCanvas(canvas);
  if (!f) return;
  const { ctx, width, height } = f;
  const days = weeklyData();
  const padL = 34, padB = 30, padT = 22, plotH = height - padB - padT, plotW = width - padL - 8;
  ctx.font = "11px -apple-system, Segoe UI, Roboto, sans-serif";
  ctx.textBaseline = "middle";
  [0, 50, 100].forEach(v => {
    const y = padT + plotH - (v / 100) * plotH;
    ctx.strokeStyle = COLORS.grid; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(width - 8, y); ctx.stroke();
    ctx.fillStyle = cssv("--muted"); ctx.textAlign = "right"; ctx.fillText(v + "%", padL - 6, y);
  });
  const slot = plotW / 7, bw = Math.min(46, slot * 0.55);
  days.forEach((d, i) => {
    const x = padL + slot * i + (slot - bw) / 2;
    const h = d.score === null ? 3 : Math.max(3, (d.score / 100) * plotH);
    ctx.fillStyle = d.score === null ? cssv("--track") : scoreColor(d.score);
    ctx.globalAlpha = d.isToday || d.score === null ? 1 : 0.85;
    ctx.fillRect(x, padT + plotH - h, bw, h);
    ctx.globalAlpha = 1;
    ctx.textAlign = "center";
    ctx.fillStyle = d.isToday ? cssv("--text") : cssv("--muted");
    ctx.fillText(d.date.toLocaleDateString(undefined, { weekday: "short" }), x + bw / 2, height - 12);
    ctx.fillStyle = cssv("--text");
    ctx.fillText(d.score === null ? "-" : d.score + "%", x + bw / 2, padT + plotH - h - 9);
  });
}

function renderStrainBars(container, totals, note) {
  const order = ["forward", "backward", "left", "right"];
  const sum = order.reduce((a, k) => a + (totals[k] || 0), 0);
  if (sum < 1) { container.innerHTML = `<div class="empty">${esc(note || "No out-of-posture time recorded.")}</div>`; return; }
  const max = Math.max(...order.map(k => totals[k] || 0));
  container.innerHTML = order.map(k => {
    const v = totals[k] || 0;
    return `<div class="strain-row"><span>${esc(STRAIN_INFO[k].name)}</span><div class="strain-bar"><i style="width:${(v / max) * 100}%"></i></div><b>${formatSec(v)} <small>(${Math.round((v / sum) * 100)}%)</small></b></div>`;
  }).join("");
}

function renderAnalytics() {
  lastAnalyticsAt = Date.now();
  const src = rec ? { r: snapshotRecord(rec), label: "Live session" } : (() => { const l = sessions.find(s => !s.summaryOnly); return l ? { r: l, label: "Last saved session - " + fmtDate(l.start) + ", " + fmtTime(l.start) } : null; })();
  const set = (id, v) => { if ($(id)) $(id).textContent = v; };
  if (src) {
    set("avg", src.r.avg.toFixed(1) + "°"); set("median", src.r.median.toFixed(1) + "°");
    set("maxDev", src.r.max.toFixed(1) + "°"); set("samples", src.r.samples);
  } else { set("avg", "0.0°"); set("median", "0.0°"); set("maxDev", "0.0°"); set("samples", 0); }
  set("analyticsSource", src ? "Showing: " + src.label : "No data yet - connect your device or start demo data from the Device tab.");

  const all = allRecords();
  const totalSec = all.reduce((a, s) => a + recTimes(s).t, 0);
  const days = weeklyData();
  const wc = days.reduce((a, d) => a + d.c, 0), wt = days.reduce((a, d) => a + d.t, 0);
  const best = days.filter(d => d.score !== null).sort((a, b) => b.score - a.score)[0];
  set("lifeSessions", all.length); set("lifeTime", formatSec(totalSec));
  set("lifeWeekScore", wt > 0 ? Math.round((wc / wt) * 100) + "%" : "-");
  set("lifeBestDay", best ? best.score + "%" : "-");
  set("lifeBestNote", best ? best.date.toLocaleDateString(undefined, { weekday: "long" }) : "No data yet");
  drawWeek();

  const weekKeys = new Set(days.map(d => d.key));
  const totals = { forward: 0, backward: 0, left: 0, right: 0 };
  all.forEach(s => { if (s.strain && weekKeys.has(dayKey(new Date(s.start)))) Object.keys(totals).forEach(k => { totals[k] += s.strain[k] || 0; }); });
  if ($("strainBars")) renderStrainBars($("strainBars"), totals, "No out-of-posture time recorded in the last 7 days.");
}

// ==========================================================
// 20. SESSION HISTORY (list + detail)
// ==========================================================
function renderHistory() {
  lastHistoryAt = Date.now();
  const list = $("historyList");
  if (!list) return;
  const rows = [];
  if (rec) { const s = snapshotRecord(rec); rows.push(histRow(s, "live")); }
  sessions.forEach(s => rows.push(histRow(s)));
  list.innerHTML = rows.length ? rows.join("") : "<div class='empty'>No sessions recorded yet. Connect your device (or start demo data on the Device tab) - every session is saved here automatically.</div>";
  if ($("historyNote")) $("historyNote").textContent = isGuest
    ? "Demo mode: sessions are not saved."
    : `${sessions.filter(s => !s.summaryOnly).length} detailed sessions on this device, ${sessions.filter(s => s.summaryOnly).length} summaries from your account${rec ? " + 1 in progress" : ""}.`;
  updateLoadMore();
}

function histRow(s, live) {
  const badge = live ? '<em class="badge live">LIVE</em>' : s.source === "demo" ? '<em class="badge demo">DEMO</em>' : s.summaryOnly ? '<em class="badge srv">SERVER</em>' : s.recovered ? '<em class="badge srv">RECOVERED</em>' : "";
  return `<button type="button" class="hist-row" data-id="${live ? "live" : esc(s.id)}">
    <div class="hist-main"><b>${esc(fmtDate(s.start))} ${badge}</b>
      <small>${esc(fmtTime(s.start))} · ${esc(formatSec(s.duration))} monitored · ${s.alerts} alerts · avg ${Number(s.avg).toFixed(1)}°</small></div>
    <div class="hist-score" style="color:${scoreColor(s.score)}">${s.score}%<i><u style="width:${s.score}%;background:${scoreColor(s.score)}"></u></i></div></button>`;
}

function findRecord(id) { return id === "live" ? (rec ? snapshotRecord(rec) : null) : sessions.find(s => s.id === id) || null; }

function showSessionDetail(id) {
  const r = findRecord(id);
  const panel = $("sessionDetail");
  if (!r || !panel) return;
  panel.hidden = false;
  panel.dataset.id = id;
  const x = recTimes(r);
  const kpi = (label, val, sub) => `<article class="metric"><span>${esc(label)}</span><strong>${val}</strong><small>${esc(sub || "")}</small></article>`;
  const evs = (r.events || []).slice().reverse();
  $("detailBody").innerHTML = `
    <div class="panel-head"><div><h3>${esc(fmtDate(r.start))}, ${esc(fmtTime(r.start))} ${r.source === "demo" ? '<em class="badge demo">DEMO</em>' : ""}</h3>
      <p>${esc(r.summaryOnly ? "Server summary (detailed data was not stored on this browser)" : `${fmtStamp(r.start)} to ${fmtStamp(r.end)} · ${r.transport || ""}`)}</p></div>
      <div class="history-actions"><button class="primary" id="detailPdfBtn" type="button">📄 Download report (PDF)</button>
      ${id === "live" ? "" : '<button class="danger-btn" id="detailDeleteBtn" type="button">Delete</button>'}
      <button class="secondary" id="detailCloseBtn" type="button">Close</button></div></div>
    <div class="metrics-grid">
      ${kpi("Posture Score", `<span style="color:${scoreColor(r.score)}">${r.score}%</span>`, "Time sitting well")}
      ${kpi("Time Worn", esc(formatSec(r.duration)), `${formatSec(x.c)} correct`)}
      ${kpi("Needs Correction", esc(formatSec(r.summaryOnly ? r.duration - x.c : r.incorrectSec)), "Time out of posture")}
      ${kpi("Slouch Alerts", r.alerts, "Times you were reminded")}
      ${kpi("Average / Typical Lean", `${Number(r.avg).toFixed(1)}° / ${r.median !== undefined ? r.median.toFixed(1) : "-"}°`, "Forward lean")}
      ${kpi("Worst Lean", (r.max !== undefined ? r.max.toFixed(1) : "-") + "°", r.peakLoad ? `~${r.peakLoad} lbs est. peak neck load` : "")}
    </div>
    ${r.trend && r.trend.pitch.length > 1 ? `<h4 class="sub-h">Forward lean during the session</h4><div class="chart-box detail-chart"><canvas id="detailChart"></canvas></div>` : ""}
    ${r.strain ? `<h4 class="sub-h">What kind of slouching</h4><div id="detailStrain"></div>` : ""}
    <h4 class="sub-h">What happened</h4>
    <div class="events">${evs.length ? evs.slice(0, 60).map(e => `<div class="event"><span style="color:${e.type === "good" ? "#2ecc71" : "#f43f5e"};font-weight:bold">${e.type === "good" ? "✓" : "!"}</span><div><b>${esc(e.title)}</b><small>${esc(e.detail)} · ${esc(new Date(e.t).toLocaleTimeString())}</small></div></div>`).join("") : "<div class='empty'>No incidents recorded.</div>"}</div>`;
  if (r.strain) renderStrainBars($("detailStrain"), r.strain, "No out-of-posture time in this session.");
  $("detailPdfBtn").onclick = () => exportClinicalPdfReport(findRecord(id));
  if ($("detailDeleteBtn")) $("detailDeleteBtn").onclick = () => {
    if (!confirm("Delete this session permanently?")) return;
    sessions = sessions.filter(s => s.id !== id); saveSessions();
    panel.hidden = true; renderHistory(); renderAnalytics(); toast("Session deleted");
  };
  $("detailCloseBtn").onclick = () => { panel.hidden = true; };
  requestAnimationFrame(() => { const c = $("detailChart"); if (c) drawSessionChart(c, r); });
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

function bindHistoryUI() {
  if ($("historyList")) $("historyList").onclick = e => { const row = e.target.closest(".hist-row"); if (row) showSessionDetail(row.dataset.id); };
  if ($("exportJsonBtn")) $("exportJsonBtn").onclick = () => {
    const data = { app: "BioSpine", user: currentUser, exportedAt: new Date().toISOString(), sessions: sessions.filter(s => !s.summaryOnly) };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = `BioSpine_history_${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    toast("History exported");
  };
  if ($("clearHistoryBtn")) $("clearHistoryBtn").onclick = () => {
    if (!sessions.length || !confirm("Delete ALL saved sessions for this account on this browser? This cannot be undone.")) return;
    sessions = []; saveSessions();
    if ($("sessionDetail")) $("sessionDetail").hidden = true;
    renderHistory(); renderAnalytics(); toast("History cleared");
  };
  if ($("demoBtn")) $("demoBtn").onclick = toggleDemo;
  if ($("loadMoreSessionsBtn")) $("loadMoreSessionsBtn").onclick = loadMoreSessions;
}

// ==========================================================
// 21. CLINICAL REPORT (jsPDF, with print-to-PDF fallback)
// ==========================================================
function pdfSafe(s) {
  return String(s ?? "").replace(/[\u2018\u2019]/g, "'").replace(/[\u201C\u201D]/g, '"').replace(/[\u2013\u2014]/g, "-")
    .replace(/\u2022/g, "-").replace(/\u2026/g, "...").replace(/[^\x20-\x7E\u00A0-\u00FF]/g, "?");
}

function interpretation(r) {
  const x = recTimes(r), lines = [];
  const verdict = r.score >= 90 ? "Excellent" : r.score >= 75 ? "Good" : r.score >= 50 ? "Needs improvement" : "Poor";
  lines.push(`${verdict}: ${r.score}% of the monitored time was spent in neutral alignment (${formatSec(x.c)} of ${formatSec(x.t)}).`);
  if (r.strain) {
    const tot = Object.values(r.strain).reduce((a, b) => a + b, 0);
    const top = Object.entries(r.strain).sort((a, b) => b[1] - a[1])[0];
    if (tot >= 1 && top && top[1] / tot >= 0.5) lines.push(`Most out-of-posture time (${Math.round((top[1] / tot) * 100)}%) was "${STRAIN_INFO[top[0]].name}". Focus corrections on this pattern: ${STRAIN_INFO[top[0]].tips[0].toLowerCase()}.`);
  }
  if (r.peakLoad >= 40) lines.push(`Estimated peak cervical load reached ${r.peakLoad} lbs, well above the ~11 lbs neutral baseline. Sustained loads like this accelerate neck fatigue.`);
  if (r.alerts >= 5) lines.push(`${r.alerts} strain episodes were recorded; consider a short mobility break every 30-45 minutes.`);
  lines.push("Values are estimates from a single wearable sensor for ergonomic guidance only and are not a medical diagnosis.");
  return lines;
}

function pickReportRecord() {
  if (rec) { const s = snapshotRecord(rec); if (s.duration >= 5) return s; }
  return sessions.find(s => !s.summaryOnly) || null;
}

function renderTrendImage(r) {
  if (!r.trend || r.trend.pitch.length < 2) return null;
  try {
    const c = document.createElement("canvas");
    if (!drawSessionChart(c, r, 720, 200, 2)) return null;
    return { data: c.toDataURL("image/png"), w: 720, h: 200 };
  } catch (_) { return null; }
}

function buildPdfReport(Ctor, r) {
  const doc = new Ctor({ unit: "mm", format: "a4" });
  const W = 210, M = 14, CW = W - 2 * M, x = recTimes(r);
  let y = 0;
  const ensure = h => { if (y + h > 282) { doc.addPage(); y = 18; } };
  const heading = t => { ensure(16); doc.setFont("helvetica", "bold"); doc.setFontSize(12); doc.setTextColor(15, 23, 42); doc.text(pdfSafe(t), M, y); y += 2.5; doc.setDrawColor(203, 213, 225); doc.setLineWidth(0.3); doc.line(M, y, W - M, y); y += 7; };
  const kvRow = (a, b) => { ensure(7); doc.setFont("helvetica", "normal"); doc.setFontSize(10); doc.setTextColor(100, 116, 139); doc.text(pdfSafe(a), M + 2, y); doc.setFont("helvetica", "bold"); doc.setTextColor(15, 23, 42); doc.text(pdfSafe(b), M + 62, y); y += 6.5; };

  doc.setFillColor(7, 13, 24); doc.rect(0, 0, W, 34, "F");
  doc.setTextColor(255, 255, 255); doc.setFont("helvetica", "bold"); doc.setFontSize(19);
  doc.text("BioSpine Clinical Posture Report", M, 16);
  doc.setFont("helvetica", "normal"); doc.setFontSize(9.5); doc.setTextColor(148, 163, 184);
  doc.text(pdfSafe(`Patient profile: ${currentUser || "guest"}   |   Generated ${new Date().toLocaleString()}`), M, 25);
  y = 46;

  heading("Session summary");
  kvRow("Session start", fmtStamp(r.start));
  kvRow("Session end", fmtStamp(r.end));
  kvRow("Time monitored", formatSec(x.t));
  kvRow("Data source", (r.source === "demo" ? "DEMO (simulated data)" : "Wearable sensor") + (r.transport ? ` via ${r.transport}` : ""));
  kvRow("Ergonomic preset", String(r.mode || "-").toUpperCase());
  kvRow("Alert thresholds", `Sagittal ${r.angle}°  |  Lateral ${r.lateral}°  |  Safe-zone ±${r.safeZone}°`);
  y += 3;

  heading("Key performance indicators");
  ensure(26);
  const tiles = [["Posture compliance", `${r.score}%`], ["Time in neutral", formatSec(x.c)], ["Needs correction", formatSec(x.t - x.c)], ["Strain episodes", String(r.alerts)]];
  const tw = (CW - 3 * 4) / 4;
  tiles.forEach(([label, val], i) => {
    const tx = M + i * (tw + 4);
    doc.setFillColor(241, 245, 249); doc.roundedRect(tx, y, tw, 22, 2, 2, "F");
    doc.setFont("helvetica", "bold"); doc.setFontSize(15);
    if (i === 0) { const c = r.score >= 80 ? [22, 163, 74] : r.score >= 60 ? [217, 119, 6] : [220, 38, 38]; doc.setTextColor(c[0], c[1], c[2]); } else doc.setTextColor(15, 23, 42);
    doc.text(pdfSafe(val), tx + tw / 2, y + 11, { align: "center" });
    doc.setFont("helvetica", "normal"); doc.setFontSize(8); doc.setTextColor(100, 116, 139);
    doc.text(pdfSafe(label), tx + tw / 2, y + 18, { align: "center" });
  });
  y += 30;

  heading("Deviation statistics (whole session)");
  kvRow("Mean sagittal deviation", `${Number(r.avg).toFixed(1)}°`);
  kvRow("Median sagittal deviation", `${Number(r.median).toFixed(1)}°`);
  kvRow("Peak sagittal deviation", `${Number(r.max).toFixed(1)}°`);
  kvRow("Mean / peak lateral tilt", `${Number(r.avgRoll).toFixed(1)}° / ${Number(r.maxRoll).toFixed(1)}°`);
  kvRow("Est. peak cervical load", `${r.peakLoad} lbs (${(r.peakLoad * 0.4536).toFixed(1)} kg)`);
  kvRow("Longest neutral streak", formatSec(r.longestStreak));
  kvRow("Telemetry samples", String(r.samples));
  y += 3;

  heading("Anatomical strain distribution");
  const strainSum = Object.values(r.strain).reduce((a, b) => a + b, 0);
  ["forward", "backward", "right", "left"].forEach(k => {
    ensure(9);
    const v = r.strain[k] || 0, pct = x.t > 0 ? (v / x.t) * 100 : 0;
    doc.setFont("helvetica", "normal"); doc.setFontSize(10); doc.setTextColor(15, 23, 42);
    doc.text(pdfSafe(STRAIN_INFO[k].name), M + 2, y);
    doc.text(pdfSafe(`${formatSec(v)}  (${pct.toFixed(1)}% of monitored time)`), M + 70, y);
    doc.setFillColor(226, 232, 240); doc.rect(M + 142, y - 3, 40, 3.4, "F");
    if (pct > 0) { doc.setFillColor(244, 63, 94); doc.rect(M + 142, y - 3, Math.max(0.8, (Math.min(100, pct) / 100) * 40), 3.4, "F"); }
    y += 7;
  });
  if (strainSum < 1) { doc.setFontSize(9); doc.setTextColor(100, 116, 139); doc.text("No out-of-posture time was recorded in this session.", M + 2, y); y += 6; }
  y += 3;

  const img = renderTrendImage(r);
  if (img) {
    heading("Forward lean during the session");
    const ih = (CW * img.h) / img.w;
    ensure(ih + 10);
    doc.addImage(img.data, "PNG", M, y, CW, ih);
    y += ih + 3;
    doc.setFont("helvetica", "normal"); doc.setFontSize(8); doc.setTextColor(100, 116, 139);
    doc.text(`Dashed red lines mark the +/-${r.angle}° strain threshold; shaded bands show time out of posture.`, M, y + 3);
    y += 10;
  }

  heading("Incident log");
  const evs = r.events || [];
  if (!evs.length) { doc.setFont("helvetica", "normal"); doc.setFontSize(9); doc.setTextColor(100, 116, 139); doc.text("Nothing to report - well done!", M + 2, y); y += 7; }
  evs.slice(0, 40).forEach(e => {
    ensure(6.5);
    doc.setFont("helvetica", "normal"); doc.setFontSize(9);
    doc.setTextColor(100, 116, 139); doc.text(pdfSafe(new Date(e.t).toLocaleTimeString()), M + 2, y);
    doc.setTextColor(e.type === "good" ? 22 : 220, e.type === "good" ? 163 : 38, e.type === "good" ? 74 : 38); doc.text(e.type === "good" ? "Recovered" : "Strain", M + 28, y);
    doc.setTextColor(15, 23, 42); doc.text(pdfSafe(`${e.title} - ${e.detail}`).slice(0, 88), M + 48, y);
    y += 5.5;
  });
  if (evs.length > 40) { ensure(6); doc.setFontSize(8); doc.setTextColor(100, 116, 139); doc.text(`+ ${evs.length - 40} more events available in the app.`, M + 2, y); y += 6; }
  y += 3;

  heading("Interpretation");
  doc.setFont("helvetica", "normal"); doc.setFontSize(10); doc.setTextColor(30, 41, 59);
  interpretation(r).forEach(line => {
    const parts = doc.splitTextToSize(pdfSafe(line), CW - 4);
    ensure(parts.length * 5 + 2);
    doc.text(parts, M + 2, y); y += parts.length * 5 + 2;
  });

  if (currentUser) {
    heading("AI Physio Q&A Log");
    if (!chatHistory.length) {
      doc.setFont("helvetica", "normal"); doc.setFontSize(9); doc.setTextColor(100, 116, 139);
      doc.text("No questions were asked to the AI Physio for this account yet.", M + 2, y); y += 7;
    } else {
      chatHistory.slice(0, 15).forEach(c => {
        const qLines = doc.splitTextToSize(pdfSafe(`Q: ${c.question}`), CW - 4);
        const aLines = doc.splitTextToSize(pdfSafe(`A: ${c.answer}`), CW - 4);
        ensure(qLines.length * 4.6 + aLines.length * 4.6 + 8);
        doc.setFont("helvetica", "bold"); doc.setFontSize(9.5); doc.setTextColor(37, 99, 235);
        doc.text(qLines, M + 2, y); y += qLines.length * 4.6;
        doc.setFont("helvetica", "normal"); doc.setFontSize(9.5); doc.setTextColor(30, 41, 59);
        doc.text(aLines, M + 2, y); y += aLines.length * 4.6 + 1;
        doc.setFontSize(7.5); doc.setTextColor(140, 150, 165);
        doc.text(pdfSafe(fmtStamp(c.date)), M + 2, y); y += 6;
      });
    }
    y += 2;
  }

  const pages = doc.getNumberOfPages();
  for (let i = 1; i <= pages; i++) {
    doc.setPage(i); doc.setFont("helvetica", "normal"); doc.setFontSize(8); doc.setTextColor(140, 150, 165);
    doc.text("BioSpine wearable  |  Estimated values for ergonomic guidance - not a medical diagnosis", M, 290);
    doc.text(`Page ${i} of ${pages}`, W - M, 290, { align: "right" });
  }
  return doc;
}

function printReportHtml(r) {
  const x = recTimes(r);
  const rows = (arr) => arr.map(([a, b]) => `<tr><td>${esc(a)}</td><td><b>${esc(b)}</b></td></tr>`).join("");
  const html = `<!doctype html><html><head><meta charset="utf-8"><title>BioSpine Clinical Posture Report</title>
  <style>body{font-family:Arial,sans-serif;margin:28px;color:#0f172a}h1{margin:0 0 4px}h2{border-bottom:1px solid #cbd5e1;padding-bottom:4px;margin-top:22px}table{border-collapse:collapse;width:100%}td{padding:4px 8px;border-bottom:1px solid #e2e8f0}small{color:#64748b}</style></head><body>
  <h1>BioSpine Clinical Posture Report</h1><small>Patient profile: ${esc(currentUser || "guest")} | Generated ${esc(new Date().toLocaleString())}</small>
  <h2>Session summary</h2><table>${rows([["Start", fmtStamp(r.start)], ["End", fmtStamp(r.end)], ["Time monitored", formatSec(x.t)], ["Source", r.source === "demo" ? "DEMO (simulated)" : "Wearable sensor"], ["Preset", String(r.mode || "-")], ["Thresholds", `Sagittal ${r.angle}° / Lateral ${r.lateral}° / Safe-zone ±${r.safeZone}°`]])}</table>
  <h2>Key indicators</h2><table>${rows([["Posture compliance", r.score + "%"], ["Time in neutral", formatSec(x.c)], ["Needs correction", formatSec(x.t - x.c)], ["Strain episodes", String(r.alerts)], ["Mean / median / peak sagittal", `${r.avg}° / ${r.median}° / ${r.max}°`], ["Mean / peak lateral", `${r.avgRoll}° / ${r.maxRoll}°`], ["Est. peak cervical load", r.peakLoad + " lbs"], ["Longest neutral streak", formatSec(r.longestStreak)], ["Samples", String(r.samples)]])}</table>
  <h2>Strain distribution</h2><table>${rows(["forward", "backward", "right", "left"].map(k => [STRAIN_INFO[k].name, `${formatSec(r.strain[k] || 0)} (${x.t > 0 ? (((r.strain[k] || 0) / x.t) * 100).toFixed(1) : 0}%)`]))}</table>
  <h2>Interpretation</h2>${interpretation(r).map(l => `<p>${esc(l)}</p>`).join("")}
  <h2>AI Physio Q&amp;A log</h2>${chatHistory.length
    ? chatHistory.slice(0, 30).map(c => `<div style="margin-bottom:10px"><p style="margin:0"><b>Q:</b> ${esc(c.question)}</p><p style="margin:0"><b>A:</b> ${esc(c.answer)}</p><small>${esc(fmtStamp(c.date))}</small></div>`).join("")
    : "<p>No questions were asked to the AI Physio for this account yet.</p>"}
  </body></html>`;
  const w = window.open("", "_blank");
  if (!w) { toast("Allow pop-ups to open the printable report"); return; }
  w.document.open(); w.document.write(html); w.document.close();
  setTimeout(() => { try { w.focus(); w.print(); } catch (_) {} }, 400);
  toast("PDF library unavailable - opened a printable report (choose Save as PDF)");
}

function exportClinicalPdfReport(recordOverride) {
  const r = recordOverride && recordOverride.id ? recordOverride : pickReportRecord();
  if (!r) { toast(rec ? "This session just started - give it a few more seconds of data, then export again." : "No posture data yet - connect your device (or start demo data) first."); return; }
  if (r.summaryOnly) { toast("Only a server summary exists for this session - no detailed data for a full report."); return; }
  const Ctor = window.jspdf && window.jspdf.jsPDF;
  if (!Ctor) { printReportHtml(r); return; }
  try {
    const doc = buildPdfReport(Ctor, r);
    doc.save(`BioSpine_Report_${new Date(r.start).toISOString().slice(0, 16).replace(/[:T]/g, "-")}.pdf`);
    toast("Clinical report downloaded");
  } catch (e) {
    console.error("[BioSpine] PDF build failed", e);
    printReportHtml(r);
  }
}

// ==========================================================
// 22. AI DIAGNOSIS (uses whole-session statistics)
// ==========================================================
async function requestAiDiagnosis() {
  const r = rec ? snapshotRecord(rec) : sessions.find(s => !s.summaryOnly);
  if (!r || r.duration < 10) {
    alert("Collect at least 1–2 minutes of posture monitoring before requesting AI analysis.");
    return;
  }
  if (isGuest || !sessionToken) { $("aiOutputContainer").innerHTML = "<p style='color:var(--muted)'>Create a free account to generate an AI diagnosis.</p>"; return; }
  $("aiLoadingState").style.display = "flex";
  $("aiOutputContainer").innerHTML = "";
  $("generateAiReportBtn").disabled = true;
  try {
    const { res, data: d } = await api("/api/ai/diagnose", {
      method: "POST",
      body: {
        duration: formatSec(r.duration), compliance: r.score, avgDev: r.avg.toFixed(1), maxDev: r.max.toFixed(1), alerts: r.alerts,
        neckLoad: `${r.peakLoad} lbs (peak)`,
        postureBreakdown: Object.fromEntries(Object.entries(r.strain).map(([k, v]) => [k, Math.round(v) + "s"])),
        mode: String(userSettings.mode).toUpperCase()
      }
    });
    $("aiLoadingState").style.display = "none";
    if (res.ok && d.success) { $("aiOutputContainer").innerHTML = d.html; toast("AI Ergonomic Diagnosis Ready"); }   // html is built & escaped on the server
    else $("aiOutputContainer").innerHTML = `<div style="color:var(--red); padding:10px;">⚠ ${esc(d.error || "The AI is unavailable right now. Please try again shortly.")}</div>`;
  } catch (e) {
    $("aiLoadingState").style.display = "none";
    $("aiOutputContainer").innerHTML = "<div style='color:var(--red); padding:10px;'>⚠ Could not connect. Check your internet connection and try again.</div>";
  } finally {
    $("generateAiReportBtn").disabled = false;
  }
}

window.addEventListener("load", () => setTimeout(updateStats, 0));   // first paint of the dashboard stats (dashes until data arrives)


// ==========================================================
// 23. v4: GOALS, BADGES, PROGRESS, ACCOUNT, PWA, COMPATIBILITY
// ==========================================================
let lastGoalAt = 0, lastBreakAt = 0;

function todaySeconds() {
  const key = dayKey(new Date());
  return allRecords().reduce((a, s) => a + (dayKey(new Date(s.start)) === key ? (s.duration || 0) : 0), 0);
}

const BADGES = [
  { id: "first",   icon: "🌱", name: "First session",  test: c => c.count >= 1 },
  { id: "hour",    icon: "⏱",  name: "1-hour session", test: c => c.longest >= 3600 },
  { id: "sharp",   icon: "🎯", name: "90%+ session",   test: c => c.bestScore >= 90 },
  { id: "s3",      icon: "🔥", name: "3-day streak",   test: c => c.bestStreak >= 3 },
  { id: "s7",      icon: "🏅", name: "7-day streak",   test: c => c.bestStreak >= 7 },
  { id: "s30",     icon: "🏆", name: "30-day streak",  test: c => c.bestStreak >= 30 },
  { id: "h10",     icon: "💪", name: "10 hours worn",  test: c => c.totalSec >= 36000 },
  { id: "h50",     icon: "🦾", name: "50 hours worn",  test: c => c.totalSec >= 180000 },
  { id: "goal",    icon: "✅", name: "Daily goal hit", test: c => c.goalHit }
];

function renderGoalAndBadges() {
  if (!$("goalFill")) return;
  const goalMin = userSettings.dailyGoal || 120;
  const sec = todaySeconds();
  const pct = Math.min(100, Math.round((sec / 60 / goalMin) * 100));
  $("goalFill").style.width = pct + "%";
  $("goalPct").textContent = pct + "%";
  $("goalText").textContent = `${Math.floor(sec / 60)} / ${goalMin} min`;
  $("goalNote").textContent = pct >= 100 ? "Goal reached - great work!" : "Wear time today";
  if ($("goalSelect") && document.activeElement !== $("goalSelect")) $("goalSelect").value = String(goalMin);

  const all = allRecords();
  const ctx = {
    count: all.length,
    longest: Math.max(0, ...all.map(s => s.duration || 0)),
    bestScore: Math.max(0, ...all.filter(s => (s.duration || 0) >= 600).map(s => s.score || 0)),
    totalSec: all.reduce((a, s) => a + (s.duration || 0), 0),
    bestStreak: Math.max(userStreak.longest || 0, userStreak.current || 0),
    goalHit: pct >= 100
  };
  $("badgeRow").innerHTML = BADGES.map(b => {
    const got = b.test(ctx);
    return `<span class="badge-chip ${got ? "got" : ""}" title="${esc(b.name)}${got ? "" : " (locked)"}"><i>${b.icon}</i>${esc(b.name)}</span>`;
  }).join("");
}

function renderProgress() {
  const box = $("progressCompare");
  if (!box) return;
  const all = allRecords().filter(s => (s.duration || 0) >= 30);
  if (!all.length) return;
  const DAY = 86400000;
  const starts = all.map(s => s.start);
  const first = Math.min(...starts), last = Math.max(...starts);
  const span = Math.floor((last - first) / DAY) + 1;
  if (span < 4) {
    box.innerHTML = `<div class="empty">You have ${span} day${span === 1 ? "" : "s"} of data. Keep going - your before/after comparison appears once you have about a week.</div>`;
    return;
  }
  const w = Math.min(7, Math.floor(span / 2));
  const agg = list => { let c = 0, t = 0; list.forEach(s => { const x = recTimes(s); c += x.c; t += x.t; }); return { n: list.length, score: t > 0 ? Math.round((c / t) * 100) : null, hrs: t / 3600 }; };
  const A = agg(all.filter(s => s.start < first + w * DAY));
  const B = agg(all.filter(s => s.start >= last - (w - 1) * DAY - (last % DAY)));
  if (A.score === null || B.score === null) return;
  const d = B.score - A.score;
  const cls = d > 0 ? "up" : d < 0 ? "down" : "flat";
  box.innerHTML = `
    <div class="cmp-card"><small>First ${w} days</small><b>${A.score}%</b><span>${A.n} sessions · ${A.hrs.toFixed(1)} h</span></div>
    <div class="cmp-arrow ${cls}">${d > 0 ? "▲" : d < 0 ? "▼" : "■"}<b>${d > 0 ? "+" : ""}${d} pts</b></div>
    <div class="cmp-card"><small>Latest ${w} days</small><b>${B.score}%</b><span>${B.n} sessions · ${B.hrs.toFixed(1)} h</span></div>
    <p class="cmp-note">${d > 5 ? "Your posture is clearly improving. Keep the habit going!" : d >= 0 ? "Holding steady. Try a slightly stricter warning angle to keep progressing." : "Posture slipped a little. Short breaks every 30 minutes help a lot."}</p>`;
}

// ---------- older sessions (paging) ----------
function updateLoadMore() {
  const btn = $("loadMoreSessionsBtn");
  if (btn) btn.hidden = isGuest || serverLoaded >= serverTotal;
}

async function loadMoreSessions() {
  const btn = $("loadMoreSessionsBtn");
  if (btn) btn.disabled = true;
  try {
    const { data } = await api(`/api/user/sessions?offset=${serverLoaded}&limit=50`);
    if (data.success) {
      sessions = mergeServerSessions(sessions, data.sessions);
      serverLoaded = data.nextOffset; serverTotal = data.total;
      renderHistory(); renderAnalytics(); renderProgress(); renderGoalAndBadges();
    }
  } catch (_) { toast("Could not load older sessions."); }
  if (btn) btn.disabled = false;
  updateLoadMore();
}

// ---------- account & privacy ----------
function updateAccountUI() {
  const verified = emailVerified || isGuest;
  if ($("verifyBanner")) $("verifyBanner").hidden = verified;
  if ($("guestBanner")) $("guestBanner").hidden = !isGuest;
  if ($("accountPanel")) $("accountPanel").style.display = isGuest ? "none" : "";
  if ($("acctEmail")) $("acctEmail").textContent = currentUser;
  if ($("acctVerified")) { $("acctVerified").textContent = emailVerified ? "✓ verified" : "not verified"; $("acctVerified").className = emailVerified ? "pill-ok" : "pill-warn"; }
  if ($("weeklyToggle")) $("weeklyToggle").checked = userSettings.weeklyEmail !== false;
}

function clearAccountLocalData(email) {
  try {
    const prefix = `biospine:${STORE_VER}:${String(email).toLowerCase()}:`;
    Object.keys(localStorage).filter(k => k.startsWith(prefix)).forEach(k => localStorage.removeItem(k));
  } catch (_) {}
}

function bindAccountUI() {
  if ($("guestSignupBtn")) $("guestSignupBtn").onclick = () => { handleSignOutToRegister(); };
  if ($("signOutBtn2")) $("signOutBtn2").onclick = handleSignOut;
  if ($("resendVerifyBtn")) $("resendVerifyBtn").onclick = async () => {
    try { const { data } = await api("/api/auth/resend-verification", { method: "POST", body: {} }); toast(data.message || data.error || "Done"); }
    catch (_) { toast("Could not reach the server."); }
  };
  if ($("weeklyToggle")) $("weeklyToggle").onchange = e => { userSettings.weeklyEmail = e.target.checked; syncSettings(); toast(e.target.checked ? "Weekly email on" : "Weekly email off"); };
  if ($("goalSelect")) $("goalSelect").onchange = e => { userSettings.dailyGoal = Number(e.target.value); syncSettings(); renderGoalAndBadges(); };
  if ($("pwChangeBtn")) $("pwChangeBtn").onclick = async () => {
    const cur = $("pwCurrent").value, neu = $("pwNew").value;
    if (!cur || neu.length < 8) { toast("Enter your current password and a new one (min. 8 characters)."); return; }
    try {
      const { res, data } = await api("/api/auth/change-password", { method: "POST", body: { current: cur, new: neu } });
      if (res.ok && data.success) { $("pwCurrent").value = ""; $("pwNew").value = ""; toast("Password updated. Other devices were signed out."); }
      else toast(data.error || "Could not change the password.");
    } catch (_) { toast("Could not reach the server."); }
  };
  if ($("exportDataBtn")) $("exportDataBtn").onclick = async () => {
    try {
      const res = await fetch("/api/user/export", { headers: { Authorization: "Bearer " + sessionToken } });
      if (!res.ok) { toast("Could not download your data."); return; }
      const blob = await res.blob(), a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = "biospine_my_data.json";
      document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    } catch (_) { toast("Could not reach the server."); }
  };
  if ($("deleteAccountBtn")) $("deleteAccountBtn").onclick = async () => {
    const pw = $("delPassword").value;
    if (!pw) { toast("Enter your password to confirm."); return; }
    if (!confirm("Permanently delete your account, history and AI chats? This cannot be undone.")) return;
    try {
      const { res, data } = await api("/api/auth/delete", { method: "POST", body: { password: pw } });
      if (res.ok && data.success) {
        clearAccountLocalData(currentUser);
        localStorage.removeItem("biospine_active_user"); localStorage.removeItem("biospine_session_token");
        alert("Your account and data were deleted.");
        location.reload();
      } else toast(data.error || "Could not delete the account.");
    } catch (_) { toast("Could not reach the server."); }
  };
}

function handleSignOutToRegister() {
  if (demoTimer) { clearInterval(demoTimer); demoTimer = null; }
  clearGuestData();
  try { sessionStorage.setItem("bs_open_register", "1"); } catch (_) {}
  location.reload();
}

// ---------- PWA ----------
function registerServiceWorker() {
  if ("serviceWorker" in navigator && location.protocol !== "file:") navigator.serviceWorker.register("/sw.js").catch(() => {});
}

function setupInstallPrompt() {
  const dismissed = () => { try { return localStorage.getItem("biospine_install_dismissed") === "1"; } catch (_) { return false; } };
  const standalone = window.matchMedia && (window.matchMedia("(display-mode: standalone)").matches || navigator.standalone);
  window.addEventListener("beforeinstallprompt", e => {
    e.preventDefault(); deferredInstall = e;
    if ($("installBtn2")) $("installBtn2").hidden = false;
    if (!dismissed() && $("installBanner") && !standalone) $("installBanner").hidden = false;
  });
  window.addEventListener("appinstalled", () => { deferredInstall = null; if ($("installBanner")) $("installBanner").hidden = true; if ($("installBtn2")) $("installBtn2").hidden = true; toast("BioSpine installed!"); });
  const doInstall = async () => {
    if (!deferredInstall) return;
    deferredInstall.prompt();
    try { await deferredInstall.userChoice; } catch (_) {}
    deferredInstall = null;
    if ($("installBanner")) $("installBanner").hidden = true;
    if ($("installBtn2")) $("installBtn2").hidden = true;
  };
  if ($("installBtn")) $("installBtn").onclick = doInstall;
  if ($("installBtn2")) $("installBtn2").onclick = doInstall;
  if ($("installDismiss")) $("installDismiss").onclick = () => { $("installBanner").hidden = true; try { localStorage.setItem("biospine_install_dismissed", "1"); } catch (_) {} };
  // iPhone/iPad Safari never fires beforeinstallprompt: show a how-to hint once
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent) && !window.MSStream;
  if (ios && !standalone && !dismissed() && $("installBanner")) {
    $("installBanner").querySelector("span").textContent = "📲 To install: tap the Share button, then “Add to Home Screen”.";
    if ($("installBtn")) $("installBtn").style.display = "none";
    $("installBanner").hidden = false;
  }
}

// ---------- device / browser compatibility ----------
function applyCompat() {
  const notes = [];
  if (!navigator.bluetooth) notes.push("This browser can't pair over Bluetooth (iPhone/iPad browsers and Firefox don't support Web Bluetooth). Use Chrome or Edge on Android or desktop, or try the demo data below.");
  if (location.protocol === "https:") notes.push("Wi-Fi direct mode only works when the app is opened over http:// on your local network - browsers block it on secure pages.");
  const el = $("compatNote");
  if (el) { el.hidden = !notes.length; el.innerHTML = notes.map(n => "ℹ️ " + esc(n)).join("<br>"); }
  if (!("serial" in navigator)) { ["serialBtn", "deviceConnectUsb"].forEach(id => { if ($(id)) $(id).style.display = "none"; }); }
  if (!("documentPictureInPicture" in window) && $("pipBtn")) $("pipBtn").style.display = "none";
}

window.onload = init;
