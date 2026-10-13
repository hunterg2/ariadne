<script lang="ts">
  import Modal from "../ui/Modal.svelte";
  import Button from "../ui/Button.svelte";
  import Chip from "../ui/Chip.svelte";
  import { library } from "../stores/library.svelte";
  import { count } from "../format";

  interface Props { open: boolean; paths: string[]; onclose: () => void }
  let { open, paths, onclose }: Props = $props();

  let text = $state("");
  let input: HTMLInputElement | undefined = $state();

  /* tags on every selected image vs on some of them */
  const rows = $derived(paths.map((p) => library.rows.find((r) => r?.path === p)).filter(Boolean) as NonNullable<typeof library.rows[number]>[]);
  const onAll = $derived(rows.length ? rows[0].user_tags.filter((t) => rows.every((r) => r.user_tags.includes(t))) : []);
  const onSome = $derived(Array.from(new Set(rows.flatMap((r) => r.user_tags))).filter((t) => !onAll.includes(t)));
  const suggestions = $derived(
    library.tags.filter((t) => !onAll.includes(t.tag) && (!text || t.tag.toLowerCase().includes(text.toLowerCase()))).slice(0, 24));

  $effect(() => { if (open) { text = ""; setTimeout(() => input?.focus(), 30); } });

  function add(tag: string) {
    const clean = tag.trim().replace(/^#/, "");
    if (!clean) return;
    library.addTags(paths, [clean]);
    text = "";
  }
  function submit(e: Event) {
    e.preventDefault();
    for (const part of text.split(",")) add(part);
  }
</script>

<Modal {open} {onclose} title={`Tags for ${count(paths.length)} image${paths.length === 1 ? "" : "s"}`} width={480}>
  <div class="stack">
    <form class="row" onsubmit={submit}>
      <input bind:this={input} bind:value={text} placeholder="Type a tag, comma for several, Enter to add" />
      <Button type="submit" icon="plus">Add</Button>
    </form>
    <div>
      <h4>On {paths.length === 1 ? "this image" : "all of them"}</h4>
      <div class="chips">
        {#each onAll as t (t)}<Chip color={library.tags.find((x) => x.tag === t)?.color || undefined} onremove={() => library.removeTags(paths, [t])}>{t}</Chip>{:else}<span class="hint">None yet</span>{/each}
      </div>
    </div>
    {#if onSome.length}
      <div>
        <h4>On some of them</h4>
        <div class="chips">
          {#each onSome as t (t)}<Chip onclick={() => add(t)} onremove={() => library.removeTags(paths, [t])} title="Click to add to all">{t}</Chip>{/each}
        </div>
      </div>
    {/if}
    <div>
      <h4>Your tags</h4>
      <div class="chips">
        {#each suggestions as t (t.tag)}<Chip small color={t.color || undefined} onclick={() => add(t.tag)}>{t.tag} <span class="faint">{t.count}</span></Chip>{:else}<span class="hint">No matches</span>{/each}
      </div>
    </div>
  </div>
  {#snippet actions()}<Button variant="primary" onclick={onclose}>Done</Button>{/snippet}
</Modal>

<style>
  .row input { flex: 1; }
  .chips { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 6px; }
</style>
