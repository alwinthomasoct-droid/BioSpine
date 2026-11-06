/**
 * BioSpine v5 extras: light/dark theme, interactive home page, rewards (XP / levels / quests / badges),
 * back-break reminders, Posture Lab, one-time review prompt, Excel + PDF reports, live device gauges.
 * Loaded after app.js and uses its globals ($, sessions, userSettings, storeGet, toast, bsHooks ...).
 */
"use strict";
(function () {
  const q = (sel, root) => (root || document).querySelector(sel);
  const qa = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const E = s => (typeof esc === "function" ? esc(s) : String(s ?? ""));
  const reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const aiOn = () => document.body.dataset.ai === "1";

  // =====================================================================
  // 1. THEME (light / dark)
  // =====================================================================
  function currentTheme() { return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark"; }
  function applyTheme(t) {
    document.documentElement.setAttribute("data-theme", t);
    try { localStorage.setItem("biospine_theme", t); } catch (_) {}
    const m = q('meta[name="theme-color"]'); if (m) m.setAttribute("content", t === "light" ? "#f1f5fb" : "#070d18");
    qa("[data-theme-toggle]").forEach(b => {
      const side = b.classList.contains("side");
      b.textContent = t === "light" ? (side ? "🌙 Dark" : "🌙") : (side ? "☀️ Light" : "☀️");
      b.setAttribute("title", t === "light" ? "Switch to dark mode" : "Switch to light mode");
    });
    // canvases read their colours when they draw, so draw them again
    try { if (typeof updateCharts === "function" && q("#appShell").style.display !== "none") updateCharts(); } catch (_) {}
    try { if (typeof activeView !== "undefined" && activeView === "analytics") renderAnalytics(); } catch (_) {}
  }
  function initTheme() {
    qa("[data-theme-toggle]").forEach(b => b.addEventListener("click", () => applyTheme(currentTheme() === "light" ? "dark" : "light")));
    applyTheme(currentTheme());
  }

  // =====================================================================
  // 2. HOME PAGE (counters, playable demo, slides, flip cards, reviews)
  // =====================================================================
  const NECK_TABLE = [[0, 12], [15, 27], [30, 40], [45, 49], [60, 60]];
  function neckLoad(deg) {
    deg = clamp(Math.abs(deg), 0, 60);
    for (let i = 1; i < NECK_TABLE.length; i++) {
      if (deg <= NECK_TABLE[i][0]) {
        const [d0, l0] = NECK_TABLE[i - 1], [d1, l1] = NECK_TABLE[i];
        return l0 + ((deg - d0) / (d1 - d0)) * (l1 - l0);
      }
    }
    return 60;
  }
  const likeWhat = lbs => lbs < 15 ? "a bowling ball" : lbs < 30 ? "a 2-year-old child" : lbs < 45 ? "a big bag of dog food" : "a heavy suitcase";
  const tone = deg => deg < 8 ? "good" : deg < 20 ? "warn" : "bad";

  function initCounters() {
    const els = qa(".stat-chip b[data-count]");
    const run = el => {
      const to = +el.dataset.count, suf = el.dataset.suffix || "";
      if (reduced) { el.textContent = to + suf; return; }
      const t0 = performance.now();
      const step = t => { const k = clamp((t - t0) / 1100, 0, 1); el.textContent = Math.round(to * (1 - Math.pow(1 - k, 3))) + suf; if (k < 1) requestAnimationFrame(step); };
      requestAnimationFrame(step);
    };
    if ("IntersectionObserver" in window) {
      const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { run(e.target); io.unobserve(e.target); } }), { threshold: .4 });
      els.forEach(e => io.observe(e));
    } else els.forEach(run);
  }

  function initHomeDemo() {
    const box = q("#homeDemo"), r = q("#demoRange");
    if (!box || !r) return;
    const msgs = { good: "Perfect! Your head sits right over your shoulders.", warn: "Careful: your neck is working harder now. Lift your chin and screen.", bad: "Ouch! That is a lot of weight on your neck. A BioSpine buzz would remind you now." };
    const upd = () => {
      const d = +r.value, lbs = Math.round(neckLoad(d)), t = tone(d);
      q("#demoHead").style.transform = `rotate(${d * 0.9}deg)`;
      q("#demoDeg").textContent = d + "°"; q("#demoLbs").textContent = lbs + " lbs"; q("#demoAnimal").textContent = "like " + likeWhat(lbs);
      box.classList.remove("good", "warn", "bad"); box.classList.add(t); q("#demoMsg").textContent = msgs[t];
    };
    r.addEventListener("input", upd); upd();
  }

  function initSlider() {
    const root = q("#homeSlider"); if (!root) return;
    const track = q(".slides", root), slides = qa(".slide", root), dots = q(".slider-dots", root);
    let i = 0, timer = null;
    slides.forEach((_, n) => { const b = document.createElement("button"); b.type = "button"; b.setAttribute("aria-label", "Slide " + (n + 1)); b.addEventListener("click", () => go(n, true)); dots.appendChild(b); });
    function go(n, user) { i = (n + slides.length) % slides.length; track.style.transform = `translateX(-${i * 100}%)`; qa("button", dots).forEach((b, k) => b.classList.toggle("on", k === i)); if (user) restart(); }
    function restart() { clearInterval(timer); if (!reduced) timer = setInterval(() => go(i + 1), 6500); }
    q(".prev", root).addEventListener("click", () => go(i - 1, true)); q(".next", root).addEventListener("click", () => go(i + 1, true));
    root.addEventListener("mouseenter", () => clearInterval(timer)); root.addEventListener("mouseleave", restart);
    let x0 = null;
    root.addEventListener("touchstart", e => { x0 = e.touches[0].clientX; }, { passive: true });
    root.addEventListener("touchend", e => { if (x0 === null) return; const dx = e.changedTouches[0].clientX - x0; x0 = null; if (Math.abs(dx) > 45) go(i + (dx < 0 ? 1 : -1), true); }, { passive: true });
    go(0); restart();
  }

  function initFlipCards() { qa(".flip-card").forEach(c => c.addEventListener("click", () => c.classList.toggle("flipped"))); }

  async function loadHomeReviews() {
    const track = q("#reviewTrack"); if (!track) return;
    try {
      const res = await fetch("/api/reviews"); const d = await res.json();
      if (!d.success || !d.reviews.length) return;
      q("#reviewEmpty").hidden = true;
      const sum = q("#reviewSummary");
      if (d.average) { sum.hidden = false; sum.innerHTML = `<b>${d.average}</b> ★ average from ${d.count} review${d.count === 1 ? "" : "s"}`; }
      track.innerHTML = d.reviews.map(r => `<article class="review-card-item"><div class="stars-static" aria-label="${r.rating} out of 5 stars">${"★".repeat(r.rating)}${"☆".repeat(5 - r.rating)}</div><p>${r.comment ? "“" + E(r.comment) + "”" : "<i>(rated BioSpine without a comment)</i>"}</p><footer>${E(r.name)}</footer></article>`).join("");
    } catch (_) { /* the home page still works without reviews */ }
  }

  // =====================================================================
  // 3. SMALL HELPERS shared by the app screens
  // =====================================================================
  const get = (name, fb) => { try { return typeof storeGet === "function" ? storeGet(name, fb) : fb; } catch (_) { return fb; } };
  const put = (name, v) => { try { if (typeof storeSet === "function") storeSet(name, v); } catch (_) {} };
  const dayStr = d => { d = d || new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
  const hhmm = s => { s = Math.max(0, Math.round(s)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
  const recs = () => { try { return allRecords().filter(r => r && (r.duration || 0) >= 5 && (isGuest || r.source !== "demo")); } catch (_) { return []; } };
  const lbl = n => ({ forward: "Forward slouch", backward: "Leaning back", left: "Leaning left", right: "Leaning right" }[n] || n);

  function ex() { const e = get("extras", null) || {}; return { breaks: 0, breakXp: 0, breakDays: {}, quizBest: 0, quizDays: {}, quests: {}, earned: {}, lastLevel: 0, ...e }; }
  // Progress follows the account: the same merge rules as the server (numbers take the larger value, days and badges are combined).
  function mergeEx(a, b) {
    a = { breaks: 0, breakXp: 0, quizBest: 0, lastLevel: 0, breakDays: {}, quizDays: {}, quests: {}, earned: {}, ...(a || {}) };
    b = { breaks: 0, breakXp: 0, quizBest: 0, lastLevel: 0, breakDays: {}, quizDays: {}, quests: {}, earned: {}, ...(b || {}) };
    const out = {};
    ["breaks", "breakXp", "quizBest", "lastLevel"].forEach(k => { out[k] = Math.max(+a[k] || 0, +b[k] || 0); });
    out.breakDays = {}; Object.keys({ ...a.breakDays, ...b.breakDays }).forEach(k => { out.breakDays[k] = Math.max(a.breakDays[k] || 0, b.breakDays[k] || 0); });
    out.quizDays = { ...a.quizDays, ...b.quizDays };
    out.quests = {}; Object.keys({ ...a.quests, ...b.quests }).forEach(k => { out.quests[k] = Array.from(new Set([...(a.quests[k] || []), ...(b.quests[k] || [])])); });
    out.earned = { ...b.earned }; Object.keys(a.earned).forEach(k => { out.earned[k] = out.earned[k] && out.earned[k] < a.earned[k] ? out.earned[k] : a.earned[k]; });
    return out;
  }
  let pushTimer = null;
  function pushExtras() {
    if (typeof isGuest === "undefined" || isGuest || !sessionToken) return;
    clearTimeout(pushTimer);
    pushTimer = setTimeout(async () => { try { await api("/api/user/extras", { method: "POST", body: { extras: ex() } }); } catch (_) {} }, 1500);
  }
  function saveEx(e) { put("extras", e); pushExtras(); }
  let serverXp = 0, serverStats = null;

  document.addEventListener("click", e => {
    const g = e.target.closest("[data-goto]");
    if (g && typeof showView === "function") { e.preventDefault(); showView(g.dataset.goto); }
  });

  // confetti burst (no library)
  function confetti(n) {
    if (reduced) return;
    const c = q("#confetti"); if (!c) return;
    const ctx = c.getContext("2d"); c.width = innerWidth; c.height = innerHeight;
    const cols = ["#6366f1", "#22d3ee", "#34d399", "#fbbf24", "#f43f5e", "#a855f7"];
    const ps = Array.from({ length: n || 120 }, () => ({ x: innerWidth / 2 + (Math.random() - .5) * 200, y: innerHeight * .35, vx: (Math.random() - .5) * 13, vy: -Math.random() * 12 - 4, s: 5 + Math.random() * 6, r: Math.random() * 6, vr: (Math.random() - .5) * .4, c: cols[(Math.random() * cols.length) | 0], life: 0 }));
    let f = 0;
    (function frame() {
      ctx.clearRect(0, 0, c.width, c.height); f++;
      ps.forEach(p => { p.vy += .35; p.x += p.vx; p.y += p.vy; p.r += p.vr; ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.r); ctx.fillStyle = p.c; ctx.globalAlpha = clamp(1 - f / 120, 0, 1); ctx.fillRect(-p.s / 2, -p.s / 3, p.s, p.s * .66); ctx.restore(); });
      if (f < 125) requestAnimationFrame(frame); else ctx.clearRect(0, 0, c.width, c.height);
    })();
  }
  window.bsConfetti = confetti;

  // =====================================================================
  // 4. REWARDS: XP, levels, daily quests, badges (everything is worked out from your saved sessions)
  // =====================================================================
  const TITLES = ["Rookie", "Upright Apprentice", "Spine Scout", "Posture Padawan", "Desk Ranger", "Posture Pro", "Back Boss", "Spine Sage", "Chiro Champion", "Spine Legend"];
  const levelOf = xp => Math.floor((1 + Math.sqrt(1 + xp / 12.5)) / 2);
  const levelStart = L => 50 * L * (L - 1);
  const titleOf = L => TITLES[Math.min(TITLES.length - 1, L - 1)] + (L > TITLES.length ? " " + "★".repeat(Math.min(5, L - TITLES.length)) : "");
  function sessXp(r) {
    const base = Math.round((r.duration / 60) * 2 * (r.score / 100));
    const bonus = r.duration >= 600 && r.score >= 90 ? 25 : r.duration >= 300 && r.score >= 75 ? 10 : 0;
    return base + bonus;
  }

  function todayInfo() {
    const t = dayStr(); let c = 0, tot = 0;
    recs().forEach(r => { if (dayStr(new Date(r.start)) === t) { const x = recTimes(r); c += x.c; tot += x.t; } });
    return { sec: tot, score: tot > 0 ? Math.round((c / tot) * 100) : 0 };
  }
  function questList(E) {
    const t = dayStr(), td = todayInfo();
    return [
      { id: "wear30", ico: "⏱", name: "Wear it for 30 minutes", sub: "Minutes worn today", have: Math.min(30, td.sec / 60), need: 30, unit: "min" },
      { id: "score80", ico: "🎯", name: "Score 80%+ today", sub: "Needs at least 10 minutes of wear", have: td.sec >= 600 ? td.score : Math.min(79, td.score), need: 80, unit: "%", gate: td.sec >= 600 },
      { id: "break", ico: "🧘", name: "Take a back break", sub: "Do a 1-minute stretch", have: Math.min(1, E.breakDays[t] || 0), need: 1, unit: "" },
      { id: "quiz", ico: "🧠", name: "Finish the Posture Quiz", sub: "In the Posture Lab", have: E.quizDays[t] ? 1 : 0, need: 1, unit: "" },
    ].map(x => ({ ...x, done: x.have >= x.need && x.gate !== false }));
  }

  function badgeCtx(E) {
    const list = recs(), ss = serverStats || {};
    const st = typeof userStreak !== "undefined" ? userStreak : { current: 0, longest: 0 };
    return {
      count: Math.max(list.length, ss.sessions || 0), totalSec: Math.max(list.reduce((a, r) => a + r.duration, 0), ss.totalSec || 0),
      bestScore: Math.max(list.reduce((a, r) => (r.duration >= 300 ? Math.max(a, r.score) : a), 0), ss.bestScore || 0),
      longestStreak: Math.max(st.longest || 0, st.current || 0), perfect: !!ss.perfect || list.some(r => r.duration >= 300 && r.score >= 99),
      early: list.some(r => new Date(r.start).getHours() < 9), breaks: E.breaks, quizBest: E.quizBest,
      goal: todayInfo().sec / 60 >= (userSettings.dailyGoal || 120),
    };
  }
  const BADGE_DEFS = [
    { id: "first", ico: "🌱", name: "First Steps", desc: "Record your first session", prog: c => [c.count, 1] },
    { id: "s5", ico: "🖐", name: "High Five", desc: "Record 5 sessions", prog: c => [c.count, 5] },
    { id: "s25", ico: "🚀", name: "Regular", desc: "Record 25 sessions", prog: c => [c.count, 25] },
    { id: "hour", ico: "⏳", name: "Hour Hero", desc: "Wear it for 1 hour in total", prog: c => [c.totalSec / 3600, 1] },
    { id: "h10", ico: "⌛", name: "Ten Hours", desc: "Wear it for 10 hours in total", prog: c => [c.totalSec / 3600, 10] },
    { id: "sharp", ico: "🎯", name: "Sharp Shooter", desc: "Score 90%+ in a session of 5+ min", prog: c => [c.bestScore, 90] },
    { id: "perfect", ico: "💎", name: "Flawless", desc: "Score 99%+ in a session of 5+ min", prog: c => [c.perfect ? 1 : 0, 1] },
    { id: "st3", ico: "🔥", name: "On Fire", desc: "3-day streak", prog: c => [c.longestStreak, 3] },
    { id: "st7", ico: "🏆", name: "Week Warrior", desc: "7-day streak", prog: c => [c.longestStreak, 7] },
    { id: "st30", ico: "👑", name: "Spine Royalty", desc: "30-day streak", prog: c => [c.longestStreak, 30] },
    { id: "goal", ico: "✅", name: "Goal Getter", desc: "Reach your daily wear goal", prog: c => [c.goal ? 1 : 0, 1] },
    { id: "early", ico: "🌅", name: "Early Bird", desc: "Start a session before 9 am", prog: c => [c.early ? 1 : 0, 1] },
    { id: "br1", ico: "🧘", name: "First Stretch", desc: "Do your first back break", prog: c => [c.breaks, 1] },
    { id: "br10", ico: "🤸", name: "Break Habit", desc: "Do 10 back breaks", prog: c => [c.breaks, 10] },
    { id: "quiz", ico: "🧠", name: "Quiz Whiz", desc: "Score 5 out of 5 in the quiz", prog: c => [c.quizBest, 5] },
  ];

  let rewState = null, rewReady = false;
  function computeRewards(celebrate) {
    const E = ex(), ctx = badgeCtx(E);
    const quests = questList(E);
    let changed = false, fresh = [];
    // badges stay unlocked once earned
    BADGE_DEFS.forEach(b => { const [h, n] = b.prog(ctx); if (h >= n && !E.earned[b.id]) { E.earned[b.id] = dayStr(); fresh.push(b); changed = true; } });
    const t = dayStr(); E.quests[t] = E.quests[t] || [];
    const questsNew = [];
    quests.forEach(qq => { if (qq.done && !E.quests[t].includes(qq.id)) { E.quests[t].push(qq.id); questsNew.push(qq); changed = true; } });
    const questTotal = Object.values(E.quests).reduce((a, l) => a + l.length, 0);
    const sess = Math.max(recs().reduce((a, r) => a + sessXp(r), 0), (typeof isGuest !== "undefined" && !isGuest) ? serverXp : 0);   // account total, so a new device keeps your level
    const badgeCount = Object.keys(E.earned).length;
    const xp = sess + 50 * badgeCount + 20 * (E.breakXp || 0) + 10 * E.quizBest + 15 * questTotal;
    const level = levelOf(xp);
    const levelUp = E.lastLevel > 0 && level > E.lastLevel;
    if (E.lastLevel !== level) { E.lastLevel = level; changed = true; }
    if (changed) saveEx(E);
    rewState = { E, ctx, quests, xp, level, badgeCount };
    if (celebrate && rewReady) {
      questsNew.forEach(qq => toast(`✅ Quest done: ${qq.name} (+15 XP)`));
      fresh.forEach(b => { toast(`🏅 New badge: ${b.name}! (+50 XP)`); confetti(90); });
      if (levelUp) { toast(`⬆ LEVEL UP! You are now level ${level}: ${titleOf(level)}`); confetti(170); }
    }
    return rewState;
  }

  function renderRewards() {
    const s = computeRewards(true); if (!s) return;
    const lo = levelStart(s.level), hi = levelStart(s.level + 1), pct = clamp(((s.xp - lo) / (hi - lo)) * 100, 0, 100);
    // sidebar chip + dashboard strip
    q("#sideLevelNum") && (q("#sideLevelNum").textContent = s.level);
    q("#sideLevelTitle") && (q("#sideLevelTitle").textContent = titleOf(s.level));
    q("#sideLevelBar") && (q("#sideLevelBar").style.width = pct + "%");
    q("#sideXp") && (q("#sideXp").textContent = `${s.xp} XP`);
    let strip = q("#dashXp");
    if (!strip && q("#statusCard")) {
      strip = document.createElement("div"); strip.id = "dashXp"; strip.className = "dashboard-xp"; strip.dataset.goto = "rewards"; strip.setAttribute("role", "button"); strip.tabIndex = 0;
      strip.innerHTML = '<span class="lv-badge" id="dxNum">1</span><span class="dx-mid"><b id="dxTitle"></b> <span id="dxText"></span><span class="xp-bar"><i id="dxBar"></i></span></span><span>🎮</span>';
      q("#statusCard").parentNode.insertBefore(strip, q("#statusCard"));
      strip.addEventListener("keydown", e => { if (e.key === "Enter") showView("rewards"); });
    }
    if (strip) { q("#dxNum").textContent = s.level; q("#dxTitle").textContent = titleOf(s.level); q("#dxText").textContent = `· ${s.xp} XP · ${hi - s.xp} to level ${s.level + 1}`; q("#dxBar").style.width = pct + "%"; }
    if (typeof activeView === "undefined" || activeView !== "rewards") return;
    // full page
    q("#lvNum").textContent = s.level; q("#lvTitle").textContent = titleOf(s.level); q("#lvBar").style.width = pct + "%";
    q("#lvRing").style.setProperty("--p", pct.toFixed(0) + "%");
    q("#lvText").textContent = `${s.xp} XP · ${hi - s.xp} XP to level ${s.level + 1}`;
    const cur = (typeof userStreak !== "undefined" ? userStreak.current : 0) || 0;
    q("#flameNum").textContent = cur; q("#flameCard").classList.toggle("cold", cur === 0);
    q("#questList").innerHTML = s.quests.map(x => {
      const p = clamp((x.have / x.need) * 100, 0, 100);
      return `<div class="quest ${x.done ? "done" : ""}"><span class="q-ico">${x.done ? "✅" : x.ico}</span><span><b>${x.name}</b><small>${x.sub}${x.done ? "" : ` · ${Math.floor(x.have)}${x.unit ? " " + x.unit : ""} / ${x.need}${x.unit ? " " + x.unit : ""}`}</small><span class="q-bar"><i style="width:${p}%"></i></span></span><span class="q-xp">${x.done ? "+15 XP ✓" : "+15 XP"}</span></div>`;
    }).join("");
    q("#questNote").textContent = `${s.quests.filter(x => x.done).length} of ${s.quests.length} done today`;
    const todo = BADGE_DEFS.filter(b => !s.E.earned[b.id]).map(b => { const [h, n] = b.prog(s.ctx); return { b, h, n, r: clamp(h / n, 0, 1) }; }).sort((a, b) => b.r - a.r).slice(0, 3);
    q("#nextUp").innerHTML = todo.length ? todo.map(x => `<div class="next-item"><i>${x.b.ico}</i><span><b>${x.b.name}</b><small>${x.b.desc} · ${Math.floor(x.h * 10) / 10 >= 10 ? Math.floor(x.h) : Math.round(x.h * 10) / 10} / ${x.n}</small></span></div>`).join("") : '<div class="empty">You unlocked every badge. Legend!</div>';
    q("#badgeCount").textContent = `${s.badgeCount} of ${BADGE_DEFS.length} unlocked`;
    q("#badgeGrid").innerHTML = BADGE_DEFS.map(b => `<div class="badge-tile ${s.E.earned[b.id] ? "got" : ""}"><i>${b.ico}</i><b>${b.name}</b><small>${b.desc}</small></div>`).join("");
  }

  // =====================================================================
  // 5. BACK BREAKS (works with or without a device; meeting-friendly silent mode)
  // =====================================================================
  const STRETCHES = [
    { id: "neck", ico: "🙆", name: "Neck reset", sub: "Eases a stiff neck and head-forward posture",
      steps: ["Sit tall. Look straight ahead.", "Gently tuck your chin back, like making a double chin. Hold 5 seconds.", "Slowly tilt your right ear toward your right shoulder. Hold 10 seconds.", "Switch to the left side. Hold 10 seconds.", "Roll your shoulders back 5 times. Breathe slowly."] },
    { id: "chest", ico: "🤗", name: "Open the chest", sub: "Undoes rounded shoulders",
      steps: ["Sit on the front half of your chair.", "Clasp your hands behind your back (or hold the chair sides).", "Gently lift your chest and squeeze your shoulder blades together.", "Hold 20 seconds, breathing normally.", "Release slowly and shake out your arms."] },
    { id: "twist", ico: "🌀", name: "Seated back twist", sub: "Loosens the middle and lower back",
      steps: ["Sit tall with both feet flat on the floor.", "Place your right hand on your left knee, left hand on the chair back.", "Breathe in to grow tall, breathe out and turn gently to the left. Hold 20 seconds.", "Come back to centre, then repeat to the other side.", "Never force the twist. Stop if it hurts."] },
    { id: "stand", ico: "🧍", name: "Stand up & reach", sub: "Wakes up the whole back, great in a meeting break",
      steps: ["Stand up and place your feet hip-width apart.", "Reach both arms overhead and stretch up tall. Hold 10 seconds.", "Place your hands on your lower back and lean back slightly. Hold 10 seconds.", "Slowly bend your knees and let your arms hang forward for 10 seconds.", "Walk for the rest of the minute, then sit back down tall."] },
  ];
  let brk = { timer: null, stretch: null, t0: 0, rewardedThisStage: false };

  const brkSettings = () => ({ on: !!userSettings.breakReminder, every: Number(userSettings.breakEveryMin) || 60, quiet: !!userSettings.breakQuiet });
  function nextBreakAt() { return Number(get("nextBreak", 0)) || 0; }
  function setNextBreak(ts) { put("nextBreak", ts); }
  function scheduleBreak(fromNow) { setNextBreak(Date.now() + (fromNow ?? brkSettings().every * 60000)); }

  function renderBreakUI() {
    const b = brkSettings();
    if (q("#breakToggle")) q("#breakToggle").checked = b.on;
    if (q("#breakQuiet")) q("#breakQuiet").checked = b.quiet;
    qa("#breakEvery .chip").forEach(c => c.classList.toggle("active", +c.dataset.min === b.every));
    const label = b.every === 60 ? "every hour" : b.every === 120 ? "every 2 hours" : `every ${b.every} minutes`;
    if (q("#breakStatus")) q("#breakStatus").textContent = b.on ? `Reminding you ${label}${b.quiet ? " · meeting-friendly (silent)" : ""}` : "Reminders are off";
    tickBreakCountdown();
  }
  function tickBreakCountdown() {
    const b = brkSettings(), el = q("#breakLeft"); if (!el) return;
    if (!b.on) { el.textContent = "--:--"; q("#breakLeftNote").textContent = "Switch the reminders on to start the timer"; return; }
    const left = Math.max(0, (nextBreakAt() - Date.now()) / 1000);
    el.textContent = left >= 3600 ? `${Math.floor(left / 3600)}:${String(Math.floor((left % 3600) / 60)).padStart(2, "0")}:${String(Math.floor(left % 60)).padStart(2, "0")}` : hhmm(left);
    q("#breakLeftNote").textContent = "until your next back break";
  }
  function breakDue() {
    const b = brkSettings();
    scheduleBreak(b.quiet ? 15 * 60000 : undefined);             // if ignored in quiet mode, gently ask again in 15 minutes
    if (b.quiet) {
      const n = q("#quietBreakNote"); if (n) n.hidden = false;      // small corner note: no sound, no pop-up, no vibration
    } else {
      toast(`⏱ Time for a back break! Stand up, roll your shoulders, look far away.`);
      try { if (userSettings.notify) showDesktopNotification("Back break", "Stand up and stretch for a minute."); } catch (_) {}
      try { if (userSettings.sound) playChime("good"); } catch (_) {}
    }
  }
  function breakLoop() {
    const b = brkSettings();
    if (b.on) { if (!nextBreakAt()) scheduleBreak(); else if (Date.now() >= nextBreakAt()) breakDue(); }
    tickBreakCountdown();
  }
  function openStretch(id) {
    const s = STRETCHES.find(x => x.id === id) || STRETCHES[Math.floor(Math.random() * STRETCHES.length)];
    brk.stretch = s; brk.rewardedThisStage = false; clearInterval(brk.timer);
    q("#stretchName").textContent = `${s.ico} ${s.name}`;
    q("#stretchSteps").innerHTML = s.steps.map(t => `<li>${E(t)}</li>`).join("") + '<li class="muted-p small">Move gently and stop if anything hurts. These are general wellness stretches, not medical advice.</li>';
    q("#stretchSecs").textContent = "60"; q("#stretchStart").textContent = "▶ Start";
    q("#stretchStage").hidden = false; q("#stretchStage").scrollIntoView({ behavior: "smooth", block: "nearest" });
    const n = q("#quietBreakNote"); if (n) n.hidden = true;
  }
  function startStretch() {
    clearInterval(brk.timer); brk.t0 = Date.now(); const steps = qa("#stretchSteps li:not(.muted-p)"), per = 60 / steps.length;
    q("#stretchStart").textContent = "↻ Restart";
    brk.timer = setInterval(() => {
      const el = (Date.now() - brk.t0) / 1000, left = Math.max(0, 60 - el);
      q("#stretchSecs").textContent = Math.ceil(left);
      steps.forEach((li, i) => li.classList.toggle("now", Math.floor(el / per) === i));
      if (left <= 0) { clearInterval(brk.timer); steps.forEach(li => li.classList.remove("now")); finishBreak(true); }
    }, 250);
  }
  function finishBreak(auto) {
    if (brk.rewardedThisStage) return;
    brk.rewardedThisStage = true; clearInterval(brk.timer);
    const E = ex(), t = dayStr();
    E.breaks += 1; E.breakDays[t] = (E.breakDays[t] || 0) + 1;
    const rewarded = (E.breakDays[t] || 0) <= 8; if (rewarded) E.breakXp = (E.breakXp || 0) + 1;
    saveEx(E);
    if (brkSettings().on) scheduleBreak();
    toast(rewarded ? (auto ? "🧘 Great job! Break complete (+20 XP)" : "🧘 Break logged (+20 XP)") : "🧘 Break logged. (XP is limited to 8 breaks a day.)");
    renderRewards(); renderBreakUI();
  }
  function initBreaks() {
    if (!q("#breakToggle")) return;
    q("#breakToggle").addEventListener("change", e => {
      userSettings.breakReminder = e.target.checked; persistSettings();
      if (e.target.checked) { scheduleBreak(); toast("Back-break reminders on"); } else toast("Back-break reminders off");
      renderBreakUI();
    });
    q("#breakQuiet").addEventListener("change", e => { userSettings.breakQuiet = e.target.checked; persistSettings(); toast(e.target.checked ? "Meeting-friendly mode on: silent reminders only" : "Meeting-friendly mode off"); renderBreakUI(); });
    qa("#breakEvery .chip").forEach(c => c.addEventListener("click", () => { userSettings.breakEveryMin = +c.dataset.min; userSettings.breakReminder = true; persistSettings(); scheduleBreak(); renderBreakUI(); toast(`Reminders: every ${c.textContent.toLowerCase()}`); }));
    q("#breakNowBtn").addEventListener("click", () => openStretch(STRETCHES[Math.floor(Math.random() * STRETCHES.length)].id));
    q("#breakSnoozeBtn").addEventListener("click", () => { scheduleBreak(15 * 60000); const n = q("#quietBreakNote"); if (n) n.hidden = true; toast("OK, no reminder for 15 minutes"); renderBreakUI(); });
    q("#stretchList").innerHTML = STRETCHES.map(s => `<button type="button" class="stretch-item" data-stretch="${s.id}"><i>${s.ico}</i><span><b>${s.name}</b><small>${s.sub}</small></span></button>`).join("");
    q("#stretchList").addEventListener("click", e => { const b = e.target.closest("[data-stretch]"); if (b) openStretch(b.dataset.stretch); });
    q("#stretchStart").addEventListener("click", startStretch);
    q("#stretchDone").addEventListener("click", () => finishBreak(false));
    q("#stretchClose").addEventListener("click", () => { clearInterval(brk.timer); q("#stretchStage").hidden = true; });
    q("#quietBreakOpen").addEventListener("click", () => { showView("breaktime"); openStretch(); });
    q("#quietBreakLater").addEventListener("click", () => { scheduleBreak(15 * 60000); q("#quietBreakNote").hidden = true; });
    renderBreakUI();
  }

  // =====================================================================
  // 6. POSTURE LAB (interactive neck load, desk risk check, quiz)
  // =====================================================================
  function initLab() {
    if (!q("#labRange")) return;
    qa(".lab-tab").forEach(t => t.addEventListener("click", () => {
      qa(".lab-tab").forEach(x => x.classList.toggle("active", x === t));
      qa(".lab-pane").forEach(p => p.classList.toggle("active", p.id === "lab-" + t.dataset.lab));
    }));
    const r = q("#labRange"), stage = q(".lab-stage");
    const tips = { good: ["Keep your screen at eye level", "Stand up and move every hour"], warn: ["Raise your screen or laptop so you look straight ahead", "Tuck your chin gently, ears over shoulders", "Take a 1-minute back break"], bad: ["Lift your head: hold your phone up at eye level", "Sit back in your chair with your back supported", "Do the 'Neck reset' stretch now"] };
    // updNeck(actual): the slider only goes to 60 degrees (that is where the research chart ends).
    // A live reading can be bigger than that: then the figure shows the real angle and we warn about a "very huge load".
    const updNeck = actual => {
      const over = typeof actual === "number" && actual > 60, d = over ? 60 : +r.value, ang = over ? Math.min(actual, 90) : d;
      const lbs = Math.round(neckLoad(d)), t = over ? "bad" : tone(d), extra = lbs - 12, warn = q("#labWarn");
      q("#labHead").style.transform = `rotate(${ang * 0.9}deg)`;
      q("#labDeg").textContent = over ? Math.round(actual) + "° (past 60°)" : d + "°";
      q("#labLbs").textContent = over ? "60+ lbs" : lbs + " lbs"; q("#labKg").textContent = over ? "27+ kg" : (lbs * 0.4536).toFixed(1) + " kg";
      stage.classList.remove("good", "warn", "bad"); stage.classList.add(t);
      q("#labLike").textContent = over ? "Like carrying a heavy suitcase or more" : "Like carrying " + likeWhat(lbs);
      q("#labSay").textContent = over ? "Very huge load! Your head is leaning even further than the chart can measure. Sit up and lift your chin now." : t === "good" ? "Perfect! Your neck muscles are relaxed." : t === "warn" ? "Your neck is working harder than it should. Over hours, this causes aches and stiffness." : "Heavy! Holding this for long is very tiring for your neck and shoulders.";
      q("#labExtra").textContent = over ? "+48 lbs or more" : "+" + extra + " lbs"; q("#labRisk").textContent = over ? "Extreme" : t === "good" ? "Very low" : d < 20 ? "Medium" : d < 35 ? "High" : "Very high";
      q("#labMeter").style.left = `calc(${(d / 60) * 100}% - 4px)`;
      q("#labTips").innerHTML = tips[t].map(x => `<li>${x}</li>`).join("");
      if (warn) { warn.hidden = !over; if (over) warn.textContent = `⚠ VERY HUGE LOAD: your live lean is ${Math.round(actual)}°, beyond the 60° this chart measures. The load on your neck is more than 60 lbs. Sit up now!`; }
    };
    r.addEventListener("input", () => updNeck()); updNeck();
    q("#labResetBtn").addEventListener("click", () => { r.value = 0; updNeck(); });
    q("#labLiveBtn").addEventListener("click", () => {
      const p = (typeof historyPitchSigned !== "undefined" && historyPitchSigned.length) ? Math.abs(historyPitchSigned[historyPitchSigned.length - 1]) : null;
      if (p === null) { toast("No live reading yet. Connect your device or start the demo on the My Device page."); return; }
      r.value = Math.min(60, Math.round(p)); updNeck(p > 60 ? p : undefined);
      toast(p > 60 ? `⚠ Your live lean is ${p.toFixed(0)}°: very huge load!` : `Your live lean is ${p.toFixed(0)}°`);
    });

    // --- desk risk check (simple RULA-style estimate) ---
    const ids = ["rulaArm", "rulaElbow", "rulaWrist", "rulaNeck", "rulaTrunk"];
    const advice = {
      rulaArm: "Bring your elbows closer to your body and lower your armrests or desk height.",
      rulaElbow: "Adjust your chair or keyboard so your elbows rest at about a right angle.",
      rulaWrist: "Keep your wrists straight, use a wrist rest or a keyboard tilted flat.",
      rulaNeck: "Raise your screen so the top is at eye level and tuck your chin gently.",
      rulaTrunk: "Sit back, support your lower back and keep your hips at the back of the chair.",
    };
    const levels = [
      { n: 1, cls: "", title: "Level 1 - Looks good", say: "Your posture is fine. Keep moving now and then." },
      { n: 2, cls: "l2", title: "Level 2 - Small changes may help", say: "Nothing urgent. A few small tweaks will make you more comfortable." },
      { n: 3, cls: "l3", title: "Level 3 - Change your set-up soon", say: "Your posture is putting extra strain on your body. Please make changes soon." },
      { n: 4, cls: "l4", title: "Level 4 - Change it as soon as possible", say: "Your posture is putting a lot of strain on you. Please fix your set-up soon." },
    ];
    q("#rulaCards").innerHTML = levels.map(l => `<div class="rula-card rula-${l.n}" data-l="${l.n}"><strong>${l.title.split(" - ")[0]}</strong><span>${l.title.split(" - ")[1]}</span></div>`).join("");
    const updRula = () => {
      const vals = ids.map(i => +q("#" + i).value), stat = q("#rulaStatic").checked ? 1 : 0;
      const score = clamp(vals.reduce((a, b) => a + b, 0) - 4 + stat, 1, 7);
      const L = score <= 2 ? 1 : score <= 4 ? 2 : score <= 6 ? 3 : 4, lv = levels[L - 1];
      q("#rulaNum").textContent = score; q("#rulaDial").className = "rula-dial " + lv.cls;
      q("#rulaTitle").textContent = lv.title; q("#rulaAdvice").textContent = lv.say;
      qa("#rulaCards .rula-card").forEach(c => { c.classList.toggle("on", +c.dataset.l === L); c.classList.toggle("dim", +c.dataset.l !== L); });
      const bad = ids.filter((i, k) => vals[k] > 1).map(i => advice[i]);
      if (stat) bad.push("Change position at least every 10 minutes and take back breaks.");
      q("#rulaTips").innerHTML = (bad.length ? bad : ["Nothing to fix. Keep it up!"]).map(x => `<li>${x}</li>`).join("");
    };
    ids.concat(["rulaStatic"]).forEach(i => q("#" + i).addEventListener("change", updRula)); updRula();
    q("#rulaFromLive").addEventListener("click", () => {
      const p = (typeof historyPitchSigned !== "undefined" && historyPitchSigned.length) ? historyPitchSigned[historyPitchSigned.length - 1] : null;
      if (p === null) { toast("No live reading yet. Connect your device or start the demo first."); return; }
      q("#rulaNeck").value = Math.abs(p) < 10 ? 1 : Math.abs(p) < 20 ? 2 : p > 0 ? 3 : 4; updRula(); toast("Neck updated from your live posture");
    });

    // --- quiz ---
    const QS = [
      { q: "About how much does an adult head weigh?", o: ["About 1 kg (2 lbs)", "About 5 kg (11 lbs)", "About 12 kg (26 lbs)"], a: 1, why: "A head weighs about 5 kg. That is why leaning it forward makes your neck work so hard." },
      { q: "When your head leans forward 30°, the load on your neck is roughly...", o: ["The same as sitting straight", "About 20 lbs", "About 40 lbs"], a: 2, why: "Around 40 lbs, almost four times the load of sitting straight." },
      { q: "How often should you break up long sitting?", o: ["Once a day is enough", "Every 30 to 60 minutes", "Only when it starts to hurt"], a: 1, why: "Short movement breaks every 30-60 minutes keep your back and neck happier." },
      { q: "Where should the top of your screen be?", o: ["Below your chest", "At or just below eye level", "Well above your head"], a: 1, why: "A screen at eye level lets your head stay over your shoulders." },
      { q: "What does a BioSpine alarm mean?", o: ["The battery is low", "You have been slouching for a few seconds", "It is time for lunch"], a: 1, why: "The alarm is a nudge to sit up. It stops as soon as you do." },
    ];
    let qi = 0, score = 0, locked = false;
    const showQ = () => {
      locked = false; const k = QS[qi];
      q("#quizProgress").textContent = `Question ${qi + 1} of ${QS.length}`; q("#quizQ").textContent = k.q; q("#quizFeedback").textContent = "";
      q("#quizNext").hidden = true; q("#quizRestart").hidden = true;
      q("#quizOpts").innerHTML = k.o.map((t, i) => `<button type="button" class="quiz-opt" data-i="${i}">${E(t)}</button>`).join("");
      const best = ex().quizBest; q("#quizBest").textContent = best ? `Best: ${best}/5` : "";
    };
    q("#quizOpts").addEventListener("click", e => {
      const b = e.target.closest(".quiz-opt"); if (!b || locked) return; locked = true;
      const k = QS[qi], i = +b.dataset.i; qa(".quiz-opt").forEach(x => { x.disabled = true; if (+x.dataset.i === k.a) x.classList.add("right"); });
      if (i === k.a) { score++; q("#quizFeedback").textContent = "✅ Correct! " + k.why; } else { b.classList.add("wrong"); q("#quizFeedback").textContent = "Not quite. " + k.why; }
      q("#quizNext").hidden = false; q("#quizNext").textContent = qi === QS.length - 1 ? "See my score" : "Next question →";
    });
    q("#quizNext").addEventListener("click", () => {
      if (qi < QS.length - 1) { qi++; showQ(); return; }
      const E2 = ex(); const newBest = score > E2.quizBest; if (newBest) E2.quizBest = score; E2.quizDays[dayStr()] = true; saveEx(E2);
      q("#quizQ").textContent = `You scored ${score} out of ${QS.length}! ${score === 5 ? "🏆 Perfect!" : score >= 3 ? "👏 Nice work." : "Keep learning, you will get there."}`;
      q("#quizOpts").innerHTML = "";
      q("#quizFeedback").textContent = newBest ? "New personal best! XP added." : "";
      q("#quizNext").hidden = true; q("#quizRestart").hidden = false; if (score === 5) confetti(110); renderRewards();
    });
    q("#quizRestart").addEventListener("click", () => { qi = 0; score = 0; showQ(); });
    showQ();
  }

  // =====================================================================
  // 7. ONE-TIME REVIEW PROMPT (after the 5th saved session)
  // =====================================================================
  let reviewOpen = false, reviewRating = 0, myReview = null;
  const WORDS = ["", "Not good", "Could be better", "It's okay", "Good", "Love it!"];
  function paintStars(n) { qa("#reviewStars button").forEach(b => b.classList.toggle("on", +b.dataset.v <= n)); q("#reviewWord").textContent = WORDS[n] || "Tap a star"; }
  function showReview() {
    if (reviewOpen || isGuest || !sessionToken || !q("#reviewModal")) return;
    if (typeof rec !== "undefined" && rec) { setTimeout(showReview, 60000); return; }      // never interrupt a running session
    reviewOpen = true; reviewRating = 0; paintStars(0); q("#reviewError").textContent = "";
    q("#reviewTitle").textContent = "You've finished 5 sessions!"; q("#reviewIntro").textContent = "How is BioSpine working for you? Your honest review helps us improve (it takes 20 seconds)."; q("#reviewComment").value = "";
    q("#reviewName").value = (currentUser || "").split("@")[0].replace(/[._-]+/g, " ").replace(/\b\w/g, c => c.toUpperCase()).slice(0, 24);
    q("#reviewModal").style.display = "flex";
  }
  // Open the review box any time (sidebar button / Settings): the person can write a new review or change the old one.
  function openReviewManual() {
    if (reviewOpen) return;
    if (isGuest || !sessionToken) { toast("Create a free account or sign in to write a review"); return; }
    reviewOpen = true; reviewRating = myReview ? myReview.rating : 0; paintStars(reviewRating); q("#reviewError").textContent = "";
    q("#reviewTitle").textContent = myReview ? "Your review of BioSpine" : "Review BioSpine";
    q("#reviewIntro").textContent = myReview ? "You can change your rating or comment. (An edited review is checked again before it can appear on the home page.)" : "Tell us how BioSpine is working for you. Your honest review helps us improve.";
    q("#reviewName").value = myReview ? myReview.name : (currentUser || "").split("@")[0].replace(/[._-]+/g, " ").replace(/\b\w/g, c => c.toUpperCase()).slice(0, 24);
    q("#reviewComment").value = myReview ? myReview.comment : "";
    q("#reviewModal").style.display = "flex";
  }
  function closeReview() { q("#reviewModal").style.display = "none"; reviewOpen = false; }
  function initReview() {
    if (!q("#reviewModal")) return;
    qa("[data-review-open]").forEach(b => b.addEventListener("click", openReviewManual));
    qa("#reviewStars button").forEach(b => { b.addEventListener("click", () => { reviewRating = +b.dataset.v; paintStars(reviewRating); }); b.addEventListener("mouseenter", () => paintStars(+b.dataset.v)); b.addEventListener("mouseleave", () => paintStars(reviewRating)); });
    q("#reviewLater").addEventListener("click", async () => { closeReview(); try { await api("/api/review/dismiss", { method: "POST", body: {} }); } catch (_) {} });
    q("#reviewSend").addEventListener("click", async () => {
      if (!reviewRating) { q("#reviewError").textContent = "Please tap a star rating first."; return; }
      q("#reviewSend").disabled = true; q("#reviewError").textContent = "";
      try {
        const { res, data } = await api("/api/review", { method: "POST", body: { rating: reviewRating, name: q("#reviewName").value, comment: q("#reviewComment").value } });
        if (res.ok && data.success) { myReview = { rating: reviewRating, comment: q("#reviewComment").value.trim(), name: q("#reviewName").value.trim() || "A BioSpine user" }; closeReview(); toast("💙 Thank you for your review!"); confetti(100); }
        else q("#reviewError").textContent = data.error || "Could not send your review. Please try again.";
      } catch (_) { q("#reviewError").textContent = "Could not reach the server. Please try again."; }
      q("#reviewSend").disabled = false;
    });
  }

  // =====================================================================
  // 8. MY DEVICE: live gauges and signal quality
  // =====================================================================
  let lastOk = null, rateHist = Array(40).fill(0), rateTick = 0;
  function gauge(prefix, val, limit) {
    const k = clamp(Math.abs(val) / Math.max(1, limit), 0, 1.4), arc = q(`#g${prefix}Fill`), needle = q(`#g${prefix}Needle`);
    if (!arc) return;
    const frac = clamp(Math.abs(val) / 45, 0, 1) * 100;
    arc.style.strokeDasharray = `${frac} 100`; arc.style.opacity = frac < 1 ? 0 : 1;
    arc.style.stroke = k < 0.7 ? "var(--green)" : k < 1 ? "var(--amber)" : "var(--red)";
    needle.style.transform = `rotate(${clamp(val / 45, -1, 1) * 85}deg)`;
    q(`#g${prefix}Val`).textContent = val.toFixed(1) + "°";
  }
  function deviceLive() {
    const panel = q("#devStatus"); if (!panel) return;
    const isDemo = typeof demoTimer !== "undefined" && !!demoTimer, on = typeof connected !== "undefined" && connected;
    panel.classList.toggle("on", on && !isDemo); panel.classList.toggle("demo", isDemo);
    q("#devOrbIcon").textContent = isDemo ? "🧪" : on ? "✅" : "🔌";
    const fresh = typeof lastPacketAt !== "undefined" && lastPacketAt && Date.now() - lastPacketAt < 3000;
    q("#devLiveDot").textContent = fresh ? "● LIVE" : on ? "● WAITING" : "● OFFLINE";
    const p = (typeof historyPitchSigned !== "undefined" && historyPitchSigned.length) ? historyPitchSigned[historyPitchSigned.length - 1] : 0;
    const rl = (typeof historyRollSigned !== "undefined" && historyRollSigned.length) ? historyRollSigned[historyRollSigned.length - 1] : 0;
    gauge("Pitch", fresh ? p : 0, userSettings.angle); gauge("Roll", fresh ? rl : 0, userSettings.lateralLimit);
    if (typeof pktOk !== "undefined") {
      rateTick++;
      if (lastOk === null || pktOk < lastOk) lastOk = pktOk;
      if (rateTick % 3 === 0) { rateHist.push(Math.max(0, pktOk - lastOk)); lastOk = pktOk; rateHist.shift(); }
      const mx = Math.max(5, ...rateHist);
      q("#devSparkLine").setAttribute("points", rateHist.map((v, i) => `${(i / (rateHist.length - 1)) * 220},${76 - (v / mx) * 70}`).join(" "));
      q("#devRate").textContent = (rateHist[rateHist.length - 1] || 0) + " / sec";
      const tot = pktOk + pktBad, ratio = tot ? pktOk / tot : null;
      q("#devSignal").textContent = ratio === null ? "—" : ratio >= .98 ? "Excellent" : ratio >= .9 ? "Good" : "Weak - move closer or use USB";
    }
    const mb = q("#modeBadge"); if (mb) mb.textContent = { focus: "FOCUS MODE", meeting: "MEETING MODE", rehab: "TRAINING MODE" }[userSettings.mode] || "FOCUS MODE";
  }

  // =====================================================================
  // 9. MY REPORT (plain language) + EXCEL / PDF downloads
  // =====================================================================
  const fmtDur = sec => { sec = Math.round(sec); const h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60); return h ? `${h} h ${m} min` : `${m} min`; };
  const dayName = ds => new Date(ds + "T12:00:00").toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "short" });
  const fmtDate = ts => { const d = new Date(ts); return `${dayStr(d)} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`; };

  function reportData(days) {
    const since = days ? Date.now() - days * 86400000 : 0;
    const list = recs().filter(r => r.start >= since).sort((a, b) => a.start - b.start);
    const w = l => l.reduce((a, r) => { const x = recTimes(r); a.c += x.c; a.t += x.t; return a; }, { c: 0, t: 0 });
    const tot = w(list), byDay = {}, byHour = Array.from({ length: 24 }, () => ({ c: 0, t: 0 })), strain = { forward: 0, backward: 0, left: 0, right: 0 };
    let alerts = 0;
    list.forEach(r => {
      const x = recTimes(r), d = dayStr(new Date(r.start)); (byDay[d] = byDay[d] || { c: 0, t: 0, n: 0, alerts: 0 });
      byDay[d].c += x.c; byDay[d].t += x.t; byDay[d].n++; byDay[d].alerts += r.alerts || 0; alerts += r.alerts || 0;
      const h = new Date(r.start).getHours(); byHour[h].c += x.c; byHour[h].t += x.t;
      Object.keys(strain).forEach(k => { strain[k] += (r.strain && r.strain[k]) || 0; });
    });
    const dayRows = Object.entries(byDay).map(([d, v]) => ({ date: d, minutes: Math.round(v.t / 60), score: v.t ? Math.round((v.c / v.t) * 100) : 0, sessions: v.n, alerts: v.alerts })).sort((a, b) => a.date.localeCompare(b.date));
    const solid = dayRows.filter(d => d.minutes >= 5);
    const best = solid.slice().sort((a, b) => b.score - a.score)[0], worst = solid.slice().sort((a, b) => a.score - b.score)[0];
    const hr = byHour.map((v, h) => ({ h, t: v.t, s: v.t >= 300 ? v.c / v.t : -1 })).filter(x => x.s >= 0).sort((a, b) => b.s - a.s);
    const score = tot.t ? Math.round((tot.c / tot.t) * 100) : null;
    let delta = null;
    if (days) { const pl = recs().filter(r => r.start >= since - days * 86400000 && r.start < since), pw = w(pl); if (pw.t >= 600 && tot.t >= 600) delta = score - Math.round((pw.c / pw.t) * 100); }
    const topStrain = Object.entries(strain).sort((a, b) => b[1] - a[1])[0];
    return { list, days, score, secs: tot.t, alerts, perHour: tot.t ? Math.round((alerts / (tot.t / 3600)) * 10) / 10 : 0, dayRows, best, worst, bestHour: hr[0], worstHour: hr[hr.length - 1], strain, topStrain: topStrain && topStrain[1] > 0 ? topStrain : null, delta,
      streak: (typeof userStreak !== "undefined" ? userStreak.current : 0) || 0 };
  }
  function reportSentences(R) {
    if (!R.list.length) return ["No sessions in this period yet. Wear your device (or start the demo) and your report will appear here."];
    const o = [];
    const word = R.score >= 80 ? "excellent" : R.score >= 60 ? "good" : "a little low";
    o.push(`You wore BioSpine for ${fmtDur(R.secs)} over ${R.dayRows.length} day${R.dayRows.length === 1 ? "" : "s"}. Your posture score was ${R.score}%, which is ${word}.`);
    if (R.delta !== null) o.push(R.delta > 1 ? `📈 That is ${R.delta} points better than the previous ${R.days} days. Nice progress!` : R.delta < -1 ? `📉 That is ${Math.abs(R.delta)} points lower than the previous ${R.days} days. A fresh start today can turn it around.` : "That is about the same as the previous period.");
    if (R.best && R.worst && R.best.date !== R.worst.date) o.push(`Your best day was ${dayName(R.best.date)} (${R.best.score}%). Your toughest day was ${dayName(R.worst.date)} (${R.worst.score}%).`);
    if (R.bestHour && R.worstHour && R.bestHour.h !== R.worstHour.h) o.push(`You sit best around ${R.bestHour.h}:00 and slouch most around ${R.worstHour.h}:00. Plan a stretch before then.`);
    if (R.topStrain) o.push(`Your most common slouch was “${lbl(R.topStrain[0])}”, about ${fmtDur(R.topStrain[1])} in total.`);
    o.push(`You were reminded ${R.alerts} time${R.alerts === 1 ? "" : "s"}, about ${R.perHour} per hour worn.${R.streak ? ` Your streak is ${R.streak} day${R.streak === 1 ? "" : "s"} 🔥.` : ""}`);
    o.push(R.score >= 80 ? "Tip: keep it up. Add a short stretch each hour to stay loose." : R.score >= 60 ? "Tip: raise your screen to eye level and turn on the back-break reminders." : "Tip: try Focus Mode, set your good posture again, and take a 1-minute stretch every hour.");
    return o;
  }
  function renderReport() {
    const box = q("#reportBody"); if (!box) return;
    const R = reportData(+q("#reportRange").value);
    if (!R.list.length) { box.innerHTML = '<div class="empty">' + E(reportSentences(R)[0]) + "</div>"; return; }
    box.innerHTML = `<div class="metrics-grid">
      <div class="metric"><span>Posture score</span><strong>${R.score}%</strong><small>${R.delta === null ? "Whole period" : (R.delta >= 0 ? "▲ " : "▼ ") + Math.abs(R.delta) + " vs before"}</small></div>
      <div class="metric"><span>Time worn</span><strong>${fmtDur(R.secs)}</strong><small>${R.list.length} session${R.list.length === 1 ? "" : "s"}</small></div>
      <div class="metric"><span>Reminders</span><strong>${R.alerts}</strong><small>${R.perHour} per hour</small></div>
      <div class="metric"><span>Streak</span><strong>${R.streak} 🔥</strong><small>days in a row</small></div></div>
      <ul class="report-says">${reportSentences(R).map(x => `<li>${E(x)}</li>`).join("")}</ul>`;
  }

  function download(blob, name) { const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 4000); }
  function sessionRows(list) {
    return list.map(r => ({
      "Date & time": fmtDate(r.start), "Minutes worn": Math.round((r.duration / 60) * 10) / 10, "Posture score %": r.score,
      "Slouching minutes": Math.round(((r.incorrectSec ?? r.duration * (1 - r.score / 100)) / 60) * 10) / 10, "Reminders": r.alerts || 0,
      "Average forward lean (deg)": r.avg ?? "", "Typical forward lean (deg)": r.median ?? "", "Worst forward lean (deg)": r.max ?? "",
      "Highest neck load (lbs)": r.peakLoad ?? "", "Mode": { focus: "Focus", meeting: "Meeting", rehab: "Training" }[r.mode] || r.mode || "", "Source": r.source === "demo" ? "Demo" : "Device",
    }));
  }
  function exportExcel(days) {
    const R = reportData(days || 0);
    if (!R.list.length) { toast("Nothing to export yet. Record a session first."); return; }
    const name = `biospine_report_${dayStr()}`;
    const rows = sessionRows(R.list);
    if (typeof XLSX === "undefined") {   // library blocked / offline: give a CSV that Excel opens
      const head = Object.keys(rows[0]), csv = [head.join(",")].concat(rows.map(r => head.map(h => `"${String(r[h]).replace(/"/g, '""')}"`).join(","))).join("\r\n");
      download(new Blob(["\ufeff" + csv], { type: "text/csv" }), name + ".csv"); toast("Excel library not available, saved as CSV (opens in Excel)"); return;
    }
    const wb = XLSX.utils.book_new(), add = (title, data, widths) => { const ws = XLSX.utils.json_to_sheet(data); if (widths) ws["!cols"] = widths.map(w => ({ wch: w })); XLSX.utils.book_append_sheet(wb, ws, title); };
    const summary = [["BioSpine posture report"], ["Created", fmtDate(Date.now())], ["Account", isGuest ? "Guest (demo)" : currentUser], ["Period", days ? `Last ${days} days` : "Everything"], [], ...reportSentences(R).map(x => ["• " + x]), [],
      ["Posture score %", R.score], ["Time worn (min)", Math.round(R.secs / 60)], ["Sessions", R.list.length], ["Reminders", R.alerts], ["Reminders per hour", R.perHour], ["Current streak (days)", R.streak]];
    const ws0 = XLSX.utils.aoa_to_sheet(summary); ws0["!cols"] = [{ wch: 30 }, { wch: 60 }]; XLSX.utils.book_append_sheet(wb, ws0, "Summary");
    add("Sessions", rows, [18, 13, 14, 16, 10, 22, 22, 22, 20, 10, 9]);
    add("Day by day", R.dayRows.map(d => ({ Date: d.date, "Minutes worn": d.minutes, "Posture score %": d.score, Sessions: d.sessions, Reminders: d.alerts })), [12, 14, 16, 10, 10]);
    add("Slouch types", Object.keys(R.strain).map(k => ({ "Slouch type": lbl(k), "Minutes": Math.round((R.strain[k] / 60) * 10) / 10 })), [20, 12]);
    const ev = []; R.list.forEach(r => (r.events || []).forEach(e => ev.push({ "Session": fmtDate(r.start), "Time": e.t !== undefined ? hhmm(e.t) : "", "What happened": e.title || "", "Detail": e.detail || e.desc || "" })));
    if (ev.length) add("Activity log", ev.slice(0, 5000), [18, 8, 30, 50]);
    XLSX.writeFile(wb, name + ".xlsx"); toast("📗 Excel file downloaded");
  }
  function exportPdf(days) {
    const R = reportData(days || 0), lib = window.jspdf && window.jspdf.jsPDF;
    if (!R.list.length) { toast("Nothing to report yet. Record a session first."); return; }
    if (!lib) { toast("The PDF tool did not load. Check your internet connection and try again."); return; }
    const doc = new lib({ unit: "mm", format: "a4" }); let y = 18;
    doc.setFillColor(30, 58, 138); doc.rect(0, 0, 210, 26, "F"); doc.setTextColor(255); doc.setFontSize(18); doc.text("My BioSpine posture report", 14, 16);
    doc.setFontSize(9); doc.text(`${fmtDate(Date.now())} · ${days ? "Last " + days + " days" : "Everything"}`, 196, 16, { align: "right" });
    doc.setTextColor(30); y = 38;
    [["Posture score", R.score + "%"], ["Time worn", fmtDur(R.secs)], ["Sessions", String(R.list.length)], ["Reminders", `${R.alerts} (${R.perHour}/hour)`]].forEach((k, i) => {
      const x = 14 + i * 47; doc.setDrawColor(200); doc.roundedRect(x, y - 6, 43, 20, 3, 3); doc.setFontSize(8); doc.setTextColor(110); doc.text(k[0], x + 3, y); doc.setFontSize(13); doc.setTextColor(30, 58, 138); doc.text(k[1], x + 3, y + 8);
    });
    y += 24; doc.setTextColor(30); doc.setFontSize(13); doc.text("What your report says", 14, y); y += 6; doc.setFontSize(10);
    reportSentences(R).forEach(t => { const lines = doc.splitTextToSize("• " + t.replace(/[\u{1F300}-\u{1FAFF}\u2600-\u27BF]/gu, "").trim(), 180); doc.text(lines, 14, y); y += lines.length * 5 + 2; });
    y += 4; doc.setFontSize(13); doc.text("Day by day", 14, y); y += 6; doc.setFontSize(9); doc.setFillColor(238, 242, 249); doc.rect(14, y - 4, 182, 6, "F");
    ["Date", "Minutes", "Score", "Sessions", "Reminders"].forEach((h, i) => doc.text(h, 16 + i * 36, y)); y += 6;
    R.dayRows.slice(-26).forEach(d => { if (y > 280) { doc.addPage(); y = 20; } [d.date, String(d.minutes), d.score + "%", String(d.sessions), String(d.alerts)].forEach((v, i) => doc.text(v, 16 + i * 36, y)); y += 5.5; });
    doc.setFontSize(8); doc.setTextColor(120); doc.text("Wellness information from your BioSpine sensor. Not a medical diagnosis.", 14, 290);
    doc.save(`biospine_report_${dayStr()}.pdf`); toast("📄 PDF downloaded");
  }
  function initReports() {
    q("#exportXlsxBtn") && q("#exportXlsxBtn").addEventListener("click", () => exportExcel(0));
    q("#reportXlsxBtn") && q("#reportXlsxBtn").addEventListener("click", () => exportExcel(+q("#reportRange").value));
    q("#reportPdfBtn") && q("#reportPdfBtn").addEventListener("click", () => exportPdf(+q("#reportRange").value));
    q("#reportRange") && q("#reportRange").addEventListener("change", renderReport);
  }

  // =====================================================================
  // 9b. HEIGHT / WEIGHT -> BMI (sign-up preview and Settings > My body)
  // =====================================================================
  function bmiInfo(h, w) {
    h = parseFloat(h); w = parseFloat(w);
    if (!(h >= 50 && h <= 250) || !(w >= 15 && w <= 350)) return null;
    const m = h / 100, bmi = w / (m * m);
    const key = bmi < 18.5 ? "under" : bmi < 25 ? "healthy" : bmi < 30 ? "over" : "obese";
    const cat = { under: "Underweight", healthy: "Healthy weight", over: "Overweight", obese: "Obesity range" }[key];
    return { bmi: Math.round(bmi * 10) / 10, key, category: cat, lo: Math.round(18.5 * m * m * 10) / 10, hi: Math.round(24.9 * m * m * 10) / 10 };
  }
  const BMI_ADVICE = {
    under: "Your BMI is below the usual range. If you are worried about your weight, a doctor or dietitian can help.",
    healthy: "Your weight is in the usual healthy range for your height. Keep it up!",
    over: "A little above the usual range. Regular movement and back breaks help your back and neck too.",
    obese: "Above the usual range. Extra weight adds load to the back and neck, so gentle regular activity and a chat with your doctor can help.",
  };
  // ---- Performance mode: turns the animated background and the extra effects off. Saved in this browser. Default = off (full visuals). ----
  const perfOn = () => { try { return localStorage.getItem("biospine_bg3d") === "off"; } catch (_) { return false; } };
  function syncPerfUI() {
    const on = perfOn();
    document.body.classList.toggle("bg3d-off", on);
    qa("[data-perf-toggle]").forEach(b => {
      b.setAttribute("aria-pressed", on ? "true" : "false"); b.classList.toggle("on", on);
      b.innerHTML = b.classList.contains("side") ? (on ? "⚡ Performance: ON" : "⚡ Performance") : `⚡<span class="perf-text"> Performance mode${on ? ": ON" : ""}</span>`;
    });
    const pt = q("#perfToggle"); if (pt) pt.checked = on;
  }
  function setPerf(on, quiet) {
    try { localStorage.setItem("biospine_bg3d", on ? "off" : "on"); } catch (_) {}
    syncPerfUI(); if (window.bsBgRefresh) window.bsBgRefresh();
    if (!quiet) toast(on ? "⚡ Performance mode ON: animated background turned off" : "Performance mode off: animated background is back");
  }
  function initPerf() {
    qa("[data-perf-toggle]").forEach(b => b.addEventListener("click", () => setPerf(!perfOn())));
    const pt = q("#perfToggle"); if (pt) pt.addEventListener("change", () => setPerf(pt.checked));
    syncPerfUI();
  }

  // ---- Test mode: also send demo sessions to the account (default off) ----
  function initTestMode() {
    const t = q("#syncDemoToggle"); if (!t) return;
    t.checked = !!userSettings.syncDemo;
    t.addEventListener("change", () => {
      userSettings.syncDemo = t.checked; persistSettings();
      if (!t.checked) { toast("Test mode off: demo sessions stay on this device"); return; }
      if (isGuest || !sessionToken) { toast("Sign in to an account first, then demo sessions can be saved to it"); return; }
      const old = sessions.filter(s => !s.summaryOnly && s.source === "demo" && !s.synced).slice(0, 25);
      old.forEach(s => queuePending(s.id)); flushPending();
      toast(old.length ? `Test mode on: sending ${old.length} demo session${old.length === 1 ? "" : "s"} to your account` : "Test mode on: new demo sessions will be saved to your account");
    });
  }

  function initBody() {
    const live = () => {
      const i = bmiInfo(q("#authHeight") && q("#authHeight").value, q("#authWeight") && q("#authWeight").value), box = q("#authBmi");
      if (!box) return;
      box.textContent = i ? `Your BMI: ${i.bmi} · ${i.category}` : "Enter your height and weight to see your BMI.";
      box.className = "bmi-live" + (i ? " " + i.key : "");
    };
    ["#authHeight", "#authWeight"].forEach(s => q(s) && q(s).addEventListener("input", live));
    if (!q("#bodyPanel")) return;
    q("#bodySave").addEventListener("click", async () => {
      const h = q("#bodyHeight").value, w = q("#bodyWeight").value, i = bmiInfo(h, w);
      if (!i) { q("#bodyMsg").textContent = "Please enter a height of 50-250 cm and a weight of 15-350 kg."; return; }
      showBmi(i);
      if (isGuest || !sessionToken) { q("#bodyMsg").textContent = "Calculated. Create a free account to save it."; return; }
      try {
        const { res, data } = await api("/api/user/body", { method: "POST", body: { heightCm: +h, weightKg: +w } });
        q("#bodyMsg").textContent = res.ok && data.success ? "Saved ✓" : (data.error || "Could not save. Please try again.");
      } catch (_) { q("#bodyMsg").textContent = "Could not reach the server."; }
    });
  }
  function showBmi(i) {
    q("#bmiCard").hidden = false; q("#bmiNum").textContent = i.bmi; q("#bmiCat").textContent = i.category;
    q("#bmiCat").className = "bmi-cat " + i.key;
    q("#bmiAdvice").textContent = `${BMI_ADVICE[i.key]} A healthy weight for your height is about ${i.lo}-${i.hi} kg.`;
    q("#bmiMark").style.left = clamp(((i.bmi - 15) / 25) * 100, 0, 100) + "%";
  }
  function fillBody(userData) {
    const b = userData && userData.body;
    if (!q("#bodyPanel") || !b) return;
    if (b.heightCm) q("#bodyHeight").value = b.heightCm;
    if (b.weightKg) q("#bodyWeight").value = b.weightKg;
    const i = bmiInfo(b.heightCm, b.weightKg); if (i) showBmi(i);
    q("#bodyMsg").textContent = i ? "" : "Add your height and weight to see your BMI.";
  }

  // =====================================================================
  // 9c. ANIMATED BACKGROUNDS
  //     home / log-in page : a large tilted DNA double helix in "plexus" style (particle dust + mesh lines,
  //                          glowing cyan base-pair rungs, a floating network of nodes, soft bokeh)
  //     inside the app     : slow aurora waves
  //     Pure canvas, no library. Pauses when hidden, 30 fps in the app, honours "reduce motion" and the Settings switch.
  // =====================================================================
  function initBg3D() {
    const cv = q("#bg3d"), land = q("#landingPage"), appShell = q("#appShell");
    if (!cv || !land || !cv.getContext) return;
    const ctx = cv.getContext("2d");
    const sceneNow = () => land.offsetParent !== null ? "home" : (appShell && appShell.offsetParent !== null ? "app" : null);
    const bgOn = () => { try { return localStorage.getItem("biospine_bg3d") !== "off"; } catch (_) { return true; } };
    const applyBodyClass = () => document.body.classList.toggle("bg3d-off", !bgOn());
    const light = () => document.documentElement.getAttribute("data-theme") === "light";
    const rnd = (a, b) => a + Math.random() * (b - a);
    let W = 0, H = 0, dpr = 1, running = false, tick = 0, mx = 0, my = 0, tx = 0, ty = 0, glow = null;
    applyBodyClass();
    const resize = () => { dpr = Math.min(2, window.devicePixelRatio || 1); W = cv.width = Math.round(innerWidth * dpr); H = cv.height = Math.round(innerHeight * dpr); cv.style.width = innerWidth + "px"; cv.style.height = innerHeight + "px"; glow = null; };
    resize(); window.addEventListener("resize", resize);
    window.addEventListener("pointermove", e => { tx = e.clientX / innerWidth - 0.5; ty = e.clientY / innerHeight - 0.5; }, { passive: true });

    // ---------------------------------------------------------------- DNA scene
    const small = innerWidth < 700;
    const STEPS = small ? 100 : 190, CLOUD = 4, TURNS = 2.7, LEN = 1500, RAD = 230, FOV = 900, CAM = 420, TILT = 0.36;
    const jitter = () => [rnd(-11, 11), rnd(-11, 11), rnd(-11, 11)];
    const strand = [0, 1].map(() => Array.from({ length: STEPS + 1 }, () => Array.from({ length: CLOUD }, jitter)));
    const rungs = Array.from({ length: Math.floor(STEPS / 3) + 1 }, () => ({ gap: rnd(0.26, 0.5), glow: rnd(0.55, 1), skip: Math.random() < 0.12 }));
    const NODES = small ? 40 : 90;
    const nodes = Array.from({ length: NODES }, (_, i) => ({ x: rnd(-1300, 1300), y: rnd(-800, 800), z: rnd(-200, 1100), ring: Math.random() < 0.22, ph: rnd(0, 6.28), i }));
    const bokeh = Array.from({ length: 7 }, () => ({ x: Math.random(), y: Math.random(), r: rnd(60, 150), ph: rnd(0, 6.28), a: rnd(0.04, 0.09) }));
    let sprite = null;
    const makeSprite = () => { const c = document.createElement("canvas"); c.width = c.height = 128; const g = c.getContext("2d"), r = g.createRadialGradient(64, 64, 0, 64, 64, 64); r.addColorStop(0, "rgba(255,255,255,0.9)"); r.addColorStop(1, "rgba(255,255,255,0)"); g.fillStyle = r; g.fillRect(0, 0, 128, 128); return c; };
    let cam = { ct: 1, st: 0, cy: 1, sy: 0, cp: 1, sp: 0, ox: 0, oy: 0 };
    function setCam(yaw, pitch, ox, oy) { cam = { ct: Math.cos(TILT), st: Math.sin(TILT), cy: Math.cos(yaw), sy: Math.sin(yaw), cp: Math.cos(pitch), sp: Math.sin(pitch), ox, oy }; }
    function proj(x, y, z) {
      const X = x * cam.ct - y * cam.st, Y = x * cam.st + y * cam.ct;                   // lean the helix over (like the video)
      const X2 = X * cam.cy + z * cam.sy, Z2 = -X * cam.sy + z * cam.cy;               // turn with the mouse
      const Y2 = Y * cam.cp - Z2 * cam.sp, Z3 = Y * cam.sp + Z2 * cam.cp;
      const f = FOV / (FOV + CAM + Z3);
      return { x: W / 2 + (X2 + cam.ox) * f * dpr, y: H / 2 + (Y2 + cam.oy) * f * dpr, f, z: Z3 };
    }
    function drawDNA(t) {
      const lt = light(), K = (lt ? 0.8 : 1) * (innerWidth < 900 ? 0.6 : 1);
      const silver = lt ? "62,82,110" : "214,228,244", cyan = lt ? "2,132,199" : "56,196,255", node = lt ? "71,100,140" : "170,200,230";
      if (!glow) { glow = ctx.createRadialGradient(W * 0.22, H * 0.12, 0, W * 0.22, H * 0.12, W * 0.7); glow.addColorStop(0, lt ? "rgba(56,139,249,0.16)" : "rgba(30,110,200,0.30)"); glow.addColorStop(1, "rgba(0,0,0,0)"); }
      ctx.globalCompositeOperation = "source-over"; ctx.fillStyle = glow; ctx.fillRect(0, 0, W, H);
      ctx.globalCompositeOperation = lt ? "source-over" : "lighter";
      const spin = t * 0.00035, yaw = mx * 0.6 + Math.sin(t * 0.00017) * 0.22, pitch = my * 0.22;
      setCam(yaw, pitch, innerWidth > 900 ? innerWidth * 0.24 : 0, Math.sin(t * 0.0002) * 20);
      // backbone positions (3 particles per step, each with its own fixed jitter)
      const P = [[], []];
      for (let s = 0; s < 2; s++) for (let i = 0; i <= STEPS; i++) {
        const u = i / STEPS, y = (u - 0.5) * LEN, a = spin + u * TURNS * 6.2832 + s * 3.1416, x = RAD * Math.cos(a), z = RAD * Math.sin(a);
        P[s].push(strand[s][i].map(j => proj(x + j[0], y + j[1], z + j[2])));
      }
      // mesh lines along each strand (the jagged "plexus" look)
      ctx.lineJoin = "round";
      for (let s = 0; s < 2; s++) {
        ctx.lineWidth = 1.2 * dpr; ctx.strokeStyle = `rgba(${silver},${0.62 * K})`; ctx.beginPath();
        P[s].forEach((c, i) => { i ? ctx.lineTo(c[0].x, c[0].y) : ctx.moveTo(c[0].x, c[0].y); }); ctx.stroke();
        ctx.lineWidth = 0.8 * dpr; ctx.strokeStyle = `rgba(${silver},${0.40 * K})`; ctx.beginPath();
        P[s].forEach((c, i) => { const q1 = c[(i + 1) % CLOUD]; i ? ctx.lineTo(q1.x, q1.y) : ctx.moveTo(q1.x, q1.y); }); ctx.stroke();
        ctx.beginPath();
        P[s].forEach((c, i) => { const q2 = c[(i * 2 + 2) % CLOUD]; i ? ctx.lineTo(q2.x, q2.y) : ctx.moveTo(q2.x, q2.y); }); ctx.stroke();
      }
      // particle dust on the backbones
      for (let s = 0; s < 2; s++) P[s].forEach(c => c.forEach(p => {
        const sz = (1.1 + p.f * 2.2) * dpr; ctx.fillStyle = `rgba(${silver},${Math.min(1, 0.4 + p.f * 0.7) * K})`; ctx.fillRect(p.x - sz / 2, p.y - sz / 2, sz, sz);
      }));
      // faint link between the two halves of every base pair
      ctx.lineWidth = 0.8 * dpr;
      for (let i = 0; i <= STEPS; i += 3) { const A = P[0][i][0], B = P[1][i][0]; ctx.strokeStyle = `rgba(${cyan},${0.14 * K})`; ctx.beginPath(); ctx.moveTo(A.x, A.y); ctx.lineTo(B.x, B.y); ctx.stroke(); }
      // glowing base pairs (rungs)
      for (let i = 0, r = 0; i <= STEPS; i += 3, r++) {
        const rg = rungs[r]; if (!rg || rg.skip) continue;
        const A = P[0][i][0], B = P[1][i][0], g = rg.gap / 2;
        const ax = A.x + (B.x - A.x) * (0.5 - g), ay = A.y + (B.y - A.y) * (0.5 - g), bx = A.x + (B.x - A.x) * (0.5 + g), by = A.y + (B.y - A.y) * (0.5 + g);
        const f = (A.f + B.f) / 2;
        [[A.x, A.y, ax, ay], [B.x, B.y, bx, by]].forEach(([x1, y1, x2, y2]) => {
          ctx.lineCap = "round";
          ctx.strokeStyle = `rgba(${cyan},${0.10 * rg.glow * K})`; ctx.lineWidth = 11 * f * dpr; ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();   // soft glow
          ctx.strokeStyle = `rgba(${cyan},${0.9 * rg.glow * K})`; ctx.lineWidth = 3 * f * dpr; ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();      // bright core
        });
        ctx.fillStyle = `rgba(255,255,255,${0.75 * rg.glow * K})`; ctx.fillRect(ax - 1.5 * dpr, ay - 1.5 * dpr, 3 * dpr, 3 * dpr); ctx.fillRect(bx - 1.5 * dpr, by - 1.5 * dpr, 3 * dpr, 3 * dpr);
      }
      // floating network (nodes and thin lines, a few ring-shaped nodes like the video)
      const N = nodes.map(n => proj(n.x + Math.sin(t * 0.0002 + n.ph) * 40, n.y + Math.cos(t * 0.00017 + n.ph) * 30, n.z));
      ctx.lineWidth = 0.8 * dpr;
      for (let i = 0; i < N.length; i++) for (let j = i + 1; j < Math.min(N.length, i + 9); j++) {
        const d = Math.hypot(N[i].x - N[j].x, N[i].y - N[j].y) / dpr;
        if (d < 190) { ctx.strokeStyle = `rgba(${node},${(0.2 * (1 - d / 190) * Math.min(N[i].f, N[j].f) * 1.5 * K).toFixed(3)})`; ctx.beginPath(); ctx.moveTo(N[i].x, N[i].y); ctx.lineTo(N[j].x, N[j].y); ctx.stroke(); }
      }
      N.forEach((p, i) => {
        const al = Math.min(0.8, 0.2 + p.f * 0.5) * K;
        if (nodes[i].ring) { ctx.strokeStyle = `rgba(${node},${al})`; ctx.lineWidth = 1 * dpr; ctx.beginPath(); ctx.arc(p.x, p.y, 4 * p.f * 1.6 * dpr, 0, 6.2832); ctx.stroke(); }
        ctx.fillStyle = `rgba(${node},${al})`; ctx.beginPath(); ctx.arc(p.x, p.y, Math.max(0.8, 1.8 * p.f * 1.5) * dpr, 0, 6.2832); ctx.fill();
      });
      // soft out-of-focus lights
      if (!sprite) sprite = makeSprite();
      ctx.globalCompositeOperation = lt ? "source-over" : "lighter";
      bokeh.forEach(b => { const r = b.r * dpr, bx = (b.x + Math.sin(t * 0.00006 + b.ph) * 0.03) * W, by = (b.y + Math.cos(t * 0.00005 + b.ph) * 0.03) * H; ctx.globalAlpha = b.a * (lt ? 0.5 : 1); ctx.drawImage(sprite, bx - r, by - r, r * 2, r * 2); });
      ctx.globalAlpha = 1;
    }

    // ---------------------------------------------------------------- AURORA scene (inside the app)
    const strips = {};
    const strip = rgb => {
      if (strips[rgb]) return strips[rgb];
      const c = document.createElement("canvas"); c.width = 1; c.height = 256; const g = c.getContext("2d"), gr = g.createLinearGradient(0, 0, 0, 256);
      gr.addColorStop(0, `rgba(${rgb},0)`); gr.addColorStop(0.05, `rgba(${rgb},0.95)`); gr.addColorStop(0.3, `rgba(${rgb},0.38)`); gr.addColorStop(1, `rgba(${rgb},0)`);
      g.fillStyle = gr; g.fillRect(0, 0, 1, 256); return (strips[rgb] = c);
    };
    const LAYERS = [
      { rgb: "46,204,113", base: 0.20, amp: 0.07, f1: 1.1, f2: 2.6, sp: 0.00016, h: 0.42, a: 0.55 },
      { rgb: "56,189,248", base: 0.32, amp: 0.08, f1: 1.7, f2: 3.1, sp: 0.00021, h: 0.40, a: 0.50 },
      { rgb: "167,139,250", base: 0.44, amp: 0.06, f1: 0.9, f2: 2.2, sp: 0.00013, h: 0.38, a: 0.38 },
    ];
    const stars = Array.from({ length: 70 }, () => ({ x: Math.random(), y: Math.random() * 0.6, ph: rnd(0, 6.28), s: rnd(0.6, 1.6) }));
    function drawAurora(t) {
      const lt = light();
      ctx.globalCompositeOperation = lt ? "source-over" : "lighter";
      const col = Math.max(4, Math.round(5 * dpr));
      if (!lt) stars.forEach(s => { ctx.globalAlpha = 0.25 + 0.35 * Math.abs(Math.sin(t * 0.0008 + s.ph)); ctx.fillStyle = "#fff"; ctx.fillRect(s.x * W, s.y * H, s.s * dpr, s.s * dpr); });
      LAYERS.forEach((L, li) => {
        const img = strip(L.rgb), ph = li * 1.7;
        for (let x = 0; x < W; x += col) {
          const nx = x / W;
          const y = H * (L.base + L.amp * Math.sin(nx * L.f1 * 6.2832 + t * L.sp * 3 + ph) + L.amp * 0.6 * Math.sin(nx * L.f2 * 6.2832 - t * L.sp * 4.1 + ph));
          const h = H * L.h * (0.72 + 0.28 * Math.sin(nx * 9 + t * L.sp * 6 + ph));
          ctx.globalAlpha = L.a * (0.55 + 0.45 * Math.sin(nx * 5 + t * L.sp * 5 + ph)) * (lt ? 0.45 : 1);
          ctx.drawImage(img, 0, 0, 1, 256, x, y, col + 1, h);
        }
      });
      ctx.globalAlpha = 1;
    }

    function draw(t) {
      ctx.globalCompositeOperation = "source-over"; ctx.globalAlpha = 1; ctx.clearRect(0, 0, W, H);
      mx += (tx - mx) * 0.04; my += (ty - my) * 0.04;
      if (sceneNow() === "app") drawAurora(t); else drawDNA(t);
    }
    function loop(t) {
      const m = sceneNow(), show = !!m && bgOn();
      cv.style.display = show ? "block" : "none";
      if (!show || document.hidden) { running = false; return; }
      if (m === "app" && (++tick & 1)) { requestAnimationFrame(loop); return; }       // 30 fps is plenty behind the dashboard
      draw(t); if (!reduced) requestAnimationFrame(loop); else running = false;
    }
    const kick = () => { applyBodyClass(); if (!running && sceneNow() && bgOn() && !document.hidden) { running = true; requestAnimationFrame(loop); } else if (!bgOn()) cv.style.display = "none"; };
    window.bsBgRefresh = kick;
    document.addEventListener("visibilitychange", kick);
    setInterval(kick, 1000);                       // wakes up again when the scene changes (sign-in / sign-out)
    kick();
  }

  // =====================================================================
  // 10. WIRING
  // =====================================================================
  bsHooks.viewShown = v => {
    if (v === "rewards") renderRewards();
    if (v === "breaktime") renderBreakUI();
    if (v === "history") { renderReport(); if (typeof renderSyncStatus === "function") renderSyncStatus(); }
    if (v === "device") deviceLive();
  };
  bsHooks.afterLogin = userData => {
    fillBody(userData);
    myReview = (userData && userData.review && userData.review.mine) || null;
    // bring this account's progress onto this device (and the other way round)
    serverXp = (userData && userData.sessionXp) || 0; serverStats = (userData && userData.stats) || null;
    if (userData && userData.extras) { const m = mergeEx(ex(), userData.extras); put("extras", m); pushExtras(); }
    rewReady = false; computeRewards(false); rewReady = true; renderRewards(); renderBreakUI(); renderReport();
    if (userData && userData.review && userData.review.promptDue) setTimeout(showReview, 8000);
  };
  bsHooks.sessionSaved = () => { renderRewards(); renderReport(); };
  bsHooks.rewardsChanged = () => renderRewards();
  bsHooks.afterSync = d => {
    if (d && d.sessionXp != null) serverXp = d.sessionXp;
    if (d && d.stats) serverStats = d.stats;
    renderRewards();
    if (d && d.reviewPromptDue) setTimeout(showReview, 1800);
  };

  function init() {
    initTheme(); initCounters(); initHomeDemo(); initSlider(); initFlipCards(); loadHomeReviews();
    initBreaks(); initLab(); initReview(); initReports(); initPerf(); initTestMode(); initBody(); initBg3D();
    const y = q("#yr"); if (y) y.textContent = new Date().getFullYear();
    setInterval(() => { if (q("#appShell") && q("#appShell").style.display !== "none") { breakLoop(); deviceLive(); } }, 1000);
    setInterval(() => { if (q("#appShell") && q("#appShell").style.display !== "none") { rewReady = true; renderRewards(); } }, 20000);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
