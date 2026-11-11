<script lang="ts">
  import { Images, Square } from '@lucide/svelte'
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
    {#if p.total_steps}
      <div class="percent num">{Math.floor(fraction * 100)}<span>%</span></div>
    {:else}
      <span class="loading loading-ring loading-xl waiting"></span>
    {/if}
    <div class="state">
      <h2>{headline}</h2>
      <p class="muted num">
        {#if p.total_steps}
          {p.step} / {p.total_steps} 步{#if remaining !== null && p.step > 0}，还需约 {formatDuration(remaining)}（不含出图）{/if}
        {:else}
          训练 {run.name}，{run.num_images} 张图片
        {/if}
      </p>
    </div>
    <button class="btn btn-sm btn-outline btn-error" disabled={stopping} onclick={stop}><Square />停止训练</button>
  </header>

  <!-- One track for the whole training; the notches are the ends of the rounds. -->
  <div class="track" role="progressbar" aria-valuenow={Math.round(fraction * 100)} aria-valuemin="0" aria-valuemax="100">
    <div class="fill" style:width="{fraction * 100}%"></div>
    {#each { length: run.config.epochs - 1 }, i (i)}
      <span class="notch" style:left="{((i + 1) / run.config.epochs) * 100}%"></span>
    {/each}
  </div>

  <div class="body">
    <section class="samples">
      {#if shownEpoch !== null}
        <div class="epochs">
          {#each epochs as epoch (epoch)}
            <button
              class={['btn btn-xs', epoch === shownEpoch ? 'btn-primary' : 'btn-ghost']}
              onclick={() => (viewEpoch = epoch === epochs.at(-1) ? null : epoch)}
            >
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
        <div class="placeholder">
          <Images />
          <p class="muted">
            {run.config.sample_prompts.length
              ? '预览图会出现在这里：先是一组训练前的对照图，之后每轮一组。'
              : '这次训练没有设置预览提示词。'}
          </p>
        </div>
      {/if}
    </section>

    <aside>
      <div class="facts">
        <div>
          <span class="figure num">{p.seconds_per_step ? p.seconds_per_step.toFixed(2) : '—'}</span>
          <span class="muted">秒 / 步</span>
        </div>
        <div>
          <span class="figure num">{losses.at(-1)?.toFixed(3) ?? '—'}</span>
          <span class="muted">Loss</span>
        </div>
      </div>

      {#if chart}
        <svg viewBox="0 0 100 40" preserveAspectRatio="none" role="img" aria-label="loss 曲线">
          <polyline points={chart.points} />
        </svg>
        <p class="muted num">最低 {chart.min.toFixed(4)}，最高 {chart.max.toFixed(4)}</p>
      {/if}
      <p class="muted">Loss 只说明模型在拟合，不能说明效果好坏。哪一轮最好，主要看预览图。</p>

      <h3>这次的设置</h3>
      <dl>
        <dt>底模</dt>
        <dd>{run.config.base_model.split(/[\\/]/).pop()?.replace(/\.safetensors$/, '')}</dd>
        <dt>图片</dt>
        <dd class="num">{run.num_images} 张</dd>
        <dt>容量</dt>
        <dd class="num">rank {run.config.network_dim}</dd>
        <dt>学习率</dt>
        <dd class="num">{run.config.unet_lr}</dd>
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
    gap: var(--space-4);
    padding: var(--space-5) var(--space-5) var(--space-4);
  }
  .percent {
    font-family: var(--font-display);
    font-size: 56px;
    font-weight: 700;
    line-height: 1;
    letter-spacing: -0.03em;
    color: var(--accent);
    min-width: 2.2ch;
    text-align: right;
  }
  .percent span {
    font-size: 22px;
    margin-left: 2px;
  }
  .waiting {
    color: var(--accent);
    margin: 0 var(--space-2);
  }
  .state {
    flex: 1;
    min-width: 0;
  }
  h2 {
    font-size: var(--text-xl);
  }

  .track {
    position: relative;
    height: 6px;
    margin: 0 var(--space-5);
    border-radius: 3px;
    background: var(--surface-2);
    flex: none;
  }
  .fill {
    height: 100%;
    border-radius: 3px;
    background: var(--accent);
    box-shadow: 0 0 14px color-mix(in oklab, var(--accent) 70%, transparent);
    transition: width 0.6s ease-out;
  }
  .notch {
    position: absolute;
    top: -3px;
    width: 2px;
    height: 12px;
    background: var(--surface);
  }

  .body {
    flex: 1;
    display: grid;
    grid-template-columns: minmax(0, 1fr) 300px;
    min-height: 0;
    margin-top: var(--space-4);
    border-top: 1px solid var(--border);
  }
  .samples {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    padding: var(--space-4) var(--space-5);
    min-height: 0;
    background: var(--bg);
  }
  .epochs {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1);
    flex: none;
  }
  .images {
    flex: 1;
    display: flex;
    gap: var(--space-4);
    min-height: 0;
  }
  figure {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  figure img {
    flex: 1;
    min-height: 0;
    width: 100%;
    object-fit: contain;
    object-position: left top;
    border-radius: var(--radius);
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
    margin: auto;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-3);
    max-width: 36ch;
    text-align: center;
  }
  .placeholder :global(svg) {
    width: 36px;
    height: 36px;
    stroke-width: 1.5;
    color: var(--text-3);
  }

  aside {
    padding: var(--space-4);
    border-left: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    overflow-y: auto;
  }
  .facts {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--space-2);
  }
  .facts div {
    display: flex;
    flex-direction: column;
    font-size: var(--text-sm);
  }
  .figure {
    font-family: var(--font-display);
    font-size: 26px;
    font-weight: 650;
    line-height: 1.2;
  }
  h3 {
    font-size: var(--text-md);
    margin-top: var(--space-2);
  }
  aside svg {
    width: 100%;
    height: 96px;
    background: var(--bg);
    border-radius: var(--radius);
  }
  polyline {
    fill: none;
    stroke: var(--accent);
    stroke-width: 1.5;
    vector-effect: non-scaling-stroke;
  }
  aside p {
    font-size: var(--text-sm);
    line-height: 1.6;
  }
  dl {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: var(--space-1) var(--space-3);
  }
  dt {
    color: var(--text-2);
  }
  dd {
    text-align: right;
    overflow-wrap: anywhere;
  }
</style>
