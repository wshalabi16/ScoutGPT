import postgres from "postgres";

// Defaults to the read-only role so the app can never write, even if misconfigured.
const connectionString =
  process.env.DATABASE_URL ||
  "postgresql://scout_readonly:readonly@localhost:5432/scoutgpt";

const sql = postgres(connectionString, {
  max: 10,
  idle_timeout: 30,
  connect_timeout: 10,
  connection: { statement_timeout: 5000 },
});

export default sql;
