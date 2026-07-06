<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<script lang="ts">
    import { createEventDispatcher, onDestroy, onMount, tick } from "svelte";
    import { fade } from "svelte/transition";

    type TourStep = {
        sel: string;
        title: string;
        body: string;
        emphasis?: boolean;
    };
    type Rect = { top: number; left: number; width: number; height: number };

    export let steps: TourStep[] = [];

    const dispatch = createEventDispatcher();
    const PAD = 10;

    let i = 0;
    let rect: Rect | null = null;
    let cardH = 0;
    let cardW = 360;
    let vw = 0;
    let vh = 0;

    $: step = steps[i] ?? null;
    $: last = i >= steps.length - 1;

    function readViewport(): void {
        vw = window.innerWidth;
        vh = window.innerHeight;
        cardW = Math.min(360, vw - 24);
    }

    function updateRect(): void {
        const el = step ? document.querySelector(step.sel) : null;
        if (!el) {
            rect = null;
            return;
        }
        const r = el.getBoundingClientRect();
        rect = { top: r.top, left: r.left, width: r.width, height: r.height };
    }

    async function goTo(n: number): Promise<void> {
        i = Math.max(0, Math.min(steps.length - 1, n));
        await tick();
        const el = step ? document.querySelector(step.sel) : null;
        if (el) {
            el.scrollIntoView({ behavior: "smooth", block: "center" });
        }
        // Keep the spotlight glued to the target while the smooth scroll settles.
        const started = performance.now();
        const track = (): void => {
            updateRect();
            if (performance.now() - started < 550) {
                requestAnimationFrame(track);
            }
        };
        requestAnimationFrame(track);
    }

    function next(): void {
        if (last) {
            finish();
        } else {
            goTo(i + 1);
        }
    }
    function back(): void {
        goTo(i - 1);
    }
    function finish(): void {
        dispatch("done");
    }

    function onResize(): void {
        readViewport();
        updateRect();
    }

    onMount(() => {
        readViewport();
        window.addEventListener("resize", onResize);
        window.addEventListener("scroll", updateRect, true);
        goTo(0);
    });
    onDestroy(() => {
        window.removeEventListener("resize", onResize);
        window.removeEventListener("scroll", updateRect, true);
    });

    // Prefer placing the card below the target; flip above when there's no
    // room, and center it when the target isn't on screen.
    $: belowY = rect ? rect.top + rect.height + PAD : 0;
    $: placeAbove = rect ? belowY + cardH + 16 > vh : false;

    function tipTopFor(
        r: Rect | null,
        above: boolean,
        below: number,
        h: number,
        height: number,
    ): number {
        if (!r) {
            return Math.max(16, height / 2 - h / 2);
        }
        if (above) {
            return Math.max(16, r.top - PAD - h);
        }
        return below;
    }
    function tipLeftFor(r: Rect | null, w: number, width: number): number {
        if (!r) {
            return Math.max(12, width / 2 - w / 2);
        }
        const center = r.left + r.width / 2 - w / 2;
        return Math.max(12, Math.min(center, width - w - 12));
    }

    $: tipTop = tipTopFor(rect, placeAbove, belowY, cardH, vh);
    $: tipLeft = tipLeftFor(rect, cardW, vw);
</script>

{#if step}
    <div
        class="tour"
        role="dialog"
        aria-modal="true"
        aria-label="Homebase walkthrough"
        tabindex="-1"
        transition:fade={{ duration: 180 }}
    >
        <div class="catcher"></div>
        {#if rect}
            <div
                class="spotlight"
                class:emphasis={step.emphasis}
                style="top:{rect.top - PAD}px;left:{rect.left -
                    PAD}px;width:{rect.width + PAD * 2}px;height:{rect.height +
                    PAD * 2}px;"
            ></div>
        {:else}
            <div class="dim"></div>
        {/if}
        <div
            class="tip"
            class:emphasis={step.emphasis}
            bind:clientHeight={cardH}
            style="top:{tipTop}px;left:{tipLeft}px;width:{cardW}px;"
        >
            <span class="progress">{i + 1} of {steps.length}</span>
            <h3>{step.title}</h3>
            <p>{step.body}</p>
            <div class="tour-actions">
                <button class="skip" on:click={finish}>Skip</button>
                <div class="nav">
                    {#if i > 0}
                        <button class="ghost" on:click={back}>Back</button>
                    {/if}
                    <button class="cta" on:click={next}>
                        {last ? "Get started" : "Next"}
                    </button>
                </div>
            </div>
        </div>
    </div>
{/if}

<style lang="scss">
    .tour {
        --maroon: #6e1423;
        --maroon-deep: #4a0d18;
        --beige: #f6edda;
        --paper: #fffdf6;
        --ink: #2c1b1e;
        --muted: #7a6a63;
        --gold: #e0a83a;
        position: fixed;
        inset: 0;
        z-index: 2000;
        font-family:
            "Jost",
            -apple-system,
            "Segoe UI",
            system-ui,
            sans-serif;
    }

    .catcher {
        position: fixed;
        inset: 0;
        cursor: default;
    }
    .dim {
        position: fixed;
        inset: 0;
        background: rgba(30, 8, 12, 0.62);
    }

    .spotlight {
        position: fixed;
        border-radius: 16px;
        box-shadow: 0 0 0 9999px rgba(30, 8, 12, 0.62);
        outline: 3px solid rgba(246, 237, 218, 0.9);
        outline-offset: 2px;
        pointer-events: none;
        transition:
            top 160ms ease,
            left 160ms ease,
            width 160ms ease,
            height 160ms ease;
        &.emphasis {
            outline-color: var(--gold);
            box-shadow:
                0 0 0 9999px rgba(30, 8, 12, 0.68),
                0 0 28px 6px rgba(224, 168, 58, 0.55);
        }
    }

    .tip {
        position: fixed;
        background: var(--paper);
        color: var(--ink);
        border-radius: 14px;
        border: 1px solid rgba(74, 13, 24, 0.15);
        box-shadow: 0 16px 40px rgba(30, 8, 12, 0.4);
        padding: 1.15rem 1.25rem 1rem;
        transition:
            top 160ms ease,
            left 160ms ease;
        &.emphasis {
            border-color: var(--gold);
        }
        h3 {
            margin: 0.35rem 0 0.4rem;
            color: var(--maroon-deep);
            font-size: 1.2rem;
        }
        p {
            margin: 0 0 1rem;
            line-height: 1.55;
            font-size: 0.95rem;
            color: var(--ink);
        }
    }

    .progress {
        text-transform: uppercase;
        letter-spacing: 0.08em;
        font-size: 0.68rem;
        font-weight: 800;
        color: var(--maroon);
    }

    .tour-actions {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 0.6rem;
    }
    .nav {
        display: flex;
        gap: 0.5rem;
    }

    button {
        font: inherit;
        cursor: pointer;
        border: none;
        border-radius: 9px;
    }
    .skip {
        background: none;
        color: var(--muted);
        font-weight: 600;
        padding: 0.5rem 0.4rem;
        &:hover {
            color: var(--maroon-deep);
        }
    }
    .ghost {
        padding: 0.55rem 0.95rem;
        font-weight: 600;
        color: var(--maroon-deep);
        border: 1px solid rgba(74, 13, 24, 0.2);
        background: var(--beige);
    }
    .cta {
        padding: 0.55rem 1.2rem;
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
</style>
