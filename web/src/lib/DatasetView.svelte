<script lang="ts">
  import { ArrowRight, Check, ImagePlus, Search, Sparkles, Trash2, TriangleAlert, X } from '@lucide/svelte'
  import { api, fileUrl, splitTags, thumbUrl, type DatasetImage, type ImportResult, type Project } from './api'
  import { COMMON_TIPS, CONSTANT_ADVICE, GUIDES, SMALL_SIDE, constantTags, countAdvice, countRange } from './guidance'
  import TagChips from './TagChips.svelte'
  import TaggingPanel from './TaggingPanel.svelte'

  let { project, onchange }: { project: Project; onchange: () => void } = $props()

  let images = $state<DatasetImage[]>([])
  let selected = $state(new Set<number>())
  let anchorId: number | null = null // start of a shift-click range
  let filterTags = $state<string[]>([])
  let filterProblem = $state<'' | 'uncaptioned' | 'small'>('')
  let tagSearch = $state('')
  let thumbSize = $state(168)
  let busy = $state('')
  let message = $state('')
  let dragging = $state(false)
  let folderPath = $state('')
  let showImport = $state(false)
  let showTagging = $state(false)
  let fileInput: HTMLInputElement

  // Batch edit inputs
  let batchAdd = $state('')
  let replaceFrom = $state('')
  let replaceTo = $state('')

  const isSmall = (image: DatasetImage) => Math.min(image.width, image.height) < SMALL_SIDE

  const tagCounts = $derived.by(() => {
    const counts = new Map<string, number>()
    for (const image of images) for (const tag of splitTags(image.caption)) counts.set(tag, (counts.get(tag) ?? 0) + 1)
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
  })
  const visibleTagCounts = $derived(
    tagSearch ? tagCounts.filter(([tag]) => tag.toLowerCase().includes(tagSearch.trim().toLowerCase())) : tagCounts,
  )
  const uncaptionedCount = $derived(images.filter((i) => !i.caption).length)
  const smallCount = $derived(images.filter(isSmall).length)

  const visible = $derived(
    images.filter((image) => {
      if (filterProblem === 'uncaptioned' && image.caption) return false
      if (filterProblem === 'small' && !isSmall(image)) return false
      if (filterTags.length === 0) return true
      const tags = new Set(splitTags(image.caption))
      return filterTags.every((t) => tags.has(t))
    }),
  )
  const selectedImages = $derived(images.filter((i) => selected.has(i.id)))

  // Is the dataset ready to train on?
  const guide = $derived(GUIDES[project.kind])
  const count = $derived(countAdvice(project.kind, images.length))
  const constant = $derived(constantTags(project, images))
  const missingTrigger = $derived(
    project.trigger ? images.filter((i) => !splitTags(i.caption).includes(project.trigger)).length : 0,
  )
  const single = $derived(selectedImages.length === 1 ? selectedImages[0] : null)

  // For a multi-selection: tags on every selected image, and tags on only some of them.
  const sharedTags = $derived.by(() => {
    const counts = new Map<string, number>()
    for (const image of selectedImages) for (const tag of splitTags(image.caption)) counts.set(tag, (counts.get(tag) ?? 0) + 1)
    const all: string[] = []
    const some: string[] = []
    for (const [tag, count] of counts) (count === selectedImages.length ? all : some).push(tag)
    return { all, some }
  })

  async function load() {
    images = await api.listImages(project.id)
  }
  load()

  function applyUpdates(updated: DatasetImage[]) {
    const byId = new Map(updated.map((i) => [i.id, i]))
    images = images.map((i) => byId.get(i.id) ?? i)
  }

  async function run(label: string, action: () => Promise<void>) {
    busy = label
    message = ''
    try {
      await action()
    } catch (error) {
      message = String(error)
    } finally {
      busy = ''
    }
  }

  // --- Selection ---

  function clickImage(event: MouseEvent, image: DatasetImage) {
    const ids = visible.map((i) => i.id)
    // Without a visible anchor (none yet, or filtered away) a shift-click is an ordinary click.
    if (event.shiftKey && anchorId !== null && ids.includes(anchorId)) {
      const [from, to] = [ids.indexOf(anchorId), ids.indexOf(image.id)].sort((a, b) => a - b)
      selected = new Set([...(event.ctrlKey ? selected : []), ...ids.slice(from, to + 1)])
      return
    }
    if (event.ctrlKey || event.metaKey) {
      const next = new Set(selected)
      next.has(image.id) ? next.delete(image.id) : next.add(image.id)
      selected = next
    } else {
      selected = new Set([image.id])
    }
    anchorId = image.id
  }

  function onKeydown(event: KeyboardEvent) {
    if (showTagging || (event.target as HTMLElement).matches('input, textarea, select')) return
    if ((event.ctrlKey || event.metaKey) && event.key === 'a') {
      event.preventDefault()
      selected = new Set(visible.map((i) => i.id))
    } else if (event.key === 'Escape') {
      selected = new Set()
    } else if (event.key === 'Delete' && selected.size > 0) {
      deleteSelected()
    }
  }

  function toggleFilterTag(tag: string) {
    filterTags = filterTags.includes(tag) ? filterTags.filter((t) => t !== tag) : [...filterTags, tag]
  }

  // --- Import and delete ---

  function reportImport(result: ImportResult) {
    images = [...images, ...result.added]
    selected = new Set(result.added.map((i) => i.id))
    message =
      `已导入 ${result.added.length} 张` +
      (result.skipped_duplicates ? `，跳过 ${result.skipped_duplicates} 张重复图片` : '') +
      (result.unreadable.length ? `，${result.unreadable.length} 个文件打不开：${result.unreadable.slice(0, 5).join('、')}` : '') +
      (result.unreadable.length > 5 ? ' 等' : '')
    onchange()
  }

  const upload = (files: File[]) =>
    run('正在导入…', async () => {
      if (files.length) reportImport(await api.uploadImages(project.id, files))
    })

  const importFromFolder = () =>
    run('正在导入…', async () => {
      reportImport(await api.importFolder(project.id, folderPath.trim()))
      showImport = false
    })

  function onDrop(event: DragEvent) {
    event.preventDefault()
    dragging = false
    upload([...(event.dataTransfer?.files ?? [])])
  }

  function deleteSelected() {
    const ids = [...selected]
    if (!confirm(`从数据集中删除 ${ids.length} 张图片？原始文件不受影响，但项目内的副本和标注会被删除。`)) return
    run('正在删除…', async () => {
      await api.deleteImages(ids)
      const deleted = new Set(ids)
      images = images.filter((i) => !deleted.has(i.id))
      selected = new Set([...selected].filter((id) => !deleted.has(id)))
      onchange()
    })
  }

  // --- Tag editing ---

  const editTags = (body: Omit<Parameters<typeof api.editTags>[0], 'image_ids'>) =>
    run('', async () => applyUpdates(await api.editTags({ image_ids: [...selected], ...body })))

  const setCaption = (image: DatasetImage, tags: string[]) =>
    run('', async () => applyUpdates([await api.updateCaption(image.id, tags.join(', '))]))

  const addTriggerToAll = () =>
    run('', async () =>
      applyUpdates(await api.editTags({ image_ids: images.map((i) => i.id), add: [project.trigger], add_position: 'start' })),
    )

  function submitBatchAdd(position: 'start' | 'end') {
    const tags = splitTags(batchAdd)
    if (!tags.length) return
    editTags({ add: tags, add_position: position })
    batchAdd = ''
  }

  function submitReplace() {
    if (!replaceFrom.trim() || !replaceTo.trim()) return
    editTags({ replace: { [replaceFrom.trim()]: replaceTo.trim() } })
    replaceFrom = replaceTo = ''
  }
</script>

<svelte:window onkeydown={onKeydown} />

<div class="dataset">
  <!-- Left: what is in the captions, and what needs attention -->
  <section class="filters">
    {#if uncaptionedCount || smallCount}
      <div class="panel-head"><span class="label-quiet">需要留意</span></div>
      {#if uncaptionedCount}
        <button
          class="issue"
          class:active={filterProblem === 'uncaptioned'}
          onclick={() => (filterProblem = filterProblem === 'uncaptioned' ? '' : 'uncaptioned')}
        >
          <TriangleAlert /><span>没有标注</span><span class="num">{uncaptionedCount}</span>
        </button>
      {/if}
      {#if smallCount}
        <button
          class="issue"
          class:active={filterProblem === 'small'}
          onclick={() => (filterProblem = filterProblem === 'small' ? '' : 'small')}
        >
          <TriangleAlert /><span>短边不到 {SMALL_SIDE} 像素</span><span class="num">{smallCount}</span>
        </button>
      {/if}
    {/if}

    <div class="panel-head">
      <span class="label-quiet">标签</span>
      <span class="muted num">{tagCounts.length} 种</span>
    </div>
    <label class="input input-sm">
      <Search />
      <input type="search" placeholder="找标签" bind:value={tagSearch} />
    </label>
    <div class="tag-list">
      {#each visibleTagCounts as [tag, count] (tag)}
        <!-- The bar shows how much of the dataset carries the tag. -->
        <button
          class="tag-row"
          class:active={filterTags.includes(tag)}
          style:--share="{(count / images.length) * 100}%"
          onclick={() => toggleFilterTag(tag)}
        >
          <span class="tag-name">{tag}</span>
          <span class="num">{count}</span>
        </button>
      {:else}
        <p class="muted hint">{images.length ? '没有匹配的标签' : '放入图片后，这里会列出所有标签和出现的次数。'}</p>
      {/each}
    </div>
  </section>

  <!-- Centre: the images -->
  <section class="grid-area">
    <div class="toolbar">
      <span class="count num">
        {#if visible.length !== images.length}{visible.length} / {/if}{images.length} 张{#if selected.size}，<b>已选 {selected.size}</b>{/if}
      </span>
      {#if filterTags.length || filterProblem}
        <button class="btn btn-xs btn-soft" onclick={() => ((filterTags = []), (filterProblem = ''))}><X />取消筛选</button>
      {/if}
      <span class="notice-text" class:error={message && !message.startsWith('已')}>{busy || message}</span>
      <span class="spacer"></span>
      <input class="range range-xs size" type="range" min="96" max="320" step="8" bind:value={thumbSize} title="缩略图大小" />
      {#if selected.size}
        <button class="btn btn-sm btn-ghost text-error" onclick={deleteSelected}><Trash2 />删除</button>
      {/if}
      <button class="btn btn-sm" disabled={!images.length} onclick={() => (showTagging = true)}><Sparkles />自动标注</button>
      <button class="btn btn-sm btn-primary" onclick={() => (showImport = !showImport)}><ImagePlus />放入图片</button>
    </div>

    {#if showImport}
      <div class="import-bar">
        <button class="btn btn-sm" onclick={() => fileInput.click()}>选择文件…</button>
        <span class="muted">或者填本机的文件夹：</span>
        <input type="text" class="input input-sm path" placeholder="D:\datasets\my-character" bind:value={folderPath} />
        <button class="btn btn-sm" disabled={!folderPath.trim() || !!busy} onclick={importFromFolder}>导入文件夹</button>
        <span class="muted note">同名的 .txt 会作为标注一起导入。</span>
      </div>
    {/if}
    <input
      bind:this={fileInput}
      type="file"
      multiple
      accept="image/*,.txt"
      hidden
      onchange={() => upload([...(fileInput.files ?? [])])}
    />

    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="thumbs"
      class:dragging
      style:--thumb="{thumbSize}px"
      ondragover={(e) => (e.preventDefault(), (dragging = true))}
      ondragleave={() => (dragging = false)}
      ondrop={onDrop}
    >
      {#each visible as image (image.id)}
        <button class="cell" class:selected={selected.has(image.id)} onclick={(e) => clickImage(e, image)}>
          <img src={thumbUrl(image.id)} alt={image.filename} loading="lazy" draggable="false" />
          {#if selected.has(image.id)}<span class="tick"><Check /></span>{/if}
          {#if !image.caption}<span class="flag">没有标注</span>{/if}
        </button>
      {:else}
        <div class="empty">
          {#if images.length}
            <p class="muted">没有符合筛选条件的图片。</p>
          {:else}
            <ImagePlus class="big-icon" />
            <h2>把图片拖到这里</h2>
            <p class="muted">同名的 .txt 会作为标注一起导入。也可以点右上角的"放入图片"。</p>
            <div class="guide">
              <p class="guide-lead">学{guide.noun}，准备 <b class="num">{countRange(project.kind)}</b></p>
              <ul>
                {#each [...guide.tips, ...COMMON_TIPS] as tip (tip)}<li>{tip}</li>{/each}
              </ul>
            </div>
          {/if}
        </div>
      {/each}
    </div>
  </section>

  <!-- Right: the selection -->
  <section class="inspector">
    {#if single}
      <a class="preview" href={fileUrl(single.id)} target="_blank" rel="noreferrer" title="查看原图">
        <img src={fileUrl(single.id)} alt={single.filename} />
      </a>
      <div class="meta">
        <span class="filename" title={single.filename}>{single.filename}</span>
        <span class="muted num" class:warn={isSmall(single)}>{single.width}×{single.height}</span>
      </div>

      <div class="panel-head">
        <span class="label-quiet">标签</span>
        <span class="muted num">{splitTags(single.caption).length}</span>
      </div>
      <TagChips
        tags={splitTags(single.caption)}
        onchange={(tags) => setCaption(single, tags)}
        suggestions={tagCounts.map(([tag]) => tag)}
      />
    {:else if selectedImages.length > 1}
      <h3>已选 {selectedImages.length} 张</h3>

      <div class="panel-head"><span class="label-quiet">每张都有的标签</span></div>
      <TagChips tags={sharedTags.all} onremove={(tag) => editTags({ remove: [tag] })} readonlyOrder />
      {#if sharedTags.some.length}
        <div class="panel-head"><span class="label-quiet">只有部分图片有</span></div>
        <TagChips tags={sharedTags.some} faded onremove={(tag) => editTags({ remove: [tag] })} readonlyOrder />
      {/if}

      <div class="panel-head"><span class="label-quiet">给它们都加上</span></div>
      <input
        type="text"
        class="input input-sm mono"
        placeholder="标签，用逗号分隔"
        bind:value={batchAdd}
        onkeydown={(e) => e.key === 'Enter' && submitBatchAdd('end')}
      />
      <div class="row">
        <button class="btn btn-sm" disabled={!batchAdd.trim()} onclick={() => submitBatchAdd('start')}>加到最前</button>
        <button class="btn btn-sm" disabled={!batchAdd.trim()} onclick={() => submitBatchAdd('end')}>加到最后</button>
      </div>

      <div class="panel-head"><span class="label-quiet">把一个标签换成另一个</span></div>
      <div class="row">
        <input type="text" class="input input-sm mono" placeholder="原标签" bind:value={replaceFrom} />
        <ArrowRight class="arrow" />
        <input
          type="text"
          class="input input-sm mono"
          placeholder="新标签"
          bind:value={replaceTo}
          onkeydown={(e) => e.key === 'Enter' && submitReplace()}
        />
      </div>
      <div class="row">
        <button class="btn btn-sm" disabled={!replaceFrom.trim() || !replaceTo.trim()} onclick={submitReplace}>替换</button>
      </div>
    {:else}
      <h3>数据集</h3>
      <div class="facts">
        <div><span class="figure num">{images.length}</span><span class="muted">张图片</span></div>
        <div><span class="figure num">{tagCounts.length}</span><span class="muted">种标签</span></div>
        <div>
          <span class="figure num" class:warn={uncaptionedCount > 0}>{uncaptionedCount}</span>
          <span class="muted">张没标注</span>
        </div>
      </div>
      {#if images.length}
        <div class="panel-head"><span class="label-quiet">可以训练了吗</span></div>
        <ul class="checks">
          <li class:bad={!count.ok}>
            {#if count.ok}<Check />{:else}<TriangleAlert />{/if}
            <span>{count.text}</span>
          </li>
          <li class:bad={uncaptionedCount > 0}>
            {#if uncaptionedCount}<TriangleAlert />{:else}<Check />{/if}
            <span>
              {#if uncaptionedCount}
                {uncaptionedCount} 张没有标注，训练时学不到它们该对应什么词。
                <button class="link link-primary" onclick={() => (filterProblem = 'uncaptioned')}>看看是哪些</button>
              {:else}
                每张图片都有标注。
              {/if}
            </span>
          </li>
          {#if project.trigger}
            <li class:bad={missingTrigger > 0}>
              {#if missingTrigger}<TriangleAlert />{:else}<Check />{/if}
              <span>
                {#if missingTrigger}
                  {missingTrigger} 张的标注里没有触发词 <code>{project.trigger}</code>。
                  <button class="link link-primary" onclick={addTriggerToAll}>加到所有图片最前面</button>
                {:else}
                  每张图片的标注里都有触发词 <code>{project.trigger}</code>。
                {/if}
              </span>
            </li>
          {/if}
          {#if smallCount}
            <li class="bad">
              <TriangleAlert />
              <span>
                {smallCount} 张短边不到 {SMALL_SIDE} 像素，训练时会被放大，细节发糊。能换成大图就换。
                <button class="link link-primary" onclick={() => (filterProblem = 'small')}>看看是哪些</button>
              </span>
            </li>
          {/if}
          {#if constant.length}
            <li class="bad">
              <TriangleAlert />
              <span>
                几乎每张图都有这些标签：
                <span class="constant">
                  {#each constant.slice(0, 8) as tag (tag)}
                    <button class="mini-tag" class:active={filterTags.includes(tag)} onclick={() => toggleFilterTag(tag)}>{tag}</button>
                  {/each}
                  {#if constant.length > 8}<span class="muted">等 {constant.length} 个</span>{/if}
                </span>
                {CONSTANT_ADVICE[project.kind]}
              </span>
            </li>
          {/if}
        </ul>

        <!-- With no images yet, the empty state in the centre says the same. -->
        <details class="tips" open={!count.ok}>
          <summary>什么样的图片合适</summary>
          <p>学{guide.noun}，一般准备 {countRange(project.kind)}。</p>
          <ul>
            {#each [...guide.tips, ...COMMON_TIPS] as tip (tip)}<li>{tip}</li>{/each}
          </ul>
        </details>
      {/if}

      <p class="muted hint">点一张图片，在这里改它的标签。选中多张可以一起改。</p>
      <dl class="keys">
        <dt><kbd class="kbd kbd-sm">Ctrl</kbd> + 点击</dt>
        <dd>多选</dd>
        <dt><kbd class="kbd kbd-sm">Shift</kbd> + 点击</dt>
        <dd>连选</dd>
        <dt><kbd class="kbd kbd-sm">Ctrl</kbd> + <kbd class="kbd kbd-sm">A</kbd></dt>
        <dd>全选</dd>
        <dt><kbd class="kbd kbd-sm">Delete</kbd></dt>
        <dd>删除选中的</dd>
      </dl>
    {/if}
  </section>

  {#if showTagging}
    <TaggingPanel
      {project}
      {images}
      selectedIds={[...selected]}
      onclose={() => (showTagging = false)}
      onaccepted={applyUpdates}
    />
  {/if}
</div>

<style>
  .dataset {
    position: relative;
    flex: 1;
    display: grid;
    grid-template-columns: 232px 1fr 328px;
    min-height: 0;
  }
  section {
    min-height: 0;
    min-width: 0;
    display: flex;
    flex-direction: column;
  }

  .filters,
  .inspector {
    gap: var(--space-2);
    padding: var(--space-4);
    overflow-y: auto;
  }
  .filters {
    border-right: 1px solid var(--border);
  }
  .inspector {
    border-left: 1px solid var(--border);
  }
  .panel-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin-top: var(--space-3);
    font-size: var(--text-sm);
  }
  .panel-head:first-child {
    margin-top: 0;
  }
  h3 {
    font-size: var(--text-lg);
  }

  .issue {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: 6px var(--space-2);
    border-radius: var(--radius);
    background: color-mix(in oklab, var(--warn) 12%, transparent);
    color: var(--warn);
    font-size: var(--text-sm);
    text-align: left;
  }
  .issue span:first-of-type {
    flex: 1;
  }
  .issue :global(svg) {
    width: 14px;
    height: 14px;
    flex: none;
  }
  .issue.active {
    outline: 1.5px solid var(--warn);
  }

  .filters :global(label.input svg) {
    width: 14px;
    height: 14px;
    opacity: 0.5;
  }
  .tag-list {
    flex: 1;
    min-height: 80px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 1px;
    margin-right: calc(-1 * var(--space-2));
    padding-right: var(--space-2);
  }
  .tag-row {
    position: relative;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: var(--space-2);
    height: 26px;
    padding: 0 var(--space-2);
    border-radius: 6px;
    text-align: left;
    font-size: var(--text-sm);
    color: var(--text-3);
    flex: none;
    overflow: hidden;
  }
  .tag-row::before {
    content: '';
    position: absolute;
    inset: 0 auto 0 0;
    width: var(--share);
    background: color-mix(in oklab, var(--text) 7%, transparent);
    border-radius: 6px;
  }
  .tag-row > * {
    position: relative;
  }
  .tag-row:hover::before {
    background: color-mix(in oklab, var(--text) 13%, transparent);
  }
  .tag-row.active {
    color: var(--accent);
  }
  .tag-row.active::before {
    background: var(--accent-bg);
  }
  .tag-name {
    font-family: var(--font-mono);
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .tag-row.active .tag-name {
    color: inherit;
  }
  .hint {
    font-size: var(--text-sm);
    line-height: 1.7;
  }
  .warn {
    color: var(--warn);
  }

  .grid-area {
    background: var(--bg);
  }
  .toolbar,
  .import-bar {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-4);
    flex: none;
  }
  .toolbar {
    height: 52px;
  }
  .count b {
    color: var(--accent);
    font-weight: 600;
  }
  .import-bar {
    margin: 0 var(--space-4) var(--space-2);
    padding: var(--space-3);
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    font-size: var(--text-sm);
    flex-wrap: wrap;
  }
  .path {
    flex: 1;
    min-width: 200px;
    font-family: var(--font-mono);
  }
  .note {
    flex-basis: 100%;
  }
  .spacer {
    flex: 1;
  }
  .notice-text {
    font-size: var(--text-sm);
    color: var(--text-2);
  }
  .notice-text.error {
    color: var(--danger);
  }
  .size {
    width: 96px;
  }

  .thumbs {
    flex: 1;
    overflow-y: auto;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(var(--thumb), 1fr));
    align-content: start;
    grid-auto-rows: max-content;
    gap: 10px;
    padding: var(--space-1) var(--space-4) var(--space-4);
  }
  .thumbs.dragging {
    outline: 2px dashed var(--accent);
    outline-offset: -8px;
    border-radius: var(--radius-lg);
  }
  .cell {
    position: relative;
    aspect-ratio: 3 / 4;
    border-radius: var(--radius);
    background: var(--surface-2);
    overflow: hidden;
    width: 100%;
    outline: 2px solid transparent;
    outline-offset: 2px;
    transition:
      outline-color 0.1s,
      transform 0.1s;
  }
  .cell img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    object-position: center 20%;
    display: block;
  }
  .cell:hover {
    outline-color: var(--border-strong);
  }
  .cell.selected {
    outline-color: var(--accent);
  }
  .tick {
    position: absolute;
    top: 6px;
    right: 6px;
    display: grid;
    place-items: center;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    background: var(--accent);
    color: var(--color-primary-content);
  }
  .tick :global(svg) {
    width: 13px;
    height: 13px;
    stroke-width: 3;
  }
  .flag {
    position: absolute;
    left: 6px;
    bottom: 6px;
    padding: 1px 6px;
    border-radius: 4px;
    background: var(--warn);
    color: var(--color-warning-content);
    font-size: var(--text-xs);
    font-weight: 600;
  }
  .empty {
    grid-column: 1 / -1;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-2);
    margin: 48px auto;
    padding: 56px 48px;
    border: 1.5px dashed var(--border-strong);
    border-radius: var(--radius-lg);
    text-align: center;
  }
  .empty :global(.big-icon) {
    width: 40px;
    height: 40px;
    color: var(--accent);
    stroke-width: 1.5;
  }
  .empty h2 {
    font-size: var(--text-xl);
  }

  .guide {
    max-width: 460px;
    margin-top: var(--space-4);
    padding-top: var(--space-4);
    border-top: 1px solid var(--border);
    text-align: left;
  }
  .guide-lead {
    margin: 0 0 var(--space-2);
    font-size: 15px;
  }
  .guide-lead b {
    color: var(--accent);
    font-weight: 600;
  }
  .guide ul,
  .tips ul {
    margin: 0;
    padding-left: 1.2em;
    list-style: disc;
    color: var(--text-2);
    line-height: 1.7;
  }
  .guide li + li,
  .tips li + li {
    margin-top: var(--space-1);
  }

  .checks {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
    font-size: var(--text-sm);
    line-height: 1.6;
    color: var(--text-2);
  }
  .checks li {
    display: grid;
    grid-template-columns: 14px 1fr;
    gap: var(--space-2);
  }
  .checks li > :global(svg) {
    width: 14px;
    height: 14px;
    margin-top: 3px;
    color: var(--ok);
  }
  .checks li.bad {
    color: var(--text);
  }
  .checks li.bad > :global(svg) {
    color: var(--warn);
  }
  .checks code {
    font-family: var(--font-mono);
  }
  .constant {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1);
    margin: var(--space-1) 0;
  }
  .mini-tag {
    padding: 0 6px;
    border-radius: 4px;
    background: var(--surface-2);
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    line-height: 20px;
  }
  .mini-tag:hover {
    background: var(--border-strong);
  }
  .mini-tag.active {
    background: var(--accent-bg);
    color: var(--accent);
  }
  .tips {
    margin-top: var(--space-3);
    font-size: var(--text-sm);
  }
  .tips summary {
    cursor: pointer;
    color: var(--text-2);
    width: fit-content;
  }
  .tips p {
    margin: var(--space-2) 0;
  }

  .preview {
    display: block;
    background: var(--bg);
    border-radius: var(--radius);
    overflow: hidden;
    flex: none;
  }
  .preview img {
    display: block;
    width: 100%;
    max-height: 380px;
    object-fit: contain;
  }
  .meta {
    display: flex;
    justify-content: space-between;
    gap: var(--space-2);
    font-size: var(--text-sm);
  }
  .filename {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .row {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  .row :global(.arrow) {
    width: 14px;
    height: 14px;
    flex: none;
    color: var(--text-3);
  }

  .facts {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: var(--space-2);
    margin: var(--space-2) 0;
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
  .keys {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: var(--space-2) var(--space-3);
    margin-top: var(--space-3);
    font-size: var(--text-sm);
    color: var(--text-2);
    align-items: center;
  }
</style>
