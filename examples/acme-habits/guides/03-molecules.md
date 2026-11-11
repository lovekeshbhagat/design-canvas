<!--
title: Molecules
group: Components
parts: true
-->
# Molecules

### Habit row [molecule]

::: specimen
<div class="stage">
  <div class="p-habit done"><span class="p-check on">{{icon:check}}</span><div class="meta"><span class="name">Drink water</span><span class="sub">{{icon:flame}} 12 day streak</span></div></div>
  <div class="p-habit"><span class="p-check"></span><div class="meta"><span class="name">Read 10 pages</span><span class="sub">{{icon:flame}} 4 day streak</span></div>{{icon:chevronRight}}</div>
</div>
:::

A check circle, the habit name and its streak. The whole row is the tap target; tapping the circle marks it done.

::: lineage HabitRow

### Progress card [molecule]

::: specimen
<div class="stage">
  <div class="p-card"><b style="font:var(--t-heading)">3 of 5 done</b><div class="p-progress"><i style="width:60%"></i></div><span style="font:var(--t-caption);color:var(--c-text-muted)">Two left for today</span></div>
</div>
:::

Sits at the top of Today and Stats. `shadow.card`, `radius.card`.

::: lineage ProgressCard
