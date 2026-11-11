<script lang="ts">
  import { api, errorText, type Project } from './api'
  import { countRange, kindTips } from './guidance'
  import { t } from './i18n/index.svelte'

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

  const KINDS = ['character', 'style', 'concept'] as const

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
    if (!confirm(t().project.confirmDelete(project.name))) return
    try {
      await api.deleteProject(project.id)
      ondelete?.()
    } catch (e) {
      error = errorText(e, t().common.projectBusy)
    }
  }
</script>

<dialog class="modal" bind:this={dialog} {onclose}>
  <div class="modal-box">
  <form onsubmit={submit}>
    <h2>{project ? t().project.editTitle : t().project.newTitle}</h2>

    <label>
      <span>{t().project.name}</span>
      <!-- svelte-ignore a11y_autofocus -->
      <input class="input input-sm" type="text" bind:value={name} required autofocus />
    </label>

    <label>
      <span>{t().project.kind}</span>
      <select class="select select-sm" bind:value={kind}>
        {#each KINDS as k (k)}<option value={k}>{t().project.kindOptions[k]}</option>{/each}
      </select>
    </label>
    <p class="help">{t().project.prepare(countRange(kind), kindTips(kind)[0])}</p>

    <label>
      <span>{t().project.trigger}</span>
      <input class="input input-sm" type="text" bind:value={trigger} placeholder={t().project.triggerPlaceholder} />
    </label>
    <p class="help">{t().project.triggerHelp}</p>

    {#if error}<p class="error">{error}</p>{/if}

    <div class="actions">
      {#if project}<button type="button" class="btn btn-sm btn-ghost text-error" onclick={remove}>{t().project.delete}</button>{/if}
      <span class="spacer"></span>
      <button class="btn btn-sm" type="button" onclick={onclose}>{t().common.cancel}</button>
      <button class="btn btn-sm btn-primary" disabled={!name.trim()}>{project ? t().common.save : t().project.create}</button>
    </div>
  </form>
  </div>
  <form method="dialog" class="modal-backdrop"><button>{t().common.close}</button></form>
</dialog>

<style>
  /* Two columns: labels as wide as the longest one in the current language, then the fields. */
  .modal-box form {
    display: grid;
    grid-template-columns: auto 1fr;
    align-items: center;
    gap: var(--space-3) var(--space-2);
  }
  .modal-box form > :global(*) {
    grid-column: 1 / -1;
  }
  h2 {
    font-size: var(--text-xl);
    margin-bottom: var(--space-2);
  }
  .modal-box form > label {
    display: contents;
  }
  label span {
    color: var(--text-2);
    grid-column: 1;
  }
  label :global(input),
  label :global(select) {
    grid-column: 2;
  }
  .modal-box form > .help {
    grid-column: 2;
    margin: calc(-1 * var(--space-1)) 0 0;
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
