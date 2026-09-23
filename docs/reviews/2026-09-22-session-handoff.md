# Session hand-off protocol — 2026-09-22 remediation

Every remediation session reads this file together with the
[remediation checklist](./2026-09-22-remediation-checklist.md). The checklist says
*what* to do; this file says how a session starts, how it is configured, and how it
ends by producing the prompt for the next session, so the chain runs to the end of
the checklist without re-planning.

## 1. One-time setup (owner)

1. Get both plan files onto `main` (merge PR #22). Until then, sessions read them
   from the owner's checkout at `/home/fortune/CodeProjects/First-Helios/docs/reviews/`.
2. Optional but recommended: hard-block the dangerous commands for every session by
   adding this to `.claude/settings.local.json` (local only, not committed):

   ```json
   {
     "permissions": {
       "deny": [
         "Read(./.env)",
         "Read(./.env.local)",
         "Bash(cat .env)",
         "Bash(gh pr merge:*)",
         "Bash(git push --force:*)",
         "Bash(git push -f:*)"
       ]
     }
   }
   ```

   With those in place, auto mode is safe for implementation sessions: the stop
   points are draft PRs, and merging stays yours.

## 2. Session configuration

Start every session as a **fresh `claude` process in the repo root** (not `/clear`
inside a long one), launched with the model below; set effort in the `/model`
picker. Mode: auto (or accept-edits) for all sessions.

| Session | Model | Effort | Why this setting |
|---|---|---|---|
| S1 Guardrails | Opus 5.5 | high | CI + config + CLAUDE.md; moderate reasoning, stop-and-ask review |
| S2 Crawler etiquette | Opus 5.5 | high | Security-relevant parsing (RFC 9309, redirects, private IPs) |
| S3 URL pipeline logic | Opus 5.5 | high | Identity-state transitions and batching |
| S4 Menu-URL quality | Sonnet 5 | high | Heuristics in two files; well specified |
| S5 Evidence ADR | Opus 5.5 | xhigh | Design decision on the provenance contract |
| S6 Evidence implementation | Opus 5.5 | high | Contract change, possible migration |
| S7 Gold refresh fix | Opus 5.5 | xhigh | Subtle transaction and selection semantics |
| S8 Identity lock order | Opus 5.5 | xhigh | Concurrency and deadlock ordering |
| S9 API polish | Sonnet 5 | high | Many small, well-specified fixes |
| S10 Test hardening | Sonnet 5 | medium | Mechanical test tightening |
| S11 Menu selector | Opus 5.5 | xhigh | ADR-0005 correspondence rules |
| S12 Fingerprint + lifecycle ADR | Opus 5.5 | high | Matching policy plus an ADR draft |
| S13 Venue lifecycle | Opus 5.5 | high | Implements an accepted ADR |
| S14 Schema tightening | Opus 5.5 | high | Migration with hand-reviewed SQL |
| S15 Infra and tooling | Sonnet 5 | medium | Config cleanup |
| S16 Docs drift | Sonnet 5 | medium | Documentation sweep |
| S17 Close-out | Sonnet 5 | medium | Bookkeeping and a final CI run |

Model IDs for `claude --model …`: Opus 5.5 = `claude-opus-5-5`, Sonnet 5 =
`claude-sonnet-5`. If a session hits the 5-hour budget, the next session uses the
same setting and resumes from the log.

## 3. Start of session (agent)

1. Read `CLAUDE.md`, this file, the checklist's **Session rules**, your session's
   block, and the rows for your R-IDs in the
   [review](./2026-09-22-full-codebase-review.md).
2. **Work in a git worktree** (the `EnterWorktree` tool, or
   `git worktree add ../First-Helios-<slug> -b <branch> origin/main`). The owner may
   be editing the checklist in the main checkout at the same time; never edit or
   switch branches there.
3. **Decisions.** Read your session's decision group from `main`, then from the
   owner's live copy at
   `/home/fortune/CodeProjects/First-Helios/docs/reviews/2026-09-22-remediation-checklist.md`
   (read-only; it may have newer ticks). For every question still unanswered, ask the
   owner with `AskUserQuestion`: one question per item, the ⭐ option first labelled
   "(Recommended)", the *Why* line as its description. Write the final answers into
   your branch's copy of the checklist.
4. Don't spawn subagents; the 5-hour budget is better spent in one context.

Then do the work exactly as the checklist's Session rules and your session's
*Recommended approach* describe.

## 4. End of session (agent) — always the last thing you do

1. Tick your boxes in the checklist, add a session-log row, push the branch, and open
   the PR (draft for ⚠ sessions). Never merge.
2. **Choose the next step:**
   - Walk the checklist's "Progress at a glance" table in order and take the first
     session that is not done and whose *Needs* are satisfied. Satisfied means: its
     decision group is answered (on `main`, in the owner's live copy, or answerable
     at the start of the next session), and every prerequisite PR is merged
     (`gh pr list --state all`, plus the session log).
   - If the next in-order session waits on the owner's review of a ⚠ PR, pick the
     next independent session instead (S10, S15 and S16 never depend on others) and
     say why.
   - Never skip past a 🚦 gate for work the gate protects.
3. **Output this block as the final message, in a fenced code block**, filled in:

   ```text
   NEXT SESSION: S<n> — <title>        decision group: D<k> | none
   Before you start: <PRs to merge / decisions to tick first, or "nothing">
   Launch: claude --model <model-id>    then /model → effort: <level>; mode: auto
   Prompt:
   Work the remediation plan: docs/reviews/2026-09-22-session-handoff.md and
   docs/reviews/2026-09-22-remediation-checklist.md.
   This session: <"go over decision group D<k> with me, then do" | "do"> session S<n> (<title>).
   Context: <one or two lines of carry-over: open PRs, resume notes, anything the
   next session must not touch>.
   Follow the hand-off protocol: start-of-session steps, the checklist's Session
   rules and S<n>'s Recommended approach, and end with the next-session block.
   ```

4. If every box in the checklist is ticked or listed in D9, output
   `REMEDIATION COMPLETE` with the S17 summary instead.

## 5. Universal fallback prompt

If a hand-off block is ever lost, this prompt recovers the chain from the files
alone (use the S1 setting from §2 if unsure):

```text
Work the remediation plan: docs/reviews/2026-09-22-session-handoff.md and
docs/reviews/2026-09-22-remediation-checklist.md. Work out the next session from
the progress table, session log and open PRs, confirm it with me, then run it.
Follow the hand-off protocol and end with the next-session block.
```
