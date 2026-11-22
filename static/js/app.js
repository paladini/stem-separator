/* Stem Separator — Frontend Controller */

(function () {
    "use strict";

    // Application state populated from GET /api/system
    const state = {
        system: null,
        selectedFile: null,
        activeJobId: null,
        pollTimer: null,
    };

    // DOM references
    const els = {
        deviceDot: document.getElementById("deviceDot"),
        deviceBadgeText: document.getElementById("deviceBadgeText"),
        maxUploadLabel: document.getElementById("maxUploadLabel"),
        dropzone: document.getElementById("dropzone"),
        dropzoneLabel: document.getElementById("dropzoneLabel"),
        audioFileInput: document.getElementById("audioFileInput"),
        selectedFileBar: document.getElementById("selectedFileBar"),
        selectedFileName: document.getElementById("selectedFileName"),
        selectedFileSize: document.getElementById("selectedFileSize"),
        changeFileBtn: document.getElementById("changeFileBtn"),
        presetGrid: document.getElementById("presetGrid"),
        tracksGrid: document.getElementById("tracksGrid"),
        activeModelTag: document.getElementById("activeModelTag"),
        outputFormatSelect: document.getElementById("outputFormatSelect"),
        modelNoticeBox: document.getElementById("modelNoticeBox"),
        modelNoticeText: document.getElementById("modelNoticeText"),
        advancedPanel: document.getElementById("advancedPanel"),
        modelSelect: document.getElementById("modelSelect"),
        deviceSelect: document.getElementById("deviceSelect"),
        advancedModelSummary: document.getElementById("advancedModelSummary"),
        advancedModelMeta: document.getElementById("advancedModelMeta"),
        separationForm: document.getElementById("separationForm"),
        startBtn: document.getElementById("startBtn"),
        startBtnText: document.getElementById("startBtnText"),
        statusPanel: document.getElementById("statusPanel"),
        statusBadge: document.getElementById("statusBadge"),
        statusDeviceBadge: document.getElementById("statusDeviceBadge"),
        statusTitle: document.getElementById("statusTitle"),
        statusMessage: document.getElementById("statusMessage"),
        stageSteps: document.getElementById("stageSteps"),
        progressTrack: document.getElementById("progressTrack"),
        progressBarFill: document.getElementById("progressBarFill"),
        errorPanel: document.getElementById("errorPanel"),
        errorTitle: document.getElementById("errorTitle"),
        errorMessage: document.getElementById("errorMessage"),
        errorSuggestion: document.getElementById("errorSuggestion"),
        retryBtn: document.getElementById("retryBtn"),
        useFastModelBtn: document.getElementById("useFastModelBtn"),
        resultsPanel: document.getElementById("resultsPanel"),
        resultsMeta: document.getElementById("resultsMeta"),
        downloadZipBtn: document.getElementById("downloadZipBtn"),
        resetJobBtn: document.getElementById("resetJobBtn"),
        resultsTracksList: document.getElementById("resultsTracksList"),
    };

    const ALLOWED_EXTENSIONS = [".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus"];

    function formatFileSize(bytes) {
        if (!bytes || bytes <= 0) return "0 KB";
        const units = ["Bytes", "KB", "MB", "GB"];
        const idx = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
        return (bytes / Math.pow(1024, idx)).toFixed(idx === 0 ? 0 : 1) + " " + units[idx];
    }

    function getSelectedMode() {
        const checked = document.querySelector('input[name="mode"]:checked');
        return checked ? checked.value : "vocals_music";
    }

    function getActiveModelSpec() {
        if (!state.system || !state.system.models) {
            return null;
        }
        const explicitId = els.modelSelect ? els.modelSelect.value : "auto";
        if (explicitId && explicitId !== "auto") {
            return state.system.models.find((m) => m.id === explicitId) || state.system.models[0];
        }
        const mode = getSelectedMode();
        const preset = (state.system.presets || []).find((p) => p.id === mode);
        const targetId = preset ? preset.default_model_id : "vocals_music_fast";
        return state.system.models.find((m) => m.id === targetId) || state.system.models[0];
    }

    function getSelectedTracks() {
        const boxes = els.tracksGrid.querySelectorAll('input[name="tracks"]:not(:disabled)');
        return Array.from(boxes)
            .filter((cb) => cb.checked)
            .map((cb) => cb.value);
    }

    function syncTracksAndNotice(preserveTrackSelection) {
        const model = getActiveModelSpec();
        if (!model) return;

        // Sync preset highlight if an explicit model was chosen in Advanced
        const explicitId = els.modelSelect ? els.modelSelect.value : "auto";
        if (explicitId !== "auto") {
            const radio = document.querySelector(`input[name="mode"][value="${model.mode}"]`);
            if (radio) {
                radio.checked = true;
            }
        }

        // Highlight active preset card
        const activeMode = getSelectedMode();
        document.querySelectorAll(".preset-card").forEach((card) => {
            card.classList.toggle("selected", card.dataset.mode === activeMode);
        });

        // Update model tag
        els.activeModelTag.textContent = `Model: ${model.friendly_name}`;

        // Determine default tracks for the active preset/model
        const preset = (state.system.presets || []).find((p) => p.id === model.mode);
        const defaultTracks = preset ? preset.default_tracks : model.outputs;
        const previousTracks = getSelectedTracks();

        // Show only tracks that the active model can produce
        const trackChips = els.tracksGrid.querySelectorAll(".track-chip");
        trackChips.forEach((chip) => {
            const trackId = chip.dataset.track;
            const checkbox = chip.querySelector('input[type="checkbox"]');
            const supported = model.outputs.includes(trackId);
            if (supported) {
                chip.hidden = false;
                checkbox.disabled = false;
                if (!preserveTrackSelection) {
                    checkbox.checked = defaultTracks.includes(trackId);
                } else if (previousTracks.length === 0) {
                    checkbox.checked = defaultTracks.includes(trackId);
                }
            } else {
                chip.hidden = true;
                checkbox.checked = false;
                checkbox.disabled = true;
            }
            chip.classList.toggle("checked", checkbox.checked && !checkbox.disabled);
        });

        // Ensure at least one valid track is checked if none survived
        if (getSelectedTracks().length === 0 && !preserveTrackSelection) {
            trackChips.forEach((chip) => {
                const trackId = chip.dataset.track;
                const checkbox = chip.querySelector('input[type="checkbox"]');
                if (!checkbox.disabled && defaultTracks.includes(trackId)) {
                    checkbox.checked = true;
                    chip.classList.add("checked");
                }
            });
        }

        // Update model notice & device description
        const devicePref = els.deviceSelect ? els.deviceSelect.value : "auto";
        const cudaAvailable = state.system && state.system.cuda_available;
        let deviceLabel = "CPU";
        if (devicePref === "cuda") {
            deviceLabel = cudaAvailable ? `NVIDIA GPU (${state.system.device_name})` : "NVIDIA GPU (Requested)";
        } else if (devicePref === "auto" && cudaAvailable) {
            deviceLabel = `NVIDIA GPU (${state.system.device_name})`;
        }

        if (model.installed) {
            els.modelNoticeBox.classList.remove("warn");
            els.modelNoticeText.innerHTML =
                `<strong>Model cached and ready on ${deviceLabel}.</strong> ` +
                `${model.friendly_name} is already stored locally—no download needed.`;
        } else {
            const isLarge = model.download_size_mb > 250;
            els.modelNoticeBox.classList.toggle("warn", isLarge);
            els.modelNoticeText.innerHTML =
                `<strong>First-time download (~${model.download_size_mb.toFixed(1)} MB) on ${deviceLabel}.</strong> ` +
                `${model.friendly_name} will be downloaded once and saved permanently in the model volume.`;
        }

        // Update advanced details card
        els.advancedModelSummary.innerHTML = `<strong>${model.friendly_name}:</strong> ${model.summary}`;
        els.advancedModelMeta.textContent =
            `Architecture: ${model.architecture} • Size: ${model.download_size_mb.toFixed(1)} MB • ` +
            `Status: ${model.installed ? "Cached locally" : "Will download on first run"} • License: ${model.license_info}`;

        updateStartButtonState();
    }

    function updateStartButtonState() {
        const selectedTracks = getSelectedTracks();
        if (!state.selectedFile) {
            els.startBtn.disabled = true;
            els.startBtnText.textContent = "Select an audio file to begin";
            return;
        }
        if (selectedTracks.length === 0) {
            els.startBtn.disabled = true;
            els.startBtnText.textContent = "Select at least one track to separate";
            return;
        }
        els.startBtn.disabled = false;
        if (selectedTracks.length === 1) {
            const trackDef = state.system && state.system.tracks && state.system.tracks[selectedTracks[0]];
            const label = trackDef ? trackDef.label : selectedTracks[0];
            els.startBtnText.textContent = `Start Separation (${label})`;
        } else {
            els.startBtnText.textContent = `Start Separation (${selectedTracks.length} Tracks)`;
        }
    }

    async function loadSystemInfo() {
        try {
            const response = await fetch("/api/system");
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            state.system = data;

            if (els.maxUploadLabel && data.max_upload_mb) {
                els.maxUploadLabel.textContent = String(data.max_upload_mb);
            }

            if (data.cuda_available) {
                els.deviceDot.classList.add("gpu");
                els.deviceBadgeText.textContent = `GPU Ready: ${data.device_name}`;
            } else {
                els.deviceDot.classList.remove("gpu");
                els.deviceBadgeText.textContent = "Local Engine Ready (CPU)";
            }

            syncTracksAndNotice(false);
        } catch (err) {
            console.error("Failed to load /api/system:", err);
            els.deviceBadgeText.textContent = "Local Engine Active";
        }
    }

    function attachEvents() {
        // Preset radio changes
        document.querySelectorAll('input[name="mode"]').forEach((radio) => {
            radio.addEventListener("change", () => {
                // When user clicks a top-level preset, reset explicit model override to "auto"
                if (els.modelSelect) {
                    els.modelSelect.value = "auto";
                }
                syncTracksAndNotice(false);
            });
        });

        // Track checkboxes
        els.tracksGrid.querySelectorAll('input[name="tracks"]').forEach((cb) => {
            cb.addEventListener("change", () => {
                const chip = cb.closest(".track-chip");
                if (chip) {
                    chip.classList.toggle("checked", cb.checked && !cb.disabled);
                }
                updateStartButtonState();
            });
        });

        // Advanced model & device dropdowns
        if (els.modelSelect) {
            els.modelSelect.addEventListener("change", () => {
                syncTracksAndNotice(false);
            });
        }
        if (els.deviceSelect) {
            els.deviceSelect.addEventListener("change", () => {
                syncTracksAndNotice(true);
            });
        }
    }

    document.addEventListener("DOMContentLoaded", () => {
        attachEvents();
        loadSystemInfo();
    });
})();
