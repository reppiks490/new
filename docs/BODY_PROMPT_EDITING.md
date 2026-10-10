# Body prompt editing

The Body tab accepts short, local edit prompts for the supported adult character
base. Examples include `increase breast size by 40% and glute size by 30%`,
`reduce breast width by 15%`, and `increase glute projection by 20%`. The prompt
updates the same authored controls shown below it, so slider values, undo, and
export stay in sync. The prompt is interpreted in the browser; it does not call
an AI service.

Imported GLB files expose only shape targets authored in their source. Prompt
edits and sliders can change those targets, but they cannot create anatomical
targets for a file that has none. When a file has no shape targets, the Body
panel explains that limit and offers the editable adult base. Clothing fit,
rigging, and animation are not automatically corrected after source morphs.
