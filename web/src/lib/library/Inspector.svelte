<script lang="ts">
  /* The kind-aware details panel. Follows the focused image; with several
     selected it shows the batch controls instead. */
  import type { ImageRow } from "../api";
  import * as api from "../api";
  import Button from "../ui/Button.svelte";
  import Chip from "../ui/Chip.svelte";
  import Icon from "../ui/Icon.svelte";
  import StarRating from "../ui/StarRating.svelte";
  import Thumb from "../ui/Thumb.svelte";
  import { library } from "../stores/library.svelte";
  import { toast } from "../stores/toasts.svelte";
  import { bytes, dateTime, exifDate, count } from "../format";

  interface Props {
    row: ImageRow | undefined;
    onopen?: (path: string) => void;
    ontag: (paths: string[]) => void;
    oncollect: (paths: string[]) => void;
    onedit?: (path: string) => void;
    compact?: boolean;       // inside the viewer: no thumbnail, no open button
  }
  let { row, onopen, ontag, oncollect, onedit, compact = false }: Props = $props();

  const LABELS = ["#f38ba8", "#fab387", "#f9e2af", "#a6e3a1", "#89b4fa", "#cba6f7"];
  const selectedCount = $derived(library.selected.size);
  const batch = $derived(selectedCount > 1);
  const paths = $derived(batch ? Array.from(library.selected) : row ? [row.path] : []);

  let promptOpen = $state(true);
  let newTag = $state("");

  function copy(text: string, what = "Copied") {
    navigator.clipboard.writeText(text).then(() => toast(what + "."), () => toast("Could not copy.", { error: true }));
  }

  function filterBy(field: string, value: string) {
    if (!value) return;
    library.setFilters({ q: `${field}: "${value}"` });
  }

  function addTag() {
    const t = newTag.trim().replace(/^#/, "");
    if (!t) return;
    library.addTags(paths, [t]);
    newTag = "";
  }

  const collectionsOf = $derived(row ? library.collections.filter((c) => row.collections.includes(c.id)) : []);

  const mapUrl = $derived(row?.camera.lat != null && row?.camera.lon != null
    ? `https://www.openstreetmap.org/?mlat=${row.camera.lat}&mlon=${row.camera.lon}#map=15/${row.camera.lat}/${row.camera.lon}` : "");
</script>

<aside class="inspector" class:compact>
  {#if batch}
    <div class="section">
      <h3>{count(selectedCount)} selected</h3>
      <p class="hint">Ratings and tags here apply to all of them.</p>
    </div>
    <div class="section">
      <h4>Rating</h4>
      <div class="row">
        <StarRating value={0} size={20} onchange={(n) => library.rate(paths, { stars: n })} onreject={() => library.rate(paths, { rejected: true })} />
        <Button size="sm" variant="subtle" onclick={() => library.rate(paths, { rejected: false })}>Un-reject</Button>
      </div>
      <div class="labels">
        {#each LABELS as c}<button class="swatch" style={`background:${c}`} title="Colour label" onclick={() => library.rate(paths, { label: c })}></button>{/each}
        <button class="swatch none" title="No label" onclick={() => library.rate(paths, { label: null })}><Icon name="x" size={10} /></button>
      </div>
    </div>
    <div class="section">
      <h4>Tags</h4>
      <form class="row" onsubmit={(e) => { e.preventDefault(); addTag(); }}>
        <input bind:value={newTag} placeholder="Add a tag to all" list="tag-suggestions" />
        <Button size="sm" type="submit" icon="plus" square title="Add" />
      </form>
      <Button size="sm" variant="ghost" icon="tag" onclick={() => ontag(paths)}>Edit tags…</Button>
    </div>
    <div class="section"><Button size="sm" variant="ghost" icon="layers" onclick={() => oncollect(paths)}>Add to collection…</Button></div>
  {:else if !row}
    <div class="section empty">
      <Icon name="info" size={22} />
      <p class="hint">Click an image to see its details here. Press Space to hide this panel.</p>
    </div>
  {:else}
    {#if !compact}
      <div class="preview"><Thumb path={row.path} fit="contain" /></div>
    {/if}
    <div class="section head">
      <div class="name" title={row.path}>{row.name}</div>
      <div class="facts">
        {#if row.kind === "generated"}<span class="badge accent"><Icon name="sparkles" size={11} />Generated</span>
        {:else if row.kind === "photo"}<span class="badge info"><Icon name="camera" size={11} />Photo</span>
        {:else}<span class="badge"><Icon name="image" size={11} />Image</span>{/if}
        <span>{row.width}×{row.height}</span>
        <span>{bytes(row.bytes)}</span>
        <span>{row.ext.replace(".", "").toUpperCase()}</span>
      </div>
      <div class="facts faint">{dateTime(row.time)}</div>
      {#if !row.indexed}<div class="hint"><Icon name="loader" size={12} class="spin" /> Reading the file…</div>{/if}
    </div>

    <div class="section">
      <div class="row">
        <StarRating value={row.stars} rejected={!!row.rejected} size={20}
          onchange={(n) => library.rate([row.path], { stars: n })}
          onreject={() => library.rate([row.path], { rejected: !row.rejected })} />
        <span class="spacer"></span>
        <div class="labels">
          {#each LABELS as c}<button class="swatch" class:on={row.label === c} style={`background:${c}`} title="Colour label" onclick={() => library.rate([row.path], { label: row.label === c ? null : c })}></button>{/each}
        </div>
      </div>
    </div>

    <div class="section">
      <h4>Tags</h4>
      <div class="chips">
        {#each row.user_tags as t (t)}
          <Chip small color={library.tags.find((x) => x.tag === t)?.color || undefined} onclick={() => library.setFilters({ tag: t })} onremove={() => library.removeTags([row.path], [t])}>{t}</Chip>
        {:else}
          <span class="hint">No tags</span>
        {/each}
      </div>
      <form class="row" onsubmit={(e) => { e.preventDefault(); addTag(); }}>
        <input bind:value={newTag} placeholder="Add a tag (T)" list="tag-suggestions" />
        <Button size="sm" type="submit" icon="plus" square title="Add" />
      </form>
    </div>

    {#if row.kind === "generated"}
      <div class="section">
        <div class="row">
          <h4>Prompt</h4><span class="spacer"></span>
          <Button size="sm" variant="subtle" icon="copy" title="Copy prompt" square onclick={() => copy(row.prompt, "Prompt copied")} />
          <Button size="sm" variant="subtle" icon={promptOpen ? "chevronUp" : "chevronDown"} square onclick={() => (promptOpen = !promptOpen)} />
        </div>
        {#if promptOpen}
          <p class="prompt">{row.prompt || "No prompt found."}</p>
          {#if row.prompt_lines > 1}<p class="hint">Line {row.prompt_line} of a {row.prompt_lines} line prompt list.</p>{/if}
          {#if row.negative}<h4 class="sub">Negative</h4><p class="prompt neg">{row.negative}</p>{/if}
        {/if}
      </div>
      <div class="section">
        <h4>Generation</h4>
        <div class="kv">
          {#if row.model}<button class="k" onclick={() => filterBy("model", row.model)}>Model</button><span class="v" title={row.model}>{row.model}</span>{/if}
          {#if row.loras.length}<span class="k">LoRAs</span><span class="v">{row.loras.join(", ")}</span>{/if}
          {#if row.steps}<button class="k" onclick={() => filterBy("steps", row.steps)}>Steps</button><span class="v">{row.steps}</span>{/if}
          {#if row.cfg}<button class="k" onclick={() => filterBy("cfg", row.cfg)}>CFG</button><span class="v">{row.cfg}</span>{/if}
          {#if row.sampler}<button class="k" onclick={() => filterBy("sampler", row.sampler)}>Sampler</button><span class="v">{row.sampler}</span>{/if}
          {#if row.scheduler}<button class="k" onclick={() => filterBy("scheduler", row.scheduler)}>Scheduler</button><span class="v">{row.scheduler}</span>{/if}
          {#if row.seed}<button class="k" onclick={() => filterBy("seed", row.seed)}>Seed</button><span class="v mono">{row.seed}</span>{/if}
          {#if row.denoise}<span class="k">Denoise</span><span class="v">{row.denoise}</span>{/if}
          <span class="k">Read from</span><span class="v faint">{row.source || "nothing found"}</span>
        </div>
        <div class="row wrap">
          <Button size="sm" variant="ghost" icon="copy" onclick={async () => { const r = await api.getPrompt(row.path); copy(r.raw_workflow, "Workflow copied"); }}>Copy workflow</Button>
        </div>
      </div>
    {:else if row.kind === "photo"}
      <div class="section">
        <h4>Camera</h4>
        <div class="kv">
          {#if row.camera.make || row.camera.model}<span class="k">Camera</span><span class="v">{[row.camera.make, row.camera.model].filter(Boolean).join(" ")}</span>{/if}
          {#if row.camera.lens}<span class="k">Lens</span><span class="v">{row.camera.lens}</span>{/if}
          {#if row.camera.exposure || row.camera.aperture || row.camera.iso}
            <span class="k">Exposure</span>
            <span class="v">{[row.camera.exposure && row.camera.exposure + " s", row.camera.aperture && "f/" + row.camera.aperture, row.camera.iso && "ISO " + row.camera.iso].filter(Boolean).join("  ·  ")}</span>
          {/if}
          {#if row.camera.focal}<span class="k">Focal</span><span class="v">{row.camera.focal} mm</span>{/if}
          {#if row.camera.taken_at}<span class="k">Taken</span><span class="v">{exifDate(row.camera.taken_at)}</span>{/if}
          {#if row.camera.software}<span class="k">Software</span><span class="v">{row.camera.software}</span>{/if}
          {#if mapUrl}<span class="k">Location</span><span class="v"><a href={mapUrl} target="_blank" rel="noopener">{row.camera.lat?.toFixed(5)}, {row.camera.lon?.toFixed(5)} <Icon name="external" size={11} /></a></span>{/if}
        </div>
      </div>
    {:else}
      <div class="section">
        <h4>File</h4>
        <div class="kv">
          <span class="k">Format</span><span class="v">{row.ext.replace(".", "").toUpperCase()}</span>
          <span class="k">Size</span><span class="v">{row.width}×{row.height}, {bytes(row.bytes)}</span>
          <span class="k">Created</span><span class="v">{dateTime(row.time)}</span>
          <span class="k">Modified</span><span class="v">{dateTime(row.mtime)}</span>
          {#if row.camera.software}<span class="k">Software</span><span class="v">{row.camera.software}</span>{/if}
        </div>
        <p class="hint">No generation data or camera tags were found in this file.</p>
      </div>
    {/if}

    <div class="section">
      <h4>Collections</h4>
      <div class="chips">
        {#each collectionsOf as c (c.id)}
          <Chip small icon="layers" color={c.color || undefined} onclick={() => library.open({ type: "collection", id: c.id })}>{c.name}</Chip>
        {/each}
        <Chip small icon="plus" onclick={() => oncollect([row.path])}>Add</Chip>
      </div>
    </div>

    <div class="section actions">
      {#if !compact && onopen}<Button size="sm" icon="maximize" onclick={() => onopen(row.path)}>Open</Button>{/if}
      {#if onedit}<Button size="sm" variant="ghost" icon="edit" onclick={() => onedit(row.path)}>Edit</Button>{/if}
      <Button size="sm" variant="ghost" icon="folder" title="Reveal in file manager (R)" onclick={() => api.reveal(row.path)}>Reveal</Button>
      <Button size="sm" variant="danger" icon="trash" onclick={() => library.trash([row.path])}>Trash</Button>
    </div>
    <div class="section path"><span class="mono faint" title={row.path}>{row.folder}</span></div>
  {/if}
</aside>

<datalist id="tag-suggestions">
  {#each library.tags.slice(0, 200) as t (t.tag)}<option value={t.tag}></option>{/each}
</datalist>

<style>
  .inspector { width: 300px; flex: none; height: 100%; overflow-y: auto; background: var(--surface); border-left: 1px solid var(--border); display: flex; flex-direction: column; }
  .inspector.compact { width: 320px; background: transparent; border: 0; }
  .preview { aspect-ratio: 4 / 3; background: var(--bg); flex: none; }
  .section { padding: var(--sp3) var(--sp4); border-bottom: 1px solid var(--border); display: flex; flex-direction: column; gap: var(--sp2); }
  .section:last-child { border-bottom: 0; }
  .section.empty { align-items: center; text-align: center; padding-top: var(--sp8); color: var(--muted); }
  .section.actions { flex-direction: row; flex-wrap: wrap; }
  .section.path { padding-top: var(--sp2); }
  .section.path span { font-size: 11px; word-break: break-all; }
  .head .name { font-weight: 600; font-size: 14px; word-break: break-all; }
  .facts { display: flex; flex-wrap: wrap; gap: var(--sp2); align-items: center; font-size: 12px; color: var(--muted); }
  .facts.faint { color: var(--faint); }
  .labels { display: flex; gap: 4px; align-items: center; }
  .swatch { width: 14px; height: 14px; border-radius: 50%; border: 2px solid transparent; cursor: pointer; padding: 0; opacity: .6; }
  .swatch:hover, .swatch.on { opacity: 1; border-color: var(--text); }
  .swatch.none { background: var(--surface-2); display: grid; place-items: center; color: var(--muted); }
  .chips { display: flex; flex-wrap: wrap; gap: 4px; }
  .row input { flex: 1; min-width: 0; }
  .row.wrap { flex-wrap: wrap; }
  .prompt { font-size: 12.5px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; max-height: 220px; overflow: auto; background: var(--surface-2); border-radius: var(--r-sm); padding: var(--sp2) var(--sp3); }
  .prompt.neg { color: var(--muted); max-height: 110px; }
  h4.sub { margin-top: var(--sp1); }
  .kv { display: grid; grid-template-columns: max-content 1fr; gap: 4px 10px; font-size: 12.5px; align-items: baseline; }
  .k { color: var(--muted); text-align: left; border: 0; background: transparent; padding: 0; font: inherit; font-size: 12px; cursor: default; }
  button.k { cursor: pointer; text-decoration: underline dotted; text-underline-offset: 3px; }
  button.k:hover { color: var(--accent); }
  .v { word-break: break-word; }
  .v.mono { font-family: var(--mono); font-size: 12px; }
  .v a { display: inline-flex; align-items: center; gap: 3px; }
</style>
