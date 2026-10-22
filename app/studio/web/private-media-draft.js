// Private image/video editor drafts are intentionally tab-memory-only.
// Never persist prompts to localStorage, IndexedDB, URLs, or job-list markup.
export function bindVolatileEditorDraft(root, draft, fieldIds) {
  for (const [key, id] of Object.entries(fieldIds)) {
    const input = root?.querySelector?.(`#${id}`);
    if (!input) continue;
    if (Object.prototype.hasOwnProperty.call(draft, key)) {
      // Assign as a DOM property, not HTML: prompts may contain arbitrary text.
      input.value = draft[key];
    }
    const remember = () => { draft[key] = input.value; };
    input.addEventListener('input', remember);
    input.addEventListener('change', remember);
  }
}
