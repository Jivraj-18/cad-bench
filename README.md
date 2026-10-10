# CAD benchmark browser stories

**Live site:** https://jivraj-18.github.io/cad-bench/

**Repository:** https://github.com/Jivraj-18/cad-bench

The current six-trial pilot is complete: Claude Opus 5.5 / Claude Code and GPT-6.1 Sol / Codex, both with FreeCAD MCP, each reconstructing the same three drawings. Every story has three horizontal 3D panels: Claude, Codex, and the dataset reference. Each panel rotates, zooms, and resets independently; they start at a common display scale and orientation. Saved CAD revisions and feature-tree stages can be inspected in the browser. Cost and wall time are shown above each output. Reported cost is an API-equivalent token estimate, not actual subscription billing.

| Drawing | Opus score | Sol score |
| --- | ---: | ---: |
| Forked mounting bracket (`f32bdb2966`) | 0.999873 | 0.473345 |
| Stepped enclosure (`6b54209a13`) | 0.615385 | 0.333304 |
| Double-clevis mount (`f4e56c467a`) | 0.663475 | 0.710356 |

These three drawings do not establish a dataset-wide winner. There are no baseline arms in the active scope, so the results do not establish that MCP improved either model. Native CAD submissions and scores have not been manually corrected.

## Browser publication

GitHub Pages serves `docs/`. R2 serves the drawings, exported geometry, unchanged final CAD/Python files, actual sampled CAD revisions, and selected process/scoring evidence under `~/r2/cad-bench/`. Raw native logs and trajectories remain in local `jobs/` and are excluded from public upload. `configs/publication.json` records the public data prefix; each upload bundle includes a size/hash manifest. Three.js 0.186.1 and its MIT license are vendored in `web/lib/`.

```sh
.venv/bin/python scripts/bench.py collect --experiment mcp-3-sol-v1 --enhancement freecad-mcp
.venv/bin/python scripts/visuals.py --experiment mcp-3-sol-v1
.venv/bin/python scripts/story.py --experiment mcp-3-sol-v1
.venv/bin/python scripts/build_site.py --r2-base "$R2_BASE_URL"
mkdir -p ~/r2/cad-bench
cp -a dist/r2/cad-bench/mcp-3-sol-v1 ~/r2/cad-bench/
r2up cad-bench
git add docs stories configs README.md
git commit -m "Update CAD benchmark stories"
git push
```

The bucket must allow GET/HEAD CORS from the GitHub Pages origin. For this deployment the existing allowlist includes `https://jivraj-18.github.io`, `http://127.0.0.1:8765`, and `http://localhost:8765`. When repeating on another account, use your own R2 base URL and allow your Pages origin. `r2up` is the user's existing uploader and requires authenticated Wrangler. The browser renders tessellated geometry; the original editable `.FCStd` files remain available for download.

The scripts below retain the original experiment history and optional repeatability workflows. The background service and timer are **not installed**.

# Current scope

As of 2026-10-10, the active plan contains **6 MCP-only trials**: Claude Opus / Claude Code + FreeCAD MCP and GPT-6.1 Sol / Codex + FreeCAD MCP, each on the original three drawings. Sol replaces Astra and runs first in the new `mcp-3-sol-v1` experiment; old Astra results remain unchanged. Baseline and verification-skill trials are excluded from active planning; historical files remain available. The installed background service and timer have been removed at the user’s request. Scheduler installation instructions below are retained for reproducibility and do not imply that a scheduler is currently installed.

# Drawing-only CAD benchmark

Reconstruct editable parametric FreeCAD parts from engineering drawings, then compare them against the official held-back CAD Bench V3 references. This project extends [Anand's single-example experiment](https://sanand0.github.io/research/2026-10-ed-viz/) to a repeatable **three-example pilot**.

The drawing is the only source of geometry. Every baseline uses the original Harbor instruction: `/app/answer.py` must produce `/app/answer.FCStd`, exactly one PartDesign Body producing one solid, FreeCAD 1.1.0, no online task-specific solutions, and 9,000 seconds. No text specifications, hidden reference models, or graders enter the agent container.

## Experiment

| Model | Native agent | Pinned agent version | Effort |
| --- | --- | --- | --- |
| Claude Opus 5.5 | Claude Code | 2.1.289 | high |
| GPT-6 Astra | Codex | 0.161.0 | high |

Here, an **enhancement** means a skill or tool added to the agent. The pilot tests three separate setups per model:

1. Baseline: official task instruction, native agent, no additional skill or MCP server.
2. Verification skill: frozen Superpowers `verification-before-completion` skill, explicitly invoked. This is a test of that single skill, not the entire Superpowers framework.
3. FreeCAD MCP: frozen `neka-nat/freecad-mcp`, with GUI state inspection, code execution, and visual feedback inside the isolated agent container. Prebuilt-parts/library tools are excluded because the drawing must remain the only geometry source; unrelated FEM tools are excluded. The adapter and exposed tool set are recorded.

This is **6 baseline trials, or 18 trials including both enhancements**. Fable 5.1 and Fable 5 were excluded at the user's request after both access probes required usage credits. The original model list is retained in the configuration; `configs/exclusions.json` records this scope change. The enhancements are not combined. See [HARNESS-MATRIX.md](HARNESS-MATRIX.md) for the exact six setups and [research/selection.md](research/selection.md) for adoption evidence.

The frozen examples are:

- `freecad-f32bdb2966`: Anand's forked mounting bracket.
- `freecad-6b54209a13`: the drawing discussed in this conversation.
- `freecad-f4e56c467a`: drawn from the remaining image tasks using seed `20261008`.

These are convenience anchors plus one seeded sample, not a representative random estimate of the entire dataset. The cohort was frozen before model scores. All comparisons use these same examples.

## Requirements and installation

Use Linux x86-64, Docker Engine with Compose, Git, `uv`, and Python 3.12 or newer. The experiment on this machine uses Python 3.14.7. FreeCAD is installed **inside Docker**; a desktop FreeCAD installation is not used for scoring. Allow roughly 15–25 GB of available disk space for builds, multiple runtimes, and artifacts; the first build can take several minutes.

```bash
uv venv --python 3.14 .venv
uv pip sync --python .venv/bin/python requirements.lock
.venv/bin/harbor --version
docker run --rm hello-world
.venv/bin/python scripts/bench.py prepare --download --count 3
.venv/bin/python scripts/setup-tools.py
```

Harbor is pinned to **0.23.0**. All Python dependency versions are in `requirements.lock`; MCP container dependencies are independently pinned in `tools/mcp-requirements.lock`. Enhancement source commits and individual file hashes are frozen in `configs/enhancements.lock.json`. The source downloader verifies frozen hashes on subsequent runs.

The dataset is `gnucleus-ai/cad-bench` V3, pinned to:

```text
sha256:8a786725d3648a76282fc5868df06da3d5e00d603f283573a53430803465d78a
```

`prepare` downloads all 100 tasks but selects only the **40** that contain the drawing-only instruction, exactly one input PNG, and a separate verifier. `configs/cohort.lock.json` retains the package digests and SHA-256 of every task file. The runner rejects changed task files. Text-to-CAD and create/edit tasks are excluded.

## Authentication

Copy `.env.example` to `.env` and set only the credentials you intend to use. Keep `.env` local and set restrictive permissions (`chmod 600 .env`). Never paste tokens into chat, commit them, or add them to public reports.

### Native subscription runs

```bash
claude setup-token
# Save the returned token locally in .env as CLAUDE_CODE_OAUTH_TOKEN=...
codex login
.venv/bin/python scripts/bench.py preflight --auth subscription
```

Being signed into Claude locally does not automatically give its isolated Harbor container a token. This runner first uses an explicit `CLAUDE_CODE_OAUTH_TOKEN`, or reads an unexpired native Claude CLI credential into memory. The self-loop can refresh an expired native login with a minimal CLI availability probe. Tokens are never written into experiment configs or logs. Harbor uses `CLAUDE_FORCE_OAUTH=1`. Codex uses `CODEX_FORCE_AUTH_JSON=1` and uploads only its login file into the agent container's private credential location. The host's projects, skills, and reference data are not mounted. Subscription model availability and usage limits still apply. Reported token costs are estimates at model list prices, not necessarily subscription charges; missing costs remain unknown.

### API runs

Set `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` in `.env` for API mode. Set provider-side project spending limits. The runner requires `--max-cost-usd` for API runs and stops between trials when reported cost reaches that amount. Claude also receives its supported per-trial dollar limit. **Codex and the MCP arm do not have a guaranteed hard total dollar cap from this runner**: in-flight calls can exceed a between-trial limit. Unknown cost stops subsequent API trials. Use provider limits for a hard bound.

## Plan and run

These commands do not silently use Harbor's default oracle agent.

```bash
# Write and validate six baseline configs; no model calls.
.venv/bin/python scripts/bench.py plan

# Baseline, using subscriptions.
.venv/bin/python scripts/bench.py run --auth subscription

# Run one model, or one task, as an access/vision pilot first.
.venv/bin/python scripts/bench.py run --auth subscription --cell codex-astra --max-trials 1

# Add both enhancement arms. Existing trials are retained, not rerun.
.venv/bin/python scripts/bench.py run --auth subscription \
  --enhancement verification-skill --enhancement freecad-mcp

# Alternatively use API billing with a BETWEEN-TRIAL cost bound.
.venv/bin/python scripts/bench.py run --auth api --max-cost-usd 100
```

The runner invokes `harbor run --config <frozen-config.json>`. It pins the model IDs, CLI versions, effort, provider host allowlist, timeout, and Docker environment. Trials run sequentially to make interruption and budget accounting clear. No automatic retries, model fallbacks, best-of selection, or external solution searches are enabled. Requested model and harness-reported model/version are retained; a requested model ID alone is not proof of provider identity.

For the oracle infrastructure check, use an explicit oracle name and a separate job name:

```bash
.venv/bin/harbor run \
  -p "$PWD/data/cad-bench/freecad-6b54209a13" \
  -a oracle -o "$PWD/jobs" --job-name infrastructure-oracle -n 1 -k 1 -r 0
```

Use **absolute paths** for the jobs directory: Harbor's Compose artifact copy can resolve relative output paths against the task's build directory. Oracle results are excluded from model results. The oracle copies a known reference to test the scorer and should score 1.0; it is not an AI reconstruction.

## Logs, frozen submissions, and repeatability

Keep the entire project audit archive, not just `results.csv`:

| Location | Contents |
| --- | --- |
| `configs/` | Experiment definition, immutable cohort and source hashes |
| `data/cad-bench/` | Exact task instructions, drawings, runtime and grader sources, licenses |
| `data/variants/` | Derived MCP agent environments; official verifier unchanged |
| `vendor/` | Frozen skill/tool source and licenses |
| `runs/<experiment>/` | Planned configs, actual launch exit codes and hashes, execution snapshot |
| `jobs/<job>/<trial>/agent/` | Native agent stdout/events, native session files, converted tool trajectory |
| `jobs/<job>/<trial>/artifacts/` | Submitted Python and CAD; new configs also collect the full `/app` workspace |
| `jobs/<job>/<trial>/verifier/` | Official reward, diagnostic reasons, stdout/stderr, candidate preview |
| `jobs/<job>/<trial>/result.json` | Versions, timing, token/cost fields, exception details |
| `reports/<experiment>/` | Structured results, CSV, rendered comparisons, static stories |
| `stories/<experiment>/` | Editable narrative Markdown, preserved on rebuild |

The initial Astra baseline batch used Harbor's original task artifact list (`answer.py` and `answer.FCStd`) before full `/app` collection was added; its native tool logs retain crop-generation commands and image observations. Later launch configs collect the full workspace. Canonical final submissions always come from Harbor's task artifact collection and are hashed after the trial. Intermediate snapshots must not be mistaken for the final graded candidate. Files deleted by an agent are not recovered by final workspace collection; retain the native trajectory to reconstruct intermediate operations.

Preserve failed and cancelled trials too. Existing job directories are never silently overwritten or automatically rerun. Use a new experiment name for a genuinely new attempt or changed setup, and retain the old one. A `not_run` or `incomplete` trial has no score; a completed failed launched trial counts as zero in aggregate analysis. Pending cells must not be treated as failed models.

Task runtimes use pinned FreeCAD/NumPy and a pinned base-image digest, but some transitive conda/APT packages in the **official** Dockerfiles are not individually frozen. Record the actual Docker image IDs/digests and retain images (`docker save`) for stronger offline reproduction. Identical source/configuration does not guarantee identical outputs from a hosted stochastic model or a changing subscription backend.

Inspect raw logs locally:

```bash
.venv/bin/harbor view "$PWD/jobs"
```

Raw logs may contain account-sensitive session metadata. They stay local and are not embedded wholesale in the public-style story. Credential files are never part of the audit export.

## Generate and edit the stories

```bash
.venv/bin/python scripts/bench.py collect \
  --enhancement verification-skill --enhancement freecad-mcp
.venv/bin/python scripts/build-render-runtime.py
.venv/bin/python scripts/visuals.py
.venv/bin/python scripts/story.py
python3 -m http.server 8000 --bind 127.0.0.1 --directory reports/pilot-3-v1
```

Open `http://127.0.0.1:8000`. Each example gets its own story: original drawing, all model/setup results, hidden reference vs frozen candidate, a comparison slider, construction stages, actual grader diagnostics, exact instruction, and downloadable submitted CAD. Raw CSV and JSON are available alongside the stories.

Edit `stories/pilot-3-v1/<task>.md`, then rerun `story.py`. Narrative edits survive regeneration and never change the official scores or submitted CAD. These are portable static files, so the report can be copied elsewhere after reviewing evidence files. No publication or upload is automatic.

Comparison renders use a separate offline FreeCAD 1.1.0 runtime. Reference and candidate share camera and scale. Alignment is rigid rotation/translation only: no reflection, deformation, or rescaling. PCA/ICP alignment is approximate visualization, independently documented in `alignment.json`; it does not replace the official geometric scorer.

## Interpret the results

An official perfect result is **reward 1.0**. Geometry similarity, specification consistency, and the combined reward are reported separately. A good specification score can match values on the wrong features; a valid solid and a plausible render do not establish correctness. Keep errors, missing measurements, and unsupported access visible.

Compare an enhancement against the **same model on the same task**, with the same effort and time limit. Report paired differences, not just a mixed leaderboard. Verify tool/skill use from trajectories before attributing an improvement. Model access, context compaction, network failures, different tool overhead, and execution dates can affect results. Three examples and one attempt per setup are a pilot, not a statistically convincing claim about the entire benchmark.

## Validation

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Tests cover cohort filtering, changed-file rejection, withheld verifier integrity, missing/failed result semantics, and rigid visualization alignment. The official oracle checks the actual FreeCAD/scorer runtime independently.

## Automatic self-loop for usage limits

The installed `cad-bench-self-loop.timer` runs independently of this chat. It checks pending work every two minutes after the previous worker activation finishes. It covers both Claude Code/Opus and Codex/Astra, including the two enhancement arms. The MCP arm is gated on a passed `scripts/smoke-mcp.py` test. No charger or internet checks are performed, as requested.

The worker stops an affected active run when it sees a provider usage-limit rejection, retains its logs/artifacts, and waits until a structured provider reset time plus 60 seconds when available. If the provider omits a reset timestamp, it waits one hour before a small native-model availability probe. A successful probe starts a separately named `--rescheduled-N` attempt. The original failure is not erased. There is no fixed reschedule count cap. Ordinary CAD/code failures are retained without automatic reruns. Billing/access errors such as `credits_required` are not treated as temporary quota resets; Fable is excluded entirely.

The queue runs one new trial per activation and waits for existing active benchmark jobs. The machine must remain powered and the user service manager must be running; a user-level timer survives closing this chat, but is not a promise that trials continue through shutdown/logout. Refresh and availability probes consume a small amount of the same native subscription usage. The worker explicitly removes API-key variables for scheduled runs so they do not silently switch into API billing.

Install on another machine (after preparing the project and authenticating):

```bash
.venv/bin/python scripts/install-loop.py
systemctl --user status cad-bench-self-loop.timer
systemctl --user list-timers cad-bench-self-loop.timer
```

State and logs:

```text
runs/pilot-3-v1/queue-state.json
runs/pilot-3-v1/scheduler.log
runs/pilot-3-v1/scheduler-logs/
runs/availability-probes/
```

To stop the loop and the current worker explicitly:

```bash
systemctl --user stop cad-bench-self-loop.timer cad-bench-self-loop.service
```

To resume:

```bash
systemctl --user start cad-bench-self-loop.timer
```

## Parallel Sol pass and stories

The three `mcp-3-sol-v1` Sol trials run concurrently in separate Harbor Docker environments. Each uses the original drawing-only instruction, FreeCAD 1.1.0, high reasoning, and the frozen MCP tool. No background systemd service is installed.

Per-drawing stories in `reports/mcp-3-sol-v1/` show reported token cost and total wall time at the top; reported API-equivalent cost is not a subscription charge. Unknown cost is not zero. Only consequential CAD actions are shown in the story; full logs stay in `jobs/`. The observer samples changed `/app/answer.py` and `/app/answer.FCStd` every 30 seconds into each trial's `progress/` directory. This is a sampled history, not a guarantee of capturing every transient revision. Snapshot rendering suppresses repeated geometry. Final feature-tree stages describe construction history; they are distinct from actual intermediate saves.

After the runs finish, regenerate evidence and stories with:

```sh
.venv/bin/python scripts/bench.py collect --experiment mcp-3-sol-v1 --cell codex-sol-6-1 --enhancement freecad-mcp
.venv/bin/python scripts/visuals.py --experiment mcp-3-sol-v1
.venv/bin/python scripts/story.py --experiment mcp-3-sol-v1
```

Editable interpretation lives in `stories/mcp-3-sol-v1/*.md`. Changes there survive regeneration. Trial logs, timelines, intermediate snapshots, final candidates, and verifier diagnostics remain separately available for audit.
