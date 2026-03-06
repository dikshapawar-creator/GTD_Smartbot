import os

files_to_delete = [
    "check_versions.py",
    "debug_settings.py",
    "dump_db.py",
    "inspect_session.py",
    "tmp_check_schema.py",
    "tmp_inspect_data.py",
    "verify_db.py"
]

for file in files_to_delete:
    try:
        if os.path.exists(file):
            os.remove(file)
            print(f"Deleted: {file}")
        else:
            print(f"Skipped (not found): {file}")
    except Exception as e:
        print(f"Error deleting {file}: {e}")

print("Cleanup script finished.")
