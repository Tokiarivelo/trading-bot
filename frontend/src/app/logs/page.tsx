import { ActivityLogList } from "@/features/logs/ActivityLogList";
import { MenuButton } from "@/shared/ui/NavigationDrawer";

export const metadata = { title: "Activity log — AI Trading Bot" };

export default function ActivityLogPage() {
  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center gap-3 border-b border-line px-4 py-2">
        <MenuButton />
        <h1 className="text-base font-bold">Activity log</h1>
      </header>
      <main className="min-h-0 flex-1 overflow-y-auto">
        <ActivityLogList />
      </main>
    </div>
  );
}
