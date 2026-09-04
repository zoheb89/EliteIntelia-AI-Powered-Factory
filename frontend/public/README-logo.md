# Brand assets

`logo.svg` and `icon.svg` ship with the app as a vector rendering of the
EliteInteliA Technologies mark, so the shell is branded out of the box.

**To use the official artwork**, replace those two files with the real ones
(same names), or add the PNGs below — no code change either way.

| File | Used for | Spec |
|---|---|---|
| `logo.png` | Sidebar and sign-in screen | Transparent PNG or SVG, ~3:1 landscape, ≥600px wide |
| `icon.png` | Browser tab (favicon) | Square PNG, 512×512, transparent |
| `favicon.ico` | Legacy tab icon | 32×32 ICO (optional if `icon.png` is present) |
| `apple-touch-icon.png` | iOS home screen | Square PNG, 180×180, opaque background |

The square glyph from the EliteInteliA Technologies mark works well for
`icon.png`; the full wordmark belongs in `logo.png`.

Every one of these degrades quietly when absent: the sidebar falls back to the
typeset wordmark and the browser shows its default tab icon, so a missing file
never leaves a broken image in the shell.
