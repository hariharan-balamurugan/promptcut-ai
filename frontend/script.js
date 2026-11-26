/* =================================================================
   PromptCut AI — script.js
   Sections:
     1. State + constants
     2. Tab navigation
     3. Single Edit
     4. Batch Processing
     5. Reference Video
     6. Music Library
     7. Utilities
   ================================================================= */

/* ================================================================
   1. STATE + CONSTANTS
   ================================================================ */

const API = (window.location.protocol.startsWith("http") && (window.location.port === "8000" || window.location.host.includes(":8000")))
  ? ""
  : "http://127.0.0.1:8000";

const state = {
  singleVideoId: null,
  singleVideoIds: [],
  singleClips: [],
  batchFiles: [],         // [{file, videoId, status:"waiting"|"uploading"|"done"|"failed", error}]
  batchMode: "merge",     // "merge" | "individual"
  currentBatchId: null,
  referenceId: null,
  useReference: false,
  pollingTimer: null
};

/* ================================================================
   2. TAB NAVIGATION
   ================================================================ */

const tabBtns = document.querySelectorAll(".tab-btn");
const tabPanes = document.querySelectorAll(".tab-pane");

tabBtns.forEach(btn => {
  btn.addEventListener("click", () => {
    const target = btn.dataset.tab;
    tabBtns.forEach(b => b.classList.toggle("active", b === btn));
    tabPanes.forEach(p => {
      const isTarget = p.id === `tab-${target}`;
      p.classList.toggle("active", isTarget);
    });
  });
});

/* ================================================================
   3. SINGLE EDIT
   ================================================================ */

const videoFile          = document.getElementById("videoFile");
const videoPreview       = document.getElementById("videoPreview");
const previewPlaceholder = document.getElementById("previewPlaceholder");
const uploadStatus       = document.getElementById("uploadStatus");
const singleMultiClipsList = document.getElementById("singleMultiClipsList");
const videoInfo          = document.getElementById("videoInfo");
const editPrompt         = document.getElementById("editPrompt");
const aiProvider         = document.getElementById("aiProvider");
const editButton         = document.getElementById("editButton");
const editStatus         = document.getElementById("editStatus");
const resultCard         = document.getElementById("resultCard");
const resultDetails      = document.getElementById("resultDetails");
const downloadBtn        = document.getElementById("downloadBtn");
const referenceToggleBar = document.getElementById("referenceToggleBar");
const referenceToggleInfo= document.getElementById("referenceToggleInfo");
const useReferenceToggle = document.getElementById("useReferenceToggle");

// AI Step Progress Tracker DOM elements (04. Separate Bottom Box)
const liveTrackerPanel        = document.getElementById("liveTrackerPanel");
const trackerLiveBadge        = document.getElementById("trackerLiveBadge");
const aiStepTimer             = document.getElementById("aiStepTimer");
const aiStepProgressFill      = document.getElementById("aiStepProgressFill");
const bannerSpinner           = document.getElementById("bannerSpinner");
const trackerCurrentAction    = document.getElementById("trackerCurrentAction");
const terminalStatusText      = document.getElementById("terminalStatusText");
const trackerTerminalBody     = document.getElementById("trackerTerminalBody");
const trackerCompletedBox     = document.getElementById("trackerCompletedBox");
const trackerCompletedSummary = document.getElementById("trackerCompletedSummary");
const aiOperationsList        = document.getElementById("aiOperationsList");

let trackerTimerInterval = null;
let trackerStepInterval  = null;
let trackerSeconds       = 0;
let currentActiveStep    = 1;

function addTerminalLog(msg, type = "info") {
  if (!trackerTerminalBody) return;
  const now = new Date().toTimeString().split(" ")[0];
  const line = document.createElement("div");
  line.className = `log-line ${type}`;
  line.textContent = `[${now}] ${msg}`;
  trackerTerminalBody.appendChild(line);
  trackerTerminalBody.scrollTop = trackerTerminalBody.scrollHeight;
}

function resetStepTracker() {
  if (trackerTimerInterval) clearInterval(trackerTimerInterval);
  if (trackerStepInterval) clearInterval(trackerStepInterval);
  trackerSeconds = 0;
  currentActiveStep = 1;

  if (trackerLiveBadge) {
    trackerLiveBadge.className = "tracker-live-badge ready";
    trackerLiveBadge.textContent = "READY";
  }
  if (aiStepTimer) aiStepTimer.textContent = "00:00";
  if (aiStepProgressFill) {
    aiStepProgressFill.style.width = "0%";
    aiStepProgressFill.style.background = "linear-gradient(90deg, #6366f1, #a855f7, #ec4899, #10b981)";
  }
  if (bannerSpinner) bannerSpinner.className = "banner-spinner stopped";
  if (trackerCurrentAction) trackerCurrentAction.textContent = "Ready. Select a video and click \"Generate editing plan\".";
  if (terminalStatusText) terminalStatusText.textContent = "IDLE";
  if (trackerCompletedBox) trackerCompletedBox.style.display = "none";
  if (aiOperationsList) aiOperationsList.innerHTML = "";

  for (let i = 1; i <= 6; i++) {
    const el = document.getElementById(`step-${i}`);
    if (!el) continue;
    el.className = "tracker-step-card pending";
    const status = el.querySelector(".step-card-status");
    if (status) status.textContent = "Waiting";
  }
}

function setStepState(stepNum, status, statusText = null, actionText = null) {
  const el = document.getElementById(`step-${stepNum}`);
  if (!el) return;
  el.className = `tracker-step-card ${status}`;
  const statusEl = el.querySelector(".step-card-status");

  if (status === "active") {
    if (statusEl) statusEl.textContent = statusText || "Running...";
    if (trackerCurrentAction && actionText) trackerCurrentAction.textContent = actionText;
    addTerminalLog(`Stage ${stepNum} started: ${actionText || statusText || 'Running'}`, "active");
  } else if (status === "done") {
    if (statusEl) statusEl.textContent = statusText || "Done ✓";
    addTerminalLog(`Stage ${stepNum} completed successfully ✓`, "success");
  } else if (status === "failed") {
    if (statusEl) statusEl.textContent = statusText || "Failed ✗";
    addTerminalLog(`Stage ${stepNum} failed: ${actionText || 'Error'}`, "error");
  } else {
    if (statusEl) statusEl.textContent = statusText || "Waiting";
  }
}

function startStepTracker(promptText = "") {
  resetStepTracker();

  if (liveTrackerPanel) {
    liveTrackerPanel.scrollIntoView({ behavior: "smooth", block: "start" });
    liveTrackerPanel.classList.add("active-tracking");
  }

  if (trackerLiveBadge) {
    trackerLiveBadge.className = "tracker-live-badge running";
    trackerLiveBadge.textContent = "PROCESSING";
  }
  if (bannerSpinner) bannerSpinner.className = "banner-spinner";
  if (terminalStatusText) terminalStatusText.textContent = "ACTIVE";

  addTerminalLog(`New edit job initiated with prompt: "${promptText.slice(0, 60)}${promptText.length > 60 ? '...' : ''}"`, "info");
  addTerminalLog("⚡ Turbo Fast Mode active (optimized multi-threaded rendering).", "info");

  // Step 1 active immediately
  setStepState(1, "active", "In Progress", "Interpreting prompt instructions with AI...");
  if (aiStepProgressFill) aiStepProgressFill.style.width = "15%";

  trackerTimerInterval = setInterval(() => {
    trackerSeconds++;
    const m = String(Math.floor(trackerSeconds / 60)).padStart(2, "0");
    const s = String(trackerSeconds % 60).padStart(2, "0");
    if (aiStepTimer) aiStepTimer.textContent = `${m}:${s}`;
  }, 1000);

  const stepDelays = [
    { step: 1, advanceAt: 2,  next: 2, pct: 30, label: "Analyzing", desc: "Extracting video keyframes and analyzing emotion timeline with Vision AI..." },
    { step: 2, advanceAt: 5,  next: 3, pct: 55, label: "Matching",  desc: "Searching catalog and matching soundtrack with emotion intervals..." },
    { step: 3, advanceAt: 9,  next: 4, pct: 75, label: "Rendering", desc: "Applying visual transitions (slides/zooms), cuts, and speed adjustments..." },
    { step: 4, advanceAt: 13, next: 5, pct: 88, label: "Syncing",    desc: "Synchronizing soundtrack audio and background music..." },
    { step: 5, advanceAt: 17, next: 6, pct: 96, label: "Exporting", desc: "FFmpeg combining audio/video streams and rendering final MP4 video..." }
  ];

  trackerStepInterval = setInterval(() => {
    for (const d of stepDelays) {
      if (trackerSeconds >= d.advanceAt && currentActiveStep === d.step) {
        setStepState(d.step, "done");
        setStepState(d.next, "active", d.label, d.desc);
        currentActiveStep = d.next;
        if (aiStepProgressFill) aiStepProgressFill.style.width = `${d.pct}%`;
        break;
      }
    }
  }, 1000);
}

function completeStepTracker(data) {
  if (trackerTimerInterval) clearInterval(trackerTimerInterval);
  if (trackerStepInterval) clearInterval(trackerStepInterval);

  if (liveTrackerPanel) {
    liveTrackerPanel.classList.remove("active-tracking");
  }

  for (let i = 1; i <= 6; i++) {
    setStepState(i, "done", "Done ✓");
  }

  if (trackerLiveBadge) {
    trackerLiveBadge.className = "tracker-live-badge completed";
    trackerLiveBadge.textContent = "COMPLETED";
  }
  if (bannerSpinner) bannerSpinner.className = "banner-spinner stopped";
  if (aiStepProgressFill) aiStepProgressFill.style.width = "100%";
  if (terminalStatusText) terminalStatusText.textContent = "DONE";
  if (trackerCurrentAction) trackerCurrentAction.textContent = "All 6 stages of the AI editing pipeline completed successfully!";

  addTerminalLog("Video editing & mastering finished! Output ready for download.", "success");

  // Populate completed chips
  if (aiOperationsList) {
    aiOperationsList.innerHTML = "";
    const chips = [];

    if (data.operations_applied) {
      const list = Array.isArray(data.operations_applied) ? data.operations_applied : [data.operations_applied];
      list.forEach(op => {
        if (typeof op === "object") {
          chips.push(`<strong>Action:</strong> ${op.type || "Effect"} ${op.transition || ""}`);
        } else {
          chips.push(`<strong>Applied:</strong> ${op}`);
        }
      });
    }

    if (data.detected_emotion) {
      chips.push(`<strong>Emotion Detected:</strong> ${data.detected_emotion}`);
    }

    if (data.background_music) {
      const title = data.background_music.track_name || data.background_music.filename || "Soundtrack";
      chips.push(`<strong>Music:</strong> ${title}`);
    }

    if (data.captions) {
      if (data.captions.subtitle_rendered) {
        chips.push(`<strong>Karaoke Captions:</strong> Rendered (${data.captions.caption_count || 0} events)`);
      } else {
        chips.push(`<strong>Captions:</strong> ${data.captions.status || "Ready"}`);
      }
    }

    if (data.output_info) {
      chips.push(`<strong>Export:</strong> ${data.output_info.width || ""}×${data.output_info.height || ""} (${Number(data.output_info.duration_seconds || 0).toFixed(1)}s)`);
    }

    chips.forEach(html => {
      const chip = document.createElement("div");
      chip.className = "completed-chip";
      chip.innerHTML = html;
      aiOperationsList.appendChild(chip);
    });
  }

  // Update download link
  const downloadFilename = data.output_filename || (data.download_url ? data.download_url.split("/").pop() : null);
  if (downloadFilename && downloadBtn) {
    downloadBtn.href = `${API}/api/download/${downloadFilename}`;
    downloadBtn.style.display = "inline-block";
  }

  if (trackerCompletedBox) trackerCompletedBox.style.display = "flex";

  // Smooth scroll to the tracker panel so the user sees the completed box immediately
  if (liveTrackerPanel) {
    liveTrackerPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
}

function failStepTracker(errMessage) {
  if (trackerTimerInterval) clearInterval(trackerTimerInterval);
  if (trackerStepInterval) clearInterval(trackerStepInterval);

  if (trackerLiveBadge) {
    trackerLiveBadge.className = "tracker-live-badge failed";
    trackerLiveBadge.textContent = "FAILED";
  }
  if (bannerSpinner) bannerSpinner.className = "banner-spinner stopped";
  if (terminalStatusText) terminalStatusText.textContent = "ERROR";
  if (trackerCurrentAction) trackerCurrentAction.textContent = `Interrupted: ${errMessage}`;
  if (aiStepProgressFill) aiStepProgressFill.style.background = "#ef4444";

  setStepState(currentActiveStep, "failed", "Failed ✗", errMessage);
  addTerminalLog(`Error: ${errMessage}`, "error");
}

let previewUrl = null;

// Sync the reference toggle with state
useReferenceToggle.addEventListener("change", () => {
  state.useReference = useReferenceToggle.checked;
  referenceToggleInfo.textContent = state.useReference
    ? `Reference style will be applied (ID: ${state.referenceId})`
    : "";
});

function renderSingleClipsList() {
  if (!singleMultiClipsList) return;
  if (!state.singleClips || state.singleClips.length <= 1) {
    singleMultiClipsList.style.display = "none";
    singleMultiClipsList.innerHTML = "";
    return;
  }
  singleMultiClipsList.style.display = "flex";
  singleMultiClipsList.innerHTML = `
    <div style="font-size:12px; font-weight:700; color:var(--accent-light); margin-bottom:4px; display:flex; justify-content:space-between; align-items:center;">
      <span>🎬 CLIPS TO MERGE (${state.singleClips.length} clips in order)</span>
      <span style="font-size:11px; color:var(--muted); font-weight:normal;">Will stitch into 1 video</span>
    </div>
  `;
  state.singleClips.forEach((clip, idx) => {
    const item = document.createElement("div");
    item.className = "clip-order-item";
    const statusText = clip.status === "done" ? "✓ Ready" : clip.status === "uploading" ? "⬆ Uploading..." : "✗ Failed";
    const statusColor = clip.status === "done" ? "var(--green)" : clip.status === "uploading" ? "var(--accent)" : "var(--red)";
    item.innerHTML = `
      <span class="clip-index-badge">#${idx + 1}</span>
      <span style="flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(clip.file.name)}">${escapeHtml(clip.file.name)}</span>
      <span style="color:${statusColor}; font-size:11px; font-weight:600;">${statusText}</span>
      <button class="btn-reorder" data-action="up" data-idx="${idx}" ${idx === 0 ? "disabled" : ""}>▲</button>
      <button class="btn-reorder" data-action="down" data-idx="${idx}" ${idx === state.singleClips.length - 1 ? "disabled" : ""}>▼</button>
      <button class="file-list-remove" data-action="del" data-idx="${idx}">✕</button>
    `;
    singleMultiClipsList.appendChild(item);
  });

  singleMultiClipsList.querySelectorAll(".btn-reorder").forEach(btn => {
    btn.addEventListener("click", () => {
      const idx = parseInt(btn.dataset.idx, 10);
      const action = btn.dataset.action;
      if (action === "up" && idx > 0) {
        const temp = state.singleClips[idx];
        state.singleClips[idx] = state.singleClips[idx - 1];
        state.singleClips[idx - 1] = temp;
      } else if (action === "down" && idx < state.singleClips.length - 1) {
        const temp = state.singleClips[idx];
        state.singleClips[idx] = state.singleClips[idx + 1];
        state.singleClips[idx + 1] = temp;
      }
      state.singleVideoIds = state.singleClips.filter(c => c.status === "done").map(c => c.videoId);
      renderSingleClipsList();
    });
  });

  singleMultiClipsList.querySelectorAll(".file-list-remove").forEach(btn => {
    btn.addEventListener("click", () => {
      const idx = parseInt(btn.dataset.idx, 10);
      state.singleClips.splice(idx, 1);
      state.singleVideoIds = state.singleClips.filter(c => c.status === "done").map(c => c.videoId);
      state.singleVideoId = state.singleVideoIds[0] || null;
      renderSingleClipsList();
      if (state.singleClips.length === 0) {
        editButton.disabled = true;
        editButton.textContent = "✦ Generate editing plan";
      }
    });
  });
}

// File(s) selected for single edit
videoFile.addEventListener("change", async () => {
  const files = Array.from(videoFile.files);
  if (!files.length) return;

  resultCard.style.display = "none";
  editButton.disabled = true;

  if (files.length === 1) {
    const file = files[0];
    if (file.size > 200 * 1024 * 1024) {
      uploadStatus.textContent = "File exceeds the 200 MB limit.";
      videoFile.value = "";
      return;
    }
    state.singleClips = [];
    state.singleVideoIds = [];
    renderSingleClipsList();

    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = URL.createObjectURL(file);
    videoPreview.src = previewUrl;
    videoPreview.hidden = false;
    previewPlaceholder.hidden = true;

    uploadStatus.textContent = "Uploading video...";
    editStatus.textContent = "Please wait for the upload to finish.";
    editButton.textContent = "✦ Generate editing plan";

    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await fetch(`${API}/api/upload`, {
        method: "POST",
        body: formData
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Video upload failed.");

      state.singleVideoId = data.video_id;
      state.singleVideoIds = [data.video_id];
      uploadStatus.textContent = "Video uploaded successfully!";
      videoInfo.textContent =
        `Duration: ${Number(data.duration_seconds).toFixed(2)} s · ` +
        `Resolution: ${data.width} × ${data.height}`;
      editStatus.textContent = "Your video is ready for editing.";
      editButton.disabled = false;
      resetStepTracker();
    } catch (err) {
      state.singleVideoId = null;
      state.singleVideoIds = [];
      uploadStatus.textContent = `Upload error: ${err.message}`;
      editStatus.textContent = "Check that the FastAPI backend is running.";
      editButton.disabled = true;
      showToast(err.message, "error");
    }
    return;
  }

  // Multiple files selected (2 or more clips to merge)
  state.singleClips = files.map(f => ({ file: f, videoId: null, status: "uploading", duration: 0 }));
  state.singleVideoIds = [];
  renderSingleClipsList();

  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = URL.createObjectURL(files[0]);
  videoPreview.src = previewUrl;
  videoPreview.hidden = false;
  previewPlaceholder.hidden = true;

  uploadStatus.textContent = `Uploading ${files.length} clips for merged editing...`;
  editStatus.textContent = "Uploading selected clips...";
  editButton.textContent = "🎬 Merge & Generate editing plan";

  for (let i = 0; i < files.length; i++) {
    const f = files[i];
    const formData = new FormData();
    formData.append("file", f);
    try {
      const res = await fetch(`${API}/api/upload`, { method: "POST", body: formData });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Upload failed");
      state.singleClips[i].videoId = data.video_id;
      state.singleClips[i].status = "done";
      state.singleClips[i].duration = data.duration_seconds;
    } catch (err) {
      state.singleClips[i].status = "failed";
      showToast(`Failed uploading ${f.name}: ${err.message}`, "error");
    }
    renderSingleClipsList();
  }

  state.singleVideoIds = state.singleClips.filter(c => c.status === "done").map(c => c.videoId);
  state.singleVideoId = state.singleVideoIds[0] || null;

  if (state.singleVideoIds.length >= 2) {
    uploadStatus.textContent = `✓ ${state.singleVideoIds.length} clips uploaded! Ready to merge & edit into a single video.`;
    videoInfo.textContent = `Multiple Clips: ${state.singleVideoIds.length} clips ready for sequential merge.`;
    editStatus.textContent = "Enter your prompt and click 'Merge & Generate editing plan'.";
    editButton.disabled = false;
    resetStepTracker();
  } else {
    uploadStatus.textContent = `Upload complete. At least 2 clips required to merge.`;
    editButton.disabled = state.singleVideoIds.length === 0;
  }
});

// Generate editing plan / edit
editButton.addEventListener("click", async () => {
  const prompt = editPrompt.value.trim();

  if (!state.singleVideoId && (!state.singleVideoIds || state.singleVideoIds.length === 0)) {
    editStatus.textContent = "Please upload video file(s) first.";
    return;
  }
  if (!prompt) {
    editStatus.textContent = "Please describe the edits you want.";
    return;
  }

  editButton.disabled = true;
  editStatus.textContent = "Generating your editing plan...";
  resultCard.style.display = "none";
  const planSummaryBox = document.getElementById("planSummaryBox");
  if (planSummaryBox) planSummaryBox.style.display = "none";
  startStepTracker(prompt);

  try {
    let endpoint = `${API}/api/edit`;
    let body = {};

    if (state.singleVideoIds && state.singleVideoIds.length > 1) {
      endpoint = `${API}/api/edit/merge`;
      body = {
        video_ids: state.singleVideoIds,
        prompt: prompt,
        provider: aiProvider.value,
        fast_mode: true
      };
      if (trackerCurrentAction) {
        trackerCurrentAction.textContent = `Merging ${state.singleVideoIds.length} clips into a single video and processing AI edits...`;
      }
    } else {
      body = {
        video_id: state.singleVideoId,
        prompt: prompt,
        provider: aiProvider.value,
        fast_mode: true
      };
      if (state.useReference && state.referenceId) {
        endpoint = `${API}/api/edit/with-reference`;
        body.reference_id = state.referenceId;
      }
    }

    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });

    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Editing request failed.");

    // Complete the step tracker with live operations breakdown
    completeStepTracker(data);

    // Show result card
    renderResultCard(data);
    renderPlanSummary(data);
    editStatus.textContent = "Edit complete! All AI operations executed.";
    showToast("Edit completed successfully!", "success");

  } catch (err) {
    failStepTracker(err.message);
    editStatus.textContent = `Error: ${err.message}\nCheck the backend endpoint and provider configuration.`;
    showToast(err.message, "error");
  } finally {
    editButton.disabled = false;
  }
});

function renderResultCard(data) {
  resultCard.style.display = "block";
  resultDetails.innerHTML = "";

  // Build detail rows from response fields
  const fields = [];

  const downloadFilename = data.output_filename || (data.download_url ? data.download_url.split("/").pop() : null);
  if (downloadFilename) {
    fields.push({ label: "Output File", value: downloadFilename });
    downloadBtn.href = `${API}/api/download/${downloadFilename}`;
    downloadBtn.style.display = "inline-block";
  } else {
    downloadBtn.style.display = "none";
  }

  if (data.operations_applied)
    fields.push({ label: "Operations Applied", value: Array.isArray(data.operations_applied) ? data.operations_applied.join(", ") : data.operations_applied });

  if (data.duration_seconds != null)
    fields.push({ label: "Output Duration", value: formatDuration(data.duration_seconds) });

  if (data.music_track)
    fields.push({ label: "Music Track", value: data.music_track });

  if (data.provider_used)
    fields.push({ label: "Provider Used", value: data.provider_used });

  if (data.message)
    fields.push({ label: "Message", value: data.message });

  // Fallback: show raw JSON keys
  if (fields.length === 0) {
    fields.push({ label: "Response", value: JSON.stringify(data, null, 2) });
  }

  fields.forEach(({ label, value }) => {
    const item = document.createElement("div");
    item.className = "result-detail-item";
    item.innerHTML = `<div class="result-detail-label">${label}</div><div class="result-detail-value">${escapeHtml(String(value))}</div>`;
    resultDetails.appendChild(item);
  });
}

function renderPlanSummary(data) {
  const planSummaryBox = document.getElementById("planSummaryBox");
  const planSummaryCount = document.getElementById("planSummaryCount");
  const planSummaryOverview = document.getElementById("planSummaryOverview");
  const planSummaryOps = document.getElementById("planSummaryOps");
  if (!planSummaryBox || !planSummaryCount || !planSummaryOverview || !planSummaryOps) return;

  const plan = data.plan || {};
  const ops = Array.isArray(plan.operations) ? plan.operations : [];

  planSummaryCount.textContent = `${ops.length} operation${ops.length === 1 ? "" : "s"} executed`;

  let overviewText = "";
  if (data.merged_clips_count && data.merged_clips_count > 1) {
    overviewText += `Merged <strong>${data.merged_clips_count} clips</strong> into a single cohesive video. `;
  }
  if (data.background_music && data.background_music.title) {
    overviewText += `Matched soundtrack: <em>"${escapeHtml(data.background_music.title)}"</em>. `;
  } else if (data.music_track) {
    overviewText += `Soundtrack: <em>"${escapeHtml(data.music_track)}"</em>. `;
  }
  if (!overviewText) {
    overviewText = "AI analyzed the video and executed the planned adjustments:";
  }
  planSummaryOverview.innerHTML = overviewText;

  planSummaryOps.innerHTML = "";

  if (ops.length === 0) {
    const emptyItem = document.createElement("div");
    emptyItem.className = "plan-summary-item";
    emptyItem.innerHTML = `<span class="plan-op-badge">DIRECT</span> <span class="plan-op-desc">Audio mix & processing completed</span>`;
    planSummaryOps.appendChild(emptyItem);
  } else {
    ops.forEach(op => {
      const item = document.createElement("div");
      item.className = "plan-summary-item";

      let desc = "";
      const type = (op.type || "edit").toLowerCase();

      if (type === "trim") {
        desc = `Cut section from ${op.start ?? 0}s to ${op.end ?? "end"}s`;
      } else if (type === "resize") {
        desc = `Adjust aspect ratio to ${op.aspect_ratio || "custom"}`;
      } else if (type === "speed") {
        desc = `Change playback speed to ${op.factor}x${op.start != null ? ` (${op.start}s to ${op.end}s)` : " (full video)"}`;
      } else if (type === "transition") {
        desc = `Apply ${op.transition?.replace(/_/g, " ") || "fade"} transition (${op.duration || 1}s)`;
      } else if (type === "mute") {
        desc = `Muted original audio track`;
      } else {
        desc = `Applied ${type} modification`;
      }

      item.innerHTML = `<span class="plan-op-badge">${escapeHtml(type)}</span> <span class="plan-op-desc">${escapeHtml(desc)}</span>`;
      planSummaryOps.appendChild(item);
    });
  }

  planSummaryBox.style.display = "block";
}

/* ================================================================
   4. BATCH PROCESSING
   ================================================================ */

const batchDropZone   = document.getElementById("batchDropZone");
const batchFileInput  = document.getElementById("batchFileInput");
const batchFileList   = document.getElementById("batchFileList");
const uploadAllBtn    = document.getElementById("uploadAllBtn");
const batchPrompt     = document.getElementById("batchPrompt");
const batchProvider   = document.getElementById("batchProvider");
const startBatchBtn   = document.getElementById("startBatchBtn");
const batchStartStatus= document.getElementById("batchStartStatus");
const batchDashboard  = document.getElementById("batchDashboard");
const batchIdLabel    = document.getElementById("batchIdLabel");
const downloadZipBtn  = document.getElementById("downloadZipBtn");
const batchProgressFill = document.getElementById("batchProgressFill");
const batchProgressLabel= document.getElementById("batchProgressLabel");
const batchTableBody  = document.getElementById("batchTableBody");

const modeCardMerge          = document.getElementById("modeCardMerge");
const modeCardIndividual     = document.getElementById("modeCardIndividual");
const batchMergedResultBox   = document.getElementById("batchMergedResultBox");
const batchMergedDownloadBtn = document.getElementById("batchMergedDownloadBtn");
const batchMergedVideoPreview= document.getElementById("batchMergedVideoPreview");
const batchMergedSummaryText = document.getElementById("batchMergedSummaryText");

if (modeCardMerge && modeCardIndividual) {
  modeCardMerge.addEventListener("click", () => {
    state.batchMode = "merge";
    modeCardMerge.classList.add("active");
    modeCardIndividual.classList.remove("active");
    startBatchBtn.textContent = "🎬 Merge & Edit into Single Video";
    if (downloadZipBtn) downloadZipBtn.style.display = "none";
  });

  modeCardIndividual.addEventListener("click", () => {
    state.batchMode = "individual";
    modeCardIndividual.classList.add("active");
    modeCardMerge.classList.remove("active");
    startBatchBtn.textContent = "⚙ Start Batch Processing (Individual)";
    if (downloadZipBtn) downloadZipBtn.style.display = "inline-block";
  });
}

// Drag-and-drop support
batchDropZone.addEventListener("click", () => batchFileInput.click());

batchDropZone.addEventListener("dragover", e => {
  e.preventDefault();
  batchDropZone.classList.add("drag-over");
});

batchDropZone.addEventListener("dragleave", () => batchDropZone.classList.remove("drag-over"));

batchDropZone.addEventListener("drop", e => {
  e.preventDefault();
  batchDropZone.classList.remove("drag-over");
  addBatchFiles(Array.from(e.dataTransfer.files));
});

batchFileInput.addEventListener("change", () => {
  addBatchFiles(Array.from(batchFileInput.files));
  batchFileInput.value = ""; // reset so same file can be re-added
});

function addBatchFiles(files) {
  const allowed = /\.(mp4|mov|mkv|webm)$/i;
  files.forEach(file => {
    if (!allowed.test(file.name)) {
      showToast(`Skipped "${file.name}" — unsupported format`, "warning");
      return;
    }
    if (file.size > 200 * 1024 * 1024) {
      showToast(`"${file.name}" exceeds 200 MB`, "warning");
      return;
    }
    // Avoid duplicate filenames
    if (state.batchFiles.some(f => f.file.name === file.name && f.file.size === file.size)) {
      showToast(`"${file.name}" already in list`, "info");
      return;
    }
    state.batchFiles.push({ file, videoId: null, status: "waiting", error: null });
  });
  renderBatchFileList();
}

function renderBatchFileList() {
  batchFileList.innerHTML = "";
  state.batchFiles.forEach((item, idx) => {
    const row = document.createElement("div");
    row.className = "file-list-item";
    row.id = `bfl-${idx}`;

    const badge = makeBadge(item.status);
    const removeDisabled = item.status === "uploading" ? "disabled" : "";

    row.innerHTML = `
      <span class="clip-index-badge">#${idx + 1}</span>
      <span class="file-list-name" title="${escapeHtml(item.file.name)}">${escapeHtml(item.file.name)}</span>
      <span class="file-list-size">${formatSize(item.file.size)}</span>
      ${badge.outerHTML}
      <button class="btn-reorder" data-action="up" data-idx="${idx}" ${idx === 0 ? "disabled" : ""} title="Move Up">▲</button>
      <button class="btn-reorder" data-action="down" data-idx="${idx}" ${idx === state.batchFiles.length - 1 ? "disabled" : ""} title="Move Down">▼</button>
      <button class="file-list-remove" data-idx="${idx}" ${removeDisabled}>✕</button>
    `;
    batchFileList.appendChild(row);
  });

  // Reorder buttons
  batchFileList.querySelectorAll(".btn-reorder").forEach(btn => {
    btn.addEventListener("click", () => {
      const idx = parseInt(btn.dataset.idx, 10);
      const action = btn.dataset.action;
      if (action === "up" && idx > 0) {
        const temp = state.batchFiles[idx];
        state.batchFiles[idx] = state.batchFiles[idx - 1];
        state.batchFiles[idx - 1] = temp;
        renderBatchFileList();
      } else if (action === "down" && idx < state.batchFiles.length - 1) {
        const temp = state.batchFiles[idx];
        state.batchFiles[idx] = state.batchFiles[idx + 1];
        state.batchFiles[idx + 1] = temp;
        renderBatchFileList();
      }
    });
  });

  // Remove buttons
  batchFileList.querySelectorAll(".file-list-remove").forEach(btn => {
    btn.addEventListener("click", () => {
      const idx = parseInt(btn.dataset.idx, 10);
      state.batchFiles.splice(idx, 1);
      renderBatchFileList();
    });
  });

  uploadAllBtn.disabled = state.batchFiles.length === 0 ||
    state.batchFiles.every(f => f.status === "done");

  updateStartBatchBtn();
}

function updateBatchFileStatus(idx, status, videoId = null, error = null) {
  state.batchFiles[idx].status = status;
  if (videoId) state.batchFiles[idx].videoId = videoId;
  if (error)   state.batchFiles[idx].error   = error;

  const row = document.getElementById(`bfl-${idx}`);
  if (!row) return;
  const badge = row.querySelector(".status-badge");
  const newBadge = makeBadge(status);
  if (badge) badge.replaceWith(newBadge);
}

function updateStartBatchBtn() {
  const allDone = state.batchFiles.length > 0 &&
    state.batchFiles.every(f => f.status === "done" || f.status === "failed");
  const anyDone = state.batchFiles.some(f => f.status === "done");
  startBatchBtn.disabled = !(allDone && anyDone);
}

// Upload All — sequential
uploadAllBtn.addEventListener("click", async () => {
  uploadAllBtn.disabled = true;

  for (let i = 0; i < state.batchFiles.length; i++) {
    const item = state.batchFiles[i];
    if (item.status === "done") continue; // already uploaded

    updateBatchFileStatus(i, "uploading");

    const formData = new FormData();
    formData.append("file", item.file);

    try {
      const response = await fetch(`${API}/api/upload`, {
        method: "POST",
        body: formData
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Upload failed");

      updateBatchFileStatus(i, "done", data.video_id);
    } catch (err) {
      updateBatchFileStatus(i, "failed", null, err.message);
      showToast(`Failed to upload "${item.file.name}": ${err.message}`, "error");
    }
  }

  renderBatchFileList();
  updateStartBatchBtn();
  showToast("All uploads complete!", "success");
});

// Start Batch Processing
startBatchBtn.addEventListener("click", async () => {
  const prompt = batchPrompt.value.trim();
  if (!prompt) {
    batchStartStatus.textContent = "Please enter a batch editing prompt.";
    return;
  }

  const videoIds = state.batchFiles.filter(f => f.status === "done").map(f => f.videoId);
  if (videoIds.length === 0) {
    batchStartStatus.textContent = "No successfully uploaded videos to process.";
    return;
  }

  startBatchBtn.disabled = true;
  batchStartStatus.textContent = state.batchMode === "merge" ? "Merging clips & creating batch job..." : "Creating batch job...";

  try {
    const response = await fetch(`${API}/api/batch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        batch_prompt: prompt,
        video_ids: videoIds,
        provider: batchProvider.value,
        mode: state.batchMode || "merge"
      })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Batch creation failed");

    state.currentBatchId = data.batch_id;
    batchStartStatus.textContent = `Batch started! ID: ${data.batch_id}`;
    batchIdLabel.textContent = `BATCH: ${data.batch_id.slice(0, 8)}…`;

    showBatchDashboard(data);
    startBatchPolling(data.batch_id);
    showToast(state.batchMode === "merge" ? "Multi-clip merge batch started!" : "Batch processing started!", "success");

  } catch (err) {
    batchStartStatus.textContent = `Error: ${err.message}`;
    startBatchBtn.disabled = false;
    showToast(err.message, "error");
  }
});

function showBatchDashboard(data) {
  batchDashboard.style.display = "block";
  if (batchMergedResultBox) batchMergedResultBox.style.display = "none";
  renderBatchTable(data.jobs || []);
  updateBatchProgress(data);
  checkBatchMergedResult(data);
}

function checkBatchMergedResult(data) {
  const isMerge = data.mode === "merge" || state.batchMode === "merge";
  if (isMerge && data.output_filename && batchMergedResultBox) {
    batchMergedResultBox.style.display = "block";
    if (batchMergedVideoPreview) {
      batchMergedVideoPreview.src = `${API}/api/download/${data.output_filename}`;
      batchMergedVideoPreview.style.display = "block";
    }
    if (batchMergedDownloadBtn) {
      batchMergedDownloadBtn.href = `${API}/api/download/${data.output_filename}`;
      batchMergedDownloadBtn.style.display = "inline-block";
    }
    if (downloadZipBtn) {
      downloadZipBtn.style.display = "none";
    }
  } else if (!isMerge && downloadZipBtn) {
    downloadZipBtn.style.display = "inline-block";
  }
}

function renderBatchTable(jobs) {
  batchTableBody.innerHTML = "";
  if (!jobs || jobs.length === 0) {
    batchTableBody.innerHTML = `<tr><td colspan="3" class="table-empty">No jobs yet.</td></tr>`;
    return;
  }
  jobs.forEach(job => {
    const tr = document.createElement("tr");
    tr.id = `batch-job-${job.job_id}`;

    // Find original filename from state or use job label
    let filename = job.original_filename;
    if (!filename || filename === job.video_id) {
      const matchedFile = state.batchFiles.find(f => f.videoId === job.video_id);
      filename = matchedFile ? matchedFile.file.name : job.video_id;
    }

    const badge = makeBadge(job.status);
    let actions = "";
    if (job.status === "completed" && job.output_filename) {
      actions = `<a href="${API}/api/download/${job.output_filename}" class="btn-download" style="padding:6px 14px;font-size:12px" download>⬇ Download</a>`;
    } else if (job.status === "failed") {
      actions = `<span class="muted-text">${escapeHtml(job.error_message || "Failed")}</span>`;
    } else {
      actions = `<span class="muted-text">—</span>`;
    }

    tr.innerHTML = `
      <td style="max-width:320px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escapeHtml(filename)}">${escapeHtml(filename)}</td>
      <td>${badge.outerHTML}</td>
      <td>${actions}</td>
    `;
    batchTableBody.appendChild(tr);
  });
}

function updateBatchProgress(data) {
  const total = data.total_jobs || (data.jobs ? data.jobs.length : 0);
  const completed = data.completed_jobs || (data.jobs ? data.jobs.filter(j => j.status === "completed").length : 0);
  const failed    = data.failed_jobs    || (data.jobs ? data.jobs.filter(j => j.status === "failed").length : 0);
  const pct = total > 0 ? Math.round((completed + failed) / total * 100) : 0;
  batchProgressFill.style.width = `${pct}%`;
  batchProgressLabel.textContent = `${completed} of ${total} completed${failed > 0 ? ` · ${failed} failed` : ""}`;
}

function startBatchPolling(batchId) {
  if (state.pollingTimer) clearInterval(state.pollingTimer);

  state.pollingTimer = setInterval(async () => {
    try {
      const response = await fetch(`${API}/api/batch/${batchId}`);
      const data = await response.json();
      if (!response.ok) return;

      renderBatchTable(data.jobs || []);
      updateBatchProgress(data);
      checkBatchMergedResult(data);

      const stillRunning = (data.jobs || []).some(j => j.status === "pending" || j.status === "processing");
      if (!stillRunning) {
        clearInterval(state.pollingTimer);
        state.pollingTimer = null;
        checkBatchMergedResult(data);
        showToast(data.mode === "merge" ? "Merged video ready!" : "All batch jobs finished!", "success");
      }
    } catch (_) {
      // Network hiccup — keep polling
    }
  }, 3000);
}

// Download All ZIP
downloadZipBtn.addEventListener("click", () => {
  if (!state.currentBatchId) return;
  window.location.href = `${API}/api/batch/${state.currentBatchId}/zip`;
});

/* ================================================================
   5. REFERENCE VIDEO
   ================================================================ */

const refVideoFile     = document.getElementById("refVideoFile");
const refUploadStatus  = document.getElementById("refUploadStatus");
const styleProfileCard = document.getElementById("styleProfileCard");
const styleProfileGrid = document.getElementById("styleProfileGrid");
const applyReferenceToggle = document.getElementById("applyReferenceToggle");
const applyReferenceStatus = document.getElementById("applyReferenceStatus");

refVideoFile.addEventListener("change", async () => {
  const file = refVideoFile.files[0];
  if (!file) return;

  if (file.size > 200 * 1024 * 1024) {
    refUploadStatus.textContent = "File exceeds the 200 MB limit.";
    refVideoFile.value = "";
    return;
  }

  refUploadStatus.textContent = "Uploading and analyzing reference video...";
  styleProfileCard.style.display = "none";

  const formData = new FormData();
  formData.append("file", file);

  try {
    const response = await fetch(`${API}/api/reference/upload`, {
      method: "POST",
      body: formData
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Reference upload failed.");

    state.referenceId = data.reference_id;
    refUploadStatus.textContent = "Reference video analyzed!";
    renderStyleProfile(data.style_profile || {});
    styleProfileCard.style.display = "block";

    // Show toggle bar on Single Edit tab
    referenceToggleBar.style.display = "flex";
    showToast("Reference style profile ready!", "success");

  } catch (err) {
    refUploadStatus.textContent = `Error: ${err.message}`;
    showToast(err.message, "error");
  }
});

function renderStyleProfile(profile) {
  styleProfileGrid.innerHTML = "";

  const fields = [
    { label: "Pacing",          value: profile.pacing           || "—" },
    { label: "Color Tone",      value: profile.color_tone       || "—" },
    { label: "Mood",            value: profile.estimated_mood   || "—" },
    { label: "Avg Cut Duration",value: profile.avg_cut_duration != null ? `${Number(profile.avg_cut_duration).toFixed(2)} s` : "—" },
    { label: "Transitions",     value: Array.isArray(profile.primary_transitions) ? profile.primary_transitions.join(", ") : (profile.primary_transitions || "—") },
    { label: "Aspect Ratio",    value: profile.aspect_ratio     || "—" },
  ];

  if (profile.has_slow_motion != null)
    fields.push({ label: "Slow Motion", value: profile.has_slow_motion ? "Yes" : "No" });
  if (profile.has_fast_motion != null)
    fields.push({ label: "Fast Motion", value: profile.has_fast_motion ? "Yes" : "No" });

  fields.forEach(({ label, value }) => {
    const item = document.createElement("div");
    item.className = "style-profile-item";
    item.innerHTML = `<div class="style-profile-label">${label}</div><div class="style-profile-value">${escapeHtml(String(value))}</div>`;
    styleProfileGrid.appendChild(item);
  });
}

// Toggle: apply reference style to Single Edit
applyReferenceToggle.addEventListener("change", () => {
  state.useReference = applyReferenceToggle.checked;
  useReferenceToggle.checked = state.useReference;

  if (state.useReference) {
    applyReferenceStatus.textContent = `Reference style will be applied to Single Edit (ID: ${state.referenceId})`;
    referenceToggleInfo.textContent = `Reference style active (ID: ${state.referenceId})`;
    showToast("Reference style will be applied to Single Edit", "info");
  } else {
    applyReferenceStatus.textContent = "Reference style disabled.";
    referenceToggleInfo.textContent = "";
  }
});

/* ================================================================
   6. MUSIC LIBRARY
   ================================================================ */

const musicSearchQ       = document.getElementById("musicSearchQ");
const musicCategory      = document.getElementById("musicCategory");
const musicMood          = document.getElementById("musicMood");
const musicLanguage      = document.getElementById("musicLanguage");
const musicSearchBtn     = document.getElementById("musicSearchBtn");
const musicSearchStatus  = document.getElementById("musicSearchStatus");
const musicResultCount   = document.getElementById("musicResultCount");
const musicTableBody     = document.getElementById("musicTableBody");
const musicFile          = document.getElementById("musicFile");
const musicUploadMeta    = document.getElementById("musicUploadMeta");
const musicTitle         = document.getElementById("musicTitle");
const musicArtist        = document.getElementById("musicArtist");
const musicUploadCategory= document.getElementById("musicUploadCategory");
const musicUploadMood    = document.getElementById("musicUploadMood");
const musicUploadBtn     = document.getElementById("musicUploadBtn");
const musicUploadStatus  = document.getElementById("musicUploadStatus");

musicSearchBtn.addEventListener("click", searchMusic);
musicSearchQ.addEventListener("keydown", e => { if (e.key === "Enter") searchMusic(); });

const fetchOnlineTamilBtn = document.getElementById("fetchOnlineTamilBtn");
if (fetchOnlineTamilBtn) {
  fetchOnlineTamilBtn.addEventListener("click", async () => {
    fetchOnlineTamilBtn.disabled = true;
    const oldText = fetchOnlineTamilBtn.textContent;
    fetchOnlineTamilBtn.textContent = "⏳ Fetching...";
    musicSearchStatus.textContent = "Searching Jamendo for online Tamil/World tracks...";
    try {
      const res = await fetch(`${API}/api/music/fetch-online`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category: "tamil" })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to fetch online music.");
      showToast(`Added: ${data.track?.title || "Online Track"}`, "success");
      musicSearchStatus.textContent = `Added: ${data.track?.title} (${data.track?.artist})`;
      musicCategory.value = "tamil";
      searchMusic();
    } catch (err) {
      showToast(err.message, "error");
      musicSearchStatus.textContent = `Error: ${err.message}`;
    } finally {
      fetchOnlineTamilBtn.disabled = false;
      fetchOnlineTamilBtn.textContent = oldText;
    }
  });
}

async function searchMusic() {
  const q        = musicSearchQ.value.trim();
  const category = musicCategory.value;
  const mood     = musicMood.value;
  const language = musicLanguage.value;

  musicSearchStatus.textContent = "Searching...";
  musicResultCount.textContent = "";

  const params = new URLSearchParams();
  if (q)        params.set("q", q);
  if (category) params.set("category", category);
  if (mood)     params.set("mood", mood);
  if (language) params.set("language", language);

  try {
    const response = await fetch(`${API}/api/music/search?${params}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Search failed");

    const tracks = Array.isArray(data) ? data : (data.tracks || data.results || []);
    musicSearchStatus.textContent = "";
    musicResultCount.textContent = `${tracks.length} TRACK${tracks.length !== 1 ? "S" : ""}`;
    renderMusicTable(tracks);

  } catch (err) {
    musicSearchStatus.textContent = `Error: ${err.message}`;
    showToast(err.message, "error");
  }
}

function renderMusicTable(tracks) {
  musicTableBody.innerHTML = "";
  if (tracks.length === 0) {
    musicTableBody.innerHTML = `<tr><td colspan="6" class="table-empty">No tracks found.</td></tr>`;
    return;
  }

  tracks.forEach(track => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(track.title || "—")}</td>
      <td>${escapeHtml(track.artist || "—")}</td>
      <td>${escapeHtml(track.category || "—")}</td>
      <td>${escapeHtml(track.mood || "—")}</td>
      <td>${escapeHtml(track.language || "—")}</td>
      <td>
        <button class="btn-small music-delete-btn" data-id="${escapeHtml(String(track.music_id || track.id || ""))}" style="background:transparent;border:1px solid var(--border);color:var(--muted);font-size:12px">✕ Delete</button>
      </td>
    `;
    musicTableBody.appendChild(tr);
  });

  musicTableBody.querySelectorAll(".music-delete-btn").forEach(btn => {
    btn.addEventListener("click", () => deleteMusic(btn.dataset.id, btn));
  });
}

async function deleteMusic(musicId, btn) {
  if (!musicId) return;
  if (!confirm("Delete this track?")) return;

  btn.disabled = true;
  btn.textContent = "Deleting...";

  try {
    const response = await fetch(`${API}/api/music/${musicId}`, { method: "DELETE" });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || "Delete failed");
    }
    btn.closest("tr").remove();
    showToast("Track deleted.", "success");
    // Refresh count
    const remaining = musicTableBody.querySelectorAll("tr:not(.table-empty)").length;
    musicResultCount.textContent = `${remaining} TRACK${remaining !== 1 ? "S" : ""}`;
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "✕ Delete";
    showToast(err.message, "error");
  }
}

// Show meta fields when file selected for upload
musicFile.addEventListener("change", () => {
  if (musicFile.files.length > 0) {
    musicUploadMeta.style.display = "grid";
    // Pre-fill title from filename
    const name = musicFile.files[0].name.replace(/\.[^/.]+$/, "");
    musicTitle.value = musicTitle.value || name;
  } else {
    musicUploadMeta.style.display = "none";
  }
});

musicUploadBtn.addEventListener("click", async () => {
  const file = musicFile.files[0];
  if (!file) {
    showToast("Select a music file first.", "warning");
    return;
  }

  musicUploadStatus.textContent = "Uploading...";
  musicUploadBtn.disabled = true;

  const formData = new FormData();
  formData.append("file", file);
  formData.append("title", musicTitle.value.trim() || file.name);
  formData.append("artist", musicArtist.value.trim() || "Unknown");
  formData.append("category", musicUploadCategory.value);
  formData.append("mood", musicUploadMood.value);

  try {
    const response = await fetch(`${API}/api/music/upload`, {
      method: "POST",
      body: formData
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Music upload failed");

    musicUploadStatus.textContent = "Track uploaded successfully!";
    musicFile.value = "";
    musicTitle.value = "";
    musicArtist.value = "";
    musicUploadMeta.style.display = "none";
    showToast("Track uploaded!", "success");

  } catch (err) {
    musicUploadStatus.textContent = `Error: ${err.message}`;
    showToast(err.message, "error");
  } finally {
    musicUploadBtn.disabled = false;
  }
});

/* ================================================================
   7. UTILITIES
   ================================================================ */

function showToast(message, type = "info", duration = 4000) {
  const container = document.getElementById("toastContainer");
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  const icon = { info: "ℹ", success: "✓", error: "✕", warning: "⚠" }[type] || "ℹ";
  toast.innerHTML = `<span>${icon}</span><span>${escapeHtml(String(message))}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.animation = "toastOut 0.3s ease forwards";
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatDuration(seconds) {
  if (seconds == null || isNaN(seconds)) return "—";
  const s = Number(seconds);
  const m = Math.floor(s / 60);
  const rem = (s % 60).toFixed(1);
  return m > 0 ? `${m}m ${rem}s` : `${rem}s`;
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function makeBadge(status) {
  const span = document.createElement("span");
  span.className = `status-badge ${status}`;
  const labels = {
    waiting: "Waiting",
    uploading: "Uploading…",
    done: "✓ Done",
    failed: "✕ Failed",
    pending: "Pending",
    processing: "Processing",
    completed: "✓ Done",
  };
  span.textContent = labels[status] || status;
  return span;
}
