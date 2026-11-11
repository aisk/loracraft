<script lang="ts">
  import { Download, GalleryHorizontalEnd, Star, Trash2 } from '@lucide/svelte'
  import { checkpointEpoch, errorText, parseSampleName, runApi, sampleUrl, type Project, type Run } from './api'
  import { t } from './i18n/index.svelte'

  let {
    project,
    focusRunId,
    ongototrain,
  }: { project: Project; focusRunId: number | null; ongototrain: () => void } = $props()

  let runs = $state<Run[] | null>(null)
  // svelte-ignore state_referenced_locally -- only the initial focus matters
  let selectedId = $state<number | null>(focusRunId)
  let zoomed = $state<string | null>(null)
  let message = $state('')
  let exportDir = $state('')
  let needExportDir = $state(false)

  const run = $derived(runs?.find((r) => r.id === selectedId) ?? runs?.[0] ?? null)

  async function refresh() {
    const fresh = await runApi.list(project.id)
    // While notes are being typed or saved, the server's copy is older than the text box.
    if (!notesBusy) runs = fresh
  }
  refresh()

  // A run still going gains rounds and previews; keep them coming in.
  const anyActive = $derived(runs?.some((r) => r.status === 'queued' || r.status === 'running') ?? false)
  $effect(() => {
    if (!anyActive) return
    const timer = setInterval(() => refresh().catch(() => {}), 4000)
    return () => clearInterval(timer)
  })

  function replace(updated: Run) {
    runs = runs!.map((r) => (r.id === updated.id ? updated : r))
  }

  // rows: one per epoch that has samples or a checkpoint; epoch 0 is the untrained baseline.
  const rows = $derived.by(() => {
    if (!run) return []
    const byEpoch = new Map<number, { samples: string[]; checkpoint: string | null }>()
    const row = (epoch: number) => {
      if (!byEpoch.has(epoch)) byEpoch.set(epoch, { samples: [], checkpoint: null })
      return byEpoch.get(epoch)!
    }
    for (const name of run.samples) {
      const parsed = parseSampleName(name)
      if (parsed) row(parsed.epoch).samples[parsed.prompt] = name
    }
    for (const name of run.checkpoints) row(checkpointEpoch(name)).checkpoint = name
    return [...byEpoch.entries()].sort((a, b) => a[0] - b[0]).map(([epoch, data]) => ({ epoch, ...data }))
  })
  const prompts = $derived(run?.config.sample_prompts ?? [])

  // What changed compared with the previous run, in plain words.
  const changes = $derived.by(() => {
    if (!run || !runs) return []
    const previous = runs.find((r) => r.id < run.id)
    if (!previous) return []
    const labels: Record<string, string> = t().results.fields
    const short = (v: unknown) => (typeof v === 'string' ? (v.split(/[\\/]/).pop() ?? v).replace('.safetensors', '') : String(v))
    const out: string[] = []
    for (const [key, label] of Object.entries(labels)) {
      const a = (previous.config as unknown as Record<string, unknown>)[key]
      const b = (run.config as unknown as Record<string, unknown>)[key]
      if (a !== b) out.push(`${label} ${short(a)} → ${short(b)}`)
    }
    if (previous.num_images !== run.num_images) out.push(t().results.imagesChange(previous.num_images, run.num_images))
    return out
  })

  async function pick(checkpoint: string) {
    replace(await runApi.update(run!.id, { best_checkpoint: run!.best_checkpoint === checkpoint ? '' : checkpoint }))
  }

  async function exportCheckpoint(checkpoint: string) {
    message = ''
    try {
      const { path } = await runApi.exportCheckpoint(run!.id, checkpoint)
      message = t().results.exported(path)
      needExportDir = false
    } catch (error) {
      const settings = await runApi.getSettings()
      if (!settings.export_dir) needExportDir = true
      else message = String(error)
    }
  }

  async function saveExportDir(checkpoint: string | null) {
    const settings = await runApi.getSettings()
    await runApi.putSettings({ ...settings, export_dir: exportDir.trim() })
    needExportDir = false
    if (checkpoint) await exportCheckpoint(checkpoint)
  }

  let pendingExport = $state<string | null>(null)
  let notesTimer: ReturnType<typeof setTimeout>
  let notesBusy = 0 // saves scheduled or under way
  function saveNotes(value: string) {
    // The text box is the truth while typing: the answer to a save must never be written back into it.
    const target = run!
    target.notes = value
    if (notesTimer) (clearTimeout(notesTimer), notesBusy--)
    notesBusy++
    notesTimer = setTimeout(async () => {
      notesTimer = undefined!
      try {
        await runApi.update(target.id, { notes: value })
      } catch (error) {
        message = String(error)
      } finally {
        notesBusy--
      }
    }, 500)
  }

  async function remove() {
    const target = run!
    if (!confirm(t().results.confirmDelete(target.name, target.checkpoints.length))) return
    message = ''
    try {
      await runApi.remove(target.id)
      runs = runs!.filter((r) => r.id !== target.id)
      selectedId = null
    } catch (error) {
      message = errorText(error, t().common.runBusy)
    }
  }
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && (zoomed = null)} />

{#if runs === null}
  <div class="empty muted">{t().common.loading}</div>
{:else if !run}
  <div class="empty">
    <GalleryHorizontalEnd class="big-icon" />
    <h2>{t().results.emptyTitle}</h2>
    <p class="muted">{t().results.emptyBody}</p>
    <button class="btn btn-primary" onclick={ongototrain}>{t().results.gotoTrain}</button>
  </div>
{:else}
  <div class="results">
    <section class="run-list">
      <span class="label-quiet">{t().results.history}</span>
      {#each runs as r (r.id)}
        <button class="run" class:active={r.id === run.id} onclick={() => ((selectedId = r.id), (message = ''))}>
          <span class="title">
            <strong>{t().common.runName(r.name)}</strong>
            {#if t().results.status[r.status]}<span class="state" class:bad={r.status === 'failed'}>{t().results.status[r.status]}</span>{/if}
          </span>
          <span class="meta num">{t().results.runMeta(r.created_at.slice(5, 16), r.num_images, r.config.epochs)}</span>
          {#if r.best_checkpoint}
            <span class="meta picked"><Star />{t().results.picked(checkpointEpoch(r.best_checkpoint))}</span>
          {/if}
        </button>
      {/each}
    </section>

    <section class="detail">
      <div class="head">
        <div class="summary">
          <h2>{t().common.runName(run.name)}</h2>
          <p class="muted">
            {t().results.summary(
              run.config.base_model.split(/[\\/]/).pop()?.replace('.safetensors', '') ?? '',
              run.config.network_dim,
              run.config.unet_lr,
              run.num_images,
            )}
          </p>
          {#if changes.length}
            <p class="muted">{t().results.changes(changes)}</p>
          {/if}
          {#if run.status !== 'queued' && run.status !== 'running'}
            <button class="btn btn-xs btn-ghost text-error mt-1" onclick={remove}><Trash2 />{t().results.deleteRun}</button>
          {/if}
        </div>
        <textarea
          class="textarea"
          rows="2"
          placeholder={t().results.notesPlaceholder}
          value={run.notes}
          oninput={(e) => saveNotes(e.currentTarget.value)}
        ></textarea>
      </div>

      {#if message}<p class="message">{message}</p>{/if}
      {#if needExportDir}
        <div class="export-setup">
          <span>{t().results.exportWhere}</span>
          <input class="input input-sm mono" type="text" placeholder="D:\ComfyUI\models\loras" bind:value={exportDir} />
          <button class="btn btn-sm btn-primary" disabled={!exportDir.trim()} onclick={() => saveExportDir(pendingExport)}>
            {t().results.saveAndExport}
          </button>
        </div>
      {/if}

      {#if rows.length === 0}
        <p class="muted pad">{t().results.noRounds}</p>
      {:else}
        <!-- A contact sheet: rounds run left to right, so each prompt's strip reads as the training's progress. -->
        <div class="sheet" style:--cols={rows.length}>
          {#each rows as row (row.epoch)}
            {@const best = !!row.checkpoint && row.checkpoint === run.best_checkpoint}
            <div class="round" class:best>
              <strong>{t().common.round(row.epoch)}</strong>
              {#if row.checkpoint}
                <div class="round-actions">
                  <button class={['btn btn-xs', best ? 'btn-primary' : 'btn-soft']} onclick={() => pick(row.checkpoint!)}>
                    <Star />{best ? t().results.best : t().results.pickAsBest}
                  </button>
                  <button
                    class="btn btn-xs btn-ghost"
                    onclick={() => ((pendingExport = row.checkpoint), exportCheckpoint(row.checkpoint!))}
                  >
                    <Download />{t().results.export}
                  </button>
                </div>
              {:else if row.epoch === 0}
                <span class="muted small">{t().results.baselineNote}</span>
              {/if}
            </div>
          {/each}

          {#each prompts as prompt, i (i)}
            <div class="prompt" title={prompt.prompt}><span>{prompt.prompt}</span></div>
            {#each rows as row (row.epoch)}
              <div class="frame" class:best={row.checkpoint && row.checkpoint === run.best_checkpoint}>
                {#if row.samples[i]}
                  <button class="image" onclick={() => (zoomed = sampleUrl(run.id, row.samples[i]))}>
                    <img src={sampleUrl(run.id, row.samples[i])} alt={t().results.sampleAlt(t().common.round(row.epoch), i + 1)} loading="lazy" />
                  </button>
                {/if}
              </div>
            {/each}
          {/each}
        </div>
      {/if}
    </section>
  </div>
{/if}

{#if zoomed}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="lightbox" onclick={() => (zoomed = null)}>
    <img src={zoomed} alt={t().results.zoomedAlt} />
  </div>
{/if}

<style>
  .empty {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--space-3);
    padding: var(--space-5);
    text-align: center;
  }
  .empty :global(.big-icon) {
    width: 40px;
    height: 40px;
    stroke-width: 1.5;
    color: var(--accent);
  }
  .empty h2 {
    font-size: var(--text-xl);
  }
  .empty p {
    max-width: 40ch;
    line-height: 1.7;
    margin-bottom: var(--space-2);
  }

  .results {
    flex: 1;
    display: grid;
    grid-template-columns: 232px minmax(0, 1fr);
    min-height: 0;
  }
  .run-list {
    border-right: 1px solid var(--border);
    overflow-y: auto;
    padding: var(--space-4) var(--space-3);
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .run-list .label-quiet {
    padding: 0 var(--space-2) var(--space-2);
  }
  .run {
    padding: var(--space-2);
    border-radius: var(--radius);
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 2px;
    text-align: left;
  }
  .run:hover {
    background: color-mix(in oklab, var(--text) 5%, transparent);
  }
  .run.active {
    background: var(--surface-2);
  }
  .title {
    display: flex;
    gap: var(--space-2);
    align-items: baseline;
  }
  .state {
    font-size: var(--text-xs);
    color: var(--text-2);
  }
  .state.bad {
    color: var(--danger);
  }
  .meta {
    font-size: var(--text-xs);
    color: var(--text-3);
  }
  .picked {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    color: var(--accent);
  }
  .picked :global(svg) {
    width: 11px;
    height: 11px;
    fill: currentColor;
  }

  .detail {
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow: auto;
    background: var(--bg);
  }
  .head {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 340px;
    gap: var(--space-4);
    padding: var(--space-4) var(--space-5);
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    position: sticky;
    left: 0;
  }
  h2 {
    font-size: var(--text-lg);
  }
  .summary p {
    margin-top: 4px;
    line-height: 1.6;
    overflow-wrap: anywhere;
  }
  .head textarea {
    font-family: var(--font-sans);
    font-size: var(--text-md);
    resize: none;
  }
  .message,
  .pad {
    padding: var(--space-2) var(--space-5);
  }
  .message {
    background: var(--accent-bg);
    overflow-wrap: anywhere;
  }
  .export-setup {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-3) var(--space-5);
    background: var(--surface);
    border-bottom: 1px solid var(--border);
  }
  .export-setup input {
    flex: 1;
  }

  .sheet {
    display: grid;
    grid-template-columns: repeat(var(--cols), 240px);
    padding: var(--space-4) var(--space-5) var(--space-6);
    width: max-content;
  }
  .round {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: var(--space-3) var(--space-2) var(--space-2);
    border-radius: var(--radius-lg) var(--radius-lg) 0 0;
    min-height: 72px;
  }
  .round strong {
    font-family: var(--font-display);
    font-size: 15px;
  }
  .round-actions {
    display: flex;
    gap: var(--space-1);
  }
  .round.best :global(.btn svg) {
    fill: currentColor;
  }
  .prompt {
    grid-column: 1 / -1;
    padding: var(--space-3) var(--space-2) var(--space-1);
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: var(--text-2);
  }
  /* Keep the prompt readable while the sheet scrolls sideways. */
  .prompt span {
    position: sticky;
    left: var(--space-5);
    display: inline-block;
    max-width: 70vw;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .frame {
    padding: var(--space-2);
  }
  /* The chosen round is lit as one column, top to bottom. */
  .round.best,
  .frame.best {
    background: var(--accent-bg);
  }
  .frame.best:last-child,
  .frame.best:nth-last-child(-n + 1) {
    border-radius: 0 0 var(--radius-lg) var(--radius-lg);
  }
  .image {
    display: block;
    width: 100%;
    border-radius: 6px;
    overflow: hidden;
    cursor: zoom-in;
    transition: transform 0.12s;
  }
  .image:hover {
    transform: scale(1.015);
  }
  .image img {
    display: block;
    width: 100%;
  }
  .small {
    font-size: var(--text-xs);
  }

  .lightbox {
    position: fixed;
    inset: 0;
    z-index: 10;
    background: rgb(0 0 0 / 0.9);
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: zoom-out;
  }
  .lightbox img {
    max-width: 96vw;
    max-height: 96vh;
    border-radius: var(--radius);
  }
</style>
