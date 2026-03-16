from processors.db import init_db

if __name__ == "__main__":
    result = init_db()
    print("Storage initialized.")
    for name, path in result["storage"].items():
        print(f"- {name}: {path}")
    print(f"- db_path: {result['db_path']}")
    print("Database initialized.")
