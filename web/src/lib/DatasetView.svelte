<script lang="ts">
  import { api, fileUrl, splitTags, thumbUrl, type DatasetImage, type ImportResult, type Project } from './api'
  import TagChips from './TagChips.svelte'
  import TaggingPanel from './TaggingPanel.svelte'

  let { project, onchange }: { project: Project; onchange: () => void } = $props()

  const SMALL_SIDE = 768 // images whose short side is below this are flagged

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
  <!-- Left: filters -->
  <section class="filters">
    <div class="panel-head">
      <span class="label">标签</span>
      <span class="muted num">{tagCounts.length}</span>
    </div>
    <input type="search" placeholder="筛选标签" bind:value={tagSearch} />
    <div class="tag-list">
      {#each visibleTagCounts as [tag, count] (tag)}
        <button class="tag-row" class:active={filterTags.includes(tag)} onclick={() => toggleFilterTag(tag)}>
          <span class="tag-name">{tag}</span>
          <span class="num">{count}</span>
        </button>
      {:else}
        <p class="muted hint">{images.length ? '没有匹配的标签' : '导入图片后，这里会列出所有标签及出现次数。'}</p>
      {/each}
    </div>

    <div class="panel-head"><span class="label">问题</span></div>
    <button
      class="tag-row"
      class:active={filterProblem === 'uncaptioned'}
      disabled={!uncaptionedCount}
      onclick={() => (filterProblem = filterProblem === 'uncaptioned' ? '' : 'uncaptioned')}
    >
      <span class:warn={uncaptionedCount > 0}>缺标注</span>
      <span class="num">{uncaptionedCount}</span>
    </button>
    <button
      class="tag-row"
      class:active={filterProblem === 'small'}
      disabled={!smallCount}
      onclick={() => (filterProblem = filterProblem === 'small' ? '' : 'small')}
    >
      <span class:warn={smallCount > 0}>短边小于 {SMALL_SIDE}</span>
      <span class="num">{smallCount}</span>
    </button>
  </section>

  <!-- Centre: grid -->
  <section class="grid-area">
    <div class="toolbar">
      <span class="num">
        {#if visible.length !== images.length}{visible.length} / {/if}{images.length} 张
        {#if selected.size}<span class="muted"> · 已选 {selected.size}</span>{/if}
      </span>
      {#if filterTags.length || filterProblem}
        <button class="ghost" onclick={() => ((filterTags = []), (filterProblem = ''))}>清除筛选</button>
      {/if}
      <span class="status" class:error={message && !message.startsWith('已')}>{busy || message}</span>
      <span class="spacer"></span>
      <input class="size" type="range" min="96" max="320" step="8" bind:value={thumbSize} title="缩略图大小" />
      <button class="danger" disabled={!selected.size} onclick={deleteSelected}>删除</button>
      <button disabled={!images.length} onclick={() => (showTagging = true)}>自动标注</button>
      <button class="primary" onclick={() => (showImport = !showImport)}>导入</button>
    </div>

    {#if showImport}
      <div class="import-bar">
        <button onclick={() => fileInput.click()}>选择文件…</button>
        <span class="muted">或填写本机文件夹路径：</span>
        <input type="text" class="path" placeholder="D:\datasets\my-character" bind:value={folderPath} />
        <button disabled={!folderPath.trim() || !!busy} onclick={importFromFolder}>导入文件夹</button>
        <span class="muted">同名 .txt 会作为标注一并导入。</span>
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
      class="grid"
      class:dragging
      style:--thumb="{thumbSize}px"
      ondragover={(e) => (e.preventDefault(), (dragging = true))}
      ondragleave={() => (dragging = false)}
      ondrop={onDrop}
    >
      {#each visible as image (image.id)}
        <button class="cell" class:selected={selected.has(image.id)} onclick={(e) => clickImage(e, image)}>
          <img src={thumbUrl(image.id)} alt={image.filename} loading="lazy" draggable="false" />
          {#if !image.caption}<span class="badge" title="缺标注">无标注</span>{/if}
        </button>
      {:else}
        <div class="empty">
          {#if images.length}
            <p class="muted">没有符合筛选条件的图片。</p>
          {:else}
            <p>把图片（和同名 .txt 标注）拖到这里，</p>
            <p class="muted">或点右上角的"导入"。</p>
          {/if}
        </div>
      {/each}
    </div>
  </section>

  <!-- Right: inspector -->
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
        <span class="label">标签</span>
        <span class="muted num">{splitTags(single.caption).length}</span>
      </div>
      <TagChips
        tags={splitTags(single.caption)}
        onchange={(tags) => setCaption(single, tags)}
        suggestions={tagCounts.map(([tag]) => tag)}
      />
    {:else if selectedImages.length > 1}
      <div class="panel-head">
        <span class="label">已选 {selectedImages.length} 张</span>
      </div>

      <div class="panel-head"><span class="label">共有标签</span></div>
      <TagChips tags={sharedTags.all} onremove={(tag) => editTags({ remove: [tag] })} readonlyOrder />
      {#if sharedTags.some.length}
        <div class="panel-head"><span class="label">部分图片有</span></div>
        <TagChips tags={sharedTags.some} faded onremove={(tag) => editTags({ remove: [tag] })} readonlyOrder />
      {/if}

      <div class="panel-head"><span class="label">批量添加</span></div>
      <div class="row">
        <input type="text" placeholder="标签，用逗号分隔" bind:value={batchAdd} onkeydown={(e) => e.key === 'Enter' && submitBatchAdd('end')} />
      </div>
      <div class="row">
        <button disabled={!batchAdd.trim()} onclick={() => submitBatchAdd('start')}>加到最前</button>
        <button disabled={!batchAdd.trim()} onclick={() => submitBatchAdd('end')}>加到最后</button>
      </div>

      <div class="panel-head"><span class="label">批量替换</span></div>
      <div class="row">
        <input type="text" placeholder="原标签" bind:value={replaceFrom} />
        <span class="muted">→</span>
        <input type="text" placeholder="新标签" bind:value={replaceTo} onkeydown={(e) => e.key === 'Enter' && submitReplace()} />
      </div>
      <div class="row">
        <button disabled={!replaceFrom.trim() || !replaceTo.trim()} onclick={submitReplace}>替换</button>
      </div>
    {:else}
      <div class="panel-head"><span class="label">数据集</span></div>
      <dl>
        <dt>图片</dt>
        <dd class="num">{images.length}</dd>
        <dt>不同标签</dt>
        <dd class="num">{tagCounts.length}</dd>
        <dt>缺标注</dt>
        <dd class="num" class:warn={uncaptionedCount > 0}>{uncaptionedCount}</dd>
      </dl>
      <p class="muted hint">
        点击选中图片后在这里编辑标签。<br />
        Ctrl+点击 多选，Shift+点击 连选，Ctrl+A 全选，Delete 删除。
      </p>
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
    grid-template-columns: 216px 1fr 312px;
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
    padding: var(--space-3);
    background: var(--surface);
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
    margin-top: var(--space-2);
    font-size: var(--text-xs);
  }
  .panel-head:first-child {
    margin-top: 0;
  }

  .tag-list {
    flex: 1;
    min-height: 80px;
    overflow-y: auto;
    margin: 0 calc(-1 * var(--space-2));
  }
  .tag-row {
    display: flex;
    justify-content: space-between;
    gap: var(--space-2);
    width: 100%;
    height: 24px;
    padding: 0 var(--space-2);
    border: none;
    background: none;
    text-align: left;
    font-size: var(--text-sm);
    color: var(--text-2);
    flex: none;
  }
  .tag-row.active {
    background: var(--accent-bg);
    color: var(--accent);
  }
  .tag-name {
    font-family: var(--font-mono);
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .tag-row.active .tag-name {
    color: inherit;
  }
  .hint {
    font-size: var(--text-sm);
    padding: 0 var(--space-2);
    line-height: 1.7;
  }
  .inspector .hint {
    padding: 0;
  }
  .warn {
    color: var(--warn);
  }

  .toolbar,
  .import-bar {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    border-bottom: 1px solid var(--border);
    flex: none;
  }
  .import-bar {
    background: var(--surface);
    font-size: var(--text-sm);
    flex-wrap: wrap;
  }
  .path {
    flex: 1;
    min-width: 200px;
    font-family: var(--font-mono);
    font-size: var(--text-sm);
  }
  .spacer {
    flex: 1;
  }
  .status {
    font-size: var(--text-sm);
    color: var(--text-2);
  }
  .status.error {
    color: var(--danger);
  }
  .size {
    width: 96px;
  }

  .grid {
    flex: 1;
    overflow-y: auto;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(var(--thumb), 1fr));
    align-content: start;
    grid-auto-rows: max-content;
    gap: var(--space-2);
    padding: var(--space-3);
  }
  .grid.dragging {
    outline: 2px dashed var(--accent);
    outline-offset: -6px;
  }
  .cell {
    position: relative;
    aspect-ratio: 1;
    height: auto;
    padding: 0;
    border: 1px solid transparent;
    border-radius: var(--radius);
    background: var(--surface-2);
    overflow: hidden;
    width: 100%;
    min-height: 0;
  }
  .cell img {
    width: 100%;
    height: 100%;
    object-fit: contain;
    display: block;
  }
  .cell.selected {
    border-color: var(--accent);
    box-shadow: 0 0 0 2px var(--accent);
  }
  .badge {
    position: absolute;
    left: 4px;
    bottom: 4px;
    padding: 0 5px;
    border-radius: 3px;
    background: var(--warn);
    color: #fff;
    font-size: var(--text-xs);
  }
  .empty {
    grid-column: 1 / -1;
    padding: 80px 0;
    text-align: center;
  }
  .empty p {
    margin: 0;
    line-height: 1.8;
  }

  .preview {
    display: block;
    background: var(--surface-2);
    border-radius: var(--radius);
    overflow: hidden;
    flex: none;
  }
  .preview img {
    display: block;
    width: 100%;
    max-height: 340px;
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
  .row input {
    flex: 1;
    font-family: var(--font-mono);
    font-size: var(--text-sm);
  }
  dl {
    display: grid;
    grid-template-columns: 1fr auto;
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
