<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<script lang="ts">
    import { bridgeCommand, bridgeCommandsAvailable } from "@tslib/bridgecommand";
    import { createEventDispatcher } from "svelte";

    const dispatch = createEventDispatcher();

    type Choice = { letter: string; text: string };
    type Q = {
        section: string;
        sectionLabel: string;
        stimulus: string;
        question: string;
        choices: Choice[];
        answer: string;
        explanation: string;
        questionType?: string | null;
        passage?: string | null;
    };

    let step: "name" | "date" | "diag" | "saving" = "name";
    let name = "";
    let startDate = new Date().toISOString().slice(0, 10);

    let questions: Q[] = [];
    let qIndex = 0;
    let picked: string | null = null;
    let answers: {
        section: string;
        correct: boolean;
        questionType?: string | null;
        passage?: string | null;
    }[] = [];

    function call<T>(cmd: string): Promise<T | null> {
        return new Promise((resolve) => {
            if (!bridgeCommandsAvailable()) {
                resolve(null);
                return;
            }
            bridgeCommand<T>(cmd, (res) => resolve(res));
        });
    }

    function planEnd(iso: string): string {
        const d = new Date(iso + "T00:00:00");
        d.setMonth(d.getMonth() + 8);
        return d.toLocaleDateString(undefined, {
            month: "long",
            day: "numeric",
            year: "numeric",
        });
    }

    async function toDiagnostic(): Promise<void> {
        const res = await call<{ questions: Q[] }>("lsat:onboard:questions");
        questions = res?.questions ?? [];
        qIndex = 0;
        picked = null;
        answers = [];
        step = "diag";
        if (!questions.length) {
            finish();
        }
    }

    $: current = questions[qIndex] ?? null;
    $: pickedCorrect =
        picked && current
            ? picked.toUpperCase() === current.answer.toUpperCase()
            : false;

    function pick(letter: string): void {
        if (picked || !current) {
            return;
        }
        picked = letter;
        answers = [
            ...answers,
            {
                section: current.section,
                correct: letter.toUpperCase() === current.answer.toUpperCase(),
                questionType: current.questionType ?? null,
                passage: current.passage ?? null,
            },
        ];
    }

    function nextQuestion(): void {
        if (qIndex < questions.length - 1) {
            qIndex += 1;
            picked = null;
        } else {
            finish();
        }
    }

    async function finish(): Promise<void> {
        step = "saving";
        const correct = answers.filter((a) => a.correct).length;
        const data = {
            name: name.trim(),
            startDate,
            diagnostic: { correct, total: answers.length, answers },
        };
        const payload = await call("lsat:onboard:complete:" + JSON.stringify(data));
        dispatch("done", payload);
    }

    $: correctSoFar = answers.filter((a) => a.correct).length;
</script>

<div class="onb">
    {#if step === "name"}
        <div class="card">
            <span class="step">Step 1 of 3</span>
            <h1>What should we call you?</h1>
            <p class="sub">We'll use your name to keep things personal.</p>
            <input
                class="field"
                type="text"
                bind:value={name}
                placeholder="Your name"
                on:keydown={(e) => e.key === "Enter" && name.trim() && (step = "date")}
            />
            <button
                class="cta"
                disabled={!name.trim()}
                on:click={() => (step = "date")}
            >
                Continue
            </button>
        </div>
    {:else if step === "date"}
        <div class="card">
            <span class="step">Step 2 of 3</span>
            <h1>When are you starting?</h1>
            <p class="sub">
                We'll map out a plan: <b>2 hours a day for 8 months</b>
                .
            </p>
            <input class="field" type="date" bind:value={startDate} />
            <div class="plan-preview">
                <div>
                    <span class="pk">Daily</span>
                     2 hours
                </div>
                <div>
                    <span class="pk">Length</span>
                     8 months (~240 days)
                </div>
                <div>
                    <span class="pk">Target date</span>
                    {planEnd(startDate)}
                </div>
            </div>
            <div class="row">
                <button class="ghost" on:click={() => (step = "name")}>Back</button>
                <button class="cta" on:click={toDiagnostic}>Continue</button>
            </div>
        </div>
    {:else if step === "diag" && current}
        <div class="card wide">
            <span class="step">
                Step 3 of 3 · Diagnostic · {qIndex + 1}/{questions.length}
            </span>
            <h1 class="diag-h">Let's see where you're starting</h1>
            <div class="qsection">{current.sectionLabel}</div>
            {#if current.stimulus}
                <div class="stimulus">{current.stimulus}</div>
            {/if}
            <p class="question">{current.question}</p>
            <div class="choices">
                {#each current.choices as c}
                    <button
                        class="choice"
                        class:correct={picked &&
                            c.letter.toUpperCase() === current.answer.toUpperCase()}
                        class:wrong={picked === c.letter &&
                            c.letter.toUpperCase() !== current.answer.toUpperCase()}
                        class:dim={picked &&
                            picked !== c.letter &&
                            c.letter.toUpperCase() !== current.answer.toUpperCase()}
                        disabled={!!picked}
                        on:click={() => pick(c.letter)}
                    >
                        <span class="letter">{c.letter}</span>
                        <span>{c.text}</span>
                    </button>
                {/each}
            </div>
            {#if picked}
                <div
                    class="feedback"
                    class:good={pickedCorrect}
                    class:bad={!pickedCorrect}
                >
                    <b>{pickedCorrect ? "Correct" : `Answer: ${current.answer}`}</b>
                    {#if current.explanation}<p>{current.explanation}</p>{/if}
                    <button class="cta" on:click={nextQuestion}>
                        {qIndex < questions.length - 1 ? "Next question" : "Finish"}
                    </button>
                </div>
            {/if}
        </div>
    {:else}
        <div class="card">
            <h1>Setting up your plan…</h1>
            <p class="sub">Scored {correctSoFar}/{answers.length} on the diagnostic.</p>
        </div>
    {/if}
</div>

<style lang="scss">
    .onb {
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

        /* Sit above the floating clouds in the sky layer (z-index: 0) so the
           onboarding text stays readable. */
        position: relative;
        z-index: 1;
        min-height: calc(100vh - 3rem);
        display: flex;
        align-items: flex-start;
        justify-content: center;
        padding: 2.5rem 1.25rem;
        font-family:
            "Jost",
            -apple-system,
            "Segoe UI",
            system-ui,
            sans-serif;
        color: var(--ink);
    }

    button {
        font: inherit;
        cursor: pointer;
        border: none;
        background: none;
        color: inherit;
    }

    .card {
        background: var(--paper);
        border: 1px solid var(--beige-deep);
        border-radius: 16px;
        padding: 2rem;
        width: 100%;
        max-width: 30rem;
        box-shadow: 0 10px 30px rgba(74, 13, 24, 0.12);
        &.wide {
            max-width: 44rem;
        }
    }

    .step {
        text-transform: uppercase;
        font-size: 0.7rem;
        letter-spacing: 0.08em;
        font-weight: 800;
        color: var(--maroon-bright);
    }
    h1 {
        margin: 0.4rem 0 0.3rem;
        color: var(--maroon-deep);
        font-size: 1.6rem;
    }
    .diag-h {
        font-size: 1.35rem;
    }
    .sub {
        color: var(--muted);
        margin: 0 0 1.25rem;
    }

    .field {
        width: 100%;
        padding: 0.7rem 0.85rem;
        border: 2px solid var(--beige-deep);
        border-radius: 10px;
        background: var(--beige);
        font: inherit;
        color: var(--ink);
        margin-bottom: 1.25rem;
        &:focus {
            outline: none;
            border-color: var(--maroon-bright);
        }
    }

    .plan-preview {
        background: var(--beige);
        border-radius: 10px;
        padding: 0.9rem 1rem;
        margin-bottom: 1.25rem;
        display: flex;
        flex-direction: column;
        gap: 0.4rem;
        font-size: 0.9rem;
        .pk {
            display: inline-block;
            width: 6.5rem;
            color: var(--muted);
            font-weight: 700;
        }
    }

    .row {
        display: flex;
        gap: 0.6rem;
        justify-content: space-between;
    }

    .cta {
        padding: 0.65rem 1.3rem;
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
    .ghost {
        padding: 0.65rem 1.1rem;
        border-radius: 9px;
        font-weight: 600;
        color: var(--maroon-deep);
        border: 1px solid var(--beige-deep);
        background: var(--beige);
    }

    .qsection {
        font-size: 0.72rem;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        font-weight: 800;
        color: var(--maroon-bright);
        margin-bottom: 0.5rem;
    }
    .stimulus {
        white-space: pre-wrap;
        line-height: 1.5;
        margin-bottom: 0.9rem;
        padding-bottom: 0.9rem;
        border-bottom: 1px dashed var(--beige-deep);
        max-height: 12rem;
        overflow-y: auto;
    }
    .question {
        font-weight: 700;
        color: var(--maroon-deep);
        margin: 0 0 0.9rem;
    }
    .choices {
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
    }
    .choice {
        display: flex;
        gap: 0.7rem;
        align-items: flex-start;
        text-align: left;
        padding: 0.65rem 0.8rem;
        border: 2px solid var(--beige-deep);
        border-radius: 9px;
        background: var(--beige);
        line-height: 1.4;
        &:hover:not(:disabled) {
            border-color: var(--maroon-bright);
        }
        .letter {
            flex-shrink: 0;
            width: 1.5rem;
            height: 1.5rem;
            display: grid;
            place-items: center;
            border-radius: 50%;
            background: var(--maroon);
            color: var(--beige);
            font-weight: 800;
            font-size: 0.8rem;
        }
        &.correct {
            border-color: var(--green);
            background: #e4f0e8;
            .letter {
                background: var(--green);
            }
        }
        &.wrong {
            border-color: var(--red);
            background: #f7e1e1;
            .letter {
                background: var(--red);
            }
        }
        &.dim {
            opacity: 0.55;
        }
        &:disabled {
            cursor: default;
        }
    }
    .feedback {
        margin-top: 1rem;
        padding: 0.9rem 1rem;
        border-radius: 9px;
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
        p {
            margin: 0.4rem 0 0.9rem;
            line-height: 1.5;
        }
    }
</style>
