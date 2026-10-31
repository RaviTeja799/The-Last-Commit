# The Last Commit: building an offline AI that lets abandoned repositories speak

*Draft for the DEV submission. Adjust the challenge name, links and any personal
details before publishing.*

---

The last commit is almost never dramatic.

In the repository I built for this project, it is a typo fix. `fix typo in --help
output`, one file, two lines added, one removed. Before that: a branch called
`wip/crash-safe`, three commits ahead of `main`, never merged. Before that: a
test skipped with the comment "for now". Before that: a TODO that names the exact
thing that was too hard.

Then nothing. 3,184 days of nothing.

I have a folder of repositories like this. Some are mine. Some belong to people I
never met. The reasons are never in the git log. What is in the git log is the
*shape* of the stopping — and for years I have wanted a tool that could read that
shape without inventing a story around it.

So I built one. It runs entirely on my laptop, with the Wi-Fi off and a 4B model.

## What it is

**The Last Commit** is a local-first digital archaeologist. You point it at a git
repository that stopped. It reads the history, turns commits, TODOs, skipped
tests and unmerged branches into an evidence archive, and lets you ask the
project what happened.

The answers are not free text. Every factual sentence carries a citation like
`[C3]`, and every citation opens the exact commit, branch or TODO it came from.
The right-hand panel is the ledger of memories the model was allowed to use. If
the model cites something that was not in that ledger, the interface flags it.

The first question I asked it was: *why were you abandoned?*

It answered:

> The record does not contain a stated reason [C1]. The last commit is a typo fix
> in the --help output [C2]. When it stopped, the `wip/crash-safe` branch was
> three commits ahead and unmerged [C3], alongside four TODO markers still
> present [C6, C7]. *(inference)* It seems likely that the project stalled due to
> unresolved technical challenges.

That is the whole thesis in one answer. The record does not contain the reason.
The tool says so, then gives you the shape: the branch, the TODOs, the mundane
last commit. The guess is marked as a guess.

## Three decisions that shaped everything

### 1. No embeddings, no vector database

The obvious 2026 stack for "chat with a repository" is embeddings plus a vector
store. I did not want that here. An embedding model is another download, another
runtime, another thing that can fail on a machine where the demo is supposed to
just work.

Instead each memory is a row in SQLite, indexed with FTS5. Retrieval is BM25
plus intent anchors. A question about abandonment pulls the last commit, the
unmerged branch and the oldest TODO. A question about unfinished work pulls
TODOs, the skipped test and the branch ahead. A per-kind cap stops the prompt
from filling with ten near-identical commits.

This is unfashionable and it works. File names, identifiers and rare words are
exactly where lexical search is strongest, and repository questions are full of
both.

### 2. Grounding is measured in public, including its limits

After each answer the backend splits it into sentences, counts sentences of five
words or more that carry a citation tag, and reports coverage. It also reports
any citation id that was never in the evidence. The UI shows `2/3 claims cited ·
PARTIAL` — not a green checkmark.

I want to be precise about what this is: a heuristic, not a proof. It cannot tell
whether a cited sentence actually follows from the cited commit. It catches the
failure that matters most in practice — a confident paragraph that cites nothing
— and it refuses to hide the failure it cannot catch. The README says this. The
meter says `PARTIAL` instead of rounding up.

### 3. The patch is never applied

The resurrection tab generates a revival plan from the same evidence: what
blocks the most, the first concrete edit, what to keep, what could go wrong. Pick
any TODO and the model proposes a minimal change.

The model does not write a unified diff. Small models are bad at them — they
invent hunk headers, glue lines together, and rename identifiers nobody asked
them to touch. Instead it returns a small `find` / `replace` edit as arrays of
lines. The app locates those exact lines in the file at `HEAD`, re-indents the
replacement to the block it matched, and builds the diff with `difflib`.

Then `git apply --check` decides whether the diff is even applicable.

Nothing is ever written. There is no `git apply`, no commit, no checkout, no code
execution in the patch path. The diff is a proposal on a screen, and the screen
says so.

A patch that applies is still not a patch that is correct. In my demo run the
model "fixed" `coerce idle_minutes to int` by calling `int()` on every config
value, including the database path. Git accepts it. A human has to read it. That
distinction is the point, not a bug to hide.

## The demo repository is synthetic. The archaeology is not.

The bundled specimen, `sundial`, is a generated 2017 time-tracking CLI: 47
commits, two authors, a tag, four TODOs, one skipped test, one unmerged branch,
and a final typo fix. The generator is in the repo, so the demo has a known shape
and works on a fresh clone with no network.

I could have used a famous abandoned project. I chose not to, because the demo
needs to be reproducible and because the interesting claim is about the method,
not about borrowing someone else's history. Every citation points at a real
object in a real git repository that you can inspect with `git log` and `git
show`. The importer accepts any local path or cloneable URL.

## What I got wrong

**Citations bunch at the end.** My first model, `qwen2.5:3b`, produced good
summaries and then appended `[C1][C2][C3]` at the end like a bibliography. The
grounding meter punished it, correctly. `gemma3:4b` follows the per-sentence
instruction much better, at the cost of speed. This is now documented instead of
hidden.

**My sentence splitter lied.** The verifier split on every period, so a citation
after a sentence became its own one-word fragment and was not counted. The meter
said `0/3` for an answer that had citations. I fixed the splitter to keep
trailing citation tags with the sentence they close — and then the same answer
read `2/3`, which was the truth.

**The first patch prompt was too ambitious.** Asking a 4B model for a unified
diff produced plausible-looking patches that `git apply` rejected with cryptic
errors. The find/replace pipeline exists because the model is better at quoting
lines than at counting hunk offsets. The rejection path is still there for edits
that do not match the file — and it says so in plain language: *"A guess that
does not apply is not a patch."*

## Offline, on purpose

The app talks to a local Ollama server and nothing else. The interface has no
external fonts, no CDN, no analytics, no images fetched at runtime. The archive
is SQLite. The frontend is a static build served by FastAPI. Importing a URL is
the only network path, and it is explicit.

The reason is not purity. It is that the subjects of this project are abandoned
things. A tool for reading them should not depend on a service that might also be
abandoned. It should work when the network is off, on a laptop, years from now,
with the same repository.

## Try it

```bash
ollama pull gemma3:4b
ollama serve
git clone <this repo>
cd the-last-commit
./run.sh
# open http://127.0.0.1:8000 → SUMMON THE SPECIMEN
```

Ask it why it was abandoned. Open a citation. Generate the plan. Propose a patch
and watch git refuse or accept it. Then import one of your own dead repositories
and see what shape it left behind.

## What's next

- A proper semantic check of citations, not just coverage: does this commit
  actually support this sentence?
- Better handling of huge histories — the current reading window is 220 commits.
- A way to export the excavation as a static page, so an abandoned project can
  have a small memorial that does not need a server.
- Patch proposals for more than one file, still never applied.

The last commit is usually boring. That is what makes it worth reading.

---

*The Last Commit is MIT licensed. It runs on Python 3.13, FastAPI, SQLite/FTS5,
React and a local Ollama model. No paid API, no cloud, no telemetry.*
