(function () {
  "use strict";

  const root = document.getElementById("risk");
  if (!root) return;

  let currentStep = 1;
  let highestUnlockedStep = 1;
  const stepNames = {1: "Accounting quality", 2: "Core value"};

  function syncCompany(value) {
    const company = String(value || "").trim().toUpperCase();
    if (!company) return;
    ["valuationCompany", "tradeCompany"].forEach(function (id) {
      const field = document.getElementById(id);
      if (field) field.value = company;
    });
  }

  function closeInfoTips(except) {
    root.querySelectorAll(".risk-info-tip.is-open").forEach(function (tip) {
      if (tip === except) return;
      tip.classList.remove("is-open");
      tip.setAttribute("aria-expanded", "false");
    });
  }

  function toggleInfoTip(tip) {
    const open = !tip.classList.contains("is-open");
    closeInfoTips(tip);
    tip.classList.toggle("is-open", open);
    tip.setAttribute("aria-expanded", String(open));
  }

  function openRiskTarget(id) {
    const target = document.getElementById(id);
    if (!target) return;
    if (target.tagName === "DETAILS") target.open = true;
    target.scrollIntoView({behavior: "smooth", block: "start"});
    window.setTimeout(function () {
      (target.tagName === "DETAILS" ? target.querySelector("summary") : target)?.focus?.({preventScroll: true});
    }, 350);
  }

  function updateStepTracker() {
    root.querySelectorAll("[data-risk-step-tab]").forEach(function (tab) {
      const step = Number(tab.dataset.riskStepTab);
      const unlocked = step <= highestUnlockedStep;
      const active = step === currentStep;
      const complete = step < currentStep || (step < highestUnlockedStep && !active);
      tab.disabled = !unlocked;
      tab.setAttribute("aria-disabled", String(!unlocked));
      if (active) tab.setAttribute("aria-current", "step");
      else tab.removeAttribute("aria-current");
      tab.dataset.state = active ? "active" : complete ? "complete" : unlocked ? "available" : "locked";
      const status = tab.querySelector("[data-risk-step-status]");
      if (status) status.textContent = active ? "Current" : complete ? "Complete" : unlocked ? "Available" : "Locked";
    });
    const label = root.querySelector("[data-risk-progress-label]");
    if (label) label.textContent = `Stage ${currentStep} of 2 · ${stepNames[currentStep]}`;
    const bar = root.querySelector("[data-risk-progress-bar]");
    if (bar) bar.style.width = `${currentStep / 2 * 100}%`;
  }

  function setStep(step, options) {
    const next = Number(step);
    if (!Number.isInteger(next) || next < 1 || next > highestUnlockedStep) return;
    currentStep = next;
    root.querySelectorAll("[data-risk-step-panel]").forEach(function (panel) {
      panel.hidden = Number(panel.dataset.riskStepPanel) !== currentStep;
    });
    updateStepTracker();
    if (options?.scroll !== false) {
      root.querySelector(`[data-risk-step-panel="${currentStep}"]`)?.scrollIntoView({behavior: "smooth", block: "start"});
    }
  }

  function resetProgress() {
    highestUnlockedStep = root.dataset.reviewReady === "true" ? 2 : 1;
    currentStep = 1;
    root.querySelectorAll("[data-risk-step-panel]").forEach(function (panel) {
      panel.hidden = Number(panel.dataset.riskStepPanel) !== 1;
    });
    updateStepTracker();
  }

  root.addEventListener("click", function (event) {
    const infoTip = event.target.closest(".risk-info-tip");
    if (infoTip) {
      event.preventDefault();
      event.stopPropagation();
      toggleInfoTip(infoTip);
      return;
    }
    closeInfoTips();

    const stepTab = event.target.closest("[data-risk-step-tab]");
    if (stepTab) {
      setStep(stepTab.dataset.riskStepTab);
      return;
    }
    const stepAction = event.target.closest("[data-risk-step-go]");
    if (stepAction) {
      setStep(stepAction.dataset.riskStepGo);
      return;
    }
    const targetButton = event.target.closest("[data-risk-target]");
    if (targetButton) openRiskTarget(targetButton.dataset.riskTarget);
    if (event.target.closest('[data-action="risk"]')) {
      root.dataset.reviewReady = "false";
      highestUnlockedStep = 1;
      currentStep = 1;
      updateStepTracker();
    }
  });

  root.addEventListener("keydown", function (event) {
    const infoTip = event.target.closest(".risk-info-tip");
    if (infoTip && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      toggleInfoTip(infoTip);
    } else if (event.key === "Escape") {
      closeInfoTips();
      event.target.blur?.();
    }
  });

  document.getElementById("riskCompany")?.addEventListener("change", function (event) {
    syncCompany(event.currentTarget.value);
  });
  document.getElementById("riskCompany")?.addEventListener("keydown", function (event) {
    if (event.key !== "Enter") return;
    event.preventDefault();
    syncCompany(event.currentTarget.value);
    root.querySelector('[data-action="risk"]')?.click();
  });

  root.addEventListener("risk:review-ready", function () {
    root.dataset.reviewReady = "true";
    highestUnlockedStep = 2;
    updateStepTracker();
  });
  root.addEventListener("risk:open-step", function (event) {
    const step = Number(event.detail?.step);
    if (event.detail?.unlock && step === 2) highestUnlockedStep = 2;
    setStep(step, {scroll: false});
  });
  root.addEventListener("risk:opened", resetProgress);

  resetProgress();
})();
