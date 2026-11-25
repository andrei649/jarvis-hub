import { apiGet, apiPost } from "./api.js";

const keysAre = (value, keys) => value && typeof value === "object" && !Array.isArray(value) &&
  Object.keys(value).sort().join("|") === keys.slice().sort().join("|");
const vector = (value) => Array.isArray(value) && value.length === 3 &&
  value.every((number) => typeof number === "number" && Number.isFinite(number) && Math.abs(number) <= 500);
const color = (value) => typeof value === "string" && /^#[0-9a-fA-F]{6}$/.test(value);
const unit = (value) => typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;

export function validWorkshopProject(project) {
  if (!keysAre(project, ["version", "view", "camera", "state"]) || project.version !== 1 ||
      !keysAre(project.camera, ["position", "target"]) ||
      !vector(project.camera.position) || !vector(project.camera.target) ||
      project.camera.position.every((axis, i) => axis === project.camera.target[i])) return false;
  const state = project.state;
  if (project.view === "robot") {
    return keysAre(state, ["housingColor", "ringColor", "shellColor", "metalness", "roughness", "explode"]) &&
      color(state.housingColor) && color(state.ringColor) && color(state.shellColor) &&
      unit(state.metalness) && unit(state.roughness) && unit(state.explode);
  }
  if (project.view === "house") {
    const booleans = ["centeredDoorNoStairs", "garageCars", "poolBackPalmsAndFlowers",
      "poolLoungeChairs", "showRoof", "showRoomLabels", "explodedLayers"];
    return keysAre(state, ["mode", "livingRoomExtraMeters", "kitchenExtraMeters",
      "roofVisibilityOverride", ...booleans]) &&
      (state.mode === "3d" || state.mode === "miniature") &&
      booleans.every((key) => typeof state[key] === "boolean") &&
      (state.roofVisibilityOverride === null || typeof state.roofVisibilityOverride === "boolean") &&
      typeof state.livingRoomExtraMeters === "number" && Number.isFinite(state.livingRoomExtraMeters) &&
      state.livingRoomExtraMeters >= 0 && state.livingRoomExtraMeters <= 5 &&
      typeof state.kitchenExtraMeters === "number" && Number.isFinite(state.kitchenExtraMeters) &&
      state.kitchenExtraMeters >= 0 && state.kitchenExtraMeters <= 4;
  }
  return false;
}

export class WorkshopProjects {
  constructor(app, get = apiGet, post = apiPost) {
    this.app = app;
    this.get = get;
    this.post = post;
    this.panel = document.getElementById("workshop-projects");
    this.form = document.getElementById("workshop-projects-form");
    this.title = document.getElementById("workshop-project-title");
    this.list = document.getElementById("workshop-projects-list");
    this.status = document.getElementById("workshop-projects-status");
    this.saveButton = document.getElementById("workshop-project-save");
    this.refreshButton = document.getElementById("workshop-project-refresh");
    this.serial = 0;
    this.busy = false;
    this.form.addEventListener("submit", (event) => { event.preventDefault(); this.save(); });
    this.title.addEventListener("input", () => this._setBusy(this.busy));
    document.getElementById("workshop-project-refresh").addEventListener("click", () => this.refresh());
    document.getElementById("workshop-projects-close").addEventListener("click", () => this.close());
    this.panel.addEventListener("keydown", (event) => {
      if (event.key === "Escape") { event.preventDefault(); this.close(); }
      if (event.key !== "Tab") return;
      const items = [...this.panel.querySelectorAll('button:not([disabled]), input, a[href]')];
      if (!items.length) return;
      if (event.shiftKey && document.activeElement === items[0]) {
        event.preventDefault(); items.at(-1).focus();
      } else if (!event.shiftKey && document.activeElement === items.at(-1)) {
        event.preventDefault(); items[0].focus();
      }
    });
  }

  _message(message) { this.status.textContent = message; }

  _link(path) {
    const url = new URL(window.location.href);
    url.search = "";
    url.searchParams.set("project", path);
    return url.href;
  }

  _setBusy(value) {
    this.busy = value;
    this.saveButton.disabled = value || !!this.pendingSavedPath &&
      this.title.value.trim().toLocaleLowerCase() === this.pendingSavedTitle;
    this.refreshButton.disabled = value;
    this.list.querySelectorAll("button").forEach((button) => { button.disabled = value; });
  }

  async open({ refresh = true } = {}) {
    if (this.app.activeView !== "robot" && this.app.activeView !== "house") return false;
    this.opener = document.activeElement;
    this.panel.classList.remove("hidden");
    this.title.focus();
    if (refresh) await this.refresh();
    return true;
  }

  close(restoreFocus = true) {
    this.serial++;
    this.panel.classList.add("hidden");
    if (restoreFocus) {
      const button = this.app.activeView === "robot" ? "rb-projects-btn" : "hs-projects-btn";
      (this.opener?.isConnected ? this.opener : document.getElementById(button))?.focus();
    }
  }

  async refresh() {
    const serial = ++this.serial;
    this._message("Loading saved versions…");
    try {
      const response = await this.get("/workshop/projects");
      if (!response.ok) throw new Error("unavailable");
      const data = await response.json();
      if (!data?.ok || !Array.isArray(data.projects)) throw new Error("invalid list");
      if (serial !== this.serial) return false;
      if (data.projects.some((item) => item.path === this.pendingSavedPath)) {
        this.pendingSavedPath = null;
        this.pendingSavedTitle = null;
      }
      this.list.replaceChildren();
      for (const item of data.projects) {
        if (typeof item.path !== "string" || typeof item.title !== "string" ||
            !["robot", "house"].includes(item.view)) continue;
        const row = document.createElement("div");
        row.className = "workshop-project-row";
        row.setAttribute("role", "listitem");
        const label = document.createElement("span");
        label.textContent = `${item.title} · ${item.view}`;
        const load = document.createElement("button");
        load.type = "button";
        load.textContent = "Open";
        load.setAttribute("aria-label", `Open ${item.title}`);
        load.addEventListener("click", () => this.load(item.path));
        const link = document.createElement("a");
        link.href = this._link(item.path);
        link.textContent = "Project link";
        link.setAttribute("aria-label", `Project link for ${item.title}`);
        row.append(label, load, link);
        this.list.appendChild(row);
      }
      this._setBusy(this.busy);
      this._message(this.pendingSavedPath ?
        `A version was written at ${this.pendingSavedPath} but is not listed yet. Refresh or choose a different name.` :
        data.projects.length ? "Choose a version to resume, or save the current scene." :
          "No saved versions yet. Name the current scene to save it.");
      return true;
    } catch (_) {
      if (serial === this.serial) {
        this.list.replaceChildren();
        this._message(this.pendingSavedPath ?
          `A version was written at ${this.pendingSavedPath} but could not be reopened. Refresh or choose a different name.` :
          "Obsidian inbox is unavailable. You can still use this workshop; try again when the vault is connected.");
      }
      return false;
    }
  }

  async save() {
    if (this.busy || this.panel.classList.contains("hidden")) return false;
    const title = this.title.value.trim();
    if (this.pendingSavedPath && title.toLocaleLowerCase() === this.pendingSavedTitle) return false;
    if (!title) { this._message("Enter a version name."); this.title.focus(); return false; }
    const view = this.app.activeView;
    if (view !== "robot" && view !== "house") return false;
    const project = (view === "robot" ? this.app.robotWorkshop : this.app.houseWorkshop).projectSnapshot();
    if (!validWorkshopProject(project)) { this._message("This scene cannot be saved. Please try again."); return false; }
    this.serial++;
    const revision = this.app.workshopViewRevision;
    const request = this.request = {};
    this._setBusy(true);
    this._message("Saving version…");
    try {
      const response = await this.post("/workshop/projects", { title, project });
      if (!response.ok) {
        let failure = {};
        try { failure = await response.json(); } catch (_) { /* unavailable response body */ }
        if (failure.error === "project saved but could not be reopened") {
          this.pendingSavedPath = typeof failure.path === "string" ? failure.path : null;
          this.pendingSavedTitle = title.toLocaleLowerCase();
          throw new Error("saved but could not be reopened");
        }
        throw new Error("save failed");
      }
      const data = await response.json();
      if (!data?.ok || typeof data.path !== "string") throw new Error("invalid save response");
      const message = revision === this.app.workshopViewRevision ?
        `Saved “${data.title || title}”. The project link is in the list below.` :
        `Saved “${data.title || title}” from before your latest change.`;
      if (!this.panel.classList.contains("hidden")) {
        await this.refresh();
        if (!this.panel.classList.contains("hidden") && this.request === request) this._message(message);
      }
      return true;
    } catch (error) {
      if (error.message === "saved but could not be reopened" && !this.panel.classList.contains("hidden")) {
        const savedPath = this.pendingSavedPath;
        await this.refresh();
        if (!this.pendingSavedPath && savedPath) {
          this._message(`The version was saved at ${savedPath} and is now listed below.`);
          return true;
        }
      }
      if (!this.panel.classList.contains("hidden") && this.request === request) this._message(
        error.message === "saved but could not be reopened" ?
          `A version was written at ${this.pendingSavedPath || "the vault inbox"} but could not be reopened. Refresh or choose a different name.` :
          "Could not save to the Obsidian inbox. Your current scene is still here.");
      return false;
    } finally {
      if (this.request === request) { this.request = null; this._setBusy(false); }
    }
  }

  async load(path) {
    if (this.busy || typeof path !== "string" || !path) return false;
    const serial = ++this.serial;
    const revision = this.app.workshopViewRevision;
    const request = this.request = {};
    this._setBusy(true);
    this._message("Opening version…");
    try {
      const response = await this.get(`/workshop/project?path=${encodeURIComponent(path)}`);
      if (!response.ok) throw new Error("load failed");
      const data = await response.json();
      if (!data?.ok || data.path !== path || !validWorkshopProject(data.project)) throw new Error("invalid project");
      if (serial !== this.serial || revision !== this.app.workshopViewRevision ||
          this.app.activeView !== "robot" && this.app.activeView !== "house") return false;
      this.app.restoreWorkshopProject(data.project);
      this._message(`Opened “${data.title || "saved version"}”.`);
      this.close(false);
      const button = document.getElementById(this.app.activeView === "robot" ? "rb-projects-btn" : "hs-projects-btn");
      (button || document.getElementById("jarvis-prompt-input"))?.focus();
      return true;
    } catch (_) {
      if (serial === this.serial) this._message("Could not open that version. Your current scene is still here.");
      return false;
    } finally {
      if (this.request === request) { this.request = null; this._setBusy(false); }
    }
  }
}
