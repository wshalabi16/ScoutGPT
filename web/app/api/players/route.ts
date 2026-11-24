import { connection } from "next/server";
import sql from "@/lib/db";

export async function GET() {
  await connection();

  const rows = await sql`
    SELECT p.player_name, t.team_name, s.matches_played, s.goals, s.shots, s.xg
    FROM player_tournament_stats s
    JOIN players p ON p.player_id = s.player_id
    JOIN teams   t ON t.team_id   = s.team_id
    ORDER BY s.goals DESC, s.xg DESC
    LIMIT 10
  `;
  return Response.json(rows);
}
