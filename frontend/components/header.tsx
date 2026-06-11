import { Seal } from "@/components/brand/Seal"
import Link from "next/link"

export default function Header() {
  return (
    <header className="relative z-10 w-full px-4 sm:px-8 lg:px-80 py-6 border-b border-border">
      <div className="max-w-7xl mx-auto flex justify-between items-center">
        <Link href="/">
          <div className="flex items-center space-x-2">
            <Seal size={28} />
            <span className="text-xl font-medium text-foreground">ForensicAI</span>
          </div>
        </Link>

        <nav className="hidden md:flex items-center space-x-8">
          <Link
            href="/analysis-dashboard"
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            Dashboard
          </Link>
          <Link
            href="/global-search"
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            Global Search
          </Link>
          <Link
            href="/query-plan"
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            Query Plan
          </Link>
          <Link
            href="/patterns"
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            Patterns
          </Link>
          <Link
            href="/cross-case"
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            Cross-case
          </Link>
          <Link
            href="/link-graph"
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            Link Graph
          </Link>
          <a
            href="#features"
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            Features
          </a>
          <a
            href="#demo"
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            Demo
          </a>
          <Link href="/signup">
            <button className="bg-signal text-signal-foreground px-4 py-2 rounded-lg text-sm font-medium hover:brightness-110 transition-all">
              Get Started
            </button>
          </Link>
        </nav>
      </div>
    </header>
  )
}
