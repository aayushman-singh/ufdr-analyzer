import Header from "@/components/header"
import { WobbleCard } from "@/components/ui/wobble-card"
import { ArrowRight, FileText, Search, BarChart2, GitFork, Zap, Eye, Database } from "lucide-react"
import Link from "next/link"

export default function Home() {
  return (
    <div className="theme-light min-h-screen w-full bg-background relative overflow-hidden">
      {/* Background grid + signal radial */}
      <div className="fixed inset-0 z-0 bg-grid">
        <div
          className="absolute inset-0"
          style={{
            background:
              "radial-gradient(circle 800px at 0% 200px, color-mix(in oklch, var(--signal) 12%, transparent), transparent)",
          }}
        />
      </div>

    <Header/>

      {/* Main Content - Hero Section */}
      <main className="relative z-10 flex-grow flex flex-col items-center justify-center text-center px-4 py-16">
        {/* Badge */}
        <div className="inline-flex items-center rounded-full border border-border bg-surface-1 text-muted-foreground px-4 py-1 text-sm font-light mb-6">
          Accelerate Investigations
        </div>

        {/* Headlines */}
        <h2 className="text-5xl md:text-6xl font-light text-foreground tracking-tight">AI-Powered Insights</h2>
        <h1 className="text-5xl md:text-6xl font-normal text-foreground tracking-tight mb-6">from UFDR Files</h1>

        {/* Sub-description */}
        <p className="max-w-xl text-lg text-muted-foreground font-light mb-10">
          Transform raw forensic data into actionable intelligence. Our assistant empowers investigators with natural
          language queries and visual analysis.
        </p>

        {/* Call to Action Buttons */}
        <div className="flex flex-col sm:flex-row gap-4 mb-16">
          <Link href="/upload">
            <button className="bg-signal text-signal-foreground font-medium py-3 px-6 rounded-lg hover:brightness-110 transition-all flex items-center justify-center gap-2 shadow-sm">
              Start Analyzing <ArrowRight size={18} />
            </button>
          </Link>
          <button className="bg-surface-1 text-foreground font-light py-3 px-6 rounded-lg border border-border hover:bg-surface-2 transition-colors flex items-center justify-center gap-2 shadow-sm">
            Learn More
          </button>
        </div>

        {/* Key Features Section */}
       <div className="max-w-7xl py-16 px-14 mx-auto w-full">
      <h2 className="text-3xl font-light text-foreground mb-2">Key Features</h2>
      <p className="text-muted-foreground font-light mb-8">
        Transform your data background with any file formats.
      </p>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Large Feature */}
        <WobbleCard
          containerClassName="col-span-1 lg:col-span-2 h-full bg-card min-h-[400px] [background-image:radial-gradient(circle_at_30%_40%,color-mix(in_oklch,var(--signal)_12%,transparent),transparent_60%)]"
        >
          <div className="max-w-md">
            <h3 className="text-left text-base md:text-xl lg:text-3xl font-semibold text-foreground">
              FileText – Organize and Analyze
            </h3>
            <p className="mt-4 text-left text-base text-muted-foreground">
             Upload UFDR files or forensic documents and let AI handle
                  extraction and organization instantly. Our advanced parsing
                  engine supports XML, HTML, SQLite, JSON, and more, creating a
                  structured database for efficient analysis.
            </p>
          </div>
          <img
            src="/query.png"
            width={500}
            height={500}
            alt="FileText Feature"
            className="absolute -right-1 lg:-right-[30%] -bottom-55 object-contain rounded-2xl"
          />
        </WobbleCard>

        {/* Small Feature */}
        <WobbleCard containerClassName="col-span-1 min-h-[200px] bg-card [background-image:radial-gradient(circle_at_70%_30%,color-mix(in_oklch,var(--info)_18%,transparent),transparent_60%)]">
          <h3 className="text-left text-base md:text-xl lg:text-2xl font-semibold text-foreground">
            Powerful Search
          </h3>
          <p className="mt-4 text-left text-base text-muted-foreground">
               Natural language search across all your data, from chats to call
                logs, leveraging AI for precise and contextual results.
          </p>
        </WobbleCard>

        {/* Another Large Feature */}
        <WobbleCard
          containerClassName="col-span-1 lg:col-span-3 bg-card min-h-[400px] [background-image:radial-gradient(circle_at_20%_60%,color-mix(in_oklch,var(--signal)_8%,transparent),transparent_50%),radial-gradient(circle_at_80%_30%,color-mix(in_oklch,var(--info)_10%,transparent),transparent_50%)]"
        >
          <div className="max-w-lg">
            <h3 className="text-left text-base md:text-xl lg:text-3xl font-semibold text-foreground">
              Advanced Analytics &amp; Reporting
            </h3>
            <p className="mt-4 text-left text-base text-muted-foreground">
              Get interactive timelines, visual link analysis, and automated
                  reports out of the box. Identify key entities, relationships,
                  and patterns effortlessly to build stronger cases.
            </p>
          </div>
          <img
            src="/query.png"
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
            <h3 className="text-3xl font-light text-foreground mb-4">See It In Action</h3>
            <p className="text-lg text-muted-foreground font-light">
              Experience how natural language queries transform complex forensic data into clear insights
            </p>
          </div>

          <div className="grid md:grid-cols-2 gap-8">
            {/* Query Examples */}
            <div className="bg-card/80 backdrop-blur-sm rounded-2xl p-8 border border-border">
              <h4 className="text-xl font-medium text-foreground mb-6">Natural Language Queries</h4>
              <div className="space-y-4">
                <div className="bg-surface-1 rounded-lg p-4">
                  <p className="text-sm text-muted-foreground mb-2">Query:</p>
                  <p className="text-foreground font-mono text-sm">
                    &ldquo;Show me all WhatsApp messages containing crypto wallet addresses from the last 30 days&rdquo;
                  </p>
                </div>
                <div className="bg-surface-1 rounded-lg p-4">
                  <p className="text-sm text-muted-foreground mb-2">Query:</p>
                  <p className="text-foreground font-mono text-sm">
                    &ldquo;Find deleted files related to financial transactions between March 1-15&rdquo;
                  </p>
                </div>
                <div className="bg-surface-1 rounded-lg p-4">
                  <p className="text-sm text-muted-foreground mb-2">Query:</p>
                  <p className="text-foreground font-mono text-sm">
                    &ldquo;Generate timeline of all communication with contact &apos;John Smith&apos;&rdquo;
                  </p>
                </div>
              </div>
            </div>

            {/* Key Benefits */}
           <div className="bg-card/80 backdrop-blur-sm rounded-2xl p-8 border border-border">
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
      <footer className="relative z-10 w-full py-8 text-center text-sm text-muted-foreground font-light">
        <p>Powered by AI. Designed for speed and precision.</p>
      </footer>
    </div>
  )
}
