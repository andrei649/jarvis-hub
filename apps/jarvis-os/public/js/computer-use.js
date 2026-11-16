/**
 * JARVIS Computer Use: Meta Ads Autonomous Campaign Driver + Live Browser Tab Screen-Share
 */

import { campaignRowsHtml } from "./templates.js";

const INITIAL_CAMPAIGNS = [
  {
    on: false,
    name: "AIW | Jarvis Static | Purchase | 350 | Oct 10-17 2026",
    delivery: "Off",
    objective: "Sales",
    budget: "$120.00",
    results: "3 Website purchases",
    reach: "1,533",
    cpr: "$34.80",
    isDraft: false,
  },
  {
    on: false,
    name: "AIW | Jarvis Restaurant Reel | Purchase | 7D | Oct 2026",
    delivery: "Off",
    objective: "Sales",
    budget: "$95.00",
    results: "5 Website purchases",
    reach: "2,789",
    cpr: "$28.40",
    isDraft: false,
  },
  {
    on: false,
    name: "AI Workshop Skool",
    delivery: "Off",
    objective: "Leads",
    budget: "$50.00",
    results: "—",
    reach: "—",
    cpr: "—",
    isDraft: false,
  },
];

export class ComputerUseController {
  constructor(hud) {
    this.hud = hud;
    this.overlay = document.getElementById("computer-use-overlay");
    this.tbody = document.getElementById("meta-campaigns-tbody");
    this.cursor = document.getElementById("ai-driver-cursor");
    this.driverLog = document.getElementById("meta-driver-log");
    this.modal = document.getElementById("meta-create-modal");
    this.publishBtn = document.getElementById("meta-publish-btn");
    this.campaigns = [...INITIAL_CAMPAIGNS];
    this.screenStream = null;
    this.running = false;

    this._renderTable();
    this._bindEvents();
  }

  _renderTable() {
    this.tbody.innerHTML = campaignRowsHtml(this.campaigns);

    const drafts = this.campaigns.filter((c) => c.isDraft).length;
    this.publishBtn.textContent = `Review and publish (${drafts})`;
    this.publishBtn.disabled = drafts === 0;
    document.getElementById("meta-selected-badge").textContent = `${this.campaigns.length} total`;
  }

  _bindEvents() {
    document.getElementById("cu-close-btn").addEventListener("click", () => this.close());

    document.getElementById("cu-run-demo-btn").addEventListener("click", () => {
      this.runAutonomousCampaign({
        campaignName: "AIW | Skool Community Leads | Nov 2026",
        dailyBudget: 65,
        objective: "Leads",
      });
    });

    document.getElementById("meta-create-btn").addEventListener("click", () => {
      this.modal.classList.remove("hidden");
    });

    document.getElementById("meta-modal-close").addEventListener("click", () => {
      this.modal.classList.add("hidden");
    });

    document.querySelectorAll(".obj-item").forEach((el) => {
      el.addEventListener("click", () => {
        document.querySelectorAll(".obj-item").forEach((o) => o.classList.remove("active"));
        el.classList.add("active");
      });
    });

    document.getElementById("meta-save-draft-btn").addEventListener("click", () => {
      const name = document.getElementById("meta-camp-name").value.trim() || "New Leads Campaign";
      const budget = Number(document.getElementById("meta-camp-budget").value || 50);
      const activeObj = document.querySelector(".obj-item.active")?.dataset.obj || "Leads";
      this._insertDraft(name, budget, activeObj);
      this.modal.classList.add("hidden");
    });

    document.getElementById("meta-discard-btn").addEventListener("click", () => {
      this.campaigns = this.campaigns.filter((c) => !c.isDraft);
      this._renderTable();
      this.driverLog.textContent = "Drafts cleared";
    });

    document.getElementById("meta-publish-btn").addEventListener("click", () => {
      this.campaigns.forEach((c) => {
        if (c.isDraft) {
          c.isDraft = false;
          c.on = true;
          c.delivery = "In Review";
        }
      });
      this._renderTable();
      this.hud.speak("Campaign submitted for review, sir.");
    });

    // Live browser tab sharing via getDisplayMedia
    document.getElementById("cu-share-tab-btn").addEventListener("click", async () => {
      try {
        this.screenStream = await navigator.mediaDevices.getDisplayMedia({ video: true });
        const video = document.getElementById("cu-live-video");
        video.srcObject = this.screenStream;
        document.getElementById("meta-ads-workspace").classList.add("hidden");
        document.getElementById("cu-live-screen-wrap").classList.remove("hidden");
        document.getElementById("cu-sharing-status").textContent = "Sharing Live Browser Tab to J.A.R.V.I.S. (DRIVING)";
        this.hud.setStatus("driving");
        this.hud.speak("Live screen feed locked in, sir. Watching your active tab.");
      } catch (_) {
        this.hud.showSubtitle("Tab screen-share cancelled — staying in Meta Ads sandbox.");
      }
    });

    document.getElementById("cu-stop-share-btn").addEventListener("click", () => {
      if (this.screenStream) this.screenStream.getTracks().forEach((t) => t.stop());
      this.screenStream = null;
      document.getElementById("cu-live-screen-wrap").classList.add("hidden");
      document.getElementById("meta-ads-workspace").classList.remove("hidden");
    });
  }

  _insertDraft(name, budget, objective) {
    // These can be a model's action parameters: coerce the types here, and the table
    // builder escapes the text (templates.js).
    const amount = Number(budget);
    this.campaigns.unshift({
      on: true,
      name: String(name ?? ""),
      delivery: "In Draft",
      objective: String(objective ?? ""),
      budget: `$${(Number.isFinite(amount) ? amount : 0).toFixed(2)}`,
      results: "Advantage+ Ready",
      reach: "Est. 8.4K–21K",
      cpr: "—",
      isDraft: true,
    });
    this._renderTable();
  }

  open() {
    this.overlay.classList.remove("hidden");
    this.hud.setStatus("driving");
  }

  close() {
    this.overlay.classList.add("hidden");
    if (this.screenStream) {
      this.screenStream.getTracks().forEach((t) => t.stop());
      this.screenStream = null;
    }
    this.cursor.classList.add("hidden");
    this.hud.setStatus("online");
  }

  _moveCursorToEl(el) {
    if (!el) return;
    const r = el.getBoundingClientRect();
    this.cursor.style.left = `${r.left + r.width * 0.45}px`;
    this.cursor.style.top = `${r.top + r.height * 0.5}px`;
  }

  async runAutonomousCampaign({
    campaignName = "AIW | Skool Sign-Up Leads | Nov 2026",
    dailyBudget = 50,
    objective = "Leads",
  } = {}) {
    if (this.running) return;
    this.running = true;
    this.open();

    const wait = (ms) => new Promise((res) => setTimeout(res, ms));
    this.cursor.classList.remove("hidden");
    this.hud.setStatus("driving");
    this.hud.logReflex("ComputerUse: Navigating Meta Ads Manager");

    // Step 1: Move to + Create button
    this.driverLog.textContent = "Step 1/5 · Clicking '+ Create' campaign...";
    const createBtn = document.getElementById("meta-create-btn");
    this._moveCursorToEl(createBtn);
    await wait(750);
    this.modal.classList.remove("hidden");
    await wait(500);

    // Step 2: Select Leads Objective
    this.driverLog.textContent = `Step 2/5 · Selecting '${objective}' objective...`;
    const objEl =
      Array.from(document.querySelectorAll(".obj-item")).find((el) => el.dataset.obj === objective) ||
      document.getElementById("obj-leads");
    this._moveCursorToEl(objEl);
    await wait(650);
    document.querySelectorAll(".obj-item").forEach((o) => o.classList.remove("active"));
    objEl.classList.add("active");

    // Step 3: Type Campaign Name character-by-character
    this.driverLog.textContent = "Step 3/5 · Naming Skool sign-up campaign...";
    const nameInput = document.getElementById("meta-camp-name");
    this._moveCursorToEl(nameInput);
    await wait(550);
    nameInput.value = "";
    for (let i = 0; i < campaignName.length; i += 2) {
      nameInput.value = campaignName.slice(0, i + 2);
      await wait(35);
    }

    // Step 4: Configure Advantage+ Daily Budget
    this.driverLog.textContent = `Step 4/5 · Setting Advantage+ budget to $${dailyBudget}/day...`;
    const budgetInput = document.getElementById("meta-camp-budget");
    this._moveCursorToEl(budgetInput);
    await wait(550);
    budgetInput.value = String(dailyBudget);

    // Step 5: Save Draft & Hover Review button safely
    this.driverLog.textContent = "Step 5/5 · Saving draft for human approval...";
    const saveBtn = document.getElementById("meta-save-draft-btn");
    this._moveCursorToEl(saveBtn);
    await wait(700);
    this._insertDraft(campaignName, dailyBudget, objective);
    this.modal.classList.add("hidden");

    await wait(350);
    this._moveCursorToEl(this.publishBtn);
    this.driverLog.textContent = "Draft staged — awaiting human approval to publish";

    this.hud.speak(
      `Your new ${String(objective).toLowerCase()} campaign "${campaignName}" is staged at ${dailyBudget} dollars a day, sir. Ready whenever you wish to press publish.`
    );
    setTimeout(() => {
      this.cursor.classList.add("hidden");
      this.running = false;
    }, 1400);
  }
}
