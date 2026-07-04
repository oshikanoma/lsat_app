<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<script lang="ts">
    import { bridgeCommand, bridgeCommandsAvailable } from "@tslib/bridgecommand";
    import { onDestroy, onMount } from "svelte";
    import { fade } from "svelte/transition";

    type Choice = { letter: string; text: string };
    type Session = { total: number; remaining: number } | null;
    type Progress = { correct: number; total: number };
    type Card = {
        done: boolean;
        section: string;
        reason?: string;
        stimulus?: string;
        question?: string;
        choices?: Choice[];
        answer?: string;
        explanation?: string;
        remaining?: number;
        session?: Session;
        progress?: Progress;
    };

    let card: Card | null = null;
    let chosen: string | null = null;
    let answered = false;
    let correctCount = 0;
    let totalCount = 0;

    // Intro -> flying hourglass -> active question flow
    let phase: "intro" | "flying" | "active" = "intro";
    let flyerEl: HTMLDivElement | null = null;
    let slotEl: HTMLElement | null = null;

    // Timed-lesson hourglass
    let total = 0;
    let secondsLeft = 0;
    let timer: ReturnType<typeof setInterval> | null = null;

    function syncSession(c: Card | null): void {
        if (c && c.session) {
            total = c.session.total;
            secondsLeft = c.session.remaining;
            if (!timer) {
                timer = setInterval(() => {
                    secondsLeft = Math.max(0, secondsLeft - 1);
                }, 1000);
            }
        } else {
            total = 0;
            secondsLeft = 0;
            if (timer) {
                clearInterval(timer);
                timer = null;
            }
        }
    }

    function fmtTime(s: number): string {
        const h = Math.floor(s / 3600);
        const m = Math.floor((s % 3600) / 60);
        const sec = s % 60;
        const pad = (n: number) => String(n).padStart(2, "0");
        return h > 0 ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
    }

    $: frac = total ? Math.max(0, Math.min(1, secondsLeft / total)) : 0;
    $: topH = 22 * frac;
    $: topY = 29 - topH;
    $: botH = 22 * (1 - frac);
    $: botY = 54 - botH;

    onDestroy(() => timer && clearInterval(timer));

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
        chosen = null;
        answered = false;
        card = await call<Card>("lsat:practice:next");
        syncSession(card);
        if (card?.progress) {
            correctCount = card.progress.correct;
            totalCount = card.progress.total;
        }
    }

    function choose(letter: string): void {
        if (answered || !card) {
            return;
        }
        chosen = letter;
        answered = true;
        totalCount += 1;
        if (letter.toUpperCase() === (card.answer ?? "").toUpperCase()) {
            correctCount += 1;
        }
        bridgeCommand(`lsat:practice:answer:${letter}`);
    }

    const exit = () => bridgeCommand("lsat:practice:exit");

    function choiceClass(letter: string): string {
        if (!answered || !card) {
            return "";
        }
        if (letter.toUpperCase() === (card.answer ?? "").toUpperCase()) {
            return "correct";
        }
        if (letter === chosen) {
            return "wrong";
        }
        return "dimmed";
    }

    $: isCorrect =
        answered && card && chosen?.toUpperCase() === (card.answer ?? "").toUpperCase();
    $: accuracy = totalCount ? Math.round((correctCount / totalCount) * 100) : 0;
    // Compact header title so the bar stays a single line on mobile.
    $: shortSection =
        card?.section === "Logical Reasoning"
            ? "LR"
            : card?.section === "Reading Comprehension"
              ? "RC"
              : (card?.section ?? "Practice");

    async function begin(): Promise<void> {
        // Measure how far the big hourglass must travel to reach the corner slot.
        if (flyerEl && slotEl) {
            const f = flyerEl.getBoundingClientRect();
            const s = slotEl.getBoundingClientRect();
            const dx = s.left + s.width / 2 - (f.left + f.width / 2);
            const dy = s.top + s.height / 2 - (f.top + f.height / 2);
            const scale = Math.max(0.12, s.height / f.height);
            flyerEl.style.setProperty("--dx", `${dx}px`);
            flyerEl.style.setProperty("--dy", `${dy}px`);
            flyerEl.style.setProperty("--s", `${scale}`);
        }
        phase = "flying";
        // Start the backend clock now and fetch the first card during the flight.
        chosen = null;
        answered = false;
        card = await call<Card>("lsat:practice:begin");
        syncSession(card);
        if (card?.progress) {
            correctCount = card.progress.correct;
            totalCount = card.progress.total;
        }
        // Let the flip-shrink-slide animation play, then reveal the question.
        setTimeout(() => (phase = "active"), 1150);
    }

    onMount(async () => {
        // If a lesson is already in progress (user toggled back from home),
        // skip the intro animation and restore the clock + score directly.
        const st = await call<Card & { active?: boolean }>("lsat:practice:resume");
        if (st && st.active) {
            card = st;
            syncSession(card);
            if (card?.progress) {
                correctCount = card.progress.correct;
                totalCount = card.progress.total;
            }
            phase = "active";
        }
    });
</script>

<div class="lsat-app">
    <header class="bar">
        <button class="back" on:click={exit}>Home</button>
        <span class="title">{phase === "active" ? shortSection : "Practice"}</span>
        <div class="bar-right">
            {#if phase === "active"}
                <span class="score" in:fade={{ duration: 250 }}>
                    {correctCount}/{totalCount} · {accuracy}%
                </span>
            {/if}
            <span class="hg-slot" bind:this={slotEl}>
                {#if phase === "active" && total}
                    <span
                        class="hourglass"
                        title="Time remaining"
                        in:fade={{ duration: 300, delay: 60 }}
                    >
                        <svg
                            viewBox="0 0 40 60"
                            width="20"
                            height="30"
                            aria-hidden="true"
                        >
                            <defs>
                                <clipPath id="topTri">
                                    <polygon points="7,7 33,7 20,29" />
                                </clipPath>
                                <clipPath id="botTri">
                                    <polygon points="20,31 33,53 7,53" />
                                </clipPath>
                            </defs>
                            <rect
                                x="7"
                                y={topY}
                                width="26"
                                height={topH}
                                fill="#e7c66b"
                                clip-path="url(#topTri)"
                            />
                            <rect
                                x="7"
                                y={botY}
                                width="26"
                                height={botH}
                                fill="#e7c66b"
                                clip-path="url(#botTri)"
                            />
                            {#if frac > 0 && frac < 1}
                                <rect
                                    x="19.2"
                                    y="29"
                                    width="1.6"
                                    height="2"
                                    fill="#e7c66b"
                                />
                            {/if}
                            <polygon
                                points="7,7 33,7 20,29"
                                fill="none"
                                stroke="#f6edda"
                                stroke-width="1.6"
                            />
                            <polygon
                                points="20,31 33,53 7,53"
                                fill="none"
                                stroke="#f6edda"
                                stroke-width="1.6"
                            />
                            <line
                                x1="5"
                                y1="7"
                                x2="35"
                                y2="7"
                                stroke="#f6edda"
                                stroke-width="2.2"
                                stroke-linecap="round"
                            />
                            <line
                                x1="5"
                                y1="53"
                                x2="35"
                                y2="53"
                                stroke="#f6edda"
                                stroke-width="2.2"
                                stroke-linecap="round"
                            />
                        </svg>
                        <span class="clock">{fmtTime(secondsLeft)}</span>
                    </span>
                {/if}
            </span>
        </div>
    </header>

    <main class="stage">
        {#if phase !== "active"}
            <div class="intro">
                <div
                    class="flyer"
                    class:flying={phase === "flying"}
                    bind:this={flyerEl}
                >
                    <svg
                        class="hg"
                        viewBox="0 0 80 120"
                        width="140"
                        height="205"
                        aria-hidden="true"
                    >
                        <defs>
                            <linearGradient id="hgSand" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0" stop-color="#f2c765" />
                                <stop offset="1" stop-color="#d99a2b" />
                            </linearGradient>
                            <radialGradient id="hgGlow" cx="0.5" cy="0.5" r="0.5">
                                <stop offset="0" stop-color="rgba(224,168,58,0.45)" />
                                <stop offset="1" stop-color="rgba(224,168,58,0)" />
                            </radialGradient>
                        </defs>
                        <ellipse cx="40" cy="60" rx="36" ry="50" fill="url(#hgGlow)" />
                        <polygon points="14,106 66,106 40,62" fill="url(#hgSand)" />
                        <rect x="38.6" y="52" width="2.8" height="10" fill="#d99a2b" />
                        <polygon points="34,50 46,50 40,58" fill="url(#hgSand)" />
                        <polygon
                            points="14,14 66,14 40,58"
                            fill="none"
                            stroke="#8c1c2b"
                            stroke-width="2.4"
                            stroke-linejoin="round"
                        />
                        <polygon
                            points="40,62 66,106 14,106"
                            fill="none"
                            stroke="#8c1c2b"
                            stroke-width="2.4"
                            stroke-linejoin="round"
                        />
                        <line
                            x1="8"
                            y1="14"
                            x2="72"
                            y2="14"
                            stroke="#6e1423"
                            stroke-width="4.5"
                            stroke-linecap="round"
                        />
                        <line
                            x1="8"
                            y1="106"
                            x2="72"
                            y2="106"
                            stroke="#6e1423"
                            stroke-width="4.5"
                            stroke-linecap="round"
                        />
                        <line
                            x1="12"
                            y1="14"
                            x2="12"
                            y2="106"
                            stroke="#6e1423"
                            stroke-width="3"
                            stroke-linecap="round"
                        />
                        <line
                            x1="68"
                            y1="14"
                            x2="68"
                            y2="106"
                            stroke="#6e1423"
                            stroke-width="3"
                            stroke-linecap="round"
                        />
                    </svg>
                </div>
                <div class="intro-copy" class:hide={phase === "flying"}>
                    <h1>Ready to get started?</h1>
                    <p class="lead">
                        A 2-hour adaptive lesson, tuned to your weakest area.
                    </p>
                    <button class="cta big" on:click={begin}>Begin lesson</button>
                    <p class="science">
                        Focused study blocks of roughly two hours — long enough for deep
                        work, short enough to stay ahead of fatigue — are a sweet spot
                        for durable, long-term retention.
                    </p>
                </div>
            </div>
        {:else if !card}
            <p class="loading">Loading…</p>
        {:else if card.done}
            <div class="done">
                <h1>{card.reason === "time" ? "Time's up." : "Nice work."}</h1>
                <p>
                    {#if card.reason === "time"}
                        Your 2-hour lesson is complete.
                    {:else}
                        You've cleared the questions due for now.
                    {/if}
                    {#if totalCount}
                        This session: <b>{correctCount}/{totalCount}</b>
                        correct ({accuracy}%).
                    {/if}
                </p>
                <p class="hint">FSRS will bring these back when it's time to review.</p>
                <button class="cta" on:click={exit}>Back to home</button>
            </div>
        {:else}
            <article class="qcard">
                {#if card.stimulus}
                    <div class="stimulus">{@html card.stimulus}</div>
                {/if}
                <h2 class="question">{card.question}</h2>

                <ul class="choices">
                    {#each card.choices ?? [] as c}
                        <li>
                            <button
                                class="choice {choiceClass(c.letter)}"
                                disabled={answered}
                                on:click={() => choose(c.letter)}
                            >
                                <span class="letter">{c.letter}</span>
                                <span class="ctext">{c.text}</span>
                            </button>
                        </li>
                    {/each}
                </ul>

                {#if answered}
                    <div class="feedback" class:good={isCorrect} class:bad={!isCorrect}>
                        <div class="verdict">
                            {isCorrect
                                ? "Correct"
                                : `Incorrect — answer is ${card.answer}`}
                        </div>
                        {#if card.explanation}
                            <p class="explanation">{card.explanation}</p>
                        {/if}
                        <button class="cta" on:click={loadNext}>Next question</button>
                    </div>
                {/if}
            </article>
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
        --green: #2f7d4f;
        --red: #b23a3a;

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
            letter-spacing: 0.01em;
            white-space: nowrap;
        }
        .bar-right {
            display: flex;
            align-items: center;
            gap: 0.9rem;
            flex: none;
        }
        .score {
            font-variant-numeric: tabular-nums;
            opacity: 0.9;
            white-space: nowrap;
        }
        .hg-slot {
            display: flex;
            align-items: center;
            justify-content: flex-end;
            min-width: 92px;
            height: 30px;
        }
        .hourglass {
            display: flex;
            align-items: center;
            gap: 0.35rem;
        }
        .clock {
            font-variant-numeric: tabular-nums;
            font-weight: 700;
            font-size: 0.9rem;
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

    .stage {
        max-width: 48rem;
        margin: 0 auto;
        padding: 1.75rem 1.25rem 4rem;
    }

    .loading {
        color: var(--maroon);
        text-align: center;
        margin-top: 4rem;
    }

    /* ---- lesson intro + flying hourglass ---- */
    .intro {
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        padding-top: 3.5rem;
        min-height: 70vh;
    }
    .flyer {
        z-index: 5;
        transform-origin: center center;
        will-change: transform, opacity;
    }
    .flyer .hg {
        display: block;
        filter: drop-shadow(0 10px 18px rgba(74, 13, 24, 0.22));
    }
    .flyer:not(.flying) .hg {
        animation: hgidle 4.5s ease-in-out infinite;
        transform-origin: center center;
    }
    @keyframes hgidle {
        0%,
        100% {
            transform: rotate(-2.5deg);
        }
        50% {
            transform: rotate(2.5deg);
        }
    }
    .flyer.flying {
        animation: fly 1150ms cubic-bezier(0.6, 0.04, 0.24, 1) forwards;
    }
    @keyframes fly {
        0% {
            transform: translate(0, 0) rotate(0deg) scale(1);
            opacity: 1;
        }
        30% {
            transform: translate(0, 0) rotate(180deg) scale(1);
            opacity: 1;
        }
        44% {
            transform: translate(0, 0) rotate(180deg) scale(1.07);
            opacity: 1;
        }
        88% {
            opacity: 1;
        }
        100% {
            transform: translate(var(--dx, 0), var(--dy, -260px)) rotate(180deg)
                scale(var(--s, 0.15));
            opacity: 0;
        }
    }

    .intro-copy {
        margin-top: 1.75rem;
        max-width: 30rem;
        transition:
            opacity 300ms ease,
            transform 300ms ease;
        h1 {
            font-size: 2rem;
            font-weight: 800;
            color: var(--maroon-deep);
            margin: 0 0 0.4rem;
        }
        .lead {
            color: var(--maroon);
            font-weight: 600;
            margin: 0 0 1.4rem;
        }
        .science {
            margin: 1.4rem auto 0;
            max-width: 26rem;
            font-size: 0.85rem;
            line-height: 1.55;
            color: var(--muted, #7a6a63);
            font-style: italic;
        }
    }
    .intro-copy.hide {
        opacity: 0;
        transform: translateY(10px);
        pointer-events: none;
    }
    .cta.big {
        font-size: 1.1rem;
        padding: 0.85rem 2rem;
        border-radius: 12px;
        box-shadow: 0 10px 24px rgba(74, 13, 24, 0.22);
    }

    .qcard {
        background: var(--paper);
        border: 1px solid var(--beige-deep);
        border-radius: 14px;
        padding: 1.5rem;
        box-shadow: 0 6px 20px rgba(74, 13, 24, 0.08);
    }

    .stimulus {
        line-height: 1.55;
        margin-bottom: 1rem;
        padding-bottom: 1rem;
        border-bottom: 1px dashed var(--beige-deep);
        white-space: pre-wrap;
    }

    .question {
        font-size: 1.15rem;
        font-weight: 700;
        margin: 0 0 1.1rem;
        color: var(--maroon-deep);
    }

    .choices {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: 0.6rem;
    }

    .choice {
        display: flex;
        align-items: flex-start;
        gap: 0.75rem;
        width: 100%;
        text-align: left;
        padding: 0.8rem 0.9rem;
        border: 2px solid var(--beige-deep);
        border-radius: 10px;
        background: var(--beige);
        transition:
            border-color 120ms ease,
            background 120ms ease,
            transform 80ms ease;

        &:not(:disabled):hover {
            border-color: var(--maroon-bright);
            transform: translateY(-1px);
        }
        .letter {
            flex-shrink: 0;
            width: 1.6rem;
            height: 1.6rem;
            display: grid;
            place-items: center;
            border-radius: 50%;
            background: var(--maroon);
            color: var(--beige);
            font-weight: 800;
            font-size: 0.85rem;
        }
        .ctext {
            line-height: 1.45;
            padding-top: 0.1rem;
        }

        &.correct {
            border-color: var(--green);
            background: rgba(47, 125, 79, 0.12);
            .letter {
                background: var(--green);
            }
        }
        &.wrong {
            border-color: var(--red);
            background: rgba(178, 58, 58, 0.12);
            .letter {
                background: var(--red);
            }
        }
        &.dimmed {
            opacity: 0.55;
        }
        &:disabled {
            cursor: default;
        }
    }

    .feedback {
        margin-top: 1.25rem;
        padding: 1rem 1.1rem;
        border-radius: 10px;
        border-left: 5px solid var(--maroon);
        background: var(--beige-deep);

        &.good {
            border-left-color: var(--green);
            background: #e4f0e8;
        }
        &.bad {
            border-left-color: var(--red);
            background: #f7e1e1;
        }
        .verdict {
            font-weight: 800;
            margin-bottom: 0.4rem;
        }
        .explanation {
            margin: 0 0 1rem;
            line-height: 1.55;
        }
    }

    .cta {
        padding: 0.6rem 1.2rem;
        border-radius: 8px;
        font-weight: 700;
        color: var(--beige);
        background: var(--maroon);
        transition:
            background 120ms ease,
            transform 80ms ease;
        &:hover {
            background: var(--maroon-bright);
            transform: translateY(-1px);
        }
    }

    .done {
        text-align: center;
        margin-top: 3rem;
        h1 {
            color: var(--maroon-deep);
            margin-bottom: 0.5rem;
        }
        .hint {
            color: var(--maroon);
            opacity: 0.8;
            margin-bottom: 1.5rem;
        }
    }
</style>
