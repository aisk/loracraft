<script lang="ts">
  import { X } from '@lucide/svelte'
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
      <button class="x" title="移除" onclick={() => remove(tag)}><X /></button>
    </span>
  {:else}
    {#if readonlyOrder}<span class="none">无</span>{/if}
  {/each}

  {#if onchange}
    <input class="add" type="text" placeholder="添加标签，回车确认" list={listId} bind:value={draft} onkeydown={onKeydown} onblur={add} />
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
    gap: 6px;
  }
  .chip {
    display: inline-flex;
    align-items: center;
    height: 26px;
    padding-left: 9px;
    border-radius: 6px;
    background: var(--surface-2);
    font-family: var(--font-mono);
    font-size: var(--text-sm);
  }
  .faded .chip {
    background: none;
    outline: 1px dashed var(--border-strong);
    outline-offset: -1px;
    color: var(--text-2);
  }
  .x {
    display: grid;
    place-items: center;
    width: 24px;
    height: 26px;
    color: var(--text-3);
  }
  .x :global(svg) {
    width: 12px;
    height: 12px;
  }
  .x:hover {
    color: var(--danger);
  }
  .add {
    flex: 1;
    min-width: 150px;
    height: 26px;
    padding: 0 9px;
    border-radius: 6px;
    background: none;
    outline: 1px dashed var(--border-strong);
    outline-offset: -1px;
    font-family: var(--font-mono);
    font-size: var(--text-sm);
  }
  .add:focus {
    outline: 1.5px solid var(--accent);
  }
  .none {
    color: var(--text-3);
    font-size: var(--text-sm);
  }
</style>
