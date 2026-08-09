import duckdb


class DatabaseCatalog:
    def __init__(self, database_path: str = None):
        """
        Initializes the DatabaseCatalog.
        :param database_path: Path to a DuckDB database file. If None, uses an in-memory database.
        """
        self.database_path = database_path or ":memory:"
        self.con = None

    def _ensure_connection(self):
        if self.con is None:
            try:
                self.con = duckdb.connect(self.database_path)
            except Exception:
                pass

    def get_table_schema(self, table_name: str) -> dict[str, str]:
        """
        Returns column names mapped to DuckDB data types from information_schema
        (e.g. {'LO_QUANTITY': 'INTEGER', 'LO_REVENUE': 'BIGINT', 'LO_SHIPMODE': 'VARCHAR'}).
        """
        self._ensure_connection()
        if self.con:
            try:
                query = """
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE lower(table_name) = lower(?);
                """
                res = self.con.execute(query, [table_name]).fetchall()
                if res:
                    return {
                        col_name.upper(): data_type.upper()
                        for col_name, data_type in res
                    }
            except Exception:
                pass
        return {}

    def get_primary_keys(self, table_name: str) -> list[str]:
        """
        Returns list of primary keys for a table.
        """
        self._ensure_connection()
        pks = []
        if self.con:
            try:
                query = """
                    SELECT column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                      ON tc.constraint_name = kcu.constraint_name
                    WHERE tc.constraint_type = 'PRIMARY KEY' AND lower(tc.table_name) = lower(?);
                """
                res = self.con.execute(query, [table_name]).fetchall()
                pks = [row[0].upper() for row in res]
            except Exception:
                pass
        return pks
