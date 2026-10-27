# Databricks notebook source
# Demo only: writes sample CSV files into the landing volume, as a source system would
dbutils.widgets.text("catalog", "demo_dabs")
catalog = dbutils.widgets.get("catalog")
landing = f"/Volumes/{catalog}/landing/files"

for t in ["customer", "orders", "nation", "region", "supplier", "part"]:
    (spark.table(f"samples.tpch.{t}").limit(5000)
        .write.mode("overwrite").option("header", True)
        .csv(f"{landing}/{t}"))
