import { useNavigate, useParams } from "react-router-dom";
import { KeyRound, ScrollText, ShieldCheck, SlidersHorizontal, UserRound, Users } from "lucide-react";
import { PageHeader } from "@/components/ui/misc";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { GeneralSettings } from "@/components/settings/GeneralSettings";
import { UsersPanel } from "@/components/settings/UsersPanel";
import { TokensPanel } from "@/components/settings/TokensPanel";
import { AuditLog } from "@/components/settings/AuditLog";
import { PosturePanel } from "@/components/settings/PosturePanel";
import { ProfilePanel } from "@/components/settings/ProfilePanel";

const TABS = [
  { id: "general", label: "General", icon: SlidersHorizontal },
  { id: "users", label: "Users", icon: Users },
  { id: "tokens", label: "API tokens", icon: KeyRound },
  { id: "audit", label: "Audit", icon: ScrollText },
  { id: "posture", label: "Posture", icon: ShieldCheck },
  { id: "profile", label: "Profile", icon: UserRound },
] as const;

type TabId = (typeof TABS)[number]["id"];

export function SettingsPage() {
  const { tab } = useParams<{ tab?: string }>();
  const navigate = useNavigate();
  const active: TabId = TABS.some((item) => item.id === tab) ? (tab as TabId) : "general";

  return (
    <div>
      <PageHeader title="Settings" description="Platform configuration, accounts, API tokens, audit evidence and your own profile." />
      <Tabs value={active} onValueChange={(value) => navigate(`/settings/${value}`)}>
        <TabsList className="-mx-1 overflow-x-auto px-1">
          {TABS.map((item) => (
            <TabsTrigger key={item.id} value={item.id} data-testid={`settings-tab-${item.id}`}>
              <item.icon /> {item.label}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="general">
          <GeneralSettings />
        </TabsContent>
        <TabsContent value="users">
          <UsersPanel />
        </TabsContent>
        <TabsContent value="tokens">
          <TokensPanel />
        </TabsContent>
        <TabsContent value="audit">
          <AuditLog />
        </TabsContent>
        <TabsContent value="posture">
          <PosturePanel />
        </TabsContent>
        <TabsContent value="profile">
          <ProfilePanel />
        </TabsContent>
      </Tabs>
    </div>
  );
}
