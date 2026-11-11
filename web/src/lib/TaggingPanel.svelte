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
  import { around, t } from './i18n/index.svelte'

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

  const GOALS = ['character', 'style', 'concept', 'general'] as const
  const FORMATS = ['danbooru', 'natural', 'mixed'] as const
  // Issues for which a tag was left out of the suggestion, rather than kept and flagged.
  const SKIPPED = ['banned', 'fixed_trait', 'not_in_vocabulary'] as const
  type Skipped = (typeof SKIPPED)[number]

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
    const m = t().tagging
    if (selectedIds.length) return { ids: selectedIds, label: m.targetSelected(selectedIds.length) }
    const uncaptioned = images.filter((i) => !i.caption).map((i) => i.id)
    if (uncaptioned.length) return { ids: uncaptioned, label: m.targetUncaptioned(uncaptioned.length) }
    return { ids: images.map((i) => i.id), label: m.targetAll(images.length) }
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
      skipped: s.issues.filter((i) => (SKIPPED as readonly string[]).includes(i.kind)),
    }
  }
</script>

<div class="panel">
  <header>
    <h2>{t().tagging.title}</h2>
    <span class="muted">{t().tagging.subtitle}</span>
    <span class="spacer"></span>
    <button class="btn btn-sm" onclick={onclose}><X />{t().common.close}</button>
  </header>

  {#if !profile || !tagging}
    <p class="pad muted">{error || t().common.loading}</p>
  {:else}
    <div class="columns">
      <div class="form">
        <section>
          <h3>{t().tagging.modelTitle}</h3>
          {#if editingModel}
            <p class="help">{t().tagging.modelHelp}</p>
            <label><span>{t().settings.baseUrl}</span><input type="text" class="input input-sm mono" placeholder="http://localhost:11434/v1" bind:value={baseUrl} /></label>
            <label><span>{t().settings.model}</span><input type="text" class="input input-sm mono" placeholder="qwen2.5vl:7b" bind:value={model} /></label>
            <label><span>{t().settings.apiKey}</span><input type="text" class="input input-sm mono" placeholder={t().settings.apiKeyPlaceholder} bind:value={apiKey} /></label>
            <div class="row">
              <button class="btn btn-sm btn-primary" disabled={!baseUrl.trim() || !model.trim()} onclick={saveModel}>{t().common.save}</button>
              {#if tagging.configured}<button class="btn btn-sm" onclick={() => (editingModel = false)}>{t().common.cancel}</button>{/if}
            </div>
          {:else}
            <div class="row">
              <code>{model}</code>
              <button class="link link-primary" onclick={() => (editingModel = true)}>{t().common.change}</button>
            </div>
          {/if}
        </section>

        <section>
          <h3>{t().tagging.goalTitle}</h3>
          <div class="goals">
            {#each GOALS as g (g)}
              <button class={['btn btn-sm', profile.goal === g && 'btn-primary btn-soft']} onclick={() => (profile!.goal = g)}>{t().tagging.goals[g].name}</button>
            {/each}
          </div>
          <p class="help">{t().tagging.goals[profile.goal].hint}</p>
          {#if profile.goal === 'character'}
            <label class="stacked">
              <span>{t().tagging.fixedTraits}</span>
              <input type="text" class="input input-sm mono" placeholder="silver hair, red eyes, cat ears" bind:value={fixedTraits} />
            </label>
          {:else if profile.goal === 'concept'}
            <label class="stacked">
              <span>{t().tagging.concept}</span>
              <input class="input input-sm" type="text" placeholder={t().tagging.conceptPlaceholder} bind:value={profile.concept} />
            </label>
          {/if}
        </section>

        <section>
          <h3>{t().tagging.formatTitle}</h3>
          <select class="select select-sm" bind:value={profile.format}>
            {#each FORMATS as f (f)}<option value={f}>{t().tagging.formats[f]}</option>{/each}
          </select>
          {#if profile.format !== 'natural'}
            <label class="stacked">
              <span>{t().tagging.preferred}</span>
              <textarea class="textarea" rows="2" placeholder={t().tagging.commaSeparated} bind:value={preferred}></textarea>
            </label>
            <label class="check"><input class="checkbox checkbox-sm" type="checkbox" bind:checked={profile.preferred_only} /><span>{t().tagging.preferredOnly}</span></label>
            <label class="stacked">
              <span>{t().tagging.banned}</span>
              <input type="text" class="input input-sm mono" placeholder={t().tagging.commaSeparated} bind:value={banned} />
            </label>
            {#if profile.format === 'danbooru' && tagging.dictionary_size === 0}
              {@const [before, after] = around(t().tagging.noDictionary)}
              <p class="help">{before}<code>dictionaries</code>{after}</p>
            {/if}
          {/if}
          <label class="stacked">
            <span>{t().tagging.extra}</span>
            <textarea class="textarea" rows="2" placeholder={t().tagging.extraPlaceholder} bind:value={profile.extra_instructions}></textarea>
          </label>
          <details>
            <summary>{t().tagging.showPrompt}</summary>
            <pre>{prompt}</pre>
          </details>
        </section>

        <section class="actions">
          {#if error}<p class="error">{error}</p>{/if}
          {#if tagging.job?.running}
            <div class="row">
              <span class="num">{t().tagging.progress(tagging.job.done, tagging.job.total)}</span>
              <button class="btn btn-sm" onclick={() => taggingApi.cancel(project.id)}>{t().common.stop}</button>
            </div>
          {:else}
            <p class="help">{t().tagging.targetHelp(target.label)}</p>
            <div class="row">
              <button class="btn btn-sm" disabled={!tagging.configured || !target.ids.length} onclick={() => start(target.ids.slice(0, 3))}>
                {t().tagging.tryFirst(Math.min(3, target.ids.length))}
              </button>
              <button class="btn btn-sm btn-primary" disabled={!tagging.configured || !target.ids.length} onclick={() => start(target.ids)}>
                {t().tagging.runAll(target.label)}
              </button>
            </div>
          {/if}
        </section>
      </div>

      <div class="review">
        {#if tagging.job?.errors.length}
          <div class="errors">
            <strong>{t().tagging.failed(tagging.job.errors.length)}</strong>
            <span>{tagging.job.errors[0].message}</span>
          </div>
        {/if}

        {#if tagging.suggestions.length}
          <div class="review-head">
            <span>{t().tagging.pending(tagging.suggestions.length)}</span>
            <span class="legend"><span class="tag new">{t().tagging.legendNew}</span><span class="tag">{t().tagging.legendKept}</span><span class="tag warn">{t().tagging.legendUnknown}</span></span>
            <span class="spacer"></span>
            <button class="btn btn-sm" onclick={() => discard(tagging!.suggestions)}>{t().tagging.discardAll}</button>
            <button class="btn btn-sm btn-primary" onclick={() => accept(tagging!.suggestions)}>{t().tagging.acceptAll}</button>
          </div>
          <div class="suggestions">
            {#each tagging.suggestions as s (s.image_id)}
              {@const d = diff(s)}
              <article>
                <img src={thumbUrl(s.image_id)} alt="" />
                <div class="body">
                  <div class="tags">
                    {#each d.tags as item, index (`${index} ${item.tag}`)}
                      <button
                        class="tag"
                        class:new={item.isNew}
                        class:warn={item.issue?.kind === 'unknown'}
                        class:struck={removed[s.image_id]?.includes(item.tag)}
                        title={item.issue?.kind === 'corrected'
                          ? t().tagging.corrected(item.issue.original ?? '')
                          : item.issue
                            ? t().tagging.unknownTitle
                            : t().tagging.strikeTitle}
                        onclick={() => strike(s.image_id, item.tag)}>{item.tag}</button
                      >
                    {/each}
                  </div>
                  {#if d.dropped.length}
                    <p class="note">{t().tagging.willDrop}<span class="mono">{d.dropped.join(', ')}</span></p>
                  {/if}
                  {#if d.skipped.length}
                    <p class="note">
                      {t().tagging.skipped}{#each d.skipped as issue, i (`${i} ${issue.tag}`)}{i ? t().common.comma : ''}<span class="mono"
                          >{issue.tag}</span
                        >{t().tagging.reason(t().tagging.issueReason[issue.kind as Skipped])}{/each}
                    </p>
                  {/if}
                </div>
                <div class="decide">
                  <button class="btn btn-sm btn-primary" onclick={() => accept([s])}>{t().tagging.accept}</button>
                  <button class="btn btn-sm" onclick={() => discard([s])}>{t().tagging.discard}</button>
                </div>
              </article>
            {/each}
          </div>
        {:else if tagging.job?.running}
          <p class="pad muted">{t().tagging.arriving}</p>
        {:else}
          <p class="pad muted">{t().tagging.empty}</p>
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
    grid-template-columns: 96px 1fr;
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
