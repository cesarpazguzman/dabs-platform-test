import json, re, sys

cfg = json.load(sys.stdin)
bundle = cfg["bundle"]["name"]
resources = cfg.get("resources", {})
errors = []

# Rule 1: a use case does not create catalogs or schemas (that is the platform's job)
for kind in ("catalogs", "schemas"):
    if resources.get(kind):
        errors.append(f"'{kind}' are not allowed in a use-case bundle")

for key, job in resources.get("jobs", {}).items():
    # Rule 2: the job name starts with the bundle name and is lowercase
    if not re.fullmatch(rf"{bundle}-[a-z0-9_-]+", job.get("name", "")):
        errors.append(f"Job '{key}': name must start with '{bundle}-' and be lowercase")
    # Rule 3: every job sends an email on failure
    if not job.get("email_notifications", {}).get("on_failure"):
        errors.append(f"Job '{key}': missing email_notifications.on_failure")
    # Rule 4: every job says who owns it, for support and cost reports
    if not job.get("tags", {}).get("owner"):
        errors.append(f"Job '{key}': missing tags.owner")

if errors:
    print("\n".join("ERROR: " + e for e in errors))
    sys.exit(1)
print("Platform rules: OK")
