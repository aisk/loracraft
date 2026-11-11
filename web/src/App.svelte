<script lang="ts">
  import { Check, ChevronRight, Moon, Plus, Settings, SlidersHorizontal, Sun } from '@lucide/svelte'
  import { api, runApi, thumbUrl, type Project, type Run } from './lib/api'
  import DatasetView from './lib/DatasetView.svelte'
  import NewProjectDialog from './lib/NewProjectDialog.svelte'
  import ResultsView from './lib/ResultsView.svelte'
  import SettingsDialog from './lib/SettingsDialog.svelte'
  import TrainView from './lib/TrainView.svelte'

  type TabId = 'dataset' | 'train' | 'results'
  const TAB_IDS: TabId[] = ['dataset', 'train', 'results']
  const KIND_LABEL = { character: '角色', style: '画风', concept: '概念' }

  let projects = $state<Project[]>([])
  let runs = $state<Run[]>([]) // of the open project, newest first
  // The open project and tab live in the URL hash, so a reload lands in the same place.
  const fromHash = new URLSearchParams(location.hash.slice(1))
  let currentId = $state<number | null>(Number(fromHash.get('project')) || null)
  let tab = $state<TabId>(TAB_IDS.find((t) => t === fromHash.get('tab')) ?? 'dataset')
  $effect(() => {
    if (currentId !== null) history.replaceState(null, '', `#project=${currentId}&tab=${tab}`)
  })
  let showNewProject = $state(false)
  let showEditProject = $state(false)
  let showSettings = $state(false)
  let loadError = $state('')
  let focusRunId = $state<number | null>(null)

  let theme = $state(readTheme())
  function readTheme(): 'darkroom' | 'daylight' {
    try {
      return localStorage.getItem('theme') === 'daylight' ? 'daylight' : 'darkroom'
    } catch {
      return 'darkroom'
    }
  }
  $effect(() => {
    document.documentElement.dataset.theme = theme
    try {
      localStorage.setItem('theme', theme)
    } catch {
      // Private mode: the choice just does not persist.
    }
  })

  const current = $derived(projects.find((p) => p.id === currentId) ?? null)
  const activeRun = $derived(runs.find((r) => r.status === 'queued' || r.status === 'running') ?? null)

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

  // The workflow bar shows where the project stands, so its figures are kept fresh.
  $effect(() => {
    const id = currentId
    runs = []
    if (id === null) return
    let cancelled = false
    const load = async () => {
      try {
        const fresh = await runApi.list(id)
        if (!cancelled) runs = fresh
      } catch {
        // Shown by the views themselves; the bar just keeps its last figures.
      }
    }
    load()
    const timer = setInterval(() => (load(), refreshProjects()), 4000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  })

  const steps = $derived.by(() => {
    if (!current) return []
    const count = current.image_count ?? 0
    const uncaptioned = current.uncaptioned_count ?? 0
    const finished = runs.filter((r) => r.checkpoints.length > 0)

    let train = '还没有训练过'
    if (activeRun) {
      const p = activeRun.progress
      train =
        activeRun.status === 'queued'
          ? '排队中'
          : p.total_steps && p.step
            ? `训练中，${Math.round((p.step / p.total_steps) * 100)}%`
            : '正在准备'
    } else if (runs[0]) {
      train = { done: '上次训练已完成', stopped: '上次训练已停止', failed: '上次训练出错', queued: '', running: '' }[runs[0].status]
    }

    return [
      {
        id: 'dataset' as TabId,
        label: '数据集',
        status: count ? `${count} 张图片` + (uncaptioned ? `，${uncaptioned} 张没有标注` : '') : '先放入图片',
        done: count > 0 && uncaptioned === 0,
        live: false,
      },
      { id: 'train' as TabId, label: '训练', status: train, done: finished.length > 0 && !activeRun, live: !!activeRun },
      {
        id: 'results' as TabId,
        label: '结果',
        status: !finished.length
          ? '训练后在这里挑选'
          : runs.some((r) => r.best_checkpoint)
            ? `${finished.length} 次训练，已选出最佳`
            : `${finished.length} 次训练，等你挑选`,
        done: runs.some((r) => r.best_checkpoint),
        live: false,
      },
    ]
  })
</script>

<div class="shell">
  <aside>
    <div class="brand">
      <span class="mark" aria-hidden="true"></span>
      <span class="word">LoraCraft</span>
    </div>

    <div class="section-head">
      <span class="label-quiet">项目</span>
      <button class="btn btn-ghost btn-xs btn-square" title="新建项目" onclick={() => (showNewProject = true)}>
        <Plus />
      </button>
    </div>
    <div class="projects">
      {#each projects as project (project.id)}
        <button class="project" class:active={project.id === currentId} onclick={() => (currentId = project.id)}>
          {#if project.cover_image_id}
            <img src={thumbUrl(project.cover_image_id)} alt="" />
          {:else}
            <span class="cover-empty"></span>
          {/if}
          <span class="text">
            <span class="name">{project.name}</span>
            <span class="meta num">{KIND_LABEL[project.kind]}，{project.image_count ?? 0} 张</span>
          </span>
          {#if project.active_runs}<span class="live-dot" title="正在训练"></span>{/if}
        </button>
      {:else}
        <p class="empty muted">还没有项目</p>
      {/each}
    </div>

    <div class="foot">
      <button class="btn btn-ghost btn-sm" onclick={() => (showSettings = true)}><Settings />设置</button>
      <button
        class="btn btn-ghost btn-sm btn-square"
        title={theme === 'darkroom' ? '换成浅色界面' : '换成深色界面'}
        onclick={() => (theme = theme === 'darkroom' ? 'daylight' : 'darkroom')}
      >
        {#if theme === 'darkroom'}<Sun />{:else}<Moon />{/if}
      </button>
    </div>
  </aside>

  <main>
    {#if loadError}
      <div class="center">
        <p>连不上 LoraCraft 的后台服务：{loadError}</p>
        <button class="btn" onclick={refreshProjects}>重试</button>
      </div>
    {:else if current}
      <header>
        <div class="title">
          <h1>{current.name}</h1>
          <span class="badge badge-soft badge-sm">{KIND_LABEL[current.kind]}</span>
          {#if current.trigger}<code class="trigger" title="触发词">{current.trigger}</code>{/if}
          <button class="btn btn-ghost btn-xs" onclick={() => (showEditProject = true)}>
            <SlidersHorizontal />项目设置
          </button>
        </div>

        <!-- The three stages of making a LoRA, each saying where this project stands. -->
        <nav aria-label="流程">
          {#each steps as step, index (step.id)}
            {#if index}<ChevronRight class="arrow" aria-hidden="true" />{/if}
            <button class="stage" class:active={tab === step.id} aria-current={tab === step.id} onclick={() => (tab = step.id)}>
              <span class="bullet" class:done={step.done} class:live={step.live}>
                {#if step.done}<Check />{:else}{index + 1}{/if}
              </span>
              <span class="text">
                <span class="stage-name">{step.label}</span>
                <span class="stage-status num">{step.status}</span>
              </span>
            </button>
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
      <div class="center welcome">
        <span class="mark big" aria-hidden="true"></span>
        <h1>从一组图片，做出你自己的 LoRA</h1>
        <p class="muted">每个项目对应一个 LoRA：放入图片、写好标注、训练，再从每一轮的预览图里挑出最好的。</p>
        <button class="btn btn-primary btn-lg" onclick={() => (showNewProject = true)}><Plus />新建项目</button>
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
  .shell {
    display: grid;
    grid-template-columns: 232px 1fr;
    height: 100%;
  }

  aside {
    display: flex;
    flex-direction: column;
    padding: var(--space-4) var(--space-3) var(--space-3);
    background: var(--bg);
    border-right: 1px solid var(--border);
    min-height: 0;
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 0 var(--space-2) var(--space-5);
  }
  /* The mark: a safelight, the one lamp you may leave on while an image develops. */
  .mark {
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: var(--accent);
    box-shadow:
      0 0 0 4px color-mix(in oklab, var(--accent) 22%, transparent),
      0 0 18px color-mix(in oklab, var(--accent) 60%, transparent);
  }
  .mark.big {
    width: 28px;
    height: 28px;
    box-shadow:
      0 0 0 8px color-mix(in oklab, var(--accent) 18%, transparent),
      0 0 60px color-mix(in oklab, var(--accent) 70%, transparent);
    margin-bottom: var(--space-4);
  }
  .word {
    font-family: var(--font-display);
    font-size: 19px;
    font-weight: 700;
    letter-spacing: -0.02em;
  }
  .section-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 var(--space-1) var(--space-1) var(--space-2);
  }
  .projects {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 2px;
    overflow-y: auto;
    min-height: 0;
  }
  .project {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 6px var(--space-2);
    border-radius: var(--radius);
    text-align: left;
    transition: background 0.12s;
  }
  .project:hover {
    background: var(--surface);
  }
  .project.active {
    background: var(--surface-2);
  }
  .project img,
  .cover-empty {
    width: 36px;
    height: 36px;
    border-radius: 6px;
    object-fit: cover;
    flex: none;
    background: var(--surface-2);
  }
  .cover-empty {
    border: 1px dashed var(--border-strong);
    background: none;
  }
  .project .text {
    display: flex;
    flex-direction: column;
    min-width: 0;
    flex: 1;
  }
  .project .name {
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .project .meta {
    font-size: var(--text-xs);
    color: var(--text-3);
  }
  .live-dot,
  .bullet.live {
    animation: pulse 1.6s ease-in-out infinite;
  }
  .live-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--accent);
    flex: none;
  }
  @keyframes pulse {
    50% {
      box-shadow: 0 0 0 5px color-mix(in oklab, var(--accent) 25%, transparent);
    }
  }
  .empty {
    padding: var(--space-2);
    font-size: var(--text-sm);
  }
  .foot {
    display: flex;
    justify-content: space-between;
    padding-top: var(--space-2);
  }

  main {
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
    background: var(--surface);
  }
  header {
    flex: none;
    padding: var(--space-4) var(--space-5) 0;
    border-bottom: 1px solid var(--border);
  }
  .title {
    display: flex;
    align-items: center;
    gap: var(--space-3);
  }
  h1 {
    font-size: var(--text-xl);
    line-height: 1.2;
  }
  .trigger {
    font-family: var(--font-mono);
    font-size: var(--text-sm);
    color: var(--accent);
  }

  nav {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin-top: var(--space-3);
  }
  nav :global(.arrow) {
    width: 16px;
    height: 16px;
    color: var(--text-3);
    flex: none;
    margin-bottom: 10px;
  }
  .stage {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 6px var(--space-3) 14px var(--space-1);
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
    text-align: left;
    color: var(--text-2);
    transition: color 0.12s;
  }
  .stage:hover {
    color: var(--text);
  }
  .stage.active {
    color: var(--text);
    border-bottom-color: var(--accent);
  }
  .bullet {
    display: grid;
    place-items: center;
    width: 24px;
    height: 24px;
    border-radius: 50%;
    border: 1.5px solid var(--border-strong);
    font-family: var(--font-display);
    font-size: var(--text-sm);
    font-weight: 700;
    flex: none;
  }
  .stage.active .bullet {
    border-color: var(--accent);
    color: var(--accent);
  }
  .bullet.done {
    border-color: transparent;
    background: color-mix(in oklab, var(--ok) 18%, transparent);
    color: var(--ok);
  }
  .stage.active .bullet.done {
    color: var(--ok);
  }
  .bullet.live {
    border-color: var(--accent);
    background: var(--accent);
    color: var(--color-primary-content);
  }
  .stage.active .bullet.live {
    color: var(--color-primary-content);
  }
  .bullet :global(svg) {
    width: 14px;
    height: 14px;
  }
  .stage .text {
    display: flex;
    flex-direction: column;
    line-height: 1.3;
  }
  .stage .stage-name {
    font-family: var(--font-display);
    font-size: 15px;
    font-weight: 650;
  }
  .stage .stage-status {
    font-size: var(--text-xs);
    color: var(--text-3);
  }
  .stage.active .stage-status {
    color: var(--text-2);
  }

  .center {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--space-3);
    padding: var(--space-5);
    text-align: center;
  }
  .welcome h1 {
    font-size: 30px;
  }
  .welcome p {
    max-width: 44ch;
    margin-bottom: var(--space-3);
  }
</style>
