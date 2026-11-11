<!--
title: Start here
group: Guide
-->
# Start here

Acme Habits is a made-up habit tracker. It exists so design-canvas has something small to build: its "code" is the `app/` folder next to `design.json`.

Everything on these pages is read from that code: the colours, type, spacing, corner radii, shadows, motion and icons. The component sections show each part drawn with the app's own tokens. Switch between **Light** and **Dark** at the top of the sidebar to see both themes.

> **Rule:** change a value in the code first, then update `design.json` and rebuild. `python3 engine/build.py examples/acme-habits --check` fails when the two disagree.

The [canvas](canvas.html) puts every screen of the app on one board.
