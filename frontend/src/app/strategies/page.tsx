import { redirect } from "next/navigation";

// Superseded by the /bots hub (create/edit/delete/apply-to-symbol in one
// place) — this URL is kept only so old links/bookmarks still land somewhere.
export default function StrategiesPage() {
  redirect("/bots");
}
