# Body prompt editing

The Body tab accepts short, local edit prompts for the supported adult character
base. Examples include `increase breast size by 40% and glute size by 30%`,
`reduce breast width by 15%`, and `increase glute projection by 20%`. The prompt
updates the same authored controls shown below it, so slider values, undo, and
export stay in sync. The prompt is interpreted in the browser; it does not call
an AI service.

Imported GLB files expose their authored shape targets and include a direct
surface-sculpt path for meshes without shape keys: pick a visible point, set a
brush radius, then prompt for fuller or smaller. Each localized edit is stored
as a shape key, included in GLB exports, and saved with the source-linked model
project. Sculpt clothing meshes separately when they are separate objects.
Rigging and animation correctives are not generated automatically.

## Precision limitation and required behavior

The current parser is not safe for constrained natural-language edits. It splits
on `and` before resolving negation, has no protected-region model, and uses a
default 40% adjustment when no amount is specified. For example,
`slim her waist without reducing glute and hip size` can miss the waist, reduce
glute volume, and increase hip width. Do not treat this parser as production
semantic editing. The target behavior and acceptance tests are recorded in
[`BEYOND_TRIPO_SPEC.md`](BEYOND_TRIPO_SPEC.md).

Source files are not interchangeable in capability: the imported Street Fighter
GLBs are high-density static meshes with no body morph targets, while some
Dropbox `.blend` sources contain authored body morphs, vertex groups, and rigs.
Use a per-model capability report. Preserve source files and block a requested
edit when its target/protected regions cannot be mapped and verified.
