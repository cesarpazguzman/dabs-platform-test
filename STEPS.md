# Setup log: Declarative Automation Bundles demo

This document records what has been set up so far for the Declarative Automation Bundles (DABs) demo:
which objects were created in Databricks and GitHub, which files were added to this repository and why,
and the exact commands that were run.

## 1. Goal and architecture

The demo shows how a **platform team** and several **use-case teams** can work with bundles in a setup
that is close to a real one:

| Piece | Where | Owner |
| --- | --- | --- |
| Shared objects (schemas, landing volume, sample data) | `platform-bundle/` in this repo | Platform team |
| Reusable CI workflow (validate, rules, plan, deploy to qa and prd) | `.github/workflows/bundle-ci.yml` in this repo | Platform team |
| Platform rules checked on every PR | `ci/check_rules.py` in this repo | Platform team |
| Template every new use case starts from | `templates/use-case/` in this repo | Platform team |
| Use-case bundles (`sales`, `ingestion`) | `dabs-use-cases-test` repo, one folder per bundle | Each use-case team |

The platform team defines the template, the CI and the rules **once**. Each use-case repository calls the
CI workflow by version (`@v1`), so a change made here reaches every use case.

```
GitHub: cesarpazguzman
├── dabs-platform-test      (this repo: platform bundle, reusable CI, rules, template)
└── dabs-use-cases-test     (one bundle per folder; calls bundle-ci.yml@v1)
            │
            │ GitHub Actions deploys qa with sp-dabs-qa and prd with sp-dabs-prd
            ▼
Databricks Free Edition workspace · catalog demo_dabs
├── metadata.ingestion_datasets     (table that drives the ingestion bundle)
├── landing.files                   (volume with sample CSV files)
└── <use_case>_dev · <use_case>_qa · <use_case>_prd   (one schema per use case and environment)
```

All data comes from the built-in `samples.tpch` dataset. No customer data is used.

## 2. Environments and branching model

### 2.1 Three environments, one branch

Environments are bundle **targets**, not Git branches. The repositories follow a trunk-based model: a single
long-lived branch (`main`) plus short-lived feature branches.

```
feature/my-change ──PR──► main ──► deploy qa (automatic) ──► deploy prd (manual approval)
        │
        └── from a laptop: databricks bundle deploy  →  dev (personal copy)
```

| Target | Who deploys | Identity | When | Purpose |
| --- | --- | --- | --- | --- |
| `dev` | Each developer, from a laptop | The developer's own user | While working on a feature branch | Try a change without affecting anyone else |
| `qa` | CI only | Service principal `sp-dabs-qa` | On every merge to `main` | Integration: the result of everyone's changes |
| `prd` | CI only | Service principal `sp-dabs-prd` | After qa, once a reviewer approves | Production |

**Why not one branch per environment:** with `dev`, `qa` and `prd` branches, the branches drift apart
(hotfixes that never flow back), every promotion is a merge that can conflict, and what reaches production is
not exactly the commit that was tested in qa. With a single branch, **the same commit** goes through qa and prd;
promotion is controlled by an approval, not by a merge. GitHub → Environments shows which commit is deployed
in each environment.

### 2.2 What `dev` is

`dev` is the developer's working environment. It is where a change is tested before a PR is opened:

```bash
git switch main && git pull                 # start from the latest main
git switch -c feature/my-change
# edit resources/ or src/
databricks bundle plan                      # what will change in MY dev copy
databricks bundle deploy                    # dev is the default target
databricks bundle run sales_main            # does it work?
```

- `dev` uses `mode: development`. Each developer gets **their own copy** of the bundle's jobs and files
  (for example `[dev cesar_paz] sales-main-dev`, under `/Workspace/Users/<user>/.bundle/...`), and schedules
  are paused, so developers never overwrite each other's jobs.
- **Data in dev is shared** (`<use_case>_dev`). If two developers run the same dev job at the same time, the
  last write wins. This is an accepted trade-off for a sandbox.
- A dev copy that falls behind is not a problem: it is disposable and is not the source of truth. Updating the
  branch from `main` and running `bundle deploy` again creates, updates **and deletes** jobs so the copy
  matches the code. `databricks bundle destroy` removes it completely.
- `dev` is the default target as a safety net: a plain `databricks bundle deploy` can never reach qa or prd.
- Who can deploy to each target is not decided by `databricks.yml` but by permissions and CI. In a real
  setup, developers have no write access to qa or prd, so `-t qa` from a laptop fails.

## 3. Environment

| Item | Value |
| --- | --- |
| Databricks workspace | Free Edition, `https://dbc-e146da84-2d63.cloud.databricks.com` |
| Databricks CLI | v1.22.1 |
| Catalog | `demo_dabs` |
| SQL warehouse | Starter Warehouse |
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
# e4867e98b93429dc  Serverless Starter Warehouse
```

**Why:** the `ingestion` bundle generates its jobs in Python by reading a metadata table at deploy time, and
it runs that query on a SQL warehouse. The bundle finds the warehouse **by name** with a variable lookup
(see 7.3), so its ID does not have to be exported, stored in a `.env` file or kept as a GitHub secret.

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
  written anywhere else.

A first service principal, `sp-dabs-demo`, was used while setting up the demo with a single CI identity.
It is replaced by `sp-dabs-qa` and `sp-dabs-prd` and will be removed.

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
└── STEPS.md
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

**Jobs:**

| Job | Runs on | Identity | Steps |
| --- | --- | --- | --- |
| `plan` | Every PR and every merge | `sp-dabs-qa` (repository secrets) | `bundle validate -t qa`, platform rules, `bundle plan -t qa` |
| `deploy-qa` | Merge to `main` only, after `plan` | `sp-dabs-qa` (GitHub environment `qa`) | `bundle deploy -t qa` |
| `deploy-prd` | After `deploy-qa`, **once a reviewer approves** | `sp-dabs-prd` (GitHub environment `prd`) | `bundle deploy -t prd` |

Every job checks out the calling repository and installs the Databricks CLI. If the bundle has a
`requirements-bundle.txt`, it also creates the bundle's Python virtual environment (needed by bundles that
generate resources in Python). The `plan` job also checks out this repository at tag `v1` to get the rules.

**Why:**

- Use-case repositories contain only a few lines of workflow. How to validate, which rules apply and how to
  deploy are owned and versioned by the platform team.
- Inside a reusable workflow, `github.ref` refers to the calling repository's branch, which is how it tells a
  PR from a merge.
- The `plan` job of a PR uses the **qa** identity. A PR has not been approved yet, so it never gets prd
  credentials.
- `deploy-prd` deploys **the same commit** that was just deployed to qa.

**Credentials:** each job reads `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET`
from the **calling** repository (passed with `secrets: inherit`). A job that
declares `environment: prd` receives that environment's secrets, which override the repository secrets with
the same name. That is how `deploy-prd` gets the prd service principal.

### 5.4 Platform rules (`ci/check_rules.py`)

**What it is:** a script that reads the fully resolved bundle configuration from
`databricks bundle validate --output json` and fails the PR if a rule is broken.

| Rule | Check |
| --- | --- |
| 1 | A use-case bundle must not create catalogs or schemas (that is the platform's job). |
| 2 | Every job name starts with the bundle name followed by `-` and is lowercase. |
| 3 | Every job has `email_notifications.on_failure`. |

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
the use-case team's choice. The service principal questions are **not** about who runs `bundle init`: they
are values written into the `qa` and `prd` targets. `dev` never uses a service principal.

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
| `.github/workflows/deploy-<use_case>.yml` | The use-case workflow. It only runs when files in its own folder change and delegates everything to `bundle-ci.yml@v1`. |

**Targets in the generated `databricks.yml`:**

| Target | `mode` | Schema | Root path | Runs as |
| --- | --- | --- | --- | --- |
| `dev` (default) | `development` | `<use_case>_dev` | `/Workspace/Users/<developer>/.bundle/...` | The developer |
| `qa` | `production` | `<use_case>_qa` | `/Workspace/Users/<sp-dabs-qa>/.bundle/...` | `sp-dabs-qa` |
| `prd` | `production` | `<use_case>_prd` | `/Workspace/Users/<sp-dabs-prd>/.bundle/...` | `sp-dabs-prd` |

- `mode: production` enforces a single, fixed copy per environment: the CLI refuses to deploy unless
  `root_path` is set. The root path is the service principal's home folder, which other users cannot write to
  (a `/Workspace/Shared` path would be writable by everyone).
- `run_as` makes the qa and prd jobs run as their service principal, not as whoever deployed them.
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
or credentials are committed.

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

### 5.9 Publish version `v1`

```bash
git add . && git commit -m "Platform v1" && git push origin main
git tag v1 && git push origin v1
```

**Why:** use cases call the workflow and the rules by the tag `v1`, not by `main`. The platform team
decides when a change is released. To publish a backwards-compatible change to every repository, the tag
is moved:

```bash
git tag -f v1 && git push -f origin v1
```

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
| `qa` | None | `main` only | None (uses the repository secrets) |
| `prd` | Yes (self-review allowed in this demo) | `main` only | `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET` of `sp-dabs-prd` |

**Why an environment for qa, even without reviewers:** it restricts qa deployments to `main`, keeps a
deployment history (which commit is in qa, and when) and leaves a place for qa-specific secrets.

**Why the prd secrets live only in the `prd` environment:** GitHub only gives them to a job that declares
`environment: prd`, and only after a reviewer approves it. No PR and no other job can use them.

**Why only in the use-case repository:** a reusable workflow runs in the context of the repository that
calls it and receives that repository's secrets through `secrets: inherit`. This repository never deploys
from GitHub (the platform bundle is deployed by hand), and it is public, so the CI can check out the rules
without credentials. Each use-case repository therefore owns its own deployment identities, while the
platform only defines *how* to deploy.

## 6. Step 3: Permissions for the service principals

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
| Read access on `metadata` | The `ingestion` bundle reads `ingestion_datasets` at deploy time to generate its jobs. |
| `USE SCHEMA` on `landing` and `READ VOLUME` on `landing.files` | The ingestion jobs read the CSV files from the landing volume. |

Neither service principal has access to the `dev` schemas: `dev` belongs to developers.

Both also need permission to use the SQL warehouse (SQL Warehouses → Starter Warehouse → Permissions →
**Can use**). This was set through the Permissions API:

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
├── sales/                                # bundle: daily sales aggregation
│   ├── databricks.yml
│   ├── resources/sales.job.yml
│   └── src/main.py
├── ingestion/                            # bundle: jobs generated from the metadata table
│   ├── databricks.yml
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

### 7.2 `sales`: daily sales aggregation

`sales/src/main.py` is replaced with a real transformation: one row per day with the number of orders and the
revenue, computed from `samples.tpch.orders` and written to `<catalog>.<schema>.daily_sales`.

Test it in your personal dev copy, from `sales/`:

```bash
databricks bundle validate          # Target: dev, Path: /Workspace/Users/<you>/.bundle/sales/dev
databricks bundle plan              # create jobs.sales_main
databricks bundle deploy
databricks bundle run sales_main    # "[dev <you>] sales-main-dev" ... TERMINATED SUCCESS
```

```sql
SELECT * FROM demo_dabs.sales_dev.daily_sales ORDER BY order_date LIMIT 10;
```

To see what CI will check on a PR, run the platform rules locally:

```bash
databricks bundle validate -t qa --output json | python3 <path-to>/dabs-platform-test/ci/check_rules.py
# Platform rules: OK
```

### 7.3 `ingestion`: jobs generated in Python from a metadata table

**What it solves:** with many similar flows, configuration grows out of control if every dataset has its own
YAML file. Instead, this bundle reads the table `demo_dabs.metadata.ingestion_datasets` **at deploy time**
and generates one job per active row. Adding a dataset means inserting a row; nobody edits YAML. With five
rows or a thousand, the code is the same.

**How it works:** on `validate`, `plan` and `deploy`, the CLI calls the function `load_resources` in
`resources/__init__.py`. That function queries the table through the SQL warehouse (with the Databricks SDK)
and returns the jobs, which are then deployed exactly as if they had been written in YAML.

The sample job and notebook created by the template are removed, and these files are added:

| File | What it does |
| --- | --- |
| `requirements-bundle.txt` | Python packages the CLI needs to run the bundle's code: `databricks-bundles` (same version as the CLI, `1.22.1`) and `databricks-sdk`. |
| `databricks.yml` | The template's file, plus a `warehouse_id` variable and a `python:` block (below). |
| `resources/__init__.py` | `read_metadata` queries the table; `create_job` is the job template for one dataset; `load_resources` adds one job per row. |
| `src/ingest_dataset.py` | The single notebook every job uses: reads the dataset's CSV from the landing volume and saves it as `raw_<dataset>`. |

Additions to `databricks.yml`:

```yaml
variables:
  warehouse_id:
    description: SQL warehouse used to read the metadata table at deploy time
    lookup:
      warehouse: Serverless Starter Warehouse

python:
  venv_path: .venv
  resources:
    - 'resources:load_resources'
```

- The warehouse is found **by name**, and the Python code reads the resolved value with
  `bundle.resolve_variable(Variables.warehouse_id)`. No environment variable, `.env` file or GitHub secret is
  needed for it, and it works the same for every developer and in CI.
- The Python code authenticates with `WorkspaceClient()`, which reuses the CLI's authentication: the
  developer's profile locally, the service principal in CI. Nothing has to be exported.

Every generated job complies with the platform rules: its name is `ingestion-<dataset>-<target>` and it has
`email_notifications.on_failure`.

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

**Adding and removing datasets** (this is shown live in the demo):

```sql
-- Add a dataset: the next plan proposes a new job, ingest_part
INSERT INTO demo_dabs.metadata.ingestion_datasets
VALUES ('part', '/Volumes/demo_dabs/landing/files/part', true);

-- Deactivate a dataset: the next plan proposes deleting ingest_region
UPDATE demo_dabs.metadata.ingestion_datasets SET active = false WHERE dataset = 'region';
```

Two caveats:

- A deployment depends on the table's content **at that moment**, so two deployments of the same commit can
  produce different jobs. In a real setup the metadata should also be versioned (for example, loaded into the
  table from a file in Git).
- The alternative without Python is a single generic job with a `for_each` task that reads the table at run
  time. It creates fewer objects, but there is no longer one visible job per dataset.

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
lines). With a branch ruleset that requires review from code owners, a PR that only changes `sales/src/`
is approved by the sales team, while a PR that changes `sales/databricks.yml` also needs the platform team.

## 8. Design decisions

| Decision | Reason |
| --- | --- |
| Two repositories: platform and use cases | Separates what the platform team owns (CI, rules, template, shared objects) from what each team owns (its bundle and code). |
| One bundle per folder in the use-case repository | Each use case has its own `databricks.yml`, workflow and owner, while living in a single repository. |
| Trunk-based branching; environments are targets, not branches | The same commit is promoted from qa to prd; no drift between environment branches. |
| `dev` per developer (`mode: development`), with shared dev data | Developers never overwrite each other's jobs; dev data is a shared sandbox. |
| `qa` and `prd` in `mode: production`, owned by a service principal | One fixed copy per environment, deployed and run only by CI. |
| One service principal per environment | Leaked qa credentials cannot touch prd; each identity can write only to its own environment. |
| prd deployment gated by a GitHub environment approval | Promotion to production is an explicit, recorded decision. |
| `dev`, `qa` and `prd` as schemas, not workspaces | Free Edition has only one workspace. In a real setup, prd would be a separate workspace. |
| Service principals and the warehouse found by name with variable lookups | No IDs hard-coded, no `.env` files and no extra exports or secrets; the same configuration works for every developer and in CI. |
| CI versioned by tag (`@v1`) | Platform changes are released on purpose, not on every commit to `main`. |
| CODEOWNERS with users instead of teams | The repositories belong to a personal GitHub account; teams require an organization. |
| All repository content in English | Code, comments, messages, commit messages and PRs are written in English. |

## 9. Next steps

1. **First PR:** push the use-case repository on a branch and open a PR, to see `plan` in CI; after the
   merge, check the qa deployment and the prd approval.
2. **GitHub ruleset on `main`:** require a pull request, review from code owners and passing `ci / plan`
   checks. Because the same account opens and approves PRs, the repository admin is added to the bypass list.
3. **Rehearsal:** prepare the governance PRs for the demo (a failing rule, a sensitive file, a new
   platform rule).
4. **Clean-up:** remove the initial service principal `sp-dabs-demo` and its grants, and the
   `DATABRICKS_WAREHOUSE_ID` repository secret, which is no longer used.
