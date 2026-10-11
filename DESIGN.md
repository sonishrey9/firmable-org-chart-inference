# DESIGN

World: a **survey map**. Warm paper background, ink text, and one deep teal accent. Confidence is the only thing that gets colour: a sequential ramp from amber (unsure) to teal (sure). Wrong edges, which only show in answer-key mode, are crimson.

- Type: Instrument Sans (UI and headings) and IBM Plex Mono (numbers, ids, data cells, always tabular).
- Tokens: `--paper #f6f4ee`, `--ink #15191f`, `--muted #5b6270`, `--line #dcd8cc`, `--accent #0f6b63`; dark: `--paper #101317`, `--ink #e9e6dd`, `--muted #9aa1ad`, `--line #262b33`, `--accent #4fb3a6`.
- Confidence ramp: `<0.6 #c2410c`, `0.6-0.8 #b7791f`, `0.8-0.9 #5f8f3e`, `>=0.9 #0f6b63`.
- Edges: solid means a direct manager, with width growing with confidence. Dashed means "rolls up to" (a skip-level link). Nodes with no confident manager get a dashed outline.
- Motion: one moment. The chart eases in when a company loads. Everything else is instant.
- Layout: sidebar company picker, a canvas, and a details panel. Below 900px the sidebar becomes a sheet and the details become a bottom sheet.
