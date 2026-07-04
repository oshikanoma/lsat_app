<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<script lang="ts">
    import { bridgeCommand, bridgeCommandsAvailable } from "@tslib/bridgecommand";
    import { onMount } from "svelte";
    import { fly } from "svelte/transition";

    type Choice = { letter: string; text: string };
    type Q = {
        done: boolean;
        stimulus?: string;
        question?: string;
        choices?: Choice[];
        wrongLetter?: string;
        correctAnswer?: string;
        aiEnabled?: boolean;
    };
    type Msg = { role: "user" | "assistant"; content: string };
    type ChatRes = {
        reply?: string;
        understood?: boolean;
        coins?: number;
        concluded?: boolean;
        error?: boolean;
        source?: "ai" | "heuristic";
    };
    type StatusRes = { aiEnabled?: boolean };

    let q: Q | null = null;
    let input = "";
    let messages: Msg[] = [];
    let understood = false;
    let concluded = false;
    let busy = false;
    let coinsEarned = 0;
    let showPassage = false;

    // AI tutor status badge (read-only; the key is bundled with the app)
    let aiEnabled = false;

    // --- Voice: spoken Socratic dialogue (mic in, tutor speaks back) ---
    const OPENAI = "https://api.openai.com/v1";
    const STT_MODEL = "whisper-1";
    const TTS_MODEL = "gpt-4o-mini-tts";
    const TTS_FALLBACK_MODEL = "tts-1";
    const TTS_VOICE = "alloy";

    let voiceKey = "";
    let voiceReady = false; // key present + browser can capture audio
    let speakOn = true; // tutor reads replies aloud
    let recording = false;
    let transcribing = false;
    let speaking = false;
    let mediaRecorder: MediaRecorder | null = null;
    let recordedChunks: BlobPart[] = [];
    let micStream: MediaStream | null = null;
    let currentAudio: HTMLAudioElement | null = null;

    // Arrival animation: train chugs in -> intro card -> live station
    let phase: "arriving" | "intro" | "active" = "arriving";

    function call<T>(cmd: string): Promise<T | null> {
        return new Promise((resolve) => {
            if (!bridgeCommandsAvailable()) {
                resolve(null);
                return;
            }
            bridgeCommand<T>(cmd, (res) => resolve(res));
        });
    }

    async function loadNext(): Promise<void> {
        input = "";
        understood = false;
        concluded = false;
        showPassage = false;
        messages = [];
        q = await call<Q>("lsat:socratic:next");
        if (q && typeof q.aiEnabled === "boolean") {
            aiEnabled = q.aiEnabled;
        }
        if (q && !q.done) {
            const opener =
                "Take a look at the flagged answer below. In a sentence or two, why is it wrong?";
            messages = [{ role: "assistant", content: opener }];
            void speak(opener);
        }
    }

    async function send(): Promise<void> {
        if (busy || !input.trim() || understood || concluded) {
            return;
        }
        const text = input.trim();
        messages = [...messages, { role: "user", content: text }];
        input = "";
        busy = true;
        const res = await call<ChatRes>(
            "lsat:socratic:chat:" + JSON.stringify({ history: messages }),
        );
        busy = false;
        if (res?.reply) {
            messages = [...messages, { role: "assistant", content: res.reply }];
            void speak(res.reply);
        } else if (!res || res.error) {
            messages = [
                ...messages,
                {
                    role: "assistant",
                    content:
                        "Sorry — I couldn't reach the tutor just now. Give it another try.",
                },
            ];
        }
        if (res?.understood) {
            understood = true;
            if (res.coins) {
                coinsEarned += res.coins;
            }
        }
        if (res?.concluded) {
            concluded = true;
        }
        if (res?.source) {
            aiEnabled = res.source === "ai";
        }
    }

    async function refreshStatus(): Promise<void> {
        const s = await call<StatusRes>("lsat:socratic:status");
        if (s && typeof s.aiEnabled === "boolean") {
            aiEnabled = s.aiEnabled;
        }
    }

    async function reveal(): Promise<void> {
        if (busy || understood || concluded) {
            return;
        }
        busy = true;
        const res = await call<ChatRes>("lsat:socratic:reveal");
        busy = false;
        if (res?.reply) {
            messages = [...messages, { role: "assistant", content: res.reply }];
            void speak(res.reply);
        }
        concluded = true;
    }

    function pushBot(content: string): void {
        messages = [...messages, { role: "assistant", content }];
    }

    async function loadVoiceCreds(): Promise<void> {
        const c = await call<{ key?: string }>("lsat:socratic:voicecreds");
        voiceKey = (c && c.key) || "";
        const canCapture =
            typeof navigator !== "undefined" &&
            !!navigator.mediaDevices &&
            typeof navigator.mediaDevices.getUserMedia === "function" &&
            typeof window !== "undefined" &&
            "MediaRecorder" in window;
        voiceReady = !!voiceKey && canCapture;
    }

    async function toggleRecording(): Promise<void> {
        if (!voiceReady || busy || transcribing || understood || concluded) {
            return;
        }
        if (recording) {
            stopRecording();
            return;
        }
        // Don't record the tutor talking over us.
        stopSpeaking();
        try {
            micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        } catch (e) {
            pushBot(
                "I couldn't get to your microphone — check mic permission, or just type your answer below.",
            );
            return;
        }
        recordedChunks = [];
        const rec = new MediaRecorder(micStream);
        mediaRecorder = rec;
        rec.ondataavailable = (ev) => {
            if (ev.data && ev.data.size > 0) {
                recordedChunks.push(ev.data);
            }
        };
        rec.onstop = () => {
            void handleRecordingStop(rec.mimeType);
        };
        rec.start();
        recording = true;
    }

    function stopRecording(): void {
        recording = false;
        try {
            mediaRecorder?.stop();
        } catch (_) {
            /* already stopped */
        }
        micStream?.getTracks().forEach((t) => t.stop());
        micStream = null;
    }

    async function handleRecordingStop(mime: string): Promise<void> {
        mediaRecorder = null;
        if (!recordedChunks.length) {
            return;
        }
        const type = mime || "audio/webm";
        const blob = new Blob(recordedChunks, { type });
        recordedChunks = [];
        await transcribeAndSend(blob, type);
    }

    function fileNameFor(mime: string): string {
        if (mime.includes("ogg")) return "speech.ogg";
        if (mime.includes("mp4") || mime.includes("m4a")) return "speech.mp4";
        if (mime.includes("wav")) return "speech.wav";
        if (mime.includes("mpeg") || mime.includes("mp3")) return "speech.mp3";
        return "speech.webm";
    }

    async function transcribeAndSend(blob: Blob, mime: string): Promise<void> {
        transcribing = true;
        try {
            const form = new FormData();
            form.append("file", blob, fileNameFor(mime));
            form.append("model", STT_MODEL);
            const resp = await fetch(`${OPENAI}/audio/transcriptions`, {
                method: "POST",
                headers: { Authorization: `Bearer ${voiceKey}` },
                body: form,
            });
            if (!resp.ok) {
                throw new Error(`STT ${resp.status}`);
            }
            const data = await resp.json();
            const text = (data.text || "").trim();
            transcribing = false;
            if (text) {
                input = text;
                await send();
            } else {
                pushBot("I didn't quite catch that — want to try saying it again?");
            }
        } catch (e) {
            transcribing = false;
            pushBot(
                "Sorry, I couldn't make out the recording. Give it another go, or type your answer instead.",
            );
        }
    }

    function stopSpeaking(): void {
        if (currentAudio) {
            try {
                currentAudio.pause();
            } catch (_) {
                /* ignore */
            }
            currentAudio = null;
        }
        speaking = false;
    }

    async function speak(text: string): Promise<void> {
        if (!speakOn || !voiceKey || !text) {
            return;
        }
        stopSpeaking();
        const instructions =
            "You are a warm, encouraging LSAT tutor speaking out loud. Sound natural and conversational, at an even pace.";
        for (const model of [TTS_MODEL, TTS_FALLBACK_MODEL]) {
            try {
                const body: Record<string, unknown> = {
                    model,
                    voice: TTS_VOICE,
                    input: text,
                    response_format: "mp3",
                };
                if (model === TTS_MODEL) {
                    body.instructions = instructions;
                }
                const resp = await fetch(`${OPENAI}/audio/speech`, {
                    method: "POST",
                    headers: {
                        Authorization: `Bearer ${voiceKey}`,
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify(body),
                });
                if (!resp.ok) {
                    throw new Error(`TTS ${resp.status}`);
                }
                const url = URL.createObjectURL(await resp.blob());
                const audio = new Audio(url);
                currentAudio = audio;
                speaking = true;
                const clear = () => {
                    if (currentAudio === audio) {
                        speaking = false;
                        currentAudio = null;
                    }
                    URL.revokeObjectURL(url);
                };
                audio.onended = clear;
                audio.onerror = clear;
                await audio.play();
                return;
            } catch (e) {
                // fall through to the next model; give up quietly if both fail
                speaking = false;
            }
        }
    }

    function toggleSpeak(): void {
        speakOn = !speakOn;
        if (!speakOn) {
            stopSpeaking();
        }
    }

    function onKeydown(e: KeyboardEvent): void {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            send();
        }
    }

    const exit = () => {
        stopRecording();
        stopSpeaking();
        bridgeCommand("lsat:socratic:exit");
    };

    function getStarted(): void {
        phase = "active";
        loadNext();
    }

    onMount(() => {
        refreshStatus();
        void loadVoiceCreds();
        // let the train chug across, then reveal the intro card
        const t = setTimeout(() => (phase = "intro"), 2600);
        return () => {
            clearTimeout(t);
            stopRecording();
            stopSpeaking();
        };
    });
</script>

<div class="lsat-app">
    <header class="bar">
        <button class="back" on:click={exit}>Home</button>
        <span class="title">Socratic Station</span>
        <div class="bar-right">
            {#if voiceReady}
                <button
                    class="voice-toggle"
                    class:on={speakOn}
                    class:speaking
                    on:click={toggleSpeak}
                    aria-pressed={speakOn}
                    title={speakOn
                        ? "Tutor voice on — tap to mute"
                        : "Tutor voice off — tap to unmute"}
                >
                    <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
                        <path d="M4 9v6h4l5 4V5L8 9H4z" fill="currentColor" />
                        {#if speakOn}
                            <path
                                d="M16 8.5a4 4 0 0 1 0 7M18.5 6a7 7 0 0 1 0 12"
                                fill="none"
                                stroke="currentColor"
                                stroke-width="1.8"
                                stroke-linecap="round"
                            />
                        {:else}
                            <path
                                d="M17 9.5l4 5M21 9.5l-4 5"
                                fill="none"
                                stroke="currentColor"
                                stroke-width="1.8"
                                stroke-linecap="round"
                            />
                        {/if}
                    </svg>
                    Voice
                </button>
            {/if}
            <span
                class="engine"
                class:on={aiEnabled}
                title={aiEnabled ? "AI tutor active" : "Offline grader"}
            >
                <span class="dot-led" class:on={aiEnabled}></span>
                {aiEnabled ? "AI tutor" : "Offline grader"}
            </span>
            <span class="coins">{coinsEarned.toLocaleString()} earned</span>
        </div>
    </header>

    <main class="stage" class:wide={phase !== "active"}>
        {#if phase !== "active"}
            <div class="depot">
                <div class="scene">
                    <div class="train" class:parked={phase === "intro"}>
                        <svg
                            class="loco"
                            viewBox="0 0 220 104"
                            width="300"
                            height="142"
                            aria-hidden="true"
                        >
                            <defs>
                                <linearGradient id="boiler" x1="0" y1="0" x2="0" y2="1">
                                    <stop offset="0" stop-color="#b23640" />
                                    <stop offset="1" stop-color="#6e1423" />
                                </linearGradient>
                                <radialGradient id="winglow" cx="0.5" cy="0.4" r="0.7">
                                    <stop offset="0" stop-color="#fff4cf" />
                                    <stop offset="1" stop-color="#e0a83a" />
                                </radialGradient>
                            </defs>
                            <ellipse
                                cx="112"
                                cy="98"
                                rx="104"
                                ry="6"
                                fill="rgba(74,13,24,0.18)"
                            />
                            <!-- passenger car -->
                            <rect
                                x="6"
                                y="34"
                                width="72"
                                height="10"
                                rx="4"
                                fill="#4a0d18"
                            />
                            <rect
                                x="8"
                                y="42"
                                width="68"
                                height="38"
                                rx="7"
                                fill="#7a1a29"
                            />
                            <rect
                                x="16"
                                y="50"
                                width="20"
                                height="17"
                                rx="3"
                                fill="url(#winglow)"
                            />
                            <rect
                                x="46"
                                y="50"
                                width="20"
                                height="17"
                                rx="3"
                                fill="url(#winglow)"
                            />
                            <rect
                                x="8"
                                y="74"
                                width="68"
                                height="6"
                                fill="#c89b3c"
                                opacity="0.8"
                            />
                            <rect
                                x="76"
                                y="66"
                                width="10"
                                height="5"
                                rx="2"
                                fill="#4a0d18"
                            />
                            <!-- locomotive -->
                            <rect
                                x="84"
                                y="30"
                                width="36"
                                height="50"
                                rx="7"
                                fill="#8c1c2b"
                            />
                            <rect
                                x="92"
                                y="38"
                                width="20"
                                height="18"
                                rx="3"
                                fill="url(#winglow)"
                            />
                            <rect
                                x="112"
                                y="50"
                                width="66"
                                height="30"
                                rx="15"
                                fill="url(#boiler)"
                            />
                            <rect
                                x="120"
                                y="50"
                                width="4"
                                height="30"
                                fill="#c89b3c"
                                opacity="0.55"
                            />
                            <rect
                                x="150"
                                y="50"
                                width="4"
                                height="30"
                                fill="#c89b3c"
                                opacity="0.55"
                            />
                            <path d="M132 50 a8 8 0 0 1 16 0 z" fill="#4a0d18" />
                            <rect
                                x="118"
                                y="34"
                                width="12"
                                height="18"
                                rx="1.5"
                                fill="#4a0d18"
                            />
                            <polygon
                                points="114,34 134,34 130,28 118,28"
                                fill="#4a0d18"
                            />
                            <circle cx="178" cy="65" r="15" fill="#6e1423" />
                            <circle
                                cx="178"
                                cy="65"
                                r="15"
                                fill="none"
                                stroke="#c89b3c"
                                stroke-width="2"
                            />
                            <circle cx="181" cy="60" r="4" fill="url(#winglow)" />
                            <polygon points="178,80 196,92 178,92" fill="#4a0d18" />
                            <!-- wheels -->
                            <g class="wheel">
                                <circle cx="24" cy="86" r="9" fill="#2c1b1e" />
                                <circle
                                    cx="24"
                                    cy="86"
                                    r="9"
                                    fill="none"
                                    stroke="#c89b3c"
                                    stroke-width="1.6"
                                />
                                <line
                                    x1="24"
                                    y1="77"
                                    x2="24"
                                    y2="95"
                                    stroke="#c89b3c"
                                    stroke-width="1.4"
                                />
                                <line
                                    x1="15"
                                    y1="86"
                                    x2="33"
                                    y2="86"
                                    stroke="#c89b3c"
                                    stroke-width="1.4"
                                />
                            </g>
                            <g class="wheel">
                                <circle cx="60" cy="86" r="9" fill="#2c1b1e" />
                                <circle
                                    cx="60"
                                    cy="86"
                                    r="9"
                                    fill="none"
                                    stroke="#c89b3c"
                                    stroke-width="1.6"
                                />
                                <line
                                    x1="60"
                                    y1="77"
                                    x2="60"
                                    y2="95"
                                    stroke="#c89b3c"
                                    stroke-width="1.4"
                                />
                                <line
                                    x1="51"
                                    y1="86"
                                    x2="69"
                                    y2="86"
                                    stroke="#c89b3c"
                                    stroke-width="1.4"
                                />
                            </g>
                            <g class="wheel">
                                <circle cx="120" cy="84" r="13" fill="#2c1b1e" />
                                <circle
                                    cx="120"
                                    cy="84"
                                    r="13"
                                    fill="none"
                                    stroke="#c89b3c"
                                    stroke-width="2"
                                />
                                <line
                                    x1="120"
                                    y1="72"
                                    x2="120"
                                    y2="96"
                                    stroke="#c89b3c"
                                    stroke-width="1.6"
                                />
                                <line
                                    x1="108"
                                    y1="84"
                                    x2="132"
                                    y2="84"
                                    stroke="#c89b3c"
                                    stroke-width="1.6"
                                />
                            </g>
                            <g class="wheel">
                                <circle cx="152" cy="84" r="13" fill="#2c1b1e" />
                                <circle
                                    cx="152"
                                    cy="84"
                                    r="13"
                                    fill="none"
                                    stroke="#c89b3c"
                                    stroke-width="2"
                                />
                                <line
                                    x1="152"
                                    y1="72"
                                    x2="152"
                                    y2="96"
                                    stroke="#c89b3c"
                                    stroke-width="1.6"
                                />
                                <line
                                    x1="140"
                                    y1="84"
                                    x2="164"
                                    y2="84"
                                    stroke="#c89b3c"
                                    stroke-width="1.6"
                                />
                            </g>
                            <g class="wheel">
                                <circle cx="180" cy="88" r="7" fill="#2c1b1e" />
                                <circle
                                    cx="180"
                                    cy="88"
                                    r="7"
                                    fill="none"
                                    stroke="#c89b3c"
                                    stroke-width="1.4"
                                />
                            </g>
                            <!-- smoke -->
                            <g class="smoke">
                                <circle
                                    class="puff p1"
                                    cx="124"
                                    cy="26"
                                    r="6"
                                    fill="rgba(120,110,110,0.5)"
                                />
                                <circle
                                    class="puff p2"
                                    cx="124"
                                    cy="26"
                                    r="8"
                                    fill="rgba(120,110,110,0.4)"
                                />
                                <circle
                                    class="puff p3"
                                    cx="124"
                                    cy="26"
                                    r="10"
                                    fill="rgba(120,110,110,0.3)"
                                />
                            </g>
                        </svg>
                    </div>
                </div>

                {#if phase === "intro"}
                    <div
                        class="depot-copy"
                        in:fly={{ y: 22, duration: 500, delay: 120 }}
                    >
                        <span class="eyebrow">Now arriving</span>
                        <h1>Socratic Station</h1>
                        <p>
                            The station flags one wrong answer choice. Your job is to
                            explain the exact flaw that makes it wrong.
                        </p>
                        <button class="cta big" on:click={getStarted}>
                            Get started
                        </button>
                    </div>
                {/if}
            </div>
        {:else if !q}
            <p class="loading">Loading…</p>
        {:else if q.done}
            <div class="done">
                <h1>No questions available.</h1>
                <button class="cta" on:click={exit}>Back to home</button>
            </div>
        {:else}
            <div class="chat">
                <div class="bubble bot">
                    <p class="lead">
                        The <b>flagged</b>
                        choice below is wrong. Talk it through with me and I'll help you
                        pin down exactly
                        <b>why</b>
                         — I may ask you to clarify.
                    </p>
                    {#if q.stimulus}
                        <button
                            class="passage-toggle"
                            on:click={() => (showPassage = !showPassage)}
                        >
                            {showPassage ? "Hide context" : "Show context"}
                        </button>
                        {#if showPassage}
                            <div class="stimulus">{q.stimulus}</div>
                        {/if}
                    {/if}
                    <p class="qtext">{q.question}</p>
                    {#if q.choices}
                        <div class="choices">
                            {#each q.choices as c}
                                <div
                                    class="choice"
                                    class:target={c.letter === q.wrongLetter}
                                    class:correct={understood &&
                                        c.letter === q.correctAnswer}
                                >
                                    <span class="letter">{c.letter}</span>
                                    <span class="ctext">{c.text}</span>
                                    {#if c.letter === q.wrongLetter}
                                        <span class="tag tag-wrong">explain this</span>
                                    {/if}
                                    {#if understood && c.letter === q.correctAnswer}
                                        <span class="tag tag-right">correct</span>
                                    {/if}
                                </div>
                            {/each}
                        </div>
                    {/if}
                </div>

                {#each messages as m}
                    <div
                        class="bubble msg"
                        class:bot={m.role === "assistant"}
                        class:user={m.role === "user"}
                    >
                        <span class="msg-text">{m.content}</span>
                        {#if voiceReady && m.role === "assistant"}
                            <button
                                class="replay"
                                on:click={() => speak(m.content)}
                                title="Play aloud"
                                aria-label="Play this reply aloud"
                            >
                                <svg
                                    viewBox="0 0 24 24"
                                    width="14"
                                    height="14"
                                    aria-hidden="true"
                                >
                                    <path d="M8 5v14l11-7z" fill="currentColor" />
                                </svg>
                            </button>
                        {/if}
                    </div>
                {/each}

                {#if busy}
                    <div class="bubble bot typing" aria-label="Tutor is thinking">
                        <span class="dot"></span>
                        <span class="dot"></span>
                        <span class="dot"></span>
                    </div>
                {/if}

                {#if understood || concluded}
                    <div
                        class="bubble bot verdict"
                        class:good={understood}
                        class:bad={!understood}
                    >
                        <p class="lead">
                            {understood
                                ? "Nicely reasoned — coins added to your homebase."
                                : "That's the flaw. No coins this time — but now you've seen it."}
                        </p>
                        <button class="cta" on:click={loadNext}>Next question</button>
                    </div>
                {/if}
            </div>

            {#if !understood && !concluded}
                <div class="composer">
                    {#if recording || transcribing || speaking}
                        <div class="voice-status" class:rec={recording}>
                            {#if recording}
                                <span class="pulse"></span>
                                 Listening… tap the mic when you're done
                            {:else if transcribing}
                                <span class="spin"></span>
                                 Transcribing what you said…
                            {:else}
                                <span class="pulse soft"></span>
                                 Tutor is speaking…
                            {/if}
                        </div>
                    {/if}
                    <textarea
                        bind:value={input}
                        on:keydown={onKeydown}
                        placeholder={voiceReady
                            ? "Tap the mic to talk it through — or type here…"
                            : "This answer is wrong because…"}
                        rows="3"
                    ></textarea>
                    <div class="composer-actions">
                        <div class="left-actions">
                            {#if voiceReady}
                                <button
                                    class="mic"
                                    class:rec={recording}
                                    disabled={busy ||
                                        transcribing ||
                                        understood ||
                                        concluded}
                                    on:click={toggleRecording}
                                    title={recording
                                        ? "Stop and send"
                                        : "Talk it through out loud"}
                                >
                                    {#if recording}
                                        <svg
                                            viewBox="0 0 24 24"
                                            width="18"
                                            height="18"
                                            aria-hidden="true"
                                        >
                                            <rect
                                                x="7"
                                                y="7"
                                                width="10"
                                                height="10"
                                                rx="2"
                                                fill="currentColor"
                                            />
                                        </svg>
                                        Stop
                                    {:else}
                                        <svg
                                            viewBox="0 0 24 24"
                                            width="18"
                                            height="18"
                                            aria-hidden="true"
                                        >
                                            <rect
                                                x="9"
                                                y="3"
                                                width="6"
                                                height="11"
                                                rx="3"
                                                fill="currentColor"
                                            />
                                            <path
                                                d="M6 11a6 6 0 0 0 12 0M12 17v3"
                                                fill="none"
                                                stroke="currentColor"
                                                stroke-width="1.8"
                                                stroke-linecap="round"
                                            />
                                        </svg>
                                        {transcribing ? "…" : "Speak"}
                                    {/if}
                                </button>
                            {/if}
                            <button
                                class="pass"
                                disabled={busy || recording}
                                on:click={reveal}
                            >
                                Skip &amp; show me
                            </button>
                        </div>
                        <button
                            class="cta"
                            disabled={!input.trim() || busy || recording}
                            on:click={send}
                        >
                            {busy ? "Thinking…" : "Send"}
                        </button>
                    </div>
                </div>
            {/if}
        {/if}
    </main>
</div>

<style lang="scss">
    @import url("https://fonts.googleapis.com/css2?family=Jost:wght@400;500;600;700;800&display=swap");

    .lsat-app {
        --maroon: #6e1423;
        --maroon-deep: #4a0d18;
        --maroon-bright: #9e2a2b;
        --beige: #f6edda;
        --beige-deep: #ece0c2;
        --paper: #fffdf6;
        --ink: #2c1b1e;
        --muted: #7a6a63;
        --green: #2f7d4f;
        --red: #b23a3a;
        --gold: #c89b3c;

        min-height: 100vh;
        background: var(--beige);
        color: var(--ink);
        font-size: 15px;
        font-family:
            "Jost",
            -apple-system,
            "Segoe UI",
            system-ui,
            sans-serif;
        -webkit-font-smoothing: antialiased;
    }

    button {
        font: inherit;
        cursor: pointer;
        border: none;
        background: none;
        color: inherit;
    }

    .bar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 1rem;
        padding: 0.75rem 1.25rem;
        background: var(--maroon);
        color: var(--beige);
        position: sticky;
        top: 0;
        z-index: 2;
        .title {
            font-weight: 800;
        }
        .coins {
            color: var(--gold);
            font-weight: 700;
            font-variant-numeric: tabular-nums;
        }
        .back {
            color: var(--beige);
            padding: 0.35rem 0.7rem;
            border-radius: 8px;
            transition: background 120ms ease;
            -webkit-tap-highlight-color: transparent;
            &:hover,
            &:focus-visible,
            &:active {
                background: rgba(246, 237, 218, 0.12);
            }
        }
    }
    .bar-right {
        display: flex;
        align-items: center;
        gap: 0.85rem;
    }
    .engine {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        padding: 0.28rem 0.6rem;
        border-radius: 999px;
        font-size: 0.74rem;
        font-weight: 700;
        color: var(--beige);
        background: rgba(246, 237, 218, 0.12);
        &.on {
            color: #fffdf6;
            background: rgba(47, 125, 79, 0.55);
        }
    }
    .dot-led {
        width: 0.5rem;
        height: 0.5rem;
        border-radius: 50%;
        background: var(--gold);
        box-shadow: 0 0 0 2px rgba(200, 155, 60, 0.25);
        &.on {
            background: #57e08a;
            box-shadow: 0 0 0 2px rgba(87, 224, 138, 0.3);
        }
    }
    .voice-toggle {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        padding: 0.28rem 0.6rem;
        border-radius: 999px;
        font-size: 0.74rem;
        font-weight: 700;
        color: var(--beige);
        background: rgba(246, 237, 218, 0.12);
        transition:
            background 120ms ease,
            transform 80ms ease;
        &.on {
            color: #fffdf6;
            background: rgba(200, 155, 60, 0.5);
        }
        &.speaking svg {
            animation: pulseFade 0.9s ease-in-out infinite;
        }
        &:hover {
            transform: translateY(-1px);
        }
    }
    @keyframes pulseFade {
        0%,
        100% {
            opacity: 1;
        }
        50% {
            opacity: 0.4;
        }
    }

    .stage {
        max-width: 44rem;
        margin: 0 auto;
        padding: 1.5rem 1.25rem 3rem;
    }
    .loading {
        text-align: center;
        color: var(--maroon);
        margin-top: 4rem;
    }

    /* ---- arrival: train chugs in, then intro card ---- */
    .stage.wide {
        max-width: none;
        padding-left: 0;
        padding-right: 0;
    }
    .depot {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        min-height: 68vh;
    }
    .scene {
        position: relative;
        width: 100vw;
        left: 50%;
        transform: translateX(-50%);
        overflow: hidden;
        display: flex;
        justify-content: center;
        padding: 0.5rem 0;
    }
    .train {
        animation: chugin 2.6s cubic-bezier(0.17, 0.67, 0.24, 1) both;
    }
    @keyframes chugin {
        from {
            transform: translateX(-135vw);
        }
        to {
            transform: translateX(0);
        }
    }
    .loco {
        display: block;
        filter: drop-shadow(0 10px 16px rgba(74, 13, 24, 0.18));
    }
    .train:not(.parked) .loco {
        animation: enginebob 0.28s steps(2, end) infinite;
    }
    @keyframes enginebob {
        0% {
            transform: translateY(0);
        }
        50% {
            transform: translateY(-1.5px);
        }
    }
    .wheel {
        transform-box: fill-box;
        transform-origin: center;
    }
    .train:not(.parked) .wheel {
        animation: roll 0.5s linear infinite;
    }
    @keyframes roll {
        to {
            transform: rotate(360deg);
        }
    }
    .puff {
        transform-box: fill-box;
        transform-origin: center;
        animation: puff 1.5s ease-out infinite;
    }
    .puff.p2 {
        animation-delay: 0.4s;
    }
    .puff.p3 {
        animation-delay: 0.8s;
    }
    @keyframes puff {
        0% {
            opacity: 0.55;
            transform: translate(0, 0) scale(0.45);
        }
        100% {
            opacity: 0;
            transform: translate(-26px, -42px) scale(1.7);
        }
    }

    .depot-copy {
        text-align: center;
        max-width: 32rem;
        margin: 0.5rem auto 0;
        padding: 0 1.25rem;
        .eyebrow {
            text-transform: uppercase;
            letter-spacing: 0.1em;
            font-size: 0.72rem;
            font-weight: 800;
            color: var(--maroon-bright);
        }
        h1 {
            font-size: 2.1rem;
            font-weight: 800;
            color: var(--maroon-deep);
            margin: 0.2rem 0 0.5rem;
        }
        p {
            color: var(--muted);
            line-height: 1.55;
            margin: 0 0 1.4rem;
        }
    }
    .cta.big {
        align-self: center;
        font-size: 1.05rem;
        padding: 0.8rem 2rem;
        border-radius: 12px;
        box-shadow: 0 10px 24px rgba(74, 13, 24, 0.22);
    }

    .chat {
        display: flex;
        flex-direction: column;
        gap: 0.9rem;
    }
    .bubble {
        padding: 1rem 1.1rem;
        border-radius: 14px;
        line-height: 1.5;
        max-width: 92%;
        &.bot {
            background: var(--paper);
            border: 1px solid var(--beige-deep);
            align-self: flex-start;
            border-bottom-left-radius: 4px;
        }
        &.user {
            background: var(--maroon);
            color: var(--beige);
            align-self: flex-end;
            border-bottom-right-radius: 4px;
            white-space: pre-wrap;
        }
        &.msg {
            display: flex;
            align-items: flex-end;
            gap: 0.5rem;
        }
    }
    .msg-text {
        white-space: pre-wrap;
    }
    .replay {
        flex-shrink: 0;
        width: 1.5rem;
        height: 1.5rem;
        display: grid;
        place-items: center;
        border-radius: 50%;
        color: var(--maroon-bright);
        background: var(--beige);
        border: 1px solid var(--beige-deep);
        opacity: 0.7;
        transition:
            opacity 120ms ease,
            background 120ms ease;
        &:hover {
            opacity: 1;
            background: var(--beige-deep);
        }
    }

    .typing {
        display: flex;
        gap: 0.32rem;
        align-items: center;
        .dot {
            width: 0.5rem;
            height: 0.5rem;
            border-radius: 50%;
            background: var(--muted);
            animation: blink 1.2s infinite ease-in-out both;
        }
        .dot:nth-child(2) {
            animation-delay: 0.18s;
        }
        .dot:nth-child(3) {
            animation-delay: 0.36s;
        }
    }
    @keyframes blink {
        0%,
        80%,
        100% {
            opacity: 0.25;
            transform: translateY(0);
        }
        40% {
            opacity: 1;
            transform: translateY(-2px);
        }
    }
    .lead {
        margin: 0 0 0.6rem;
        font-weight: 600;
        color: var(--maroon-deep);
    }
    .qtext {
        margin: 0.6rem 0 0.7rem;
        font-weight: 700;
    }
    .passage-toggle {
        font-size: 0.78rem;
        font-weight: 700;
        color: var(--maroon-bright);
    }
    .stimulus {
        white-space: pre-wrap;
        margin-top: 0.5rem;
        padding: 0.7rem 0.8rem;
        background: var(--beige);
        border-radius: 8px;
        max-height: 14rem;
        overflow-y: auto;
        font-size: 0.92rem;
    }
    .choices {
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
    }
    .choice {
        display: flex;
        gap: 0.6rem;
        align-items: center;
        padding: 0.6rem 0.75rem;
        border-radius: 9px;
        background: var(--paper);
        border: 1.5px solid var(--beige-deep);
        .letter {
            flex-shrink: 0;
            width: 1.5rem;
            height: 1.5rem;
            display: grid;
            place-items: center;
            border-radius: 50%;
            background: var(--beige-deep);
            color: var(--maroon-deep);
            font-weight: 800;
            font-size: 0.8rem;
        }
        .ctext {
            flex: 1;
        }
        .tag {
            flex-shrink: 0;
            font-size: 0.62rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            padding: 0.15rem 0.45rem;
            border-radius: 999px;
        }
        .tag-wrong {
            background: var(--red);
            color: #fff;
        }
        .tag-right {
            background: var(--green);
            color: #fff;
        }
        &.target {
            background: #f7e1e1;
            border-color: var(--red);
            .letter {
                background: var(--red);
                color: #fff;
            }
        }
        &.correct {
            background: #e2f0e6;
            border-color: var(--green);
            .letter {
                background: var(--green);
                color: #fff;
            }
        }
    }
    .verdict {
        &.good {
            border-color: var(--green);
        }
        &.bad {
            border-color: var(--red);
        }
        .model {
            margin: 0 0 1rem;
            line-height: 1.55;
        }
    }

    .composer-actions {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 0.6rem;
    }
    .left-actions {
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    .mic {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        padding: 0.5rem 0.9rem;
        border-radius: 9px;
        font-weight: 700;
        font-size: 0.88rem;
        color: var(--beige);
        background: var(--maroon-bright);
        transition:
            background 120ms ease,
            transform 80ms ease;
        &:hover:not(:disabled) {
            transform: translateY(-1px);
        }
        &:disabled {
            opacity: 0.45;
            cursor: default;
        }
        &.rec {
            background: var(--red);
            animation: recGlow 1.1s ease-in-out infinite;
        }
    }
    @keyframes recGlow {
        0%,
        100% {
            box-shadow: 0 0 0 0 rgba(178, 58, 58, 0.5);
        }
        50% {
            box-shadow: 0 0 0 6px rgba(178, 58, 58, 0);
        }
    }
    .voice-status {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        font-size: 0.85rem;
        font-weight: 600;
        color: var(--muted);
        padding: 0.2rem 0.1rem;
        &.rec {
            color: var(--red);
        }
        .pulse {
            width: 0.6rem;
            height: 0.6rem;
            border-radius: 50%;
            background: var(--red);
            animation: recGlow 1.1s ease-in-out infinite;
            &.soft {
                background: var(--maroon-bright);
            }
        }
        .spin {
            width: 0.8rem;
            height: 0.8rem;
            border-radius: 50%;
            border: 2px solid var(--beige-deep);
            border-top-color: var(--maroon-bright);
            animation: spin 0.8s linear infinite;
        }
    }
    @keyframes spin {
        to {
            transform: rotate(360deg);
        }
    }
    .pass {
        padding: 0.55rem 1rem;
        border-radius: 9px;
        font-weight: 600;
        font-size: 0.88rem;
        color: var(--muted);
        border: 1px solid var(--beige-deep);
        background: var(--paper);
        transition:
            background 120ms ease,
            color 120ms ease;
        &:hover:not(:disabled) {
            background: var(--beige-deep);
            color: var(--maroon-deep);
        }
        &:disabled {
            opacity: 0.45;
            cursor: default;
        }
    }

    .composer {
        margin-top: 1rem;
        display: flex;
        flex-direction: column;
        gap: 0.6rem;
        textarea {
            width: 100%;
            padding: 0.8rem 0.9rem;
            border: 2px solid var(--beige-deep);
            border-radius: 10px;
            background: var(--paper);
            font: inherit;
            color: var(--ink);
            resize: vertical;
            &:focus {
                outline: none;
                border-color: var(--maroon-bright);
            }
        }
    }

    .cta {
        align-self: flex-start;
        padding: 0.6rem 1.3rem;
        border-radius: 9px;
        font-weight: 700;
        color: var(--beige);
        background: var(--maroon);
        transition:
            background 120ms ease,
            transform 80ms ease;
        &:hover:not(:disabled) {
            background: #7f2230;
            transform: translateY(-1px);
        }
        &:disabled {
            opacity: 0.45;
            cursor: default;
        }
    }
    .done {
        text-align: center;
        margin-top: 3rem;
        h1 {
            color: var(--maroon-deep);
            margin-bottom: 1rem;
        }
    }
</style>
