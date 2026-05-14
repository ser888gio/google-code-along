import { NextRequest, NextResponse } from "next/server";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";
const ADMIN_API_TOKEN = process.env.ADMIN_API_TOKEN ?? "";

export async function GET(req: NextRequest) {
  const days = req.nextUrl.searchParams.get("days") ?? "7";
  const upstream = await fetch(
    `${API_URL}/admin/metrics?days=${encodeURIComponent(days)}`,
    {
      headers: ADMIN_API_TOKEN
        ? { Authorization: `Bearer ${ADMIN_API_TOKEN}` }
        : {},
    },
  );
  const body = await upstream.text();
  return new NextResponse(body, {
    status: upstream.status,
    headers: { "Content-Type": "application/json" },
  });
}
