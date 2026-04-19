files = ["lifecycle.py", "pipeline/tasks.py"]
for path in files:
    with open(path, "r") as f:
        data = f.read()
    data = data.replace("backend.database.persistence", "database.persistence")
    data = data.replace("backend.pipeline.tasks", "pipeline.tasks")
    with open(path, "w") as f:
        f.write(data)
