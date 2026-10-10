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
