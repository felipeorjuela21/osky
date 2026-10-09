import sys
from pathlib import Path
import pandas as pd
from backend.app.core.db import make_engine

def main():
    if len(sys.argv) != 3:
        print("Usage: python -m backend.scripts.import_csv <csv_or_xlsx_path> <table_name>")
        raise SystemExit(1)

    path = Path(sys.argv[1])
    table_name = sys.argv[2]

    if not path.exists():
        raise FileNotFoundError(path)

    if path.suffix.lower() in {".xlsx", ".xls"}:
        df = pd.read_excel(path, dtype=str)
    else:
        df = pd.read_csv(path, dtype=str)

    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    for column in df.columns:
        if column.endswith("_date") or column == "date":
            df[column] = pd.to_datetime(df[column]).dt.date
        elif column in {"amount"}:
            df[column] = pd.to_numeric(df[column])

    engine = make_engine()
    df.to_sql(table_name, engine, if_exists="replace", index=False)
    print(f"Imported {len(df)} rows into {table_name}")
    print("Remember: only datasets/fields declared in backend/app/core/data_dictionary.py can be queried.")

if __name__ == "__main__":
    main()
