<script lang="ts">
  import { X } from '@lucide/svelte'
  import { api, runApi, type DatasetImage, type Project, type Run } from './api'
  import TrainMonitor from './TrainMonitor.svelte'
  import TrainSetup from './TrainSetup.svelte'

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
  <div class="reading muted">正在读取…</div>
{:else if active}
  <TrainMonitor run={active} />
{:else}
  {#if last && last.id !== dismissed && last.status !== 'queued'}
    <div class="banner" class:failed={last.status === 'failed'}>
      {#if last.status === 'done'}
        <span>训练 {last.name} 已完成，保存了 {last.checkpoints.length} 个轮次。</span>
        <button class="btn btn-sm btn-primary" onclick={() => ongotoresults(last.id)}>挑选最好的一轮</button>
      {:else if last.status === 'stopped'}
        <span>训练 {last.name} 已停止，保留了 {last.checkpoints.length} 个轮次。</span>
        {#if last.checkpoints.length}<button class="btn btn-sm" onclick={() => ongotoresults(last.id)}>查看结果</button>{/if}
      {:else}
        <span>训练 {last.name} 出错中断：{last.progress.error ?? '训练进程意外退出，详见该次训练目录下的 trainer.log。'}</span>
      {/if}
      <button class="btn btn-sm btn-ghost btn-square" title="关闭" onclick={() => (dismissed = last.id)}><X /></button>
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
