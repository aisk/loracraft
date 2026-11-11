<script lang="ts">
  import { X } from '@lucide/svelte'
  import { api, runApi, type DatasetImage, type Project, type Run } from './api'
  import TrainMonitor from './TrainMonitor.svelte'
  import TrainSetup from './TrainSetup.svelte'
  import { t } from './i18n/index.svelte'

  let {
    project,
    ongotodataset,
    ongotoresults,
  }: { project: Project; ongotodataset: () => void; ongotoresults: (runId: number) => void } = $props()

  let runs = $state<Run[] | null>(null)
  let images = $state<DatasetImage[] | null>(null)
  let dismissed = $state<number | null>(null) // id of the finished run whose banner was closed

  const active = $derived(runs?.find((r) => r.status === 'queued' || r.status === 'running') ?? null)
  const last = $derived(runs?.[0] ?? null)

  async function refresh() {
    runs = await runApi.list(project.id)
  }
  const loadImages = async () => (images = await api.listImages(project.id))

  refresh()
  loadImages()

  // Keep the active run's progress fresh.
  $effect(() => {
    if (!active) return
    const timer = setInterval(refresh, 2000)
    return () => clearInterval(timer)
  })
</script>

{#if runs === null || images === null}
  <div class="reading muted">{t().common.loading}</div>
{:else if active}
  <TrainMonitor run={active} />
{:else}
  {#if last && last.id !== dismissed && last.status !== 'queued'}
    <div class="banner" class:failed={last.status === 'failed'}>
      {#if last.status === 'done'}
        <span>{t().train.finished(last.name, last.checkpoints.length)}</span>
        <button class="btn btn-sm btn-primary" onclick={() => ongotoresults(last.id)}>{t().train.pickBest}</button>
      {:else if last.status === 'stopped'}
        <span>{t().train.stopped(last.name, last.checkpoints.length)}</span>
        {#if last.checkpoints.length}<button class="btn btn-sm" onclick={() => ongotoresults(last.id)}>{t().train.viewResults}</button>{/if}
      {:else}
        <span>{t().train.failed(last.name, last.progress.error ?? t().train.crashed)}</span>
      {/if}
      <button class="btn btn-sm btn-ghost btn-square" title={t().common.close} onclick={() => (dismissed = last.id)}><X /></button>
    </div>
  {/if}
    <TrainSetup
      {project}
      {images}
      lastRun={last}
      onstart={refresh}
      {ongotodataset}
      onimageschange={loadImages}
    />
{/if}

<style>
  .reading {
    padding: var(--space-5);
  }
  .banner {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    margin: var(--space-4) var(--space-5) 0;
    padding: var(--space-2) var(--space-2) var(--space-2) var(--space-4);
    background: var(--accent-bg);
    border-radius: var(--radius-lg);
    flex: none;
  }
  .banner span {
    flex: 1;
    overflow-wrap: anywhere;
  }
  .banner.failed {
    background: color-mix(in srgb, var(--danger) 14%, var(--surface));
  }
</style>
