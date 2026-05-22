"use client";

import { AppHeader } from "@/components/ui/AppHeader";
import { BottomNav } from "@/components/ui/BottomNav";
import { ChatButton } from "@/components/chat/ChatButton";
import { FarmTabBar } from "@/components/ui/FarmTabBar";
import { FlowmeterDashboard } from "@/components/flowmeter/FlowmeterDashboard";

interface Props {
  params: { farmId: string };
}

export default function CaudalimetrosPage({ params }: Props) {
  const { farmId } = params;

  return (
    <div className="min-h-screen bg-paper pb-20 sm:pb-8">
      <AppHeader crumbs={[{ label: "Exploração", href: `/farms/${farmId}` }, { label: "Caudalímetros" }]} />
      <FarmTabBar farmId={farmId} />
      <FlowmeterDashboard farmId={farmId} />
      <BottomNav farmId={farmId} />
      <ChatButton farmId={farmId} />
    </div>
  );
}
