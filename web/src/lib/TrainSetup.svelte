<script lang="ts">
  import { Play, Plus, X } from '@lucide/svelte'
  import {
    api,
    formatDuration,
    runApi,
    splitTags,
    type BaseModel,
    type DatasetImage,
    type Project,
    type Run,
    type TrainerStatus,
    type TrainSettings,
  } from './api'
  import { countAdvice } from './guidance'
  import { around, t } from './i18n/index.svelte'

  let {
    project,
    images,
    lastRun,
    onstart,
    ongotodataset,
    onimageschange,
  }: {
    project: Project
    images: DatasetImage[]
    lastRun: Run | null
    onstart: (run: Run) => void
    ongotodataset: () => void
    onimageschange: () => void
  } = $props()

  const NEGATIVE = 'worst quality, low quality, lowres, bad anatomy'
  const SIZES = [
    { shape: 'portrait', width: 832, height: 1216 },
    { shape: 'square', width: 1024, height: 1024 },
    { shape: 'landscape', width: 1216, height: 832 },
  ] as const
  // How much the LoRA can hold. Alpha follows at half the rank.
  const CAPACITIES = [8, 16, 32] as const
  const SCHEDULERS = ['cosine', 'constant', 'constant_with_warmup', 'cosine_with_restarts', 'linear'] as const
  // Rough number of steps that usually works at batch size 1, by what is being taught.
  const TARGET_STEPS = { character: 1600, style: 2400, concept: 2000 }
  const ROUNDS = 10 // each round saves a LoRA and renders previews; ten gives enough to choose from

  // Shuffling suits tag lists. On sentences it would scramble the clauses between commas.
  function captionsAreSentences(): boolean {
    const pieces = images.flatMap((image) => splitTags(image.caption))
    const long = pieces.filter((piece) => piece.split(/\s+/).length > 4).length
    return pieces.length > 0 && long / pieces.length > 0.3
  }

  function initialSettings(): TrainSettings {
    if (lastRun) return structuredClone($state.snapshot(lastRun.config)) as TrainSettings

    const lead = project.trigger ? `${project.trigger}, ` : ''
    const prompts =
      project.kind === 'style'
        ? [`${lead}1girl, solo, upper body, looking at viewer`, `${lead}scenery, outdoors, no humans`]
        : [`${lead}solo, upper body, looking at viewer, simple background`, `${lead}solo, full body, standing, outdoors`]
    const dim = project.kind === 'style' ? 32 : 16
    // Small datasets repeat each image within a round, so that ten rounds add up to the target.
    const repeats = Math.max(1, Math.round(TARGET_STEPS[project.kind] / (ROUNDS * Math.max(1, images.length))))
    return {
      base_model: '',
      prediction_type: 'epsilon',
      zero_terminal_snr: false,
      output_name: project.name.replace(/[^\p{L}\p{N}_-]+/gu, '_') || 'lora',
      resolution: 1024,
      repeats,
      shuffle_caption: !captionsAreSentences(),
      keep_tokens: project.trigger ? 1 : 0,
      caption_dropout_rate: 0,
      network_dim: dim,
      network_alpha: dim / 2,
      epochs: ROUNDS,
      batch_size: 1,
      optimizer: 'adamw',
      unet_lr: 1e-4,
      train_text_encoder: false,
      text_encoder_lr: 5e-5,
      lr_scheduler: 'cosine',
      lr_warmup_steps: 0,
      min_snr_gamma: 5,
      noise_offset: null,
      mixed_precision: 'fp16',
      seed: 42,
      save_every_n_epochs: 1,
      sample_every_n_epochs: 1,
      sample_prompts: prompts.map((prompt, i) => ({
        prompt,
        negative_prompt: NEGATIVE,
        width: 832,
        height: 1216,
        steps: 24,
        cfg_scale: 6,
        seed: 1000 + i,
      })),
    }
  }

  let settings = $state(initialSettings())
  let models = $state<BaseModel[]>([])
  let modelsLoaded = $state(false)
  let trainer = $state<TrainerStatus | null>(null)
  let modelDir = $state('')
  let error = $state('')
  let starting = $state(false)

  async function loadModels() {
    const result = await runApi.models()
    models = result.models
    modelsLoaded = true
    if (!models.some((m) => m.path === settings.base_model)) pickModel(models[0]?.path ?? '')
  }
  loadModels().catch((e) => (error = String(e)))
  runApi
    .trainer()
    .then((status) => {
      trainer = status
      // The trainer only does full precision on Apple Silicon: show what will actually happen.
      if (status.device === 'mps') settings.mixed_precision = 'no'
    })
    .catch((e) => (error = String(e)))

  function pickModel(path: string) {
    settings.base_model = path
    const model = models.find((m) => m.path === path)
    if (model) {
      settings.prediction_type = model.v_prediction ? 'v_prediction' : 'epsilon'
      settings.zero_terminal_snr = model.zero_terminal_snr
    }
  }

  async function addModelDir() {
    try {
      const current = await runApi.getSettings()
      await runApi.putSettings({ ...current, model_dirs: [...current.model_dirs, modelDir.trim()] })
      modelDir = ''
      error = ''
      await loadModels()
      if (!models.length) error = t().setup.noModelInFolder
    } catch (e) {
      error = String(e)
    }
  }

  const selectedModel = $derived(models.find((m) => m.path === settings.base_model))
  const steps = $derived(Math.ceil((images.length * settings.repeats) / settings.batch_size) * settings.epochs)
  const secondsPerStep = $derived(lastRun?.progress.seconds_per_step ?? null)

  const count = $derived(countAdvice(project.kind, images.length))
  const uncaptioned = $derived(images.filter((i) => !i.caption).length)
  const withTrigger = $derived(
    project.trigger ? images.filter((i) => splitTags(i.caption).includes(project.trigger)).length : 0,
  )
  const size = $derived(
    SIZES.findIndex((s) => s.width === settings.sample_prompts[0]?.width && s.height === settings.sample_prompts[0]?.height),
  )

  function setSize(index: number) {
    for (const p of settings.sample_prompts) Object.assign(p, { width: SIZES[index].width, height: SIZES[index].height })
  }

  function addPrompt() {
    const base = settings.sample_prompts[0]
    settings.sample_prompts.push({
      prompt: project.trigger ? `${project.trigger}, ` : '',
      negative_prompt: base?.negative_prompt ?? NEGATIVE,
      width: base?.width ?? 832,
      height: base?.height ?? 1216,
      steps: 24,
      cfg_scale: 6,
      seed: 1000 + settings.sample_prompts.length,
    })
  }

  async function addTriggerToAll() {
    await api.editTags({ image_ids: images.map((i) => i.id), add: [project.trigger], add_position: 'start' })
    onimageschange()
  }

  async function start() {
    starting = true
    error = ''
    try {
      const config = $state.snapshot(settings) as TrainSettings
      config.sample_prompts = config.sample_prompts.filter((p) => p.prompt.trim())
      onstart(await runApi.create(project.id, '', config))
    } catch (e) {
      error = String(e)
      starting = false
    }
  }

  const torchHelp = $derived(around(t().setup.torchHelp))

  const nullable = (value: string) => (value.trim() === '' ? null : Number(value))
</script>

<div class="setup">
  <div class="form">
    {#if images.length === 0}
      <div class="notice">
        <p>{t().setup.noImages}</p>
        <button class="btn btn-sm btn-primary" onclick={ongotodataset}>{t().setup.gotoDataset}</button>
      </div>
    {/if}

    {#if trainer && !trainer.ready}
      <div class="notice column">
        {#if trainer.problem === 'missing'}
          <p>{t().setup.torchMissing}</p>
        {:else if trainer.problem === 'no_gpu'}
          <p>{t().setup.torchNoGpu(trainer.torch_version)}</p>
        {:else}
          <p>{t().setup.torchBroken}</p>
        {/if}
        <p class="help">
          {torchHelp[0]}<a class="link" href="https://pytorch.org/get-started/locally/" target="_blank" rel="noreferrer">pytorch.org</a>{torchHelp[1]}
        </p>
        <code class="mono command">
          "{trainer.python}" -m pip install torch --index-url &lt;{t().setup.installSource}&gt;{trainer.problem === 'missing' ? '' : ' --force-reinstall'}
        </code>
      </div>
    {/if}

    <section>
      <h2>{t().setup.modelTitle}</h2>
      <p class="help">{t().setup.modelHelp}</p>
      {#if models.length}
        <select class="select select-sm" value={settings.base_model} onchange={(e) => pickModel(e.currentTarget.value)}>
          {#each models as model (model.path)}
            <option value={model.path}>{t().setup.modelOption(model.name, model.size_gb)}</option>
          {/each}
        </select>
        {#if selectedModel?.v_prediction}
          <p class="help">{t().setup.vPrediction}</p>
        {/if}
      {:else if modelsLoaded}
        <p class="help">{t().setup.modelDirHelp}</p>
        <div class="line">
          <input type="text" class="input input-sm mono wide" placeholder="D:\ComfyUI\models\checkpoints" bind:value={modelDir} />
          <button class="btn btn-sm" disabled={!modelDir.trim()} onclick={addModelDir}>{t().setup.useFolder}</button>
        </div>
      {/if}
    </section>

    <section>
      <h2>{t().setup.lengthTitle}</h2>
      <p class="help">{t().setup.lengthHelp(settings.repeats)}</p>
      <div class="line">
        <input type="number" class="input input-sm short" min="1" max="200" bind:value={settings.epochs} />
        <span>{t().setup.rounds}</span>
        <span class="muted num">
          {t().setup.totalSteps(steps)}{#if secondsPerStep}{t().setup.estimate(formatDuration(steps * secondsPerStep))}{/if}
        </span>
      </div>
    </section>

    <section>
      <h2>{t().setup.capacityTitle}</h2>
      <div class="choices">
        {#each CAPACITIES as dim (dim)}
          <button
            class="choice"
            class:active={settings.network_dim === dim}
            onclick={() => ((settings.network_dim = dim), (settings.network_alpha = dim / 2))}
          >
            <strong>{t().setup.capacities[dim].name}</strong>
            <span>{t().setup.capacities[dim].hint}</span>
          </button>
        {/each}
      </div>
    </section>

    <section>
      <h2>{t().setup.samplesTitle}</h2>
      <p class="help">{t().setup.samplesHelp}</p>
      {#each settings.sample_prompts as prompt, index (index)}
        <div class="line top">
          <textarea class="textarea wide" rows="2" bind:value={prompt.prompt}></textarea>
          <button class="btn btn-sm btn-ghost btn-square" title={t().setup.removePrompt} onclick={() => settings.sample_prompts.splice(index, 1)}><X /></button>
        </div>
      {/each}
      <div class="line">
        <button class="btn btn-sm" onclick={addPrompt}><Plus />{t().setup.addPrompt}</button>
        <select class="select select-sm" value={size} onchange={(e) => setSize(Number(e.currentTarget.value))}>
          {#each SIZES as s, i (s.shape)}<option value={i}>{t().setup.sizes[s.shape]} {s.width}×{s.height}</option>{/each}
        </select>
      </div>
    </section>

    <details>
      <summary>{t().setup.more}</summary>
      <div class="fields">
        <label><span>{t().setup.lr}</span><input class="input input-sm" type="number" step="0.00001" bind:value={settings.unet_lr} /></label>
        <label>
          <span>{t().setup.optimizer}</span>
          <select class="select select-sm" bind:value={settings.optimizer}>
            <option value="adamw">AdamW</option>
            <option value="prodigy">{t().setup.prodigy}</option>
          </select>
        </label>
        <label>
          <span>{t().setup.scheduler}</span>
          <select class="select select-sm" bind:value={settings.lr_scheduler}>
            {#each SCHEDULERS as s (s)}<option value={s}>{t().setup.schedulers[s]}</option>{/each}
          </select>
        </label>
        <label><span>{t().setup.warmup}</span><input class="input input-sm" type="number" min="0" bind:value={settings.lr_warmup_steps} /></label>
        <label><span>Rank</span><input class="input input-sm" type="number" min="1" max="256" bind:value={settings.network_dim} /></label>
        <label><span>Alpha</span><input class="input input-sm" type="number" min="0" step="0.5" bind:value={settings.network_alpha} /></label>
        <label><span>{t().setup.batchSize}</span><input class="input input-sm" type="number" min="1" max="8" bind:value={settings.batch_size} /></label>
        <label><span>{t().setup.repeats}</span><input class="input input-sm" type="number" min="1" max="100" bind:value={settings.repeats} /></label>
        <label>
          <span>{t().setup.resolution}</span>
          <select class="select select-sm" bind:value={settings.resolution}>
            <option value={768}>768</option>
            <option value={1024}>1024</option>
          </select>
        </label>
        <label>
          <span>Min-SNR gamma</span>
          <input class="input input-sm"
            type="number"
            min="0"
            placeholder={t().setup.off}
            value={settings.min_snr_gamma ?? ''}
            onchange={(e) => (settings.min_snr_gamma = nullable(e.currentTarget.value))}
          />
        </label>
        <label>
          <span>Noise offset</span>
          <input class="input input-sm"
            type="number"
            min="0"
            step="0.01"
            placeholder={t().setup.off}
            value={settings.noise_offset ?? ''}
            onchange={(e) => (settings.noise_offset = nullable(e.currentTarget.value))}
          />
        </label>
        <label><span>{t().setup.seed}</span><input class="input input-sm" type="number" bind:value={settings.seed} /></label>
        <label>
          <span>{t().setup.keepTokens}</span>
          <input class="input input-sm" type="number" min="0" bind:value={settings.keep_tokens} />
        </label>
        <label>
          <span>{t().setup.captionDropout}</span>
          <input class="input input-sm" type="number" min="0" max="1" step="0.05" bind:value={settings.caption_dropout_rate} />
        </label>
        <label>
          <span>{t().setup.precision}</span>
          <select class="select select-sm" bind:value={settings.mixed_precision} disabled={trainer?.device === 'mps'}>
            {#if trainer?.device === 'mps'}
              <option value="no">{t().setup.precisionMac}</option>
            {:else}
              <option value="fp16">{t().setup.precisionFp16}</option>
              <option value="bf16">bf16</option>
              <option value="no">{t().setup.precisionFull}</option>
            {/if}
          </select>
        </label>
        <label><span>{t().setup.outputName}</span><input class="input input-sm" type="text" bind:value={settings.output_name} /></label>
        <label class="check"><input class="checkbox checkbox-sm" type="checkbox" bind:checked={settings.shuffle_caption} /><span>{t().setup.shuffle}</span></label>
        <label class="check">
          <input class="checkbox checkbox-sm" type="checkbox" bind:checked={settings.train_text_encoder} /><span>{t().setup.trainTextEncoder}</span>
        </label>
        {#if settings.train_text_encoder}
          <label>
            <span>{t().setup.textEncoderLr}</span>
            <input class="input input-sm" type="number" step="0.00001" bind:value={settings.text_encoder_lr} />
          </label>
        {/if}
      </div>
    </details>
  </div>

  <aside>
    <h2>{t().setup.summaryTitle}</h2>
    <dl>
      <dt>{t().setup.images}</dt>
      <dd class="num">{t().setup.imageCount(images.length)}</dd>
      <dt>{t().setup.baseModel}</dt>
      <dd>{selectedModel?.name ?? t().setup.notChosen}</dd>
      <dt>{t().setup.length}</dt>
      <dd class="num">{t().setup.lengthValue(settings.epochs, steps)}</dd>
      <dt>{t().setup.output}</dt>
      <dd class="num">{t().setup.outputValue(Math.ceil(settings.epochs / settings.save_every_n_epochs))}</dd>
    </dl>

    {#if images.length > 0 && !count.ok}
      <p class="warn">
        {t().setup.fewImages(count.text)}<button class="link link-primary" onclick={ongotodataset}>{t().setup.gotoDataset}</button>
      </p>
    {/if}
    {#if uncaptioned > 0}
      <p class="warn">{t().setup.uncaptioned(uncaptioned)}<button class="link link-primary" onclick={ongotodataset}>{t().setup.fix}</button></p>
    {/if}
    {#if project.kind !== 'style' && !project.trigger}
      <p class="warn">{t().setup.noTrigger}</p>
    {:else if project.trigger && images.length > 0 && withTrigger < images.length}
      {@const [before, after] = around(t().setup.triggerPartial(withTrigger, images.length))}
      <p class="warn">
        {before}<code>{project.trigger}</code>{after}
        <button class="link link-primary" onclick={addTriggerToAll}>{t().common.addTriggerToAll}</button>
      </p>
    {/if}
    {#if lastRun}
      <p class="muted small">{t().setup.inherited(lastRun.name)}</p>
    {/if}
    {#if error}<p class="error">{error}</p>{/if}

    <button class="btn btn-primary btn-lg start" disabled={starting || !settings.base_model || images.length === 0 || trainer?.ready === false} onclick={start}>
      <Play />{t().setup.start}
    </button>
  </aside>
</div>

<style>
  .setup {
    flex: 1;
    display: grid;
    grid-template-columns: minmax(0, 1fr) 300px;
    min-height: 0;
  }
  .form {
    overflow-y: auto;
    padding: var(--space-5) var(--space-5) 64px;
    display: flex;
    flex-direction: column;
    gap: 28px;
  }
  .form > * {
    max-width: 640px;
    width: 100%;
  }
  section {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  h2 {
    font-size: var(--text-lg);
  }
  .help {
    margin: 0;
    color: var(--text-2);
    line-height: 1.6;
  }
  .line {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  .line.top {
    align-items: flex-start;
  }
  .wide {
    flex: 1;
  }
  .mono {
    font-family: var(--font-mono);
    font-size: var(--text-sm);
  }
  .short {
    width: 88px;
  }
  .line .select {
    width: auto;
  }
  section > select {
    max-width: 420px;
  }

  .choices {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: var(--space-2);
  }
  .choice {
    padding: var(--space-3) var(--space-4);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-lg);
    background: var(--bg);
    transition: border-color 0.12s;
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    text-align: left;
    white-space: normal;
    align-items: flex-start;
  }
  .choice span {
    color: var(--text-2);
    font-size: var(--text-sm);
    line-height: 1.5;
  }
  .choice strong {
    font-family: var(--font-display);
    font-size: 15px;
  }
  .choice:hover {
    border-color: var(--text-3);
  }
  .choice.active {
    border-color: var(--accent);
    box-shadow: inset 0 0 0 1px var(--accent);
    background: var(--accent-bg);
  }
  .choice.active strong {
    color: var(--accent);
  }

  details summary {
    cursor: pointer;
    color: var(--text-2);
    width: fit-content;
  }
  .fields {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--space-2) var(--space-5);
    margin-top: var(--space-3);
  }
  .fields label {
    display: grid;
    grid-template-columns: 1fr 150px;
    align-items: center;
    gap: var(--space-2);
  }
  .fields label span {
    color: var(--text-2);
  }
  .fields label.check {
    grid-template-columns: auto 1fr;
  }

  .notice {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    padding: var(--space-3) var(--space-4);
    border-radius: var(--radius-lg);
    background: var(--accent-bg);
  }
  .notice p {
    margin: 0;
  }
  .notice.column {
    flex-direction: column;
    align-items: stretch;
    gap: var(--space-2);
  }
  .command {
    overflow-wrap: anywhere;
    user-select: all;
  }

  aside {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    padding: var(--space-5) var(--space-4);
    background: var(--bg);
    border-left: 1px solid var(--border);
    overflow-y: auto;
  }
  dl {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: var(--space-2) var(--space-3);
    margin: 0;
  }
  dt {
    color: var(--text-2);
  }
  dd {
    margin: 0;
    text-align: right;
    overflow-wrap: anywhere;
  }
  aside p {
    margin: 0;
    line-height: 1.6;
  }
  .warn {
    color: var(--warn);
    font-size: var(--text-sm);
  }
  .error {
    color: var(--danger);
    font-size: var(--text-sm);
    overflow-wrap: anywhere;
  }
  .small {
    font-size: var(--text-sm);
  }
  .start {
    margin-top: var(--space-2);
  }
</style>
