<script lang="ts">
  import { X } from '@lucide/svelte'
  import {
    runApi,
    splitTags,
    taggingApi,
    thumbUrl,
    type DatasetImage,
    type Project,
    type TaggingProfile,
    type TaggingState,
    type TagSuggestion,
  } from './api'

  let {
    project,
    images,
    selectedIds,
    onclose,
    onaccepted,
  }: {
    project: Project
    images: DatasetImage[]
    selectedIds: number[]
    onclose: () => void
    onaccepted: (updated: DatasetImage[]) => void
  } = $props()

  const GOALS = [
    { id: 'character', name: '一个角色', hint: '角色固有的外貌不写进标注，让它们绑定到触发词上；服装、姿势、表情、背景等会变化的内容都标出来。' },
    { id: 'style', name: '一种画风', hint: '画风、笔触、媒介都不写，让它们绑定到触发词上；画面里的内容尽量标全。' },
    { id: 'concept', name: '一个概念', hint: '要学的概念本身（比如一件衣服、一个姿势）不写，其余都标出来。' },
    { id: 'general', name: '不特别针对', hint: '看到什么标什么。' },
  ] as const
  const ISSUE_REASON = { banned: '在禁用列表里', fixed_trait: '角色固有特征', not_in_vocabulary: '不在指定标签里' }

  let tagging = $state<TaggingState | null>(null)
  let profile = $state<TaggingProfile | null>(null)
  let prompt = $state('')
  let error = $state('')
  let removed = $state<Record<number, string[]>>({}) // tags the user struck from a suggestion

  // Vision model connection
  let editingModel = $state(false)
  let baseUrl = $state('')
  let apiKey = $state('')
  let model = $state('')

  // Comma-separated text fields backing the profile's lists
  let fixedTraits = $state('')
  let preferred = $state('')
  let banned = $state('')

  const list = (text: string) => splitTags(text.replaceAll('\n', ','))
  const imageById = $derived(new Map(images.map((i) => [i.id, i])))

  // What "start" will work on: the selection if there is one, else whatever lacks a caption, else everything.
  const target = $derived.by(() => {
    if (selectedIds.length) return { ids: selectedIds, label: `选中的 ${selectedIds.length} 张` }
    const uncaptioned = images.filter((i) => !i.caption).map((i) => i.id)
    if (uncaptioned.length) return { ids: uncaptioned, label: `还没有标注的 ${uncaptioned.length} 张` }
    return { ids: images.map((i) => i.id), label: `全部 ${images.length} 张` }
  })

  async function refresh() {
    tagging = await taggingApi.get(project.id)
  }

  async function init() {
    await refresh()
    profile = tagging!.profile
    prompt = tagging!.prompt
    fixedTraits = profile.fixed_traits.join(', ')
    preferred = profile.preferred_tags.join(', ')
    banned = profile.banned_tags.join(', ')
    const settings = await runApi.getSettings()
    baseUrl = settings.tagger_base_url
    apiKey = settings.tagger_api_key
    model = settings.tagger_model
    editingModel = !tagging!.configured
  }
  init().catch((e) => (error = String(e)))

  const currentProfile = (): TaggingProfile => ({
    ...$state.snapshot(profile!),
    fixed_traits: list(fixedTraits),
    preferred_tags: list(preferred),
    banned_tags: list(banned),
  })

  // Keep the instruction preview in step with the form.
  $effect(() => {
    if (!profile) return
    const body = currentProfile()
    const timer = setTimeout(async () => (prompt = (await taggingApi.prompt(body)).prompt), 300)
    return () => clearTimeout(timer)
  })

  // Poll while a job runs.
  $effect(() => {
    if (!tagging?.job?.running) return
    const timer = setInterval(refresh, 1500)
    return () => clearInterval(timer)
  })

  async function saveModel() {
    const settings = await runApi.getSettings()
    await runApi.putSettings({ ...settings, tagger_base_url: baseUrl.trim(), tagger_api_key: apiKey.trim(), tagger_model: model.trim() })
    editingModel = false
    await refresh()
  }

  async function start(ids: number[]) {
    error = ''
    try {
      await taggingApi.run(project.id, ids, currentProfile())
      for (const id of ids) delete removed[id] // strikes belonged to the suggestions being replaced
      await refresh()
    } catch (e) {
      error = String(e)
    }
  }

  function finalCaption(s: TagSuggestion) {
    const struck = removed[s.image_id] ?? []
    return struck.length ? splitTags(s.caption).filter((t) => !struck.includes(t)).join(', ') : s.caption
  }

  async function accept(suggestions: TagSuggestion[]) {
    const captions = Object.fromEntries(suggestions.map((s) => [s.image_id, finalCaption(s)]))
    onaccepted(await taggingApi.accept(suggestions.map((s) => s.image_id), captions))
    await refresh()
  }

  async function discard(suggestions: TagSuggestion[]) {
    await taggingApi.discard(suggestions.map((s) => s.image_id))
    await refresh()
  }

  function strike(imageId: number, tag: string) {
    const current = removed[imageId] ?? []
    removed[imageId] = current.includes(tag) ? current.filter((t) => t !== tag) : [...current, tag]
  }

  // Split a suggestion into display parts, compared with the image's current caption.
  function diff(s: TagSuggestion) {
    const current = splitTags(imageById.get(s.image_id)?.caption ?? '')
    const proposed = splitTags(s.caption)
    const flagged = new Map(s.issues.filter((i) => i.kind === 'unknown' || i.kind === 'corrected').map((i) => [i.tag, i]))
    return {
      tags: proposed.map((tag) => ({ tag, isNew: !current.includes(tag), issue: flagged.get(tag) })),
      dropped: current.filter((tag) => !proposed.includes(tag)),
      skipped: s.issues.filter((i) => i.kind in ISSUE_REASON),
    }
  }
</script>

<div class="panel">
  <header>
    <h2>自动标注</h2>
    <span class="muted">让视觉模型看图写标注。结果先作为建议列出，你确认后才会写入。</span>
    <span class="spacer"></span>
    <button class="btn btn-sm" onclick={onclose}><X />关闭</button>
  </header>

  {#if !profile || !tagging}
    <p class="pad muted">{error || '正在读取…'}</p>
  {:else}
    <div class="columns">
      <div class="form">
        <section>
          <h3>用哪个模型看图</h3>
          {#if editingModel}
            <p class="help">任何兼容 OpenAI 接口的视觉模型都可以：云端服务，或本机的 Ollama、LM Studio。素材不适合发到云端时，用本机模型。</p>
            <label><span>服务地址</span><input type="text" class="input input-sm mono" placeholder="http://localhost:11434/v1" bind:value={baseUrl} /></label>
            <label><span>模型名</span><input type="text" class="input input-sm mono" placeholder="qwen2.5vl:7b" bind:value={model} /></label>
            <label><span>API Key</span><input type="text" class="input input-sm mono" placeholder="本机模型可留空" bind:value={apiKey} /></label>
            <div class="row">
              <button class="btn btn-sm btn-primary" disabled={!baseUrl.trim() || !model.trim()} onclick={saveModel}>保存</button>
              {#if tagging.configured}<button class="btn btn-sm" onclick={() => (editingModel = false)}>取消</button>{/if}
            </div>
          {:else}
            <div class="row">
              <code>{model}</code>
              <button class="link link-primary" onclick={() => (editingModel = true)}>更改</button>
            </div>
          {/if}
        </section>

        <section>
          <h3>这个 LoRA 要学什么</h3>
          <div class="goals">
            {#each GOALS as g (g.id)}
              <button class={['btn btn-sm', profile.goal === g.id && 'btn-primary btn-soft']} onclick={() => (profile!.goal = g.id)}>{g.name}</button>
            {/each}
          </div>
          <p class="help">{GOALS.find((g) => g.id === profile!.goal)?.hint}</p>
          {#if profile.goal === 'character'}
            <label class="stacked">
              <span>这个角色固有的特征</span>
              <input type="text" class="input input-sm mono" placeholder="silver hair, red eyes, cat ears" bind:value={fixedTraits} />
            </label>
          {:else if profile.goal === 'concept'}
            <label class="stacked">
              <span>要学的概念是什么</span>
              <input class="input input-sm" type="text" placeholder="例如：一件特定的红色旗袍" bind:value={profile.concept} />
            </label>
          {/if}
        </section>

        <section>
          <h3>标注怎么写</h3>
          <select class="select select-sm" bind:value={profile.format}>
            <option value="danbooru">Danbooru 标签（二次元底模用这个）</option>
            <option value="natural">自然语言描述</option>
            <option value="mixed">标签加一句描述</option>
          </select>
          {#if profile.format !== 'natural'}
            <label class="stacked">
              <span>优先使用这些标签</span>
              <textarea class="textarea" rows="2" placeholder="用逗号分隔" bind:value={preferred}></textarea>
            </label>
            <label class="check"><input class="checkbox checkbox-sm" type="checkbox" bind:checked={profile.preferred_only} /><span>只允许使用上面这些标签</span></label>
            <label class="stacked">
              <span>不要出现的标签</span>
              <input type="text" class="input input-sm mono" placeholder="用逗号分隔" bind:value={banned} />
            </label>
            {#if profile.format === 'danbooru' && tagging.dictionary_size === 0}
              <p class="help">
                没有安装标签词典，所以无法检查模型写的标签是否真实存在。把 danbooru.csv 放进数据目录下的
                <code>dictionaries</code> 文件夹后会自动启用校验。
              </p>
            {/if}
          {/if}
          <label class="stacked">
            <span>其他要求</span>
            <textarea class="textarea" rows="2" placeholder="例如：服装细节写详细一些" bind:value={profile.extra_instructions}></textarea>
          </label>
          <details>
            <summary>查看发给模型的完整指令</summary>
            <pre>{prompt}</pre>
          </details>
        </section>

        <section class="actions">
          {#if error}<p class="error">{error}</p>{/if}
          {#if tagging.job?.running}
            <div class="row">
              <span class="num">正在标注 {tagging.job.done} / {tagging.job.total}</span>
              <button class="btn btn-sm" onclick={() => taggingApi.cancel(project.id)}>停止</button>
            </div>
          {:else}
            <p class="help">对象：{target.label}。建议先试几张，看结果满意再全部标注。</p>
            <div class="row">
              <button class="btn btn-sm" disabled={!tagging.configured || !target.ids.length} onclick={() => start(target.ids.slice(0, 3))}>
                先试 {Math.min(3, target.ids.length)} 张
              </button>
              <button class="btn btn-sm btn-primary" disabled={!tagging.configured || !target.ids.length} onclick={() => start(target.ids)}>
                标注{target.label}
              </button>
            </div>
          {/if}
        </section>
      </div>

      <div class="review">
        {#if tagging.job?.errors.length}
          <div class="errors">
            <strong>{tagging.job.errors.length} 张没有成功</strong>
            <span>{tagging.job.errors[0].message}</span>
          </div>
        {/if}

        {#if tagging.suggestions.length}
          <div class="review-head">
            <span>{tagging.suggestions.length} 条建议待确认</span>
            <span class="legend"><span class="tag new">新增</span><span class="tag">已有</span><span class="tag warn">词典里没有</span></span>
            <span class="spacer"></span>
            <button class="btn btn-sm" onclick={() => discard(tagging!.suggestions)}>全部丢弃</button>
            <button class="btn btn-sm btn-primary" onclick={() => accept(tagging!.suggestions)}>全部采用</button>
          </div>
          <div class="suggestions">
            {#each tagging.suggestions as s (s.image_id)}
              {@const d = diff(s)}
              <article>
                <img src={thumbUrl(s.image_id)} alt="" />
                <div class="body">
                  <div class="tags">
                    {#each d.tags as t, index (`${index} ${t.tag}`)}
                      <button
                        class="tag"
                        class:new={t.isNew}
                        class:warn={t.issue?.kind === 'unknown'}
                        class:struck={removed[s.image_id]?.includes(t.tag)}
                        title={t.issue?.kind === 'corrected'
                          ? `模型写的是"${t.issue.original}"，已按词典改正`
                          : t.issue
                            ? '标签词典里没有这个词，点击去掉'
                            : '点击去掉这个标签'}
                        onclick={() => strike(s.image_id, t.tag)}>{t.tag}</button
                      >
                    {/each}
                  </div>
                  {#if d.dropped.length}
                    <p class="note">会去掉现有的：<span class="mono">{d.dropped.join(', ')}</span></p>
                  {/if}
                  {#if d.skipped.length}
                    <p class="note">
                      已略过：{#each d.skipped as issue, i (`${i} ${issue.tag}`)}{i ? '，' : ''}<span class="mono">{issue.tag}</span>（{ISSUE_REASON[
                          issue.kind as keyof typeof ISSUE_REASON
                        ]}）{/each}
                    </p>
                  {/if}
                </div>
                <div class="decide">
                  <button class="btn btn-sm btn-primary" onclick={() => accept([s])}>采用</button>
                  <button class="btn btn-sm" onclick={() => discard([s])}>丢弃</button>
                </div>
              </article>
            {/each}
          </div>
        {:else if tagging.job?.running}
          <p class="pad muted">标注结果会陆续出现在这里。</p>
        {:else}
          <p class="pad muted">还没有待确认的建议。在左边说明要求，然后开始标注。</p>
        {/if}
      </div>
    </div>
  {/if}
</div>

<style>
  .panel {
    position: absolute;
    inset: 0;
    z-index: 5;
    background: var(--bg);
    display: flex;
    flex-direction: column;
  }
  header {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-3) var(--space-5);
    border-bottom: 1px solid var(--border);
    background: var(--surface);
    flex: none;
  }
  h2 {
    font-size: var(--text-xl);
  }
  h3 {
    font-size: 15px;
  }
  .spacer {
    flex: 1;
  }
  .pad {
    padding: var(--space-5);
    margin: 0;
  }

  .columns {
    flex: 1;
    display: grid;
    grid-template-columns: 380px minmax(0, 1fr);
    min-height: 0;
  }
  .form {
    overflow: hidden auto;
    padding: var(--space-4);
    background: var(--surface);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    gap: var(--space-5);
  }
  section {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  /* The start buttons stay reachable however long the form above grows. */
  .actions {
    position: sticky;
    bottom: calc(-1 * var(--space-4));
    margin: 0 calc(-1 * var(--space-4)) calc(-1 * var(--space-4));
    padding: var(--space-3) var(--space-4) var(--space-4);
    background: var(--surface);
    border-top: 1px solid var(--border);
  }
  .help {
    margin: 0;
    color: var(--text-2);
    font-size: var(--text-sm);
    line-height: 1.6;
  }
  label {
    display: grid;
    grid-template-columns: 72px 1fr;
    align-items: center;
    gap: var(--space-2);
  }
  label > span {
    color: var(--text-2);
  }
  label.stacked {
    grid-template-columns: 1fr;
    gap: var(--space-1);
  }
  label.check {
    grid-template-columns: auto 1fr;
  }
  .mono {
    font-family: var(--font-mono);
    font-size: var(--text-sm);
  }
  .row {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  .goals {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: var(--space-1);
  }
  .goals :global(.btn) {
    padding-inline: 0;
  }
  details summary {
    cursor: pointer;
    color: var(--text-2);
    font-size: var(--text-sm);
  }
  pre {
    margin: var(--space-2) 0 0;
    padding: var(--space-2);
    background: var(--bg);
    border-radius: var(--radius);
    font: var(--text-xs) / 1.5 var(--font-mono);
    white-space: pre-wrap;
    max-height: 260px;
    overflow-y: auto;
  }
  .error {
    margin: 0;
    color: var(--danger);
    font-size: var(--text-sm);
    overflow-wrap: anywhere;
  }

  .review {
    display: flex;
    flex-direction: column;
    min-height: 0;
  }
  .review-head {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-2) var(--space-4);
    border-bottom: 1px solid var(--border);
    flex: none;
  }
  .legend {
    display: flex;
    gap: var(--space-1);
  }
  .errors {
    padding: var(--space-2) var(--space-4);
    background: color-mix(in srgb, var(--danger) 14%, var(--surface));
    display: flex;
    gap: var(--space-3);
    overflow-wrap: anywhere;
    flex: none;
  }
  .suggestions {
    overflow-y: auto;
    flex: 1;
  }
  article {
    display: grid;
    grid-template-columns: 96px minmax(0, 1fr) auto;
    gap: var(--space-3);
    padding: var(--space-3) var(--space-4);
    border-bottom: 1px solid var(--border);
  }
  article img {
    width: 96px;
    height: 128px;
    object-fit: cover;
    object-position: center 20%;
    border-radius: 6px;
  }
  .body {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .tags {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1);
  }
  .tag {
    display: inline-flex;
    align-items: center;
    height: 26px;
    padding: 0 9px;
    border: 1px solid transparent;
    border-radius: 6px;
    background: var(--surface-2);
    font-family: var(--font-mono);
    font-size: var(--text-sm);
    color: var(--text-2);
  }
  .tag.new {
    color: var(--text);
    border-color: color-mix(in srgb, var(--accent) 50%, var(--border));
    background: var(--accent-bg);
  }
  .tag.warn {
    border-color: var(--warn);
    color: var(--warn);
    background: none;
  }
  .tag.struck {
    text-decoration: line-through;
    opacity: 0.5;
  }
  .note {
    margin: 0;
    font-size: var(--text-sm);
    color: var(--text-2);
  }
  .decide {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
</style>
