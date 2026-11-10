'use client';

import { FileText, GitPullRequest, LayoutDashboard, Settings } from 'lucide-react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { cn } from '@/lib/utils';

import { ProfileMenu } from './profile-menu';
import { TenantSelector } from './tenant-selector';

const NAVIGATION = [
  { href: '/dashboard', label: 'Painel', icon: LayoutDashboard },
  { href: '/release-notes', label: 'Release notes', icon: FileText },
  { href: '/configuracoes', label: 'Configurações', icon: Settings },
] as const;

export function AppHeader() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-40 border-b border-border bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container flex h-14 items-center gap-6">
        <Link href="/dashboard" className="flex items-center gap-2 font-semibold tracking-tight">
          <span className="flex size-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <GitPullRequest className="size-4" aria-hidden />
          </span>
          <span className="hidden sm:inline">PR Insights</span>
        </Link>

        <div className="h-5 w-px bg-border" aria-hidden />
        <TenantSelector />

        <nav aria-label="Navegação principal" className="ml-2 flex items-center gap-1">
          {NAVIGATION.map(({ href, label, icon: Icon }) => {
            const active = pathname === href;
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? 'page' : undefined}
                className={cn(
                  'flex items-center gap-2 rounded-md px-3 py-1.5 text-sm transition-colors',
                  active ? 'bg-accent text-accent-foreground' : 'text-muted-foreground hover:text-foreground',
                )}
              >
                <Icon className="size-4" aria-hidden />
                <span className="hidden md:inline">{label}</span>
              </Link>
            );
          })}
        </nav>

        <div className="ml-auto">
          <ProfileMenu />
        </div>
      </div>
    </header>
  );
}
