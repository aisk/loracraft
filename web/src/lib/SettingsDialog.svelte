<script lang="ts">
  import { runApi, type Settings } from './api'

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
    <h2>设置</h2>
    {#if settings}
      <label>
        <span>底模所在的文件夹</span>
        <textarea class="textarea" rows="2" placeholder="每行一个文件夹" bind:value={modelDirs}></textarea>
      </label>
      <label>
        <span>LoRA 导出到</span>
        <input class="input input-sm" type="text" placeholder="例如 ComfyUI 的 models\loras" bind:value={settings.export_dir} />
      </label>

      <h3>自动标注用的视觉模型</h3>
      <label><span>服务地址</span><input class="input input-sm" type="text" placeholder="http://localhost:11434/v1" bind:value={settings.tagger_base_url} /></label>
      <label><span>模型名</span><input class="input input-sm" type="text" bind:value={settings.tagger_model} /></label>
      <label><span>API Key</span><input class="input input-sm" type="text" placeholder="本机模型可留空" bind:value={settings.tagger_api_key} /></label>
      <p class="help">API Key 以明文保存在本机的数据目录里，不会发送到模型服务以外的地方。</p>
    {/if}
    {#if error}<p class="error">{error}</p>{/if}
    <div class="actions">
      <button class="btn btn-sm" type="button" onclick={onclose}>取消</button>
      <button class="btn btn-sm btn-primary" disabled={!settings}>保存</button>
    </div>
  </form>
  </div>
  <form method="dialog" class="modal-backdrop"><button>关闭</button></form>
</dialog>

<style>
  .modal-box {
    max-width: 560px;
  }
  .modal-box form {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  h2 {
    font-size: var(--text-xl);
    margin-bottom: var(--space-2);
  }
  h3 {
    font-size: var(--text-md);
    margin-top: var(--space-2);
  }
  label {
    display: grid;
    grid-template-columns: 128px 1fr;
    align-items: start;
    gap: var(--space-2);
  }
  label span {
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
