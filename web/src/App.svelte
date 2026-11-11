<script lang="ts">
  import { api, type Project } from './lib/api'
  import DatasetView from './lib/DatasetView.svelte'
  import NewProjectDialog from './lib/NewProjectDialog.svelte'
  import SettingsDialog from './lib/SettingsDialog.svelte'
  import ResultsView from './lib/ResultsView.svelte'
  import TrainView from './lib/TrainView.svelte'

  const TABS = [
    { id: 'dataset', label: '数据集' },
    { id: 'train', label: '训练' },
    { id: 'results', label: '结果' },
  ] as const
  type TabId = (typeof TABS)[number]['id']

  const KIND_LABEL = { character: '角色', style: '画风', concept: '概念' }

  let projects = $state<Project[]>([])
  // The open project and tab live in the URL hash, so a reload or a shared link lands in the same place.
  const fromHash = new URLSearchParams(location.hash.slice(1))
  let currentId = $state<number | null>(Number(fromHash.get('project')) || null)
  let tab = $state<TabId>(TABS.find((t) => t.id === fromHash.get('tab'))?.id ?? 'dataset')
  $effect(() => {
    if (currentId !== null) history.replaceState(null, '', `#project=${currentId}&tab=${tab}`)
  })
  let showNewProject = $state(false)
  let showEditProject = $state(false)
  let showSettings = $state(false)
  let loadError = $state('')
  let focusRunId = $state<number | null>(null)

  const current = $derived(projects.find((p) => p.id === currentId) ?? null)

  async function refreshProjects() {
    try {
      projects = await api.listProjects()
      loadError = ''
      if (currentId === null || !projects.some((p) => p.id === currentId)) {
        currentId = projects[0]?.id ?? null
      }
    } catch (error) {
      loadError = String(error)
    }
  }

  refreshProjects()
</script>

<div class="shell">
  <aside>
    <div class="brand">LoraCraft</div>

    <div class="section">
      <div class="section-head">
        <span class="label">项目</span>
        <button class="ghost add" title="新建项目" onclick={() => (showNewProject = true)}>+</button>
      </div>
      {#each projects as project (project.id)}
        <button class="nav-item" class:active={project.id === currentId} onclick={() => (currentId = project.id)}>
          <span class="name">{project.name}</span>
          <span class="count num">{project.image_count ?? 0}</span>
        </button>
      {:else}
        <p class="empty muted">还没有项目</p>
      {/each}
    </div>
    <span class="grow"></span>
    <button class="nav-item" onclick={() => (showSettings = true)}>设置</button>
  </aside>

  <main>
    {#if loadError}
      <div class="center">
        <p>无法连接后端：{loadError}</p>
        <button onclick={refreshProjects}>重试</button>
      </div>
    {:else if current}
      <header>
        <h1>{current.name}</h1>
        <span class="kind">{KIND_LABEL[current.kind]}</span>
        {#if current.trigger}<code class="trigger">{current.trigger}</code>{/if}
        <button class="ghost edit" onclick={() => (showEditProject = true)}>项目设置</button>
        <nav>
          {#each TABS as t (t.id)}
            <button class="tab" class:active={tab === t.id} onclick={() => (tab = t.id)}>{t.label}</button>
          {/each}
        </nav>
      </header>

      {#if tab === 'dataset'}
        {#key current.id}
          <DatasetView project={current} onchange={refreshProjects} />
        {/key}
      {:else if tab === 'train'}
        {#key current.id}
          <TrainView
            project={current}
            ongotodataset={() => (tab = 'dataset')}
            ongotoresults={(runId) => ((focusRunId = runId), (tab = 'results'))}
          />
        {/key}
      {:else}
        {#key current.id}
          <ResultsView project={current} {focusRunId} ongototrain={() => (tab = 'train')} />
        {/key}
      {/if}
    {:else}
      <div class="center">
        <p class="muted">新建一个项目开始：每个项目对应一个要训练的 LoRA。</p>
        <button class="primary" onclick={() => (showNewProject = true)}>新建项目</button>
      </div>
    {/if}
  </main>
</div>

{#if showNewProject}
  <NewProjectDialog
    onclose={() => (showNewProject = false)}
    onsave={async (project) => {
      showNewProject = false
      await refreshProjects()
      currentId = project.id
      tab = 'dataset'
    }}
  />
{/if}

{#if showEditProject && current}
  <NewProjectDialog
    project={current}
    onclose={() => (showEditProject = false)}
    onsave={async () => {
      showEditProject = false
      await refreshProjects()
    }}
    ondelete={async () => {
      showEditProject = false
      currentId = null
      await refreshProjects()
    }}
  />
{/if}

{#if showSettings}
  <SettingsDialog onclose={() => (showSettings = false)} />
{/if}

<style>
  .grow {
    flex: 1;
  }
  .edit {
    height: 24px;
    padding: 0 var(--space-2);
    font-size: var(--text-sm);
    color: var(--text-2);
  }
  .shell {
    display: grid;
    grid-template-columns: 208px 1fr;
    height: 100%;
  }

  aside {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    padding: var(--space-3) var(--space-2);
    background: var(--surface);
    border-right: 1px solid var(--border);
    overflow-y: auto;
  }
  .brand {
    padding: var(--space-1) var(--space-2);
    font-size: var(--text-lg);
    font-weight: 700;
    letter-spacing: -0.01em;
  }
  .section-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 var(--space-2);
    height: var(--row-height);
  }
  .add {
    width: 24px;
    height: 24px;
    padding: 0;
    font-size: 16px;
    line-height: 1;
    color: var(--text-2);
  }
  .nav-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    width: 100%;
    border: none;
    background: none;
    text-align: left;
    padding: 0 var(--space-2);
  }
  .nav-item.active {
    background: var(--accent-bg);
    color: var(--accent);
    font-weight: 600;
  }
  .nav-item .name {
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .nav-item .count {
    font-size: var(--text-xs);
    color: var(--text-3);
    font-weight: 400;
  }
  .empty {
    padding: 0 var(--space-2);
    font-size: var(--text-sm);
  }

  main {
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
  }
  header {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    height: 44px;
    padding: 0 var(--space-4);
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    flex: none;
  }
  h1 {
    font-size: var(--text-lg);
  }
  .kind {
    font-size: var(--text-xs);
    color: var(--text-2);
    border: 1px solid var(--border);
    border-radius: 3px;
    padding: 0 5px;
  }
  .trigger {
    font-family: var(--font-mono);
    font-size: var(--text-sm);
    color: var(--text-2);
  }
  nav {
    display: flex;
    align-self: stretch;
    margin-left: var(--space-4);
  }
  .tab {
    height: 100%;
    border: none;
    border-radius: 0;
    background: none;
    color: var(--text-2);
    border-bottom: 2px solid transparent;
    border-top: 2px solid transparent;
    padding: 0 var(--space-3);
  }
  .tab:hover:not(:disabled) {
    background: none;
    color: var(--text);
  }
  .tab.active {
    color: var(--text);
    font-weight: 600;
    border-bottom-color: var(--accent);
  }

  .center {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--space-3);
  }
</style>
