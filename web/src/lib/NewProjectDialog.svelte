<script lang="ts">
  import { api, type Project } from './api'

  // Creates a project, or edits `project` when one is given.
  let {
    project = null,
    onclose,
    onsave,
    ondelete,
  }: {
    project?: Project | null
    onclose: () => void
    onsave: (project: Project) => void
    ondelete?: () => void
  } = $props()

  let dialog: HTMLDialogElement
  // svelte-ignore state_referenced_locally -- the dialog edits a copy of the project it was opened with
  let name = $state(project?.name ?? '')
  // svelte-ignore state_referenced_locally
  let kind = $state<Project['kind']>(project?.kind ?? 'character')
  // svelte-ignore state_referenced_locally
  let trigger = $state(project?.trigger ?? '')
  let error = $state('')

  $effect(() => dialog.showModal())

  async function submit(event: SubmitEvent) {
    event.preventDefault()
    const body = { name: name.trim(), kind, trigger: trigger.trim() }
    try {
      onsave(project ? await api.updateProject(project.id, body) : await api.createProject(body))
    } catch (e) {
      error = String(e)
    }
  }

  async function remove() {
    if (!project) return
    if (!confirm(`删除项目"${project.name}"？它的图片副本、标注和所有训练结果都会被删除，无法恢复。`)) return
    try {
      await api.deleteProject(project.id)
      ondelete?.()
    } catch (e) {
      error = String(e)
    }
  }
</script>

<dialog bind:this={dialog} {onclose}>
  <form onsubmit={submit}>
    <h2>{project ? '项目设置' : '新建项目'}</h2>

    <label>
      <span>名称</span>
      <!-- svelte-ignore a11y_autofocus -->
      <input type="text" bind:value={name} required autofocus />
    </label>

    <label>
      <span>要学什么</span>
      <select bind:value={kind}>
        <option value="character">一个角色</option>
        <option value="style">一种画风</option>
        <option value="concept">一个概念（服装、姿势等）</option>
      </select>
    </label>

    <label>
      <span>触发词</span>
      <input type="text" bind:value={trigger} placeholder="出图时用来调用这个 LoRA 的词" />
    </label>
    <p class="help">触发词最好是一个不存在的词（比如 mychar01），避免和底模已经认识的概念混在一起。</p>

    {#if error}<p class="error">{error}</p>{/if}

    <div class="actions">
      {#if project}<button type="button" class="danger" onclick={remove}>删除项目</button>{/if}
      <span class="spacer"></span>
      <button type="button" onclick={onclose}>取消</button>
      <button class="primary" disabled={!name.trim()}>{project ? '保存' : '创建'}</button>
    </div>
  </form>
</dialog>

<style>
  form {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  h2 {
    font-size: var(--text-lg);
    margin-bottom: var(--space-1);
  }
  label {
    display: grid;
    grid-template-columns: 64px 1fr;
    align-items: center;
    gap: var(--space-2);
  }
  label span {
    color: var(--text-2);
  }
  .help {
    margin: 0 0 0 72px;
    color: var(--text-2);
    font-size: var(--text-sm);
    line-height: 1.6;
  }
  .error {
    margin: 0;
    color: var(--danger);
  }
  .actions {
    display: flex;
    gap: var(--space-2);
    margin-top: var(--space-2);
  }
  .spacer {
    flex: 1;
  }
</style>
