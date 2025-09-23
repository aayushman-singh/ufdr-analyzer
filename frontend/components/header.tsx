import { Shield } from "lucide-react"
import Link from "next/link"

export default function Header() {
  return (
    <header className="relative z-10 w-full px-4 sm:px-8 lg:px-80 py-6">
      <div className="max-w-7xl mx-auto flex justify-between items-center">
        <div className="flex items-center space-x-2">
          <div className="w-8 h-8 bg-gradient-to-br from-purple-600 to-purple-800 rounded-lg flex items-center justify-center">
            <Shield className="w-4 h-4 text-white" />
          </div>
          <span className="text-xl font-medium text-slate-900">ForensicAI</span>
        </div>

        <nav className="hidden md:flex items-center space-x-8">
          <a
            href="#features"
            className="text-slate-600 hover:text-slate-900 transition-colors"
          >
            Features
          </a>
          <a
            href="#demo"
            className="text-slate-600 hover:text-slate-900 transition-colors"
          >
            Demo
          </a>
          <Link href="/signup">
  <button className="bg-slate-900 text-white px-4 py-2 rounded-lg text-sm hover:bg-slate-700 transition-colors">
    Get Started
  </button>
</Link>
        </nav>
      </div>
    </header>
  )
}
