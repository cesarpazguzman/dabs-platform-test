# Databricks notebook source
dbutils.widgets.text("catalog", "demo_dabs")
catalog = dbutils.widgets.get("catalog")
landing = f"/Volumes/{catalog}/landing/files"

# 1) Sample CSV files in the landing zone (volume)
for t in ["customer", "orders", "nation", "region", "supplier", "part"]:
    (spark.table(f"samples.tpch.{t}").limit(5000)
        .write.mode("overwrite").option("header", True)
        .csv(f"{landing}/{t}"))

# 2) Metadata table: one row per dataset to ingest
active = ["customer", "orders", "nation", "region", "supplier"]
rows = [(t, f"{landing}/{t}", True) for t in active]
(spark.createDataFrame(rows, "dataset string, source_path string, active boolean")
    .write.mode("overwrite").saveAsTable(f"{catalog}.metadata.ingestion_datasets"))
