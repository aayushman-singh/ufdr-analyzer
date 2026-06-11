"use client"
import { Plus, FileText, Clock, MoreHorizontal } from 'lucide-react';
import Link from 'next/link';
import Header from '@/components/header';

// Mock data for the analysis cases
const analysisCases = [
  {
    id: 'case-001',
    title: 'Case #001 - Mobile Extraction',
    date: 'Sep 22, 2025',
    status: 'Completed',
  },
  {
    id: 'case-002',
    title: 'Case #002 - Drive Image',
    date: 'Sep 21, 2025',
    status: 'In Progress',
  },
];

const CaseCard = ({ caseData }: { caseData: typeof analysisCases[0] }) => {
  const isCompleted = caseData.status === 'Completed';
  return (
    <div className="bg-card/60 backdrop-blur-sm border border-border rounded-2xl p-6 shadow-sm hover:shadow-md transition-shadow duration-300">
      <div className="flex justify-between items-start">
        <div className="flex items-start space-x-4">
          <div className="bg-surface-2 rounded-lg p-3 flex-shrink-0">
            <FileText className="w-5 h-5 text-muted-foreground" />
          </div>
          <div>
            <h3 className="font-semibold text-foreground">{caseData.title}</h3>
            <div className="flex items-center space-x-2 text-sm text-muted-foreground mt-1">
              <Clock className="w-4 h-4" />
              <span>{caseData.date}</span>
            </div>
          </div>
        </div>
        <button className="text-muted-foreground hover:text-foreground">
          <MoreHorizontal className="w-5 h-5" />
        </button>
      </div>
      <div className="mt-6">
        <span
          className={`px-3 py-1 text-xs font-medium rounded-full ${
            isCompleted
              ? 'bg-[color-mix(in_oklch,var(--signal)_15%,transparent)] text-signal'
              : 'bg-[color-mix(in_oklch,var(--info)_15%,transparent)] text-info'
          }`}
        >
          {caseData.status}
        </span>
      </div>
    </div>
  );
};

export default function AnalysisDashboardPage() {
  return (
    <div className="theme-light min-h-screen w-full relative bg-background">
      {/* Signal radial background */}
      <div
        className="absolute inset-0 z-0 bg-grid"
        style={{
          backgroundImage: `
            linear-gradient(to right, oklch(0.205 0.012 256 / 0.04) 1px, transparent 1px),
            linear-gradient(to bottom, oklch(0.205 0.012 256 / 0.04) 1px, transparent 1px)
          `,
          backgroundSize: "64px 64px",
        }}
      >
        <div
          className="absolute inset-0"
          style={{
            background:
              "radial-gradient(circle at top center, color-mix(in oklch, var(--signal) 10%, transparent), transparent 70%)",
          }}
        />
      </div>

      <div className="relative z-10">
        <Header />

        <main className="max-w-7xl mx-auto px-8 py-10">

          <div className="flex justify-between items-center mb-16">
            <div>
              <h1 className="text-5xl font-light text-foreground mb-2">Analysis Dashboard</h1>
              <p className="text-lg text-muted-foreground font-light">
                Manage and review your forensic analysis cases.
              </p>
            </div>
            <Link href="/upload" passHref>
              <button className="bg-signal text-signal-foreground font-medium py-3 px-6 rounded-lg flex items-center space-x-2 hover:brightness-110 transition-all shadow-sm">
                <Plus className="w-5 h-5" />
                <span>Upload UFDR File</span>
              </button>
            </Link>
          </div>

          {/* Case Cards Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {analysisCases.map((caseItem) => (
              <CaseCard key={caseItem.id} caseData={caseItem} />
            ))}
          </div>
        </main>
      </div>
    </div>
  );
}
