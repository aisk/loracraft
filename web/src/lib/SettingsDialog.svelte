<script lang="ts">
  import { runApi, type Settings } from './api'
  import { t } from './i18n/index.svelte'

  let { onclose }: { onclose: () => void } = $props()

  let dialog: HTMLDialogElement
  let settings = $state<Settings | null>(null)
  let modelDirs = $state('')
  let error = $state('')

  $effect(() => dialog.showModal())

  runApi
    .getSettings()
    .then((s) => {
      settings = s
      modelDirs = s.model_dirs.join('\n')
    })
    .catch((e) => (error = String(e)))

  async function submit(event: SubmitEvent) {
    event.preventDefault()
    try {
      await runApi.putSettings({ ...settings!, model_dirs: modelDirs.split('\n').map((d) => d.trim()).filter(Boolean) })
      onclose()
    } catch (e) {
      error = String(e)
    }
  }
</script>

<dialog class="modal" bind:this={dialog} {onclose}>
  <div class="modal-box">
  <form onsubmit={submit}>
    <h2>{t().settings.title}</h2>
    {#if settings}
      <label>
        <span>{t().settings.modelDirs}</span>
        <textarea class="textarea" rows="2" placeholder={t().settings.modelDirsPlaceholder} bind:value={modelDirs}></textarea>
      </label>
      <label>
        <span>{t().settings.exportDir}</span>
        <input class="input input-sm" type="text" placeholder={t().settings.exportDirPlaceholder} bind:value={settings.export_dir} />
      </label>

      <h3>{t().settings.taggerTitle}</h3>
      <label><span>{t().settings.baseUrl}</span><input class="input input-sm" type="text" placeholder="http://localhost:11434/v1" bind:value={settings.tagger_base_url} /></label>
      <label><span>{t().settings.model}</span><input class="input input-sm" type="text" bind:value={settings.tagger_model} /></label>
      <label><span>{t().settings.apiKey}</span><input class="input input-sm" type="text" placeholder={t().settings.apiKeyPlaceholder} bind:value={settings.tagger_api_key} /></label>
      <p class="help">{t().settings.apiKeyHelp}</p>
    {/if}
    {#if error}<p class="error">{error}</p>{/if}
    <div class="actions">
      <button class="btn btn-sm" type="button" onclick={onclose}>{t().common.cancel}</button>
      <button class="btn btn-sm btn-primary" disabled={!settings}>{t().common.save}</button>
    </div>
  </form>
  </div>
  <form method="dialog" class="modal-backdrop"><button>{t().common.close}</button></form>
</dialog>

<style>
  .modal-box {
    max-width: 560px;
  }
  /* Two columns: labels as wide as the longest one in the current language, then the fields. */
  .modal-box form {
    display: grid;
    grid-template-columns: auto 1fr;
    align-items: start;
    gap: var(--space-3) var(--space-3);
  }
  .modal-box form > :global(*) {
    grid-column: 1 / -1;
  }
  .modal-box form > label {
    display: contents;
  }
  label :global(input),
  label :global(textarea) {
    grid-column: 2;
  }
  h2 {
    font-size: var(--text-xl);
    margin-bottom: var(--space-2);
  }
  h3 {
    font-size: var(--text-md);
    margin-top: var(--space-2);
  }
  label span {
    grid-column: 1;
    color: var(--text-2);
    line-height: var(--row-height);
  }
  input {
    font-family: var(--font-mono);
  }
  .help {
    margin: 0;
    color: var(--text-2);
    font-size: var(--text-sm);
  }
  .error {
    margin: 0;
    color: var(--danger);
  }
  .actions {
    display: flex;
    justify-content: flex-end;
    gap: var(--space-2);
  }
</style>
