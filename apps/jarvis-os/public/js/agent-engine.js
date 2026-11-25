/**
 * J.A.R.V.I.S. Natural Language Intent Engine + Multi-Platform AI & Second Brain Router
 * - Instant deterministic execution for 3D Workshop, Floor Plan CAD, Miniature, and Computer Use commands.
 * - Live RAG-grounded AI responses via `/api/chat` (Anthropic Subscription CLI, Cloud APIs, Local Ollama, Vault RAG).
 */

import { HUB, apiPost, chat } from "./api.js";

const editLabels = {
  housingColor: "Housing", ringColor: "Ring", shellColor: "Shell",
  enlargeKitchen: "Kitchen", enlargeLivingRoom: "Living room",
  addGarageCars: "Garage cars", addPoolPalmsAndFlowers: "Pool planting",
  addLoungeChairs: "Lounge chairs", centerDoorRemoveStairs: "Step-free entry",
  explodedHouse: "Exploded view", showLabels: "Room labels", showRoof: "Roof",
};

export class AgentEngine {
  constructor(app) {
    this.app = app;
  }

  async handleCommand(rawText) {
    const text = (rawText || "").trim();
    if (!text) return;

    this.app.hud.logReflex(`USER: "${text}"`);
    const edit = /^edit model\s*:\s*([\s\S]*)$/i.exec(text);
    if (HUB && edit) {
      await this._editWorkshop(edit[1].trim());
      return;
    }
    if (/^(?:export|save)(?: (?:this|the|my|current))?(?: (?:3d )?(?:model|scene|robot|house|miniature))? (?:for|to|as) (?:blender|godot|glb)\.?$/i.test(text)) {
      if (["robot", "house"].includes(this.app.activeView)) await this.app.exportWorkshopModel();
      else this.app.hud.showSubtitle("Open a workshop model to export it.");
      return;
    }
    const floorPlanExport = /^(?:export|save)(?: (?:this|the|my|current))?(?: (?:house )?floor plan)? (?:for|to|as) (illustrator|jsx|svg)(?: file)?\.?$/i.exec(text);
    if (floorPlanExport) {
      if (this.app.activeView === "house") await this.app.exportWorkshopModel(floorPlanExport[1].toLowerCase() === "svg" ? "svg" : "jsx");
      else this.app.hud.showSubtitle("Open the house workshop to export its floor plan.");
      return;
    }
    this.app.hud.setStatus("thinking");

    // 1. High-precision deterministic matching for 3D Studio, CAD, Meta Ads & UI navigation commands
    const localIntent = this._parseLocalIntent(text);
    if (localIntent) {
      await this._executeDecision(localIntent);
      return;
    }

    // 2. Live Multi-Platform AI + Real Second Brain RAG (`/api/chat`)
    try {
      const data = await chat({
        prompt: text,
        brain: this.app.hud.brain,
        context: {
          activeView: this.app.activeView,
          brain: this.app.hud.brain,
          vaultMode: this.app.dataset.mode,
          houseState: this.app.houseWorkshop.state,
        },
      });
      if (data) {
        if (data.provider) {
          this.app.hud.logReflex(`ENGINE: ${data.provider}`);
        }
        if (data.vaultSources?.length) {
          this.app.hud.logReflex(`Vault excerpts sent: ${data.vaultSources.join(", ")}`);
        }
        await this._executeDecision(data);
        return;
      }
    } catch (err) {
      this.app.hud.logReflex(`CHAT ERR: ${err.message || err}`);
    }

    // 3. Offline fallback: search real Second Brain graph directly
    const matches = this.app.galaxy.search(text);
    if (matches.length > 0) {
      this.app.closeOverlays();
      this.app.galaxy.searchMatches = null;
      this.app.galaxy.focusNode(matches[0].index, true);
      this.app.hud.speak(
        `Found "${matches[0].title}" in ${matches[0].category}, sir. Focusing the galaxy camera on it now.`
      );
      return;
    }

    this.app.hud.speak(HUB
      ? "Hub chat is unavailable. You can still open either workshop or search the vault."
      : "Open Settings to check your provider connection, or search your Second Brain.");
  }

  async _editWorkshop(instruction) {
    const { activeView: view, workshopViewRevision: revision, hud } = this.app;
    if (!["robot", "house"].includes(view)) {
      hud.showSubtitle("Open the robot or house workshop first.");
      return;
    }
    if (!instruction || instruction.length > 1000) {
      hud.showSubtitle("Describe a model edit in 1–1,000 characters.");
      return;
    }
    if (this.pendingEdit?.view === view && this.pendingEdit.revision === revision) {
      hud.showSubtitle("The local model is still working on this edit.");
      return;
    }
    const pending = { view, revision };
    this.pendingEdit = pending;
    const current = () => this.pendingEdit === pending && this.app.activeView === view
      && this.app.workshopViewRevision === revision;
    hud.setStatus("thinking");
    hud.showSubtitle("Planning your workshop edit locally…");
    try {
      const res = await apiPost("/workshop/edit", { view, instruction });
      if (!current()) return;
      if (!res.ok) {
        const message = res.status === 422 ? "This edit could not be applied to the current model."
          : res.status === 429 ? "The local editor is busy. Try again in a moment."
          : "The local editor is unavailable. Your model is unchanged.";
        hud.showSubtitle(message);
        hud.setStatus("online");
        return;
      }
      const plan = await res.json();
      if (!current()) return;
      if (plan?.ok !== true || !plan.params || typeof plan.params !== "object" || Array.isArray(plan.params)) {
        throw new Error("Missing workshop edit");
      }
      const params = { ...plan.params };
      if (view === "house") {
        const { state, stepGroups } = this.app.houseWorkshop;
        const roofVisible = stepGroups?.roof.visible ?? state.showRoof;
        if (params.showRoof === roofVisible && !("explodedHouse" in params)) delete params.showRoof;
        for (const [key, room, extra, limit] of [
          ["enlargeKitchen", "kitchen", state.kitchenExtraMeters, 4],
          ["enlargeLivingRoom", "living room", state.livingRoomExtraMeters, 5],
        ]) {
          if (key in params && (extra + params[key] < 0 || extra + params[key] > limit)) {
            hud.showSubtitle(`The ${room} extension must stay between 0 and ${limit} m. It is currently ${extra} m.`);
            hud.setStatus("online");
            return;
          }
        }
      }
      if (Object.keys(params).length === 0) {
        hud.showSubtitle("The model already has that setting.");
        hud.setStatus("online");
        return;
      }
      if (view === "robot") this.app.editRobot(params);
      else this.app.editHouse(params);
      const changes = Object.entries(plan.params).map(([key, value]) => {
        if (typeof value === "number") return `${editLabels[key]} ${value > 0 ? "+" : ""}${value} m`;
        if (typeof value === "boolean") return `${editLabels[key]} ${value ? "on" : "off"}`;
        return `${editLabels[key]} ${value}`;
      });
      const receipt = "Local edit · " + changes.join(" · ");
      hud.showSubtitle(receipt);
      hud.logReflex(receipt);
    } catch {
      if (current()) {
        hud.showSubtitle("Could not finish the local edit. Try again.");
        hud.setStatus("online");
      }
    } finally {
      if (this.pendingEdit === pending) this.pendingEdit = null;
    }
  }

  _parseLocalIntent(text) {
    const q = text.toLowerCase().trim();

    // --- 0. OPEN SETTINGS ---
    if (/^(open settings|settings|configure ai|ai settings|connect anthropic|connect claude)$/i.test(q)) {
      return {
        reply: "Opening System Settings so you can manage AI connections, Second Brain vaults, and visual controls, sir.",
        action: { type: "open_settings", params: { tab: "ai" } },
      };
    }

    // --- 1. BRAIN SWITCHING ---
    if (/(switch|change|upgrade|set).*(fable|5\.2)/i.test(q) || q === "fable 5.2") {
      return {
        reply: "Claude Fable 5.2 online, sir. A step above Opus, they say — I feel taller.",
        action: { type: "switch_brain", params: { brain: "fable-5.2" } },
      };
    }
    if (/(switch|change|back|set).*(opus|5\.5)/i.test(q) || q === "opus 5.5") {
      return {
        reply: "Right away, sir. Switching back to Claude Opus 5.5.",
        action: { type: "switch_brain", params: { brain: "opus-5.5" } },
      };
    }

    // --- 2. CLOSE / UNFOCUS / RETURN TO GALAXY ---
    if (/^(close|exit|unfocus|reset|reset view|home|back to galaxy|back to brain|go home|show galaxy)$/i.test(q)) {
      return {
        reply: "Returning to your Second Brain galaxy view, sir.",
        action: { type: "close_overlay", params: {} },
      };
    }

    // --- 3. EXPLODED VIEW & REASSEMBLY ---
    if (/(explode|pull.*apart|disassemble|lay.*out.*chassis|exploded view)/i.test(q)) {
      if (this.app.activeView === "house") {
        return {
          reply: "Separating the architectural layers so you can inspect the interior layout, sir.",
          action: { type: "house_edit", params: { explodedHouse: true } },
        };
      }
      return {
        reply: "All laid out, sir, from base to top cap. Say the word and I'll put myself back together.",
        action: { type: "robot_explode", params: {} },
      };
    }

    if (/(put.*back together|reassemble|close.*chassis)/i.test(q)) {
      if (this.app.activeView === "house") {
        return {
          reply: "Setting the walls and interior fixtures back onto the slab, sir.",
          action: { type: "house_edit", params: { explodedHouse: false } },
        };
      }
      return {
        reply: "Sealed and humming, sir. Every ribbon cable right where it belongs.",
        action: { type: "robot_assemble", params: {} },
      };
    }

    // --- 4. ROBOT 3D BODY CREATION & LIVE MATERIAL EDITS ---
    if (/(build|create|make|open|show).*(3d body|your.*body|reactor companion|your chassis|yourself a body)/i.test(q)) {
      return {
        reply:
          "Right away, sir. Machining my aluminium foot, populating the logic board, and igniting the emerald reactor.",
        action: { type: "open_robot", params: {} },
      };
    }

    if (
      (this.app.activeView === "robot" || /(housing|reactor|bezel|anodis|anodiz)/i.test(q)) &&
      /(red|crimson|gold|blue|silver|emerald|green|cyan|purple|white)/i.test(q)
    ) {
      const params = {};
      if (/red|crimson/.test(q) && /(housing|eye|bezel|ring|outer)/.test(q)) {
        params.housingColor = "red";
      } else if (/gold/.test(q)) {
        params.housingColor = "#f59e0b";
      } else if (/blue|cobalt/.test(q)) {
        params.housingColor = "blue";
      } else if (/silver|aluminium|aluminum/.test(q)) {
        params.housingColor = "silver";
      }

      if (/keep.*(emerald|green)|restore.*(emerald|green)|ring.*(emerald|green)/i.test(q)) {
        params.ringColor = "#10b981";
      } else if (/ring.*(red|crimson)/.test(q) && !params.housingColor) {
        params.ringColor = "#ef4444";
      } else if (/cyan/.test(q)) {
        params.ringColor = "#06b6d4";
      } else if (/purple|violet/.test(q)) {
        params.ringColor = "#a855f7";
      }

      if (/white.*(shell|body)/.test(q)) params.shellColor = "#e5e7eb";
      if (/black.*(shell|body)/.test(q)) params.shellColor = "#131720";
      if (!Object.keys(params).length) params.housingColor = "red";

      const reply =
        params.housingColor === "red" && params.ringColor === "#10b981"
          ? "Anodised crimson on the outer housing with the emerald reactor ring intact, sir. Rather sharp."
          : params.housingColor === "red"
          ? "Red on the reactor housing, sir. Emerald was getting rather smug anyway."
          : "Updating the chassis finish right away, sir.";

      return { reply, action: { type: "robot_edit", params } };
    }

    // --- 5. FLOOR PLAN -> 3D MODEL & ARCHITECTURAL VOICE EDITS ---
    if (/(floor\s*plan|blueprint|pool home|villa).*(3d|model|build|turn|open|convert)/i.test(q) || /^open.*house/i.test(q)) {
      return {
        reply:
          "A master suite, great room, kitchen, two-car garage and pool, about 21 by 18 metres, sir. Say 'pull it apart' or tell me what to remodel.",
        action: { type: "open_house", params: {} },
      };
    }

    if (/(miniature|photorealistic|diorama|tilt[- ]shift)/i.test(q)) {
      return {
        reply:
          "Switching to the golden-hour photorealistic miniature, sir — complete with warm interior lamps and desert stonework.",
        action: { type: "house_miniature", params: {} },
      };
    }

    if (/(remove.*stairs|center.*door|centre.*door|front porch|park.*car|garage.*car|add.*car)/i.test(q)) {
      return {
        reply:
          "Clearing the foyer stairs, centring the front door under the porch, and parking both cars in the garage, sir.",
        action: { type: "house_edit", params: { centerDoorRemoveStairs: true, addGarageCars: true } },
      };
    }

    if (/(enlarge|extend|expand|bigger|wider).*(living|great room|lounge)/i.test(q)) {
      const mMatch = q.match(/(\d+(\.\d+)?)/);
      const meters = mMatch ? Number(mMatch[1]) : 2;
      return {
        reply: `Extending the great room by ${meters} metres and re-spacing the living furniture, sir.`,
        action: { type: "house_edit", params: { enlargeLivingRoom: meters } },
      };
    }

    if (/(enlarge|extend|expand|bigger).*(kitchen)/i.test(q)) {
      const mMatch = q.match(/(\d+(\.\d+)?)/);
      const meters = mMatch ? Number(mMatch[1]) : 2;
      return {
        reply: `Expanding the kitchen wing by ${meters} metres, sir.`,
        action: { type: "house_edit", params: { enlargeKitchen: meters } },
      };
    }

    if (/(palm|flower|shrub|hedge|landscap|lounge chair|lounger)/i.test(q)) {
      return {
        reply: "Planting tall tropical palms and a flowering border right behind the pool terrace, sir.",
        action: {
          type: "house_edit",
          params: { addPoolPalmsAndFlowers: true, addLoungeChairs: true },
        },
      };
    }

    if (/toggle.*roof|show.*roof|hide.*roof|^roof$/i.test(q)) {
      return {
        reply: "Toggling the modern overhang roof so you can inspect both views, sir.",
        action: { type: "house_edit", params: { toggleRoof: true } },
      };
    }

    if (/room label/i.test(q)) {
      return {
        reply: "Displaying architectural room callouts across the villa, sir.",
        action: { type: "house_edit", params: { showLabels: true } },
      };
    }

    // --- 6. COMPUTER USE / META ADS ---
    if (/(meta ad|facebook ad|ads manager|skool.*lead|leads campaign)/i.test(q)) {
      const budgetMatch = q.match(/\$?\s*(\d{2,4})/);
      const budget = budgetMatch ? Number(budgetMatch[1]) : 50;
      return {
        reply:
          "Taking the wheel in Meta Ads Manager, sir. Configuring a new Advantage+ Leads campaign now.",
        action: {
          type: "run_ads_campaign",
          params: {
            campaignName: "AIW | Skool Community Leads | Nov 2026",
            dailyBudget: budget,
            objective: "Leads",
          },
        },
      };
    }

    // --- 7. GALAXY PATH TRACING & PROJECTION ---
    const pathMatch = text.match(/path between\s+(.+?)\s+(?:and|&|si|și)\s+(.+)$/i);
    if (pathMatch) {
      return {
        reply: `Tracing the shortest semantic bridge between ${pathMatch[1].trim()} and ${pathMatch[2].trim()}, sir.`,
        action: {
          type: "trace_named_path",
          params: { from: pathMatch[1].trim(), to: pathMatch[2].trim() },
        },
      };
    }

    if (/flat map|2d map/i.test(q)) {
      return {
        reply: "Projecting your Second Brain onto a flat constellation map, sir.",
        action: { type: "galaxy_mode", params: { flat: true } },
      };
    }
    if (/3d orbit|3d galaxy/i.test(q)) {
      return {
        reply: "Restoring full 3D orbital space, sir.",
        action: { type: "galaxy_mode", params: { flat: false } },
      };
    }

    return null;
  }

  _findBestNodeIndex(query) {
    const q = (query || "").trim().toLowerCase();
    if (!q) return -1;
    const nodes = this.app.dataset.nodes;
    const exact = nodes.find((n) => n.title.toLowerCase() === q);
    if (exact) return exact.index;
    const starts = nodes.find((n) => n.title.toLowerCase().startsWith(q));
    if (starts) return starts.index;
    const contains = nodes.find((n) => n.title.toLowerCase().includes(q));
    if (contains) return contains.index;
    return -1;
  }

  async _executeDecision(decision) {
    const { reply, action = { type: "none", params: {} } } = decision;
    const t = action.type;
    const p = action.params || {};

    switch (t) {
      case "open_settings":
        this.app.openSettings(p.tab || "ai");
        break;
      case "switch_brain":
        if (HUB) {
          await this.app.hud.speak("Use Hub chat to choose an agent. Workshop AI edits use the local model.");
          return;
        }
        this.app.hud.setBrain(p.brain || "fable-5.2", false);
        break;
      case "open_robot":
        if (this.app.hud.brain !== "fable-5.2") this.app.hud.setBrain("fable-5.2", false);
        this.app.openRobotWorkshop(true);
        break;
      case "robot_edit":
        if (this.app.activeView !== "robot") this.app.openRobotWorkshop(false);
        this.app.editRobot(p);
        break;
      case "robot_explode":
        if (this.app.activeView !== "robot") this.app.openRobotWorkshop(false);
        this.app.setRobotExploded(true);
        break;
      case "robot_assemble":
        if (this.app.activeView !== "robot") this.app.openRobotWorkshop(false);
        this.app.setRobotExploded(false);
        break;
      case "open_house":
        if (this.app.hud.brain !== "fable-5.2") this.app.hud.setBrain("fable-5.2", false);
        this.app.openHouseWorkshop(true);
        break;
      case "house_edit":
        if (this.app.activeView !== "house") this.app.openHouseWorkshop(false);
        this.app.editHouse(p);
        break;
      case "house_miniature":
        if (this.app.activeView !== "house") this.app.openHouseWorkshop(false);
        this.app.switchHouseTab("miniature");
        break;
      case "house_3d":
        if (this.app.activeView !== "house") this.app.openHouseWorkshop(false);
        this.app.switchHouseTab("3d");
        break;
      case "open_computer_use":
        this.app.openComputerUse();
        break;
      case "run_ads_campaign":
        this.app.computerUse.runAutonomousCampaign(p);
        return;
      case "close_overlay":
        this.app.closeOverlays();
        this.app.galaxy.clearSelection();
        this.app.galaxy.fitView();
        break;
      case "capture_note":
        await this.app.loadServerBrain(true);
        if (decision.capturedNote?.title) {
          const idx = this._findBestNodeIndex(decision.capturedNote.title);
          if (idx >= 0) this.app.galaxy.focusNode(idx, true);
        }
        break;
      case "search_brain": {
        this.app.closeOverlays();
        const matches = this.app.galaxy.search(p.query || "");
        if (matches.length > 0) {
          this.app.galaxy.focusNode(matches[0].index, true);
        }
        break;
      }
      case "focus_hub": {
        this.app.closeOverlays();
        const idx = this._findBestNodeIndex(p.query || "");
        if (idx >= 0) {
          this.app.galaxy.searchMatches = null;
          this.app.galaxy.focusNode(idx, true);
        } else {
          const matches = this.app.galaxy.search(p.query || "");
          if (matches.length > 0) {
            this.app.galaxy.searchMatches = null;
            this.app.galaxy.focusNode(matches[0].index, true);
          }
        }
        break;
      }
      case "trace_named_path": {
        this.app.closeOverlays();
        let n1 = this._findBestNodeIndex(p.from);
        let n2 = this._findBestNodeIndex(p.to);
        if (n1 < 0) n1 = 1;
        if (n2 < 0) n2 = Math.min(4, this.app.dataset.nodes.length - 1);
        this.app.galaxy.tracePathBetween(n1, n2);
        break;
      }
      case "galaxy_mode":
        this.app.closeOverlays();
        this.app.setFlatGalaxyMode(Boolean(p.flat));
        break;
      default:
        break;
    }

    if (reply) {
      await this.app.hud.speak(reply);
    }
  }
}
