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
    type TrainSettings,
  } from './api'

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
    { label: '竖图 832×1216', width: 832, height: 1216 },
    { label: '方图 1024×1024', width: 1024, height: 1024 },
    { label: '横图 1216×832', width: 1216, height: 832 },
  ]
  // How much the LoRA can hold. Alpha follows at half the rank.
  const CAPACITIES = [
    { dim: 8, name: '小', hint: '文件小，不容易学过头。适合特征简单的角色。' },
    { dim: 16, name: '标准', hint: '大多数角色和概念用这个。' },
    { dim: 32, name: '大', hint: '能记住更多细节。适合画风，或细节复杂的角色。' },
  ]
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
      if (!models.length) error = '这个文件夹里没有找到 SDXL 底模（.safetensors）。'
    } catch (e) {
      error = String(e)
    }
  }

  const selectedModel = $derived(models.find((m) => m.path === settings.base_model))
  const steps = $derived(Math.ceil((images.length * settings.repeats) / settings.batch_size) * settings.epochs)
  const secondsPerStep = $derived(lastRun?.progress.seconds_per_step ?? null)

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

  const nullable = (value: string) => (value.trim() === '' ? null : Number(value))
</script>

<div class="setup">
  <div class="form">
    {#if images.length === 0}
      <div class="notice">
        <p>数据集里还没有图片，先导入要学习的图片。</p>
        <button class="btn btn-sm btn-primary" onclick={ongotodataset}>去数据集</button>
      </div>
    {/if}

    <section>
      <h2>在哪个底模上训练</h2>
      <p class="help">选你平时出图用的那个底模，或者它所属系列的基础模型。LoRA 在同系列的模型上通用。</p>
      {#if models.length}
        <select class="select select-sm" value={settings.base_model} onchange={(e) => pickModel(e.currentTarget.value)}>
          {#each models as model (model.path)}
            <option value={model.path}>{model.name}（{model.size_gb} GB）</option>
          {/each}
        </select>
        {#if selectedModel?.v_prediction}
          <p class="help">这是 v-prediction 模型，已自动使用对应的训练方式。</p>
        {/if}
      {:else if modelsLoaded}
        <p class="help">还不知道你的底模放在哪里。填入存放 SDXL 底模的文件夹：</p>
        <div class="line">
          <input type="text" class="input input-sm mono wide" placeholder="D:\ComfyUI\models\checkpoints" bind:value={modelDir} />
          <button class="btn btn-sm" disabled={!modelDir.trim()} onclick={addModelDir}>使用这个文件夹</button>
        </div>
      {/if}
    </section>

    <section>
      <h2>训练多久</h2>
      <p class="help">
        每一轮把所有图片学 {settings.repeats} 遍。轮数太少学不像，太多会学过头（画面僵硬、只会复刻原图）。每一轮都会保存并出预览图，训练完可以挑最好的那一轮。
      </p>
      <div class="line">
        <input type="number" class="input input-sm short" min="1" max="200" bind:value={settings.epochs} />
        <span>轮</span>
        <span class="muted num">
          共 {steps} 步{#if secondsPerStep}，约 {formatDuration(steps * secondsPerStep)}（按上次的速度估算，不含出图）{/if}
        </span>
      </div>
    </section>

    <section>
      <h2>LoRA 的容量</h2>
      <div class="choices">
        {#each CAPACITIES as c (c.dim)}
          <button
            class="choice"
            class:active={settings.network_dim === c.dim}
            onclick={() => ((settings.network_dim = c.dim), (settings.network_alpha = c.dim / 2))}
          >
            <strong>{c.name}</strong>
            <span>{c.hint}</span>
          </button>
        {/each}
      </div>
    </section>

    <section>
      <h2>训练中的预览图</h2>
      <p class="help">每一轮结束后，用这些提示词各出一张图。种子固定，所以可以逐轮对比变化。写你最想检验的场景。</p>
      {#each settings.sample_prompts as prompt, index (index)}
        <div class="line top">
          <textarea class="textarea wide" rows="2" bind:value={prompt.prompt}></textarea>
          <button class="btn btn-sm btn-ghost btn-square" title="删除这条" onclick={() => settings.sample_prompts.splice(index, 1)}><X /></button>
        </div>
      {/each}
      <div class="line">
        <button class="btn btn-sm" onclick={addPrompt}><Plus />加一条提示词</button>
        <select class="select select-sm" value={size} onchange={(e) => setSize(Number(e.currentTarget.value))}>
          {#each SIZES as s, i (s.label)}<option value={i}>{s.label}</option>{/each}
        </select>
      </div>
    </section>

    <details>
      <summary>更多设置</summary>
      <div class="fields">
        <label><span>学习率</span><input class="input input-sm" type="number" step="0.00001" bind:value={settings.unet_lr} /></label>
        <label>
          <span>优化器</span>
          <select class="select select-sm" bind:value={settings.optimizer}>
            <option value="adamw">AdamW</option>
            <option value="prodigy">Prodigy（自动调学习率）</option>
          </select>
        </label>
        <label>
          <span>学习率变化</span>
          <select class="select select-sm" bind:value={settings.lr_scheduler}>
            <option value="cosine">逐渐降低（cosine）</option>
            <option value="constant">保持不变</option>
            <option value="constant_with_warmup">预热后不变</option>
            <option value="cosine_with_restarts">周期重启</option>
            <option value="linear">线性降低</option>
          </select>
        </label>
        <label><span>预热步数</span><input class="input input-sm" type="number" min="0" bind:value={settings.lr_warmup_steps} /></label>
        <label><span>Rank</span><input class="input input-sm" type="number" min="1" max="256" bind:value={settings.network_dim} /></label>
        <label><span>Alpha</span><input class="input input-sm" type="number" min="0" step="0.5" bind:value={settings.network_alpha} /></label>
        <label><span>每步图片数</span><input class="input input-sm" type="number" min="1" max="8" bind:value={settings.batch_size} /></label>
        <label><span>每轮重复次数</span><input class="input input-sm" type="number" min="1" max="100" bind:value={settings.repeats} /></label>
        <label>
          <span>训练分辨率</span>
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
            placeholder="关闭"
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
            placeholder="关闭"
            value={settings.noise_offset ?? ''}
            onchange={(e) => (settings.noise_offset = nullable(e.currentTarget.value))}
          />
        </label>
        <label><span>随机种子</span><input class="input input-sm" type="number" bind:value={settings.seed} /></label>
        <label>
          <span>固定前几个标签</span>
          <input class="input input-sm" type="number" min="0" bind:value={settings.keep_tokens} />
        </label>
        <label>
          <span>整条标注丢弃率</span>
          <input class="input input-sm" type="number" min="0" max="1" step="0.05" bind:value={settings.caption_dropout_rate} />
        </label>
        <label>
          <span>计算精度</span>
          <select class="select select-sm" bind:value={settings.mixed_precision}>
            <option value="fp16">fp16（推荐）</option>
            <option value="bf16">bf16</option>
            <option value="no">全精度（慢，占显存）</option>
          </select>
        </label>
        <label><span>输出文件名</span><input class="input input-sm" type="text" bind:value={settings.output_name} /></label>
        <label class="check"><input class="checkbox checkbox-sm" type="checkbox" bind:checked={settings.shuffle_caption} /><span>每步打乱标签顺序（标注是完整句子时不要开）</span></label>
        <label class="check">
          <input class="checkbox checkbox-sm" type="checkbox" bind:checked={settings.train_text_encoder} /><span>同时训练文本编码器</span>
        </label>
        {#if settings.train_text_encoder}
          <label>
            <span>文本编码器学习率</span>
            <input class="input input-sm" type="number" step="0.00001" bind:value={settings.text_encoder_lr} />
          </label>
        {/if}
      </div>
    </details>
  </div>

  <aside>
    <h2>这次训练</h2>
    <dl>
      <dt>图片</dt>
      <dd class="num">{images.length} 张</dd>
      <dt>底模</dt>
      <dd>{selectedModel?.name ?? '未选择'}</dd>
      <dt>时长</dt>
      <dd class="num">{settings.epochs} 轮，{steps} 步</dd>
      <dt>产出</dt>
      <dd class="num">{Math.ceil(settings.epochs / settings.save_every_n_epochs)} 个可选的 LoRA</dd>
    </dl>

    {#if uncaptioned > 0}
      <p class="warn">有 {uncaptioned} 张图片没有标注，它们会被当作"无提示词"来学。<button class="link link-primary" onclick={ongotodataset}>去处理</button></p>
    {/if}
    {#if project.kind !== 'style' && !project.trigger}
      <p class="warn">这个项目没有设置触发词，训练出的内容只能靠其他标签带出来。</p>
    {:else if project.trigger && images.length > 0 && withTrigger < images.length}
      <p class="warn">
        触发词 <code>{project.trigger}</code> 只出现在 {withTrigger} / {images.length} 张图片的标注里。
        <button class="link link-primary" onclick={addTriggerToAll}>加到所有图片最前面</button>
      </p>
    {/if}
    {#if lastRun}
      <p class="muted small">设置沿用自上一次训练 {lastRun.name}。</p>
    {/if}
    {#if error}<p class="error">{error}</p>{/if}

    <button class="btn btn-primary btn-lg start" disabled={starting || !settings.base_model || images.length === 0} onclick={start}>
      <Play />开始训练
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
