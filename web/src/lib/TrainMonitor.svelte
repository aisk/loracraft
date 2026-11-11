<script lang="ts">
  import { formatDuration, parseSampleName, runApi, sampleUrl, type Run } from './api'

  let { run }: { run: Run } = $props()

  let losses = $state<number[]>([])
  let received = 0
  let stopping = $state(false)
  let viewEpoch = $state<number | null>(null) // null follows the newest epoch

  // Pull new events for the loss curve. The run summary itself is refreshed by the parent.
  // The parent replaces `run` with a fresh object on every refresh; only a different run restarts polling.
  const runId = $derived(run.id)
  $effect(() => {
    const id = runId
    let cancelled = false
    let busy = false
    losses = []
    received = 0
    async function poll() {
      if (busy) return // a slow answer must not be requested a second time with the same offset
      busy = true
      try {
        const { events } = await runApi.events(id, received)
        if (cancelled) return
        received += events.length
        const fresh = events.filter((e) => e.type === 'step').map((e) => e.loss_avg as number)
        if (fresh.length) losses = [...losses, ...fresh]
      } catch {
        // Transient; the next tick retries.
      } finally {
        busy = false
      }
    }
    poll()
    const timer = setInterval(poll, 2000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  })

  const p = $derived(run.progress)
  const fraction = $derived(p.total_steps ? p.step / p.total_steps : 0)
  const remaining = $derived(
    p.total_steps && p.seconds_per_step ? (p.total_steps - p.step) * p.seconds_per_step : null,
  )

  const headline = $derived.by(() => {
    if (stopping) return '正在停止，当前这一步结束后停下'
    if (run.status === 'queued') return '排队中，等前一个训练结束'
    switch (p.phase) {
      case 'loading_model':
        return '正在加载底模'
      case 'caching_latents':
        return `正在预处理图片 ${p.cache_done} / ${run.num_images}`
      case 'sampling':
        return p.step === 0 ? '正在生成训练前的对照图' : `第 ${p.epoch} 轮结束，正在生成预览图`
      case 'training':
        return `正在训练第 ${Math.max(1, p.epoch)} / ${run.config.epochs} 轮`
      default:
        return '正在启动'
    }
  })

  // Samples grouped by epoch: Map<epoch, file name per prompt index>
  const byEpoch = $derived.by(() => {
    const map = new Map<number, string[]>()
    for (const name of run.samples) {
      const parsed = parseSampleName(name)
      if (!parsed) continue
      const row = map.get(parsed.epoch) ?? []
      row[parsed.prompt] = name
      map.set(parsed.epoch, row)
    }
    return map
  })
  const epochs = $derived([...byEpoch.keys()].sort((a, b) => a - b))
  const shownEpoch = $derived(viewEpoch !== null && byEpoch.has(viewEpoch) ? viewEpoch : (epochs.at(-1) ?? null))

  const chart = $derived.by(() => {
    if (losses.length < 2) return null
    const min = Math.min(...losses)
    const max = Math.max(...losses)
    const span = max - min || 1
    const points = losses
      .map((v, i) => `${((i / (losses.length - 1)) * 100).toFixed(2)},${(36 - ((v - min) / span) * 32).toFixed(2)}`)
      .join(' ')
    return { points, min, max }
  })

  async function stop() {
    if (!confirm('停止这次训练？已经保存的轮次会保留。')) return
    stopping = true
    await runApi.stop(run.id)
  }
</script>

<div class="monitor">
  <header>
    <div class="status">
      <h2>{headline}</h2>
      <p class="muted num">
        {#if p.total_steps}
          {p.step} / {p.total_steps} 步
          {#if remaining !== null && p.step > 0}，还需约 {formatDuration(remaining)}（不含出图）{/if}
        {:else}
          训练 {run.name}，{run.num_images} 张图片
        {/if}
      </p>
    </div>
    <button class="danger" disabled={stopping} onclick={stop}>停止训练</button>
  </header>
  <div class="bar"><div style:width="{fraction * 100}%"></div></div>

  <div class="body">
    <section class="samples">
      {#if shownEpoch !== null}
        <div class="epochs">
          {#each epochs as epoch (epoch)}
            <button class:active={epoch === shownEpoch} onclick={() => (viewEpoch = epoch === epochs.at(-1) ? null : epoch)}>
              {epoch === 0 ? '训练前' : `第 ${epoch} 轮`}
            </button>
          {/each}
        </div>
        <div class="images">
          {#each byEpoch.get(shownEpoch) ?? [] as name, index (index)}
            {#if name}
              <figure>
                <img src={sampleUrl(run.id, name)} alt="预览图 {index + 1}" />
                <figcaption title={run.config.sample_prompts[index]?.prompt}>
                  {run.config.sample_prompts[index]?.prompt}
                </figcaption>
              </figure>
            {/if}
          {/each}
        </div>
      {:else}
        <p class="muted placeholder">
          {run.config.sample_prompts.length ? '预览图会在这里出现：先是一组训练前的对照图，之后每轮一组。' : '这次训练没有设置预览提示词。'}
        </p>
      {/if}
    </section>

    <aside>
      <h3>Loss</h3>
      {#if chart}
        <svg viewBox="0 0 100 40" preserveAspectRatio="none" role="img" aria-label="loss 曲线">
          <polyline points={chart.points} />
        </svg>
        <p class="muted num range">{chart.min.toFixed(4)} – {chart.max.toFixed(4)}，当前 {losses.at(-1)?.toFixed(4)}</p>
      {:else}
        <p class="muted">训练开始后显示。</p>
      {/if}
      <p class="muted note">Loss 只说明模型在拟合，不能说明效果好坏。判断哪一轮最好，主要看预览图。</p>

      <h3>设置</h3>
      <dl>
        <dt>容量</dt>
        <dd class="num">rank {run.config.network_dim}</dd>
        <dt>学习率</dt>
        <dd class="num">{run.config.unet_lr}</dd>
        <dt>速度</dt>
        <dd class="num">{p.seconds_per_step ? `${p.seconds_per_step.toFixed(2)} 秒 / 步` : '—'}</dd>
      </dl>
    </aside>
  </div>
</div>

<style>
  .monitor {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-height: 0;
  }
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-4);
    padding: var(--space-4) var(--space-5);
  }
  h2 {
    font-size: 18px;
  }
  header p {
    margin: 2px 0 0;
  }
  .bar {
    height: 3px;
    background: var(--border);
    flex: none;
  }
  .bar div {
    height: 100%;
    background: var(--accent);
    transition: width 0.4s;
  }

  .body {
    flex: 1;
    display: grid;
    grid-template-columns: minmax(0, 1fr) 280px;
    min-height: 0;
  }
  .samples {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    padding: var(--space-4) var(--space-5);
    min-height: 0;
  }
  .epochs {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1);
    flex: none;
  }
  .epochs button {
    height: 24px;
    padding: 0 var(--space-2);
    font-size: var(--text-sm);
    color: var(--text-2);
  }
  .epochs button.active {
    border-color: var(--accent);
    background: var(--accent-bg);
    color: var(--accent);
  }
  .images {
    flex: 1;
    display: flex;
    gap: var(--space-3);
    min-height: 0;
  }
  figure {
    flex: 1;
    min-width: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  figure img {
    flex: 1;
    min-height: 0;
    width: 100%;
    object-fit: contain;
    object-position: left top;
  }
  figcaption {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: var(--text-2);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    flex: none;
  }
  .placeholder {
    margin: 80px 0;
  }

  aside {
    padding: var(--space-4);
    background: var(--surface);
    border-left: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    overflow-y: auto;
  }
  h3 {
    font-size: var(--text-md);
    margin-top: var(--space-3);
  }
  h3:first-child {
    margin-top: 0;
  }
  svg {
    width: 100%;
    height: 96px;
    background: var(--surface-2);
    border-radius: var(--radius);
  }
  polyline {
    fill: none;
    stroke: var(--accent);
    stroke-width: 1.5;
    vector-effect: non-scaling-stroke;
  }
  aside p {
    margin: 0;
    font-size: var(--text-sm);
    line-height: 1.6;
  }
  dl {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: var(--space-1) var(--space-3);
    margin: 0;
  }
  dt {
    color: var(--text-2);
  }
  dd {
    margin: 0;
    text-align: right;
  }
</style>
