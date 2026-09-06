from pathlib import Path

Path("build/report.txt").write_text("report\n", encoding="utf-8")
print("build report created")
