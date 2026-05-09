// game.js — StemGuessr browser-side game logic.
//
// Reads manifest.json (Phase 5 schema v1) from the same directory, then
// runs the round-by-round Bandle-style guessing loop:
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
    buffersByUrl: new Map(),  // url -> AudioBuffer
    activeSources: [],     // currently-playing AudioBufferSourceNodes
    playStartContextTime: 0,  // audioCtx.currentTime at play() call
    rafId: null,           // requestAnimationFrame id for waveform redraw loop
};

// ============================================================
// DOM cache
// ============================================================

const els = {
    status:        document.getElementById('status-line'),
    canvas:        document.getElementById('waveform'),
    playBtn:       document.getElementById('play-btn'),
    roundLabel:    document.getElementById('round-label'),
    guessInput:    document.getElementById('guess-input'),
    guessForm:     document.getElementById('guess-form'),
    skipBtn:       document.getElementById('skip-btn'),
    guessList:     document.getElementById('guess-list'),
    reveal:        document.getElementById('reveal'),
    revealTitle:   document.getElementById('reveal-title'),
    revealArtists: document.getElementById('reveal-artists'),
    revealOutcome: document.getElementById('reveal-outcome'),
    nextBtn:       document.getElementById('next-track-btn'),
};

// ============================================================
// Bootstrap
// ============================================================

async function init() {
    els.status.textContent = 'Loading manifest…';
    let manifest;
    try {
        const response = await fetch('manifest.json', { cache: 'no-cache' });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        manifest = await response.json();
    } catch (e) {
        els.status.textContent = `Could not load manifest.json — ${e.message}. ` +
            'Run `stemguessr ingest <playlist_url>` first.';
        return;
    }

    if (manifest.version !== 1) {
        els.status.textContent =
            `Unsupported manifest version: ${manifest.version}. Frontend supports v1.`;
        return;
    }
    if (!manifest.tracks || manifest.tracks.length === 0) {
        els.status.textContent = 'Manifest has no tracks.';
        return;
    }

    state.manifest = manifest;
    state.trackOrder = shuffle([...manifest.tracks]);

    els.status.textContent =
        `${manifest.tracks.length} tracks · ${manifest.stems.length} stems · ` +
        `${manifest.model}`;

    wireEvents();
    await loadCurrentTrack();
}

function wireEvents() {
    els.playBtn.addEventListener('click', togglePlay);
    els.guessForm.addEventListener('submit', (e) => {
        e.preventDefault();
        submitGuess(els.guessInput.value);
    });
    els.skipBtn.addEventListener('click', skip);
    els.nextBtn.addEventListener('click', nextTrack);
}

// ============================================================
// Track lifecycle
// ============================================================

async function loadCurrentTrack() {
    state.round = 0;
    state.guesses = [];
    els.guessList.innerHTML = '';
    els.reveal.hidden = true;
    els.guessInput.value = '';
    els.guessInput.disabled = false;
    els.skipBtn.disabled = false;
    els.playBtn.disabled = true;

    const track = state.trackOrder[state.currentIndex];
    if (!track) {
        // Reached the end of the playlist
        els.status.textContent = '🎉 Playlist complete.';
        els.playBtn.disabled = true;
        els.guessInput.disabled = true;
        return;
    }

    els.status.textContent =
        `Track ${state.currentIndex + 1}/${state.trackOrder.length} — ` +
        'fetching stems…';

    try {
        await Promise.all(state.manifest.stems.map((s) => loadBuffer(track.stems[s])));
    } catch (e) {
        els.status.textContent = `Stem fetch failed: ${e.message}`;
        return;
    }

    els.status.textContent =
        `Track ${state.currentIndex + 1}/${state.trackOrder.length}`;
    els.playBtn.disabled = false;
    els.guessInput.focus();
    updateRoundLabel();
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
    // Some browsers suspend the AudioContext until a user gesture; resume it.
    if (state.audioCtx.state === 'suspended') {
        state.audioCtx.resume();
    }

    const urls = getActiveStemUrls();
    state.activeSources = urls.map((url) => {
        const src = state.audioCtx.createBufferSource();
        src.buffer = state.buffersByUrl.get(url);
        src.connect(state.audioCtx.destination);
        src.start();
        return src;
    });

    state.isPlaying = true;
    state.playStartContextTime = state.audioCtx.currentTime;
    els.playBtn.textContent = '■';

    // All stems are co-aligned; the first source's `ended` event signals end.
    state.activeSources[0].onended = () => {
        if (state.isPlaying) stop();
    };

    state.rafId = requestAnimationFrame(drawWaveformFrame);
}

function stop() {
    for (const src of state.activeSources) {
        try { src.stop(); } catch { /* already ended */ }
    }
    state.activeSources = [];
    state.isPlaying = false;
    els.playBtn.textContent = '▶';
    if (state.rafId !== null) cancelAnimationFrame(state.rafId);
    state.rafId = null;
    drawIdleWaveform();
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

    const urls = getActiveStemUrls();
    if (urls.length === 0) return;
    const buffer = state.buffersByUrl.get(urls[0]);
    if (!buffer) return;
    drawBufferOnCanvas(ctx, buffer, w, h);
}

function drawWaveformFrame() {
    if (!state.isPlaying) return;
    const ctx = els.canvas.getContext('2d');
    const { width: w, height: h } = els.canvas;

    // Background + waveform
    ctx.fillStyle = '#1f140b';
    ctx.fillRect(0, 0, w, h);
    const urls = getActiveStemUrls();
    const buffer = state.buffersByUrl.get(urls[0]);
    if (buffer) drawBufferOnCanvas(ctx, buffer, w, h);

    // Playback cursor
    if (buffer) {
        const elapsed = state.audioCtx.currentTime - state.playStartContextTime;
        const cursorX = (elapsed / buffer.duration) * w;
        ctx.fillStyle = '#9a2a35';
        ctx.fillRect(Math.max(0, cursorX - 1), 0, 2, h);
    }

    state.rafId = requestAnimationFrame(drawWaveformFrame);
}

function drawBufferOnCanvas(ctx, buffer, w, h) {
    const data = buffer.getChannelData(0);
    const samplesPerPixel = Math.max(1, Math.floor(data.length / w));
    ctx.strokeStyle = '#f3e9d2';
    ctx.lineWidth = 1;
    ctx.beginPath();
    const midY = h / 2;
    for (let x = 0; x < w; x++) {
        let min = 1, max = -1;
        const start = x * samplesPerPixel;
        const end = Math.min(data.length, start + samplesPerPixel);
        for (let i = start; i < end; i++) {
            const v = data[i];
            if (v < min) min = v;
            if (v > max) max = v;
        }
        const yMin = midY - min * midY;
        const yMax = midY - max * midY;
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
}

function revealAnswer({ won, atRound }) {
    stop();
    const track = state.trackOrder[state.currentIndex];
    els.revealTitle.textContent = track.title;
    els.revealArtists.textContent = track.artists.join(', ');
    els.revealOutcome.textContent = won
        ? `solved on round ${atRound + 1} of ${state.manifest.stems.length}`
        : 'no win — out of guesses';
    els.reveal.hidden = false;
    els.guessInput.disabled = true;
    els.skipBtn.disabled = true;
    els.playBtn.disabled = false;  // user may want to re-listen
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
