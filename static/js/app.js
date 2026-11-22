/* Stem Separator — Frontend Controller */

(function () {
    "use strict";

    const state = {
        system: null,
        selectedFile: null,
        activeJobId: null,
        pollTimer: null,
        isProcessing: false,
    };

    const els = {
        deviceDot: document.getElementById("deviceDot"),
        deviceBadgeText: document.getElementById("deviceBadgeText"),
        maxUploadLabel: document.getElementById("maxUploadLabel"),
        dropzone: document.getElementById("dropzone"),
        dropzoneLabel: document.getElementById("dropzoneLabel"),
        dropzonePrimaryText: document.getElementById("dropzonePrimaryText"),
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
    const STAGE_ORDER = ["preparing", "downloading_model", "separating", "exporting"];

    const STAGE_COPY = {
        queued: {
            badge: "Queued",
            title: "Waiting in queue…",
            message: "Your file is uploaded and waiting for the local processor.",
        },
        preparing: {
            badge: "Step 1 of 4",
            title: "Preparing audio…",
            message: "Checking audio format, sample rate, and channel layout.",
        },
        downloading_model: {
            badge: "Step 2 of 4",
            title: "Downloading & loading AI model…",
            message: "First-time model download in progress. Once cached, future runs skip this download.",
        },
        separating: {
            badge: "Step 3 of 4",
            title: "Separating tracks with AI…",
            message: "Isolating your selected tracks locally. This typically takes 30 seconds to a few minutes.",
        },
        exporting: {
            badge: "Step 4 of 4",
            title: "Exporting audio files & ZIP package…",
            message: "Encoding your requested tracks and building the download archive.",
        },
    };

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

        const explicitId = els.modelSelect ? els.modelSelect.value : "auto";
        if (explicitId !== "auto") {
            const radio = document.querySelector(`input[name="mode"][value="${model.mode}"]`);
            if (radio) {
                radio.checked = true;
            }
        }

        const activeMode = getSelectedMode();
        document.querySelectorAll(".preset-card").forEach((card) => {
            card.classList.toggle("selected", card.dataset.mode === activeMode);
        });

        els.activeModelTag.textContent = `Model: ${model.friendly_name}`;

        const preset = (state.system.presets || []).find((p) => p.id === model.mode);
        const defaultTracks = preset ? preset.default_tracks : model.outputs;
        const previousTracks = getSelectedTracks();

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

        els.advancedModelSummary.innerHTML = `<strong>${model.friendly_name}:</strong> ${model.summary}`;
        els.advancedModelMeta.textContent =
            `Architecture: ${model.architecture} • Size: ${model.download_size_mb.toFixed(1)} MB • ` +
            `Status: ${model.installed ? "Cached locally" : "Will download on first run"} • License: ${model.license_info}`;

        updateStartButtonState();
    }

    function updateStartButtonState() {
        if (state.isProcessing) {
            els.startBtn.disabled = true;
            els.startBtnText.textContent = "Separating audio…";
            return;
        }
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

    function handleFileSelection(file) {
        hideError();
        if (!file) {
            state.selectedFile = null;
            els.selectedFileBar.hidden = true;
            updateStartButtonState();
            return;
        }

        const dotIdx = file.name.lastIndexOf(".");
        const ext = dotIdx >= 0 ? file.name.substring(dotIdx).toLowerCase() : "";
        if (!ALLOWED_EXTENSIONS.includes(ext)) {
            state.selectedFile = null;
            els.selectedFileBar.hidden = true;
            showError({
                title: "Unsupported file format",
                message: `The file '${file.name}' is not a supported audio format.`,
                suggestion: "Please select an MP3, WAV, FLAC, M4A, AAC, OGG, or OPUS audio file.",
            });
            updateStartButtonState();
            return;
        }

        if (file.size === 0) {
            state.selectedFile = null;
            els.selectedFileBar.hidden = true;
            showError({
                title: "The selected file is empty",
                message: `'${file.name}' contains 0 bytes of audio data.`,
                suggestion: "Please choose a valid, non-empty audio file.",
            });
            updateStartButtonState();
            return;
        }

        const maxMb = (state.system && state.system.max_upload_mb) || 250;
        if (file.size > maxMb * 1024 * 1024) {
            state.selectedFile = null;
            els.selectedFileBar.hidden = true;
            showError({
                title: "Audio file is too large",
                message: `'${file.name}' (${formatFileSize(file.size)}) exceeds the ${maxMb} MB limit.`,
                suggestion: `Choose an audio file under ${maxMb} MB or compress it to FLAC or MP3.`,
            });
            updateStartButtonState();
            return;
        }

        state.selectedFile = file;
        els.selectedFileName.textContent = file.name;
        els.selectedFileSize.textContent = formatFileSize(file.size);
        els.selectedFileBar.hidden = false;
        updateStartButtonState();
    }

    function showError(errObj) {
        els.errorTitle.textContent = errObj.title || "Unable to process audio";
        els.errorMessage.textContent = errObj.message || "Something went wrong during separation.";
        els.errorSuggestion.textContent =
            errObj.suggestion || "Please verify your audio file or switch to the fast default model.";
        els.errorPanel.hidden = false;
    }

    function hideError() {
        els.errorPanel.hidden = true;
    }

    function updateStageUI(job) {
        els.statusPanel.hidden = false;
        const stage = job.stage || "queued";
        const copy = STAGE_COPY[stage] || STAGE_COPY.separating;

        els.statusBadge.textContent = copy.badge;
        els.statusDeviceBadge.textContent = `Device: ${(job.device_used || "cpu").toUpperCase()}`;
        els.statusTitle.textContent = copy.title;
        els.statusMessage.textContent = copy.message;

        const currentIdx = STAGE_ORDER.indexOf(stage);
        els.stageSteps.querySelectorAll(".stage-step").forEach((li) => {
            const stepStage = li.dataset.stage;
            const stepIdx = STAGE_ORDER.indexOf(stepStage);
            li.classList.remove("active", "done");
            if (currentIdx >= 0) {
                if (stepIdx < currentIdx) {
                    li.classList.add("done");
                } else if (stepIdx === currentIdx) {
                    li.classList.add("active");
                }
            }
        });

        // Only show percentage when a reliable progress_percent number exists
        if (typeof job.progress_percent === "number" && job.progress_percent >= 0) {
            els.progressBarFill.classList.remove("indeterminate");
            els.progressBarFill.style.width = `${Math.min(100, Math.max(5, job.progress_percent))}%`;
            els.progressTrack.setAttribute("aria-valuenow", String(job.progress_percent));
        } else {
            els.progressBarFill.classList.add("indeterminate");
            els.progressBarFill.style.width = "40%";
            els.progressTrack.removeAttribute("aria-valuenow");
        }
    }

    function renderResults(job) {
        els.statusPanel.hidden = true;
        els.errorPanel.hidden = true;
        els.resultsPanel.hidden = false;

        const metaParts = [
            `File: ${job.input_filename || "audio"}`,
            `Model: ${job.model_name || job.model_id}`,
            `Device: ${(job.device_used || "cpu").toUpperCase()}`,
            `Format: ${job.output_format || "WAV"}`,
        ];
        els.resultsMeta.textContent = metaParts.join(" • ");

        if (job.zip_url) {
            els.downloadZipBtn.href = job.zip_url;
            els.downloadZipBtn.setAttribute("download", `stem_separator_${job.job_id}.zip`);
            els.downloadZipBtn.hidden = false;
        } else {
            els.downloadZipBtn.hidden = true;
        }

        els.resultsTracksList.innerHTML = "";
        (job.tracks || []).forEach((track) => {
            const card = document.createElement("div");
            card.className = "track-result-card";

            const info = document.createElement("div");
            info.className = "track-result-info";

            const iconSpan = document.createElement("span");
            iconSpan.className = "track-result-icon";
            iconSpan.setAttribute("aria-hidden", "true");
            iconSpan.textContent = track.icon || "🎵";

            const textWrap = document.createElement("div");
            const titleDiv = document.createElement("div");
            titleDiv.className = "track-result-title";
            titleDiv.textContent = track.label || track.track_id;

            const metaDiv = document.createElement("div");
            metaDiv.className = "track-result-meta";
            metaDiv.textContent = `${track.format || job.output_format} • ${formatFileSize(track.size_bytes)}`;

            textWrap.appendChild(titleDiv);
            textWrap.appendChild(metaDiv);
            info.appendChild(iconSpan);
            info.appendChild(textWrap);

            const playerWrap = document.createElement("div");
            playerWrap.className = "track-result-player";
            const audio = document.createElement("audio");
            audio.controls = true;
            audio.preload = "metadata";
            audio.src = track.url;
            audio.setAttribute("aria-label", `Preview ${track.label || track.track_id}`);
            playerWrap.appendChild(audio);

            const dlBtn = document.createElement("a");
            dlBtn.className = "btn-secondary btn-sm";
            dlBtn.href = track.url;
            dlBtn.setAttribute("download", track.filename);
            dlBtn.setAttribute("aria-label", `Download ${track.label || track.track_id}`);
            dlBtn.innerHTML = `<span aria-hidden="true">⬇️</span><span>Download</span>`;

            card.appendChild(info);
            card.appendChild(playerWrap);
            card.appendChild(dlBtn);

            els.resultsTracksList.appendChild(card);
        });

        // Refresh system info so model cached state updates
        loadSystemInfo();
    }

    function stopPolling() {
        if (state.pollTimer) {
            clearTimeout(state.pollTimer);
            state.pollTimer = null;
        }
    }

    async function pollJobStatus(jobId) {
        stopPolling();
        try {
            const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`);
            const data = await response.json();

            if (!response.ok) {
                state.isProcessing = false;
                els.statusPanel.hidden = true;
                updateStartButtonState();
                const err = (data && data.error) || {
                    title: "Could not check job status",
                    message: "The separation job could not be found on the server.",
                    suggestion: "Please try starting the separation again.",
                };
                showError(err);
                return;
            }

            if (data.status === "completed") {
                state.isProcessing = false;
                updateStartButtonState();
                renderResults(data);
                return;
            }

            if (data.status === "failed") {
                state.isProcessing = false;
                els.statusPanel.hidden = true;
                updateStartButtonState();
                showError(
                    data.error || {
                        title: "Separation failed",
                        message: "The separation job did not complete.",
                        suggestion: "Try again or select the fast CPU model.",
                    }
                );
                return;
            }

            updateStageUI(data);
            state.pollTimer = setTimeout(() => pollJobStatus(jobId), 800);
        } catch (err) {
            console.error("Polling error:", err);
            state.pollTimer = setTimeout(() => pollJobStatus(jobId), 1500);
        }
    }

    async function submitSeparationForm(event) {
        event.preventDefault();
        if (state.isProcessing) return;

        hideError();
        if (!state.selectedFile) {
            showError({
                title: "No audio file selected",
                message: "Please choose or drag & drop an audio file first.",
                suggestion: "Click the upload box in Step 1 to pick an MP3, WAV, or FLAC file.",
            });
            return;
        }

        const selectedTracks = getSelectedTracks();
        if (selectedTracks.length === 0) {
            showError({
                title: "No tracks selected",
                message: "Please check at least one output track to extract.",
                suggestion: "Select Vocals, Music, or another available instrument track in Step 2.",
            });
            return;
        }

        const formData = new FormData();
        formData.append("file", state.selectedFile);
        formData.append("mode", getSelectedMode());
        formData.append("tracks", selectedTracks.join(","));
        formData.append("output_format", els.outputFormatSelect.value);
        formData.append("model_id", els.modelSelect ? els.modelSelect.value : "auto");
        formData.append("device_preference", els.deviceSelect ? els.deviceSelect.value : "auto");

        state.isProcessing = true;
        updateStartButtonState();
        els.resultsPanel.hidden = true;
        updateStageUI({ stage: "queued", device_used: state.system ? state.system.device : "cpu" });

        try {
            const response = await fetch("/api/jobs", {
                method: "POST",
                body: formData,
            });
            const data = await response.json();

            if (!response.ok) {
                state.isProcessing = false;
                els.statusPanel.hidden = true;
                updateStartButtonState();
                const err = (data && data.error) || {
                    title: "Upload rejected",
                    message: "The server could not start the separation job.",
                    suggestion: "Check the file format and try again.",
                };
                showError(err);
                return;
            }

            state.activeJobId = data.job_id;
            updateStageUI(data);
            pollJobStatus(data.job_id);
        } catch (err) {
            console.error("Submission error:", err);
            state.isProcessing = false;
            els.statusPanel.hidden = true;
            updateStartButtonState();
            showError({
                title: "Could not reach the server",
                message: "The upload request failed due to a network error.",
                suggestion: "Check that the Stem Separator server is running and try again.",
            });
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

            syncTracksAndNotice(true);
        } catch (err) {
            console.error("Failed to load /api/system:", err);
            els.deviceBadgeText.textContent = "Local Engine Active";
        }
    }

    function attachEvents() {
        // File input change
        els.audioFileInput.addEventListener("change", (e) => {
            const file = e.target.files && e.target.files[0];
            handleFileSelection(file || null);
        });

        // Change file button
        els.changeFileBtn.addEventListener("click", () => {
            els.audioFileInput.value = "";
            els.audioFileInput.click();
        });

        // Drag and drop on dropzone
        ["dragenter", "dragover"].forEach((evtName) => {
            els.dropzone.addEventListener(evtName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                els.dropzone.classList.add("drag-over");
            });
        });

        ["dragleave", "drop"].forEach((evtName) => {
            els.dropzone.addEventListener(evtName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                els.dropzone.classList.remove("drag-over");
            });
        });

        els.dropzone.addEventListener("drop", (e) => {
            const files = e.dataTransfer && e.dataTransfer.files;
            if (files && files.length > 0) {
                handleFileSelection(files[0]);
            }
        });

        // Preset radio changes
        document.querySelectorAll('input[name="mode"]').forEach((radio) => {
            radio.addEventListener("change", () => {
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

        // Advanced dropdowns
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

        // Form submission
        els.separationForm.addEventListener("submit", submitSeparationForm);

        // Error recovery buttons
        els.retryBtn.addEventListener("click", () => {
            hideError();
            if (state.selectedFile) {
                els.separationForm.requestSubmit();
            } else {
                els.audioFileInput.click();
            }
        });

        els.useFastModelBtn.addEventListener("click", () => {
            hideError();
            const vocalsRadio = document.querySelector('input[name="mode"][value="vocals_music"]');
            if (vocalsRadio) vocalsRadio.checked = true;
            if (els.modelSelect) els.modelSelect.value = "vocals_music_fast";
            if (els.deviceSelect) els.deviceSelect.value = "cpu";
            syncTracksAndNotice(false);
        });

        // Reset button in results
        els.resetJobBtn.addEventListener("click", () => {
            stopPolling();
            els.resultsPanel.hidden = true;
            els.statusPanel.hidden = true;
            hideError();
            els.audioFileInput.value = "";
            handleFileSelection(null);
            window.scrollTo({ top: 0, behavior: "smooth" });
        });
    }

    document.addEventListener("DOMContentLoaded", () => {
        attachEvents();
        loadSystemInfo();
    });
})();
