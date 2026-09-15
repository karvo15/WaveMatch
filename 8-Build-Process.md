# WaveMatch - Build Process (the 5-Step Building Plan)

> This is the working method for every task/phase in this project. Apply the five
> steps in order, every time.

## The 5 steps

1. **Explain the task and establish a plan to do it effectively.** State exactly
   what "done" means (which checklist items, which spec sections), then lay out the
   concrete steps that will get there. Keep the work small, sequential, and
   individually testable.

2. **Evaluate the plan - will it finish the task without breaking what already
   works or creating new bugs?** Before writing code, check the plan against the
   real codebase and the source-of-truth docs. Identify blast radius (files and
   behavior that already work), schema/interaction-type constraints, and failure
   modes. If the plan cannot pass this evaluation, do not proceed.

3. **If the plan does not pass step 2, update the plan in step 1 until step 2 is
   passed.** Iterate on the plan until it is demonstrably safe and sufficient, then
   move on. Do not paper over gaps.

4. **Perform the task following the established plan strictly**, unless an
   unforeseen challenge appears that genuinely requires working differently - in
   which case adapt deliberately (and record why) rather than drifting.

5. **After performing the task, verify it is successfully solved, did not break the
   initial codebase, and created no new bugs, and that it performs the required
   task.** Verify against real file content and real behavior, not self-reports. If
   verification fails, restart from step 1. If it passes, inform the user.

## Ground rules that reinforce the 5 steps

- Verify each phase actually works before starting the next (per `7-Build-Checklist.md`).
- Never trust a large chunk of fresh code as correct; isolate where something breaks.
- Consult `3-Full-Product-Logic.md` (esp. Section 0), `4-Message-Flow-Examples.md`,
  `5-Data-Schema.sql`, and `6-Platform-Constraints.md` before building, not after.
- New Meta-approvable message templates get drafted/submitted as early as possible, in
  parallel with other work, never at the end.
