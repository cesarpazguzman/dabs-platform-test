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
| Reusable CI workflow (validate, rules, plan, deploy) | `.github/workflows/bundle-ci.yml` in this repo | Platform team |
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
            │ GitHub Actions deploys with a service principal
            ▼
Databricks Free Edition workspace · catalog demo_dabs
├── metadata.ingestion_datasets     (table that drives the ingestion bundle)
├── landing.files                   (volume with sample CSV files)
└── sales_dev · sales_qa · ingestion_dev · ingestion_qa   (one schema per use case and environment)
```

All data comes from the built-in `samples.tpch` dataset. No customer data is used.

## 2. Environment

| Item | Value |
| --- | --- |
| Databricks workspace | Free Edition, `https://dbc-e146da84-2d63.cloud.databricks.com` |
| Databricks CLI | v1.22.1 |
| Catalog | `demo_dabs` |
| SQL warehouse | Starter Warehouse |
| CI identity | Service principal `sp-dabs-demo` |
| GitHub | Personal account `cesarpazguzman`, two public repositories |

Free Edition limitations that shape the design:

- **One workspace only.** `dev` and `qa` are separate *schemas* in the same workspace instead of separate workspaces.
- **Serverless compute only.** Jobs do not define clusters.
- **At most 5 concurrent job tasks.** Jobs are run one at a time.

## 3. Step 1: Workspace preparation

### 3.1 Authenticate the Databricks CLI

```bash
databricks auth login --host https://dbc-e146da84-2d63.cloud.databricks.com
```

**Why:** the CLI is the tool that validates, plans and deploys bundles. Logging in stores a profile in
`~/.databrickscfg` (OAuth, user-to-machine). Local deployments run **as the developer**, using this profile.
No credentials are stored in any repository or `.env` file.

### 3.2 Create the catalog

Run in the SQL editor:

```sql
CREATE CATALOG IF NOT EXISTS demo_dabs;
```

**Why:** Unity Catalog organises data as `catalog.schema.table`. The catalog is the top-level container for
everything in the demo. It is created once, by hand, because it is the platform's responsibility and
sits above every bundle. Schemas inside it are created as code (see step 2).

### 3.3 Get the SQL warehouse ID

SQL Warehouses → Starter Warehouse → Connection details → the last segment of the HTTP path.

**Why:** the `ingestion` bundle generates its jobs in Python by reading a metadata table at deploy time.
It runs that query on the SQL warehouse, so it needs the warehouse ID (passed as the
`DATABRICKS_WAREHOUSE_ID` environment variable).

### 3.4 Create the CI identity (service principal)

1. Settings → Identity and access → Service principals → **Add service principal**, named `sp-dabs-demo`.
   Entitlements: workspace access and Databricks SQL access.
2. In the service principal → Secrets → **Generate secret**, with scope **`all-apis`** and a short lifetime.

**Why:** GitHub Actions must not deploy with a person's credentials. A service principal is a technical
identity that authenticates with OAuth machine-to-machine (a client ID plus a secret).

- The **client ID** is the service principal's *application ID*.
- The scope is `all-apis` because a deployment touches many APIs: workspace files, jobs, Unity Catalog
  and SQL statement execution. A narrower scope makes `bundle deploy` fail. The scope does **not** grant
  access to data; data access is controlled only by the Unity Catalog grants in step 3.
- The secret is shown only once. It was stored directly as a GitHub secret (section 4.6) and is not
  written anywhere else.

The service principal can be checked from the CLI:

```bash
databricks service-principals list
```

## 4. Step 2: Platform repository (`dabs-platform-test`)

### 4.1 Repository layout

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

### 4.2 Platform bundle (`platform-bundle/`)

| File | What it does | Why |
| --- | --- | --- |
| `databricks.yml` | Declares the bundle `platform`, the `catalog` variable (default `demo_dabs`) and a single target `demo` pointing at the workspace. | Entry point of the bundle. The catalog is a variable so the same code could target another catalog. |
| `resources/platform.yml` | Declares six schemas (`metadata`, `landing`, `sales_dev`, `sales_qa`, `ingestion_dev`, `ingestion_qa`), the managed volume `landing.files` and the job `platform-setup-demo`. | Shared objects are created **as code**, before any use case exists. This answers "who creates the catalog and the schemas": the platform. In a real setup this could be Terraform; a bundle shows it is also possible. |
| `src/setup_demo.py` | Notebook that writes six `samples.tpch` tables as CSV files into the landing volume and creates the table `metadata.ingestion_datasets` with one row per dataset to ingest. | Provides realistic input files and the metadata table for the `ingestion` use case. The `part` dataset is written as CSV but **left out of the metadata table on purpose**, so it can be added live during the demo. |

The platform bundle is deployed by hand and is **not** checked by the platform rules, because creating
schemas is exactly what it is meant to do.

### 4.3 Reusable CI workflow (`.github/workflows/bundle-ci.yml`)

**What it is:** the single place that defines how any bundle is validated and deployed. It declares
`on: workflow_call`, so other repositories call it with
`uses: cesarpazguzman/dabs-platform-test/.github/workflows/bundle-ci.yml@v1`.

**What it does on every run:**

1. Checks out the calling repository (the use-case code) and this repository at tag `v1` (to get the rules).
2. Installs the Databricks CLI.
3. If the bundle has a `requirements-bundle.txt`, creates its Python virtual environment
   (needed by bundles that generate resources in Python).
4. Job `plan`: runs `databricks bundle validate -t qa`, then the platform rules, then `databricks bundle plan -t qa`.
5. Job `deploy-qa`: only when the event is a push to `main` (a merge), runs `databricks bundle deploy -t qa`.

**Why:** use-case repositories contain only a few lines of workflow. How to validate, which rules apply
and how to deploy are owned and versioned by the platform team. Inside a reusable workflow, `github.ref`
refers to the calling repository's branch, which is how it tells a PR from a merge.

**Credentials:** the workflow reads `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET`
and `DATABRICKS_WAREHOUSE_ID` from the **calling** repository's secrets (passed with `secrets: inherit`).

### 4.4 Platform rules (`ci/check_rules.py`)

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

### 4.5 Use-case template (`templates/use-case/`)

**What it is:** the skeleton every use case starts from. `databricks bundle init` asks the questions in
`databricks_template_schema.json` and copies `template/`, replacing the `{{.variable}}` placeholders
(also in file names). Files ending in `.tmpl` are processed; the rest are copied as they are.

| Question | Default | Used for |
| --- | --- | --- |
| `use_case` | (none; lowercase, digits and `_`) | Bundle name, folder name, job name, schema names |
| `github_org` | `cesarpazguzman` | The `uses:` line that calls the reusable workflow |
| `catalog` | `demo_dabs` | Default value of the `catalog` variable |

| Generated file | Content |
| --- | --- |
| `<use_case>/databricks.yml` | Variables `catalog` and `schema`; targets `dev` (default, schema `<use_case>_dev`) and `qa` (schema `<use_case>_qa`). `{{workspace_host}}` is filled in with the workspace the CLI is logged into. |
| `<use_case>/resources/<use_case>.job.yml` | A sample job `<use_case>-main-<target>` that already complies with the rules. `{{user_name}}` (the person running `bundle init`) receives the failure emails. |
| `<use_case>/src/main.py` | A sample notebook that writes a small table into the environment schema. |
| `.github/workflows/deploy-<use_case>.yml` | The use-case workflow. It only runs when files in its own folder change and delegates everything to `bundle-ci.yml@v1`. |

**Why:** every use case is born with the same structure, the same environments and a job that already
passes the rules. Teams do not copy and paste from each other.

### 4.6 `.gitignore`

Excludes `.databricks/` (local deployment state), `.venv/`, `__pycache__/` and `.env`, so no local state
or credentials are committed.

### 4.7 Deploy and run the platform bundle

From `platform-bundle/`:

```bash
databricks bundle validate        # checks the configuration; "Validation OK!"
databricks bundle plan            # shows what will change: 8 to add (6 schemas, 1 volume, 1 job)
databricks bundle deploy          # creates the schemas, the volume and the job
databricks bundle run setup_demo  # runs the job: TERMINATED SUCCESS
```

Verification:

```bash
databricks schemas list demo_dabs
# default, information_schema, ingestion_dev, ingestion_qa, landing, metadata, sales_dev, sales_qa

databricks fs ls dbfs:/Volumes/demo_dabs/landing/files/
# customer, nation, orders, part, region, supplier
```

```sql
SELECT * FROM demo_dabs.metadata.ingestion_datasets ORDER BY dataset;
-- 5 rows: customer, nation, orders, region, supplier (all active; part is left out on purpose)
```

### 4.8 Test the template

The template was tested locally by generating a throwaway use case called `marketing` outside the
repository, and running the platform rules on it:

```bash
databricks bundle init templates/use-case --config-file <answers.json> --output-dir <tmp-dir>
cd <tmp-dir>/marketing
databricks bundle validate -t qa --output json | python3 <path-to>/ci/check_rules.py
# Platform rules: OK
```

### 4.9 Publish version `v1`

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

### 4.10 GitHub secrets

Configured in **`dabs-use-cases-test`** → Settings → Secrets and variables → Actions:

| Secret | Value |
| --- | --- |
| `DATABRICKS_HOST` | Workspace URL |
| `DATABRICKS_CLIENT_ID` | Application ID of `sp-dabs-demo` |
| `DATABRICKS_CLIENT_SECRET` | OAuth secret generated in step 3.4 |
| `DATABRICKS_WAREHOUSE_ID` | ID of the Starter Warehouse |

**Why only in the use-case repository:** a reusable workflow runs in the context of the repository that
calls it and receives that repository's secrets through `secrets: inherit`. This repository never deploys
from GitHub (the platform bundle is deployed by hand), and it is public, so the CI can check out the rules
without credentials. Each use-case repository therefore owns its own deployment identity, while the
platform only defines *how* to deploy.

## 5. Step 3: Permissions for the service principal

The service principal deploys and runs the `qa` jobs, so it needs Unity Catalog grants. It is identified by
its application ID. Run in the SQL editor (or through the SQL Statement Execution API):

```sql
GRANT USE CATALOG ON CATALOG demo_dabs TO `<sp-application-id>`;
GRANT USE SCHEMA, CREATE TABLE, SELECT, MODIFY ON SCHEMA demo_dabs.sales_qa     TO `<sp-application-id>`;
GRANT USE SCHEMA, CREATE TABLE, SELECT, MODIFY ON SCHEMA demo_dabs.ingestion_qa TO `<sp-application-id>`;
GRANT USE SCHEMA, SELECT ON SCHEMA demo_dabs.metadata TO `<sp-application-id>`;
GRANT USE SCHEMA ON SCHEMA demo_dabs.landing TO `<sp-application-id>`;
GRANT READ VOLUME ON VOLUME demo_dabs.landing.files TO `<sp-application-id>`;
```

| Grant | Why |
| --- | --- |
| `USE CATALOG` on `demo_dabs` | Required to reach anything inside the catalog. |
| Write access on `sales_qa` and `ingestion_qa` | The `qa` jobs create and overwrite their tables there. |
| Read access on `metadata` | The `ingestion` bundle reads `ingestion_datasets` at deploy time to generate its jobs. |
| `USE SCHEMA` on `landing` and `READ VOLUME` on `landing.files` | The ingestion jobs read the CSV files from the landing volume. |

The service principal gets **no** access to the `dev` schemas: `dev` belongs to developers, and `qa` is
only reached through CI.

It also needs permission to use the SQL warehouse (SQL Warehouses → Starter Warehouse → Permissions →
**Can use**). This was set through the Permissions API:

```bash
databricks api patch /api/2.0/permissions/warehouses/<warehouse-id> --json '{
  "access_control_list": [
    {"service_principal_name": "<sp-application-id>", "permission_level": "CAN_USE"}
  ]
}'
```

Note: the `samples` catalog does not support grants
(`Permissions not supported on sample databases/tables`). It is readable by default.

## 6. Design decisions

| Decision | Reason |
| --- | --- |
| Two repositories: platform and use cases | Separates what the platform team owns (CI, rules, template, shared objects) from what each team owns (its bundle and code). |
| One bundle per folder in the use-case repository | Each use case has its own `databricks.yml`, workflow and owner, while living in a single repository. |
| `dev` and `qa` as schemas, not workspaces | Free Edition has only one workspace. In a real setup each target would point at its own workspace. |
| Local deploys as the developer, CI deploys as a service principal | Developers iterate in `dev` with their own identity; `qa` is only changed by CI, through a reviewed PR. |
| CI versioned by tag (`@v1`) | Platform changes are released on purpose, not on every commit to `main`. |
| CODEOWNERS with users instead of teams | The repositories belong to a personal GitHub account; teams require an organization. |
| All repository content in English | Code, comments, messages, commit messages and PRs are written in English. |

## 7. Next steps

1. **Use-case repository (`dabs-use-cases-test`):** generate `sales/` and `ingestion/` from the template,
   customise them (daily sales aggregation; jobs generated in Python from the metadata table), test them in
   `dev` and add `CODEOWNERS`.
2. **GitHub ruleset on `main`:** require a pull request, review from code owners and passing `ci / plan`
   checks. Because the same account opens and approves PRs, the repository admin is added to the bypass list.
3. **Rehearsal:** one test PR per use case, checking that CI passes and that a merge deploys to `qa`;
   prepare the governance PRs for the demo (a failing rule, a sensitive file, a new platform rule).
