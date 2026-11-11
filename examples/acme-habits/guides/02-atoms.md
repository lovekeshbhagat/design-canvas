<!--
title: Atoms
group: Components
parts: true
-->
# Atoms

The smallest parts. Each one is drawn with the app's tokens on the app's own background.

### Button [atom]

::: specimen
<div class="stage row">
  <button class="p-btn">Add habit</button>
  <button class="p-btn secondary">Skip today</button>
  <button class="p-btn ghost">Edit</button>
  <button class="p-btn sm">{{icon:plus:16}} New</button>
  <button class="p-btn" disabled>Saving…</button>
</div>
:::

`app/src/components/Button.tsx`. Height 48, pill radius, `label` type at weight 600.

| Variant | Use |
| --- | --- |
| `primary` | The one main action on a screen |
| `secondary` | A second, quieter action |
| `ghost` | Inline actions inside cards and headers |

::: lineage Button

### Chip [atom]

::: specimen
<div class="stage row">
  <span class="p-chip on">{{icon:check}} Daily</span>
  <span class="p-chip">Weekdays</span>
  <span class="p-chip">3× a week</span>
</div>
:::

Picks how often a habit repeats. One chip in a group is on at a time.

::: lineage Chip

### Check circle [atom]

::: specimen
<div class="stage row">
  <span class="p-check"></span>
  <span class="p-check on">{{icon:check}}</span>
</div>
:::

28 pt circle. Turns `success` green with a check when the habit is done for the day.
