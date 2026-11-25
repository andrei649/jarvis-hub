import { createBrainDataset, hydrateServerBrainDataset } from "./brain-data.js";
import { KnowledgeGalaxy } from "./galaxy.js";
import { obsidianOpenUri } from "./obsidian-source.js";
import { JarvisHUD } from "./jarvis-hud.js";
import { RobotWorkshop } from "./workshop-robot.js";
import { HouseWorkshop } from "./workshop-house.js";
import { WorkshopProjects } from "./workshop-projects.js";
import { ComputerUseController } from "./computer-use.js";
import { AgentEngine } from "./agent-engine.js";
import { HUB, apiGet, apiPost, applyBackendMode } from "./api.js";
import { escapeHtml, filterRowsHtml, hubRowsHtml, modelOptionsHtml, sourceCardsHtml } from "./templates.js";

class JarvisOSApp {
  constructor() {
    this.activeView = "galaxy"; // 'galaxy' | 'robot' | 'house' | 'computer'
    this.workshopViewRevision = 0;
    this.dataset = createBrainDataset();
    this.oauthPollTimer = null;

    this.hud = new JarvisHUD({
      onCommand: (cmd) => this.agent.handleCommand(cmd),
      onToggleFocus: (on) => {
        this.galaxy.isolateMode = on;
        this.galaxy.refreshVisualHighlights();
      },
    });

    this.galaxy = new KnowledgeGalaxy(document.getElementById("galaxy-canvas"), this.dataset, {
      onSelectNode: (node, neighborIndices) => this._renderInspectorNode(node, neighborIndices),
      onPathTraced: (pathNodes) => this._renderInspectorPath(pathNodes),
      onClearSelection: () => this._renderInspectorDefault(),
    });

    const workshopCanvasWrap = document.getElementById("workshop-canvas-wrap");
    const calloutSvg = document.getElementById("exploded-svg");
    const calloutLabels = document.getElementById("exploded-labels");

    this.robotWorkshop = new RobotWorkshop(workshopCanvasWrap, calloutSvg, calloutLabels);
    this.houseWorkshop = new HouseWorkshop(workshopCanvasWrap, calloutSvg, calloutLabels);
    this.projects = new WorkshopProjects(this);
    this.computerUse = new ComputerUseController(this.hud);
    this.agent = new AgentEngine(this);

    this.telemetryStart = performance.now();

    this._restoreVisualPrefs();
    this._populateSidebarHubsAndFilters();
    this._bindGlobalControls();
    this._startRenderLoop();

    applyBackendMode();

    // Hydrate real Second Brain & AI status from server immediately
    this.loadServerBrain(false);
    this.refreshAIStatus(false);
  }

  /* =========================================================
     REAL SECOND BRAIN LOADING & SIDEBAR POPULATION
     ========================================================= */
  async loadServerBrain(reindex = false) {
    try {
      const res = await apiGet(`/brain${reindex ? "?reindex=1" : ""}`);
      const data = await res.json();
      if (data && data.ok) {
        if (data.mode === "demo_550" || !Array.isArray(data.nodes)) {
          this.dataset = createBrainDataset();
        } else {
          this.dataset = hydrateServerBrainDataset(data);
        }
        this.galaxy.setDataset(this.dataset);
        this._populateSidebarHubsAndFilters();
        this._renderDiscoveredSources(data.discoveredSources || []);
        const skipped = data.skipped && data.skipped.count ? data.skipped : null;
        const vaultMsg = document.getElementById("vault-status-msg");
        if (vaultMsg) vaultMsg.textContent = data.mode === "demo_550"
          ? "Showing the demo graph. Connect a vault to browse your notes."
          : `${data.discoveredSources?.[0]?.detail || "Vault indexed"}.`;
        if (skipped && vaultMsg) {
          const why = Object.entries(skipped.reasons || {})
            .map(([reason, count]) => `${count} ${reason}`)
            .join(", ");
          vaultMsg.textContent += ` Skipped ${skipped.count} entries (${why}).`;
        }
      }
    } catch (_) {
      this._populateSidebarHubsAndFilters();
    }
  }

  _populateSidebarHubsAndFilters() {
    document.getElementById("brand-title").textContent = this.dataset.brandTitle || "ANDREI OS";
    document.getElementById("vault-source-badge").textContent =
      this.dataset.vaultLabel || "Andrei OS Obsidian";
    document.getElementById("galaxy-stats-subtitle").textContent =
      `${this.dataset.nodes.length} nodes · ${this.dataset.edges.length} connections`;

    // Top Hubs
    const hubsEl = document.getElementById("top-hubs-list");
    const hubs = this.dataset.topHubs || [];
    hubsEl.innerHTML = hubRowsHtml(hubs, this.dataset.nodes);

    hubsEl.querySelectorAll(".hub-row").forEach((row) => {
      row.addEventListener("click", () => {
        const idx = Number(row.dataset.nodeIdx);
        hubsEl.querySelectorAll(".hub-row").forEach((r) => r.classList.remove("active"));
        row.classList.add("active");
        this.galaxy.focusNode(idx, true);
      });
    });

    // Right Filter Legend
    const filterEl = document.getElementById("filter-list");
    const cats = this.dataset.categories || [];
    filterEl.innerHTML = filterRowsHtml(cats);

    filterEl.querySelectorAll(".filter-row").forEach((row) => {
      row.addEventListener("click", () => {
        const cat = row.dataset.cat;
        if (this.galaxy.mutedCategories.has(cat)) {
          this.galaxy.mutedCategories.delete(cat);
          row.classList.remove("muted");
        } else {
          this.galaxy.mutedCategories.add(cat);
          row.classList.add("muted");
        }
        this.galaxy.refreshVisualHighlights();
      });
    });
  }

  _renderDiscoveredSources(sources) {
    const el = document.getElementById("discovered-sources-list");
    if (!el) return;
    if (!sources.length) {
      el.innerHTML = `<div class="source-item-card"><div class="source-item-detail">Switch to Andrei OS mode to inspect local vaults.</div></div>`;
      return;
    }
    el.innerHTML = sourceCardsHtml(sources);
  }

  _escapeHtml(str) {
    return escapeHtml(str);
  }

  _renderInspectorDefault() {
    document.querySelectorAll("#top-hubs-list .hub-row").forEach((r) => r.classList.remove("active"));
    document.getElementById("inspector-card").innerHTML = `
      <p class="inspector-placeholder">
        Click any node to focus it and read the real Markdown note from your vault. Shift-click a second node to trace the shortest semantic path.
      </p>
    `;
  }

  async _renderInspectorNode(node, neighborIndices) {
    const topNeighbors = neighborIndices.slice(0, 8).map((i) => this.dataset.nodes[i]).filter(Boolean);
    const card = document.getElementById("inspector-card");
    const cleanBody = (node.body || "").replace(/^#+\s*/gm, "").trim();
    const sourceUri = obsidianOpenUri(node.obsidianSource);

    card.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;margin-bottom:4px;">
        <div class="inspector-node-title" style="margin-bottom:0;">${this._escapeHtml(node.title)}</div>
        <button id="inspector-unfocus-btn" class="link-emerald" style="margin-top:0;flex-shrink:0;">✕ Unfocus</button>
      </div>
      <div class="inspector-node-meta">
        <span>● ${this._escapeHtml(node.category)}</span>
        <span>·</span>
        <span>${neighborIndices.length} links</span>
      </div>
      ${node.relPath ? `<div class="inspector-path-badge">${this._escapeHtml(node.relPath)}</div>` : ""}
      ${sourceUri ? `<a class="inspector-source-link" href="${this._escapeHtml(sourceUri)}">Open in Obsidian</a>` : ""}
      <div class="inspector-node-body" id="inspector-body-content">${this._escapeHtml(cleanBody)}</div>
      <div class="inspector-neighbors">
        ${topNeighbors
          .map((nb) => `<button class="neighbor-chip" data-idx="${Number(nb.index)}">${this._escapeHtml(nb.title)}</button>`)
          .join("")}
      </div>
    `;

    document.getElementById("inspector-unfocus-btn").addEventListener("click", () => {
      this.galaxy.clearSelection();
      this.galaxy.fitView();
    });
    card.querySelectorAll(".neighbor-chip").forEach((btn) => {
      btn.addEventListener("click", () => this.galaxy.focusNode(Number(btn.dataset.idx), true));
    });

    // On-demand hydration if a file was ever cloud-evicted
    if (node.cloudEvicted && node.relPath) {
      try {
        const res = await apiGet(`/brain/note?relPath=${encodeURIComponent(node.relPath)}`);
        const d = await res.json();
        if (d.ok && d.body) {
          node.body = d.body;
          node.cloudEvicted = false;
          const bodyEl = document.getElementById("inspector-body-content");
          if (bodyEl) bodyEl.textContent = d.body.replace(/^#+\s*/gm, "").trim();
        }
      } catch (_) {}
    }
  }

  _renderInspectorPath(pathNodes) {
    const card = document.getElementById("inspector-card");
    card.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
        <div class="inspector-node-title" style="margin-bottom:0;">Semantic Path (${pathNodes.length - 1} hops)</div>
        <button id="inspector-unfocus-btn" class="link-emerald" style="margin-top:0;">✕ Unfocus</button>
      </div>
      <div class="inspector-node-meta"><span>● Bridge Illuminated</span></div>
      <div class="inspector-neighbors">
        ${pathNodes
          .map(
            (n, i) =>
              `<button class="neighbor-chip" data-idx="${Number(n.index)}">${i + 1}. ${this._escapeHtml(n.title)}</button>`
          )
          .join("")}
      </div>
    `;
    document.getElementById("inspector-unfocus-btn").addEventListener("click", () => {
      this.galaxy.clearSelection();
      this.galaxy.fitView();
    });
    card.querySelectorAll(".neighbor-chip").forEach((btn) => {
      btn.addEventListener("click", () => this.galaxy.focusNode(Number(btn.dataset.idx), true));
    });
  }

  setFlatGalaxyMode(isFlat) {
    this.galaxy.setFlatMode(isFlat);
    document.getElementById("mode-3d-btn").classList.toggle("active", !isFlat);
    document.getElementById("mode-flat-btn").classList.toggle("active", isFlat);
    document.getElementById("back-to-2d-btn").textContent = isFlat ? "← back to 3D" : "← back to 2D";
  }

  /* =========================================================
     SETTINGS HUB & MULTI-PLATFORM AI STATUS
     ========================================================= */
  openSettings(tabName = "ai") {
    if (HUB && tabName === "ai") tabName = "brain";
    document.getElementById("quick-modal").classList.add("hidden");
    const modal = document.getElementById("settings-modal");
    modal.classList.remove("hidden");
    this.switchSettingsTab(tabName);
    this.refreshAIStatus(true);
  }

  closeSettings() {
    document.getElementById("settings-modal").classList.add("hidden");
    if (this.oauthPollTimer) {
      clearInterval(this.oauthPollTimer);
      this.oauthPollTimer = null;
    }
  }

  switchSettingsTab(tabName) {
    document.querySelectorAll(".settings-tab-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.stab === tabName);
    });
    document.querySelectorAll(".settings-tab-pane").forEach((p) => {
      p.classList.toggle("active", p.id === `stab-${tabName}`);
    });
  }

  async refreshAIStatus(force = false) {
    try {
      const res = await apiGet(`/status${force ? "?refresh=1" : ""}`);
      const st = await res.json();
      if (!st.ok) return;

      const engineLabel = st.activeEngine || "ollama";
      document.getElementById("settings-active-engine").textContent = engineLabel;
      document.getElementById("hud-engine-pill").textContent = `AI: ${engineLabel}`;

      document.getElementById("cfg-preferred-provider").value = st.preferredProvider || "ollama";
      document.getElementById("cfg-cloud-consent").checked = st.cloudConsent === true;
      document.getElementById("cfg-vault-mode").value = st.vaultMode || "andrei_plus_nerva";
      document.getElementById("cfg-vault-path").value = st.vaultPath || "";
      if (st.inboxFolder) document.getElementById("inbox-capture-msg").textContent = `Saves new notes to ${st.inboxFolder}/`;
      document.getElementById("cfg-nerva-path").value = st.nervaPath || "";
      document.getElementById("cfg-ollama-url").value = st.ollamaUrl || "http://127.0.0.1:11434";
      document.getElementById("cfg-openrouter-url").value = st.openrouterUrl || "";
      document.getElementById("cfg-openrouter-model").value = st.openrouterModel || "";
      document.getElementById("cfg-elevenlabs-voice").value = st.elevenlabsVoiceId || "";

      // Claude Subscription Badge
      const cSub = st.claudeSubscription || {};
      const cBadge = document.getElementById("claude-sub-badge");
      if (cSub.loggedIn) {
        cBadge.textContent = `● Connected (${cSub.email || cSub.subscriptionType || "Claude OAuth"})`;
        cBadge.className = "conn-pill connected";
        document.getElementById("btn-claude-oauth").textContent = "✓ Subscription Active";
        if (this.oauthPollTimer) {
          clearInterval(this.oauthPollTimer);
          this.oauthPollTimer = null;
        }
      } else if (cSub.installed) {
        cBadge.textContent = "○ CLI Ready · Sign-In Needed";
        cBadge.className = "conn-pill pending";
        document.getElementById("btn-claude-oauth").textContent = "🔑 Sign in with Claude Subscription";
      } else {
        cBadge.textContent = "CLI Not Found";
        cBadge.className = "conn-pill";
      }

      // Ollama Badge & Model List
      const oll = st.ollama || {};
      const oBadge = document.getElementById("ollama-status-badge");
      const oSelect = document.getElementById("cfg-ollama-model");
      if (oll.online) {
        oBadge.textContent = `● Online (${(oll.models || []).length} models)`;
        oBadge.className = "conn-pill connected";
        if (Array.isArray(oll.models) && oll.models.length > 0) {
          oSelect.innerHTML = modelOptionsHtml(oll.models);
          if (oll.models.includes(st.ollamaModel)) {
            oSelect.value = st.ollamaModel;
          }
        }
      } else {
        oBadge.textContent = "Offline";
        oBadge.className = "conn-pill";
      }

      // Cloud Key Badges & Masking
      const setKeyBadge = (badgeId, inputId, hasKey, defaultLabel = "Optional") => {
        const b = document.getElementById(badgeId);
        const inp = document.getElementById(inputId);
        if (!b || !inp) return;
        if (hasKey) {
          b.textContent = "● Key Saved";
          b.className = "conn-pill connected";
          if (!inp.value) inp.value = "***";
        } else {
          b.textContent = defaultLabel;
          b.className = "conn-pill";
        }
      };

      const p = st.providers || {};
      setKeyBadge("badge-anthropic", "cfg-anthropic", p.anthropic);
      setKeyBadge("badge-openai", "cfg-openai", p.openai);
      setKeyBadge("badge-gemini", "cfg-gemini", p.gemini);
      setKeyBadge("badge-openrouter", "cfg-openrouter-key", p.openrouter);
      if (p.elevenlabs) {
        setKeyBadge("badge-elevenlabs", "cfg-elevenlabs", true);
      } else {
        const eb = document.getElementById("badge-elevenlabs");
        eb.textContent = "macOS Daniel Active";
        eb.className = "conn-pill connected";
      }
    } catch (_) {}
  }

  _restoreVisualPrefs() {
    try {
      const saved = JSON.parse(localStorage.getItem("jarvis_visual_prefs") || "{}");
      if (saved.showFilter === false) {
        document.body.classList.add("hide-filter-legend");
        document.getElementById("toggle-filter-legend").checked = false;
      }
      if (saved.showSubsystems === false) {
        document.body.classList.add("hide-hud-subsystems");
        document.getElementById("toggle-hud-subsystems").checked = false;
      }
      if (saved.showVisModes === false) {
        document.body.classList.add("hide-vis-modes");
        document.getElementById("toggle-vis-modes").checked = false;
      }
    } catch (_) {}
  }

  _saveVisualPrefs() {
    const prefs = {
      showFilter: document.getElementById("toggle-filter-legend").checked,
      showSubsystems: document.getElementById("toggle-hud-subsystems").checked,
      showVisModes: document.getElementById("toggle-vis-modes").checked,
    };
    localStorage.setItem("jarvis_visual_prefs", JSON.stringify(prefs));
  }

  /* =========================================================
     WORKSHOP OVERLAY MANAGEMENT (ROBOT & FLOOR PLAN STUDIO)
     ========================================================= */
  _showBuildChecklist(stateTitle, thinkingLabel, thinkingDesc, steps, activeIdx, completed = false) {
    this._workshopHasBuildStatus = true;
    const card = document.getElementById("build-status-card");
    card.classList.remove("hidden");
    document.getElementById("build-card-body").classList.remove("hidden");
    document.getElementById("build-card-hide-btn").textContent = "Hide";
    document.getElementById("build-card-state").textContent = stateTitle;

    const dot = document.getElementById("build-thinking-dot");
    dot.className = `status-dot ${completed ? "green" : "amber"}`;
    document.getElementById("build-thinking-label").textContent = thinkingLabel;
    document.getElementById("build-thinking-text").textContent = thinkingDesc;

    const ul = document.getElementById("build-checklist");
    ul.innerHTML = steps
      .map((s, idx) => {
        const cls = completed || idx < activeIdx ? "done" : idx === activeIdx ? "active" : "";
        const sym = completed || idx < activeIdx ? "✓" : "";
        return `<li class="${cls}"><span class="check-badge">${sym}</span><span>${s}</span></li>`;
      })
      .join("");
  }

  openRobotWorkshop(animateBuild = true) {
    this._cancelWorkshopExport();
    this.computerUse.close();
    this.houseWorkshop.unmount();

    this.activeView = "robot";
    document.body.dataset.view = "robot";
    this.telemetryStart = performance.now();

    document.getElementById("workshop-overlay").classList.remove("hidden");
    document.getElementById("workshop-header-left").classList.remove("hidden");
    document.getElementById("workshop-title").textContent = "Jarvis Reactor Companion";
    document.getElementById("your-picture-card").classList.add("hidden");

    this._renderRobotTopBar();
    this.robotWorkshop.mount();
    this.hud.setStatus("working");

    if (animateBuild) {
      const startTs = performance.now();
      this.robotWorkshop.playProgressiveBuild(
        (steps, idx) => {
          this._showBuildChecklist(
            "BUILDING",
            "Assembling the model",
            "Setting the frame deck and the battery cradle heights, then wiring the tick handler so the ring and tick group pulse with the voice level.",
            steps,
            idx,
            false
          );
        },
        () => {
          const secs = ((performance.now() - startTs) / 1000).toFixed(1);
          this._showBuildChecklist(
            "BUILT",
            `Assembly complete in ${secs} s`,
            "15 precision-machined parts assembled with PBR studio materials and exploded-view vectors ready.",
            [
              "Turning the aluminium foot",
              "Seating the speaker driver",
              "Populating the logic board",
              "Fitting the heat sink",
              "Wrapping the acoustic band",
              "Lighting the emerald reactor",
              "Closing the soft-touch shell",
              "Waking the reactor",
            ],
            8,
            true
          );
          this.hud.setStatus("online");
        }
      );
    } else {
      this._workshopHasBuildStatus = false;
      this.robotWorkshop.setExploded(false);
      document.getElementById("build-status-card").classList.add("hidden");
      this.hud.setStatus("online");
    }
  }

  _renderRobotTopBar() {
    const bar = document.getElementById("workshop-top-bar");
    const isExp = this.robotWorkshop.explodeTarget > 0.5;
    bar.innerHTML = `
      <button id="rb-assemble-btn" class="top-pill-btn ${!isExp ? "active" : ""}">3D Chassis</button>
      <button id="rb-explode-btn" class="top-pill-btn ${isExp ? "active" : ""}">Exploded View</button>
      <input id="rb-explode-slider" type="range" min="0" max="100" value="${Math.round(this.robotWorkshop.explodeTarget * 100)}" style="width:88px; accent-color:#22c55e; margin:0 6px;" title="Explode Offset" />
      <button id="rb-red-btn" class="top-pill-btn">🔴 Red Housing</button>
      <button id="rb-save-btn" class="top-pill-btn">Save picture</button>
      <button id="rb-projects-btn" class="top-pill-btn" aria-haspopup="dialog">Projects</button>
      ${HUB ? '<button id="rb-ai-edit-btn" class="top-pill-btn">Edit with AI</button>' : ''}
      <button id="rb-export-btn" class="top-pill-btn" ${this._workshopExportRequest ? "disabled" : ""}>Blender / Godot (.glb)</button>
      <span id="workshop-export-status" role="status" aria-live="polite">${this._workshopExportStatus || ""}</span>
    `;

    document.getElementById("rb-assemble-btn").addEventListener("click", () => this.setRobotExploded(false));
    document.getElementById("rb-explode-btn").addEventListener("click", () => this.setRobotExploded(true));
    document.getElementById("rb-explode-slider").addEventListener("input", (e) => {
      this._cancelWorkshopExport();
      this.robotWorkshop.setExplodeAmount(Number(e.target.value) / 100);
    });
    document.getElementById("rb-red-btn").addEventListener("click", () => {
      this.agent.handleCommand("Make the reactor housing anodized red, keep the ring emerald green");
    });
    document.getElementById("rb-save-btn").addEventListener("click", () => {
      this._downloadDataUrl(this.robotWorkshop.capturePNG(), "jarvis-reactor-companion.png");
    });
    document.getElementById("rb-export-btn").addEventListener("click", () => this.exportWorkshopModel());
    document.getElementById("rb-projects-btn").addEventListener("click", () => this.projects.open());
    document.getElementById("rb-ai-edit-btn")?.addEventListener("click", () => this._focusWorkshopPrompt());
  }

  editRobot(params) {
    this._cancelWorkshopExport();
    this.hud.setStatus("working");
    this.robotWorkshop.applyMaterialEdit(params, (steps, idx) => {
      if (idx !== 0) return;
      this._showBuildChecklist(steps.length ? "UPDATED" : "NO CHANGE", steps.length ? "Model materials updated" : "Materials unchanged", "The current 3D model reflects this request.", steps, steps.length, true);
      this.hud.setStatus("online");
    });
  }

  setRobotExploded(exploded) {
    this._cancelWorkshopExport();
    this.robotWorkshop.setExploded(exploded);
    if (exploded) {
      document.getElementById("build-status-card").classList.add("hidden");
    }
    this._renderRobotTopBar();
  }

  openHouseWorkshop(animateBuild = true) {
    this._cancelWorkshopExport();
    this.computerUse.close();
    this.robotWorkshop.unmount();

    this.activeView = "house";
    document.body.dataset.view = "house";
    this.telemetryStart = performance.now();

    document.getElementById("workshop-overlay").classList.remove("hidden");
    document.getElementById("workshop-header-left").classList.remove("hidden");
    document.getElementById("workshop-title").textContent = "Pool Home Plan";
    document.getElementById("your-picture-card").classList.remove("hidden");

    this.houseWorkshop.mount();
    this._renderHouseTopBar(animateBuild);

    if (animateBuild) {
      this.hud.setStatus("working");
      this.houseWorkshop.playInitialBuild(
        (steps, idx) => {
          this._showBuildChecklist(
            "BUILDING",
            "Assembling the model",
            "Extruding architectural wall boundaries, placing interior furniture at offset coordinates, and pouring the pool terrace...",
            steps,
            idx,
            false
          );
        },
        () => {
          this._showBuildChecklist(
            "BUILT",
            "Model assembled",
            "21m × 18m villa ready for live voice remodeling — try 'remove front stairs', 'enlarge living room', or 'add palm trees behind the pool'.",
            [
              "Raising the walls",
              "Furnishing the living spaces",
              "Fitting bedroom and baths",
              "Pouring the pool terrace",
              "Laying out the grounds",
              "Setting the roof",
            ],
            6,
            true
          );
          this.hud.setStatus("online");
        },
        () => {
          this._renderHouseTopBar(false);
        }
      );
    } else {
      this._workshopHasBuildStatus = false;
      document.getElementById("build-status-card").classList.add("hidden");
      this._renderHouseTopBar(false);
    }
  }

  _renderHouseTopBar(craftingMiniature = false) {
    const bar = document.getElementById("workshop-top-bar");
    const mode = this.houseWorkshop.viewMode;
    bar.innerHTML = `
      <button id="hs-3d-btn" class="top-pill-btn ${mode === "3d" ? "active" : ""}">3D model</button>
      <button id="hs-mini-btn" class="top-pill-btn ${mode === "miniature" ? "active" : ""}">Miniature</button>
      <button id="hs-save-btn" class="top-pill-btn">Save picture</button>
      <button id="hs-projects-btn" class="top-pill-btn" aria-haspopup="dialog">Projects</button>
      ${HUB ? '<button id="hs-ai-edit-btn" class="top-pill-btn">Edit with AI</button>' : ''}
      <button id="hs-export-btn" class="top-pill-btn" ${this._workshopExportRequest ? "disabled" : ""}>Blender / Godot (.glb)</button>
      <button id="hs-ai-btn" class="top-pill-btn" title="Download a script that builds the current drawing in Illustrator" ${this._workshopExportRequest ? "disabled" : ""}>Illustrator script (.jsx)</button>
      <button id="hs-svg-btn" class="top-pill-btn" ${this._workshopExportRequest ? "disabled" : ""}>Export floor plan as SVG for Illustrator (.svg)</button>
      <span id="workshop-export-status" role="status" aria-live="polite">${this._workshopExportStatus || ""}</span>
      ${
        craftingMiniature
          ? `<span class="crafting-badge"><span class="spinner-ring"></span> Crafting the miniature</span>`
          : ""
      }
    `;

    document.getElementById("hs-3d-btn").addEventListener("click", () => this.switchHouseTab("3d"));
    document.getElementById("hs-mini-btn").addEventListener("click", () => this.switchHouseTab("miniature"));
    document.getElementById("hs-save-btn").addEventListener("click", () => {
      this._downloadDataUrl(this.houseWorkshop.capturePNG(), `pool-home-${mode}.png`);
    });
    document.getElementById("hs-export-btn").addEventListener("click", () => this.exportWorkshopModel());
    document.getElementById("hs-ai-btn").addEventListener("click", () => this.exportWorkshopModel("jsx"));
    document.getElementById("hs-svg-btn").addEventListener("click", () => this.exportHouseFloorPlan());
    document.getElementById("hs-projects-btn").addEventListener("click", () => this.projects.open());
    document.getElementById("hs-ai-edit-btn")?.addEventListener("click", () => this._focusWorkshopPrompt());
  }

  switchHouseTab(mode) {
    this._cancelWorkshopExport();
    this.houseWorkshop.setViewMode(mode);
    const isMini = mode === "miniature";
    document.getElementById("your-picture-card").classList.toggle("hidden", isMini);
    document.getElementById("build-status-card").classList.toggle("hidden", isMini || !this._workshopHasBuildStatus);
    document.getElementById("workshop-header-left").classList.toggle("hidden", isMini);
    this._renderHouseTopBar(false);
  }

  editHouse(params) {
    this._cancelWorkshopExport();
    this.hud.setStatus("working");
    this.houseWorkshop.applyEdit(params, (steps, idx) => {
      if (idx !== 0) return;
      this._showBuildChecklist(steps.length ? "UPDATED" : "NO CHANGE", steps.length ? "Model updated" : "Model unchanged", "The current 3D model reflects this request.", steps, steps.length, true);
      this._renderHouseTopBar(false);
      this.hud.setStatus("online");
    });
  }

  openComputerUse() {
    this.projects?.close(false);
    this._cancelWorkshopExport();
    this.robotWorkshop.unmount();
    this.houseWorkshop.unmount();
    document.getElementById("workshop-overlay").classList.add("hidden");
    this.activeView = "computer";
    document.body.dataset.view = "computer";
    this.computerUse.open();
  }

  closeOverlays() {
    this.projects?.close(false);
    this._cancelWorkshopExport();
    this.robotWorkshop.unmount();
    this.houseWorkshop.unmount();
    this.computerUse.close();
    document.getElementById("workshop-overlay").classList.add("hidden");
    document.getElementById("workshop-header-left").classList.remove("hidden");
    this.activeView = "galaxy";
    document.body.dataset.view = "galaxy";
    this.hud.setStatus("online");
  }

  _downloadDataUrl(dataUrl, filename) {
    const a = document.createElement("a");
    a.href = dataUrl;
    a.download = filename;
    a.click();
    this.hud.showSubtitle(`Saved high-resolution snapshot "${filename}", sir.`);
  }

  _cancelWorkshopExport() {
    this.workshopViewRevision = (this.workshopViewRevision || 0) + 1;
    this._workshopExportRequest = null;
    this._workshopExportStatus = "";
    const status = document.getElementById("workshop-export-status");
    if (status) status.textContent = "";
    const button = document.getElementById(this.activeView === "robot" ? "rb-export-btn" : "hs-export-btn");
    if (button) button.disabled = false;
    const svgButton = document.getElementById("hs-svg-btn");
    if (svgButton) svgButton.disabled = false;
    const aiButton = document.getElementById("hs-ai-btn");
    if (aiButton) aiButton.disabled = false;
  }

  _focusWorkshopPrompt() {
    if (!HUB || (this.activeView !== "robot" && this.activeView !== "house")) return;
    const input = document.getElementById("jarvis-prompt-input");
    if (!input) return;
    if (!input.value.trim()) input.value = "Edit model: ";
    else if (!/^edit model:/i.test(input.value.trimStart())) input.value = `Edit model: ${input.value}`;
    input.title = `Describe an edit to the ${this.activeView === "robot" ? "robot" : "house"} model`;
    input.focus();
  }

  restoreWorkshopProject(project) {
    if (project.view === "robot") {
      this.openRobotWorkshop(false);
      this.robotWorkshop.restoreProject(project);
      this._renderRobotTopBar();
    } else {
      this.openHouseWorkshop(false);
      this.houseWorkshop.restoreProject(project);
      const mini = project.state.mode === "miniature";
      document.getElementById("your-picture-card").classList.toggle("hidden", mini);
      document.getElementById("workshop-header-left").classList.toggle("hidden", mini);
      this._renderHouseTopBar(false);
    }
    document.getElementById("build-status-card").classList.add("hidden");
    this.hud.setStatus("online");
  }

  async exportWorkshopModel(format = "glb") {
    const view = this.activeView;
    if (!['glb', 'svg', 'jsx'].includes(format) ||
        (format !== "glb" ? view !== "house" : view !== "robot" && view !== "house") || this._workshopExportRequest) return false;
    const mode = view === "house" ? this.houseWorkshop.viewMode : null;
    const roots = format !== "glb" ? null : view === "robot" ? [this.robotWorkshop.robotRoot]
      : mode === "miniature" ? [this.houseWorkshop.houseRoot, this.houseWorkshop.miniatureEnvGroup]
        : [this.houseWorkshop.houseRoot];
    const filename = format !== "glb" ? `pool-home-floor-plan.${format}`
      : view === "robot" ? "jarvis-reactor-companion.glb" : `pool-home-${mode}.glb`;
    const request = {};
    this._workshopExportRequest = request;
    this._workshopExportStatus = format !== "glb" ? "Exporting floor plan…" : "Exporting model…";
    const status = document.getElementById("workshop-export-status");
    const button = document.getElementById(view === "robot" ? "rb-export-btn" : "hs-export-btn");
    const svgButton = view === "house" ? document.getElementById("hs-svg-btn") : null;
    const aiButton = view === "house" ? document.getElementById("hs-ai-btn") : null;
    if (status) status.textContent = this._workshopExportStatus;
    if (button) button.disabled = true;
    if (svgButton) svgButton.disabled = true;
    if (aiButton) aiButton.disabled = true;
    try {
      const exporter = await import("./workshop-export.js");
      if (this._workshopExportRequest !== request || this.activeView !== view) return false;
      const blob = format === "svg"
        ? new Blob([exporter.houseFloorPlanSVG(this.houseWorkshop)], { type: "image/svg+xml;charset=utf-8" })
        : format === "jsx"
          ? new Blob([exporter.houseFloorPlanIllustratorScript(this.houseWorkshop)], { type: "application/octet-stream" })
        : await exporter.workshopGLB(roots);
      if (this._workshopExportRequest !== request || this.activeView !== view ||
          (view === "house" && this.houseWorkshop.viewMode !== mode)) return false;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      try { a.click(); } finally {
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 0);
      }
      this._workshopExportStatus = format === "jsx"
        ? `Downloaded ${filename}. In Illustrator, choose File › Scripts › Other Script, open the download, then save your drawing as .ai.`
        : format === "glb" ? `Downloaded ${filename}. Drop it into Godot’s FileSystem dock or import it as glTF in Blender.` : `Downloaded ${filename}`;
      if (status) status.textContent = this._workshopExportStatus;
      this.hud.showSubtitle(format === "jsx" ? this._workshopExportStatus : `Saved editable ${format === "glb" ? "model" : "floor plan"} "${filename}", sir.`);
      return true;
    } catch (error) {
      if (this._workshopExportRequest === request) {
        this._workshopExportStatus = format !== "glb" ? "Could not export floor plan. Please try again." : "Could not export model. Please try again.";
        if (status) status.textContent = this._workshopExportStatus;
      }
      return false;
    } finally {
      if (this._workshopExportRequest === request) {
        this._workshopExportRequest = null;
        if (button) button.disabled = false;
        if (svgButton) svgButton.disabled = false;
        if (aiButton) aiButton.disabled = false;
      }
    }
  }

  exportHouseFloorPlan() { return this.exportWorkshopModel("svg"); }

  /* =========================================================
     GLOBAL UI & KEYBOARD EVENT BINDINGS
     ========================================================= */
  _bindGlobalControls() {
    // Sidebar Collapse
    const sidebar = document.getElementById("left-sidebar");
    const collapseBtn = document.getElementById("sidebar-collapse-btn");
    collapseBtn.addEventListener("click", () => {
      const collapsed = sidebar.classList.toggle("collapsed");
      collapseBtn.textContent = collapsed ? "›" : "‹";
    });

    // Search Brain
    const searchInput = document.getElementById("brain-search");
    searchInput.addEventListener("input", () => {
      this.galaxy.search(searchInput.value);
    });
    searchInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        const matches = this.galaxy.search(searchInput.value);
        if (matches.length > 0) this.galaxy.focusNode(matches[0].index, true);
      }
    });

    // Force Sliders (inside Settings -> Visuals)
    document.getElementById("force-repel").addEventListener("input", (e) => {
      this.galaxy.repelScale = Number(e.target.value) / 100;
      this.galaxy.updatePositions(true);
    });
    document.getElementById("force-link-length").addEventListener("input", (e) => {
      this.galaxy.linkScale = Number(e.target.value) / 100;
      this.galaxy.updatePositions(true);
    });

    // Display Checkboxes (inside Settings -> Visuals)
    document.getElementById("toggle-hub-labels").addEventListener("change", (e) => {
      this.galaxy.showHubLabels = e.target.checked;
      this.galaxy.refreshVisualHighlights();
    });
    document.getElementById("toggle-particle-flow").addEventListener("change", (e) => {
      this.galaxy.showParticles = e.target.checked;
    });
    document.getElementById("toggle-auto-rotate").addEventListener("change", (e) => {
      this.galaxy.autoRotate = e.target.checked;
    });
    document.getElementById("toggle-starfield").addEventListener("change", (e) => {
      this.galaxy.showStarfield = e.target.checked;
    });

    // Homescreen & HUD Visibility Declutter Toggles
    document.getElementById("toggle-filter-legend").addEventListener("change", (e) => {
      document.body.classList.toggle("hide-filter-legend", !e.target.checked);
      this._saveVisualPrefs();
    });
    document.getElementById("toggle-hud-subsystems").addEventListener("change", (e) => {
      document.body.classList.toggle("hide-hud-subsystems", !e.target.checked);
      this._saveVisualPrefs();
    });
    document.getElementById("toggle-vis-modes").addEventListener("change", (e) => {
      document.body.classList.toggle("hide-vis-modes", !e.target.checked);
      this._saveVisualPrefs();
    });

    // Theme Swatches
    document.querySelectorAll(".swatch-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".swatch-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        this.galaxy.setTheme(btn.dataset.theme);
      });
    });

    // 3D Orbit vs Flat Map
    document.getElementById("mode-3d-btn").addEventListener("click", () => this.setFlatGalaxyMode(false));
    document.getElementById("mode-flat-btn").addEventListener("click", () => this.setFlatGalaxyMode(true));
    document.getElementById("back-to-2d-btn").addEventListener("click", () => {
      this.setFlatGalaxyMode(this.galaxy.targetFlatFactor < 0.5);
    });

    // Top Galaxy Pills
    document.getElementById("btn-fit-galaxy").addEventListener("click", () => {
      document.getElementById("brain-search").value = "";
      this.galaxy.search("");
      this.galaxy.clearSelection();
      this.galaxy.fitView();
    });
    document.getElementById("btn-tour-galaxy").addEventListener("click", () => {
      const hubs = this.dataset.topHubs || [];
      const pick = hubs.length
        ? hubs[Math.floor(Math.random() * hubs.length)].nodeIndex
        : Math.min(1, this.dataset.nodes.length - 1);
      if (pick !== undefined && this.dataset.nodes[pick]) {
        this.galaxy.focusNode(pick, true);
        this.hud.speak(`Flying to ${this.dataset.nodes[pick].title}, sir.`);
      }
    });
    document.getElementById("btn-crown-hubs").addEventListener("click", (e) => {
      this.galaxy.crownHighlight = !this.galaxy.crownHighlight;
      e.currentTarget.classList.toggle("active", this.galaxy.crownHighlight);
      this.galaxy.refreshVisualHighlights();
    });

    // Workshop Overlay Close & Hide Build Card
    document.getElementById("workshop-close-btn").addEventListener("click", () => this.closeOverlays());
    document.getElementById("build-card-hide-btn").addEventListener("click", (e) => {
      const body = document.getElementById("build-card-body");
      const hidden = body.classList.toggle("hidden");
      e.currentTarget.textContent = hidden ? "Show" : "Hide";
    });

    // Custom Floor Plan Image Upload & Drag-and-Drop
    const fpInput = document.getElementById("floorplan-upload-input");
    fpInput.addEventListener("change", (e) => {
      const file = e.target.files?.[0];
      if (file) this._loadCustomFloorplanFile(file);
    });

    window.addEventListener("dragover", (e) => e.preventDefault());
    window.addEventListener("drop", (e) => {
      e.preventDefault();
      const file = e.dataTransfer?.files?.[0];
      if (file && file.type.startsWith("image/")) {
        this._loadCustomFloorplanFile(file);
      }
    });

    // Bottom Prompt Form & Dock Buttons
    document.getElementById("jarvis-prompt-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const input = document.getElementById("jarvis-prompt-input");
      const val = input.value.trim();
      if (!val) return;
      input.value = "";
      this.agent.handleCommand(val);
    });

    document.getElementById("dock-voice-btn").addEventListener("click", (e) => {
      this.hud.voiceEnabled = !this.hud.voiceEnabled;
      e.currentTarget.classList.toggle("active", this.hud.voiceEnabled);
      e.currentTarget.textContent = this.hud.voiceEnabled ? "🔊" : "🔇";
      if (!this.hud.voiceEnabled && "speechSynthesis" in window) {
        window.speechSynthesis.cancel();
      }
    });

    document.getElementById("dock-robot-btn").addEventListener("click", () => {
      this.agent.handleCommand("Jarvis, build yourself a 3D body");
    });

    document.getElementById("dock-computer-btn").addEventListener("click", () => {
      this.openComputerUse();
      this.hud.speak("Meta Ads Manager ready in Computer Use mode, sir. Click Run or tell me the campaign goal.");
    });

    document.getElementById("dock-house-btn").addEventListener("click", () => {
      this.agent.handleCommand("Turn the Pool Home floor plan into a 3D model");
    });

    // Command Deck Modal (💡)
    const quickModal = document.getElementById("quick-modal");
    document.getElementById("dock-demos-btn").addEventListener("click", () => {
      quickModal.classList.remove("hidden");
    });
    document.getElementById("quick-modal-close").addEventListener("click", () => {
      quickModal.classList.add("hidden");
    });
    quickModal.addEventListener("click", (e) => {
      if (e.target === quickModal) quickModal.classList.add("hidden");
    });

    document.querySelectorAll(".demo-cmd-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        quickModal.classList.add("hidden");
        this.agent.handleCommand(btn.dataset.cmd);
      });
    });

    document.getElementById("dock-mic-btn").addEventListener("click", () => {
      this.hud.toggleListening();
    });

    // Dedicated Settings Modal (⚙️) Openers & Tabs
    const settingsModal = document.getElementById("settings-modal");
    document.getElementById("dock-settings-btn").addEventListener("click", () => this.openSettings("ai"));
    document.getElementById("sidebar-settings-btn").addEventListener("click", () => this.openSettings("visuals"));
    document.getElementById("deck-open-settings-btn").addEventListener("click", () => this.openSettings("ai"));
    document.getElementById("brain-menu-settings-link").addEventListener("click", (e) => {
      e.stopPropagation();
      document.getElementById("brain-dropdown-menu").classList.add("hidden");
      this.openSettings("ai");
    });
    document.getElementById("quick-inbox-btn").addEventListener("click", () => {
      this.openSettings("brain");
      setTimeout(() => document.getElementById("inbox-note-title")?.focus(), 80);
    });

    document.getElementById("settings-modal-close").addEventListener("click", () => this.closeSettings());
    settingsModal.addEventListener("click", (e) => {
      if (e.target === settingsModal) this.closeSettings();
    });

    document.querySelectorAll(".settings-tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => this.switchSettingsTab(btn.dataset.stab));
    });

    // Anthropic Subscription OAuth Sign-In Trigger
    document.getElementById("btn-claude-oauth").addEventListener("click", async () => {
      const hint = document.getElementById("claude-oauth-hint");
      hint.classList.remove("hidden");
      hint.textContent = "Launching Anthropic Subscription OAuth in your browser... Complete sign-in there and this status will update automatically.";
      try {
        await apiPost("/claude/login");
        if (this.oauthPollTimer) clearInterval(this.oauthPollTimer);
        this.oauthPollTimer = setInterval(() => this.refreshAIStatus(true), 4000);
      } catch (err) {
        hint.textContent = `Could not launch OAuth automatically: ${err.message}`;
      }
    });

    document.getElementById("btn-refresh-ai-status").addEventListener("click", () => {
      this.refreshAIStatus(true);
    });

    // Save AI Connections
    const saveAllSettings = async (statusElId) => {
      const payload = {
        preferredProvider: document.getElementById("cfg-preferred-provider").value,
        cloudConsent: document.getElementById("cfg-cloud-consent").checked,
        vaultMode: document.getElementById("cfg-vault-mode").value,
        vaultPath: document.getElementById("cfg-vault-path").value,
        nervaPath: document.getElementById("cfg-nerva-path").value,
        ollamaUrl: document.getElementById("cfg-ollama-url").value,
        ollamaModel: document.getElementById("cfg-ollama-model").value,
        anthropicKey: document.getElementById("cfg-anthropic").value,
        geminiKey: document.getElementById("cfg-gemini").value,
        openaiKey: document.getElementById("cfg-openai").value,
        openrouterUrl: document.getElementById("cfg-openrouter-url").value,
        openrouterModel: document.getElementById("cfg-openrouter-model").value,
        openrouterKey: document.getElementById("cfg-openrouter-key").value,
        elevenlabsKey: document.getElementById("cfg-elevenlabs").value,
        elevenlabsVoiceId: document.getElementById("cfg-elevenlabs-voice").value,
      };
      // On the hub, providers, keys and paths are the hub's own: only re-index.
      let data = { activeEngine: "nerva hub" };
      try {
        if (!HUB) {
          const response = await apiPost("/config", payload);
          data = await response.json();
          if (!response.ok || data.ok !== true) throw new Error("Settings were not saved");
        }
      } catch (_) {
        const msgEl = document.getElementById(statusElId);
        if (msgEl) msgEl.textContent = "Could not save or confirm settings. Refresh status before relying on this change, or retry.";
        return;
      }
      await this.refreshAIStatus(true);
      await this.loadServerBrain(true);
      const msgEl = document.getElementById(statusElId);
      if (msgEl) {
        msgEl.textContent = `Saved! Active responder: ${data.activeEngine || "ready"} · Brain: ${this.dataset.nodes.length} nodes.`;
      }
    };

    document.getElementById("cfg-save-btn").addEventListener("click", () => saveAllSettings("cfg-status-msg"));
    document.getElementById("btn-save-vault").addEventListener("click", () => saveAllSettings("vault-status-msg"));

    // Quick capture into the configured inbox.
    document.getElementById("btn-capture-inbox").addEventListener("click", async () => {
      const titleInput = document.getElementById("inbox-note-title");
      const bodyInput = document.getElementById("inbox-note-body");
      const msgEl = document.getElementById("inbox-capture-msg");
      const title = titleInput.value.trim();
      const content = bodyInput.value.trim();
      if (!title && !content) {
        msgEl.textContent = "Enter a title or note content first.";
        return;
      }
      const saveButton = document.getElementById("btn-capture-inbox");
      if (saveButton.disabled) return;
      saveButton.disabled = true;
      msgEl.textContent = "Saving note…";
      let data;
      try {
        const res = await apiPost("/brain/capture", { title, content });
        data = await res.json();
        if (!res.ok || !data.ok) throw new Error(data.error || "The hub could not confirm the save.");
      } catch (err) {
        msgEl.textContent = `Check the vault before retrying. ${err.message || "Could not confirm the save."}`;
        return;
      } finally {
        saveButton.disabled = false;
      }
      if (data.ok) {
        titleInput.value = "";
        bodyInput.value = "";
        msgEl.textContent = `Saved to ${data.path}!`;
        await this.loadServerBrain(true);
        this.closeSettings();
        if (data.node?.title) {
          const idx = this.dataset.nodes.findIndex((n) => n.relPath === data.node.relPath);
          if (idx >= 0) this.galaxy.focusNode(idx, true);
        }
        this.hud.showSubtitle(`Saved ${data.node?.relPath || data.path}`);
      } else {
        msgEl.textContent = `Error: ${data.error || "Could not write note"}`;
      }
    });

    // Keyboard Shortcuts ('l' isolate, 'Escape' clear/close)
    window.addEventListener("keydown", (e) => {
      if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") return;
      if (e.key === "Escape") {
        if (!document.getElementById("settings-modal").classList.contains("hidden")) {
          this.closeSettings();
        } else if (!document.getElementById("quick-modal").classList.contains("hidden")) {
          document.getElementById("quick-modal").classList.add("hidden");
        } else if (this.activeView !== "galaxy") {
          this.closeOverlays();
        } else {
          this.galaxy.clearSelection();
        }
      } else if (e.key.toLowerCase() === "l" && this.activeView === "galaxy") {
        this.galaxy.isolateMode = !this.galaxy.isolateMode;
        this.galaxy.refreshVisualHighlights();
      }
    });
  }

  _loadCustomFloorplanFile(file) {
    const reader = new FileReader();
    reader.onload = () => {
      this.openHouseWorkshop(false);
      document.getElementById("your-picture-img").src = reader.result;
      this.hud.speak(`Reference image "${file.name}" loaded beside the Pool Home example model.`);
    };
    reader.readAsDataURL(file);
  }

  _startRenderLoop() {
    let last = performance.now();
    const frame = (now) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;

      this.hud.tick(dt);

      if (this.activeView === "galaxy") {
        this.galaxy.tick(dt);
      } else if (this.activeView === "robot" || this.activeView === "house") {
        const elapsedSec = Math.floor((now - this.telemetryStart) / 1000);
        const mins = Math.floor(elapsedSec / 60);
        const secs = String(elapsedSec % 60).padStart(2, "0");
        document.getElementById("workshop-timer").textContent = `${mins}:${secs}`;

        if (this.activeView === "robot") {
          this.robotWorkshop.tick(dt, this.hud.voiceLevel);
        } else {
          this.houseWorkshop.tick(dt);
        }
      }

      requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
  }
}

window.addEventListener("DOMContentLoaded", () => {
  window.jarvisApp = new JarvisOSApp();
  const params = new URLSearchParams(window.location.search);
  const project = params.get("project");
  if (project) {
    window.jarvisApp.openRobotWorkshop(false);
    window.jarvisApp.projects.open({ refresh: false });
    window.jarvisApp.projects.load(project);
    return;
  }
  const studio = params.get("studio");
  if (studio === "robot") window.jarvisApp.openRobotWorkshop(false);
  else if (studio === "house") window.jarvisApp.openHouseWorkshop(false);
});
