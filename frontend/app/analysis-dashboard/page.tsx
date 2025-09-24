"use client"
import { Plus, FileText, Clock, MoreHorizontal } from 'lucide-react';
import Link from 'next/link';
import Header from '@/components/header'; // Assuming your pre-built header is here

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
    <div className="bg-white/60 backdrop-blur-sm border border-gray-200/80 rounded-2xl p-6 shadow-sm hover:shadow-md transition-shadow duration-300">
      <div className="flex justify-between items-start">
        <div className="flex items-start space-x-4">
          <div className="bg-gray-100 rounded-lg p-3 flex-shrink-0">
            <FileText className="w-5 h-5 text-gray-600" />
          </div>
          <div>
            <h3 className="font-semibold text-gray-800">{caseData.title}</h3>
            <div className="flex items-center space-x-2 text-sm text-gray-500 mt-1">
              <Clock className="w-4 h-4" />
              <span>{caseData.date}</span>
            </div>
          </div>
        </div>
        <button className="text-gray-400 hover:text-gray-700">
          <MoreHorizontal className="w-5 h-5" />
        </button>
      </div>
      <div className="mt-6">
        <span
          className={`px-3 py-1 text-xs font-medium rounded-full ${
            isCompleted
              ? 'bg-green-100 text-green-700'
              : 'bg-blue-100 text-blue-700'
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
    <div className="min-h-screen w-full relative bg-white">
      {/* Purple Glow Top Background */}
      <div
        className="absolute inset-0 z-0"
        style={{
          background: "#ffffff",
          backgroundImage: `
            radial-gradient(
              circle at top center,
              rgba(173, 109, 244, 0.5),
              transparent 70%
            )
          `,
          filter: "blur(80px)",
          backgroundRepeat: "no-repeat",
        }}
      />

   
      <div className="relative z-10">
        <Header />

        <main className="max-w-7xl mx-auto px-8 py-10">
       
          <div className="flex justify-between items-center mb-16">
            <div>
              <h1 className="text-5xl font-light text-slate-900 mb-2">Analysis Dashboard</h1>
              <p className="text-lg text-slate-600 font-light">
                Manage and review your forensic analysis cases.
              </p>
            </div>
            <Link href="/upload" passHref>
              <button className="bg-slate-900 text-white font-light py-3 px-6 rounded-lg flex items-center space-x-2 hover:bg-slate-700 transition-colors shadow-sm">
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