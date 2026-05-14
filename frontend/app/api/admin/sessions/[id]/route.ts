import { NextRequest, NextResponse } from "next/server";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";
const ADMIN_API_TOKEN = process.env.ADMIN_API_TOKEN ?? "";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const upstream = await fetch(
    `${API_URL}/admin/sessions/${encodeURIComponent(id)}`,
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
