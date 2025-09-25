import {
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
} from "@/components/ui/sidebar"
import { Badge } from "@/components/ui/badge"
import { MenuItem } from "./data"

interface SidebarNavProps {
  menuItems: MenuItem[]
  activeContent: string
  setActiveContent: (content: string) => void
}

export function SidebarNav({ menuItems, activeContent, setActiveContent }: SidebarNavProps) {
  return (
    <SidebarMenu>
      {menuItems.map((item) => (
        <SidebarMenuItem key={item.content}>
          <SidebarMenuButton
            onClick={() => setActiveContent(item.content)}
            isActive={activeContent === item.content}
            tooltip={item.description}
          >
            <item.icon className="w-4 h-4" />
            <span className="font-light">{item.title}</span>
            {item.badge && (
              <Badge variant="secondary" className="ml-auto text-xs bg-purple-100 text-purple-700">
                {item.badge}
              </Badge>
            )}
          </SidebarMenuButton>
        </SidebarMenuItem>
      ))}
    </SidebarMenu>
  )
}