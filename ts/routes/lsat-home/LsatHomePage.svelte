<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<script lang="ts">
    import { bridgeCommand, bridgeCommandsAvailable } from "@tslib/bridgecommand";
    import { onDestroy, onMount, tick } from "svelte";
    import { fade, fly } from "svelte/transition";
    import { cubicOut, backOut } from "svelte/easing";
    import Onboarding from "./Onboarding.svelte";
    import Walkthrough from "./Walkthrough.svelte";

    type Score = {
        available: boolean;
        value: string;
        range: string;
        confidence: number;
        sampleSize: number;
        reasons: string[];
    };
    type TypeStat = {
        type: string;
        correct: number;
        total: number;
        accuracy: number | null;
        enoughData: boolean;
        needed: number;
    };
    type Quiz = { word: string; correct: string; wrong: string };
    type WordEntry = {
        word: string;
        pos: string;
        def: string;
        example: string;
        quiz: Quiz | null;
    };
    type Profile = {
        onboarded: boolean;
        name: string;
        startDate: string;
        planMonths: number;
        dailyHours: number;
    };
    type Plan = {
        startDate: string;
        endDate: string;
        dailyHours: number;
        totalDays: number;
        dayNumber: number;
    };
    type Upgrade = {
        id: string;
        name: string;
        desc: string;
        cost: number;
        owned: boolean;
    };
    type House = { coins: number; upgrades: string[]; catalog: Upgrade[] };
    type HomeState = {
        profile: Profile;
        plan: Plan;
        house: House;
        words: WordEntry[];
        vocabCount: number;
        vocabTotal: number;
        loggedIn: boolean;
        scores: { memory: Score; performance: Score; readiness: Score };
        gradedReviews: number;
        topicCoverage?: number;
        typeBreakdown?: TypeStat[];
        nextStep: string;
        missing: string[];
        startInMenu?: boolean;
        mobile?: boolean;
    };

    let state: HomeState | null = null;
    // "hub" = just the floating homebase; tap it to reveal everything ("menu").
    // Fresh app launch opens on the hub; returning from a lesson/Socratic this
    // run opens straight into the menu (backend sends startInMenu).
    let view: "hub" | "menu" = "hub";
    let viewInit = false;
    let showShop = false;

    function call(cmd: string): Promise<HomeState | null> {
        return new Promise((resolve) => {
            if (!bridgeCommandsAvailable()) {
                resolve(null);
                return;
            }
            bridgeCommand<HomeState>(cmd, (res) => resolve(res));
        });
    }

    async function refresh(): Promise<void> {
        const res = await call("lsat:home");
        if (res) {
            state = res;
        }
    }

    async function addWord(): Promise<void> {
        const res = await call("lsat:vocab:add");
        if (res) {
            state = res;
        }
    }

    async function sync(): Promise<void> {
        await call("lsat:sync");
        setTimeout(refresh, 1500);
    }

    // Sign-in from the login gate. Unlike a plain sync, this keeps each account
    // isolated on the device: a different account pulls its own data instead of
    // merging/uploading whatever progress is already stored locally.
    async function signIn(): Promise<void> {
        await call("lsat:signin");
        setTimeout(refresh, 1500);
    }

    let confirmingLogout = false;

    async function logout(): Promise<void> {
        const res = await call("lsat:logout");
        if (res) {
            state = res;
            view = "hub";
            showShop = false;
            openScore = null;
        }
    }

    async function confirmLogout(): Promise<void> {
        confirmingLogout = false;
        await logout();
    }

    // Wipe this account's progress everywhere (this device AND the account on
    // AnkiWeb) and start completely fresh. Used to clean up an account whose
    // data got mixed up, or to reset for a from-scratch demo.
    async function resetAll(): Promise<void> {
        confirmingLogout = false;
        await call("lsat:reset");
        view = "hub";
        showShop = false;
        openScore = null;
        viewInit = false;
        // The wipe + clean upload runs on a background thread; refresh a couple
        // of times so the UI reflects the fresh (onboarding) state once done.
        setTimeout(refresh, 1500);
        setTimeout(refresh, 3500);
    }

    async function buyUpgrade(id: string): Promise<void> {
        const res = await call(`lsat:house:buy:${id}`);
        if (res) {
            state = res;
        }
    }

    const reviewVocab = () => bridgeCommand("lsat:vocab:review");
    const startLesson = () => bridgeCommand("lsat:lesson:start");
    const openSocratic = () => bridgeCommand("lsat:socratic:open");

    function enterMenu(): void {
        view = "menu";
    }
    function toHub(): void {
        view = "hub";
        showShop = false;
    }

    // First-run guided tour of the homebase. Each step points at a real
    // element on the menu screen by CSS selector.
    let showTour = false;
    const TOUR_STEPS = [
        {
            sel: ".homebase",
            title: "This is your homebase",
            body: "Tap the little house anytime to come back here. It's your launchpad — every part of your prep is one tap away.",
        },
        {
            sel: ".homebar",
            title: "Make it your own",
            body: "The coins you earn buy upgrades for your homebase — gardens, lanterns, even an aurora sky. Small rewards that make the daily grind feel like somewhere you want to be.",
        },
        {
            sel: ".lesson-cta",
            title: "Your daily 2-hour lesson",
            body: "This is the heart of it. Each day is one focused 2-hour session — and that cap is the whole point. Short, deliberate reps beat marathon cram sessions, so the timer protects your learning instead of grinding you down. Every correct answer earns 100 coins.",
            emphasis: true,
        },
        {
            sel: ".socratic-cta",
            title: "The Socratic Station",
            body: "Hop on the train to explain out loud why a wrong answer is wrong. Saying your reasoning aloud — not just clicking a choice — is what forces real understanding to stick (and it's worth 500 coins a time).",
        },
        {
            sel: ".dashboard",
            title: "Three honest scores",
            body: "Memory, Performance, and Readiness — each shown as a range, never a fake single number. We only reveal a score once there's enough data to trust it, and always point you to the single best thing to study next.",
        },
    ];

    async function startTour(): Promise<void> {
        view = "menu";
        showShop = false;
        await tick();
        // Let the menu's fly-in transitions land before we measure targets.
        setTimeout(() => (showTour = true), 420);
    }

    async function onOnboardDone(detail: HomeState): Promise<void> {
        state = detail;
        viewInit = true;
        await startTour();
    }

    function niceDate(iso: string): string {
        if (!iso) {
            return "";
        }
        const d = new Date(iso + "T00:00:00");
        return d.toLocaleDateString(undefined, {
            month: "short",
            day: "numeric",
            year: "numeric",
        });
    }

    let timer: ReturnType<typeof setInterval>;
    onMount(async () => {
        await refresh();
        // Only begin building progress (the daily word) once signed in; on
        // mobile, login is handled natively so keep the existing behaviour.
        if (state?.loggedIn) {
            const res = await call("lsat:vocab:ensure");
            if (res) {
                state = res;
            }
        }
        // Skip the "tap the homebase" hub if the user already started this run.
        if (!viewInit) {
            if (state?.startInMenu) {
                view = "menu";
            }
            viewInit = true;
        }
        timer = setInterval(refresh, 5000);
    });
    onDestroy(() => clearInterval(timer));

    const SCORE_META = [
        { key: "memory", label: "Memory" },
        { key: "performance", label: "Performance" },
        { key: "readiness", label: "Readiness" },
    ] as const;

    let openScore: string | null = null;
    const toggleScore = (key: string) => (openScore = openScore === key ? null : key);

    // Word-of-the-day navigation + comprehension quiz
    let wordIndex = -1;
    let quizWord = "";
    let quizPick: string | null = null;
    let quizOrder: { text: string; correct: boolean }[] = [];

    function setupQuiz(w: WordEntry): void {
        quizWord = w.word;
        quizPick = null;
        if (w.quiz && w.quiz.wrong) {
            const opts = [
                { text: w.quiz.correct, correct: true },
                { text: w.quiz.wrong, correct: false },
            ];
            quizOrder = Math.random() < 0.5 ? opts : [opts[1], opts[0]];
        } else {
            quizOrder = [];
        }
    }

    const pick = (o: { text: string; correct: boolean }) => {
        if (!quizPick) {
            quizPick = o.text;
        }
    };
    const prevWord = () => wordIndex > 0 && (wordIndex -= 1);
    const nextWord = () => wordIndex < words.length - 1 && (wordIndex += 1);

    $: profile = state?.profile ?? null;
    $: plan = state?.plan ?? null;
    $: house = state?.house ?? null;
    // Mobile shows the same homebase hub landing as desktop, but hides the
    // coin/upgrade shop (which lives in the homebar).
    $: mobile = state?.mobile ?? false;
    $: onboarded = profile ? profile.onboarded : true;
    $: coins = house?.coins ?? 0;
    $: catalog = house?.catalog ?? [];
    $: owned = new Set(house?.upgrades ?? []);
    $: words = state?.words ?? [];
    $: if (words.length && (wordIndex < 0 || wordIndex >= words.length)) {
        wordIndex = words.length - 1;
    }
    $: current = words[wordIndex] ?? null;
    $: if (current && current.word !== quizWord) {
        setupQuiz(current);
    }
    $: quizPickCorrect = quizPick
        ? (quizOrder.find((o) => o.text === quizPick)?.correct ?? false)
        : false;

    $: vocabCount = state?.vocabCount ?? 0;
    $: gradedReviews = state?.gradedReviews ?? 0;
    $: topicCoverage = state?.topicCoverage ?? 0;
    $: typeBreakdown = state?.typeBreakdown ?? [];
    $: practicedTypes = typeBreakdown.filter((t) => t.total > 0);
    $: nextStep = state?.nextStep ?? "Loading…";
    $: missing = state?.missing ?? [];
    $: loggedIn = state?.loggedIn ?? false;
</script>

<div class="lsat-app" class:has-aurora={owned.has("aurora")}>
    <!-- Pale-blue sky behind everything -->
    <div class="sky" aria-hidden="true">
        {#if owned.has("aurora")}
            <div class="sunset" transition:fade={{ duration: 700 }}></div>
        {/if}
        <span class="cloud c1"></span>
        <span class="cloud c2"></span>
        <span class="cloud c3"></span>
    </div>

    <header class="bar">
        <span class="brand">homebase.</span>
        {#if loggedIn}
            <div class="bar-right">
                <span class="coins" title="Coins">
                    <span class="coin-icon" aria-hidden="true"></span>
                    {coins.toLocaleString()}
                </span>
                {#if onboarded}
                    <button
                        class="help"
                        on:click={startTour}
                        title="Replay the walkthrough"
                        aria-label="Replay the walkthrough"
                    >
                        ?
                    </button>
                {/if}
                <button class="sync on" on:click={sync}>Synced</button>
                <button
                    class="mini"
                    on:click={() => (confirmingLogout = true)}
                    title="Sign out and clear this device's progress"
                >
                    Sign out
                </button>
            </div>
        {/if}
    </header>

    {#if confirmingLogout}
        <div
            class="modal-scrim"
            role="presentation"
            on:click={() => (confirmingLogout = false)}
        >
            <!-- svelte-ignore a11y-click-events-have-key-events -->
            <div
                class="logout-card"
                role="dialog"
                aria-modal="true"
                aria-labelledby="logout-title"
                tabindex="-1"
                on:click|stopPropagation
            >
                <h3 id="logout-title">Sign out?</h3>
                <p>
                    Your progress is saved to your AnkiWeb account — your name, coins,
                    homebase, vocabulary and stats. Signing out just locks this device;
                    sign back in anytime to pick up right where you left off, here or on
                    any other device.
                </p>
                <div class="modal-actions">
                    <button
                        class="modal-cancel"
                        on:click={() => (confirmingLogout = false)}
                    >
                        Cancel
                    </button>
                    <button class="modal-confirm" on:click={confirmLogout}>
                        Sign out
                    </button>
                </div>
                <button
                    class="reset-link"
                    on:click={resetAll}
                    title="Erase this account's progress everywhere and start fresh"
                >
                    Reset &amp; start over
                </button>
            </div>
        </div>
    {/if}

    {#if state && !loggedIn}
        <section class="gate" in:fade={{ duration: 300 }}>
            <div class="gate-card">
                <span class="gate-brand">homebase.</span>
                <p class="gate-tag">Your LSAT prep, synced across every device.</p>
                <button class="gate-btn" on:click={signIn}>Sign in to begin</button>
                <p class="gate-note">
                    Sign in with your AnkiWeb account. Your progress lives on the
                    account and syncs across every device, so you'll pick up right where
                    you left off.
                </p>
            </div>
        </section>
    {:else if state && !onboarded}
        <Onboarding on:done={(e) => onOnboardDone(e.detail)} />
    {:else}
        <main
            class="stage"
            class:hub={view === "hub"}
            class:menu={view === "menu"}
            class:mobile
        >
            <!-- The homebase: on desktop it persists across both views and morphs
                 to the top; on mobile it disappears entirely once tapped. -->
            {#if !mobile || view === "hub"}
                <div class="hero" out:fade={{ duration: 220 }}>
                    <button
                        class="homebase"
                        on:click={view === "hub" ? enterMenu : toHub}
                        aria-label={view === "hub"
                            ? "Open your homebase"
                            : "Back to homebase"}
                    >
                        <div class="float">
                            <svg
                                viewBox="0 0 260 252"
                                width="260"
                                height="252"
                                role="img"
                                aria-hidden="true"
                            >
                                <defs>
                                    <!-- platform -->
                                    <linearGradient
                                        id="gTop"
                                        x1="0"
                                        y1="0"
                                        x2="1"
                                        y2="1"
                                    >
                                        <stop offset="0" stop-color="#f7eed6" />
                                        <stop offset="1" stop-color="#e4d4ac" />
                                    </linearGradient>
                                    <linearGradient
                                        id="gSideR"
                                        x1="0"
                                        y1="0"
                                        x2="0"
                                        y2="1"
                                    >
                                        <stop offset="0" stop-color="#c2a488" />
                                        <stop offset="1" stop-color="#6f5147" />
                                    </linearGradient>
                                    <linearGradient
                                        id="gSideL"
                                        x1="0"
                                        y1="0"
                                        x2="0"
                                        y2="1"
                                    >
                                        <stop offset="0" stop-color="#8a6e60" />
                                        <stop offset="1" stop-color="#3f2b27" />
                                    </linearGradient>
                                    <!-- walls + roof -->
                                    <linearGradient
                                        id="gWallR"
                                        x1="0"
                                        y1="0"
                                        x2="0"
                                        y2="1"
                                    >
                                        <stop offset="0" stop-color="#fffdf6" />
                                        <stop offset="1" stop-color="#ecdcba" />
                                    </linearGradient>
                                    <linearGradient
                                        id="gWallL"
                                        x1="0"
                                        y1="0"
                                        x2="0"
                                        y2="1"
                                    >
                                        <stop offset="0" stop-color="#e7d7b4" />
                                        <stop offset="1" stop-color="#c3ac85" />
                                    </linearGradient>
                                    <linearGradient
                                        id="gRoofR"
                                        x1="0"
                                        y1="0"
                                        x2="0.6"
                                        y2="1"
                                    >
                                        <stop offset="0" stop-color="#b23640" />
                                        <stop offset="1" stop-color="#6e1423" />
                                    </linearGradient>
                                    <linearGradient
                                        id="gRoofL"
                                        x1="0"
                                        y1="0"
                                        x2="0.4"
                                        y2="1"
                                    >
                                        <stop offset="0" stop-color="#6e1423" />
                                        <stop offset="1" stop-color="#4a0d18" />
                                    </linearGradient>
                                    <linearGradient
                                        id="gDome"
                                        x1="0"
                                        y1="0"
                                        x2="0"
                                        y2="1"
                                    >
                                        <stop offset="0" stop-color="#fdf6e6" />
                                        <stop offset="1" stop-color="#dcc9a2" />
                                    </linearGradient>
                                    <!-- glowing window -->
                                    <radialGradient id="gWin" cx="0.5" cy="0.4" r="0.7">
                                        <stop offset="0" stop-color="#fff4cf" />
                                        <stop offset="0.5" stop-color="#ffcf55" />
                                        <stop offset="1" stop-color="#e0951f" />
                                    </radialGradient>
                                    <radialGradient
                                        id="gUnder"
                                        cx="0.5"
                                        cy="0.5"
                                        r="0.5"
                                    >
                                        <stop
                                            offset="0"
                                            stop-color="rgba(20,20,25,0.38)"
                                        />
                                        <stop
                                            offset="1"
                                            stop-color="rgba(20,20,25,0)"
                                        />
                                    </radialGradient>
                                    <radialGradient
                                        id="gSpill"
                                        cx="0.5"
                                        cy="0.5"
                                        r="0.5"
                                    >
                                        <stop
                                            offset="0"
                                            stop-color="rgba(255,206,120,0.55)"
                                        />
                                        <stop
                                            offset="1"
                                            stop-color="rgba(255,206,120,0)"
                                        />
                                    </radialGradient>
                                    <radialGradient
                                        id="gPond"
                                        cx="0.4"
                                        cy="0.35"
                                        r="0.75"
                                    >
                                        <stop offset="0" stop-color="#dff0fa" />
                                        <stop offset="1" stop-color="#8fbdd8" />
                                    </radialGradient>
                                    <radialGradient
                                        id="gLeaf"
                                        cx="0.4"
                                        cy="0.3"
                                        r="0.8"
                                    >
                                        <stop offset="0" stop-color="#7cb073" />
                                        <stop offset="1" stop-color="#3f7a4a" />
                                    </radialGradient>
                                    <radialGradient
                                        id="gBalloon"
                                        cx="0.36"
                                        cy="0.28"
                                        r="0.85"
                                    >
                                        <stop offset="0" stop-color="#c24a52" />
                                        <stop offset="0.55" stop-color="#8c1c2b" />
                                        <stop offset="1" stop-color="#4a0d18" />
                                    </radialGradient>
                                    <filter
                                        id="dropSoft"
                                        x="-40%"
                                        y="-40%"
                                        width="180%"
                                        height="200%"
                                    >
                                        <feDropShadow
                                            dx="0"
                                            dy="7"
                                            stdDeviation="7"
                                            flood-color="#3a0a12"
                                            flood-opacity="0.32"
                                        />
                                    </filter>
                                    <filter
                                        id="winGlow"
                                        x="-120%"
                                        y="-120%"
                                        width="340%"
                                        height="340%"
                                    >
                                        <feGaussianBlur stdDeviation="3.2" result="b" />
                                        <feMerge>
                                            <feMergeNode in="b" />
                                            <feMergeNode in="SourceGraphic" />
                                        </feMerge>
                                    </filter>
                                </defs>

                                <!-- under-glow beneath the floating island -->
                                <ellipse
                                    class="glow"
                                    cx="130"
                                    cy="228"
                                    rx="82"
                                    ry="13"
                                    fill="url(#gUnder)"
                                />

                                {#if owned.has("balloon")}
                                    <g class="balloon">
                                        <path
                                            d="M215,12 C205,12 201,22 201,27 C201,35 208,40 215,47 C222,40 229,35 229,27 C229,22 225,12 215,12 Z"
                                            fill="url(#gBalloon)"
                                        />
                                        <path
                                            d="M215,12 C210,21 210,34 215,47"
                                            fill="none"
                                            stroke="rgba(255,220,190,0.28)"
                                            stroke-width="1"
                                        />
                                        <path
                                            d="M215,12 C220,21 220,34 215,47"
                                            fill="none"
                                            stroke="rgba(74,13,24,0.32)"
                                            stroke-width="1"
                                        />
                                        <ellipse
                                            cx="209.5"
                                            cy="22"
                                            rx="3.2"
                                            ry="5"
                                            fill="rgba(255,236,214,0.28)"
                                        />
                                        <line
                                            x1="207.5"
                                            y1="42"
                                            x2="213"
                                            y2="48"
                                            stroke="#5a3d24"
                                            stroke-width="0.8"
                                        />
                                        <line
                                            x1="222.5"
                                            y1="42"
                                            x2="217"
                                            y2="48"
                                            stroke="#5a3d24"
                                            stroke-width="0.8"
                                        />
                                        <path
                                            d="M212,48 L218,48 L217,53 L213,53 Z"
                                            fill="#7a5636"
                                        />
                                        <path
                                            d="M212,48 L218,48 L217.6,50 L212.4,50 Z"
                                            fill="#95744d"
                                        />
                                    </g>
                                {/if}

                                <!-- floating island (isometric slab with extruded sides).
                                 Side tops overlap under the top face so no sky shows at the seams. -->
                                <polygon
                                    points="49.8,148 130,190 130,219 49.8,176"
                                    fill="url(#gSideL)"
                                />
                                <polygon
                                    points="130,190 210.2,148 210.2,176 130,219"
                                    fill="url(#gSideR)"
                                />
                                <path
                                    d="M145.8,96.6 L210.2,131.4 Q226,140 210.2,148.6 L145.8,183.4 Q130,192 114.2,183.4 L49.8,148.6 Q34,140 49.8,131.4 L114.2,96.6 Q130,88 145.8,96.6 Z"
                                    fill="url(#gTop)"
                                />
                                <!-- rim light on the top edge -->
                                <path
                                    d="M49.8,131.4 Q34,140 49.8,148.6 L114.2,183.4 Q130,192 145.8,183.4 L210.2,148.6"
                                    fill="none"
                                    stroke="rgba(255,240,205,0.6)"
                                    stroke-width="1.5"
                                    stroke-linecap="round"
                                />

                                {#if owned.has("pond")}
                                    <ellipse
                                        cx="98"
                                        cy="159"
                                        rx="15"
                                        ry="6.5"
                                        fill="url(#gPond)"
                                    />
                                    <ellipse
                                        cx="92"
                                        cy="156.5"
                                        rx="5"
                                        ry="1.6"
                                        fill="#f2fafe"
                                        opacity="0.85"
                                    />
                                {/if}

                                {#if owned.has("path")}
                                    <!-- straight walkway from the front-right wall to the island edge -->
                                    <polygon
                                        points="136.3,147.6 153.1,138.4 190,158.4 173.2,167.6"
                                        fill="#c9c1b4"
                                    />
                                    <polygon
                                        points="136.3,147.6 153.1,138.4 190,158.4 173.2,167.6"
                                        fill="none"
                                        stroke="#a99f8d"
                                        stroke-width="1"
                                    />
                                    <line
                                        x1="148.5"
                                        y1="154.2"
                                        x2="165.3"
                                        y2="145"
                                        stroke="#a99f8d"
                                        stroke-width="1"
                                    />
                                    <line
                                        x1="160.7"
                                        y1="160.8"
                                        x2="177.5"
                                        y2="151.6"
                                        stroke="#a99f8d"
                                        stroke-width="1"
                                    />
                                {/if}

                                {#if owned.has("hedges")}
                                    <!-- back half of the rim hedge (behind the house) -->
                                    <path
                                        d="M44,140 L130,98 L216,140"
                                        fill="none"
                                        stroke="#3f7a4a"
                                        stroke-width="9"
                                        stroke-linejoin="round"
                                        stroke-linecap="round"
                                    />
                                    <path
                                        d="M44,138 L130,96 L216,138"
                                        fill="none"
                                        stroke="#7cb073"
                                        stroke-width="4"
                                        stroke-linejoin="round"
                                        stroke-linecap="round"
                                    />
                                {/if}

                                {#if owned.has("fountain")}
                                    <ellipse
                                        cx="126"
                                        cy="168"
                                        rx="12"
                                        ry="5"
                                        fill="#bbb2a3"
                                    />
                                    <ellipse
                                        cx="126"
                                        cy="167"
                                        rx="9"
                                        ry="3.6"
                                        fill="url(#gPond)"
                                    />
                                    <rect
                                        x="124.5"
                                        y="158"
                                        width="3"
                                        height="10"
                                        rx="1.5"
                                        fill="#bbb2a3"
                                    />
                                    <ellipse
                                        cx="126"
                                        cy="158"
                                        rx="5"
                                        ry="2"
                                        fill="#bbb2a3"
                                    />
                                    <ellipse
                                        cx="126"
                                        cy="157.5"
                                        rx="3.5"
                                        ry="1.4"
                                        fill="url(#gPond)"
                                    />
                                {/if}

                                {#if owned.has("orchard")}
                                    <!-- a real garden bed: soil, rows, and fruit/veg -->
                                    <polygon
                                        points="66,131 82,138 66,145 50,138"
                                        fill="#5a3d24"
                                    />
                                    <polygon
                                        points="66,131 82,138 66,145 50,138"
                                        fill="none"
                                        stroke="#6b4a2b"
                                        stroke-width="1"
                                    />
                                    <line
                                        x1="57"
                                        y1="135"
                                        x2="73"
                                        y2="141"
                                        stroke="#7a5636"
                                        stroke-width="1"
                                    />
                                    <line
                                        x1="61"
                                        y1="133"
                                        x2="77"
                                        y2="139"
                                        stroke="#7a5636"
                                        stroke-width="1"
                                    />
                                    <circle cx="60" cy="137" r="2" fill="#5a8a52" />
                                    <circle cx="66" cy="140" r="2" fill="#c0392b" />
                                    <circle cx="72" cy="137" r="2.1" fill="#e67e22" />
                                    <circle cx="66" cy="134.5" r="2" fill="#5a8a52" />
                                    <circle cx="70" cy="141" r="2" fill="#c0392b" />
                                {/if}

                                {#if owned.has("garden")}
                                    <ellipse
                                        cx="188"
                                        cy="149"
                                        rx="10"
                                        ry="3.4"
                                        fill="rgba(58,40,25,0.22)"
                                    />
                                    <rect
                                        x="185.6"
                                        y="132"
                                        width="4.8"
                                        height="16"
                                        rx="2"
                                        fill="#6b4a2b"
                                    />
                                    <circle
                                        cx="188"
                                        cy="128"
                                        r="12"
                                        fill="url(#gLeaf)"
                                    />
                                    <circle
                                        cx="181"
                                        cy="133"
                                        r="7.5"
                                        fill="url(#gLeaf)"
                                    />
                                    <circle
                                        cx="195"
                                        cy="133"
                                        r="7.5"
                                        fill="url(#gLeaf)"
                                    />
                                    <ellipse
                                        cx="98"
                                        cy="146"
                                        rx="9"
                                        ry="5.5"
                                        fill="url(#gLeaf)"
                                    />
                                    <ellipse
                                        cx="108"
                                        cy="149"
                                        rx="6"
                                        ry="4"
                                        fill="url(#gLeaf)"
                                    />
                                {/if}

                                {#if owned.has("tower")}
                                    <!-- behind the main house -->
                                    <polygon
                                        points="132,100 150,110 150,62 132,52"
                                        fill="url(#gWallL)"
                                    />
                                    <polygon
                                        points="150,110 168,100 168,52 150,62"
                                        fill="url(#gWallR)"
                                    />
                                    <polygon
                                        points="132,52 150,62 150,30"
                                        fill="url(#gRoofL)"
                                    />
                                    <polygon
                                        points="150,62 168,52 150,30"
                                        fill="url(#gRoofR)"
                                    />
                                    <polygon
                                        points="153,86 163,80.5 163,68.5 153,74"
                                        fill="url(#gWin)"
                                        opacity={owned.has("lights") ? "1" : "0.7"}
                                        filter="url(#winGlow)"
                                        class:lit={owned.has("lights")}
                                    />
                                {/if}

                                {#if owned.has("lights")}
                                    <!-- warm light spilling onto the island -->
                                    <ellipse
                                        cx="130"
                                        cy="168"
                                        rx="52"
                                        ry="18"
                                        fill="url(#gSpill)"
                                    />
                                {/if}

                                <!-- main house (isometric) -->
                                <g filter="url(#dropSoft)">
                                    <polygon
                                        points="88,128 130,151 130,111 88,88"
                                        fill="url(#gWallL)"
                                    />
                                    <polygon
                                        points="130,151 172,128 172,88 130,111"
                                        fill="url(#gWallR)"
                                    />
                                    <polygon
                                        points="88,88 130,111 130,48"
                                        fill="url(#gRoofL)"
                                    />
                                    <polygon
                                        points="130,111 172,88 130,48"
                                        fill="url(#gRoofR)"
                                    />
                                    <!-- ridge highlight -->
                                    <line
                                        x1="130"
                                        y1="48"
                                        x2="130"
                                        y2="111"
                                        stroke="rgba(255,220,180,0.35)"
                                        stroke-width="1.2"
                                    />
                                </g>

                                {#if owned.has("lamps")}
                                    <!-- lanterns, symmetric on both sides of the path; drawn
                                     above the house so its shadow doesn't swallow them -->
                                    <line
                                        x1="167.2"
                                        y1="144.7"
                                        x2="167.2"
                                        y2="134.7"
                                        stroke="#4a0d18"
                                        stroke-width="1.6"
                                    />
                                    <circle
                                        cx="167.2"
                                        cy="132.7"
                                        r="3"
                                        fill="url(#gWin)"
                                        filter="url(#winGlow)"
                                    />
                                    <line
                                        x1="182"
                                        y1="152.7"
                                        x2="182"
                                        y2="142.7"
                                        stroke="#4a0d18"
                                        stroke-width="1.6"
                                    />
                                    <circle
                                        cx="182"
                                        cy="140.7"
                                        r="3"
                                        fill="url(#gWin)"
                                        filter="url(#winGlow)"
                                    />
                                    <line
                                        x1="148"
                                        y1="155.3"
                                        x2="148"
                                        y2="145.3"
                                        stroke="#4a0d18"
                                        stroke-width="1.6"
                                    />
                                    <circle
                                        cx="148"
                                        cy="143.3"
                                        r="3"
                                        fill="url(#gWin)"
                                        filter="url(#winGlow)"
                                    />
                                    <line
                                        x1="162.8"
                                        y1="163.3"
                                        x2="162.8"
                                        y2="153.3"
                                        stroke="#4a0d18"
                                        stroke-width="1.6"
                                    />
                                    <circle
                                        cx="162.8"
                                        cy="151.3"
                                        r="3"
                                        fill="url(#gWin)"
                                        filter="url(#winGlow)"
                                    />
                                {/if}

                                {#if owned.has("hedges")}
                                    <!-- front half of the rim hedge, drawn above the lamps -->
                                    <path
                                        d="M44,140 L130,182 L216,140"
                                        fill="none"
                                        stroke="#3f7a4a"
                                        stroke-width="9"
                                        stroke-linejoin="round"
                                        stroke-linecap="round"
                                    />
                                    <path
                                        d="M44,138 L130,180 L216,138"
                                        fill="none"
                                        stroke="#7cb073"
                                        stroke-width="4"
                                        stroke-linejoin="round"
                                        stroke-linecap="round"
                                    />
                                {/if}

                                {#if owned.has("observatory")}
                                    <!-- rooftop dome on the right roof slope, clear of the peak/banner -->
                                    <ellipse
                                        cx="148"
                                        cy="86"
                                        rx="11"
                                        ry="4.5"
                                        fill="#7a1a29"
                                    />
                                    <path
                                        d="M137,86 A11,10 0 0 1 159,86 Z"
                                        fill="url(#gDome)"
                                    />
                                    <!-- open telescope slit so it reads as an observatory -->
                                    <path
                                        d="M146.4,86 L146.4,78 A1.9,1.9 0 0 1 149.6,78 L149.6,86 Z"
                                        fill="#2c1b1e"
                                        opacity="0.55"
                                    />
                                {/if}

                                {#if owned.has("flag")}
                                    <line
                                        x1="130"
                                        y1="48"
                                        x2="130"
                                        y2="29"
                                        stroke="#4a0d18"
                                        stroke-width="1.6"
                                        stroke-linecap="round"
                                    />
                                    <polygon
                                        points="130,30 147,34.5 130,39"
                                        fill="url(#gRoofR)"
                                    />
                                    <circle cx="130" cy="28" r="1.8" fill="#c89b3c" />
                                {/if}

                                {#if owned.has("lights")}
                                    <!-- shutters framing each window -->
                                    <polygon
                                        points="137.7,132.76 141.9,130.48 141.9,116.48 137.7,118.76"
                                        fill="url(#gRoofR)"
                                    />
                                    <polygon
                                        points="160.1,120.52 164.3,118.24 164.3,104.24 160.1,106.52"
                                        fill="url(#gRoofR)"
                                    />
                                    <polygon
                                        points="118.1,130.48 122.5,132.76 122.5,118.76 118.1,116.48"
                                        fill="url(#gRoofL)"
                                    />
                                    <polygon
                                        points="99.9,120.52 95.7,118.24 95.7,104.24 99.9,106.52"
                                        fill="url(#gRoofL)"
                                    />
                                {/if}

                                <!-- glowing windows (one per visible wall) -->
                                <polygon
                                    points="117.4,130.1 100.6,120.9 100.6,106.9 117.4,116.1"
                                    fill="url(#gWin)"
                                    opacity={owned.has("lights") ? "1" : "0.72"}
                                    filter="url(#winGlow)"
                                    class:lit={owned.has("lights")}
                                />
                                <polygon
                                    points="142.6,130.1 159.4,120.9 159.4,106.9 142.6,116.1"
                                    fill="url(#gWin)"
                                    opacity={owned.has("lights") ? "1" : "0.72"}
                                    filter="url(#winGlow)"
                                    class:lit={owned.has("lights")}
                                />
                            </svg>
                        </div>
                        {#if view === "hub"}
                            <span class="hint" transition:fade={{ duration: 300 }}>
                                Tap your homebase to begin
                            </span>
                        {/if}
                    </button>
                </div>
            {/if}

            {#if view === "menu"}
                <div class="reveal">
                    <!-- Homebase coins + upgrade shop (desktop only) -->
                    {#if !mobile}
                        <section
                            class="homebar"
                            in:fly={{
                                y: 20,
                                duration: 450,
                                delay: 40,
                                easing: backOut,
                            }}
                        >
                            <div class="homebar-info">
                                <span class="homebar-title">Your homebase</span>
                                <span class="homebar-sub">
                                    {coins.toLocaleString()} coins · {owned.size}/{catalog.length}
                                    upgrades
                                </span>
                            </div>
                            <button
                                class="customize"
                                on:click={() => (showShop = !showShop)}
                            >
                                {showShop ? "Close" : "Customize"}
                            </button>
                        </section>
                    {/if}

                    {#if showShop && !mobile}
                        <section
                            class="shop"
                            transition:fly={{ y: -8, duration: 300, easing: cubicOut }}
                        >
                            {#each catalog as u}
                                <div class="up" class:owned={u.owned}>
                                    <div class="up-text">
                                        <span class="up-name">{u.name}</span>
                                        <span class="up-desc">{u.desc}</span>
                                    </div>
                                    {#if u.owned}
                                        <span class="up-owned">Owned</span>
                                    {:else}
                                        <button
                                            class="up-buy"
                                            disabled={coins < u.cost}
                                            on:click={() => buyUpgrade(u.id)}
                                        >
                                            <span class="up-price">
                                                {u.cost.toLocaleString()}
                                            </span>
                                            <small>coins</small>
                                        </button>
                                    {/if}
                                </div>
                            {/each}
                        </section>
                    {/if}

                    {#if profile?.name || plan}
                        <section
                            class="planstrip"
                            in:fly={{
                                y: 20,
                                duration: 450,
                                delay: 110,
                                easing: backOut,
                            }}
                        >
                            <div class="greet">
                                {profile?.name
                                    ? `Hi, ${profile.name}.`
                                    : "Welcome back."}
                                <span class="greet-sub">Let's get you ready.</span>
                            </div>
                            {#if plan}
                                <div class="planinfo">
                                    <span class="planday">
                                        Day {plan.dayNumber}
                                        <span class="planday-of">
                                            / {plan.totalDays}
                                        </span>
                                    </span>
                                    <span class="planmeta">
                                        {plan.dailyHours} hrs/day · through {niceDate(
                                            plan.endDate,
                                        )}
                                    </span>
                                </div>
                            {/if}
                        </section>
                    {/if}

                    <!-- Word of the day -->
                    <section
                        class="wotd"
                        in:fly={{ y: 24, duration: 500, delay: 180, easing: backOut }}
                    >
                        <div class="wotd-head">
                            <span class="eyebrow">Word of the day</span>
                            {#if words.length}
                                <div class="nav">
                                    <button
                                        class="navbtn"
                                        on:click={prevWord}
                                        disabled={wordIndex <= 0}
                                        aria-label="Previous word"
                                    >
                                        ‹
                                    </button>
                                    <span class="navcount">
                                        {wordIndex + 1}/{words.length}
                                    </span>
                                    <button
                                        class="navbtn"
                                        on:click={nextWord}
                                        disabled={wordIndex >= words.length - 1}
                                        aria-label="Next word"
                                    >
                                        ›
                                    </button>
                                </div>
                            {/if}
                        </div>

                        {#if current}
                            <div class="wotd-body">
                                <span class="word">{current.word}</span>
                                <span class="pos">{current.pos}</span>
                            </div>
                            <p class="def">{current.def}</p>
                            {#if current.example}
                                <p class="example">"{current.example}"</p>
                            {/if}
                            {#if quizOrder.length}
                                <div class="quiz">
                                    <span class="quiz-q">
                                        Which sentence uses "{current.word}" correctly?
                                    </span>
                                    <div class="quiz-opts">
                                        {#each quizOrder as o}
                                            <button
                                                class="quiz-opt"
                                                class:correct={quizPick && o.correct}
                                                class:wrong={quizPick === o.text &&
                                                    !o.correct}
                                                class:dim={quizPick &&
                                                    quizPick !== o.text &&
                                                    !o.correct}
                                                disabled={!!quizPick}
                                                on:click={() => pick(o)}
                                            >
                                                {o.text}
                                            </button>
                                        {/each}
                                    </div>
                                    {#if quizPick}
                                        <span
                                            class="quiz-fb"
                                            class:good={quizPickCorrect}
                                        >
                                            {quizPickCorrect
                                                ? "Correct — that's the right usage."
                                                : "Not quite — the highlighted sentence is the correct usage."}
                                        </span>
                                    {/if}
                                </div>
                            {/if}
                        {:else}
                            <p class="def">Getting your first word…</p>
                        {/if}

                        <div class="wotd-actions">
                            <button class="primary" on:click={reviewVocab}>
                                Review my vocab ({vocabCount})
                            </button>
                            <button class="ghost" on:click={addWord}>
                                Add another word
                            </button>
                        </div>
                    </section>

                    <!-- Lesson + Socratic: two big icon tiles, side by side -->
                    <div class="cta-row">
                        <!-- Adaptive timed lesson: the main event -->
                        <button
                            class="lesson-cta"
                            on:click={startLesson}
                            in:fly={{
                                y: 24,
                                duration: 500,
                                delay: 250,
                                easing: backOut,
                            }}
                        >
                            <span class="cta-icon" aria-hidden="true">
                                <!-- classroom: a chalkboard on an easel -->
                                <svg class="cta-svg" viewBox="0 0 48 48">
                                    <rect
                                        x="8"
                                        y="7"
                                        width="32"
                                        height="23"
                                        rx="2.5"
                                        fill="#4a0d18"
                                        stroke="#f6edda"
                                        stroke-width="2.4"
                                    />
                                    <path
                                        d="M13 24 L20 19 L27 22 L35 13"
                                        fill="none"
                                        stroke="#e0a83a"
                                        stroke-width="2.2"
                                        stroke-linecap="round"
                                        stroke-linejoin="round"
                                    />
                                    <rect
                                        x="10"
                                        y="30"
                                        width="28"
                                        height="2.6"
                                        rx="1.3"
                                        fill="#f6edda"
                                    />
                                    <path
                                        d="M14 32 L10 42 M34 32 L38 42 M24 32 L24 42"
                                        stroke="#f6edda"
                                        stroke-width="2.2"
                                        stroke-linecap="round"
                                    />
                                </svg>
                            </span>
                            <span class="lesson-title">Start lesson</span>
                            <span class="cta-meta">2 hours · 100 coins / correct</span>
                        </button>

                        <!-- Socratic Station -->
                        <button
                            class="socratic-cta"
                            on:click={openSocratic}
                            in:fly={{
                                y: 24,
                                duration: 500,
                                delay: 320,
                                easing: backOut,
                            }}
                        >
                            <span class="cta-icon" aria-hidden="true">
                                <!-- the same little train from the arrival animation -->
                                <svg class="cta-svg" viewBox="0 0 48 48">
                                    <rect
                                        x="5"
                                        y="38"
                                        width="38"
                                        height="2.4"
                                        rx="1.2"
                                        fill="#6e1423"
                                        opacity="0.35"
                                    />
                                    <rect
                                        x="27"
                                        y="10"
                                        width="5"
                                        height="9"
                                        rx="1.5"
                                        fill="#4a0d18"
                                    />
                                    <circle
                                        cx="29.5"
                                        cy="7"
                                        r="2.4"
                                        fill="#6e1423"
                                        opacity="0.3"
                                    />
                                    <rect
                                        x="7"
                                        y="15"
                                        width="30"
                                        height="5"
                                        rx="2"
                                        fill="#4a0d18"
                                    />
                                    <rect
                                        x="9"
                                        y="18"
                                        width="26"
                                        height="16"
                                        rx="3"
                                        fill="#6e1423"
                                    />
                                    <rect
                                        x="13"
                                        y="21"
                                        width="9"
                                        height="8"
                                        rx="1.5"
                                        fill="#e0a83a"
                                    />
                                    <rect
                                        x="35"
                                        y="22"
                                        width="6"
                                        height="12"
                                        rx="2"
                                        fill="#8c1c2b"
                                    />
                                    <circle cx="16" cy="35" r="4" fill="#4a0d18" />
                                    <circle cx="30" cy="35" r="4" fill="#4a0d18" />
                                    <circle cx="16" cy="35" r="1.5" fill="#f6edda" />
                                    <circle cx="30" cy="35" r="1.5" fill="#f6edda" />
                                </svg>
                            </span>
                            <span class="lesson-title">Socratic Station</span>
                            <span class="cta-meta">
                                Talk it out · 500 coins / correct
                            </span>
                        </button>
                    </div>

                    <!-- Scores -->
                    <section
                        class="dashboard"
                        in:fly={{ y: 24, duration: 500, delay: 390, easing: backOut }}
                    >
                        <div class="dash-head">
                            <h2>Your scores</h2>
                            <span class="reviews">
                                {gradedReviews} graded review{gradedReviews === 1
                                    ? ""
                                    : "s"}
                                · {Math.round(topicCoverage * 100)}% of exam covered
                            </span>
                        </div>

                        <div class="score-grid">
                            {#each SCORE_META as meta}
                                {@const sc = state?.scores?.[meta.key]}
                                <button
                                    class="score-card"
                                    class:locked={!sc?.available}
                                    class:open={openScore === meta.key}
                                    on:click={() => toggleScore(meta.key)}
                                >
                                    <div class="score-top">
                                        <span class="score-label">{meta.label}</span>
                                        {#if sc?.available}
                                            <span class="score-conf">
                                                {Math.round(sc.confidence * 100)}% conf.
                                            </span>
                                        {/if}
                                    </div>
                                    {#if sc?.available}
                                        <div class="score-value">{sc.value}</div>
                                        <div class="score-range">likely {sc.range}</div>
                                    {:else}
                                        <div class="score-value muted">
                                            Not enough data yet
                                        </div>
                                    {/if}
                                    <div class="score-why">
                                        {openScore === meta.key
                                            ? "Hide details"
                                            : "Why this score?"}
                                    </div>
                                    {#if openScore === meta.key}
                                        <ul class="reasons">
                                            {#each sc?.reasons ?? [] as r}
                                                <li>{r}</li>
                                            {/each}
                                            {#if sc?.available}
                                                <li>
                                                    Based on {sc.sampleSize} data point{sc.sampleSize ===
                                                    1
                                                        ? ""
                                                        : "s"}.
                                                </li>
                                            {/if}
                                        </ul>
                                    {/if}
                                </button>
                            {/each}
                        </div>

                        <div class="next">
                            <span class="next-label">Next best step</span>
                            <span class="next-text">{nextStep}</span>
                        </div>

                        {#if missing.length}
                            <div class="missing">
                                <span class="next-label">
                                    Still needed before a Readiness score
                                </span>
                                <ul>
                                    {#each missing as m}
                                        <li>{m}</li>
                                    {/each}
                                </ul>
                            </div>
                        {/if}

                        {#if practicedTypes.length}
                            <div class="types">
                                <span class="next-label">
                                    Logical Reasoning by question type
                                </span>
                                <ul class="type-list">
                                    {#each typeBreakdown as t}
                                        <li
                                            class="type-row"
                                            class:untried={t.total === 0}
                                        >
                                            <span class="type-name">{t.type}</span>
                                            {#if t.accuracy !== null}
                                                <span
                                                    class="type-acc"
                                                    class:weak={(t.accuracy ?? 1) < 0.6}
                                                >
                                                    {Math.round(
                                                        (t.accuracy ?? 0) * 100,
                                                    )}%
                                                </span>
                                            {:else if t.total === 0}
                                                <span class="type-note">
                                                    not tried yet
                                                </span>
                                            {:else}
                                                <span class="type-note">
                                                    {t.needed} more to score
                                                </span>
                                            {/if}
                                        </li>
                                    {/each}
                                </ul>
                                <span class="type-foot">
                                    Lessons steer toward your weakest types first.
                                </span>
                            </div>
                        {/if}
                    </section>
                </div>
            {/if}
        </main>
    {/if}

    {#if showTour}
        <Walkthrough steps={TOUR_STEPS} on:done={() => (showTour = false)} />
    {/if}
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
        --gold: #c89b3c;
        /* pale-blue sky */
        --sky-top: #cfe6f5;
        --sky-bot: #eaf4fb;

        position: relative;
        /* Own the scroll so the sticky top bar sticks to the viewport instead of
           scrolling away (overflow-x:hidden alone made this the sticky container
           while the page itself scrolled). */
        height: 100vh;
        overflow-y: auto;
        overflow-x: hidden;
        background: linear-gradient(
            180deg,
            var(--sky-top) 0%,
            var(--sky-bot) 46%,
            var(--beige) 100%
        );
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

    /* ---- sky decoration ---- */
    .sky {
        position: fixed;
        inset: 0;
        pointer-events: none;
        z-index: 0;
        overflow: hidden;
    }
    .cloud {
        position: absolute;
        background: rgba(255, 255, 255, 0.75);
        border-radius: 999px;
        filter: blur(6px);
        opacity: 0.8;
    }
    .cloud.c1 {
        top: 12%;
        left: -12%;
        width: 220px;
        height: 58px;
        animation: drift 60s linear infinite;
    }
    .cloud.c2 {
        top: 26%;
        left: -20%;
        width: 320px;
        height: 74px;
        animation: drift 90s linear infinite;
        animation-delay: -20s;
    }
    .cloud.c3 {
        top: 6%;
        left: -15%;
        width: 160px;
        height: 46px;
        animation: drift 75s linear infinite;
        animation-delay: -50s;
    }
    @keyframes drift {
        from {
            transform: translateX(0);
        }
        to {
            transform: translateX(140vw);
        }
    }
    /* Sunset sky: top-to-bottom purple -> pink -> red -> orange -> yellow */
    .sunset {
        position: absolute;
        inset: 0;
        background: linear-gradient(
            180deg,
            #5b2a86 0%,
            #a3439b 24%,
            #e0518f 44%,
            #e0403f 62%,
            #f2842e 82%,
            #f7d774 100%
        );
    }

    button {
        font: inherit;
        cursor: pointer;
        border: none;
        background: none;
        color: inherit;
    }

    .bar {
        position: sticky;
        top: 0;
        z-index: 3;
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0.8rem 1.5rem;
        background: var(--maroon);
        color: var(--beige);

        .brand {
            font-weight: 800;
            font-size: 2rem;
            letter-spacing: 0.01em;
            line-height: 1;
        }
    }
    .bar-right {
        display: flex;
        align-items: center;
        gap: 0.7rem;
    }
    .coins {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        padding: 0.35rem 0.7rem;
        border-radius: 999px;
        background: rgba(246, 237, 218, 0.16);
        border: 1px solid rgba(246, 237, 218, 0.4);
        color: var(--gold);
        font-weight: 700;
        font-size: 0.85rem;
        font-variant-numeric: tabular-nums;
    }
    .coin-icon {
        width: 0.95em;
        height: 0.95em;
        border-radius: 50%;
        flex: none;
        background: radial-gradient(
            circle at 35% 30%,
            #ffe6a3 0%,
            #f4c744 45%,
            #c8901f 100%
        );
        box-shadow:
            inset 0 0 0 1px rgba(140, 92, 12, 0.55),
            inset 1px 1px 1.5px rgba(255, 255, 255, 0.6);
    }
    .sync {
        padding: 0.45rem 0.9rem;
        border: 1px solid rgba(246, 237, 218, 0.5);
        border-radius: 8px;
        color: var(--beige);
        font-weight: 600;
        transition: background 120ms ease;
        &:hover {
            background: rgba(246, 237, 218, 0.12);
        }
        &.on {
            border-color: var(--beige);
        }
    }
    .help {
        width: 1.9rem;
        height: 1.9rem;
        display: grid;
        place-items: center;
        border-radius: 50%;
        border: 1px solid rgba(246, 237, 218, 0.5);
        color: var(--beige);
        font-weight: 800;
        font-size: 0.95rem;
        line-height: 1;
        transition: background 120ms ease;
        &:hover {
            background: rgba(246, 237, 218, 0.12);
        }
    }
    .mini {
        padding: 0.4rem 0.7rem;
        border: 1px solid rgba(246, 237, 218, 0.35);
        border-radius: 8px;
        color: rgba(246, 237, 218, 0.85);
        font-weight: 600;
        font-size: 0.82rem;
        transition:
            background 120ms ease,
            border-color 120ms ease,
            color 120ms ease;
        &:hover {
            background: rgba(246, 237, 218, 0.12);
            color: var(--beige);
        }
    }

    /* ---- login gate ---- */
    .gate {
        position: relative;
        z-index: 1;
        min-height: calc(100vh - 4rem);
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 2rem 1.5rem;
    }
    .gate-card {
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        gap: 0.6rem;
        max-width: 26rem;
        padding: 2.4rem 2rem;
        background: var(--paper);
        border: 1px solid var(--beige-deep);
        border-radius: 18px;
        box-shadow: 0 18px 44px rgba(74, 13, 24, 0.16);
    }
    .gate-brand {
        font-weight: 800;
        font-size: 2.4rem;
        line-height: 1;
        color: var(--maroon-deep);
    }
    .gate-tag {
        margin: 0.2rem 0 0.4rem;
        color: var(--muted);
        font-size: 1rem;
    }
    .gate-btn {
        margin-top: 0.4rem;
        padding: 0.85rem 2rem;
        border-radius: 10px;
        font-weight: 800;
        font-size: 1.05rem;
        color: var(--beige);
        background: var(--maroon);
        box-shadow: 0 8px 20px rgba(74, 13, 24, 0.22);
        transition:
            background 120ms ease,
            transform 120ms ease;
        &:hover {
            background: var(--maroon-bright);
            transform: translateY(-2px);
        }
    }
    .gate-note {
        margin: 0.6rem 0 0;
        color: var(--muted);
        font-size: 0.82rem;
        line-height: 1.5;
    }

    /* ---- sign-out confirmation modal ---- */
    .modal-scrim {
        position: fixed;
        inset: 0;
        z-index: 50;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 1.5rem;
        background: rgba(44, 27, 30, 0.62);
    }
    .logout-card {
        position: relative;
        z-index: 1;
        display: block;
        max-width: 24rem;
        width: 100%;
        background: #fffdf6;
        border: 1px solid var(--beige-deep);
        border-radius: 16px;
        padding: 1.6rem 1.5rem 1.3rem;
        box-shadow: 0 20px 50px rgba(74, 13, 24, 0.28);
        h3 {
            margin: 0 0 0.6rem;
            color: var(--maroon-deep);
            font-size: 1.3rem;
            font-weight: 800;
        }
        p {
            margin: 0;
            color: var(--muted);
            font-size: 0.9rem;
            line-height: 1.55;
        }
    }
    .modal-actions {
        margin-top: 1.3rem;
        display: flex;
        justify-content: flex-end;
        gap: 0.6rem;
    }
    .modal-cancel,
    .modal-confirm {
        padding: 0.55rem 1.2rem;
        border-radius: 9px;
        font-weight: 700;
        font-size: 0.9rem;
        transition:
            background 120ms ease,
            transform 80ms ease;
    }
    .modal-cancel {
        color: var(--ink);
        background: var(--beige-deep);
        &:hover {
            background: #e0d3b3;
        }
    }
    .modal-confirm {
        color: var(--beige);
        background: var(--maroon);
        &:hover {
            background: var(--maroon-bright);
            transform: translateY(-1px);
        }
    }
    .reset-link {
        display: block;
        margin: 1rem auto 0;
        padding: 0.3rem 0.4rem;
        background: none;
        border: none;
        color: var(--muted);
        font-size: 0.78rem;
        text-decoration: underline;
        text-underline-offset: 2px;
        cursor: pointer;
        opacity: 0.75;
        &:hover {
            color: var(--maroon);
            opacity: 1;
        }
    }

    /* ---- stage + morphing homebase ---- */
    .stage {
        position: relative;
        z-index: 1;
        max-width: 54rem;
        margin: 0 auto;
        padding: 1rem 1.5rem 3.5rem;
    }
    .hero {
        display: flex;
        align-items: center;
        justify-content: center;
        transition: min-height 700ms cubic-bezier(0.22, 1, 0.36, 1);
    }
    .stage.hub .hero {
        min-height: 74vh;
    }
    .stage.menu .hero {
        min-height: 150px;
    }

    .homebase {
        position: relative;
        display: flex;
        flex-direction: column;
        align-items: center;
        padding: 0.5rem 1rem;
        -webkit-appearance: none;
        appearance: none;
        background: transparent;
        border-radius: 24px;
        transform-origin: center top;
        transition:
            transform 700ms cubic-bezier(0.22, 1, 0.36, 1),
            background 200ms ease;
        filter: drop-shadow(0 18px 26px rgba(74, 13, 24, 0.18));
    }
    .homebase:hover {
        background: rgba(255, 255, 255, 0.22);
    }
    .homebase:focus {
        outline: none;
    }
    .homebase:focus-visible {
        background: rgba(255, 255, 255, 0.28);
    }
    .stage.hub .homebase {
        transform: scale(1.34);
    }
    .stage.menu .homebase {
        transform: scale(0.82);
    }

    .float {
        animation: bob 5.5s ease-in-out infinite;
    }
    @keyframes bob {
        0%,
        100% {
            transform: translateY(0);
        }
        50% {
            transform: translateY(-10px);
        }
    }
    .glow {
        transform-box: fill-box;
        transform-origin: center;
        animation: glowpulse 5.5s ease-in-out infinite;
    }
    @keyframes glowpulse {
        0%,
        100% {
            opacity: 0.9;
            transform: scale(1);
        }
        50% {
            opacity: 0.6;
            transform: scale(0.9);
        }
    }
    .balloon {
        transform-box: fill-box;
        transform-origin: center;
        animation: balloondrift 7s ease-in-out infinite;
    }
    @keyframes balloondrift {
        0%,
        100% {
            transform: translate(0, 0);
        }
        50% {
            transform: translate(-6px, 5px);
        }
    }
    .lit {
        animation: flick 3.5s ease-in-out infinite;
        filter: drop-shadow(0 0 3px rgba(255, 200, 90, 0.8));
    }
    @keyframes flick {
        0%,
        100% {
            opacity: 1;
        }
        48% {
            opacity: 0.86;
        }
        52% {
            opacity: 1;
        }
    }
    .hint {
        margin-top: 0.4rem;
        font-size: 0.9rem;
        font-weight: 600;
        color: var(--maroon);
        background: rgba(255, 253, 246, 0.7);
        padding: 0.3rem 0.8rem;
        border-radius: 999px;
        animation: pulsehint 2.4s ease-in-out infinite;
    }
    @keyframes pulsehint {
        0%,
        100% {
            opacity: 0.7;
            transform: translateY(0);
        }
        50% {
            opacity: 1;
            transform: translateY(-2px);
        }
    }

    /* ---- homebase bar + shop ---- */
    .homebar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 1rem;
        background: var(--paper);
        border: 1px solid var(--beige-deep);
        border-radius: 12px;
        padding: 0.7rem 1rem;
        margin-bottom: 1rem;
        box-shadow: 0 4px 14px rgba(74, 13, 24, 0.06);
    }
    .homebar-title {
        display: block;
        font-weight: 800;
        color: var(--maroon-deep);
    }
    .homebar-sub {
        font-size: 0.8rem;
        color: var(--muted);
    }
    .customize {
        padding: 0.5rem 1rem;
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
    .shop {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 0.6rem;
        margin-bottom: 1.5rem;
    }
    .up {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 0.6rem;
        background: var(--paper);
        border: 1px solid var(--beige-deep);
        border-radius: 10px;
        padding: 0.7rem 0.85rem;
        &.owned {
            border-color: var(--green);
            background: #f0f6f1;
        }
    }
    .up-name {
        display: block;
        font-weight: 700;
        color: var(--maroon-deep);
    }
    .up-desc {
        font-size: 0.76rem;
        color: var(--muted);
    }
    .up-owned {
        color: var(--green);
        font-weight: 800;
        font-size: 0.8rem;
        white-space: nowrap;
    }
    .up-buy {
        display: flex;
        flex-direction: column;
        align-items: center;
        line-height: 1.1;
        padding: 0.4rem 0.7rem;
        border-radius: 8px;
        font-weight: 700;
        font-size: 0.8rem;
        color: var(--beige);
        background: var(--maroon);
        white-space: nowrap;
        transition:
            background 120ms ease,
            transform 80ms ease;
        &:hover:not(:disabled) {
            background: var(--maroon-bright);
            transform: translateY(-1px);
        }
        &:disabled {
            background: var(--beige-deep);
            color: var(--muted);
            cursor: default;
        }
        .up-price {
            font-size: 0.95rem;
            font-variant-numeric: tabular-nums;
        }
        small {
            color: var(--gold);
            font-size: 0.62rem;
            letter-spacing: 0.04em;
        }
        &:disabled small {
            color: var(--muted);
        }
    }

    /* ---- greeting / plan ---- */
    .planstrip {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 1rem;
        margin-bottom: 1.25rem;
        flex-wrap: wrap;
    }
    .greet {
        font-size: 1.35rem;
        font-weight: 800;
        color: var(--maroon-deep);
    }
    .greet-sub {
        display: block;
        font-size: 0.85rem;
        font-weight: 500;
        color: var(--muted);
    }
    .planinfo {
        text-align: right;
    }
    .planday {
        font-size: 1.1rem;
        font-weight: 800;
        color: var(--maroon);
    }
    .planday-of {
        color: var(--muted);
        font-weight: 600;
    }
    .planmeta {
        display: block;
        font-size: 0.78rem;
        color: var(--muted);
    }

    .eyebrow {
        text-transform: uppercase;
        font-size: 0.7rem;
        letter-spacing: 0.08em;
        color: var(--maroon-bright);
        font-weight: 800;
    }

    /* Two big icon tiles, side by side */
    .cta-row {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 1rem;
        margin-bottom: 1.5rem;
    }
    .cta-icon {
        flex: none;
        display: grid;
        place-items: center;
        width: 6rem;
        height: 6rem;
        border-radius: 20px;
    }
    .cta-svg {
        width: 5rem;
        height: 5rem;
        display: block;
    }
    .cta-meta {
        font-size: 0.82rem;
        font-weight: 600;
        opacity: 0.85;
    }

    .lesson-cta,
    .socratic-cta {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 0.85rem;
        min-width: 0;
        padding: 1.9rem 1.25rem;
        text-align: center;
        border-radius: 18px;
        transition:
            background 120ms ease,
            transform 120ms ease,
            box-shadow 120ms ease;
        &:hover {
            transform: translateY(-2px);
        }
        .lesson-title {
            font-weight: 800;
            font-size: 1.4rem;
            line-height: 1.1;
        }
    }

    .lesson-cta {
        color: var(--beige);
        background: var(--maroon);
        box-shadow: 0 10px 26px rgba(74, 13, 24, 0.22);
        &:hover {
            background: #7f2230;
            box-shadow: 0 14px 32px rgba(74, 13, 24, 0.3);
        }
        .cta-icon {
            background: rgba(246, 237, 218, 0.12);
            border: 1px solid rgba(246, 237, 218, 0.28);
        }
    }

    .socratic-cta {
        color: var(--maroon-deep);
        background: var(--beige-deep);
        border: 2px solid var(--maroon);
        &:hover {
            background: #e6d6b3;
        }
        .cta-icon {
            background: var(--beige);
            border: 1px solid rgba(110, 20, 35, 0.2);
        }
        .lesson-title {
            color: var(--maroon-deep);
        }
    }

    /* ---- word of the day ---- */
    .wotd {
        background: var(--paper);
        border: 1px solid var(--beige-deep);
        border-radius: 14px;
        padding: 1.1rem 1.25rem;
        margin-bottom: 1.5rem;
        box-shadow: 0 4px 14px rgba(74, 13, 24, 0.06);

        .wotd-body {
            display: flex;
            align-items: baseline;
            gap: 0.6rem;
            margin-top: 0.35rem;
        }
        .word {
            font-size: 1.7rem;
            font-weight: 800;
            color: var(--maroon-deep);
        }
        .pos {
            color: var(--muted);
            font-style: italic;
        }
        .def {
            margin: 0.4rem 0 0;
        }
        .example {
            margin: 0.3rem 0 0;
            color: var(--muted);
            font-style: italic;
        }
        .wotd-head {
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .nav {
            display: flex;
            align-items: center;
            gap: 0.4rem;
        }
        .navbtn {
            width: 1.5rem;
            height: 1.5rem;
            display: grid;
            place-items: center;
            border-radius: 6px;
            font-size: 1.1rem;
            line-height: 1;
            color: var(--maroon);
            background: var(--beige);
            border: 1px solid var(--beige-deep);
            transition:
                background 120ms ease,
                color 120ms ease;
            &:hover:not(:disabled) {
                background: var(--maroon);
                color: var(--beige);
            }
            &:disabled {
                opacity: 0.35;
                cursor: default;
            }
        }
        .navcount {
            font-size: 0.75rem;
            color: var(--muted);
            font-variant-numeric: tabular-nums;
            min-width: 2.2rem;
            text-align: center;
        }
        .quiz {
            margin-top: 0.9rem;
            padding-top: 0.85rem;
            border-top: 1px solid var(--beige-deep);
        }
        .quiz-q {
            display: block;
            font-weight: 600;
            font-size: 0.9rem;
            color: var(--maroon-deep);
            margin-bottom: 0.55rem;
        }
        .quiz-opts {
            display: flex;
            flex-direction: column;
            gap: 0.45rem;
        }
        .quiz-opt {
            text-align: left;
            padding: 0.6rem 0.75rem;
            border-radius: 8px;
            border: 1.5px solid var(--beige-deep);
            background: var(--beige);
            font-size: 0.9rem;
            line-height: 1.4;
            transition:
                border-color 120ms ease,
                background 120ms ease;
            &:hover:not(:disabled) {
                border-color: var(--maroon-bright);
            }
            &.correct {
                border-color: var(--green);
                background: #e4f0e8;
            }
            &.wrong {
                border-color: #b23a3a;
                background: #f7e1e1;
            }
            &.dim {
                opacity: 0.55;
            }
            &:disabled {
                cursor: default;
            }
        }
        .quiz-fb {
            display: block;
            margin-top: 0.55rem;
            font-size: 0.85rem;
            font-weight: 600;
            color: #b23a3a;
            &.good {
                color: var(--green);
            }
        }
        .wotd-actions {
            display: flex;
            gap: 0.6rem;
            margin-top: 0.9rem;
            flex-wrap: wrap;
        }
    }

    /* Bigger, thumb-friendly left/right word arrows at the top-right of the
       word-of-the-day box on the phone (desktop keeps the compact glyphs). */
    .stage.mobile .wotd .nav {
        gap: 0.5rem;
    }
    .stage.mobile .wotd .navbtn {
        width: 2.4rem;
        height: 2.4rem;
        font-size: 1.6rem;
        border-radius: 8px;
    }
    .stage.mobile .wotd .navcount {
        font-size: 0.85rem;
    }

    .primary {
        padding: 0.55rem 1.1rem;
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
    .ghost {
        padding: 0.55rem 0.9rem;
        border: 1px solid var(--beige-deep);
        border-radius: 8px;
        background: var(--beige);
        font-weight: 600;
        color: var(--maroon-deep);
        &:hover {
            border-color: var(--maroon-bright);
        }
    }

    /* ---- scores ---- */
    .dashboard {
        background: var(--paper);
        border: 1px solid var(--beige-deep);
        border-radius: 14px;
        padding: 1.25rem;
        margin-bottom: 1.5rem;
        box-shadow: 0 4px 14px rgba(74, 13, 24, 0.06);
    }
    .dash-head {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        margin-bottom: 1rem;
        h2 {
            margin: 0;
            font-size: 1.2rem;
            font-weight: 800;
            color: var(--maroon-deep);
        }
        .reviews {
            color: var(--muted);
            font-size: 0.85rem;
        }
    }
    .score-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 0.85rem;
    }
    .score-card {
        display: block;
        width: 100%;
        text-align: left;
        border: 1px solid var(--beige-deep);
        border-top: 4px solid var(--maroon);
        border-radius: 10px;
        padding: 0.9rem 1rem;
        background: var(--beige);
        transition:
            box-shadow 120ms ease,
            transform 80ms ease;
        &:hover {
            box-shadow: 0 6px 16px rgba(74, 13, 24, 0.12);
            transform: translateY(-1px);
        }
        &.open {
            box-shadow: 0 8px 20px rgba(74, 13, 24, 0.16);
        }
        &.locked {
            border-top-color: var(--beige-deep);
        }
        .score-top {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .score-label {
            font-weight: 800;
            color: var(--maroon-deep);
        }
        .score-conf {
            font-size: 0.72rem;
            color: var(--muted);
        }
        .score-value {
            font-size: 2rem;
            font-weight: 800;
            margin-top: 0.25rem;
            color: var(--maroon-deep);
            &.muted {
                font-size: 1rem;
                font-weight: 600;
                color: var(--muted);
            }
        }
        .score-range {
            color: var(--muted);
            font-size: 0.85rem;
        }
        .score-why {
            margin-top: 0.5rem;
            font-size: 0.72rem;
            font-weight: 700;
            color: var(--maroon-bright);
            letter-spacing: 0.02em;
        }
        .reasons {
            margin: 0.4rem 0 0;
            padding-left: 1.1rem;
            color: var(--muted);
            font-size: 0.78rem;
            li {
                margin-bottom: 0.15rem;
            }
        }
    }
    .next,
    .missing,
    .types {
        margin-top: 1.1rem;
        padding-top: 0.9rem;
        border-top: 1px solid var(--beige-deep);
    }
    .next {
        display: flex;
        flex-direction: column;
        gap: 0.15rem;
    }
    .next-label {
        text-transform: uppercase;
        font-size: 0.68rem;
        letter-spacing: 0.06em;
        color: var(--maroon-bright);
        font-weight: 800;
    }
    .next-text {
        font-weight: 600;
    }
    .missing ul {
        margin: 0.3rem 0 0;
        padding-left: 1.2rem;
        color: var(--muted);
        font-size: 0.85rem;
    }

    .type-list {
        list-style: none;
        margin: 0.45rem 0 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
    }
    .type-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 0.75rem;
        font-size: 0.88rem;
    }
    .type-row.untried {
        opacity: 0.6;
    }
    .type-name {
        font-weight: 600;
    }
    .type-acc {
        font-weight: 800;
        color: #2f7d43;
    }
    .type-acc.weak {
        color: var(--maroon-bright);
    }
    .type-note {
        font-size: 0.8rem;
        color: var(--muted);
    }
    .type-foot {
        display: block;
        margin-top: 0.5rem;
        font-size: 0.78rem;
        color: var(--muted);
        font-style: italic;
    }

    @media (max-width: 640px) {
        .score-grid {
            grid-template-columns: 1fr;
        }
        .shop {
            grid-template-columns: 1fr;
        }
    }
</style>
