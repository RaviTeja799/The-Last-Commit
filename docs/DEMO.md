# Demo run-of-show

A three-minute script for a live demo or a screen recording. Everything below is
local; do the pre-flight once, then unplug the network if you want to prove it.

## Pre-flight (once)

```bash
ollama pull gemma3:4b
ollama serve &
cd /path/to/the-last-commit
./run.sh
```

Open <http://127.0.0.1:8000>. The header should show a green dot, `gemma3:4b`,
and `ONLINE`. If it shows `no model server detected`, the archive still works,
but the answers will be evidence quotes rather than prose — fix this before
recording.

For a clean slate:

```bash
rm -f data/ghosts.db data/ghosts.db-shm data/ghosts.db-wal
# restart the server, then click SUMMON THE SPECIMEN
```

## The script

| Time | Do | Say |
| --- | --- | --- |
| 0:00 | Landing page | "Every abandoned repository ends with a boring commit. This one ends with a typo fix, then 3,184 days of silence." |
| 0:20 | **SUMMON THE SPECIMEN** | "The history is read on this machine. Commits, TODOs, the skipped test, the unmerged branch — 76 memories, no embeddings, no cloud." |
| 0:40 | Point at the timeline and the signals panel | "The silence is drawn to scale. The last commit is red. Four TODOs are still in the tree." |
| 0:55 | Ask **Why were you abandoned?** | "The interesting part is what it refuses to do." |
| 1:10 | Read the answer aloud, especially the first sentence | "The record does not contain a stated reason. Then it gives the shape of the stop, and marks the guess as a guess." |
| 1:30 | Click a `[C3]` citation | "Every claim is a door. This is the branch that was three commits from done." |
| 1:45 | Point at the grounding meter | "Two of three claims cited. It says PARTIAL, not 'verified'." |
| 1:55 | **RESURRECTION → BEGIN THE EXCAVATION** | "Same evidence, a different question: what would it take to come back?" |
| 2:15 | Read one step and its first action | "Ordered by what unblocks the most. The first action is an edit, not a vibe." |
| 2:30 | **PROPOSE** on the `config.py` TODO | "The model quotes lines it wants to change; the app builds the diff; git decides if it applies." |
| 2:45 | Point at the verdict and the fineprint | "Accepted by `git apply --check` — and still not applied. A patch that applies is not a patch that is correct." |
| 2:55 | Close on the archive view | "No API keys. No cloud. The Wi-Fi can stay off." |

## If something goes wrong

- **The first answer takes longer than expected.** It is a 4B model on a laptop;
  20–40 seconds is normal. The token stream starts immediately, so do not wait in
  silence — narrate the evidence panel while it writes.
- **Ollama is down.** The chat returns an evidence-only answer with a notice.
  Show it; it is part of the honesty story. Then restart Ollama and retry.
- **The patch is rejected.** That is a feature. Read the reason aloud: git
  refused a diff that does not apply, and nothing was written. Then try the next
  TODO.
- **The model bunches citations.** The grounding meter will show `PARTIAL`. Say
  so. Do not switch models mid-demo unless you have rehearsed the other one.

## Screens to capture

1. Landing (wordmark, specimen button)
2. Séance with a cited answer + evidence ledger (`docs/screens/seance.png`)
3. Resurrection plan (`docs/screens/plan.png`)
4. Patch review with the `git apply --check` verdict (`docs/screens/patch.png`)

## Before publishing

- Remove `data/ghosts.db` from the recording machine or keep it; the app rebuilds
  it on import.
- Confirm the specimen imports from a fresh clone with no `data/` directory.
- Check the README screenshots still match the build.
