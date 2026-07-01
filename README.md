# Formula 1 Database Performance Comparison

This project compares relational and graph database implementations of a cleaned Formula 1 dataset.

## PostgreSQL with Docker

Build the Python initialization image, start PostgreSQL, create the schema, and load the processed CSV files:

```bash
docker compose up --build
```

The compose stack contains:

- `postgres`: PostgreSQL 16 database container.
- `db_init`: Python container that creates the SQL schema and imports `data/processed/*.csv`.

Default connection settings:

```text
host: localhost
port: 5432
database: formula1
user: f1_user
password: f1_password
```

The initialization script is idempotent by default because `RESET_DATABASE=true` drops and recreates the Formula 1 tables each time `db_init` runs.
