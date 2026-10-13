<script lang="ts">
  import * as api from "../lib/api";
  import Button from "../lib/ui/Button.svelte";
  import Icon from "../lib/ui/Icon.svelte";
  import TrashDialog from "../lib/library/TrashDialog.svelte";
  import { library } from "../lib/stores/library.svelte";
  import { toast, reportError } from "../lib/stores/toasts.svelte";
  import { settings } from "../lib/stores/settings.svelte";
  import { go } from "../lib/router.svelte";

  let trashOpen = $state(false);
  let fileInput: HTMLInputElement | undefined = $state();
  const folder = $derived(library.folder || settings.data.last_folder || "");
  const selection = $derived(Array.from(library.selected));
  const one = $derived(selection.length === 1 ? selection[0] : selection.length === 0 ? library.focused?.path ?? null : null);

  async function importFile(input: HTMLInputElement) {
    const file = input.files?.[0];
    if (!file) return;
    try {
      const data = JSON.parse(await file.text());
      const res = await api.importLibrary(data, "merge");
      toast(`Imported ${res.ratings} ratings and ${res.tag_links} tag links.`);
      library.reload();
    } catch (e) { reportError(e, "That file could not be imported."); }
    input.value = "";
  }

  const needOne = (tool: string) => () => one ? go("/library", { tool }) : toast(selection.length ? "Pick one image for this." : "Pick an image in the Library first.");

  const tools = [
    { icon: "edit", title: "Image editor", text: "Annotate, blur or pixelate, stamp a watermark, crop, rotate and flip. Saves a copy with the metadata you choose; the original is never touched.", action: needOne("edit"), need: "one image" },
    { icon: "dupes", title: "Find duplicates", text: "Perceptual-hash scan of a folder or the whole library with a review screen that suggests which copy to keep.", action: () => go("/library", { folder: folder || undefined, tool: "dupes" }) },
    { icon: "hash", title: "Unique prompts", text: "Every distinct prompt in the open folder with counts; pin the grid to one of them.", action: () => folder ? go("/library", { folder, tool: "prompts" }) : go("/library"), need: "a folder" },
    { icon: "compare", title: "Compare", text: "Side by side, wipe or difference view of two to six selected images, with a table of what differs.", action: () => selection.length >= 2 ? go("/library", { tool: "compare" }) : toast("Select at least two images in the Library first."), need: "a selection" },
    { icon: "sparkles", title: "Suggest tags", text: "Tag proposals from the prompt, or from a vision model through Ollama, OpenAI or Anthropic. Reviewed before anything is written.", action: () => selection.length ? go("/library", { tool: "autotag" }) : toast("Select some images in the Library first."), need: "a selection" },
    { icon: "trash", title: "Trash", text: "Restore or purge soft-deleted images.", action: () => (trashOpen = true) },
  ];
</script>

<div class="tools">
  <h2>Tools</h2>
  <div class="grid">
    {#each tools as t}
      <button class="tool" type="button" onclick={t.action}>
        <span class="ic"><Icon name={t.icon} size={20} /></span>
        <span class="t">{t.title}</span>
        <span class="d">{t.text}</span>
        {#if t.need}<span class="need">Needs {t.need}</span>{/if}
      </button>
    {/each}
  </div>

  <h3>Library data</h3>
  <div class="row wrap">
    <Button icon="download" onclick={() => (location.href = "/api/library/export")}>Export ratings and tags</Button>
    <Button icon="upload" onclick={() => fileInput?.click()}>Import…</Button>
    <input bind:this={fileInput} type="file" accept="application/json,.json" style="display:none" onchange={(e) => importFile(e.currentTarget)} />
  </div>
  <p class="hint">Ratings and tags live only in the database. A copy is taken every time the app starts; the export is the portable version. Exports from the previous build import too.</p>
</div>

<TrashDialog open={trashOpen} onclose={() => (trashOpen = false)} />

<style>
  .tools { padding: var(--sp5); overflow: auto; height: 100%; display: flex; flex-direction: column; gap: var(--sp3); }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: var(--sp3); margin: var(--sp2) 0 var(--sp4); }
  .tool { display: flex; flex-direction: column; align-items: flex-start; gap: 6px; padding: var(--sp4); background: var(--surface); border: 1px solid var(--border); border-radius: var(--r); color: var(--text); font: inherit; text-align: left; cursor: pointer; transition: border-color var(--dur) var(--ease), transform var(--dur) var(--ease); }
  .tool:hover { border-color: var(--accent); transform: translateY(-1px); }
  .ic { width: 36px; height: 36px; border-radius: var(--r-sm); background: var(--accent-soft); color: var(--accent); display: grid; place-items: center; }
  .t { font-weight: 600; font-size: 14px; }
  .d { color: var(--muted); font-size: 12.5px; }
  .need { font-size: 11px; color: var(--faint); margin-top: auto; }
  .wrap { flex-wrap: wrap; }
</style>
