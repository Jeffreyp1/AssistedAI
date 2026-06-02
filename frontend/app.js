/* AssistedAI frontend — view router + renderers, fed by the FastAPI backend.
   Overview + list use the lightweight /api/patients feed; the profile fetches
   the full record on demand; "Analyze" posts to /api/patients/{id}/analyze. */

(function () {
  "use strict";

  var app = document.getElementById("app");

  var FACILITY = { name: "Facility", as_of: new Date().toISOString() };
  var SUMMARY = { total: 0, counts: { attention: 0, watch: 0, improving: 0, stable: 0 } };
  var LIST = []; // lightweight resident items

  var STATUS_LABEL = { attention: "Needs attention", watch: "Watch", improving: "Improving", stable: "Stable" };
  var TREND_LABEL = { eating: "Eating", social: "Social", activity: "Activity" };
  var AREA_LABEL = {
    behavioral: "Behavioral analysis",
    treatment: "Treatment research",
    trials: "Clinical trials",
    drug_safety: "Drug safety",
  };

  var state = { view: "overview", patientId: null, patient: null, query: "", filter: "all" };

  /* ---------- net ---------- */
  function fetchJSON(url, opts) {
    return fetch(url, opts).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  /* ---------- helpers ---------- */
  function el(html) { var t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstChild; }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function initials(name) { return name.split(" ").map(function (p) { return p[0]; }).slice(0, 2).join("").toUpperCase(); }
  function trendDir(v) { return v === "improving" ? "up" : v === "declining" ? "down" : "flat"; }
  function trendArrow(v) { return v === "improving" ? "↑" : v === "declining" ? "↓" : "→"; }
  function trendWord(v) { return v.charAt(0).toUpperCase() + v.slice(1); }
  function fmtDate(iso) {
    var d = new Date(iso);
    return isNaN(d) ? "" : d.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" });
  }
  function badge(status) { return '<span class="badge s-' + status + '"><span class="dot"></span>' + STATUS_LABEL[status] + "</span>"; }

  /* ---------- overview ---------- */
  function renderOverview() {
    var counts = SUMMARY.counts;
    var flagged = LIST.filter(function (p) { return p.status === "attention"; });
    var updates = LIST.filter(function (p) { return p.latest_note; })
      .map(function (p) { return { id: p.id, name: p.name, note: p.latest_note }; })
      .sort(function (a, b) { return a.note.date < b.note.date ? 1 : -1; }).slice(0, 5);

    var v = el('<section class="view"></section>');
    v.appendChild(el(
      '<div class="page-head"><div class="eyebrow">Facility overview</div>' +
      "<h1>Good morning</h1>" +
      '<p class="sub">' + esc(FACILITY.name) + " · " + SUMMARY.total + " residents under care today.</p></div>"
    ));

    var stats = el('<div class="stats stagger"></div>');
    stats.appendChild(el(
      '<div class="tile" style="--i:0"><div class="tile-label">Total residents</div>' +
      '<div class="tile-num num">' + SUMMARY.total + '</div><div class="tile-cap">Across all units</div></div>'
    ));
    var att = el(
      '<button class="tile accent-attention" style="--i:1"><span class="corner"></span>' +
      '<div class="tile-label">Needs attention</div><div class="tile-num num">' + counts.attention +
      '</div><div class="tile-cap">Tap to review &rarr;</div></button>'
    );
    att.addEventListener("click", function () { go("list", { filter: "attention" }); });
    stats.appendChild(att);
    var imp = el(
      '<button class="tile accent-improving" style="--i:2"><span class="corner"></span>' +
      '<div class="tile-label">Improving</div><div class="tile-num num">' + counts.improving +
      '</div><div class="tile-cap">Trending up</div></button>'
    );
    imp.addEventListener("click", function () { go("list", { filter: "improving" }); });
    stats.appendChild(imp);
    stats.appendChild(el(
      '<div class="tile" style="--i:3"><div class="tile-label">Stable &amp; watch</div>' +
      '<div class="tile-num num">' + (counts.stable + counts.watch) + '</div>' +
      '<div class="tile-cap">' + counts.watch + " on watch</div></div>"
    ));
    v.appendChild(stats);

    var cols = el('<div class="cols"></div>');

    var leftPanel = el('<div class="panel"></div>');
    var ph = el('<div class="panel-head"><h3>Needs attention now</h3></div>');
    var viewAll = el('<button class="linkish">View all &rarr;</button>');
    viewAll.addEventListener("click", function () { go("list", { filter: "attention" }); });
    ph.appendChild(viewAll);
    leftPanel.appendChild(ph);
    var rowsWrap = el('<div class="panel-body"><div class="rows"></div></div>');
    var rows = rowsWrap.querySelector(".rows");
    flagged.forEach(function (p) { rows.appendChild(residentRow(p)); });
    if (!flagged.length) rows.appendChild(el('<div class="empty">No residents need attention.</div>'));
    leftPanel.appendChild(rowsWrap);
    cols.appendChild(leftPanel);

    var rightPanel = el('<div class="panel"><div class="panel-head"><h3>Recent updates</h3></div></div>');
    var feed = el('<div class="panel-body"><div class="feed"></div></div>');
    var feedInner = feed.querySelector(".feed");
    updates.forEach(function (u) {
      var item = el(
        '<button class="feed-item row" style="display:block">' +
        '<div class="fi-top"><span class="fi-who">' + esc(u.name) + '</span>' +
        '<span class="fi-time">' + esc(u.note.date.split(" ")[0]) + "</span></div>" +
        '<div class="fi-text">' + esc(u.note.text) + "</div></button>"
      );
      item.addEventListener("click", function () { go("profile", { patientId: u.id }); });
      feedInner.appendChild(item);
    });
    rightPanel.appendChild(feed);
    cols.appendChild(rightPanel);
    v.appendChild(cols);
    v.appendChild(el('<p class="proto-note">Mock resident data · AI insights via PubMed, ClinicalTrials.gov &amp; OpenFDA</p>'));
    return v;
  }

  function residentRow(p) {
    var r = el(
      '<button class="row s-' + p.status + '">' +
      '<span class="avatar">' + initials(p.name) + "</span>" +
      '<span class="who"><span class="nm">' + esc(p.name) +
      '<span class="room-chip">Rm ' + esc(p.room) + "</span></span>" +
      '<span class="sm">' + esc(p.summary) + "</span></span>" +
      '<span class="meta-right">' + badge(p.status) + "</span></button>"
    );
    r.addEventListener("click", function () { go("profile", { patientId: p.id }); });
    return r;
  }

  /* ---------- attention list ---------- */
  function renderList() {
    var v = el('<section class="view"></section>');
    v.appendChild(el(
      '<div class="page-head"><div class="eyebrow">Residents</div><h1>Who needs you</h1>' +
      '<p class="sub">Search by name or room, or filter by how each resident is trending.</p></div>'
    ));

    var toolbar = el('<div class="toolbar"></div>');
    var search = el(
      '<div class="search"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.2-3.2"/></svg>' +
      '<input type="text" placeholder="Search residents…" /></div>'
    );
    var input = search.querySelector("input");
    input.value = state.query;
    input.addEventListener("input", function () { state.query = input.value; refreshList(); });
    toolbar.appendChild(search);

    var chips = el('<div class="chips"></div>');
    [["all", "All"], ["attention", "Attention"], ["watch", "Watch"], ["improving", "Improving"], ["stable", "Stable"]].forEach(function (f) {
      var c = el('<button class="chip" data-f="' + f[0] + '">' + f[1] + "</button>");
      c.setAttribute("aria-pressed", state.filter === f[0] ? "true" : "false");
      c.addEventListener("click", function () { state.filter = f[0]; refreshList(); });
      chips.appendChild(c);
    });
    toolbar.appendChild(chips);
    v.appendChild(toolbar);
    v.appendChild(el('<div class="count-line" id="count-line"></div>'));
    v.appendChild(el('<div class="list-card"><div class="rows" id="list-rows"></div></div>'));
    return v;
  }

  function currentList() {
    var q = state.query.trim().toLowerCase();
    return LIST.filter(function (p) {
      var matchF = state.filter === "all" || p.status === state.filter;
      var matchQ = !q || p.name.toLowerCase().indexOf(q) > -1 || p.room.indexOf(q) > -1;
      return matchF && matchQ;
    });
  }

  function refreshList() {
    app.querySelectorAll(".chip").forEach(function (c) {
      c.setAttribute("aria-pressed", c.getAttribute("data-f") === state.filter ? "true" : "false");
    });
    var rows = document.getElementById("list-rows");
    var countLine = document.getElementById("count-line");
    if (!rows) return;
    rows.innerHTML = "";
    var list = currentList();
    countLine.textContent = list.length + (list.length === 1 ? " resident" : " residents") +
      (state.filter === "all" ? "" : " · " + STATUS_LABEL[state.filter]);
    if (!list.length) { rows.appendChild(el('<div class="empty">No residents match your search.</div>')); return; }
    list.forEach(function (p) { rows.appendChild(residentRow(p)); });
  }

  /* ---------- profile ---------- */
  function renderProfile() {
    var p = state.patient;
    if (!p) return el('<div class="empty">Loading resident…</div>');

    var v = el('<section class="view"></section>');
    var back = el('<button class="back"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6"/></svg> Back to residents</button>');
    back.addEventListener("click", function () { go("list", {}); });
    v.appendChild(back);

    v.appendChild(el(
      '<div class="profile-head"><div class="big-avatar">' + initials(p.name) + "</div>" +
      '<div class="ph-main"><h1>' + esc(p.name) + "</h1>" +
      '<div class="ph-meta">Room ' + esc(p.room) + " · " + p.age + " · " + (p.sex === "F" ? "Female" : "Male") +
      " · Admitted " + esc(p.admission_date) + "</div>" +
      '<div class="dx-chips">' + p.diagnoses.map(function (d) { return '<span class="dx">' + esc(d) + "</span>"; }).join("") + "</div></div>" +
      "<div>" + badge(p.status) + "</div></div>"
    ));

    var tc = el('<div class="trend-cards"></div>');
    Object.keys(TREND_LABEL).forEach(function (k) {
      var dir = trendDir(p.trends[k]);
      tc.appendChild(el(
        '<div class="tcard ' + dir + '"><div class="tc-label">' + TREND_LABEL[k] + "</div>" +
        '<div class="tc-val"><span class="arrow">' + trendArrow(p.trends[k]) + "</span>" + trendWord(p.trends[k]) + "</div></div>"
      ));
    });
    v.appendChild(tc);

    v.appendChild(aiPanel(p));

    var grid = el('<div class="grid-2"></div>');
    grid.appendChild(adlCard(p));
    grid.appendChild(vitalsCard(p));
    v.appendChild(grid);

    var grid2 = el('<div class="grid-2"></div>');
    grid2.appendChild(notesCard(p));
    grid2.appendChild(medsCard(p));
    v.appendChild(grid2);
    return v;
  }

  function adlCard(p) {
    var latest = p.adl[p.adl.length - 1];
    var names = [["eating", "Eating"], ["mobility", "Mobility"], ["bathing", "Bathing"], ["dressing", "Dressing"], ["toileting", "Toileting"]];
    var rows = names.map(function (n) {
      var score = latest[n[0]];
      var segs = "";
      for (var i = 1; i <= 5; i++) {
        var cls = i <= score ? "seg on" + (score <= 2 ? " low" : score === 3 ? " mid" : "") : "seg";
        segs += '<span class="' + cls + '"></span>';
      }
      return '<div class="adl-row"><span class="adl-name">' + n[1] + '</span><span class="adl-bar">' + segs + '</span><span class="adl-score num">' + score + "/5</span></div>";
    }).join("");
    return el('<div class="card"><h3>Daily function</h3><div class="card-in">' + rows + '<p class="ai-disclaimer">Latest assessment ' + esc(latest.date) + " · 5 = fully independent</p></div></div>");
  }

  function vitalsCard(p) {
    var last = p.vitals[p.vitals.length - 1];
    var prev = p.vitals.length > 1 ? p.vitals[p.vitals.length - 2] : last;
    var dw = last.weight - prev.weight;
    var wcls = dw > 0 ? "up" : dw < 0 ? "down" : "flat";
    var wsign = dw > 0 ? "+" : "";
    var inner =
      '<div class="vitals">' +
      '<div class="vital"><div class="v-label">Weight</div><div class="v-num num">' + last.weight + '<span class="v-unit">lb</span></div>' +
      '<div class="v-delta ' + wcls + '">' + (dw === 0 ? "no change" : wsign + dw + " lb") + "</div></div>" +
      '<div class="vital"><div class="v-label">Blood pressure</div><div class="v-num num">' + esc(last.bp) + '</div><div class="v-delta flat">mmHg</div></div>' +
      '<div class="vital"><div class="v-label">Heart rate</div><div class="v-num num">' + last.hr + '<span class="v-unit">bpm</span></div><div class="v-delta flat">resting</div></div>' +
      "</div>";
    return el('<div class="card"><h3>Vitals</h3><div class="card-in">' + inner + '<p class="ai-disclaimer">As of ' + esc(last.date) + "</p></div></div>");
  }

  function notesCard(p) {
    var notes = p.notes.map(function (n) {
      return '<div class="note"><div class="n-top"><span class="n-who">' + esc(n.author) + '</span><span class="n-time">' + esc(n.date) + "</span></div>" +
        '<div class="n-text">' + esc(n.text) + "</div></div>";
    }).join("");
    return el('<div class="card"><h3>Care notes</h3><div class="card-in"><div class="timeline">' + notes + "</div></div></div>");
  }

  function medsCard(p) {
    var meds = (p.medications || []).map(function (m) {
      return '<div class="med"><div class="m-name">' + esc(m.name) + '</div><div class="m-dose">' + esc(m.dose) + "</div></div>";
    }).join("");
    return el('<div class="card"><h3>Medications</h3><div class="card-in"><div class="meds">' + (meds || '<span class="ai-disclaimer">None on file</span>') + "</div></div></div>");
  }

  function aiPanel(p) {
    var panel = el(
      '<div class="ai"><div class="ai-head"><div class="ai-title">' +
      '<span class="spark"><svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M18 6l-2.5 2.5M8.5 15.5 6 18"/></svg></span>' +
      "<div><h3>AI insight</h3><div class=\"sub\">Drawn from notes, trends &amp; live medical sources</div></div></div>" +
      '<button class="btn" id="analyze-btn">Analyze resident</button></div>' +
      '<div class="ai-body" id="ai-body" hidden></div></div>'
    );
    var btn = panel.querySelector("#analyze-btn");
    var body = panel.querySelector("#ai-body");
    btn.addEventListener("click", function () {
      btn.disabled = true; btn.textContent = "Analyzing…";
      body.hidden = false;
      body.innerHTML = '<p class="ai-disclaimer">Reviewing record and consulting medical sources…</p>' +
        '<div class="shimmer-line"></div><div class="shimmer-line"></div><div class="shimmer-line short"></div>';
      fetchJSON("/api/patients/" + p.id + "/analyze", { method: "POST" })
        .then(function (res) { revealAnalysis(body, res); btn.textContent = "Re-analyze"; })
        .catch(function () { body.innerHTML = '<p class="ai-disclaimer">Analysis failed. Check the server and try again.</p>'; btn.textContent = "Analyze resident"; })
        .then(function () { btn.disabled = false; });
    });
    return panel;
  }

  function revealAnalysis(body, a) {
    var areas = (a.areas || []).map(function (x) { return '<span class="area-tag">' + (AREA_LABEL[x] || x) + "</span>"; }).join("");
    var research = "";
    if (a.research && a.research.length) {
      research = '<div class="research"><h4>Supporting sources</h4>' +
        a.research.map(function (c) {
          return '<div class="cite"><span class="src">' + esc(c.source) + '</span><span><span class="ct">' + esc(c.title) + '</span> <span class="cr">' + esc(c.ref) + "</span></span></div>";
        }).join("") + "</div>";
    }
    var simNote = a.simulated
      ? '<p class="ai-disclaimer">Illustrative result (no API key set — showing a saved example).</p>'
      : '<p class="ai-disclaimer">AI-generated decision support. Not a diagnosis — confirm with a clinician before acting.</p>';
    body.innerHTML =
      '<div class="ai-meta"><span class="conf ' + (a.confidence || "moderate") + '">Confidence: ' + (a.confidence || "moderate") + "</span>" + areas + "</div>" +
      '<p class="ai-conclusion">' + esc(a.conclusion) + "</p>" + research + simNote;
  }

  /* ---------- router ---------- */
  function go(view, opts) {
    opts = opts || {};
    state.view = view;
    if (opts.filter !== undefined) state.filter = opts.filter;
    window.scrollTo({ top: 0, behavior: "smooth" });

    if (view === "profile") {
      state.patientId = opts.patientId;
      state.patient = null;
      render(); // show "Loading resident…"
      fetchJSON("/api/patients/" + opts.patientId)
        .then(function (full) { if (state.view === "profile" && state.patientId === opts.patientId) { state.patient = full; render(); } })
        .catch(function () { app.innerHTML = '<div class="empty">Could not load this resident.</div>'; });
      return;
    }
    render();
  }

  function render() {
    app.innerHTML = "";
    var node;
    if (state.view === "list") node = renderList();
    else if (state.view === "profile") node = renderProfile();
    else node = renderOverview();
    app.appendChild(node);
    if (state.view === "list") refreshList();
  }

  /* ---------- boot ---------- */
  function boot() {
    Promise.all([fetchJSON("/api/summary"), fetchJSON("/api/patients")])
      .then(function (res) {
        SUMMARY = res[0];
        FACILITY = res[0].facility;
        LIST = res[1];
        document.getElementById("fac-name").textContent = FACILITY.name;
        document.getElementById("fac-date").textContent = fmtDate(FACILITY.as_of);
        render();
      })
      .catch(function () {
        app.innerHTML = '<div class="empty">Could not reach the AssistedAI server.<br/>Start the backend (uvicorn main:app) and reload.</div>';
      });
  }

  boot();
})();
