<script lang="ts">
  // A list of tag chips. With `onchange` it is a full editor (add, remove); with only
  // `onremove` it shows removable chips, used for the batch view of a multi-selection.
  let {
    tags,
    onchange,
    onremove,
    suggestions = [],
    faded = false,
    readonlyOrder = false,
  }: {
    tags: string[]
    onchange?: (tags: string[]) => void
    onremove?: (tag: string) => void
    suggestions?: string[]
    faded?: boolean
    readonlyOrder?: boolean
  } = $props()

  let draft = $state('')
  const listId = `tags-${Math.random().toString(36).slice(2)}`

  function remove(tag: string) {
    if (onremove) onremove(tag)
    else onchange?.(tags.filter((t) => t !== tag))
  }

  function add() {
    const incoming = draft
      .split(',')
      .map((t) => t.trim())
      .filter((t) => t && !tags.includes(t))
    draft = ''
    if (incoming.length) onchange?.([...tags, ...incoming])
  }

  function onKeydown(event: KeyboardEvent) {
    if (event.key === 'Enter') {
      event.preventDefault()
      add()
    } else if (event.key === 'Backspace' && !draft && tags.length) {
      remove(tags[tags.length - 1])
    }
  }
</script>

<div class="chips" class:faded>
  {#each tags as tag (tag)}
    <span class="chip">
      {tag}
      <button class="x" title="移除" onclick={() => remove(tag)}>×</button>
    </span>
  {:else}
    {#if readonlyOrder}<span class="none">无</span>{/if}
  {/each}

  {#if onchange}
    <input type="text" placeholder="添加标签，回车确认" list={listId} bind:value={draft} onkeydown={onKeydown} onblur={add} />
    <datalist id={listId}>
      {#each suggestions.filter((s) => !tags.includes(s)).slice(0, 200) as suggestion (suggestion)}
        <option value={suggestion}></option>
      {/each}
    </datalist>
  {/if}
</div>

<style>
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1);
  }
  .chip {
    display: inline-flex;
    align-items: center;
    height: 22px;
    padding-left: 7px;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--surface-2);
    font-family: var(--font-mono);
    font-size: var(--text-sm);
  }
  .faded .chip {
    background: none;
    border-style: dashed;
    color: var(--text-2);
  }
  .x {
    width: 20px;
    height: 20px;
    padding: 0;
    border: none;
    background: none;
    color: var(--text-3);
    font-size: 14px;
    line-height: 1;
  }
  .x:hover:not(:disabled) {
    background: none;
    color: var(--danger);
  }
  input {
    flex: 1;
    min-width: 140px;
    height: 22px;
    font-family: var(--font-mono);
    font-size: var(--text-sm);
  }
  .none {
    color: var(--text-3);
    font-size: var(--text-sm);
  }
</style>
