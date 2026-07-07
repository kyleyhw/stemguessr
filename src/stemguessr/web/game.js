// game.js — StemGuessr browser-side game logic.
//
// Reads manifest.json (Phase 5 schema v1) from the same directory, then
// runs the round-by-round guessing loop:
//   round k reveals stems[0..k]; player guesses; correct or no-guesses-left
//   ends the track and reveals the answer.
//
// All state is in the `state` object below; the rest of the file is pure
// functions reading and mutating it. There is no framework, no bundler,
// and no build step.

// ============================================================
// Application state
// ============================================================

const state = {
    manifest: null,        // parsed manifest.json
    trackOrder: [],        // shuffled clone of manifest.tracks
    currentIndex: 0,       // index into trackOrder
    round: 0,              // 0..manifest.stems.length-1; revealed stems = stems[0..round]
    guesses: [],           // [{text, correct, skipped}]
    isPlaying: false,
    audioCtx: null,        // AudioContext (lazy: created on first play)
    masterGain: null,      // GainNode all sources connect through; controls volume
    volume: 0.1,           // 0..0.25 — initial volume kept low; full mix is hot
    buffersByUrl: new Map(),  // url -> AudioBuffer
    activeSources: [],     // currently-playing AudioBufferSourceNodes
    playStartContextTime: 0,  // audioCtx.currentTime - pausedOffset (so elapsed = real position)
    pausedOffset: 0,       // seconds into the clip; the position play() will start from
    rafId: null,           // requestAnimationFrame id for waveform redraw loop
    knownTrackIds: new Set(),  // ids of tracks already in trackOrder
    pollTimer: null,       // setTimeout handle for the next manifest poll
    // Pre-computed per-pixel min/max for the *currently active* stem mix —
    // recomputed at every round advance (and on initial track load), then
    // referenced by the draw routines on every animation frame. Caching it
    // once per round avoids re-summing 4-6 stems × millions of samples on
    // every redraw.
    cachedWaveform: null,  // { min: Float32Array, max: Float32Array, peak: number }
};

// Manifest-polling cadence while ingest is still in progress (manifest.complete=false).
// 2 s is fast enough that newly-separated tracks become playable promptly without
// hammering the local server.
const POLL_INTERVAL_MS = 2000;

// ============================================================
// DOM cache
// ============================================================

const els = {
    status:         document.getElementById('status-line'),
    canvas:         document.getElementById('waveform'),
    playBtn:        document.getElementById('play-btn'),
    roundLabel:     document.getElementById('round-label'),
    volumeSlider:   document.getElementById('volume-slider'),
    guessInput:     document.getElementById('guess-input'),
    guessForm:      document.getElementById('guess-form'),
    skipBtn:        document.getElementById('skip-btn'),
    guessList:      document.getElementById('guess-list'),
    revealInfo:     document.getElementById('reveal-info'),
    revealTitle:    document.getElementById('reveal-title'),
    revealArtists:  document.getElementById('reveal-artists'),
    revealOutcome:  document.getElementById('reveal-outcome'),
    nextBtn:        document.getElementById('next-track-btn'),
    playerCover:    document.getElementById('player-cover'),
    waveformCanvas: document.getElementById('waveform'),
    // Ingest form (visible only when there is no manifest yet, or the
    // manifest is finalised but empty).
    ingestPrompt:   document.getElementById('ingest-prompt'),
    ingestForm:     document.getElementById('ingest-form'),
    playlistInput:  document.getElementById('playlist-url-input'),
    stemsSelect:    document.getElementById('stems-select'),
    limitInput:     document.getElementById('limit-input'),
    ingestSubmit:   document.getElementById('ingest-submit'),
    playerSection:  document.getElementById('player-section'),
    guessSection:   document.getElementById('guess-section'),
};

// ============================================================
// Bootstrap
// ============================================================

async function init() {
    wireEvents();

    // Probe for an existing manifest. We use it only to pre-fill the form
    // and surface a "you have N tracks cached" hint — we do NOT populate
    // trackOrder or load any audio yet. That happens once the user has
    // committed to a playlist via the form (either resuming the cached one
    // or pasting a fresh URL).
    state.manifest = await peekManifest();
    showIngestPrompt();
}

async function peekManifest() {
    try {
        const response = await fetch('manifest.json', { cache: 'no-cache' });
        if (!response.ok) return null;
        const m = await response.json();
        return m && m.version === 1 ? m : null;
    } catch {
        return null;
    }
}

function showIngestPrompt() {
    els.ingestPrompt.hidden = false;
    els.playerSection.hidden = true;
    els.guessSection.hidden = true;
    clearRevealView();

    if (state.manifest && state.manifest.tracks.length > 0) {
        // Pre-fill with the cached playlist's URL so the user can press
        // submit to resume in one click.
        els.playlistInput.value = state.manifest.source_playlist.url;
        const n = state.manifest.tracks.length;
        const expected = state.manifest.expected_tracks ?? n;
        const cacheState = state.manifest.complete
            ? 'cached locally'
            : `ingest in progress (${n}/${expected})`;
        els.status.textContent =
            `${n} track${n === 1 ? '' : 's'} ${cacheState}. ` +
            'Submit the same URL to resume, or paste a different one.';
    } else {
        els.playlistInput.value = '';
        els.status.textContent = 'Paste a public Spotify playlist URL to begin.';
    }
    els.playlistInput.focus();
}

// 22-char base-62. Mirrors stemguessr.spotify._PLAYLIST_ID_PATTERN.
const PLAYLIST_ID_RE = /[A-Za-z0-9]{22}/;

function extractPlaylistId(urlOrUri) {
    const s = (urlOrUri || '').trim();
    // Bare ID
    if (/^[A-Za-z0-9]{22}$/.test(s)) return s;
    // spotify:playlist:<id>
    let m = s.match(/^spotify:playlist:([A-Za-z0-9]{22})$/);
    if (m) return m[1];
    // URL form: .../playlist/<id>(?...)
    m = s.match(/playlist\/([A-Za-z0-9]{22})/);
    if (m) return m[1];
    return null;
}

function hideIngestPrompt() {
    els.ingestPrompt.hidden = true;
    els.playerSection.hidden = false;
    els.guessSection.hidden = false;
}

async function submitIngestForm(event) {
    event.preventDefault();
    const playlistUrl = els.playlistInput.value.trim();
    if (!playlistUrl) return;

    // Cache short-circuit: if the submitted URL resolves to the same
    // playlist ID as the manifest currently on disk, do not round-trip
    // to the server at all — just promote the cached manifest into the
    // playable state. This makes refresh-and-resume a one-click,
    // zero-network-cost operation.
    const submittedId = extractPlaylistId(playlistUrl);
    const cachedId = state.manifest && state.manifest.source_playlist
        ? state.manifest.source_playlist.spotify_id
        : null;
    if (
        submittedId
        && cachedId
        && submittedId === cachedId
        && state.manifest.tracks.length > 0
    ) {
        // Populate playable state from the cached manifest and start playing.
        const shuffled = shuffle([...state.manifest.tracks]);
        state.trackOrder = shuffled;
        state.knownTrackIds = new Set(shuffled.map((t) => t.id));
        state.currentIndex = 0;

        hideIngestPrompt();
        await loadCurrentTrack();
        // If the cached manifest reports the previous run was still
        // mid-ingest, resume polling so any tracks the server is still
        // working on stream in.
        if (!state.manifest.complete) {
            scheduleManifestPoll();
        }
        return;
    }

    // Different playlist (or no cache) — start a real ingest run.
    const nStems = parseInt(els.stemsSelect.value, 10);
    const limitRaw = els.limitInput.value.trim();
    const limit = limitRaw === '' ? null : parseInt(limitRaw, 10);

    els.ingestSubmit.disabled = true;
    els.status.textContent = 'Starting ingest…';

    let response;
    try {
        response = await fetch('/api/ingest', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                playlist_url: playlistUrl,
                n_stems: nStems,
                limit,
            }),
        });
    } catch (e) {
        els.status.textContent =
            `Could not reach the server: ${e.message}. ` +
            'Is `stemguessr serve` running?';
        els.ingestSubmit.disabled = false;
        return;
    }

    if (!response.ok) {
        const body = await response.text();
        els.status.textContent = `Ingest rejected (HTTP ${response.status}): ${body}`;
        els.ingestSubmit.disabled = false;
        return;
    }

    // Reset client state so the new playlist is picked up cleanly on the
    // next poll (and the Fisher–Yates shuffle re-runs against the new tracks).
    state.manifest = null;
    state.trackOrder = [];
    state.knownTrackIds = new Set();
    state.currentIndex = 0;

    hideIngestPrompt();
    els.status.textContent = 'Ingest started — waiting for first track…';
    els.playBtn.disabled = true;
    els.guessInput.disabled = true;
    els.skipBtn.disabled = true;
    els.ingestSubmit.disabled = false;

    scheduleManifestPoll();
}

/**
 * Fetch manifest.json, validate, merge into state.
 * Returns false on a fatal error (status set, caller should bail).
 */
async function fetchAndUpdateManifest(opts = {}) {
    const silent = !!opts.silent;
    let manifest;
    try {
        const response = await fetch('manifest.json', { cache: 'no-cache' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        manifest = await response.json();
    } catch (e) {
        if (!silent) {
            els.status.textContent =
                `Could not load manifest.json — ${e.message}.`;
        }
        return false;
    }
    if (manifest.version !== 1) {
        els.status.textContent =
            `Unsupported manifest version: ${manifest.version}. Frontend supports v1.`;
        return false;
    }

    const isFirstFetch = state.manifest === null;
    state.manifest = manifest;

    // "No current playable track" — currentIndex is at or past the end of
    // the (possibly empty) trackOrder. Captured BEFORE we merge new tracks
    // so we can detect the transition into "has playable track".
    const wasWithoutPlayable =
        state.currentIndex >= state.trackOrder.length;

    const newTracks = manifest.tracks.filter(
        (t) => !state.knownTrackIds.has(t.id),
    );

    if (isFirstFetch && manifest.tracks.length > 0) {
        // Initial population — shuffle once.
        const shuffled = shuffle([...manifest.tracks]);
        state.trackOrder = shuffled;
        for (const t of shuffled) state.knownTrackIds.add(t.id);
    } else if (newTracks.length > 0) {
        // Incremental — append in arrival (ingestion) order without
        // disturbing the existing shuffle of already-known tracks. The
        // backend shuffles its processing order, so arrivals are already
        // random rather than playlist-ordered.
        state.trackOrder.push(...newTracks);
        for (const t of newTracks) state.knownTrackIds.add(t.id);
    }

    updateProgressLine();

    // Transition: "no playable track" → "has one". Covers three cases:
    //   1. initial fetch with tracks already present
    //   2. polling brings in the first track after an empty-manifest start
    //   3. user finished every track, then polling appends a new one
    if (wasWithoutPlayable && state.currentIndex < state.trackOrder.length) {
        await loadCurrentTrack();
    }

    return true;
}

function updateProgressLine() {
    if (!state.manifest) return;
    const total = state.trackOrder.length;
    const trackText =
        total > 0 && state.currentIndex < total
            ? `Track ${state.currentIndex + 1}/${total}`
            : (state.manifest.complete ? '🎉 Playlist complete.' : 'Waiting…');
    if (state.manifest.complete) {
        els.status.textContent =
            `${trackText} · ${state.manifest.stems.length} stems · ${state.manifest.model}`;
    } else {
        const ready = state.manifest.tracks.length;
        const expected = state.manifest.expected_tracks ?? '?';
        els.status.textContent = `${trackText} · ingesting ${ready}/${expected}`;
    }
}

function scheduleManifestPoll() {
    if (state.pollTimer !== null) return;
    state.pollTimer = setTimeout(async () => {
        state.pollTimer = null;
        await fetchAndUpdateManifest();
        if (state.manifest && !state.manifest.complete) {
            scheduleManifestPoll();
        }
    }, POLL_INTERVAL_MS);
}

function wireEvents() {
    els.playBtn.addEventListener('click', togglePlay);
    els.guessForm.addEventListener('submit', (e) => {
        e.preventDefault();
        submitGuess(els.guessInput.value);
    });
    els.skipBtn.addEventListener('click', skip);
    els.nextBtn.addEventListener('click', nextTrack);
    els.ingestForm.addEventListener('submit', submitIngestForm);

    // Initialise slider to the documented default; user adjustments live-update
    // the master gain.
    els.volumeSlider.value = String(state.volume);
    els.volumeSlider.addEventListener('input', () => {
        const v = parseFloat(els.volumeSlider.value);
        if (Number.isFinite(v)) {
            state.volume = v;
            if (state.masterGain) state.masterGain.gain.value = v;
        }
    });

    attachWaveformScrub();
}

// ============================================================
// Waveform scrubbing — click and drag the canvas to seek
// ============================================================
//
// Pause-while-scrubbing pattern: pointerdown stops the active sources and
// remembers whether we were playing; pointermove updates pausedOffset and
// the visual cursor without re-creating sources (so we don't churn audio
// nodes at 60 Hz); pointerup resumes from the new offset if we were playing
// before the drag started. A single click in playing state therefore
// seeks-and-continues; in paused state it just moves the cursor.

function attachWaveformScrub() {
    const canvas = els.canvas;
    let scrubbing = false;
    let resumeAfter = false;

    function fractionFromEvent(e) {
        const rect = canvas.getBoundingClientRect();
        return (e.clientX - rect.left) / rect.width;
    }

    canvas.addEventListener('pointerdown', (e) => {
        if (!currentBuffer()) return;  // no audio yet — nothing to seek
        scrubbing = true;
        resumeAfter = state.isPlaying;
        if (state.isPlaying) stop();
        try { canvas.setPointerCapture(e.pointerId); } catch { /* unsupported */ }
        seekToFraction(fractionFromEvent(e));
        e.preventDefault();
    });

    canvas.addEventListener('pointermove', (e) => {
        if (!scrubbing) return;
        seekToFraction(fractionFromEvent(e));
    });

    function endScrub(e) {
        if (!scrubbing) return;
        scrubbing = false;
        try { canvas.releasePointerCapture(e.pointerId); } catch { /* unsupported */ }
        if (resumeAfter) play();
    }

    canvas.addEventListener('pointerup', endScrub);
    canvas.addEventListener('pointercancel', endScrub);
}

// ============================================================
// Track lifecycle
// ============================================================

async function loadCurrentTrack() {
    // Tear down any audio still running from the previous track. Without
    // this, hitting "Next track" mid-playback leaves the old AudioBuffer-
    // SourceNodes alive and they keep playing under the new round label.
    stop();

    state.round = 0;
    state.guesses = [];
    state.pausedOffset = 0;
    els.guessList.innerHTML = '';
    clearRevealView();
    els.guessInput.value = '';
    els.guessInput.disabled = false;
    els.skipBtn.disabled = false;
    els.playBtn.disabled = true;

    const track = state.trackOrder[state.currentIndex];
    if (!track) {
        els.playBtn.disabled = true;
        els.guessInput.disabled = true;
        els.skipBtn.disabled = true;
        if (state.manifest.complete) {
            els.status.textContent = '🎉 Playlist complete.';
        } else {
            els.status.textContent =
                'Waiting for next track to finish separating…';
        }
        return;
    }

    els.status.textContent =
        `Track ${state.currentIndex + 1}/${state.trackOrder.length} — ` +
        'fetching stems…';

    try {
        await Promise.all(
            state.manifest.stems.map((s) => loadBuffer(track.stems[s])),
        );
    } catch (e) {
        els.status.textContent = `Stem fetch failed: ${e.message}`;
        return;
    }

    updateProgressLine();
    els.playBtn.disabled = false;
    els.guessInput.focus();
    updateRoundLabel();
    rebuildActiveWaveform();
    drawIdleWaveform();
}

async function loadBuffer(url) {
    if (state.buffersByUrl.has(url)) return;
    if (state.audioCtx === null) {
        // AudioContext construction must happen after a user gesture in some
        // browsers; we create it eagerly for buffer decoding (decode does not
        // require a started context).
        const Ctx = window.AudioContext || window.webkitAudioContext;
        state.audioCtx = new Ctx();
        // Insert a master GainNode between every source and the destination
        // so the volume slider has somewhere to attach.
        state.masterGain = state.audioCtx.createGain();
        state.masterGain.gain.value = state.volume;
        state.masterGain.connect(state.audioCtx.destination);
    }
    const response = await fetch(url, { cache: 'force-cache' });
    if (!response.ok) {
        throw new Error(`fetch ${url}: HTTP ${response.status}`);
    }
    const arrayBuffer = await response.arrayBuffer();
    const audioBuffer = await state.audioCtx.decodeAudioData(arrayBuffer);
    state.buffersByUrl.set(url, audioBuffer);
}

function updateRoundLabel() {
    const stems = state.manifest.stems;
    const revealed = stems.slice(0, state.round + 1);
    els.roundLabel.textContent =
        `Round ${state.round + 1} / ${stems.length} — ${revealed.join(' + ')}`;
}

function getActiveStemUrls() {
    const track = state.trackOrder[state.currentIndex];
    const stems = state.manifest.stems.slice(0, state.round + 1);
    return stems.map((s) => track.stems[s]);
}

// ============================================================
// Playback
// ============================================================

function togglePlay() {
    if (state.isPlaying) stop();
    else play();
}

function play() {
    if (state.audioCtx.state === 'suspended') {
        state.audioCtx.resume();
    }

    const urls = getActiveStemUrls();
    if (urls.length === 0) return;
    const offset = clampOffset(state.pausedOffset);

    state.activeSources = urls.map((url) => {
        const src = state.audioCtx.createBufferSource();
        src.buffer = state.buffersByUrl.get(url);
        src.connect(state.masterGain);
        // start(when=0 → immediately, offset=offset)
        src.start(0, offset);
        return src;
    });

    state.isPlaying = true;
    // Anchoring playStartContextTime this way means
    //   elapsed = audioCtx.currentTime - playStartContextTime
    // gives the *current* playhead position (not "time since play() was called"),
    // which is what every cursor and seek calculation needs.
    state.playStartContextTime = state.audioCtx.currentTime - offset;
    els.playBtn.textContent = '■';

    // Bind onended only to *this* source. If a seek replaces state.activeSources
    // with a fresh batch, the old onended firing must not stop the new sources.
    const firstNew = state.activeSources[0];
    firstNew.onended = () => {
        if (state.isPlaying && state.activeSources[0] === firstNew) {
            stop();
        }
    };

    state.rafId = requestAnimationFrame(drawWaveformFrame);
}

function stop() {
    const wasPlaying = state.isPlaying;
    const ctxTime = state.audioCtx ? state.audioCtx.currentTime : 0;

    for (const src of state.activeSources) {
        try { src.stop(); } catch { /* already ended */ }
    }
    state.activeSources = [];
    state.isPlaying = false;
    els.playBtn.textContent = '▶';
    if (state.rafId !== null) cancelAnimationFrame(state.rafId);
    state.rafId = null;

    if (wasPlaying) {
        // Capture the position we left off at, so a subsequent play() resumes
        // from there. If the clip ended naturally (elapsed past duration),
        // reset to 0 so the next play replays from the start.
        const elapsed = ctxTime - state.playStartContextTime;
        const buf = currentBuffer();
        const dur = buf ? buf.duration : 0;
        state.pausedOffset = (elapsed < 0 || elapsed >= dur) ? 0 : elapsed;
    }

    drawIdleWaveform();
}

function currentBuffer() {
    const urls = getActiveStemUrls();
    return urls.length > 0 ? state.buffersByUrl.get(urls[0]) : null;
}

function clampOffset(seconds) {
    const buf = currentBuffer();
    if (!buf) return 0;
    return Math.max(0, Math.min(buf.duration, seconds));
}

function seekToFraction(fraction) {
    fraction = Math.max(0, Math.min(1, fraction));
    const buf = currentBuffer();
    if (!buf) return;
    state.pausedOffset = fraction * buf.duration;
    if (state.isPlaying) {
        // Cheap approach: just update playStartContextTime so the on-screen
        // cursor jumps. Audio sources keep going at the OLD position until
        // pointer-up, when the pause/resume restart picks up the new offset.
        // (Updating sources mid-drag would mean stop/start dozens of times
        // per second; we settle on pointer-up instead.)
        state.playStartContextTime =
            state.audioCtx.currentTime - state.pausedOffset;
    } else {
        drawIdleWaveform();
    }
}

// ============================================================
// Waveform rendering
//
// Strategy: for the first active stem, downsample its first channel into
// per-pixel min/max and draw vertical lines (classic waveform shape).
// During playback, overlay a vertical cursor at the current playhead.
// ============================================================

function drawIdleWaveform() {
    const ctx = els.canvas.getContext('2d');
    const { width: w, height: h } = els.canvas;
    ctx.fillStyle = '#1f140b';
    ctx.fillRect(0, 0, w, h);

    drawCachedWaveform(ctx, w, h);

    // Show the playhead at pausedOffset whenever we're not currently playing.
    // (During playback, drawWaveformFrame draws a moving cursor instead.)
    const buf = currentBuffer();
    if (buf && state.pausedOffset > 0) {
        const cursorX = (state.pausedOffset / buf.duration) * w;
        ctx.fillStyle = '#9a2a35';
        ctx.fillRect(Math.max(0, cursorX - 1), 0, 2, h);
    }
}

function drawWaveformFrame() {
    if (!state.isPlaying) return;
    const ctx = els.canvas.getContext('2d');
    const { width: w, height: h } = els.canvas;

    // Background + waveform
    ctx.fillStyle = '#1f140b';
    ctx.fillRect(0, 0, w, h);
    drawCachedWaveform(ctx, w, h);

    // Playback cursor
    const buf = currentBuffer();
    if (buf) {
        const elapsed = state.audioCtx.currentTime - state.playStartContextTime;
        const cursorX = (elapsed / buf.duration) * w;
        ctx.fillStyle = '#9a2a35';
        ctx.fillRect(Math.max(0, cursorX - 1), 0, 2, h);
    }

    state.rafId = requestAnimationFrame(drawWaveformFrame);
}

function rebuildActiveWaveform() {
    // Sum channel-0 of every currently-active stem and downsample to one
    // (min, max) pair per canvas-buffer pixel. Stored on state.cachedWaveform
    // and consumed by drawCachedWaveform at idle-redraw and per-frame.
    const urls = getActiveStemUrls();
    const channels = urls
        .map((u) => state.buffersByUrl.get(u))
        .filter(Boolean)
        .map((b) => b.getChannelData(0));

    if (channels.length === 0) {
        state.cachedWaveform = null;
        return;
    }

    const w = els.canvas.width;
    const length = channels[0].length;
    const samplesPerPixel = Math.max(1, Math.floor(length / w));

    const min = new Float32Array(w);
    const max = new Float32Array(w);
    let peak = 0;

    for (let x = 0; x < w; x++) {
        const start = x * samplesPerPixel;
        const end = Math.min(length, start + samplesPerPixel);
        let pmin = Infinity;
        let pmax = -Infinity;
        for (let i = start; i < end; i++) {
            let sum = 0;
            for (let c = 0; c < channels.length; c++) sum += channels[c][i];
            if (sum < pmin) pmin = sum;
            if (sum > pmax) pmax = sum;
        }
        if (!Number.isFinite(pmin)) pmin = 0;
        if (!Number.isFinite(pmax)) pmax = 0;
        min[x] = pmin;
        max[x] = pmax;
        const a = Math.max(Math.abs(pmin), Math.abs(pmax));
        if (a > peak) peak = a;
    }

    state.cachedWaveform = { min, max, peak };
}

function drawCachedWaveform(ctx, w, h) {
    if (!state.cachedWaveform) return;
    const { min, max, peak } = state.cachedWaveform;
    // Normalise so the loudest sample reaches the top/bottom of the canvas;
    // otherwise summing 4 stems can clip well outside [-1, 1] and the
    // first-round (drums-only) waveform looks tiny by comparison.
    const scale = peak > 0 ? 1 / peak : 1;
    const midY = h / 2;
    ctx.strokeStyle = '#f3e9d2';
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let x = 0; x < w; x++) {
        const yMin = midY - max[x] * scale * midY;
        const yMax = midY - min[x] * scale * midY;
        ctx.moveTo(x, yMin);
        ctx.lineTo(x, yMax);
    }
    ctx.stroke();
}

// ============================================================
// Guess loop
// ============================================================

function normalize(s) {
    return s
        .toLowerCase()
        .normalize('NFD')
        .replace(/[̀-ͯ]/g, '')   // strip diacritics
        .replace(/\(.*?\)/g, '')           // drop parenthetical (Remix), (feat. ...)
        .replace(/\[.*?\]/g, '')           // drop bracketed similarly
        .replace(/[^\w\s]/g, '')           // strip remaining punctuation
        .replace(/\s+/g, ' ')
        .trim();
}

function isCorrect(guess, track) {
    const target = normalize(track.title);
    const guessN = normalize(guess);
    if (guessN.length === 0) return false;
    return guessN === target;
}

function submitGuess(text) {
    const guess = text.trim();
    if (!guess) return;

    const track = state.trackOrder[state.currentIndex];
    const correct = isCorrect(guess, track);
    state.guesses.push({ text: guess, correct, skipped: false });
    appendGuessLi(guess, correct ? 'correct' : '');
    els.guessInput.value = '';

    if (correct) {
        revealAnswer({ won: true, atRound: state.round });
        return;
    }
    advance();
}

function skip() {
    state.guesses.push({ text: '— skipped —', correct: false, skipped: true });
    appendGuessLi('— skipped —', 'skipped');
    advance();
}

function appendGuessLi(text, cls) {
    const li = document.createElement('li');
    li.textContent = text;
    if (cls) li.classList.add(cls);
    els.guessList.appendChild(li);
}

function advance() {
    state.round++;
    if (state.round >= state.manifest.stems.length) {
        revealAnswer({ won: false, atRound: null });
        return;
    }
    updateRoundLabel();
    stop();
    // Each round is a fresh listen — don't carry the previous round's
    // playhead position over to the new (cumulative) stem mix.
    state.pausedOffset = 0;
    // The active stem set just changed; the cached summed waveform must
    // grow to match what the next play() will actually output.
    rebuildActiveWaveform();
    drawIdleWaveform();
}

function revealAnswer({ won, atRound }) {
    stop();

    // Promote the player to the full-mix view — every stem revealed —
    // so the auto-play below renders the complete clip rather than
    // whatever partial round the player was on.
    state.round = state.manifest.stems.length - 1;
    state.pausedOffset = 0;
    updateRoundLabel();
    // Waveform now reflects the full mix, matching what auto-play will
    // produce.
    rebuildActiveWaveform();

    const track = state.trackOrder[state.currentIndex];

    // Album cover sits above the title inside the reveal-info card. The
    // waveform stays visible up top so the player can keep scrubbing the
    // full mix while looking at the answer.
    if (track.cover_url) {
        els.playerCover.src = track.cover_url;
        els.playerCover.alt = `Album cover for ${track.title}`;
        els.playerCover.hidden = false;
    } else {
        els.playerCover.removeAttribute('src');
        els.playerCover.hidden = true;
    }

    els.revealTitle.textContent = track.title;
    els.revealArtists.textContent = track.artists.join(', ');
    els.revealOutcome.textContent = won
        ? `solved on round ${atRound + 1} of ${state.manifest.stems.length}`
        : 'no win — out of guesses';
    els.revealInfo.hidden = false;
    els.guessInput.disabled = true;
    els.skipBtn.disabled = true;
    els.playBtn.disabled = false;  // user may want to pause / re-listen

    // Auto-play the full mix from the start, so the reveal *is* the song
    // playing in full, not just a static answer card.
    play();
}

function clearRevealView() {
    // Tear down the reveal block between tracks / on form re-show. The
    // waveform is unaffected — it stays the player's primary visual at
    // all times now.
    els.revealInfo.hidden = true;
    els.playerCover.hidden = true;
    els.playerCover.removeAttribute('src');
}

function nextTrack() {
    state.currentIndex++;
    loadCurrentTrack();
}

// ============================================================
// Helpers
// ============================================================

function shuffle(arr) {
    // Fisher–Yates
    for (let i = arr.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [arr[i], arr[j]] = [arr[j], arr[i]];
    }
    return arr;
}

// ============================================================

init();
