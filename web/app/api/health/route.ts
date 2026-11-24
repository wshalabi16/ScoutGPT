import { connection } from "next/server";
import sql from "@/lib/db";

export async function GET() {
  await connection();

  try {
    const [info] = await sql`
      SELECT
        current_user AS db_user,
        (SELECT extversion FROM pg_extension WHERE extname = 'vector') AS pgvector_version,
        (SELECT COUNT(*)::int FROM matches) AS matches,
        (SELECT COUNT(*)::int FROM events)  AS events,
        (SELECT COUNT(*)::int FROM players) AS players
    `;
    return Response.json({ status: "ok", ...info });
  } catch (err) {
    return Response.json(
      { status: "error", message: (err as Error).message },
      { status: 503 },
    );
  }
}
