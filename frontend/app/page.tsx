import Header from "@/components/header"
import { WobbleCard } from "@/components/ui/wobble-card"
import { ArrowRight, FileText, Search, BarChart2, GitFork, Shield, Zap, Eye, Database } from "lucide-react"
import Link from "next/link"

export default function Home() {
  return (
    <div className="min-h-screen w-full bg-white relative overflow-hidden">
      {/* Background with Purple Gradient Grid */}
      <div
        className="fixed inset-0 z-0"
        style={{
          backgroundImage: `
            linear-gradient(to right, #f0f0f0 1px, transparent 1px),
            linear-gradient(to bottom, #f0f0f0 1px, transparent 1px),
            radial-gradient(circle 800px at 0% 200px, #d5c5ff, transparent)
          `,
          backgroundSize: "96px 64px, 96px 64px, 100% 100%",
        }}
      />

    <Header/>

      {/* Main Content - Hero Section */}
      <main className="relative z-10 flex-grow flex flex-col items-center justify-center text-center px-4 py-16">
        {/* Badge */}
        <div className="inline-flex items-center rounded-full border border-gray-200 bg-gray-50 text-gray-700 px-4 py-1 text-sm font-light mb-6">
          Accelerate Investigations
        </div>

        {/* Headlines */}
        <h2 className="text-5xl md:text-6xl font-light text-slate-900 tracking-tight">AI-Powered Insights</h2>
        <h1 className="text-5xl md:text-6xl font-normal text-slate-900 tracking-tight mb-6">from UFDR Files</h1>

        {/* Sub-description */}
        <p className="max-w-xl text-lg text-slate-600 font-light mb-10">
          Transform raw forensic data into actionable intelligence. Our assistant empowers investigators with natural
          language queries and visual analysis.
        </p>

        {/* Call to Action Buttons */}
        <div className="flex flex-col sm:flex-row gap-4 mb-16">
        <Link href="/upload">
  <button className="bg-slate-900 text-white font-light py-3 px-6 rounded-lg hover:bg-slate-700 transition-colors flex items-center justify-center gap-2 shadow-sm">
    Start Analyzing <ArrowRight size={18} />
  </button>
</Link>
          <button className="bg-white text-slate-700 font-light py-3 px-6 rounded-lg border border-gray-300 hover:bg-gray-50 transition-colors flex items-center justify-center gap-2 shadow-sm">
            Learn More
          </button>
        </div>

        {/* Key Features Section */}
       <div className="max-w-7xl py-16 px-14 mx-auto w-full">
      <h2 className="text-3xl font-light text-slate-900 mb-2">Key Features</h2>
      <p className="text-slate-600 font-light mb-8">
        Transform your data background with any file formats.
      </p>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Large Feature */}
        <WobbleCard
          containerClassName="col-span-1 lg:col-span-2 h-full bg-purple-800 min-h-[400px]"
        >
          <div className="max-w-md">
            <h3 className="text-left text-base md:text-xl lg:text-3xl font-semibold text-white">
              FileText – Organize and Analyze
            </h3>
            <p className="mt-4 text-left text-base text-neutral-200">
             Upload UFDR files or forensic documents and let AI handle
                  extraction and organization instantly. Our advanced parsing
                  engine supports XML, HTML, SQLite, JSON, and more, creating a
                  structured database for efficient analysis.
            </p>
          </div>
          <img
            src="/query.png" // your feature image
            width={500}
            height={500}
            alt="FileText Feature"
            className="absolute -right-1 lg:-right-[30%] -bottom-55 object-contain rounded-2xl"
          />
        </WobbleCard>

        {/* Small Feature */}
        <WobbleCard containerClassName="col-span-1 min-h-[200px] bg-blue-700">
          <h3 className="text-left text-base md:text-xl lg:text-2xl font-semibold text-white">
            Powerful Search
          </h3>
          <p className="mt-4 text-left text-base text-neutral-200">
               Natural language search across all your data, from chats to call
                logs, leveraging AI for precise and contextual results.
          </p>
        </WobbleCard>

        {/* Another Large Feature */}
        <WobbleCard
          containerClassName="col-span-1 lg:col-span-3 bg-slate-900 min-h-[400px]"
        >
          <div className="max-w-lg">
            <h3 className="text-left text-base md:text-xl lg:text-3xl font-semibold text-white">
              Advanced Analytics & Reporting
            </h3>
            <p className="mt-4 text-left text-base text-neutral-200">
              Get interactive timelines, visual link analysis, and automated
                  reports out of the box. Identify key entities, relationships,
                  and patterns effortlessly to build stronger cases.
            </p>
          </div>
          <img
            src="/query.png" // your feature image
            width={500}
            height={500}
            alt="Analytics Feature"
            className="absolute -right-10 -bottom-50 object-contain rounded-2xl"
          />
        </WobbleCard>
      </div>
    </div>
      </main>

      {/* Enhanced Demo Section */}
      <section id="demo" className="relative z-10 w-full py-16 px-4">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-12">
            <h3 className="text-3xl font-light text-slate-900 mb-4">See It In Action</h3>
            <p className="text-lg text-slate-600 font-light">
              Experience how natural language queries transform complex forensic data into clear insights
            </p>
          </div>

          <div className="grid md:grid-cols-2 gap-8">
            {/* Query Examples */}
            <div className="bg-white/80 backdrop-blur-sm rounded-2xl p-8 border border-gray-200">
              <h4 className="text-xl font-medium text-slate-900 mb-6">Natural Language Queries</h4>
              <div className="space-y-4">
                <div className="bg-slate-50 rounded-lg p-4">
                  <p className="text-sm text-slate-500 mb-2">Query:</p>
                  <p className="text-slate-800 font-mono text-sm">
                    "Show me all WhatsApp messages containing crypto wallet addresses from the last 30 days"
                  </p>
                </div>
                <div className="bg-slate-50 rounded-lg p-4">
                  <p className="text-sm text-slate-500 mb-2">Query:</p>
                  <p className="text-slate-800 font-mono text-sm">
                    "Find deleted files related to financial transactions between March 1-15"
                  </p>
                </div>
                <div className="bg-slate-50 rounded-lg p-4">
                  <p className="text-sm text-slate-500 mb-2">Query:</p>
                  <p className="text-slate-800 font-mono text-sm">
                    "Generate timeline of all communication with contact 'John Smith'"
                  </p>
                </div>
              </div>
            </div>

            {/* Key Benefits */}
           <div className="bg-white/80 backdrop-blur-sm rounded-2xl p-8 border border-gray-200">
  <img
    src="/query.png"
    alt="Practical Benefits"
    className="w-full h-auto rounded-xl object-cover"
  />
</div>

          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="relative z-10 w-full py-8 text-center text-sm text-slate-500 font-light">
        <p>Powered by AI. Designed for speed and precision.</p>
      </footer>
    </div>
  )
}
