# Setup log: Declarative Automation Bundles demo

This document records everything that has been set up for the Declarative Automation Bundles (DABs) demo:
which objects were created in Databricks and GitHub, which files were added to the repositories and why,
the exact commands that were run, what was tested, and which problems were found and fixed on the way.

## 1. Goal and architecture

The demo shows how a **platform team** and several **use-case teams** can work with bundles in a setup
that is close to a real one:

| Piece | Where | Owner |
| --- | --- | --- |
| Shared objects (schemas, landing volume, sample data) | `platform-bundle/` in this repo | Platform team |
| Reusable CI workflow (validate, rules, tests, plan, deploy to qa and prd) | `.github/workflows/bundle-ci.yml` in this repo | Platform team |
| Platform rules checked on every PR | `ci/check_rules.py` in this repo | Platform team |
| Template every new use case starts from | `templates/use-case/` in this repo | Platform team |
| Use-case bundles (`sales`, `ingestion`) | `dabs-use-cases-test` repo, one folder per bundle | Each use-case team |

The platform team defines the template, the CI and the rules **once**. Each use-case repository calls the
CI workflow by version (`@v1`), so a change released here reaches every use case.

```
GitHub: cesarpazguzman
├── dabs-platform-test      (this repo: platform bundle, reusable CI, rules, template)
└── dabs-use-cases-test     (one bundle per folder; calls bundle-ci.yml@v1)
            │
            │ GitHub Actions: branch qa → target qa (sp-dabs-qa)
            │                 branch main → target prd (sp-dabs-prd, after approval)
            ▼
Databricks Free Edition workspace · catalog demo_dabs
├── metadata.ingestion_datasets     (table that drove the ingestion bundle; replaced by a file, 7.3)
├── landing.files                   (volume with sample CSV files)
└── <use_case>_dev · <use_case>_qa · <use_case>_prd   (one schema per use case and environment)
```

All data comes from the built-in `samples.tpch` dataset. No customer data is used.

## 2. Environments and branching model

### 2.1 One branch per environment

Each shared environment has its own long-lived branch. Merging into that branch is what deploys it.

| Target | Branch | Who deploys | Identity | When | Purpose |
| --- | --- | --- | --- | --- | --- |
| `dev` | any feature branch | Each developer, from a laptop | The developer's own user | While working on a change | Try a change without affecting anyone else |
| `qa` | `qa` | CI only | Service principal `sp-dabs-qa` | On every merge into `qa` | Integration: the result of everyone's changes |
| `prd` | `main` | CI only | Service principal `sp-dabs-prd` | On every merge into `main`, **once a reviewer approves** | Production |

```
feature/*  ──PR──►  qa    ──push──►  deploy qa  (automatic)
qa         ──PR──►  main  ──push──►  deploy prd (manual approval)
hotfix/*   ──PR──►  main  ──push──►  deploy prd (manual approval)  ──►  merge main back into qa

any branch  ──laptop: databricks bundle deploy──►  dev (personal copy)
```

- `qa` is the default branch of the use-case repository, so new branches and PRs start from it.
- **Only `qa` and `hotfix/*` can be merged into `main`.** This is enforced by the CI (section 5.3).
- `qa` → `main` (promotion) and `main` → `qa` (back-merge) use **merge commits**, never squash, so both
  branches keep the same history. Feature branches are squashed into `qa`.

### 2.2 Why one branch per environment

The demo started with a trunk-based model (only `main`; qa and prd deployed from the same commit, prd after an
approval). It was changed after rehearsing this scenario:

> Change A is merged and deployed to qa, but it is not ready for production. Change B, an urgent fix, is merged
> after it. B's commit contains A, so B cannot reach prd without A.

With trunk-based development the only ways out are reverting A or hiding it behind a feature flag. With one
branch per environment, `main` only contains what has already been promoted, so a `hotfix/*` branch taken from
`main` does not contain A and goes straight to prd.

| | Trunk-based (previous) | One branch per environment (current) |
| --- | --- | --- |
| Normal promotion | Approve the prd deployment of a run | PR `qa` → `main`, then approve |
| Urgent fix with an unfinished change ahead of it | Revert the change, or a feature flag | `hotfix/*` → `main`, then back-merge into `qa` |
| Long-lived branches | 1 | 2 |
| PRs per change | 1 | 2 (feature → `qa`, `qa` → `main`) |
| "What is in prd?" | The commit of the last approved run | The branch `main` |
| Typical risk | Something not ready gets into `main` | `qa` and `main` drift apart (forgotten back-merges) |

Costs that come with this model, and how they are handled:

- **A promotion takes everything that is in `qa`.** If something in `qa` is not ready, it must be reverted in
  `qa` or be behind a flag before promoting. The hotfix path is what this model makes easier.
- **A hotfix skips qa.** It only gets the PR checks (validation, rules, unit tests) and the developer's own
  dev test. A stricter setup could deploy it to a separate target before prd.
- **Back-merges are mandatory.** After a hotfix, `main` must be merged back into `qa`; otherwise qa is tested
  against a state that is not the one in production.

### 2.3 What `dev` is

`dev` is the developer's working environment. It is where a change is tested before a PR is opened:

```bash
git switch qa && git pull                   # start from the latest qa
git switch -c feature/my-change
# edit resources/ or src/
databricks bundle validate --strict         # same check as CI
databricks bundle plan                      # what will change in MY dev copy
databricks bundle deploy                    # dev is the default target
databricks bundle run sales_main            # does it work?
```

- `dev` uses `mode: development`. Each developer gets **their own copy** of the bundle's jobs and files
  (for example `[dev cesar_paz] sales-main-dev`, under `/Workspace/Users/<user>/.bundle/...`), and schedules
  are paused, so developers never overwrite each other's jobs.
- **Data in dev is shared** (`<use_case>_dev`). If two developers run the same dev job at the same time, the
  last write wins. Deploying and running from an **outdated branch** writes old logic into the shared tables,
  so the team rule is: update the branch from `qa` before deploying to dev.
- A dev copy that falls behind is not a problem in itself: it is disposable. `bundle deploy` creates, updates
  **and deletes** jobs so the copy matches the code, and `databricks bundle destroy` removes it completely.
- `dev` is the default target as a safety net: a plain `databricks bundle deploy` can never reach qa or prd.
- Who can deploy to each target is not decided by `databricks.yml` but by permissions and CI. Developers have
  no write access to the qa and prd schemas, and only GitHub holds the service principal secrets.

## 3. Environment

| Item | Value |
| --- | --- |
| Databricks workspace | Free Edition, `https://dbc-e146da84-2d63.cloud.databricks.com` |
| Databricks CLI | v1.22.1 |
| Catalog | `demo_dabs` |
| SQL warehouse | `Serverless Starter Warehouse` |
| CI identities | Service principals `sp-dabs-qa` and `sp-dabs-prd` |
| GitHub | Personal account `cesarpazguzman`, two public repositories |

Free Edition limitations that shape the design:

- **One workspace only.** `dev`, `qa` and `prd` are separate *schemas* in the same workspace. In a real setup,
  at least prd would live in its own workspace.
- **Serverless compute only.** Jobs do not define clusters.
- **At most 5 concurrent job tasks.** Jobs are run one at a time.

## 4. Step 1: Workspace preparation

### 4.1 Authenticate the Databricks CLI

```bash
databricks auth login --host https://dbc-e146da84-2d63.cloud.databricks.com
```

**Why:** the CLI is the tool that validates, plans and deploys bundles. Logging in stores a profile in
`~/.databrickscfg` (OAuth, user-to-machine). Local deployments run **as the developer**, using this profile.
No credentials are stored in any repository or `.env` file.

### 4.2 Create the catalog

Run in the SQL editor:

```sql
CREATE CATALOG IF NOT EXISTS demo_dabs;
```

**Why:** Unity Catalog organises data as `catalog.schema.table`. The catalog is the top-level container for
everything in the demo. It is created once, by hand, because it is the platform's responsibility and
sits above every bundle. Schemas inside it are created as code (see step 2).

### 4.3 Identify the SQL warehouse

```bash
databricks warehouses list
# <warehouse-id>  Serverless Starter Warehouse
```

**Why:** the first version of the `ingestion` bundle generated its jobs by reading a metadata table at deploy
time, and it ran that query on a SQL warehouse, found **by name** with a variable lookup so its ID did not
have to be exported, stored in a `.env` file or kept as a GitHub secret. Since the bundle reads a file
instead (section 7.3), no bundle needs the warehouse; it is only used from the SQL editor.

### 4.4 Create the CI identities (one service principal per environment)

**Why service principals:** GitHub Actions must not deploy with a person's credentials. A service principal
is a technical identity that authenticates with OAuth machine-to-machine (a client ID plus a secret).

**Why one per environment:** if the qa credentials leak, they must not be usable against production. Each
service principal only has write access to its own environment's schemas, and the prd secret is only handed
to the prd deployment job after an approval (see 5.10).

Create both service principals with workspace and Databricks SQL access:

```bash
for sp in sp-dabs-qa sp-dabs-prd; do
  databricks service-principals create --json "{\"displayName\":\"$sp\",\"active\":true,\"entitlements\":[{\"value\":\"workspace-access\"},{\"value\":\"databricks-sql-access\"}]}"
done
databricks service-principals list          # shows each one's id and applicationId
```

Generate an OAuth secret for each one (lifetime: 90 days):

```bash
databricks service-principal-secrets-proxy create <service-principal-id> --lifetime 7776000s
```

The same can be done in the UI: Settings → Identity and access → Service principals → **Add service
principal**, then Secrets → **Generate secret**.

- The **client ID** is the service principal's *application ID* (a UUID). The numeric `id` is only used to
  manage it (for example, to create the secret).
- Secrets have the scope **`all-apis`**, because a deployment touches many APIs: workspace files, jobs,
  Unity Catalog and SQL statement execution. A narrower scope makes `bundle deploy` fail. The scope does
  **not** grant access to data; data access is controlled only by the Unity Catalog grants in step 3.
- Each secret is shown only once. It was stored directly as a GitHub secret (section 5.10) and is not
  written anywhere else. Secrets expire after 90 days, so they must be rotated.

A first service principal, `sp-dabs-demo`, was used while the demo had a single CI identity. It was retired
once `sp-dabs-qa` and `sp-dabs-prd` were in place (section 10).

## 5. Step 2: Platform repository (`dabs-platform-test`)

### 5.1 Repository layout

```
dabs-platform-test/
├── .github/workflows/
│   └── bundle-ci.yml                     # reusable CI workflow
├── ci/
│   └── check_rules.py                    # platform rules
├── templates/use-case/                   # use-case template
│   ├── databricks_template_schema.json
│   └── template/
│       ├── {{.use_case}}/databricks.yml.tmpl
│       ├── {{.use_case}}/resources/{{.use_case}}.job.yml.tmpl
│       ├── {{.use_case}}/src/main.py
│       └── .github/workflows/deploy-{{.use_case}}.yml.tmpl
├── platform-bundle/                      # platform bundle
│   ├── databricks.yml
│   ├── resources/platform.yml
│   └── src/setup_demo.py
├── .gitignore
├── README.md                             # short overview
└── STEPS.md                              # this document
```

### 5.2 Platform bundle (`platform-bundle/`)

| File | What it does | Why |
| --- | --- | --- |
| `databricks.yml` | Declares the bundle `platform`, the `catalog` variable (default `demo_dabs`) and a single target `demo` pointing at the workspace. | Entry point of the bundle. The catalog is a variable so the same code could target another catalog. |
| `resources/platform.yml` | Declares eight schemas (`metadata`, `landing`, and `sales_*` / `ingestion_*` for `dev`, `qa` and `prd`), the managed volume `landing.files` and the job `platform-setup-demo`. | Shared objects are created **as code**, before any use case exists. This answers "who creates the catalog and the schemas": the platform. In a real setup this could be Terraform; a bundle shows it is also possible. |
| `src/setup_demo.py` | Notebook that writes six `samples.tpch` tables as CSV files into the landing volume and creates the table `metadata.ingestion_datasets` with one row per dataset to ingest. | Provides realistic input files and the metadata table for the `ingestion` use case. The `part` dataset is written as CSV but **left out of the metadata table on purpose**, so it can be added live during the demo. |

The platform bundle is deployed by hand and is **not** checked by the platform rules, because creating
schemas is exactly what it is meant to do.

### 5.3 Reusable CI workflow (`.github/workflows/bundle-ci.yml`)

**What it is:** the single place that defines how any bundle is validated and deployed. It declares
`on: workflow_call`, so other repositories call it with
`uses: cesarpazguzman/dabs-platform-test/.github/workflows/bundle-ci.yml@v1`.

The workflow works out the target from the branch the change goes into: the PR's base branch, or the
pushed branch. `main` means `prd`; `qa` means `qa`.

**Jobs:**

| Job | Runs on | Identity | Steps |
| --- | --- | --- | --- |
| `plan` | Every PR into `qa` or `main`, and every push to them | `sp-dabs-qa` (repository secrets) | Branch policy (PRs into `main` only), `bundle validate --strict`, platform rules, `bundle plan` (qa only), unit tests (if the bundle has `tests/`) |
| `deploy-qa` | Push to `qa`, after `plan` | `sp-dabs-qa` (GitHub environment `qa`) | Skip stale deployments, `bundle deploy -t qa` |
| `deploy-prd` | Push to `main`, after `plan`, **once a reviewer approves** | `sp-dabs-prd` (GitHub environment `prd`) | Refuse stale deployments, `bundle plan -t prd`, `bundle deploy -t prd` |

Every job checks out the calling repository and installs the Databricks CLI. If the bundle has a
`requirements-bundle.txt`, it also creates the bundle's Python virtual environment (needed by bundles that
generate resources in Python). The `plan` job also checks out this repository at tag `v1` to get the rules.
All jobs run on a pinned runner image (`ubuntu-24.04`) and current action versions (`checkout@v5`,
`setup-java@v5`).

**Safeguards, and why each one exists:**

| Safeguard | What it does | Why |
| --- | --- | --- |
| `validate --strict` | Treats warnings as errors | A plain `validate` only **warns** about an unknown field (for example `notebok_task` instead of `notebook_task`) and exits with code 0; `plan` even shows `update jobs.sales_main` as if nothing were wrong. Found while rehearsing (section 9). |
| Validation against the right target | A PR into `main` is validated and checked against the **prd** configuration | What is checked is what will be deployed. |
| Branch policy | In a PR into `main`, fails unless the source branch is `qa` or `hotfix/*` | GitHub cannot restrict the source branch of a PR. Because the step is part of the required check `ci / plan`, the PR can be opened but not merged. |
| Back-merge check | In a PR from `qa` into `main`, fails if `main` has file changes that `qa` does not contain (`git diff` from the merge base of both branches to `main`) | Forces a hotfix to be merged back into `qa` before the next promotion. A normal promotion's merge commit changes no files, so it never asks for a sync. |
| Plan only for qa in PRs | `bundle plan -t prd` runs inside `deploy-prd`, just before the deployment | The qa identity cannot read the prd deployment state. The prd plan is logged with the prd identity as a record of what was applied. |
| Unit tests | If the bundle has `tests/`, installs `requirements-test.txt` and runs `pytest` on a local Spark | Catches logic errors that `validate` and `plan` cannot see (section 7.5). |
| `concurrency` per bundle and environment | At most one deployment per bundle and environment at a time, plus one queued; a newer queued run replaces an older queued one | Two deployments of the same target would otherwise collide (the bundle takes a deployment lock and the second one fails). |
| Skip stale deployments (qa) | Before deploying, compares the bundle folder of this run with the current tip of `qa`. If `qa` has moved on, it skips the deployment with a notice | `concurrency` serialises runs but does not order them. A run whose `plan` was slower could otherwise deploy an **older** state on top of a newer one. The newer run already contains the change. |
| Refuse stale deployments (prd) | Same comparison against the tip of `main`, but it **fails** | In prd, approving an old run is a human mistake that must be visible. |

`concurrency` does not cancel a run that is waiting for approval: GitHub counts it as in progress. Newer runs
queue behind it, so prd runs are approved one at a time, oldest first, and the stale check stops an old one
from overwriting a newer state.

**Credentials:** each job reads `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET`
from the **calling** repository (passed with `secrets: inherit`). A job that declares `environment: prd`
receives that environment's secrets, which override the repository secrets with the same name. That is how
`deploy-prd` gets the prd service principal. The `plan` job of a PR uses the **qa** identity: a PR has not
been approved yet, so it never gets prd credentials.

### 5.4 Platform rules (`ci/check_rules.py`)

**What it is:** a script that reads the fully resolved bundle configuration from
`databricks bundle validate --output json` and fails the PR if a rule is broken.

| Rule | Check |
| --- | --- |
| 1 | A use-case bundle must not create catalogs or schemas (that is the platform's job). |
| 2 | Every job name starts with the bundle name followed by `-` and is lowercase. |
| 3 | Every job has `email_notifications.on_failure`. |
| 4 | Every job has an `owner` tag (`tags.owner`), for support and cost reports. Added during the rehearsal to show a new rule reaching every repository (section 9). |

**Why:** the rules run on the **final** configuration, with variables resolved and Python-generated
resources included. They therefore see exactly what will be deployed, including jobs generated from
metadata. Because the script lives here, changing a rule changes it for every repository at once.

### 5.5 Use-case template (`templates/use-case/`)

**What it is:** the skeleton every use case starts from. `databricks bundle init` asks the questions in
`databricks_template_schema.json` and copies `template/`, replacing the `{{.variable}}` placeholders
(also in file names). Files ending in `.tmpl` are processed; the rest are copied as they are.

| Parameter | Asked? | Value | Used for |
| --- | --- | --- | --- |
| `use_case` | Yes | (lowercase, digits and `_`) | Bundle name, folder name, job name, schema names |
| `github_org` | No | `cesarpazguzman` | The `uses:` line that calls the reusable workflow |
| `catalog` | No | `demo_dabs` | Default value of the `catalog` variable |
| `qa_sp` | No | `sp-dabs-qa` | Service principal that deploys and runs qa |
| `prd_sp` | No | `sp-dabs-prd` | Service principal that deploys and runs prd |

Only the use-case name is asked. The other parameters are decided by the platform, so they are hidden with
`"skip_prompt_if": {}` and always take their default value. In particular, the deployment identities are not
the use-case team's choice. The service principal values are written into the `qa` and `prd` targets; `dev`
never uses a service principal.

**A template is a starting point, not a link.** `bundle init` runs once per use case; after that, the files
belong to the use-case team and are never regenerated. Platform changes reach existing use cases like this:

| What the platform changes | Reaches existing use cases automatically? | How |
| --- | --- | --- |
| CI workflow (`bundle-ci.yml`) | Yes | Use cases call it by `@v1`; moving the tag updates the next run |
| Rules (`check_rules.py`) | Yes | CI checks them out at `@v1` on every PR |
| Template (`templates/use-case/`) | No, only new use cases | Existing use cases adapt through a PR; a new rule can make the change mandatory |

So anything that must always apply to every use case belongs in the CI or the rules, not only in the template.

| Generated file | Content |
| --- | --- |
| `<use_case>/databricks.yml` | Variables and the three targets described below. `{{workspace_host}}` is filled in with the workspace the CLI is logged into. |
| `<use_case>/resources/<use_case>.job.yml` | A sample job `<use_case>-main-<target>` that already complies with the rules. `{{user_name}}` (the person running `bundle init`) receives the failure emails. |
| `<use_case>/src/main.py` | A sample notebook that writes a small table into the environment schema. |
| `.github/workflows/deploy-<use_case>.yml` | The use-case workflow. It runs on PRs into and pushes to `qa` and `main`, only when files in its own folder change, and delegates everything to `bundle-ci.yml@v1`. |

**Targets in the generated `databricks.yml`:**

| Target | `mode` | Schema | Root path | Runs as |
| --- | --- | --- | --- | --- |
| `dev` (default) | `development` | `<use_case>_dev` | `/Workspace/Users/<developer>/.bundle/...` | The developer |
| `qa` | `production` | `<use_case>_qa` | `/Workspace/Users/<sp-dabs-qa>/.bundle/...` | `sp-dabs-qa` |
| `prd` | `production` | `<use_case>_prd` | `/Workspace/Users/<sp-dabs-prd>/.bundle/...` | `sp-dabs-prd` |

- `mode: production` enforces a single, fixed copy per environment: the CLI refuses to deploy unless
  `root_path` is set. The root path is the service principal's home folder, which other users cannot write to
  (a `/Workspace/Shared` path would be writable by everyone).
- `run_as` makes the qa and prd jobs run as their service principal, not as whoever deployed or started them.
- The service principals are found **by name** with a variable lookup, so their IDs are not hard-coded:

  ```yaml
  variables:
    deployer_sp:
      default: ""                # dev does not use a service principal
  targets:
    qa:
      variables:
        deployer_sp:
          lookup:
            service_principal: sp-dabs-qa
  ```

  The variable needs a value in every target, so it defaults to an empty string that `dev` never uses.

**Why:** every use case is born with the same structure, the same environments and a job that already
passes the rules. Teams do not copy and paste from each other.

### 5.6 `.gitignore`

Excludes `.databricks/` (local deployment state), `.venv/`, `__pycache__/` and `.env`, so no local state
or credentials are committed. The use-case repository also ignores `.venv-test/` and `.pytest_cache/`.

### 5.7 Deploy and run the platform bundle

From `platform-bundle/`:

```bash
databricks bundle validate        # checks the configuration; "Validation OK!"
databricks bundle plan            # shows what will change
databricks bundle deploy          # creates the schemas, the volume and the job
databricks bundle run setup_demo  # runs the job: TERMINATED SUCCESS
```

The bundle was first deployed with the dev and qa schemas (8 resources: 6 schemas, 1 volume, 1 job). When
the prd environment was added, the same `plan` and `deploy` created only the two new schemas
(`sales_prd`, `ingestion_prd`) and left everything else unchanged.

Verification:

```bash
databricks schemas list demo_dabs
# default, information_schema, ingestion_dev, ingestion_prd, ingestion_qa, landing, metadata,
# sales_dev, sales_prd, sales_qa

databricks fs ls dbfs:/Volumes/demo_dabs/landing/files/
# customer, nation, orders, part, region, supplier
```

```sql
SELECT * FROM demo_dabs.metadata.ingestion_datasets ORDER BY dataset;
-- 5 rows: customer, nation, orders, region, supplier (all active; part is left out on purpose)
```

### 5.8 Test the template

The template was tested locally by generating a throwaway use case called `marketing` outside the
repository, validating every target and running the platform rules on it:

```bash
databricks bundle init templates/use-case --config-file <answers.json> --output-dir <tmp-dir>
cd <tmp-dir>/marketing
databricks bundle validate -t dev    # root path in the developer's folder
databricks bundle validate -t qa     # root path in sp-dabs-qa's folder
databricks bundle validate -t prd    # root path in sp-dabs-prd's folder
databricks bundle validate -t qa --output json | python3 <path-to>/ci/check_rules.py
# Platform rules: OK
```

### 5.9 Publish and update version `v1`

```bash
git add . && git commit -m "Platform v1" && git push origin main
git tag v1 && git push origin v1
```

**Why:** use cases call the workflow and the rules by the tag `v1`, not by `main`. The platform team
decides when a change is released. To publish a change to every repository, the tag is moved:

```bash
git commit -am "<change>" && git push
git tag -f v1 && git push -f origin v1
```

What moving the tag means in practice (all of these were observed during the rehearsal):

- **Every use case gets the new version on its next run**, without opting in. A bug in the platform breaks
  everyone's CI at once.
- **Runs that already exist keep the old version.** GitHub resolves `@v1` when a run is created; re-running
  a failed job reuses the workflow it was created with, even after the tag has moved. A platform fix only
  applies to new runs.
- The rules are checked out with `ref: v1` when the step runs, so a re-run can combine an old workflow with
  newer rules.
- A change validated in qa with the previous version can fail in the promotion PR if the new version brings a
  stricter rule. That is sometimes the goal (it forces adaptation), but it should not come as a surprise.

How to version this safely in a real setup is listed in section 12.

### 5.10 GitHub secrets and environments

All of this is configured in **`dabs-use-cases-test`** → Settings.

**Repository secrets** (Secrets and variables → Actions), used by `plan` and `deploy-qa`:

| Secret | Value |
| --- | --- |
| `DATABRICKS_HOST` | Workspace URL |
| `DATABRICKS_CLIENT_ID` | Application ID of `sp-dabs-qa` |
| `DATABRICKS_CLIENT_SECRET` | OAuth secret of `sp-dabs-qa` |

**Environments** (Environments → New environment):

| Environment | Required reviewers | Deployment branches | Environment secrets |
| --- | --- | --- | --- |
| `qa` | None | `qa` only | None (uses the repository secrets) |
| `prd` | Yes (self-review allowed in this demo) | `main` only | `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET` of `sp-dabs-prd` |

The reviewers and the deployment branches are saved with **their own "Save protection rules" button**,
separate from the secrets. During setup the prd reviewers were not saved, and the first merge deployed to prd
without waiting. Check what is really configured with:

```bash
gh api repos/cesarpazguzman/dabs-use-cases-test/environments --jq '.environments[] | {name, rules: [.protection_rules[].type]}'
# {"name":"prd","rules":["required_reviewers","branch_policy"]}
# {"name":"qa","rules":["branch_policy"]}
```

**Why an environment for qa, even without reviewers:**

- The branch restriction lives in the repository settings, not in a workflow file, so a PR cannot change it.
- It keeps a deployment history: which commit is in qa, and when.
- It leaves a place for qa-specific secrets or a wait timer without changing the CI.

**Why the prd secrets live only in the `prd` environment:** GitHub only gives them to a job that declares
`environment: prd`, and only after a reviewer approves it. No PR and no other job can use them.

**Why only in the use-case repository:** a reusable workflow runs in the context of the repository that
calls it and receives that repository's secrets through `secrets: inherit`. This repository never deploys
from GitHub (the platform bundle is deployed by hand), and it is public, so the CI can check out the rules
without credentials. Each use-case repository therefore owns its own deployment identities, while the
platform only defines *how* to deploy.

### 5.11 Branch protection (rulesets `protect-qa` and `protect-main`)

`dabs-use-cases-test` → Settings → Rules → Rulesets. There is one ruleset per branch, with the branch name
listed explicitly instead of `~DEFAULT_BRANCH` (the default branch is `qa`, so `main` would otherwise be left
unprotected).

| Rule | `qa` | `main` | Effect |
| --- | --- | --- | --- |
| Restrict deletions | ✓ | ✓ | The branch cannot be deleted |
| Block force pushes | ✓ | ✓ | History cannot be rewritten |
| Require a pull request | ✓ | ✓ | One approval, **review from code owners**, approvals dismissed when new commits are pushed |
| Require status checks: `ci / plan` | ✓ | ✓ | The PR cannot be merged until validation, rules, branch policy, back-merge check and tests pass |
| Require branches to be up to date | ✓ | — | The PR must contain the latest `qa`, so CI tests the combination that will actually be merged |
| Bypass: repository admin, *pull requests only* | ✓ | ✓ | The admin can merge a PR without waiting for the requirements (needed here because the same account opens and approves PRs), but cannot push directly |

**Why `main` does not require branches to be up to date:** every promotion creates a merge commit that only
exists on `main`, so `qa` is always one commit behind afterwards. With the rule on `main`, every promotion would
first need a `main` → `qa` sync PR, even when nothing had changed. `main` only receives changes that were
already tested in `qa` or explicit hotfixes, and the back-merge check (section 5.3) asks for a sync only when
`main` really has something `qa` lacks.

The first version was a single ruleset for both branches, created with:

```bash
gh api -X POST repos/cesarpazguzman/dabs-use-cases-test/rulesets --input - <<'EOF'
{
  "name": "protect-main-and-qa",
  "target": "branch",
  "enforcement": "active",
  "conditions": { "ref_name": { "include": ["refs/heads/main", "refs/heads/qa"], "exclude": [] } },
  "bypass_actors": [ { "actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "pull_request" } ],
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    { "type": "pull_request", "parameters": {
        "required_approving_review_count": 1, "require_code_owner_review": true,
        "dismiss_stale_reviews_on_push": true, "require_last_push_approval": false,
        "required_review_thread_resolution": false } },
    { "type": "required_status_checks", "parameters": {
        "strict_required_status_checks_policy": true,
        "required_status_checks": [ { "context": "ci / plan", "integration_id": 15368 } ] } }
  ]
}
EOF
gh repo edit cesarpazguzman/dabs-use-cases-test --default-branch qa
```

`actor_id: 5` is the repository **Admin** role and `integration_id: 15368` is GitHub Actions. A direct push
to `main` is rejected with "Changes must be made through a pull request".

It was then split in two: the existing ruleset was limited to `qa`, and a copy without "up to date" was
created for `main`:

```bash
R=repos/cesarpazguzman/dabs-use-cases-test
RS=<ruleset-id>

gh api $R/rulesets/$RS \
  | jq '{name:"protect-qa",target,enforcement,bypass_actors,rules,
         conditions:{ref_name:{include:["refs/heads/qa"],exclude:[]}}}' \
  | gh api -X PUT $R/rulesets/$RS --input -

gh api $R/rulesets/$RS \
  | jq '{name:"protect-main",target,enforcement,bypass_actors,
         conditions:{ref_name:{include:["refs/heads/main"],exclude:[]}},
         rules:(.rules | map(if .type=="required_status_checks"
                             then .parameters.strict_required_status_checks_policy=false else . end))}' \
  | gh api -X POST $R/rulesets --input -
```

A PR that changes no bundle folder (for example only `CODEOWNERS`) does not start any workflow, because the
workflows filter by path. The required check never reports and the PR waits for it; the admin bypass is
needed to merge it.

## 6. Step 3: Permissions

### 6.1 Service principals

The service principals deploy and run the qa and prd jobs, so they need Unity Catalog grants. They are
identified by their application ID. Run in the SQL editor (or through the SQL Statement Execution API):

```sql
-- Both service principals: reach the catalog, read metadata and landing files
GRANT USE CATALOG ON CATALOG demo_dabs TO `<qa-application-id>`;
GRANT USE CATALOG ON CATALOG demo_dabs TO `<prd-application-id>`;
GRANT USE SCHEMA, SELECT ON SCHEMA demo_dabs.metadata TO `<qa-application-id>`;
GRANT USE SCHEMA, SELECT ON SCHEMA demo_dabs.metadata TO `<prd-application-id>`;
GRANT USE SCHEMA ON SCHEMA demo_dabs.landing TO `<qa-application-id>`;
GRANT USE SCHEMA ON SCHEMA demo_dabs.landing TO `<prd-application-id>`;
GRANT READ VOLUME ON VOLUME demo_dabs.landing.files TO `<qa-application-id>`;
GRANT READ VOLUME ON VOLUME demo_dabs.landing.files TO `<prd-application-id>`;

-- qa service principal: write only on the qa schemas
GRANT USE SCHEMA, CREATE TABLE, SELECT, MODIFY ON SCHEMA demo_dabs.sales_qa     TO `<qa-application-id>`;
GRANT USE SCHEMA, CREATE TABLE, SELECT, MODIFY ON SCHEMA demo_dabs.ingestion_qa TO `<qa-application-id>`;

-- prd service principal: write only on the prd schemas
GRANT USE SCHEMA, CREATE TABLE, SELECT, MODIFY ON SCHEMA demo_dabs.sales_prd     TO `<prd-application-id>`;
GRANT USE SCHEMA, CREATE TABLE, SELECT, MODIFY ON SCHEMA demo_dabs.ingestion_prd TO `<prd-application-id>`;
```

| Grant | Why |
| --- | --- |
| `USE CATALOG` on `demo_dabs` | Required to reach anything inside the catalog. |
| Write access on its own environment's schemas | The jobs create and overwrite their tables there. Each service principal can write **only** to its own environment. |
| Read access on `metadata` | The first version of `ingestion` read `ingestion_datasets` at deploy time. No longer needed since the bundle reads `datasets.yml` (section 7.3). |
| `USE SCHEMA` on `landing` and `READ VOLUME` on `landing.files` | The ingestion jobs read the CSV files from the landing volume. |

Neither service principal has access to the `dev` schemas: `dev` belongs to developers.

Both also got permission to use the SQL warehouse (SQL Warehouses → Serverless Starter Warehouse →
Permissions → **Can use**), for the metadata query of the first version of `ingestion`. It was set through
the Permissions API:

```bash
databricks api patch /api/2.0/permissions/warehouses/<warehouse-id> --json '{
  "access_control_list": [
    {"service_principal_name": "<qa-application-id>",  "permission_level": "CAN_USE"},
    {"service_principal_name": "<prd-application-id>", "permission_level": "CAN_USE"}
  ]
}'
```

Note: the `samples` catalog does not support grants
(`Permissions not supported on sample databases/tables`). It is readable by default.

### 6.2 Read access for people

Tables in qa and prd are created by the service principals (through `run_as`), so **the service principal
owns them**. Owning the catalog lets a person grant access, but does not give `SELECT` on tables created by
someone else. The first query on `sales_qa.daily_sales` failed with `INSUFFICIENT_PERMISSIONS`, which is the
intended model: nobody writes to qa or prd except the service principal, and reading is granted explicitly.

```sql
GRANT USE SCHEMA, SELECT ON SCHEMA demo_dabs.sales_qa      TO `<user-or-group>`;
GRANT USE SCHEMA, SELECT ON SCHEMA demo_dabs.sales_prd     TO `<user-or-group>`;
GRANT USE SCHEMA, SELECT ON SCHEMA demo_dabs.ingestion_qa  TO `<user-or-group>`;
GRANT USE SCHEMA, SELECT ON SCHEMA demo_dabs.ingestion_prd TO `<user-or-group>`;
```

`SELECT` on a schema is inherited by every table in it, including tables created later. Read-only access means
an `INSERT` or `DROP` on a prd table still fails. In a real setup these grants go to **groups** (for example
`data-engineers`), and prd may be restricted to a smaller group.

These grants are not declared in `platform.yml` yet: the `grants` of a bundle resource are **authoritative**,
so on every deployment they would remove the grants that were given by hand to the service principals. To
manage them as code, every grant (service principals included) has to be declared there.

## 7. Step 4: Use-case repository (`dabs-use-cases-test`)

One repository with **one bundle per folder**. Each folder has its own `databricks.yml`, its own workflow and
its own owner.

```
dabs-use-cases-test/
├── .github/
│   ├── CODEOWNERS
│   └── workflows/
│       ├── deploy-sales.yml              # generated by the template
│       └── deploy-ingestion.yml          # generated by the template
├── sales/                                # bundle: three chained jobs on the ingested orders
│   ├── databricks.yml
│   ├── requirements-test.txt             # pyspark and pytest, for unit tests only
│   ├── resources/                        # sales.job.yml (trigger), sales_monthly.job.yml, sales_top_customers.job.yml
│   ├── src/                              # main.py, monthly.py, top_customers.py: thin notebooks
│   ├── src/transformations.py            # pure, tested logic
│   └── tests/                            # conftest.py and test_transformations.py
├── ingestion/                            # bundle: jobs generated from a datasets file
│   ├── databricks.yml
│   ├── datasets.yml                      # the team's datasets, one entry each
│   ├── requirements-bundle.txt
│   ├── resources/__init__.py
│   └── src/ingest_dataset.py
└── .gitignore
```

### 7.1 Create the use cases from the template

From the root of the cloned repository, run once per use case. Only the use-case name is asked:

```bash
databricks bundle init https://github.com/cesarpazguzman/dabs-platform-test --template-dir templates/use-case
# Use-case name (lowercase, no spaces): sales

databricks bundle init https://github.com/cesarpazguzman/dabs-platform-test --template-dir templates/use-case
# Use-case name (lowercase, no spaces): ingestion
```

Each run creates the bundle folder and its workflow in `.github/workflows/`, which already calls
`bundle-ci.yml@v1`.

### 7.2 `sales`: three chained jobs on top of the ingested orders

`sales` reads what `ingestion` loads (bronze, `ingestion_<env>.raw_*`) and writes aggregates for consumers
(gold, `sales_<env>.*`). It has three jobs, so it also shows how jobs are triggered and chained:

```
raw_orders updated ──trigger──► sales-main: daily_sales ──┬──► sales-monthly        → monthly_sales
                                                          └──► sales-top-customers  → top_customers
                                                               (in parallel)
```

| Job | File | Reads | Writes |
| --- | --- | --- | --- |
| `sales-main-<target>` | `resources/sales.job.yml` | `ingestion_<env>.raw_orders` | `daily_sales`: orders, revenue, and average, minimum and maximum order value per day |
| `sales-monthly-<target>` | `resources/sales_monthly.job.yml` | `daily_sales` | `monthly_sales`: orders, revenue and average order value per month |
| `sales-top-customers-<target>` | `resources/sales_top_customers.job.yml` | `raw_orders`, `raw_customer` | `top_customers`: the ten customers with the highest revenue |

**Trigger.** `sales-main` has a `table_update` trigger on `raw_orders`: it runs when the ingestion use case
updates the table, waiting 60 seconds after the last change and at most once every 5 minutes. It depends on
the table, not on the job that writes it, so the two bundles (and teams) stay independent.

```yaml
trigger:
  pause_status: ${var.trigger_pause}       # PAUSED by default, UNPAUSED in prd
  table_update:
    table_names: [ "${var.catalog}.${var.source_schema}.raw_orders" ]
    condition: ANY_UPDATED
    wait_after_last_change_seconds: 60
    min_time_between_triggers_seconds: 300
```

Only prd runs by itself: `dev` pauses triggers anyway (`mode: development`), and qa is paused so it does not
fire on every test. In prd the full chain is the `orders` ingestion at 06:00 (its schedule in
`datasets.yml`), then `sales-main`, then the two downstream jobs.

**Chaining.** After its `daily_sales` task, `sales-main` starts the other two jobs with `run_job_task`
tasks that both depend on `daily_sales`, so they run in parallel. The job IDs are references between
resources of the same bundle (`${resources.jobs.sales_monthly.id}`), resolved at deploy time; no ID is
written by hand. Each downstream job can also be run on its own.

**Environments.** Two variables in `databricks.yml` keep every environment reading its own data:
`source_schema` (`ingestion_dev`, `ingestion_qa`, `ingestion_prd`) and `trigger_pause`. The tables read
must exist before the jobs run, so `ingestion` has to run once in an environment before `sales`. Deploying
`sales` does not need them.

**Code.**

- The logic lives in pure functions in `src/transformations.py` (`daily_sales`, `monthly_sales`,
  `top_customers`): they take and return DataFrames, with no tables or widgets, and are unit-tested
  (section 7.5).
- `src/main.py`, `src/monthly.py` and `src/top_customers.py` are thin notebooks: they read the widgets,
  call one function and write one table. They import `transformations` directly, because a notebook's folder
  is on the Python path in Databricks.
- Tables are written with `mode("overwrite")` and `option("overwriteSchema", "true")`. Without the option,
  adding a column fails in qa and prd, where the table already exists with the previous columns.
- Every job has `max_concurrent_runs: 1`, `timeout_seconds: 3600`, failure emails and `tags.owner`, as the
  platform rules require.

The first version had a single job reading `samples.tpch.orders`. It was extended during the rehearsal to
connect it to `ingestion` and to show triggers and chaining.

Test it in your personal dev copy, from `sales/`:

```bash
databricks bundle validate --strict  # Target: dev, Path: /Workspace/Users/<you>/.bundle/sales/dev
databricks bundle plan
databricks bundle deploy
databricks bundle run sales_main     # "[dev <you>] sales-main-dev" ... TERMINATED SUCCESS
```

`raw_orders` and `raw_customer` must exist in `ingestion_dev` first (`databricks bundle run ingest_orders`
and `ingest_customer` from `ingestion/`). In the run, `monthly_sales` and `top_customers` start at the same
second, after `daily_sales`.

```sql
SELECT * FROM demo_dabs.sales_dev.daily_sales ORDER BY order_date LIMIT 10;
SELECT * FROM demo_dabs.sales_dev.monthly_sales ORDER BY month LIMIT 10;
SELECT * FROM demo_dabs.sales_dev.top_customers;
```

To see what CI will check on a PR, run the platform rules locally:

```bash
databricks bundle validate -t qa --output json | python3 <path-to>/dabs-platform-test/ci/check_rules.py
# Platform rules: OK
```

### 7.3 `ingestion`: jobs generated in Python from a datasets file

**What it solves:** with many similar flows, configuration grows out of control if every dataset has its own
job in YAML. Instead, the team lists its datasets in one file, `ingestion/datasets.yml`, one short entry per
dataset, and the bundle generates one job per enabled entry. With five datasets or a thousand, the code is
the same.

**Who owns what:**

| Who | Defines | Where |
| --- | --- | --- |
| Platform | Catalog, schemas per environment, the landing volume `landing.files`, the rules | `platform-bundle/`, `ci/check_rules.py` |
| The team | Its datasets: name, source folder, format, reader options, write mode, schedule | `ingestion/datasets.yml`, owned by the team in CODEOWNERS |
| The bundle code | How an entry becomes a job, and the checks on the file | `ingestion/resources/__init__.py` |

The team never writes volume paths or schema names: an entry names a folder in the landing volume, and the
catalog and schema come from the target. Adding a dataset is a PR in the team's own folder, reviewed by the
team, so the platform team is not involved.

**How it works:** on `validate`, `plan` and `deploy`, the CLI calls `load_resources` in `resources/__init__.py`.
It reads `datasets.yml`, checks it, and returns one job per enabled entry, which is then deployed exactly as
if it had been written in YAML.

`datasets.yml` (the header comment in the file documents every field):

```yaml
alerts:
  on_failure: [data-team@example.com]

datasets:
  - name: customer
    source: customer            # folder in /Volumes/<catalog>/landing/files
  - name: orders
    source: orders
    schedule: "0 0 6 * * ?"     # Quartz cron, Europe/Madrid; paused outside prd
  # ...
```

| Field | Required | Default | Effect |
| --- | --- | --- | --- |
| `owner` (file) | Platform rule 4 | — | `tags.owner` on every job |
| `alerts.on_failure` (file) | Yes | — | Failure emails on every job (platform rule 3) |
| `name` | Yes | — | Job `ingestion-<name>-<target>`, table `raw_<name>` |
| `source` | Yes | — | Folder in the landing volume |
| `format` | No | `csv` | `csv`, `json` or `parquet` |
| `options` | No | `header` and `inferSchema` for csv | Spark reader options |
| `mode` | No | `overwrite` | `overwrite` or `append` |
| `schedule` | No | on demand | Quartz cron; the schedule is active only in prd |
| `enabled` | No | `true` | `false` removes the job and keeps the entry |

**The file is checked** before any job is generated: unknown fields (a typo such as `sorce`), repeated keys
(PyYAML would silently keep the last one; it happened in the rehearsal when two PRs added `owner`), invalid or
duplicated names, a missing `source` or `alerts`, and unknown formats or modes. Any mistake fails
`validate` in the PR with every error listed:

```
Error: Failed to load resources
ValueError: datasets.yml is not valid:
  datasets[1] (nation): unknown field 'sorce'
  datasets[1] (nation): source is required
```

Files of the bundle:

| File | What it does |
| --- | --- |
| `datasets.yml` | The team's list of datasets. |
| `requirements-bundle.txt` | Python packages the CLI needs to run the bundle's code: `databricks-bundles` (same version as the CLI, `1.22.1`) and `PyYAML`. |
| `databricks.yml` | The template's file, plus a `python:` block (below). |
| `resources/__init__.py` | `read_datasets` reads and checks the file; `create_job` is the job template for one dataset; `load_resources` adds one job per enabled entry. |
| `src/ingest_dataset.py` | The single notebook every job uses: reads the dataset from the landing volume with its format and options, and writes `raw_<dataset>` in the dataset's mode. |

```yaml
python:
  venv_path: .venv
  resources:
    - 'resources:load_resources'
```

Every generated job complies with the platform rules: its name is `ingestion-<dataset>-<target>`, and it
gets `email_notifications.on_failure` and `tags.owner` from the file.

Test it in your personal dev copy, from `ingestion/`. The virtual environment is created once:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-bundle.txt

databricks bundle validate
databricks bundle plan              # 5 jobs: ingest_customer, ingest_nation, ingest_orders, ingest_region, ingest_supplier
databricks bundle deploy
databricks bundle run ingest_customer
```

```sql
SELECT COUNT(*) FROM demo_dabs.ingestion_dev.raw_customer;   -- 5000
```

**Adding and removing datasets** (shown live in the demo) is a PR to `qa` that edits `datasets.yml`:

- Add an entry for `part` (its CSV files are already in the landing volume): the PR's plan shows
  `create jobs.ingest_part`.
- Set `enabled: false` on an entry, or delete it: the plan shows `delete jobs.ingest_<name>`.

The change then travels like any other: qa on merge, prd through the promotion and its approval.

**Why a file and not a table.** The first version read the table `demo_dabs.metadata.ingestion_datasets` at
deploy time (created by `platform-setup-demo`, section 5.2). It was replaced during the rehearsal:

| | File in the team's folder | Table |
| --- | --- | --- |
| Add or remove a dataset | PR in the team's folder, reviewed by the team | An `INSERT`, without review |
| Visible in the CI plan | Yes | No: the change does not trigger the CI |
| Reaches prd | Through qa, the promotion and the approval | On the next deployment of any change, even an unrelated hotfix |
| History and rollback | `git log`, `git revert` | Delta time travel, by hand |
| Same commit, same jobs | Yes | No: it depends on the table's content at that moment |
| Who can edit it | People who use Git | Anyone with SQL, or an app or form |

The table is the same for qa and prd, so a dataset added to try something would reach prd with the next
deployment, without going through qa. A table still fits when the people who register datasets do not use
Git, or when the source is another system such as a data catalog; then it should be one table per
environment. The file also removed the SQL warehouse lookup and the `databricks-sdk` dependency.

**Many teams:** each team keeps its own bundle and its own `datasets.yml`, so a thousand pipelines across
twenty teams are about fifty lines per file. The next step is to move the generator (`read_datasets` and
`create_job`) into a library owned by the platform and versioned like the CI (section 12), so teams only
own their file.

The alternative without Python is a single generic job with a `for_each` task over the list of datasets. It
creates fewer objects, but there is no longer one visible job, schedule and alert per dataset.

### 7.4 CODEOWNERS

`.github/CODEOWNERS` assigns owners to paths. Each team owns its use-case folder, but the files that decide
**where and as whom** a bundle is deployed (`databricks.yml`) and the CI workflows belong to the platform team.
When several lines match a file, the last one wins.

```
/sales/                     @cesarpazguzman
/ingestion/                 @cesarpazguzman
/sales/databricks.yml       @cesarpazguzman
/ingestion/databricks.yml   @cesarpazguzman
/.github/                   @cesarpazguzman
```

The repositories belong to a personal GitHub account, so the owners are users. With an organization they
would be teams: `@<org>/sales-team`, `@<org>/ingestion-team` and `@<org>/platform-team` (for the last three
lines). With the ruleset requiring review from code owners, a PR that only changes `sales/src/` is approved by
the sales team, while a PR that changes `sales/databricks.yml` also needs the platform team.

### 7.5 Unit tests

`validate` and `plan` check the configuration, but never run the code. A renamed column or a wrong
aggregation passes both. Unit tests cover that gap without Databricks:

```
sales/
├── src/transformations.py      # daily_sales(orders): DataFrame in, DataFrame out
├── src/main.py                 # notebook: widgets → daily_sales(...) → table
├── tests/conftest.py           # local Spark session (local[1]) and src/ on the Python path
├── tests/test_transformations.py
└── requirements-test.txt       # pyspark==4.0.1, pytest==8.4.2
```

The tests build DataFrames with a few made-up rows and check: for `daily_sales`, one row per day, the
aggregated values (count, sum, average, minimum, maximum) and the column order; for `monthly_sales`, that days
roll up into their month; for `top_customers`, the ranking by revenue and the limit. They need no workspace,
credentials or compute, and run in seconds.

The CI step only runs when the bundle has a `tests/` folder, so `ingestion` is not affected. It installs Java
17 (Spark needs it), creates a separate virtual environment from `requirements-test.txt` and runs `pytest`.
The CI already runs per bundle, so only the tests of the bundle that changed are run; inside a bundle, all of
its tests are run, because a change in one function can break another one's test.

The same pattern applies to every kind of code:

| Code | What is unit-tested |
| --- | --- |
| Job notebooks, like `sales` | The transformation functions |
| Lakeflow Declarative Pipelines (DLT) | The same: the `@dlt.table` function only calls a pure transformation, which is what is tested. DLT *expectations* are data-quality checks at run time; they complement tests, they do not replace them |
| Python-generated resources, like `ingestion/resources` | That `create_job(ds)` returns a job with the right name, notification and parameters, without reading the real table |

To run the tests locally, Java is needed:

```bash
brew install openjdk@17
export JAVA_HOME=$(brew --prefix openjdk@17)
cd sales && python3.13 -m venv .venv-test && .venv-test/bin/pip install -r requirements-test.txt && .venv-test/bin/pytest -q tests
```

## 8. Working with the repositories

### 8.1 A normal change

```bash
git switch qa && git pull
git switch -c feature/my-change
# edit, then test in dev (section 2.3)
git commit -am "<what and why>"
git push -u origin feature/my-change
gh pr create --fill --base qa
gh pr checks --watch                   # ci / plan: validate, rules, plan, tests
gh pr merge --squash --delete-branch   # after review; deploys qa automatically
```

Then check qa, and run the job there if needed. A deployment creates or updates the job but **does not run
it**:

```bash
databricks bundle run sales_main -t qa      # runs as sp-dabs-qa, because of run_as
```

### 8.2 Promote qa to prd

```bash
gh pr create --base main --head qa --title "Promote qa to prd" --body "<what is being promoted>"
gh pr checks qa --watch                 # branch policy, validate and rules against prd, tests
gh pr merge qa --merge                  # merge commit; never --squash, never --delete-branch
```

The merge starts `deploy-prd`, which waits for approval: Actions → the run → **Review deployments** →
`prd` → **Approve and deploy**. The job then checks that the run is not stale, prints the prd plan and deploys.

### 8.3 Urgent fix

```bash
git switch main && git pull
git switch -c hotfix/<what>
# fix, test in dev
gh pr create --fill --base main         # allowed: the branch starts with hotfix/
# merge and approve prd as in 8.2
```

Then bring the fix back into `qa`. Until this is done, the next promotion PR fails in the back-merge check.

```bash
git fetch origin
git switch -c chore/back-merge-<what> origin/qa
git merge --no-edit origin/main         # resolve conflicts here, if any
git log --oneline --graph -6            # a merge commit with two parents: qa and the hotfix
git push -u origin chore/back-merge-<what>
gh pr create --base qa --title "Merge main back into qa" --body "Brings the hotfix from main into qa."
sleep 20; gh pr checks --watch
gh pr merge --merge --delete-branch     # merge commit, never squash; deploys qa with the fix
```

Then the promotion PR (`qa` → `main`) re-runs its checks by itself, and the back-merge check prints
"qa contains everything on main":

```bash
git switch qa && git pull
sleep 20; gh pr checks qa --watch
gh pr merge qa --merge                  # never --delete-branch
gh api repos/<owner>/<repo>/compare/main...qa --jq '"qa ahead \(.ahead_by), behind \(.behind_by)"'
# after approving prd: "ahead 0"; "behind" only counts merge commits, which change no files
```

- The back-merge goes through a branch taken from `qa`, not a PR straight from `main`: `qa` requires PRs to
  be up to date, and `main` does not contain the latest `qa`.
- It must be a **merge commit**. A squash copies the changes but does not record that `main` is now part of
  `qa`, so the back-merge check keeps failing. In the web UI, check that the button says "Create a merge
  commit": it remembers the last method used, which is usually the squash of a feature.
- If a back-merge was squashed by mistake (the `qa` commit has a single parent), repeat it with a merge
  commit. The merge changes no files, it only records the ancestry. Because no file under the bundle folder
  changes, the CI does not run and `ci / plan` stays "Expected — Waiting for status to be reported", so it is
  merged with the admin bypass:

  ```bash
  git fetch origin
  git switch -c chore/back-merge-<what>-2 origin/qa
  git merge --no-edit origin/main
  git log --oneline --graph -4          # a merge commit with two parents
  git diff origin/qa --stat             # empty: no file changes
  git push -u origin chore/back-merge-<what>-2
  gh pr create --base qa --title "Merge main back into qa (record the hotfix ancestry)" \
    --body "The previous back-merge was squashed, so qa did not record that it contains main. No file changes."
  gh pr merge --merge --admin --delete-branch
  ```

### 8.4 What `plan` shows, and what it does not

- **Configuration changes** (YAML, or Python-generated resources) appear in the plan as add, change or delete.
- **Code changes** (notebooks, `.py` files) do not: the plan says `unchanged`, because the job still points to
  the same file. The new code is in the PR diff and is uploaded by `deploy`, which syncs the bundle folder.

## 9. Rehearsal log

What was run end to end, what was found, and what was changed as a result.

| Scenario | Result | Finding and fix |
| --- | --- | --- |
| First PR (`sales` and `ingestion`) and merge | Checks green; qa jobs created by `sp-dabs-qa`, prd jobs by `sp-dabs-prd` | prd deployed **without approval**: the environment's reviewers had not been saved. Fixed in Settings and verified with `gh api` (section 5.10). |
| Typo in a job field (`notebok_task`) | `validate` only warned and exited 0; `plan` showed `update jobs.sales_main` | CI now runs `validate --strict`, which fails. |
| New column in `sales` | Deployed to qa | Without `overwriteSchema`, Delta rejects overwriting a table with a different schema. Added to the notebook. |
| Change in a notebook only | `plan` showed `unchanged` | Expected: plan compares resources, not file contents (section 8.4). |
| Querying qa and prd tables | `INSUFFICIENT_PERMISSIONS` | Expected: the service principals own those tables. Read grants added (section 6.2). |
| Unit tests in CI | `3 passed` in the PR | — |
| Two merges, approving the older prd run (trunk-based) | The older run deployed | Two bugs in the stale check: `git log -- <path>` skipped merge commits, and `actions/checkout` points `origin/main` at the run's own commit. The check now fetches the real tip of the branch and compares **content** with `git diff`. Verified by simulating the runner's checkout. |
| Re-running a failed run after moving `v1` | Still used the old workflow | Expected GitHub behaviour (section 5.9). A new run is needed. |
| `concurrency` with a run waiting for approval | The newer run queued behind it instead of cancelling it | Runs are approved one at a time, oldest first; the stale check covers the rest (section 5.3). |
| Two merges into `qa` back to back (admin bypass) | When A's `deploy-qa` started, `qa` already contained B: A skipped with the notice "sales has changed on qa… Skipping", and B deployed both changes | "Skip stale deployments" was added to `deploy-qa` before this test, because `concurrency` does not guarantee order. |
| Promotion PR `qa` → `main` | Branch policy passed; validate and rules ran against prd with the qa identity; prd deployed after approval | After the merge, `qa` showed as one commit behind `main`, which would have blocked every following promotion. Fixed by dropping "up to date" on `main` and adding the back-merge check (sections 5.3 and 5.11). The check was verified on a clone: OK after a promotion, fails with an un-merged hotfix, OK after a merge-commit back-merge, fails after a squash back-merge. |

| PR from `feature/*` into `main` | Failed in Branch policy: "Only qa or hotfix/* branches can be merged into main" | — |
| `hotfix/*` into `main` while `qa` had an unpromoted feature | Branch policy passed; prd deployed the fix after approval, without the feature | — |
| Promotion PR right after the hotfix | Failed in the back-merge check, listing `sales/src/main.py` | — |
| Back-merge merged with **squash** | The promotion PR kept failing in the back-merge check | Expected (squash records no ancestry), but easy to do by mistake from the web UI. Repeated with a merge commit, which changed no files, so the CI did not run and it was merged with the admin bypass (section 8.3). |
| Promotion PR after the merge-commit back-merge | "qa contains everything on main"; prd deployed the feature after approval | — |

Still to rehearse: the governance PRs (a failing rule, a sensitive file, a new platform rule) and adding and
removing ingestion datasets.

## 10. Clean-up

| What | How |
| --- | --- |
| Initial service principal `sp-dabs-demo` | Its grants were revoked (catalog, `metadata`, `landing`, the qa and prd schemas, the landing volume), its home folder (only template test leftovers) was deleted, and then the service principal itself. Its `CAN_USE` on the warehouse disappeared with it. It owned no jobs. |
| Repository secret `DATABRICKS_WAREHOUSE_ID` | Deleted; the warehouse is found by name. |

```bash
databricks grants update schema demo_dabs.sales_qa --json '{"changes":[{"principal":"<old-application-id>","remove":["CREATE_TABLE","MODIFY","SELECT","USE_SCHEMA"]}]}'
# ... same for the other objects ...
databricks workspace delete /Workspace/Users/<old-application-id> --recursive
databricks service-principals delete <old-service-principal-id>
gh secret delete DATABRICKS_WAREHOUSE_ID -R cesarpazguzman/dabs-use-cases-test
```

## 11. Design decisions

| Decision | Reason |
| --- | --- |
| Two repositories: platform and use cases | Separates what the platform team owns (CI, rules, template, shared objects) from what each team owns (its bundle and code). |
| One bundle per folder in the use-case repository | Each use case has its own `databricks.yml`, workflow and owner, while living in a single repository. Bundles are the unit of isolation: changes in different bundles never block each other. |
| One branch per environment (`qa`, `main`) | A hotfix reaches prd without carrying unfinished work from qa (section 2.2). |
| Only `qa` and `hotfix/*` into `main` | Everything reaches prd either through qa or as an explicit hotfix. |
| `dev` per developer (`mode: development`), with shared dev data | Developers never overwrite each other's jobs; dev data is a shared sandbox. |
| `qa` and `prd` in `mode: production`, owned by a service principal | One fixed copy per environment, deployed and run only by CI. |
| One service principal per environment | Leaked qa credentials cannot touch prd; each identity can write only to its own environment. |
| prd deployment gated by a GitHub environment approval | Promotion to production is an explicit, recorded decision. |
| Stale-deployment checks and `concurrency` | An older state can never overwrite a newer one, in qa or in prd. |
| `validate --strict` and unit tests in CI | Configuration warnings and logic errors stop the PR, not the deployment. |
| `dev`, `qa` and `prd` as schemas, not workspaces | Free Edition has only one workspace. In a real setup, prd would be a separate workspace. |
| Ingestion datasets in a file in each team's folder, not in a table | Every change is a reviewed PR, shows in the plan and reaches prd through qa and the approval (section 7.3). |
| Service principals and the warehouse found by name with variable lookups | No IDs hard-coded, no `.env` files and no extra exports or secrets; the same configuration works for every developer and in CI. |
| CI versioned by tag (`@v1`) | Platform changes are released on purpose, not on every commit to `main`. |
| CODEOWNERS with users instead of teams | The repositories belong to a personal GitHub account; teams require an organization. |
| All repository content in English | Code, comments, messages, commit messages and PRs are written in English. |

## 12. Known issues and next steps

### Platform hardening

1. **Pin the Databricks CLI version** in `bundle-ci.yml`. Today `databricks/setup-cli@main` installs the latest
   CLI every day, while `ingestion` pins `databricks-bundles==1.22.1` to match the CLI; a new CLI release can
   break that match. Upgrading the CLI then becomes a platform release.
2. **Immutable versions plus a moving tag:** `v1.0.0`, `v1.1.0`… with `v1` pointing at the latest `1.x`.
   A bad release is rolled back by pointing `v1` at the previous version.
3. **Breaking changes go to `v2`.** `v1` keeps working and each use case migrates with a PR that changes
   `@v1` to `@v2` (Dependabot can open those PRs).
4. **New rules warn before they block:** a rule first prints a warning with a date, and a later release turns
   it into an error.
5. **Protect the release tags** in this repository with a tag ruleset on `v*` (restrict updates and
   deletions, bypass only for the platform team).
6. **Restrict who can create `hotfix/*` branches** with a ruleset on `refs/heads/hotfix/*` (restrict
   creations, bypass only for the people on call).
7. **A branch-policy workflow without path filters**, so that PRs that change no bundle also get a clear
   message instead of a missing check.
8. **Automate the back-merge** after a hotfix: open the `main` → `qa` PR from CI.

### Testing

9. **Unit tests in the template**, so every new use case is born with `tests/` and `conftest.py`.
10. **Smoke test in qa:** run the main job after `deploy-qa` (`bundle run`) and fail if it fails.
11. **Integration test in the PR:** deploy to a temporary target with its own schema, run, then `bundle destroy`.
    Complete, but costly in time and compute (and limited by Free Edition's 5 concurrent tasks).

### Data and security

12. **Grants as code** in the platform bundle, declaring the service principals' grants too (section 6.2).
13. **Read-only identity for `plan`:** a service principal that can validate and plan but not deploy, so the qa
    secrets can move into the `qa` environment and only the `qa` branch can use the identity that deploys.
14. **Ingestion generator as a platform library:** move `read_datasets` and `create_job` into a package in this
    repository, installed by tag from `requirements-bundle.txt`, so each team only owns its `datasets.yml`
    (section 7.3). Then retire the table `metadata.ingestion_datasets`, its grants and the warehouse `CAN_USE`.
15. **prd in its own workspace** outside Free Edition.

### Demo

16. Rehearse the remaining scenarios listed at the end of section 9.
