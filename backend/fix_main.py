with open("backend/main.py", "r") as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if line.startswith("        try:") and len(new_lines) > 0 and new_lines[-1].startswith("async def"):
        new_lines.append("    try:\n")
    else:
        new_lines.append(line)

with open("backend/main.py", "w") as f:
    f.writelines(new_lines)
