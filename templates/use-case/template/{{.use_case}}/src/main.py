# Databricks notebook source
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
target = f'{dbutils.widgets.get("catalog")}.{dbutils.widgets.get("schema")}.example'
spark.range(10).write.mode("overwrite").saveAsTable(target)
