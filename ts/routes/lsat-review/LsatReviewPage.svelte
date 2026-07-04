<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<script lang="ts">
    import { bridgeCommand, bridgeCommandsAvailable } from "@tslib/bridgecommand";
    import { onMount } from "svelte";

    type Card = {
        done: boolean;
        word?: string;
        pos?: string;
        def?: string;
        example?: string;
        remaining?: number;
    };

    let card: Card | null = null;
    let revealed = false;
    let reviewed = 0;

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
        revealed = false;
        card = await call<Card>("lsat:review:next");
    }

    function grade(rating: string): void {
        reviewed += 1;
        bridgeCommand(`lsat:review:answer:${rating}`);
        loadNext();
    }

    const exit = () => bridgeCommand("lsat:review:exit");

    onMount(loadNext);
</script>

<div class="lsat-app">
    <header class="bar">
        <button class="back" on:click={exit}>Home</button>
        <span class="title">Vocab</span>
        <span class="score">{card?.remaining ?? 0} left</span>
    </header>

    <main class="stage">
        {#if !card}
            <p class="loading">Loading…</p>
        {:else if card.done}
            <div class="done">
                <h1>All caught up.</h1>
                <p>
                    No vocab due right now.
                    {#if reviewed}You reviewed <b>{reviewed}</b>
                         this session.{/if}
                </p>
                <p class="hint">FSRS will resurface these when it's time.</p>
                <button class="cta" on:click={exit}>Back to home</button>
            </div>
        {:else}
            <article class="qcard">
                <div class="word">{card.word}</div>
                {#if card.pos}<div class="pos">{card.pos}</div>{/if}

                {#if !revealed}
                    <button class="cta reveal" on:click={() => (revealed = true)}>
                        Show definition
                    </button>
                {:else}
                    <div class="reveal-body">
                        <p class="def">{card.def}</p>
                        {#if card.example}
                            <p class="example">"{card.example}"</p>
                        {/if}
                    </div>
                    <div class="grade">
                        <button class="g again" on:click={() => grade("again")}>
                            Again
                        </button>
                        <button class="g good" on:click={() => grade("good")}>
                            Good
                        </button>
                        <button class="g easy" on:click={() => grade("easy")}>
                            Easy
                        </button>
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
        --muted: #7a6a63;
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
        }
        .score {
            font-variant-numeric: tabular-nums;
            opacity: 0.9;
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
        max-width: 42rem;
        margin: 0 auto;
        padding: 2rem 1.25rem 4rem;
    }

    .loading {
        color: var(--maroon);
        text-align: center;
        margin-top: 4rem;
    }

    .qcard {
        background: var(--paper);
        border: 1px solid var(--beige-deep);
        border-radius: 14px;
        padding: 2.25rem 1.75rem;
        text-align: center;
        box-shadow: 0 6px 20px rgba(74, 13, 24, 0.08);
    }

    .word {
        font-size: 2.4rem;
        font-weight: 800;
        color: var(--maroon-deep);
    }
    .pos {
        color: var(--muted);
        font-style: italic;
        margin-top: 0.25rem;
    }

    .reveal-body {
        margin-top: 1.4rem;
        padding-top: 1.4rem;
        border-top: 1px solid var(--beige-deep);
    }
    .def {
        font-size: 1.15rem;
        margin: 0;
    }
    .example {
        margin: 1rem 0 0;
        color: var(--maroon);
        font-style: italic;
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
            background: #7f2230;
            transform: translateY(-1px);
        }
    }
    .reveal {
        margin-top: 1.75rem;
    }

    .grade {
        display: flex;
        gap: 0.6rem;
        justify-content: center;
        margin-top: 1.75rem;
    }
    .g {
        flex: 1;
        max-width: 8rem;
        padding: 0.65rem 0.5rem;
        border-radius: 8px;
        font-weight: 700;
        border: 2px solid var(--beige-deep);
        background: var(--beige);
        transition:
            border-color 120ms ease,
            background 120ms ease,
            transform 80ms ease;
        &:hover {
            transform: translateY(-1px);
        }
        &.again:hover {
            border-color: var(--red);
            background: #f7e1e1;
        }
        &.good:hover {
            border-color: var(--maroon-bright);
        }
        &.easy:hover {
            border-color: var(--green);
            background: #e4f0e8;
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
